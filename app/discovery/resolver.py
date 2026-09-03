import re
from urllib.parse import urlparse
from ..fetch.parser import extract_links, extract_title
from ..schemas import Bureau

STATS_DOMAIN_RE = re.compile(r"(?:tjj|stats|tj)\.[a-z0-9\-]+\.gov\.cn$")
STATS_TEXT_RE = re.compile(r"统计")

def _domain(url):
    return urlparse(url).netloc.lower()

def is_stats_link(url, text, registry):
    d = _domain(url)
    if d in registry.exclude_domains:
        return False
    if d in registry.known_domains:
        return True
    if d.endswith(".gov.cn") and (STATS_DOMAIN_RE.match(d) or "tjj" in d):
        return True
    return bool(STATS_TEXT_RE.search(text)) and d.endswith(".gov.cn")

def discover_candidates(html, base_url, registry):
    out = []
    for url, text in extract_links(html, base_url):
        if is_stats_link(url, text, registry):
            out.append({"url": url, "text": text})
    return out

def verify_bureau(client, url):
    try:
        title = extract_title(client.get(url))
        if "统计局" in title or "统计" in title:
            return title
    except Exception:
        return None
    return None

def derive_region(name):
    n = name.replace("统计局", "").strip()
    if n in ("国家", "中国", ""):
        return "中国"
    return n

def discover_children(client, registry, parent, targets=None):
    html = client.get(parent.url)
    parent_domain = _domain(parent.url)
    seen = set()
    children = []
    found = set()
    links = extract_links(html, parent.url)
    # 白名单域名优先校验，减少对无关候选的抓取
    links.sort(key=lambda ut: 0 if _domain(ut[0]) in registry.known_domains else 1)
    for url, text in links:
        if _domain(url) == parent_domain:
            continue
        if urlparse(url).path not in ("", "/"):
            continue
        if not is_stats_link(url, text, registry):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = verify_bureau(client, url)
        if not title:
            continue
        level = "city" if parent.level == "province" else "province"
        region = derive_region(title)
        children.append(Bureau(level=level, name=title, url=url,
                               region=region, parent_id=parent.id, verified=True))
        if targets is not None:
            found.add(region)
            if set(targets).issubset(found):
                break
    return children
