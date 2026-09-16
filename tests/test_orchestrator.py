import json
import os
from app.store.db import init_db
from app.store.repository import Repository
from app.discovery.registry import Registry
from app.extract.rule_extractor import load_rules
from app.fetch.search import build_was_url
from app.orchestrator import _find_bulletin_links, run_pipeline

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")
CFG = os.path.join(BASE, "..", "config")

FALLBACK_HTML = "<html><head><title>placeholder</title></head><body></body></html>"


class FakeClient:
    def __init__(self, mapping, fallback=FALLBACK_HTML):
        self.mapping = mapping
        self.fallback = fallback

    def get(self, url):
        if url in self.mapping:
            return self.mapping[url]
        if self.fallback is not None:
            return self.fallback
        raise Exception(f"no fixture {url}")

    def download(self, url):
        return self.get(url).encode("utf-8")


def _fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_pipeline(tmp_path):
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    detail = col + "202403/t20240313_6413971.htm"
    client = FakeClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": _fixture("fujian_home.html"),
        # M9a：适配器声明的栏目页只作下钻入口（不再作为正文入库），
        # 因此公报正文必须挂在详情页 URL 上（A5-2 规格变更）。
        col: ('<html><body><a href="' + detail + '">'
              '2023年福建省国民经济和社会发展统计公报</a></body></html>'),
        detail: _fixture("bulletin_2024.txt"),
        "https://tjj.fuzhou.gov.cn/": "<html><title>福州市统计局</title></html>",
        "https://tjj.zhangzhou.gov.cn/": "<html><title>漳州市统计局</title></html>",
        "https://tjj.sm.gov.cn/": "<html><title>三明市统计局</title></html>",
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] in ("success", "partial")
    s = json.loads(run["summary_json"])
    assert s["bureaus"] >= 4
    assert s["values"] >= 1
    assert len(repo.list_bureaus()) >= 4


def test_manual_bureau_putian_via_was(tmp_path):
    """手工锚点机构（莆田）通过 was5 检索定位公报并入库。"""
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    scfg = registry.manual_bureaus[0]["bulletin_search"]
    was_url = build_was_url(scfg)
    assert "莆田市" in registry.manual_bureaus[0]["region"]

    was_html = (
        '<html><body>'
        '{"title2":"2025年莆田市国民经济和社会发展统计公报",'
        '"url":"http://www.putian.gov.cn/zwgk/tjxx/tjgb/202605/t20260501_99999.htm"},'
        '{"title2":"2025年仙游县国民经济和社会发展统计公报",'
        '"url":"http://www.xianyou.gov.cn/xtjj/xxgk/tjgk/tjxx/202607/t20260703_111.htm"},'
        '</body></html>'
    )
    bulletin_html = (
        '<html><head><title>2025年莆田市国民经济和社会发展统计公报</title></head><body>'
        '<p>2025年莆田市国民经济和社会发展统计公报</p>'
        '<p>莆田市统计局　2026 年4月15 日发布</p>'
        '<p>一、综合</p><p>初步核算，全年实现地区生产总值3200.50亿元，比上年增长5.0%。</p>'
        '<p>十、人民生活</p><p>年末常住人口319万人。</p>'
        '</body></html>'
    )
    client = FakeClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": _fixture("fujian_home.html"),
        "https://tjj.fujian.gov.cn/xxgk/tjgb/": _fixture("bulletin_2024.txt"),
        was_url: was_html,
        "http://www.putian.gov.cn/zwgk/tjxx/tjgb/202605/t20260501_99999.htm": bulletin_html,
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] in ("success", "partial")

    names = [b["name"] for b in repo.list_bureaus()]
    assert "莆田市统计局" in names
    rows = repo.query_data(region="莆田市", indicator="地区生产总值")
    assert len(rows) >= 1
    assert rows[0]["value"] == "3200.50"
    assert rows[0]["year"] == "2025"
    pop = repo.query_data(region="莆田市", indicator="常住人口")
    assert pop[0]["value"] == "319"


def test_bulletin_links_same_domain_only():
    """公报详情链接仅限本机构域名（排除跨站引用污染）。"""
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    html = ('<html><body>'
            '<a href="https://tjj.quanzhou.gov.cn/tjzl/tjgb/202603/t20260331_1.htm">2025年泉州市统计公报</a>'
            '<a href="https://www.stats.gov.cn/sj/zxfbhjd/202602/t20260228_1.html">各地区生产总值发布</a>'
            '<a href="https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_1.htm">福建省统计公报</a>'
            '</body></html>')
    links = _find_bulletin_links(html, "https://tjj.quanzhou.gov.cn/", registry)
    assert links == ["https://tjj.quanzhou.gov.cn/tjzl/tjgb/202603/t20260331_1.htm"]


def test_pipeline_content_dedup_on_rerun(tmp_path):
    """同一内容重复运行不产生重复值（内容哈希去重）。"""
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    detail = col + "202403/t20240313_6413971.htm"
    client = FakeClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": _fixture("fujian_home.html"),
        # M9a：正文挂详情页（栏目页只作下钻入口）
        col: ('<html><body><a href="' + detail + '">'
              '2023年福建省国民经济和社会发展统计公报</a></body></html>'),
        detail: _fixture("bulletin_2024.txt"),
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_pipeline(client, repo, registry, rules)
    n1 = len(repo.query_data())
    run_pipeline(client, repo, registry, rules)
    n2 = len(repo.query_data())
    assert n1 > 0
    assert n1 == n2


def test_pipeline_survives_single_page_failure(tmp_path):
    """单页抓取失败被隔离：错误计入日志、其它公报仍入库、整体不中断。"""
    good = "https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_good.htm"
    bad = "https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260319_bad.htm"
    fujian_home = (
        '<html><head><title>福建省统计局</title></head><body>'
        f'<a href="{good}">2025年福建省统计公报</a>'
        f'<a href="{bad}">2025年福建省统计公报（发布稿）</a>'
        '</body></html>'
    )

    class FlakyClient(FakeClient):
        def download(self, url):
            if url == bad:
                raise Exception("boom: connection reset")
            return super().download(url)

    client = FlakyClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": fujian_home,
        good: _fixture("bulletin_2024.txt"),
        bad: _fixture("bulletin_2024.txt"),
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] in ("success", "partial")
    s = json.loads(run["summary_json"])
    assert s["errors"] >= 1, "坏页应计入 errors"
    assert s["values"] >= 1, "好公报仍应抽取入库"
    assert "页面失败" in (run["log"] or ""), "日志应记录页面失败"
    # 好公报的 GDP 应已入库
    assert len(repo.query_data(region="福建省", indicator="地区生产总值")) >= 1


def test_status_failed_when_all_pages_fail(tmp_path):
    """全部公报抓取失败时运行状态必须是 failed（不得误报 success）。"""
    class TotalFailClient(FakeClient):
        def download(self, url):
            raise Exception("all requests fail")

    client = TotalFailClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": _fixture("fujian_home.html"),
        "https://tjj.fujian.gov.cn/xxgk/tjgb/": _fixture("bulletin_2024.txt"),
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] == "failed"
    s = json.loads(run["summary_json"])
    assert s["errors"] >= 1
    assert s["values"] == 0


def test_content_update_replaces_without_duplicates(tmp_path):
    """同一 URL 内容更新（如公报修订）应刷新页面并替换旧值，不累积重复。"""
    good = "https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_good.htm"
    fujian_home = (
        '<html><head><title>福建省统计局</title></head><body>'
        f'<a href="{good}">2025年福建省统计公报</a></body></html>')
    v1 = _fixture("bulletin_2024.txt")
    v2 = v1.replace("53162.36", "99999.99")

    client = FakeClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": fujian_home,
        good: v1,
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))

    run_pipeline(client, repo, registry, rules)
    gdp1 = repo.query_data(region="福建省", indicator="地区生产总值")
    assert len(gdp1) == 1 and gdp1[0]["value"] == "53162.36"

    client.mapping[good] = v2  # 内容更新
    run_pipeline(client, repo, registry, rules)
    gdp2 = repo.query_data(region="福建省", indicator="地区生产总值")
    assert len(gdp2) == 1, "更新后不应累积旧值"
    assert gdp2[0]["value"] == "99999.99"
    # 页面内容应已刷新为最新版本
    pid = gdp2[0]["page_id"]
    row = [p for p in repo.list_pages() if p["id"] == pid][0]
    assert "99999.99" in (row["content_text"] or "")


def test_listing_page_drilldown(tmp_path):
    """首页公报链接指向栏目列表页时应下钻一层取详情正文（三明场景）。"""
    listing = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    d1 = "https://tjj.fujian.gov.cn/xxgk/tjgb/202403/t20240301_111.htm"
    d2 = "https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_222.htm"
    home = ('<html><head><title>福建省统计局</title></head><body>'
            f'<a href="{listing}">统计公报</a></body></html>')
    listing_html = (
        '<html><head><title>统计公报列表</title></head><body>'
        f'<a href="{d1}">2023年福建省国民经济和社会发展统计公报</a>'
        f'<a href="{d2}">2025年福建省国民经济和社会发展统计公报</a>'
        '<div class="page">共 2 条</div></body></html>'
    )
    v1 = _fixture("bulletin_2024.txt")
    v2 = v1.replace("53162.36", "99999.99").replace("2024年福建省", "2025年福建省")

    client = FakeClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": home,
        listing: listing_html,
        d1: v1,
        d2: v2,
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] in ("success", "partial")
    # 两个详情页的公报都应入库，栏目列表页本身不作为正文页
    gdp = repo.query_data(region="福建省", indicator="地区生产总值")
    vals = sorted(g["value"] for g in gdp)
    assert vals == ["53162.36", "99999.99"]
    urls = [p["url"] for p in repo.list_pages()]
    assert listing not in urls, "栏目列表页不应作为正文页入库"
    assert d1 in urls and d2 in urls


def test_manual_listing_urls_drilldown(tmp_path):
    """手工锚点机构经 listing_urls（栏目页直连）下钻取详情（漳州/南平 cms 场景）。"""
    listing = "http://tjj.zhangzhou.gov.cn/cms/html/zzstjj/tjgb/index.html"
    d1 = "http://tjj.zhangzhou.gov.cn/cms/html/zzstjj/2025-03-31/2027111163.html"
    listing_html = (
        '<html><head><title>统计公报</title></head><body>'
        f'<a href="{d1}">2024年漳州市国民经济和社会发展统计公报</a>'
        '</body></html>')
    v1 = _fixture("bulletin_2024.txt").replace("53162.36", "11000.00")

    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    registry.manual_bureaus = [{
        "level": "city", "name": "漳州市统计局", "region": "漳州市",
        "url": "http://tjj.zhangzhou.gov.cn/",
        "listing_urls": [listing],
    }]
    client = FakeClient({
        "https://www.stats.gov.cn/": _fixture("national_home.html"),
        "https://tjj.fujian.gov.cn/": _fixture("fujian_home.html"),
        "https://tjj.fujian.gov.cn/xxgk/tjgb/": _fixture("bulletin_2024.txt"),
        listing: listing_html,
        d1: v1,
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] in ("success", "partial")
    names = [b["name"] for b in repo.list_bureaus()]
    assert "漳州市统计局" in names
    rows = repo.query_data(region="漳州市", indicator="地区生产总值")
    assert len(rows) >= 1
    assert rows[0]["value"] == "11000.00"
    urls = [p["url"] for p in repo.list_pages()]
    assert d1 in urls
