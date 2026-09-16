# 统计局数据采集平台 · 设计文档

## 1. 项目概述

### 1.1 目标

一个 Python Web 管理平台，从国家统计局官网出发，逐级自动发现「国家 → 福建省 → 福建各地级市」统计局官方网址，采集网页文字类的年度统计公报（综合公报 + 单独发布的专题指标公报），经规则抽取（预留 LLM 接口）结构化后按年度分类入库，提供一键运行、运行日志与数据浏览导出。

### 1.2 试点范围

| 维度 | 范围 |
|------|------|
| 地域 | 国家统计局 + 福建省统计局 + 福建省 9 个设区市（福州、厦门、漳州、泉州、三明、莆田、南平、龙岩、宁德） |
| 数据形态 | 网页文字 / 统计公报（不含 Excel、PDF） |
| 数据集 | 年度《国民经济和社会发展统计公报》+ 单独发布的年度专题指标公报（按年度为标尺） |
| 抽取方式 | 规则抽取（本次），LLM 抽取器接口（预留，二期落地） |

### 1.3 验收标准（可验证）

1. 一键运行后，国家 + 福建 + 福建各地级市统计局官方网址自动发现并落库，数量正确、链接可访问（校验：查库计数 + 抽样访问）。
2. 对选定公报/指标页面完成「采集 → 规则抽取 → 分类入库」，入库字段与原始页面抽样对比一致（校验：抽样 diff）。
3. 全流程端到端无人工干预跑通（校验：一条命令跑完，日志成功/失败数可追踪）。

### 1.4 非目标（本次明确不做）

- 定时/实时更新（仅手动触发）
- 数据可视化 / 图表前端
- 登录 / 多用户权限
- Excel / PDF 文件解析
- 月度 / 季度指标（本次仅做年度数据）
- LLM 抽取落地（只留接口）

---

## 2. 总体架构

采用「分层模块化单体」，同步爬取 + 可插拔抽取器。

```
discovery(URL 递进发现) → fetch(requests + BeautifulSoup 同步采集)
       → extract(抽取器接口: 本次 RuleExtractor / 预留 LLMExtractor)
       → store(SQLite 分类表) → web(FastAPI + 单页) → orchestrator(一键管线)
```

数据流：

```
一键运行(orchestrator)
  ├─ 1. discovery: 国家官网 → 省级官网 → 地市官网（链接发现 + 域名模式 + 校验）
  ├─ 2. fetch:     逐站定位综合公报与专题指标公报栏目，抓取列表页与详情页
  ├─ 3. extract:   规则抽取 → 结构化指标值（DataValue）
  ├─ 4. store:     去重入库（bureaus / pages / data_values / runs）
  └─ 5. 汇总:      返回 run_id + 各阶段成功/失败统计
```

各层职责与依赖方向：`web` 只依赖 `orchestrator` 与 `store`；`orchestrator` 按顺序调用 `discovery → fetch → extract → store`；`extract` 只依赖 `fetch` 产出的页面文本，不反向依赖。

---

## 3. 代码目录结构

```
stats-collector/
├── README.md
├── requirements.txt
├── config/
│   ├── bureaus.yaml          # 种子 + 站点注册表（校验白名单 / 提示）
│   └── extract_rules.yaml    # 指标词典 + 抽取规则
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI 入口与路由
│   ├── orchestrator.py       # 一键管线编排
│   ├── discovery/
│   │   ├── __init__.py
│   │   ├── registry.py       # 读取 bureaus.yaml 注册表
│   │   └── resolver.py       # 链接发现 + 域名模式匹配 + 站点校验
│   ├── fetch/
│   │   ├── __init__.py
│   │   ├── client.py         # HTTP 客户端（重试/限速/UA/robots）
│   │   └── parser.py         # HTML → 标题/正文/链接/去重
│   ├── extract/
│   │   ├── __init__.py
│   │   ├── base.py           # Extractor 抽象接口
│   │   ├── schemas.py        # DataValue / Page 数据类
│   │   ├── rule_extractor.py # 规则抽取（综合公报 / 专题公报）
│   │   └── llm_extractor.py  # 预留（二期）
│   ├── store/
│   │   ├── __init__.py
│   │   ├── db.py             # SQLite 建表与连接
│   │   └── repository.py     # 增删改查 / 去重
│   └── web/
│       ├── __init__.py
│       └── static/
│           ├── index.html
│           ├── app.js
│           └── style.css
├── data/                     # 运行时生成 stats.db
├── tests/
│   ├── test_discovery.py
│   ├── test_extract.py
│   ├── test_store.py
│   └── test_orchestrator.py
└── docs/
    ├── DESIGN.md
    └── PLAN.md
```

---

## 4. 数据模型（SQLite）

### 4.1 `bureaus`（统计局机构）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| level | TEXT | `national` / `province` / `city` |
| name | TEXT | 机构名，如「国家统计局」「福建省统计局」「福州市统计局」 |
| url | TEXT | 官网首页 URL |
| region | TEXT | 地域名，如「中国」「福建省」「福州市」 |
| parent_id | INTEGER FK | 上级机构 id，national 为 NULL |
| verified | INTEGER | 0/1，是否通过站点校验 |
| discovered_at | TEXT | 发现时间 |

### 4.2 `pages`（采集页面）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| bureau_id | INTEGER FK | 归属机构 |
| url | TEXT UNIQUE | 页面 URL |
| title | TEXT | 页面标题 |
| content_text | TEXT | 清洗后正文文本 |
| dataset_type | TEXT | `bulletin`（综合公报）/ `topic`（专题指标公报） |
| period | TEXT | 年度，如 `2024` |
| content_hash | TEXT | 正文哈希，用于去重 |
| fetched_at | TEXT | 抓取时间 |
| status | TEXT | `fetched` / `failed` |

### 4.3 `indicators`（指标词典）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| name | TEXT | 规范指标名，如「地区生产总值」 |
| aliases | TEXT | 别名 JSON 数组，如 `["GDP", "生产总值"]` |
| unit | TEXT | 默认单位 |
| category | TEXT | 章节分类，如「综合」「人民生活」 |

### 4.4 `data_values`（结构化指标值）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| page_id | INTEGER FK | 来源页面 |
| bureau_id | INTEGER FK | 归属机构（冗余，便于查询） |
| region | TEXT | 地域名 |
| year | TEXT | 年份 |
| indicator_name | TEXT | 指标名 |
| value | TEXT | 数值 |
| unit | TEXT | 单位 |
| category | TEXT | 章节分类 |
| raw_text | TEXT | 原文片段，用于溯源与抽样校验 |
| method | TEXT | `rule`（本次）/ `llm`（预留） |
| extracted_at | TEXT | 抽取时间 |

### 4.5 `runs`（运行记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增 |
| started_at | TEXT | 开始时间 |
| finished_at | TEXT | 结束时间 |
| status | TEXT | `running` / `success` / `partial` / `failed` |
| summary_json | TEXT | 各阶段成功/失败统计（JSON） |
| log | TEXT | 运行日志 |

---

## 5. 关键流程

### 5.1 URL 递进发现（discovery）

核心机制：**递进发现为主，注册表校验兜底**，而不是硬编码全部 URL。

1. 种子：`bureaus.yaml` 中声明国家统计局官网首页 `https://www.stats.gov.cn/`，并预置福建省统计局官网 `https://tjj.fujian.gov.cn/` 作为省级锚点。
2. 省级发现：抓取国家站首页与其导航/链接页，提取全部 `<a>` 链接，解析为绝对 URL，去重；按「域名模式 + 链接文本」过滤候选（域名匹配 `tjj.<拼音>.gov.cn`，或链接文本含「统计局 / 统计」），再逐条校验（抓取标题，确认含「统计局」）。
3. 地市发现：对每个已发现的省级站，重复第 2 步，发现其下地级市统计局链接。
4. 校验与落库：通过校验的站点写入 `bureaus`；`bureaus.yaml` 中的注册表作为「已知官方域名白名单」用于兜底补齐与去伪（例如发现结果与白名单不一致时以白名单纠正，发现遗漏时以白名单补全）。
5. 福建省 9 个设区市名称在 `bureaus.yaml` 中作为预期清单，运行后校验是否全部发现。

### 5.2 采集（fetch）

1. 对每个 `bureaus`，在站内定位「统计公报」栏目，以及单独发布的年度专题指标公报（如工业、农业、人口、R&D 经费等，由链接文本关键词匹配；栏目定位规则写入 `bureaus.yaml`）。
2. 抓取列表页，提取详情页链接，逐条抓取详情页。
3. 清洗为正文文本 `content_text`，记录 `title`、`period`（年度）、`dataset_type`，计算 `content_hash` 去重。
4. 限速、超时、重试（2 次指数退避）、UA 与 robots 尊重均在 `fetch/client.py` 统一处理。
5. 本次仅采集最新一个年度（最近一期）的公开公报，历史年度留待二期。

### 5.3 规则抽取（extract）

`RuleExtractor` 实现 `Extractor` 接口，配置驱动：

1. 统一以「年度」为标尺，产出以 `(region, year, indicator)` 为键：
   - `bulletin`（综合公报）：按章节标题（一、二、……或「（一）」）切分正文，逐章用指标模式抽取。
   - `topic`（专题指标公报）：针对该专题的指标集合抽取（如工业专题抽「规模以上工业增加值」、人口专题抽「常住人口」等）。
2. 指标词典来自 `extract_rules.yaml`：每个指标含规范名、别名、默认单位、分类、数值正则。
3. 抽取产出 `DataValue`（含 `raw_text` 原文片段，供溯源与抽样校验），`method=rule`。
4. 抽取失败不阻断整体：单条失败记录日志，其余继续。

`LLMExtractor` 本次仅定义接口（`extract(page, config)`），不实现真实调用，二期接入 OpenAI 兼容端点后无需改动其他层。

### 5.4 一键管线（orchestrator）

`run_pipeline()` 依次执行 discovery → fetch → extract → store，各阶段 try/except 隔离（单站点失败不影响整体），结束后写入 `runs` 记录并返回 `run_id` 与阶段统计。

### 5.5 Web 界面（最小可用）

单页静态前端（原生 JS，无框架）+ FastAPI 后端：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/run` | POST | 触发一键管线，返回 `run_id` |
| `/api/runs` | GET | 运行历史 |
| `/api/runs/{id}` | GET | 运行详情 + 日志 + 阶段统计 |
| `/api/bureaus` | GET | 三级机构列表 |
| `/api/data?bureau=&indicator=&year=` | GET | 数据查询 |
| `/api/export?bureau=&year=` | GET | 导出 CSV |

前端页面：一个「运行采集」按钮、运行历史与日志区、数据浏览表、导出按钮。

---

## 6. 错误处理与边界

- 反爬 / 网站改版：域名模式与校验阈值做成配置，可调；失败站点跳过并记录。
- robots 尊重：默认开启，可在 `bureaus.yaml` 关闭（个人研究用途）。
- 限速：请求间隔默认 1 秒，可配置。
- 去重：URL 唯一约束 + 正文 `content_hash`。
- 失败隔离：站点级、页面级异常均捕获，写入 `runs.log`，不中断全局。

---

## 7. 二期预留（本次不做）

- `LLMExtractor` 真实实现（OpenAI 兼容端点）
- 异步并发爬取（httpx + asyncio 任务池）
- 扩展至全国 31 省级 + 全部地级市
- Excel / PDF 年鉴解析
- 定时调度、图表、登录权限

---

## 8. 风险与依赖

| 风险 | 缓解 |
|------|------|
| 统计局网站改版、链接结构变化 | 域名模式 + 注册表白名单双重兜底；规则配置化 |
| 公报非结构化、表述差异 | 指标别名词典 + `raw_text` 溯源，抽样校验 |
| 反爬限制 | 限速、UA、robots、重试；个人低频使用风险低 |
| 依赖 Python 环境 | requirements.txt 固定依赖，标准库优先（SQLite 用 `sqlite3`） |

---

## 9. 本轮扩展落地记录（2026-09，福建全流程试点）

在基础采集之上，为「福建省采集 + 分析全流程」补充以下能力（对应代码以 `git log` 为准）：

### 9.1 莆田市接入（无独立统计域名的站点）

- 莆田统计局挂在政府门户 `www.putian.gov.cn` 子版块（`/zfxxgk/bmzfxxgk/ptstjj/`），列表页为前端 JS 动态渲染，静态无法定位文章。
- 方案：`config/bureaus.yaml` 新增 `manual_bureaus`（手工锚点机构，含 `bulletin_search` 检索配置）；`orchestrator` 在递进发现后补入手工机构并走 **was5 站内检索**（`app/fetch/search.py`）定位公报。
- 近年莆田公报为 **PDF**：`app/fetch/pdf.py`（pdfplumber）提取文字后进入统一抽取管线；`HttpClient.download` 提供二进制下载。
- 经验参数：was5 检索需 `perpage` 足够大（≥50）且经标题 `include/exclude` 过滤（排除区县/解读/通知）。

### 9.2 采集健壮性修正（真实验证暴露）

- **同域过滤**：公报详情链接仅限本机构域名，排除首页上跨站引用（如市级站链向 `stats.gov.cn` 发布的各省数据页）造成的归属污染。
- **内容哈希去重**：同一内容经不同 URL（http/https、多栏目）多次抓取时，第二次起跳过，避免重复入库与重复运行累积。
- **正文清洗**：抽取前删除脚注角标 `[n]`、`（GDP）` 括号标注、零宽字符（真实公报中这些字符会插在「地区生产总值 [2] 60199.45 亿元」之间阻断正则）。
- **人均前缀排除**：GDP 规则以 `(?<!人均)` 排除「人均地区生产总值」误匹配；恢复 `GDP` 英文备选以兼容厦门等表述。
- **年度取自标题优先**：PDF 公报正文开头为发布日期（如「2026 年4月15 日」），年度优先从标题（「2025 年…统计公报」）提取，正文作兜底。

### 9.3 分析模块（`app/analysis/`）

- `core.py`：从 `data_values` 读取结构化值 → 参考年度宽表、各市排名、GDP 名义增速（需相邻两年）、三次产业结构（占 GDP 比重）。
- `report.py`：渲染 Markdown / HTML / CSV（每指标宽表 `data/reports/csv/`）。
- 入口：CLI `run.py analyze`（或 `analyze.py`）、Web `GET /api/analysis` + 页面「生成对比分析报告」。
- 局限：固定资产投资 / 常住人口 / CPI 覆盖率受公报排版差异影响；增速需两年数据（当前只采最近一期，属二期扩展）。
