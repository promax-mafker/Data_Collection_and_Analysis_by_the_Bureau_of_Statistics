"""M9a 存量脏页清理（幂等、带备份）。

背景（docs/research/EVIDENCE_DATA_GAP.md §8）：

1. **栏目页自身被当作公报正文入库** —— 福建省 `/xxgk/tjgb/`（抓取于 2026-09-03，
   早于列表页下钻功能上线）。代码侧已由 M9a 修复（适配器栏目页只作下钻入口），
   但存量数据需清理。
2. **跨栏目误匹配** —— `/xxgk/ztgg/202212/t20221202_6069899.htm`「执法证公示」
   因旧实现只按 URL 形态匹配而被标为 `bulletin`。代码侧已加跨栏目守卫，
   存量数据需清理。

安全性（设计 P1「错 > 缺」的反向应用：**宁可留脏，不可误删真数据**）：

* 只删「URL 命中名单 **且** 该页 `data_values` 行数为 0」的页面；
* 命中名单但已有数据行 → **保留**并计入 ``kept_with_values``，输出告警；
* ``--apply`` 前自动备份 `stats.db`（先 WAL checkpoint 再复制）；
* **幂等**：重复执行第二次 ``deleted == 0``。
"""
import argparse
import datetime
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 取证删除：实测跨栏目误匹配（0 行数据，抓取于 2026-09-05）
DICTATED_DELETE_URLS = [
    "http://tjj.fujian.gov.cn/xxgk/ztgg/202212/t20221202_6069899.htm",
    # M9a 端到端暴露：泉州「数据解读」栏目（/tjzl/sjjd/）被当作公报入库
    "http://tjj.quanzhou.gov.cn/tjzl/sjjd/201804/t20180416_623773.htm",
]

# 栏目/列表页存量（0 行数据，抓取于 2026-09-03）
LISTING_PAGE_URLS = [
    "http://tjj.fujian.gov.cn/xxgk/tjgb/",
]


def _values_count(con, page_id):
    return con.execute("SELECT COUNT(*) FROM data_values WHERE page_id=?", (page_id,)).fetchone()[0]


def cleanup(con, apply=False):
    """清理存量脏页。

    返回 ``{"would_delete", "deleted", "kept_with_values", "details"}``。
    ``apply=False`` 为干跑，不改动任何数据。
    """
    targets = ([(u, "dictated") for u in DICTATED_DELETE_URLS]
               + [(u, "listing") for u in LISTING_PAGE_URLS])
    details = []
    would_delete = deleted = kept = 0
    for url, reason in targets:
        row = con.execute("SELECT id FROM pages WHERE url=?", (url,)).fetchone()
        if row is None:
            continue
        pid = row[0]
        n = _values_count(con, pid)
        if n > 0:
            kept += 1
            details.append({"url": url, "reason": reason,
                            "action": "keep", "values": n})
            continue
        would_delete += 1
        details.append({"url": url, "reason": reason, "action": "delete", "values": 0})
        if apply:
            # 先删子表再删主表（外键开启）
            con.execute("DELETE FROM data_values WHERE page_id=?", (pid,))
            con.execute("DELETE FROM doc_insights WHERE page_id=?", (pid,))
            con.execute("DELETE FROM pages WHERE id=?", (pid,))
            deleted += 1
    if apply and deleted:
        con.commit()
    return {"would_delete": would_delete, "deleted": deleted,
            "kept_with_values": kept, "details": details}


def recompute_empty_valued_periods(con, apply=False):
    """纠正「0 数据值」公报页的 period（与采集侧同一套年份推导规则）。

    背景：T6 真实采集暴露 run 4/5 遗留 **98 个空值页 period 被兜底成 2025**。
    采集代码已修（未知年份如实记空），存量需一并纠正；否则页面计数与
    后续按年查询会看到凭空的 2025。

    **安全性**：只处理 0 数据值的页面。有值的页面其 period 已随值入库，
    改动会造成「值—年」不一致。

    返回 ``{"recomputed", "details"}``；``apply=False`` 为干跑。
    """
    from app.orchestrator import _derive_year

    rows = con.execute(
        "SELECT p.id, p.url, p.title, p.period, p.content_text FROM pages p "
        "WHERE p.dataset_type='bulletin' "
        "AND (SELECT COUNT(*) FROM data_values v WHERE v.page_id=p.id)=0"
    ).fetchall()
    recomputed = 0
    details = []
    for pid, url, title, period, text in rows:
        new = (_derive_year(url or "", "") or _derive_year(title or "", "")
               or _derive_year(text or "", ""))
        if new != (period or ""):
            recomputed += 1
            details.append({"page_id": pid, "url": url, "old": period, "new": new})
            if apply:
                con.execute("UPDATE pages SET period=? WHERE id=?", (new, pid))
    if apply and recomputed:
        con.commit()
    return {"recomputed": recomputed, "details": details}


def backup_db(db_path):
    """备份数据库（先 WAL checkpoint 再复制），返回备份路径。"""
    from app.store.db import init_db

    con = init_db(db_path)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    dst = f"{db_path}.bak-{stamp}"
    shutil.copy2(db_path, dst)
    return dst


def main():
    ap = argparse.ArgumentParser(description="M9a 存量脏页清理（默认干跑）")
    ap.add_argument("--apply", action="store_true", help="实际执行删除（会先备份）")
    ap.add_argument("--db", default=os.path.join(BASE, "data", "stats.db"))
    args = ap.parse_args()

    from app.store.db import init_db

    if args.apply:
        dst = backup_db(args.db)
        print(f"[备份] {dst}")
    con = init_db(args.db)
    res = cleanup(con, apply=args.apply)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 脏页: would_delete={res['would_delete']} deleted={res['deleted']} "
          f"kept_with_values={res['kept_with_values']}")
    for d in res["details"]:
        note = f"values={d['values']}"
        if d["action"] == "keep":
            note += "  ⚠ 有数据行，保留（请人工复核）"
        print(f"  - [{d['reason']}] {d['action']:6s} {note}  {d['url']}")

    rec = recompute_empty_valued_periods(con, apply=args.apply)
    print(f"[{mode}] 年份纠正: recomputed={rec['recomputed']}（仅 0 数据值页面）")
    for d in rec["details"][:15]:
        print(f"  - page {d['page_id']}: {d['old']!r} → {d['new']!r}  {d['url'][-70:]}")
    if len(rec["details"]) > 15:
        print(f"  … 其余 {len(rec['details']) - 15} 条同规则处理")

    if not args.apply and (res["would_delete"] or rec["recomputed"]):
        print("（干跑模式：如需执行请加 --apply）")


if __name__ == "__main__":
    main()
