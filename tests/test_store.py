from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import Bureau, DataValue

def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))

def test_bureau_upsert_dedup(tmp_path):
    repo = _repo(tmp_path)
    b1 = Bureau(level="city", name="福州市统计局", url="https://tjj.fuzhou.gov.cn/", region="福州市")
    i = repo.upsert_bureau(b1)
    b2 = Bureau(level="city", name="福州市统计局", url="https://tjj.fuzhou.gov.cn/", region="福州市", verified=True)
    j = repo.upsert_bureau(b2)
    assert i == j
    assert repo.list_bureaus()[0]["verified"] == 1

def test_insert_and_query_and_export(tmp_path):
    repo = _repo(tmp_path)
    v = DataValue(page_id=None, bureau_id=None, region="福建省", year="2024",
                  indicator_name="地区生产总值", value="53162.36", unit="亿元",
                  category="综合", raw_text="地区生产总值53162.36亿元")
    assert repo.insert_values([v]) == 1
    rows = repo.query_data(region="福建省", indicator="地区生产总值", year="2024")
    assert len(rows) == 1
    assert rows[0]["value"] == "53162.36"
    assert "地区生产总值" in repo.export_csv(region="福建省")

def test_run_lifecycle(tmp_path):
    repo = _repo(tmp_path)
    rid = repo.start_run()
    repo.finish_run(rid, "success", {"values": 3}, "log line")
    run = repo.get_run(rid)
    assert run["status"] == "success"
    assert len(repo.list_runs()) == 1
