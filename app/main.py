import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .store.db import init_db
from .store.repository import Repository
from .discovery.registry import Registry
from .extract.rule_extractor import load_rules
from .fetch.client import HttpClient
from .orchestrator import run_pipeline

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
def api_data(region: str = None, indicator: str = None, year: str = None):
    return build_repo().query_data(region, indicator, year)

@app.get("/api/export")
def api_export(region: str = None, year: str = None):
    csv_text = build_repo().export_csv(region, year)
    return PlainTextResponse(csv_text, media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=stats.csv"})

app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "app", "web", "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
