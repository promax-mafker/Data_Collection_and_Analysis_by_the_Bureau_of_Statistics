"""站点适配知识库（M9a）。

把「站点 → 公报栏目 / 分页模式 / TLS 与 Referer 需求」从代码搬到配置，
治理各站点结构不统一导致的漏检（见 docs/research/EVIDENCE_DATA_GAP.md §5/§6）。

铁律（设计 P2）：不硬编码详情 URL 与表号；详情链接一律从栏目页 HTML 解析。
"""
import re
from urllib.parse import urljoin, urlparse

import yaml

# 政府站文章详情 URL 的常见形态（从栏目页 HTML 解析出来的链接用它校验，不用于拼接）
DEFAULT_DETAIL_PATTERN = r"t20\d{6}_\d+\.(htm|html)"

_ARTICLE_RE = re.compile(DEFAULT_DETAIL_PATTERN)
_INDEX_FILE_RE = re.compile(r"index(_\d+)?\.(htm|html)$")


class SiteAdapter:
    """单个站点的采集适配配置。"""

    def __init__(self, region, bulletin_column="", paging=None,
                 detail_pattern=DEFAULT_DETAIL_PATTERN,
                 verify_tls=True, referer="", note="", year_range=None):
        self.region = region
        self.bulletin_column = bulletin_column
        self.paging = paging or {}
        self.detail_pattern = detail_pattern
        self.verify_tls = bool(verify_tls)
        self.referer = referer
        self.note = note
        self.year_range = year_range  # (start, end) 或 None

    def page_urls(self):
        """栏目页 + 分页 URL 列表（顺序即抓取顺序）。

        无 paging 配置 → 只返回栏目页本身（如福建省一页到底）。

        约定：``max_pages`` 是**总页数上限（含栏目页本身）**。
        例：``max_pages=3`` → 栏目页 + ``index_1`` + ``index_2``，共 3 页。
        """
        if not self.bulletin_column:
            return []
        urls = [self.bulletin_column]
        pattern = self.paging.get("pattern")
        if not pattern:
            return urls
        start = int(self.paging.get("start", 1))
        max_pages = max(1, int(self.paging.get("max_pages", 1)))
        for n in range(start, max_pages):
            urls.append(urljoin(self.bulletin_column, pattern.format(n=n)))
        return urls


class AdapterRegistry:
    """适配库：按 region 查询。"""

    def __init__(self, adapters=None):
        self.adapters = adapters or []

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        out = []
        for a in d.get("adapters", []):
            yr = a.get("year_range")
            out.append(SiteAdapter(
                region=a.get("region", ""),
                bulletin_column=a.get("bulletin_column", ""),
                paging=a.get("paging"),
                detail_pattern=a.get("detail_pattern", DEFAULT_DETAIL_PATTERN),
                verify_tls=a.get("verify_tls", True),
                referer=a.get("referer", ""),
                note=a.get("note", ""),
                year_range=tuple(yr) if yr else None,
            ))
        return cls(out)

    def for_region(self, region):
        for a in self.adapters:
            if a.region == region:
                return a
        return None


def is_detail_link(url, text, base_url, pattern=DEFAULT_DETAIL_PATTERN):
    """判断链接是否为「栏目页内的公报详情页」。同域为前提。

    **实测缺陷一（跨栏目泄漏）**：福建省统计公报栏目页下钻时，
    `/xxgk/ztgg/202212/t20221202_6069899.htm`（「执法证公示」）
    因旧实现只按 URL 形态匹配而被当作公报入库。

    **实测缺陷二（详情页被误判为列表页，M9a 端到端暴露）**：
    若规则写成「锚文本含『公报』即通过」，则**每个公报详情页**的站点导航链接
    （锚文本恰为「统计公报」、不含年份）都会通过，使详情页被判为列表页而
    **整页跳过** —— 真实采集中泉州 2024/2023/2022 公报因此全部丢失。

    规则：
      1. URL 形态匹配 ``pattern`` → 必须位于栏目页**路径之下**（跨栏目守卫）。
      2. 形态不匹配（cms 等站点）→ 锚文本须同时含「统计公报」**且含 4 位年份**。
         年份要求是关键：它把「详情页导航」与「栏目内条目」区分开。
    """
    bu, uu = urlparse(base_url), urlparse(url)
    if bu.netloc.lower() != uu.netloc.lower():
        return False
    if not re.search(pattern, uu.path):
        t = text or ""
        return "统计公报" in t and bool(re.search(r"20\d{2}", t))
    # 统一成目录前缀：去尾斜杠 → 去 index 文件名 → 补尾斜杠。
    # 必须先去尾斜杠，否则 "…/index_1.htm/" 无法被 index 正则匹配，
    # 会把分页页自身路径当成目录前缀，导致该页全部链接被拒。
    base_path = bu.path.rstrip("/")
    base_path = _INDEX_FILE_RE.sub("", base_path)
    if not base_path.endswith("/"):
        base_path += "/"
    return uu.path.startswith(base_path)
