import os
from app.store.db import init_db
from app.store.repository import Repository
from app.discovery.registry import Registry
from app.extract.rule_extractor import load_rules
from app.fetch.client import HttpClient
from app.orchestrator import run_pipeline

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base, "data", "stats.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    repo = Repository(init_db(db_path))
    registry = Registry.load(os.path.join(base, "config", "bureaus.yaml"))
    rules = load_rules(os.path.join(base, "config", "extract_rules.yaml"))
    client = HttpClient()
    print("开始一键采集（国家 → 福建 → 地级市）…")
    run_id = run_pipeline(client, repo, registry, rules)
    run = repo.get_run(run_id)
    print(f"完成 run_id={run_id} status={run['status']}")
    print(run["summary_json"])
    print(run["log"])

if __name__ == "__main__":
    main()
