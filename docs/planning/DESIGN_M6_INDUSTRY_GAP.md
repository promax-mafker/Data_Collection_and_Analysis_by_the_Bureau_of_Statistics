# M6 泉州经济驱动画像 · 设计文档(产业结构错配 + 三驾马车)

> 状态:待用户审查。软件工作流阶段 1,确认前不写代码。
> 背景:用户先后指出 ①「判断支柱产业不能只读政府规划,要有实际数据支撑」;②「新增 CPI、人均 GDP、收入中位数,衡量本地消费对经济的支撑」;③「添加政府债务/GDP 及配套指标衡量政府投资拉动,举一反三到出口」。
> 侦察结论(三个子代理实测可得):
> - 产业结构:五经普 2023 分行业(单位/从业/营收)+ 年鉴表 8-7/8-8(规上工业分行业+重点产业 2016-2024 时序)+ 170 家企业名单。分行业税收/进出口不可得。
> - 消费:常住人口、人均可支配收入(全体/城乡)、人均消费支出+8 大类、恩格尔系数、CPI 历年(1984-2024)均可得;**收入中位数、支出法 GDP/最终消费率地市级制度性不可得**(需降级)。
> - 投资/债务/出口:政府债务余额/限额(2019-2024 序列)、基建财政支出(决算表)、出口/进口/净出口(分列+历年序列)、投资增速(公报)可得;**支出法 GDP、一般/专项债分项、官方债务率、固投绝对额序列不可得**。

## 1. 目标与验收标准

### 1.1 目标

把泉州画像从「截面 + 规划承诺」升级为**经济驱动全景**,四块:

**A. 实际产业结构 × 规划承诺错配**(支柱产业真实度)
1. 实际产业结构:分行业法人单位数/从业人员/营业收入(五经普 2023)。
2. 重点产业时序:规上工业重点产业 2016-2024,识别真增长引擎。
3. 企业行业归类:170 家上市后备企业行业集中度。
4. 增长贡献度:产业增量对 GDP 增量贡献率(用户自定义)。
5. 错配矩阵:🔴规划强/实际弱 · 🟢沉默支柱 · ⚪一致。

**B. 消费支撑度**(本地消费对经济的支撑)
1. 消费规模:社零/GDP、社零增速 vs GDP 增速。
2. 消费能力:人均可支配收入、人均消费支出、**消费倾向(消费支出÷收入)**。
3. 购买力与物价:CPI 历年序列。
4. 消费结构:8 大类分项占比 + 恩格尔系数。
5. 收入分配代理:城乡收入比(替代不可得的中位数)。

**C. 政府债务与投资拉动**(政府投资对 GDP 的拉动)
1. 政府杠杆:**债务余额/GDP**、债务余额/限额使用率、债务余额 2019-2024 增速 vs GDP 增速。
2. 投资拉动:固定资产投资/基础设施投资增速 vs GDP 增速(公报口径)。
3. 财政基建投入:政府性基金支出、基建相关预算支出(决算表)。

**D. 净出口拉动**(出口对 GDP 的拉动)
1. 外贸规模:出口额/GDP(外贸依存度)、净出口额。
2. 出口拉动:出口增速 vs GDP 增速、历年出口/进口/净出口序列。

### 1.2 验收标准(可验证)

1. 采集:五经普第一/二号、年鉴表 8-7/8-8、表 3-4(常住人口)、表 4-5~4-9(收支)、表 5-2(CPI)、表 12-3(进出口)、债务报告(2019-2024)、决算表 全部入库,行数与源一致。
2. 企业归类:170 家 ≥80% 归入行业大类(规则+LLM 兜底),可抽样核对。
3. 增长贡献度:≥5 个重点产业增量贡献率计算正确、公式可复核。
4. 错配矩阵:每个规划支柱产业有「实际占比/增速/企业数」证据,判定规则明确。
5. 三驾马车:消费/投资/出口三类拉动指标齐全,因支出法 GDP 缺失采用的**代理口径在报告显式注明**,不冒充核算口径。
6. 测试全绿;报告新增「实际产业结构错配」「三驾马车拉动」两章。

### 1.3 非目标

- 分行业税收、分行业进出口(官方无公开,放弃)
- 收入中位数、支出法 GDP/最终消费率(地市制度性不公布,用代理指标并显式标注)
- 全国/其余 8 市推广(仍是泉州样板)
- 不改 M5 已有画像结构(新增章节)

- 分行业税收、分行业进出口(官方无公开,放弃,不硬造)
- 不做全国扩展、其余 8 市推广(仍是泉州样板)
- 不改变 M5 已有画像结构(新增章节,不动旧章)

---

## 2. 数据源(已实测)

| 源 | URL | 形态 | 数据 |
|----|-----|------|------|
| S1 五经普第一号 | tjj.quanzhou.gov.cn/tjzl/tjgb/202505/t20250512_3168240.htm | HTML 表格 | 表1-2 法人单位数、表1-3 从业人员、表1-4 营业收入(行业门类) |
| S2 五经普第二号 | …/t20250512_3168260.htm | HTML 表格 | 表2-2 工业分行业单位+从业、表2-3 分行业营收/资产/负债(行业大类) |
| S3 年鉴 2025 表8-7 | …/tsys/UpLoadFiles/43sjfb/129ndsj/qztjnj2025/index-cn.htm(iframe) | HTML 表格 | 规上工业分行业 2024 单位/资产/利润/利税/增值税 |
| S4 年鉴 2025 表8-8 | 同上 | HTML 表格 | 规上工业重点产业 2016-2024 时序(纺织鞋服/石化/机械/电子/健康食品) |
| S5 企业名单 | 已入库 | enterprises 表 | 170 家,名称+县区 |

> 风险:S3/S4 是 iframe 嵌套电子年鉴,实际数据可能在 iframe 的二级 URL 中;采集时需先抓 index-cn.htm 再解析 iframe src,逐层进入「第八章 工业」表格页。侦察确认可达,但 URL 层级待采集中定位(失败则回退五经普第一号+第二号,已足够支撑错配分析)。

---

## 3. 数据模型

### 3.1 新表 `industry_data`(分行业实际数据)

```sql
CREATE TABLE IF NOT EXISTS industry_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,          -- census2023_1 / census2023_2 / yearbook_8_7 / yearbook_8_8
  industry TEXT,        -- 行业名(如 纺织鞋服 / 石油化工 / 农副食品加工)
  year TEXT,            -- 2023(普查) / 2024(年鉴) / 2016-2024 时序
  metric TEXT,          -- units(单位数) / employees(从业人员) / revenue(营业收入) / added_value(增加值) / assets / profit
  value TEXT,           -- 数值(保留原始字符串,解析时转 float)
  unit TEXT,            -- 万元 / 人 / 个
  raw_text TEXT,        -- 源表行原文(溯源)
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

### 3.2 企业行业归类

不改 enterprises 表结构,新增 `enterprise_industry` 表或在分析层动态归类(优先动态,避免脏数据):

```sql
CREATE TABLE IF NOT EXISTS enterprise_industry (
  enterprise_id INTEGER PRIMARY KEY,
  industry TEXT,        -- 归入的行业大类
  method TEXT,          -- rule(关键词) / llm(兜底) / unknown
);
```

## 4. 解析引擎分工

| 数据 | 解析器 | 说明 |
|------|--------|------|
| 五经普表格(1-2/1-3/1-4/2-2/2-3) | `extract_table_records`(已有)+ 表头→metric 映射 | HTML 表格,复用 table.py |
| 年鉴 8-7/8-8 | 同上 | 需先穿透 iframe 取表页 |
| 企业行业归类 | 规则关键词词典 + LLM 兜底 | `app/parse/industry_classify.py`(新增) |

## 5. 企业行业归类规则(`app/parse/industry_classify.py`)

按企业名称关键词 → 行业大类。词典覆盖泉州主导产业:

| 行业大类 | 关键词 |
|---------|--------|
| 纺织鞋服 | 纺织、制衣、鞋、服装、纤维、皮革、皮业、服饰 |
| 机械装备 | 机械、智能装备、机电、汽配、汽车、模具 |
| 电子信息 | 电子、通信、通讯、光电、半导体、物联网、科技(部分) |
| 石油化工 | 石化、化工、燃气、油 |
| 健康食品 | 食品、茶业、水产、饮料 |
| 建材家居 | 建材、陶瓷、卫浴、石材、家居 |
| 卫生用品 | 卫生用品、妇幼、纸业 |
| 新材料 | 新材料、材料科技、纤维制品(交叉,优先新材料) |
| 金融 | 银行、融资租赁、小额贷款、供应链金融 |
| 环保/公用 | 环保、供水、水务、燃气 |
| 建筑/园林 | 建设、园林、城市规划 |
| 其他 | 兜底 |

关键词匹配顺序按「特异性优先」(长词/精准词在前),`method=rule`;无法归入的 `method=unknown` 交 LLM 兜底(批量送一次,按名称列表返回归类)。

## 6. 增长贡献度(用户自定义「地区经济增量与产业增量相关度」)

对规上工业重点产业 2016-2024 时序(S4 表8-8):

```
产业贡献率 = Δ产业增加值(相邻年) / ΔGDP(相邻年) × 100%
产业增速 = (v2024 - v2016) / v2016 × 100%
```

计算每个重点产业的:
- 累计增速(2016→2024)
- 年均复合增速 CAGR
- 最近一年增量对 GDP 增量的贡献率

排序后识别「真增长引擎」(贡献率高)与「规划强但贡献低」的产业。

> 口径:规上工业重点产业增加值与全市 GDP 的增量直接相除有口径差(工业 vs 全部),贡献率作为**相对排序指标**使用,报告注明「相对贡献,非国民经济核算口径」。

## 7. 错配矩阵(`app/analysis/industry_gap.py`)

输入:规划产业(来自 doc_insights kind=industry,含 plan_role)+ industry_data + enterprise_industry 归类计数。

```
对每个规划支柱产业:
  actual_share   = 该产业营收(或从业) ÷ 全行业总和
  actual_growth  = 2016-2024 增速(若有时序)
  actual_units   = 五经普该行业单位数
  enterprise_cnt = 该行业上市后备企业数
  判定:
    plan_role ∈ {支柱} 且 actual_share < 阈值(如营收占比 <5%) 且 growth < 平均 → 🔴 规划强/实际弱
    plan_role ∈ {支柱} 且 数据吻合 → ⚪ 一致
  反向:
    非规划产业但 actual_share 高 或 growth 高 → 🟢 沉默支柱
```

判定阈值配置化(默认:营收占比 <5% 为「弱」、增速高于重点产业中位数为「强」)。

输出 `gap` 结构:
```
[{industry, plan_role, actual_share, actual_growth, actual_units, enterprise_cnt,
  verdict: overpromised|matched|silent_pillar, evidence[]}]
```

## 8. 报告(新增第八章「实际产业结构与规划承诺错配」)

```
8. 实际产业结构 × 规划承诺错配
  8.1 实际产业结构(五经普 2023):分行业从业/营收 Top10 表
  8.2 重点产业时序(2016-2024):累计增速/CAGR/增长贡献率表
  8.3 上市后备企业行业分布:行业计数 + 与规划产业对照
  8.4 错配矩阵:🔴规划强实际弱 / 🟢沉默支柱 / ⚪一致,含 evidence
```

## 9. 文件与任务拆解预告

| 文件 | 职责 |
|------|------|
| `config/industry_sources.yaml` | 五经普+年鉴源注册表 |
| `app/parse/industry_classify.py` | 企业行业归类(规则+LLM 兜底) |
| `app/fetch/industry_documents.py` | 分行业数据采集器(复用 table 解析+iframe 穿透) |
| `app/store/db.py` | industry_data / enterprise_industry 表 |
| `app/store/repository.py` | 新表 CRUD |
| `app/analysis/industry_gap.py` | 增长贡献度 + 错配矩阵 |
| `app/analysis/report.py` | 第八章渲染 |
| `quanzhou.py` + `main.py` + web | CLI/API 接入 |
| `tests/` | test_industry_classify / test_industry_gap / test_industry_documents |

## 10. 风险与降级

| 风险 | 缓解 |
|------|------|
| 年鉴 iframe 嵌套导致表 8-7/8-8 URL 难定位 | 侦察已确认 index-cn.htm 可达;若穿透失败,回退五经普第一/二号(已足够错配分析) |
| 分行业税收/进出口不可得 | 已明确放弃,不硬造 |
| 企业归类歧义 | 特异性词典 + LLM 兜底 + unknown 标记;不强行归类 |
| 贡献率口径差(工业 vs GDP) | 报告注明「相对排序指标」 |
| 行业名口径不一致(规划 vs 普查 vs 年鉴) | 建立行业名别名字典对齐(如「纺织鞋服」=「纺织服装、服饰业」) |

---

## 11. 三驾马车拉动设计(消费/投资/出口)

### 11.1 数据源补充(侦察实测)

| 源 | URL | 形态 | 数据 |
|----|-----|------|------|
| C1 常住人口 | 年鉴表 3-4 `…/qztjnj2025/cn/html/0304_3-4.html` | HTML 表格 | 2000-2024 常住人口序列 + 城镇化率 |
| C2 收支 | 年鉴表 4-5~4-9 | HTML 表格 | 全体/城乡人均可支配收入、消费支出 8 大类、恩格尔系数历年 |
| C3 CPI | 年鉴表 5-2 `…/0502_5-2.html` | HTML 表格 | 1984-2024 历年 CPI 序列 |
| C4 进出口 | 年鉴表 12-3 `…/1203_12-3.html` | HTML 表格 | 历年出口/进口/净出口(人民币+美元) |
| C5 债务 | czj 政府债务栏 + 预决算平台(2019-2024 报告) | HTML/PDF | 债务余额/限额(全市+市本级) |
| C6 基建支出 | 决算草案 + 决算表 Excel(sjjsgk 栏) | HTML/Excel | 政府性基金、城乡社区/交通运输等基建支出 |
| C7 投资增速 | 2022-2025 统计公报 | HTML | 固定资产投资/基础设施投资/民间投资增速 |

### 11.2 数据模型

`industry_data` 表(§3.1)扩展 source 取值,统一承载所有分项数据:
- `population`(常住人口)/ `income`(可支配收入)/ `consumption`(消费支出)/ `cpi` / `trade`(进出口)/ `debt`(债务)/ `investment`(投资增速)

> 债务/收支等非「产业」数据复用 industry_data 有语义偏差。改用**通用指标表 `econ_series`**(见下),与 industry_data 分工:industry_data 专存分行业数据;econ_series 存宏观时间序列。

```sql
CREATE TABLE IF NOT EXISTS econ_series (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT,          -- yearbook_3_4 / yearbook_4_7 / yearbook_5_2 / yearbook_12_3 / debt_2024 / budget_2023 ...
  indicator TEXT,       -- population / urban_income / rural_income / consumption / engel / cpi / export / import / debt_balance / debt_limit / infra_invest ...
  year TEXT,
  value TEXT,
  unit TEXT,
  note TEXT,            -- 口径备注(如「全市CPI仅含市区」)
  raw_text TEXT,
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

### 11.3 消费支撑度计算(`app/analysis/consumption.py`)

| 指标 | 公式 | 输入 |
|------|------|------|
| 消费规模比 | 社零总额 ÷ GDP | econ_series(社零)+ data_values(GDP) |
| 消费-经济增速差 | 社零增速 − GDP 增速 | 跨年 |
| 人均可支配收入 | 全体/城镇/农村 | 表 4-5~4-9 |
| 消费倾向 | 人均消费支出 ÷ 人均可支配收入 | 表 4-7 |
| 恩格尔系数 | 食品烟酒支出 ÷ 消费支出 | 表 4-7 分项 + 公报 |
| CPI 水平与趋势 | 历年 CPI 序列(上年=100) | 表 5-2 |
| 城乡收入比 | 城镇收入 ÷ 农村收入 | 表 4-8/4-9 |
| 收入中位数 | **不可得** → 用城乡收入比 + 消费倾向作代理,报告显式标注 | — |

### 11.4 政府债务与投资拉动计算(`app/analysis/investment.py`)

| 指标 | 公式 | 输入 |
|------|------|------|
| 债务/GDP(政府杠杆) | 债务余额 ÷ GDP | debt_balance + GDP |
| 债务限额使用率 | 余额 ÷ 限额 | 债务报告 |
| 债务余额增速 | 2019→2024 复合增速 vs GDP 复合增速 | 债务序列 |
| 投资拉动 | 固定资产投资/基础设施投资增速 vs GDP 增速 | 公报增速 |
| 基建财政投入 | 政府性基金支出、城乡社区/交通运输支出 | 决算表 |

> 口径注明:①官方债务率不公布,余额/GDP 为自算;②投资仅有增速无绝对额,「投资对 GDP 拉动」用增速差近似,非核算口径;③一般/专项债分项附表未挂网,只有总量。

### 11.5 净出口拉动计算(`app/analysis/trade.py`)

| 指标 | 公式 | 输入 |
|------|------|------|
| 外贸依存度 | 出口额 ÷ GDP | 表 12-3 + GDP |
| 净出口 | 出口 − 进口 | 表 12-3 |
| 出口拉动 | 出口增速 vs GDP 增速 | 历年序列 |
| 结构 | 贸易方式/国别(可选) | 表 12-4/12-8 |

### 11.6 报告新增章节

```
9. 三驾马车拉动(代理口径,支出法 GDP 地市不核算,显式标注)
  9.1 消费:社零/GDP、消费倾向、恩格尔系数、CPI、城乡收入比(替代中位数)
  9.2 投资:政府债务/GDP、债务增速 vs GDP、基建财政支出、投资增速差
  9.3 净出口:外贸依存度、净出口、出口增速差
  9.4 口径与局限:支出法 GDP/收入中位数/一般专项债分项缺失说明
```

## 12. 文件与任务拆解(合并版)

| 文件 | 职责 |
|------|------|
| `config/industry_sources.yaml` | 五经普+年鉴表+债务+决算源注册表 |
| `app/parse/industry_classify.py` | 企业行业归类(规则+LLM 兜底) |
| `app/fetch/industry_documents.py` | 分行业+宏观序列采集(iframe 穿透+table 解析) |
| `app/store/db.py` | industry_data / econ_series / enterprise_industry 表 |
| `app/store/repository.py` | 新表 CRUD |
| `app/analysis/industry_gap.py` | 增长贡献度 + 错配矩阵 |
| `app/analysis/consumption.py` | 消费支撑度 |
| `app/analysis/investment.py` | 债务与投资拉动 |
| `app/analysis/trade.py` | 净出口拉动 |
| `app/analysis/report.py` | 第八、九章渲染 |
| `app/analysis/kami.py` | **Kami Parchment HTML 渲染器(统一视觉)** |
| `quanzhou.py` + `main.py` + web | CLI/API 接入 |
| `tests/` | test_industry_classify / test_industry_gap / test_consumption / test_investment / test_trade / test_industry_documents / test_kami |

## 12.5 报告 Kami Parchment 渲染规范(用户指定)

报告 HTML 采用 Kami Parchment Document 模板的视觉签名(**全篇唯一视觉风格,替换现有 quanzhou_profile 的朴素表格样式**)。规范来源 `~/.dsh/skills/tresearch/reference/kami-spec.md`。

### 硬约束(不可突破)

| 规则 | 值 |
|------|-----|
| 底色 | `#f5f4ed`(暖羊皮纸),禁 `#fff` |
| 正文色 | `#1f1d18`(近黑暖灰),禁 `#000` |
| 强调色 | `#1B365D`(墨蓝),全篇唯一彩色 |
| 中文正文 | `'Noto Serif SC', 'Source Han Serif SC', 'STSong', 'SimSun', serif` |
| 英文/数字 | `'Crimson Text', 'Georgia', serif`;数据等宽 `'JetBrains Mono', 'Consolas', monospace` |
| 标题字重 | 500,禁 700/800/900 |
| 正文行高 | 1.65;标题 1.2-1.3 |
| 板块分隔 | `border-bottom: 1px solid rgba(27,54,93,0.15)` |
| 错配标识 | 🔴→暗红文字 `#8b1a1a`(非色块)、🟢→暗绿 `#2d5016`、⚪→次级灰 |
| 阴影 | 仅 `box-shadow: 0 1px 3px rgba(0,0,0,0.06)` |

### 禁则

渐变背景、KPI 卡片、大 emoji 图标、圆角>2px、彩色徽章、hero 大图、仪表盘布局。

### 结构

```html
<article>
  <header><p class="report-type">泉州经济驱动画像</p><h1>…</h1><p class="date-line">…</p></header>
  <section id="…"><h2>…</h2>…</section>
  …
  <footer><p>数据来源…</p><p>口径与局限…</p></footer>
</article>
```

### 实现

- `app/analysis/kami.py`:`KamiRenderer` 类,提供 `doc(title, report_type, date_line)` 上下文 + `section(title)` + `table(headers, rows, align_right_cols)` + `source(url, name, date)` + `bullish/bearish span` + `note_limited`。
- `render_quanzhou_html(profile)` 改为调 KamiRenderer,产出完整独立 HTML(内联 CSS,无外部依赖;Noto Serif SC 用系统回退栈,不引 CDN)。
- 报告内可跳转:每个 section 加 `id`,`header` 下加章节目录 `<nav>`(纯文本锚点链接,墨蓝色),点击跳转对应章节。

### 测试(`tests/test_kami.py`)

- 底色/字体/墨蓝在渲染输出中出现
- 表格右对齐列、来源链接、错配三色 span
- 目录锚点与 section id 对应
- 无 `#fff`/`#000`/`gradient`/`border-radius` 超过 2px

## 13. 风险与降级(合并)

| 风险 | 缓解 |
|------|------|
| 年鉴 iframe 嵌套导致表 URL 难定位 | index-cn.htm 已确认可达;失败回退五经普+公报 |
| 支出法 GDP/收入中位数/分项债务不可得 | 代理指标 + 报告显式标注,不冒充核算口径 |
| 企业归类歧义 | 特异性词典 + LLM 兜底 + unknown 标记 |
| 行业名口径不一致 | 行业名别名字典对齐 |
| 贡献率口径差(工业 vs GDP、社零 vs GDP) | 报告注明「相对/代理指标」 |
