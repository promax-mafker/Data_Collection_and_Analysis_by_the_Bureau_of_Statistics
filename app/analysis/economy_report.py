"""M6 泉州经济驱动画像 Kami 报告组装。

把 M5 画像 + M6 错配矩阵 + 三驾马车 组装成 Kami Parchment HTML。
"""
import datetime

from .kami import KamiRenderer
from .industry_gap import growth_contribution, industry_gap
from .consumption import consumption_support
from .investment import investment_support
from .trade import trade_support


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
    r.table(["指标", "数值", "口径"],
            [["社零总额(亿元)", _fmt(cons.get("retail")), "2025 全年"],
             ["GDP(亿元)", _fmt(cons.get("gdp")), "2025 全年"],
             ["社零/GDP", _fmt(cons.get("retail_gdp_ratio")), "% 消费规模比"],
             ["人均可支配收入(元)", _fmt(cons.get("income")), "2024 全体"],
             ["人均消费支出(元)", _fmt(cons.get("spending")), "2024 全体"],
             ["消费倾向(支出/收入)", _fmt(cons.get("propensity")), "%"],
             ["恩格尔系数(食品/消费)", _fmt(cons.get("engel")), "%"]],
            align_right=[1])
    r.note_limited("收入中位数地市不公布,以消费倾向与恩格尔系数作消费能力代理;"
                   "支出法 GDP 地市不核算,社零/GDP 为规模代理。")

    # 三、政府债务与投资拉动
    r.section("sec-inv", "三、政府债务与投资拉动")
    r.table(["指标", "数值", "口径"],
            [["政府债务余额(亿元)", _fmt(inv.get("debt_balance")), "2024 底全市"],
             ["债务限额(亿元)", _fmt(inv.get("debt_limit")), "2024 底全市"],
             ["债务/GDP", _fmt(inv.get("debt_gdp")), "% 政府杠杆(自算)"],
             ["债务限额使用率", _fmt(inv.get("debt_limit_usage")), "%"]],
            align_right=[1])
    r.note_limited("官方债务率不公布,债务/GDP 为自算;一般/专项债分项附表未挂网,仅总量;"
                   "固定资产投资无绝对额序列,投资拉动用公报增速差近似。")

    # 四、净出口拉动
    r.section("sec-trade", "四、净出口拉动")
    r.table(["指标", "数值", "口径"],
            [["出口额(亿元)", _fmt(trd.get("export")), "2024"],
             ["进口额(亿元)", _fmt(trd.get("import")), "2024"],
             ["净出口(亿元)", _fmt(trd.get("net_export")), "出口−进口"],
             ["外贸依存度(出口/GDP)", _fmt(trd.get("export_gdp_ratio")), "%"]],
            align_right=[1])

    # 五、口径与局限
    r.section("sec-note", "五、口径与局限")
    r.para("本画像的「三驾马车拉动」因泉州市不核算支出法 GDP,采用代理指标:"
           "消费以社零、投资以债务与投资增速、外需以进出口额近似。")
    r.para("收入中位数、支出法 GDP/最终消费率、一般/专项债分项、分行业税收与进出口"
           "均属制度性不可得(地市级不公布),未编造。")
    r.source("https://tjj.quanzhou.gov.cn/tjzl/tjgb/", "泉州市统计局·五经普公报", "2025")
    r.source("https://czj.quanzhou.gov.cn/ztzl/zfzw/", "泉州市财政局·政府债务", "2025")

    return r.doc()
