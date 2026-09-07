"""M6 净出口拉动。"""
import re

_NUM = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")


def _num(v):
    if v is None:
        return None
    m = _NUM.search(str(v).replace(" ", ""))
    return float(m.group(0).replace(",", "")) if m else None


def trade_support(repo) -> dict:
    """净出口拉动。缺失 → None。"""
    export = None
    import_ = None
    for r in repo.list_econ_series(indicator="trade"):
        note = r.get("note") or ""
        v = _num(r.get("value"))
        if "出口" in note and export is None:
            export = v
        elif "进口" in note and import_ is None:
            import_ = v
    gdp_rows = repo.query_data(indicator="地区生产总值", region="泉州市")
    gdp = None
    if gdp_rows:
        yrs = sorted({r.get("year") for r in gdp_rows if r.get("year")})
        gdp = _num([r for r in gdp_rows if r.get("year") == yrs[-1]][0].get("value")) if yrs else None

    return {
        "export": export,
        "import": import_,
        "gdp": gdp,
        "export_gdp_ratio": (export / gdp * 100.0) if export and gdp else None,
        "net_export": (export - import_) if (export is not None and import_ is not None) else None,
    }
