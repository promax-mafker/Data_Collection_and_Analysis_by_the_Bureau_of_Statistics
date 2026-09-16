"""国家统计局新版 API 适配器测试（M9c），真实响应夹具驱动。"""
import json
import os

from app.fetch.nbs_api import _split_unit, _year, ingest_nbs, parse_default_series
from app.store.db import init_db
from app.store.repository import Repository

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _fx():
    with open(os.path.join(FIX, "nbs_default_series.json"), encoding="utf-8") as f:
        return json.load(f)


def test_year_and_unit_helpers():
    assert _year("2015年") == "2015"
    assert _year("2025") == "2025"
    assert _year("无") == ""
    assert _split_unit("旅客运输量 (万人)") == ("旅客运输量", "万人")
    assert _split_unit("货物进出口总额（百万美元）") == ("货物进出口总额", "百万美元")
    assert _split_unit("无单位指标") == ("无单位指标", "")


def test_parse_real_fixture():
    rows = parse_default_series(_fx())
    assert rows, "真实响应应解析出序列"
    assert all(r["values"] for r in rows)
    names = {r["indicator"] for r in rows}
    assert any("旅客运输量" in n for n in names), f"实得 {sorted(names)[:5]}"


def test_parse_aligns_years_and_values():
    rows = parse_default_series(_fx())
    tr = [r for r in rows if "旅客运输量" in r["indicator"]]
    assert tr, "应含旅客运输量序列"
    v = tr[0]["values"]
    assert v.get("2015") == "62849", f"实得 {v.get('2015')}"
    assert tr[0]["unit"] == "万人"
    assert tr[0]["catalog"] == "运输量"


def test_malformed_payload_is_safe():
    assert parse_default_series({}) == []
    assert parse_default_series({"data": []}) == []
    assert parse_default_series({"data": [{"xData": ["2024年"], "yData": [{}]}]}) == []
    # 缺值不得填 0
    got = parse_default_series({"data": [{"catalogName": "c", "xData": ["2024年", "2025年"],
                                          "yData": [{"name": "x (亿元)", "value": ["1", "—"]}]}]})
    assert got[0]["values"] == {"2024": "1"}


def test_ingest_writes_econ_series_with_scope_note(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    n = ingest_nbs(repo, [_fx()])
    assert n > 0
    rows = repo.list_econ_series(source="nbs_api")
    assert rows and all("省级" in (r["note"] or "") for r in rows)
