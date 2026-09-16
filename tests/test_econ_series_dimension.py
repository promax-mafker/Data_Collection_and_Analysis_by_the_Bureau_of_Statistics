"""`econ_series` 维度承载方式的特征化测试。

背景：M11 复核发现 `econ_series` 的 `indicator` 列是**通用名**
（`trade` / `population` / `cpi` / `income_consumption`），子维度（出口/进口、
出生率/死亡率、全国/全省/全市…）保存在 **`note`** 列。因此
`find_ambiguous_econ_series()` 报出的「同键多值」**不等于**静默错值 —— 前提是
消费方按 `note` 消歧。

本文件锁定这一依赖：若将来有人把 `note` 消歧去掉，这些测试会红。
"""
from app.analysis.trade import trade_support
from app.store.db import init_db
from app.store.repository import Repository


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def test_trade_separates_export_and_import_by_note(tmp_path):
    """同一年 `indicator='trade'` 两行，必须靠 note 分成出口/进口。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("trade_12_3", [
        {"indicator": "trade", "year": "2024", "value": "1988.0", "unit": "亿元",
         "note": "出口额"},
        {"indicator": "trade", "year": "2024", "value": "727.0", "unit": "亿元",
         "note": "进口额"},
    ])
    tx = trade_support(repo, "泉州市")
    assert tx["export"] == 1988.0
    assert tx["import"] == 727.0
    assert tx["net_export"] == 1988.0 - 727.0
    assert tx["year"] == "2024"


def test_trade_ignores_rows_without_direction_note(tmp_path):
    """note 不含方向的行不得被当成出口或进口（宁可缺，不可错配）。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("trade_12_3", [
        {"indicator": "trade", "year": "2024", "value": "999", "unit": "亿元",
         "note": "进出口总额"},
    ])
    tx = trade_support(repo, "泉州市")
    assert tx["export"] is None and tx["import"] is None


def test_trade_requires_same_year_pair_for_net_export(tmp_path):
    """无同年对时不得算净出口（M8 A10 纪律）。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("trade_12_3", [
        {"indicator": "trade", "year": "2023", "value": "1885.5", "unit": "亿元",
         "note": "出口额"},
        {"indicator": "trade", "year": "2024", "value": "727.0", "unit": "亿元",
         "note": "进口额"},
    ])
    tx = trade_support(repo, "泉州市")
    assert tx["net_export"] is None
    assert "无同年" in tx["note"] or tx["year"] is None
