"""数据来源维度与主源视图测试（M9b T3）。

设计 §5.2 的关键风险：引入多源后同一 `(region, year, indicator_name, caliber)`
会出现多行，而既有分析层假定其唯一 —— 不加隔离会让**所有既有分析静默错乱**
（不是报错，是算错）。本文件就是那道防线的测试。
"""
from app.store.db import _migrate, init_db
from app.store.repository import Repository

SEED = """
INSERT INTO bureaus (level,name,url,region) VALUES ('city','泉州市统计局','http://qz','泉州市');
INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category)
  VALUES (1,'http://qz/bulletin','2024公报','bulletin','2024','bulletin');
INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category)
  VALUES (1,'http://qz/yearbook','2025年鉴','bulletin','2024','bulletin');
-- 公报（主源 rank=1）
INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,caliber,
                         source_kind,source_rank,extracted_at)
  VALUES (1,1,'泉州市','2024','地区生产总值','13094.32','亿元','final','bulletin',1,'2026-01-01 00:00:00');
-- 年鉴（次源 rank=2，值略有差异 —— 正是需要主源裁决的情形）
INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,caliber,
                         source_kind,source_rank,extracted_at)
  VALUES (2,1,'泉州市','2024','地区生产总值','13094.00','亿元','final','yearbook',2,'2026-02-01 00:00:00');
"""


def _seed(con):
    con.executescript(SEED)
    con.commit()


def test_migration_adds_source_columns_and_is_idempotent(tmp_path):
    p = str(tmp_path / "t.db")
    init_db(p)
    con = init_db(p)  # 第二次：迁移必须幂等
    cols = [r[1] for r in con.execute("PRAGMA table_info(data_values)")]
    assert "source_kind" in cols
    assert "source_rank" in cols
    assert cols.count("source_kind") == 1


def test_legacy_rows_default_to_primary_rank(tmp_path):
    """旧库既有行未显式指定来源 → 默认 `rank=1`（主源），且迁移可重复执行。

    （这是 M9b 之前所有历史数据的形态：它们都是统计局来源，理应为主源。）
    """
    p = str(tmp_path / "t.db")
    con = init_db(p)
    con.executescript("""
    INSERT INTO bureaus (level,name,url,region) VALUES ('city','泉州市统计局','http://qz','泉州市');
    INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category)
      VALUES (1,'http://qz/a','公报','bulletin','2024','bulletin');
    INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit)
      VALUES (1,1,'泉州市','2024','地区生产总值','1','亿元');
    """)
    con.commit()
    r = con.execute("SELECT source_kind, source_rank FROM data_values").fetchone()
    assert r["source_rank"] == 1, "旧行必须默认为主源"
    assert r["source_kind"] == ""
    _migrate(con)  # 再迁一次仍应成功（幂等）
    assert con.execute("SELECT COUNT(*) FROM data_values_primary").fetchone()[0] == 1


def test_primary_view_picks_lowest_rank():
    con = init_db(":memory:")
    _seed(con)
    rows = con.execute("SELECT value, source_kind, source_rank FROM data_values_primary").fetchall()
    assert len(rows) == 1, "同三元组只能出 1 行"
    assert rows[0][0] == "13094.32", "应取 rank 最小（公报）"
    assert rows[0][1] == "bulletin"


def test_query_data_defaults_to_primary_only():
    con = init_db(":memory:")
    _seed(con)
    repo = Repository(con)

    prim = repo.query_data(region="泉州市", indicator="地区生产总值", year="2024")
    assert len(prim) == 1, "默认必须只读主源（否则分析会看到重复行）"
    assert prim[0]["value"] == "13094.32"

    alt = repo.query_data(region="泉州市", indicator="地区生产总值", year="2024",
                          primary_only=False)
    assert len(alt) == 2, "显式要求时才返回全部来源（供交叉验证据此对账）"


def test_view_tie_break_prefers_latest_extracted_at():
    con = init_db(":memory:")
    _seed(con)
    con.execute(
        "INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,"
        "caliber,source_kind,source_rank,extracted_at) VALUES "
        "(2,1,'泉州市','2024','地区生产总值','99999','亿元','final','yearbook',1,'2026-03-01 00:00:00')")
    con.commit()
    rows = con.execute("SELECT value FROM data_values_primary").fetchall()
    assert len(rows) == 1 and rows[0][0] == "99999", "同 rank 时取 extracted_at 最新"


def test_view_keeps_distinct_calibers_apart():
    """口径不同不算重复 —— 预算与决算必须并存（既有口径隔离机制）。"""
    con = init_db(":memory:")
    _seed(con)
    con.execute(
        "INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,"
        "caliber,source_kind,source_rank,extracted_at) VALUES "
        "(2,1,'泉州市','2024','地区生产总值','14000','亿元','budget','yearbook',2,'2026-02-01 00:00:00')")
    con.commit()
    vals = sorted(r[0] for r in con.execute("SELECT value FROM data_values_primary"))
    assert vals == ["13094.32", "14000"]


def test_find_ambiguous_groups_flags_different_values():
    """同键多行且**值不同** = 真歧义（不是重复），必须显式报出而非静默择一。

    实测动机：三明 2023「居民人均可支配收入」同时有 36851/24822/46517
    （城镇/农村被抽成同一指标名），raw_text 形态一致无法区分。
    主源视图按 rank 取一行属于静默择一 —— 本探测器让这类组可见。
    """
    con = init_db(":memory:")
    _seed(con)  # 公报 13094.32 / 年鉴 13094.00 → 值不同 = 歧义组
    repo = Repository(con)
    groups = repo.find_ambiguous_groups()
    assert len(groups) == 1
    g = groups[0]
    assert g["region"] == "泉州市" and g["year"] == "2024"
    assert g["indicator_name"] == "地区生产总值"
    assert g["n"] == 2
    assert len(g["values"]) == 2


def test_find_ambiguous_groups_ignores_true_duplicates():
    """值完全相同的多行是**真重复**，不算歧义（可安全折叠）。"""
    con = init_db(":memory:")
    con.executescript("""
    INSERT INTO bureaus (level,name,url,region) VALUES ('city','泉州市统计局','http://qz','泉州市');
    INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category)
      VALUES (1,'http://qz/a','a','bulletin','2024','bulletin');
    INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,caliber)
      VALUES (1,1,'泉州市','2024','地区生产总值','1','亿元','final');
    INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,caliber)
      VALUES (1,1,'泉州市','2024','地区生产总值','1','亿元','final');
    """)
    con.commit()
    assert Repository(con).find_ambiguous_groups() == []
