"""Minimal .env loader. Real environment variables always win."""

from __future__ import annotations

import os
from pathlib import Path


def parse_env(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines (supports ``export``, quotes and comments)."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = (s.strip() for s in line.split("=", 1))
        if not key.isidentifier():
            continue
        if value[:1] in {'"', "'"} and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def env_candidates(root: Path) -> list[Path]:
    """Highest priority first: project .quack/.env, project .env, user-level config."""
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return [Path(root) / ".quack" / ".env", Path(root) / ".env", xdg / "quack" / ".env"]


def load_env_files(root: Path) -> list[Path]:
    """Load env files into ``os.environ`` without overriding existing variables."""
    loaded: list[Path] = []
    for path in env_candidates(root):
        try:
            if not path.is_file():
                continue
            for k, v in parse_env(path.read_text(encoding="utf-8")).items():
                os.environ.setdefault(k, v)
            loaded.append(path)
        except OSError:
            continue
    return loaded
