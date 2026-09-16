"""年鉴（统计年鉴在线版）解析：TOC 定位 + 宽表转置（M9b）。

与 `series_table.py` 的分工：

* `series_table` 处理 M6 用到的**年份为行**的年鉴表；
* 本模块处理泉州/福建年鉴的**年份为列、指标为行**宽表（如「1—2 国民经济主要年份主要指标」），
  一张表即可提供 1949-2023 的长序列。

复用 `series_table._grid`（lxml 矩形展开，已解决 colspan/rowspan），
不重复实现表格展开。

**设计 P2（禁止硬编码定位）**：表号会位移（实测「国民经济主要年份主要指标」
2016-2023 在 `0103`、2024 在 `0102`），2025 卷文件名形态也不同
（`0102.htm` → `0102_1-3.html`）。因此一律**从 TOC 按标题匹配**，绝不拼 URL 或写死表号。
"""
import re
from dataclasses import dataclass

from .series_table import _clean, _grid

# 表文件链接：0102.htm / 0102_1-3.html / 00a.htm 等
_TABLE_LINK = re.compile(r"/\d{2,4}(?:[-_][\w\-]+)?\.html?$", re.I)
# 标题前的编号：1—2 / 1-2 / 附录1-15
_NUM_PREFIX = re.compile(r"^\s*(?:附录)?\s*\d+\s*-\s*\d+\s*")
# 标题尾部的年份括注：（2023年）
_YEAR_PAREN = re.compile(r"[（(]\s*(?:19|20)\d{2}\s*年\s*[）)]\s*$")
# 表头中的年份单元格：'1949' 或 '1985年'（后者来自 <br> 分隔）
_YEAR_CELL = re.compile(r"^((?:19|20)\d{2})\s*年?$")
# 视为「无值」的占位符
_EMPTY_MARKS = {"", "—", "-", "－", "…", "...", "——", "空"}


def normalize_title(t):
    """归一化表标题：统一破折号 → 去编号前缀 → 去尾部年份括注 → 压空格。

    归一化是标题匹配的前提：年鉴标题的编号与年份括注逐年变化，
    但**语义部分稳定**。
    """
    s = _clean(t)
    s = re.sub(r"[—–－]", "-", s)
    s = _NUM_PREFIX.sub("", s)
    s = _YEAR_PAREN.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def load_toc(html, base_url):
    """解析年鉴目录页 → ``[(表 URL, 表标题)]``，仅保留表文件链接。"""
    from ..fetch.parser import extract_links

    out = []
    for url, text in extract_links(html, base_url):
        if _TABLE_LINK.search(url):
            out.append((url, text or ""))
    return out


def match_tables(toc, patterns):
    """按**标题正则**匹配表 → ``{key: url | None}``。

    ``patterns`` 形如 ``{"main": "国民经济主要(年份)?主要指标", ...}``。
    ``title`` 支持正则（用 ``re.search``；纯字符串等同子串匹配，向后兼容）——
    因为**标题逐年漂移**（实测：2018/2022 卷「国民经济主要指标」，
    2024 卷「国民经济主要年份主要指标」；2025 卷「…居民消费价格**指数**（上年=100）」
    而非「…总指数」）。只做子串匹配会换一卷就漏表。

    命中多个时取标题最短者（最具体）。**匹配不到返回 ``None``，绝不猜一个表**
    —— 猜错会把别的指标值灌进目标指标（静默错值）。
    """
    norm = [(u, normalize_title(t)) for u, t in toc]
    out = {}
    for key, pat in patterns.items():
        p = normalize_title(pat)
        if not p:
            out[key] = None
            continue
        try:
            rx = re.compile(p)
        except re.error:
            rx = None
        cands = [(u, t) for u, t in norm if (rx.search(t) if rx else p in t)]
        out[key] = min(cands, key=lambda x: len(x[1]))[0] if cands else None
    return out


def parse_year_columns(html, table_index=0):
    """解析「年份为列」的宽表 → ``[{indicator, unit, values: {year: value}}]``。

    * 表头行 = 前 8 行中年份单元格 ≥3 的行；
    * 分组行（除首格外全空）跳过，不产出指标；
    * 值保留原文（不换算单位），单位随行返回 —— 年鉴同一表内可能混用单位。
    """
    grid = _grid(html, table_index)
    if not grid:
        return []

    header_idx = None
    for i, row in enumerate(grid[:8]):
        n_year = sum(1 for c in row if _YEAR_CELL.match(_clean(c)))
        if n_year >= 3:
            header_idx = i
            break
    if header_idx is None:
        return []

    year_cols = []
    for j, c in enumerate(grid[header_idx]):
        m = _YEAR_CELL.match(_clean(c))
        if m:
            year_cols.append((j, m.group(1)))
    if not year_cols:
        return []

    out = []
    for row in grid[header_idx + 1:]:
        if not row:
            continue
        name = _clean(row[0])
        if not name:
            continue
        unit = _clean(row[1]) if len(row) > 1 else ""
        rest = [_clean(v) for v in row[1:]]
        if all(v in _EMPTY_MARKS for v in rest):
            continue  # 分组行 / 空行
        values = {}
        for j, year in year_cols:
            if j >= len(row):
                continue
            v = _clean(row[j])
            if v not in _EMPTY_MARKS:
                values[year] = v
        if values:
            out.append({"indicator": name, "unit": unit, "values": values})
    return out


# 表内单位行：`单位:万元`
_UNIT_LINE = re.compile(r"^单位\s*[:：]\s*(.+)$")


# 年鉴单位 → 指标词典规范单位的换算系数（只列确定无疑的十进换算）
_UNIT_FACTORS = {
    ("万元", "亿元"): 1e-4,
    ("元", "万元"): 1e-4,
    ("元", "亿元"): 1e-8,
    ("人", "万人"): 1e-4,
    ("吨", "万吨"): 1e-4,
    ("平方米", "万平方米"): 1e-4,
    ("公顷", "万公顷"): 1e-4,
}


def _fmt_num(x):
    """保留 2 位小数并去尾零（'592.07' / '45'）。"""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def to_canonical(value, unit, canonical_unit):
    """把年鉴值换算到**指标词典的规范单位**。

    返回 ``(值字符串 | None, 说明)``。

    为什么必须有这一步：年鉴宽表以「万元」给 GDP，而指标词典
    （`config/extract_rules.yaml`）的规范单位是「亿元」。不换算就入库会让
    GDP **静默差 10^4 倍**，且不会被任何既有校验发现 —— 正是设计 P1
    「错 > 缺」要防的情形。无法换算时**拒绝入库**（返回 ``None``），不照原值写。
    """
    raw = _clean(value)
    u = _clean(unit)
    c = _clean(canonical_unit)
    if not raw or not re.search(r"\d", raw):
        return None, f"非数值 {raw!r}"
    try:
        num = float(raw.replace(",", ""))
    except ValueError:
        return None, f"非数值 {raw!r}"
    if not c or not u or u == c:
        note = "" if (u == c) else f"单位未知（{u or '空'}），按原值入库"
        return _fmt_num(num), note
    factor = _UNIT_FACTORS.get((u, c))
    if factor is None:
        return None, f"无法换算 {u}→{c}"
    return _fmt_num(num * factor), f"{u}→{c}"


@dataclass
class YearbookCell:
    """年鉴表的统一中间表示：一条「指标 × 年份 × 值」。

    宽表与长表解析结果都归一到它，入库层因此只需处理一种形状。
    """
    indicator: str
    unit: str
    year: str
    value: str
    raw_text: str = ""


def _global_unit(grid, limit=4):
    """从表头上方的「单位:XXX」行取全局单位（长表用；宽表单位随行返回）。"""
    for row in grid[:limit]:
        for c in row[:3]:
            m = _UNIT_LINE.match(_clean(c))
            if m:
                return m.group(1).strip()
    return ""


def parse_yearbook_table(html, table_index=0):
    """**按表的真实形状分派**解析 → ``list[YearbookCell]``。

    年鉴同一卷内表结构并不统一（实测）：

    * 「年份为列、指标为行」宽表（如 `0102`）→ `parse_year_columns`
    * 「年份为行 + 表格头」长表（如 `0603`）→ 复用 `series_table.parse_plain_series`

    先试宽表；宽表为空再走长表。**按形状分派而非按表号** —— 表号会位移（P2）。
    """
    grid = _grid(html, table_index)
    wide = parse_year_columns(html, table_index)
    if wide:
        return [YearbookCell(indicator=r["indicator"], unit=r["unit"], year=y, value=v,
                             raw_text=f"{r['indicator']} | {y} | {v}")
                for r in wide for y, v in sorted(r["values"].items())]

    from .series_table import parse_plain_series

    unit = _global_unit(grid)
    out = []
    for r in parse_plain_series(html):
        year = r.get("year", "")
        if not year:
            continue          # 行业维度行（无年份）本模块不处理
        out.append(YearbookCell(indicator=r.get("metric", ""), unit=unit, year=str(year),
                                value=str(r.get("value", "")),
                                raw_text=r.get("raw_text", "")))
    return out
