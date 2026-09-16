"""`decision_tree` 读 `econ_series(cpi)` 的健全性测试（M11 复核最后一项）。

背景：`indicator='cpi'` 混装了**全国/全省/全市**三个地区（子维度在 `note`），
真实库 2024 年三个值为 `100.2 / 99.9 / 100.0`。
原实现 `_econ_map(repo, "cpi")` 用 `{year: value}` 字典覆盖 → 取到**该年最后一行**，
即把哪个地区的 CPI 当成本地 CPI 取决于行序 —— 与已修的 `population` 同类缺陷。
"""
from app.analysis.decision_tree import _cpi_series
from app.store.db import init_db
from app.store.repository import Repository


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def test_cpi_series_picks_local_not_national(tmp_path):
    repo = _repo(tmp_path)
    repo.replace_econ_series("cpi_5_2", [
        {"indicator": "cpi", "year": "2024", "value": "100.2", "unit": "上年=100",
         "note": "全国"},
        {"indicator": "cpi", "year": "2024", "value": "99.9", "unit": "上年=100",
         "note": "全省"},
        {"indicator": "cpi", "year": "2024", "value": "100.0", "unit": "上年=100",
         "note": "全市"},
    ])
    assert _cpi_series(repo) == {"2024": 100.0}


def test_cpi_series_empty_when_no_local_marker(tmp_path):
    """只有全国/全省时宁可返回空（缺），也不拿外地的 CPI 冒充本地（错）。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("cpi_5_2", [
        {"indicator": "cpi", "year": "2024", "value": "100.2", "unit": "上年=100",
         "note": "全国"},
        {"indicator": "cpi", "year": "2024", "value": "99.9", "unit": "上年=100",
         "note": "全省"},
    ])
    assert _cpi_series(repo) == {}


def test_cpi_series_accepts_quanzhou_marker(tmp_path):
    """部分卷次的列名是「泉州」而非「全市」（实测年鉴 2020 卷如此）。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("cpi_5_2", [
        {"indicator": "cpi", "year": "2020", "value": "102.5", "unit": "上年=100",
         "note": "泉州"},
    ])
    assert _cpi_series(repo) == {"2020": 102.5}
