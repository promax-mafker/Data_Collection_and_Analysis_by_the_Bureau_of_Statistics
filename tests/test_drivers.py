"""三驾马车分析测试：消费/投资/出口。"""
from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import DataValue
from app.analysis.consumption import consumption_support
from app.analysis.investment import investment_support
from app.analysis.trade import trade_support


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def _seed_macro(repo):
    """GDP + 社零（data_values）+ 人口/收支/CPI/进出口/债务（econ_series）。"""
    repo.insert_values([
        DataValue(None, None, "泉州市", "2025", "地区生产总值", "13778.34", "亿元", "综合", "…"),
        DataValue(None, None, "泉州市", "2024", "地区生产总值", "13094.87", "亿元", "综合", "…"),
        DataValue(None, None, "泉州市", "2025", "社会消费品零售总额", "6416.07", "亿元", "国内贸易", "…"),
        DataValue(None, None, "泉州市", "2024", "社会消费品零售总额", "6164.07", "亿元", "国内贸易", "…"),
        DataValue(None, None, "泉州市", "2025", "一般公共预算收入", "592.07", "亿元", "财政金融", "…"),
    ])
    repo.replace_econ_series("pop_3_4", [
        {"indicator": "population", "year": "2024", "value": "891.4", "unit": "万人", "note": "常住人口", "raw_text": ""},
    ])
    repo.replace_econ_series("income_4_7", [
        {"indicator": "income_consumption", "year": "2024", "value": "54858", "unit": "元", "note": "全体居民人均可支配收入", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "33723", "unit": "元", "note": "全体居民人均消费支出", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "11001", "unit": "元", "note": "食品烟酒", "raw_text": ""},
    ])
    repo.replace_econ_series("trade_12_3", [
        {"indicator": "trade", "year": "2024", "value": "1651.70", "unit": "亿元", "note": "出口额", "raw_text": ""},
        {"indicator": "trade", "year": "2024", "value": "712.09", "unit": "亿元", "note": "进口额", "raw_text": ""},
    ])
    repo.replace_econ_series("debt_2024", [
        {"indicator": "debt_balance", "year": "2024", "value": "2661.16", "unit": "亿元", "note": "全市", "raw_text": ""},
        {"indicator": "debt_limit", "year": "2024", "value": "2753.80", "unit": "亿元", "note": "全市", "raw_text": ""},
    ])


def test_consumption_support(tmp_path):
    repo = _repo(tmp_path); _seed_macro(repo)
    c = consumption_support(repo)
    # 社零/GDP (2025)
    assert abs(c["retail_gdp_ratio"] - 6416.07 / 13778.34 * 100) < 1e-6
    # 消费倾向 = 33723/54858
    assert abs(c["propensity"] - 33723 / 54858 * 100) < 1e-6
    # 恩格尔系数 = 11001/33723
    assert abs(c["engel"] - 11001 / 33723 * 100) < 1e-6


def test_consumption_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    c = consumption_support(repo)
    assert c["retail_gdp_ratio"] is None
    assert c["propensity"] is None


def test_investment_support(tmp_path):
    repo = _repo(tmp_path); _seed_macro(repo)
    inv = investment_support(repo)
    # 债务/GDP = 2661.16/13094.87（债务 2024 末 ÷ 同年 GDP 2024，M8 修正跨年错配）
    assert abs(inv["debt_gdp"] - 2661.16 / 13094.87 * 100) < 1e-6
    # 债务限额使用率 = 2661.16/2753.80
    assert abs(inv["debt_limit_usage"] - 2661.16 / 2753.80 * 100) < 1e-6
    assert inv["debt_year"] == "2024" and inv["gdp_year"] == "2024"


def test_investment_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    inv = investment_support(repo)
    assert inv["debt_gdp"] is None


def test_trade_support(tmp_path):
    repo = _repo(tmp_path); _seed_macro(repo)
    t = trade_support(repo)
    # 外贸依存度 = 出口(2024)/GDP(2024)——同年口径(M8 修正)
    assert abs(t["export_gdp_ratio"] - 1651.70 / 13094.87 * 100) < 1e-6
    # 净出口 = 1651.70 - 712.09
    assert abs(t["net_export"] - (1651.70 - 712.09)) < 1e-6
    assert t["year"] == "2024" and t["gdp_year"] == "2024"


def test_trade_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    t = trade_support(repo)
    assert t["export_gdp_ratio"] is None
    assert t["net_export"] is None


# ---------- M8: 同年取数回归(A10 修复) ----------

def test_consumption_years_aligned_to_same_year(tmp_path):
    """收入/支出/食品必须取同一年份——防止错年配对。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("income_4_7", [
        {"indicator": "income_consumption", "year": "2023", "value": "52000", "unit": "元",
         "note": "全体居民人均可支配收入", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "54858", "unit": "元",
         "note": "全体居民人均可支配收入", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "33723", "unit": "元",
         "note": "全体居民人均消费支出", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "11001", "unit": "元",
         "note": "食品烟酒", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2023", "value": "31500", "unit": "元",
         "note": "全体居民人均消费支出", "raw_text": ""},
    ])
    c = consumption_support(repo)
    assert c["propensity"] is not None and c["engel"] is not None
    assert abs(c["propensity"] - 33723 / 54858 * 100) < 1e-6  # 2024 对 2024
    assert c["income_year"] == c["spending_year"] == "2024"


def test_consumption_mismatched_years_propensity_none(tmp_path):
    """收入只到 2023、支出只到 2024 → 倾向不可比，返回 None 而非错年配对。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("income_4_7", [
        {"indicator": "income_consumption", "year": "2023", "value": "52000", "unit": "元",
         "note": "全体居民人均可支配收入", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "33723", "unit": "元",
         "note": "全体居民人均消费支出", "raw_text": ""},
    ])
    c = consumption_support(repo)
    assert c["propensity"] is None
    assert c["engel"] is None


def test_trade_latest_same_year_not_first(tmp_path):
    """出口/进口取「同年都存在」的最大年份——修复取最早年份(1984)事故。"""
    repo = _repo(tmp_path)
    rows = []
    for y in ("1984", "1990", "2023"):
        rows += [
            {"indicator": "trade", "year": y, "value": "10.0", "unit": "亿元", "note": "出口额", "raw_text": ""},
            {"indicator": "trade", "year": y, "value": "8.0", "unit": "亿元", "note": "进口额", "raw_text": ""},
        ]
    rows += [{"indicator": "trade", "year": "2024", "value": "1651.70", "unit": "亿元", "note": "出口额", "raw_text": ""}]
    repo.replace_econ_series("trade_12_3", rows)
    repo.insert_values([
        DataValue(None, None, "泉州市", "2023", "地区生产总值", "12000.0", "亿元", "综合", "…"),
    ])
    t = trade_support(repo)
    # 2024 只有出口无进口 → 退回 2023 同年对
    assert t["year"] == "2023"
    assert abs(t["net_export"] - 2.0) < 1e-6
    assert abs(t["export_gdp_ratio"] - 10.0 / 12000.0 * 100) < 1e-6  # GDP 取 2023


def test_investment_debt_gdp_same_year(tmp_path):
    """债务余额(2024 末) ÷ GDP(2024)——不再错配 GDP 2025。"""
    repo = _repo(tmp_path)
    repo.insert_values([
        DataValue(None, None, "泉州市", "2025", "地区生产总值", "13778.34", "亿元", "综合", "…"),
        DataValue(None, None, "泉州市", "2024", "地区生产总值", "13094.87", "亿元", "综合", "…"),
    ])
    repo.replace_econ_series("debt_2024", [
        {"indicator": "debt_balance", "year": "2024", "value": "2661.16", "unit": "亿元", "note": "全市", "raw_text": ""},
        {"indicator": "debt_limit", "year": "2024", "value": "2753.80", "unit": "亿元", "note": "全市", "raw_text": ""},
    ])
    inv = investment_support(repo)
    assert inv["debt_year"] == "2024" and inv["gdp_year"] == "2024"
    assert abs(inv["debt_gdp"] - 2661.16 / 13094.87 * 100) < 1e-6
