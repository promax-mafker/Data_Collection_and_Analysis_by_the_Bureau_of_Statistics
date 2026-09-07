"""年鉴 HTML 表格 → 结构化序列解析（M6）。

用 lxml 遍历表格并展开 colspan/rowspan 合并单元格为矩形网格，
再按各表真实结构提取。pandas.read_html 的表头推断会吃掉表题行，
故自行展开（逻辑简单、可测、无魔法）。
"""
from lxml import html as lh


def _clean(v):
    if v is None:
        return ""
    return " ".join(str(v).replace("\xa0", " ").replace("\u3000", " ").split())


def _grid(html, table_index=0):
    """把第 table_index 个 <table> 展开为矩形二维列表。

    合并单元格只取左上角文本；colspan 右侧为空串，rowspan 下方为空串。
    """
    doc = lh.fromstring(html)
    tables = doc.xpath("//table")
    if table_index >= len(tables):
        return []
    rows = []
    widths = []
    for tr in tables[table_index].xpath(".//tr"):
        cells = tr.xpath("./th | ./td")
        row = []
        spans = []  # (col, remaining, text)
        # 上方 rowspan 下沉占位先填
        for col in range(max(widths, default=0)):
            row.append("")
        placed = [False] * (len(widths) + len(cells) + 8)
        # 简化：自建 span 管理
        row, spans = _fill_row(cells, width=max(widths, default=0) + len(cells) + 2)
        rows.append((row, spans))
        widths.append(len(row))
    if not rows:
        return []
    # 统一宽度并应用 rowspan 下沉
    w = max(widths)
    matrix = []
    active_spans = []  # (col, remaining_rows, text)
    for row, spans in rows:
        line = []
        for col in range(w):
            # 先填来自上方 rowspan 的值
            val = ""
            for sp in active_spans:
                if sp[0] == col:
                    val = sp[2]
            if not val and col < len(row):
                val = row[col]
            line.append(val)
        # 推进 rowspan 计数
        active_spans = [(c, r - 1, t) for (c, r, t) in active_spans if r > 1]
        for (col, remaining, text) in spans:
            active_spans.append((col, remaining, text))
        matrix.append(line)
    return matrix


def _fill_row(cells, width):
    """填充一行：返回 (row list, spans list)。"""
    row = [""] * width
    spans = []
    col = 0
    for cell in cells:
        while col < width and row[col] != "":
            col += 1
        text = _clean("".join(cell.itertext()))
        try:
            colspan = max(int(cell.get("colspan", 1) or 1), 1)
        except (TypeError, ValueError):
            colspan = 1
        try:
            rowspan = max(int(cell.get("rowspan", 1) or 1), 1)
        except (TypeError, ValueError):
            rowspan = 1
        if col + colspan > width:
            row.extend([""] * (col + colspan - width))
        for k in range(colspan):
            row[col + k] = text if k == 0 else ""
        if rowspan > 1:
            spans.append((col, rowspan - 1, text))
        col += colspan
    return row, spans


def tables_count(html) -> int:
    try:
        doc = lh.fromstring(html)
        return len(doc.xpath("//table"))
    except Exception:
        return 0


def _header_row_idx(grid, names=("年份", "指标名称", "项目", "行业", "指标")):
    for i in range(min(len(grid), 8)):
        if grid[i] and grid[i][0] in names:
            return i
    return 0


def parse_plain_series(html):
    """标准纵向表：表头行(首格=年份/指标名称) → 数据行。

    返回 [{year|industry, metric, value, raw_text}]。
    """
    grid = _grid(html)
    if not grid:
        return []
    hi = _header_row_idx(grid)
    head = grid[hi]
    if not head or not head[0]:
        return []
    first_col = head[0]
    metrics = head[1:]
    out = []
    for cells in grid[hi + 1:]:
        if not cells or not cells[0]:
            continue
        entity = cells[0]
        for mi, m in enumerate(metrics):
            ci = mi + 1
            if ci >= len(cells):
                continue
            val = cells[ci]
            if not val or val in ("—", "-", "nan", "0.0") or val == "0":
                continue
            row = {"metric": m, "value": val, "raw_text": " | ".join(cells)}
            if first_col == "年份" or (entity.isdigit() and len(entity) == 4):
                row["year"] = entity
            else:
                row["industry"] = entity
            out.append(row)
    return out


def parse_dual_header(html):
    """8-8 双列头表：年份行下方为数据行，每年两列。

    实测：数据列序恒为 [企业单位数（个）, 工业增加值增长（%）]（值 4514=企业数、
    7.7=增长），但指标名标签行因 colspan 错位不可信 → metric 名按固定列序赋予。

    返回 [{industry, year, metric, value, raw_text}]。
    """
    grid = _grid(html)
    if not grid:
        return []
    hi = _header_row_idx(grid)
    if hi + 1 >= len(grid):
        return []
    h_year = grid[hi]
    years = []
    for y in h_year[1:]:
        if y and (not years or years[-1] != y):
            years.append(y)
    if not years:
        return []
    per_year_metrics = ["企业单位数（个）", "工业增加值增长（%）"]
    out = []
    for cells in grid[hi + 2:]:
        if not cells or not cells[0]:
            continue
        industry = cells[0]
        if not any(ch.isdigit() for ch in "".join(cells[1:])):
            continue  # 分组标题行无数字 → 跳过
        data = cells[1:]
        for yi, year in enumerate(years):
            for k in range(2):
                ci = yi * 2 + k
                if ci >= len(data):
                    break
                val = data[ci]
                metric = per_year_metrics[k]
                if val and val not in ("—", "-", "nan"):
                    out.append({"industry": industry, "year": year, "metric": metric,
                                "value": val, "raw_text": " | ".join(cells)})
    return out


def parse_trade(html):
    """12-3 进出口表：年份 | 万美元(总额/出口/进口) | 亿元(总额/出口/进口)。

    返回 [{year, metric(出口额/进口额), value, unit, raw_text}]。
    """
    grid = _grid(html)
    if not grid:
        return []
    # 定位：优先「年份 + 出口额」同行（真实表行2）；否则「年份行 + 下一行出口额子表头」
    data_start = None
    for i in range(min(len(grid), 8)):
        cells = grid[i]
        nxt = grid[i + 1] if i + 1 < len(grid) else []
        if not cells or cells[0] != "年份":
            continue
        if any("出口额" in c for c in cells):
            data_start = i + 1
            break
        if any("出口额" in c for c in nxt):
            data_start = i + 2  # 跳过子表头行
            break
    if data_start is None:
        return []
    out = []
    for cells in grid[data_start:]:
        if not cells:
            continue
        year = cells[0]
        if not (year.isdigit() and len(year) == 4):
            continue
        if len(cells) >= 7 and cells[4]:
            base, unit = 4, "亿元"
        elif len(cells) >= 4 and cells[1]:
            base, unit = 1, "万美元"
        else:
            continue
        for offset, metric in ((1, "出口额"), (2, "进口额")):
            ci = base + offset
            if ci < len(cells) and cells[ci] and cells[ci] != "nan":
                out.append({"year": year, "metric": metric, "value": cells[ci],
                            "unit": unit, "raw_text": " | ".join(cells)})
    return out


def parse_income_rows(html):
    """4-7 收支表：行=收支项目，列0=项目名，列1=2024年值。

    返回 [{item, value, raw_text}]（只取 2024 列）。
    """
    grid = _grid(html)
    if not grid:
        return []
    hi = _header_row_idx(grid)
    out = []
    for cells in grid[hi + 1:]:
        if not cells or not cells[0]:
            continue
        item = cells[0]
        if not any(k in item for k in ("收入", "支出", "食品", "衣着", "居住", "交通",
                                       "医疗", "教育", "用品", "服务", "可支配")):
            continue
        val = cells[1] if len(cells) > 1 else ""
        if val and val != "nan":
            out.append({"item": item, "value": val, "raw_text": " | ".join(cells)})
    return out
