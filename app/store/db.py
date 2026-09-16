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
  caliber TEXT NOT NULL DEFAULT 'final',
  source_url TEXT NOT NULL DEFAULT '',
  source_kind TEXT NOT NULL DEFAULT '',
  source_rank INTEGER NOT NULL DEFAULT 1,
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
  region TEXT NOT NULL DEFAULT '',
  period TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS industry_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,
  industry TEXT,
  year TEXT,
  metric TEXT,
  value TEXT,
  unit TEXT,
  raw_text TEXT,
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS econ_series (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,
  indicator TEXT,
  year TEXT,
  value TEXT,
  unit TEXT,
  note TEXT,
  raw_text TEXT,
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS enterprise_industry (
  enterprise_id INTEGER PRIMARY KEY,
  industry TEXT,
  method TEXT
);
"""

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db(path: str) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn

def _table_cols(conn: sqlite3.Connection, table: str) -> list:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

def _migrate(conn: sqlite3.Connection):
    """幂等迁移：
    1) 旧库 pages 表无 doc_category 列时补列（旧行默认 bulletin）。
    2) data_values 补 caliber/source_url（M7a 口径维度）。
    3) doc_insights 补 region/period（M7a 区域隔离）。
    4) data_values 补 source_kind/source_rank（M9b 多源维度）。
    5) 建/重建 data_values_primary 主源视图（M9b §5.2）。
    6) 回填：budget 页数值行 caliber='budget'；洞察 region 按 page→bureau。
    """
    # 1) pages.doc_category
    if "doc_category" not in _table_cols(conn, "pages"):
        conn.execute("ALTER TABLE pages ADD COLUMN doc_category TEXT NOT NULL DEFAULT 'bulletin'")
    # 2) data_values 口径列
    dv_cols = _table_cols(conn, "data_values")
    if "caliber" not in dv_cols:
        conn.execute("ALTER TABLE data_values ADD COLUMN caliber TEXT NOT NULL DEFAULT 'final'")
    if "source_url" not in dv_cols:
        conn.execute("ALTER TABLE data_values ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
    # 4) data_values 来源列（M9b）
    if "source_kind" not in dv_cols:
        conn.execute("ALTER TABLE data_values ADD COLUMN source_kind TEXT NOT NULL DEFAULT ''")
    if "source_rank" not in dv_cols:
        conn.execute("ALTER TABLE data_values ADD COLUMN source_rank INTEGER NOT NULL DEFAULT 1")
    # 3) doc_insights 区域列
    di_cols = _table_cols(conn, "doc_insights")
    if "region" not in di_cols:
        conn.execute("ALTER TABLE doc_insights ADD COLUMN region TEXT NOT NULL DEFAULT ''")
    if "period" not in di_cols:
        conn.execute("ALTER TABLE doc_insights ADD COLUMN period TEXT NOT NULL DEFAULT ''")
    # 5) 主源视图：同一 (region, year, indicator_name, caliber) 只保留一行，
    #    按 source_rank 升序（1=统计局公报/年鉴主源）→ extracted_at 最新 → id 最大。
    #    用 IS 比较以正确处理 NULL。视图在 ALTER 之后创建，故旧库升级也安全。
    #    必须重建（DROP + CREATE）以便视图定义可随版本演进。
    conn.execute("DROP VIEW IF EXISTS data_values_primary")
    conn.execute("""
        CREATE VIEW data_values_primary AS
        SELECT dv.* FROM data_values dv
        WHERE dv.id = (
          SELECT x.id FROM data_values x
          WHERE x.region IS dv.region
            AND x.year IS dv.year
            AND x.indicator_name IS dv.indicator_name
            AND x.caliber IS dv.caliber
          ORDER BY x.source_rank ASC, x.extracted_at DESC, x.id DESC
          LIMIT 1
        )
    """)
    # 6) 回填（幂等）
    conn.execute(
        "UPDATE data_values SET caliber='budget' "
        "WHERE page_id IN (SELECT id FROM pages WHERE doc_category='budget')")
    conn.execute(
        "UPDATE doc_insights SET region="
        "(SELECT b.region FROM pages p JOIN bureaus b ON b.id=p.bureau_id WHERE p.id=doc_insights.page_id) "
        "WHERE region='' AND page_id IN (SELECT id FROM pages)")
