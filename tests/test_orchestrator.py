import json
import os
from app.store.db import init_db
from app.store.repository import Repository
from app.discovery.registry import Registry
from app.extract.rule_extractor import load_rules
from app.orchestrator import run_pipeline

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")
CFG = os.path.join(BASE, "..", "config")

class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping
    def get(self, url):
        if url in self.mapping:
            return self.mapping[url]
        raise Exception(f"no fixture {url}")

def test_pipeline(tmp_path):
    client = FakeClient({
        "https://www.stats.gov.cn/": open(os.path.join(FIX, "national_home.html"), encoding="utf-8").read(),
        "https://tjj.fujian.gov.cn/": open(os.path.join(FIX, "fujian_home.html"), encoding="utf-8").read(),
        "https://tjj.fujian.gov.cn/xxgk/tjgb/": open(os.path.join(FIX, "bulletin_2024.txt"), encoding="utf-8").read(),
        "https://tjj.fuzhou.gov.cn/": "<html><title>福州市统计局</title></html>",
        "https://tjj.zhangzhou.gov.cn/": "<html><title>漳州市统计局</title></html>",
        "https://tjj.sm.gov.cn/": "<html><title>三明市统计局</title></html>",
    })
    repo = Repository(init_db(str(tmp_path / "t.db")))
    registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
    rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    assert run["status"] in ("success", "partial")
    s = json.loads(run["summary_json"])
    assert s["bureaus"] >= 4
    assert s["values"] >= 1
    assert len(repo.list_bureaus()) >= 4
