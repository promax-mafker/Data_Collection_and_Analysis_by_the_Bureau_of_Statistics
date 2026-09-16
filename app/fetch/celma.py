"""CELMA 地方政府债券信息公开平台适配器（M9c）。

设计判定：这是目前**唯一能免费拿到政府债务一般债/专项债分项**的公开源
（见 `docs/research/ALT_SOURCES.md` §3.3）。

实测（2026-09-15）：

* 端点 ``https://www.governbond.org.cn:4443/api/loadBondData.action``
* ``?dataType=FDQNDZB&zb=060101``（一般债务余额）/ ``060102``（专项债务余额）
* HTTP 200、402 条，字段 ``{AD_CODE, AD_NAME, SET_YEAR, ZB_ID, AMOUNT}``，**无鉴权**
* ⚠ 该站证书链异常，请求须 ``verify=False``
* ⚠ **只到省级**（31 省 + 计划单列市）——**泉州等地级市拿不到**，
  故 note 里强制写明「省级口径」，避免下游误以为有地市级分项。
* ⚠ 同一平台的 ``12xx`` 社会经济序列实测异常（福建进出口相邻年跳变 6 倍），
  **本适配器只取债务类 ``01/03/04/05/06/07``**，不外扩。
"""
import requests

BASE = "https://www.governbond.org.cn:4443/api/loadBondData.action"
DATA_TYPE = "FDQNDZB"

ZB_GENERAL = "060101"
ZB_SPECIAL = "060102"

_INDICATOR = {ZB_GENERAL: "debt_general", ZB_SPECIAL: "debt_special"}
_LABEL = {ZB_GENERAL: "一般债务余额", ZB_SPECIAL: "专项债务余额"}

SCOPE_NOTE = "省级口径（CELMA 地方政府债券平台）；不含地市级"

# ⚠ 实测：不带浏览器 UA 直接请求会被反爬拦截（HTTP 418）。
#   探针用浏览器 UA 得 200；适配器若用 requests 默认 UA 则 418。
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def parse_celma(payload, region_name="福建省"):
    """CELMA JSON → ``[{indicator, year, value, unit, note, raw_text}]``。

    只取目标省级地区；年份非法或缺值一律跳过（不猜、不补）。
    """
    out = []
    for rec in (payload or {}).get("data") or []:
        if str(rec.get("AD_NAME") or "").strip() != region_name:
            continue
        zb = str(rec.get("ZB_ID") or "")
        indicator = _INDICATOR.get(zb)
        if not indicator:
            continue
        year = str(rec.get("SET_YEAR") or "").strip()
        if len(year) != 4 or not year.isdigit():
            continue
        try:
            amount = float(rec.get("AMOUNT"))
        except (TypeError, ValueError):
            continue
        out.append({
            "indicator": indicator,
            "year": year,
            "value": amount,
            "unit": "亿元",
            "note": SCOPE_NOTE,
            "raw_text": f"CELMA {_LABEL.get(zb, zb)} {region_name} {year} {amount}",
        })
    return out


def fetch_celma(region_name="福建省", zbs=(ZB_GENERAL, ZB_SPECIAL), timeout=30, session=None):
    """抓取原始 payload → ``[(payload, zb)]``（网络层，测试不覆盖）。"""
    s = session or requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                      "Referer": "https://www.governbond.org.cn/"})
    out = []
    for zb in zbs:
        r = s.get(BASE, params={"dataType": DATA_TYPE, "zb": zb},
                  timeout=timeout, verify=False)   # 该站证书链异常，实测必须 verify=False
        r.raise_for_status()
        out.append((r.json(), zb))
    return out


def ingest_celma(repo, payloads=None, region_name="福建省"):
    """解析并写入 `econ_series`（按 zb 分 source，整批替换保证幂等）。返回写入行数。"""
    if payloads is None:
        payloads = fetch_celma(region_name)
    n = 0
    for payload, zb in payloads:
        rows = parse_celma(payload, region_name)
        if rows:
            n += repo.replace_econ_series(f"celma_{zb}", rows)
    return n
