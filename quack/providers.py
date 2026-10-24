"""LLM providers: local Ollama (default) and opt-in OpenAI-compatible APIs.

Remote providers (OpenRouter, OpenAI, Groq, ...) are blocked unless the user
explicitly allowed remote use (``quack init --provider ...`` or ``--remote``).
Only redacted, compact context is ever sent.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from .errors import ProviderError
from .models import TutorResponse
from .prompts import JSON_HINT

if TYPE_CHECKING:
    from .config import Config

OLLAMA_URL = "http://localhost:11434"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


class LLMClient(Protocol):
    """Anything that can turn (system, user) into a JSON string."""

    last_tokens: int
    label: str

    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    kind: str  # "ollama" | "openai"
    base_url: str
    key_env: str
    default_model: str
    note: str = ""

    @property
    def local(self) -> bool:
        return is_local_url(self.base_url)


PRESETS: dict[str, ProviderSpec] = {
    s.name: s
    for s in [
        ProviderSpec("ollama", "ollama", OLLAMA_URL, "", "gemma3:4b", "Local, private, free (default)"),
        ProviderSpec("lmstudio", "openai", "http://localhost:1234/v1", "", "local-model", "Local LM Studio server"),
        ProviderSpec("llamacpp", "openai", "http://localhost:8080/v1", "", "local-model", "Local llama.cpp server"),
        ProviderSpec("openrouter", "openai", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
                     "google/gemma-3-27b-it", "Hundreds of models behind one key"),
        ProviderSpec("anthropic", "anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
                     "claude-haiku-5-5", "Claude via the native Messages API"),
        ProviderSpec("openai", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini"),
        ProviderSpec("cerebras", "openai", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "llama-3.3-70b",
                     "Very fast inference"),
        ProviderSpec("fireworks", "openai", "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY",
                     "accounts/fireworks/models/llama-v3p3-70b-instruct"),
        ProviderSpec("huggingface", "openai", "https://router.huggingface.co/v1", "HF_TOKEN",
                     "meta-llama/Llama-3.3-70B-Instruct", "Hugging Face inference router"),
        ProviderSpec("xai", "openai", "https://api.x.ai/v1", "XAI_API_KEY", "grok-3-mini"),
        ProviderSpec("groq", "openai", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
        ProviderSpec("together", "openai", "https://api.together.xyz/v1", "TOGETHER_API_KEY",
                     "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
        ProviderSpec("mistral", "openai", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest"),
        ProviderSpec("deepseek", "openai", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "deepseek-chat"),
        ProviderSpec("gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
                     "GEMINI_API_KEY", "gemini-2.0-flash", "Google's OpenAI-compatible endpoint"),
        ProviderSpec("custom", "openai", "", "", "", "Any OpenAI-compatible endpoint: set base_url + api_key_env"),
    ]
}


def is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS


def _guard(url: str, allow_remote: bool, name: str) -> None:
    if not is_local_url(url) and not allow_remote:
        host = urlparse(url).hostname
        raise ProviderError(
            f"Remote provider '{name}' ({host}) is blocked: Quack is local-only by default. "
            f"Opt in with `quack init --provider {name}` or pass --remote."
        )


class _HTTPStatus(Exception):
    def __init__(self, code: int, body: str) -> None:
        super().__init__(f"HTTP {code}")
        self.code, self.body = code, body


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - scheme is http(s) by construction
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _HTTPStatus(e.code, e.read().decode("utf-8", "replace")[:500]) from e
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise ProviderError(f"Could not reach {urlparse(url).netloc}: {e}") from e
    except ValueError as e:
        raise ProviderError(f"{urlparse(url).netloc} returned invalid JSON") from e


class OllamaClient:
    """Local Ollama. Uses the `ollama` package if installed, plain HTTP otherwise."""

    def __init__(self, model: str, endpoint: str = OLLAMA_URL, timeout: int = 120, allow_remote: bool = False) -> None:
        self.model, self.endpoint, self.timeout, self.allow_remote = model, endpoint.rstrip("/"), timeout, allow_remote
        self.last_tokens = 0
        self.label = f"ollama:{model}"

    def _unreachable(self, e: Exception) -> ProviderError:
        return ProviderError(
            f"Ollama is not reachable at {self.endpoint} ({e}). Start it with `ollama serve` and run "
            f"`ollama pull {self.model}`."
        )

    def complete(self, system: str, user: str) -> str:
        _guard(self.endpoint, self.allow_remote, "ollama")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        schema = TutorResponse.model_json_schema()
        try:
            import ollama  # type: ignore[import-not-found]
        except ImportError:
            ollama = None
        if ollama is not None:
            try:
                resp = ollama.Client(host=self.endpoint, timeout=self.timeout).chat(
                    model=self.model, messages=messages, format=schema, options={"temperature": 0.2}
                )
            except ollama.ResponseError as e:
                raise ProviderError(f"Ollama error: {e}. Is the model pulled? `ollama pull {self.model}`") from e
            except Exception as e:  # noqa: BLE001 - connection errors vary by httpx version
                raise self._unreachable(e) from e
            self.last_tokens = int(getattr(resp, "prompt_eval_count", 0) or 0) + int(getattr(resp, "eval_count", 0) or 0)
            return resp["message"]["content"]
        try:
            data = _post(
                f"{self.endpoint}/api/chat",
                {"model": self.model, "messages": messages, "format": schema, "stream": False,
                 "options": {"temperature": 0.2}},
                {}, self.timeout,
            )
        except _HTTPStatus as e:
            raise ProviderError(f"Ollama error {e.code}: {e.body}") from e
        except ProviderError as e:
            raise self._unreachable(e) from e
        self.last_tokens = int(data.get("prompt_eval_count", 0) or 0) + int(data.get("eval_count", 0) or 0)
        return data["message"]["content"]


class OpenAICompatClient:
    """Any OpenAI-compatible /chat/completions endpoint (OpenRouter, Groq, LM Studio, ...)."""

    def __init__(
        self, name: str, base_url: str, model: str, api_key: str | None = None, timeout: int = 120,
        allow_remote: bool = False, extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name, self.base_url, self.model = name, base_url.rstrip("/"), model
        self.api_key, self.timeout, self.allow_remote = api_key, timeout, allow_remote
        self.extra_headers = extra_headers or {}
        self.last_tokens = 0
        self.label = f"{name}:{model}"

    def _explain(self, e: _HTTPStatus) -> str:
        if e.code in (401, 403):
            return f"{self.name}: authentication failed (HTTP {e.code}). Check your API key."
        if e.code == 402:
            return f"{self.name}: insufficient credits (HTTP 402)."
        if e.code == 404:
            return f"{self.name}: model or endpoint not found for '{self.model}' (HTTP 404)."
        if e.code == 429:
            return f"{self.name}: rate limited (HTTP 429). Try again shortly or switch provider."
        return f"{self.name}: HTTP {e.code}: {e.body[:200]}"

    def complete(self, system: str, user: str) -> str:
        _guard(self.base_url, self.allow_remote, self.name)
        headers = dict(self.extra_headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": f"{system}\n\n{JSON_HINT}"}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.base_url}/chat/completions"
        data: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                data = _post(url, payload, headers, self.timeout)
                break
            except _HTTPStatus as e:
                if e.code == 400 and "response_format" in payload:
                    payload.pop("response_format")  # some models reject JSON mode; retry without
                    continue
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise ProviderError(self._explain(e)) from e
        if data is None:
            raise ProviderError(f"{self.name}: request failed after retries")
        if data.get("error"):
            raise ProviderError(f"{self.name}: {str(data['error'])[:200]}")
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(f"{self.name}: unexpected response shape") from e
        if not content:
            raise ProviderError(f"{self.name}: model returned empty content")
        usage = data.get("usage") or {}
        self.last_tokens = int(usage.get("prompt_tokens", 0) or 0) + int(usage.get("completion_tokens", 0) or 0)
        return content


class AnthropicClient:
    """Claude through Anthropic's native Messages API."""

    def __init__(
        self, model: str, api_key: str, base_url: str = "https://api.anthropic.com/v1", timeout: int = 120,
        allow_remote: bool = False,
    ) -> None:
        self.model, self.api_key, self.base_url = model, api_key, base_url.rstrip("/")
        self.timeout, self.allow_remote = timeout, allow_remote
        self.name = "anthropic"
        self.last_tokens = 0
        self.label = f"anthropic:{model}"

    def complete(self, system: str, user: str) -> str:
        _guard(self.base_url, self.allow_remote, "anthropic")
        payload = {
            "model": self.model, "max_tokens": 1500, "temperature": 0.2,
            "system": f"{system}\n\n{JSON_HINT}",
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                data = _post(f"{self.base_url}/messages", payload, headers, self.timeout)
                break
            except _HTTPStatus as e:
                if e.code in (429, 500, 502, 503, 504, 529) and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if e.code in (401, 403):
                    raise ProviderError("anthropic: authentication failed. Check ANTHROPIC_API_KEY.") from e
                if e.code == 404:
                    raise ProviderError(f"anthropic: model '{self.model}' not found. Pass --model.") from e
                raise ProviderError(f"anthropic: HTTP {e.code}: {e.body[:200]}") from e
        if data is None:
            raise ProviderError("anthropic: request failed after retries")
        try:
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise ProviderError("anthropic: unexpected response shape") from e
        if not text:
            raise ProviderError("anthropic: model returned empty content")
        usage = data.get("usage") or {}
        self.last_tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
        return text


class FallbackClient:
    """Try each client in order; the first success wins."""

    def __init__(self, clients: list[LLMClient]) -> None:
        self.clients = clients
        self.last_tokens = 0
        self.label = clients[0].label

    def complete(self, system: str, user: str) -> str:
        errors: list[str] = []
        for c in self.clients:
            try:
                out = c.complete(system, user)
            except ProviderError as e:
                errors.append(f"{c.label}: {e}")
                continue
            self.last_tokens, self.label = c.last_tokens, c.label
            return out
        raise ProviderError("All providers failed:\n  " + "\n  ".join(errors))


def resolve_spec(name: str, config: "Config") -> ProviderSpec:
    spec = PRESETS.get(name)
    if spec is None:
        raise ProviderError(f"Unknown provider '{name}'. Run `quack providers` to see the options.")
    if name == config.provider and config.base_url:
        spec = replace(spec, base_url=config.base_url)
    if name == "custom":
        if not spec.base_url:
            raise ProviderError("Provider 'custom' needs a base_url: `quack config set base_url https://host/v1`.")
        spec = replace(spec, key_env=config.api_key_env)
    elif name == config.provider and config.api_key_env:
        spec = replace(spec, key_env=config.api_key_env)
    return spec


def _build_one(
    name: str, config: "Config", model: str | None, allow_remote: bool, is_fallback: bool = False,
) -> LLMClient:
    spec = resolve_spec(name, config)
    if model:
        chosen = model
    elif is_fallback:
        chosen = config.fallback_model or spec.default_model
    else:
        chosen = config.model if name == config.provider else spec.default_model
    chosen = chosen or spec.default_model
    if not spec.local and not allow_remote:
        _guard(spec.base_url, False, name)
    if spec.kind == "ollama":
        return OllamaClient(chosen, spec.base_url, config.timeout, allow_remote)
    key = os.environ.get(spec.key_env) if spec.key_env else None
    if spec.key_env and not key and not spec.local:
        raise ProviderError(
            f"Set {spec.key_env} in your environment or a .env file to use {name} (keys are never stored by Quack)."
        )
    if spec.kind == "anthropic":
        return AnthropicClient(chosen, key or "", spec.base_url, config.timeout, allow_remote)
    headers = {"HTTP-Referer": "https://github.com/quack-tutor", "X-Title": "Quack"} if name == "openrouter" else {}
    return OpenAICompatClient(name, spec.base_url, chosen, key, config.timeout, allow_remote, headers)


def build_client(
    config: "Config", provider: str | None = None, model: str | None = None, allow_remote: bool | None = None,
) -> LLMClient:
    """Create the configured client, wrapped with the configured fallback if any."""
    name = provider or config.provider
    allowed = config.allow_remote if allow_remote is None else allow_remote
    primary = _build_one(name, config, model, allowed)
    if config.fallback and config.fallback != name:
        try:
            return FallbackClient([primary, _build_one(config.fallback, config, None, allowed, True)])
        except ProviderError:
            return primary
    return primary
