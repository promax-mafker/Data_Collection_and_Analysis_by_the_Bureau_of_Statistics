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
    # 债务/GDP = 2661.16/13778.34
    assert abs(inv["debt_gdp"] - 2661.16 / 13778.34 * 100) < 1e-6
    # 债务限额使用率 = 2661.16/2753.80
    assert abs(inv["debt_limit_usage"] - 2661.16 / 2753.80 * 100) < 1e-6


def test_investment_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    inv = investment_support(repo)
    assert inv["debt_gdp"] is None


def test_trade_support(tmp_path):
    repo = _repo(tmp_path); _seed_macro(repo)
    t = trade_support(repo)
    # 外贸依存度 = 出口/GDP
    assert abs(t["export_gdp_ratio"] - 1651.70 / 13778.34 * 100) < 1e-6
    # 净出口 = 1651.70 - 712.09
    assert abs(t["net_export"] - (1651.70 - 712.09)) < 1e-6


def test_trade_missing_returns_none(tmp_path):
    repo = _repo(tmp_path)
    t = trade_support(repo)
    assert t["export_gdp_ratio"] is None
    assert t["net_export"] is None
