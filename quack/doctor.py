"""`quack doctor`: check the environment without changing anything."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.request
from dataclasses import dataclass

from .config import Config
from .providers import OLLAMA_URL, PRESETS, resolve_spec


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _ollama_models(endpoint: str) -> list[str] | None:
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/api/tags", timeout=1.5) as r:  # noqa: S310
            return [m["name"] for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:  # noqa: BLE001
        return None


def run_checks(config: Config) -> list[Check]:
    checks = [Check("python", sys.version_info >= (3, 10), sys.version.split()[0])]
    for mod, label in (("ollama", "ollama package"), ("rich", "rich (pretty output)"),
                       ("git", "gitpython (--since)"), ("sentry_sdk", "sentry-sdk (tracing)")):
        found = importlib.util.find_spec(mod) is not None
        checks.append(Check(label, found, "installed" if found else "optional, not installed"))

    spec = resolve_spec(config.provider, config) if config.provider in PRESETS else None
    checks.append(Check("provider", spec is not None, f"{config.provider} / {config.model}"))
    if spec and spec.kind == "ollama" or config.fallback == "ollama":
        endpoint = spec.base_url if spec and spec.kind == "ollama" else OLLAMA_URL
        models = _ollama_models(endpoint)
        if models is None:
            checks.append(Check("ollama server", False, f"not reachable at {endpoint} (run `ollama serve`)"))
        else:
            want = config.model if config.provider == "ollama" else (config.fallback_model or "gemma3:4b")
            have = any(m == want or m.split(":")[0] == want.split(":")[0] and ":" not in want for m in models)
            checks.append(Check("ollama model", have, f"{want} " + ("pulled" if have else f"missing: `ollama pull {want}`")))
    if spec and spec.key_env:
        checks.append(Check(f"${spec.key_env}", bool(os.environ.get(spec.key_env)), "set" if os.environ.get(spec.key_env) else "not set"))
    if spec and not spec.local:
        checks.append(Check("remote opt-in", config.allow_remote, "allowed" if config.allow_remote else "blocked (run `quack init`)"))
    checks.append(Check(
        ".env files", True,
        ", ".join(str(p) for p in config.env_files) if config.env_files else "none loaded (optional)",
    ))
    checks.append(Check("index", config.index_db_path.exists(), "built" if config.index_db_path.exists() else "run `quack index`"))
    checks.append(Check("git repo", (config.root / ".git").exists(), "found" if (config.root / ".git").exists() else "none (verify uses hashes)"))
    return checks
