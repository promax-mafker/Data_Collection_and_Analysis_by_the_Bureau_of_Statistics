from abc import ABC, abstractmethod

class Extractor(ABC):
    @abstractmethod
    def extract(self, content_text: str, meta: dict, rules: list):
        """返回 DataValue 列表"""
