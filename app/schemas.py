from dataclasses import dataclass
from typing import Optional

@dataclass
class Bureau:
    level: str                    # national / province / city
    name: str
    url: str
    region: str
    parent_id: Optional[int] = None
    id: Optional[int] = None      # 数据库主键，入库后回填
    verified: bool = False

@dataclass
class Page:
    bureau_id: int
    url: str
    title: str
    content_text: str
    dataset_type: str             # bulletin / topic
    period: str                   # 年度，如 2024
    content_hash: str
    doc_category: str = "bulletin"  # bulletin / plan / gov_report / budget / enterprise
    status: str = "fetched"

@dataclass
class DataValue:
    page_id: Optional[int]
    bureau_id: Optional[int]
    region: str
    year: str
    indicator_name: str
    value: str
    unit: str
    category: str
    raw_text: str
    method: str = "rule"
