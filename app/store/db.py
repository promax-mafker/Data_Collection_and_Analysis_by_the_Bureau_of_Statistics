import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS bureaus (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  region TEXT NOT NULL,
  parent_id INTEGER,
  verified INTEGER NOT NULL DEFAULT 0,
  discovered_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bureau_id INTEGER NOT NULL,
  url TEXT NOT NULL UNIQUE,
  title TEXT,
  content_text TEXT,
  dataset_type TEXT NOT NULL,
  period TEXT,
  content_hash TEXT,
  fetched_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  status TEXT NOT NULL DEFAULT 'fetched'
);
CREATE TABLE IF NOT EXISTS indicators (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  aliases TEXT,
  unit TEXT,
  category TEXT
);
CREATE TABLE IF NOT EXISTS data_values (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER,
  bureau_id INTEGER,
  region TEXT,
  year TEXT,
  indicator_name TEXT,
  value TEXT,
  unit TEXT,
  category TEXT,
  raw_text TEXT,
  method TEXT NOT NULL DEFAULT 'rule',
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  summary_json TEXT,
  log TEXT
);
CREATE TABLE IF NOT EXISTS doc_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER,
  source_id TEXT,
  kind TEXT,
  title TEXT,
  body TEXT,
  method TEXT NOT NULL DEFAULT 'llm',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS enterprises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER,
  year TEXT,
  list_type TEXT,
  name TEXT,
  county TEXT,
  rank TEXT
);
"""

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(path: str) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn

def _migrate(conn: sqlite3.Connection):
    """幂等迁移：旧库 pages 表无 doc_category 列时补列（旧行默认 bulletin）。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(pages)").fetchall()]
    if "doc_category" not in cols:
        conn.execute("ALTER TABLE pages ADD COLUMN doc_category TEXT NOT NULL DEFAULT 'bulletin'")
