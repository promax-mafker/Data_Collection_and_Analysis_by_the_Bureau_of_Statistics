"""M6 泉州经济驱动画像 Kami 报告组装。

把 M5 画像 + M6 错配矩阵 + 三驾马车 组装成 Kami Parchment HTML。
M8:口径标签由数据实际年份生成(不再写死);第六章「方法论体检」渲染决策树裁决。
"""
import datetime

from .kami import KamiRenderer
from .industry_gap import growth_contribution, industry_gap
from .consumption import consumption_support
from .investment import investment_support
from .trade import trade_support
from .decision_tree import tree_audit


def _fmt(v, nd=2):
    if v is None:
        return "—"
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def _verdict_label(v):
    return {"overpromised": "🔴 规划强 / 实际弱", "matched": "⚪ 一致",
            "silent_pillar": "🟢 沉默支柱"}.get(v, v)


def render_economy_report(repo) -> str:
    """组装完整泉州经济驱动画像（Kami 风格）。"""
    gaps = industry_gap(repo)
    growth = growth_contribution(repo)
    cons = consumption_support(repo)
    inv = investment_support(repo)
    trd = trade_support(repo)
    today = datetime.datetime.now().strftime("%Y年%m月%d日")

    r = KamiRenderer("泉州经济驱动画像", "经济驱动画像",
                     f"{today} · 来源：泉州市统计局 / 财政局 / 五经普公报")

    # 一、实际产业结构错配
    r.section("sec-gap", "一、实际产业结构 × 规划承诺错配")
    r.para("以五经普(2023)分行业单位数、规上工业重点产业时序(2016–2024)、"
           "上市后备企业行业分布为「实然」,对照十五五规划宣称的「应然」,"
           "识别规划与实际的结构性错配。")
    if gaps:
        rows = []
        for g in sorted(gaps, key=lambda x: -((x.get("actual_growth") or 0))):
            rows.append([
                g["industry"], g.get("plan_role") or "（未列入规划）",
                _fmt(g.get("actual_share")), _fmt(g.get("actual_growth")),
                str(g.get("enterprise_cnt", 0)), _verdict_label(g["verdict"]),
            ])
        r.table(["产业", "规划定位", "实际占比%", "增速%", "上市后备企业", "判定"], rows,
                align_right=[2, 3, 4])
    else:
        r.note_limited("暂无错配数据，请先运行 M6 采集")
    # 重点产业增长贡献
    if growth:
        rows = [[k, _fmt(v["growth_pct"]), v["start_year"], v["end_year"]]
                for k, v in sorted(growth.items(), key=lambda kv: -(kv[1]["growth_pct"]))]
        r.para("规上工业重点产业单位数累计增速(2016→2024,相对指标):")
        r.table(["产业", "累计增速%", "起始年", "末年"], rows, align_right=[1])
    r.note_limited("口径:规上工业单位数增速为相对排序指标,非国民经济核算口径。")

    # 二、消费支撑度
    r.section("sec-cons", "二、本地消费对经济的支撑")
    cons_y = lambda k: cons.get(k) or "—"
    r.table(["指标", "数值", "口径"],
            [["社零总额(亿元)", _fmt(cons.get("retail")), f"{cons_y('retail_year')} 全年"],
             ["GDP(亿元)", _fmt(cons.get("gdp")), f"{cons_y('gdp_year')} 全年"],
             ["社零/GDP", _fmt(cons.get("retail_gdp_ratio")), "% 消费规模比"],
             ["人均可支配收入(元)", _fmt(cons.get("income")), f"{cons_y('income_year')} 全体"],
             ["人均消费支出(元)", _fmt(cons.get("spending")), f"{cons_y('spending_year')} 全体"],
             ["消费倾向(支出/收入)", _fmt(cons.get("propensity")), "%"],
             ["恩格尔系数(食品/消费)", _fmt(cons.get("engel")), "%"]],
            align_right=[1])
    r.note_limited("收入中位数地市不公布,以消费倾向与恩格尔系数作消费能力代理;"
                   "支出法 GDP 地市不核算,社零/GDP 为规模代理;比例仅在同年数据下计算。")

    # 三、政府债务与投资拉动
    r.section("sec-inv", "三、政府债务与投资拉动")
    inv_year = lambda k: inv.get(k) or "—"
    inv_note = inv.get("note") or f"{inv_year('debt_year')}债务÷同年GDP"
    r.table(["指标", "数值", "口径"],
            [["政府债务余额(亿元)", _fmt(inv.get("debt_balance")), f"{inv_year('debt_year')} 底全市"],
             ["债务限额(亿元)", _fmt(inv.get("debt_limit")), f"{inv_year('limit_year')} 底全市"],
             ["债务/GDP", _fmt(inv.get("debt_gdp")), f"% {inv_note}"],
             ["债务限额使用率", _fmt(inv.get("debt_limit_usage")), "%"]],
            align_right=[1])
    r.note_limited("官方债务率不公布,债务/GDP 为自算;一般/专项债分项附表未挂网,仅总量;"
                   "固定资产投资无绝对额序列,投资拉动用公报增速差近似。")

    # 四、净出口拉动
    r.section("sec-trade", "四、净出口拉动")
    trd_note = trd.get("note") or ""
    r.table(["指标", "数值", "口径"],
            [["出口额(亿元)", _fmt(trd.get("export")), f"{trd.get('year') or '—'}"],
             ["进口额(亿元)", _fmt(trd.get("import")), f"{trd.get('year') or '—'}"],
             ["净出口(亿元)", _fmt(trd.get("net_export")), "出口−进口(同年)"],
             ["外贸依存度(出口/GDP)", _fmt(trd.get("export_gdp_ratio")),
              "%" + (f"({trd_note})" if trd_note else "")]],
            align_right=[1])

    # 五、方法论体检(决策树裁决)
    tree = tree_audit(repo, region="泉州市")
    r.section("sec-tree", "五、方法论体检(决策树裁决)")
    r.para("按「地区经济分析决策树」(docs/methodology/ANALYSIS_DECISION_TREE.md)对上述分析过程本身体检:"
           "可信门(T0)→增长质量(T1)→结构(T2)→需求侧(T3)→分配(T4)→承诺(T5)。"
           "规则校验才给红灯,经济解读只作参考;缺数据走缺口清单,不猜测。")
    _VERDICT_LABEL_TREE = {"ok": "⚪ 通过", "flag": "🔴 存疑", "verify": "🟡 待核验",
                           "na": "⚪ 缺数据", "info": "ℹ 参考"}
    trows = []
    for n in sorted(tree["nodes"], key=lambda x: x["id"]):
        trows.append([
            n["id"], _VERDICT_LABEL_TREE.get(n["verdict"], n["verdict"]),
            n["question"], n["evidence"], n["note"],
        ])
    r.table(["节点", "裁决", "问题", "证据", "说明"], trows)
    if tree["missing"]:
        r.note_limited("数据缺口(未纳入裁决,须补齐后重跑):" + "、".join(tree["missing"]))
    if tree["verify_items"]:
        for item in tree["verify_items"]:
            r.note_limited("待核验: " + item)
    s = tree["summary"]
    r.note_limited(f"裁决汇总: 通过 {s['ok']} / 存疑 {s['flag']} / 待核验 {s['verify']} / "
                   f"缺数据 {s['na']} / 参考 {s['info']}(共 {len(tree['nodes'])} 节点)。")

    # 六、口径与局限
    r.section("sec-note", "六、口径与局限")
    r.para("本画像的「三驾马车拉动」因泉州市不核算支出法 GDP,采用代理指标:"
           "消费以社零、投资以债务与投资增速、外需以进出口额近似。")
    r.para("收入中位数、支出法 GDP/最终消费率、一般/专项债分项、分行业税收与进出口"
           "均属制度性不可得(地市级不公布),未编造。")
    r.source("https://tjj.quanzhou.gov.cn/tjzl/tjgb/", "泉州市统计局·五经普公报", "2025")
    r.source("https://czj.quanzhou.gov.cn/ztzl/zfzw/", "泉州市财政局·政府债务", "2025")

    return r.doc()
