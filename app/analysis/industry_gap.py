"""M6 错配分析：增长贡献率 + 规划 vs 实际错配矩阵。"""
import json

DEFAULT_THRESHOLDS = {"weak_share": 5.0, "strong_share": 10.0}


def hhi(counts: dict) -> float:
    total = sum(counts.values())
    if not total:
        return 0.0
    return sum((n / total) ** 2 for n in counts.values())


def _num(v):
    if v is None:
        return None
    import re
    m = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", str(v).replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def growth_contribution(repo, metric="企业单位数（个）") -> dict:
    """重点产业 2016→2024 增速（用 metric 时序）。返回 {industry: {start, end, growth_pct}}。"""
    rows = repo.list_industry_data(metric=metric)
    by_ind = {}
    for r in rows:
        v = _num(r.get("value"))
        if v is None or not r.get("year"):
            continue
        by_ind.setdefault(r["industry"], {})[r["year"]] = v
    out = {}
    for ind, yrs in by_ind.items():
        years = sorted(yrs)
        if len(years) < 2:
            continue
        y0, y1 = years[0], years[-1]
        v0, v1 = yrs[y0], yrs[y1]
        if v0:
            out[ind] = {"start_year": y0, "end_year": y1, "start": v0, "end": v1,
                        "growth_pct": round((v1 - v0) / v0 * 100.0, 2)}
    return out


def _plan_industries(repo):
    """从 doc_insights kind=industry 提取规划产业 → {name: plan_role}。"""
    out = {}
    for r in repo.list_doc_insights(kind="industry"):
        try:
            body = json.loads(r["body"])
        except (ValueError, TypeError):
            continue
        for it in body.get("industries", []):
            name = it.get("industry")
            if name:
                out[name] = it.get("plan_role", "")
    return out


def _enterprise_counts(repo):
    counts = {}
    for r in repo.list_enterprise_industry():
        ind = r.get("industry", "其他")
        counts[ind] = counts.get(ind, 0) + 1
    return counts


def industry_gap(repo, thresholds=None) -> list:
    """规划 vs 实际错配矩阵。

    返回 [{industry, plan_role, actual_share, actual_growth, enterprise_cnt,
           verdict, evidence}]，verdict ∈ overpromised | matched | silent_pillar。
    """
    th = thresholds or DEFAULT_THRESHOLDS
    plan = _plan_industries(repo)
    growth = growth_contribution(repo)
    ent_counts = _enterprise_counts(repo)

    # 实际产业集合 = 有 industry_data 或有企业归类
    actual_industries = set()
    for r in repo.list_industry_data():
        if r.get("industry"):
            actual_industries.add(r["industry"])
    actual_industries |= set(ent_counts.keys())
    # 计算营收/单位占比（用 industry_data 的 value 聚合）
    total_units = 0
    unit_by_ind = {}
    for r in repo.list_industry_data():
        v = _num(r.get("value"))
        if v is None:
            continue
        if r.get("metric", "").startswith(("企业单位数", "法人单位数")):
            unit_by_ind[r["industry"]] = unit_by_ind.get(r["industry"], 0) + v
            total_units += v
    shares = {i: (unit_by_ind[i] / total_units * 100.0 if total_units else 0.0)
              for i in unit_by_ind}

    median_growth = None
    growths = [g["growth_pct"] for g in growth.values()]
    if growths:
        growths.sort()
        median_growth = growths[len(growths) // 2]

    gaps = []
    # 规划产业逐个判定
    for name, role in plan.items():
        share = shares.get(name)
        g = growth.get(name)
        ent_cnt = ent_counts.get(name, 0)
        g_pct = g["growth_pct"] if g else None
        # 任何规划宣称（支柱/主导/重点/新兴/培育）无实际数据或弱于中位 → overpromised
        if (share is None or share < th["weak_share"]) \
                and (g_pct is None or (median_growth is not None and g_pct < median_growth)):
            verdict = "overpromised"
        else:
            verdict = "matched"
        gaps.append({
            "industry": name, "plan_role": role, "actual_share": round(share, 2) if share is not None else None,
            "actual_growth": g_pct, "enterprise_cnt": ent_cnt, "verdict": verdict,
            "evidence": _evidence(name, repo),
        })

    # 沉默支柱：实际有数据/企业 但规划未提，且增长高或占比高
    for name in sorted(actual_industries - set(plan.keys())):
        share = shares.get(name)
        g_pct = growth.get(name, {}).get("growth_pct")
        ent_cnt = ent_counts.get(name, 0)
        if (share is not None and share >= th["strong_share"]) or \
           (g_pct is not None and median_growth is not None and g_pct > median_growth) or \
           ent_cnt >= 3:
            gaps.append({
                "industry": name, "plan_role": None, "actual_share": round(share, 2) if share is not None else None,
                "actual_growth": g_pct, "enterprise_cnt": ent_cnt, "verdict": "silent_pillar",
                "evidence": _evidence(name, repo),
            })
    return gaps


def _evidence(industry, repo):
    """取该产业的规划 evidence 或实际数据 raw_text 作溯源。"""
    for r in repo.list_doc_insights(kind="industry"):
        try:
            body = json.loads(r["body"])
        except (ValueError, TypeError):
            continue
        for it in body.get("industries", []):
            if it.get("industry") == industry and it.get("evidence"):
                return [it["evidence"]]
    raw = [r["raw_text"] for r in repo.list_industry_data(industry=industry) if r.get("raw_text")]
    return raw[:1]
