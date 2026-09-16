"""泉州市地方政府债务情况专文采集（M9e 债务序列回溯）。

**为什么需要它**：`econ_series` 的 `debt_balance`/`debt_limit` 只有 2021-2024 四年，
做不了"新增债务投资转化率"与趋势判断；而地市级债务的**法定披露渠道**是
地方预决算公开平台里的「20XX年XX市地方政府债务情况」专文
（财政部 CELMA 只到省级，见 `ALT_SOURCES.md` §3.3）。

实测栏目：`https://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/`（市级政府预算公开）、
`.../sjjsgk/`（市级政府决算公开）、`.../SJYSZX/`（市级预算执行）。

写作口径：专文通常表述为
「截至20XX年底，全市政府债务余额预计执行数XXXX亿元，债务余额严格控制在
中央核定的限额YYYY亿元以内」——沿用 `industry_documents.py` 已有的两条正则，
避免同一措辞两套实现。
"""
import re

from .industry_documents import DEBT_PATTERNS

DOC_YEAR_RE = re.compile(r"(20\d{2})\s*年")
_DEBT_DOC_RE = re.compile(r"债务情况|政府债务|债务限额|债券")


def is_debt_doc(title):
    """标题是否为债务情况专文。"""
    return bool(_DEBT_DOC_RE.search(title or ""))


def extract_debt(text):
    """从专文正文抽取债务余额/限额 → ``{indicator: value}``（无则空 dict）。"""
    out = {}
    for name, pattern in DEBT_PATTERNS:
        m = re.search(pattern, text or "")
        if m:
            out[name] = m.group(1).replace(",", "")
    return out


ATTACH_RE = re.compile(r"\.(xlsx?|docx?|pdf)\b", re.I)


def has_attachment_only(html):
    """正文无债务数据、但挂着表格/文档附件 → True。

    实测：2019-2021 三篇专文正文为空，内容在 `.xlsx`/`.docx` 附件里。
    本项目文档白名单不解析这些类型，所以**取不到值**；但必须与
    「该文不含债务数据」区分——前者是"待接入表格解析"，后者是"确实没有"。
    """
    return bool(ATTACH_RE.search(html or ""))


def collect_debt_links(client, columns, max_pages=3, logger=None):
    """遍历预算公开栏目 → 债务专文 ``[(url, title)]``（去重，保序）。"""
    from .parser import decode_html, extract_links

    out, seen = [], set()
    for col in columns:
        urls = [col] + [col.rstrip("/") + f"/index_{i}.htm" for i in range(1, max_pages)]
        for page in urls:
            try:
                html = decode_html(client.download(page))
            except Exception:
                break                      # 该栏目分页到底或不可达 → 换下一个栏目
            new = 0
            for url, title in extract_links(html, page):
                if url in seen or not is_debt_doc(title):
                    continue
                seen.add(url)
                out.append((url, title.strip()))
                new += 1
            if new == 0:
                break
    return out


def ingest_debt(repo, client, columns, dry_run=False, logger=None):
    """采集债务专文 → `econ_series`（按年分 source，整批替换保证幂等）。

    返回统计；**每篇都记录是否抽到值**，抽不到如实计入 ``empty``（不静默跳过）。
    """
    from .parser import decode_html, extract_text

    stats = {"docs": 0, "written": 0, "empty": [], "attachment_only": [],
             "errors": 0, "years": []}
    for url, title in collect_debt_links(client, columns, logger=logger):
        stats["docs"] += 1
        year = DOC_YEAR_RE.search(title)
        year = year.group(1) if year else ""
        try:
            # 必须 ①走统一解码口径（GB2312 站点）②先转纯文本再跑正则。
            # 实测教训：正文里数字常被标签包裹（`预计执行数</span>2661.16</span>亿元`），
            # 直接把**原始 HTML** 喂给文本正则，`\s*` 跨不过标签 → 8 篇专文全部误判为"无数据"。
            raw_html = decode_html(client.download(url))
            text = extract_text(raw_html)
        except Exception as e:
            stats["errors"] += 1
            if logger:
                logger(f"债务专文抓取失败 {url}: {e}")
            continue
        got = extract_debt(text)
        if not got:
            # 区分「内容在附件里（xlsx/docx，本项目不解析）」与「确实无债务数据」
            if has_attachment_only(raw_html):
                stats["attachment_only"].append(title)
            else:
                stats["empty"].append(title)
            continue
        rows = [{"indicator": k, "year": year, "value": v, "unit": "亿元",
                 "note": "全市口径（地方预决算公开·政府债务情况专文）",
                 "raw_text": f"{title} | {k} | {year} | {v}亿元"}
                for k, v in got.items() if year]
        if not rows:
            stats["empty"].append(title)
            continue
        if not dry_run:
            stats["written"] += repo.replace_econ_series(f"qz_debt_{year}", rows)
        stats["years"].append(year)
    return stats
