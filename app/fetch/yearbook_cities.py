"""福建年鉴「各设区市」表采集（M9b 缺口补齐）。

与 `yearbook.py` 的差异（**这是关键**）：

| | 泉州年鉴 | 福建年鉴各设区市表 |
|---|---|---|
| 表格朝向 | 年份为列 / 年份为行 | **地区为行、指标为列** |
| `region` | 配置常量（整表一个地区） | **由行内地区名决定**（每行一个地区） |
| `year` | 表内自带年份列 | **卷年 + 偏移**（福建年鉴卷年 = 数据年 + 1） |

因此本模块单独一层：`parse_city_table` 出结构，配置把**列号映射到指标名**，
再按行产出一条条 `DataValue`（region 随行变化）。

⚠ 必须用**地区白名单**：表里有「全 省」行，若不排除会当成一个"地区"入库。
"""
import traceback
from dataclasses import dataclass, field

import yaml

from ..extract.rule_extractor import load_rules
from ..parse.yearbook import load_toc, match_tables, parse_city_table
from ..schemas import Bureau, DataValue, Page
from .parser import decode_html, hash_text

SOURCE_KIND = "yearbook"
SOURCE_RANK = 2


@dataclass
class CityColumn:
    """一列 → 一个指标的映射。"""
    col: int
    name: str
    unit: str = ""


@dataclass
class CityTableSpec:
    key: str
    title: str
    columns: list = field(default_factory=list)


def load_city_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _norm_city(s):
    return (s or "").replace(" ", "").strip()


def _resolve_bureau(repo, region):
    bid = repo.find_bureau_by_region(region)
    if bid is None:
        bid = repo.upsert_bureau(Bureau(level="city", name=f"{region}（年鉴）",
                                       url=f"meta://{region}-fj-yearbook",
                                       region=region, verified=True))
    return bid


def ingest_yearbook_cities(client, repo, cfg, logger=None):
    """按配置采集「各设区市」表 → `data_values`（region 随行）。

    返回统计；**缺失与失败一律显式记录**（设计 P6）。
    """
    template = cfg.get("template", "")
    years = cfg.get("years") or []
    offset = int(cfg.get("year_offset", -1))
    region_map = {_norm_city(k): v for k, v in (cfg.get("city_regions") or {}).items()}
    specs = [CityTableSpec(key=t.get("key", ""), title=t.get("title", ""),
                           columns=[CityColumn(col=int(c["col"]), name=c["name"],
                                               unit=c.get("unit", ""))
                                    for c in (t.get("columns") or [])])
             for t in (cfg.get("tables") or [])]
    stats = {"years": len(years), "pages": 0, "values": 0, "tables_parsed": 0,
             "missing": [], "unknown_cities": [], "errors": 0}
    if not (template and years and region_map and specs):
        stats["errors"] += 1
        stats["missing"].append("配置不完整（template/years/city_regions/tables 均为必填）")
        return stats

    bureaus = {}
    for vol_year in years:
        toc_url = template.format(year=vol_year)
        try:
            toc = load_toc(decode_html(client.download(toc_url)), toc_url)
        except Exception as e:
            stats["errors"] += 1
            stats["missing"].append(f"{vol_year}:TOC 失败 {e}")
            if logger:
                logger(f"[fj-cities] TOC 失败 {toc_url}: {traceback.format_exc()}")
            continue
        matched = match_tables(toc, {s.key: s.title for s in specs})
        data_year = str(int(vol_year) + offset)

        for spec in specs:
            url = matched.get(spec.key)
            if not url:
                stats["missing"].append(f"{vol_year}:{spec.key}（{spec.title}）")
                continue
            try:
                parsed = parse_city_table(decode_html(client.download(url)))
            except Exception as e:
                stats["errors"] += 1
                stats["missing"].append(f"{vol_year}:{spec.key} 解析失败 {e}")
                continue
            if not parsed["rows"]:
                stats["missing"].append(f"{vol_year}:{spec.key} 解析出 0 个地区行")
                continue
            stats["tables_parsed"] += 1

            values = []
            for row in parsed["rows"]:
                region = region_map.get(_norm_city(row["city"]))
                if region is None:
                    if _norm_city(row["city"]) not in ("全省", "Fujian"):
                        stats["unknown_cities"].append(row["city"])
                    continue          # 全省行 / 未登记地区 → 不入库（不猜）
                if region not in bureaus:
                    bureaus[region] = _resolve_bureau(repo, region)
                for c in spec.columns:
                    v = row["cells"].get(c.col)
                    if not v:
                        continue
                    values.append(DataValue(
                        page_id=None, bureau_id=bureaus[region], region=region,
                        year=data_year, indicator_name=c.name, value=v,
                        unit=c.unit or parsed.get("unit") or "", category="年鉴",
                        raw_text=f"{spec.title} | {row['city']} | {c.name} | "
                                 f"{data_year}(卷{vol_year}) | {v}",
                        method="yearbook", caliber="final", source_url=url,
                        source_kind=SOURCE_KIND, source_rank=SOURCE_RANK))

            page = Page(bureau_id=bureaus.get(next(iter(bureaus), ""), None)
                        or repo.upsert_bureau(Bureau(level="meta", name="福建省年鉴（各设区市）",
                                                     url=f"meta://fj-yearbook-{spec.key}",
                                                     region="福建省", verified=True)),
                        url=url, title=f"{vol_year}年福建统计年鉴·{spec.title}（各设区市）",
                        content_text="", dataset_type="yearbook", period=data_year,
                        content_hash=hash_text(f"fj-cities:{url}:{vol_year}"),
                        doc_category="yearbook")
            pid = repo.upsert_page(page)
            stats["pages"] += 1
            stats["values"] += repo.replace_page_values(pid, values)
    return stats
