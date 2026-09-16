# 统计局数据采集平台 实现计划

> **面向 AI 代理的工作者：** 使用 software-dev-workflow 阶段 3（子代理驱动或内联执行）逐任务实现。步骤用复选框（`- [ ]`）跟踪进度。

**目标：** 从国家统计局逐级发现「国家 → 福建省 → 福建地级市」统计局官网，采集年度统计公报（综合 + 专题），规则抽取结构化指标后按年度分类入库，提供一键运行与 Web 浏览导出。

**架构：** 分层模块化单体。`discovery → fetch → extract → store → web → orchestrator`。抽取层为可插拔接口（本次 `RuleExtractor`，预留 `LLMExtractor`）。

**技术栈：** Python 3.11+ / requests / beautifulsoup4 / FastAPI / uvicorn / SQLite(stdlib sqlite3) / PyYAML / pytest。

**执行方式：** 子代理驱动（推荐）；任务相互独立、边界清晰时亦可内联。见文末「执行交接」。

**关键前提（调研结论，已钉死）：**
- 国家统计局官网 `https://www.stats.gov.cn/`；福建省统计局 `https://tjj.fujian.gov.cn/`。
- 福建统计公报 URL 模式：`https://tjj.fujian.gov.cn/xxgk/tjgb/YYYYMM/tYYYYMMDD_XXXXXXX.htm`。
- 地市域名不规整（`tjj.fuzhou.gov.cn`、`tjj.zhangzhou.gov.cn`、`tjj.sm.gov.cn`），故递进发现用「域名模式 + 链接文本 + 标题校验 + 白名单兜底」。
- 本环境无外网，**所有测试必须用本地夹具（fixture）+ 伪造 HTTP 客户端**，不发起真实请求；真实联网采集在用户机器上运行。

---

## 文件结构与职责

| 文件 | 职责 |
|------|------|
| `requirements.txt` | 依赖声明 |
| `config/bureaus.yaml` | 种子、省级锚点、地市预期清单、白名单、公报关键词 |
| `config/extract_rules.yaml` | 指标词典 + 抽取正则 |
| `app/schemas.py` | `Bureau` / `Page` / `DataValue` 数据类 |
| `app/store/db.py` | SQLite 建表与连接 |
| `app/store/repository.py` | 增删改查、去重、导出、运行记录 |
| `app/fetch/parser.py` | HTML → 链接/标题/正文/哈希（纯函数） |
| `app/fetch/client.py` | HTTP 客户端（重试/限速/UA/robots） |
| `app/extract/base.py` | `Extractor` 抽象接口 |
| `app/extract/rule_extractor.py` | 规则抽取器 + 规则加载 |
| `app/extract/llm_extractor.py` | 预留（二期） |
| `app/discovery/registry.py` | 读取 `bureaus.yaml` |
| `app/discovery/resolver.py` | 链接发现 + 域名匹配 + 标题校验 + 子机构发现 |
| `app/orchestrator.py` | 一键管线编排 |
| `app/main.py` | FastAPI 入口与端点 |
| `app/web/static/index.html` `app.js` `style.css` | 单页前端 |
| `run.py` | CLI 一键运行 |
| `tests/*` | pytest 测试（夹具驱动） |

---

## 任务 1：项目脚手架与配置

**文件：**
- 创建：`requirements.txt`、`.gitignore`、`config/bureaus.yaml`、`config/extract_rules.yaml`、`tests/fixtures/national_home.html`、`tests/fixtures/fujian_home.html`、`tests/fixtures/bulletin_2024.txt`
- 创建空包目录：`app/`、`app/discovery/`、`app/fetch/`、`app/extract/`、`app/store/`、`app/web/static/`、`tests/`

- [ ] **步骤 1：初始化 git 仓库**
  ```powershell
  cd E:\Deepseek_harness\stats-collector
  git init
  ```
- [ ] **步骤 2：创建 `requirements.txt`**
  ```text
  requests==2.32.3
  beautifulsoup4==4.12.3
  fastapi==0.115.6
  uvicorn==0.34.0
  PyYAML==6.0.2
  pytest==8.3.4
  httpx==0.28.1
  ```
- [ ] **步骤 3：创建 `.gitignore`**
  ```text
  __pycache__/
  *.pyc
  .pytest_cache/
  data/
  .venv/
  ```
- [ ] **步骤 4：创建 `config/bureaus.yaml`**
  ```yaml
  seeds:
    - url: https://www.stats.gov.cn/
      name: 国家统计局
      region: 中国
      level: national
  province_anchor: https://tjj.fujian.gov.cn/
  expected_cities:
    - 福州市
    - 厦门市
    - 漳州市
    - 泉州市
    - 三明市
    - 莆田市
    - 南平市
    - 龙岩市
    - 宁德市
  known_domains:
    - tjj.fujian.gov.cn
    - tjj.fuzhou.gov.cn
    - tjj.zhangzhou.gov.cn
    - tjj.sm.gov.cn
  bulletin_keywords:
    - 统计公报
    - 国民经济和社会发展统计公报
  ```
- [ ] **步骤 5：创建 `config/extract_rules.yaml`**
  ```yaml
  indicators:
    - name: 地区生产总值
      category: 综合
      unit: 亿元
      pattern: "(?:地区生产总值|生产总值|GDP)\\s*(?:达到|实现|完成|为|约|突破)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 第一产业增加值
      category: 综合
      unit: 亿元
      pattern: "第一产业增加值\\s*(?:达到|实现|完成|为|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 第二产业增加值
      category: 综合
      unit: 亿元
      pattern: "第二产业增加值\\s*(?:达到|实现|完成|为|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 第三产业增加值
      category: 综合
      unit: 亿元
      pattern: "第三产业增加值\\s*(?:达到|实现|完成|为|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 常住人口
      category: 人民生活
      unit: 万人
      pattern: "常住人口\\s*(?:为|达到|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万人)?"
    - name: 居民人均可支配收入
      category: 人民生活
      unit: 元
      pattern: "(?:居民人均可支配收入|人均可支配收入)\\s*(?:为|达到|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>元)?"
    - name: 居民消费价格指数
      category: 人民生活
      unit: "%"
      pattern: "(?:居民消费价格|CPI).{0,6}(?P<value>[0-9]+(?:\\.[0-9]+)?)\\s*(?P<unit>%|％)?"
    - name: 社会消费品零售总额
      category: 国内贸易
      unit: 亿元
      pattern: "社会消费品零售总额\\s*(?:达到|实现|完成|为|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 固定资产投资
      category: 固定资产投资
      unit: "%"
      pattern: "固定资产投资.{0,6}增长\\s*(?P<value>[0-9]+(?:\\.[0-9]+)?)\\s*(?P<unit>%|％)?"
    - name: 进出口总额
      category: 对外经济
      unit: 亿元
      pattern: "(?:进出口总额|进出口)\\s*(?:达到|实现|完成|为|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 一般公共预算收入
      category: 财政金融
      unit: 亿元
      pattern: "(?:一般公共预算收入|地方一般公共预算收入)\\s*(?:达到|实现|完成|为|约)?\\s*(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 规模以上工业增加值
      category: 工业和建筑业
      unit: "%"
      pattern: "(?:规模以上工业增加值|规模以上工业).{0,8}增长\\s*(?P<value>[0-9]+(?:\\.[0-9]+)?)\\s*(?P<unit>%|％)?"
    - name: 农林牧渔业总产值
      category: 农业
      unit: 亿元
      pattern: "(?:农林牧渔业总产值|农林牧渔业).{0,6}(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
    - name: 研究与试验发展经费
      category: 科学技术
      unit: 亿元
      pattern: "(?:研究与试验发展|R&D).{0,10}经费.{0,6}(?P<value>[0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?P<unit>万亿元|亿元|万元)?"
  ```
- [ ] **步骤 6：创建 `tests/fixtures/national_home.html`**
  ```html
  <html><head><title>国家统计局</title></head><body>
  <a href="/sj/">数据</a>
  <a href="https://tjj.fujian.gov.cn/">福建省统计局</a>
  <a href="https://tjj.zhejiang.gov.cn/">浙江省统计局</a>
  <a href="https://www.example.com/other">无关链接</a>
  </body></html>
  ```
- [ ] **步骤 7：创建 `tests/fixtures/fujian_home.html`**
  ```html
  <html><head><title>福建省统计局</title></head><body>
  <a href="https://tjj.fuzhou.gov.cn/">福州市统计局</a>
  <a href="https://tjj.zhangzhou.gov.cn/">漳州市统计局</a>
  <a href="https://tjj.sm.gov.cn/">三明市统计局</a>
  <a href="https://tjj.fujian.gov.cn/xxgk/tjgb/">统计公报</a>
  </body></html>
  ```
- [ ] **步骤 8：创建 `tests/fixtures/bulletin_2024.txt`**
  ```text
  2024年福建省国民经济和社会发展统计公报

  福建省统计局
  2025年3月

  一、综合
  初步核算，全年实现地区生产总值53162.36亿元，比上年增长5.5%。其中，第一产业增加值2979.28亿元，增长3.2%；第二产业增加值21589.50亿元，增长5.9%；第三产业增加值28593.58亿元，增长5.3%。

  二、农业
  全年农林牧渔业总产值6185.43亿元，比上年增长3.6%。

  五、固定资产投资
  全年固定资产投资比上年增长3.5%。

  六、国内贸易
  全年社会消费品零售总额22888.95亿元，比上年增长4.3%。

  九、财政金融
  全年一般公共预算收入3728.21亿元，比上年增长3.1%。

  十、人民生活
  全年居民人均可支配收入46095元，比上年增长5.1%。
  年末常住人口4185万人。
  全年居民消费价格比上年上涨0.4%。
  ```
- [ ] **步骤 9：验证目录**
  ```powershell
  Get-ChildItem -Recurse -File | Select-Object FullName
  ```
  预期：`config/` 下 2 个 yaml，`tests/fixtures/` 下 3 个文件。
- [ ] **步骤 10：Commit**
  ```powershell
  git add -A; git commit -m "chore: 初始化项目脚手架与配置夹具"
  ```

---

## 任务 2：数据类 `app/schemas.py`

**文件：**
- 创建：`app/schemas.py`

- [ ] **步骤 1：创建 `app/schemas.py`**
  ```python
  from dataclasses import dataclass
  from typing import Optional

  @dataclass
  class Bureau:
      level: str                    # national / province / city
      name: str
      url: str
      region: str
      parent_id: Optional[int] = None
      id: Optional[int] = None      # 数据库主键，入库后回填
      verified: bool = False

  @dataclass
  class Page:
      bureau_id: int
      url: str
      title: str
      content_text: str
      dataset_type: str             # bulletin / topic
      period: str                   # 年度，如 2024
      content_hash: str
      status: str = "fetched"

  @dataclass
  class DataValue:
      page_id: Optional[int]
      bureau_id: Optional[int]
      region: str
      year: str
      indicator_name: str
      value: str
      unit: str
      category: str
      raw_text: str
      method: str = "rule"
  ```
- [ ] **步骤 2：验证导入**
  ```powershell
  python -c "from app.schemas import Bureau, Page, DataValue; print(Bureau(level='city', name='x', url='u', region='r'))"
  ```
  预期：打印 `Bureau(level='city', name='x', url='u', region='r', parent_id=None, verified=False)`。
- [ ] **步骤 3：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增核心数据类 schemas"
  ```

---

## 任务 3：存储层 `store/db.py` + `store/repository.py`

**文件：**
- 创建：`app/store/db.py`、`app/store/repository.py`
- 测试：`tests/test_store.py`

- [ ] **步骤 1：编写失败的测试 `tests/test_store.py`**
  ```python
  from app.store.db import init_db
  from app.store.repository import Repository
  from app.schemas import Bureau, DataValue

  def _repo(tmp_path):
      return Repository(init_db(str(tmp_path / "t.db")))

  def test_bureau_upsert_dedup(tmp_path):
      repo = _repo(tmp_path)
      b1 = Bureau(level="city", name="福州市统计局", url="https://tjj.fuzhou.gov.cn/", region="福州市")
      i = repo.upsert_bureau(b1)
      b2 = Bureau(level="city", name="福州市统计局", url="https://tjj.fuzhou.gov.cn/", region="福州市", verified=True)
      j = repo.upsert_bureau(b2)
      assert i == j
      assert repo.list_bureaus()[0]["verified"] == 1

  def test_insert_and_query_and_export(tmp_path):
      repo = _repo(tmp_path)
      v = DataValue(page_id=None, bureau_id=None, region="福建省", year="2024",
                    indicator_name="地区生产总值", value="53162.36", unit="亿元",
                    category="综合", raw_text="地区生产总值53162.36亿元")
      assert repo.insert_values([v]) == 1
      rows = repo.query_data(region="福建省", indicator="地区生产总值", year="2024")
      assert len(rows) == 1
      assert rows[0]["value"] == "53162.36"
      assert "地区生产总值" in repo.export_csv(region="福建省")

  def test_run_lifecycle(tmp_path):
      repo = _repo(tmp_path)
      rid = repo.start_run()
      repo.finish_run(rid, "success", {"values": 3}, "log line")
      run = repo.get_run(rid)
      assert run["status"] == "success"
      assert len(repo.list_runs()) == 1
  ```
- [ ] **步骤 2：运行测试确认失败** → `python -m pytest tests/test_store.py -v`，预期 FAIL（模块不存在）
- [ ] **步骤 3：创建 `app/store/db.py`**
  ```python
  import sqlite3

  SCHEMA = """
  CREATE TABLE IF NOT EXISTS bureaus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    parent_id INTEGER,
    verified INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
  );
  CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bureau_id INTEGER NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    content_text TEXT,
    dataset_type TEXT NOT NULL,
    period TEXT,
    content_hash TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    status TEXT NOT NULL DEFAULT 'fetched'
  );
  CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases TEXT,
    unit TEXT,
    category TEXT
  );
  CREATE TABLE IF NOT EXISTS data_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER,
    bureau_id INTEGER,
    region TEXT,
    year TEXT,
    indicator_name TEXT,
    value TEXT,
    unit TEXT,
    category TEXT,
    raw_text TEXT,
    method TEXT NOT NULL DEFAULT 'rule',
    extracted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
  );
  CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary_json TEXT,
    log TEXT
  );
  """

  def connect(path: str) -> sqlite3.Connection:
      conn = sqlite3.connect(path)
      conn.row_factory = sqlite3.Row
      return conn

  def init_db(path: str) -> sqlite3.Connection:
      conn = connect(path)
      conn.executescript(SCHEMA)
      conn.commit()
      return conn
  ```
- [ ] **步骤 4：创建 `app/store/repository.py`**
  ```python
  import csv
  import io
  import json

  class Repository:
      def __init__(self, conn):
          self.conn = conn

      def upsert_bureau(self, b) -> int:
          row = self.conn.execute("SELECT id FROM bureaus WHERE url=?", (b.url,)).fetchone()
          if row:
              self.conn.execute(
                  "UPDATE bureaus SET level=?, name=?, region=?, parent_id=?, verified=? WHERE id=?",
                  (b.level, b.name, b.region, b.parent_id, int(b.verified), row["id"]))
              self.conn.commit()
              return row["id"]
          cur = self.conn.execute(
              "INSERT INTO bureaus (level, name, url, region, parent_id, verified) VALUES (?,?,?,?,?,?)",
              (b.level, b.name, b.url, b.region, b.parent_id, int(b.verified)))
          self.conn.commit()
          return cur.lastrowid

      def list_bureaus(self):
          return [dict(r) for r in self.conn.execute("SELECT * FROM bureaus ORDER BY level, id")]

      def upsert_page(self, p) -> int:
          row = self.conn.execute("SELECT id FROM pages WHERE url=?", (p.url,)).fetchone()
          if row:
              return row["id"]
          cur = self.conn.execute(
              "INSERT INTO pages (bureau_id, url, title, content_text, dataset_type, period, content_hash, status) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (p.bureau_id, p.url, p.title, p.content_text, p.dataset_type, p.period, p.content_hash, p.status))
          self.conn.commit()
          return cur.lastrowid

      def insert_values(self, values) -> int:
          n = 0
          for v in values:
              self.conn.execute(
                  "INSERT INTO data_values (page_id, bureau_id, region, year, indicator_name, value, unit, category, raw_text, method) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (v.page_id, v.bureau_id, v.region, v.year, v.indicator_name, v.value, v.unit, v.category, v.raw_text, v.method))
              n += 1
          self.conn.commit()
          return n

      def query_data(self, region=None, indicator=None, year=None):
          sql = "SELECT * FROM data_values WHERE 1=1"
          params = []
          if region:
              sql += " AND region=?"; params.append(region)
          if indicator:
              sql += " AND indicator_name=?"; params.append(indicator)
          if year:
              sql += " AND year=?"; params.append(year)
          return [dict(r) for r in self.conn.execute(sql, params)]

      def export_csv(self, region=None, year=None):
          rows = self.query_data(region=region, year=year)
          out = io.StringIO()
          if rows:
              w = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
              w.writeheader()
              w.writerows(rows)
          return out.getvalue()

      def start_run(self) -> int:
          cur = self.conn.execute("INSERT INTO runs (status) VALUES ('running')")
          self.conn.commit()
          return cur.lastrowid

      def finish_run(self, run_id, status, summary, log):
          self.conn.execute(
              "UPDATE runs SET finished_at=datetime('now','localtime'), status=?, summary_json=?, log=? WHERE id=?",
              (status, json.dumps(summary, ensure_ascii=False), log, run_id))
          self.conn.commit()

      def get_run(self, run_id):
          row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
          return dict(row) if row else None

      def list_runs(self):
          return [dict(r) for r in self.conn.execute("SELECT * FROM runs ORDER BY id DESC")]
  ```
- [ ] **步骤 5：运行测试确认通过** → `python -m pytest tests/test_store.py -v`，预期 3 PASS
- [ ] **步骤 6：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增 SQLite 存储层与仓储"
  ```

---

## 任务 4：采集层 `fetch/parser.py` + `fetch/client.py`

**文件：**
- 创建：`app/fetch/parser.py`、`app/fetch/client.py`
- 测试：`tests/test_parser.py`

- [ ] **步骤 1：编写失败的测试 `tests/test_parser.py`**
  ```python
  from app.fetch.parser import extract_links, extract_title, extract_text, hash_text

  HTML = """<html><head><title>福建省统计局</title></head><body>
  <a href="/xxgk/tjgb/">统计公报</a>
  <a href="https://tjj.fuzhou.gov.cn/">福州市统计局</a>
  <script>var x=1;</script>
  <p>全年地区生产总值53162.36亿元。</p>
  </body></html>"""

  def test_extract_links_absolute_and_text():
      links = extract_links(HTML, "https://tjj.fujian.gov.cn/")
      assert ("https://tjj.fujian.gov.cn/xxgk/tjgb/", "统计公报") in links
      assert ("https://tjj.fuzhou.gov.cn/", "福州市统计局") in links

  def test_extract_title():
      assert extract_title(HTML) == "福建省统计局"

  def test_extract_text_removes_script():
      text = extract_text(HTML)
      assert "地区生产总值53162.36亿元" in text
      assert "var x" not in text

  def test_hash_deterministic():
      assert hash_text("abc") == hash_text("abc")
      assert len(hash_text("abc")) == 64
  ```
- [ ] **步骤 2：运行测试确认失败** → `python -m pytest tests/test_parser.py -v`，预期 FAIL
- [ ] **步骤 3：创建 `app/fetch/parser.py`**
  ```python
  import hashlib
  import re
  from urllib.parse import urljoin
  from bs4 import BeautifulSoup

  def extract_links(html: str, base_url: str):
      soup = BeautifulSoup(html, "html.parser")
      out = []
      for a in soup.find_all("a", href=True):
          href = a.get("href", "").strip()
          if not href or href.startswith(("#", "javascript:", "mailto:")):
              continue
          out.append((urljoin(base_url, href), a.get_text(" ", strip=True)))
      return out

  def extract_title(html: str) -> str:
      soup = BeautifulSoup(html, "html.parser")
      t = soup.find("title")
      return t.get_text(strip=True) if t else ""

  def extract_text(html: str) -> str:
      soup = BeautifulSoup(html, "html.parser")
      for tag in soup(["script", "style", "noscript"]):
          tag.decompose()
      text = soup.get_text("\n", strip=True)
      return re.sub(r"\n{2,}", "\n", text)

  def hash_text(text: str) -> str:
      return hashlib.sha256(text.encode("utf-8")).hexdigest()
  ```
- [ ] **步骤 4：创建 `app/fetch/client.py`**
  ```python
  import time
  import requests
  from urllib.parse import urlparse
  from urllib.robotparser import RobotFileParser

  class FetchError(Exception):
      pass

  class HttpClient:
      def __init__(self, timeout=20, retries=2, delay=1.0, user_agent=None, respect_robots=True):
          self.timeout = timeout
          self.retries = retries
          self.delay = delay
          self.user_agent = user_agent or "Mozilla/5.0 (compatible; stats-collector/1.0)"
          self.respect_robots = respect_robots

      def _allowed(self, url) -> bool:
          if not self.respect_robots:
              return True
          try:
              p = urlparse(url)
              rp = RobotFileParser()
              rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
              rp.read()
              return rp.can_fetch(self.user_agent, url)
          except Exception:
              return True

      def get(self, url: str) -> str:
          if not self._allowed(url):
              raise FetchError(f"robots 禁止访问: {url}")
          last = None
          for attempt in range(self.retries + 1):
              try:
                  resp = requests.get(url, timeout=self.timeout,
                                      headers={"User-Agent": self.user_agent})
                  resp.raise_for_status()
                  resp.encoding = resp.apparent_encoding or resp.encoding
                  time.sleep(self.delay)
                  return resp.text
              except requests.RequestException as e:
                  last = e
                  time.sleep(2 ** attempt)
          raise FetchError(f"抓取失败 {url}: {last}")
  ```
- [ ] **步骤 5：运行测试确认通过** → `python -m pytest tests/test_parser.py -v`，预期 4 PASS
- [ ] **步骤 6：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增 HTML 解析与 HTTP 客户端"
  ```

---

## 任务 5：抽取层 `extract/base.py` + `extract/rule_extractor.py` + 预留 `llm_extractor.py`

**文件：**
- 创建：`app/extract/base.py`、`app/extract/rule_extractor.py`、`app/extract/llm_extractor.py`
- 测试：`tests/test_rule_extractor.py`

- [ ] **步骤 1：编写失败的测试 `tests/test_rule_extractor.py`**
  ```python
  import os
  from app.extract.rule_extractor import RuleExtractor, load_rules, split_sections

  BASE = os.path.dirname(os.path.abspath(__file__))
  FIXTURE = os.path.join(BASE, "fixtures", "bulletin_2024.txt")
  RULES = os.path.join(BASE, "..", "config", "extract_rules.yaml")

  def _text():
      with open(FIXTURE, encoding="utf-8") as f:
          return f.read()

  def _rules():
      return load_rules(os.path.abspath(RULES))

  def test_split_sections():
      sections = split_sections(_text())
      assert any("综合" in h for h, _ in sections)

  def test_extract_gdp():
      values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
      gdp = [v for v in values if v.indicator_name == "地区生产总值"]
      assert len(gdp) == 1
      assert gdp[0].value == "53162.36"
      assert gdp[0].unit == "亿元"
      assert gdp[0].category == "综合"

  def test_extract_population_and_income():
      values = RuleExtractor().extract(_text(), {"region": "福建省", "year": "2024"}, _rules())
      pop = [v for v in values if v.indicator_name == "常住人口"][0]
      assert pop.value == "4185"
      assert pop.category == "人民生活"
      inc = [v for v in values if v.indicator_name == "居民人均可支配收入"][0]
      assert inc.value == "46095"
  ```
- [ ] **步骤 2：运行测试确认失败** → `python -m pytest tests/test_rule_extractor.py -v`，预期 FAIL
- [ ] **步骤 3：创建 `app/extract/base.py`**
  ```python
  from abc import ABC, abstractmethod

  class Extractor(ABC):
      @abstractmethod
      def extract(self, content_text: str, meta: dict, rules: list):
          """返回 DataValue 列表"""
  ```
- [ ] **步骤 4：创建 `app/extract/rule_extractor.py`**
  ```python
  import re
  import yaml
  from .base import Extractor
  from ..schemas import DataValue

  SECTION_RE = re.compile(r'^\s*(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）)(.+)$', re.M)

  CATEGORY_KEYWORDS = {
      "综合": ["综合", "生产总值"],
      "农业": ["农业", "农林牧渔"],
      "工业和建筑业": ["工业", "建筑业"],
      "固定资产投资": ["固定资产投资", "投资"],
      "国内贸易": ["国内贸易", "社会消费品", "市场消费"],
      "对外经济": ["对外经济", "进出口", "外资"],
      "财政金融": ["财政", "金融"],
      "人民生活": ["人民生活", "居民", "收入", "消费价格", "人口"],
      "科学技术": ["科技", "科学", "研究与试验", "R&D"],
  }

  def classify_heading(heading: str) -> str:
      for cat, kws in CATEGORY_KEYWORDS.items():
          if any(k in heading for k in kws):
              return cat
      return "综合"

  def split_sections(text: str):
      matches = list(SECTION_RE.finditer(text))
      if not matches:
          return []
      sections = []
      if text[:matches[0].start()].strip():
          sections.append(("综合", text[:matches[0].start()]))
      for i, m in enumerate(matches):
          body = text[m.end():matches[i + 1].start()] if i + 1 < len(matches) else text[m.end():]
          sections.append((m.group(0).strip(), body))
      return sections

  class RuleExtractor(Extractor):
      def extract(self, content_text, meta, rules):
          values = []
          sections = split_sections(content_text)
          if not sections:
              values.extend(self._run(content_text, rules, meta))
          else:
              for heading, body in sections:
                  cat = classify_heading(heading)
                  applicable = [r for r in rules if r["category"] == cat]
                  values.extend(self._run(body, applicable, meta))
          return values

      @staticmethod
      def _run(text, rules, meta):
          out = []
          for rule in rules:
              for m in re.finditer(rule["pattern"], text):
                  out.append(DataValue(
                      page_id=meta.get("page_id"),
                      bureau_id=meta.get("bureau_id"),
                      region=meta.get("region"),
                      year=meta.get("year"),
                      indicator_name=rule["name"],
                      value=m.group("value"),
                      unit=m.groupdict().get("unit") or rule.get("unit", ""),
                      category=rule["category"],
                      raw_text=m.group(0),
                      method="rule",
                  ))
          return out

  def load_rules(path):
      with open(path, "r", encoding="utf-8") as f:
          return yaml.safe_load(f)["indicators"]
  ```
- [ ] **步骤 5：创建 `app/extract/llm_extractor.py`（预留，二期）**
  ```python
  from .base import Extractor

  class LLMExtractor(Extractor):
      """二期接入 OpenAI 兼容端点后实现，本次不落地。"""
      def extract(self, content_text, meta, rules):
          raise NotImplementedError("LLM 抽取器二期实现")
  ```
- [ ] **步骤 6：运行测试确认通过** → `python -m pytest tests/test_rule_extractor.py -v`，预期 3 PASS
- [ ] **步骤 7：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增规则抽取器与 LLM 预留接口"
  ```

---

## 任务 6：递进发现 `discovery/registry.py` + `discovery/resolver.py`

**文件：**
- 创建：`app/discovery/registry.py`、`app/discovery/resolver.py`
- 测试：`tests/test_discovery.py`

- [ ] **步骤 1：编写失败的测试 `tests/test_discovery.py`**
  ```python
  import os
  from app.discovery.registry import Registry
  from app.discovery.resolver import discover_candidates, discover_children
  from app.schemas import Bureau

  BASE = os.path.dirname(os.path.abspath(__file__))
  FIX = os.path.join(BASE, "fixtures")

  class FakeClient:
      def __init__(self, mapping):
          self.mapping = mapping
      def get(self, url):
          if url in self.mapping:
              return self.mapping[url]
          raise Exception(f"no fixture for {url}")

  def _registry():
      return Registry(
          seeds=[{"url": "https://www.stats.gov.cn/", "name": "国家统计局", "region": "中国", "level": "national"}],
          province_anchor="https://tjj.fujian.gov.cn/",
          expected_cities=["福州市", "漳州市", "三明市"],
          known_domains=["tjj.fujian.gov.cn", "tjj.fuzhou.gov.cn", "tjj.zhangzhou.gov.cn", "tjj.sm.gov.cn"],
          bulletin_keywords=["统计公报"],
      )

  def test_discover_provinces():
      html = open(os.path.join(FIX, "national_home.html"), encoding="utf-8").read()
      cands = discover_candidates(html, "https://www.stats.gov.cn/", _registry())
      urls = [c["url"] for c in cands]
      assert "https://tjj.fujian.gov.cn/" in urls
      assert "https://tjj.zhejiang.gov.cn/" in urls
      assert all("example.com" not in u for u in urls)

  def test_discover_cities():
      client = FakeClient({
          "https://tjj.fujian.gov.cn/": open(os.path.join(FIX, "fujian_home.html"), encoding="utf-8").read(),
          "https://tjj.fuzhou.gov.cn/": "<html><title>福州市统计局</title></html>",
          "https://tjj.zhangzhou.gov.cn/": "<html><title>漳州市统计局</title></html>",
          "https://tjj.sm.gov.cn/": "<html><title>三明市统计局</title></html>",
      })
      parent = Bureau(level="province", name="福建省统计局", url="https://tjj.fujian.gov.cn/", region="福建省")
      children = discover_children(client, _registry(), parent)
      names = [c.name for c in children]
      assert "福州市统计局" in names
      assert all(c.level == "city" for c in children)
      assert len(children) == 3
  ```
- [ ] **步骤 2：运行测试确认失败** → `python -m pytest tests/test_discovery.py -v`，预期 FAIL
- [ ] **步骤 3：创建 `app/discovery/registry.py`**
  ```python
  import yaml

  class Registry:
      def __init__(self, seeds, province_anchor, expected_cities, known_domains, bulletin_keywords):
          self.seeds = seeds
          self.province_anchor = province_anchor
          self.expected_cities = expected_cities
          self.known_domains = known_domains
          self.bulletin_keywords = bulletin_keywords

      @classmethod
      def load(cls, path):
          with open(path, "r", encoding="utf-8") as f:
              d = yaml.safe_load(f)
          return cls(
              seeds=d.get("seeds", []),
              province_anchor=d.get("province_anchor", ""),
              expected_cities=d.get("expected_cities", []),
              known_domains=d.get("known_domains", []),
              bulletin_keywords=d.get("bulletin_keywords", []),
          )
  ```
- [ ] **步骤 4：创建 `app/discovery/resolver.py`**
  ```python
  import re
  from urllib.parse import urlparse
  from ..fetch.parser import extract_links, extract_title
  from ..schemas import Bureau

  STATS_DOMAIN_RE = re.compile(r"(?:tjj|stats|tj)\.[a-z0-9\-]+\.gov\.cn$")
  STATS_TEXT_RE = re.compile(r"统计")

  def _domain(url):
      return urlparse(url).netloc.lower()

  def is_stats_link(url, text, registry):
      d = _domain(url)
      if d in registry.known_domains:
          return True
      if d.endswith(".gov.cn") and (STATS_DOMAIN_RE.match(d) or "tjj" in d):
          return True
      return bool(STATS_TEXT_RE.search(text)) and d.endswith(".gov.cn")

  def discover_candidates(html, base_url, registry):
      out = []
      for url, text in extract_links(html, base_url):
          if is_stats_link(url, text, registry):
              out.append({"url": url, "text": text})
      return out

  def verify_bureau(client, url):
      try:
          title = extract_title(client.get(url))
          if "统计局" in title or "统计" in title:
              return title
      except Exception:
          return None
      return None

  def derive_region(name):
      n = name.replace("统计局", "").strip()
      if n in ("国家", "中国", ""):
          return "中国"
      return n

  def discover_children(client, registry, parent):
      html = client.get(parent.url)
      parent_domain = _domain(parent.url)
      seen = set()
      children = []
      for url, text in extract_links(html, parent.url):
          if _domain(url) == parent_domain:
              continue
          if not is_stats_link(url, text, registry):
              continue
          if url in seen:
              continue
          seen.add(url)
          title = verify_bureau(client, url)
          if not title:
              continue
          level = "city" if parent.level == "province" else "province"
          children.append(Bureau(level=level, name=title, url=url,
                                 region=derive_region(title), parent_id=parent.id, verified=True))
      return children
  ```
- [ ] **步骤 5：运行测试确认通过** → `python -m pytest tests/test_discovery.py -v`，预期 2 PASS
- [ ] **步骤 6：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增统计局 URL 递进发现"
  ```

---

## 任务 7：一键管线 `app/orchestrator.py`

**文件：**
- 创建：`app/orchestrator.py`
- 测试：`tests/test_orchestrator.py`

- [ ] **步骤 1：编写失败的测试 `tests/test_orchestrator.py`**
  ```python
  import json
  import os
  from app.store.db import init_db
  from app.store.repository import Repository
  from app.discovery.registry import Registry
  from app.extract.rule_extractor import load_rules
  from app.orchestrator import run_pipeline

  BASE = os.path.dirname(os.path.abspath(__file__))
  FIX = os.path.join(BASE, "fixtures")
  CFG = os.path.join(BASE, "..", "config")

  class FakeClient:
      def __init__(self, mapping):
          self.mapping = mapping
      def get(self, url):
          if url in self.mapping:
              return self.mapping[url]
          raise Exception(f"no fixture {url}")

  def test_pipeline(tmp_path):
      client = FakeClient({
          "https://www.stats.gov.cn/": open(os.path.join(FIX, "national_home.html"), encoding="utf-8").read(),
          "https://tjj.fujian.gov.cn/": open(os.path.join(FIX, "fujian_home.html"), encoding="utf-8").read(),
          "https://tjj.fujian.gov.cn/xxgk/tjgb/": open(os.path.join(FIX, "bulletin_2024.txt"), encoding="utf-8").read(),
          "https://tjj.fuzhou.gov.cn/": "<html><title>福州市统计局</title></html>",
          "https://tjj.zhangzhou.gov.cn/": "<html><title>漳州市统计局</title></html>",
          "https://tjj.sm.gov.cn/": "<html><title>三明市统计局</title></html>",
      })
      repo = Repository(init_db(str(tmp_path / "t.db")))
      registry = Registry.load(os.path.join(CFG, "bureaus.yaml"))
      rules = load_rules(os.path.join(CFG, "extract_rules.yaml"))
      run_id = run_pipeline(client, repo, registry, rules)
      run = repo.get_run(run_id)
      assert run["status"] in ("success", "partial")
      s = json.loads(run["summary_json"])
      assert s["bureaus"] >= 4
      assert s["values"] >= 1
      assert len(repo.list_bureaus()) >= 4
  ```
- [ ] **步骤 2：运行测试确认失败** → `python -m pytest tests/test_orchestrator.py -v`，预期 FAIL
- [ ] **步骤 3：创建 `app/orchestrator.py`**
  ```python
  import datetime
  import re
  from .discovery.resolver import discover_children
  from .extract.rule_extractor import RuleExtractor
  from .fetch.parser import extract_links, extract_text, hash_text
  from .schemas import Bureau, Page

  YEAR_RE = re.compile(r'(20\d{2})\s*年')

  def _derive_year(text, default):
      m = YEAR_RE.search(text)
      return m.group(1) if m else default

  def _find_bulletin_links(html, base_url, registry):
      urls = []
      for url, text in extract_links(html, base_url):
          if any(k in (url + text) for k in registry.bulletin_keywords):
              urls.append(url)
      return urls

  def run_pipeline(client, repo, registry, rules):
      run_id = repo.start_run()
      log = []
      summary = {"bureaus": 0, "pages": 0, "values": 0, "errors": 0}

      def logl(msg):
          log.append(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

      try:
          # 1) 国家种子
          national = Bureau(level="national", name="国家统计局",
                            url=registry.seeds[0]["url"], region="中国", verified=True)
          national_id = repo.upsert_bureau(national)
          summary["bureaus"] += 1

          # 2) 国家 → 省
          provinces = discover_children(client, registry, national)
          fujian = next((b for b in provinces if "福建" in b.name), None)
          if fujian is None:
              fujian = Bureau(level="province", name="福建省统计局",
                              url=registry.province_anchor, region="福建省",
                              parent_id=national_id, verified=True)
              logl("国家站未直接发现福建，使用白名单锚点")
          fujian.parent_id = national_id
          fujian_id = repo.upsert_bureau(fujian)
          summary["bureaus"] += 1

          # 3) 省 → 市
          cities = discover_children(client, registry, fujian)
          city_ids = []
          for c in cities:
              c.parent_id = fujian_id
              city_ids.append(repo.upsert_bureau(c))
          summary["bureaus"] += len(cities)
          found = {c.region for c in cities}
          missing = [c for c in registry.expected_cities if c not in found]
          if missing:
              logl(f"未发现地市: {missing}")

          # 4) 采集 + 抽取 + 入库
          extractor = RuleExtractor()
          default_year = str(datetime.date.today().year - 1)
          bureaus = [(national_id, national), (fujian_id, fujian)] + list(zip(city_ids, cities))
          for bid, bureau in bureaus:
              try:
                  html = client.get(bureau.url)
                  for link in _find_bulletin_links(html, bureau.url, registry):
                      try:
                          detail = client.get(link)
                          text = extract_text(detail)
                          if not text.strip():
                              continue
                          year = _derive_year(text, default_year)
                          page = Page(bureau_id=bid, url=link, title=link, content_text=text,
                                      dataset_type="bulletin", period=year,
                                      content_hash=hash_text(text))
                          pid = repo.upsert_page(page)
                          summary["pages"] += 1
                          values = extractor.extract(text, {
                              "page_id": pid, "bureau_id": bid,
                              "region": bureau.region, "year": year}, rules)
                          summary["values"] += repo.insert_values(values)
                      except Exception as e:
                          logl(f"页面失败 {link}: {e}")
                          summary["errors"] += 1
              except Exception as e:
                  logl(f"机构失败 {bureau.name}: {e}")
                  summary["errors"] += 1

          status = "success"
      except Exception as e:
          logl(f"管线异常: {e}")
          status = "partial" if summary["values"] else "failed"

      repo.finish_run(run_id, status, summary, "\n".join(log))
      return run_id
  ```
- [ ] **步骤 4：运行测试确认通过** → `python -m pytest tests/test_orchestrator.py -v`，预期 1 PASS
- [ ] **步骤 5：跑全量测试** → `python -m pytest -v`，预期全部 PASS（10 个测试）
- [ ] **步骤 6：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增一键采集编排管线"
  ```

---

## 任务 8：Web 层 `app/main.py` + 静态前端

**文件：**
- 创建：`app/main.py`、`app/web/static/index.html`、`app/web/static/app.js`、`app/web/static/style.css`

- [ ] **步骤 1：创建 `app/main.py`**
  ```python
  import os
  from fastapi import FastAPI, HTTPException
  from fastapi.responses import PlainTextResponse
  from fastapi.staticfiles import StaticFiles

  from .store.db import init_db
  from .store.repository import Repository
  from .discovery.registry import Registry
  from .extract.rule_extractor import load_rules
  from .fetch.client import HttpClient
  from .orchestrator import run_pipeline

  BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
  DB_PATH = os.environ.get("STATS_DB", os.path.join(BASE_DIR, "data", "stats.db"))
  CONFIG_DIR = os.path.join(BASE_DIR, "config")

  app = FastAPI(title="统计局数据采集平台")

  def build_repo():
      os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
      return Repository(init_db(DB_PATH))

  def build_components():
      registry = Registry.load(os.path.join(CONFIG_DIR, "bureaus.yaml"))
      rules = load_rules(os.path.join(CONFIG_DIR, "extract_rules.yaml"))
      client = HttpClient()
      return registry, rules, client

  @app.post("/api/run")
  def api_run():
      repo = build_repo()
      registry, rules, client = build_components()
      run_id = run_pipeline(client, repo, registry, rules)
      return {"run_id": run_id, "run": repo.get_run(run_id)}

  @app.get("/api/runs")
  def api_runs():
      return build_repo().list_runs()

  @app.get("/api/runs/{run_id}")
  def api_run_detail(run_id: int):
      run = build_repo().get_run(run_id)
      if not run:
          raise HTTPException(404, "not found")
      return run

  @app.get("/api/bureaus")
  def api_bureaus():
      return build_repo().list_bureaus()

  @app.get("/api/data")
  def api_data(region: str = None, indicator: str = None, year: str = None):
      return build_repo().query_data(region, indicator, year)

  @app.get("/api/export")
  def api_export(region: str = None, year: str = None):
      csv_text = build_repo().export_csv(region, year)
      return PlainTextResponse(csv_text, media_type="text/csv",
                               headers={"Content-Disposition": "attachment; filename=stats.csv"})

  app.mount("/", StaticFiles(directory=os.path.join(BASE_DIR, "app", "web", "static"), html=True), name="static")

  if __name__ == "__main__":
      import uvicorn
      uvicorn.run(app, host="127.0.0.1", port=8000)
  ```
- [ ] **步骤 2：创建 `app/web/static/index.html`**
  ```html
  <!doctype html>
  <html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>统计局数据采集平台</title>
    <link rel="stylesheet" href="/style.css">
  </head>
  <body>
    <header><h1>统计局数据采集平台</h1><p>国家 → 福建 → 地级市 · 年度统计公报</p></header>
    <main>
      <section id="controls">
        <button id="runBtn">运行采集</button>
        <span id="status"></span>
      </section>
      <section id="runs"><h2>运行历史</h2><ul id="runList"></ul><pre id="runDetail"></pre></section>
      <section id="bureaus"><h2>统计局机构</h2><ul id="bureauList"></ul></section>
      <section id="data">
        <h2>数据</h2>
        <div id="filters">
          <input id="fRegion" placeholder="地区，如 福建省">
          <input id="fIndicator" placeholder="指标，如 地区生产总值">
          <input id="fYear" placeholder="年份，如 2024">
          <button id="queryBtn">查询</button>
          <a id="exportBtn" href="/api/export" download>导出 CSV</a>
        </div>
        <table id="dataTable"><thead><tr></tr></thead><tbody></tbody></table>
      </section>
    </main>
    <script src="/app.js"></script>
  </body>
  </html>
  ```
- [ ] **步骤 3：创建 `app/web/static/app.js`**
  ```javascript
  const $ = (s) => document.querySelector(s);

  async function runPipeline() {
    $("#status").textContent = "运行中…";
    try {
      const r = await fetch("/api/run", { method: "POST" });
      const d = await r.json();
      $("#status").textContent = "完成 run_id=" + d.run_id + " status=" + d.run.status;
      loadAll();
    } catch (e) {
      $("#status").textContent = "失败：" + e;
    }
  }

  async function loadRuns() {
    const runs = await (await fetch("/api/runs")).json();
    $("#runList").innerHTML = runs.map(r =>
      `<li data-id="${r.id}">#${r.id} ${r.status} ${r.started_at}</li>`).join("");
    document.querySelectorAll("#runList li").forEach(li => li.onclick = async () => {
      const d = await (await fetch("/api/runs/" + li.dataset.id)).json();
      $("#runDetail").textContent = d.log || d.summary_json || "";
    });
  }

  async function loadBureaus() {
    const bs = await (await fetch("/api/bureaus")).json();
    $("#bureauList").innerHTML = bs.map(b => `<li>${b.name} (${b.level})</li>`).join("");
  }

  async function queryData() {
    const p = new URLSearchParams();
    if ($("#fRegion").value) p.set("region", $("#fRegion").value);
    if ($("#fIndicator").value) p.set("indicator", $("#fIndicator").value);
    if ($("#fYear").value) p.set("year", $("#fYear").value);
    const rows = await (await fetch("/api/data?" + p)).json();
    const cols = rows.length ? Object.keys(rows[0]) : [];
    document.querySelector("#dataTable thead tr").innerHTML =
      cols.map(c => `<th>${c}</th>`).join("");
    $("#dataTable tbody").innerHTML = rows.map(r =>
      `<tr>${cols.map(c => `<td>${r[c] ?? ""}</td>`).join("")}</tr>`).join("");
  }

  function loadAll() { loadRuns(); loadBureaus(); queryData(); }

  $("#runBtn").onclick = runPipeline;
  $("#queryBtn").onclick = queryData;
  loadAll();
  ```
- [ ] **步骤 4：创建 `app/web/static/style.css`**
  ```css
  body { font-family: system-ui, sans-serif; margin: 24px; color: #222; }
  header h1 { margin: 0 0 4px; }
  header p { color: #666; margin: 0 0 16px; }
  section { margin: 16px 0; padding: 16px; border: 1px solid #ddd; border-radius: 6px; }
  button { padding: 6px 14px; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ddd; padding: 4px 8px; font-size: 13px; text-align: left; }
  #runDetail { white-space: pre-wrap; background: #f6f6f6; padding: 8px; max-height: 240px; overflow: auto; }
  input { margin-right: 8px; padding: 4px; }
  ```
- [ ] **步骤 5：启动服务自检**
  ```powershell
  python -m app.main
  ```
  预期：`Uvicorn running on http://127.0.0.1:8000`。用浏览器打开 `http://127.0.0.1:8000/` 应看到页面。确认后用 Ctrl+C 停止。
- [ ] **步骤 6：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增 Web 管理界面与 API"
  ```

---

## 任务 9：CLI 一键运行 `run.py` + `README.md`

**文件：**
- 创建：`run.py`、`README.md`

- [ ] **步骤 1：创建 `run.py`**
  ```python
  import os
  from app.store.db import init_db
  from app.store.repository import Repository
  from app.discovery.registry import Registry
  from app.extract.rule_extractor import load_rules
  from app.fetch.client import HttpClient
  from app.orchestrator import run_pipeline

  def main():
      base = os.path.dirname(os.path.abspath(__file__))
      db_path = os.path.join(base, "data", "stats.db")
      os.makedirs(os.path.dirname(db_path), exist_ok=True)
      repo = Repository(init_db(db_path))
      registry = Registry.load(os.path.join(base, "config", "bureaus.yaml"))
      rules = load_rules(os.path.join(base, "config", "extract_rules.yaml"))
      client = HttpClient()
      print("开始一键采集（国家 → 福建 → 地级市）…")
      run_id = run_pipeline(client, repo, registry, rules)
      run = repo.get_run(run_id)
      print(f"完成 run_id={run_id} status={run['status']}")
      print(run["summary_json"])
      print(run["log"])

  if __name__ == "__main__":
      main()
  ```
- [ ] **步骤 2：创建 `README.md`**
  ```markdown
  # 统计局数据采集平台

  从国家统计局逐级发现「国家 → 福建省 → 福建地级市」统计局官网，采集年度统计公报（综合 + 专题），规则抽取结构化指标后按年度分类入库。

  ## 安装
  ```bash
  pip install -r requirements.txt
  ```

  ## 一键运行（命令行）
  ```bash
  python run.py
  ```

  ## 启动 Web 界面
  ```bash
  python -m app.main
  ```
  打开 http://127.0.0.1:8000/ 。

  ## 测试
  ```bash
  python -m pytest -v
  ```

  ## 目录
  - `config/bureaus.yaml`：种子、省级锚点、地市清单、白名单、公报关键词
  - `config/extract_rules.yaml`：指标词典与抽取正则
  - `data/stats.db`：SQLite 数据库（运行时生成）
  ```
- [ ] **步骤 3：Commit**
  ```powershell
  git add -A; git commit -m "feat: 新增 CLI 一键运行与说明文档"
  ```

---

## 任务 10：完成前验证

- [ ] **步骤 1：安装依赖（用户机器联网）** → `pip install -r requirements.txt`
- [ ] **步骤 2：跑全量测试** → `python -m pytest -v`，预期 10 PASS、0 FAIL
- [ ] **步骤 3：CLI 端到端** → `python run.py`，预期打印 `status=success/partial` 且 `summary_json` 中 `bureaus>=4`、`values>=1`
- [ ] **步骤 4：Web 端到端** → `python -m app.main`，浏览器打开 `http://127.0.0.1:8000/`，点「运行采集」，查看运行历史、机构列表、数据表，点「导出 CSV」下载
- [ ] **步骤 5：抽样校验** → 打开 `data/stats.db`，`SELECT * FROM data_values LIMIT 20;` 与原始公报页面抽样对比字段一致性
- [ ] **步骤 6：Commit**（如验证中有修复）
  ```powershell
  git add -A; git commit -m "test: 完成端到端验证"
  ```

---

## 自检

1. **规格覆盖度**：设计文档的验收标准 1（三级网址落库）→ 任务 6/7；验收标准 2（采集→抽取→分类入库）→ 任务 4/5/7；验收标准 3（一键端到端）→ 任务 7/9/10。递进发现、规则抽取、可插拔 LLM 接口、Web 浏览导出、非目标排除均已覆盖。
2. **占位符扫描**：无「待定 / TODO / 类似任务 N」；每个代码步骤含完整代码块；`LLMExtractor` 是明确的「预留接口」（设计文档已声明二期落地，非占位符）。
3. **类型一致性**：`Bureau`/`Page`/`DataValue` 字段在各层使用一致；`RuleExtractor.extract(text, meta, rules)` 签名在测试与 orchestrator 中一致；`Registry` 字段（`seeds`/`province_anchor`/`expected_cities`/`known_domains`/`bulletin_keywords`）在 resolver 与 orchestrator 中一致。

---

## 执行交接

保存计划后选择执行方式：

1. **子代理驱动（推荐）**——每个任务一个新子代理，完成两阶段审查（规格合规 → 代码质量）。
2. **内联执行**——当前会话按任务顺序执行，每 3 个任务设批量检查点。
