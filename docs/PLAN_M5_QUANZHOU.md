# M5 泉州经济纵深画像 · 实现计划

> 对应 `docs/DESIGN_M5_QUANZHOU.md`(已批准)。执行方式:内联执行(模块耦合紧密,串行),每 3 任务批量检查点。
> 纪律:TDD——每个功能先写失败测试再实现;每任务提交一次;全绿才进下一步。

## 0. 环境与依赖

- venv:`.venv`(已有)。新增依赖 `python-dotenv`(读 .env)。
- 安装命令:`pip install python-dotenv` 并写入 `requirements.txt`。
- LLM 配置 `.env` 已就绪(qwen3.8-flash)。

## 1. 数据模型扩展(`app/store/db.py`)

### 1.1 pages 表加列 doc_category + 迁移

现有库已存在(stats.db / 测试库),`CREATE TABLE IF NOT EXISTS` 不会给旧表加列 → 需**幂等迁移**:`init_db()` 后检查 `PRAGMA table_info(pages)`,缺 `doc_category` 则 `ALTER TABLE pages ADD COLUMN doc_category TEXT NOT NULL DEFAULT 'bulletin'`。

取值:`bulletin | plan | gov_report | budget | enterprise`(既有 rows 默认 bulletin,与 M1-M4 行为一致)。

### 1.2 新表 doc_insights(LLM/结构化解读)

```sql
CREATE TABLE IF NOT EXISTS doc_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER,
  source_id TEXT,
  kind TEXT,              -- plan_goal / industry / fiscal_signal / employment / critique / narrative
  title TEXT,
  body TEXT,              -- 结构化 JSON
  method TEXT DEFAULT 'llm',
  created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### 1.3 新表 enterprises(企业名录)

```sql
CREATE TABLE IF NOT EXISTS enterprises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id INTEGER,
  year TEXT,
  list_type TEXT,         -- 上市后备 / 挂牌后备
  name TEXT,
  county TEXT,
  rank TEXT
);
```

### 1.4 测试 `tests/test_db.py`

- 对**旧 schema 库**(手动建 5 张旧表)执行 `init_db` → `doc_category` 列存在且旧行默认 `bulletin`。
- 新表创建幂等(两次 init_db 不报错)。

## 2. Repository 扩展(`app/store/repository.py`)

新增方法(全部带测试 `tests/test_store.py` 扩展):

| 方法 | 行为 |
|------|------|
| `upsert_page(p)` | 现有实现,Page 增加 `doc_category` 字段透传(改 schemas.py 加字段,默认 "bulletin") |
| `list_pages(doc_category=None, source=None)` | 按文档类过滤 |
| `insert_doc_insights(items)` | items: list[dict(page_id, source_id, kind, title, body, method)];body 已 JSON 字符串 |
| `replace_doc_insights(page_id, items)` | 先 DELETE 该页再插入(与 replace_page_values 同策略) |
| `list_doc_insights(page_id=None, kind=None)` | 过滤查询,body 保持 str |
| `replace_enterprises(page_id, rows)` | 先 DELETE 该页再插入 rows |
| `list_enterprises(year=None, list_type=None)` | 过滤查询 |

schemas.py:Page 加 `doc_category: str = "bulletin"` 字段(置于 dataset_type 后)。

## 3. 源注册表 `config/quanzhou_sources.yaml`

结构(全部 URL 侦察实测,不要改动):

```yaml
region: 泉州市
sources:
  - id: plan_15
    name: 十五五规划纲要
    category: plan
    url: https://www.quanzhou.gov.cn/zfb/xxgk/zfxxgkzl/zfxxgkml/srmzfxxgkml/ghjh/202605/P020260609588315746018.pdf
    kind: pdf
    period: "2026"
    parse: llm
    chunks: [产业体系, 民营经济, 财政, 就业, 民生]   # 送 LLM 的章节关键词(截取)
    parse_all: true                                  # 全文入库,LLM 按 chunk 抽取
  - id: gov_report_2026
    name: 2026年泉州市政府工作报告
    category: gov_report
    url: https://www.quanzhou.gov.cn/zfb/xxgk/zfxxgkzl/bgzj/zfgzbg/202603/t20260310_3273077.htm
    kind: html
    period: "2026"
    parse: llm
    chunk: auto                                        # 全文一次送入
  - id: budget_2026
    name: 2026年市本级预算报告
    category: budget
    url: https://czj.quanzhou.gov.cn/ztzl/jsgkpt/sjys/202604/t20260430_3287941.htm
    kind: html
    period: "2026"
    parse: rule+llm
    numeric_rules: [地方一般公共预算收入, 税收收入, 非税收入]   # 数值正则跑全文
  - id: execution_h1_2026
    name: 2026年上半年预算执行情况
    category: budget
    url: https://czj.quanzhou.gov.cn/zwgk/zfxxgk/fdzdgknr/czysjsbg/202607/t20260715_3309416.htm
    kind: html
    period: "2026"
    parse: rule
    numeric_rules: [一般公共预算收入, 税收收入, 政府性基金收入]
  - id: enterprises_2025
    name: 2025年度市级上市和挂牌后备企业名单
    category: enterprise
    url: https://www.quanzhou.gov.cn/zfb/xxgk/zfxxgkzl/qzdt/qzyw/202510/t20251015_3218492.htm
    kind: html
    period: "2025"
    parse: table
  - id: bulletin_2025
    name: 2025年泉州市国民经济和社会发展统计公报
    category: bulletin
    url: http://tjj.quanzhou.gov.cn/tjzl/tjgb/202603/t20260331_3279584.htm
    kind: html
    period: "2025"
    parse: rule
```

规则:
- `category` = pages.doc_category。
- `parse` ∈ `rule | llm | rule+llm | table`。
- 同一源同 URL 重复运行 → 走 content_hash 去重 + upsert 刷新(现有机制)。
- 数值抽取统一走 `RuleExtractor` 新方法 `extract_named(content_text, names, meta)`(只跑指定指标名,见任务 5)。

测试:加载 YAML 校验结构(字段齐全、URL 以 http 开头)。

## 4. HTML 表格解析器(`app/parse/table.py`) + tests/test_table.py

```python
def extract_table_records(html: str) -> list[list[str]]:
    """提取页面中所有 <table> 的行记录（去表头），返回二维列表。"""
```

测试(fixture html):单表 / 多表 / 空 / 单元格含链接与换行清理。

## 5. RuleExtractor 扩展:按指标名抽取 + 财政数值规则

`app/extract/rule_extractor.py` 新增:

```python
def extract_named(self, content_text, names, meta):
    """只对指定指标名(列表)跑规则,用于预算执行等数值页。
    复用 self._run(content_text, [r for r in rules if r["name"] in names], meta)。"""
```

`config/extract_rules.yaml` 增补财政类指标(供 budget 源使用):
- 地方一般公共预算收入(已覆盖:一般公共预算收入 模式含「地方」前缀可选,确认)
- 税收收入 / 非税收入 / 政府性基金收入 / 一般公共预算支出
- 城镇新增就业 / 城镇登记失业率

> 注意:报表口径含「完成年初预算的 X%」「同比增长 X%」等,规则只抽绝对数,增速另列指标名(如「一般公共预算收入增速」)由 LLM 或人工处理。

测试:构造含「税收收入 204.02 亿元」等的文本,断言抽取正确且不含百分比误配。

## 6. LLM 客户端(`app/extract/llm_client.py`) + tests/test_llm_client.py

```python
def load_env(): ...
class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None):  # 缺省读 .env
    @property
    def enabled(self) -> bool                       # key 缺失 → False
    def complete_json(self, system: str, user: str, temperature=0.2) -> dict:
        """POST chat/completions,要求输出 JSON;返回解析后的 dict。
        非 200 / 解析失败 → 抛 LLMError(带原始响应截断)。"""
```

- 请求体:`{"model", "messages":[{role,content}...], "temperature", "response_format": {"type": "json_object"}}`(千问兼容模式支持 json_object;若不支持则回落纯文本再剥离 ```json 围栏)。
- 测试用**假 HTTP 服务器**(`http.server` 线程)或 monkeypatch requests:验证请求构造、JSON 解析、错误路径、enabled=False。
- 千问模型名 `qwen3.8-flash` 已在 .env;单测不真正联网。

## 7. LLM 抽取器(`app/extract/llm_extractor.py` 落地)+ tests/test_llm_extractor.py

替换占位实现。接口沿用 `Extractor` 但按 M5 语义扩展:

```python
class LLMExtractor(Extractor):
    def __init__(self, client=None, enabled=None): ...
    def extract(self, content_text, meta, rules):   # 兼容接口:返回 DataValue 列表(数值型提示词,一般不用)
    def extract_insights(self, page, source, client) -> list[dict]:
        """按 source['category'] 选择 schema 与分块,产出 doc_insights 行。
        plan/gov_report → industry / plan_goal / employment / fiscal_signal
        budget          → fiscal_signal
        每 kind 一次 LLM 调用;超长文本按 chunks 切分分别调用再合并。"""
```

提示词常量(取自 DESIGN §5.2,写全量中文,含 evidence / 禁编数据 / JSON-only):
- `SYSTEM_EXTRACT`(经济学家改写,去官方口吻)
- `SYSTEM_CRITIQUE`(批判审读,spin/omission/metric_game/gap + confidence + external_claim)

meta 扩展:`page_id / bureau_id / region / year / source_id`。

测试:monkeypatch `LLMClient.complete_json` 返回固定 dict → 断言 insights 行组装正确(字段映射、method="llm")。不联网。

## 8. 批判审读器(`app/extract/critique.py`) + tests/test_critique.py

```python
def rule_checks(values_by_indicator: dict) -> list[dict]:
    """C1-C7 确定性校验(见 DESIGN §5.5)。输入:指标名→[(year, value_float)]。
    输出 check 记录 {id, subject, year, verdict: ok|flag, severity, note}。
    C2 恒等式: 一产+二产+三产 vs GDP(偏差>1% flag)
    C3 跨年突变: 相邻年 |Δ|>30% flag
    C4 目标现实差: 报告目标 vs 实际(缺同口径数据 → 返回 med '需跨年数据')
    C5 弹性: 收入增速/GDP增速 不在 [0.5,2] flag
    C6 土地依赖: 政府性基金/(一般公共预算+基金) 无逐年 → 只算当期 + 趋势占位
    C7 就业经济背离: 就业增速 vs GDP 增速(数据不足 → med 提示)

def llm_critique(text: str, client) -> list[dict]:
    """SYSTEM_CRITIQUE 一次调用 → critiques[] 规范化。"""

def merge_checks(checks, critiques) -> dict:
    """双层命中升级;输出 {checks, critiques, escalated}。"""
```

测试(纯函数,不联网):C2 构造 一产+二产+三产=GDP±0.5% → ok;±3% → flag high;C5 弹性 0.3 → flag;merge 双层命中 severity 升一级。

## 9. 文档采集编排(`app/fetch/documents.py`) + tests/test_documents.py

```python
def run_documents(client, repo, sources, rules, llm_client=None) -> dict:
    """按注册表逐源采集入库。返回 {pages, values, insights, enterprises, errors}。

    流程(每源 try/except 隔离):
      1) kind==pdf → extract_pdf_text(client.download(url));否则 decode+extract_text
      2) 空内容 → 记 errors 跳过
      3) year = source['period']; content_hash 去重/upsert
      4) parse 分支:
         rule        → RuleExtractor().extract_named(text, numeric_rules, meta) → replace_page_values
         rule+llm    → 同上 + llm
         llm         → LLMExtractor().extract_insights(page, source, llm_client) → replace_doc_insights
         table       → extract_table_records(html) → 简单列名推断 → replace_enterprises
      5) Page(doc_category=source['category']) 入库
    """
```

企业名单 county 推断:表格列含「县(市、区)」列直接取;否则按行内已知县名(晋江/石狮/南安/惠安/安溪/永春/德化/鲤城/丰泽/洛江/泉港)子串匹配。

测试:FakeClient(返回 fixture html/pdf)+ 临时库 → 断言 pages/doc_insights/enterprises 计数与分类。断言 rule+llm 源在 `llm_client=None` 时跳过 llm 分支但数值照入库。

## 10. 泉州分析模块(`app/analysis/quanzhou.py`) + tests/test_quanzhou_analysis.py

```python
def analyze_quanzhou(repo) -> dict:
    """输入 data_values+enterprises+doc_insights → 画像 dict(见 DESIGN §6)。
    fiscal:   财政强度/自给率/土地依赖/收入结构(缺失指标 → None 不编造)
    industry: doc_insights kind=industry 的条目计数/政策密度/evidence 清单
    market:   企业 county HHI + Top3 + 年度对比
    employment: 新增就业密度(需常住人口,缺则 None)/目标达成
    plan:     doc_insights kind=plan_goal 数值 + 分析层增速可行性
    credibility: rule_checks + critiques + escalated 汇总
    所有数值带 sources[] 溯源(指标+年份)。"""
```

HHI:`sum((n_i/N)^2)`,范围 0-1。

测试:构造含 财政指标 data_values(592.07/880.29/292.07)+ enterprises(晋江×5、石狮×2…)+ 假 insights → 断言各数值与 HHI 正确、None 不编造。

## 11. 报告渲染扩展(`app/analysis/report.py`) + 画像 CLI

新增:

```python
def render_quanzhou_markdown(profile: dict) -> str
def render_quanzhou_html(profile: dict) -> str    # 七章结构(DESIGN §7),第六章审读表,⚠ 样式
def write_quanzhou_report(out_dir, profile, md, html) -> str
```

CLI:`run.py quanzhou [--sources-only]`(只采不分析)与 `run.py quanzhou`(采+析+渲染),输出 `data/reports/quanzhou_profile.html/md`。

测试:假 profile dict → 断言渲染包含各章标题与关键数字(如「592.07」)与 ⚠ 标记。

## 12. API + Web(`app/main.py` + static)

- `POST /api/quanzhou/run` → 执行采集(需要时)+ 分析,返回 run 摘要。
- `GET /api/quanzhou/report?format=md|html` → 渲染画像(若未生成先分析)。
- `GET /api/quanzhou/status` → 已入库源计数 / insights 计数 / LLM 启用状态。
- 前端:index.html 顶部 Tab 切换「全省横比 / 泉州画像」,画像 Tab 内嵌 iframe(报告)+「采集并分析」按钮 + 状态行。

测试:FastAPI TestClient 冒烟(GET status 200)。

## 13. 真实端到端验证(网络,最后执行)

1. `python -m pytest -q` 全绿(预计 60+ tests)。
2. 停 Web 服务(防 db 锁)→ 新库或复用:执行 `python run.py quanzhou`。
3. 验证产物:
   - pages 计数 = 源数(≤7,含 PDF/HTML)
   - doc_insights 计数 > 0(LLM 已启用,key 就绪)
   - enterprises 计数 ≈ 170(2025 名单)
   - 财政 data_values 含 592.07(公报)/ 355.92(执行)等
   - `data/reports/quanzhou_profile.html` 七章齐全,第六章有校验结果
4. 抽样人工核对:LLM critique 与 evidence 一致性;企业名单前 5 行 vs 源网页。
5. 重启 Web → 页面 Tab 可用。

## 14. 收尾

- PROGRESS.md 更新(M5 里程碑 + 证据)。
- 本地 git 分多次提交(feat: ...);每任务提交,消息中文。
- 经 GitHub MCP push_files 推送(用户账号 contribution)。
- 汇报:证据清单 + 报告路径 + LLM 使用量提示 + 已知局限(如扫描版 PDF、缺失指标为 None)。

## 自检清单(阶段 2 硬门禁)

- [x] 规格覆盖:采集 5 类源 / 4 解析通道 / 审读双层 / 数理 6+ 指标 / 报告 7 章 / Web Tab / CLI
- [x] 无占位符:所有 URL/字段/方法签名/测试名具体列出
- [x] 类型一致:Page.doc_category 贯穿 schemas→db→repository→documents;body 一律 JSON 字符串
- [x] 降级路径明确:无 key → llm 分支跳过、报告标注
