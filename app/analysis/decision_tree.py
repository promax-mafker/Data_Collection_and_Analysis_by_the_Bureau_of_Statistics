"""M8 分析决策树引擎——把 docs/methodology/ANALYSIS_DECISION_TREE.md 的判定逻辑代码化。

`tree_audit(repo, region)` 对地区年度数据执行 T0-T5 分层体检：
- verdict 语义：ok(规则通过) / flag(规则越线) / verify(待人工复核) /
              na(数据不足，进缺口清单) / info(展示性判读)
- 原则：规则才 flag，经济学解释只 info；错>缺；只提示不结论；口径透明。
- 复用：rule_checks/merge_checks(经 analyze_quanzhou)、industry_gap、
        consumption/investment/trade_support(M8 同年修复后)。
"""
import json

from .consumption import consumption_support
from .investment import investment_support
from .trade import trade_support
from .industry_gap import industry_gap
from .quanzhou import analyze_quanzhou

# 树体检必备的 final 口径核心指标(T0-2)
REQUIRED_FINAL = ("地区生产总值", "第一产业增加值", "第二产业增加值", "第三产业增加值",
                  "一般公共预算收入", "一般公共预算支出", "政府性基金收入", "税收收入",
                  "常住人口", "社会消费品零售总额")


# ---------- 取数小工具(全部 final / 同年优先) ----------

def _final_pairs(repo, indicator, region):
    """[(year, float)] final 口径，按年升序。"""
    out = []
    for r in repo.query_data(indicator=indicator, region=region, caliber="final"):
        try:
            v = float(str(r.get("value", "")).replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        if r.get("year"):
            out.append((r["year"], v))
    out.sort()
    return out


def _growth(pairs):
    if len(pairs) < 2 or not pairs[-2][1]:
        return None
    return (pairs[-1][1] - pairs[-2][1]) / pairs[-2][1] * 100.0


def _econ_map(repo, indicator):
    """econ_series {year: float}。"""
    out = {}
    for r in repo.list_econ_series(indicator=indicator):
        try:
            v = float(str(r.get("value", "")).replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        if r.get("year"):
            out[r["year"]] = v
    return out


def _econ_by_note(repo, note_substr):
    """income_consumption 按 note 子串 {year: float}。"""
    out = {}
    for r in repo.list_econ_series(indicator="income_consumption"):
        if note_substr not in (r.get("note") or ""):
            continue
        try:
            v = float(str(r.get("value", "")).replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        if r.get("year"):
            out[r["year"]] = v
    return out


def _max_common_year(maps):
    common = set.intersection(*(set(m) for m in maps)) if maps else set()
    return max(common) if common else None


def _pop_pairs(repo, region):
    """常住人口序列：优先 final data_values，其次 econ_series(population)。"""
    pairs = _final_pairs(repo, "常住人口", region)
    if pairs:
        return pairs
    return sorted((y, v) for y, v in _econ_map(repo, "population").items())


def _exists(repo, indicator, region):
    """指标存在性：常住人口允许落在 econ_series(population)。"""
    if indicator == "常住人口":
        return bool(_pop_pairs(repo, region))
    return bool(repo.query_data(indicator=indicator, region=region, caliber="final"))


def _check_entry(checks, cid):
    """rule_checks 中取指定 check；无 → None。"""
    for c in checks:
        if c["id"] == cid:
            return c
    return None


def _num_fmt(v, nd=2):
    if v is None:
        return "—"
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


# ---------- 节点实现 ----------

def _mk(nid, layer, question, verdict, evidence, note, principle):
    return {"id": nid, "layer": layer, "question": question, "verdict": verdict,
            "evidence": evidence, "note": note, "principle": principle}


def tree_audit(repo, region="泉州市") -> dict:
    """决策树裁决。返回 {nodes, missing, verify_items, summary}。"""
    nodes = []
    missing = []
    verify_items = []

    profile = analyze_quanzhou(repo)
    checks = profile["credibility"]["checks"]
    escalated = profile["credibility"]["escalated"]
    gaps = industry_gap(repo)
    cons = consumption_support(repo)
    inv = investment_support(repo)
    trd = trade_support(repo)

    gdp_pairs = _final_pairs(repo, "地区生产总值", region)
    g_gdp = _growth(gdp_pairs)

    # ---------- T0 可信门 ----------
    # T0-1 口径污染：budget 行是否影响本树核心指标
    budget_inds = sorted({r["indicator_name"] for r in
                          repo.query_data(region=region, caliber="budget")})
    core_budget = [i for i in budget_inds if i in REQUIRED_FINAL]
    if core_budget:
        v, note = "verify", f"存在预算口径行且进入核心指标: {'、'.join(core_budget)}（分析默认已排除,直接查询会看到）"
        verify_items.append(f"T0-1: {note}")
    elif budget_inds:
        v, note = "info", f"存在非核心预算口径行: {'、'.join(budget_inds)}"
    else:
        v, note = "ok", "无预算口径行混入"
    nodes.append(_mk("T0-1", "T0", "口径是否干净(final-only)?", v, f"budget 行数={len(budget_inds)}",
                     note, "P6 口径透明"))

    # T0-2 核心指标缺口
    have = {r["indicator_name"] for r in
            repo.query_data(region=region, caliber="final")}
    lack = [i for i in REQUIRED_FINAL
            if i not in have and not _exists(repo, i, region)]
    if lack:
        missing += lack
        nodes.append(_mk("T0-2", "T0", "核心指标是否齐备?", "na",
                         f"缺失 {len(lack)} 项", "缺项: " + "、".join(lack), "P0 错>缺"))
    else:
        nodes.append(_mk("T0-2", "T0", "核心指标是否齐备?", "ok",
                         f"必备 {len(REQUIRED_FINAL)} 项齐全", "", "P0 错>缺"))

    # T0-3 双层批判
    if escalated:
        subs = "、".join(sorted({e.get("subject", "?") for e in escalated}))
        nodes.append(_mk("T0-3", "T0", "双层批判是否命中?", "verify",
                         f"升级 {len(escalated)} 项", f"主题: {subs} —— 相关结论待人工核验", "P6 披露激励"))
        verify_items.append(f"T0-3: 双层批判命中 {subs}")
    else:
        nodes.append(_mk("T0-3", "T0", "双层批判是否命中?", "ok", "无升级", "", "P6 披露激励"))

    # ---------- T1 增长质量 ----------
    # T1-1 突变
    if g_gdp is None:
        nodes.append(_mk("T1-1", "T1", "GDP 增速是否异常突变?", "na",
                         "缺两年 GDP", "至少需相邻两年 final GDP", "P5"))
        missing.append("地区生产总值(两年序列)")
    elif abs(g_gdp) > 30.0:
        nodes.append(_mk("T1-1", "T1", "GDP 增速是否异常突变?", "flag",
                         f"名义增速 {_num_fmt(g_gdp)}%",
                         "相邻年变化 >30%，疑口径切换/修订/错值，先回可信门核验", "P5"))
    else:
        nodes.append(_mk("T1-1", "T1", "GDP 增速是否异常突变?", "ok",
                         f"名义增速 {_num_fmt(g_gdp)}%", "", "P5"))

    # T1-2 名义 vs 实际
    cpi = _econ_map(repo, "cpi")
    latest_year = gdp_pairs[-1][0] if gdp_pairs else None
    if g_gdp is not None and latest_year and latest_year in cpi and cpi[latest_year]:
        real = (1 + g_gdp / 100.0) / (cpi[latest_year] / 100.0) * 100.0 - 100.0
        nodes.append(_mk("T1-2", "T1", "是否按实际口径解读?", "info",
                         f"名义 {_num_fmt(g_gdp)}% × CPI {cpi[latest_year]} → 实际 ≈ {_num_fmt(real)}%",
                         f"以 {latest_year} 年 CPI(上年=100)平减", "P5 名义≠实际"))
    else:
        if g_gdp is None:
            nodes.append(_mk("T1-2", "T1", "是否按实际口径解读?", "na", "无增速", "", "P5"))
        else:
            nodes.append(_mk("T1-2", "T1", "是否按实际口径解读?", "na",
                             f"缺 {latest_year} 年 CPI",
                             "只能按名义增速解读，注意 metric_game 风险", "P5 名义≠实际"))
            missing.append("CPI(与GDP同年)")

    # ---------- T2 结构 ----------
    # T2-1 三产恒等式(C2)
    c2 = _check_entry(checks, "C2")
    if c2 is None:
        nodes.append(_mk("T2-1", "T2", "三产之和是否等于 GDP?", "na",
                         "C2 未触发(缺同年三产/GDP)", "数据补齐后此校验自动恢复", "P0 会计恒等式"))
        for i in ("第一产业增加值", "第二产业增加值", "第三产业增加值"):
            if i not in have:
                missing.append(i)
    else:
        nodes.append(_mk("T2-1", "T2", "三产之和是否等于 GDP?", c2["verdict"],
                         c2["note"], c2.get("note", ""), "P0 会计恒等式"))

    # T2-2 结构迁移
    p3_pairs = _final_pairs(repo, "第三产业增加值", region)
    shares = []
    for y, g in gdp_pairs:
        for y3, v3 in p3_pairs:
            if y3 == y and g:
                shares.append((y, v3 / g * 100.0))
    shares.sort()
    if len(shares) >= 2:
        (y0, s0), (y1, s1) = shares[-2], shares[-1]
        d = s1 - s0
        note = (f"三产占比 {_num_fmt(s0,1)}%({y0})→{_num_fmt(s1,1)}%({y1}),Δ{_num_fmt(d,1)}pct。"
                "结构性解释需企业数/就业互证,本树不下升级结论")
        nodes.append(_mk("T2-2", "T2", "产业结构是否剧变?", "info" if abs(d) > 3 else "ok",
                         f"Δ{_num_fmt(d,1)}pct", note, "P2 配第-克拉克"))
    else:
        nodes.append(_mk("T2-2", "T2", "产业结构是否剧变?", "na",
                         "需两年三产+GDP", "无互证不下结论", "P2"))
        missing.append("第三产业增加值(两年序列)")

    # T2-3 错配疑点(数据缺失被当弱?)
    over_none_share = [g for g in gaps
                       if g.get("verdict") == "overpromised" and g.get("actual_share") is None]
    if gaps:
        dist = {}
        for g in gaps:
            dist[g["verdict"]] = dist.get(g["verdict"], 0) + 1
        ev = "、".join(f"{k}={v}" for k, v in sorted(dist.items()))
        if over_none_share:
            names_all = [g["industry"] for g in over_none_share]
            names = "、".join(names_all[:5]) + (f" 等 {len(names_all)} 个" if len(names_all) > 5 else "")
            nodes.append(_mk("T2-3", "T2", "错配判定是否有数据缺失干扰?", "verify",
                             ev, f"overpromised 且无实际占比: {names} —— 可能是采集缺口而非真弱", "P2 增长核算"))
            verify_items.append(f"T2-3: {names} 需补数据后复核")
        else:
            nodes.append(_mk("T2-3", "T2", "错配判定是否有数据缺失干扰?", "info", ev,
                             "overpromised 均有实际数据支撑", "P2"))
    else:
        nodes.append(_mk("T2-3", "T2", "错配判定是否有数据缺失干扰?", "na",
                         "无错配矩阵(industry_data/规划洞察缺失)",
                         "先运行 M6 采集(五经普/年鉴 8-8/规划产业)——行业数据缺失非指标缺口,但错配维度不可用", "P2"))

    # ---------- T3 需求侧 ----------
    # T3-1 消费
    if cons.get("propensity") is None and cons.get("engel") is None and \
            cons.get("retail_gdp_ratio") is None:
        nodes.append(_mk("T3-1", "T3", "本地消费支撑如何?", "na",
                         "收支/食品/社零/GDP 缺同年数据", "", "P4 消费函数"))
        for i in ("社会消费品零售总额",):
            if i not in have:
                missing.append(i)
        missing.append("居民收支序列(同年)")
    else:
        inc_d, sp_d, food_d = (_econ_by_note(repo, "可支配收入"),
                               _econ_by_note(repo, "消费支出"),
                               _econ_by_note(repo, "食品烟酒"))
        props = {}
        for y in sorted(set(inc_d) & set(sp_d)):
            if inc_d[y]:
                props[y] = sp_d[y] / inc_d[y] * 100.0
        drift = None
        if len(props) >= 2:
            ys = sorted(props)
            drift = props[ys[-1]] - props[ys[-2]]
        ev = (f"消费倾向={_num_fmt(cons.get('propensity'),1)}%"
              + (f"(年际Δ{_num_fmt(drift,1)}pct)" if drift is not None else "")
              + f";恩格尔={_num_fmt(cons.get('engel'),1)}%;社零/GDP={_num_fmt(cons.get('retail_gdp_ratio'),1)}%")
        if drift is not None and abs(drift) > 10:
            nodes.append(_mk("T3-1", "T3", "本地消费支撑如何?", "verify", ev,
                             "消费倾向年际变化>10pct——查收入是否含一次性/财产性、消费口径变化", "P4"))
            verify_items.append(f"T3-1: 消费倾向年际Δ{_num_fmt(drift,1)}pct")
        else:
            nodes.append(_mk("T3-1", "T3", "本地消费支撑如何?", "info", ev,
                             "倾向与恩格尔看趋势;社零/GDP 不含服务消费,三产高市偏低估", "P4"))

    # T3-2 财政自生能力
    ss = profile["fiscal"]["self_sufficiency"]
    if ss is None:
        nodes.append(_mk("T3-2", "T3", "财政自生能力如何?", "na",
                         "缺同年收入/支出", "", "P3 预算恒等式"))
        if "一般公共预算收入" not in have:
            missing.append("一般公共预算收入")
        if "一般公共预算支出" not in have:
            missing.append("一般公共预算支出")
    elif ss < 60.0:
        nodes.append(_mk("T3-2", "T3", "财政自生能力如何?", "flag",
                         f"自给率 {_num_fmt(ss,1)}%",
                         "收入/支出 <60%：依赖上级转移支付,增长自生性弱", "P3"))
    else:
        nodes.append(_mk("T3-2", "T3", "财政自生能力如何?", "ok",
                         f"自给率 {_num_fmt(ss,1)}%", "", "P3"))

    # T3-3 土地依赖(C6)
    c6 = _check_entry(checks, "C6")
    if c6 is None:
        nodes.append(_mk("T3-3", "T3", "土地财政依赖是否过高?", "na",
                         "C6 未触发(缺同年基金/收入)", "", "P3"))
        if "政府性基金收入" not in have:
            missing.append("政府性基金收入")
    else:
        nodes.append(_mk("T3-3", "T3", "土地财政依赖是否过高?", c6["verdict"],
                         c6["note"], c6.get("note", ""), "P3"))

    # T3-4 债务空间
    usage = inv.get("debt_limit_usage")
    dg = inv.get("debt_gdp")
    if usage is None and dg is None:
        nodes.append(_mk("T3-4", "T3", "政府债务空间如何?", "na", "缺债务/限额序列", "", "P3"))
        missing.append("债务余额/限额序列")
    else:
        ev = f"限额利用率={_num_fmt(usage,1)}%;债务/GDP={_num_fmt(dg,1)}%"
        if inv.get("note"):
            ev += f"({inv['note']})"
        if usage is not None and usage > 90.0:
            nodes.append(_mk("T3-4", "T3", "政府债务空间如何?", "flag", ev,
                             "限额利用率>90%：新增债务空间受限,投资拉动换挡风险", "P3"))
        else:
            nodes.append(_mk("T3-4", "T3", "政府债务空间如何?", "info", ev,
                             "马约 60% 参考线不适用地方口径,看限额利用率为准", "P3"))

    # T3-5 外需敞口
    egr = trd.get("export_gdp_ratio")
    trade_map = {}
    for r in repo.list_econ_series(indicator="trade"):
        note = r.get("note") or ""
        if "出口" in note and "进口" not in note:
            try:
                trade_map[r["year"]] = float(str(r.get("value")).replace(",", ""))
            except (ValueError, TypeError):
                pass
    tg = None
    if len(trade_map) >= 2:
        ys = sorted(trade_map)
        if trade_map[ys[-2]]:
            tg = (trade_map[ys[-1]] - trade_map[ys[-2]]) / trade_map[ys[-2]] * 100.0
    if egr is None:
        nodes.append(_mk("T3-5", "T3", "外需敞口多大?", "na", "缺同年出口/GDP", "", "P1 开放经济"))
        missing.append("进出口序列(与GDP同年)")
    else:
        ev = f"出口依存度={_num_fmt(egr,1)}%" + (f";出口增速={_num_fmt(tg,1)}%" if tg is not None else "")
        if egr > 20.0 and tg is not None and tg < 0:
            nodes.append(_mk("T3-5", "T3", "外需敞口多大?", "flag", ev,
                             "高依存 + 出口转负:增长需内需承接", "P1"))
        else:
            nodes.append(_mk("T3-5", "T3", "外需敞口多大?", "info", ev,
                             "依存度看结构;转口贸易会高估本地增值", "P1"))

    # ---------- T4 分配 ----------
    # T4-1 就业背离(C7)
    c7 = _check_entry(checks, "C7")
    if c7 is None:
        nodes.append(_mk("T4-1", "T4", "就业与增长是否背离?", "ok",
                         "两年就业与 GDP 齐备且未触发", "", "P2 奥肯弱式"))
    elif "缺少" in c7["note"] or "缺相邻" in c7["note"] or "无法" in c7["note"]:
        nodes.append(_mk("T4-1", "T4", "就业与增长是否背离?", "na", c7["note"], "", "P2"))
        missing.append("城镇新增就业(两年序列)")
    else:
        nodes.append(_mk("T4-1", "T4", "就业与增长是否背离?", c7["verdict"],
                         c7["note"], c7.get("note", ""), "P2"))

    # T4-2 收入弹性(C5)
    c5 = _check_entry(checks, "C5")
    if c5 is None:
        nodes.append(_mk("T4-2", "T4", "收入与增长是否同步?", "na",
                         "C5 未触发", "", "P4 分配"))
    elif "缺少" in c5["note"] or "无法" in c5["note"]:
        nodes.append(_mk("T4-2", "T4", "收入与增长是否同步?", "na", c5["note"], "", "P4"))
        missing.append("预算收入(两年序列)")
    else:
        nodes.append(_mk("T4-2", "T4", "收入与增长是否同步?", c5["verdict"],
                         c5["note"], c5.get("note", ""), "P4"))

    # T4-3 人均化
    pop_pairs = _pop_pairs(repo, region)
    g_pop = _growth(pop_pairs) if pop_pairs else None
    if g_gdp is not None and g_pop is not None:
        g_percap = (1 + g_gdp / 100.0) / (1 + g_pop / 100.0) * 100.0 - 100.0
        note = (f"人口增速 {_num_fmt(g_pop,2)}% → 人均 GDP 增速 ≈ {_num_fmt(g_percap,2)}%"
                + ("。总量正增长而人口下降:总量叙事可能掩盖人均问题(metric_game)" if g_pop < 0 else ""))
        nodes.append(_mk("T4-3", "T4", "增长是否落到人均?", "info",
                         f"人均 ≈ {_num_fmt(g_percap,2)}%", note, "P2 人均化"))
    else:
        nodes.append(_mk("T4-3", "T4", "增长是否落到人均?", "na",
                         "需两年 GDP + 常住人口", "总量增速无法人均化", "P2"))
        missing.append("常住人口(两年序列)")

    # ---------- T5 承诺 ----------
    plan_rows = repo.list_doc_insights(kind="plan_goal", region=region)
    targets = []
    for r in plan_rows:
        try:
            body = json.loads(r["body"])
        except (ValueError, TypeError):
            continue
        t = (body.get("targets") or {}).get("gdp_growth")
        period = body.get("period") or r.get("period") or ""
        if t is not None:
            targets.append((period, t))
    # T5-1 目标 gap
    if not targets:
        nodes.append(_mk("T5-1", "T5", "规划目标是否脱离现实?", "na",
                         "无 plan_goal 目标数据", "未采集规划文本或未启用 LLM 抽取", "P6"))
    else:
        period, target = targets[-1]
        extrap = g_gdp if g_gdp is not None else 0.0
        if extrap and target is not None and extrap > 0 and target > extrap * 1.5:
            nodes.append(_mk("T5-1", "T5", "规划目标是否脱离现实?", "verify",
                             f"目标 {target}% vs 实际外推 ≈{_num_fmt(extrap,1)}%({period})",
                             "目标显著高于近期实际——需超常规动能或目标偏乐观", "P6 目标函数"))
            verify_items.append(f"T5-1: {period} 目标 {target}% 远超外推 {_num_fmt(extrap,1)}%")
        else:
            nodes.append(_mk("T5-1", "T5", "规划目标是否脱离现实?", "info",
                             f"目标 {target}%(近两年实际 {_num_fmt(extrap,1)}%)" if extrap else f"目标 {target}%",
                             "目标≈外推或外推不可得,不升级", "P6"))
    # T5-2 跨期混搭
    periods = sorted({p for p, _ in targets})
    if len(periods) > 1:
        nodes.append(_mk("T5-2", "T5", "目标是否跨规划期混用?", "verify",
                         f"并存时期: {'、'.join(periods)}",
                         "不同规划期目标不得拼接为单一'目标组合'", "P0 口径透明"))
        verify_items.append(f"T5-2: 多规划期目标并存 {periods}")
    elif periods:
        nodes.append(_mk("T5-2", "T5", "目标是否跨规划期混用?", "ok",
                         f"单一时期: {periods[0]}", "", "P0"))
    else:
        nodes.append(_mk("T5-2", "T5", "目标是否跨规划期混用?", "na", "无目标数据", "", "P0"))

    # ---------- 汇总 ----------
    counts = {"ok": 0, "flag": 0, "verify": 0, "na": 0, "info": 0}
    for n in nodes:
        counts[n["verdict"]] += 1
    return {"region": region, "nodes": nodes,
            "missing": sorted(set(missing)),
            "verify_items": verify_items, "summary": counts}
