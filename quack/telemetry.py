"""Optional tracing: a local JSONL log, plus Sentry spans if explicitly enabled.

Off by default. Only tokens, latency, provider and model are recorded; never
prompts, code or answers. Sentry requires ``sentry = true`` in config, the
``sentry-sdk`` package and a ``SENTRY_DSN`` environment variable.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

from .config import Config
from .safety import assert_writable

_sentry_ready = False


def _sentry(config: Config) -> Any | None:
    global _sentry_ready
    if not (config.sentry and os.environ.get("SENTRY_DSN")):
        return None
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        return None
    if not _sentry_ready:
        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], traces_sample_rate=1.0, send_default_pii=False)
        _sentry_ready = True
    return sentry_sdk


@contextmanager
def span(config: Config, op: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    """Record an operation. Mutate the yielded dict to add attributes (tokens, cached, ...)."""
    rec: dict[str, Any] = {"op": op, **attrs}
    t0 = time.perf_counter()
    sdk = _sentry(config)
    cm = None
    try:
        cm = sdk.start_span(op=f"quack.{op}", name=op) if sdk else None
        if cm:
            cm.__enter__()
    except Exception:  # noqa: BLE001 - tracing must never break the tool
        cm = None
    try:
        yield rec
    finally:
        rec["ms"] = int((time.perf_counter() - t0) * 1000)
        if cm:
            try:
                for k, v in rec.items():
                    cm.set_data(k, v)
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        if config.trace:
            path = config.quack_dir / "trace.jsonl"
            assert_writable(path)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), **rec}) + "\n")
