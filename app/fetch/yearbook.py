"""统计年鉴采集编排（M9b T4）。

流程：卷 URL 模板 → 逐年取 TOC → **按标题**定位目标表 → 形状分派解析 →
单位换算到指标词典规范单位 → 入库（`source_kind='yearbook'`、`source_rank=2`）。

设计约束：

* **P2 禁止硬编码定位**：表号会位移、文件名形态会变，一律从 TOC 按标题匹配。
* **P1「错 > 缺」**：只映射语义确切的指标（户籍人口绝不冒充常住人口）；
  单位无法换算的值拒绝入库并在统计里计数，不照原值写。
* 复用既有 `parse.yearbook`（解析）与 `Repository.replace_page_values`（单事务入库）。
"""
import re
import traceback
from dataclasses import dataclass, field

import yaml

from ..extract.rule_extractor import load_rules
from ..parse.yearbook import load_toc, match_tables, parse_yearbook_table, to_canonical
from ..schemas import Bureau, DataValue, Page
from .parser import decode_html, hash_text

# 年鉴为修订后口径、非当年快照 → 与公报（rank=1）区分，作为次源
YEARBOOK_SOURCE_RANK = 2
YEARBOOK_SOURCE_KIND = "yearbook"


@dataclass
class TableSpec:
    """一张目标表的采集规格。"""
    key: str
    title: str
    indicators: list = field(default_factory=list)


def load_yearbook_config(path):
    """加载年鉴采集配置（YAML）。

    结构::

        region: 泉州市
        template: "https://.../qztjnj{year}/contents-cn.htm"
        years: [2016, ..., 2025]
        tables:
          - key: main
            title: 国民经济主要年份主要指标
            indicators:
              - {match: 地区生产总值, name: 地区生产总值, unit: 亿元}
    """
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _canonical_units(rules=None):
    """指标词典的规范单位：``{indicator_name: unit}``。"""
    try:
        rs = rules if rules is not None else load_rules(
            _default_rules_path())
    except Exception:
        return {}
    return {r.get("name"): r.get("unit") for r in rs if r.get("name")}


def _default_rules_path():
    import os
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "config", "extract_rules.yaml")


def _resolve_bureau(repo, region):
    bid = repo.find_bureau_by_region(region)
    if bid is None:
        bid = repo.upsert_bureau(Bureau(level="meta", name=f"{region}年鉴",
                                       url=f"meta://{region}-yearbook",
                                       region=region, verified=True))
    return bid


def _norm_indicator(s):
    """归一化指标行名：去 `#` 标记、去 `N.` 编号、压空格。

    例：``'# 第一产业'`` → ``'第一产业'``；``'1. 年末户籍人口数'`` → ``'年末户籍人口数'``。
    """
    t = re.sub(r"^[#＃\s]*(\d+\s*[.．、])?\s*", "", (s or "").strip())
    return re.sub(r"\s+", " ", t).strip()


def _match_indicator(cells, pattern):
    """按**正则 fullmatch** 匹配指标行。

    必须精确匹配：用子串匹配时 ``'地区生产总值'`` 会同时命中
    「地区生产总值（当年价）」「人均地区生产总值」「地区生产总值指数」等
    **语义不同**的行，把它们折叠成一个指标名 —— 真实库实测已有 154 组
    同键多值的真歧义（见 `Repository.find_ambiguous_groups`）。
    需要模糊时可显式写正则（如 ``地区生产总值.*``）。
    """
    hits = []
    for c in cells:
        name = _norm_indicator(c.indicator)
        if not name:
            continue
        try:
            if re.fullmatch(pattern, name):
                hits.append(c)
        except re.error:
            if name == pattern:
                hits.append(c)
    return hits


def _map_cells(cells, spec, region, vol_year, url, canonical, stats):
    """把表格单元格按规格映射为 DataValue（含单位换算与拒绝计数）。"""
    out = []
    for ind in spec.indicators:
        target_name = ind.get("name") or ind.get("match")
        target_unit = ind.get("unit") or canonical.get(target_name, "")
        hit = _match_indicator(cells, ind.get("match", ""))
        if not hit:
            stats["missing"].append(f"{vol_year}:{spec.key}:{ind.get('match')}")
            continue
        for c in hit:
            value, note = to_canonical(c.value, c.unit, target_unit)
            if value is None:
                stats["rejected"] += 1
                stats["rejected_detail"].append(
                    f"{vol_year}:{spec.key}:{c.indicator}:{c.value}{c.unit} -> {note}")
                continue
            out.append(DataValue(
                page_id=None, bureau_id=None, region=region, year=c.year,
                indicator_name=target_name, value=value,
                unit=target_unit or c.unit, category="年鉴",
                raw_text=f"{spec.title} | {c.indicator} | {c.year} | {c.value}{c.unit}"
                         + (f" | {note}" if note else ""),
                method="yearbook", caliber="final", source_url=url,
                source_kind=YEARBOOK_SOURCE_KIND, source_rank=YEARBOOK_SOURCE_RANK))
    return out


def ingest_yearbook(client, repo, cfg, logger=None):
    """按配置采集年鉴并入册。

    返回统计字典；**失败与缺失一律显式记录**，不静默跳过（设计 P6）。
    """
    region = cfg.get("region", "")
    template = cfg.get("template", "")
    years = cfg.get("years") or []
    specs = [TableSpec(key=t.get("key", ""), title=t.get("title", ""),
                       indicators=t.get("indicators") or [])
             for t in (cfg.get("tables") or [])]
    stats = {"region": region, "years": len(years), "pages": 0, "values": 0,
             "tables_present": 0, "tables_parsed": 0, "missing": [],
             "rejected": 0, "rejected_detail": [], "errors": 0}
    if not (region and template and years and specs):
        stats["errors"] += 1
        stats["missing"].append("配置不完整（region/template/years/tables 均为必填）")
        return stats

    canonical = _canonical_units()
    bureau_id = _resolve_bureau(repo, region)

    for vol_year in years:
        toc_url = template.format(year=vol_year)
        try:
            toc_html = decode_html(client.download(toc_url))
        except Exception as e:
            stats["errors"] += 1
            stats["missing"].append(f"{vol_year}:TOC 抓取失败 {e}")
            if logger:
                logger(f"[yearbook] TOC 失败 {toc_url}: {traceback.format_exc()}")
            continue
        toc = load_toc(toc_html, toc_url)
        if not toc:
            stats["missing"].append(f"{vol_year}:TOC 未解析出表链接")
            continue
        matched = match_tables(toc, {s.key: s.title for s in specs})

        for spec in specs:
            url = matched.get(spec.key)
            if not url:
                stats["missing"].append(f"{vol_year}:{spec.key}（{spec.title}）")
                continue
            stats["tables_present"] += 1
            try:
                html = decode_html(client.download(url))
                cells = parse_yearbook_table(html)
            except Exception as e:
                stats["errors"] += 1
                stats["missing"].append(f"{vol_year}:{spec.key} 抓取/解析失败 {e}")
                if logger:
                    logger(f"[yearbook] 表失败 {url}: {traceback.format_exc()}")
                continue
            if not cells:
                stats["missing"].append(f"{vol_year}:{spec.key} 解析为 0 行")
                continue
            stats["tables_parsed"] += 1
            values = _map_cells(cells, spec, region, vol_year, url, canonical, stats)

            page = Page(bureau_id=bureau_id, url=url,
                        title=f"{vol_year}年{region}统计年鉴·{spec.title}",
                        content_text="", dataset_type="yearbook",
                        period=str(vol_year),
                        content_hash=hash_text(f"yearbook:{url}:{vol_year}"),
                        doc_category="yearbook")
            pid = repo.upsert_page(page)
            stats["pages"] += 1
            # 单事务整页替换；空结果不删旧（M7a 护栏，防解析失败抹库）
            stats["values"] += repo.replace_page_values(pid, values)
    return stats
