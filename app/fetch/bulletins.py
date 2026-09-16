"""公报栏目分页遍历（M9a）。

职责：给定 SiteAdapter，遍历栏目页与分页，返回去重后的详情链接（最新在前）。
不负责抽取与入库 —— 与站点细节解耦，便于夹具测试。

依据：docs/research/EVIDENCE_DATA_GAP.md §5/§6
（旧实现只抓首页或只取栏目第一页，导致泉州仅入 1 期、福建仅入 2 页。）
"""
import traceback

from .adapters import is_detail_link
from .parser import decode_html, extract_links


def collect_detail_links(client, adapter, logger=None):
    """遍历适配器的栏目页与分页。

    返回 ``(links, visited)``：

    * ``links``   —— 去重后的详情 URL 列表，顺序为「先出现的在前」
      （政府站栏目通常最新在前，故顺序即由新到旧）
    * ``visited`` —— 实际成功抓取的栏目/分页 URL 列表

    终止条件（任一）：

    1. 该页未产出任何**新**链接（站点分页到底，或分页参数无效返回同一页）
    2. 已达 ``max_pages``（含栏目页本身，见 ``SiteAdapter.page_urls``）
    3. 该页抓取失败（记日志并中断翻页，**已收集的链接保留**）

    设计 P6：失败绝不静默 —— 传入 ``logger`` 时记录异常与 traceback。
    """
    links, visited = [], []
    seen = set()
    for page_url in adapter.page_urls():
        try:
            html = decode_html(client.download(page_url))
        except Exception as e:  # 单页失败隔离，不影响其它页
            if logger:
                logger(f"栏目页失败 {page_url}: {e}\n{traceback.format_exc()}")
            break
        visited.append(page_url)
        new_on_page = 0
        for url, text in extract_links(html, page_url):
            if url in seen:
                continue
            if not is_detail_link(url, text, page_url, adapter.detail_pattern):
                continue
            seen.add(url)
            links.append(url)
            new_on_page += 1
        if not new_on_page:
            break  # 到底或重复：提前终止，避免无谓请求
    return links, visited


def parse_year_range(spec):
    """``'2015-2025'`` → ``(2015, 2025)``；``'2020'`` → ``(2020, 2020)``；空 → ``None``。

    ``None`` 表示「未配置区间」，调用方据此不过滤（向后兼容）。
    """
    if not spec:
        return None
    s = str(spec).strip()
    if not s:
        return None
    if "-" in s:
        a, b = s.split("-", 1)
        return (int(a), int(b))
    y = int(s)
    return (y, y)


def in_year_range(year, year_range):
    """年份是否落在采集区间内。

    * 未配置区间（``None``）→ 一律通过，保持既有行为不变。
    * 年份未识别或非法 → **拒绝**。符合设计 P1「错 > 缺」：
      采到归属不明的页面比漏采更危险（会造成年份错配的静默污染）。
    """
    if year_range is None:
        return True
    if not year:
        return False
    try:
        y = int(str(year).strip())
    except (TypeError, ValueError):
        return False
    return year_range[0] <= y <= year_range[1]
