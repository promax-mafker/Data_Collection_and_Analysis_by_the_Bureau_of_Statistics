import os
from app.extract.rule_extractor import RuleExtractor, load_rules, split_sections

BASE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(BASE, "fixtures", "bulletin_2024.txt")
RULES = os.path.join(BASE, "..", "config", "extract_rules.yaml")

def _text():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()

def _rules():
    return load_rules(os.path.abspath(RULES))

def test_split_sections():
    sections = split_sections(_text())
    assert any("综合" in h for h, _ in sections)

def test_extract_gdp():
    values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
    gdp = [v for v in values if v.indicator_name == "地区生产总值"]
    assert len(gdp) == 1
    assert gdp[0].value == "53162.36"
    assert gdp[0].unit == "亿元"
    assert gdp[0].category == "综合"

def test_extract_agriculture_total():
    values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
    agri = [v for v in values if v.indicator_name == "农林牧渔业总产值"][0]
    assert agri.value == "6185.43"

def test_extract_industrial_added_value_only():
    values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
    ind = [v for v in values if v.indicator_name == "规模以上工业增加值"]
    assert len(ind) == 1
    assert ind[0].value == "6.5"

def test_extract_gdp_with_footnote_and_bracket():
    """脚注角标与（GDP）括号不应阻断抽取。"""
    text = ("一、综合\n"
            "初步核算，全年实现地区生产总值（GDP）[2]8980.37亿元，比上年增长5.7%。")
    values = RuleExtractor().extract(text, {"region": "厦门市", "year": "2025"}, _rules())
    gdp = [v for v in values if v.indicator_name == "地区生产总值"]
    assert len(gdp) == 1
    assert gdp[0].value == "8980.37"
    assert gdp[0].unit == "亿元"

def test_extract_population_and_income():
    values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
    pop = [v for v in values if v.indicator_name == "常住人口"][0]
    assert pop.value == "4185"
    assert pop.category == "人民生活"
    inc = [v for v in values if v.indicator_name == "居民人均可支配收入"][0]
    assert inc.value == "46095"


def test_fallback_population_cpi_investment():
    """人口/CPI/投资段无编号标题（未落入对应章节）时，fallback 全文补漏并排除城镇口径。"""
    text = ("一、综合\n"
            "初步核算，全年实现地区生产总值12345.67亿元，比上年增长5.5%。\n"
            "人口\n年末常住人口345万人，常住人口城镇化率55%。其中，城镇常住人口213万人。\n"
            "居民消费价格\n全年居民消费价格比上年上涨0.4%。\n"
            "投资\n全年固定资产投资比上年增长5.2%。")
    values = RuleExtractor().extract(text, {"region": "某市", "year": "2025"}, _rules())
    pop = [v for v in values if v.indicator_name == "常住人口"]
    cpi = [v for v in values if v.indicator_name == "居民消费价格指数"]
    inv = [v for v in values if v.indicator_name == "固定资产投资"]
    assert pop and pop[0].value == "345"
    assert cpi and cpi[0].value == "0.4"
    assert inv and inv[0].value == "5.2"


# ---------- M7a: normalize_value 与每页每指标单值收敛 ----------

from app.extract.rule_extractor import normalize_value  # noqa: E402


def test_normalize_fullwidth():
    assert normalize_value("５３１６２．３６") == "53162.36"
    assert normalize_value("１６８８．２") == "1688.2"


def test_normalize_thousands_and_spaces():
    assert normalize_value("1,688.2") == "1688.2"
    assert normalize_value("1 688") == "1688"
    assert normalize_value("2486 450") == "2486450"


def test_ningde_style_trade_converges_to_total():
    """同页子口径(民营/国有/RCEP/五年累计/占比)不再重复入库——只留全年总额。"""
    text = ("全年进出口总额502.5亿元，比上年增长17.9%。其中，民营企业进出口306.2亿元，"
            "增长10.8%；国有企业进出口133.2亿元，增长93.1%；对RCEP成员国进出口185.9亿元，"
            "占进出口总额37%。“十三五”期间，累计实现进出口总额1844.02亿元，年均增长13.8%。")
    values = RuleExtractor().extract(text, {"region": "宁德市", "year": "2020"}, _rules())
    trade = [v for v in values if v.indicator_name == "进出口总额"]
    assert len(trade) == 1, [v.raw_text for v in trade]
    assert trade[0].value == "502.5"


def test_tax_pick_main_caliber_over_customs():
    """海关代征税收 121.87 是子口径，不顶替主口径 814.34。"""
    text = ("税务部门组织的各项收入1494.89亿元，其中税收收入814.34亿元，下降1.2%。"
            "海关代征税收收入121.87亿元，下降25.9%。")
    values = RuleExtractor().extract(text, {"region": "泉州市", "year": "2025"}, _rules())
    tax = [v for v in values if v.indicator_name == "税收收入"]
    assert len(tax) == 1
    assert tax[0].value == "814.34"


def test_same_value_duplicate_converges():
    """同页同值(摘要段与正文段各出现一次)只留一行。"""
    text = ("全年货物进出口总额2363.79亿元，比上年下降12.9%。\n"
            "其中，全年货物进出口总额2363.79亿元，出口1651.70亿元。")
    values = RuleExtractor().extract(text, {"region": "泉州市", "year": "2025"}, _rules())
    trade = [v for v in values if v.indicator_name == "进出口总额"]
    assert len(trade) == 1


def test_share_percent_value_not_captured_as_total():
    """“占进出口总额37%”的比例不产出 进出口总额 行。"""
    text = ("对RCEP成员国进出口185.9亿元，占进出口总额37%。全年进出口总额502.5亿元。")
    values = RuleExtractor().extract(text, {"region": "某市", "year": "2020"}, _rules())
    trade = [v for v in values if v.indicator_name == "进出口总额"]
    assert [v.value for v in trade] == ["502.5"]
