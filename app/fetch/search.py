"""福建省政府门户 was5 站内检索解析（莆田等无独立统计局站点用）。"""
import re
from urllib.parse import urlencode

WAS_PAIR_RE = re.compile(r'"title2"\s*:\s*"([^"]+)",\s*.*?"url"\s*:\s*"([^"]+)"')


def build_was_url(cfg: dict) -> str:
    """由配置构造 was5 检索 URL。cfg: {endpoint, channelid?, searchword, perpage?}"""
    q = {"searchword": cfg.get("searchword", ""), "perpage": cfg.get("perpage", "20")}
    if cfg.get("channelid"):
        q["channelid"] = cfg["channelid"]
    sep = "&" if "?" in cfg["endpoint"] else "?"
    return cfg["endpoint"] + sep + urlencode(q)


def parse_was_items(html: str):
    """解析 was5 检索返回（HTML 内嵌 JSON 字段 title2/url），去重。"""
    items = []
    seen = set()
    for title, url in WAS_PAIR_RE.findall(html):
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url})
    return items


def filter_items(items, include=None, exclude=None):
    """按标题关键词过滤（include 需命中其一，exclude 命中其一即剔除）。"""
    out = []
    for it in items:
        t = it.get("title", "")
        if include and not any(k in t for k in include):
            continue
        if exclude and any(k in t for k in exclude):
            continue
        out.append(it)
    return out
