"""Central configuration: paths, provider/model selection and defaults."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .envfile import load_env_files
from .errors import QuackError
from .safety import assert_writable


@dataclass
class Config:
    """Runtime configuration. Path fields are derived; the rest is user-tunable."""

    root: Path
    quack_dir: Path
    index_db_path: Path
    history_db_path: Path
    cache_dir: Path
    tasks_md_path: Path
    history_md_path: Path
    env_files: list[Path] = field(default_factory=list)
    model: str = "gemma3:4b"
    provider: str = "ollama"
    base_url: str = ""
    api_key_env: str = ""
    allow_remote: bool = False
    fallback: str = ""
    fallback_model: str = ""
    timeout: int = 120
    trace: bool = False
    sentry: bool = False
    depth: int = 2
    k_files: int = 3
    max_tokens_per_ask: int = 5000
    cache_ttl_seconds: int = 86400
    batch_size: int = 3
    max_review_files: int = 30


_PATH_FIELDS = {
    "root", "quack_dir", "index_db_path", "history_db_path", "cache_dir", "tasks_md_path", "history_md_path",
    "env_files",
}
SETTABLE_KEYS: tuple[str, ...] = tuple(f.name for f in fields(Config) if f.name not in _PATH_FIELDS)


def coerce(key: str, raw: Any) -> Any:
    """Convert ``raw`` to the type of the config field ``key``."""
    if key not in SETTABLE_KEYS:
        raise ValueError(f"Unknown config key '{key}'. Valid keys: {', '.join(SETTABLE_KEYS)}")
    default = Config.__dataclass_fields__[key].default
    if isinstance(default, bool):
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"'{key}' expects true/false, got '{raw}'")
    if isinstance(default, int):
        return int(raw)
    return str(raw)


def _flat_toml(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = (s.strip() for s in line.split("=", 1))
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v.strip("\"'")
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib as toml  # type: ignore[import-not-found]
    except ImportError:
        try:
            import tomli as toml  # type: ignore[import-not-found,no-redef]
        except ImportError:
            return _flat_toml(text)
    return toml.loads(text)


def load_config(root: Path) -> Config:
    """Build a Config for ``root``, creating ``.quack/`` and ``.quack/cache/``."""
    root = Path(root).resolve()
    qd = root / ".quack"
    (qd / "cache").mkdir(parents=True, exist_ok=True)
    loaded_env = load_env_files(root)  # real env vars still win
    cfg = Config(
        env_files=loaded_env,
        root=root,
        quack_dir=qd,
        index_db_path=qd / "index.db",
        history_db_path=qd / "history.db",
        cache_dir=qd / "cache",
        tasks_md_path=root / "TASKS.md",
        history_md_path=root / "QUACK_HISTORY.md",
    )
    toml_path = qd / "config.toml"
    if toml_path.exists():
        try:
            data = _read_toml(toml_path)
            for k, v in data.items():
                if k in SETTABLE_KEYS:
                    setattr(cfg, k, coerce(k, v))
        except (ValueError, OSError) as e:
            raise QuackError(f"Invalid .quack/config.toml: {e}") from e
    for env, key in (("QUACK_PROVIDER", "provider"), ("QUACK_MODEL", "model"), ("QUACK_BASE_URL", "base_url")):
        if os.environ.get(env):
            setattr(cfg, key, os.environ[env])
    return cfg


def write_config_values(config: Config, updates: dict[str, Any]) -> None:
    """Persist ``updates`` into ``.quack/config.toml`` (flat TOML)."""
    path = config.quack_dir / "config.toml"
    assert_writable(path)
    data: dict[str, Any] = _read_toml(path) if path.exists() else {}
    for k, v in updates.items():
        data[k] = coerce(k, v)
    lines = ["# Quack config. Never put API keys here; use environment variables.\n"]
    for k, v in data.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}\n")
        elif isinstance(v, int):
            lines.append(f"{k} = {v}\n")
        else:
            lines.append(f"{k} = {json.dumps(str(v))}\n")
    path.write_text("".join(lines), encoding="utf-8")
