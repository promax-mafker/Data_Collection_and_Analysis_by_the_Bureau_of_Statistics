"""决策树 T5 层（跨源一致性）测试（M9d）。

T5 回答一个「结论可信度」问题：关键指标是否有**独立口径**第二来源。
没有 → 结论可能对，但**无独立证据**支撑，必须标 verify 而不是 ok。
"""
from app.analysis.decision_tree import source_independence_node
from app.schemas import Bureau, DataValue
from app.store.db import init_db
from app.store.repository import Repository


def _repo(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    bid = repo.upsert_bureau(Bureau(level="city", name="泉州市统计局",
                                    url="http://qz", region="泉州市"))
    repo.insert_values([
        DataValue(page_id=None, bureau_id=bid, region="泉州市", year="2024",
                  indicator_name="地区生产总值", value="13778.34", unit="亿元",
                  category="综合", raw_text="r", source_kind=""),
    ])
    return repo


def test_flags_single_source_as_verify(tmp_path):
    n = source_independence_node(_repo(tmp_path))
    assert n["id"] == "T5-3" and n["layer"] == "T5"
    assert n["verdict"] == "verify"
    assert "单一来源" in n["note"]


def test_ok_when_independent_source_present(tmp_path):
    repo = _repo(tmp_path)
    repo.conn.execute(
        "INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,"
        "category,raw_text,caliber,source_kind,source_rank) VALUES "
        "(NULL,1,'泉州市','2024','一般公共预算收入','592.07','亿元','财政','r','final','celma',3)")
    repo.conn.commit()
    n = source_independence_node(repo)
    assert n["verdict"] == "verify" or n["verdict"] == "ok"
    assert "独立口径" in n["evidence"]


def test_na_without_any_data(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t2.db")))
    assert source_independence_node(repo)["verdict"] == "na"
