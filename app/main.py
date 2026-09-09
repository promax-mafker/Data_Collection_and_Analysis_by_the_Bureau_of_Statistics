import csv
import io
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .store.db import init_db
from .store.repository import Repository
from .discovery.registry import Registry
from .extract.rule_extractor import load_rules
from .extract.llm_client import LLMClient
from .fetch.client import HttpClient
from .fetch.documents import load_sources, run_documents
from .orchestrator import run_pipeline
from .analysis.core import analyze
from .analysis.quanzhou import analyze_quanzhou
from .analysis.report import (render_html, render_markdown,
                              render_quanzhou_markdown, render_quanzhou_html)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("STATS_DB", os.path.join(BASE_DIR, "data", "stats.db"))
CONFIG_DIR = os.path.join(BASE_DIR, "config")

app = FastAPI(title="统计局数据采集平台")

def build_repo():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return Repository(init_db(DB_PATH))

def build_components():
    registry = Registry.load(os.path.join(CONFIG_DIR, "bureaus.yaml"))
    rules = load_rules(os.path.join(CONFIG_DIR, "extract_rules.yaml"))
    client = HttpClient()
    return registry, rules, client

@app.post("/api/run")
def api_run():
    repo = build_repo()
    registry, rules, client = build_components()
    run_id = run_pipeline(client, repo, registry, rules)
    return {"run_id": run_id, "run": repo.get_run(run_id)}

@app.get("/api/runs")
def api_runs():
    return build_repo().list_runs()

@app.get("/api/runs/{run_id}")
def api_run_detail(run_id: int):
    run = build_repo().get_run(run_id)
    if not run:
        raise HTTPException(404, "not found")
    return run

@app.get("/api/bureaus")
def api_bureaus():
    return build_repo().list_bureaus()

@app.get("/api/data")
def api_data(region: str = None, indicator: str = None, year: str = None, text: str = None):
    """数据查询：text 整句自然查询；否则三个精确条件（均走宽容解析）。"""
    repo = build_repo()
    if text:
        return repo.query_text(text)
    return repo.query_lax(region, indicator, year)

@app.get("/api/filters")
def api_filters():
    """查询候选：地区 / 指标 / 年份去重列表（供前端提示）。"""
    repo = build_repo()
    rows = repo.query_data()
    regions, indicators, years = [], [], []
    for r in rows:
        if r.get("region") and r["region"] not in regions:
            regions.append(r["region"])
        if r.get("indicator_name") and r["indicator_name"] not in indicators:
            indicators.append(r["indicator_name"])
        if r.get("year") and r["year"] not in years:
            years.append(r["year"])
    return {"regions": sorted(regions), "indicators": sorted(indicators),
            "years": sorted(years)}

@app.get("/api/export")
def api_export(region: str = None, indicator: str = None, year: str = None, text: str = None):
    repo = build_repo()
    if text:
        res = repo.query_text(text)
    else:
        res = repo.query_lax(region, indicator, year)
    rows = res["rows"]
    out = io.StringIO()
    if rows:
        w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return PlainTextResponse(out.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=stats.csv"})

@app.get("/api/analysis")
def api_analysis(format: str = "html"):
    result = analyze(build_repo())
    if format == "md":
        return PlainTextResponse(render_markdown(result),
                                 media_type="text/markdown; charset=utf-8")
    return HTMLResponse(render_html(result))

# ---------- M5 泉州画像 ----------

def _quanzhou_components():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return (os.path.join(base, "config", "quanzhou_sources.yaml"),
            os.path.join(CONFIG_DIR, "extract_rules.yaml"))

@app.post("/api/quanzhou/run")
def api_quanzhou_run():
    """采集泉州政府公开文档 → 分析（同步执行）。"""
    repo = build_repo()
    client = HttpClient()
    llm = LLMClient()
    sources_path, rules_path = _quanzhou_components()
    region, sources = load_sources(sources_path)
    rules = load_rules(rules_path)
    stats = run_documents(client, repo, sources, rules=rules,
                          llm_client=llm, region=region)
    profile = analyze_quanzhou(repo)
    md = render_quanzhou_markdown(profile)
    html = render_quanzhou_html(profile)
    out_dir = os.path.join(BASE_DIR, "data", "reports")
    from .analysis.report import write_quanzhou_report
    path = write_quanzhou_report(out_dir, profile, md, html)
    return {"stats": stats, "llm_enabled": llm.enabled, "report": path,
            "profile": profile}

@app.get("/api/quanzhou/status")
def api_quanzhou_status():
    repo = build_repo()
    pages = repo.list_pages()
    by_cat = {}
    for p in pages:
        c = p.get("doc_category") or "bulletin"
        by_cat[c] = by_cat.get(c, 0) + 1
    return {
        "pages": by_cat,
        "doc_insights": len(repo.list_doc_insights()),
        "critiques": len(repo.list_doc_insights(kind="critique", region="泉州市")),
        "enterprises": len(repo.list_enterprises()),
        "fiscal_values": len(repo.query_data(region="泉州市", indicator="一般公共预算收入",
                                             caliber="final")),
        "llm_enabled": LLMClient().enabled,
    }

@app.get("/api/quanzhou/report")
def api_quanzhou_report(format: str = "html"):
    repo = build_repo()
    profile = analyze_quanzhou(repo)
    if format == "md":
        return PlainTextResponse(render_quanzhou_markdown(profile),
                                 media_type="text/markdown; charset=utf-8")
    return HTMLResponse(render_quanzhou_html(profile))

@app.get("/api/quanzhou/economy")
def api_quanzhou_economy():
    """M6 经济驱动画像（Kami Parchment HTML）。"""
    from .analysis.economy_report import render_economy_report
    return HTMLResponse(render_economy_report(build_repo()))

@app.get("/api/quanzhou/tree")
def api_quanzhou_tree():
    """M8 决策树方法论体检（JSON 裁决）。"""
    from .analysis.decision_tree import tree_audit
    return tree_audit(build_repo(), region="泉州市")

app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "app", "web", "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
