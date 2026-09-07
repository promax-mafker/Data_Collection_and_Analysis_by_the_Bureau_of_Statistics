"""extract_named：按指标名子集抽取（预算执行等数值页专用）。"""
from app.extract.rule_extractor import RuleExtractor

FISCAL_TEXT = """2026年上半年全市预算执行情况
全市地方一般公共预算收入 355.92 亿元，同比增长 4.1%；税收收入 204.02 亿元，
政府性基金收入 105.3 亿元；一般公共预算支出完成 480.6 亿元。
其中市本级一般公共预算收入 80.2 亿元。
"""


def _rules():
    # 用与配置一致的规则结构（避免单测依赖磁盘 yaml）
    return [
        {"name": "地方一般公共预算收入", "category": "财政金融", "unit": "亿元",
         "pattern": r"地方一般公共预算收入[^0-9]{0,10}(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>亿元)?"},
        {"name": "税收收入", "category": "财政金融", "unit": "亿元",
         "pattern": r"税收收入[^0-9]{0,10}(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>亿元)?"},
        {"name": "政府性基金收入", "category": "财政金融", "unit": "亿元",
         "pattern": r"政府性基金收入[^0-9]{0,10}(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>亿元)?"},
        {"name": "地区生产总值", "category": "综合", "unit": "亿元",
         "pattern": r"(?<!人均)(?:地区生产总值|GDP)[^0-9]{0,10}(?P<value>[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?P<unit>亿元)?"},
    ]


def test_extract_named_only_selected():
    ex = RuleExtractor()
    values = ex.extract_named(FISCAL_TEXT, ["税收收入", "政府性基金收入"],
                              {"region": "泉州市", "year": "2026"}, _rules())
    names = {v.indicator_name for v in values}
    assert names == {"税收收入", "政府性基金收入"}
    tax = [v for v in values if v.indicator_name == "税收收入"][0]
    assert tax.value == "204.02"
    assert tax.unit == "亿元"
    fund = [v for v in values if v.indicator_name == "政府性基金收入"][0]
    assert fund.value == "105.3"


def test_extract_named_empty_names_returns_nothing():
    ex = RuleExtractor()
    values = ex.extract_named(FISCAL_TEXT, [], {"region": "泉州市", "year": "2026"}, _rules())
    assert values == []


def test_extract_named_does_not_grab_unrequested():
    ex = RuleExtractor()
    values = ex.extract_named(FISCAL_TEXT, ["地区生产总值"],
                              {"region": "泉州市", "year": "2026"}, _rules())
    assert values == []  # 文本没有 GDP，不应抓到收入


def test_full_extract_still_works():
    """extract(全量) 行为不受影响。"""
    ex = RuleExtractor()
    values = ex.extract(FISCAL_TEXT, {"region": "泉州市", "year": "2026"}, _rules())
    names = {v.indicator_name for v in values}
    assert "税收收入" in names and "地区生产总值" not in names


def test_fund_with_budget_suffix():
    """「政府性基金预算收入」也应命中（泉州公报表述）。"""
    from app.extract.rule_extractor import load_rules
    rules = load_rules(r"config/extract_rules.yaml")
    ex = RuleExtractor()
    text = "政府性基金预算收入292.07亿元，政府性基金预算支出525.80亿元"
    vals = ex.extract_named(text, ["政府性基金收入"], {"region": "泉州市", "year": "2025"}, rules)
    assert len(vals) == 1
    assert vals[0].value == "292.07"
