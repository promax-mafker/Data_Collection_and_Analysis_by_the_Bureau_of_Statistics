import os
import sys

from app.analysis.core import analyze
from app.analysis.report import render_html, render_markdown, write_reports
from app.store.db import init_db
from app.store.repository import Repository


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    db_path = os.environ.get("STATS_DB", os.path.join(base, "data", "stats.db"))
    if not os.path.exists(db_path):
        print("未找到数据库，请先运行 `python run.py` 完成采集。")
        sys.exit(1)
    repo = Repository(init_db(db_path))
    out_dir = os.path.join(base, "data", "reports")
    result = analyze(repo)
    md = render_markdown(result)
    html = render_html(result)
    path = write_reports(out_dir, result, md, html)
    print(f"分析完成：参考年度 {result.get('reference_year')}")
    print(f"HTML 报告：{path}")
    print(f"Markdown ：{os.path.join(out_dir, 'report.md')}")
    print(f"CSV 目录 ：{os.path.join(out_dir, 'csv')}")


if __name__ == "__main__":
    main()
