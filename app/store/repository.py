import csv
import io
import json

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
        row = self.conn.execute("SELECT id FROM pages WHERE url=?", (p.url,)).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO pages (bureau_id, url, title, content_text, dataset_type, period, content_hash, status) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p.bureau_id, p.url, p.title, p.content_text, p.dataset_type, p.period, p.content_hash, p.status))
        self.conn.commit()
        return cur.lastrowid

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

    def query_data(self, region=None, indicator=None, year=None):
        sql = "SELECT * FROM data_values WHERE 1=1"
        params = []
        if region:
            sql += " AND region=?"; params.append(region)
        if indicator:
            sql += " AND indicator_name=?"; params.append(indicator)
        if year:
            sql += " AND year=?"; params.append(year)
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
