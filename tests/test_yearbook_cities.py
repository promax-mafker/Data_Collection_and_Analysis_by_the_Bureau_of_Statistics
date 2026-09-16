"""福建年鉴「各设区市」表采集测试（M9b 缺口），真实夹具驱动。

关键差异：**region 由行内地区名决定**（不是配置常量），**year 由卷年 + 偏移**给出。
"""
import os

from app.fetch.yearbook_cities import ingest_yearbook_cities
from app.store.db import init_db
from app.store.repository import Repository

BASE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(BASE, "fixtures")
V = "https://tjj.fujian.gov.cn/tongjinianjian/dz2022/"
TOC = V + "contents-cn.htm"
T0407 = V + "cn-en/html/0407.htm"
CFG = {
    "template": V + "contents-cn.htm".replace("contents-cn.htm", "contents-cn.htm"),
    "years": [2022],
    "year_offset": -1,
    "city_regions": {"福州市": "福州市", "厦门市": "厦门市", "泉州市": "泉州市",
                     "莆田市": "莆田市", "三明市": "三明市", "漳州市": "漳州市",
                     "南平市": "南平市", "龙岩市": "龙岩市", "宁德市": "宁德市"},
    "tables": [{"key": "inv", "title": "各设区市固定资产投资额",
                "columns": [{"col": 2, "name": "固定资产投资", "unit": "亿元"}]}],
}
CFG["template"] = V + "contents-cn.htm".replace("dz2022/", "dz{year}/")


def _fx(n):
    with open(os.path.join(FIX, n), encoding="utf-8") as f:
        return f.read()


class FakeClient:
    def __init__(self, mapping):
        self.mapping = mapping

    def download(self, url):
        return self.mapping[url].encode("utf-8")


def _run(tmp_path):
    client = FakeClient({TOC: _fx("fj_yearbook_toc_2022.htm"), T0407: _fx("fj_yearbook_0407.htm")})
    repo = Repository(init_db(str(tmp_path / "t.db")))
    return repo, ingest_yearbook_cities(client, repo, CFG)


def test_region_comes_from_row_not_config(tmp_path):
    repo, st = _run(tmp_path)
    assert st["tables_parsed"] == 1
    assert st["values"] >= 9, f"应写入 9 个设区市，实得 {st['values']}"
    rows = repo.query_data(indicator="固定资产投资", year="2021", primary_only=False)
    regions = {r["region"] for r in rows}
    assert "泉州市" in regions and "福州市" in regions and "厦门市" in regions
    qz = [r for r in rows if r["region"] == "泉州市"][0]
    assert qz["value"] == "2576.14", f"实得 {qz['value']}"
    assert qz["unit"] == "亿元"


def test_province_row_is_excluded(tmp_path):
    """「全 省」行不得被当成一个地区入库（否则多出一个假地区）。"""
    repo, st = _run(tmp_path)
    regions = {r["region"] for r in repo.query_data(indicator="固定资产投资",
                                                   primary_only=False)}
    assert "全 省" not in regions and "全省" not in regions
    assert len(regions) == 9, f"应恰好 9 个设区市，实得 {sorted(regions)}"


def test_year_is_volume_year_plus_offset(tmp_path):
    """福建年鉴 dz2022 卷载 2021 年数据（卷年 = 数据年 + 1）。"""
    repo, _ = _run(tmp_path)
    years = {r["year"] for r in repo.query_data(indicator="固定资产投资",
                                                primary_only=False)}
    assert years == {"2021"}, f"实得 {years}"


def test_idempotent_on_rerun(tmp_path):
    repo, st1 = _run(tmp_path)
    n1 = len(repo.query_data(indicator="固定资产投资", primary_only=False))
    client = FakeClient({TOC: _fx("fj_yearbook_toc_2022.htm"), T0407: _fx("fj_yearbook_0407.htm")})
    ingest_yearbook_cities(client, repo, CFG)
    n2 = len(repo.query_data(indicator="固定资产投资", primary_only=False))
    assert n1 == n2, f"重跑应幂等：{n1} → {n2}"


def test_missing_table_recorded(tmp_path):
    cfg = dict(CFG, tables=[{"key": "nope", "title": "不存在的表", "columns": []}])
    client = FakeClient({TOC: _fx("fj_yearbook_toc_2022.htm")})
    repo = Repository(init_db(str(tmp_path / "t.db")))
    st = ingest_yearbook_cities(client, repo, cfg)
    assert st["tables_parsed"] == 0 and st["missing"]
