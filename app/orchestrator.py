import datetime
import re
from .discovery.resolver import discover_children
from .extract.rule_extractor import RuleExtractor
from .fetch.parser import extract_links, extract_text, hash_text
from .schemas import Bureau, Page

YEAR_RE = re.compile(r'(20\d{2})\s*年')

def _derive_year(text, default):
    m = YEAR_RE.search(text)
    return m.group(1) if m else default

def _find_bulletin_links(html, base_url, registry):
    urls = []
    for url, text in extract_links(html, base_url):
        if any(k in (url + text) for k in registry.bulletin_keywords):
            urls.append(url)
    return urls

def run_pipeline(client, repo, registry, rules):
    run_id = repo.start_run()
    log = []
    summary = {"bureaus": 0, "pages": 0, "values": 0, "errors": 0}

    def logl(msg):
        log.append(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

    try:
        # 1) 国家种子
        national = Bureau(level="national", name="国家统计局",
                          url=registry.seeds[0]["url"], region="中国", verified=True)
        national_id = repo.upsert_bureau(national)
        summary["bureaus"] += 1

        # 2) 国家 → 省
        provinces = discover_children(client, registry, national, targets=["福建省"])
        fujian = next((b for b in provinces if "福建" in b.name), None)
        if fujian is None:
            fujian = Bureau(level="province", name="福建省统计局",
                            url=registry.province_anchor, region="福建省",
                            parent_id=national_id, verified=True)
            logl("国家站未直接发现福建，使用白名单锚点")
        fujian.parent_id = national_id
        fujian_id = repo.upsert_bureau(fujian)
        summary["bureaus"] += 1

        # 3) 省 → 市
        cities = discover_children(client, registry, fujian, targets=registry.expected_cities)
        city_ids = []
        for c in cities:
            c.parent_id = fujian_id
            city_ids.append(repo.upsert_bureau(c))
        summary["bureaus"] += len(cities)
        found = {c.region for c in cities}
        missing = [c for c in registry.expected_cities if c not in found]
        if missing:
            logl(f"未发现地市: {missing}")

        # 4) 采集 + 抽取 + 入库
        extractor = RuleExtractor()
        default_year = str(datetime.date.today().year - 1)
        bureaus = [(national_id, national), (fujian_id, fujian)] + list(zip(city_ids, cities))
        for bid, bureau in bureaus:
            try:
                html = client.get(bureau.url)
                for link in _find_bulletin_links(html, bureau.url, registry):
                    try:
                        detail = client.get(link)
                        text = extract_text(detail)
                        if not text.strip():
                            continue
                        year = _derive_year(text, default_year)
                        page = Page(bureau_id=bid, url=link, title=link, content_text=text,
                                    dataset_type="bulletin", period=year,
                                    content_hash=hash_text(text))
                        pid = repo.upsert_page(page)
                        summary["pages"] += 1
                        values = extractor.extract(text, {
                            "page_id": pid, "bureau_id": bid,
                            "region": bureau.region, "year": year}, rules)
                        summary["values"] += repo.insert_values(values)
                    except Exception as e:
                        logl(f"页面失败 {link}: {e}")
                        summary["errors"] += 1
            except Exception as e:
                logl(f"机构失败 {bureau.name}: {e}")
                summary["errors"] += 1

        status = "success"
    except Exception as e:
        logl(f"管线异常: {e}")
        status = "partial" if summary["values"] else "failed"

    repo.finish_run(run_id, status, summary, "\n".join(log))
    return run_id
