"""M6 政府债务与投资拉动。"""
import re

_NUM = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = _NUM.search(str(v).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def _series_latest(repo, indicator):
    rows = repo.list_econ_series(indicator=indicator)
    if not rows:
        return None
    return _num(rows[-1].get("value"))


def investment_support(repo) -> dict:
    """政府债务与投资拉动。缺失 → None。"""
    debt = _series_latest(repo, "debt_balance")
    limit = _series_latest(repo, "debt_limit")
    gdp_rows = repo.query_data(indicator="地区生产总值", region="泉州市")
    gdp = None
    if gdp_rows:
        yrs = sorted({r.get("year") for r in gdp_rows if r.get("year")})
        gdp = _num([r for r in gdp_rows if r.get("year") == yrs[-1]][0].get("value")) if yrs else None

    return {
        "debt_balance": debt,
        "debt_limit": limit,
        "gdp": gdp,
        "debt_gdp": (debt / gdp * 100.0) if debt and gdp else None,
        "debt_limit_usage": (debt / limit * 100.0) if debt and limit else None,
    }
