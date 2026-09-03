from .base import Extractor

class LLMExtractor(Extractor):
    """二期接入 OpenAI 兼容端点后实现，本次不落地。"""
    def extract(self, content_text, meta, rules):
        raise NotImplementedError("LLM 抽取器二期实现")
