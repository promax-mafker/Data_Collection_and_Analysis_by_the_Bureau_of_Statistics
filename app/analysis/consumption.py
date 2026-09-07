"""M6 消费支撑度（本地消费对经济的支撑）。"""
import re

_NUM = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = _NUM.search(str(v).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def _dv(repo, indicator, year="2025"):
    rows = repo.query_data(indicator=indicator, region="泉州市")
    if year:
        rows = [r for r in rows if r.get("year") == year]
    if not rows:
        return None
    return _num(rows[0].get("value"))


def _series(repo, note_substr):
    """按 note 子串匹配 econ_series 取最新值。"""
    rows = repo.list_econ_series()
    cands = [r for r in rows if note_substr in (r.get("note") or "")]
    if not cands:
        return None
    return _num(cands[-1].get("value"))


def consumption_support(repo) -> dict:
    """消费支撑度。缺失 → None（不编造）。"""
    retail = _dv(repo, "社会消费品零售总额", "2025")
    gdp = _dv(repo, "地区生产总值", "2025")
    income = _series(repo, "人均可支配收入")
    spending = _series(repo, "人均消费支出")
    food = _series(repo, "食品烟酒")

    return {
        "retail": retail,
        "gdp": gdp,
        "retail_gdp_ratio": (retail / gdp * 100.0) if retail and gdp else None,
        "income": income,
        "spending": spending,
        "propensity": (spending / income * 100.0) if spending and income else None,
        "engel": (food / spending * 100.0) if food and spending else None,
    }
