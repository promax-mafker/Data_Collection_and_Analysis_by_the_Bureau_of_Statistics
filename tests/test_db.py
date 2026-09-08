"""db.py 迁移与新表测试：doc_category 列幂等迁移、doc_insights/enterprises 建表。"""
import sqlite3

from app.store.db import connect, init_db

OLD_SCHEMA = """
CREATE TABLE bureaus (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT NOT NULL, name TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
  region TEXT NOT NULL, parent_id INTEGER, verified INTEGER NOT NULL DEFAULT 0,
  discovered_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bureau_id INTEGER NOT NULL, url TEXT NOT NULL UNIQUE, title TEXT,
  content_text TEXT, dataset_type TEXT NOT NULL, period TEXT,
  content_hash TEXT,
  fetched_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  status TEXT NOT NULL DEFAULT 'fetched'
);
CREATE TABLE indicators (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE, aliases TEXT, unit TEXT, category TEXT
);
CREATE TABLE data_values (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER, bureau_id INTEGER, region TEXT, year TEXT,
  indicator_name TEXT, value TEXT, unit TEXT, category TEXT,
  raw_text TEXT, method TEXT NOT NULL DEFAULT 'rule',
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  finished_at TEXT, status TEXT NOT NULL DEFAULT 'running',
  summary_json TEXT, log TEXT
);
"""


def _old_lib_db(tmp_path):
    """构造一个旧版（无 doc_category）库，并插入一行旧 pages 数据。"""
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.execute(
        "INSERT INTO pages (bureau_id, url, dataset_type, period) VALUES (1, 'http://old/', 'bulletin', '2024')")
    con.commit()
    con.close()
    return path


def test_doc_category_column_added_to_old_db(tmp_path):
    path = _old_lib_db(tmp_path)
    conn = init_db(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()]
    assert "doc_category" in cols
    row = conn.execute("SELECT doc_category FROM pages WHERE url='http://old/'").fetchone()
    assert row[0] == "bulletin"  # 旧行默认 bulletin


def test_init_db_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path)
    init_db(path)  # 第二次不报错
    conn = connect(path)
    assert conn.execute("SELECT count(*) FROM doc_insights").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM enterprises").fetchone()[0] == 0


def test_doc_insights_table_columns(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(doc_insights)").fetchall()]
    for expect in ("id", "page_id", "source_id", "kind", "title", "body", "method", "created_at"):
        assert expect in cols


def test_enterprises_table_columns(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(enterprises)").fetchall()]
    for expect in ("id", "page_id", "year", "list_type", "name", "county", "rank"):
        assert expect in cols


def test_industry_data_table_columns(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(industry_data)").fetchall()]
    for expect in ("id", "source", "industry", "year", "metric", "value", "unit", "raw_text"):
        assert expect in cols


def test_econ_series_table_columns(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(econ_series)").fetchall()]
    for expect in ("id", "source", "indicator", "year", "value", "unit", "note", "raw_text"):
        assert expect in cols


def test_enterprise_industry_table_columns(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(enterprise_industry)").fetchall()]
    for expect in ("enterprise_id", "industry", "method"):
        assert expect in cols


def test_m6_tables_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    init_db(path)
    init_db(path)
    conn = connect(path)
    for t in ("industry_data", "econ_series", "enterprise_industry"):
        assert conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0


# ---------- M7a: caliber/source_url(region/period) 迁移与 PRAGMA ----------

MID_SCHEMA = OLD_SCHEMA + """
CREATE TABLE doc_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER, source_id TEXT, kind TEXT, title TEXT,
  body TEXT, method TEXT NOT NULL DEFAULT 'llm',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def _mid_lib_db(tmp_path):
    """次旧版库：有 doc_category(通过 init 两次模拟)但 data_values/doc_insights 无新列。

    直接手工按 MID_SCHEMA 建表并插入关联行。
    """
    path = str(tmp_path / "mid.db")
    con = sqlite3.connect(path)
    con.executescript(MID_SCHEMA)
    con.executescript("""
    ALTER TABLE pages ADD COLUMN doc_category TEXT NOT NULL DEFAULT 'bulletin';
    INSERT INTO bureaus (level, name, url, region) VALUES ('city', '泉州市统计局', 'http://qz/', '泉州市');
    INSERT INTO pages (bureau_id, url, title, dataset_type, period, doc_category)
      VALUES (1, 'http://qz/budget', '2026预算', 'topic', '2026', 'budget');
    INSERT INTO pages (bureau_id, url, title, dataset_type, period, doc_category)
      VALUES (1, 'http://qz/bulletin', '2025公报', 'bulletin', '2025', 'bulletin');
    INSERT INTO data_values (page_id, bureau_id, region, year, indicator_name, value, unit, raw_text)
      VALUES (1, 1, '泉州市', '2026', '一般公共预算收入', '355.92', '亿元', 'x');
    INSERT INTO data_values (page_id, bureau_id, region, year, indicator_name, value, unit, raw_text)
      VALUES (2, 1, '泉州市', '2025', '地区生产总值', '13778.34', '亿元', 'y');
    INSERT INTO doc_insights (page_id, kind, title, body) VALUES (2, 'industry', 't', '{}');
    """)
    con.commit()
    con.close()
    return path


def test_data_values_has_caliber_and_source_url(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(data_values)").fetchall()]
    assert "caliber" in cols
    assert "source_url" in cols


def test_doc_insights_has_region_period(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(doc_insights)").fetchall()]
    assert "region" in cols
    assert "period" in cols


def test_mid_lib_upgrade_backfills_budget_caliber(tmp_path):
    path = _mid_lib_db(tmp_path)
    conn = init_db(path)  # 触发迁移
    rows = {r["indicator_name"]: r["caliber"] for r in
            conn.execute("SELECT indicator_name, caliber FROM data_values").fetchall()}
    assert rows["一般公共预算收入"] == "budget"   # budget 页行 → budget
    assert rows["地区生产总值"] == "final"        # 默认 final


def test_mid_lib_upgrade_backfills_insight_region(tmp_path):
    path = _mid_lib_db(tmp_path)
    conn = init_db(path)
    row = conn.execute("SELECT region FROM doc_insights WHERE kind='industry'").fetchone()
    assert row[0] == "泉州市"   # 经 page → bureau.region 回填


def test_wal_and_busy_timeout_pragmas(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
    bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert bt == 30000
