"""宽容查询层测试：地区前缀/后缀补全、年份容错、指标别名与歧义提示。"""
from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import DataValue

def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))

def _seed(repo):
    """省 + 两市的多年数据（模拟真实库）。"""
    rows = [
        DataValue(None, None, "福建省", "2025", "地区生产总值", "60199.72", "亿元", "综合", "…"),
        DataValue(None, None, "莆田市", "2025", "第一产业增加值", "158.35", "亿元", "综合", "第一产业增加值 158.35 亿元"),
        DataValue(None, None, "莆田市", "2024", "第一产业增加值", "150.2", "亿元", "综合", "…"),
        DataValue(None, None, "福州市", "2025", "第一产业增加值", "600.1", "亿元", "综合", "…"),
        DataValue(None, None, "厦门市", "2024", "第二产业增加值", "1800.0", "亿元", "综合", "…"),
    ]
    assert repo.insert_values(rows) == len(rows)

def _lax(repo, region=None, indicator=None, year=None):
    return repo.query_lax(region_q=region, indicator_q=indicator, year_q=year)

# ---------- 地区宽容 ----------

def test_region_with_province_prefix(tmp_path):
    """「福建省莆田市」应剥掉上级前缀命中「莆田市」。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, region="福建省莆田市")
    assert out["warnings"] == []
    assert {r["region"] for r in out["rows"]} == {"莆田市"}

def test_region_suffix_completion(tmp_path):
    """「莆田」自动补全为「莆田市」。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, region="莆田")
    assert out["warnings"] == []
    assert {r["region"] for r in out["rows"]} == {"莆田市"}

def test_region_exact(tmp_path):
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, region="福建省")
    assert {r["region"] for r in out["rows"]} == {"福建省"}

def test_region_unmatched_warns_empty(tmp_path):
    """未识别的地区：明确警告且返回空，而不是静默返回全量。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, region="泉州府")
    assert out["rows"] == []
    assert any("泉州府" in w for w in out["warnings"])

# ---------- 年份宽容 ----------

def test_year_with_unit_suffix(tmp_path):
    """「2025年」应命中 2025。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, year="2025年")
    assert out["warnings"] == []
    assert {r["year"] for r in out["rows"]} == {"2025"}

def test_year_unparseable_warns(tmp_path):
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, year="最新")
    assert out["rows"] == []
    assert out["warnings"]

# ---------- 指标宽容 ----------

def test_indicator_prefix_completion(tmp_path):
    """「第一产业」补全为「第一产业增加值」。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, indicator="第一产业")
    assert out["warnings"] == []
    assert {r["indicator_name"] for r in out["rows"]} == {"第一产业增加值"}

def test_indicator_alias_gdp(tmp_path):
    """GDP 别名 → 地区生产总值。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, indicator="GDP")
    assert out["warnings"] == []
    assert {r["indicator_name"] for r in out["rows"]} == {"地区生产总值"}

def test_indicator_ambiguous_warns(tmp_path):
    """「增加值」命中多个指标：警告且不返回歧义结果。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, indicator="增加值")
    assert out["rows"] == []
    assert any("增加值" in w for w in out["warnings"])

# ---------- 组合 ----------

def test_combined_natural_query(tmp_path):
    """用户自然写法「福建省莆田市 / 第一产业 / 2025年」一次命中。"""
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo, region="福建省莆田市", indicator="第一产业", year="2025年")
    assert out["warnings"] == []
    assert len(out["rows"]) == 1
    assert out["rows"][0]["value"] == "158.35"

def test_no_filters_returns_all(tmp_path):
    repo = _repo(tmp_path); _seed(repo)
    out = _lax(repo)
    assert out["warnings"] == []
    assert len(out["rows"]) == 5
