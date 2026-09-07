"""quanzhou 报告渲染测试：七章结构、关键数字、⚠ 审读标记。"""
from app.analysis.report import render_quanzhou_markdown, render_quanzhou_html


def _profile():
    return {
        "region": "泉州市",
        "reference_year": "2025",
        "fiscal": {
            "revenue": 592.07, "expenditure": 880.29, "fund": 292.07, "tax": 500.0,
            "gdp": 14000.0, "revenue_growth": 3.87,
            "self_sufficiency": 67.26, "land_dependence": 33.03,
            "fiscal_intensity": 4.23, "tax_ratio": 3.57, "unit": "亿元"},
        "industry": [
            {"industry": "纺织鞋服", "plan_role": "支柱", "scale_or_target": "万亿集群",
             "growth_claim": None, "policy_instruments": ["技改补助"],
             "evidence": "原文1"},
            {"industry": "电子信息", "plan_role": "新兴", "scale_or_target": None,
             "growth_claim": None, "policy_instruments": [], "evidence": "原文2"},
        ],
        "market": {"total_2025": 170, "prev_total": 182, "county_counts": {"晋江市": 50, "石狮市": 30},
                   "hhi": 0.15, "top_counties": [("晋江市", 50), ("石狮市", 30)]},
        "employment": {"new_jobs": 9.49, "density_permille": 10.66, "population": 890.0},
        "plan": {"period": "十五五", "gdp_growth_target": 5.0, "revenue_growth_target": 2.5,
                 "jobs_target": 8.0, "evidence": ["原文3"]},
        "credibility": {
            "checks": [
                {"id": "C5", "subject": "预算收入增速弹性", "year": "2025",
                 "verdict": "flag", "severity": "med", "note": "弹性 0.5 临界"},
                {"id": "C2", "subject": "三次产业和", "year": "2025",
                 "verdict": "ok", "severity": "low", "note": "偏差 0.1%"},
            ],
            "critiques": [
                {"type": "spin", "severity": "med", "claim": "历史新高",
                 "reality": "无同比数据支撑", "what_to_check": "近三年序列",
                 "confidence": "med", "evidence": "原文摘录"},
            ],
            "escalated": [],
        },
    }


def test_markdown_has_seven_sections():
    md = render_quanzhou_markdown(_profile())
    for key in ("财政税收结构", "支柱产业图谱", "核心机构与市场主体",
                "就业岗位分布", "五年规划路径", "数据可信度审读"):
        assert key in md, f"缺章节 {key}"


def test_markdown_contains_key_numbers():
    md = render_quanzhou_markdown(_profile())
    assert "592.07" in md
    assert "880.29" in md
    assert "170" in md
    assert "9.49" in md
    assert "纺织鞋服" in md
    assert "晋江市" in md


def test_markdown_shows_flag_marks():
    md = render_quanzhou_markdown(_profile())
    assert "⚠" in md
    assert "C5" in md
    assert "历史新高" in md  # LLM 批判 evidence 展示


def test_html_renders():
    html = render_quanzhou_html(_profile())
    assert "<h1>" in html
    assert "泉州市" in html
    assert "592.07" in html
    assert "⚠" in html


def test_empty_profile_graceful():
    empty = {"region": "泉州市", "reference_year": None, "fiscal": {},
             "industry": [], "market": {}, "employment": {},
             "plan": {}, "credibility": {"checks": [], "critiques": [], "escalated": []}}
    md = render_quanzhou_markdown(empty)
    assert "暂无数据" in md or "—" in md
