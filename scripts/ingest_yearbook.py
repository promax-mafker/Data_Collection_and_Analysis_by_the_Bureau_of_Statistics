"""年鉴采集 CLI（M9b）。

用法::

    .venv\\Scripts\\python scripts\\ingest_yearbook.py                # 用默认配置
    .venv\\Scripts\\python scripts\\ingest_yearbook.py --config ...   # 指定配置
    .venv\\Scripts\\python scripts\\ingest_yearbook.py --years 2020-2025
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def _parse_years(spec):
    """``'2020-2025'`` → ``[2020, ..., 2025]``；空 → None（用配置里的）。"""
    if not spec:
        return None
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def main():
    ap = argparse.ArgumentParser(description="统计年鉴采集（M9b）")
    ap.add_argument("--config", default=os.path.join(BASE, "config", "yearbook_volumes.yaml"))
    ap.add_argument("--db", default=os.path.join(BASE, "data", "stats.db"))
    ap.add_argument("--years", default="", help="覆盖配置年份，如 2020-2025")
    args = ap.parse_args()

    from app.fetch.client import HttpClient
    from app.fetch.yearbook import ingest_yearbook, load_yearbook_config
    from app.store.db import init_db
    from app.store.repository import Repository

    cfg = load_yearbook_config(args.config)
    years = _parse_years(args.years)
    if years:
        cfg["years"] = years

    client = HttpClient(timeout=40, retries=1, delay=0.3)
    repo = Repository(init_db(args.db))
    stats = ingest_yearbook(client, repo, cfg, logger=lambda m: print(m, flush=True))

    print(json.dumps({k: v for k, v in stats.items() if k != "rejected_detail"},
                     ensure_ascii=False, indent=2))
    if stats["rejected_detail"]:
        print(f"\n拒绝入库（单位无法换算等）前 10 条，共 {stats['rejected']}:")
        for line in stats["rejected_detail"][:10]:
            print("  - " + line)


if __name__ == "__main__":
    main()
