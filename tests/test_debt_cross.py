"""债务跨层级交叉验证测试（M9e E6）。

用两个**独立来源**相互印证：
* 省级：CELMA 地方政府债券平台（一般债 060101 + 专项债 060102）
* 地市级：地方预决算公开·政府债务情况专文

恒等约束：地市债务余额**不可能 ≥ 全省**。违反即数据错误（不是"存疑"，是"不可能"）。
"""
from app.analysis.debt import cross_check_debt
from app.store.db import init_db
from app.store.repository import Repository


def _repo(tmp_path, prov_general, prov_special, city_balance):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    repo.replace_econ_series("celma_060101", [
        {"indicator": "debt_general", "year": "2024", "value": str(prov_general), "unit": "亿元"}])
    repo.replace_econ_series("celma_060102", [
        {"indicator": "debt_special", "year": "2024", "value": str(prov_special), "unit": "亿元"}])
    repo.replace_econ_series("qz_debt_2024", [
        {"indicator": "debt_balance", "year": "2024", "value": str(city_balance), "unit": "亿元"}])
    return repo


def test_agree_when_city_is_plausible_share_of_province(tmp_path):
    repo = _repo(tmp_path, 3553.74, 10110.63, 2661.16)   # 福建 13664.37 / 泉州 2661.16
    r = cross_check_debt(repo)
    assert r["verdict"] == "agree"
    assert r["year"] == "2024"
    assert abs(r["province_value"] - 13664.37) < 0.01
    assert abs(r["city_value"] - 2661.16) < 0.01
    assert 15 < r["ratio"] < 25
    assert "不可能" not in (r["note"] or "")


def test_flags_impossible_city_ge_province(tmp_path):
    """地市 ≥ 全省是不可能事件 → 必须 flag（数据错误），不得当作"存疑"。"""
    repo = _repo(tmp_path, 1000.0, 1000.0, 2661.16)
    r = cross_check_debt(repo)
    assert r["verdict"] == "diverge"
    assert "不可能" in r["note"]


def test_not_comparable_without_common_year(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    repo.replace_econ_series("celma_060101", [
        {"indicator": "debt_general", "year": "2019", "value": "100", "unit": "亿元"}])
    r = cross_check_debt(repo)
    assert r["verdict"] == "not_comparable"
    assert r["note"]


def test_verify_when_share_out_of_plausible_band(tmp_path):
    """占比过小/过大 → verify（可能是口径不一致，如市本级 vs 全市）。"""
    repo = _repo(tmp_path, 3553.74, 10110.63, 50.0)   # 仅占 0.37%
    r = cross_check_debt(repo)
    assert r["verdict"] == "verify"
    assert "口径" in r["note"]
