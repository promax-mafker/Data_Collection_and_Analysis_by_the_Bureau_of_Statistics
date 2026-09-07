"""泉州经济纵深画像 · 数理分析（M5 §6）。

输入：data_values + enterprises + doc_insights → 画像 dict。
全部数值带指标名与年份，缺失返回 None 不编造。
"""
import json
import re

NUM_RE = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = NUM_RE.search(str(v).replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _value(repo, indicator, year=None, region=None):
    """返回 (数值, unit)；缺失返回 (None, '')。region 给定则限定地域。"""
    rows = repo.query_data(indicator=indicator, region=region)
    if year:
        rows = [r for r in rows if r.get("year") == year]
    if not rows:
        return None, ""
    v = _num(rows[0].get("value"))
    return v, rows[0].get("unit", "")


def _year_pair(repo, indicator, region=None):
    """指标按年份升序 → [(year, float)]。"""
    out = []
    for r in repo.query_data(indicator=indicator, region=region):
        v = _num(r.get("value"))
        if v is not None and r.get("year"):
            out.append((r["year"], v))
    out.sort()
    return out


def hhi(counts: dict) -> float:
    """赫芬达尔指数：sum((n_i/N)^2)，0-1。"""
    total = sum(counts.values())
    if not total:
        return 0.0
    return sum((n / total) ** 2 for n in counts.values())


def analyze_quanzhou(repo) -> dict:
    """主分析。region 固定泉州（M5 样板）。"""
    region = "泉州市"
    values_rows = repo.query_data(region=region)
    years = sorted({r.get("year") for r in values_rows if r.get("year")})
    # 参考年优先取 GDP 最新年度（完整年度锚点），避免半年预算执行等子年度数据抬高基准
    gdp_years = sorted({r.get("year") for r in values_rows
                        if r.get("indicator_name") == "地区生产总值" and r.get("year")})
    ref_year = gdp_years[-1] if gdp_years else (years[-1] if years else None)

    # ---------- 财政维度 ----------
    revenue, rev_unit = _value(repo, "地方一般公共预算收入", ref_year, region)
    if revenue is None:
        revenue, rev_unit = _value(repo, "一般公共预算收入", ref_year, region)
    expenditure, _ = _value(repo, "一般公共预算支出", ref_year, region)
    fund, _ = _value(repo, "政府性基金收入", ref_year, region)
    tax, _ = _value(repo, "税收收入", ref_year, region)
    gdp, _ = _value(repo, "地区生产总值", ref_year, region)

    rev_pairs = _year_pair(repo, "地方一般公共预算收入", region)
    gdp_pairs = _year_pair(repo, "地区生产总值", region)
    rev_growth = None
    if len(rev_pairs) >= 2:
        (_, v1), (_, v2) = rev_pairs[-2], rev_pairs[-1]
        if v1:
            rev_growth = (v2 - v1) / v1 * 100.0

    fiscal = {
        "revenue": revenue, "expenditure": expenditure, "fund": fund, "tax": tax,
        "gdp": gdp, "revenue_growth": rev_growth,
        "self_sufficiency": (revenue / expenditure * 100.0)
        if revenue is not None and expenditure else None,
        "land_dependence": (fund / (revenue + fund) * 100.0)
        if fund is not None and revenue is not None and (revenue + fund) else None,
        "fiscal_intensity": (revenue / gdp * 100.0)
        if revenue is not None and gdp else None,
        "tax_ratio": (tax / gdp * 100.0) if tax is not None and gdp else None,
        "unit": rev_unit,
    }

    # ---------- 产业(来自 doc_insights kind=industry) ----------
    industry = []
    for r in repo.list_doc_insights(kind="industry"):
        try:
            body = json.loads(r["body"])
        except (ValueError, TypeError):
            continue
        for it in body.get("industries", []):
            industry.append({
                "industry": it.get("industry"),
                "plan_role": it.get("plan_role"),
                "scale_or_target": it.get("scale_or_target"),
                "growth_claim": it.get("growth_claim"),
                "policy_instruments": it.get("policy_instruments", []),
                "evidence": it.get("evidence"),
            })

    # ---------- 市场主体 ----------
    ents_2025 = repo.list_enterprises(year=ref_year or "2025")
    ents_prev_year = str(int(ref_year) - 1) if ref_year and ref_year.isdigit() else None
    ents_prev = repo.list_enterprises(year=ents_prev_year) if ents_prev_year else []
    county_counts = {}
    for e in ents_2025:
        c = e.get("county") or "未知"
        county_counts[c] = county_counts.get(c, 0) + 1
    top = sorted(county_counts.items(), key=lambda kv: -kv[1])[:3]
    market = {
        "total": len(ents_2025),
        "total_2025": len(ents_2025),
        "prev_total": len(ents_prev),
        "county_counts": county_counts,
        "hhi": hhi(county_counts),
        "top_counties": top,
    }

    # ---------- 就业 ----------
    jobs, _ = _value(repo, "城镇新增就业", ref_year, region)
    pop, _ = _value(repo, "常住人口", ref_year, region)
    employment = {
        "new_jobs": jobs,
        "density_permille": (jobs / pop * 1000.0) if jobs is not None and pop else None,
        "population": pop,
    }

    # ---------- 规划目标(plan_goal) ----------
    plan = {"period": None, "gdp_growth_target": None, "revenue_growth_target": None,
            "jobs_target": None, "evidence": []}
    for r in repo.list_doc_insights(kind="plan_goal"):
        try:
            body = json.loads(r["body"])
        except (ValueError, TypeError):
            continue
        plan["period"] = body.get("period", plan["period"])
        t = body.get("targets", {}) or {}
        plan["gdp_growth_target"] = t.get("gdp_growth", plan["gdp_growth_target"])
        plan["revenue_growth_target"] = t.get("revenue_growth", plan["revenue_growth_target"])
        plan["jobs_target"] = t.get("jobs", plan["jobs_target"])
        plan["evidence"].extend(body.get("evidence", []))

    # ---------- 可信度审读（延迟导入避免环） ----------
    from ..extract.critique import llm_critique, merge_checks, rule_checks

    values_by_indicator = {}
    for r in values_rows:
        values_by_indicator.setdefault(r["indicator_name"], []).append(
            (r["year"], r["value"]))
    checks = rule_checks(values_by_indicator)

    critiques = []
    for r in repo.list_doc_insights(kind="critique"):
        try:
            body = json.loads(r["body"])
        except (ValueError, TypeError):
            continue
        critiques.extend(body.get("critiques", []))
    merged = merge_checks(checks, critiques)

    return {
        "region": region,
        "reference_year": ref_year,
        "fiscal": fiscal,
        "industry": industry,
        "market": market,
        "employment": employment,
        "plan": plan,
        "credibility": merged,
    }
