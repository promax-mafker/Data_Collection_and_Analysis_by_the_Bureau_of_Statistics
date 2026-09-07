"""Kami Parchment Document HTML 渲染器（M6 报告视觉）。

视觉签名：暖羊皮纸底 + 墨蓝唯一强调 + 衬线字体 + 编辑级排版。
规范来源 tresearch skill 的 kami-spec.md。产出完全独立 HTML（内联 CSS）。
"""
import html as _html


class KamiRenderer:
    def __init__(self, title, report_type, date_line):
        self.title = title
        self.report_type = report_type
        self.date_line = date_line
        self._body = []
        self._toc = []

    # ---------- 构建 ----------

    def section(self, sid, heading):
        """开启一个可跳转的章节。"""
        self._toc.append((sid, heading))
        self._body.append(f'<section id="{sid}">')
        self._body.append(f"<h2>{_html.escape(heading)}</h2>")
        return self

    def para(self, text):
        self._body.append(f"<p>{_html.escape(text)}</p>")
        return self

    def table(self, headers, rows, align_right=None):
        align_right = align_right or []
        thead = "".join(f"<th>{_html.escape(str(h))}</th>" for h in headers)
        body = ""
        for row in rows:
            tds = []
            for i, c in enumerate(row):
                cls = ' class="num"' if i in align_right else ""
                tds.append(f"<td{cls}>{_html.escape(str(c))}</td>")
            body += "<tr>" + "".join(tds) + "</tr>"
        self._body.append(
            f'<table><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>')
        return self

    def source(self, url, name, date):
        self._body.append(
            f'<p class="source">来源 <a href="{_html.escape(url)}">{_html.escape(name)}</a>'
            f" · {_html.escape(date)}</p>")
        return self

    def bullish(self, text):
        self._body.append(f'<span class="bullish">{_html.escape(text)}</span>')
        return self

    def bearish(self, text):
        self._body.append(f'<span class="bearish">{_html.escape(text)}</span>')
        return self

    def note_limited(self, text):
        self._body.append(f'<p class="note-limited">⚠ {_html.escape(text)}</p>')
        return self

    def blockquote(self, text):
        self._body.append(f"<blockquote>{_html.escape(text)}</blockquote>")
        return self

    # ---------- 输出 ----------

    def doc(self):
        toc = "".join(
            f'<li><a href="#{sid}">{_html.escape(h)}</a></li>' for sid, h in self._toc)
        header = (
            f'<header><p class="report-type">{_html.escape(self.report_type)}</p>'
            f"<h1>{_html.escape(self.title)}</h1>"
            f'<p class="date-line">{_html.escape(self.date_line)}</p>'
            f'<nav><ol>{toc}</ol></nav></header>')
        body = "\n".join(self._body)
        return _KAMI_TEMPLATE.format(
            title=_html.escape(self.title), header=header, body=body)


_KAMI_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{
    background-color: #f5f4ed;
    color: #1f1d18;
    font-family: 'Noto Serif SC', 'Source Han Serif SC', 'STSong', 'SimSun', 'Crimson Text', Georgia, serif;
    font-size: 1rem; font-weight: 400; line-height: 1.65;
    max-width: 720px; margin: 0 auto; padding: 3rem 2rem 4rem;
  }}
  header {{ margin-bottom: 2.5rem; padding-bottom: 1.5rem;
           border-bottom: 2px solid rgba(27, 54, 93, 0.3); }}
  .report-type {{ font-size: 0.8rem; color: #8a8780; text-transform: uppercase;
                 letter-spacing: 0.12em; margin-bottom: 0.5rem; }}
  h1 {{ font-size: 2.2rem; font-weight: 500; line-height: 1.2; color: #1B365D; margin: 0; }}
  .date-line {{ font-size: 0.85rem; color: #4a4742; margin-top: 0.5rem; }}
  nav ol {{ margin: 1rem 0 0; padding-left: 1.2rem; font-size: 0.9rem; }}
  nav a {{ color: #1B365D; text-decoration: none;
           border-bottom: 1px dotted rgba(27, 54, 93, 0.3); }}
  section {{ margin-top: 2.5rem; }}
  section:first-of-type {{ margin-top: 2rem; }}
  section h2 {{ font-size: 1.4rem; font-weight: 500; line-height: 1.3; color: #1f1d18;
                padding-bottom: 0.35rem;
                border-bottom: 1px solid rgba(27, 54, 93, 0.25); }}
  p {{ margin: 0.6rem 0; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1.2rem 0; font-size: 0.95rem; }}
  thead th {{ font-weight: 500; text-align: left; padding: 0.5rem 0.75rem;
              border-bottom: 2px solid rgba(27, 54, 93, 0.3); color: #1f1d18;
              font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.06em; }}
  tbody td {{ padding: 0.45rem 0.75rem; border-bottom: 1px solid rgba(27, 54, 93, 0.08); }}
  tbody tr:hover {{ background-color: rgba(27, 54, 93, 0.03); }}
  td.num {{ text-align: right; font-family: 'JetBrains Mono', 'Consolas', monospace; }}
  .source {{ font-size: 0.8rem; color: #8a8780; margin-top: 0.25rem; }}
  .source a {{ color: #1B365D; text-decoration: none;
               border-bottom: 1px dotted rgba(27, 54, 93, 0.3); }}
  .bullish {{ color: #2d5016; font-weight: 500; }}
  .bearish {{ color: #8b1a1a; font-weight: 500; }}
  .note-limited {{ color: #8a8780; font-style: italic; padding: 0.5rem 0;
                   border-left: 2px solid rgba(27, 54, 93, 0.15); padding-left: 0.8rem; }}
  blockquote {{ margin: 0.8rem 0; padding: 0.6rem 0.9rem; color: #4a4742;
                border-left: 2px solid rgba(27, 54, 93, 0.15);
                background: rgba(27, 54, 93, 0.02); }}
  footer {{ margin-top: 3rem; padding-top: 1.5rem;
            border-top: 1px solid rgba(27, 54, 93, 0.15);
            font-size: 0.8rem; color: #8a8780; }}
  @media (max-width: 720px) {{
    body {{ padding: 1.5rem 1rem; font-size: 0.95rem; }}
  }}
</style>
</head>
<body>
<article>
{header}
{body}
<footer><p>本报告数据来自泉州市政府公开文件（统计局/财政局），经规则与 LLM 抽取，可溯源。口径与局限见各章标注。</p></footer>
</article>
</body>
</html>"""
