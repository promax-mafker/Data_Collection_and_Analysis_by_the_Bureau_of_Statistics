"""福建省统计数据分析：指标宽表 / 排名 / 名义增速 / 三次产业结构。"""
import re

NUM_RE = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")

# (指标名, 分组, 是否可排名) —— 增速/指数类为百分比，不作排名
DEFAULT_INDICATORS = [
    ("地区生产总值", "经济总量", True),
    ("第一产业增加值", "三次产业", True),
    ("第二产业增加值", "三次产业", True),
    ("第三产业增加值", "三次产业", True),
    ("规模以上工业增加值", "增长", False),
    ("固定资产投资", "增长", False),
    ("社会消费品零售总额", "贸易消费", True),
    ("进出口总额", "贸易消费", True),
    ("一般公共预算收入", "财政", True),
    ("居民人均可支配收入", "民生", True),
    ("常住人口", "人口", True),
    ("居民消费价格指数", "价格", False),
]

# 需要按两年绝对额算名义增速的核心指标
GROWTH_INDICATORS = ["地区生产总值"]


def parse_num(v):
    if v is None:
        return None
    m = NUM_RE.search(str(v).replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def fmt(v, ndigits=2):
    """数字展示：最多保留 ndigits 位小数并去掉尾 0。"""
    s = f"{v:.{ndigits}f}"
    s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def _latest_year(repo):
    rows = repo.query_data(caliber="final")  # M7a: 预算口径行不抬高参考年
    years = [r.get("year") for r in rows if r.get("year")]
    return max(years) if years else None


def value_matrix(repo, indicator, year):
    """region -> {"value": float, "unit": str}（同一 region 重复取首条）。"""
    out = {}
    for r in repo.query_data(indicator=indicator, year=year, caliber="final"):
        v = parse_num(r.get("value"))
        if v is None:
            continue
        out.setdefault(r.get("region"), {"value": v, "unit": r.get("unit", "")})
    return out


def _year_vals(repo, indicator, region):
    """该 region 各年份值 -> {year: float}"""
    out = {}
    for r in repo.query_data(indicator=indicator, caliber="final"):
        if r.get("region") != region:
            continue
        v = parse_num(r.get("value"))
        if v is not None:
            out.setdefault(r.get("year"), v)
    return out


def analyze(repo, indicators=None, reference_year=None):
    """主分析。indicators: list[(name, group, rankable)]。"""
    indicators = indicators or DEFAULT_INDICATORS
    ref_year = reference_year or _latest_year(repo)

    table = {}
    regions = set()
    for name, group, rankable in indicators:
        m = value_matrix(repo, name, ref_year)
        table[name] = {"group": group, "rankable": rankable,
                       "regions": {r: x["value"] for r, x in m.items()},
                       "unit": next((x["unit"] for x in m.values()), "")}
        regions.update(m.keys())
    region_order = sorted(regions, key=lambda r: (0 if r in ("中国", "福建省") else 1, r))

    # 名义增速（核心指标，需两年）
    growth = {}
    for name in GROWTH_INDICATORS:
        for region in regions:
            vals = _year_vals(repo, name, region)
            years = sorted(vals.keys())
            if len(years) >= 2:
                y2, y1 = years[-1], years[-2]
                v2, v1 = vals[y2], vals[y1]
                if v1:
                    growth.setdefault(region, {})[name] = {
                        "year": y2, "prev_year": y1,
                        "value": v2, "prev_value": v1,
                        "pct": (v2 - v1) / v1 * 100.0,
                    }

    # 三次产业结构（参考年，占 GDP 比重）
    structure = {}
    gdp = table.get("地区生产总值", {}).get("regions", {})
    for part in ("第一产业增加值", "第二产业增加值", "第三产业增加值"):
        pm = table.get(part, {}).get("regions", {})
        for region in regions:
            g = gdp.get(region)
            p = pm.get(region)
            if g and p is not None:
                structure.setdefault(region, {})[part] = p / g * 100.0

    # 指标自洽校验（把领域恒等式变成显性检查）
    consistency = {}
    for region in regions:
        item = {}
        g = gdp.get(region)
        parts = [table.get(n, {}).get("regions", {}).get(region)
                 for n in ("第一产业增加值", "第二产业增加值", "第三产业增加值")]
        if g is not None and all(p is not None for p in parts):
            item["industry_sum_dev_pct"] = (sum(parts) / g - 1.0) * 100.0   # 三产和相对 GDP 偏差 %
        sh = structure.get(region)
        if sh:
            item["share_total"] = sum(sh.values())                            # 结构占比合计 %
        if item:
            consistency[region] = item

    notes = []
    if not ref_year:
        notes.append("库内暂无结构化数据，请先运行采集。")
    return {
        "reference_year": ref_year,
        "regions": region_order,
        "table": table,
        "growth": growth,
        "structure": structure,
        "consistency": consistency,
        "notes": notes,
    }
