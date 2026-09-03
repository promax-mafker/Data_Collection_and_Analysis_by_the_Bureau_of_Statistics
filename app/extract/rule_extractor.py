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

class RuleExtractor(Extractor):
    def extract(self, content_text, meta, rules):
        values = []
        sections = split_sections(content_text)
        if not sections:
            values.extend(self._run(content_text, rules, meta))
        else:
            for heading, body in sections:
                cat = classify_heading(heading)
                applicable = [r for r in rules if r["category"] == cat]
                values.extend(self._run(body, applicable, meta))
        return values

    @staticmethod
    def _run(text, rules, meta):
        out = []
        for rule in rules:
            for m in re.finditer(rule["pattern"], text):
                out.append(DataValue(
                    page_id=meta.get("page_id"),
                    bureau_id=meta.get("bureau_id"),
                    region=meta.get("region"),
                    year=meta.get("year"),
                    indicator_name=rule["name"],
                    value=m.group("value"),
                    unit=m.groupdict().get("unit") or rule.get("unit", ""),
                    category=rule["category"],
                    raw_text=m.group(0),
                    method="rule",
                ))
        return out

def load_rules(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["indicators"]
