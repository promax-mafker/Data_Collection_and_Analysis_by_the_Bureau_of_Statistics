"""M6 政府债务与投资拉动。

M8 修复：债务余额(年末)与 GDP 分母绑定同一年（原取各自最新 → 债务 2024 底 ÷
GDP 2025 的跨年错配）；返回年份字段供报告标注。
"""
import re

_NUM = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = _NUM.search(str(v).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def _series_latest_year(repo, indicator):
    """econ_series 该指标最新年份 → (value, year)。"""
    best = None
    for r in repo.list_econ_series(indicator=indicator):
        y = r.get("year")
        if not y:
            continue
        if best is None or y > best[1]:
            best = (_num(r.get("value")), y)
    return best or (None, None)


def _latest_gdp(repo, region="泉州市", year=None):
    """final 口径 GDP：给定 year → 该年值；否则最新年值。"""
    best = None
    for r in repo.query_data(indicator="地区生产总值", region=region, caliber="final"):
        y = r.get("year")
        if not y:
            continue
        if year is not None and y != year:
            continue
        if best is None or y > best[1]:
            best = (_num(r.get("value")), y)
    return best or (None, None)


def investment_support(repo) -> dict:
    """政府债务与投资拉动（债务年份与 GDP 同年）。缺失 → None。"""
    debt, debt_year = _series_latest_year(repo, "debt_balance")
    limit, limit_year = _series_latest_year(repo, "debt_limit")

    gdp, gdp_year = _latest_gdp(repo, year=debt_year) if debt_year else (None, None)
    note = ""
    if debt_year and gdp_year and gdp_year != debt_year:
        note = f"债务为 {debt_year} 年末口径，GDP 无 {debt_year} 年值，取 {gdp_year} 近似"
    if debt_year and gdp_year is None:
        gdp, gdp_year = _latest_gdp(repo)
        note = f"债务为 {debt_year} 年末口径，GDP 缺失同年度，取最新 {gdp_year} 近似"

    return {
        "debt_balance": debt,
        "debt_limit": limit,
        "gdp": gdp,
        "debt_year": debt_year,
        "limit_year": limit_year,
        "gdp_year": gdp_year,
        "note": note,
        "debt_gdp": (debt / gdp * 100.0) if (debt and gdp and gdp_year == debt_year) else None,
        "debt_limit_usage": (debt / limit * 100.0) if (debt and limit) else None,
    }
