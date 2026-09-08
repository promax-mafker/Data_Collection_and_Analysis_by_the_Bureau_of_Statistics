"""cleanup_m7a.py 测试：幂等清理逻辑（内存库，不碰真实数据）。"""
import sqlite3

from app.store.db import init_db
from scripts.cleanup_m7a import (cleanup_budget_caliber, cleanup_dicated,
                                 cleanup_exact_duplicates, table_counts)


def _conn():
    con = init_db(":memory:")  # 建库并返回同一连接
    return con


def _seed(con):
    con.executescript("""
    INSERT INTO bureaus (level,name,url,region) VALUES ('city','泉州市统计局','http://qz','泉州市');
    INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category)
      VALUES (1,'http://qz/budget','2026预算','topic','2026','budget');
    INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category)
      VALUES (1,'http://qz/bul','2025公报','bulletin','2025','bulletin');
    -- 取证行(宁德式子口径):5 行
    INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,raw_text)
      VALUES (2,1,'泉州市','2020','进出口总额','502.5','亿元','r1'),
             (2,1,'泉州市','2020','进出口总额','306.2','亿元','r2'),
             (2,1,'泉州市','2020','进出口总额','133.2','亿元','r3');
    -- 完全重复:同值两行
    INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,raw_text)
      VALUES (2,1,'泉州市','2025','进出口总额','2363.79','亿元','r4'),
             (2,1,'泉州市','2025','进出口总额','2363.79','亿元','r4');
    -- budget 页行(2026 预算)
    INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,raw_text)
      VALUES (1,1,'泉州市','2026','一般公共预算收入','355.92','亿元','r5');
    """)


def test_cleanup_dicated_idempotent():
    con = _conn()
    _seed(con)
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM data_values WHERE value IN ('306.2','133.2')")]
    assert cleanup_dicated(con, ids) == 2
    con.commit()
    assert cleanup_dicated(con, ids) == 0  # 幂等：再跑删 0 行
    left = [r["value"] for r in con.execute("SELECT value FROM data_values")]
    assert "502.5" in left and "306.2" not in left


def test_cleanup_exact_duplicates_keeps_min_id():
    con = _conn()
    _seed(con)
    dup_ids = [r["id"] for r in con.execute(
        "SELECT id FROM data_values WHERE value='2363.79'")]
    assert len(dup_ids) == 2
    cleanup_exact_duplicates(con)
    con.commit()
    left = [r["id"] for r in con.execute(
        "SELECT id FROM data_values WHERE value='2363.79'")]
    assert left == [min(dup_ids)]  # 保留最小 id
    # 不同值同键(如口径差异)不受影响
    assert con.execute("SELECT COUNT(*) c FROM data_values WHERE value='502.5'").fetchone()[0] == 1


def test_cleanup_budget_caliber():
    con = _conn()
    _seed(con)
    cleanup_budget_caliber(con)
    con.commit()
    row = con.execute("SELECT caliber FROM data_values WHERE value='355.92'").fetchone()
    assert row["caliber"] == "budget"
    row = con.execute("SELECT caliber FROM data_values WHERE value='502.5'").fetchone()
    assert row["caliber"] == "final"
    # 幂等
    assert cleanup_budget_caliber(con) == 0


def test_table_counts_shape():
    con = _conn()
    _seed(con)
    c = table_counts(con)
    assert c["data_values"] == 6
    assert c["doc_insights"] == 0
