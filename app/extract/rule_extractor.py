import re
import yaml
from .base import Extractor
from ..schemas import DataValue

SECTION_RE = re.compile(r'^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）)(.+)$', re.M)

CATEGORY_KEYWORDS = {
    "综合": ["综合", "生产总值"],
    "农业": ["农业", "农林牧渔"],
    "工业和建筑业": ["工业", "建筑业"],
    "固定资产投资": ["固定资产投资", "投资"],
    "国内贸易": ["国内贸易", "社会消费品", "市场消费"],
    "对外经济": ["对外经济", "进出口", "外资"],
    "财政金融": ["财政", "金融"],
    "人民生活": ["人民生活", "居民", "收入", "消费价格", "人口"],
    "科学技术": ["科技", "科学", "研究与试验", "R&D"],
}

def classify_heading(heading: str) -> str:
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in heading for k in kws):
            return cat
    return "综合"

def split_sections(text: str):
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        return []
    sections = []
    if text[:matches[0].start()].strip():
        sections.append(("综合", text[:matches[0].start()]))
    for i, m in enumerate(matches):
        body = text[m.end():matches[i + 1].start()] if i + 1 < len(matches) else text[m.end():]
        sections.append((m.group(0).strip(), body))
    return sections

def clean_bulletin_text(text: str) -> str:
    """清洗公报正文噪声：删除脚注角标 [n]、『（GDP）』括号标注、页眉零宽残留。"""
    text = re.sub(r"\[\d+\]", "", text)                 # 脚注角标 [2]
    text = re.sub(r"[（(]\s*GDP\s*[)）]", "", text)      # （GDP）
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)  # 零宽字符
    return text


_FULLWIDTH = {ord(f): ord(t) for f, t in zip(
    "０１２３４５６７８９．，％－　", "0123456789.,%- ")}


def normalize_value(s: str) -> str:
    """数字清洗收口：全角→半角、去千分位逗号（数字间）、去数字内空格。"""
    if not s:
        return s
    t = s.translate(_FULLWIDTH).strip()
    t = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", t)   # 1,688.2 → 1688.2
    t = re.sub(r"(?<=\d)\s+(?=\d)", "", t)             # 1 688 / 517 .70 → 合并
    return t


def _main_caliber_score(raw: str) -> int:
    """粗略主口径打分（输入含匹配前 10 字上下文）：主口径词加分、子口径/跨期词减分。

    注意：「其中税收收入814」的「其中」是主口径引导语，不作为扣分词；
    子口径由 民营/国有/海关代征/累计/期间 等本体词标识。
    """
    score = 0
    if "总额" in raw or "合计" in raw:
        score += 1
    if any(k in raw for k in ("全年", "全市", "本年")):
        score += 1
    if "完成" in raw or "实现" in raw:
        score += 1
    if any(k in raw for k in ("民营", "国有", "集体", "海关代征", "代征",
                              "累计", "期间", "年均", "占")):
        score -= 2
    return score


def _converge_values(values) -> list:
    """跨章节最终收敛：每页每指标最多一条（M7a 单值化兜底）。"""
    by_ind = {}
    for v in values:
        by_ind.setdefault(v.indicator_name, []).append(v)
    out = []
    for vs in by_ind.values():
        uniq = {}
        for v in vs:
            uniq.setdefault(v.value, v)
        vs = list(uniq.values())
        if len(vs) > 1:
            vs = [max(vs, key=lambda v: _main_caliber_score(v.raw_text))]
        out.extend(vs)
    return out


class RuleExtractor(Extractor):
    def extract(self, content_text, meta, rules):
        content_text = clean_bulletin_text(content_text)
        values = []
        sections = split_sections(content_text)
        if not sections:
            values.extend(self._run(content_text, rules, meta))
        else:
            for heading, body in sections:
                cat = classify_heading(heading)
                applicable = [r for r in rules if r["category"] == cat]
                values.extend(self._run(body, applicable, meta))
        # —— 补漏：章节限定下某规则零命中且配置了 fallback → 全文宽松模式再跑一次 ——
        for rule in rules:
            fallback = rule.get("fallback")
            if not fallback:
                continue
            if any(v.indicator_name == rule["name"] for v in values):
                continue
            values.extend(self._run(content_text, [dict(rule, pattern=fallback)], meta))
        return _converge_values(values)

    @staticmethod
    def _run(text, rules, meta):
        """对每条规则跑全文并收敛：每页每指标最多产出一条（M7a 单值化）。

        - 排除比例/增速误配（value 后紧跟 % 且规则无单位捕获）；
        - 同值完全重复只留一条；
        - 子口径/跨期命中按主口径分收敛，同分保留先出现者。
        """
        out = []
        for rule in rules:
            cands = []  # (value, raw_text, unit, ctx)
            rule_unit = rule.get("unit", "") or ""
            for m in re.finditer(rule["pattern"], text):
                gd = m.groupdict()
                unit = gd.get("unit") or rule_unit
                if not unit and text[m.end():m.end() + 1] in ("%", "％"):
                    continue  # 规则无单位且后随 % → 占比/增速表述，非总量值
                ctx = text[max(0, m.start() - 10):m.end()]
                cands.append((normalize_value(gd.get("value")), m.group(0), unit, ctx))
            # 同值去重（保留先出现者）
            uniq = {}
            for c in cands:
                uniq.setdefault(c[0], c)
            cands = list(uniq.values())
            # 多候选收敛到主口径（打分看含前文的 ctx，如"全年/占"常在匹配前）
            if len(cands) > 1:
                cands = [max(cands, key=lambda c: _main_caliber_score(c[3]))]
            for value, raw, unit, _ctx in cands:
                out.append(DataValue(
                    page_id=meta.get("page_id"),
                    bureau_id=meta.get("bureau_id"),
                    region=meta.get("region"),
                    year=meta.get("year"),
                    indicator_name=rule["name"],
                    value=value,
                    unit=unit,
                    category=rule["category"],
                    raw_text=raw,
                    method="rule",
                    caliber=meta.get("caliber", "final"),
                    source_url=meta.get("source_url", ""),
                ))
        return out

    def extract_named(self, content_text, names, meta, rules):
        """只对指定指标名(列表)跑规则 —— 预算执行等数值页按需抽取。

        names 为空 → 返回空列表。rules 为完整规则列表，内部按 name 过滤。
        """
        if not names:
            return []
        wanted = {n for n in names}
        subset = [r for r in rules if r["name"] in wanted]
        content_text = clean_bulletin_text(content_text)
        return self._run(content_text, subset, meta)

def load_rules(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["indicators"]
