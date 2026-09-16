from app.fetch import client as client_mod
from app.fetch.client import HttpClient


def test_robots_failopen_and_cached(monkeypatch):
    """robots.txt 读取失败时 fail-open，且按站点缓存（不重复请求）。"""
    calls = []

    def fake_get(url, timeout, headers):
        calls.append(url)
        raise Exception("no network")

    monkeypatch.setattr(client_mod.requests, "get", fake_get)
    c = HttpClient(delay=0)
    assert c._allowed("https://example.gov.cn/a.htm") is True
    assert len(calls) == 1
    # 同站点第二次命中缓存，不再请求 robots.txt
    assert c._allowed("https://example.gov.cn/b.htm") is True
    assert len(calls) == 1


def test_robots_respect_when_forbidden(monkeypatch):
    class FakeResp:
        text = "User-agent: *\nDisallow: /private/\n"

    def fake_get(url, timeout, headers):
        return FakeResp()

    monkeypatch.setattr(client_mod.requests, "get", fake_get)
    c = HttpClient(delay=0)
    assert c._allowed("https://example.gov.cn/public/a.htm") is True
    assert c._allowed("https://example.gov.cn/private/a.htm") is False


def test_verify_param_passed_to_requests(monkeypatch):
    """verify 参数应透传给 requests.get（政府站自签名证书场景）。"""
    captured = {}

    class FakeResp:
        content = b"<html></html>"

        def raise_for_status(self):
            pass

    def fake_get(url, timeout, headers, verify):
        captured["verify"] = verify
        return FakeResp()

    monkeypatch.setattr(client_mod.requests, "get", fake_get)
    c = HttpClient(delay=0, verify=False)
    c.get("https://example.gov.cn/x.htm")
    assert captured["verify"] is False
