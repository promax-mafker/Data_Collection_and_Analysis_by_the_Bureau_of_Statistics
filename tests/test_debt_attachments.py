"""债务专文「仅附件」形态的识别测试。

实测：2019-2021 三篇「泉州市地方政府债务情况」**正文为空**，内容放在附件里
（`附表：2019年地方政府债务限额余额情况表.xlsx`、`2020年泉州市地方政府债务情况 2.docx`）。
本项目明确不解析 doc/xls（文档类型白名单），因此这几篇取不到值。

**但必须与「没有债务数据」区分开**：前者是"数据在附件里、待接入表格解析"，
后者是"该文不含债务数据"。混在一起会让人以为这几年的数据不存在。
"""
import os

from app.fetch.debt_docs import ingest_debt
from app.store.db import init_db
from app.store.repository import Repository

COL = "https://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/"
DOC = "https://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/202106/t20210610_2571756.htm"
TITLE = "2020年泉州市地方政府债务情况"

COL_HTML = f'<html><body><a href="{DOC}">{TITLE}</a></body></html>'
DOC_HTML = ('<html><body><p>' + TITLE + '</p><p>附件下载</p>'
            '<a href="/x/2019债务限额余额情况表.xlsx">附表：2019年地方政府债务限额余额情况表.xlsx</a>'
            '<a href="/x/2020债务情况.docx">2020年泉州市地方政府债务情况 2.docx</a>'
            '</body></html>')


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url):
        return self.mapping[url]

    def download(self, url):
        return self.mapping[url].encode("utf-8")


def _run(tmp_path):
    client = FakeClient({COL: COL_HTML, DOC: DOC_HTML})
    repo = Repository(init_db(str(tmp_path / "t.db")))
    return ingest_debt(repo, client, [COL])


def test_attachment_only_doc_is_classified_separately(tmp_path):
    st = _run(tmp_path)
    assert st["attachment_only"] == [TITLE], "仅附件形态必须单独归类"
    assert st["empty"] == [], "不得混入 empty（那会被读成『该文无债务数据』）"
    assert st["written"] == 0


def test_inline_doc_still_extracts(tmp_path):
    inline = ('<html><body><p>' + TITLE + '</p><p>截至2020年底，全市政府债务余额'
              '预计执行数1865.66亿元，债务余额严格控制在中央核定的限额2112.73亿元内。</p>'
              '</body></html>')
    client = FakeClient({COL: COL_HTML, DOC: inline})
    repo = Repository(init_db(str(tmp_path / "t2.db")))
    st = ingest_debt(repo, client, [COL])
    assert st["written"] == 2
    assert st["attachment_only"] == []
