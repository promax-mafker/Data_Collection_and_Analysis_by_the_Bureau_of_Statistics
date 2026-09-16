"""跨源一致性状态测试（M9d）。

核心纪律（设计 P5）：**同源搬运不算交叉验证** —— 公报与年鉴都是统计局口径，
两者并存**不构成**独立第二来源。
"""
from app.analysis.crosscheck import cross_source_status, summarize_cross_source
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
                  category="综合", raw_text="r", source_kind=""),          # 公报
        DataValue(page_id=None, bureau_id=bid, region="泉州市", year="2024",
                  indicator_name="进出口总额", value="2715", unit="亿元",
                  category="外贸", raw_text="r", source_kind="yearbook"),   # 年鉴
    ])
    return repo


def test_yearbook_is_not_an_independent_second_source(tmp_path):
    """公报 + 年鉴 并存 ≠ 可交叉验证（都是统计局口径）。"""
    repo = _repo(tmp_path)
    s = {x["indicator"]: x for x in cross_source_status(repo)}
    assert s["进出口总额"]["verdict"] == "single_source"
    assert s["进出口总额"]["independent"] == []
    assert "单一来源" in s["进出口总额"]["note"]


def test_independent_source_marks_ok(tmp_path):
    repo = _repo(tmp_path)
    repo.conn.execute(
        "INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,"
        "category,raw_text,caliber,source_kind,source_rank) VALUES "
        "(NULL,1,'泉州市','2024','一般公共预算收入','592.07','亿元','财政','r','final','celma',3)")
    repo.conn.commit()
    s = {x["indicator"]: x for x in cross_source_status(repo)}
    assert s["一般公共预算收入"]["verdict"] == "ok"
    assert "财政部" in s["一般公共预算收入"]["note"]


def test_missing_indicator_is_na(tmp_path):
    repo = _repo(tmp_path)
    s = {x["indicator"]: x for x in cross_source_status(repo)}
    assert s["常住人口"]["verdict"] == "na"


def test_summary_lists_single_source_indicators(tmp_path):
    repo = _repo(tmp_path)
    summ = summarize_cross_source(cross_source_status(repo))
    assert summ["single_source"] >= 2
    assert "进出口总额" in summ["single_list"]
    assert summ["ok"] == 0
