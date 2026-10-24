import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from quack.config import load_config
from quack.errors import ProviderError
from quack.providers import FallbackClient, OllamaClient, OpenAICompatClient, build_client

from .conftest import CANNED


@pytest.fixture()
def server():
    seen = {"requests": [], "reject_json_mode": False}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen["requests"].append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if seen["reject_json_mode"] and "response_format" in body:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"unsupported response_format"}')
                return
            out = {"choices": [{"message": {"content": json.dumps(CANNED)}}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", seen
    srv.shutdown()


def test_openai_compat_roundtrip(server):
    url, seen = server
    c = OpenAICompatClient("custom", url, "m", api_key="secret-key")
    out = c.complete("sys", "user")
    assert json.loads(out)["confidence"] == "high"
    assert c.last_tokens == 120
    req = seen["requests"][0]
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer secret-key"
    assert "JSON" in req["body"]["messages"][0]["content"]


def test_retries_without_json_mode_on_400(server):
    url, seen = server
    seen["reject_json_mode"] = True
    OpenAICompatClient("custom", url, "m").complete("s", "u")
    assert len(seen["requests"]) == 2 and "response_format" not in seen["requests"][1]["body"]


def test_anthropic_native_roundtrip():
    from quack.providers import AnthropicClient

    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["key"] = self.headers.get("x-api-key")
            seen["ver"] = self.headers.get("anthropic-version")
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            out = {"content": [{"type": "text", "text": json.dumps(CANNED)}],
                   "usage": {"input_tokens": 90, "output_tokens": 30}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(out).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = AnthropicClient("claude-test", "k-123", f"http://127.0.0.1:{srv.server_port}/v1")
        assert json.loads(c.complete("sys", "user"))["confidence"] == "high"
    finally:
        srv.shutdown()
    assert c.last_tokens == 120 and seen["path"] == "/v1/messages"
    assert seen["key"] == "k-123" and seen["ver"] == "2023-06-01"
    assert seen["body"]["system"].startswith("sys") and seen["body"]["messages"][0]["role"] == "user"


def test_anthropic_build_needs_opt_in_and_key(repo, monkeypatch):
    cfg = load_config(repo)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        build_client(cfg, provider="anthropic", allow_remote=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    with pytest.raises(ProviderError, match="blocked"):
        build_client(cfg, provider="anthropic")
    assert build_client(cfg, provider="anthropic", allow_remote=True).label.startswith("anthropic:")


def test_remote_blocked_without_opt_in():
    c = OpenAICompatClient("openrouter", "https://openrouter.ai/api/v1", "m", "k", allow_remote=False)
    with pytest.raises(ProviderError, match="blocked"):
        c.complete("s", "u")


def test_ollama_remote_host_blocked():
    with pytest.raises(ProviderError, match="blocked"):
        OllamaClient("gemma3:4b", "http://10.0.0.5:11434").complete("s", "u")


def test_build_client_requires_opt_in_and_key(repo, monkeypatch):
    cfg = load_config(repo)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(ProviderError, match="blocked"):
        build_client(cfg, provider="openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        build_client(cfg, provider="openrouter", allow_remote=True)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    client = build_client(cfg, provider="openrouter", allow_remote=True)
    assert client.label == "openrouter:google/gemma-3-27b-it"
    assert client.extra_headers["X-Title"] == "Quack"


def test_unknown_provider(repo):
    with pytest.raises(ProviderError, match="Unknown provider"):
        build_client(load_config(repo), provider="nope")


def test_fallback_uses_second_client_when_first_fails(server):
    url, _ = server
    dead = OpenAICompatClient("custom", "http://127.0.0.1:9/v1", "m", timeout=1)
    good = OpenAICompatClient("custom", url, "m")
    fb = FallbackClient([dead, good])
    assert fb.complete("s", "u")
    assert fb.label == "custom:m" and fb.last_tokens == 120
