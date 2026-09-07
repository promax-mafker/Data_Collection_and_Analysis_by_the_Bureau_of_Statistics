"""HTML 表格解析：提取页面全部 <table> 的数据行（跳过表头行）。"""
from bs4 import BeautifulSoup


def _cell_text(td) -> str:
    """单元格文本清洗：链接取文本、去多余空白与不换行空格。"""
    return " ".join(td.get_text(" ", strip=True).replace("\xa0", " ").split())


def _is_header_row(tr) -> bool:
    """表头行：单元格标签全部为 th。"""
    cells = tr.find_all(["th", "td"])
    return bool(cells) and all(c.name == "th" for c in cells)


def extract_table_records(html: str) -> list:
    """返回 [ [cell, cell, ...], ... ]，跳过各表的表头行。"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            if _is_header_row(tr):
                continue
            cells = [_cell_text(td) for td in tr.find_all(["th", "td"])]
            if cells and any(c for c in cells):
                out.append(cells)
    return out
