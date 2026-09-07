"""LLM 抽取器落地：按文档类别/章节选择提示词，产出 doc_insights 结构化洞察。

M5 语义：把规划纲要/政府工作报告等政策性文本，剥离官方口吻后改写为
经济学结构化 JSON（industry / plan_goal / fiscal_signal / employment），
每条含 evidence 原文摘录，供人工复核与数理分析。
"""
import json

from .base import Extractor
from .llm_client import LLMClient, LLMError

SYSTEM_EXTRACT = (
    "你是一名中国经济研究者。把政府文件原文改写成经济学分析："
    "剥离宣传语与官方口吻（如「砥砺奋进」「迈上新台阶」），"
    "只保留可检验的事实、目标、机制与约束。"
    "输出严格 JSON，不要多余文字。每个条目必须含 evidence 字段"
    "（从原文摘录的关键句子，一字不改）。禁止编造原文没有的数值。"
)

# kind → (中文说明, 输出 JSON schema 提示)
# 注意 schema 保持精简、条目限数：复杂 schema + 长输出会让 qwen3.8-flash 生成超时
KIND_SCHEMAS = {
    "industry": (
        "识别本段提到的产业/行业及其定位",
        '{"industries": [{"industry": "产业名", "plan_role": "支柱/新兴/培育/传统改造", '
        '"scale_or_target": "规模或目标(原文有则填,无则null)", '
        '"evidence": "原文摘录"}]} 最多5条'),
    "plan_goal": (
        "提取本段的发展目标与量化指标",
        '{"period": "如 十五五", '
        '"targets": {"gdp_growth": 数字或null, "revenue_growth": 数字或null, "jobs": 数字或null}, '
        '"evidence": ["原文摘录"]}'),
    "fiscal_signal": (
        "提取财政收支、税收、基金、债务、支出方向等财政信号",
        '{"fiscal": [{"subject": "科目", "item": "明细", "value": 数字或null, '
        '"unit": "单位", "note": "口径备注", "evidence": "原文摘录"}]} 最多8条'),
    "employment": (
        "提取就业岗位、新增就业、失业等就业信息",
        '{"employment": [{"segment": "人群", "value": 数字或null, "unit": "万人等", '
        '"trend": "趋势或null", "evidence": "原文摘录"}]} 最多5条'),
}

# category → 默认 kinds（未配 chunks 时）
CATEGORY_KINDS = {
    "plan": ["industry", "plan_goal"],
    "gov_report": ["industry", "plan_goal"],
    "budget": ["fiscal_signal"],
    "enterprise": [],
}

# chunk 关键词 → kind（配置了 chunks 时按段落语义分流）
CHUNK_KIND = [
    (("目标", "预期", "指标"), "plan_goal"),
    (("产业", "工业", "集群", "创新", "制造"), "industry"),
    (("就业", "民生", "收入", "人口"), "employment"),
    (("财政", "税收", "金融", "基金", "债务"), "fiscal_signal"),
]

MAX_CHUNK_CHARS = 2500
HARD_SPLIT_CHARS = 2500   # 小文本稳定：真实规划段+JSON 输出在 2500 字下较快


def _kind_for_chunk(keyword: str) -> str:
    for kws, kind in CHUNK_KIND:
        if any(k in keyword for k in kws):
            return kind
    return "industry"


def _split_by_keywords(text: str, keywords) -> list:
    """按关键词在文本中的实际出现位置把全文切成互不重叠的段。

    返回 [(keyword, segment)]：每个关键词取首次出现位置作为锚点，
    段 = 锚点起 至 下一锚点止（末段至文末）。锚点之前的文本（如
    规划纲要的政治性总论、目录）不属于任何段，直接丢弃。
    """
    anchors = []
    for kw in keywords:
        pos = text.find(kw)
        if pos >= 0:
            anchors.append((pos, kw))
    if not anchors:
        return []
    anchors.sort()
    segs = []
    for i, (pos, kw) in enumerate(anchors):
        end = anchors[i + 1][0] if i + 1 < len(anchors) else len(text)
        segs.append((kw, text[pos:end]))
    return segs


def _hard_split(text: str, max_chars=HARD_SPLIT_CHARS) -> list:
    """超长文本按段落硬切为 ≤max_chars 的块（保留段落完整性优先）。"""
    if len(text) <= max_chars:
        return [text]
    paras = text.split("\n")
    blocks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 1 > max_chars:
            blocks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        blocks.append(cur)
    return blocks


def _split_by_sections(text: str, sections) -> list:
    """起止锚点对切分：[(kind, segment)]。

    sections: [{start, end, kind}]。每段 = text[start_pos : end_pos]，
    end 缺省/未命中 → 至文末；start 未命中 → 跳过该段。
    """
    segs = []
    for s in sections:
        start = text.find(s.get("start", ""))
        if start < 0:
            continue
        end = text.find(s.get("end", ""), start + len(s.get("start", "")))
        if end < 0:
            end = len(text)
        segs.append((s.get("kind", "industry"), text[start:end]))
    return segs


class LLMExtractor(Extractor):
    """预留接口落地：抽取通道（extract_insights）。extract() 保持兼容抛错提示。"""

    def __init__(self, client=None):
        self.client = client if client is not None else LLMClient()

    def extract(self, content_text, meta, rules):
        raise NotImplementedError(
            "数值抽取请用 RuleExtractor；LLMExtractor 用于 extract_insights 文本洞察")

    # ---------- M5 洞察抽取 ----------

    def extract_insights(self, page: dict, text: str, source: dict) -> list:
        """按 source 配置对文本分块并调用 LLM，产出 doc_insights 行。

        page: {page_id, source_id, region, year, ...}
        source: {category, chunks(可选关键词), ...}
        返回 list[dict(page_id, source_id, kind, title, body, method)]，
        body 为 JSON 字符串。LLM 未启用 → 返回 []。

        切分策略（避免超长超时）：
        - chunks 关键词能命中 → 按关键词段切，逐段按 kind 抽取
        - 否则 kinds 全集逐段抽取，每段经硬切 ≤HARD_SPLIT_CHARS
        """
        if not getattr(self.client, "enabled", False):
            return []
        category = page.get("category") or source.get("category") or "plan"
        chunks = source.get("chunks") or []
        # 跳过目录/前置页：start_marker 在正文中出现第二次处截断（PDF 纲要常见 目录+正文）
        marker = source.get("start_marker")
        if marker:
            first = text.find(marker)
            if first >= 0:
                second = text.find(marker, first + 1)
                if second >= 0:
                    text = text[second:]
                else:
                    text = text[first:]
        results = []
        sections = source.get("sections") or []
        if sections:
            # 起止锚点对：精准抽取目标章节，每段已定 kind
            for kind, seg in _split_by_sections(text, sections):
                for block in _hard_split(seg):
                    results.append(self._call_and_emit(page, kind, kind, block))
        elif chunks:
            segments = _split_by_keywords(text, chunks)
            if segments:
                for kw, seg in segments:
                    kind = _kind_for_chunk(kw)
                    for block in _hard_split(seg):
                        results.append(self._call_and_emit(page, kind, kw, block))
            else:
                # 关键词全部未命中 → 兜底按 kinds 全集
                for block in _hard_split(text):
                    for kind in self._kinds_for(category, block):
                        results.append(self._call_and_emit(page, kind, category, block))
        else:
            for block in _hard_split(text):
                for kind in self._kinds_for(category, block):
                    results.append(self._call_and_emit(page, kind, category, block))
        return [r for r in results if r]

    @staticmethod
    def _kinds_for(category, block):
        """按块内容给 kinds。每块只返回 1 个主 kind，避免调用翻倍。"""
        if any(k in block for k in ("财政", "税收", "基金", "债务", "预算支出")):
            return ["fiscal_signal"]
        if any(k in block for k in ("就业", "新增", "岗位", "失业", "收入", "人口")):
            return ["employment"]
        if any(k in block for k in ("目标", "预期", "增速", "增长")):
            return ["plan_goal"]
        return CATEGORY_KINDS.get(category, ["industry"])

    def _call_and_emit(self, page, kind, label, segment):
        desc, schema = KIND_SCHEMAS.get(kind, KIND_SCHEMAS["industry"])
        user = (
            f"内容主题/章节：{label}\n\n"
            f"请完成：{desc}\n"
            f"输出 JSON 结构（严格按此 schema）：{schema}\n\n"
            f"===== 原文 =====\n{segment}\n===== 原文结束 =====\n"
        )
        try:
            data = self.client.complete_json(SYSTEM_EXTRACT, user)
        except LLMError as e:
            print(f"[LLMExtractor] {kind} 调用失败: {e}")
            return None
        if not isinstance(data, dict):
            return None
        return {
            "page_id": page.get("page_id"),
            "source_id": page.get("source_id"),
            "kind": kind,
            "title": f"{page.get('title', '')} · {kind}",
            "body": json.dumps(data, ensure_ascii=False),
            "method": "llm",
        }
