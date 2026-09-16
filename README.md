# 统计局数据采集平台

从**国家统计局**官网出发，逐级自动发现「国家 → 省级 → 地级市」统计局官方站点，采集网页与 PDF 文字型的**年度统计公报**（综合公报 + 专题公报），经规则抽取结构化后**按年度分门别类入库**，并提供**一键对比分析报告**（省/市对比、排名、名义增速、三次产业结构）。

试点范围：**福建省全流程**（福建省统计局 + 9 个设区市）。

## 功能特性

- **递进 URL 发现**：从国家统计局首页按「域名模式 + 链接文本 + 标题校验 + 白名单兜底」逐级发现省市统计局官网；命中目标即停、白名单优先。
- **手工锚点机构**：对无独立 `tjj` 域名、无法自动发现的站点（如**莆田市统计局**挂在政府门户子版块），通过 `manual_bureaus` 配置补全机构与采集入口。
- **站内检索定位公报**：动态列表站点（莆田）通过门户 **was5 检索接口**按关键词定位公报文章。
- **PDF 文字提取**：公报为 PDF（如莆田近年公报）时用 `pdfplumber` 提取文字，与网页正文走同一抽取管线。
- **非表格数据提取**：配置化指标词典 + 正则抽取（自动清洗脚注角标、`（GDP）` 标注等噪声），结果带 `raw_text` 原文溯源；预留 `LLMExtractor` 接口。
- **分门别类存放**：按机构（三级）/ 页面 / 指标 / 年度落库，SQLite 存储，去重入库。
- **对比分析报告**：一键生成 Markdown / HTML / CSV——参考年度下省与各市指标对比宽表、GDP 名义增速（需两年）、三次产业结构占比。
- **一键自动化**：`python run.py` 端到端采集，`python run.py analyze` 出报告，各站点失败隔离、运行日志可追踪。
- **最小 Web 界面**：一键运行采集、浏览数据与导出、查看分析报告。

## 架构

```
discovery(URL 递进发现 + manual 锚点 + was5 检索)
       → fetch(requests + BeautifulSoup + pdfplumber)
       → extract(RuleExtractor，规则抽取 / LLMExtractor 预留)
       → store(SQLite 分类表)
       → 输出：web(FastAPI) / 分析(analyze.py → 对比报告)
```

## 快速开始

```bash
cd stats-collector
python -m venv .venv --system-site-packages
.venv\Scripts\activate
pip install -r requirements.txt
```

**一键采集（命令行）**
```bash
python run.py
```
打印 run_id / status / 各阶段统计，数据写入 `data/stats.db`。

**一键分析（命令行）**
```bash
python run.py analyze        # 或 python analyze.py
```
在 `data/reports/` 生成 `report.md`、`report.html` 与每指标 `csv/` 宽表。

**Web 界面**
```bash
python -m app.main
```
打开 <http://127.0.0.1:8000/> ：运行采集、运行历史/日志、机构列表、数据查询与 CSV 导出、一键生成对比分析报告（内嵌预览）。

**测试**
```bash
python -m pytest -v
```

## 配置

| 文件 | 说明 |
|------|------|
| `config/bureaus.yaml` | 种子、省级锚点、地市预期清单、白名单/排除域名、**manual_bureaus（莆田：机构 URL + was5 检索配置）**、公报关键词 |
| `config/extract_rules.yaml` | 指标词典（规范名 / 别名 / 单位 / 分类 / 抽取正则） |

扩展其他省：调整种子/锚点/预期地市清单；存在无独立域名的地市时补 `manual_bureaus`。

## 数据模型（SQLite）

| 表 | 说明 |
|----|------|
| `bureaus` | 三级统计局机构（含手工锚点机构） |
| `pages` | 采集页面（url / 正文 / 年度 / 内容哈希去重） |
| `indicators` | 指标词典 |
| `data_values` | 结构化指标值（region / year / indicator_name / value / unit / category / raw_text） |
| `runs` | 运行记录 |

## 目录结构

```
stats-collector/
├── app/
│   ├── main.py               # FastAPI 入口与端点（含 /api/analysis）
│   ├── orchestrator.py       # 一键管线（发现→采集→抽取→入库；manual/was5/PDF 分支）
│   ├── analysis/             # 分析 core（宽表/排名/增速/结构）+ report（MD/HTML/CSV）
│   ├── discovery/            # URL 递进发现（registry / resolver）
│   ├── fetch/                # HTTP 客户端 + HTML 解析 + pdf.py + search.py（was5）
│   ├── extract/              # 抽取器（base / rule_extractor / llm_extractor 预留）
│   ├── store/                # SQLite 建表 + 仓储
│   └── web/static/           # 单页前端
├── analyze.py                # 分析 CLI
├── config/                   # 站点与抽取规则配置
├── data/                     # stats.db 与 reports/（运行时生成，gitignored）
├── docs/                     # DESIGN.md / PLAN.md
├── tests/                    # pytest 测试（夹具驱动，离线可跑）
├── run.py                    # CLI：采集 / analyze 子命令
└── requirements.txt
```

## 已知限制（如实说明）

- **厦门市等个别地市偶发漏检**：瞬时网络抖动导致某次运行未发现该站，重跑即可补回（bureaus upsert 幂等累积）。
- **常住人口 / 固定资产投资 / 居民消费价格指数** 覆盖率受公报排版差异影响（人口段常无编号章节标题、投资/CPI 表述多样），当前以可稳定抽取的绝对量指标（GDP、三次产业、收入、贸易、财政等）为主；详见报告「说明与局限」。
- **名义增速需相邻两年数据**：当前采集深度为「最近一期」，单年数据无法计算增速；如需增速请扩展历史年度采集（二期）。
- **规则抽取局限**：个别页面引用全省/全国对比值可能产生归属噪声，均以 `raw_text` 溯源可核；LLM 抽取为二期规划方向。
- 莆田市无独立 `tjj` 域名，其公报经门户 was5 检索 + PDF 文字提取接入（PDF 若为扫描版则无法提取文字）。

## 二期规划

1. 落地 `LLMExtractor`（OpenAI 兼容端点）提升非结构化文字理解与城镇/农村细分指标。
2. 采集历史年度（如近 3 年）以支持名义增速与趋势分析。
3. 扩展至全国 31 省 + 全部地级市（`manual_bureaus` 覆盖无独立域名站点）。
