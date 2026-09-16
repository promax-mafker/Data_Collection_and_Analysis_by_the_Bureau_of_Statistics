import os

from app.fetch.adapters import AdapterRegistry, SiteAdapter, DEFAULT_DETAIL_PATTERN

CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")


def test_load_registry_and_lookup():
    reg = AdapterRegistry.load(os.path.join(CFG, "site_adapters.yaml"))
    qz = reg.for_region("泉州市")
    assert qz is not None
    assert qz.bulletin_column == "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"
    assert qz.paging["pattern"] == "index_{n}.htm"
    assert reg.for_region("不存在的市") is None


def test_paging_urls_are_derived_not_hardcoded():
    """泉州分页是反序的：/tjzl/tjgb/ 是第 1 页，index_1.htm 是第 2 页。"""
    a = SiteAdapter(region="泉州市",
                    bulletin_column="http://tjj.quanzhou.gov.cn/tjzl/tjgb/",
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 3})
    assert a.page_urls() == [
        "http://tjj.quanzhou.gov.cn/tjzl/tjgb/",
        "http://tjj.quanzhou.gov.cn/tjzl/tjgb/index_1.htm",
        "http://tjj.quanzhou.gov.cn/tjzl/tjgb/index_2.htm",
    ]


def test_no_paging_returns_single_url():
    a = SiteAdapter(region="福建省", bulletin_column="https://tjj.fujian.gov.cn/xxgk/tjgb/")
    assert a.page_urls() == ["https://tjj.fujian.gov.cn/xxgk/tjgb/"]


def test_tls_and_referer_defaults_and_overrides():
    reg = AdapterRegistry.load(os.path.join(CFG, "site_adapters.yaml"))
    assert reg.for_region("三明市").verify_tls is False
    assert reg.for_region("厦门市").referer == "https://tjj.xm.gov.cn/"
    assert reg.for_region("泉州市").verify_tls is True
    assert reg.for_region("泉州市").referer == ""


def test_default_detail_pattern():
    assert DEFAULT_DETAIL_PATTERN == r"t20\d{6}_\d+\.(htm|html)"
