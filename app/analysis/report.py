"""分析报告渲染：Markdown / HTML / CSV。"""
import csv
import datetime
import html
import os

from .core import fmt

MISS = "—"


def region_columns(analysis):
    regions = set(analysis["regions"])
    gdp = analysis.get("table", {}).get("地区生产总值", {}).get("regions", {})
    head = [r for r in ("中国", "福建省") if r in regions]
    others = sorted(regions - set(head),
                    key=lambda r: (-gdp.get(r, float("-inf")), r))
    return head + others


def _cell(regions, value_map, ndigits=2):
    """region 列顺序取值，缺省 MISS。"""
    out = []
    for r in regions:
        v = value_map.get(r)
        out.append(fmt(v, ndigits) if v is not None else MISS)
    return out


def md_table(headers, rows):
    lines = ["| " + " | ".join(str(h) for h in headers) + " |",
             "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def html_table(headers, rows):
    thead = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>"
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"


def _main_table(analysis):
    cols = region_columns(analysis)
    headers = ["指标（单位）"] + cols
    rows = []
    table = analysis.get("table", {})
    for name, meta in table.items():
        header_cell = name if not meta.get("unit") else f"{name}（{meta['unit']}）"
        rows.append([header_cell] + _cell(cols, meta.get("regions", {})))
    return headers, rows


def _growth_table(analysis):
    cols = region_columns(analysis)
    headers = ["地区", "最新值", "上年值", "名义增速 %"]
    rows = []
    for region in cols:
        g = analysis.get("growth", {}).get(region, {})
        if not g:
            continue
        row = g.get("地区生产总值") or next(iter(g.values()), None)
        if row is None:
            continue
        rows.append([region, fmt(row["value"]), fmt(row["prev_value"]),
                     f"{fmt(row['pct'])}" if row["pct"] is not None else MISS])
    return headers, rows


def _structure_table(analysis):
    cols = region_columns(analysis)
    headers = ["地区", "第一产业 %", "第二产业 %", "第三产业 %"]
    rows = []
    for region in cols:
        s = analysis.get("structure", {}).get(region)
        if not s:
            continue
        rows.append([region,
                     fmt(s.get("第一产业增加值"), 2),
                     fmt(s.get("第二产业增加值"), 2),
                     fmt(s.get("第三产业增加值"), 2)])
    return headers, rows


def _consistency_table(analysis):
    """指标自洽校验：GDP 与三次产业和偏差、结构占比合计。"""
    cols = region_columns(analysis)
    headers = ["地区", "三产和 − GDP 偏差 %", "结构占比合计 %", "自洽性"]
    rows = []
    for region in cols:
        c = analysis.get("consistency", {}).get(region)
        if not c:
            continue
        dev = c.get("industry_sum_dev_pct")
        share = c.get("share_total")
        ok = True
        cells = []
        if dev is not None:
            cells.append(fmt(dev))
            ok = ok and abs(dev) <= 1.0
        else:
            cells.append(MISS)
        if share is not None:
            cells.append(fmt(share))
            ok = ok and abs(share - 100.0) <= 1.5
        else:
            cells.append(MISS)
        rows.append([region] + cells + ["✓" if ok else "⚠ 请核对 raw_text"])
    return headers, rows


def render_markdown(analysis):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ref = analysis.get("reference_year") or MISS
    lines = ["# 福建省统计数据对比分析报告", "",
             f"- 生成时间：{now}",
             f"- 参考年度：{ref}（最新采集年度，缺失地区以 {MISS} 表示）",
             f"- 覆盖地区：{'、'.join(region_columns(analysis))}", ""]
    if analysis.get("notes"):
        for n in analysis["notes"]:
            lines.append(f"> {n}")
        lines.append("")

    lines += ["## 一、主要指标对比", "", md_table(*_main_table(analysis)), ""]
    lines += ["## 二、地区生产总值名义增速（需相邻两个年度数据）", "",
              md_table(*_growth_table(analysis)) or "（暂无两年数据）", ""]
    lines += ["## 三、三次产业结构（占地区生产总值比重 %）", "",
              md_table(*_structure_table(analysis)) or "（暂无结构数据）", ""]
    ct = _consistency_table(analysis)
    if ct[1]:
        lines += ["## 四、指标自洽性校验（领域恒等式检查）", "",
                  md_table(*ct),
                  "> 说明：三产和与 GDP 偏差 ≤1% 且结构占比合计 ≈100% 视为自洽；⚠ 表示存在口径/归属疑点，请以原文核对。", ""]
    lines += ["## 五、说明与局限",
              "- 数据来自各级统计局官网公开发布的年度统计公报，经规则抽取入库，字段以 `raw_text` 溯源。",
              "- 增速为按公报数值计算的名义增速，未剔除价格因素；口径与官方公布的增长速度可能存在差异。",
              "- 规则抽取存在跨页引用全省/全国数值的局限，个别值可能归属有误，请以 `raw_text` 核对。",
              "- 详细指标数值见 `csv/` 目录与 Web 页面导出。", ""]
    return "\n".join(lines)


def render_html(analysis):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ref = analysis.get("reference_year") or MISS
    cols = region_columns(analysis)
    parts = []
    parts.append(f"<h1>福建省统计数据对比分析报告</h1>")
    parts.append(f"<p class='meta'>生成时间 {now} · 参考年度 {ref} · 覆盖 {len(cols)} 个地区</p>")
    if analysis.get("notes"):
        parts.append("<blockquote>" + "<br>".join(html.escape(n) for n in analysis["notes"]) + "</blockquote>")
    parts.append("<h2>一、主要指标对比</h2>")
    parts.append(html_table(*_main_table(analysis)))
    gt = _growth_table(analysis)
    if gt[1]:
        parts.append("<h2>二、地区生产总值名义增速</h2>")
        parts.append(html_table(*gt))
    st = _structure_table(analysis)
    if st[1]:
        parts.append("<h2>三、三次产业结构（%）</h2>")
        parts.append(html_table(*st))
    ct = _consistency_table(analysis)
    if ct[1]:
        parts.append("<h2>四、指标自洽性校验</h2>")
        parts.append(html_table(*ct))
    parts.append("<h2>五、说明与局限</h2>")
    parts.append("<ul>")
    for t in ["数据来自各级统计局公开发布的年度统计公报，经规则抽取入库，可经原文溯源核对。",
              "增速为按公报数值计算的名义增速，未剔除价格因素。",
              "规则抽取存在跨页引用全省/全国数值的局限，请以原文核对。"]:
        parts.append(f"<li>{t}</li>")
    parts.append("</ul>")
    body = "".join(parts)
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<title>福建省统计数据对比分析报告</title><style>"
            "body{font-family:system-ui,sans-serif;margin:24px;color:#222}"
            "table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #ccc;padding:4px 8px;font-size:13px}"
            "th{background:#f0f4f8}h1{font-size:22px}h2{font-size:17px;margin-top:24px}"
            ".meta{color:#666}blockquote{background:#f6f6f6;padding:8px;border-left:4px solid #bbb}"
            "</style></head><body>" + body + "</body></html>")


def write_reports(out_dir, analysis, md_text, html_text):
    os.makedirs(os.path.join(out_dir, "csv"), exist_ok=True)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(md_text)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(html_text)

    # 每指标宽表 CSV（region, value, unit, rank）
    table = analysis.get("table", {})
    for name, meta in table.items():
        regions = sorted(meta.get("regions", {}).items(),
                         key=lambda kv: (-kv[1], kv[0]))
        with open(os.path.join(out_dir, "csv", f"{name}.csv"), "w",
                  encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["region", "value", "unit", "rank"])
            for i, (r, v) in enumerate(regions, 1):
                w.writerow([r, fmt(v), meta.get("unit", ""), i if meta.get("rankable") else ""])
    return os.path.join(out_dir, "report.html")


# ================= M5 泉州经济纵深画像渲染 =================

_MISS = "—"


def _fmt2(v):
    return fmt(v, 2) if v is not None else _MISS


def _sev_mark(severity):
    return {"high": "🔴", "med": "⚠", "low": "ℹ"}.get(severity, "⚠")


def render_quanzhou_markdown(profile: dict) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ref = profile.get("reference_year") or _MISS
    region = profile.get("region", "泉州市")
    L = [f"# {region}经济纵深画像（{ref} 基准）", "",
         f"- 生成时间：{now}", f"- 参考年度：{ref}", ""]

    # 一、财政税收结构
    f = profile.get("fiscal", {})
    L += ["## 一、财政税收结构", "",
          md_table(
              ["指标", "数值", "单位", "口径说明"],
              [
                  ["一般公共预算收入", _fmt2(f.get("revenue")), f.get("unit", "亿元"), "地方级"],
                  ["一般公共预算支出", _fmt2(f.get("expenditure")), "亿元", "地方级"],
                  ["政府性基金收入", _fmt2(f.get("fund")), "亿元", "含土地出让"],
                  ["税收收入", _fmt2(f.get("tax")), "亿元", "口径见源"],
                  ["GDP", _fmt2(f.get("gdp")), "亿元", ""],
                  ["收入自给率（收入/支出）", _fmt2(f.get("self_sufficiency")), "%", "低于100%需上级转移支付"],
                  ["土地财政依赖度", _fmt2(f.get("land_dependence")), "%", "基金/(预算+基金)"],
                  ["财政强度（收入/GDP）", _fmt2(f.get("fiscal_intensity")), "%", "宏观税负代理"],
                  ["税收/GDP", _fmt2(f.get("tax_ratio")), "%", ""],
                  ["收入名义增速", _fmt2(f.get("revenue_growth")), "%", "相邻两年"],
              ]),
          ""]

    # 二、支柱产业图谱
    ind = profile.get("industry", [])
    L += ["## 二、支柱产业图谱", ""]
    if ind:
        for it in ind:
            inst = "、".join(it.get("policy_instruments") or []) or "—"
            L += [f"- **{it.get('industry')}**（{it.get('plan_role')}）"
                  f" 规模/目标：{it.get('scale_or_target') or '—'}；"
                  f"政策工具：{inst}",
                  f"  - 原文依据：{it.get('evidence') or '—'}"]
        L += [""]
    else:
        L += ["（暂无产业洞察数据，请先运行泉州文档采集）", ""]

    # 三、核心机构与市场主体
    m = profile.get("market", {})
    L += ["## 三、核心机构与市场主体", "",
          md_table(
              ["项目", "数值"],
              [
                  ["2025 上市后备企业数", _fmt2(m.get("total_2025"))],
                  ["上年数", _fmt2(m.get("prev_total"))],
                  ["县区集中度 HHI（0-1）", _fmt2(m.get("hhi"))],
              ]),
          ""]
    for county, n in m.get("top_counties", []):
        L += [f"- 头部县区：{county} {n} 家"]
    L += [""]

    # 四、就业岗位分布
    e = profile.get("employment", {})
    L += ["## 四、就业岗位分布", "",
          md_table(
              ["指标", "数值", "单位"],
              [
                  ["城镇新增就业", _fmt2(e.get("new_jobs")), "万人"],
                  ["新增就业密度（就业/常住人口）", _fmt2(e.get("density_permille")), "‰"],
                  ["常住人口", _fmt2(e.get("population")), "万人"],
              ]),
          ""]

    # 五、五年规划路径的数理审视
    p = profile.get("plan", {})
    L += ["## 五、五年规划路径的数理审视", ""]
    if p.get("period") or p.get("gdp_growth_target") is not None:
        L += [md_table(
            ["项目", "值"],
            [
                ["规划期", p.get("period") or _MISS],
                ["GDP 增速目标", f"{p.get('gdp_growth_target')}%" if p.get("gdp_growth_target") is not None else _MISS],
                ["预算收入增速目标", f"{p.get('revenue_growth_target')}%" if p.get("revenue_growth_target") is not None else _MISS],
                ["就业目标（万人/年）", _fmt2(p.get("jobs_target"))],
            ])]
        for ev in p.get("evidence", []):
            L += [f"- 原文依据：{ev}"]
    else:
        L += ["（暂无规划目标数据）"]
    L += [""]

    # 六、数据可信度审读
    cred = profile.get("credibility", {})
    L += ["## 六、数据可信度审读", ""]
    checks = cred.get("checks", [])
    if checks:
        L += [md_table(["检查", "主题", "结论", "说明"],
                       [[c["id"], c.get("subject"), c.get("verdict"), c.get("note")]
                        for c in checks])]
    else:
        L += ["（暂无校验记录）"]
    for k in cred.get("critiques", []):
        L += [f"- {_sev_mark(k.get('severity'))} **{k.get('type')}** 原文：{k.get('claim')}",
              f"  - 解读：{k.get('reality')}（confidence {k.get('confidence')}）",
              f"  - 待核实：{k.get('what_to_check') or '—'}"]
    for esc in cred.get("escalated", []):
        L += [f"- 🔴 重点核查：{esc.get('id')} {esc.get('subject')}（规则+LLM 双层命中）"]
    L += [""]

    L += ["---", "> 数据来源：泉州市政府公开文件（规划纲要/政府工作报告/财政预决算/企业名录/统计公报）。",
          "> LLM 输出含 evidence 原文摘录可人工复核；⚠ 为审读提示非结论。", ""]
    return "\n".join(L)


def render_quanzhou_html(profile: dict) -> str:
    md = render_quanzhou_markdown(profile)
    body = []
    for line in md.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- **") and "（" in line:
            body.append(f"<p>{html.escape(line[2:])}</p>")
        elif line.startswith("- "):
            body.append(f"<p class='li'>{html.escape(line[2:])}</p>")
        elif line.startswith("| "):
            body.append(line)  # 表格原文行，单独处理
    # 表格行聚合成 <table>
    final = []
    for ln in body:
        if isinstance(ln, str) and ln.startswith("| "):
            rows = []
            for raw in md.splitlines():
                r = raw.strip()
                if r.startswith("|"):
                    cells = [c.strip() for c in r.strip("|").split("|")]
                    if set(cells) == {"---"}:
                        continue
                    rows.append(cells)
            # 首次遇到表格头即渲染整表
            if not final or final[-1] != "__TABLE_END__":
                final.append(_md_table_to_html(rows))
                final.append("__TABLE_END__")
        elif ln == "__TABLE_END__":
            continue
        else:
            final.append(ln)
    parts = [x for x in final if x != "__TABLE_END__"]
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
            f"<title>{html.escape(profile.get('region', '泉州'))}经济纵深画像</title>"
            "<style>body{font-family:system-ui,sans-serif;margin:24px;color:#222}"
            "table{border-collapse:collapse;margin:8px 0}th,td{border:1px solid #ccc;padding:4px 8px;font-size:13px}"
            "th{background:#f0f4f8}h1{font-size:22px}h2{font-size:17px;margin-top:24px;border-bottom:1px solid #ddd;padding-bottom:4px}"
            ".li{margin:2px 0}.meta{color:#666}</style></head><body>"
            + "\n".join(parts) + "</body></html>")


def _md_table_to_html(rows):
    if not rows:
        return ""
    thead = "".join(f"<th>{html.escape(str(c))}</th>" for c in rows[0])
    body = ""
    for row in rows[1:]:
        body += "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>"
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>"


def write_quanzhou_report(out_dir, profile, md_text, html_text) -> str:
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "quanzhou_profile.md")
    html_path = os.path.join(out_dir, "quanzhou_profile.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return html_path
