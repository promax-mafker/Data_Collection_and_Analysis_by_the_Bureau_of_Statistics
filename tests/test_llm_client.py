"""llm_client.py 测试：用本地假 HTTP 服务器验证请求构造/JSON 解析/错误路径。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.extract.llm_client import LLMClient, LLMError


class _Handler(BaseHTTPRequestHandler):
    """假 OpenAI 兼容端点：记录请求，按 path 返回不同响应。"""
    captured = {}
    mode = "json"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        _Handler.captured = {"path": self.path, "body": json.loads(raw)}
        if _Handler.mode == "json":
            self._send(200, {"choices": [{"message": {"content": '{"ok": true, "n": 42}'}}]})
        elif _Handler.mode == "error":
            self._send(500, {"error": {"message": "boom"}})
        elif _Handler.mode == "badjson":
            self._send(200, {"choices": [{"message": {"content": "不是JSON"}}]})
        elif _Handler.mode == "fenced":
            self._send(200, {"choices": [{"message": {"content": "```json\n{\"ok\": true}\n```"}}]})


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def _client(base, **kw):
    return LLMClient(base_url=base, api_key="sk-test", model="qwen-test", **kw)


def test_complete_json_parses(server):
    _Handler.mode = "json"
    c = _client(server)
    out = c.complete_json("sys", "user msg")
    assert out == {"ok": True, "n": 42}
    # 请求构造正确
    body = _Handler.captured["body"]
    assert body["model"] == "qwen-test"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][1] == {"role": "user", "content": "user msg"}
    assert body["temperature"] == 0.2
    assert _Handler.captured["path"].endswith("/chat/completions")


def test_fenced_json_stripped(server):
    _Handler.mode = "fenced"
    c = _client(server)
    assert c.complete_json("s", "u") == {"ok": True}


def test_http_error_raises_llm_error(server):
    _Handler.mode = "error"
    c = _client(server)
    with pytest.raises(LLMError):
        c.complete_json("s", "u")


def test_unparseable_raises_llm_error(server):
    _Handler.mode = "badjson"
    c = _client(server)
    with pytest.raises(LLMError):
        c.complete_json("s", "u")


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    c = LLMClient(base_url="http://x", api_key=None, model="m")
    assert c.enabled is False


def test_enabled_with_key():
    c = LLMClient(base_url="http://x", api_key="sk-x", model="m")
    assert c.enabled is True


def test_env_fallback_used(monkeypatch):
    """未显式传参时从环境变量读配置。"""
    monkeypatch.setenv("LLM_BASE_URL", "http://env.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_MODEL", "qwen-env")
    c = LLMClient()
    assert c.base_url == "http://env.example/v1"
    assert c.api_key == "sk-env"
    assert c.model == "qwen-env"
    assert c.enabled is True
