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

def test_extract_population_and_income():
    values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
    pop = [v for v in values if v.indicator_name == "常住人口"][0]
    assert pop.value == "4185"
    assert pop.category == "人民生活"
    inc = [v for v in values if v.indicator_name == "居民人均可支配收入"][0]
    assert inc.value == "46095"
