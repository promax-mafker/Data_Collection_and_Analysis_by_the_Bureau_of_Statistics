"""documents.py 源注册表加载 + run_documents 编排测试。"""
import os

import pytest

from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import Page
from app.fetch.documents import load_sources, run_documents

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YAML_PATH = os.path.join(BASE, "config", "quanzhou_sources.yaml")

REQUIRED = ("id", "name", "category", "url", "kind", "period", "parse")


class FakeClient:
    """按 URL 返回 fixture 内容。"""
    def __init__(self, mapping):
        self.mapping = mapping  # url -> (kind, bytes|str)

    def download(self, url):
        kind, content = self.mapping[url]
        if kind == "bytes":
            return content if isinstance(content, bytes) else content.encode("utf-8")
        return content.encode("utf-8")


RULES = []
RULE_DEFS = []  # run_documents 需要完整规则列表？测试用空列表+extract_named 内部无规则


def _repo(tmp_path):
    return Repository(init_db(str(tmp_path / "t.db")))


def test_load_real_yaml():
    region, sources = load_sources(YAML_PATH)
    assert region == "泉州市"
    assert len(sources) >= 6
    ids = [s["id"] for s in sources]
    assert "plan_15" in ids and "enterprises_2025" in ids and "bulletin_2025" in ids


def test_required_fields_present():
    _, sources = load_sources(YAML_PATH)
    for s in sources:
        for field in REQUIRED:
            assert s.get(field), f"source {s.get('id')} 缺字段 {field}"
        assert s["url"].startswith("http"), f"source {s['id']} url 非法"
        assert s["category"] in ("plan", "gov_report", "budget", "enterprise", "bulletin")
        assert s["parse"] in ("rule", "llm", "rule+llm", "table")


def test_ids_unique():
    _, sources = load_sources(YAML_PATH)
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_sources(str(tmp_path / "nope.yaml"))


# ---------- run_documents ----------

ENTERPRISE_HTML = """
<html><body>
<p>170家入选！泉州市市级上市和挂牌后备企业名单公布</p>
<table>
  <tr><th>序号</th><th>企业名称</th><th>县（市、区）</th><th>名单类型</th></tr>
  <tr><td>1</td><td>恒安集团</td><td>晋江市</td><td>上市后备</td></tr>
  <tr><td>2</td><td>安踏体育</td><td>晋江市</td><td>上市后备</td></tr>
</table>
</body></html>
"""

BUDGET_HTML = """
<html><body>
2026年上半年全市地方一般公共预算收入 355.92 亿元，税收收入 204.02 亿元，
政府性基金收入 105.3 亿元。
</body></html>
"""

REPORT_HTML = """
<html><body>
<h1>2026年泉州市政府工作报告</h1>
<p>全市地区生产总值增长5%左右。新增城镇就业8万人。实施制造业强市战略。</p>
</body></html>
"""


def _sources(tmp_path):
    """构造 3 个临时源（覆盖 rule / table / llm）。"""
    import yaml
    path = tmp_path / "sources.yaml"
    d = {
        "region": "泉州市",
        "sources": [
            {"id": "exec", "name": "预算执行", "category": "budget", "kind": "html",
             "url": "http://t1/budget", "period": "2026", "parse": "rule",
             "numeric_rules": ["地方一般公共预算收入", "税收收入", "政府性基金收入"]},
            {"id": "ent", "name": "企业名单", "category": "enterprise", "kind": "html",
             "url": "http://t1/ent", "period": "2025", "parse": "table"},
            {"id": "rep", "name": "政府工作报告", "category": "gov_report", "kind": "html",
             "url": "http://t1/report", "period": "2026", "parse": "llm", "chunk": "full"},
        ],
    }
    path.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return load_sources(str(path))[1]


class FakeLLM:
    def __init__(self):
        self.enabled = True
        self.calls = 0

    def complete_json(self, system, user, temperature=None):
        self.calls += 1
        return {"industries": [{"industry": "纺织鞋服", "plan_role": "支柱",
                                "evidence": "实施制造业强市战略"}]}


def test_run_documents_rule_table_llm(tmp_path):
    repo = _repo(tmp_path)
    client = FakeClient({
        "http://t1/budget": ("html", BUDGET_HTML),
        "http://t1/ent": ("html", ENTERPRISE_HTML),
        "http://t1/report": ("html", REPORT_HTML),
    })
    fake_llm = FakeLLM()
    sources = _sources(tmp_path)
    stats = run_documents(client, repo, sources, rules=None, llm_client=fake_llm, region="泉州市")
    assert stats["errors"] == 0
    assert stats["pages"] == 3
    # rule 页数值入库
    rows = repo.query_data(region="泉州市", indicator="税收收入", year="2026")
    assert len(rows) == 1 and rows[0]["value"] == "204.02"
    # 页面 doc_category 正确
    cats = {p["doc_category"] for p in repo.list_pages()}
    assert cats == {"budget", "enterprise", "gov_report"}
    # enterprise 页
    ents = repo.list_enterprises(year="2025")
    assert len(ents) == 2
    assert ents[0]["name"] == "恒安集团" and ents[0]["county"] == "晋江市"
    # llm 页洞察
    insights = repo.list_doc_insights()
    assert fake_llm.calls >= 1
    assert len(insights) >= 1


def test_run_documents_without_llm_skips_llm_pages(tmp_path):
    repo = _repo(tmp_path)
    client = FakeClient({
        "http://t1/budget": ("html", BUDGET_HTML),
        "http://t1/ent": ("html", ENTERPRISE_HTML),
        "http://t1/report": ("html", REPORT_HTML),
    })
    sources = _sources(tmp_path)
    stats = run_documents(client, repo, sources, rules=None, llm_client=None, region="泉州市")
    # llm 页采集成功但无洞察（不报错）
    assert stats["errors"] == 0
    assert repo.list_doc_insights() == []
    # 规则页仍入库
    assert len(repo.query_data(indicator="税收收入")) == 1


def test_run_documents_dedup_repeat(tmp_path):
    """重复运行同一源 → 页面刷新不重复累积数值。"""
    repo = _repo(tmp_path)
    client = FakeClient({
        "http://t1/budget": ("html", BUDGET_HTML),
        "http://t1/ent": ("html", ENTERPRISE_HTML),
        "http://t1/report": ("html", REPORT_HTML),
    })
    sources = _sources(tmp_path)
    fake_llm = FakeLLM()
    run_documents(client, repo, sources, rules=None, llm_client=fake_llm, region="泉州市")
    run_documents(client, repo, sources, rules=None, llm_client=fake_llm, region="泉州市")
    assert len(repo.list_pages()) == 3  # URL upsert 不新增
    assert len(repo.query_data(indicator="税收收入")) == 1  # 整页替换不累积
    assert len(repo.list_enterprises()) == 2


def test_run_documents_error_isolated(tmp_path):
    """单个源失败不影响其他源。"""
    repo = _repo(tmp_path)
    client = FakeClient({"http://t1/budget": ("html", BUDGET_HTML)})
    sources = _sources(tmp_path)  # 3 个源，client 只有 budget
    stats = run_documents(client, repo, sources, rules=None, llm_client=None, region="泉州市")
    assert stats["errors"] == 2
    assert stats["pages"] == 1
    assert len(repo.query_data(indicator="税收收入")) == 1

