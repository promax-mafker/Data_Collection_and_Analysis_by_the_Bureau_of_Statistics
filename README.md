# 统计局数据采集平台

从**国家统计局**官网出发，逐级自动发现「国家 → 省级 → 地级市」三级统计局官方网站，采集网页文字类的**年度统计公报**（综合公报 + 单独发布的专题指标公报），经规则抽取（预留 LLM 接口）结构化后**按年度分门别类入库**，提供一键运行、运行日志与数据浏览导出。

## 功能特性

- **递进 URL 发现**：从国家统计局首页出发，按「域名模式 + 链接文本 + 标题校验 + 白名单兜底」逐级发现省级与地级市统计局官网，无需手工维护全部网址。
- **非表格数据理解与提取**：统计公报多为文字段落而非规整表格，通过配置化的指标词典 + 正则规则抽取结构化指标，每条结果保留原文片段（`raw_text`）便于溯源核对。
- **分门别类存放**：按「机构（三级）/ 页面 / 指标（14 类）/ 年度」落库，SQLite 存储，支持按地区、指标、年份查询与 CSV 导出。
- **可插拔抽取器**：本次落地 `RuleExtractor`（规则抽取），预留 `LLMExtractor` 接口，二期接入 LLM 后无需改动其他层。
- **一键自动化**：一条命令端到端完成「发现 → 采集 → 抽取 → 入库」，各站点失败隔离，运行日志可追踪。
- **最小 Web 界面**：单页前端，一键运行采集、查看运行历史/日志、浏览数据、导出 CSV。

## 架构

```
discovery(URL 递进发现) → fetch(requests + BeautifulSoup 同步采集)
       → extract(抽取器接口: RuleExtractor / LLMExtractor 预留)
       → store(SQLite 分类表) → web(FastAPI + 单页) → orchestrator(一键管线)
```

数据流：`一键运行 → 递进发现三级机构 → 逐站定位公报栏目 → 抓取详情页 → 规则抽取 → 分类入库 → 运行记录`

## 快速开始

### 1. 创建虚拟环境并安装依赖

```bash
cd stats-collector
python -m venv .venv --system-site-packages
.venv\Scripts\activate
pip install -r requirements.txt
```

> 依赖：`requests` / `beautifulsoup4` / `fastapi` / `uvicorn` / `PyYAML` / `pytest` / `httpx`。

### 2. 一键运行（命令行）

```bash
.venv\Scripts\python run.py
```

运行后会打印 `run_id`、`status`、各阶段统计（bureaus / pages / values / errors）与日志，数据写入 `data/stats.db`。

### 3. 启动 Web 界面

```bash
.venv\Scripts\python -m app.main
```

浏览器打开 <http://127.0.0.1:8000/> ，点「运行采集」，即可查看运行历史、三级机构列表、数据表，并导出 CSV。

### 4. 运行测试

```bash
.venv\Scripts\python -m pytest -v
```

## 配置

| 文件 | 说明 |
|------|------|
| `config/bureaus.yaml` | 种子站点、省级锚点、地市预期清单、白名单/排除域名、公报关键词 |
| `config/extract_rules.yaml` | 指标词典（规范名 / 别名 / 单位 / 分类 / 抽取正则） |

**试点范围**：国家统计局 + 福建省统计局 + 福建省 9 个设区市。要扩展到其他省，只需在 `bureaus.yaml` 中调整种子/锚点与地市清单。

## 数据模型（SQLite）

| 表 | 说明 |
|----|------|
| `bureaus` | 三级统计局机构（level / name / url / region / parent_id） |
| `pages` | 采集页面（url / 正文 / dataset_type / 年度 / 哈希去重） |
| `indicators` | 指标词典 |
| `data_values` | 结构化指标值（region / year / indicator_name / value / unit / category / raw_text） |
| `runs` | 运行记录（状态 / 阶段统计 / 日志） |

## 目录结构

```
stats-collector/
├── app/
│   ├── main.py               # FastAPI 入口与端点
│   ├── orchestrator.py       # 一键管线编排
│   ├── discovery/            # URL 递进发现（registry / resolver）
│   ├── fetch/                # HTTP 客户端 + HTML 解析
│   ├── extract/              # 抽取器（base / rule_extractor / llm_extractor 预留）
│   ├── store/                # SQLite 建表 + 仓储
│   └── web/static/           # 单页前端
├── config/                   # 站点与抽取规则配置
├── data/                     # stats.db（运行时生成，gitignored）
├── docs/                     # DESIGN.md / PLAN.md
├── tests/                    # pytest 测试（夹具驱动，离线可跑）
├── run.py                    # CLI 一键运行
└── requirements.txt
```

## 已知限制

- **莆田市**无独立 `tjj` 域名（挂在 `www.putian.gov.cn` 政府门户下），递进发现无法按域名/标题自动识别，需手工锚点补充。
- **瞬时网络抖动**可能导致个别站点某次运行漏检，重跑即可补回（机构 upsert 幂等累积）。
- **规则抽取固有限制**：「居民人均可支配收入」暂未区分全体/城镇/农村；个别页面引用全省数据会产生跨页归属。这两类场景是二期 `LLMExtractor` 的重点。

## 路线图（二期）

1. 落地 `LLMExtractor`（OpenAI 兼容端点），解决非表格文字的「理解 → 提取」难点与城镇/农村细分。
2. 为莆田补手工锚点，并扩展至全国 31 省 + 全部地级市（早停机制已支持目标制）。
3. 支持历史年度回溯采集。
