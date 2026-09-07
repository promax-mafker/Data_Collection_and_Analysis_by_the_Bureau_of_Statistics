"""M6 分行业 + 宏观序列采集编排。

读 config/industry_sources.yaml → 采集 五经普/年鉴表/债务 → 入库：
- 年鉴 econ 表 → econ_series
- 年鉴 industry 表(含双列头) → industry_data
- 债务报告 → 正则抽余额/限额 → econ_series
- 企业名单 → industry_classify → enterprise_industry
"""
import os
import re
import traceback

import yaml

from ..parse.series_table import (parse_plain_series, parse_dual_header,
                                  parse_trade, parse_income_rows)
from ..parse.industry_classify import classify_batch
from ..fetch.parser import decode_html
from ..fetch.pdf import extract_pdf_text

# 债务报告关键词 → 指标（锚定原文措辞，避免「新增限额」误配）
DEBT_PATTERNS = [
    ("debt_balance", r"债务余额预计执行数\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*亿元"),
    ("debt_limit", r"中央核定的限额\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*亿元"),
]

# 每表解析器分派
ECON_PARSERS = {
    "trade_12_3": parse_trade,
    "income_4_7": parse_income_rows,
}


def load_industry_sources(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fetch_html(client, url):
    """下载并解码为文本（HTML 或 PDF）。"""
    data = client.download(url)
    if data[:4] == b"%PDF":
        return extract_pdf_text(data)
    return decode_html(data)


def _strip_tags(html):
    import re
    return re.sub(r"<[^>]+>", "", html)


def _extract_debt(html, year):
    """从债务报告抽余额/限额。"""
    text = _strip_tags(html)
    out = []
    for indicator, pat in DEBT_PATTERNS:
        m = re.search(pat, text)
        if m:
            out.append({"indicator": indicator, "year": year, "value": m.group(1).replace(",", ""),
                        "unit": "亿元", "note": "全市口径", "raw_text": m.group(0)})
    return out


def _yearbook_rows(table_cfg, html):
    """按表配置分派解析器，返回统一 rows(list[dict])。"""
    tid = table_cfg["id"]
    if tid == "trade_12_3":
        return parse_trade(html)
    if tid == "income_4_7":
        return parse_income_rows(html)
    if table_cfg.get("dual_header"):
        return parse_dual_header(html)
    return parse_plain_series(html)


def run_industry_sources(client, repo, cfg_path) -> dict:
    """采集全部 M6 源。返回 {series, industry_rows, enterprises, errors, skipped}。"""
    cfg = load_industry_sources(cfg_path)
    base = cfg["yearbook_base"]
    stats = {"series": 0, "industry_rows": 0, "enterprises": 0, "errors": 0, "skipped": []}

    # 1) 年鉴表
    for t in cfg.get("yearbook_tables", []):
        url = base + t["path"]
        try:
            html = _fetch_html(client, url)
            rows = _yearbook_rows(t, html)
            if t.get("kind") == "econ":
                if t["id"] == "trade_12_3":
                    series = [{"indicator": "trade", "year": r.get("year", ""),
                               "value": r["value"], "unit": r.get("unit", ""),
                               "note": r.get("metric", ""), "raw_text": r.get("raw_text", "")}
                              for r in rows]
                elif t["id"] == "income_4_7":
                    series = [{"indicator": "income_consumption", "year": "2024",
                               "value": r["value"], "unit": "元", "note": r.get("item", ""),
                               "raw_text": r.get("raw_text", "")}
                              for r in rows]
                else:
                    series = [{"indicator": t.get("indicator", ""), "year": r.get("year", ""),
                               "value": r["value"], "unit": "", "note": r.get("metric", ""),
                               "raw_text": r.get("raw_text", "")}
                              for r in rows]
                stats["series"] += repo.replace_econ_series(t["id"], series)
            elif t.get("kind") == "industry":
                idata = [{"industry": r.get("industry", ""), "year": r.get("year", ""),
                          "metric": r["metric"], "value": r["value"], "unit": "",
                          "raw_text": r.get("raw_text", "")}
                         for r in rows]
                stats["industry_rows"] += repo.replace_industry_data(t["id"], idata)
        except Exception as e:
            stats["errors"] += 1
            print(f"[industry_documents] 年鉴表失败 {url}: {e}")

    # 2) 五经普 → industry_data（取每张表，industry_col 模式）
    for c in cfg.get("census", []):
        try:
            html = _fetch_html(client, c["url"])
            rows = parse_plain_series(html)
            idata = [{"industry": r.get("industry", r.get("year", "")), "year": "2023",
                      "metric": r["metric"], "value": r["value"], "unit": "",
                      "raw_text": r.get("raw_text", "")}
                     for r in rows if r.get("industry")]
            stats["industry_rows"] += repo.replace_industry_data(c["id"], idata)
        except Exception as e:
            stats["errors"] += 1
            print(f"[industry_documents] 五经普失败 {c.get('url')}: {e}")

    # 3) 债务 → econ_series
    for d in cfg.get("debt", []):
        try:
            html = _fetch_html(client, d["url"])
            series = _extract_debt(html, d["year"])
            stats["series"] += repo.replace_econ_series(d["id"], series)
        except Exception as e:
            stats["errors"] += 1
            print(f"[industry_documents] 债务失败 {d.get('url')}: {e}")

    # 4) 企业归类
    ents = [(r["id"], r["name"]) for r in repo.list_enterprises()]
    if ents:
        rows = classify_batch(ents)
        stats["enterprises"] += repo.replace_enterprise_industry(rows)

    return stats
