"""critique.py 测试：C1-C7 规则校验、LLM 批判规范化、双层升级（纯函数不联网）。"""
from app.extract.critique import (
    rule_checks,
    llm_critique,
    merge_checks,
    parse_number,
)


class FakeCritic:
    def __init__(self, resp):
        self.resp = resp
        self.enabled = True

    def complete_json(self, system, user, temperature=None):
        return self.resp


# ---------- parse_number ----------

def test_parse_number_units():
    assert parse_number("592.07") == 592.07
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("8 万人") == 8.0
    assert parse_number("增长4.1%") == 4.1
    assert parse_number("abc") is None


# ---------- rule_checks: C2 三产和 = GDP ----------

def test_c2_consistent_industry_sum():
    vals = {"地区生产总值": [("2025", 1000.0)],
            "第一产业增加值": [("2025", 100.0)],
            "第二产业增加值": [("2025", 400.0)],
            "第三产业增加值": [("2025", 499.0)]}  # 偏差 0.1%
    checks = rule_checks(vals)
    c2 = [c for c in checks if c["id"] == "C2"][0]
    assert c2["verdict"] == "ok"


def test_c2_inconsistent_industry_sum_flags():
    vals = {"地区生产总值": [("2025", 1000.0)],
            "第一产业增加值": [("2025", 100.0)],
            "第二产业增加值": [("2025", 400.0)],
            "第三产业增加值": [("2025", 460.0)]}  # 偏差 4%
    checks = rule_checks(vals)
    c2 = [c for c in checks if c["id"] == "C2"][0]
    assert c2["verdict"] == "flag"
    assert c2["severity"] == "high"


def test_c2_missing_parts_skipped():
    vals = {"地区生产总值": [("2025", 1000.0)]}
    checks = rule_checks(vals)
    assert all(c["id"] != "C2" for c in checks)


# ---------- rule_checks: C3 跨年突变 ----------

def test_c3_sudden_jump_flags():
    vals = {"地区生产总值": [("2024", 100.0), ("2025", 150.0)]}  # +50%
    checks = rule_checks(vals)
    c3 = [c for c in checks if c["id"] == "C3"][0]
    assert c3["verdict"] == "flag"


def test_c3_normal_growth_ok():
    vals = {"地区生产总值": [("2024", 100.0), ("2025", 106.0)]}
    checks = rule_checks(vals)
    c3 = [c for c in checks if c["id"] == "C3"][0]
    assert c3["verdict"] == "ok"


# ---------- rule_checks: C5 收入/GDP 弹性 ----------

def test_c5_elasticity_abnormal():
    # 收入 +12%，GDP +3% → 弹性 4 > 2 flag
    vals = {"地方一般公共预算收入": [("2024", 100.0), ("2025", 112.0)],
            "地区生产总值": [("2024", 1000.0), ("2025", 1030.0)]}
    checks = rule_checks(vals)
    c5 = [c for c in checks if c["id"] == "C5"][0]
    assert c5["verdict"] == "flag"


def test_c5_elasticity_normal():
    vals = {"地方一般公共预算收入": [("2024", 100.0), ("2025", 105.0)],
            "地区生产总值": [("2024", 1000.0), ("2025", 1050.0)]}
    checks = rule_checks(vals)
    c5 = [c for c in checks if c["id"] == "C5"][0]
    assert c5["verdict"] == "ok"


def test_c5_insufficient_data_med():
    vals = {"地方一般公共预算收入": [("2025", 112.0)]}
    checks = rule_checks(vals)
    c5 = [c for c in checks if c["id"] == "C5"][0]
    assert c5["severity"] == "med"


# ---------- llm_critique 规范化 ----------

def test_llm_critique_normalizes():
    fake = FakeCritic({"critiques": [
        {"type": "spin", "severity": "high", "claim": "历史新高",
         "reality": "无同比数据支撑", "what_to_check": "近三年序列",
         "confidence": "med"},
    ]})
    out = llm_critique("原文", fake)
    assert len(out) == 1
    assert out[0]["type"] == "spin"
    assert out[0]["evidence"]  # 无 evidence 时占位


def test_llm_critique_disabled():
    class D:
        enabled = False
    assert llm_critique("t", D()) == []


# ---------- merge_checks 双层升级 ----------

def test_merge_upgrades_double_hit():
    checks = [{"id": "C3", "subject": "GDP", "year": "2025", "verdict": "flag",
               "severity": "med", "note": "突变"}]
    critiques = [{"type": "spin", "severity": "low", "evidence": "e"}]
    merged = merge_checks(checks, critiques)
    assert merged["escalated"] == []
    assert len(merged["checks"]) == 1
    # spin 与 C3 不同主题 → 不升级；同主题需 subject 匹配
    critiques2 = [{"type": "omission", "severity": "low",
                   "subject": "GDP", "evidence": "e"}]
    merged2 = merge_checks(checks, critiques2)
    assert len(merged2["escalated"]) == 1
    assert merged2["escalated"][0]["severity"] == "high"


# ---------- M7a: subject 打通与高置信单层升级 ----------

def test_system_critique_asks_subject():
    from app.extract.critique import SYSTEM_CRITIQUE
    assert "subject" in SYSTEM_CRITIQUE


def test_llm_critique_shape_has_subject():
    fake = FakeCritic({"critiques": [
        {"type": "metric_game", "severity": "high", "subject": "GDP增速",
         "claim": "增长6%", "reality": "名义增速", "what_to_check": "实际增速",
         "confidence": "high", "evidence": "全年增长6%"},
    ]})
    out = llm_critique("原文", fake)
    assert out[0]["subject"] == "GDP增速"


def test_llm_critique_missing_subject_defaults_empty():
    fake = FakeCritic({"critiques": [
        {"type": "spin", "severity": "low", "claim": "历史新高",
         "reality": "r", "what_to_check": "w", "confidence": "low"},
    ]})
    out = llm_critique("原文", fake)
    assert out[0]["subject"] == ""


def test_merge_subject_synonym_upgrades():
    """批判说 'GDP增速'、规则主题 '地区生产总值' → 归一后同主题升级。"""
    checks = [{"id": "C3", "subject": "地区生产总值", "year": "2025",
               "verdict": "flag", "severity": "med", "note": "突变"}]
    critiques = [{"type": "metric_game", "severity": "low",
                  "subject": "GDP增速", "evidence": "e"}]
    merged = merge_checks(checks, critiques)
    assert len(merged["escalated"]) == 1
    assert merged["escalated"][0]["severity"] == "high"


def test_merge_high_conf_single_layer_escalates():
    """批判无 subject 但 confidence=high 且规则 flag → 单层也进升级区（防漏报）。"""
    checks = [{"id": "C6", "subject": "土地财政依赖度", "year": "2025",
               "verdict": "flag", "severity": "high", "note": "依赖 45%"}]
    critiques = [{"type": "omission", "severity": "low", "confidence": "high",
                  "claim": "未披露土地出让下滑", "evidence": "e"}]
    merged = merge_checks(checks, critiques)
    assert len(merged["escalated"]) == 1
    assert merged["escalated"][0]["single_layer"] is True


def test_merge_no_subject_low_conf_no_escalate():
    checks = [{"id": "C3", "subject": "GDP", "year": "2025", "verdict": "flag",
               "severity": "med", "note": "突变"}]
    critiques = [{"type": "spin", "severity": "low", "confidence": "med",
                  "claim": "c", "evidence": "e"}]
    merged = merge_checks(checks, critiques)
    assert merged["escalated"] == []
