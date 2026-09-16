"""CELMA 地方政府债券公开 API 适配器测试（M9c）。

实测：`https://www.governbond.org.cn:4443/api/loadBondData.action`
`?dataType=FDQNDZB&zb=060101`（一般债务余额）/ `060102`（专项债务余额）
→ HTTP 200、402 条，字段 `{AD_CODE, AD_NAME, SET_YEAR, ZB_ID, AMOUNT}`，无鉴权。
⚠ 该站证书链异常，请求须 `verify=False`。
⚠ **只到省级**（31 省 + 计划单列市），泉州等地级市拿不到 —— 如实标注，不假装覆盖。
"""
import json
import os

from app.fetch.celma import ZB_GENERAL, ZB_SPECIAL, ingest_celma, parse_celma
from app.store.db import init_db
from app.store.repository import Repository

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fx(zb):
    with open(os.path.join(FIX, f"celma_{zb}.json"), encoding="utf-8") as f:
        return json.load(f)


def test_parse_celma_extracts_fujian_general_debt():
    rows = parse_celma(_fx(ZB_GENERAL), region_name="福建省")
    assert rows
    assert all(r["indicator"] == "debt_general" for r in rows)
    assert all(r["unit"] == "亿元" for r in rows)
    d = {r["year"]: r["value"] for r in rows}
    assert abs(d["2019"] - 2755.86) < 0.01
    assert min(int(y) for y in d) <= 2017, "应覆盖较早年份"


def test_parse_celma_special_debt():
    rows = parse_celma(_fx(ZB_SPECIAL), region_name="福建省")
    assert all(r["indicator"] == "debt_special" for r in rows)
    d = {r["year"]: r["value"] for r in rows}
    assert abs(d["2025"] - 12016.76) < 0.01


def test_parse_celma_ignores_other_regions():
    """只取目标省级地区 —— 其余 400 条不得混入。"""
    rows = parse_celma(_fx(ZB_GENERAL), region_name="福建省")
    assert 0 < len(rows) < 40, f"福建应只有十余年记录，实得 {len(rows)}"


def test_parse_celma_is_robust_to_empty_and_malformed():
    assert parse_celma({"code": 0, "data": []}) == []
    assert parse_celma({}) == []
    assert parse_celma({"data": [{"AD_NAME": "福建省", "SET_YEAR": "无", "AMOUNT": "x"}]}) == []


def test_ingest_celma_writes_econ_series():
    repo = Repository(init_db(":memory:"))
    n = ingest_celma(repo, [(_fx(ZB_GENERAL), ZB_GENERAL), (_fx(ZB_SPECIAL), ZB_SPECIAL)],
                     region_name="福建省")
    assert n > 10
    got = {r["indicator"] for r in repo.list_econ_series()}
    assert {"debt_general", "debt_special"} <= got
    yrs = {r["year"] for r in repo.list_econ_series(indicator="debt_special")}
    assert "2025" in yrs


def test_ingest_celma_notes_scope_limitation():
    """必须把「仅省级」写进 note —— 否则后续会误以为泉州也有分项数据。"""
    repo = Repository(init_db(":memory:"))
    ingest_celma(repo, [(_fx(ZB_GENERAL), ZB_GENERAL)], region_name="福建省")
    notes = {r["note"] for r in repo.list_econ_series()}
    assert any("省级" in (n or "") for n in notes)
