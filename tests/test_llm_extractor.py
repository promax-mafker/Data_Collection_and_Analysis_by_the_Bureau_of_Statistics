"""llm_extractor.extract_insights：按类别选 schema、组装 doc_insights 行（mock LLM，不联网）。"""
import json

import pytest

from app.extract.llm_extractor import LLMExtractor
from app.extract.llm_client import LLMClient


class FakeLLM:
    """记录调用并返回预设 JSON。"""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    @property
    def enabled(self):
        return True

    def complete_json(self, system, user, temperature=None):
        self.calls.append({"system": system, "user": user})
        return self.responses.pop(0)


INDUSTRY_RESP = {
    "industries": [
        {"industry": "纺织鞋服", "plan_role": "支柱",
         "scale_or_target": "万亿产业集群", "growth_claim": None,
         "policy_instruments": ["技改补助"], "evidence": "原文摘录1"},
    ]
}
PLAN_RESP = {
    "period": "十五五", "targets": {"gdp_growth": 5.0, "revenue_growth": 2.5},
    "evidence": ["原文2"],
}


def _page(source_id="plan_15", category="plan", period="2026"):
    return {"page_id": 7, "source_id": source_id, "region": "泉州市",
            "year": period, "category": category, "title": "test",
            "url": "http://x/", "kind": "pdf"}


def test_extract_insights_plan_industry_and_goals():
    fake = FakeLLM([INDUSTRY_RESP, PLAN_RESP])
    ex = LLMExtractor(client=fake)
    items = ex.extract_insights(_page(), "产业体系：做大纺织鞋服产业集群……", {})
    assert len(fake.calls) == 2
    # 每个 kind 一条
    kinds = [i["kind"] for i in items]
    assert "industry" in kinds and "plan_goal" in kinds
    ind = next(i for i in items if i["kind"] == "industry")
    assert ind["source_id"] == "plan_15"
    assert ind["page_id"] == 7
    assert ind["method"] == "llm"
    body = json.loads(ind["body"])
    assert body["industries"][0]["industry"] == "纺织鞋服"
    assert "evidence" in body["industries"][0]


def test_extract_insights_budget_kind():
    fake = FakeLLM([{"fiscal": [{"item": "土地出让", "value": 292.07, "unit": "亿元",
                                 "evidence": "原文"}]}])
    ex = LLMExtractor(client=fake)
    page = _page(source_id="budget_2026", category="budget")
    items = ex.extract_insights(page, "预算报告全文……", {})
    assert items[0]["kind"] == "fiscal_signal"


def test_extract_insights_disabled_returns_empty():
    class Disabled:
        enabled = False
    ex = LLMExtractor(client=Disabled())
    assert ex.extract_insights(_page(), "文本", {}) == []


def test_extract_insights_long_text_split_into_chunks():
    """超长文本按 source['chunks'] 切分：每条 chunk 一次调用，产出合并。"""
    long_text = ("第三章 加快构建现代化产业体系\n" + "产业内容" * 300 + "\n"
                 "就业民生\n" + "就业内容" * 300)
    source = {"chunks": ["产业体系", "就业"], "category": "plan"}
    fake = FakeLLM([INDUSTRY_RESP, {"employment": [{"segment": "城镇", "value": 9.49,
                                                    "unit": "万人", "evidence": "e"}]}])
    ex = LLMExtractor(client=fake)
    items = ex.extract_insights(_page(), long_text, source)
    assert len(fake.calls) == 2


def test_unknown_category_defaults_industry():
    fake = FakeLLM([INDUSTRY_RESP])
    ex = LLMExtractor(client=fake)
    items = ex.extract_insights(_page(category="weird"), "文本", {})
    assert items  # 不抛错，回退 industry schema


def test_split_by_keywords_out_of_order():
    """关键词配置顺序与文本出现顺序不一致 → 仍按实际位置切段且不重叠。"""
    from app.extract.llm_extractor import _split_by_keywords
    text = "开头财政预算…中间产业布局…后段就业民生…末尾目标计划"
    segs = _split_by_keywords(text, ["目标", "就业", "产业", "财政"])
    # 四段按文本出现顺序排列
    assert [kw for kw, _ in segs] == ["财政", "产业", "就业", "目标"]
    joined = "".join(seg for _, seg in segs)
    assert joined == "财政预算…中间产业布局…后段就业民生…末尾目标计划"
    # 锚点之前的「开头」被丢弃（政治性总论不抽取）


def test_split_by_keywords_missing_kw_skipped():
    from app.extract.llm_extractor import _split_by_keywords
    text = "只有产业内容"
    segs = _split_by_keywords(text, ["产业", "不存在的词"])
    assert [kw for kw, _ in segs] == ["产业"]
    assert segs[0][1] == "产业内容"  # 锚点前文本丢弃


def test_hard_split_long_text():
    """超长文本按段落硬切，每块不超上限。"""
    from app.extract.llm_extractor import _hard_split
    text = "\n".join(f"第{i}段" + "内容" * 500 for i in range(30))  # ~30k
    blocks = _hard_split(text, max_chars=4000)
    assert len(blocks) > 1
    assert all(len(b) <= 4000 for b in blocks)


def test_split_by_sections_start_end():
    from app.extract.llm_extractor import _split_by_sections
    text = "序言…目标GDP增长5%…产业：纺织鞋服…就业：新增8万人…财政：收入592亿"
    sections = [
        {"start": "目标", "end": "产业", "kind": "plan_goal"},
        {"start": "产业", "end": "就业", "kind": "industry"},
        {"start": "就业", "end": "财政", "kind": "employment"},
    ]
    segs = _split_by_sections(text, sections)
    assert [(k, "…" in _ or True) for k, _ in segs]  # 3 段
    assert [k for k, _ in segs] == ["plan_goal", "industry", "employment"]
    assert "GDP增长5%" in segs[0][1]
    assert "纺织鞋服" in segs[1][1]
    assert "新增8万人" in segs[2][1]


def test_split_by_sections_missing_start_skipped():
    from app.extract.llm_extractor import _split_by_sections
    text = "只有产业内容"
    segs = _split_by_sections(text, [
        {"start": "不存在的", "end": "x", "kind": "industry"},
        {"start": "产业", "end": "x", "kind": "industry"},
    ])
    assert len(segs) == 1
    assert segs[0][1] == "产业内容"


def test_extract_insights_sections_used():
    """sections 配置优先：每段按指定 kind 各一次调用。"""
    fake = FakeLLM([INDUSTRY_RESP, PLAN_RESP])
    ex = LLMExtractor(client=fake)
    source = {"category": "plan", "sections": [
        {"start": "产业", "end": "目标", "kind": "industry"},
        {"start": "目标", "end": "", "kind": "plan_goal"}]}
    items = ex.extract_insights(_page(), "产业布局…目标GDP增长5%", source)
    assert len(fake.calls) == 2
    kinds = {i["kind"] for i in items}
    assert kinds == {"industry", "plan_goal"}
