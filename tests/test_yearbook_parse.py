"""年鉴 TOC 与宽表解析测试（M9b T1/T2，真实夹具驱动）。"""
import os

from app.parse.yearbook import (load_toc, match_tables, normalize_title,
                                parse_year_columns, parse_yearbook_table,
                                to_canonical)

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")
TOC_URL = "https://tjj.quanzhou.gov.cn/tsys/UpLoadFiles/43sjfb/129ndsj/qztjnj2024/"


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_normalize_title_strips_numbering_and_year_paren():
    assert normalize_title("1—2 国民经济主要年份主要指标") == "国民经济主要年份主要指标"
    assert normalize_title("1-2 国民经济主要年份主要指标") == "国民经济主要年份主要指标"
    assert normalize_title("  2—3   历年地区生产总值 ") == "历年地区生产总值"
    assert normalize_title("3—3 各县（市、区）户籍人口（2023年）") == "各县（市、区）户籍人口"
    assert normalize_title("附录1-15 各设区市人口主要数据（2023年）") == "各设区市人口主要数据"


def test_load_toc_from_real_fixture():
    toc = load_toc(_fx("qz_yearbook_toc_2024.htm"), TOC_URL)
    assert len(toc) > 150, f"真实 TOC 应含大量表链接，实得 {len(toc)}"
    assert all("cn/html/" in u for u, _ in toc), "只应收表文件链接"


def test_match_tables_by_title_not_number():
    """按标题匹配 —— 表号会位移（设计 P2），禁止硬编码表号。"""
    toc = load_toc(_fx("qz_yearbook_toc_2024.htm"), TOC_URL)
    matched = match_tables(toc, {
        "main": "国民经济主要年份主要指标",
        "pop": "主要年份年末常住人口",
        "cpi": "居民消费价格总指数",
        "fiscal": "历年一般公共预算收支情况",
        "gdp": "历年地区生产总值",
    })
    assert matched["main"].endswith("0102.htm")
    assert matched["pop"].endswith("0304.htm")
    assert matched["cpi"].endswith("0502.htm")
    assert matched["fiscal"].endswith("0603.htm")
    assert matched["gdp"].endswith("0203.htm")


def test_match_tables_supports_regex_for_title_drift():
    """标题**逐年漂移**，title 必须支持正则，否则换一卷就漏表。

    实测：2018/2022 卷为「国民经济主要指标」，2024 卷为「国民经济主要年份主要指标」；
    2025 卷为「…居民消费价格**指数**（上年=100）」而非「…总指数」。
    """
    toc = [("http://x/cn/html/0103.htm", "1—3 国民经济主要指标"),
           ("http://x/cn/html/0102.htm", "1—2 国民经济主要年份主要指标"),
           ("http://x/cn/html/0602.htm", "6—2 历年全国、全省、全市居民消费价格总指数"),
           ("http://x/cn/html/0502_5-2.html", "5-2 历年全国、全省、全市居民消费价格指数（上年=100）")]
    m = match_tables(toc, {
        "main": "^国民经济主要(年份)?(主要)?指标$",
        "cpi": "历年全国、全省、全市居民消费价格(总)?指数",
    })
    assert m["main"] is not None and m["main"].endswith("0103.htm"), "同一卷只会有一种写法"
    assert m["cpi"] is not None

    # 单卷场景下正则必须覆盖两种写法
    only_2024 = [(u, t) for u, t in toc if "0102.htm" in u]
    assert match_tables(only_2024, {"main": "^国民经济主要(年份)?(主要)?指标$"})["main"]
    only_2025 = [(u, t) for u, t in toc if "0502_5-2" in u]
    assert match_tables(only_2025, {"cpi": "历年全国、全省、全市居民消费价格(总)?指数"})["cpi"]


def test_match_tables_reports_missing_instead_of_guessing():
    toc = [("http://x/cn/html/0101.htm", "1—1 行政区划基本情况")]
    matched = match_tables(toc, {"nope": "根本不存在的表标题"})
    assert matched["nope"] is None, "匹配不到必须返回 None，不得猜一个表"


def test_parse_year_columns_real_wide_table():
    """宽表转置：年份为列、指标为行（含 1985<br>年 形式表头）。"""
    rows = parse_year_columns(_fx("qz_yearbook_0102.htm"))
    assert rows, "应解析出指标行"
    gdp = [r for r in rows if "地区生产总值" in r["indicator"]]
    assert gdp, "应含地区生产总值行"
    g = gdp[0]
    assert g["unit"] == "万元"
    assert len(g["values"]) >= 30, f"长序列年份数不足：{len(g['values'])}"
    assert g["values"].get("1949") == "13288"
    assert g["values"].get("2023")


def test_parse_year_columns_skips_section_rows():
    """分组行（如「2. 国民经济核算」）除首格外全空，不应产出指标。"""
    rows = parse_year_columns(_fx("qz_yearbook_0102.htm"))
    assert all(r["values"] for r in rows), "返回的每行都必须至少有一个值"
    assert not any(r["indicator"].strip() in ("2.", "2", "1.", "1") for r in rows)


def test_to_canonical_converts_and_rejects():
    """单位换算守卫：年鉴单位常与指标词典规范单位不同（万元 vs 亿元）。

    绝不换算就入库会让 GDP 静默差 10^4 倍 —— 这是「错 > 缺」要防的典型情形。
    无法换算时必须拒绝（返回 None），而不是照原值入库。
    """
    v, note = to_canonical("13288", "万元", "亿元")
    assert v == "1.33" and "万元→亿元" in note

    v, note = to_canonical("5920700", "万元", "亿元")
    assert v == "592.07"

    v, note = to_canonical("219.17", "万人", "万人")
    assert v == "219.17" and note == ""

    v, note = to_canonical("45", "%", "%")
    assert v == "45"

    # 无法换算 → 拒绝并说明原因
    v, note = to_canonical("123", "万元", "%")
    assert v is None and "无法换算" in note

    # 非数值 → 拒绝
    v, note = to_canonical("—", "万元", "亿元")
    assert v is None


def test_parse_yearbook_table_dispatches_by_shape():
    """年鉴**同卷内表结构并不统一**，必须按形状分派而非假定单一形状。

    实测：`0102` 是「年份为列」（宽表），`0603` 是「年份为行 + 双层表头」。
    若只用宽表解析器，`0603` 返回 []（本测试的前身就是这么失败的）。
    """
    wide = parse_yearbook_table(_fx("qz_yearbook_0102.htm"))
    assert any("地区生产总值" in c.indicator for c in wide)
    assert any(c.year == "1949" and c.value == "13288" for c in wide)

    long_rows = parse_yearbook_table(_fx("qz_yearbook_0603.htm"))
    assert long_rows, "财政表（年份为行 + 双层表头）必须也能解析"
    assert any("一般公共预算" in c.indicator for c in long_rows)
    assert any(len(c.year) == 4 and c.year.isdigit() for c in long_rows)
    assert any(c.year == "1949" and c.value == "707" for c in long_rows)
