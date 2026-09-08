"""文档源采集编排（M5 泉州纵深画像）。

注册表(config/quanzhou_sources.yaml) → 逐源采集 → 按 parse 类型分流:
rule(数值) / llm(文本洞察) / table(企业名录)。复用 fetch/store 设施。
"""
import os
import traceback

import yaml

from ..parse.table import extract_table_records
from ..schemas import Bureau, Page
from ..extract.rule_extractor import RuleExtractor, clean_bulletin_text
from ..extract.llm_extractor import LLMExtractor
from .parser import decode_html, extract_text, hash_text
from .pdf import extract_pdf_text
from .client import FetchError

# 县（市、区）名匹配（泉州）
COUNTY_NAMES = ["晋江市", "石狮市", "南安市", "惠安县", "安溪县",
                "永春县", "德化县", "鲤城区", "丰泽区", "洛江区",
                "泉港区", "晋江", "石狮", "南安", "惠安", "安溪",
                "永春", "德化", "鲤城", "丰泽", "洛江", "泉港"]

# M7a：PDF 文本低于该阈值视为扫描版/空文档，不再静默当正文
PDF_MIN_TEXT = 80


def load_sources(path):
    """加载源注册表，返回 (region, sources)。"""
    with open(path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return d.get("region", ""), d.get("sources", [])


def _fetch(client, source) -> tuple:
    """按 kind 抓取，返回 (清洗文本, 原始HTML或None)。

    table 类源需要保留 HTML 结构（表格解析），故额外返回原始 html。
    M7a：按 URL 扩展名 + 魔数嗅探文档类型；.doc/.xls 等不支持类型显式报错。
    """
    url = source["url"]
    data = client.download(url)
    raw_html = None
    ext = url.lower().rsplit(".", 1)[-1] if "." in url else ""
    if source.get("kind") == "pdf" or data[:4] == b"%PDF":
        text = extract_pdf_text(data)
        if len(text.strip()) < PDF_MIN_TEXT:
            raise FetchError(f"PDF 文本过短({len(text.strip())} 字)，疑似扫描版/空文档: {url}")
    elif ext in ("doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip", "rar", "wps"):
        raise FetchError(f"不支持的文档类型 .{ext}（仅 HTML/PDF 可解析）: {url}")
    else:
        html = decode_html(data)
        raw_html = html
        text = extract_text(html)
    return text, raw_html


def _infer_county(row_cells) -> str:
    """从一行记录中匹配县名。优先整名(XX市/县/区)，再短名。"""
    for cell in row_cells:
        for name in COUNTY_NAMES:
            if name in cell:
                return name
    return ""


def _parse_enterprise_rows(html: str, year: str):
    """HTML 表格 → enterprises 行。识别列:序号/企业名称/县(市、区)/名单类型。"""
    rows = extract_table_records(html)
    out = []
    for row in rows:
        if len(row) < 2:
            continue
        joined = "".join(row)
        # 表头残留（非 th 表头）：序号/企业名称/县… 组合
        if row[0] in ("序号", "名次", "排名") and any(
                k in joined for k in ("企业名称", "单位名称", "县")):
            continue
        if "企业" in row[0] and len(row[0]) < 8 and len(rows) > 1 and row[0].isdigit() is False:
            continue  # 保守跳过疑似表头行（多为 th 已处理，此处兜底）
        name = ""
        county = ""
        list_type = ""
        for i, cell in enumerate(row):
            if i == 0 and cell.isdigit():
                continue  # 序号列
            if "县" in cell or "区" in cell or "市" in cell and len(cell) <= 6:
                county = _infer_county([cell]) or county
                continue
            if "后备" in cell or "上市" in cell or "挂牌" in cell:
                list_type = cell
                continue
            if not name and len(cell) >= 2:
                name = cell
        if not name:
            # 兜底：无明确企业名列，取第一列非序号值
            name = row[1] if len(row) > 1 else row[0]
        if not county:
            county = _infer_county(row)
        if not list_type:
            list_type = "上市后备" if "挂牌" not in "".join(row) else "挂牌后备"
        # 过滤表头残留/空行
        if name in ("序号", "企业名称", "单位名称", "县（市、区）", "名单类型", ""):
            continue
        if len(name) < 4 or not any("\u4e00" <= ch <= "\u9fff" for ch in name):
            continue
        out.append({"year": year, "list_type": list_type,
                    "name": name, "county": county,
                    "rank": row[0] if row and row[0].isdigit() else ""})
    return out


def _load_default_rules():
    """懒加载项目 config/extract_rules.yaml（数值规则）。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "config", "extract_rules.yaml")
    from ..extract.rule_extractor import load_rules
    return load_rules(path)


def run_documents(client, repo, sources, rules=None, llm_client=None, region="泉州市"):
    """按注册表逐源采集入库。

    rules: 完整规则列表；None → 自动加载 config/extract_rules.yaml。
    返回 {pages, values, insights, enterprises, errors, skipped}。
    每源异常隔离；llm_client 未启用 → llm 页只落 page 不产洞察（不报错）。
    """
    if rules is None:
        rules = _load_default_rules()
    rule_ex = RuleExtractor()
    llm_ex = LLMExtractor(client=llm_client) if llm_client is not None else None
    stats = {"pages": 0, "values": 0, "insights": 0, "enterprises": 0,
             "errors": 0, "skipped": [], "llm_errors": 0, "critiques": 0}
    # M7a: bureau 归属按 region 解析（不再硬编码 id=1），未命中自建 meta 机构
    bureau_id = repo.find_bureau_by_region(region)
    if bureau_id is None:
        meta = Bureau(level="meta", name=f"{region}文档源",
                      url=f"meta://{region}", region=region, verified=True)
        bureau_id = repo.upsert_bureau(meta)

    for src in sources:
        url = src["url"]
        try:
            text, raw_html = _fetch(client, src)
            if not text.strip():
                stats["skipped"].append(url)
                continue
            content_hash = hash_text(text)
            page_title = src.get("name", url)
            year = src.get("period", "")
            page = Page(bureau_id=bureau_id, url=url, title=page_title,
                        content_text=text, dataset_type="topic", period=year,
                        content_hash=content_hash,
                        doc_category=src.get("category", "bulletin"))
            pid = repo.upsert_page(page)
            stats["pages"] += 1

            parse_mode = src.get("parse", "rule")
            caliber = "budget" if src.get("category") == "budget" else "final"
            page_meta = {"page_id": pid, "bureau_id": bureau_id,
                         "region": region, "year": year,
                         "caliber": caliber, "source_url": url}

            if parse_mode in ("rule", "rule+llm"):
                names = src.get("numeric_rules") or []
                if names:
                    values = rule_ex.extract_named(text, names, page_meta, rules)
                    stats["values"] += repo.replace_page_values(pid, values)

            if parse_mode in ("table",):
                rows = _parse_enterprise_rows(raw_html or text, year)
                stats["enterprises"] += repo.replace_enterprises(pid, rows)

            if parse_mode in ("llm", "rule+llm"):
                if llm_ex is not None and getattr(llm_client, "enabled", False):
                    page_dict = dict(page_meta)
                    page_dict.update({"source_id": src.get("id"),
                                      "category": src.get("category"),
                                      "title": page_title, "url": url,
                                      "kind": src.get("kind")})
                    items = llm_ex.extract_insights(page_dict, text, src)
                    items = [dict(it, region=region, period=year) for it in items]
                    if not items:
                        stats["llm_errors"] += 1
                    stats["insights"] += len(items)
                    crit_items = []
                    try:
                        from ..extract.critique import llm_critique
                        crits = llm_critique(text, llm_client)
                        if crits:
                            crit_items = [{"page_id": pid, "source_id": src.get("id"),
                                           "kind": "critique",
                                           "title": f"{page_title}·批判审读",
                                           "body": __import__("json").dumps(c, ensure_ascii=False),
                                           "method": "llm", "region": region,
                                           "period": year} for c in crits]
                            stats["critiques"] += len(crit_items)
                    except Exception as e:
                        stats["llm_errors"] += 1
                        print(f"[documents] 批判失败 {url}: {e}")
                    stats["insights"] += repo.replace_doc_insights(pid, items + crit_items)
                # llm 未启用：页面落库但洞察/批判静默跳过（不产错）
        except Exception as e:
            stats["errors"] += 1
            print(f"[documents] 源失败 {url}: {e}\n{traceback.format_exc()}")
    return stats
