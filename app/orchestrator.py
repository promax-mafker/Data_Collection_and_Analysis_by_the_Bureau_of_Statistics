import datetime
import re
import traceback
from urllib.parse import urlparse
from .discovery.resolver import discover_children
from .extract.rule_extractor import RuleExtractor
from .fetch.adapters import is_detail_link
from .fetch.bulletins import in_year_range
from .fetch.parser import decode_html, extract_links, extract_text, hash_text
from .fetch.pdf import extract_pdf_text, is_pdf_bytes
from .fetch.search import build_was_url, filter_items, parse_was_items
from .schemas import Bureau, Page

YEAR_RE = re.compile(r'(20\d{2})\s*年')


def _derive_year(text, default):
    m = YEAR_RE.search(text)
    return m.group(1) if m else default


def _final_status(errors: int, values: int) -> str:
    if errors == 0:
        return "success"
    return "partial" if values > 0 else "failed"


def _find_bulletin_links(html, base_url, registry):
    """从机构页面找公报详情链接，仅限本机构域名（排除跨站引用链接）。"""
    host = urlparse(base_url).netloc.lower()
    urls = []
    for url, text in extract_links(html, base_url):
        if urlparse(url).netloc.lower() != host:
            continue
        if any(k in (url + text) for k in registry.bulletin_keywords):
            urls.append(url)
    return urls


ARTICLE_RE = re.compile(r"t20\d{6}_\d+\.(?:htm|html)")

# M9a：编排层此前缺少文档类型白名单（documents.py 有），
# 导致 .doc/.xls 等二进制被 decode 成乱码后以「公报正文」身份入库
# （实测：泉州 201006 附件 W020160831598354815443.doc）。
UNSUPPORTED_EXT = {"doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "wps"}


def _unsupported_ext(url: str) -> str:
    """返回不支持解析的文档扩展名；空字符串表示可尝试解析。"""
    path = urlparse(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    ext = name.rsplit(".", 1)[-1]
    return ext if ext in UNSUPPORTED_EXT else ""


def _listing_detail_links(html, base_url):
    """判断页面是否为公报列表页：是则返回同域公报详情链接；否则返回空。

    M9a：详情判定收敛到 `is_detail_link`，接入**跨栏目守卫**。
    实测缺陷：福建省统计公报栏目页下钻时，`/xxgk/ztgg/…`（「执法证公示」）
    因只按 URL 形态匹配而被当作公报入库 —— 现要求 URL 位于栏目路径之下。
    """
    host = urlparse(base_url).netloc.lower()
    out = []
    seen = set()
    for url, text in extract_links(html, base_url):
        if urlparse(url).netloc.lower() != host:
            continue
        if url in seen or url.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(url)
        if is_detail_link(url, text, base_url):
            out.append(url)
        elif "统计公报" in (text or "") and re.search(r"20\d{2}", text or ""):
            out.append(url)
    return out


def _bulletin_candidates(client, registry, bureau):
    """返回 [(标题或 None, 公报URL), ...]。

    优先级（M9a）：手工机构配置（was5 检索 > listing_urls）
    > **站点适配器栏目页（含分页）** > 首页启发式。

    注意：适配器是**增补**首页启发式而非替代 —— 栏目页只覆盖单一栏目，
    而首页可能挂有别的公报入口（如经济普查公报独立栏目）。替代会静默丢覆盖。

    首页抓取失败时：若已有适配器候选则降级继续（不让首页故障抹掉整站）；
    否则照旧抛给上层计数，保持既有错误口径不变。
    """
    cfg = registry.manual_cfg(bureau)
    if cfg:
        if cfg.get("bulletin_search"):
            scfg = cfg["bulletin_search"]
            html = decode_html(client.download(build_was_url(scfg)))
            items = parse_was_items(html)
            items = filter_items(items, include=scfg.get("include"), exclude=scfg.get("exclude"))
            return [(i["title"], i["url"]) for i in items]
        if cfg.get("listing_urls"):
            return [(None, u) for u in cfg["listing_urls"]]

    candidates = []
    adapter = registry.adapter_for(bureau.region)
    if adapter is not None and adapter.bulletin_column:
        candidates.extend((None, u) for u in adapter.page_urls())
    try:
        html = client.get(bureau.url)
    except Exception:
        if not candidates:
            raise
        html = None
    if html:
        candidates.extend((None, u) for u in _find_bulletin_links(html, bureau.url, registry))

    out, seen = [], set()
    for item in candidates:
        if item[1] in seen:
            continue
        seen.add(item[1])
        out.append(item)
    return out


def run_pipeline(client, repo, registry, rules, extractor=None):
    run_id = repo.start_run()
    log = []
    summary = {"bureaus": 0, "pages": 0, "values": 0, "errors": 0}

    def logl(msg):
        log.append(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

    try:
        # 1) 国家种子
        national = Bureau(level="national", name="国家统计局",
                          url=registry.seeds[0]["url"], region="中国", verified=True)
        national.id = repo.upsert_bureau(national)
        national_id = national.id
        summary["bureaus"] += 1

        # 2) 国家 → 省（发现异常回退白名单锚点，不让单点网络问题中断全局）
        fujian = None
        try:
            provinces = discover_children(client, registry, national, targets=["福建省"])
            fujian = next((b for b in provinces if "福建" in b.name), None)
        except Exception as e:
            logl(f"省级发现异常，回退白名单锚点: {e}")
        if fujian is None:
            fujian = Bureau(level="province", name="福建省统计局",
                            url=registry.province_anchor, region="福建省",
                            parent_id=national_id, verified=True)
        fujian.parent_id = national_id
        fujian.id = repo.upsert_bureau(fujian)
        fujian_id = fujian.id
        summary["bureaus"] += 1

        # 3) 省 → 市（发现异常不中断，缺口以日志记录）
        cities = []
        try:
            cities = discover_children(client, registry, fujian, targets=registry.expected_cities)
        except Exception as e:
            logl(f"地市发现异常: {e}")
        city_ids = []
        for c in cities:
            c.parent_id = fujian_id
            c.id = repo.upsert_bureau(c)
            city_ids.append(c.id)
        summary["bureaus"] += len(cities)

        # 3.5) 手工锚点机构（莆田等无独立统计域名、无法自动发现的站点）
        manual_bureau_ids = []
        for m in registry.manual_bureaus:
            b = Bureau(level=m.get("level", "city"), name=m["name"],
                       url=m["url"], region=m["region"],
                       parent_id=fujian_id, verified=True)
            b.id = repo.upsert_bureau(b)
            manual_bureau_ids.append(b.id)
        if registry.manual_bureaus:
            summary["bureaus"] += len(registry.manual_bureaus)
            logl(f"补入手工锚点机构: {[m['name'] for m in registry.manual_bureaus]}")

        found = {c.region for c in cities} | {m["region"] for m in registry.manual_bureaus}
        missing = [c for c in registry.expected_cities if c not in found]
        if missing:
            logl(f"未发现地市: {missing}")

        # 4) 采集 + 抽取 + 入库（候选支持列表页自动下钻一层：首页→栏目页→详情页）
        extractor = extractor or RuleExtractor()
        # M9a：不再用「采集年 - 1」兜底未知年份。T6 真实采集暴露福州 39 个页面
        # 被兜底成 2025，而抽取上下文会把这个 year 传给指标 → 把上一年的数据
        # 标成当年，属**静默值污染**。按设计 P1「错 > 缺」，未知年份如实记空。
        bureaus = [(national_id, national), (fujian_id, fujian)] + list(zip(city_ids, cities))
        for m, bid in zip(registry.manual_bureaus, manual_bureau_ids):
            bureaus.append((bid, Bureau(level=m.get("level", "city"), name=m["name"],
                                        url=m["url"], region=m["region"])))
        for bid, bureau in bureaus:
            try:
                adapter = registry.adapter_for(bureau.region)
                # M9a（A5-2）：适配器声明的栏目/分页 URL 只作下钻入口，
                # 即便本次未解析出详情链接（如异常返回空体）也绝不作为正文入库。
                listing_urls = set(adapter.page_urls()) if adapter is not None else set()
                year_range = adapter.year_range if adapter is not None else None
                queue = list(_bulletin_candidates(client, registry, bureau))
                if not queue:
                    logl(f"{bureau.name} 未找到公报候选（请检查栏目定位或检索配置）")
                processed = set()
                while queue:
                    title, link = queue.pop(0)
                    if link in processed:
                        continue
                    processed.add(link)
                    try:
                        bad_ext = _unsupported_ext(link)
                        if bad_ext:
                            logl(f"跳过不支持的文档类型 .{bad_ext} {link}")
                            continue
                        if link.lower().endswith(".pdf"):
                            text = extract_pdf_text(client.download(link))
                        else:
                            html = decode_html(client.download(link))
                            details = _listing_detail_links(html, link)
                            if details:
                                for d in details:
                                    if d not in processed:
                                        queue.append((None, d))
                            if link in listing_urls or details:
                                continue   # 列表页/栏目页本身不作为正文
                            text = extract_text(html)
                        if not text.strip():
                            logl(f"空内容跳过 {link}")
                            continue
                        page_title = title or link
                        year = _derive_year(page_title, None) or _derive_year(text, "")
                        if not year:
                            logl(f"年份未识别（不兜底，如实记缺） {link}")
                        if not in_year_range(year, year_range):
                            logl(f"年份越界跳过 year={year} {link}")
                            continue
                        content_hash = hash_text(text)
                        if repo.page_id_by_hash(content_hash):
                            logl(f"内容重复跳过 {link}")
                            continue
                        page = Page(bureau_id=bid, url=link, title=page_title, content_text=text,
                                    dataset_type="bulletin", period=year,
                                    content_hash=content_hash)
                        pid = repo.upsert_page(page)          # URL 已存在则刷新页面内容
                        summary["pages"] += 1
                        values = extractor.extract(text, {
                            "page_id": pid, "bureau_id": bid,
                            "region": bureau.region, "year": year}, rules)
                        summary["values"] += repo.replace_page_values(pid, values)  # 整页替换防版本累积
                    except Exception as e:
                        logl(f"页面失败 {link}: {e}\n{traceback.format_exc()}")
                        summary["errors"] += 1
            except Exception as e:
                logl(f"机构失败 {bureau.name}: {e}\n{traceback.format_exc()}")
                summary["errors"] += 1

        status = _final_status(summary["errors"], summary["values"])
    except Exception as e:
        logl(f"管线异常: {e}\n{traceback.format_exc()}")
        status = _final_status(summary["errors"], summary["values"])

    repo.finish_run(run_id, status, summary, "\n".join(log))
    return run_id
