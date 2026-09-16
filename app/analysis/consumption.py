"""M6 消费支撑度分析。

M8 修复：收入/支出/食品烟酒改为「同年最新」配对（原各取各最新导致年份错位、
_dv 写死 year="2025"），倾向/恩格尔仅在数据同年时计算。
"""
import re

_NUM = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = _NUM.search(str(v).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def _latest_value(repo, indicator, region="泉州市"):
    """data_values(final 口径)该指标最新年份值 → (value, unit, year)。"""
    best = None
    for r in repo.query_data(indicator=indicator, region=region, caliber="final"):
        y = r.get("year")
        if not y:
            continue
        if best is None or y > best[2]:
            best = (_num(r.get("value")), r.get("unit", ""), y)
    return best or (None, "", None)


def _series_year(repo, note_substr):
    """econ_series(income_consumption) 按 note 子串 → {year: float}。"""
    out = {}
    for r in repo.list_econ_series(indicator="income_consumption"):
        note = r.get("note") or ""
        if note_substr not in note:
            continue
        v = _num(r.get("value"))
        y = r.get("year")
        if v is not None and y:
            out[y] = v
    return out


def _max_common_year(maps):
    """多张 {year: v} 的共有年份最大值；无 → None。"""
    common = set.intersection(*(set(m) for m in maps)) if maps else set()
    return max(common) if common else None


def consumption_support(repo) -> dict:
    """消费支撑度。缺失 → None（不编造）；比例仅在同年数据下计算。"""
    retail, _, retail_year = _latest_value(repo, "社会消费品零售总额")
    gdp, _, gdp_year = _latest_value(repo, "地区生产总值")
    income_d = _series_year(repo, "可支配收入")
    spend_d = _series_year(repo, "消费支出")
    food_d = _series_year(repo, "食品烟酒")

    # 倾向 = 支出/收入（同年）；恩格尔 = 食品烟酒/支出（同年）
    propensity = engel = None
    income_year = spending_year = food_year = None
    y_is = _max_common_year([income_d, spend_d])
    if y_is is not None:
        income_year = spending_year = y_is
        income, spending = income_d[y_is], spend_d[y_is]
        if income:
            propensity = spending / income * 100.0
    y_sf = _max_common_year([spend_d, food_d])
    if y_sf is not None:
        food_year = y_sf
        if spend_d[y_sf]:
            engel = food_d[y_sf] / spend_d[y_sf] * 100.0

    income = income_d.get(income_year) if income_year else None
    spending = spend_d.get(spending_year) if spending_year else None
    food = food_d.get(food_year) if food_year else None

    return {
        "retail": retail,
        "gdp": gdp,
        "retail_gdp_ratio": (retail / gdp * 100.0)
        if (retail and gdp and retail_year == gdp_year) else None,
        "income": income,
        "spending": spending,
        "food": food,
        "propensity": propensity,
        "engel": engel,
        "retail_year": retail_year,
        "gdp_year": gdp_year,
        "income_year": income_year,
        "spending_year": spending_year,
        "food_year": food_year,
    }
