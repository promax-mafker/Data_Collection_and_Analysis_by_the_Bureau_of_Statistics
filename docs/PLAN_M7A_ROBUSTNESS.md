# M7a 实现计划:管线鲁棒性 P0 修复

> 依据:`docs/DESIGN_M7_ROBUSTNESS.md`(已批准,2026-09-08)
> 执行方式:**内联执行**(任务间 API/模式强耦合:迁移列名 → repository → 上层消费,逐任务 TDD,每 3 任务全量检查点)。测试命令:`.venv\Scripts\python -m pytest tests -q`(workdir `E:\Deepseek_harness\stats-collector`)。

## 任务顺序(串行,每任务先写失败测试)

### P1 基础:db.py 迁移与 PRAGMA
- 改 `app/store/db.py`:`connect()` 内 `PRAGMA journal_mode=WAL`(try/except 容忍只读/内存库)、`PRAGMA busy_timeout=30000`、`PRAGMA foreign_keys=ON`;`_migrate()` 追加(幂等,PRAGMA table_info 探测后 ALTER):data_values +caliber DEFAULT 'final' +source_url DEFAULT '';doc_insights +region DEFAULT '' +period DEFAULT '';回填 UPDATE 两条(见设计 §3)。
- 测试 `tests/test_db.py` 追加:`test_migrate_adds_caliber_source_url`、`test_migrate_adds_insight_region_period`、`test_backfill_budget_caliber`(插 budget 页+行 → init_db 后 caliber='budget')、`test_backfill_insight_region`(pages.bureau→bureaus.region 回填)、`test_wal_busy_timeout_pragmas`(PRAGMA 查询断言)。
- 红:先写测试(旧代码无列 → fail)→ 绿:改 db.py。

### P2 repository:字段透传/事务化/region/find_bureau
- 改 `app/store/repository.py`:
  - `insert_values`/`replace_page_values`:SQL 加 caliber、source_url 列(DataValue 新字段);replace_page_values:values 空且非 force → 不删旧返回 0;非空 → 单事务 DELETE+批量 INSERT,异常 rollback 后 raise。`replace_doc_insights`:items 空 → 不删返回 0;非空单事务。`replace_enterprises`/`replace_industry_data`/`replace_econ_series` 同样事务化 + 空不删(force=False)。
  - `list_doc_insights(..., region=None)` 参数与 SQL。
  - `find_bureau_by_region(region)` → id or None。
  - `query_data/query_lax/query_text/_query_in` 支持 `caliber=None` 过滤参数(传 None 不过滤)。
- 改 `app/schemas.py`:DataValue 加 `caliber: str = "final"`、`source_url: str = ""`。
- 测试 `tests/test_store.py` 追加:`test_replace_empty_keeps_old`(插入2行→空替换→行数不变)、`test_replace_empty_force`、`test_replace_rollback_on_error`(INSERT 超长/坏类型 → rollback 旧行在)、`test_replace_values_with_caliber`、`test_list_doc_insights_region_filter`、`test_find_bureau_by_region`(命中+未命中 None)、`test_query_data_caliber_filter`。
- 注意:repository 中由元组构造的 SQL 全部参数化(检查 INSERT 语句列数匹配)。

### P3 rule_extractor:normalize_value 与单值收敛
- 改 `app/extract/rule_extractor.py`:新增模块函数 `normalize_value(s)`(全角→半角:str.translate 表 ０-９/．/，/％;去 `[0-9]` 脚注形态已在 clean;去千分位逗号与数字内空格:先剥 `,` 当千分位——注意 "1,688" →1688 与 "12,3%" 不同,规则:数字上下文 `(?<=\d),(?=\d{3}(?:\D|$))` 才剥);`_run` 输出前 value=normalize_value;按 (page, indicator) 收敛:finditer 命中 >1 → `_pick_best(matches, rule)`:
  - 完全同值去重;
  - 主口径分:raw 含主词(总额|合计|全市|全年|完成|实现|外贸进出口总额)+2,含子口径词(其中|民营|国有|海关代征|对|占|累计|地方级)+0;
  - 占比/增速误配排除:raw 匹配 `占.{0,6}(?:总额|比重)|增长|下降` 且 unit 空且其 value 后紧跟 `%` → 排除;
  - 其余按 (主词分, raw 长度) 取最大;无法区分取首条。
  - 结果:返回收敛后的 values(每页每指标最多 1 条;排除的重复条目不产生 warning,保持函数签名不变)。
- 测试 `tests/test_rule_extractor.py` 追加:`test_normalize_fullwidth`、`test_normalize_thousands`、`test_same_value_dedup`(文本两处同句同值 →1)、`test_pick_total_over_subitem`(宁德公报样文 502.5 总/306.2 民营/133.2 国有 → 仅 502.5)、`test_exclude_share_mismatch`("占进出口总额37%"不产出)、`test_tax_pick_first`(814.34 与海关代征 121.87 并存 → 814.34)。

### P4 documents.py:caliber/类型白名单/bureau 解析
- 改 `app/fetch/documents.py`:
  - `_fetch`:嗅探规则——`.pdf` 后缀或前 4 字节 `%PDF` → PDF 路径;`.htm/.html` 或无扩展 → HTML;其余扩展 → `raise FetchError(f"不支持的文档类型: {ext}")`;扫描版 PDF(页数>1 且文本<100 字)→ 返回 ("", None) 特殊标记(通过 raise FetchError("扫描版/空PDF"))由上层进 skipped。
  - `run_documents`:入口 `bid = repo.find_bureau_by_region(region)`,None → `repo.upsert_bureau(Bureau(level="meta", name=f"{region}文档源", url="", region=region, verified=True))`;删除 `meta_bureau_id=1`;Page/DataValue meta 的 bureau_id 用 bid。
  - 抽取 meta 加 `caliber="budget" if src.get("category")=="budget" else "final"`;`extract_named` 后 replace_page_values 前把 values 的 caliber/source_url 补上(rule_ex.extract_named 用 meta 里的 caliber 构造 DataValue——实际在 extract_named/_run 里 DataValue(caliber=meta.get("caliber"), source_url=meta.get("url")))。
  - 统计:`stats["skipped"]` 增原因文本;加 `llm_errors` 计数:llm 段 try/except LLMError → llm_errors+=1;extract_insights 返回 [] 且 llm_client.enabled → llm_errors+=1(不再静默)。
- 测试 `tests/test_documents.py` 追加:`test_fetch_unsupported_ext_raises`(.doc URL)、`test_scan_pdf_skipped`(短文本假 PDF bytes)、`test_bureau_lookup_by_region`(存在→用其 id;不存在→建 meta bureau 并复用)、`test_values_get_caliber`(budget 源→budget)、`test_llm_errors_counted`(mock LLMClient.extract_insights 抛 LLMError)。

### P5 critique.py:subject 打通 + merge 修正
- 改 `app/extract/critique.py`:
  - SYSTEM_CRITIQUE 输出 schema 加 subject 字段(提示候选列表,见设计 T5);llm_critique 输出 dict 带 `"subject": it.get("subject","")`。
  - 新增 `_subj_key(s)` 归一:去尾部 增速|收入弹性|依赖度|弹性 等词。
  - merge_checks:匹配 = `_subj_key(k.subj)==_subj_key(c.subject)` 或互为子串(核心词长度≥2);另:critique 无 subject 但 confidence=="high" 且 check.verdict=="flag" → escalated 追加(标注 "single_layer": True)。
- 测试 `tests/test_critique.py` 追加:`test_llm_critique_shape_has_subject`(fake client 返回含 subject)、`test_merge_subject_synonym`("GDP增速"↔"地区生产总值"经 _subj_key 命中?——设计宽松:加显式同义映射 {"gdp":"地区生产总值","地区生产总值":"地区生产总值"…} 简化:映射表 GDP/地区生产总值 互认 + 预算收入互认)、`test_merge_high_conf_single_layer`、`test_system_critique_asks_subject`(SYSTEM_CRITIQUE 字符串含 "subject")。
- 注:_subj_key 与同义映射用模块级 `SUBJECT_SYNONYMS` dict({"gdp":"地区生产总值","gdp增速":"地区生产总值","地区生产总值":"地区生产总值","一般公共预算收入":"一般公共预算收入","预算收入":"一般公共预算收入","税收收入弹性":"税收收入",...})——映射键有限集,不透写模糊。

### P6 documents.py 批判接线 + region/period 落库
- 改 `app/fetch/documents.py`:
  - 每源 rule+llm/llm 页:llm 抽取后追加批判——`items = llm_ex.extract_insights(...)`(既有);随后若 llm_client.enabled:`crits = llm_critique(text, llm_client)`(from ..extract.critique import llm_critique);`crit_items=[{page_id, source_id, kind:"critique", title:page_title+"·批判审读", body:json.dumps(c, ensure_ascii=False), method:"llm", region:region, period:year}]`;`repo.replace_doc_insights(pid, items+crit_items)`(统一一次替换:items 与 crit_items 合并后替换——注意 replace 语义是整页删,现在合并写入保持整页一致性)。
  - 所有 items 带 region/period。
  - 统计 critiques 数。
  - llm 未启用:critiques 不产,llm_errors 不增,skipped 说明。
  - 注意:llm_critique 失败返回 [] → 不追加 crit_items,llm_errors+=1。
- 改 `app/store/repository.py` insert_doc_insights:SQL 加 region/period 列。
- 测试 `tests/test_documents.py` 追加:`test_critique_written`(fake enabled client:llm_extractor 返回 1 item + critique 2 条 → repo 该页 doc_insights 含 kind=critique 行)、`test_critique_failure_counts_error`(llm_critique 抛 → llm_errors)。

### P7 分析层:caliber + region 隔离
- 改 `app/analysis/quanzhou.py`:`values_rows = repo.query_data(region=region, caliber="final")`(57 行);`_value/_year_pair` 增 caliber 参数默认 "final" 传入 query_data;kind=industry/plan_goal/critique 的 list_doc_insights 加 region="泉州市";critique body 解析兼容无 subject。
- 改 `app/analysis/industry_gap.py`:52/145 行 list_doc_insights(kind="industry", region="泉州市")。
- 改 `app/analysis/core.py`:analyze 内 query_data 调用带 caliber="final"(如适用;core 分析全省比较——data_values 全省行为公报 → final;不改会污染吗?core 的 ref year 也吃 2026?泉州 2026 budget 行 region 泉州;core 全 region 比较含泉州 2026 GDP?没有 GDP2026。为一致性,core.analyze 的 query_data 同样 caliber="final")。
- 测试:`tests/test_quanzhou_analysis.py` 追加 `test_fiscal_ignores_budget_caliber`(seed final+budget 行,断言取值 final);`test_insights_region_isolation`(seed 漳州 kind=industry → 产业列表不含);`tests/test_industry_gap.py` 追加同类 region seed 断言。

### P8 main.py/quanzhou.py 状态暴露 + 旧测试适配
- `app/main.py`:/api/quanzhou/run stats 返回含 llm_errors/critiques;/api/quanzhou/status 加 "critiques": len(list_doc_insights(kind="critique", region="泉州市"))。
- `quanzhou.py` CLI:打印 critiques/llm_errors。
- 全量 pytest;修旧测试中受 caliber 默认影响者(预期:rule_checks 不再见 2026 budget 行;test_quanzhou_analysis 若有 seed 预算行断言变化 → 更新 seed 或断言,逐一定位)。
- 旧测试检查点:166 全绿。

### P9 scripts/cleanup_m7a.py + 真实数据清理
- 新增 `scripts/cleanup_m7a.py`:纯函数 `plan_cleanup(conn) -> {delete_ids:[...], update_ids:[...], backup_path}` + main(--apply);删除行 id 常量清单(设计 §T8);UPDATE 802/803/804 → caliber='budget'(并通用 UPDATE doc_category=budget 页);执行前 cp 备份 `data/stats.db.bak-20260908`;输出前后 COUNT 对照;幂等(--apply 后再跑:delete 无行可删→0;update 幂等)。
- 测试 `tests/test_cleanup_m7a.py`(构造内存库种子行,断言 plan/apply)。
- 真实执行:先跑 --dry(打印清单)→ 确认 → --apply → 验证 COUNT + 抽查行消失/口径正确。

### P10 全量验证与文档
- pytest 全量 0 fail;`.venv\Scripts\python -c "from app.store.db import init_db;..."` 对真实库跑 init_db 验证迁移成功;API 冒烟(服务重启后 /api/quanzhou/status、/api/data?text=泉州…税收收入2025 无 121.87);审查报告 §3 建议状态勾选更新;PROGRESS.md §M7 追加。
- 本地提交(按 chinese-conventions:type+中文描述,分 2-3 commit:数据层、采集与批判层、分析与清理)+ MCP 推送 GitHub。

## 自检
- 规格覆盖:设计 T1-T8 ↔ 计划 P1-P10 一一映射 ✓;测试先行每任务标注红→绿 ✓;无占位符(所有 id/列名/文件名已定)✓;行为变化点(P7 caliber 过滤)已列旧测试适配项 ✓。
