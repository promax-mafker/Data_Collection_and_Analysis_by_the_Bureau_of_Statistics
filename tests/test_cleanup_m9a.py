"""cleanup_m9a.py 测试：存量脏页清理（内存库，不碰真实数据）。"""
from app.store.db import init_db
from scripts.cleanup_m9a import (DICTATED_DELETE_URLS, LISTING_PAGE_URLS, cleanup,
                                 recompute_empty_valued_periods)

REAL = "https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_7109476.htm"


def _seed(con):
    con.executescript(
        "INSERT INTO bureaus (level,name,url,region) "
        "VALUES ('province','福建省统计局','https://tjj.fujian.gov.cn/','福建省');"
        "INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category) "
        f"VALUES (1,'{LISTING_PAGE_URLS[0]}','{LISTING_PAGE_URLS[0]}','bulletin','2025','bulletin');"
        "INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category) "
        f"VALUES (1,'{DICTATED_DELETE_URLS[0]}','{DICTATED_DELETE_URLS[0]}','bulletin','2024','bulletin');"
        "INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category) "
        f"VALUES (1,'{REAL}','真公报','bulletin','2025','bulletin');"
    )
    con.commit()


def _urls(con):
    return [r[0] for r in con.execute("SELECT url FROM pages")]


def test_dry_run_does_not_touch_data():
    con = init_db(":memory:")
    _seed(con)
    res = cleanup(con, apply=False)
    assert res["would_delete"] == 2
    assert res["deleted"] == 0
    assert len(_urls(con)) == 3


def test_apply_removes_listing_and_dictated_only():
    con = init_db(":memory:")
    _seed(con)
    res = cleanup(con, apply=True)
    assert res["deleted"] == 2
    urls = _urls(con)
    assert LISTING_PAGE_URLS[0] not in urls, "栏目页存量应清除"
    assert DICTATED_DELETE_URLS[0] not in urls, "跨栏目误匹配存量应清除"
    assert REAL in urls, "真公报必须保留"


def test_idempotent():
    con = init_db(":memory:")
    _seed(con)
    cleanup(con, apply=True)
    again = cleanup(con, apply=True)
    assert again["deleted"] == 0
    assert again["would_delete"] == 0
    assert len(_urls(con)) == 1


def test_page_with_values_is_kept_with_warning():
    """命中名单但已有数据行 → 保留并告警（P1：绝不误删真数据）。"""
    con = init_db(":memory:")
    _seed(con)
    pid = con.execute("SELECT id FROM pages WHERE url=?", (LISTING_PAGE_URLS[0],)).fetchone()[0]
    con.execute(
        "INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,raw_text) "
        "VALUES (?,1,'福建省','2025','地区生产总值','57761.28','亿元','r')", (pid,))
    con.commit()

    res = cleanup(con, apply=True)
    assert res["kept_with_values"] == 1
    assert res["deleted"] == 1                    # 只删取证名单那页
    assert LISTING_PAGE_URLS[0] in _urls(con), "有数据行的页面不得删除"


def test_recompute_clears_fabricated_year_on_empty_page():
    """T6 实测：run 4/5 遗留「0 数据值页面被兜底成 2025」共 98 行，须纠正。

    规则与采集一致：URL/正文都无法识别年份 → 置空（如实记缺），
    能识别的 → 保持/纠正为识别值。
    """
    con = init_db(":memory:")
    con.executescript(
        "INSERT INTO bureaus (level,name,url,region) "
        "VALUES ('city','福州市统计局','https://tjj.fuzhou.gov.cn/','福州市');"
        # 伪造年份：URL 与正文均无「YYYY年」，0 数据值
        "INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category,content_text) "
        "VALUES (1,'https://tjj.fuzhou.gov.cn/zwgk/tjzl/ndbg/202403/t20240320_4795617.htm','x',"
        "'bulletin','2025','bulletin','地区生产总值 1 亿元');"
        # 正文含年份：应纠正为 2024
        "INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category,content_text) "
        "VALUES (1,'https://tjj.fuzhou.gov.cn/zwgk/tjzl/ndbg/202403/t20240320_4795618.htm','y',"
        "'bulletin','2025','bulletin','2024年福州市地区生产总值 1 亿元');"
    )
    con.commit()
    res = recompute_empty_valued_periods(con, apply=True)
    got = dict(con.execute("SELECT url, period FROM pages").fetchall())
    assert got["https://tjj.fuzhou.gov.cn/zwgk/tjzl/ndbg/202403/t20240320_4795617.htm"] == "", \
        "无法识别年份应置空，不得保留伪造的 2025"
    assert got["https://tjj.fuzhou.gov.cn/zwgk/tjzl/ndbg/202403/t20240320_4795618.htm"] == "2024", \
        "能从正文识别年份的应纠正"
    assert res["recomputed"] == 2


def test_recompute_skips_pages_with_values():
    """有数据值的页面不得改动 period（值本身已按该年份入库）。"""
    con = init_db(":memory:")
    con.executescript(
        "INSERT INTO bureaus (level,name,url,region) "
        "VALUES ('city','福州市统计局','https://tjj.fuzhou.gov.cn/','福州市');"
        "INSERT INTO pages (bureau_id,url,title,dataset_type,period,doc_category,content_text) "
        "VALUES (1,'https://tjj.fuzhou.gov.cn/a.htm','x','bulletin','2025','bulletin','无年份正文');"
        "INSERT INTO data_values (page_id,bureau_id,region,year,indicator_name,value,unit,raw_text) "
        "VALUES (1,1,'福州市','2025','地区生产总值','1','亿元','r');"
    )
    con.commit()
    res = recompute_empty_valued_periods(con, apply=True)
    assert res["recomputed"] == 0
    assert con.execute("SELECT period FROM pages WHERE id=1").fetchone()[0] == "2025"
