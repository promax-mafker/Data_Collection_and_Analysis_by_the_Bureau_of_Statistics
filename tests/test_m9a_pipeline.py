"""M9a 管线接线测试（T4）。

覆盖三件事：
  1. 适配器声明的栏目页**只作下钻入口**，绝不作为正文入库（A5-2 回归）
  2. 年度区间过滤生效（越界不采）
  3. 手工锚点（莆田 was5）**优先于**适配器栏目，避免两者冲突
"""
import datetime
import os

from app.discovery.registry import Registry
from app.extract.rule_extractor import load_rules
from app.fetch.adapters import AdapterRegistry, SiteAdapter
from app.orchestrator import run_pipeline
from app.store.db import init_db
from app.store.repository import Repository

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, "..", "config")

NATIONAL_HOME = "<html><title>国家统计局</title><body></body></html>"
PROV_HOME = "<html><title>福建省统计局</title><body></body></html>"
EMPTY = "<html><body></body></html>"


class RecordingClient:
    """返回映射内容，并记录被请求的 URL（用于断言"走了哪条路"）。"""

    def __init__(self, mapping, fallback=EMPTY):
        self.mapping = mapping
        self.fallback = fallback
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return self.mapping.get(url, self.fallback)

    def download(self, url):
        return self.get(url).encode("utf-8")


def _registry(adapters=None, manual_bureaus=None):
    return Registry(
        seeds=[{"url": "https://www.stats.gov.cn/", "name": "国家统计局",
                "region": "中国", "level": "national"}],
        province_anchor="https://tjj.fujian.gov.cn/",
        expected_cities=[],
        known_domains=[],
        bulletin_keywords=["统计公报"],
        manual_bureaus=manual_bureaus or [],
        adapters=adapters,
    )


def _run(client, tmp_path, registry):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_pipeline(client, repo, registry, rules)
    return repo


def _base_mapping():
    return {
        "https://www.stats.gov.cn/": NATIONAL_HOME,
        "https://tjj.fujian.gov.cn/": PROV_HOME,
    }


def test_adapter_column_is_never_stored_as_content(tmp_path):
    """A5-2 回归：栏目页只作下钻入口，不以「公报正文」身份入库。"""
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    detail = col + "202603/t20260313_7109476.htm"
    client = RecordingClient({
        **_base_mapping(),
        col: "<html><body><a href='./202603/t20260313_7109476.htm'>"
             "2025年福建省国民经济和社会发展统计公报</a></body></html>",
        detail: "<html><body>2025年福建省地区生产总值 57761.28 亿元</body></html>",
    })
    reg = _registry(adapters=AdapterRegistry([SiteAdapter(region="福建省", bulletin_column=col)]))
    repo = _run(client, tmp_path, reg)

    urls = [p["url"] for p in repo.list_pages()]
    assert col not in urls, "栏目页不得作为正文入库"
    assert detail in urls, "详情页应正常入库"


def test_year_range_filters_out_of_range_bulletin(tmp_path):
    """年度区间越界不采（设计 P1：错 > 缺）。"""
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    old = col + "201503/t20150313_1111111.htm"
    new = col + "202503/t20250313_6779048.htm"
    client = RecordingClient({
        **_base_mapping(),
        col: "<html><body>"
             f"<a href='{new}'>2024年福建省国民经济和社会发展统计公报</a>"
             f"<a href='{old}'>2015年福建省国民经济和社会发展统计公报</a>"
             "</body></html>",
        old: "<html><body>2015年福建省地区生产总值 25979.82 亿元</body></html>",
        new: "<html><body>2024年福建省地区生产总值 57761.28 亿元</body></html>",
    })
    ad = SiteAdapter(region="福建省", bulletin_column=col, year_range=(2020, 2025))
    repo = _run(client, tmp_path, _registry(adapters=AdapterRegistry([ad])))

    urls = [p["url"] for p in repo.list_pages()]
    assert new in urls, "区间内的详情页应入库"
    assert old not in urls, "区间外的详情页不应入库"


def test_unsupported_document_type_is_not_stored(tmp_path):
    """M9a：编排层补文档类型白名单 —— .doc 附件不得以「公报正文」入库。

    实测：泉州栏目 201006 附件 `W020160831598354815443.doc` 曾被 decode 成
    乱码文本后入库（0 行数据、period 被兜底成当年）。
    """
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    doc = col + "201006/W020160831598354815443.doc"
    client = RecordingClient({
        **_base_mapping(),
        col: f"<html><body><a href='{doc}'>2010年福建省国民经济和社会发展统计公报</a></body></html>",
        doc: "\xd0\xd0\xd0\xd0binary",
    })
    ad = SiteAdapter(region="福建省", bulletin_column=col)
    repo = _run(client, tmp_path, _registry(adapters=AdapterRegistry([ad])))
    assert doc not in [p["url"] for p in repo.list_pages()], ".doc 不得入库"


def test_detail_page_is_stored_not_skipped_as_listing(tmp_path):
    """端到端回归：公报详情页内含「统计公报」导航链接时，仍须作为正文入库。

    否则详情页被判为列表页而整页跳过（真实采集中泉州 2024/2023/2022 公报丢失）。
    """
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    detail = col + "202503/t20250313_6779048.htm"
    nav = f"<a href='{col}'>统计公报</a><a href='{col}'>政务公开</a>"
    client = RecordingClient({
        **_base_mapping(),
        col: f"<html><body><a href='{detail}'>2024年福建省国民经济和社会发展统计公报</a></body></html>",
        detail: f"<html><body>{nav}2024年福建省地区生产总值 57761.28 亿元</body></html>",
    })
    ad = SiteAdapter(region="福建省", bulletin_column=col)
    repo = _run(client, tmp_path, _registry(adapters=AdapterRegistry([ad])))
    urls = [p["url"] for p in repo.list_pages()]
    assert detail in urls, "详情页必须入库（不得被误判为列表页）"
    assert repo.query_data(region="福建省", indicator="地区生产总值"), "详情页数据必须抽取入库"


def test_page_without_year_is_not_given_fabricated_year(tmp_path):
    """设计 P1「错 > 缺」：年份无法识别时不得兜底为采集年。

    T6 真实采集暴露：福州 39 个正文不含「YYYY年」的页面 period 被兜底成 2025。
    危害不止是页面计数：抽取上下文把该 year 传给指标，会把上一年的数据
    标成当年 —— 这是**静默的值污染**，比缺失严重得多。
    """
    col = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    detail = col + "202403/t20240313_6413971.htm"
    client = RecordingClient({
        **_base_mapping(),
        col: f"<html><body><a href='{detail}'>2023年福建省国民经济和社会发展统计公报</a></body></html>",
        detail: "<html><body>地区生产总值 53162.36 亿元</body></html>",   # 正文无年份
    })
    ad = SiteAdapter(region="福建省", bulletin_column=col)
    repo = _run(client, tmp_path, _registry(adapters=AdapterRegistry([ad])))

    rows = [p for p in repo.list_pages() if p["url"] == detail]
    assert rows, "页面本身应入库（不丢页面）"
    fabricated = str(datetime.date.today().year - 1)
    assert rows[0]["period"] != fabricated, "不得把未知年份兜底成采集年"
    assert rows[0]["period"] == "", "年份未知应记为空，如实体现『缺』"


def test_manual_bureau_takes_priority_over_adapter(tmp_path):
    """手工锚点（was5 检索）优先于适配器栏目，两者不得冲突。"""
    adapter_col = "https://should-not-be-used.example/col/"
    manual = [{
        "level": "city",
        "name": "莆田市统计局",
        "region": "莆田市",
        "url": "https://www.putian.gov.cn/tjj/",
        "bulletin_search": {
            "endpoint": "https://www.putian.gov.cn/was5/web/search",
            "channelid": "210831",
            "searchword": "国民经济和社会发展统计公报",
            "perpage": "50",
        },
    }]
    client = RecordingClient(_base_mapping())
    reg = _registry(
        adapters=AdapterRegistry([SiteAdapter(region="莆田市", bulletin_column=adapter_col)]),
        manual_bureaus=manual,
    )
    _run(client, tmp_path, reg)

    assert any("was5" in u for u in client.requested), "应走 was5 检索"
    assert adapter_col not in client.requested, "手工锚点优先，适配器栏目不应被请求"
