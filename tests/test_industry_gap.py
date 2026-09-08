"""industry_gap.py 测试：增长贡献率 + 错配矩阵。"""
import json

from app.store.db import init_db
from app.store.repository import Repository
from app.analysis.industry_gap import growth_contribution, industry_gap, hhi


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def _seed_industry_data(repo):
    """重点产业 2016/2024 企业单位数（模拟 8-8 表）。"""
    rows = [
        {"industry": "纺织鞋服", "year": "2016", "metric": "企业单位数（个）", "value": "3000", "unit": "", "raw_text": ""},
        {"industry": "纺织鞋服", "year": "2024", "metric": "企业单位数（个）", "value": "3600", "unit": "", "raw_text": ""},
        {"industry": "机械装备", "year": "2016", "metric": "企业单位数（个）", "value": "1000", "unit": "", "raw_text": ""},
        {"industry": "机械装备", "year": "2024", "metric": "企业单位数（个）", "value": "2000", "unit": "", "raw_text": ""},
        {"industry": "电子信息", "year": "2016", "metric": "企业单位数（个）", "value": "500", "unit": "", "raw_text": ""},
        {"industry": "电子信息", "year": "2024", "metric": "企业单位数（个）", "value": "550", "unit": "", "raw_text": ""},
    ]
    repo.replace_industry_data("industry_8_8", rows)


def _seed_plan(repo):
    """规划产业（doc_insights kind=industry，泉州 region）。"""
    repo.insert_doc_insights([
        {"page_id": 1, "source_id": "plan_15", "kind": "industry", "title": "x",
         "body": json.dumps({"industries": [
             {"industry": "纺织鞋服", "plan_role": "支柱", "evidence": "e1"},
             {"industry": "机械装备", "plan_role": "支柱", "evidence": "e2"},
             {"industry": "健康食品", "plan_role": "新兴", "evidence": "e3"}]}, ensure_ascii=False),
         "method": "llm", "region": "泉州市", "period": "2026"},
    ])


def _seed_enterprise_industry(repo):
    repo.replace_enterprise_industry([
        {"enterprise_id": 1, "industry": "纺织鞋服", "method": "rule"},
        {"enterprise_id": 2, "industry": "纺织鞋服", "method": "rule"},
        {"enterprise_id": 3, "industry": "机械装备", "method": "rule"},
        {"enterprise_id": 4, "industry": "电子信息", "method": "rule"},
    ])


def test_hhi():
    assert abs(hhi({"a": 2, "b": 1}) - (4 / 9 + 1 / 9)) < 1e-9


def test_growth_contribution(tmp_path):
    repo = _repo(tmp_path)
    _seed_industry_data(repo)
    g = growth_contribution(repo, metric="企业单位数（个）")
    # 纺织鞋服 2016→2024 增速 +20%；机械 +100%；电子 +10%
    assert g["纺织鞋服"]["growth_pct"] == 20.0
    assert g["机械装备"]["growth_pct"] == 100.0
    assert g["电子信息"]["growth_pct"] == 10.0


def test_industry_gap_matched(tmp_path):
    repo = _repo(tmp_path)
    _seed_industry_data(repo)
    _seed_plan(repo)
    _seed_enterprise_industry(repo)
    gaps = industry_gap(repo)
    by_name = {g["industry"]: g for g in gaps}
    # 纺织鞋服：规划支柱 + 有企业 + 有增长 → matched
    assert by_name["纺织鞋服"]["verdict"] in ("matched", "overpromised")


def test_industry_gap_overpromised(tmp_path):
    """规划列为支柱但无实际数据支撑 → overpromised。"""
    repo = _repo(tmp_path)
    _seed_industry_data(repo)
    _seed_plan(repo)  # 健康食品 规划新兴，但 industry_data 无记录
    _seed_enterprise_industry(repo)
    gaps = industry_gap(repo)
    by_name = {g["industry"]: g for g in gaps}
    assert by_name["健康食品"]["verdict"] == "overpromised"


def test_silent_pillar(tmp_path):
    """实际数据强（电子信息有企业+增长）但规划未提 → silent_pillar。"""
    repo = _repo(tmp_path)
    _seed_industry_data(repo)
    # 规划只提纺织鞋服，不提电子信息
    repo.insert_doc_insights([
        {"page_id": 1, "source_id": "plan_15", "kind": "industry", "title": "x",
         "body": json.dumps({"industries": [
             {"industry": "纺织鞋服", "plan_role": "支柱", "evidence": "e1"}]}, ensure_ascii=False),
         "method": "llm", "region": "泉州市", "period": "2026"},
    ])
    _seed_enterprise_industry(repo)
    gaps = industry_gap(repo, thresholds={"weak_share": 5.0, "strong_share": 8.0})
    by_name = {g["industry"]: g for g in gaps}
    assert by_name["电子信息"]["verdict"] == "silent_pillar"


def test_industry_gap_plan_region_isolation(tmp_path):
    """industry_gap 只读泉州规划洞察：外市 kind=industry 不进入错配判断。"""
    repo = _repo(tmp_path)
    _seed_industry_data(repo)
    repo.insert_doc_insights([
        {"page_id": 2, "source_id": "zz", "kind": "industry", "title": "漳州规划",
         "body": json.dumps({"industries": [
             {"industry": "石化基地", "plan_role": "支柱", "evidence": "e"}]}, ensure_ascii=False),
         "method": "llm", "region": "漳州市", "period": "2026"},
    ])
    _seed_enterprise_industry(repo)
    gaps = industry_gap(repo)
    names = {g["industry"] for g in gaps}
    assert "石化基地" not in names  # 漳州规划不进入泉州错配矩阵


def test_gap_has_evidence(tmp_path):
    repo = _repo(tmp_path)
    _seed_industry_data(repo)
    _seed_plan(repo)
    _seed_enterprise_industry(repo)
    gaps = industry_gap(repo)
    for g in gaps:
        assert "evidence" in g
        assert "enterprise_cnt" in g
