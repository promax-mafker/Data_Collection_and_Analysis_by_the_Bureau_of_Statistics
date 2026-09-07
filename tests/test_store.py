from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import Bureau, DataValue, Page

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

def test_page_doc_category_persisted(tmp_path):
    repo = _repo(tmp_path)
    b = Bureau(level="city", name="泉州市政府", url="https://www.quanzhou.gov.cn/", region="泉州市")
    bid = repo.upsert_bureau(b)
    p = Page(bureau_id=bid, url="https://www.quanzhou.gov.cn/plan.pdf",
             title="十五五纲要", content_text="全文…", dataset_type="topic",
             period="2026", content_hash="h1", doc_category="plan")
    pid = repo.upsert_page(p)
    pages = repo.list_pages(doc_category="plan")
    assert len(pages) == 1 and pages[0]["id"] == pid
    assert repo.list_pages(doc_category="bulletin") == []

def test_doc_insights_crud_and_replace(tmp_path):
    repo = _repo(tmp_path)
    items = [
        {"page_id": 1, "source_id": "plan_15", "kind": "industry", "title": "纺织鞋服",
         "body": '{"industry":"纺织鞋服"}', "method": "llm"},
        {"page_id": 1, "source_id": "plan_15", "kind": "plan_goal", "title": "增速目标",
         "body": '{"gdp_growth":5}', "method": "llm"},
    ]
    assert repo.insert_doc_insights(items) == 2
    rows = repo.list_doc_insights(page_id=1)
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"industry", "plan_goal"}
    assert repo.list_doc_insights(kind="industry")[0]["title"] == "纺织鞋服"
    # 整页替换
    assert repo.replace_doc_insights(1, [dict(items[0])]) == 1
    assert len(repo.list_doc_insights(page_id=1)) == 1

def test_enterprises_crud_and_replace(tmp_path):
    repo = _repo(tmp_path)
    rows = [
        {"year": "2025", "list_type": "上市后备", "name": "恒安集团", "county": "晋江市", "rank": "1"},
        {"year": "2025", "list_type": "上市后备", "name": "安踏体育", "county": "晋江市", "rank": "2"},
    ]
    assert repo.replace_enterprises(9, rows) == 2
    got = repo.list_enterprises(year="2025")
    assert len(got) == 2 and got[0]["name"] == "恒安集团"
    assert repo.replace_enterprises(9, [rows[0]]) == 1
    assert len(repo.list_enterprises()) == 1
    assert repo.list_enterprises(list_type="挂牌后备") == []


# ---------- M6 新表 CRUD ----------

def test_industry_data_crud_and_replace(tmp_path):
    repo = _repo(tmp_path)
    rows = [
        {"industry": "纺织鞋服", "year": "2024", "metric": "revenue", "value": "5000", "unit": "万元", "raw_text": "r1"},
        {"industry": "机械装备", "year": "2024", "metric": "employees", "value": "30000", "unit": "人", "raw_text": "r2"},
    ]
    assert repo.replace_industry_data("yearbook_8_8", rows) == 2
    got = repo.list_industry_data(source="yearbook_8_8")
    assert len(got) == 2
    assert repo.list_industry_data(metric="revenue")[0]["value"] == "5000"
    # 重复 replace 不累积
    assert repo.replace_industry_data("yearbook_8_8", [rows[0]]) == 1
    assert len(repo.list_industry_data(source="yearbook_8_8")) == 1


def test_econ_series_crud_and_replace(tmp_path):
    repo = _repo(tmp_path)
    rows = [
        {"indicator": "population", "year": "2024", "value": "891.4", "unit": "万人", "note": "", "raw_text": "r"},
        {"indicator": "cpi", "year": "2024", "value": "101.0", "unit": "", "note": "上年=100", "raw_text": "r"},
    ]
    assert repo.replace_econ_series("yearbook_3_4", rows) == 2
    got = repo.list_econ_series(source="yearbook_3_4")
    assert len(got) == 2
    assert repo.list_econ_series(indicator="population")[0]["value"] == "891.4"
    assert repo.replace_econ_series("yearbook_3_4", [rows[1]]) == 1
    assert len(repo.list_econ_series(source="yearbook_3_4")) == 1


def test_enterprise_industry_crud(tmp_path):
    repo = _repo(tmp_path)
    rows = [
        {"enterprise_id": 1, "industry": "卫生用品", "method": "rule"},
        {"enterprise_id": 2, "industry": "金融", "method": "llm"},
    ]
    assert repo.replace_enterprise_industry(rows) == 2
    got = repo.list_enterprise_industry()
    assert len(got) == 2
    assert {r["industry"] for r in got} == {"卫生用品", "金融"}
    # 重新归类覆盖
    assert repo.replace_enterprise_industry([{"enterprise_id": 1, "industry": "纺织鞋服", "method": "rule"}]) == 1
    got2 = {r["enterprise_id"]: r["industry"] for r in repo.list_enterprise_industry()}
    assert got2[1] == "纺织鞋服"
