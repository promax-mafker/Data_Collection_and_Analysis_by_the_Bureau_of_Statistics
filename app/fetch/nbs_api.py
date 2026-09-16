"""国家统计局**新版**公开数据 API 适配器（M9c）。

实测（2026-09-15）基础地址：``https://data.stats.gov.cn/dg/website/publicrelease/web/external``

| 端点 | 用途 | 实测 |
|---|---|---|
| ``/new/queryIndexTreeAsync?pid=&code=6`` | 目录树（code: 3=年度 6=分省年度 8=主要城市年度） | 200 / 508B |
| ``/new/getDefaultIndicData?code=26`` | 取默认指标**时间序列** | 200 / 3490B |
| ``/query?search=GDP&pagenum=1&pageSize=3`` | 关键词搜索指标 | 200 / 4630B |

⚠ 与 `ALT_SOURCES.md` 的差异：**旧 `easyquery.htm` 已被 WAF 封禁（403 UrlACL），
本文档的端点是从新版 SPA 逆向出来的**，两者不可混用。

⚠ **只到省级**（主要城市数据集为 36 个大中城市，福建仅福州/厦门）——
泉州等地级市不覆盖，故 note 强制写明口径。
"""
BASE = "https://data.stats.gov.cn/dg/website/publicrelease/web/external"
SCOPE_NOTE = "省级口径（国家统计局新版 API）；不含普通地级市"

_EMPTY = {"", "—", "-", "null", "None", "nan"}


def _year(v):
    """"2015年" → "2015"；非年份 → ""。"""
    s = str(v or "").strip()
    s = s[:-1] if s.endswith("年") else s
    return s if len(s) == 4 and s.isdigit() else ""


def _split_unit(name):
    """"旅客运输量 (万人)" → ("旅客运输量", "万人")。"""
    s = str(name or "").strip()
    if s.endswith(")") and "(" in s:
        head, _, tail = s.rpartition("(")
        return head.strip(), tail[:-1].strip()
    if s.endswith("）") and "（" in s:
        head, _, tail = s.rpartition("（")
        return head.strip(), tail[:-1].strip()
    return s, ""


def parse_default_series(payload):
    """``getDefaultIndicData`` 响应 → ``[{catalog, indicator, unit, values}]``。

    结构实测：``{data: [{catalogName, xData:[年份], yData:[{name, value:[...]}]}]}``。
    ``xData`` 与 ``yData[i].value`` 按下标对齐；长度不齐时以较短者为准，
    缺值（空/—）跳过而非填 0。
    """
    out = []
    for cat in (payload or {}).get("data") or []:
        years = [_year(x) for x in (cat.get("xData") or [])]
        for series in cat.get("yData") or []:
            indicator, unit = _split_unit(series.get("name"))
            if not indicator:
                continue
            values = {}
            for i, raw in enumerate(series.get("value") or []):
                if i >= len(years) or not years[i]:
                    continue
                s = str(raw).strip()
                if s in _EMPTY:
                    continue
                values[years[i]] = s
            if values:
                out.append({"catalog": cat.get("catalogName") or "",
                            "indicator": indicator, "unit": unit, "values": values})
    return out


def ingest_nbs(repo, payloads, source="nbs_api", note=None):
    """把若干 payload 写入 ``econ_series``（整批替换，幂等）。返回行数。"""
    rows = []
    for p in payloads:
        for s in parse_default_series(p):
            for year, value in sorted(s["values"].items()):
                rows.append({"indicator": s["indicator"], "year": year, "value": value,
                             "unit": s["unit"], "note": note or SCOPE_NOTE,
                             "raw_text": f"NBS API {s['catalog']} | {s['indicator']} | {year}"})
    return repo.replace_econ_series(source, rows) if rows else 0
