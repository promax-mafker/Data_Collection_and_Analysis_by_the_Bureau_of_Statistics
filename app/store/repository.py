import csv
import io
import json
import re

# 指标常见别名（小写归一后查表）
INDICATOR_ALIASES = {
    "gdp": "地区生产总值",
    "gross domestic product": "地区生产总值",
    "第一产业": "第一产业增加值",
    "第二产业": "第二产业增加值",
    "第三产业": "第三产业增加值",
}

_YEAR_RE = re.compile(r"(\d{4})")

# 地区名后缀可省略的行政字（核心名匹配用）
_REGION_SUFFIX = ("省", "市")
# 核心名（去掉省/市）之前允许出现的中文字：连接词/行政字，其余中文视为长词中段
_REGION_OK_BEFORE = "省市的和与及、,，:： "
# 句中若出现这些字却无地区命中，视为「给了无法识别的地区」
# 注意不能含「区/地区」——「地区生产总值」等指标名会误触发
_REGION_HINT = ("省", "市", "县", "自治")


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
                "UPDATE pages SET title=?, content_text=?, dataset_type=?, period=?, content_hash=?, doc_category=?, status=? WHERE id=?",
                (p.title, p.content_text, p.dataset_type, p.period, p.content_hash, p.doc_category, p.status, row["id"]))
            self.conn.commit()
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO pages (bureau_id, url, title, content_text, dataset_type, period, content_hash, doc_category, status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (p.bureau_id, p.url, p.title, p.content_text, p.dataset_type, p.period, p.content_hash, p.doc_category, p.status))
        self.conn.commit()
        return cur.lastrowid

    def list_pages(self, doc_category=None):
        sql = "SELECT * FROM pages WHERE 1=1"
        params = []
        if doc_category:
            sql += " AND doc_category=?"
            params.append(doc_category)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def page_id_by_hash(self, content_hash):
        """按内容哈希查已入库页面 id，无则 None（用于内容级去重）。"""
        row = self.conn.execute("SELECT id FROM pages WHERE content_hash=?", (content_hash,)).fetchone()
        return row["id"] if row else None

    def find_bureau_by_region(self, region) -> int:
        """按 region 查机构 id；无则 None（M7a: 归属不再硬编码）。"""
        row = self.conn.execute(
            "SELECT id FROM bureaus WHERE region=? ORDER BY id LIMIT 1", (region,)).fetchone()
        return row["id"] if row else None

    def _insert_values(self, values) -> int:
        """逐条插入 data_values（不 commit，供单事务调用）。"""
        n = 0
        for v in values:
            self.conn.execute(
                "INSERT INTO data_values (page_id, bureau_id, region, year, indicator_name, value, unit, category, raw_text, method, caliber, source_url) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (v.page_id, v.bureau_id, v.region, v.year, v.indicator_name, v.value,
                 v.unit, v.category, v.raw_text, v.method, v.caliber, v.source_url))
            n += 1
        return n

    def insert_values(self, values) -> int:
        try:
            n = self._insert_values(values)
            self.conn.commit()
            return n
        except Exception:
            self.conn.rollback()
            raise

    def replace_page_values(self, page_id, values, force=False) -> int:
        """整页替换指标值：单事务 DELETE+INSERT。

        M7a 护栏：values 为空且非 force → 不删旧值返回 0（防"空解析抹库"）。
        """
        if not values and not force:
            return 0
        try:
            self.conn.execute("DELETE FROM data_values WHERE page_id=?", (page_id,))
            self._insert_values(values)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return len(values)

    def query_data(self, region=None, indicator=None, year=None, caliber=None):
        sql = "SELECT * FROM data_values WHERE 1=1"
        params = []
        if region:
            sql += " AND region=?"; params.append(region)
        if indicator:
            sql += " AND indicator_name=?"; params.append(indicator)
        if year:
            sql += " AND year=?"; params.append(year)
        if caliber:
            sql += " AND caliber=?"; params.append(caliber)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def query_lax(self, region_q=None, indicator_q=None, year_q=None, caliber=None):
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
        return {"rows": self.query_data(region, indicator, year, caliber), "warnings": warnings}

    # ---------- 整句自然语言查询 ----------

    def _candidates(self, column):
        return [r[column] for r in self.conn.execute(
            f"SELECT DISTINCT {column} FROM data_values "
            f"WHERE {column} IS NOT NULL AND {column} != ''")]

    def query_text(self, text, caliber=None):
        """整句解析：从一句话里同时抽出地区/指标/年份后过滤。

        规则：
        - 地区：候选全名或去省/市后缀的核心名；多个命中时紧邻视为
          「上级修饰下级」只保留最具体者，连接词分隔则分别保留。
        - 指标：全名优先，别名兜底；「人均地区生产总值」等带人均前缀
          的表述不误配总量指标。
        - 年份：多个 4 位年份取最后出现。
        - 地区词有线索却无法识别 → 警告并返回空，避免误导。
        """
        text = (text or "").strip()
        warnings = []
        if not text:
            return {"rows": [], "warnings": ["请输入查询内容"], "matched": {}}
        regions_all = self._candidates("region")
        indicators_all = self._candidates("indicator_name")

        # 1) 地区：全名 + 核心名（去掉 省/市）命中
        hits = []  # (pos, end, region)
        for c in regions_all:
            i = text.find(c)
            if i >= 0:
                hits.append((i, i + len(c), c)); continue
            core = c[:-1] if len(c) > 2 and c[-1] in _REGION_SUFFIX else None
            if core:
                j = text.find(core)
                if j >= 0:
                    before = text[j - 1:j]
                    # 前导是中文但非连接/行政字 → 视为长词中段（如「福建师范大学」的福建）
                    if not before or not ('\u4e00' <= before <= '\u9fff') or before in _REGION_OK_BEFORE:
                        hits.append((j, j + len(core), c))
        # 紧邻命中归组，组内取最具体（最后一个）
        hits.sort(key=lambda h: (h[0], -h[1]))
        groups = []
        for h in hits:
            if groups and h[0] == groups[-1][-1][1]:
                groups[-1].append(h)
            else:
                groups.append([h])
        regions = [g[-1][2] for g in groups]
        region_hint = any(ch in text for ch in _REGION_HINT)
        if not regions and region_hint:
            warnings.append(f"无法识别地区「{text}」中的地市（候选：{'、'.join(regions_all)}）")

        # 2) 指标：全名优先，别名兜底；防「人均」前缀误配
        indicator = None
        found_pos = None
        for c in indicators_all:
            i = text.find(c)
            if i >= 0 and text[max(0, i - 2):i] != "人均":
                indicator, found_pos = c, i
                break
        if indicator is None:
            low = text.lower()
            for alias, name in INDICATOR_ALIASES.items():
                j = low.find(alias)
                if j >= 0 and low[max(0, j - 2):j] != "人均" and name in indicators_all:
                    indicator, found_pos = name, j
                    break
        if indicator is None:
            warnings.append("未能识别指标（含人均/细分口径？候选：" +
                            "、".join(indicators_all[:12]) + "）")

        # 3) 年份：取最后出现的 4 位年份
        years = _YEAR_RE.findall(text)
        year = years[-1] if years else None
        if len(set(years)) > 1:
            warnings.append(f"句中出现多个年份（{'、'.join(dict.fromkeys(years))}），按最后一个 {year} 查询")

        # 地区有线索却未识别 / 指标未识别 → 返回空（不误导）
        if (region_hint and not regions) or indicator is None:
            return {"rows": [], "warnings": warnings,
                    "matched": {"regions": regions, "indicator": indicator, "year": year}}
        if not regions:
            # 无任何地区词 → 不限地区
            rows = self.query_data(None, indicator, year, caliber)
        else:
            rows = self.query_data(regions[0], indicator, year, caliber) if len(regions) == 1 else self._query_in(
                regions, indicator, year, caliber)
        return {"rows": rows, "warnings": warnings,
                "matched": {"regions": regions, "indicator": indicator, "year": year}}

    def _query_in(self, regions, indicator, year, caliber=None):
        marks = ",".join("?" * len(regions))
        sql = f"SELECT * FROM data_values WHERE region IN ({marks})"
        params = list(regions)
        if indicator:
            sql += " AND indicator_name=?"; params.append(indicator)
        if year:
            sql += " AND year=?"; params.append(year)
        if caliber:
            sql += " AND caliber=?"; params.append(caliber)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

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

    # ---------- M5: doc_insights / enterprises ----------

    def _insert_doc_insights(self, items) -> int:
        """插入洞察（不 commit）；items 可含 region/period。"""
        n = 0
        for it in items:
            self.conn.execute(
                "INSERT INTO doc_insights (page_id, source_id, kind, title, body, method, region, period) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (it.get("page_id"), it.get("source_id"), it.get("kind"),
                 it.get("title", ""), it.get("body", ""), it.get("method", "llm"),
                 it.get("region", ""), it.get("period", "")))
            n += 1
        return n

    def insert_doc_insights(self, items) -> int:
        """items: list[dict(page_id, source_id, kind, title, body, method, region?, period?)]。"""
        try:
            n = self._insert_doc_insights(items)
            self.conn.commit()
            return n
        except Exception:
            self.conn.rollback()
            raise

    def replace_doc_insights(self, page_id, items, force=False) -> int:
        """整页替换洞察：单事务 DELETE+INSERT（页面刷新防版本累积）。

        M7a 护栏：items 为空且非 force → 不删旧行返回 0（LLM 失败不清空旧洞察）。
        """
        if not items and not force:
            return 0
        try:
            self.conn.execute("DELETE FROM doc_insights WHERE page_id=?", (page_id,))
            for it in items:
                it["page_id"] = page_id
            self._insert_doc_insights(items)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return len(items)

    def list_doc_insights(self, page_id=None, kind=None, region=None):
        sql = "SELECT * FROM doc_insights WHERE 1=1"
        params = []
        if page_id:
            sql += " AND page_id=?"
            params.append(page_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if region:
            sql += " AND region=?"
            params.append(region)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def replace_enterprises(self, page_id, rows, force=False) -> int:
        """rows: list[dict(year, list_type, name, county, rank)]；整页替换（单事务）。"""
        if not rows and not force:
            return 0
        try:
            self.conn.execute("DELETE FROM enterprises WHERE page_id=?", (page_id,))
            n = 0
            for r in rows:
                self.conn.execute(
                    "INSERT INTO enterprises (page_id, year, list_type, name, county, rank) VALUES (?,?,?,?,?,?)",
                    (page_id, r.get("year"), r.get("list_type", ""), r.get("name"),
                     r.get("county", ""), r.get("rank", "")))
                n += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n

    def list_enterprises(self, year=None, list_type=None):
        sql = "SELECT * FROM enterprises WHERE 1=1"
        params = []
        if year:
            sql += " AND year=?"
            params.append(year)
        if list_type:
            sql += " AND list_type=?"
            params.append(list_type)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    # ---------- M6: industry_data / econ_series / enterprise_industry ----------

    def replace_industry_data(self, source, rows, force=False) -> int:
        """rows: list[dict(industry, year, metric, value, unit, raw_text)]；按 source 整批替换（单事务）。"""
        if not rows and not force:
            return 0
        try:
            self.conn.execute("DELETE FROM industry_data WHERE source=?", (source,))
            n = 0
            for r in rows:
                self.conn.execute(
                    "INSERT INTO industry_data (source, industry, year, metric, value, unit, raw_text) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (source, r.get("industry", ""), r.get("year", ""), r.get("metric", ""),
                     r.get("value", ""), r.get("unit", ""), r.get("raw_text", "")))
                n += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n

    def list_industry_data(self, source=None, industry=None, metric=None):
        sql = "SELECT * FROM industry_data WHERE 1=1"
        params = []
        if source:
            sql += " AND source=?"
            params.append(source)
        if industry:
            sql += " AND industry=?"
            params.append(industry)
        if metric:
            sql += " AND metric=?"
            params.append(metric)
        sql += " ORDER BY id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def replace_econ_series(self, source, rows, force=False) -> int:
        """rows: list[dict(indicator, year, value, unit, note, raw_text)]；按 source 整批替换（单事务）。"""
        if not rows and not force:
            return 0
        try:
            self.conn.execute("DELETE FROM econ_series WHERE source=?", (source,))
            n = 0
            for r in rows:
                self.conn.execute(
                    "INSERT INTO econ_series (source, indicator, year, value, unit, note, raw_text) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (source, r.get("indicator", ""), r.get("year", ""), r.get("value", ""),
                     r.get("unit", ""), r.get("note", ""), r.get("raw_text", "")))
                n += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n

    def list_econ_series(self, source=None, indicator=None):
        sql = "SELECT * FROM econ_series WHERE 1=1"
        params = []
        if source:
            sql += " AND source=?"
            params.append(source)
        if indicator:
            sql += " AND indicator=?"
            params.append(indicator)
        sql += " ORDER BY year, id"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def replace_enterprise_industry(self, rows) -> int:
        """rows: list[dict(enterprise_id, industry, method)]；按 id upsert。"""
        try:
            n = 0
            for r in rows:
                self.conn.execute(
                    "INSERT INTO enterprise_industry (enterprise_id, industry, method) VALUES (?,?,?) "
                    "ON CONFLICT(enterprise_id) DO UPDATE SET industry=excluded.industry, method=excluded.method",
                    (r.get("enterprise_id"), r.get("industry", ""), r.get("method", "")))
                n += 1
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n

    def list_enterprise_industry(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM enterprise_industry ORDER BY enterprise_id")]
