"""app/parse/table.py 测试：HTML 表格 → 行记录。"""
from app.parse.table import extract_table_records

TABLE_HTML = """
<html><body>
<table>
  <tr><th>序号</th><th>企业名称</th><th>县（市、区）</th></tr>
  <tr><td>1</td><td><a href="/x">恒安集团</a></td><td>晋江市</td></tr>
  <tr><td>2</td><td>安踏体育</td><td>晋江市</td></tr>
</table>
</body></html>
"""

TWO_TABLES = """
<table><tr><th>甲</th></tr><tr><td>1</td></tr></table>
<p>分隔</p>
<table><tr><th>乙</th></tr><tr><td>2</td></tr></table>
"""


def test_single_table_rows_without_header():
    rows = extract_table_records(TABLE_HTML)
    assert len(rows) == 2
    assert rows[0] == ["1", "恒安集团", "晋江市"]  # 链接文本化
    assert rows[1] == ["2", "安踏体育", "晋江市"]


def test_multiple_tables_all_returned():
    rows = extract_table_records(TWO_TABLES)
    assert rows == [["1"], ["2"]]


def test_no_table_returns_empty():
    assert extract_table_records("<html><p>无表格</p></html>") == []


def test_empty_table():
    assert extract_table_records("<table></table>") == []


def test_cell_text_cleaned():
    html = '<table><tr><td> 恒安集团\n&nbsp; </td><td>晋江</td></tr></table>'
    rows = extract_table_records(html)
    assert rows == [["恒安集团", "晋江"]]
