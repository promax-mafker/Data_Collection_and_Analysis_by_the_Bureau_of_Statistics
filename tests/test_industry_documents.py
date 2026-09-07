"""industry_documents.py 测试：注册表加载 + 采集编排（FakeClient 离线）。"""
import os

import pytest
import yaml

from app.store.db import init_db
from app.store.repository import Repository
from app.fetch.industry_documents import load_industry_sources, run_industry_sources

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping  # url -> str(html/pdf text)

    def get(self, url):
        return self.mapping[url]

    def download(self, url):
        return self.mapping[url].encode("utf-8")


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def _cfg(tmp_path, census_html="", yearbook_html=""):
    d = {
        "region": "泉州市",
        "yearbook_base": "https://tjj.gov.cn/yb/",
        "census": [
            {"id": "census1", "url": "https://tjj.gov.cn/c1.htm", "desc": "一"},
        ],
        "yearbook_tables": [
            {"id": "pop_3_4", "path": "0304_3-4.html", "kind": "econ", "indicator": "population", "desc": "人口"},
            {"id": "trade_12_3", "path": "1203_12-3.html", "kind": "econ", "indicator": "trade", "desc": "进出口"},
            {"id": "income_4_7", "path": "0407_4-7.html", "kind": "econ", "indicator": "income_consumption", "desc": "收支"},
            {"id": "industry_8_8", "path": "0808_9-7.html", "kind": "industry", "dual_header": True, "desc": "重点产业"},
        ],
        "debt": [
            {"id": "debt_2024", "url": "https://czj.gov.cn/d2024.htm", "year": "2024", "kind": "html"},
        ],
    }
    p = tmp_path / "industry_sources.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return str(p)


POP_HTML = """<table>
  <tr><th>3—4 主要年份年末常住人口及人口变动</th></tr>
  <tr><th>年份</th><th>常住人口 （万人）</th></tr>
  <tr><td>2024</td><td>891.4</td></tr>
</table>"""

DUAL_HTML = """<table>
  <tr><th>8—8 规模以上工业重点产业情况</th></tr>
  <tr><th>指标名称</th><th>2016</th><th></th></tr>
  <tr><th></th><th>企业单位数（个）</th><th>工业增加值增长（%）</th></tr>
  <tr><td>传统产业</td><td>3363</td><td>7.0</td></tr>
</table>"""

DEBT_HTML = """<html><body>
截至2024年底，全市政府债务余额预计执行数2661.16亿元，
债务余额严格控制在中央核定的限额2753.80亿元。
2024年全市新增政府债务限额348.01亿元。
</body></html>"""

TRADE_HTML = """<table>
  <tr><th colspan="7">12—3 历年进出口总额</th></tr>
  <tr><th>年份</th><th colspan="3">进出口总额（万美元）</th><th colspan="3">进出口总额（亿元）</th></tr>
  <tr><th></th><th>进出口总额</th><th>出口额</th><th>进口额</th><th>进出口总额</th><th>出口额</th><th>进口额</th></tr>
  <tr><td>2024</td><td></td><td></td><td></td><td>2363.79</td><td>1651.70</td><td>712.09</td></tr>
</table>"""

INCOME_HTML = """<table>
  <tr><th>4—7 全体居民人均收支情况</th></tr>
  <tr><th>单位：元</th></tr>
  <tr><th>指标名称</th><th>2024年</th><th>2023年</th></tr>
  <tr><td>一、可支配收入</td><td>52214</td><td>49486</td></tr>
  <tr><td>二、生活消费支出</td><td>33723</td><td>31638</td></tr>
</table>"""


def test_load_industry_sources(tmp_path):
    cfg_path = _cfg(tmp_path)
    cfg = load_industry_sources(cfg_path)
    assert cfg["region"] == "泉州市"
    assert cfg["yearbook_base"].endswith("/yb/")
    assert len(cfg["census"]) == 1
    assert len(cfg["yearbook_tables"]) == 4
    assert len(cfg["debt"]) == 1


def test_run_industry_sources_e2e(tmp_path):
    repo = _repo(tmp_path)
    cfg_path = _cfg(tmp_path)
    client = FakeClient({
        "https://tjj.gov.cn/c1.htm": POP_HTML,
        "https://tjj.gov.cn/yb/0304_3-4.html": POP_HTML,
        "https://tjj.gov.cn/yb/1203_12-3.html": TRADE_HTML,
        "https://tjj.gov.cn/yb/0407_4-7.html": INCOME_HTML,
        "https://tjj.gov.cn/yb/0808_9-7.html": DUAL_HTML,
        "https://czj.gov.cn/d2024.htm": DEBT_HTML,
    })
    stats = run_industry_sources(client, repo, cfg_path)
    assert stats["errors"] == 0
    # 人口 econ_series
    pop = repo.list_econ_series(source="pop_3_4")
    assert len(pop) >= 1
    assert pop[0]["value"] == "891.4"
    # 进出口（亿元口径 2024）
    tr = repo.list_econ_series(source="trade_12_3")
    by_note = {r["note"]: r for r in tr if r.get("year") == "2024"}
    assert by_note["出口额"]["value"] == "1651.70"
    assert by_note["进口额"]["value"] == "712.09"
    # 收支（2024 可支配收入）
    inc = repo.list_econ_series(source="income_4_7")
    income = [r for r in inc if "可支配收入" in (r.get("note") or "") and "消费" not in (r.get("note") or "")]
    assert income and income[0]["value"] == "52214"
    # 重点产业 industry_data（双列头）
    ind = repo.list_industry_data(source="industry_8_8")
    assert any(r["industry"] == "传统产业" and r["value"] == "3363" for r in ind)
    # 债务 econ_series
    debt = repo.list_econ_series(source="debt_2024")
    assert any(r["indicator"] == "debt_balance" and r["value"] == "2661.16" for r in debt)
    assert any(r["indicator"] == "debt_limit" and r["value"] == "2753.80" for r in debt)


def test_run_industry_sources_enterprise_classify(tmp_path):
    repo = _repo(tmp_path)
    # 预置企业
    repo.replace_enterprises(1, [
        {"year": "2025", "list_type": "上市后备", "name": "泉州银行股份有限公司", "county": "丰泽区", "rank": "1"},
        {"year": "2025", "list_type": "上市后备", "name": "福建利瑶纺织制衣有限公司", "county": "晋江市", "rank": "2"},
    ])
    cfg_path = _cfg(tmp_path)
    client = FakeClient({
        "https://tjj.gov.cn/c1.htm": POP_HTML,
        "https://tjj.gov.cn/yb/0304_3-4.html": POP_HTML,
        "https://tjj.gov.cn/yb/1203_12-3.html": TRADE_HTML,
        "https://tjj.gov.cn/yb/0407_4-7.html": INCOME_HTML,
        "https://tjj.gov.cn/yb/0808_9-7.html": DUAL_HTML,
        "https://czj.gov.cn/d2024.htm": DEBT_HTML,
    })
    stats = run_industry_sources(client, repo, cfg_path)
    ei = repo.list_enterprise_industry()
    by_id = {r["enterprise_id"]: r for r in ei}
    assert by_id[1]["industry"] == "金融"
    assert by_id[2]["industry"] == "纺织鞋服"


def test_run_industry_sources_error_isolated(tmp_path):
    repo = _repo(tmp_path)
    cfg_path = _cfg(tmp_path)
    client = FakeClient({
        "https://tjj.gov.cn/yb/0304_3-4.html": POP_HTML,
        "https://tjj.gov.cn/yb/1203_12-3.html": TRADE_HTML,
        "https://tjj.gov.cn/yb/0407_4-7.html": INCOME_HTML,
        "https://tjj.gov.cn/yb/0808_9-7.html": DUAL_HTML,
        # census 和 debt 缺失 → 报错但其余继续
    })
    stats = run_industry_sources(client, repo, cfg_path)
    assert stats["errors"] >= 2
    assert len(repo.list_econ_series(source="pop_3_4")) >= 1  # 其余正常