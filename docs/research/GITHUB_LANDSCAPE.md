# 开源生态调研:有没有相似产品可借鉴(2026-09-14)

> 路径二交付物。目的:在 GitHub / 开源生态中找出与 `stats-collector` 相似的产品,
> 判断「有没有整机可抄」,并提取可落地的零件。
> **所有仓库均经真实检索 + 真实 README 读取核对**,star 数与描述来自 GitHub API 实测。

## 1. 检索方法与三个坑(先说清楚,免得后人重踩)

| 坑 | 现象 | 对策 |
|---|---|---|
| 中文宽泛 query 无效 | `统计年鉴` 命中 21174 个仓库,前 10 全是 `funNLP`、`TrendRadar` 等无关明星仓库 —— GitHub 对中文 query 是 **readme 全文匹配**,噪声淹没信号 | 改用 `in:name` 限定 + 英文词 + 窄 query |
| **`raw.githubusercontent.com` 被网络阻断** | 直连 18s 超时/连接错误;`github.com` 同样 ReadTimeout | 改用 **`api.github.com/repos/{owner}/{repo}/readme`**(该域实测 200,未被阻断) |
| 子代理取大响应会被截断 | 首个调研子代理用 GitHub API 拉 200KB+ 搜索响应,4 个 JSON 全部被截断、无法解析,子代理在写报告前就挂了 | 搜索一律 `per_page≤12`;大响应落盘后用脚本解析,**不要把原始 JSON 灌进上下文** |

> 实测网络矩阵:`api.github.com` ✅ 200 · `cdn.jsdelivr.net` ✅ · `gitee.com` ✅ 200 ·
> `raw.githubusercontent.com` ❌ 阻断 · `github.com` ❌ 超时 · `ghproxy.net` ❌ 404。

## 2. 候选清单(真实存在,已核对 README)

| 仓库 | ⭐ | 语言 | 是什么 | 可借鉴点 | 局限 |
|---|---|---|---|---|---|
| [`donadonny/statsscrapy`](https://github.com/donadonny/statsscrapy) | 低 | Python/scrapy | **最直接的同类**:用 scrapy 爬统计局年鉴,提取为结构化数据并做指标分组 | ①**附了 `data.stats.gov.cn` easyquery 真实接口参数**(见 §3.1);②数据模型口径「地区来源/数据来源/时间/表名/数据内容」 | 只覆盖国家统计局数据库;**自己是半成品**(README 自列 7 项未完成:增量爬取、Excel 下载解析、增量清洗…) |
| [`suyu0925/china-statistical-yearbook`](https://github.com/suyu0925/china-statistical-yearbook) | 2 | — | **年鉴入口 URL 索引**:国家(1999-2023)+ 广东/韶关/江西/南昌/抚州 等省市年鉴链接清单 | **把「站点→年鉴入口」沉淀成知识库**,正是我们实测缺的东西 | 只有链接,无采集代码;覆盖窄 |
| [`zhangpelf/PDF-`](https://github.com/zhangpelf/PDF-) | 0 | Python | 中国能源统计年鉴 PDF 抽取(RapidOCR + pdf2image) | **扫描版 PDF 的 OCR 方案 + 按「坐标对齐」还原表格行列** | 单一年鉴、单指标域;需 poppler |
| [`xiangyuecn/AreaCity-JsSpider-StatsGov`](https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov) | 高 | JS | 省市区乡镇**四级行政区划**(含拼音/坐标/边界),整合国家地名信息库 + 腾讯/高德地图 | **行政区划规范表**;有 [Gitee 镜像](https://gitee.com/xiangyuecn/AreaCity-JsSpider-StatsGov)(对我们的网络友好) | 是基础维表,不是统计数据 |
| [`lonlonago/china-statistical-yearbook-1950-2025`](https://github.com/lonlonago/china-statistical-yearbook-1950-2025) | 0 | — | **卖**《中国统计年鉴》1950-2025 整理好的 Excel,**$89 / Stripe+邮件发货** | 反向证据:年鉴数字化有付费需求,且**至今没被开源解决** | 不可溯源、不可核验(与我们的原则冲突) |
| [`PKUJohnson/OpenData`](https://github.com/PKUJohnson/OpenData) | 1367 | Python | `opendatatools`:多源数据提取 → **统一 API**(金融域) | **统一适配范式**:每源一模块,统一 `df, msg = module.fn(param)`,失败必带原因 | 金融数据,非政府统计 |
| [`Diraw/Data-Collection-Process-for-the-2024-Huashu-Cup-C-Problem`](https://github.com/Diraw/Data-Collection-Process-for-the-2024-Huashu-Cup-C-Problem) | 0 | Python | 华数杯赛题数据收集全过程记录 | **第三方聚合站作交叉验证源**:城市规模爬 `citypopulation.de`、空气质量爬 `air-level.com`;多源 CSV 合并/缺失分析脚本化 | 竞赛级科研脚本,非工程产品 |

另外检索到 `/tjgb/` 类同构无独立域名站点时,**未发现任何"中国地市级统计公报解析"的可用开源项目**。

## 3. 最高价值发现

### 3.1 `data.stats.gov.cn` easyquery 接口(来自 statsscrapy 的实测记录)

> ⚠️ **更正(2026-09-14,由 `ALT_SOURCES.md` 实测推翻)**:下面这套**旧 easyquery 接口在本机网络下已被 WAF 按 URL 封禁** ——
> `curl -4` 实测 **403**,响应体明文 `reason:UrlACL`;换 dbcode、补 Referer/X-Requested-With/完整浏览器头、
> 强制 IPv4 **全部 403**。**不要再按本节投入。**
> **替代方案(实测完全可用,无鉴权)**:新版官方 API
> `https://data.stats.gov.cn/dg/website/publicrelease/web/external`
> (`/query?search=` 搜索、`/new/queryIndexTreeAsync?code=6` 分省年度目录树、
> `/new/queryIndicatorsByCid?cid=` 取指标、`/new/getDefaultIndicData` 取序列)。
> 详见 `ALT_SOURCES.md` §3.1.2。下面内容仅作历史记录保留。

这是**同源但结构化**的官方接口 —— 不需要解析网页/PDF 就能拿到多年年度序列:

```
指标树:  http://data.stats.gov.cn/easyquery.htm?id=A03&dbcode=hgjd&wdcode=zb&m=getTree
查数据:  http://data.stats.gov.cn/easyquery.htm?m=QueryData&dbcode=hgnd&rowcode=zb
         &colcode=sj&wds=[]&dfwds=[{"wdcode":"zb","valuecode":"A030701"},
                                    {"wdcode":"sj","valuecode":"LAST20"}]
```

| 参数 | 含义 |
|---|---|
| `dbcode` | `hgnd` 全国年度 / `hgjd` 全国季度 / `hgyd` 全国月度(另有分省: `fsnd/fsjd/fsyd`) |
| `wdcode` | `zb` 指标 / `sj` 时间 |
| `valuecode` | 指标代码(先 `m=getTree` 拿树,父节点 `isParent=true` 可下钻) |
| 时间 | `LAST5` / `LAST10` / `LAST20` |
| `m` | `getTree` 取指标树 / `QueryData` 取数 |

**能力边界(重要)**:该接口最深到**分省**。**地市级不覆盖** —— 所以泉州这类地市
仍然只能靠公报/年鉴。它解决的是「国家 + 省级多年序列」,不是「地市序列」。

### 3.2 反向证据:这个方向没有整机

- `statsscrapy`(唯一同类)自己列的未完成清单,几乎逐条对应我们的痛点:增量爬取、增量清洗、
  多爬虫多集合存储、Excel 下载解析 → **说明连最接近的尝试也没做完。**
- 有人把年鉴 Excel 卖到 $89 → **如果存在成熟开源方案,这个生意不成立。**
- 命中「地市级统计公报」的项目数为 **0**。

**结论:开源界没有可直接抄的整机,我们是这个细分方向的领先实现。**

## 4. 横向能力对比(我们 vs 开源界)

| 能力维度 | 开源界最佳 | 我们的现状 | 判定 |
|---|---|---|---|
| 站点发现(逐级) | 无 | 国家→省→市 + 白名单 + 人工锚点 | **我们领先** |
| 栏目定位/分页回溯 | 只有 URL 索引清单 | 有下钻但**不分页** | 开源思路可补 |
| 增量爬取/去重 | statsscrapy 未完成 | 内容哈希去重 + upsert | **我们领先** |
| 非表格文本抽取 | 无 | 规则 + LLM + 批判审读 | **我们领先** |
| 表格/PDF 抽取 | 坐标对齐 + OCR | colspan 展开 + pdfplumber(**无 OCR**) | **开源更全** |
| 数据模型与口径 | statsscrapy 有「来源/时间/表名」 | caliber + source_url + raw_text 溯源 | 大致相当,可吸收其「表名」维度 |
| 多源交叉验证 | 无 | 无 | **双方都缺** |
| 官方结构化接口 | statsscrapy 抄了 easyquery 参数 | 未接入 | **开源领先** |
| 行政区划规范 | AreaCity 四级区划表 | region 纯文本匹配 | **开源领先** |

## 5. Top 5 可直接借鉴的设计(含落地位置)

1. **接入国家统计局新版官方 API** → 补国家/省级多年序列,零解析成本。
   端点 `https://data.stats.gov.cn/dg/website/publicrelease/web/external`(实测 200,无鉴权)。
   落地:`app/fetch/` 新增 `nbs_api.py`;数据源类型增加 `api`;不动现有公报管线。
   ⚠ 边界:仅到省级。~~旧 easyquery 接口~~ 已被 WAF 封禁,勿用(见 §3.1 更正)。
2. **站点适配知识库** → 把「站点 → 栏目 URL / 分页模式 / 编码 / TLS / Referer」沉淀成配置。
   直接解决我们实测的福州 404、厦门 403、三明 SSL 失败、南平无入口、泉州 `index_N.htm` 反序分页。
   落地:新建 `config/site_adapters.yaml`,收编现在散落在 `bureaus.yaml` 与 `quanzhou_sources.yaml` 的手工锚点。
   参考 [`suyu0925/china-statistical-yearbook`](https://github.com/suyu0925/china-statistical-yearbook) 的入口索引组织方式。
3. **OCR + 坐标对齐表格解析** → 解扫描版 PDF(莆田技术债)。
   落地:`app/fetch/pdf.py` 加 OCR 回退;`app/parse/table.py` 加坐标聚类行列还原。
   参考 [`zhangpelf/PDF-`](https://github.com/zhangpelf/PDF-)。
4. **行政区划规范维表** → region 从文本匹配升级为 adcode 匹配,消除「福建省莆田市/莆田市/莆田」
   歧义,并支撑区县下钻。落地:`app/store/` 加 `regions` 表 + `resolve_region()`。
   参考 [`AreaCity-JsSpider-StatsGov`](https://github.com/xiangyuecn/AreaCity-JsSpider-StatsGov)(走 Gitee 镜像下载)。
5. **统一数据源适配契约** → 为异源接入定接口,失败必带原因不静默。
   落地:`app/fetch/base.py` 抽象 `SourceAdapter.fetch(cfg) -> (records, message)`;
   公报 / API / 年鉴 / 第三方各一实现。参考 [`PKUJohnson/OpenData`](https://github.com/PKUJohnson/OpenData) 的 `df, msg` 范式。

## 6. 对「解放单一来源」的启示

- **同源结构化优先于异源**:easyquery 用官方接口拿国家/省级多年序列,比爬网页稳、比异源可信。
- **第三方聚合站可作交叉验证源**(`citypopulation.de` 人口/面积、`air-level.com` 空气质量),
  但它们是**二手转述**,只能用于「对账」不能作为主数据 —— 与「抗数据美化」的目标一致。
- **异源能覆盖的多数是「最新一年」**,而我们的瓶颈是**序列**:
  先用 easyquery + 公报分页回溯把序列补齐,再让异源做「同年同指标的第二数据点」。

> 异源选型与可达性实测见 `ALT_SOURCES.md`(另一路调研进行中)。
