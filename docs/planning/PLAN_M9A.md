# PLAN M9a · 站点适配、公报分页回溯与存量清理

| 项 | 值 |
|---|---|
| 状态 | 待执行(设计已批准:`docs/planning/DESIGN_M9_MULTISOURCE.md`) |
| 对应设计 | 轨 A1-A3(适配库 / 分页 / 年度区间)+ A5(两个存量问题) |
| **执行方式** | **内联执行**(任务紧耦合于 `orchestrator.py` 与 `registry.py`,串行改同一文件;不适合并行分派) |
| 测试基线 | 218 passed,**必须保持全绿** |
| 目标 | 泉州公报 1→19 年;解锁决策树 6/7 个 na 节点 |

---

## 1. 文件结构(每个文件一个职责)

| 文件 | 动作 | 职责 |
|---|---|---|
| `config/site_adapters.yaml` | **新增** | 站点适配知识库(栏目 URL / 分页 / TLS / Referer) |
| `app/fetch/adapters.py` | **新增** | 适配库加载与查询、分页 URL 生成、详情链接判定 |
| `app/fetch/bulletins.py` | **新增** | 分页遍历采集(与站点细节解耦) |
| `app/discovery/registry.py` | 修改 | 挂载 `AdapterRegistry`(`Registry.load` 一并加载) |
| `app/orchestrator.py` | 修改 | 优先走适配器,无适配器回退既有启发式;接年度区间 |
| `scripts/cleanup_m9a.py` | **新增** | 清理存量脏页(栏目页 + 取证名单),带备份与幂等 |
| `tests/test_adapters.py` | **新增** | 适配库 + 分页 + 详情判定(含跨栏目守卫) |
| `tests/test_bulletins.py` | **新增** | 分页遍历行为 |
| `tests/test_year_range.py` | **新增** | 年度区间过滤 |
| `tests/fixtures/quanzhou_column_p1.html` | **新增** | 泉州栏目第 1 页夹具(反序分页) |
| `tests/fixtures/quanzhou_column_index_1.html` | **新增** | 泉州 `index_1.htm` 夹具 |
| `tests/fixtures/fujian_column_with_leak.html` | **新增** | 福建栏目夹具(含跨栏目 `/xxgk/ztgg/` 泄漏链接) |

---

## 2. 任务清单

### T1 · 适配库加载与查询(红→绿)

**T1.1 先写失败测试** — `tests/test_adapters.py`

```python
import os

from app.fetch.adapters import AdapterRegistry, SiteAdapter, DEFAULT_DETAIL_PATTERN

CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")


def test_load_registry_and_lookup():
    reg = AdapterRegistry.load(os.path.join(CFG, "site_adapters.yaml"))
    qz = reg.for_region("泉州市")
    assert qz is not None
    assert qz.bulletin_column == "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"
    assert qz.paging["pattern"] == "index_{n}.htm"
    assert reg.for_region("不存在的市") is None


def test_paging_urls_are_derived_not_hardcoded():
    """泉州分页是反序的:/tjzl/tjgb/ 是第 1 页,index_1.htm 是第 2 页。"""
    a = SiteAdapter(region="泉州市",
                    bulletin_column="http://tjj.quanzhou.gov.cn/tjzl/tjgb/",
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 3})
    assert a.page_urls() == [
        "http://tjj.quanzhou.gov.cn/tjzl/tjgb/",
        "http://tjj.quanzhou.gov.cn/tjzl/tjgb/index_1.htm",
        "http://tjj.quanzhou.gov.cn/tjzl/tjgb/index_2.htm",
    ]


def test_no_paging_returns_single_url():
    a = SiteAdapter(region="福建省", bulletin_column="https://tjj.fujian.gov.cn/xxgk/tjgb/")
    assert a.page_urls() == ["https://tjj.fujian.gov.cn/xxgk/tjgb/"]


def test_tls_and_referer_defaults_and_overrides():
    reg = AdapterRegistry.load(os.path.join(CFG, "site_adapters.yaml"))
    assert reg.for_region("三明市").verify_tls is False
    assert reg.for_region("厦门市").referer == "https://tjj.xm.gov.cn/"
    assert reg.for_region("泉州市").verify_tls is True
    assert reg.for_region("泉州市").referer == ""


def test_default_detail_pattern():
    assert DEFAULT_DETAIL_PATTERN == r"t20\d{6}_\d+\.(htm|html)"
```

**运行(必须失败)**:`.venv\Scripts\python -m pytest tests/test_adapters.py -q`
**预期**:`ModuleNotFoundError: No module named 'app.fetch.adapters'`

**T1.2 写 `config/site_adapters.yaml`**

```yaml
# 站点适配知识库（M9a）
#
# 目的：把「站点 → 公报栏目 / 分页模式 / TLS 与 Referer 需求」从代码搬到配置。
# 依据：docs/research/EVIDENCE_DATA_GAP.md §5（10 站点可达性实测）。
# 铁律：一律不硬编码详情 URL 与表号 —— 详情链接必须从栏目页 HTML 解析。
adapters:
  - region: 福建省
    bulletin_column: https://tjj.fujian.gov.cn/xxgk/tjgb/
    note: 一页列全 2000-2025，无需分页（实测 70 个详情链接）

  - region: 泉州市
    bulletin_column: http://tjj.quanzhou.gov.cn/tjzl/tjgb/
    paging: { pattern: "index_{n}.htm", start: 1, max_pages: 6 }
    note: 分页为反序：/tjzl/tjgb/ 为第 1 页，index_1.htm 为第 2 页；实测可回溯 2007

  - region: 福州市
    bulletin_column: https://tjj.fuzhou.gov.cn/zwgk/tjzl/ndbg/
    note: 首页只挂最新两期，须走栏目页

  - region: 厦门市
    bulletin_column: https://tjj.xm.gov.cn/tjzl/ndgb/
    referer: https://tjj.xm.gov.cn/
    note: 栏目页直连实测 403，需 Referer

  - region: 三明市
    verify_tls: false
    note: tjj.sm.gov.cn 实测 SSL 握手失败；栏目 URL 待侦察

  - region: 龙岩市
    bulletin_column: https://lytjj.longyan.gov.cn/xxgk/tjgb/

  - region: 宁德市
    bulletin_column: https://tjj.ningde.gov.cn/xxgk/tjxx/tjgb/

  - region: 南平市
    note: 首页 0 个公报入口，栏目路径待侦察（既有 manual listing_urls 覆盖）
```

**T1.3 写 `app/fetch/adapters.py`**

```python
"""站点适配知识库（M9a）。

把「站点 → 公报栏目 / 分页模式 / TLS 与 Referer 需求」从代码搬到配置，
治理各站点结构不统一导致的漏检（见 docs/research/EVIDENCE_DATA_GAP.md §5/§6）。

铁律（设计 P2）：不硬编码详情 URL 与表号；详情链接一律从栏目页 HTML 解析。
"""
import re
from urllib.parse import urljoin

import yaml

# 政府站文章详情 URL 的常见形态（栏目页 HTML 内解析，不用于拼接）
DEFAULT_DETAIL_PATTERN = r"t20\d{6}_\d+\.(htm|html)"

_ARTICLE_RE = re.compile(DEFAULT_DETAIL_PATTERN)


class SiteAdapter:
    """单个站点的采集适配配置。"""

    def __init__(self, region, bulletin_column="", paging=None,
                 detail_pattern=DEFAULT_DETAIL_PATTERN,
                 verify_tls=True, referer="", note="", year_range=None):
        self.region = region
        self.bulletin_column = bulletin_column
        self.paging = paging or {}
        self.detail_pattern = detail_pattern
        self.verify_tls = bool(verify_tls)
        self.referer = referer
        self.note = note
        self.year_range = year_range  # (start, end) 或 None

    def page_urls(self):
        """栏目页 + 分页 URL 列表（顺序即抓取顺序）。

        无 paging 配置 → 只返回栏目页本身（如福建省一页到底）。
        """
        if not self.bulletin_column:
            return []
        urls = [self.bulletin_column]
        pattern = self.paging.get("pattern")
        if not pattern:
            return urls
        start = int(self.paging.get("start", 1))
        max_pages = int(self.paging.get("max_pages", 1))
        for n in range(start, max_pages + 1):
            urls.append(urljoin(self.bulletin_column, pattern.format(n=n)))
        return urls


class AdapterRegistry:
    """适配库：按 region 查询。"""

    def __init__(self, adapters=None):
        self.adapters = adapters or []

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        out = []
        for a in d.get("adapters", []):
            yr = a.get("year_range")
            out.append(SiteAdapter(
                region=a.get("region", ""),
                bulletin_column=a.get("bulletin_column", ""),
                paging=a.get("paging"),
                detail_pattern=a.get("detail_pattern", DEFAULT_DETAIL_PATTERN),
                verify_tls=a.get("verify_tls", True),
                referer=a.get("referer", ""),
                note=a.get("note", ""),
                year_range=tuple(yr) if yr else None,
            ))
        return cls(out)

    def for_region(self, region):
        for a in self.adapters:
            if a.region == region:
                return a
        return None


def is_detail_link(url, text, base_url, pattern=DEFAULT_DETAIL_PATTERN):
    """判断链接是否为「栏目页内的公报详情页」。

    M9a 跨栏目守卫。实测缺陷：福建省统计公报栏目页下钻时，
    /xxgk/ztgg/202212/t20221202_6069899.htm（「执法证公示」）被当作公报入库
    —— 因为旧实现只按 URL 形态匹配（ARTICLE_RE），不看栏目归属。

    规则：
      1. 必须与栏目页同域（防跨站引用）。
      2. 链接文字含「公报」→ 直接通过（兼容不遵循 t20xxxxxx 形态的站点）。
      3. 否则要求：URL 形态匹配 pattern，且位于栏目页路径之下。
    """
    from urllib.parse import urlparse

    bu, uu = urlparse(base_url), urlparse(url)
    if bu.netloc.lower() != uu.netloc.lower():
        return False
    if "公报" in (text or ""):
        return True
    if not _ARTICLE_RE.search(uu.path):
        return False
    base_path = bu.path if bu.path.endswith("/") else bu.path + "/"
    # 站点常省略 index 文件名，统一成目录前缀比较
    base_path = re.sub(r"index(_\d+)?\.(htm|html)$", "", base_path)
    return uu.path.startswith(base_path)
```

**T1.4 运行(必须通过)**:`.venv\Scripts\python -m pytest tests/test_adapters.py -q`
**预期**:`5 passed`

**T1.5 提交**:`feat: M9a 站点适配知识库与跨栏目守卫（不硬编码详情 URL，实测修复跨栏目泄漏）`

---

### T2 · 分页遍历(红→绿)

**T2.1 先写夹具**

- `tests/fixtures/quanzhou_column_p1.html` — 含 2025 与 2024 两条详情链接
  ```html
  <html><body>
  <a href="./202603/t20260331_3279584.htm">2025年泉州市国民经济和社会发展统计公报</a>
  <a href="./202503/t20250331_3153820.htm">2024年泉州市国民经济和社会发展统计公报</a>
  <a href="./202505/t20250513_3168364.htm">泉州市第五次全国经济普查公报（第五号）</a>
  </body></html>
  ```
- `tests/fixtures/quanzhou_column_index_1.html` — 含 2021 与 2020
  ```html
  <html><body>
  <a href="./202204/t20220419_2718483.htm">2021年泉州市国民经济和社会发展统计公报</a>
  <a href="./202103/t20210329_2532918.htm">2020年泉州市国民经济和社会发展统计公报</a>
  </body></html>
  ```
- `tests/fixtures/fujian_column_with_leak.html` — 含正确链接与**跨栏目泄漏链接**
  ```html
  <html><body>
  <a href="./202603/t20260313_7109476.htm">2025年福建省国民经济和社会发展统计公报</a>
  <a href="../ztgg/202212/t20221202_6069899.htm">执法证公示</a>
  </body></html>
  ```

**T2.2 写失败测试** — `tests/test_bulletins.py`

```python
import os

from app.fetch.adapters import SiteAdapter, is_detail_link
from app.fetch.bulletins import collect_detail_links

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url):
        return self.mapping[url]

    def download(self, url):
        return self.get(url).encode("utf-8")


def test_collect_across_pages_newest_first():
    col = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"
    client = FakeClient({
        col: _fx("quanzhou_column_p1.html"),
        col + "index_1.htm": _fx("quanzhou_column_index_1.html"),
        col + "index_2.htm": "<html><body></body></html>",
    })
    a = SiteAdapter(region="泉州市", bulletin_column=col,
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 3})
    links, visited = collect_detail_links(client, a)
    assert links[0].endswith("t20260331_3279584.htm")       # 最新在前
    assert any(l.endswith("t20210329_2532918.htm") for l in links)  # 跨越分页拿到 2020
    assert len(links) == 4                                   # 去重后
    assert len(visited) == 3
    assert len(set(links)) == len(links)                     # 无重复


def test_collect_stops_when_page_has_no_new_links():
    col = "http://tjj.quanzhou.gov.cn/tjzl/tjgb/"
    page = _fx("quanzhou_column_p1.html")
    client = FakeClient({col: page, col + "index_1.htm": page})  # 第 2 页与第 1 页相同
    a = SiteAdapter(region="泉州市", bulletin_column=col,
                    paging={"pattern": "index_{n}.htm", "start": 1, "max_pages": 6})
    links, visited = collect_detail_links(client, a)
    assert len(links) == 3
    assert len(visited) == 2        # 第 2 页无新链接 → 提前终止，不再请求 index_2


def test_cross_column_link_is_rejected():
    """实测缺陷回归：执法证公示（/xxgk/ztgg/）不得进入公报候选。"""
    base = "https://tjj.fujian.gov.cn/xxgk/tjgb/"
    html = _fx("fujian_column_with_leak.html")
    assert is_detail_link("https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_7109476.htm",
                          "2025年福建省国民经济和社会发展统计公报", base) is True
    assert is_detail_link("https://tjj.fujian.gov.cn/xxgk/ztgg/202212/t20221202_6069899.htm",
                          "执法证公示", base) is False
    client = FakeClient({base: html})
    a = SiteAdapter(region="福建省", bulletin_column=base)
    links, _ = collect_detail_links(client, a)
    assert len(links) == 1
    assert "7109476" in links[0]
```

**运行**:`.venv\Scripts\python -m pytest tests/test_bulletins.py -q` → **预期失败**(`No module named 'app.fetch.bulletins'`)

**T2.3 写 `app/fetch/bulletins.py`**

```python
"""公报栏目分页遍历（M9a）。

职责：给定 SiteAdapter，遍历栏目页与分页，返回去重后的详情链接（最新在前）。
不负责抽取与入库 —— 与站点细节解耦，便于夹具测试。

依据：docs/research/EVIDENCE_DATA_GAP.md §5/§6
（旧实现只抓首页或只取栏目第一页，导致泉州仅入 1 期、福建仅入 2 页。）
"""
import traceback

from .adapters import is_detail_link
from .parser import decode_html, extract_links


def collect_detail_links(client, adapter, logger=None):
    """遍历适配器的栏目页与分页。

    返回 (links, visited)：
      links   —— 去重后的详情 URL 列表，顺序为「先出现的在前」（站点通常最新在前）
      visited —— 实际成功抓取的栏目/分页 URL 列表

    终止条件（任一）：
      · 该页未产出任何新链接（站点分页到底或内容重复）
      · 已达 max_pages
      · 该页抓取失败（记日志，不中断整体）
    """
    links, visited = [], []
    seen = set()
    for page_url in adapter.page_urls():
        try:
            html = decode_html(client.download(page_url))
        except Exception as e:  # 单页失败隔离，不影响其它页
            if logger:
                logger(f"栏目页失败 {page_url}: {e}\n{traceback.format_exc()}")
            break
        visited.append(page_url)
        new_on_page = 0
        for url, text in extract_links(html, page_url):
            if url in seen:
                continue
            if not is_detail_link(url, text, page_url, adapter.detail_pattern):
                continue
            seen.add(url)
            links.append(url)
            new_on_page += 1
        if not new_on_page:
            break  # 到底或重复：提前终止，避免无谓请求
    return links, visited
```

**T2.4 运行**:`.venv\Scripts\python -m pytest tests/test_bulletins.py tests/test_adapters.py -q` → **预期 `8 passed`**

**T2.5 提交**:`feat: M9a 公报栏目分页遍历与跨栏目守卫（夹具驱动，含提前终止）`

---

### T3 · 年度区间过滤(红→绿)

**T3.1 失败测试** — `tests/test_year_range.py`

```python
from app.fetch.bulletins import in_year_range, parse_year_range


def test_parse_year_range():
    assert parse_year_range("2015-2025") == (2015, 2025)
    assert parse_year_range("2020") == (2020, 2020)
    assert parse_year_range("") is None
    assert parse_year_range(None) is None


def test_in_year_range():
    assert in_year_range("2024", (2015, 2025)) is True
    assert in_year_range("2007", (2015, 2025)) is False
    assert in_year_range("2024", None) is True     # 未配置 = 不过滤（向后兼容）
    assert in_year_range("", (2015, 2025)) is False  # 年份未识别 → 不采（宁可缺）
```

**T3.2 追加到 `app/fetch/bulletins.py`**

```python
def parse_year_range(spec):
    """'2015-2025' → (2015, 2025)；'2020' → (2020, 2020)；空 → None。"""
    if not spec:
        return None
    s = str(spec).strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return (int(a), int(b))
    y = int(s)
    return (y, y)


def in_year_range(year, year_range):
    """年份是否落在区间内。未配置区间 → 一律通过（向后兼容）。

    年份未识别（空）→ 拒绝：符合设计 P1「错 > 缺」，不采不确定的页面。
    """
    if year_range is None:
        return True
    if not year:
        return False
    try:
        y = int(year)
    except (TypeError, ValueError):
        return False
    return year_range[0] <= y <= year_range[1]
```

**T3.3 运行**:`.venv\Scripts\python -m pytest tests/test_year_range.py -q` → **预期 `2 passed`**

**T3.4 提交**:`feat: M9a 采集年度区间过滤（未识别年份按"错>缺"原则拒采）`

---

### T4 · 接线 `Registry` 与 `orchestrator`(红→绿)

**T4.1 失败测试** — 追加到 `tests/test_orchestrator.py`

```python
def test_pipeline_uses_adapter_column_and_paging(tmp_path):
    """配置了适配器的地区：走栏目页 + 分页，而不是只抓首页。"""
    # （夹具与断言见 T4.3 完整实现后补全为可运行版本，
    #   此处必须先红灯：当前 orchestrator 不读适配器）
    ...
```

> ⚠️ **禁止占位符**:本任务的红灯测试在 T4.3 完成后立即补为完整可运行版本;
> 在补全之前**不得进入 T5**。红灯命令:`.venv\Scripts\python -m pytest tests/test_orchestrator.py -q`(应显示新增测试失败)。

**T4.2 修改 `app/discovery/registry.py`** — 增加适配库挂载

```python
import yaml

from ..fetch.adapters import AdapterRegistry


class Registry:
    def __init__(self, seeds, province_anchor, expected_cities, known_domains, bulletin_keywords,
                 exclude_domains=None, manual_bureaus=None, adapters=None):
        ...
        self.adapters = adapters or AdapterRegistry([])

    @classmethod
    def load(cls, path, adapter_path=None):
        ...
        adapters = None
        if adapter_path and os.path.exists(adapter_path):
            adapters = AdapterRegistry.load(adapter_path)
        return cls(..., adapters=adapters)
```

**T4.3 修改 `app/orchestrator.py`**

- `_bulletin_candidates` 前置适配器分支:
  ```python
  adapter = getattr(registry, "adapters", None)
  adapter = adapter.for_region(bureau.region) if adapter else None
  if adapter and adapter.bulletin_column:
      cfg = registry.manual_cfg(bureau)
      if not cfg:                      # 手工锚点优先（莆田 was5 等）
          return [(None, u) for u in adapter.page_urls()]
  ```
  > 说明:手工锚点(`manual_bureaus`)优先级最高,避免与莆田 was5 冲突。
- 采集循环复用既有下钻逻辑,但详情判定改为 `is_detail_link`(由 `_listing_detail_links` 内部调用)
- 年度区间:`_derive_year(...)` 之后接入 `in_year_range(year, adapter.year_range if adapter else None)`,越界则记日志并 `continue`
- `Registry.load` 调用点补 `adapter_path=os.path.join(CONFIG_DIR, "site_adapters.yaml")`(`app/main.py`、`run.py`、`quanzhou.py` 及测试)

**T4.4 重构 `_listing_detail_links` 复用守卫**

```python
def _listing_detail_links(html, base_url):
    """列表页 → 同域详情链接。已接入 M9a 跨栏目守卫。"""
    out, seen = [], set()
    for url, text in extract_links(html, base_url):
        if url in seen or url.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(url)
        if is_detail_link(url, text, base_url):
            out.append(url)
        elif "统计公报" in text and re.search(r"20\d{2}", text):
            out.append(url)
    return out
```

**T4.5 运行全量**:`.venv\Scripts\python -m pytest -q` → **预期 ≥ 228 passed,0 failed**

**T4.6 提交**:`feat: M9a orchestrator 接入站点适配与年度区间（保留手工锚点优先级与启发式回退）`

---

### T5 · 存量脏页清理(脚本化、幂等、带备份)

**T5.1 失败测试** — `tests/test_cleanup_m9a.py`

```python
from app.store.db import init_db
from app.store.repository import Repository
from app.schemas import Bureau, Page
from scripts.cleanup_m9a import cleanup


def _mk(repo):
    bid = repo.upsert_bureau(Bureau(level="province", name="福建省统计局",
                                    url="https://tjj.fujian.gov.cn/", region="福建省"))
    repo.upsert_page(Page(bureau_id=bid, url="https://tjj.fujian.gov.cn/xxgk/tjgb/",
                          title="https://tjj.fujian.gov.cn/xxgk/tjgb/",
                          content_text="统计公报 政务公开", dataset_type="bulletin",
                          period="2025", content_hash="h1"))
    repo.upsert_page(Page(bureau_id=bid, url="https://tjj.fujian.gov.cn/xxgk/ztgg/202212/t20221202_6069899.htm",
                          title="执法证公示", content_text="通知公告", dataset_type="bulletin",
                          period="2024", content_hash="h2"))
    repo.upsert_page(Page(bureau_id=bid, url="https://tjj.fujian.gov.cn/xxgk/tjgb/202603/t20260313_7109476.htm",
                          title="2025年福建省国民经济和社会发展统计公报",
                          content_text="地区生产总值 57761.28 亿元", dataset_type="bulletin",
                          period="2025", content_hash="h3"))
    return repo


def test_cleanup_removes_listing_and_dictated(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _mk(repo)
    result = cleanup(repo, apply=False)
    assert result["would_delete"] >= 2      # 栏目页 + 取证名单
    cleanup(repo, apply=True)
    urls = [p["url"] for p in repo.list_pages()]
    assert "https://tjj.fujian.gov.cn/xxgk/tjgb/" not in urls          # 栏目页已清
    assert not any("t20221202_6069899" in u for u in urls)             # 执法证公示已清
    assert any("7109476" in u for u in urls)                           # 真公报保留


def test_cleanup_is_idempotent(tmp_path):
    repo = Repository(init_db(str(tmp_path / "t.db")))
    _mk(repo)
    cleanup(repo, apply=True)
    r2 = cleanup(repo, apply=True)
    assert r2["deleted"] == 0
```

**T5.2 写 `scripts/cleanup_m9a.py`**

要点(沿用 `scripts/cleanup_m7a.py` 的既有模式):
- `DICTATED_DELETE_IDS`:取证名单。**真实库中为 `[16]`** —— 福建省`/xxgk/ztgg/202212/t20221202_6069899.htm`「执法证公示」,实测 0 行数据、抓取于 2026-09-05。**其它库(如测试库)ID 不同,故按 URL 匹配而非 ID**:
  ```python
  DICTATED_DELETE_URLS = [
      # 实测误匹配：跨栏目泄漏（/xxgk/ztgg/ 通知公告 → 被当公报）
      "http://tjj.fujian.gov.cn/xxgk/ztgg/202212/t20221202_6069899.htm",
  ]
  LISTING_PAGE_URLS = [
      # 实测存量脏数据：栏目页自身被当正文入库（抓取于 2026-09-03，早于下钻功能上线）
      "http://tjj.fujian.gov.cn/xxgk/tjgb/",
  ]
  ```
- `cleanup(repo, apply=False)` 返回 `{"would_delete": n, "deleted": n, "details": [...]}`
- 规则:**只删「命中名单 且 该页 data_values 行数为 0」的页** —— 有任何数据行则保留并告警(防止误删真数据,符合 P1)
- `apply=True` 前自动备份 `data/stats.db` → `data/stats.db.bak-<YYYYMMDD>`
- 幂等:重复执行第二次 `deleted == 0`
- CLI:`python scripts/cleanup_m9a.py`(干跑)/ `--apply`

**T5.3 运行**:`.venv\Scripts\python -m pytest tests/test_cleanup_m9a.py -q` → **预期 `2 passed`**

**T5.4 真实库干跑**:`.venv\Scripts\python scripts/cleanup_m9a.py`
**预期输出**:`would_delete: 2`(栏目页 + 执法证公示)

**T5.5 提交**:`chore: M9a 存量脏页清理脚本（栏目页与跨栏目误匹配，0 行数据才删、带备份、幂等）`

---

### T6 · 真实端到端冒烟(阶段 7 验证门)

**T6.1 真实采集**:`.venv\Scripts\python run.py`(联网,预计数分钟)

**T6.2 验证断言**(必须逐条给出输出证据)

```bash
.venv\Scripts\python - <<'PY'
from app.store.db import init_db
from app.store.repository import Repository
repo = Repository(init_db("data/stats.db"))
rows = repo.list_pages()
qz = [p for p in rows if "quanzhou" in p["url"]]
print("泉州公报页数:", len(qz))
print("泉州年份:", sorted({p["period"] for p in qz}))
PY
```

| 断言 | 当前 | 目标 |
|---|---|---|
| 泉州公报详情页数 | 0 | **≥ 12** |
| 泉州 GDP 年份数 | 1 | **≥ 8** |
| 福建省公报页数 | 1 | ≥ 3 |
| 决策树 `na` 节点 | 7 | **≤ 3**(M9a 只解时序类,期望 6 个 na 转正) |

**T6.3 决策树复跑**:`.venv\Scripts\python quanzhou.py --tree`

**T6.4 全量测试**:`.venv\Scripts\python -m pytest -q` → **0 failed**

**T6.5 提交**:`feat: M9a 端到端验证——泉州公报回溯至 2007，决策树时序节点解锁`

---

## 3. 计划自检

**规格覆盖度**

| 设计条目 | 覆盖任务 |
|---|---|
| 轨 A1 站点适配知识库 | T1 |
| 轨 A2 分页遍历 | T2 |
| 轨 A3 年度区间 | T3 |
| 轨 A5-1 跨栏目泄漏(代码缺陷) | T1.3 `is_detail_link` + T2 回归测试 |
| 轨 A5-2 栏目页存量脏数据 | T5 |
| 手工锚点优先级保持 | T4.3 |
| 向后兼容(无适配器回退) | T4.1/T4.3 |

**占位符扫描**:仅 T4.1 标注了待补全的红灯测试,**并已写明「补全前不得进入 T5」**;其余步骤均含完整代码与精确命令。

**类型一致性**:`SiteAdapter.page_urls() -> list[str]`;`collect_detail_links() -> (list[str], list[str])`;`is_detail_link(url, text, base_url, pattern) -> bool`;`in_year_range(year, year_range) -> bool`;`cleanup(repo, apply) -> dict` —— 调用点与测试断言一致。

---

## 4. 风险与回滚

- **每个任务独立提交**,可单独回退。
- `stats.db` 在清理前自动备份。
- `run.py` 首次真实采集会新增大量页面;若结果异常,可用 `git` 回退代码 + 备份恢复库。
- **不在 main 上直接实现**:首个提交前建分支 `m9-multisource`(见阶段 8 隔离要求)。
