"""M7a 一次性数据清理(幂等,可重复执行)。

处理三类历史脏数据(取证日期 2026-09-08,依据 docs/audit/REVIEW_PIPELINE_ROBUSTNESS.md §附录C):
1. DICTATED_DELETE_IDS —— 逐行取证确认的错误行:
   宁德 2020 进出口 530-534(民营/国有/RCEP/五年累计/占比误配 37);
   三明 2021 常住人口 333/334/379(换行截断残片 2/2/12);
   泉州 2025 税收 832(121.87 为海关代征子口径,主口径 814.34 保留)。
2. 完全重复行(同 page/region/指标/year/caliber/value)保留最小 id。
   (泉州 2025 进出口 2363.79 双行即此类,自动保留 828 删 829。)
3. budget 口径回填:pages.doc_category='budget' 关联的 data_values 行 → caliber='budget'
   (802/803/804 2026 预算执行行;迁移 _migrate 已含,此处显式再跑一遍保证幂等)。

用法:python scripts/cleanup_m7a.py [--apply] [DB路径]
默认 dry-run:仅打印将执行的删除/更新明细与前后计数。
"""
import datetime
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "stats.db")

# 取证行 id(见报告附录 C;仅对本库有效,已删则空操作)
DICTATED_DELETE_IDS = [530, 531, 532, 533, 534, 333, 334, 379, 832]


def connect_db(path):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.store.db import init_db
    return init_db(path)


def backup_db(path):
    """SQLite 在线备份 API，一致性快照。"""
    ts = datetime.date.today().strftime("%Y%m%d")
    dest = f"{path}.bak-{ts}"
    src = sqlite3.connect(path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def cleanup_dicated(conn, ids=None):
    """删除显式取证行(幂等)。"""
    ids = ids if ids is not None else DICTATED_DELETE_IDS
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    cur = conn.execute(f"DELETE FROM data_values WHERE id IN ({marks})", ids)
    return cur.rowcount


def cleanup_exact_duplicates(conn):
    """删除完全重复行(同 page/region/指标/year/caliber/value/unit)，保留最小 id。"""
    cur = conn.execute(
        "DELETE FROM data_values WHERE id IN ("
        "  SELECT id FROM data_values d WHERE EXISTS ("
        "    SELECT 1 FROM data_values d2 WHERE d2.id < d.id AND "
        "    d2.page_id IS d.page_id AND d2.region IS d.region AND "
        "    d2.indicator_name IS d.indicator_name AND d2.year IS d.year AND "
        "    d2.caliber IS d.caliber AND d2.value IS d.value AND "
        "    d2.unit IS d.unit))")
    return cur.rowcount


def cleanup_budget_caliber(conn):
    """budget 页数值行 → caliber='budget'（幂等）。"""
    cur = conn.execute(
        "UPDATE data_values SET caliber='budget' WHERE caliber!='budget' AND page_id IN "
        "(SELECT id FROM pages WHERE doc_category='budget')")
    return cur.rowcount


def table_counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("data_values", "doc_insights", "industry_data",
                      "econ_series", "enterprises")}


def run(conn, apply=False):
    """执行清理；apply=False 仅打印计划。返回报告 dict。"""
    before = table_counts(conn)
    report = {"apply": apply, "before": before}

    if apply:
        report["dicated_deleted"] = cleanup_dicated(conn)
        report["duplicates_deleted"] = cleanup_exact_duplicates(conn)
        report["budget_updated"] = cleanup_budget_caliber(conn)
        conn.commit()
    else:
        # dry-run：列出将删的取证行与将更新的预算行
        marks = ",".join("?" * len(DICTATED_DELETE_IDS))
        doomed = [dict(r) for r in conn.execute(
            "SELECT id, region, indicator_name, year, value FROM data_values "
            f"WHERE id IN ({marks})", DICTATED_DELETE_IDS)]
        dupes = [dict(r) for r in conn.execute(
            "SELECT id, page_id, indicator_name, year, value FROM data_values WHERE id IN ("
            "  SELECT id FROM data_values d WHERE EXISTS ("
            "    SELECT 1 FROM data_values d2 WHERE d2.id < d.id AND "
            "    d2.page_id IS d.page_id AND d2.region IS d.region AND "
            "    d2.indicator_name IS d.indicator_name AND d2.year IS d.year AND "
            "    d2.caliber IS d.caliber AND d2.value IS d.value AND "
            "    d2.unit IS d.unit))")]
        budget = [dict(r) for r in conn.execute(
            "SELECT id, indicator_name, year, value FROM data_values WHERE caliber!='budget' "
            "AND page_id IN (SELECT id FROM pages WHERE doc_category='budget')")]
        report["dicated_doomed"] = doomed
        report["duplicate_doomed"] = dupes
        report["budget_to_update"] = budget

    after = table_counts(conn)
    report["after"] = after
    return report


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    apply = "--apply" in sys.argv
    path = args[0] if args else DB_PATH
    conn = connect_db(path)
    if apply:
        bak = backup_db(path)
        print(f"已备份: {bak}")
    rep = run(conn, apply=apply)
    if not apply:
        print("[dry-run] 取证待删行:")
        for r in rep["dicated_doomed"]:
            print("  ", r)
        print(f"[dry-run] 完全重复待删 {len(rep['duplicate_doomed'])} 行:")
        for r in rep["duplicate_doomed"][:10]:
            print("  ", r)
        print(f"[dry-run] 预算口径待更新 {len(rep['budget_to_update'])} 行:")
        for r in rep["budget_to_update"]:
            print("  ", r)
    else:
        print(f"取证行删除: {rep['dicated_deleted']}; "
              f"重复行删除: {rep['duplicates_deleted']}; "
              f"预算口径更新: {rep['budget_updated']}")
    print("data_values:", rep["before"]["data_values"], "→", rep["after"]["data_values"])
    if not apply:
        print("(未做任何修改；确认后加 --apply 执行)")


if __name__ == "__main__":
    main()
