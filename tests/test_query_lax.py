"""宽容查询层测试：地区前缀/后缀补全、年份容错、指标别名与歧义提示。"""
from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import DataValue

def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))

def _seed(repo):
    """省 + 两市的多指标数据（模拟真实库）。"""
    rows = [
        DataValue(None, None, "福建省", "2025", "地区生产总值", "60199.72", "亿元", "综合", "…"),
        DataValue(None, None, "福建省", "2025", "第一产业增加值", "3000.5", "亿元", "综合", "…"),
        DataValue(None, None, "福建省", "2024", "地区生产总值", "58000.0", "亿元", "综合", "…"),
        DataValue(None, None, "莆田市", "2025", "第一产业增加值", "158.35", "亿元", "综合", "第一产业增加值 158.35 亿元"),
        DataValue(None, None, "莆田市", "2024", "第一产业增加值", "150.2", "亿元", "综合", "…"),
        DataValue(None, None, "福州市", "2025", "第一产业增加值", "600.1", "亿元", "综合", "…"),
        DataValue(None, None, "厦门市", "2025", "第一产业增加值", "50.5", "亿元", "综合", "…"),
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
    assert len(out["rows"]) == 8

# ---------- 整句自然语言查询 ----------

def test_text_whole_sentence(tmp_path):
    """「福建省莆田市2025年第一产业增加值」一句话命中。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福建省莆田市2025年第一产业增加值")
    assert out["warnings"] == []
    rows = out["rows"]
    assert len(rows) == 1
    assert rows[0]["region"] == "莆田市"
    assert rows[0]["year"] == "2025"
    assert rows[0]["indicator_name"] == "第一产业增加值"
    assert rows[0]["value"] == "158.35"

def test_text_mixed_order_and_suffix(tmp_path):
    """打乱顺序、省略后缀的整句也应命中。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("2025年莆田市第一产业增加值是多少")
    assert out["warnings"] == []
    assert {r["value"] for r in out["rows"]} == {"158.35"}

def test_text_province_and_city_parallel(tmp_path):
    """「福建省和莆田市…」并列：省与市都返回。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福建省和莆田市2025年第一产业增加值")
    assert out["warnings"] == []
    assert {r["region"] for r in out["rows"]} == {"福建省", "莆田市"}

def test_text_two_regions_parallel(tmp_path):
    """「福州和厦门2025第一产业」→ 两市都返回（后缀补全）。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福州和厦门2025年第一产业")
    assert out["warnings"] == []
    assert {r["region"] for r in out["rows"]} == {"福州市", "厦门市"}

def test_text_region_fuzzy_inside(tmp_path):
    """「福州市和厦门市」这类多个地区的表述应分别解析。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福州市和厦门市2025年第一产业")
    assert {r["region"] for r in out["rows"]} == {"福州市", "厦门市"}

def test_text_unknown_region_warns(tmp_path):
    """句中含「市」却无法识别（不存在市）→ 空 + 警告。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("不存在市2025年第一产业增加值")
    assert out["rows"] == []
    assert any("不存在市" in w or "地区" in w for w in out["warnings"])

def test_text_no_region_returns_all(tmp_path):
    """句中无地区词（如只问指标+年份）→ 不限地区返回该指标。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("2025年第一产业增加值")
    assert out["warnings"] == []
    assert {r["region"] for r in out["rows"]} == {"福建省", "莆田市", "福州市", "厦门市"}

def test_text_renjun_gdp_not_confused(tmp_path):
    """「人均地区生产总值」不能误配成「地区生产总值」。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福建省2025年人均地区生产总值")
    assert out["rows"] == []
    assert any("人均" in w or "指标" in w for w in out["warnings"])

def test_text_gdp_alias(tmp_path):
    """GDP 别名命中地区生产总值。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福建省2025年GDP")
    assert out["rows"]
    assert {r["indicator_name"] for r in out["rows"]} == {"地区生产总值"}
    assert {r["region"] for r in out["rows"]} == {"福建省"}

def test_text_multi_years_takes_last(tmp_path):
    """句中多个年份 → 取最后出现 + 警告。"""
    repo = _repo(tmp_path); _seed(repo)
    out = repo.query_text("福建省2024年2025年地区生产总值")
    assert out["rows"]
    assert {r["year"] for r in out["rows"]} == {"2025"}
    assert any("2024" in w for w in out["warnings"])
