# M8 设计:分析决策树引擎(把方法论变成代码)

> 依据:`docs/methodology/ANALYSIS_DECISION_TREE.md`(已交付的方法论决策树)
> 关联修复:审查报告 A10(时序取数错位——消费写死 2025、贸易取最早年份、债务/GDP 跨年)
> 状态:**设计待批准**(批准前不写代码)

---

## 1. 目标与边界

**目标**:把决策树文档的判定逻辑实现为可执行模块——给定 repo(与 region),自动产出 **T0-T5 节点裁决 + 缺口清单 + 待核验项 + 口径标注**;并集成到 Kami 经济画像报告(第六章「方法论体检」)、CLI 与 JSON API,使「分析过程本身」可被审查与迭代。

**不做(YAGNI)**:不做自动结论生成/自然语言报告;不做新前端页面;不重建已有分析函数(错配矩阵/规则校验照旧复用);不 OCR/不外接新数据。

**verdict 语义**(全部节点统一):
| verdict | 含义 | 触发示例 |
|---|---|---|
| `ok` | 确定性规则通过 | 三产恒等式偏差 ≤1% |
| `flag` | 确定性规则越线(红灯存疑) | 弹性 ∉[0.5,2]、土地依赖 >40% |
| `verify` | 需人工复核(批判双层/口径/跨期) | escalated 非空、2026 预算行被引用面 |
| `na` | 数据不足——走缺口清单,不下判断 | 无 CPI、无两年序列 |
| `info` | 展示性判读,不设好坏 | 社零/GDP、恩格尔、出口依存度 |

**贯穿原则**:错>缺(na 带缺口说明而非猜测);规则才 flag,经济学解释只 info/note;每条 evidence 携带 指标/年份/数值。

---

## 2. 节点规格(引擎将裁决的全部节点)

数据源一律 **caliber='final'**(预算口径不进树),econ_series 取当年最新;缺数据 → `na` 并进入 `missing` 清单。

### T0 可信门
| ID | 问题 | 判定 | 数据 |
|---|---|---|---|
| T0-1 口径污染 | region 内存在 budget 行且影响本树所用指标? | 受影响指标列表>0 → `verify` | data_values(caliber=budget) |
| T0-2 核心指标缺口 | final 口径下必备指标集缺失项 | 缺项→`na` + missing 明细 | 必备集:地区生产总值、一/二/三产、一般公共预算收入/支出、政府性基金收入、税收收入、常住人口、社零(每项存在性) |
| T0-3 双层批判 | rule flag 与 LLM high 同主题升级 | escalated>0 → `verify`(列 subject) | merge_checks 输出 |

### T1 增长质量
| ID | 问题 | 判定 | 数据 |
|---|---|---|---|
| T1-1 突变 | GDP 相邻两年名义增速绝对值>30% | `flag`;否则 `ok` | 两年 final GDP |
| T1-2 名义/实际 | 同年 CPI(上年=100)可得? | 得 → `info` 实际增速=(1+名义)/(1+CPI)−1;不得 → `na`(note 名义口径风险) | GDP + econ_series(cpi) |

### T2 结构
| ID | 问题 | 判定 | 数据 |
|---|---|---|---|
| T2-1 三产恒等式 | C2 校验 | 复用 rule_checks C2(ok/flag) | 三产+GDP 同年 |
| T2-2 结构迁移 | 三产份额相邻年变化幅度 | |Δ|>3pct → `info`+note(需企业/就业互证,无互证不下 flag);否则 `ok` | GDP/三产两年 |
| T2-3 错配疑点 | overpromised 条目中 actual_share 为 None 的比例 | 存在 share=None 的 overpromised → `verify`(数据缺失可能被当弱);否则 `info`(给分布) | industry_gap 结果 |

### T3 需求侧
| ID | 问题 | 判定 | 数据 |
|---|---|---|---|
| T3-1 消费 | 消费倾向/恩格尔/社零比(同年) | 数据足 → `info` + 倾向年际变化>10pct → `verify`;不足 → `na` | income/spending/food 序列 + retail + GDP |
| T3-2 财政自生 | 自给率=收入/支出 | <60% → `flag`(note 转移支付依赖);≥60 → `ok` | final 收入/支出同年 |
| T3-3 土地依赖 | C6 | 复用 rule_checks C6(>40 flag) | 收入+基金同年 |
| T3-4 债务空间 | 限额利用率、债务/GDP(同年) | 利用率>90% → `flag`;债务/GDP `info`(马约 60% 仅参考,note 地方口径不可直接比) | econ_series(debt_balance/limit)+GDP |
| T3-5 外需敞口 | 出口依存度与出口增速 | 依存>20% 且出口负增 → `flag`;否则 `info` | econ_series(trade 同年)+GDP |

### T4 分配
| ID | 问题 | 判定 | 数据 |
|---|---|---|---|
| T4-1 就业背离 | C7 | 复用 rule_checks C7 | 新增就业两年+GDP 两年 |
| T4-2 收入弹性 | C5 | 复用 rule_checks C5 | 收入两年+GDP 两年 |
| T4-3 人均化 | 人均 GDP 增速 = 名义差人口 | `info`(给人均增速与人口增速;总量正+人口负 → note 总量叙事风险) | GDP 两年+常住人口两年 |

### T5 承诺
| ID | 问题 | 判定 | 数据 |
|---|---|---|---|
| T5-1 目标 gap | 规划 GDP 目标 vs 实际外推(近两年增速均值) | 目标>外推×1.5 → `verify`;目标缺失 → `na` | plan_goal insights(region) + GDP |
| T5-2 跨期混搭 | 库中 plan_goal 的 period 数>1 | `verify`(防跨文档拼目标);否则 `ok` | plan_goal insights |

## 3. 顺带修复(用户已批准):时序取数 A10

1. **consumption.py**:`consumption_support(repo)` 改为取**最新可用同一年**的 income/spending/food(原 `_series` 各取各最新 → 年份错位;`_dv` 写死 year="2025")。函数返回值新增 `years`(各子指标年份)。
2. **trade.py**:`trade_support` 改为找**出口与进口同年同时存在**的最大年份(原取第一个 → 命中最早年份如 1984);无同年对时 net_export=None 并 note。返回新增 `year`。
3. **investment.py**:debt 年份与 GDP 分母绑定同年(原 debt 最新 2024 底 ÷ GDP 最新 2025);返回新增 `debt_year/gdp_year`,跨年时 note 标注。
4. **economy_report.py**:三驾马车三节表格的「口径」标签由写死字符串改为数据实际年份(cons/inv/trd 返回的 year),消除「1984 标注 2024」类失真。

## 4. 新模块与集成

```
app/analysis/decision_tree.py   # 核心:tree_audit(repo, region="泉州市") -> dict
  {nodes: [ {id, layer, question, verdict, evidence, note, threshold?} ],
   missing: [指标名…], verify: [说明…], summary: {ok,flag,verify,na,info 计数}}
  # 复用:rule_checks/merge_checks(经 analyze_quanzhou 的 credibility)、industry_gap、
  #       consumption_support/investment_support/trade_support(修复后)
```

集成:
- **报告**:`economy_report.py` 末尾新增 `r.section("sec-tree","六、方法论体检")` + 节点表(节点/裁决/问题/证据/说明);全 na 时 `note_limited` 提示先采集。
- **CLI**:`quanzhou.py --tree` 打印裁决简表(复用 economy 渲染的树部分,或打印 JSON 摘要)。实现:先 `render_economy_report`?为避免重复采集,`--tree` 只做分析(不采集):`repo → tree_audit → 终端打印`。
- **API**:`/api/quanzhou/tree` → JSON(tree_audit 结果)。

## 5. 测试策略(TDD,先红后绿)

新 `tests/test_decision_tree.py`:
- 种子 final 齐全库 → T0-2 无缺失、T2-1 ok、T3-2 按自给率裁决、T3-3 C6 联动;
- 种子缺 CPI/两年序列 → 对应节点 `na` 且 missing 明细含指标;
- 种子 budget 行(2026)→ T0-1 `verify` 且列指标;
- 种子 escalated(规则 flag + 高置信批判同主题)→ T0-3 `verify`;
- seed overpromised + share=None → T2-3 `verify`;share 有值 → 不 verify;
- plan_goal 两个 period → T5-2 `verify`;目标 vs 外推 → T5-1;
- 空库 → 全 na 不抛异常。
`tests/test_drivers.py`(或所在文件)修正:
- trade 同年最新回归(seed 1980/2024 序列 → 取 2024 而非 1980;无同年对 → net_export None);
- consumption 年份对齐(income 2024、spending 2025 → propensity 用 2024 或 na?设计:倾向要求同年,不同年 → propensity=None+note。seed 同年 → 正常);
- investment 同年绑定。
`tests/test_kami.py`/economy 冒烟:render_economy_report 含「六、方法论体检」且空库不炸。
全量回归:现有 206 必须全绿(consumption/trade 行为变化 → 旧断言适配点逐一列出并在计划中写清)。

## 6. 风险与兼容

- consumption_support/trade_support/investment_support 返回 dict 新增字段(不破坏既有键),economy_report 标签动态化;
- 旧测试若断言固定年份口径标签 → 适配为数据驱动;
- decision_tree 全部只读 repo,无迁移、无写库;
- 树阈值与文档 §3 一致,注释标原理 P1-P6。

## 7. 交付物

`app/analysis/decision_tree.py`、consumption/trade/investment/economy_report 小修、`quanzhou.py --tree`、`main.py` API、测试、PROGRESS/决策树文档关联更新;本地 commit + MCP 推送。
