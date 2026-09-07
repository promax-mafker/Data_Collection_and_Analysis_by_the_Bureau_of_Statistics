"""批判审读器：防数据美化的双通道 —— 规则校验(C1-C7) + LLM 批判审读。

规则校验确定性、可复核；LLM 批判带 evidence 与 confidence，只提示不下结论。
"""
import re

from .llm_extractor import SYSTEM_EXTRACT
from .llm_client import LLMError

SYSTEM_CRITIQUE = (
    "你是一名对中国地方经济数据有长期研究的经济学家。政府文件倾向于选择性披露："
    "只报亮点、回避衰退、用修辞包装平淡甚至下滑的数据。"
    "请以怀疑态度审读以下原文，识别：\n"
    "1) spin 修辞包装：无数据支撑的溢美之词（「历史新高」「稳中向好」「圆满收官」等）；\n"
    "2) omission 选择性披露：只报增长/总量、回避下降/结构性问题/债务/土地财政依赖；\n"
    "3) metric_game 口径游戏：用「增长」指名义而非实际、用投资拉动掩盖消费疲弱、"
    "人均指标掩盖总量停滞等；\n"
    "4) gap 逻辑缺口：目标与现实增速的张力、财力与承诺支出的缺口。\n"
    "输出严格 JSON：{\"critiques\": [{\"type\": \"spin|omission|metric_game|gap\", "
    "\"severity\": \"high|med|low\", \"claim\": \"原文表述摘录\", "
    "\"reality\": \"经济学家的解读——为什么不可全信/缺什么数据验证\", "
    "\"what_to_check\": \"若要证实/证伪需要哪些数据\", "
    "\"confidence\": \"high|med|low\"}]}。\n"
    "禁止编造数据；无法从原文或专业知识推断的标注 confidence: low。"
)

NUM_RE = re.compile(r"-?[0-9][0-9,]*(?:\.[0-9]+)?")

SEVERITY_ORDER = {"low": 0, "med": 1, "high": 2}


def parse_number(v):
    if v is None:
        return None
    m = NUM_RE.search(str(v).replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _latest_pairs(rows):
    """rows: [(year, value_str)] → [(year, float)] 按年份升序。"""
    out = []
    for year, v in rows:
        f = parse_number(v)
        if f is not None:
            out.append((year, f))
    out.sort()
    return out


def _growth(pairs):
    """两年 → 增速百分数；不足两年 → None。"""
    if len(pairs) < 2:
        return None
    (_, v1), (_, v2) = pairs[-2], pairs[-1]
    if not v1:
        return None
    return (v2 - v1) / v1 * 100.0


def rule_checks(values_by_indicator: dict) -> list:
    """C1-C7 确定性校验。values_by_indicator: 指标名 → [(year, value_str), ...]。

    返回 check 记录列表：{id, subject, year, verdict(ok|flag), severity, note}。
    数据不足以计算时返回 med 提示，不静默。
    """
    checks = []
    gdp = _latest_pairs(values_by_indicator.get("地区生产总值", []))
    parts = {n: _latest_pairs(values_by_indicator.get(n, [])) for n in
             ("第一产业增加值", "第二产业增加值", "第三产业增加值")}
    p1, p2, p3 = parts["第一产业增加值"], parts["第二产业增加值"], parts["第三产业增加值"]

    # C2 三产和 = GDP
    if gdp and p1 and p2 and p3 and gdp[-1][0] == p1[-1][0] == p2[-1][0] == p3[-1][0]:
        (y, g), (_, a), (_, b), (_, c) = gdp[-1], p1[-1], p2[-1], p3[-1]
        dev = (a + b + c) / g - 1.0
        checks.append({
            "id": "C2", "subject": "三次产业和", "year": y,
            "verdict": "ok" if abs(dev) <= 0.01 else "flag",
            "severity": "med" if abs(dev) <= 0.01 else ("high" if abs(dev) > 0.03 else "med"),
            "note": f"三产和/GDP 偏差 {dev * 100:.2f}%",
        })

    # C3 跨年突变（对每个有两年的指标）
    for name, rows in values_by_indicator.items():
        pairs = _latest_pairs(rows)
        g = _growth(pairs)
        if g is None:
            continue
        if abs(g) > 30.0:
            checks.append({
                "id": "C3", "subject": name, "year": pairs[-1][0],
                "verdict": "flag", "severity": "med",
                "note": f"相邻年增速 {g:.1f}% 超过 ±30%，无事件说明则疑口径/修订",
            })
    if not any(c["id"] == "C3" for c in checks) and len(gdp) >= 2:
        checks.append({"id": "C3", "subject": "地区生产总值", "year": gdp[-1][0],
                       "verdict": "ok", "severity": "low", "note": "GDP 相邻年增速在正常区间"})

    # C5 收入/GDP 弹性
    revenue = _latest_pairs(values_by_indicator.get("地方一般公共预算收入", []) or
                            values_by_indicator.get("一般公共预算收入", []))
    g_rev, g_gdp = _growth(revenue), _growth(gdp)
    if g_rev is not None and g_gdp:
        elastic = g_rev / g_gdp if g_gdp else None
        if elastic is not None:
            verdict = "flag" if not (0.5 <= elastic <= 2.0) else "ok"
            checks.append({
                "id": "C5", "subject": "预算收入增速弹性", "year": revenue[-1][0],
                "verdict": verdict,
                "severity": "med" if verdict == "ok" else "high",
                "note": f"收入增速 {g_rev:.1f}% ÷ GDP 增速 {g_gdp:.1f}% = 弹性 {elastic:.2f}",
            })
    else:
        checks.append({"id": "C5", "subject": "预算收入增速弹性",
                       "year": None, "verdict": "flag", "severity": "med",
                       "note": "缺少相邻两年收入或 GDP，无法计算税收弹性"})

    # C6 土地财政依赖（当期）
    fund = _latest_pairs(values_by_indicator.get("政府性基金收入", []))
    if fund and revenue:
        y_f, f = fund[-1]
        y_r, r = revenue[-1]
        if y_f == y_r and (r + f):
            dep = f / (r + f) * 100.0
            checks.append({
                "id": "C6", "subject": "土地财政依赖度", "year": y_f,
                "verdict": "flag" if dep > 40.0 else "ok",
                "severity": "med" if dep <= 40.0 else "high",
                "note": f"政府性基金/(预算+基金) = {dep:.1f}%",
            })

    # C7 就业-经济背离（弱校验，数据不足提示）
    jobs = _latest_pairs(values_by_indicator.get("城镇新增就业", []))
    g_jobs = _growth(jobs)
    if g_jobs is not None and g_gdp is not None:
        if (g_jobs > 10.0 and g_gdp < 2.0) or (g_jobs < -5.0 and g_gdp > 5.0):
            checks.append({"id": "C7", "subject": "就业-经济背离", "year": jobs[-1][0],
                           "verdict": "flag", "severity": "med",
                           "note": f"新增就业增速 {g_jobs:.1f}% vs GDP {g_gdp:.1f}%，背离常理"})
    else:
        checks.append({"id": "C7", "subject": "就业-经济关系",
                       "year": None, "verdict": "flag", "severity": "med",
                       "note": "缺相邻两年就业数据，无法做就业-经济背离校验"})

    return checks


def llm_critique(text: str, client) -> list:
    """LLM 批判审读一次调用，规范化 critiques。"""
    if not getattr(client, "enabled", False):
        return []
    try:
        data = client.complete_json(SYSTEM_CRITIQUE,
                                    f"===== 原文 =====\n{text[:8000]}\n===== 原文结束 =====",
                                    temperature=0.3)
    except LLMError as e:
        print(f"[critique] 调用失败: {e}")
        return []
    items = data.get("critiques", []) if isinstance(data, dict) else []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "type": it.get("type", "gap"),
            "severity": it.get("severity", "med"),
            "claim": it.get("claim", ""),
            "reality": it.get("reality", ""),
            "what_to_check": it.get("what_to_check", ""),
            "confidence": it.get("confidence", "med"),
            "evidence": it.get("evidence", it.get("claim", "")),
        })
    return out


def merge_checks(checks: list, critiques: list) -> dict:
    """双层结果合并：同一 subject 双层命中 → escalated（severity 升一级）。"""
    escalated = []
    for c in checks:
        if c["verdict"] != "flag":
            continue
        for k in critiques:
            subj = (k.get("subject") or "").strip()
            if subj and subj in (c.get("subject") or ""):
                new = dict(c)
                new["severity"] = "high" if c.get("severity") != "high" else "high"
                new["critique"] = k
                escalated.append(new)
                break
    return {"checks": checks, "critiques": critiques, "escalated": escalated}
