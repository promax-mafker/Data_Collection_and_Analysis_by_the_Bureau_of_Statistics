import csv
import io
import json
import re

# 指标常见别名（小写归一后查表）
INDICATOR_ALIASES = {
    "gdp": "地区生产总值",
    "gross domestic product": "地区生产总值",
}

_YEAR_RE = re.compile(r"(\d{4})")


def _unique_or_warn(q, hits):
    """hits 唯一则返回该候选，否则返回 (None, 歧义警告)。"""
    if len(hits) == 1:
        return hits[0], None
    shown = "、".join(hits[:6])
    return None, f"「{q}」命中多个候选（{shown}…），请精确输入"


def resolve_region(q, regions):
    """把用户自然输入解析为库内精确地区名。

    支持：精确、剥上级前缀（「福建省莆田市」→「莆田市」）、
    后缀补全（「莆田」→「莆田市」）、包含匹配。
    返回 (region_or_None, warning_or_None)。
    """
    q = (q or "").strip()
    if not q:
        return None, None
    if q in regions:
        return q, None
    # 剥上级前缀：查询以某地区名结尾（如 福建省莆田市 以 莆田市 结尾）
    tails = [c for c in regions if len(c) < len(q) and q.endswith(c) and len(c) >= 2]
    if tails:
        return max(tails, key=len), None
    # 后缀补全：候选以查询开头（莆田 → 莆田市）
    heads = [c for c in regions if len(c) > len(q) and c.startswith(q)]
    if heads:
        return _unique_or_warn(q, heads)
    # 双向包含兜底
    if len(q) >= 2:
        inside = [c for c in regions if q in c or c in q]
        if inside:
            return _unique_or_warn(q, inside)
    return None, f"未识别地区「{q}」（候选：{'、'.join(regions)}）"


def resolve_indicator(q, indicators):
    """解析指标输入：别名 / 精确 / 前缀补全 / 包含。"""
    q = (q or "").strip()
    if not q:
        return None, None
    alias = INDICATOR_ALIASES.get(q.lower())
    if alias and alias in indicators:
        return alias, None
    if q in indicators:
        return q, None
    heads = [c for c in indicators if len(c) > len(q) and c.startswith(q)]
    if heads:
        return _unique_or_warn(q, heads)
    if len(q) >= 2:
        inside = [c for c in indicators if q in c or c in q]
        if inside:
            return _unique_or_warn(q, inside)
    return None, f"未识别指标「{q}」（候选：{'、'.join(indicators)}）"


def resolve_year(q):
    """年份容错：「2025年」「2025 年度」→ 2025。"""
    q = (q or "").strip()
    if not q:
        return None, None
    m = _YEAR_RE.search(q)
    if m:
        return m.group(1), None
    return None, f"无法识别年份「{q}」（请输入如 2025）"


class Repository:
    def __init__(self, conn):
        self.conn = conn

    def upsert_bureau(self, b) -> int:
        row = self.conn.execute("SELECT id FROM bureaus WHERE url=?", (b.url,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE bureaus SET level=?, name=?, region=?, parent_id=?, verified=? WHERE id=?",
                (b.level, b.name, b.region, b.parent_id, int(b.verified), row["id"]))
            self.conn.commit()
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO bureaus (level, name, url, region, parent_id, verified) VALUES (?,?,?,?,?,?)",
            (b.level, b.name, b.url, b.region, b.parent_id, int(b.verified)))
        self.conn.commit()
        return cur.lastrowid

    def list_bureaus(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM bureaus ORDER BY level, id")]

    def upsert_page(self, p) -> int:
        """URL 已存在则刷新页面内容（title/正文/年度/哈希），否则插入；返回 page id。"""
        row = self.conn.execute("SELECT id FROM pages WHERE url=?", (p.url,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE pages SET title=?, content_text=?, dataset_type=?, period=?, content_hash=?, status=? WHERE id=?",
                (p.title, p.content_text, p.dataset_type, p.period, p.content_hash, p.status, row["id"]))
            self.conn.commit()
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO pages (bureau_id, url, title, content_text, dataset_type, period, content_hash, status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p.bureau_id, p.url, p.title, p.content_text, p.dataset_type, p.period, p.content_hash, p.status))
        self.conn.commit()
        return cur.lastrowid

    def list_pages(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM pages ORDER BY id")]

    def page_id_by_hash(self, content_hash):
        """按内容哈希查已入库页面 id，无则 None（用于内容级去重）。"""
        row = self.conn.execute("SELECT id FROM pages WHERE content_hash=?", (content_hash,)).fetchone()
        return row["id"] if row else None

    def insert_values(self, values) -> int:
        n = 0
        for v in values:
            self.conn.execute(
                "INSERT INTO data_values (page_id, bureau_id, region, year, indicator_name, value, unit, category, raw_text, method) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (v.page_id, v.bureau_id, v.region, v.year, v.indicator_name, v.value, v.unit, v.category, v.raw_text, v.method))
            n += 1
        self.conn.commit()
        return n

    def replace_page_values(self, page_id, values) -> int:
        """整页替换指标值：先删该页旧值再插入（页面修订时避免版本累积）。"""
        self.conn.execute("DELETE FROM data_values WHERE page_id=?", (page_id,))
        return self.insert_values(values)

    def query_data(self, region=None, indicator=None, year=None):
        sql = "SELECT * FROM data_values WHERE 1=1"
        params = []
        if region:
            sql += " AND region=?"; params.append(region)
        if indicator:
            sql += " AND indicator_name=?"; params.append(indicator)
        if year:
            sql += " AND year=?"; params.append(year)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def query_lax(self, region_q=None, indicator_q=None, year_q=None):
        """宽容查询：自然语言输入 → 库内精确过滤。

        任一条件给出但无法解析（未识别/歧义）时返回空行并附 warnings，
        绝不静默退回全量导致用户误以为查询成功。
        """
        regions = [r["region"] for r in self.conn.execute(
            "SELECT DISTINCT region FROM data_values WHERE region IS NOT NULL AND region != ''")]
        indicators = [r["indicator_name"] for r in self.conn.execute(
            "SELECT DISTINCT indicator_name FROM data_values WHERE indicator_name IS NOT NULL AND indicator_name != ''")]

        warnings = []
        region, w = resolve_region(region_q, regions) if region_q else (None, None)
        if w: warnings.append(w)
        indicator, w = resolve_indicator(indicator_q, indicators) if indicator_q else (None, None)
        if w: warnings.append(w)
        year, w = resolve_year(year_q) if year_q else (None, None)
        if w: warnings.append(w)

        # 提供了条件却解析失败：返回空而不是误导性全量
        if any(x is None for x, q in
               ((region, region_q), (indicator, indicator_q), (year, year_q)) if q):
            return {"rows": [], "warnings": warnings}
        return {"rows": self.query_data(region, indicator, year), "warnings": warnings}

    def export_csv(self, region=None, year=None):
        rows = self.query_data(region=region, year=year)
        out = io.StringIO()
        if rows:
            w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return out.getvalue()

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (status) VALUES ('running')")
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id, status, summary, log):
        self.conn.execute(
            "UPDATE runs SET finished_at=datetime('now','localtime'), status=?, summary_json=?, log=? WHERE id=?",
            (status, json.dumps(summary, ensure_ascii=False), log, run_id))
        self.conn.commit()

    def get_run(self, run_id):
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM runs ORDER BY id DESC")]
