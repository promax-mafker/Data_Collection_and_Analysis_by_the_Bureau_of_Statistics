"""kami.py 测试：Kami Parchment HTML 渲染器视觉契约。"""
from app.analysis.kami import KamiRenderer


def _render():
    r = KamiRenderer("泉州经济驱动画像", "经济驱动画像", "2026年9月 · 来源：统计局/财政局")
    r.section("id-sec1", "实际产业结构错配")
    r.para("正文段落测试")
    r.table(["产业", "实际占比%", "增速%"], [["纺织鞋服", "12.3", "5.0"]], align_right=[1, 2])
    r.bullish("↑ 利好")
    r.bearish("↓ 利空")
    r.source("https://x.gov.cn", "统计局", "2026-09")
    r.note_limited("收入中位数地市不公布")
    html = r.doc()
    return html


def test_kami_parchment_colors():
    html = _render()
    assert "#f5f4ed" in html        # 羊皮纸底
    assert "#1f1d18" in html        # 正文
    assert "#1B365D" in html        # 墨蓝
    assert "#ffffff" not in html.replace(" ", "")
    assert "#000000" not in html.replace(" ", "")


def test_kami_fonts():
    html = _render()
    assert "Noto Serif SC" in html
    assert "Crimson Text" in html
    assert "JetBrains Mono" in html


def test_kami_anchors():
    html = _render()
    assert 'id="id-sec1"' in html
    assert 'href="#id-sec1"' in html  # 目录锚点


def test_kami_no_forbidden_visuals():
    html = _render()
    assert "gradient" not in html
    assert "border-radius: 3px" not in html
    # 无大 emoji 作为图标（只允许文本小箭头）
    assert "📊" not in html and "🚀" not in html


def test_kami_bullish_bearish_colors():
    html = _render()
    assert "#2d5016" in html  # 暗绿
    assert "#8b1a1a" in html  # 暗红


def test_kami_table_align_right():
    html = _render()
    assert "text-align: right" in html
    assert "JetBrains Mono" in html


def test_economy_report_renders():
    """economy_report 组装：空库也能渲染（None → — 不报错）。"""
    from app.store.db import init_db
    from app.store.repository import Repository
    from app.analysis.economy_report import render_economy_report
    repo = Repository(init_db(":memory:"))
    html = render_economy_report(repo)
    assert "泉州经济驱动画像" in html
    assert "消费" in html and "债务" in html and "净出口" in html
    assert "#f5f4ed" in html


def test_economy_report_has_decision_tree_section():
    """M8：报告含「方法论体检」决策树裁决节；空库输出缺数据说明不报错。"""
    from app.store.db import init_db
    from app.store.repository import Repository
    from app.analysis.economy_report import render_economy_report
    repo = Repository(init_db(":memory:"))
    html = render_economy_report(repo)
    assert "方法论体检" in html
    assert "缺" in html or "—" in html  # 空库 → 缺数据说明而非空白
