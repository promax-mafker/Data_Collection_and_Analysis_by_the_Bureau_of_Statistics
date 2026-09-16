# PLAN M9b · 泉州年鉴采集与多源数据模型

| 项 | 值 |
|---|---|
| 状态 | 执行中 |
| 对应设计 | `docs/planning/DESIGN_M9_MULTISOURCE.md` 轨 A4(年鉴采集器)+ §5(数据模型变更) |
| **执行方式** | 内联执行(串行改 `parse`/`store`/新采集器) |
| 测试基线 | 245 passed,必须保持全绿 |
| 本轮范围 | 泉州年鉴 2016-2025 的**宽表解析 + 入库 + 主源视图**;福建年鉴与地方债务源留下一轮 |

## 1. 目标与依据(实测)

泉州年鉴在线版为「**年份为列、指标为行**」的宽表。实测 `qztjnj2024/cn/html/0102.htm`:
1 个 `<table>`、38 行、36 列,表头 `['指标名称','单位','1949','1952',…,'2023']`,
表头单元格形如 `1985<br>年`(换行在同一格内,非跨列),数据行与之逐列对齐。

**单张 `0102` 表即可提供 泉州 1949-2023 的户籍人口 + GDP + 三次产业**,是 A 类时序的正源(年鉴为修订后口径)。

TOC 实测 210 条链接,关键多年份表:
| 表 | 标题 | 补什么 |
|---|---|---|
| `0102` | 国民经济主要年份主要指标 | 人口/GDP/三产长序列 |
| `0304` | 主要年份年末常住人口及人口变动 | **常住人口**(原 4/10 地区) |
| `0502` | 历年全国、全省、全市居民消费价格总指数 | **CPI**(原 3/10 地区) |
| `0310` | 主要年份年末全社会从业人员数 | **就业** |
| `0603` | 历年一般公共预算收支情况 | 财政 + 债务相关 |
| `0203` | 历年地区生产总值 | GDP 复核 |
| `1203` | 历年进出口总额 | 外贸 |

⚠️ **硬约束(设计 P2)**:表号会位移(`0102`↔`0103`,2024 卷已实测),2025 卷文件形态变异
(`NNNN.htm` → `NNNN_T-T.html`)。**一律按标题匹配,从 TOC 解析,禁止拼 URL/硬编码表号。**

## 2. 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/parse/yearbook.py` | **新增** | 年鉴 TOC 解析/标题匹配 + 宽表转置 |
| `app/fetch/yearbook.py` | **新增** | 年鉴卷采集编排(逐年 → TOC → 按标题取表 → 入库) |
| `app/store/db.py` | 修改 | 迁移:`data_values.source_kind/source_rank` + `data_values_primary` 视图 |
| `app/store/repository.py` | 修改 | `query_data(primary_only=True)` 默认读主源视图 |
| `config/yearbook_sources.yaml` | **新增** | 卷 URL 模板 + 目标表标题模式 |
| `tests/test_yearbook_parse.py` | **新增** | TOC 匹配 + 宽表转置(真实夹具) |
| `tests/test_source_rank.py` | **新增** | 主源视图唯一性与优先级 |
| `tests/fixtures/qz_yearbook_toc_2024.htm` | 已存 | 真实 TOC 夹具 |
| `tests/fixtures/qz_yearbook_0102.htm` | 已存 | 真实宽表夹具 |
| `tests/fixtures/qz_yearbook_0603.htm` | 已存 | 真实财政表夹具 |

## 3. 任务

### T1 · TOC 解析与标题匹配(红→绿)
- `load_toc(html, base_url) -> [(url, title)]`
- `normalize_title(t) -> str`:去序号前缀(`1—2`/`1-2`/`1．`)、统一全角破折号、压空格、去尾部「（20XX年）」
- `match_tables(toc, patterns) -> dict[str, str]`:pattern → 表 URL;**匹配不到返回缺失,不猜**
- 红灯:`.venv\Scripts\python -m pytest tests/test_yearbook_parse.py -q`
- 验:用 2024 真实 TOC,断言 `0102/0304/0502/0603` 均能按标题命中

### T2 · 宽表转置(红→绿)
- `parse_year_columns(html, table_index=0) -> list[dict]`
  - 复用 `app/parse/series_table.py::_grid`(矩形展开,已解决 colspan/rowspan)
  - 表头行 = 前 8 行中年份格 ≥3 的行
  - 输出 `[{indicator, unit, values: {year: value}}]`
  - 分组行(如 `2. 国民经济核算`,其余格为空)→ 跳过,但记录为 `section`
  - 指标名保留 `#` 前缀语义(次要项)与括号口径(如「（当年价）」)
- 验:真实 `0102` 夹具,断言含 GDP 行、年份数 ≥30、值可解析

### T3 · 数据模型:来源与主源视图(红→绿)
- 迁移 `source_kind TEXT`、`source_rank INTEGER DEFAULT 1`(幂等)
- `data_values_primary` 视图:同 `(region,year,indicator_name,caliber)` 取 `source_rank` 最小 → `extracted_at` 最新
- `query_data(..., primary_only=True)` 默认读视图;`include_alt=True` 才看全部来源
- **红灯保护**:既有分析测试若变红,即说明唯一性假设被破坏 —— 这是要捕捉的信号
- 验:同三元组两源两行 → 视图只出 1 行(rank 小的胜)

### T4 · 年鉴采集编排与真实入库
- `config/yearbook_sources.yaml`:`region` / `卷 URL 模板` / `目标表标题模式`
- `ingest_yearbook(client, repo, cfg, years)`:逐年 TOC → 匹配表 → 解析 → 入库
  - `source_kind='yearbook'`、`source_rank=2`、`caliber='final'`、`method='yearbook'`
  - `raw_text` 记录「表标题 + 指标名 + 年份」溯源
- 验:真实采集 2016-2025,断言 泉州常住人口/CPI/就业 从缺到有,**年份数 ≥8**

## 4. 自检
- 规格覆盖:轨 A4 → T1/T2/T4;§5 数据模型 → T3;P2 禁硬编码 → T1 标题匹配
- 占位符:无
- 类型一致:`parse_year_columns -> list[dict]`、`match_tables -> dict[str,str]`、`load_toc -> list[tuple]`

## 5. 风险
| 风险 | 对策 |
|---|---|
| 宽表列对齐错位 → **静默错值** | 夹具回归 + 断言「三产之和 ≈ GDP」自洽校验(既有 C 策) |
| 多源破坏分析唯一性 | 主源视图 + 默认 `primary_only`;245 测试作防线 |
| 2025 卷形态变异 | 按标题匹配(与文件名无关) |
| 年鉴值单位与公报不一致(万元 vs 亿元) | 保留原单位入库,不换算;分析层做单位归一 |
