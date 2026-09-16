"""地方债务专题画像（M9e，用户指定加权）。

数据源：

* `econ_series` 的 `debt_balance` / `debt_limit`（泉州 2021-2024，来自地方预决算报告）
* `data_values` 的 GDP 等同年指标

设计纪律：

* **A10 同年口径** —— 债务/GDP 必须用同一年，不能拿邻年凑数。
* **P1「错 > 缺」** —— 缺同年 GDP 时值为 ``None`` 并标 `verify`，绝不用别的年份代替。
* 每个指标带 ``principle`` 说明依据，便于报告层原样呈现（沿用决策树 P1-P6 风格）。
"""
# 债务指标的裁决阈值（依据：财政部限额管理与地方债风险预警的常用口径）
UTILIZATION_FLAG = 90.0     # 限额利用率 > 90% → 新增债务空间受限
UTILIZATION_WATCH = 80.0    # 80-90% → 关注

VERDICTS = ("ok", "flag", "verify", "na", "info")


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _metric(key, label, year, value, verdict, principle, note="", unit="%|亿元"):
    return {"key": key, "label": label, "year": year, "value": value,
            "verdict": verdict, "principle": principle, "note": note}


def _read_debt_series(repo):
    """读全库债务序列 → ``(balance, limit)`` 两个 ``{year: float}``。"""
    balance, limit = {}, {}
    try:
        rows = repo.list_econ_series()
    except Exception:
        rows = []
    for r in rows:
        ind = (r.get("indicator") or "").lower()
        year = str(r.get("year") or "").strip()
        val = _num(r.get("value"))
        if not year or val is None:
            continue
        if "balance" in ind:
            balance[year] = val
        elif "limit" in ind:
            limit[year] = val
    return balance, limit


def _latest_with(mapping, years):
    for y in sorted(years, reverse=True):
        if y in mapping:
            return y
    return None


def _limit_utilization(balance, limit):
    common = [y for y in balance if y in limit and limit[y]]
    if not common:
        return _metric("limit_utilization", "限额利用率", None, None, "na", "P-debt-1",
                       "缺债务余额或限额数据")
    y = max(common)
    util = round(balance[y] / limit[y] * 100, 2)
    if util > UTILIZATION_FLAG:
        return _metric("limit_utilization", "限额利用率", y, util, "flag", "P-debt-1",
                       f"利用率 {util}% > {UTILIZATION_FLAG}%：新增债务空间受限，"
                       "投资拉动存在换挡风险")
    if util > UTILIZATION_WATCH:
        return _metric("limit_utilization", "限额利用率", y, util, "verify", "P-debt-1",
                       f"利用率 {util}% 处于 {UTILIZATION_WATCH}-{UTILIZATION_FLAG}% 关注区间")
    return _metric("limit_utilization", "限额利用率", y, util, "ok", "P-debt-1",
                   f"利用率 {util}%，债务空间充足")


def _debt_to_gdp(repo, region, balance):
    if not balance:
        return _metric("debt_to_gdp", "债务/GDP", None, None, "na", "P-debt-2",
                       "缺债务余额数据")
    y = max(balance)
    gdp_rows = repo.query_data(region=region, indicator="地区生产总值", year=y)
    gdp = _num(gdp_rows[0]["value"]) if gdp_rows else None
    if not gdp:
        return _metric("debt_to_gdp", "债务/GDP", y, None, "verify", "P-debt-2",
                       f"缺 {y} 年 GDP（同年口径）；不取邻年代替")
    return _metric("debt_to_gdp", "债务/GDP", y, round(balance[y] / gdp * 100, 2),
                   "ok", "P-debt-2", f"{y} 年债务余额 / 同年 GDP")


def _series_outlier(balance):
    """检出序列中的**离群年**（远低于相邻两年）。

    实测动机：真实库 2022 余额 = 517.7，而 2021=1865.66、2023=2343.54 ——
    疑为误抽子项（如「新增限额」）。离群点若不标出，会让「新增债务」与趋势
    算出**看似合理实则错误**的数字（P1「错 > 缺」）。
    返回 ``(metric, outlier_years)``。
    """
    ys = sorted(balance)
    bad = []
    for i in range(1, len(ys) - 1):
        lo, mid, hi = balance[ys[i - 1]], balance[ys[i]], balance[ys[i + 1]]
        if lo > 0 and hi > 0 and mid < 0.5 * min(lo, hi):
            bad.append(ys[i])
    if not bad:
        verdict = "ok" if len(ys) >= 3 else "na"
        note = "未检出离群年" if len(ys) >= 3 else "年份少于 3，无法判断离群"
        return _metric("series_outlier", "债务序列一致性", ys[-1] if ys else None,
                       None, verdict, "P-debt-4", note), set()
    return _metric("series_outlier", "债务序列一致性", bad[-1], None, "verify", "P-debt-4",
                   f"疑离群年 {','.join(bad)}：余额显著低于相邻年，"
                   "疑误抽子项（如新增限额），需回原始报告核对"), set(bad)


def _new_debt(balance, outliers=()):
    if len(balance) < 2:
        return _metric("new_debt", "新增债务余额", None, None, "na", "P-debt-3",
                       "至少需要相邻两年债务余额")
    ys = sorted(balance)
    y0, y1 = ys[-2], ys[-1]
    if y0 in outliers or y1 in outliers:
        return _metric("new_debt", "新增债务余额", y1, None, "verify", "P-debt-3",
                       f"{y0} 或 {y1} 被标为离群年，增量不可信，先核对原始数据")
    return _metric("new_debt", "新增债务余额", y1, round(balance[y1] - balance[y0], 2),
                   "info", "P-debt-3", f"{y1} 较 {y0} 的余额增量")


def _headroom(balance, limit):
    common = [y for y in balance if y in limit and limit[y]]
    if not common:
        return _metric("headroom", "结存限额空间", None, None, "na", "P-debt-1",
                       "缺债务余额或限额数据")
    y = max(common)
    return _metric("headroom", "结存限额空间", y, round(limit[y] - balance[y], 2),
                   "info", "P-debt-1", f"{y} 年债务限额 - 余额")


def _debt_trend(balance):
    if len(balance) < 3:
        return _metric("debt_trend", "债务余额趋势", None, None, "na", "P-debt-3",
                       "至少需要 3 年才能判断趋势")
    ys = sorted(balance)
    first, last = balance[ys[0]], balance[ys[-1]]
    if first == 0:
        return _metric("debt_trend", "债务余额趋势", ys[-1], None, "verify", "P-debt-3",
                       "基年余额为 0，无法计算增速")
    return _metric("debt_trend", "债务余额趋势", ys[-1],
                   round((last - first) / first * 100, 2), "info", "P-debt-3",
                   f"{ys[0]}→{ys[-1]} 累计增速")


def _own_revenue(repo, region):
    """综合财力近似 = 一般公共预算收入 + 政府性基金收入（同年）。

    缺任一项则该年不入结果 —— 只用一半财力算出偏高的债务率属于**错**，
    按 P1 宁可 na。
    """
    out = {}
    try:
        rows = repo.query_data(region=region, primary_only=False)
    except Exception:
        return out
    by_year = {}
    for r in rows:
        name = r.get("indicator_name")
        if name not in ("一般公共预算收入", "政府性基金收入"):
            continue
        if (r.get("caliber") or "final") != "final":
            continue
        v = _num(r.get("value"))
        y = str(r.get("year") or "")
        if v is None or not y:
            continue
        by_year.setdefault(y, {})[name] = v
    for y, d in by_year.items():
        if len(d) == 2:
            out[y] = round(d["一般公共预算收入"] + d["政府性基金收入"], 2)
    return out


_VERDICT_MARK = {"flag": "🔴 FLAG", "verify": "⚠️ VERIFY", "na": "⬜ NA",
                 "ok": "✅ OK", "info": "ℹ️ INFO"}


def render_debt_markdown(profile):
    """债务专章（Markdown，供 Kami 报告渲染）。

    写作纪律：

    * 值为 ``None`` 的指标**不出现任何数字**，显式标为待核（不编造）；
    * 章节末尾固定给出**口径边界声明** —— 省级分项、债务率上界、地市口径待核，
      避免读者把本节当成定论引用。
    """
    region = profile.get("region", "")
    years = profile.get("years") or []
    balance = profile.get("balance") or {}
    limit = profile.get("limit") or {}
    summary = profile.get("summary") or {}
    lines = [f"## 地方债务 · {region}", ""]

    if not years:
        lines += ["本地尚未入库任何债务余额/限额数据。",
                  "",
                  "缺口来源：地市级债务的法定渠道是地方预决算公开平台的"
                  "「地方政府债务情况」专文；其中 2019-2021 三篇内容位于 "
                  "`.xlsx`/`.docx` 附件（本项目当前不解析该类型），需接入表格解析后补齐。",
                  ""]
        return "\n".join(lines)

    lines += [f"覆盖年份：{'、'.join(years)}（地市级，地方预决算公开）；"
              f"合计 {len(years)} 年。", ""]

    lines += ["| 指标 | 年份 | 值 | 裁决 | 依据 | 说明 |",
              "|---|---|---|---|---|---|"]
    for m in profile.get("metrics") or []:
        val = "—" if m.get("value") is None else m.get("value")
        lines.append(f"| {m.get('label')} | {m.get('year') or '—'} | {val} "
                     f"| {_VERDICT_MARK.get(m.get('verdict'), m.get('verdict'))} "
                     f"| {m.get('principle') or ''} | {m.get('note') or ''} |")
    lines.append("")

    if summary:
        lines += [f"裁决汇总：OK {summary.get('ok', 0)} · FLAG {summary.get('flag', 0)} · "
                  f"VERIFY {summary.get('verify', 0)} · NA {summary.get('na', 0)} · "
                  f"INFO {summary.get('info', 0)}", ""]

    if balance and limit:
        ys = [y for y in years if y in balance and y in limit]
        if ys:
            y = max(ys)
            lines += [f"风险提示：{y} 年债务余额 {balance[y]} 亿元、限额 {limit[y]} 亿元，"
                      f"结存空间 {round(limit[y] - balance[y], 2)} 亿元。", ""]

    missing = profile.get("missing") or []
    if missing:
        lines += ["**待核项**"] + [f"- {x}" for x in missing] + [""]

    lines += [
        "**口径边界（阅读本节前请先看）**",
        "",
        "- 债务余额/限额为**地市级（全市）**口径；2022 年数据存在执行口径与年初预算口径"
        "并存的情况，已标 `VERIFY` 待回原始报告核对。",
        "- 债务率分母目前只用**自有财力**（一般公共预算收入 + 政府性基金收入），"
        "**未含上级补助收入**，因此该比率是标准债务率的**上界**，不可直接与他地比较。",
        "- 一般债/专项债分项仅有**省级**来源（CELMA 地方政府债券平台），"
        "**地市级分项在公开渠道不可得**。",
        "- 债务数据为财政部/地方财政部门口径，与统计局口径不同源，可用于交叉印证。",
        "",
    ]
    return "\n".join(lines)


# 地市占全省债务的合理区间（低于此下限疑口径不符，高于上限疑数据错误）
CITY_SHARE_MIN = 1.0
CITY_SHARE_MAX = 60.0


def cross_check_debt(repo, city="泉州市", province="福建省"):
    """债务跨层级交叉验证（M9e E6）：省级 CELMA ↔ 地市级预决算。

    两个来源相互独立（财政部债券平台 vs 地方预决算公开），可用于抗数据美化。
    核心恒等约束：**地市债务余额不可能 ≥ 全省**。
    """
    rows = repo.list_econ_series()

    def _series(indicator, source_prefix=None):
        out = {}
        for r in rows:
            if r.get("indicator") != indicator:
                continue
            if source_prefix and not str(r.get("source") or "").startswith(source_prefix):
                continue
            v = _num(r.get("value"))
            y = str(r.get("year") or "")
            if v is not None and y:
                out[y] = v
        return out

    gen = _series("debt_general", "celma_")
    spc = _series("debt_special", "celma_")
    prov = {y: gen[y] + spc[y] for y in gen if y in spc}
    city_bal = _series("debt_balance")

    out = {"city": city, "province": province, "year": None,
           "province_value": None, "city_value": None, "ratio": None,
           "verdict": "not_comparable", "note": ""}
    if not prov:
        out["note"] = "缺省级分项（CELMA 一般债/专项债需同年齐备）"
        return out
    if not city_bal:
        out["note"] = f"缺{ city }地市级债务余额（地方预决算专文）"
        return out
    common = sorted(set(prov) & set(city_bal))
    if not common:
        out["note"] = "省级与地市级无共同年份，不可比"
        return out

    y = common[-1]
    pv, cv = prov[y], city_bal[y]
    out.update({"year": y, "province_value": round(pv, 2),
                "city_value": round(cv, 2)})
    if not pv:
        out["note"] = f"{y} 年省级债务合计为 0，不可比"
        return out
    ratio = cv / pv * 100
    out["ratio"] = round(ratio, 2)
    if cv >= pv:
        out["verdict"] = "diverge"
        out["note"] = (f"{y} 年{ city }债务 {cv} 亿元 ≥ {province}全省 {round(pv,2)} 亿元，"
                       "**不可能** —— 地市不可能超过全省，两边至少一方有误，须回原始来源核对")
    elif ratio < CITY_SHARE_MIN or ratio > CITY_SHARE_MAX:
        out["verdict"] = "verify"
        out["note"] = (f"{city}占全省 {round(ratio,2)}% 超出合理区间"
                       f"（{CITY_SHARE_MIN}-{CITY_SHARE_MAX}%），疑口径不一致"
                       "（如市本级 vs 全市），须核对")
    else:
        out["verdict"] = "agree"
        out["note"] = (f"{city}占全省 {round(ratio,2)}%，两个独立来源相互吻合"
                       "（财政部债券平台 vs 地方预决算公开）")
    return out


def debt_profile(repo, region="泉州市"):
    """地方债务画像。

    返回 ``{region, years, balance, limit, own_revenue, metrics, summary, missing}``。
    """
    balance, limit = _read_debt_series(repo)
    years = sorted(set(balance) | set(limit))
    outlier_metric, outliers = _series_outlier(balance)
    metrics = [
        _limit_utilization(balance, limit),
        _debt_to_gdp(repo, region, balance),
        outlier_metric,
        _new_debt(balance, outliers),
        _headroom(balance, limit),
        _debt_trend(balance),
    ]
    summary = {v: 0 for v in VERDICTS}
    missing = []
    for m in metrics:
        summary[m["verdict"]] = summary.get(m["verdict"], 0) + 1
        if m["verdict"] in ("na", "verify") and m["note"]:
            missing.append(f"{m['label']}: {m['note']}")
    if not years:
        missing.append("债务序列为空：需补地方预决算报告（地市级）或 CELMA（省级）")
    return {"region": region, "years": years, "balance": balance, "limit": limit,
            "own_revenue": _own_revenue(repo, region),
            "metrics": metrics, "summary": summary, "missing": missing}
