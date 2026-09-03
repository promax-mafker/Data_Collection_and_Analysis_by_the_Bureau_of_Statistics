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
        exclude_domains=["www.stats.gov.cn"],
    )

def test_discover_provinces():
    html = open(os.path.join(FIX, "national_home.html"), encoding="utf-8").read()
    cands = discover_candidates(html, "https://www.stats.gov.cn/", _registry())
    urls = [c["url"] for c in cands]
    assert "https://tjj.fujian.gov.cn/" in urls
    assert "https://tjj.zhejiang.gov.cn/" in urls
    assert all("example.com" not in u for u in urls)

def test_discover_children_skips_nonroot_path():
    html = ('<html><head><title>福建省统计局</title></head><body>'
            '<a href="http://tjj.fuzhou.gov.cn/">福州市统计局</a>'
            '<a href="http://www.stats.gov.cn/fw/tjzyjszgks/ksxx/">考试信息 - 国家统计局</a>'
            '<a href="http://www.stats.gov.cn/">国家统计局</a>'
            '</body></html>')
    client = FakeClient({
        "https://tjj.fujian.gov.cn/": html,
        "http://tjj.fuzhou.gov.cn/": "<html><title>福州市统计局</title></html>",
        "http://www.stats.gov.cn/fw/tjzyjszgks/ksxx/": "<html><title>考试信息 - 国家统计局</title></html>",
        "http://www.stats.gov.cn/": "<html><title>国家统计局</title></html>",
    })
    parent = Bureau(level="province", name="福建省统计局", url="https://tjj.fujian.gov.cn/", region="福建省")
    children = discover_children(client, _registry(), parent)
    names = [c.name for c in children]
    assert names == ["福州市统计局"]

def test_discover_children_stops_early_on_target():
    html = ('<html><head><title>福建省统计局</title></head><body>'
            '<a href="http://tjj.fuzhou.gov.cn/">福州市统计局</a>'
            '<a href="http://tjj.zhangzhou.gov.cn/">漳州市统计局</a>'
            '<a href="http://tjj.sm.gov.cn/">三明市统计局</a>'
            '</body></html>')
    calls = []
    class RecordingClient(FakeClient):
        def get(self, url):
            calls.append(url)
            return super().get(url)
    client = RecordingClient({
        "https://tjj.fujian.gov.cn/": html,
        "http://tjj.fuzhou.gov.cn/": "<html><title>福州市统计局</title></html>",
        "http://tjj.zhangzhou.gov.cn/": "<html><title>漳州市统计局</title></html>",
        "http://tjj.sm.gov.cn/": "<html><title>三明市统计局</title></html>",
    })
    parent = Bureau(level="province", name="福建省统计局", url="https://tjj.fujian.gov.cn/", region="福建省")
    children = discover_children(client, _registry(), parent, targets=["福州市"])
    assert [c.name for c in children] == ["福州市统计局"]
    assert "http://tjj.zhangzhou.gov.cn/" not in calls
    assert "http://tjj.sm.gov.cn/" not in calls

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
