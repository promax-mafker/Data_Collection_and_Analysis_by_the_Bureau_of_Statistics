from app.analysis.core import analyze, fmt, parse_num
from app.analysis.report import region_columns, render_html, render_markdown
from app.schemas import DataValue
from app.store.db import init_db
from app.store.repository import Repository


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def _put(repo, region, year, indicator, value, unit="亿元", category="综合"):
    repo.insert_values([DataValue(page_id=None, bureau_id=None, region=region, year=year,
                                  indicator_name=indicator, value=value, unit=unit,
                                  category=category, raw_text=f"{indicator}{value}{unit}")])


def test_parse_num_and_fmt():
    assert parse_num("5,000.50") == 5000.5
    assert parse_num("增长5.5%") == 5.5
    assert parse_num("abc") is None
    assert fmt(143623.0) == "143623"
    assert fmt(53162.36) == "53162.36"


def test_analyze_matrix_ranking(tmp_path):
    repo = _repo(tmp_path)
    _put(repo, "福建省", "2025", "地区生产总值", "143623")
    _put(repo, "福州市", "2025", "地区生产总值", "15112.32")
    _put(repo, "泉州市", "2025", "地区生产总值", "13070.3")
    _put(repo, "福建省", "2025", "第一产业增加值", "3354.37")
    _put(repo, "福建省", "2025", "第二产业增加值", "25497.34")
    _put(repo, "福建省", "2025", "第三产业增加值", "31347.74")
    _put(repo, "福建省", "2024", "地区生产总值", "134000")

    a = analyze(repo)
    assert a["reference_year"] == "2025"
    gdp = a["table"]["地区生产总值"]["regions"]
    assert gdp["福建省"] == 143623.0
    assert gdp["泉州市"] == 13070.3

    # region 列：福建省前置，市按 GDP 降序
    cols = region_columns(a)
    assert cols[0] == "福建省"
    assert cols.index("福州市") < cols.index("泉州市")

    # 名义增速（福建 2025 vs 2024）
    g = a["growth"]["福建省"]["地区生产总值"]
    assert abs(g["pct"] - (143623 - 134000) / 134000 * 100) < 1e-6

    # 三次产业结构
    s = a["structure"]["福建省"]
    assert abs(s["第一产业增加值"] - 3354.37 / 143623 * 100) < 1e-6
    assert abs(s["第二产业增加值"] + s["第一产业增加值"] + s["第三产业增加值"]
               - (3354.37 + 25497.34 + 31347.74) / 143623 * 100) < 1e-6


def test_reports_render(tmp_path):
    repo = _repo(tmp_path)
    _put(repo, "福建省", "2025", "地区生产总值", "143623", unit="亿元")
    _put(repo, "福州市", "2025", "地区生产总值", "15112.32")
    a = analyze(repo)
    md = render_markdown(a)
    html = render_html(a)
    assert "地区生产总值" in md
    assert "名义增速" in md
    assert "<table>" in html
    assert "143623" in md


def test_consistency_checks(tmp_path):
    repo = _repo(tmp_path)
    # 自洽：三产和 = GDP
    _put(repo, "福建省", "2025", "地区生产总值", "1000")
    _put(repo, "福建省", "2025", "第一产业增加值", "100")
    _put(repo, "福建省", "2025", "第二产业增加值", "400")
    _put(repo, "福建省", "2025", "第三产业增加值", "500")
    # 不自洽：福州市三产和 ≠ GDP（模拟归属噪声）
    _put(repo, "福州市", "2025", "地区生产总值", "800")
    _put(repo, "福州市", "2025", "第一产业增加值", "100")
    _put(repo, "福州市", "2025", "第二产业增加值", "100")
    _put(repo, "福州市", "2025", "第三产业增加值", "500")

    a = analyze(repo)
    cons = a["consistency"]
    fj = cons["福建省"]
    assert abs(fj["industry_sum_dev_pct"]) < 0.01
    assert abs(fj["share_total"] - 100.0) < 0.01
    fz = cons["福州市"]
    assert fz["industry_sum_dev_pct"] != 0  # 700 vs 800 → 偏差明显
    md = render_markdown(a)
    assert "自洽性校验" in md
