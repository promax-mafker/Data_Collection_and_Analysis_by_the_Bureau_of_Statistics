# M5 泉州经济纵深画像 · 设计文档

> 状态:待用户审查(第二版,已按用户意见加入「防美化批判审读层」)。对应软件工作流阶段 1,确认前不写代码。
> 背景:M4 完成 9 市公报横比后,用户指出「只有最抽象的截面,看不到支柱产业、核心机构、就业岗位分布、财税结构」;并希望基于政府文件原文做经济学术语的数理解析,与财政结构结合。
> 试点:泉州市单市深度样板(用户已确认)。引擎:规则 + LLM 双引擎(用户已确认,千问 qwen3.8-flash key 已配置 .env)。
> 关键修订:用户指出「政府公报会美化经济数据,要给 LLM 套壳,使其具有经济学家的洞察力,不被表面好看的数据迷惑」→ 新增 §5.5 批判审读层与 §6.5 数据可信度校验。

## 1. 目标与验收标准

### 1.1 目标

在现有「统计公报横比」之上,对泉州做一份**经济纵深画像**:把政府公开的规划纲要、政府工作报告、财政预决算、企业名录等**政策性/表格式文本**,解析为可数理分析的机构化数据,回答四问:

1. **当地靠什么吃饭** → 支柱产业图谱(产值规模、增长承诺、规划定位)
2. **谁在撑经济** → 核心机构与市场主体(上市后备企业、县市区分布、产业归属)
3. **人靠什么吃饭** → 就业岗位分布(总量、增量、与产业/人口的比例关系)
4. **钱从哪来、花到哪去** → 财政税收结构(收入/税收/基金/土地依赖、支出方向、规划财力匹配)

### 1.2 验收标准(可验证)

1. **采集**:五个来源栏目全部入库(规划纲要 PDF、2011–2026 历年政府工作报告、2025 决算+2026 预算、2026 预算执行、2025 上市后备企业 170 家名单),直链实测 200,入库页数与源 URL 计数一致。
2. **结构化**:公报数字走规则(复用 M4);规划/报告走 LLM 解析(需 key);企业名录走 HTML 表格解析。每条产出带原文溯源。
3. **数理分析**:报告产出 ≥6 个计算指标(财政强度/税收占比/土地依赖度/规划增速可行性/新增就业密度/企业产业聚合),公式可复核,输入值可溯源。
4. **报告**:`data/reports/quanzhou_profile.html/md` 单市画像报告,五章结构,无官方口吻章节由 LLM 输出并人工可审。
5. **测试**:新增测试全绿;LLM 缺失时管道仍能跑通(降级为规则+表格+跳过 LLM 章节并标注)。

### 1.3 非目标(本轮不做)

- 不做多市铺开(样板先行,验证后另立项)
- 不做「经济 → 政治」解读结论(用户自取数据做解读)
- 不采人社局失业率月度栏目(侦察存疑项)
- 不做图表可视化
- 不做土地出让逐宗明细(仅用政府性基金收入作依赖度代理)

---

## 2. 数据源清单(已实测 200)

| 类别 | 源 | 形态 | 直链(实测) |
|------|-----|------|------------|
| S1 规划纲要 | 十五五纲要全文 | PDF 130 页 8.5 万字,15 章 | `www.quanzhou.gov.cn/zfb/xxgk/zfxxgkzl/zfxxgkml/srmzfxxgkml/ghjh/202605/P020260609588315746018.pdf` |
| | 十四五纲要全文 | PDF | 同目录 `ghjh/202105/P020250305341826509942.pdf` |
| S2 政府工作报告 | 2026 年全文 | HTML 1.8 万字(回顾→十五五目标→2026 任务) | `.../bgzj/zfgzbg/202603/t20260310_3273077.htm` |
| | 历年(2011–2025) | HTML 栏目 | `.../bgzj/zfgzbg/`(历年 t20xxxxx 链接) |
| S3 财政预决算 | 2026 预算报告+收支表 | PDF×5 | `czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/` |
| | 2025 决算 | PDF | `czj.quanzhou.gov.cn/ztzl/jsgkpt/sjjsgk/` |
| | 2026 上半年预算执行 | HTML 含表 | 门户 `ztxxgk/czzj/czys` + czj `czysjsbg/` |
| S4 企业名录 | 2025 上市后备企业 | HTML 表格×2(170 家) | `.../qzdt/qzyw/202510/t20251015_3218492.htm` |
| | 2024 年 182 家 | HTML 表格 | `.../202409/t20240905_3078524.htm` |
| S5 就业 | 2025 统计公报(含就业) | HTML 10 表 | `tjj.quanzhou.gov.cn/tjzl/tjgb/202603/...` |
| | 2026 报告就业目标 | HTML | S2 内 |

口径关键数(侦察确认,用于数理分析对照):
- 2025 统计公报:地方一般公共预算收入 592.07 亿、支出 880.29 亿、政府性基金收入 292.07 亿、税收 814.34 亿
- 2026 上半年执行:地方一般公共预算收入 355.92 亿、税收 204.02 亿
- 2026 报告预期:GDP +5%、预算收入 +2.5%、城镇新增就业 8 万人
- 2025 公报实际:城镇新增就业 9.49 万人、再就业 1.67 万人

---

## 3. 架构改动(最小侵入,延续分层单体)

```
现有: discovery → fetch → extract → store → web → orchestrator (面向统计局 bureaus)
M5:   新增「文档源注册表」doc_sources.yaml —— 面向政府门户栏目(非统计局机构)
```

核心思路:**不扩 bureaus 语义**(这些不是统计局),新增一个轻量 `documents` 管线,复用 fetch/pdf/store 设施:

1. `config/quanzhou_sources.yaml`:注册表,每个源 = `{id, category, name, url, kind(html|pdf|table), parse(规则|llm|表格), years, note}`。内容来自上表实测直链。
2. `app/fetch/documents.py`(或扩 orchestrator):按注册表逐源采集 → 页面落 `pages` 表(新增 `doc_category` 列区分 bulletin/plan/gov_report/budget/enterprise),正文/PDF 文本清洗后按解析器处理。
3. 解析结果落库:
   - **数值型**(财政/就业/GDP 目标等)→ 复用 `data_values`(indicator_name 扩展新指标,如「地方一般公共预算收入」「税收收入」「政府性基金收入」)
   - **文本型洞察**(规划产业承诺、LLM 解读)→ 新表 `doc_insights`
   - **名录型**(企业)→ 新表 `enterprises`
4. `app/analysis/quanzhou.py` + `report.py` 扩展:单市画像计算 + 渲染。
5. Web:`/api/quanzhou` 端点 + 页面 Tab;`/api/run` 扩展参数 `scope=quanzhou`。

### 3.1 pages 表变更

```sql
ALTER TABLE pages ADD COLUMN doc_category TEXT NOT NULL DEFAULT 'bulletin';
-- 取值: bulletin | plan | gov_report | budget | enterprise
```

### 3.2 新表 doc_insights(LLM/结构化解读)

| 字段 | 说明 |
|------|------|
| id | PK |
| page_id | FK pages |
| source_id | 注册表源 id |
| kind | plan_goal / industry / fiscal_signal / employment / narrative |
| title | 要点标题 |
| body | 结构化解读(JSON) |
| method | llm / rule |
| created_at | 时间 |

body JSON 示例(plan_goal):`{"period":"十五五","target_gdp_growth":5,"target_revenue_growth":2.5,"target_jobs":80000,"unit":"万人/年","basis":"政府工作报告 2026"}`

### 3.3 新表 enterprises(名录)

| 字段 | 说明 |
|------|------|
| id | PK |
| page_id | FK |
| year | 2025 |
| list_type | 上市后备 / 挂牌后备 |
| name | 企业名 |
| county | 县市区(晋江/石狮/…) |
| rank | 序号 |

---

## 4. 解析引擎分工

| 源 | 解析器 | 说明 |
|----|--------|------|
| 公报(数字) | RuleExtractor(现有) | GDP/三产/就业等数值,无需改动 |
| 预算执行/决算 HTML | 规则+表格 | 收入/税收/基金等关键科目,数值正则 + HTML table 解析 |
| 企业名录 | 表格解析器 | `app/parse/table.py`(新增):HTML table → 行记录(name/county) |
| 规划纲要/政府工作报告 | **LLMExtractor**(落地) | 全文太长 → 分章送入;输出结构化 JSON(见 §5) |
| 政策解读/图解 HTML | LLMExtractor | 与纲要同构,短文本 |

---

## 5. LLM 引擎设计(LLMExtractor 落地)

### 5.1 配置

`.env`(gitignore,已就绪):
```
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxx(千问,已配置)
LLM_MODEL=qwen3.8-flash
```
`app/extract/llm_extractor.py` 实现:OpenAI 兼容 `chat/completions`,httpx/requests 调用,`load_dotenv` 读取;无 key → 构造成功但 `enabled=False`,管线跳过 LLM 步骤并在报告标注「LLM 章节未生成(缺 key)」。

### 5.2 提示词协议(去官方口吻 + 结构化)

每章调用一次,系统提示固定角色:
```
你是一名中国经济研究者。把政府文件原文改写成经济学分析,剥离宣传语与官方口吻
(如「砥砺奋进」「迈上新台阶」),只保留可检验的事实、目标、机制与约束。
输出严格 JSON,不要多余文字。
```
用户消息含「章节原文 + 抽取 schema」,schema 按 kind 分:

- **industry**:`[{industry, scale_or_target, growth_claim, plan_role(支柱/新兴/培育), policy_instruments[], evidence(原文摘录)}]`
- **fiscal_signal**:`[{subject, item, value, unit, year, note, evidence}]`(含支出方向、债务、转移支付、基金)
- **plan_goal**:`{period, targets:{gdp_growth, revenue_growth, jobs, others[]}, risk_factors[], evidence[]}`
- **employment**:`[{segment, value, unit, year, trend, evidence}]`

要求:每个输出对象含 `evidence` 原文摘录,保证**可溯源、可人工复核**;禁止模型自行发明数值。

### 5.3 文本分块

- 规划纲要 8.5 万字 → 按目录章节(15 章)切块,只送相关章节(产业体系/民营经济/财政/就业民生)各 ≤6000 字,超长再切。
- 政府工作报告 1.8 万字 → 一次送入或按「回顾/目标/任务」三段切。
- 断点续跑:已入库的 page 不重复调用(复用 content_hash 去重)。

### 5.4 人工审阅机制

LLM 输出进 `doc_insights` 后,报告渲染时默认**展示 evidence 原文摘录**,方便人工核对;分析层只用 LLM 输出的**数值字段**做数理计算(如 target_gdp_growth),文本叙述单独陈列,不进入公式。

### 5.5 批判审读层(防数据美化,用户指定)

**问题**:政府公报/报告是「选择性披露」产物——只报增长项、回避下降项、用修辞包装平淡数字。若 LLM 只做「剥离口吻的结构化抽取」,等于把美化的数字当中性事实入库,画像会被表面数据带偏。

**设计:双通道审读——规则校验器(客观、可复核) + LLM 批判审读器(语义、洞察)**。二者独立产出,均带原文证据,不互相信任,报告并列展示。

#### 通道 1:规则校验器(确定性,不依赖 LLM,先跑)

对入库数值做机械交叉校验,输出 `check` 记录(severity: high/med/low):

| 检查 | 逻辑 | 示例(泉州) |
|------|------|-----------|
| C1 口径一致 | 同一年「预算收入」在不同源(公报/决算/执行)是否一致;不一致记录两值 | 公报 592.07 亿 vs 上半年执行 355.92(半年,需换算注释) |
| C2 恒等式 | 三产和 = GDP、结构占比和 = 100、收入 = 税收 + 非税(若可得) | 复用 M4.1 C 策略 |
| C3 跨年突变 | 同指标相邻两年增速 > ±30% 或符号反转,无政策事件说明则标记 | 税收 814 亿 vs 上年 |
| C4 目标-现实落差 | 报告目标增速 vs 实际增速(如 2026 目标 +5% vs 2025 实际),差 >3pp 标记 | 需跨年公报 |
| C5 弹性异常 | 预算收入增速 ÷ GDP 增速 > 2 或 < 0.5(税收弹性),异常标记 | 目标 +2.5% ÷ GDP +5% = 0.5(临界) |
| C6 结构可疑 | 政府性基金收入占比(土地依赖)趋势、税收/非税比突变 | 基金 292 ÷ (592+292) = 33% |
| C7 就业-经济背离 | 就业高增长但 GDP 低增长,或反之(奥肯定律弱校验,仅提示) | 新增 9.49 万 vs GDP +X% |

每条 check:`{id, subject, year, expectation, actual[], verdict(ok|flag), severity, note, sources[]}`。

#### 通道 2:LLM 批判审读器(经济学家视角)

对**同一份文本**追加一次独立调用,系统提示切换为批判角色:
```
你是一名对中国地方经济数据有长期研究的经济学家。政府文件倾向于选择性披露:
只报亮点、回避衰退、用修辞包装平淡甚至下滑的数据。
请以怀疑态度审读以下原文,识别:
1) 修辞包装:无数据支撑的溢美之词(「历史新高」「稳中向好」「圆满收官」等);
2) 选择性披露:只报增长/总量、回避下降/结构性问题/债务/土地财政依赖;
3) 口径游戏:用「增长」指名义而非实际、用投资拉动掩盖消费疲弱、人均指标掩盖总量停滞等;
4) 数字间的逻辑缺口:目标与现实增速的张力、财力与承诺支出的缺口。
输出严格 JSON,每一条必须含 evidence 原文摘录,禁止编造数据,禁止给出无法从原文或
你专业知识推断的结论;不确定的标注 confidence: low。
```
输出 schema(`doc_insights.kind = critique`):
```
{critiques: [
  {type: spin|omission|metric_game|gap, severity: high|med|low,
   claim: 原文中的表述(摘录), reality: 经济学家的解读(为什么不可全信/缺什么数据验证),
   what_to_check: 若要证实/证伪需要哪些数据, confidence: high|med|low}
]}
```

**关键原则(防越界)**:
1. 批判层输出的是**「提示与质疑」不是结论**——标注 confidence,报告里以「⚠ 审读提示」呈现,不直接断言「数据造假」。
2. 每条必须挂 evidence,且 critique 中的**数值主张**(如「该增速高于全省平均」)若来自 LLM 外部知识,必须标 `external_claim: true` 并给出 what_to_check,不能冒充原文事实。
3. 规则校验(C1-C7)是客观层,LLM 批判是语义层,二者独立:同一 flag 若双层都命中,severity 升一级。
4. 与「经济→政治解读由用户自取」不冲突:审读层只处理**数据可信度与经济机制**,不延伸政治判断。

#### 存储与呈现

- 规则校验 → `data_values` 派生,运行时计算,不落库(或落 `runs` 附注)。
- LLM 批判 → `doc_insights(kind=critique)`,与提取结果同表同溯源机制。
- 报告:每章数据表下方挂该章的校验/批判结果(✓ 通过 / ⚠ flag + evidence);独立「第六章 数据可信度审读」汇总表。

---

## 6. 数理分析设计(`app/analysis/quanzhou.py`)

输入:data_values(数值)+ enterprises + doc_insights(目标值)。
全部指标:名称 + 公式 + 输入来源,可复核。

### 6.1 财政维度

| 指标 | 公式 | 输入 |
|------|------|------|
| 财政强度(宏观税负代理) | 一般公共预算收入 ÷ GDP | 592.07 / 泉州 GDP 2025 |
| 税收强度 | 税收收入 ÷ GDP(或 ÷ 预算收入) | 公报税收 814.34(含上缴中央口径,需注释) |
| 预算收入自给率 | 一般公共预算收入 ÷ 一般公共预算支出 | 592.07 / 880.29 = 67.3% |
| 土地财政依赖度 | 政府性基金收入 ÷ (一般公共预算收入+政府性基金收入) | 292.07 / (592.07+292.07) |
| 收入结构 | 税收/非税占比 | 预算执行表 |
| 规划增速可行性 | 规划预算收入增速 vs 十五五 GDP 增速弹性 | doc_insights |

### 6.2 产业维度

| 指标 | 公式 | 输入 |
|------|------|------|
| 规划产业承诺数 | 各产业 LLM 条目 count | doc_insights industry |
| 产业政策密度 | policy_instruments 总数 ÷ 产业数 | 同上 |
| 民营经济地位 | 规划民营经济章节关键词承诺 | 原文摘录 |

### 6.3 市场主体维度

| 指标 | 公式 | 输入 |
|------|------|------|
| 企业县区集中度 | 各县区企业数 ÷ 总数(赫芬达尔指数 HHI) | enterprises |
| 头部县区 | 企业数 Top3 县区及占比 | enterprises |
| 年度扩张 | 2025 名单 170 vs 2024 182 变化 | 两年度名单 |

### 6.4 就业维度

| 指标 | 公式 | 输入 |
|------|------|------|
| 新增就业密度 | 城镇新增就业 ÷ 常住人口(‰) | 9.49 万 / 泉州常住人口 |
| 就业目标达成率 | 实际新增 ÷ 报告目标 | 9.49 / 8(2025 实际 vs 2026 目标需同口径,注释) |
| 就业-财政弹性 | 新增就业增速 ÷ 预算收入增速 | 跨年 |

> 口径注意:公报「税收 814.34 亿」与预算执行「税收 204.02 亿」不同源(全口径 vs 地方级),分析必须加注释,不做静默混用。

### 6.5 数据可信度审读汇总(与 §5.5 配套)

运行时聚合两个通道输出,产出审读总表,输入报告第六章:

| 输出 | 来源 | 呈现 |
|------|------|------|
| `checks[]` | 规则校验器 C1-C7(severity/verdict) | 每章数据表下方 ✓/⚠ 标记 |
| `critiques[]` | LLM 批判审读器(spin/omission/metric_game/gap) | 第六章「⚠ 审读提示」列表,每条含 evidence |
| `escalated[]` | 双层同时命中的 flag(severity 升一级) | 第六章置顶「重点核查」 |

审读层**不修改数据值**,只做标注——数据画像主体仍是抽取出的数字,审读结果作为独立的可信度层叠加。

---

## 7. 报告结构(`data/reports/quanzhou_profile.md/html`)

```
# 泉州市经济纵深画像(2025 基准)
0. 元信息:数据源清单 + 口径声明 + LLM 启用状态
1. 财政税收结构   —— 财政强度/自给率/土地依赖/收入结构表(全部可溯源)+ ⚠ 审读标注
2. 支柱产业图谱   —— 规划产业定位 + 政策密度 + 原文 evidence + ⚠ 审读标注
3. 核心机构与市场主体 —— 上市后备企业县区分布/HHI/年度变化
4. 就业岗位分布   —— 新增就业/密度/目标达成 + ⚠ 审读标注
5. 五年规划路径的数理审视 —— 规划目标 vs 现实增速 vs 财力匹配(LLM 数值 + 分析层计算)
6. 数据可信度审读 —— 规则校验 C1-C7 结果 + LLM 批判提示(spin/omission/…)+ 重点核查(双层命中)
7. 附录:LLM 章节原始输出 + 人工复核留痕
```

Web:主界面新增「泉州画像」Tab,内嵌报告 iframe + 导出。

---

## 8. 文件与任务拆解预告(阶段 2 细化)

| 文件 | 职责 |
|------|------|
| `config/quanzhou_sources.yaml` | 注册表(§2 直链) |
| `app/fetch/documents.py` | 文档源采集器(注册表→fetch→落 pages) |
| `app/parse/table.py` | HTML 表格 → 记录列表 |
| `app/extract/llm_extractor.py` | LLM 引擎落地(§5.1-5.3,抽取通道) |
| `app/extract/critique.py` | LLM 批判审读器(§5.5 通道 2)+ 规则校验器(§5.5 通道 1,C1-C7) |
| `app/store/db.py` | pages 加列 + 新表 doc_insights/enterprises |
| `app/store/repository.py` | 新表的 CRUD |
| `app/analysis/quanzhou.py` | §6 数理计算(含 6.5 审读汇总) |
| `app/analysis/report.py` | 报告渲染扩展(含第六章审读) |
| `app/main.py` + web | /api/quanzhou + Tab |
| `tests/test_documents.py` `test_table.py` `test_llm_extractor.py` `test_critique.py` `test_quanzhou_analysis.py` | 测试 |
| `docs/PROGRESS.md` | 进度更新 |

## 9. 风险与降级

| 风险 | 缓解 |
|------|------|
| LLM key 未提供 | 管道照跑:规则+表格+公报全量,LLM 章节标注「未生成」,后续补 key 重跑只补该步(按 hash 去重) |
| LLM 输出幻觉数值 | 强制 evidence 摘录 + 数值仅从原文提取指令 + 报告附录留痕人工审 |
| LLM 批判越界(断言造假/政治化) | 批判输出限「提示与质疑」+ confidence 标注 + external_claim 区分;报告以 ⚠ 呈现非结论 |
| PDF 扫描版(十五五纲要若为图片型) | 侦察已确认文字型(8.5 万字可提取);失败则记录并跳过 |
| 口径混用(税收两套) | 分析层强制注释,指标定义内嵌口径;C1 校验器自动核对跨源同指标 |
| 报告超长 | 分章渲染,每章独立可刷 |
