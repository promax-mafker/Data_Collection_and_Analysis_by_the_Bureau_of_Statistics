"""地方债务画像测试（M9e 债务专题）。

数据源：`econ_series` 的 `debt_balance` / `debt_limit`（泉州 2021-2024）
＋ `data_values` 的 GDP/财政（同年口径，沿用 A10 纪律）。
"""
from app.analysis.debt import debt_profile
from app.schemas import DataValue
from app.store.db import init_db
from app.store.repository import Repository


def _seed(repo):
    repo.replace_econ_series("debt_2023", [
        {"indicator": "debt_balance", "year": "2023", "value": "2400", "unit": "亿元"},
        {"indicator": "debt_limit", "year": "2023", "value": "2600", "unit": "亿元"},
    ])
    repo.replace_econ_series("debt_2024", [
        {"indicator": "debt_balance", "year": "2024", "value": "2661.16", "unit": "亿元"},
        {"indicator": "debt_limit", "year": "2024", "value": "2753.80", "unit": "亿元"},
    ])
    bid = repo.upsert_bureau(__import__("app.schemas", fromlist=["Bureau"]).Bureau(
        level="city", name="泉州市统计局", url="http://qz", region="泉州市"))
    repo.insert_values([
        DataValue(page_id=None, bureau_id=bid, region="泉州市", year="2023",
                  indicator_name="地区生产总值", value="12172.33", unit="亿元",
                  category="综合", raw_text="r", method="rule"),
        DataValue(page_id=None, bureau_id=bid, region="泉州市", year="2024",
                  indicator_name="地区生产总值", value="13778.34", unit="亿元",
                  category="综合", raw_text="r", method="rule"),
    ])


def test_debt_series_parsed_from_econ_series(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _seed(repo)
    p = debt_profile(repo, "泉州市")
    assert p["balance"] == {"2023": 2400.0, "2024": 2661.16}
    assert p["limit"] == {"2023": 2600.0, "2024": 2753.80}
    assert p["years"] == ["2023", "2024"]


def test_limit_utilization_flags_above_90pct(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _seed(repo)
    m = {x["key"]: x for x in debt_profile(repo, "泉州市")["metrics"]}
    assert abs(m["limit_utilization"]["value"] - 96.63) < 0.1
    assert m["limit_utilization"]["verdict"] == "flag"
    assert m["limit_utilization"]["year"] == "2024"


def test_debt_to_gdp_uses_same_year(tmp_path):
    """债务/GDP 必须同年（A10 纪律）—— 用 2023 的 GDP 配 2024 的债务会低估风险。"""
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _seed(repo)
    m = {x["key"]: x for x in debt_profile(repo, "泉州市")["metrics"]}
    assert m["debt_to_gdp"]["year"] == "2024"
    assert abs(m["debt_to_gdp"]["value"] - 19.31) < 0.1


def test_new_debt_and_headroom(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _seed(repo)
    m = {x["key"]: x for x in debt_profile(repo, "泉州市")["metrics"]}
    assert abs(m["new_debt"]["value"] - 261.16) < 0.02      # 2661.16 - 2400
    assert abs(m["headroom"]["value"] - 92.64) < 0.02       # 2753.80 - 2661.16
    assert m["headroom"]["year"] == "2024"


def test_missing_gdp_yields_verify_not_wrong_number(tmp_path):
    """缺同年 GDP 时不得拿别的年份凑数（错 > 缺），须标 verify/na 并写明原因。"""
    repo = Repository(init_db(str(tmp_path / "t.db")))
    repo.replace_econ_series("debt_x", [
        {"indicator": "debt_balance", "year": "2024", "value": "100", "unit": "亿元"},
        {"indicator": "debt_limit", "year": "2024", "value": "200", "unit": "亿元"},
    ])
    p = debt_profile(repo, "泉州市")
    m = {x["key"]: x for x in p["metrics"]}
    assert m["debt_to_gdp"]["verdict"] in ("verify", "na")
    assert m["debt_to_gdp"]["value"] is None
    assert "GDP" in m["debt_to_gdp"]["note"]


def test_summary_and_missing_reported(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _seed(repo)
    p = debt_profile(repo, "泉州市")
    assert set(p["summary"]) >= {"ok", "flag", "verify", "na"}
    assert sum(p["summary"].values()) == len(p["metrics"])
    assert isinstance(p["missing"], list)


def test_series_outlier_is_flagged_and_blocks_new_debt(tmp_path):
    """序列离群点必须标 verify，且不得据此算「新增债务」。

    实测（真实库）：2022 余额 = **517.7**，而 2021=1865.66、2023=2343.54 ——
    明显离群（疑误抽子项，如「新增限额」）。若不拦，2023 新增债务会算成
    2343.54-517.7=1825.84 这种错值，并进一步污染趋势判断。
    """
    repo = Repository(init_db(str(tmp_path / "t.db")))
    repo.replace_econ_series("debt_bad", [
        {"indicator": "debt_balance", "year": "2021", "value": "1865.66", "unit": "亿元"},
        {"indicator": "debt_balance", "year": "2022", "value": "517.7", "unit": "亿元"},
        {"indicator": "debt_balance", "year": "2023", "value": "2343.54", "unit": "亿元"},
        {"indicator": "debt_limit", "year": "2023", "value": "2449.12", "unit": "亿元"},
    ])
    m = {x["key"]: x for x in debt_profile(repo, "泉州市")["metrics"]}
    assert m["series_outlier"]["verdict"] == "verify"
    assert "2022" in m["series_outlier"]["note"]
    assert m["new_debt"]["verdict"] == "verify", "依赖离群点时必须拒绝下结论"
    assert m["new_debt"]["value"] is None


def test_debt_nodes_cover_four_new_questions():
    """决策树债务节点由 1 个（T3-4）扩到 5 个（M9e 设计）。"""
    from app.analysis.decision_tree import debt_nodes
    nodes = debt_nodes({"years": ["2024"], "balance": {"2024": 2661.16},
                        "limit": {"2024": 2753.80}, "metrics": [], "missing": []})
    ids = [n["id"] for n in nodes]
    assert ids == ["T3-6", "T3-7", "T3-8", "T3-9"]
    assert all(n["layer"] == "T3" for n in nodes)


def test_debt_nodes_na_with_explicit_reason_when_data_missing():
    """缺数据必须 na 并写明**缺什么**，不得留空备注（否则报告里看不出为什么没结论）。"""
    from app.analysis.decision_tree import debt_nodes
    nodes = debt_nodes({"years": [], "balance": {}, "limit": {}, "metrics": [], "missing": []})
    assert all(n["verdict"] == "na" for n in nodes)
    assert all(n["note"] for n in nodes), "每个 na 节点都必须说明缺失原因"
    assert any("CELMA" in n["note"] or "分项" in n["note"] for n in nodes)


def test_debt_nodes_compute_debt_ratio_when_revenue_available():
    """给出综合财力时应算出债务率并按阈值裁决。"""
    from app.analysis.decision_tree import debt_nodes
    prof = {"years": ["2024"], "balance": {"2024": 2661.16}, "limit": {"2024": 2753.80},
            "metrics": [], "missing": [],
            "own_revenue": {"2024": 592.07 + 292.07}}   # 一般公共预算收入 + 政府性基金收入
    n = {x["id"]: x for x in debt_nodes(prof)}
    assert n["T3-6"]["verdict"] in ("flag", "verify", "ok")
    assert n["T3-6"]["evidence"]


def test_debt_nodes_land_reliance_linkage():
    """土地依赖高 × 债务空间见底 → 联动风险须 flag。"""
    from app.analysis.decision_tree import debt_nodes
    prof = {"years": ["2024"], "balance": {"2024": 2661.16}, "limit": {"2024": 2753.80},
            "metrics": [], "missing": []}
    n = {x["id"]: x for x in debt_nodes(prof, land_reliance=33.03)}
    assert n["T3-9"]["verdict"] == "flag"
    n2 = {x["id"]: x for x in debt_nodes(prof, land_reliance=5.0)}
    assert n2["T3-9"]["verdict"] in ("ok", "info")


def test_find_ambiguous_econ_series_flags_caliber_collision(tmp_path):
    """`econ_series` 也必须能被歧义探测覆盖。

    实测缺口：债务序列存在**口径混装** —— 同一 (indicator, year) 出现两个值，
    例如 2022 余额既有执行口径 517.70，又有年初预算口径 454.33（其限额 2112.73
    恰为 2021 年限额）。原先 `find_ambiguous_groups` 只扫 `data_values`，
    这类冲突**完全隐形**，会静默污染债务分析。
    """
    repo = Repository(init_db(str(tmp_path / "t.db")))
    repo.replace_econ_series("exec", [{"indicator": "debt_balance", "year": "2022",
                                       "value": "517.70", "unit": "亿元"}])
    repo.replace_econ_series("budget", [{"indicator": "debt_balance", "year": "2022",
                                         "value": "454.33", "unit": "亿元"}])
    g = repo.find_ambiguous_econ_series()
    assert len(g) == 1
    assert g[0]["indicator"] == "debt_balance" and g[0]["year"] == "2022"
    assert set(g[0]["values"]) == {"517.70", "454.33"}
    assert set(g[0]["sources"]) == {"exec", "budget"}


def test_find_ambiguous_econ_series_ignores_identical_values(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    for src in ("a", "b"):
        repo.replace_econ_series(src, [{"indicator": "debt_limit", "year": "2022",
                                        "value": "2380.47", "unit": "亿元"}])
    assert repo.find_ambiguous_econ_series() == []


def test_no_debt_data_returns_na_not_crash(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    p = debt_profile(repo, "泉州市")
    assert p["balance"] == {} and p["years"] == []
    assert all(m["verdict"] == "na" for m in p["metrics"])
    assert p["missing"]
