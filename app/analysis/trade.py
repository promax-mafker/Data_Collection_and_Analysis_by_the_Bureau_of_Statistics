"""M6 净出口拉动。

M8 修复：出口/进口取「同年都存在」的最大年份（原取第一条 → 命中最早年份如 1984，
却被报告标注为最新年）；无同年对时净出口不计算并给出年份说明。
"""
import re

_NUM = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = _NUM.search(str(v).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def trade_support(repo, region="泉州市") -> dict:
    """净出口拉动（同年口径）。缺失 → None。"""
    by_year = {}  # year -> {"出口额": v, "进口额": v}
    for r in repo.list_econ_series(indicator="trade"):
        note = r.get("note") or ""
        v = _num(r.get("value"))
        y = r.get("year")
        if v is None or not y:
            continue
        # 方向必须**明确**：note 形如「出口额」/「进口额」。
        # ⚠ 实测陷阱：「进出口总额」含子串「出口」却**不含**「进口」
        #   （字符序为 进·出·口），原判定会把它误记为出口 → 总额被当出口额。
        #   按 P1「错 > 缺」，方向不明一律不用。
        ambiguous = ("进出口" in note) or ("总额" in note)
        if ambiguous:
            continue
        if "出口" in note and "进口" not in note:
            by_year.setdefault(y, {})["出口额"] = v
        elif "进口" in note and "出口" not in note:
            by_year.setdefault(y, {})["进口额"] = v

    # 同年对：出口与进口同一年且年份最大
    year = None
    for y in sorted(by_year):
        if "出口额" in by_year[y] and "进口额" in by_year[y]:
            year = y
    if year is not None:
        export = by_year[year]["出口额"]
        import_ = by_year[year]["进口额"]
        note = f"{year} 年海关口径"
    else:
        # 无同年对：各自最新年（允许只给单边），净出口不计算
        exp_years = [y for y, m in by_year.items() if "出口额" in m]
        imp_years = [y for y, m in by_year.items() if "进口额" in m]
        year = None
        export = by_year[max(exp_years)]["出口额"] if exp_years else None
        import_ = by_year[max(imp_years)]["进口额"] if imp_years else None
        note = "出口/进口无同年数据，净出口不可比" if (export and import_) else "缺进出口数据"

    gdp = None
    gdp_year = None
    if year is not None:
        for r in repo.query_data(indicator="地区生产总值", region=region, caliber="final"):
            y = r.get("year")
            if y == year:
                gdp = _num(r.get("value"))
                gdp_year = y
                break

    return {
        "export": export,
        "import": import_,
        "gdp": gdp,
        "year": year,
        "gdp_year": gdp_year,
        "note": note,
        "export_gdp_ratio": (export / gdp * 100.0) if (export and gdp) else None,
        "net_export": (export - import_) if (export is not None and import_ is not None
                                             and year is not None) else None,
    }
