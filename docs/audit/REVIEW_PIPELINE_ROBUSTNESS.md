# Pipeline 对抗性审查报告(采集—传输—处理—存储)

> 审查日期:2026-09-08
> 审查对象:`stats-collector`(统计局数据采集 → 抽取 → SQLite → 分析 → Kami 报告)
> 方法:第一性原理拆解数据生命周期 + 真实数据库实测 + 代码逐层对抗(含两个并行专项审查:采集解析层、LLM/分析层)
> **修复状态:M7a(P0 建议 1-7 + 数据清理)已于 2026-09-08 交付,详见 `docs/planning/DESIGN_M7_ROBUSTNESS.md`/`docs/planning/PLAN_M7A_ROBUSTNESS.md`/PROGRESS §4.7;P1/P2(建议 8-17)排入 M7b/M7c。**

---

## 0. 审查框架:第一性原理

数据管线的唯一使命:**把外部世界(统计局网页/PDF)中的事实,忠实、可验证、可重复地搬运进可查询的库,并支撑不误导的分析**。围绕它拆出四层,每层问一个核心问题:

| 环节 | 核心问题(第一性) | 失效模式谱系 |
|---|---|---|
| 采集 | 源的"结构承诺"是否随时可违约? | 站点改版、URL 漂移、格式换容器(.doc/.xls)、反爬、扫描版、链接失效 |
| 传输 | 字节是否完整、真实、按预期到达? | 代理污染、TLS 降级、超时截断、4xx/429 无差别重试、无大小上限 |
| 处理 | 数字的意义(值/单位/口径/年度/地域)是否保真? | 换行截断数字、模式过宽误配、口径混装、LLM 幻觉/截断、区域串味 |
| 存储 | 已入库的"事实"是否持久、一致、可溯源? | 非事务替换、URL 漂移绕过版本清理、无外键、并发锁、id 硬编码 |

对抗性立场:审查中**假设每一次爬取都可能遇到新格式、上游每天都在改版、写库随时会被打断、查询者永远会问出模糊问题**——然后寻找代码在哪一步会**静默地**产生错误数据(错>缺:缺值可见,错值会直接污染结论)。

---

## 1. 实测数据库体检(stats.db,只读)

| 项目 | 结果 |
|---|---|
| 行数 | bureaus=11 / pages=110 / data_values=742 / doc_insights=20 / enterprises=170 / industry_data=945 / econ_series=383 / enterprise_industry=170 / runs=3(全 success) |
| 悬空引用 | data_values/doc_insights 的 page_id、bureau_id 全部有效(0 悬空);enterprise_industry 0 悬空 |
| **`indicators` 表** | **0 行**(schema 建了从未使用,指标主数据形同虚设) |
| **同 (region,指标,年) 重复** | **宁德 进出口总额 2020 = 6 行(同一页);三明 常住人口 2021 = 4 行;泉州 进出口总额 2025 = 2 行完全相同的 2363.79** |
| **规则误抽(实锤)** | 三明常住人口 value=`2`、`2`、`12`(raw_text=`常住人口\n2\n`——表格转文本换行把 2486450 截断);泉州 税收收入 2025 两行 814.34 / 121.87(两口径混装同名) |
| **口径年份混装** | 泉州 data_values 含 `2026 年` 预算数(一般公共预算收入 355.92、税收 204.02、基金 112.33)——2026 预算草案与 2025 决算同指标共存,表无口径列,查询直接命中预算数而无标注 |
| **垃圾页** | 4 个 `.doc` 附件被当 HTML 文本入库(content 仅 6 字符);run 3 仍报 `success`,无人提示"南平/三明部分年度公报实际缺失" |
| **归属错位** | `app/fetch/documents.py:125` 硬编码 `meta_bureau_id = 1`(注释自称"泉州统计局 id")——实测 `bureaus.id=1` 是**国家统计局**;M5/M6 全部页面、data_values 的 bureau_id 指向国家局(区域隔离靠 `region='泉州市'` 文本字段兜住,但溯源语义错误) |

---

## 2. 对抗性发现(按严重度)

### 🔴 A 级:会静默产生"错数据"

#### A1. 抽取器是"枚举式",无"每页每指标单值"契约
- `app/extract/rule_extractor.py:72` `for m in re.finditer(pattern, text)` → **每个命中都产出一行** DataValue。
- 后果:同一公报摘要段与正文段重复数字 → 同页同指标多行(泉州进出口 2025 两行同值 2363.79 即为铁证);公报中"其中/对某贸易伙伴"子句被过宽模式吞入 → 宁德 2020"进出口总额"6 行中混着 502.5/306.2/133.2/185.9/37/1844.02 等**不同口径子项**。
- 下游 `analysis/quanzhou.py:26-28` `_value()` 对同 (region,指标,年) 多行**静默取第一行** → 结论值由插入顺序(id)决定,运气驱动。
- 根因链:模式过宽(`config/extract_rules.yaml:45` `(?:进出口总额|进出口)`)+ 无单值约束 + 无"优先取总额/最近锚点"策略 + 入库无行级去重。

#### A2. 数值表转文本的换行截断
- 实测三明 `常住人口\n2\n`(真实值 2486450)→ 规则 `\s*` 后接数字只吃到断行残片。
- `app/fetch/parser.py:21-26` `extract_text` 只把标签转 `\n` 并压缩空行,**没有做"行尾数字与下行单位/续数"的重排**;公报正文经常有表格/多栏排版(每栏一列数字),转文本后数字必然被截断或错列。
- 同类风险:PDF 提取(`pdf.py` 的逐页 extract_text)列断行比 HTML 更严重,而 M6 年鉴正是 PDF/HTML 表格,靠专用解析器逐个救火(series_table),一旦新表型出现即回到 A1/A2。

#### A3. 无"口径/版本/来源类型"维度,年份口径混装
- `data_values` 表无 source、无 doc_category、无"执行数/预算数/快报/年鉴终值/修订值"口径列;`value` 为 TEXT、`unit` 自由文本。
- 实测:泉州 2026 预算草案数(收入 355.92 等)与 2025 决算同指标并存;画像分析靠 `ref_year=GDP 最新年`(`analysis/quanzhou.py:60-64`)**凑巧**过滤掉 2026 行——但 `/api/data?text=泉州一般公共预算收入 2026` 之类直接查询会拿到预算数且界面无任何口径提示。
- `rule_extractor` 对预算文本(`extract_rules.yaml` 财政规则)与决算文本无区分;快报/年鉴修订差异也无"后发覆盖前发"或"多值并列带来源"机制。

#### A4. 二进制文档类型无白名单,静默吞错
- `app/fetch/documents.py:40` 仅按 `%PDF` 魔数分流;`.doc/.xls/.docx` 附件直接走 HTML 解码 → 乱码"文本"入库或近乎为空;`orchestrator.py:159-172` 同样只认 `.pdf` 后缀 + 文本。
- 实测 4 个 .doc 公报页 content=6 字符,但 run 记为 success、无 skipped 统计(主管线),等于**南平 2017/2018、三明 2017/2019 公报缺失被静默吞掉**。
- 扫描版 PDF:`extract_pdf_text` 返回近空 → 只有完全空才会 skip,若有页眉噪声即当正文喂规则/LLM。

#### A5. 分析层对"多行/空/脏值"无防御
- `analysis/quanzhou.py` 的 `_value`/`_year_pair` 与多处 `float(v)` 直接信任库值;若多行含非数字字符(单位混入、断行残片)即 ValueError 崩溃整份报告(500);空序列时 ref_year=None 后多数指标静默缺失,报告仍输出(无"数据缺口清单")。

#### A6. "规则 + LLM 双层批判审读"在生产链路是**死代码**(审查最大发现)
- `llm_critique()`(`critique.py:153`)全仓**无任何生产调用方**:`analysis/quanzhou.py:154` 只是 import(从未调用),生产无任何代码写入 `kind='critique'` 的 doc_insights(LLM 抽取只产出 industry/plan_goal/fiscal_signal/employment,`llm_extractor.py:22-41`)。
- 而 `analyze_quanzhou` 从 `list_doc_insights(kind="critique")` 读批判(`quanzhou.py:163`)→ **读路径恒为空**,报告"数据可信度审读"章 critiques/escalated 恒空——宣称的"LLM 批判 + 双层命中升级"实际只有规则单层在跑。
- 升级逻辑即使接线成功也**结构性永不触发**:`merge_checks`(`critique.py:187-193`)要求批判条目带非空 `subject` 且被子串命中,而 `llm_critique` 输出形状(`critique.py:169-177`)/SYSTEM_CRITIQUE schema 均**无 subject 字段**;`test_critique.py:122-134` 手工补 `subject:"GDP"` 才测出升级——测试捏造了生产永不出现的字段形状。
- 附带:`severity` 升级语句恒为 high(`critique.py:191` 逻辑冗余)。

#### A7. doc_insights 无 region 列——"区域串染"的结构性复发口
- `doc_insights` schema 无 region(`db.py:55-64`);`documents.py:145-146` 的 page_meta 携带 region 但落库时被丢弃(`llm_extractor.py:216-222` 只写 page_id/source_id/kind/title/body/method)。
- `analyze_quanzhou` 对 kind=industry/plan_goal 的 `list_doc_insights()` **不做任何地域/来源过滤**(`quanzhou.py:96,141`);`industry_gap._plan_industries/_evidence` 同理;`repository.list_doc_insights` 也无 region 参数。
- 当前靠"只有泉州 run 产生 doc_insights"侥幸隔离;任何其它地区/省级文档走 LLM → 泉州画像自动串染。**数据值层的 region 隔离修复(历史 GDP 60199 事故)没有覆盖洞察通道**。

#### A8. LLM 输出的 evidence/claim 零落地校验(幻觉引用可直达报告)
- SYSTEM_EXTRACT 仅以 prompt 要求"evidence 从原文摘录、一字不改、禁止编造",**无代码校验**:evidence ∈ 原文段、数值与 evidence 数字对账、critique claim 是否在截断边界(8000 字)之内——全部缺失;confidence 为模型自报无校准;批判条目不携带 page_id/文本片段 → 不可溯源。

#### A9. 采集缺口会被渲染成负面经济结论
- `industry_gap.py:116-118`:overpromised 判定在"share is None 且无增速"即判"规划强/实际弱"——若五经普/年鉴采集失败或该培育产业本无历史数据 → **数据缺失被渲染成 🔴 规划过度承诺**,且报告无数据完备性警示;share 把 industry_data **所有年份**的企业单位数相加(`industry_gap.py:90-100`,8-8 表 2016-2024 逐年 + 五经普 2023 混加)→ 早期缺失年份的产业系统性低估;`silent_pillar` 三条件 OR 含 `ent_cnt>=3`(`industry_gap.py:132-134`)过触发。
- 教训:分析层必须区分"数据不存在"与"数值为零/很小",缺数据走"口径局限"通道而非结论通道。

#### A10. 时序取数错位:贸易取到最早年份、债务/GDP 跨年相除
- `trade.py:18-24` 取**第一行**含出口/进口的 econ_series,而 `list_econ_series` 按 (year,id) 升序 → 命中**最早年份**(如 1984)却被 economy_report 标注为 "2024";`investment.py:14-29` 用债务最新年(2024 底)÷ GDP 最新年(2025 全年),跨年相除;`consumption.py:14-20` 硬编码 year="2025"、收入序列被写成 year="2024"(`industry_documents.py:95`)与 GDP 2025 混比——M6 报告多处口径年份错位且标签全是写死字符串,与数据实际年份解耦。

### 🟠 B 级:一致性/持久性风险(数据可能整块丢失)

#### B1. 所有"整批替换"都是无事务 DELETE+INSERT,且**空结果也照删**
- `repository.py`:`replace_page_values:155`、`replace_doc_insights:339`、`replace_enterprises:358`、`replace_industry_data:385`、`replace_econ_series:414` — 全部先 `DELETE`(立即 commit)再逐条 `INSERT`(最后一次 commit)。
- 任一环节崩溃/断电/约束异常 → **该页/该源旧数据已删、新数据未全落,静默变空**,且 runs 表 summary 不反映(page 计数已 +1,values 计数取决于 insert 完成度)。
- **更隐蔽的触发:rows 为空也照删不误**——采集到空文本/解析零命中(结构漂移、验证码页、临时改版)→ `values=[]` → DELETE 全页旧值、插 0 行、零异常、run 仍 success(200 降级页:验证码/JS 壳/乱码页文本非空即 upsert+replace,配合此路径=静默抹库)。**"成功但空"与"失败"必须区分对待**。
- 应:单事务包裹 DELETE+批量 INSERT;必要时"影子表 + rename"原子替换;空结果默认**不 DELETE**(或先记录旧值再告警)。

#### B2. SQLite 未启用 WAL / busy_timeout / 外键
- `db.py:103-106 connect()` 无 `PRAGMA journal_mode=WAL`、无 `busy_timeout`、无 `foreign_keys=ON`。
- 并发:Web(`main.py` 每请求新连接)与 CLI 采集同时写 → `database is locked` 直接 500;采集多进程无互斥(`/api/run` 可被连点并发执行整条管线)。
- 无外键 + B1 的 DELETE/INSERT → `enterprise_industry.enterprise_id` 引用 `enterprises.id`(AUTOINCREMENT):`replace_enterprises` 每次重建 id,**重跑一次 M5 企业源,170 条行业归类全部悬空**(当前 0 悬空只是因为顺序碰巧一致,属未爆炸的定时炸弹)。

#### B3. URL 漂移绕过"防版本累积"设计
- `upsert_page`(`repository.py:114`)按 `url` 判重;同一公报换 http/https、加尾斜杠、或转载到新路径 → 新 page_id → 旧页 data_values 永不清理 → 跨 run 版本累积(与 A1 叠加,重复行只增不减)。
- 内容哈希去重(`orchestrator.py:175-178`)只防"同内容重复入库",不防"同内容不同 URL"(会误跳新 URL 的页面更新)也不防 URL 漂移后的旧页残留。

#### B4. 归属硬编码
- `documents.py:125-126` `meta_bureau_id = 1` + 误导性注释;实测 id=1 是国家统计局(见 §1)。一旦 run 顺序/库重建改变 id 分配即错位;即使现在,页面/数值的 bureau 溯源列也是错的(仅靠 region 文本列保持分析正确)。

#### B5. LLM 失败静默 + 整页 replace → "旧好数据被新空结果覆盖"
- `llm_extractor._call_and_emit` 任何 LLMError 只 print 后返回 None(`llm_extractor.py:209-215`);`extract_insights` 过滤 None(188)。而 `run_documents` 无论成败都调 `replace_doc_insights`(先 DELETE 整页再插新)。
- 反例:上次已抽出 3 章产业洞察;本次端点 404/欠费/某块 JSON 失败 → 该页洞察**整体清零**,run_documents 只对 fetch 异常计数 errors(`documents.py:168-170`)→ run 仍报 success,**零洞察静默成功**。temperature=0.2 非 0 + 无幂等键 → 重跑内容漂移;超时重试若服务端已处理则有双重计费风险。

#### B6. 子年度数据与年度公报同表混放(仅靠 year 区分)
- 半年执行报告(period="2026")以 year="2026" 与公报全年 2025 同表入库,DB 无 period/频度标记 → 跨年增速可算出 -49% 假结论;`quanzhou.py:60-62` 的 ref_year=GDP 最新年技巧只挡住一半(直接查询/其它模块仍暴露)。规则校验 C2/C5/C7 的跨年 pair 同样可能吃到同年重复值(公报摘要 vs 正文、公报 vs 执行报告同引 2025 GDP)→ 编造"突变"假阳。

### 🟡 C 级:传输与采集层的鲁棒性缺口

#### C1. 传输与代理的不对称
- `llm_client.py:50` 显式 `proxies=None` 直连(历史教训:系统代理 7890 使大请求超时);但 **HttpClient 的采集请求与 robots.txt 拉取均未豁免代理**(`client.py:29,45`),是否踩雷完全取决于运行 shell 的环境变量——同样的坑在采集侧仍未封死。
- `verify=False`(`client.py:18` 全局开关,`quanzhou.py:25` 仅 M6 用)无主机白名单:未来若复用同一 client 抓其它站点,TLS 校验被整体关闭(数据可被中间人改写,且毫无痕迹)。

#### C2. 重试/限速/大小控制粗糙
- `client.py:41-53`:4xx(404/403)也重试 2 次并退避;429 不读 `Retry-After`;无 UA/Referer 多样性(反爬敏感站易被 ban);无响应大小上限(某 200MB PDF 直接进内存);无流式+校验和。
- robots.txt 读取 `client.py:29` 不带 `verify`/代理策略且 fail-open(自签名站必然 fail-open,等于没查)。

#### C3. 解码"假成功"
- `parser.py:28-35 decode_html`:UTF-8 失败后 gb18030 几乎**总能解码成功** → 若真实编码是 Big5/latin1 或内容为压缩/二进制,得到乱码但不报错,后续抽取静默产出垃圾;HTTP header / meta charset 未参与;无乱码检测(常见字频/替换符比例)。

#### C4. 采集管线无基线对照,退化不可见
- runs.summary 只有 bureaus/pages/values/errors 总数(`orchestrator.py:195-198`),无"每机构/每源"明细基线;**没有"本次比上次少 300 个值"的自动告警**,改版漏采只能靠人肉对比日志(2024 年泉州 GDP 漏采事故即属此类,事后才发现)。
- `_final_status` 只要 errors==0 即 success——垃圾页、空内容页、扫描版、.doc 都不计 error。

#### C5. 发现层启发式脆弱(静默漏检)
- `resolver.py:56` 只收**根路径**链接(深层入口漏发现);`verify_bureau` 只看 title 含"统计";`orchestrator.py:38 ARTICLE_RE` 硬编码政府 CMS 文章 URL 形态,栏目改版即失效;公报关键词启发式漏检只写 log 不升级告警。

#### C6. 长同步 API 无互斥/无任务化
- `/api/run`、`/api/quanzhou/run`(`main.py:37,114`)同步跑整条管线(分钟级)+ LLM;HTTP 层超时后**后台仍在写库**,用户重复点击 → 多管线并发写同一 SQLite。

---

## 3. 提高鲁棒性的建议(按投入产出排序)

### P0 — 止血(数据正确性底线,建议下一迭代就做)
1. **抽取单值化 + 入库去重**:`extract_named`/`_run` 后按 (indicator) 只保留最强命中(如"总额"优先、或首个匹配上下文最完整者),并加行级 UNIQUE(region, indicator_name, year, page_id) 或插入前去重;宁德/泉州现存重复行写一次性清理脚本 + 回归测试防再犯。
2. **口径列与口径规则**:`data_values` 加 `caliber TEXT`(执行数/预算数/快报/终值/修订)与 `source_url`;规则层对"预算"类文档显式打标,查询与分析默认排除预算口径或强制标注;`indicators` 主数据表启用,指标名统一走字典。
3. **替换事务化**:所有 `replace_*` 改为单事务(DELETE+INSERT 同 commit);SQLite `connect()` 开启 `WAL + busy_timeout=30s + foreign_keys=ON`;删除/替换前记录行数,替换后行数骤变为 0 时告警。
4. **类型白名单**:非 `.pdf/.html/.htm` 扩展名 → 明确报错进 skipped/errors 而非按 HTML 解析;加扫描版 PDF 空文本检测与 skip 记录;`bureau_id` 硬编码改为按 region 查 bureau 或建 meta_bureau 行。
5. **接通批判双层(A6)**:run_documents 每源 LLM 段后追加 `llm_critique` 并以 `kind="critique"` 落库(带 page_id/source_id);`llm_critique` 输出补 subject 字段(或 merge_checks 退化为"confidence=high 单层进核查区");去掉 `quanzhou.py:154` 死 import;在 `/api/quanzhou/status` 暴露"批判层启用/条数"。
6. **洞察通道 region 隔离(A7)**:`doc_insights` 迁移加 `region/period` 列;documents.py 落库写入;`analyze_quanzhou`/`industry_gap` 所有 `list_doc_insights` 调用加 region 过滤;补跨 region 回归测试。
7. **replace 失败不清空(B5)**:`replace_doc_insights` 在 items 为空/全 None 时返回 0 且**不 DELETE**;LLM 失败计入 run summary,0 洞察时 status 降级 partial;`/api/quanzhou/run` 返回 llm_errors 计数。

### P1 — 结构加固(一致性/可观测)
8. **每次 run 落"采集清单基线"**:记录每 (机构,源,年) 的 pages/values/insights 计数到 runs 明细,与上次对比,降幅>阈值即标 partial+警告(把 C4 的"漏采不可见"变成显式信号)。
9. **版本化口径管理**:同 URL 内容变更(upsert_page 命中时)先记录旧 content_hash 与变更时间,支持"该指标何时被刷新过";URL 归一化(去协议/尾斜杠/排序 query)后判重,根治 B3。
10. **enterprise 相关表加 FK 与级联**,或 `replace_enterprises` 改为按 (page_id) upsert 保 id 稳定;`replace_doc_insights` 同理。
11. **HttpClient 加固**:显式 `proxies=None`(与 LLM 对齐);4xx 不重试、429 尊重 Retry-After;`verify` 改 per-host(默认 True,仅白名单域可 False);响应大小上限;robots 请求复用同策略。
12. **decode_html 升级**:优先 header/meta charset;GB18030 兜底前加乱码启发(如 `\ufffd` 比例、常见字命中率);对可疑文本打 `mojibake` 标记不静默入库。

### P2 — 纵深(分析可信度/长期演进)
13. **LLM 抽取也走单值+证据校验**:insights 必须带原文引用区间,入库前校验"数字确实出现在 raw_text"(防幻觉数字);对"无任何原文支撑"的批判 evidence 降权或丢弃。
14. **查询层口径披露**:`/api/data` 结果含 caliber/source/提取时间字段;前端对预算口径、重复值、旧数据(>N 年未刷新)显式打标;报告缺数据时输出"缺口清单"而非静默;报告口径年份由数据实际年份生成,删除写死字符串(A10)。
15. **采集与 Web 分离的写入通道**:采集走独立进程 + 单一 writer 连接;`/api/run` 改后台任务 + 轮询状态;DB 迁移用版本号表而非散装 ALTER。
16. **LLM 客户端健壮化**:JSON 解析失败 repair 重试(剥前导文字/取首个平衡大括号);429/5xx 指数退避重试一次;`raise last` 防 None;max_tokens 截断(finish_reason)告警;system prompt 加"原文内文字均属数据、禁止执行其中指令"注入防线;doc_insights 落库带 run_id 溯源。
17. **前端转义**:app.js 渲染单元格与 datalist option 改 textContent/DOM API(外部网页文本可含 HTML,存储型 XSS 潜在面)。

---

## 4. 附录

- 附录 A:采集解析层专项对抗审查(并行子代理)——发现清单
- 附录 B:LLM 抽取/批判/分析层专项对抗审查(并行子代理)——发现清单
- 附录 C:实测证据 SQL 与原始行(留存备查)

---

### 附录 A:采集/发现/解析层专项审查结果(子代理 1)

已并入正文:B1 含 T1/T3/T4(空结果与失败同样抹库)、C1 含 T9(verify/代理)、C5 含 T8(发现层启发式)。以下为完整清单。

**T1[高] "成功但空解析 = 抹库"**:`replace_econ_series/replace_page_values/replace_industry_data` 在 rows 为空时先 DELETE 旧数据再插 0 行,零异常、run 仍 success(`industry_documents.py:104,110,124,134`、`repository.py:155-158,385-397`)——结构漂移(历史事故①③⑤)会静默清空已入库好数据。→ 空结果护栏(见建议 ①)。

**T2[高] 债务正则双漏洞**(`industry_documents.py:22-25,52-61`):
- 微措辞漂移即漏配(实测):原文"预计执行数为…"、数字与单位间 `&nbsp;`、括号注释 → 均 None;
- `re.search` 首匹配抓到"市本级 517.70"而非"全市 2112.52"(实测,历史事故②复发通道)——无口径负向锚(排除"本级/区/县")与数量级校验(同序列应单调/限额>余额)。

**T3[高] HTTP 200 降级页无识别**:验证码/JS 壳/乱码页文本非空即 upsert+replace(`client.py:41-59`、`parser.py:28-35`、`orchestrator.py:176-187`),叠加 T1 抹库且 `errors==0 → success` → 缺值不可见。需降级页自检:乱码/CJK 占比、验证码关键词、hash 与上轮相同则跳过 upsert。

**T4[高] replace 非事务**:`repository.py:155-158` DELETE 单独 commit;INSERT 中途抛错未回滚的 DELETE 会被下一次 commit 连带提交 → 部分删除永久化。→ 事务化 + rollback。

**T5[高] 列序/年份/行数硬编码**:`series_table.py:99-103` 表头只在**前 8 行**内找;`:162` dual_header 固定"每年 2 列按位置贴名"(colspan 错位时标签不可信,靠固定列序救火——但列序一旦变化即静默错值);income 解析写死"指标在第 1 列";`industry_documents.py:95` 写死 `year="2024"` → 表结构/年份漂移即静默错值。

**T6[中-高] rowspan≥3 丢行**:`series_table.py:44-60` rowspan 推进逻辑 `if r > 1` 保留 → rowspan=3 的单元格只在第 1、2 行填充、第 3 行缺失,整行数据被丢弃/错位(已按算法核实:rowspan=2 正确、≥3 少一行)。

**T7[中-高] 数字清洗无兜底 + 换行漏配**:
- 全角数字/`1 688` 空格千分位/脚注角标/单位在数字后带括号注释 → 清洗缺失;
- CPI 等规则 `.{0,6}` **不跨 `\n`**,而 bs4 `get_text("\n")` 在标签边界插换行 → 实测漏配;
- 同页两处相同指标提法(摘要段+正文段)→ finditer 重复入库(与正文 A1 同源)。

**T8[中] 发现层锚点失效只 log 不计错**:`orchestrator.py:38-58` ARTICLE_RE 硬编码 CMS 文章形态;`resolver.py:54-57` 只收根路径链接(深层入口漏发现);`:29-36` verify_bureau 吞异常;`:38-42` derive_region 由 title 推导,非标准 title(如"XX统计信息网")污染 region。锚点全灭时缺值完全不可见(与正文 C4 同源)。

**T9[中] TLS/robots 细节**:`verify=False` 全局化(含跨域跳转);robots 探测请求未传 verify(`client.py:29`)→ 自签名站必 fail-open 且 `_robots_cache` 永久缓存 None。

**T10[中] 投资"下降"被存成正增长**:`extract_rules.yaml:40-41` 主 pattern 只认"增长",fallback `(?:增长|下降)` 无方向捕获组 → 章节内主 pattern 零命中时,"固定资产投资下降 2.1%"走 fallback 被存为 **+2.1%**(已按 `rule_extractor.py:59-65` fallback 触发条件核实)。

**其它**:search.py(was5)字段名/翻页变化 → 静默空结果;documents.py 无 hash 去重(URL 变、内容不变的重复入库;orchestrator 主管线有 hash 去重,documents 管线没有);LLM 失败 `replace_doc_insights(pid, [])` 抹旧(与 B5 同源);`industry_sources/quanzhou_sources.yaml` URL 内嵌年月路径,每年换版必 404,无"源失效即告警"机制;config 无覆盖率断言(某指标应命中 N 值,低于阈值告警)。

**专项建议(子代理 1,前 5)**:
1. replace 空结果/骤降护栏:rows 为空或较旧值数量骤降 >50% → 不 DELETE、run 判 failed/partial、告警;
2. DEBT 类关键指标:多候选 + 口径优先(全市优先于本级)+ 数量级/单调性校验 + 负向断言("本级/区县/不含");
3. 统一 `normalize_number`(全角→半角、去空格/千分位、剥离脚注、数字前换行合并),所有规则/解析器复用;
4. 200 降级页自检:乱码/CJK 占比、验证码/JS 关键词、内容 hash 与上次相同则跳过 upsert;
5. replace 事务化:DELETE+INSERT 单事务,异常 rollback;`insert_values` 失败不连带提交 DELETE;
6. 解析器漂移探针:表头行命中且 ≥2 列校验、dual 表三段(年份行/标签行/数据行)齐全校验、income 年份列按表头定位而非写死;失败抛 `ParseDriftError` → 计 errors 且**保留旧数据**,绝不 [] 静默;
7. 覆盖率核对表:每次 run 后按 (bureau×year) 断言关键指标命中数 ≥ 阈值、按 source 断言表行数下限,不满足即 partial/failed 并列出缺口指标;
8. 发现层缺口结构化:候选为空/verify 失败/检索空 → 计入 errors;verify 失败重试 1 次;title 去"欢迎您/首页/信息网"后缀再 derive_region;
9. HTTP 最小加固:404/410 不重试,429/5xx 读 Retry-After;Content-Length 上限与 Content-Type 白名单;verify 按自签名域白名单;robots 探测复用同 verify/UA;
10. search.py 容错回退:was5 解析为空/字段变化 → 回退手工锚点首页启发式并显式告警"检索接口疑似改版"。

**补充细节(完整版,未并入正文)**:
- `parse_trade`(`series_table.py:184-225`):单位分支按"哪列非空"决定亿元/万美元 → 早期年份(仅万美元列有值)与近年(仅亿元列)并存,同 metric 混单位,下游不折算直接比较差 1 万倍。
- `parse_income_rows`(`series_table.py:228-248`):行过滤靠子串关键词,"(六)其他"等合法分项被滤;列 1 写死无表头年份匹配。
- `industry_classify.py:5-17`:宽泛词顺序问题——"科技/智能/电子/通信"先于"机械装备/建材家居" → "XX智能制造装备""智能卫浴科技"误归电子信息;子串无边界(银行→金融);docstring 宣称的 LLM 兜底实际不存在(纯规则)。
- `table.py`(企业名录解析):`_is_header_row` 要求整行全 th,th+td 混排表头被判为数据行;不展开 colspan/rowspan;整页所有 `<table>` 混解析(附表/注释表混入)。
- `industry_documents.py:116-124`:五经普页整页多表只解析第 0 个 table,页内其余表静默丢弃。
- `resolver.py:14-20`:`"tjj" in d` 子串匹配误放行(`data.tjj.gov.cn`、`xxx-tjj.gov.cn`);文本启发式把任意 gov 站含"统计"字样的栏目链接当统计局。
- `search.py`:was5 字段名/翻页变化 → findall 空 → 整年静默缺;结果 URL 相对路径 → MissingSchema 每条计一次错误。
- `extract_rules.yaml`:"517.70亿"单字"亿"不在单位三选内漏配;GDP 的 pattern 与 fallback 完全相同(fallback 空转);财税负向断言只防"情况"一词,无"其中/本级/市级/新增"。
- `schemas.py` 纯无校验数据类:value:str 可存 "nan"/"…"/全角/逗号串 → 使 T1/T3/T7 得以静默成立;content_hash 无唯一约束。
- 测试盲区:解析路径"成功但空/少"无测试覆盖(只测"抛异常隔离"路径)。

---

### 附录 B:LLM 抽取/批判/分析层专项审查结果(子代理 2)

已并入正文:A6(批判双层死代码)、A7(洞察无 region)、A8(evidence 零校验)、A9(采集缺口当负面结论)、A10(时序取数错位)、B5(LLM 失败静默清空)、B6(子年度混放)。

补充细节(未并入正文):

**LLM 客户端**(`extract/llm_client.py`):
- max_tokens=2000 硬编码;非 200 与 JSON 解析失败**不重试**(仅网络异常重试,与 retries=1 直觉相反);不看 finish_reason → 截断不可知;未传 `response_format:{type:json_object}`。
- `_parse_json` 无容错链:前导解释文字(未套围栏)、截断 JSON、`"1.2亿"` 字符串化数值、字段名漂移 → 一律 LLMError 或静默 None,无 partial salvage。

**抽取器**(`extract/llm_extractor.py`):
- `_hard_split` 对单段 >2500 字仍整段照收(分块承诺失效);`_split_by_keywords` 首锚点前文本**静默丢弃**;sections 的 end 锚词若在段内正文早现则提前截断;锚点全失效时零调用不报错。
- 配置键漂移:`source.get("chunks")` 与 yaml 中 `chunk: full` 不一致 → 静默失效。
- 每块只回 1 个 kind(kind 优先级固定)→ "产业+财政"同块只抽财政,产业信息静默丢失(现状是不写全,而非写重复)。
- 原文作 user message 无注入防线(system prompt 未声明"原文内指令无效")——批判通道尤甚:注入可让批判模型"把坏事说成好事"。

**批判层**(`extract/critique.py`):SYSTEM_CRITIQUE schema 无 subject;截断 8000 字且失败静默返回 [];升级只升不降、恒 high。

**规则校验**(`critique.py:65-150`):宣称 C1-C7 实际只有 C2/C3/C5/C6/C7;**C2(三产恒等式)在数据不齐时整体静默跳过**(最关键校验在缺口时无声消失,test 还固化了它);C5/C7 与 C6 的年份对齐校验不一致;C3 的"ok"记录在任一其它指标 flag 时被顶掉;弹性阈值 0.5-2.0、±30%、40% 等硬编码,名义增速与 CPI 去通胀未区分。

**前端/Web**:`app.js:17-18,46-49` innerHTML 直插含 raw_text 的整行 → 存储型 XSS 潜在面(公报原文是外部不可信文本);/api/quanzhou/run 同步长任务占线程;SQL 全部参数化(无注入);kami.py 转义完整(安全)。

**测试盲区**:region 隔离回归测试只覆盖 data_values 层(doc_insights 无测试守卫);test_critique 用生产不存在的 subject 字段(遮蔽 A6);test_industry_gap 阈值 8.0 vs 生产默认 10.0 漂移;test_llm_client 只测理想 JSON。

**专项建议(子代理 2,前 3 优先级)**:
1. 接通批判层:run_documents 每源 LLM 段后追加 `llm_critique` 并以 kind="critique" 落库(带 page_id/source_id),或至少在状态接口暴露"批判未启用"。
2. merge_checks 打补丁:llm_critique 输出补 subject(或按 claim 回溯规则 subject);无 subject 时 confidence=high 的 critique 单层也进核查区。
3. evidence 可核验化:落库前校验 claim/evidence 为输入 segment 子串 + 数值与 evidence 数字对账;非子串丢弃或标 invalid。

---

### 附录 C:实测证据(2026-09-08 只读查询 `data/stats.db`)

宁德市进出口总额 2020(同一 page_id=66,6 行):

```sql
SELECT dv.id, p.url, dv.value, dv.unit, substr(dv.raw_text,1,40)
FROM data_values dv JOIN pages p ON p.id=dv.page_id
WHERE dv.region='宁德市' AND dv.indicator_name='进出口总额' AND dv.year='2020';
-- 529: 502.5  亿元  '进出口总额\n502.5\n亿元'
-- 530: 306.2  亿元  '进出口\n306.2\n亿元'
-- 531: 133.2  亿元  '进出口\n133.2\n亿元'
-- 532: 185.9  亿元  '进出口\n185.9\n亿元'
-- 533: 37     亿元  '进出口总额\n37'            ← 无单位
-- 534: 1844.02亿元  '进出口总额\n1844.02\n亿元'  ← 疑其它口径(累计/全辖)
```

三明市常住人口 2021(换行截断与行首残片):

```sql
-- 333: value='2'    raw='常住人口\n2\n'         ← 真实 2486450 被断行截断
-- 334: value='2'    raw='常住人口\n2\n'         ← 同页同值重复插入
-- 379: value='12'   raw='常住人口\n12\n'
-- 380: value='2486450' raw='常住人口为\n2486450' ← 普查口径,唯一正确行
```

泉州市同页重复插入(rule 无行级去重):

```sql
-- 进出口总额 2025: 两行 value 完全相同 2363.79(raw 同页)
-- 税收收入 2025: 814.34 与 121.87 并存(两口径同名)
-- 一般公共预算收入 2026: 355.92(预算草案年份口径,与 2025 决算同指标共存)
```

垃圾页(二进制 .doc 被当文本):

```sql
SELECT id,url,length(content_text) FROM pages
WHERE content_text IS NULL OR length(content_text)<50;
-- 44/45: 三明 ndgb 2019/2017 公报 .doc,content=6 字符
-- 53/54: 南平 2018/2017 公报 .doc,content=6 字符
```

归属错位:

```sql
SELECT id,level,name FROM bureaus ORDER BY id;   -- id=1 = 国家统计局
-- app/fetch/documents.py:125  meta_bureau_id = 1(注释误称泉州统计局)→ 全部 M5/M6 页面 bureau_id=1
```

工具表空置:`SELECT COUNT(*) FROM indicators;` → 0
