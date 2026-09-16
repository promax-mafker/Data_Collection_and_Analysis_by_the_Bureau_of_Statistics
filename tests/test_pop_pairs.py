"""`_pop_pairs` 回退路径的健全性测试（M11 复核）。

背景：`econ_series` 的 `indicator='population'` **混装了 6 个不同指标**
（常住人口 / 出生率 / 死亡率 / 自然增长率 / 人口密度 / 城镇化率），
子维度保存在 `note`。

原实现 `_econ_map` 用 `{year: value}` 字典覆盖 → 取到的是**该年最后一行**，
可能把「城镇化率 71.19」当成长住人口。真实库 2024 年 population 的 6 个值为
`891.4 / 7.7 / 7.1 / 0.6 / 789 / 71.19`，可见风险是实在的。
"""
from app.analysis.decision_tree import _pop_pairs
from app.store.db import init_db
from app.store.repository import Repository


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def test_pop_pairs_picks_resident_population_by_note(tmp_path):
    repo = _repo(tmp_path)
    repo.replace_econ_series("pop_3_4", [
        {"indicator": "population", "year": "2024", "value": "891.4", "unit": "万人",
         "note": "常住人口（万人）"},
        {"indicator": "population", "year": "2024", "value": "71.19", "unit": "%",
         "note": "城镇化率（%）"},
    ])
    assert _pop_pairs(repo, "泉州市") == [("2024", 891.4)]


def test_pop_pairs_returns_empty_when_no_resident_marker(tmp_path):
    """只有非人口指标时宁可返回空（缺），也不拿城镇化率冒充常住人口（错）。"""
    repo = _repo(tmp_path)
    repo.replace_econ_series("pop_3_4", [
        {"indicator": "population", "year": "2024", "value": "71.19", "unit": "%",
         "note": "城镇化率（%）"},
        {"indicator": "population", "year": "2024", "value": "789", "unit": "人/平方公里",
         "note": "人口密度（人/平方公里）"},
    ])
    assert _pop_pairs(repo, "泉州市") == []


def test_pop_pairs_prefers_data_values_over_econ_series(tmp_path):
    """data_values 有常住人口时优先用它，不回退到 econ_series。"""
    from app.schemas import Bureau, DataValue
    repo = _repo(tmp_path)
    bid = repo.upsert_bureau(Bureau(level="city", name="泉州市统计局",
                                    url="http://qz", region="泉州市"))
    repo.insert_values([DataValue(page_id=None, bureau_id=bid, region="泉州市", year="2024",
                                  indicator_name="常住人口", value="891.4", unit="万人",
                                  category="人口", raw_text="r", caliber="final")])
    repo.replace_econ_series("pop_3_4", [
        {"indicator": "population", "year": "2024", "value": "71.19", "unit": "%",
         "note": "城镇化率（%）"},
    ])
    assert [y for y, _ in _pop_pairs(repo, "泉州市")] == ["2024"]
    assert _pop_pairs(repo, "泉州市")[0][1] == 891.4
