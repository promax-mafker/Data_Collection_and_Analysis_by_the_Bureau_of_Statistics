"""quanzhou.py 分析模块测试：财政/产业/市场主体/就业/可信度（纯计算不联网）。"""
import json

from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import DataValue
from app.analysis.quanzhou import analyze_quanzhou, hhi


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def _seed_values(repo):
    """财政 + 就业数据（2025）。"""
    rows = [
        DataValue(None, None, "泉州市", "2025", "地区生产总值", "14000.0", "亿元", "综合", "…"),
        DataValue(None, None, "泉州市", "2024", "地区生产总值", "13084.0", "亿元", "综合", "…"),
        DataValue(None, None, "泉州市", "2025", "地方一般公共预算收入", "592.07", "亿元", "财政金融", "…"),
        DataValue(None, None, "泉州市", "2024", "地方一般公共预算收入", "570.0", "亿元", "财政金融", "…"),
        DataValue(None, None, "泉州市", "2025", "一般公共预算支出", "880.29", "亿元", "财政金融", "…"),
        DataValue(None, None, "泉州市", "2025", "政府性基金收入", "292.07", "亿元", "财政金融", "…"),
        DataValue(None, None, "泉州市", "2025", "税收收入", "500.0", "亿元", "财政金融", "…"),
        DataValue(None, None, "泉州市", "2025", "常住人口", "890.0", "万人", "人民生活", "…"),
        DataValue(None, None, "泉州市", "2025", "城镇新增就业", "9.49", "万人", "人民生活", "…"),
    ]
    repo.insert_values(rows)


def _seed_enterprises(repo):
    rows = [
        {"year": "2025", "list_type": "上市后备", "name": "A", "county": "晋江市", "rank": "1"},
        {"year": "2025", "list_type": "上市后备", "name": "B", "county": "晋江市", "rank": "2"},
        {"year": "2025", "list_type": "上市后备", "name": "C", "county": "石狮市", "rank": "3"},
        {"year": "2024", "list_type": "上市后备", "name": "D", "county": "晋江市", "rank": "1"},
    ]
    repo.replace_enterprises(100, rows)


def _seed_insights(repo):
    items = [
        {"page_id": 1, "source_id": "plan_15", "kind": "industry", "title": "x",
         "body": json.dumps({"industries": [
             {"industry": "纺织鞋服", "plan_role": "支柱", "evidence": "e"},
             {"industry": "电子信息", "plan_role": "新兴", "evidence": "e"}]},
             ensure_ascii=False), "method": "llm", "region": "泉州市", "period": "2026"},
        {"page_id": 1, "source_id": "rep", "kind": "plan_goal", "title": "y",
         "body": json.dumps({"period": "十五五", "targets": {"gdp_growth": 5.0}},
                            ensure_ascii=False), "method": "llm", "region": "泉州市", "period": "2026"},
        {"page_id": 1, "source_id": "rep", "kind": "critique", "title": "z",
         "body": json.dumps({"critiques": [{"type": "spin", "severity": "med",
                                            "evidence": "历史新高"}]},
                            ensure_ascii=False), "method": "llm", "region": "泉州市", "period": "2026"},
    ]
    repo.insert_doc_insights(items)


# ---------- HHI ----------

def test_hhi():
    # 晋江2/石狮1 → (2/3)^2 + (1/3)^2 = 4/9+1/9 = 5/9 ≈ 0.556
    assert abs(hhi({"晋江市": 2, "石狮市": 1}) - 5 / 9) < 1e-6
    assert hhi({}) == 0.0
    assert abs(hhi({"a": 1}) - 1.0) < 1e-9


# ---------- 财政维度 ----------

def test_fiscal_metrics(tmp_path):
    repo = _repo(tmp_path); _seed_values(repo)
    p = analyze_quanzhou(repo)
    f = p["fiscal"]
    assert abs(f["revenue"] - 592.07) < 1e-6
    assert abs(f["expenditure"] - 880.29) < 1e-6
    # 自给率 592.07/880.29
    assert abs(f["self_sufficiency"] - 592.07 / 880.29 * 100) < 1e-6
    # 土地依赖 292.07/(592.07+292.07)
    assert abs(f["land_dependence"] - 292.07 / (592.07 + 292.07) * 100) < 1e-6
    # 财政强度(宏观税负代理) 收入/GDP
    assert abs(f["fiscal_intensity"] - 592.07 / 14000.0 * 100) < 1e-6
    # 收入增速 (592.07-570)/570
    assert abs(f["revenue_growth"] - (592.07 - 570.0) / 570.0 * 100) < 1e-6


def test_fiscal_missing_indicator_none(tmp_path):
    repo = _repo(tmp_path)
    _seed_values(repo)
    # 删除基金收入 → land_dependence None
    repo.conn.execute("DELETE FROM data_values WHERE indicator_name='政府性基金收入'")
    repo.conn.commit()
    p = analyze_quanzhou(repo)
    assert p["fiscal"]["land_dependence"] is None


# ---------- 市场主体 ----------

def test_market_metrics(tmp_path):
    repo = _repo(tmp_path); _seed_enterprises(repo)
    p = analyze_quanzhou(repo)
    m = p["market"]
    assert m["total_2025"] == 3
    assert m["county_counts"]["晋江市"] == 2
    assert abs(m["hhi"] - 5 / 9) < 1e-6
    assert m["top_counties"][0][0] == "晋江市"


# ---------- 就业 ----------

def test_employment_metrics(tmp_path):
    repo = _repo(tmp_path); _seed_values(repo)
    p = analyze_quanzhou(repo)
    e = p["employment"]
    assert e["new_jobs"] == 9.49
    # 密度 9.49/890 ‰
    assert abs(e["density_permille"] - 9.49 / 890.0 * 1000) < 1e-6


def test_employment_missing_density_none(tmp_path):
    repo = _repo(tmp_path); _seed_values(repo)
    repo.conn.execute("DELETE FROM data_values WHERE indicator_name='常住人口'")
    repo.conn.commit()
    p = analyze_quanzhou(repo)
    assert p["employment"]["density_permille"] is None


# ---------- 产业与洞察 ----------

def test_industry_insights_aggregated(tmp_path):
    repo = _repo(tmp_path); _seed_insights(repo)
    p = analyze_quanzhou(repo)
    assert len(p["industry"]) == 2  # 2 条 industry 条目
    roles = {i["plan_role"] for i in p["industry"]}
    assert roles == {"支柱", "新兴"}
    assert p["plan"]["gdp_growth_target"] == 5.0


# ---------- 可信度 ----------

def test_credibility_checks_present(tmp_path):
    repo = _repo(tmp_path); _seed_values(repo)
    _seed_enterprises(repo)
    _seed_insights(repo)
    p = analyze_quanzhou(repo)
    c = p["credibility"]
    assert isinstance(c["checks"], list)
    # C2 无三产数据 → 不出现；C5 因缺 GDP 两年?有两年 → 计算
    assert any(x["id"] == "C5" for x in c["checks"])
    assert isinstance(c["critiques"], list)
    assert any(k["kind"] == "critique" for k in repo.list_doc_insights())


# ---------- 溯源 ----------

def test_sources_traceable(tmp_path):
    repo = _repo(tmp_path); _seed_values(repo)
    p = analyze_quanzhou(repo)
    assert p["reference_year"] == "2025"
    assert p["region"] == "泉州市"


def test_region_isolation_no_cross_pollution(tmp_path):
    """泉州画像不得串入福建省/其它市的同名指标值（真实验证暴露的 bug）。"""
    repo = _repo(tmp_path)
    _seed_values(repo)
    # 注入福建省 GDP（值远大于泉州），模拟库中多 region 同名指标
    repo.insert_values([
        DataValue(None, None, "福建省", "2025", "地区生产总值", "60199.45", "亿元", "综合", "…"),
        DataValue(None, None, "福建省", "2025", "一般公共预算收入", "3723.35", "亿元", "财政金融", "…"),
        DataValue(None, None, "漳州市", "2025", "常住人口", "508.4", "万人", "人民生活", "…"),
    ])
    p = analyze_quanzhou(repo)
    assert p["fiscal"]["gdp"] == 14000.0      # 泉州 GDP，非福建 60199.45
    assert p["fiscal"]["revenue"] == 592.07   # 泉州预算收入，非福建 3723.35
    assert p["employment"]["population"] == 890.0  # 泉州人口，非漳州 508.4


# ---------- M7a: caliber 隔离与洞察 region 隔离 ----------

def _dv(region, ind, year, value, **kw):
    return DataValue(None, None, region, year, ind, value, "亿元", "财政金融", "…", **kw)


def test_fiscal_ignores_budget_caliber(tmp_path):
    """预算执行口径(2026)行不进入画像取值与跨年增速。"""
    repo = _repo(tmp_path)
    _seed_values(repo)
    repo.insert_values([
        _dv("泉州市", "地方一般公共预算收入", "2026", "355.92", caliber="budget"),
        _dv("泉州市", "地区生产总值", "2026", "7000.0", caliber="budget"),
    ])
    p = analyze_quanzhou(repo)
    f = p["fiscal"]
    assert p["reference_year"] == "2025"              # GDP 2026(budget)不抬高参考年
    assert f["revenue"] == 592.07                     # 不吃 2026 预算 355.92
    # 跨年增速仍是 2025 vs 2024（不出现 (2025,592)→(2026,356) 的 -40% 假值）
    assert abs(f["revenue_growth"] - (592.07 - 570.0) / 570.0 * 100) < 1e-6


def test_insights_region_isolation(tmp_path):
    """doc_insights 按 region 隔离：漳州洞察不得进入泉州画像。"""
    repo = _repo(tmp_path)
    _seed_insights(repo)
    repo.insert_doc_insights([
        {"page_id": 2, "source_id": "zz", "kind": "industry", "title": "漳州",
         "body": json.dumps({"industries": [
             {"industry": "特殊钢铁", "plan_role": "支柱", "evidence": "e"}]},
             ensure_ascii=False), "method": "llm", "region": "漳州市", "period": "2026"},
    ])
    p = analyze_quanzhou(repo)
    names = {i["industry"] for i in p["industry"]}
    assert "纺织鞋服" in names and "电子信息" in names
    assert "特殊钢铁" not in names           # 漳州洞察被 region 过滤


def test_critique_single_dict_body_shape_supported(tmp_path):
    """兼容 run_documents 落库的单条批判 dict 形状（type/subject/...）。"""
    repo = _repo(tmp_path)
    _seed_values(repo)
    repo.insert_doc_insights([
        {"page_id": 3, "source_id": "rep", "kind": "critique", "title": "c",
         "body": json.dumps({"type": "spin", "severity": "high", "subject": "GDP",
                             "claim": "稳中向好", "reality": "r", "what_to_check": "w",
                             "confidence": "high"}, ensure_ascii=False),
         "method": "llm", "region": "泉州市", "period": "2026"},
    ])
    p = analyze_quanzhou(repo)
    assert any(k["type"] == "spin" for k in p["credibility"]["critiques"])
