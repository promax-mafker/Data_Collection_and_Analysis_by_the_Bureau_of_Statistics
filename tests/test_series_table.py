"""series_table.py 测试：真实年鉴表结构（表题行 + 表头行 + 数据行）。"""
from app.parse.series_table import parse_plain_series, parse_dual_header

# 真实表 3-4 人口：行1=表题，行2=表头，行3起=数据
POP_HTML = """
<table>
  <tr><th>3—4 主要年份年末常住人口及人口变动</th></tr>
  <tr><th>年份</th><th>常住人口 （万人）</th><th>城镇化率（ % ）</th></tr>
  <tr><td>2000</td><td>728</td><td>38.9</td></tr>
  <tr><td>2024</td><td>891.4</td><td>71.19</td></tr>
</table>
"""

# 真实表 8-8：行1表题，行2年份，行3指标名，行4起数据
DUAL_HTML = """
<table>
  <tr><th>8—8 规模以上工业重点产业情况</th></tr>
  <tr><th>指标名称</th><th>2016</th><th>2017</th></tr>
  <tr><th></th><th>企业单位数（个）</th><th>工业增加值增长（%）</th><th>企业单位数（个）</th><th>工业增加值增长（%）</th></tr>
  <tr><td>规模以上工业</td><td>4514</td><td>7.7</td><td>4635</td><td>8.3</td></tr>
  <tr><td>传统产业</td><td>3363</td><td>7.0</td><td>3454</td><td>8.6</td></tr>
</table>
"""


def test_plain_series_population():
    rows = parse_plain_series(POP_HTML)
    by_key = {(r["year"], r["metric"]): r for r in rows}
    assert by_key[("2024", "常住人口 （万人）")]["value"] == "891.4"
    assert by_key[("2024", "城镇化率（ % ）")]["value"] == "71.19"
    assert by_key[("2000", "常住人口 （万人）")]["value"] == "728"


def test_dual_header_expand():
    rows = parse_dual_header(DUAL_HTML)
    # 2 行业 × 2 年 × 2 指标 = 8 行
    assert len(rows) == 8
    by_key = {(r["industry"], r["year"], r["metric"]): r for r in rows}
    assert by_key[("规模以上工业", "2016", "企业单位数（个）")]["value"] == "4514"
    assert by_key[("规模以上工业", "2017", "工业增加值增长（%）")]["value"] == "8.3"
    assert by_key[("传统产业", "2016", "工业增加值增长（%）")]["value"] == "7.0"


def test_plain_series_industry_col():
    """首列非年份 → industry 字段。"""
    html = """<table>
      <tr><th>指标名称</th><th>单位数（个）</th><th>比重（%）</th></tr>
      <tr><td>农、林、牧、渔业</td><td>777</td><td>0.2</td></tr>
    </table>"""
    rows = parse_plain_series(html)
    assert rows[0]["industry"] == "农、林、牧、渔业"
    assert rows[0]["value"] == "777"


def test_empty_returns_empty():
    assert parse_plain_series("<table></table>") == []
    assert parse_dual_header("<table></table>") == []
