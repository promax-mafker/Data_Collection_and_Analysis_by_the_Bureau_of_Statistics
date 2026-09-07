# M6 泉州经济驱动画像 · 实现计划

> 对应 `docs/DESIGN_M6_INDUSTRY_GAP.md`(已批准)。执行方式:内联执行(模块耦合,串行),每批(产业结构/消费/投资/出口)独立测试+提交。
> 纪律:TDD 先红后绿;每任务提交;全绿才进下一步。

## 0. 前置事实(实测确认)

- 年鉴表 URL 全部验证 200(需 `verify=False`,站点证书自签名):
  - 3-4 人口 `…/qztjnj2025/cn/html/0304_3-4.html`
  - 4-7 收支 `…/0407_4-7.html`(全体居民人均收支)
  - 5-2 CPI `…/0502_5-2.html`
  - 8-7 工业经济 `…/0807_规模以上工业主要经济指标（2024年）.html`
  - 8-8 重点产业 `…/0808_9-7.html`(**双列头表**:每年两列=企业单位数+工业增加值增长,2016-2024)
  - 12-3 进出口 `…/1203_12-3.html`
- 五经普第一号 `tjj.quanzhou.gov.cn/tjzl/tjgb/202505/t20250512_3168240.htm`、第二号 `…_3168260.htm`
- 债务报告 2019-2024:czj 政府债务栏 + jsgkpt(URL 见侦察笔记 recon/)
- `HttpClient` 需支持 `verify=False`(年鉴站证书问题)→ 加参数 `verify` 默认 True,采集合规允许 False

## 1. 数据模型(`app/store/db.py`)+ 迁移

新表(幂等 `CREATE TABLE IF NOT EXISTS`,旧库 init_db 自动建):

```sql
CREATE TABLE IF NOT EXISTS industry_data (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, industry TEXT, year TEXT, metric TEXT,
  value TEXT, unit TEXT, raw_text TEXT,
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS econ_series (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, indicator TEXT, year TEXT, value TEXT, unit TEXT, note TEXT, raw_text TEXT,
  extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS enterprise_industry (
  enterprise_id INTEGER PRIMARY KEY,
  industry TEXT, method TEXT
);
```

测试 `tests/test_db.py` 扩展:新表存在且列齐全、幂等。

## 2. Repository 扩展(`app/store/repository.py`)

| 方法 | 行为 |
|------|------|
| `replace_industry_data(source, rows)` | 先 DELETE 该 source 再插入 rows(dict: industry/year/metric/value/unit/raw_text) |
| `list_industry_data(source=None, industry=None, metric=None)` | 过滤查询 |
| `replace_econ_series(source, rows)` | 先 DELETE 该 source 再插入 |
| `list_econ_series(indicator=None, source=None)` | 过滤查询,按 year 排序 |
| `replace_enterprise_industry(rows)` | rows: dict(enterprise_id, industry, method),整表 upsert |
| `list_enterprise_industry()` | 全量 |

测试 `tests/test_store.py` 扩展:CRUD + replace 去重(重复 replace 不累积)。

## 3. HttpClient 加 verify 参数

`app/fetch/client.py`:构造函数加 `verify=True`,`requests.get` 传 `verify=self.verify`。测试:monkeypatch 断言传递。

## 4. 源注册表 `config/industry_sources.yaml`

结构(全部 URL 实测):

```yaml
region: 泉州市
census:
  - id: census1
    url: https://tjj.quanzhou.gov.cn/tjzl/tjgb/202505/t20250512_3168240.htm
    tables: [table1_2, table1_3, table1_4]
  - id: census2
    url: https://tjj.quanzhou.gov.cn/tjzl/tjgb/202505/t20250512_3168260.htm
    tables: [table2_2, table2_3]
yearbook_base: https://tjj.quanzhou.gov.cn/tsys/UpLoadFiles/43sjfb/129ndsj/qztjnj2025/
yearbook_tables:
  - id: pop_3_4
    path: cn/html/0304_3-4.html
    indicator: population
  - id: income_4_7
    path: cn/html/0407_4-7.html
    indicator: income_consumption
  - id: cpi_5_2
    path: cn/html/0502_5-2.html
    indicator: cpi
  - id: industry_8_7
    path: cn/html/0807_规模以上工业主要经济指标（2024年）.html
    indicator: industry_detail
  - id: industry_8_8
    path: cn/html/0808_9-7.html
    indicator: key_industry_ts
    dual_header: true
  - id: trade_12_3
    path: cn/html/1203_12-3.html
    indicator: trade
debt:
  - {id: debt_2024, url: https://czj.quanzhou.gov.cn/ztzl/zfzw/202503/t20250312_3147982.htm, year: "2024"}
  - {id: debt_2023, url: https://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/202402/t20240218_3005325.htm, year: "2023"}
  - {id: debt_2022, url: http://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/202302/P020241106328780062391.pdf, year: "2022", kind: pdf}
  - {id: debt_2021, url: https://quanzhou.gov.cn/zfb/xxgk/ztxxgk/czzj/zfzw/202201/t20220129_2693380.htm, year: "2021"}
```

## 5. 表格→结构化解析器(`app/parse/series_table.py`)

针对年鉴 HTML 表,通用解析:

```python
def parse_series_table(html, mode) -> list[dict]:
    """mode: single_header(标准表: 首列行业/年份, 其余列为年度数值)
            dual_header(双列头: 每年两列, 需按列头循环展开)
    返回 [{year, metric, industry(可空), value, unit, raw_text}]"""
```

测试 `tests/test_series_table.py`:
- 单表头:表 3-4 人口 → 逐年 population 序列
- 双表头:8-8 重点产业 → 展开为 (industry, year, metric∈{企业单位数,工业增加值增长}, value)
- 空表/多表/单元格清理

## 6. 企业行业归类(`app/parse/industry_classify.py`)

```python
INDUSTRY_KEYWORDS = [  # (行业, [关键词]) 特异性优先
    ("纺织鞋服", ["纺织", "制衣", "鞋", "服装", "纤维", "皮革", "皮业", "服饰"]),
    ("机械装备", ["机械", "智能装备", "机电", "汽配", "汽车", "模具"]),
    ("电子信息", ["电子", "通信", "通讯", "光电", "半导体", "物联网"]),
    ("石油化工", ["石化", "化工", "燃气"]),
    ("健康食品", ["食品", "茶业", "水产", "饮料"]),
    ("建材家居", ["建材", "陶瓷", "卫浴", "石材", "家居"]),
    ("卫生用品", ["卫生用品", "妇幼", "纸业"]),
    ("新材料", ["新材料", "材料科技", "纤维制品"]),
    ("金融", ["银行", "融资租赁", "小额贷款", "供应链"]),
    ("环保公用", ["环保", "供水", "水务"]),
    ("建筑园林", ["建设", "园林", "城市规划"]),
]
def classify(name) -> (industry, method)   # rule / unknown
```

`method=unknown` 的走 LLM 兜底(批量一次,输入企业名列表 → 返回 {name: industry})。
测试:已知企业名(恒安集团→卫生用品、泉州银行→金融、卡尔美→纺织鞋服…)断言正确;unknown 标记。

## 7. 采集编排(`app/fetch/industry_documents.py`)

```python
def run_industry_sources(client, repo, sources_cfg, llm_client=None) -> dict:
    """采集 census + yearbook_tables + debt → industry_data / econ_series。
    返回 {pages, series, industry_rows, enterprises, errors}。
    逐源 try/except 隔离;table 页走 series_table 解析;债务 HTML/PDF 走规则正则。"""
```

- 五经普:HTML 表格 → industry_data(metric: units/employees/revenue)
- 年鉴表:series_table → econ_series 或 industry_data(8-7/8-8 属分行业)
- 债务:正则抽「余额/限额」→ econ_series(debt_balance/debt_limit)
- 企业归类:读 enterprises 表 → classify → enterprise_industry

测试 `tests/test_industry_documents.py`:FakeClient 返回 fixture HTML → 断言分表解析与入库计数、债务正则、企业归类 ≥80% rule 命中。

## 8. 分析:错配 + 增长贡献(`app/analysis/industry_gap.py`)

```python
def growth_contribution(repo) -> dict:
    """重点产业 2016-2024 增量贡献率(工业口径,标注相对) + CAGR + 累计增速。"""
def industry_gap(repo, thresholds=None) -> list:
    """规划产业(doc_insights industry) × industry_data × enterprise_industry → 错配矩阵。
    thresholds 默认: weak_share=5.0, strong_share=10.0。"""
```

测试 `tests/test_industry_gap.py`:构造假 industry_data + 规划产业 + 企业归类 → 断言 verdict(overpromised/matched/silent_pillar)与贡献率数值。

## 9. 分析:三驾马车

`app/analysis/consumption.py`:
```python
def consumption_support(repo) -> dict:
    # 社零/GDP、社零增速-GDP增速、消费倾向(消费÷收入)、恩格尔系数、CPI序列、城乡收入比
```
`app/analysis/investment.py`:
```python
def investment_support(repo) -> dict:
    # 债务/GDP、债务限额使用率、债务增速vs GDP增速、投资增速差、基建支出
```
`app/analysis/trade.py`:
```python
def trade_support(repo) -> dict:
    # 外贸依存度(出口/GDP)、净出口、出口增速差
```

测试 `tests/test_consumption.py` / `test_investment.py` / `test_trade.py`:构造假 econ_series + data_values → 断言各指标数值、None 不编造。

## 10. 报告渲染(`app/analysis/report.py`)+ CLI

新增 `render_industry_markdown/profile` 与 `render_drivers_markdown/profile`,合入泉州画像第八、九章:
- 第八章 实际产业结构错配(§8.1-8.4)
- 第九章 三驾马车拉动(§9.1-9.4,含口径声明)

CLI:`quanzhou.py` 增加 `--industry` 子命令(只采 M6 源)与 `--drivers`(三驾马车)。或统一 `quanzhou.py` 全量。报告 `data/reports/quanzhou_profile.md/html` 追加章节。

测试 `tests/test_quanzhou_report.py` 扩展:新章节标题与关键数字渲染。

## 11. API/Web

`app/main.py` 增加 `/api/quanzhou/industry/run`(采集 M6 源)与 status 扩展(industry_data/econ_series/enterprise_industry 计数)。Web 泉州 Tab 增加「采集产业结构与三驾马车」按钮。

## 12. 真实端到端(网络)

1. 全量 pytest 绿。
2. 停 Web → `python quanzhou.py --industry --drivers`(或合并入口)采 M6 源。
3. 验证:industry_data 行数(五经普+年鉴)、econ_series(人口/CPI/收支/进出口/债务)、enterprise_industry 170 条、报告八/九章渲染。
4. 抽样核对:8-8 重点产业数值 vs 源表;债务余额 2661.16 vs 2024 报告;出口 1651.70 vs 公报。
5. 重启 Web。

## 13. 收尾

PROGRESS 更新(M6 里程碑+证据);分多次 commit(feat: …);MCP 推送;汇报。

## 自检

- [x] 规格覆盖:四块(错配/消费/投资/出口)+ 采集+归类+分析+报告+Web
- [x] 无占位符:URL/表号/函数/测试名具体
- [x] 类型一致:industry_data vs econ_series 分工明确
- [x] 降级明确:中位数/支出法 GDP/分项债务缺失 → 代理+标注
- [x] 分批可交付:1-7 数据层,8 错配,9 三驾马车,10-13 交付
