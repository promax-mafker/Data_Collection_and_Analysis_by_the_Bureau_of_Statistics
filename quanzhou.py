"""泉州画像 CLI：采集泉州政府公开文档 → 分析 → 渲染画像报告。"""
import os
import sys

from app.store.db import init_db
from app.store.repository import Repository
from app.fetch.client import HttpClient
from app.fetch.documents import load_sources, run_documents
from app.extract.llm_client import LLMClient
from app.analysis.quanzhou import analyze_quanzhou
from app.analysis.report import render_quanzhou_markdown, render_quanzhou_html, write_quanzhou_report


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base, "data", "stats.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    repo = Repository(init_db(db_path))
    client = HttpClient()
    llm = LLMClient()

    sources_path = os.path.join(base, "config", "quanzhou_sources.yaml")
    region, sources = load_sources(sources_path)

    print(f"开始采集泉州政府公开文档（{len(sources)} 源，LLM 启用={llm.enabled}）…")
    stats = run_documents(client, repo, sources, llm_client=llm, region=region)
    print(f"采集完成: pages={stats['pages']} values={stats['values']} "
          f"insights={stats['insights']} enterprises={stats['enterprises']} "
          f"errors={stats['errors']}")

    if "--sources-only" in sys.argv:
        return

    profile = analyze_quanzhou(repo)
    md = render_quanzhou_markdown(profile)
    html = render_quanzhou_html(profile)
    out_dir = os.path.join(base, "data", "reports")
    path = write_quanzhou_report(out_dir, profile, md, html)
    print(f"画像报告: {path}")
    # 摘要
    f = profile["fiscal"]
    print(f"财政: 收入 {f['revenue']} 支出 {f['expenditure']} "
          f"自给率 {f['self_sufficiency']}% 土地依赖 {f['land_dependence']}%")
    print(f"市场主体: 2025 上市后备 {profile['market'].get('total_2025')} 家，"
          f"HHI {profile['market'].get('hhi')}")
    print(f"可信度: checks={len(profile['credibility']['checks'])} "
          f"critiques={len(profile['credibility']['critiques'])} "
          f"escalated={len(profile['credibility']['escalated'])}")


if __name__ == "__main__":
    main()
