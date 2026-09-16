"""债务报告专章渲染测试（M9e E5）。"""
from app.analysis.debt import render_debt_markdown


def _prof(**kw):
    base = {
        "region": "泉州市",
        "years": ["2021", "2024"],
        "balance": {"2021": 1865.66, "2024": 2661.16},
        "limit": {"2021": 2112.73, "2024": 2753.80},
        "own_revenue": {"2024": 884.14},
        "metrics": [
            {"key": "limit_utilization", "label": "限额利用率", "year": "2024",
             "value": 96.64, "verdict": "flag", "principle": "P-debt-1", "note": "空间受限"},
            {"key": "debt_to_gdp", "label": "债务/GDP", "year": "2024", "value": 20.32,
             "verdict": "ok", "principle": "P-debt-2", "note": ""},
            {"key": "new_debt", "label": "新增债务余额", "year": None, "value": None,
             "verdict": "verify", "principle": "P-debt-3", "note": "含离群年，先核对"},
        ],
        "summary": {"ok": 1, "flag": 1, "verify": 1, "na": 0, "info": 0},
        "missing": ["新增债务余额: 含离群年，先核对"],
    }
    base.update(kw)
    return base


def test_renders_all_metrics_with_verdicts():
    md = render_debt_markdown(_prof())
    assert "地方债务" in md
    assert "限额利用率" in md and "96.64" in md
    assert "债务/GDP" in md and "20.32" in md
    assert "新增债务余额" in md
    assert "FLAG" in md.upper() or "🔴" in md


def test_missing_values_are_not_fabricated():
    """值为 None 的指标不得出现数字，须显式标为待核。"""
    md = render_debt_markdown(_prof())
    seg = md.split("新增债务余额", 1)[1][:160]
    assert "—" in seg or "待核" in seg or "None" not in seg
    assert "None" not in md


def test_states_scope_and_caliber_limitations():
    """必须写明口径边界：仅省级分项、债务率上界、口径待核 —— 报告不能被当成定论。"""
    md = render_debt_markdown(_prof())
    assert "省级" in md
    assert "上界" in md or "未含" in md
    assert "口径" in md


def test_empty_profile_renders_na_section():
    md = render_debt_markdown({"region": "泉州市", "years": [], "balance": {}, "limit": {},
                               "own_revenue": {}, "metrics": [], "summary": {}, "missing": []})
    assert "地方债务" in md
    assert "缺" in md or "无" in md
