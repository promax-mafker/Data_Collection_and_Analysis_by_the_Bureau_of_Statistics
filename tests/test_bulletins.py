import os

from app.fetch.adapters import SiteAdapter, is_detail_link
from app.fetch.bulletins import collect_detail_links

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url):
        return self.mapping[url]

    def download(self, url):
        return self.get(url).encode("utf-8")


def test_collect_across_pages_newest_first():
    col = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"
    client = FakeClient({
        col: _fx("quanzhou_column_p1.html"),
        col + "index_1.htm": _fx("quanzhou_column_index_1.html"),
        col + "index_2.htm": "<html><body></body></html>",
    })
    a = SiteAdapter(region="泉州市", bulletin_column=col,
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 3})
    links, visited = collect_detail_links(client, a)
    assert links[0].endswith("t20260331_3279584.htm")                # 最新在前
    assert any(l.endswith("t20210329_2532918.htm") for l in links)   # 跨分页拿到 2020
    assert len(links) == 5                                           # 3 + 2，去重后
    assert len(set(links)) == len(links)                             # 无重复
    assert len(visited) == 3


def test_collect_stops_when_page_has_no_new_links():
    col = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"
    page = _fx("quanzhou_column_p1.html")
    client = FakeClient({col: page, col + "index_1.htm": page})       # 第 2 页与第 1 页相同
    a = SiteAdapter(region="泉州市", bulletin_column=col,
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 6})
    links, visited = collect_detail_links(client, a)
    assert len(links) == 3
    assert len(visited) == 2      # 第 2 页无新链接 → 提前终止，不再请求 index_2


def test_page_fetch_failure_is_isolated():
    """单页失败不中断整体，且已收集的链接保留。"""
    col = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"

    class Boom(FakeClient):
        def download(self, url):
            if url.endswith("index_1.htm"):
                raise RuntimeError("网络抖动")
            return super().download(url)

    client = Boom({col: _fx("quanzhou_column_p1.html")})
    a = SiteAdapter(region="泉州市", bulletin_column=col,
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 3})
    links, visited = collect_detail_links(client, a)
    assert len(links) == 3
    assert visited == [col]


def test_cross_column_link_is_rejected():
    """实测缺陷回归：执法证公示（/xxgk/ztgg/）不得进入公报候选。"""
    base = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    assert is_detail_link("https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_7109476.htm",
                          "2025年福建省国民经济和社会发展统计公报", base) is True
    assert is_detail_link("https://tjj.fujian.gov.cn/xxgk/ztgg/202212/t20221202_6069899.htm",
                          "执法证公示", base) is False


def test_bulletin_detail_page_nav_is_not_a_detail_link():
    """端到端暴露的回归：公报**详情页**内的站点导航链接不得被当作详情。

    导航锚文本恰为「统计公报」（无年份）。若把它当详情，详情页就会被误判为
    列表页而整页跳过 —— 真实采集中泉州 2024/2023/2022 公报因此全部丢失。
    """
    detail = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/202603/t20260331_3279584.htm"
    # 导航链接：锚文本为「统计公报」，无年份 → 必须拒绝
    assert is_detail_link("http://tjj.quanzhou.gov.cn/tjzl/tjgb/", "统计公报", detail) is False
    assert is_detail_link("http://tjj.quanzhou.gov.cn/tjzl/sjjd/", "数据解读", detail) is False
    # 反例：详情页内的真实栏目条目（含年份）仍应被接受（cms 站点形态）
    assert is_detail_link("http://tjj.quanzhou.gov.cn/cms/x/2025-03-31/123.html",
                          "2024年泉州市国民经济和社会发展统计公报", detail) is True


def test_cms_style_link_requires_year_in_text():
    """形态不匹配的站点（cms）：锚文本须同时含「统计公报」与 4 位年份。"""
    base = "http://tjj.zhangzhou.gov.cn/cms/html/zzstjj/tjgb/index.html"
    assert is_detail_link("http://tjj.zhangzhou.gov.cn/cms/infopublic/publicInfo.shtml?id=1",
                          "2024年漳州市国民经济和社会发展统计公报", base) is True
    assert is_detail_link("http://tjj.zhangzhou.gov.cn/cms/infopublic/publicInfo.shtml?id=2",
                          "统计公报", base) is False


def test_index_page_base_is_treated_as_column():
    """分页页（index_1.htm）作为 base 时，同栏目详情链接仍须通过（规则 3 路径）。

    链接文字刻意不含「公报」，以走 URL 形态 + 路径归属判定，
    防止把分页页自身路径当成目录前缀而导致整页链接被拒。
    """
    base = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/index_1.htm"
    assert is_detail_link("http://tjj.quanzhou.gov.cn/tjzl/tjgb/202204/t20220419_2718483.htm",
                          "2021年泉州市年度数据", base) is True


def test_collect_skips_leak_end_to_end():
    base = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    client = FakeClient({base: _fx("fujian_column_with_leak.html")})
    a = SiteAdapter(region="福建省", bulletin_column=base)
    links, _ = collect_detail_links(client, a)
    assert len(links) == 1
    assert "7109476" in links[0]
