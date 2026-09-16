"""年鉴采集编排测试（M9b T4），真实夹具驱动。

要点：
1. 按 TOC **标题**定位表（不硬编码表号）
2. 单位换算后再入库（万元 → 亿元）
3. **只映射语义确切的指标** —— 户籍人口绝不冒充常住人口（P1「错 > 缺」）
4. 入库打 `source_kind='yearbook'` / `source_rank=2`（次源，公报为主源）
"""
import os

from app.fetch.yearbook import TableSpec, ingest_yearbook, load_yearbook_config
from app.store.db import init_db
from app.store.repository import Repository

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")
V = "https://tjj.quanzhou.gov.cn/tsys/UpLoadFiles/43sjfb/129ndsj/qztjnj2024/"
TOC = V + "contents-cn.htm"
T0102 = V + "cn/html/0102.htm"
T0603 = V + "cn/html/0603.htm"


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url):
        return self.mapping[url]

    def download(self, url):
        return self.mapping[url].encode("utf-8")


CFG = {
    "region": "泉州市",
    "template": V.replace("2024", "{year}") + "contents-cn.htm",
    "years": [2024],
    "tables": [
        {"key": "main", "title": "国民经济主要年份主要指标",
         "indicators": [
             # 必须写**精确**行名（正则 fullmatch）—— 松散子串会折叠不同指标
             {"match": "地区生产总值（当年价）", "name": "地区生产总值", "unit": "亿元"},
             {"match": "第一产业", "name": "第一产业增加值", "unit": "亿元"},
         ]},
    ],
}


def _run(tmp_path, cfg=None):
    client = FakeClient({TOC: _fx("qz_yearbook_toc_2024.htm"),
                         T0102: _fx("qz_yearbook_0102.htm")})
    repo = Repository(init_db(str(tmp_path / "t.db")))
    stats = ingest_yearbook(client, repo, cfg or CFG)
    return repo, stats


def test_ingest_yearbook_stores_with_yearbook_source(tmp_path):
    repo, stats = _run(tmp_path)
    assert stats["tables_parsed"] == 1
    assert stats["values"] >= 60, f"2 指标 × 34 年 ≈ 68 行，实得 {stats['values']}"

    rows = repo.query_data(region="泉州市", indicator="地区生产总值", primary_only=False)
    assert rows, "年鉴值应入库"
    assert all(r["source_kind"] == "yearbook" for r in rows)
    assert all(r["source_rank"] == 2 for r in rows)


def test_ingest_yearbook_converts_units(tmp_path):
    """0102 给的是万元，指标词典规范单位是亿元 —— 必须换算。"""
    repo, _ = _run(tmp_path)
    rows = repo.query_data(region="泉州市", indicator="地区生产总值", year="1949",
                           primary_only=False)
    assert len(rows) == 1
    assert rows[0]["value"] == "1.33", f"13288 万元应为 1.33 亿元，实得 {rows[0]['value']}"
    assert rows[0]["unit"] == "亿元"


def test_ingest_yearbook_does_not_mislabel_household_as_resident(tmp_path):
    """户籍人口 ≠ 常住人口：未显式映射的指标绝不入库。"""
    repo, _ = _run(tmp_path)
    assert repo.query_data(region="泉州市", indicator="常住人口", primary_only=False) == []


def test_ingest_yearbook_creates_page_and_is_idempotent(tmp_path):
    repo, _ = _run(tmp_path)
    pages = [p for p in repo.list_pages() if p["dataset_type"] == "yearbook"]
    assert len(pages) == 1
    assert pages[0]["url"] == T0102
    assert pages[0]["period"] == "2024"          # 卷年
    n1 = len(repo.query_data(region="泉州市", primary_only=False))

    # 重跑：同内容不得重复累积
    client = FakeClient({TOC: _fx("qz_yearbook_toc_2024.htm"),
                         T0102: _fx("qz_yearbook_0102.htm")})
    ingest_yearbook(client, repo, CFG)
    n2 = len(repo.query_data(region="泉州市", primary_only=False))
    assert n1 == n2, f"重跑应幂等：{n1} → {n2}"


def test_shipped_config_excludes_ambiguous_fiscal_table():
    """口径不明的 0603「历年一般公共预算收支情况」已撤下映射（2026-09-15）。

    实测：该表标题与表内均无「全市/本级」标识，而同年在库值稳定只有公报
    （全市口径）的约一半 —— 2022 393.91/807.45、2023 437.68/850.27、
    2024 402.37/844.24，高度疑为**市本级**。
    按 P1「错 > 缺」宁可不上，也不冒充全市口径。本测试锁定该决定。
    """
    cfg = load_yearbook_config(os.path.join(BASE, "..", "config", "yearbook_volumes.yaml"))
    titles = " ".join(t.get("title", "") for t in cfg["tables"])
    assert "历年一般公共预算收支情况" not in titles
    names = [i.get("name") for t in cfg["tables"] for i in (t.get("indicators") or [])]
    assert "一般公共预算支出" not in names, "不得把疑似市本级的值挂到全市指标名下"
    assert "一般公共预算收入" not in names


def test_shipped_config_does_not_map_household_population():
    """户籍人口 ≠ 常住人口 —— 出厂配置不得映射「年末户籍人口数」。"""
    cfg = load_yearbook_config(os.path.join(BASE, "..", "config", "yearbook_volumes.yaml"))
    matches = [i.get("match", "") for t in cfg["tables"] for i in (t.get("indicators") or [])]
    assert not any("户籍" in m for m in matches)
def test_indicator_match_is_exact_not_substring(tmp_path):
    """匹配必须是**精确**的（正则 fullmatch）。

    松散子串会把「地区生产总值（当年价）」「人均地区生产总值」「地区生产总值指数」
    等**语义不同**的行折叠成一个指标名 —— 真实库实测已有 154 组同键多值的真歧义。
    本测试锁定：松散的 match 不得命中任何行（必须写精确行名）。
    """
    cfg = dict(CFG, tables=[{
        "key": "main", "title": "国民经济主要年份主要指标",
        "indicators": [{"match": "地区生产总值", "name": "地区生产总值", "unit": "亿元"}]}])
    repo, stats = _run(tmp_path, cfg)
    assert stats["values"] == 0, "松散 match 不得命中"
    assert any("地区生产总值" in m for m in stats["missing"]), "应记为缺失"
    assert repo.query_data(region="泉州市", indicator="地区生产总值",
                           primary_only=False) == []


def test_indicator_match_supports_explicit_regex(tmp_path):
    """确需模糊时必须显式写正则 —— 让作者承担歧义风险，而非默认模糊。

    `fullmatch` 天然挡住「人均地区生产总值（当年价）」这类前缀不同的行
    （`地区生产总值.*` 不会命中它）；要故意多命中须写 `.*地区生产总值.*`，
    此时产生的同键多值会被歧义探测器看见。
    """
    exact = dict(CFG, tables=[{
        "key": "main", "title": "国民经济主要年份主要指标",
        "indicators": [{"match": "地区生产总值.*", "name": "地区生产总值", "unit": "亿元"}]}])
    repo, stats = _run(tmp_path, exact)
    assert stats["values"] > 0
    assert not repo.find_ambiguous_groups(), \
        "fullmatch 下不应命中「人均地区生产总值」等同名不同义行"

    loose = dict(CFG, tables=[{
        "key": "main", "title": "国民经济主要年份主要指标",
        "indicators": [{"match": ".*地区生产总值.*", "name": "地区生产总值", "unit": "亿元"}]}])
    repo2, stats2 = _run(tmp_path, loose)
    assert stats2["values"] > stats["values"], "显式模糊应命中更多行"
    assert repo2.find_ambiguous_groups(), "多命中产生的同键多值必须被歧义探测器暴露"
def test_ingest_yearbook_records_missing_table(tmp_path):
    """TOC 中没有目标表时必须如实记录缺失，不得报成功。"""
    cfg = dict(CFG, tables=[{"key": "nope", "title": "根本不存在的表",
                             "indicators": [{"match": "X", "name": "X", "unit": ""}]}])
    repo, stats = _run(tmp_path, cfg)
    assert stats["tables_parsed"] == 0
    assert stats["missing"] and "nope" in stats["missing"][0]
    assert stats["values"] == 0


def test_ingest_yearbook_handles_year_rows_table(tmp_path):
    """0603 是「年份为行 + 双层表头」形状，须经形状分派正常入库。"""
    cfg = {
        "region": "泉州市",
        "template": CFG["template"],
        "years": [2024],
        "tables": [{"key": "fiscal", "title": "历年一般公共预算收支情况",
                    "indicators": [{"match": "一般公共预算总收入",
                                    "name": "一般公共预算收入", "unit": "亿元"}]}],
    }
    client = FakeClient({TOC: _fx("qz_yearbook_toc_2024.htm"),
                         T0603: _fx("qz_yearbook_0603.htm")})
    repo = Repository(init_db(str(tmp_path / "t.db")))
    stats = ingest_yearbook(client, repo, cfg)
    assert stats["values"] > 50
    rows = repo.query_data(region="泉州市", indicator="一般公共预算收入",
                           year="1949", primary_only=False)
    assert rows and rows[0]["value"] == "0.07", f"707 万元应为 0.07 亿元，实得 {rows}"
