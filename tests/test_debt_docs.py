"""泉州市地方政府债务情况专文采集测试（M9e 债务序列回溯）。

实测栏目：`https://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/`（市级政府预算公开）
直接挂「20XX年泉州市地方政府债务情况」专文，是**地市级**债务余额/限额的法定披露渠道。
"""
from app.fetch.debt_docs import DOC_YEAR_RE, extract_debt, is_debt_doc

DOC = """
<html><body>
<p>2024年泉州市地方政府债务情况</p>
<p>截至2024年底，全市政府债务余额预计执行数2661.16亿元，
债务余额严格控制在中央核定的限额2753.80亿元以内。</p>
</body></html>
"""


def test_extract_debt_from_real_wording():
    got = extract_debt(DOC)
    assert got["debt_balance"] == "2661.16"
    assert got["debt_limit"] == "2753.80"


def test_extract_debt_returns_empty_when_absent():
    assert extract_debt("<html><body>无关内容</body></html>") == {}


def test_is_debt_doc_recognises_title():
    assert is_debt_doc("2024年泉州市地方政府债务情况") is True
    assert is_debt_doc("2024年泉州市国民经济和社会发展统计公报") is False


def test_doc_year_regex():
    assert DOC_YEAR_RE.search("2024年泉州市地方政府债务情况").group(1) == "2024"
    assert DOC_YEAR_RE.search("关于泉州市2024年预算执行情况").group(1) == "2024"
