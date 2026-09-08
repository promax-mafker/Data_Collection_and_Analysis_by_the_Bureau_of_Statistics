# M7a 设计:管线鲁棒性 P0 修复(数据正确性止血)

> 依据:`docs/REVIEW_PIPELINE_ROBUSTNESS.md`(对抗性审查,2026-09-08)
> 批次:M7a = 报告 §3 P0 建议 1-7 + 既有脏数据清理。P1/P2(建议 8-17)留 M7b/M7c,不在本设计内。
> 状态:**设计待用户批准**(批准前不写代码)

---

## 1. 目标与不做的事

**目标**:消除审查中 A/B 级"静默产生错数据 / 整块丢失"的根因——重复行、口径混装、空结果抹库、非事务替换、批判层死代码、洞察无 region、归属硬编码、二进制静默吞错。

**明确不做(YAGNI)**:indicators 主数据表启用、UI 重做、前端转义(app.js 属 P2)、HttpClient/decode/基线告警(P1)、evidence 校验/LLM 客户端(P2)。本批只动 P0 红线。

---

## 2. 任务拆分与行为变更

### T1 抽取单值化 + 数字清洗收口
**文件**:`app/extract/rule_extractor.py`(新增 `normalize_value`;`_run` 输出收敛)、`app/parse/series_table.py`/`industry_documents.py` 数字清洗复用(仅 T1 提供函数,替换调用点放 M7b)
- 新增 `normalize_value(s)`:全角→半角、去千分位逗号/空格、剥脚注 `[n]`/零宽字符;供 `_run` 落库前清洗 value(unit 不动)。
- `_run` 每指标(每页)收敛策略:命中多行时按优先级保留一条——
  1. raw_text 含主口径词(`总额|合计|全市|全年|完成|实现`)且 value 最长单位完整者;
  2. 同一 value 完全重复 → 只留一条;
  3. 无法判主次(如"税收收入 814.34 vs 121.87"子口径并存且都无主词)——**保留首条并 append 到返回值外的 `warnings`**(页面级,入库不丢,留给 caliber 解决);
  4. 上下文是"占比/增速"形态(`占.*总额|增长|下降|%` 紧跟 value 后无单位且前词非指标)不入选。
- **行为红线**:宁缺毋滥——主口径判定不清时保留第一条(现状行为),不静默丢光。

### T2 口径维度:caliber/source_url 列 + 预算口径标注
**文件**:`app/store/db.py`(迁移)、`app/store/repository.py`(insert_values/replace_page_values/query 透传)、`app/schemas.py`(DataValue+caliber/source_url)、`app/fetch/documents.py`(传 caliber)、`app/orchestrator.py`(传 caliber)、`app/analysis/quanzhou.py`(`_value/_year_pair/values_rows` 默认只吃 final 口径)、`app/analysis/report.py`(渲染口径标注)
- 迁移:`data_values` 加列 `caliber TEXT NOT NULL DEFAULT 'final'`、`source_url TEXT NOT NULL DEFAULT ''`(旧行默认 final 合理:历史行全部来自统计公报/政府报告;再按 doc_category='budget' 的页把对应行 UPDATE 成 'budget',见 T8)。
- 语义:`final`=年度决算/公报口径(分析默认)、`budget`=预算报告/执行报告口径(半年累计、预算草案)、`flash`=快报(预留)。
- 填充:documents.py 抽取 meta 带 `caliber`('budget' if 源 category=='budget' else 'final')→ DataValue;主管线 orchestror 一律 'final';source_url=页面 url。
- 读取:repository.query_data/query_text/query_lax 增可选 `caliber` 参数;`query_text` 结果行内含 caliber 字段(前端可显示)。
- 分析隔离:quanzhou.py `_value/_year_pair` 与 `values_by_indicator` 组装处加 `caliber='final'` 过滤(**旧行为变化**:rule_checks 不再吃到 2026 预算行;2026H1 与 2025 的 -49% 假增速消失)。直接查询(web)默认不过滤,但行带 caliber 列。

### T3 替换事务化 + 空结果不删
**文件**:`app/store/repository.py`(replace_page_values/replace_doc_insights/replace_enterprises/replace_industry_data/replace_econ_series)、`app/store/db.py`(connect PRAGMA)
- `connect()`:`PRAGMA journal_mode=WAL`、`busy_timeout=30000`、`foreign_keys=ON`。
- 每个 replace_*:空 rows → **不 DELETE**,记 `skipped_empty`(返回 0);非空 → 单事务 `DELETE+INSERT`,`except: rollback; raise`。
- 参数 `force=False`:显式传 force=True 才允许空清空(备用,当前无调用方)。
- `replace_doc_insights` 失败/空时同样不清空(并允许调用方区分:返回 (n, emptied) 或 items 全 None 时跳过)。

### T4 类型白名单 + 扫描 PDF 检测 + bureau 归属解析
**文件**:`app/fetch/documents.py`(`_fetch`、`run_documents`)、`app/fetch/pdf.py`、`app/orchestrator.py`(URL 扩展名判定)、`app/schemas.py`(无)、`app/store/repository.py`(find_bureau_by_region)
- `_fetch`:按 `url 扩展名 + 内容嗅探`:`.pdf` 或 `%PDF` → PDF;`.htm(l)` 或无扩展 → HTML;其余扩展名(`.doc/.docx/.xls/.xlsx/.zip/…`)→ raise FetchError(计入 errors,message 明确"不支持类型")。内容 `%PDF` 但 url 扩展名不符 → 按 PDF。
- 扫描版 PDF:`extract_pdf_text` 总字数 <100(可配)且页数>1 → 返回空 + 标记;run_documents 把该源记入 `skipped`(原因=scan_pdf)。
- `run_documents` bureau 解析:新增 `repo.find_bureau_by_region(region)`(SELECT id FROM bureaus WHERE region=?);命中用其 id,未命中 → upsert 一个 `level='meta', name=f'{region}文档源', region=region, verified=1` 的机构并回填;删除 `meta_bureau_id = 1` 硬编码。

### T5 接通 LLM 批判双层(A6)
**文件**:`app/extract/critique.py`(SYSTEM_CRITIQUE + llm_critique + merge_checks)、`app/fetch/documents.py`(追加批判落库)、`app/store/repository.py`(insert_doc_insights 已支持 kind)、`app/analysis/quanzhou.py`(读 critique 的 subject 字段;删死 import)、`app/analysis/report.py`(escalated 渲染已有)、`app/main.py`(status 加 critique 计数)
- SYSTEM_CRITIQUE:输出 schema 增加 `"subject": "批判针对的指标/主题(尽量用:地区生产总值/一般公共预算收入/政府性基金收入/城镇新增就业/进出口总额/常住人口/居民人均可支配收入/三次产业/土地财政/目标增速 之一)"`。
- `llm_critique` 规范化输出带 subject;失败仍返回 [] 但**由调用方计错误**。
- `run_documents`:每源(llm/rule+llm 页)正文抽取后,若 LLM 启用 → 追加一次 `llm_critique(text, llm_client)`,以 `kind='critique'` + 该页 page_id/source_id 与 region 落库(replace 语义同该页:整页 kind='critique' 先删后插)。统计 `stats['critiques']`。
- `merge_checks`:subject 匹配改为——critique.subject 与 check.subject 完全相等或互为包含(核心词:去掉"增速/收入弹性/依赖度"等后缀后相等);无 subject 的 critique 若 confidence=high → 单层进 `escalated`(标注 single_layer)。
- quanzhou.py 读取 critique body 时兼容旧形状(无 subject → '' )。
- **行为变化**:报告中"可信度审读"critiques/escalated 从恒空变为有内容(依赖 LLM 在线)。

### T6 doc_insights 加 region/period 并全链路过滤(A7)
**文件**:`app/store/db.py`、`app/store/repository.py`(insert/replace/list 参数)、`app/fetch/documents.py`(写入)、`app/analysis/quanzhou.py`(96/141/163 行过滤)、`app/analysis/industry_gap.py`(52/145 过滤)
- 迁移:`doc_insights` 加 `region TEXT NOT NULL DEFAULT ''`、`period TEXT NOT NULL DEFAULT ''`;存量行按 page_id → pages 回填(bureau 对应 region 或 pages 无 → 留空并告警)。
- 写入:documents.py replace_doc_insights 前把 region/period 放进 items。
- 过滤:list_doc_insights 加 `region=None` 参数;quanzhou.py/industry_gap.py 三处(实为五处)调用加 `region="泉州市"`。
- 测试:新增跨 region 回归测试(插入非泉州 kind=industry 洞察,断言 analyze_quanzhou/industry_gap 不受影响)。

### T7 LLM 失败/禁用不再静默:llm_errors 与 0 洞察降级
**文件**:`app/fetch/documents.py`(统计)、`app/main.py`(status/run 返回)、`quanzhou.py`(CLI 打印)
- run_documents 统计加 `llm_errors`(每源 extract_insights 抛 LLMError 或返回 [] 且 LLM 启用 → +1);llm 未启用 → `llm_enabled: false` 提示(现状已静默,加 skipped 原因)。
- replace_doc_insights 空集不删(T3 已覆盖)——该页旧洞察保留。
- `/api/quanzhou/run` 返回 stats 含 llm_errors;/api/quanzhou/status 加 critiques 计数与 llm_enabled。

### T8 既有脏数据一次性清理(带备份,脚本入库)
**文件**:新增 `scripts/cleanup_m7a.py`(幂等,可重跑;每类操作打印将删行清单,`--apply` 才执行)
清理清单(已逐行取证,2026-09-08):
| 库行 id | 处理 | 依据 |
|---|---|---|
| 530/531/532/533/534(宁德进出口2020) | 删 | 民营 306.2/国有 133.2/RCEP 185.9/五年累计 1844.02 均为子口径或跨期;533 value=37 实为"占进出口总额37%"占比误配(raw_text='进出口总额\n37') |
| 529(宁德进出口2020) | 留 | 全年总额 502.5 主口径 |
| 333/334/379(三明常住人口2021) | 删 | 换行截断残片 value=2/2/12(raw_text='常住人口\n2\n') |
| 380(三明常住人口2021) | 留 | 普查口径 2486450 |
| 828 或 829(泉州进出口2025) | 删一条 | 同页同值 2363.79 完全重复 |
| 832(泉州税收2025) | 删 | 121.87 实为"海关代征税收"(上下文取证),非"税收收入"主口径;814.34 保留 |
| 802/803/804(泉州 2026) | **不删**,UPDATE caliber='budget' | 2026 预算执行口径,来自 page 132(doc_category='budget');分析层默认 final 即自动隔离 |

- 同时按 `pages.doc_category='budget'` 的页把所有关联 data_values UPDATE caliber='budget'(通用化,覆盖未来)。
- 执行前 `cp data/stats.db data/stats.db.bak-20260908`;脚本输出前后行数对照。
- 测试:脚本核心逻辑(选取准则)抽成纯函数进 tests。

---

## 3. DB 迁移总清单(db.py `_migrate` 幂等追加)

```sql
ALTER TABLE data_values ADD COLUMN caliber TEXT NOT NULL DEFAULT 'final';
ALTER TABLE data_values ADD COLUMN source_url TEXT NOT NULL DEFAULT '';
ALTER TABLE doc_insights ADD COLUMN region TEXT NOT NULL DEFAULT '';
ALTER TABLE doc_insights ADD COLUMN period TEXT NOT NULL DEFAULT '';
-- 回填 doc_insights.region(按 page → bureau.region):
UPDATE doc_insights SET region=(SELECT b.region FROM pages p JOIN bureaus b ON b.id=p.bureau_id WHERE p.id=doc_insights.page_id)
WHERE region='' AND page_id IN (SELECT id FROM pages);
-- 预算口径回填:
UPDATE data_values SET caliber='budget'
WHERE page_id IN (SELECT id FROM pages WHERE doc_category='budget');
```
- connect() 增加 `PRAGMA journal_mode=WAL; busy_timeout=30000; foreign_keys=ON`。

---

## 4. 测试策略(TDD,先红后绿)
- **T1**:`test_rule_extractor.py` 新增——同页重复同值收敛 1 条;"海关代征税收收入121.87亿元"不入选税收收入主口径(或入选但进 warnings);全角/千分位清洗;宁德 2020 公报文本 fixture 复现 → 进出口总额仅 1 行。
- **T2**:`test_db.py` 迁移加列断言;`test_store.py` insert/replace 带 caliber;`test_quanzhou_analysis.py` 含 budget 行时 ref_year 与 fiscal 取值不受污染;`test_query_lax.py` caliber 参数。
- **T3**:`test_store.py` replace_* 空集不删旧行(先插后空替换断言行数不变);异常回滚(插入坏行 → rollback 断言旧行仍在);`test_db.py` PRAGMA 生效断言(WAL/busy_timeout 读取)。
- **T4**:`test_documents.py` .doc 扩展名 raise、扫描 PDF 文本<100 进 skipped;`test_store.py` find_bureau_by_region 命中/自建 meta。
- **T5**:`test_critique.py` SYSTEM_CRITIQUE 含 subject、llm_critique 形状带 subject、merge_checks 核心词匹配与 confidence=high 单层升级;`test_documents.py` 批判落库 kind='critique' 与 stats['critiques'](mock LLMClient)。
- **T6**:`test_db.py` 迁移列;`test_documents.py` 落库带 region;`test_quanzhou_analysis.py` 跨 region 洞察不串染(新回归);`test_industry_gap.py` 同上。
- **T7**:`test_documents.py` llm 返回 [] 时 llm_errors+1 且旧洞察未清。
- **T8**:脚本纯函数单测 + 空库幂等。
- 全量回归:166 旧测试必须全绿(behavior 变化点已列明)。

## 5. 风险与回滚
- 行为变化面:analysis 默认只吃 final → 若某指标只有 budget 行会变缺失(现库仅泉州 2026 三指标属此,GDP 等不受影响;报告将显示缺失而非错值——符合"错>缺"原则)。
- 迁移影响:旧库 742+383+945 行数据加列无损;doc_insights 20 行回填 region(全部来自泉州 run,应全为泉州市;脚本打印未回填行告警)。
- 回滚:git revert + 备份库恢复。
- 执行方式:严格档——设计批准 → PLAN → 子代理逐任务执行(TDD)+ 分级审查 → 全量验证 → 提交。

## 6. 交付物
代码变更(T1-T7)+ `scripts/cleanup_m7a.py` + 本设计/计划文档 + PROGRESS 更新;按惯例本地提交后 MCP 推送 GitHub。
