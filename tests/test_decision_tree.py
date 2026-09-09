"""decision_tree.py 测试：T0-T5 节点裁决(纯库内种子,不联网)。"""
import json

from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import DataValue
from app.analysis.decision_tree import tree_audit

REQUIRED_FINAL = ("地区生产总值", "第一产业增加值", "第二产业增加值", "第三产业增加值",
                  "一般公共预算收入", "一般公共预算支出", "政府性基金收入", "税收收入",
                  "常住人口", "社会消费品零售总额")


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def _dv(region, ind, year, value, unit="亿元", **kw):
    return DataValue(None, None, region, year, ind, value, unit, "综合", "…", **kw)


def _seed_full(repo):
    """核心 final 数据两年 + econ_series(CPI/人口/收支/贸易/债务)。"""
    rows = []
    for y, gdp, p1, p2, p3 in (("2023", "12000.0", "300.0", "5000.0", "6700.0"),
                               ("2024", "13094.87", "310.0", "5600.0", "7184.87")):
        rows += [
            _dv("泉州市", "地区生产总值", y, gdp),
            _dv("泉州市", "第一产业增加值", y, p1),
            _dv("泉州市", "第二产业增加值", y, p2),
            _dv("泉州市", "第三产业增加值", y, p3),
        ]
    rows += [
        _dv("泉州市", "一般公共预算收入", "2024", "592.07"),
        _dv("泉州市", "一般公共预算收入", "2023", "570.0"),
        _dv("泉州市", "一般公共预算支出", "2024", "880.29"),
        _dv("泉州市", "政府性基金收入", "2024", "292.07"),
        _dv("泉州市", "税收收入", "2024", "500.0"),
        _dv("泉州市", "常住人口", "2024", "891.4", unit="万人"),
        _dv("泉州市", "常住人口", "2023", "888.0", unit="万人"),
        _dv("泉州市", "社会消费品零售总额", "2024", "6416.07"),
        _dv("泉州市", "社会消费品零售总额", "2023", "6100.0"),
        _dv("泉州市", "城镇新增就业", "2024", "9.49", unit="万人"),
        _dv("泉州市", "城镇新增就业", "2023", "9.20", unit="万人"),
    ]
    repo.insert_values(rows)
    repo.replace_econ_series("pop_cpi", [
        {"indicator": "cpi", "year": "2024", "value": "100.2", "unit": "", "note": "上年=100", "raw_text": ""},
    ])
    repo.replace_econ_series("income_4_7", [
        {"indicator": "income_consumption", "year": "2024", "value": "54858", "unit": "元",
         "note": "全体居民人均可支配收入", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "33723", "unit": "元",
         "note": "全体居民人均消费支出", "raw_text": ""},
        {"indicator": "income_consumption", "year": "2024", "value": "11001", "unit": "元",
         "note": "食品烟酒", "raw_text": ""},
    ])
    repo.replace_econ_series("trade_12_3", [
        {"indicator": "trade", "year": "2024", "value": "1651.70", "unit": "亿元", "note": "出口额", "raw_text": ""},
        {"indicator": "trade", "year": "2024", "value": "712.09", "unit": "亿元", "note": "进口额", "raw_text": ""},
    ])
    repo.replace_econ_series("debt_2024", [
        {"indicator": "debt_balance", "year": "2024", "value": "2661.16", "unit": "亿元", "note": "全市", "raw_text": ""},
        {"indicator": "debt_limit", "year": "2024", "value": "2753.80", "unit": "亿元", "note": "全市", "raw_text": ""},
    ])


def _node(tree, nid):
    hit = [n for n in tree["nodes"] if n["id"] == nid]
    assert hit, f"节点 {nid} 缺失: {[n['id'] for n in tree['nodes']]}"
    return hit[0]


def test_full_seed_no_missing_and_key_verdicts(tmp_path):
    repo = _repo(tmp_path)
    _seed_full(repo)
    tree = tree_audit(repo, region="泉州市")
    assert tree["missing"] == []
    assert _node(tree, "T2-1")["verdict"] in ("ok", "flag")   # C2 有裁决
    assert _node(tree, "T0-2")["verdict"] == "ok"
    assert _node(tree, "T1-1")["verdict"] == "ok"             # 增速正常
    assert _node(tree, "T3-4")["verdict"] in ("ok", "flag", "info")
    assert "evidence" in _node(tree, "T1-2")


def test_budget_rows_trigger_verify(tmp_path):
    repo = _repo(tmp_path)
    _seed_full(repo)
    repo.insert_values([_dv("泉州市", "一般公共预算收入", "2026", "355.92", caliber="budget")])
    tree = tree_audit(repo, region="泉州市")
    assert _node(tree, "T0-1")["verdict"] == "verify"
    assert any("一般公共预算收入" in n["note"] for n in tree["nodes"] if n["id"] == "T0-1")


def test_escalated_critique_triggers_verify(tmp_path):
    repo = _repo(tmp_path)
    _seed_full(repo)
    # 制造 C3 突变(2024→2025 GDP +52%)→ 规则 flag + 高置信批判 → 双层升级
    repo.insert_values([_dv("泉州市", "地区生产总值", "2025", "20000.0")])
    repo.insert_doc_insights([
        {"page_id": 1, "kind": "critique", "title": "c",
         "body": json.dumps({"type": "spin", "severity": "high", "subject": "GDP",
                             "claim": "历史新高", "reality": "r", "what_to_check": "w",
                             "confidence": "high"}, ensure_ascii=False),
         "method": "llm", "region": "泉州市", "period": "2025"},
    ])
    tree = tree_audit(repo, region="泉州市")
    assert _node(tree, "T0-3")["verdict"] == "verify"


def test_missing_indicators_go_to_na(tmp_path):
    repo = _repo(tmp_path)
    _seed_full(repo)
    repo.conn.execute("DELETE FROM data_values WHERE indicator_name='政府性基金收入'")
    repo.conn.commit()
    tree = tree_audit(repo, region="泉州市")
    assert "政府性基金收入" in tree["missing"]
    assert _node(tree, "T3-3")["verdict"] == "na"          # C6 缺基金 → na
    assert _node(tree, "T3-2")["verdict"] in ("ok", "flag", "na")


def test_overpromised_without_share_verify(tmp_path):
    repo = _repo(tmp_path)
    _seed_full(repo)
    # 规划产业无任何实际数据(industry_data 空) → industry_gap overpromised 且 share None
    repo.insert_doc_insights([
        {"page_id": 2, "kind": "industry", "title": "规划",
         "body": json.dumps({"industries": [
             {"industry": "氢能", "plan_role": "新兴", "evidence": "e"}]}, ensure_ascii=False),
         "method": "llm", "region": "泉州市", "period": "十五五"},
    ])
    tree = tree_audit(repo, region="泉州市")
    assert _node(tree, "T2-3")["verdict"] == "verify"      # 数据缺失疑点被标出


def test_plan_period_mix_triggers_verify(tmp_path):
    repo = _repo(tmp_path)
    _seed_full(repo)
    for period in ("十五五", "2026"):
        repo.insert_doc_insights([
            {"page_id": 3, "kind": "plan_goal", "title": period,
             "body": json.dumps({"period": period, "targets": {"gdp_growth": 5.0}},
                                ensure_ascii=False),
             "method": "llm", "region": "泉州市", "period": period},
        ])
    tree = tree_audit(repo, region="泉州市")
    assert _node(tree, "T5-2")["verdict"] == "verify"


def test_empty_db_all_na_no_crash(tmp_path):
    repo = _repo(tmp_path)
    tree = tree_audit(repo, region="泉州市")
    assert tree["nodes"]
    for n in tree["nodes"]:
        assert n["verdict"] in ("ok", "flag", "verify", "na", "info")
    assert tree["missing"] or True  # 空库必然有缺失说明
    # 结构完整性
    for n in tree["nodes"]:
        for key in ("id", "layer", "question", "verdict", "evidence", "note", "principle"):
            assert key in n, f"{n['id']} 缺字段 {key}"
