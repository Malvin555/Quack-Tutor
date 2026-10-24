"""Mask secrets before text is indexed or sent to a model. Pure functions."""

from __future__ import annotations

import re

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
_KEY_VALUE = re.compile(
    r"""(?ix)
    \b(?P<key>[A-Za-z0-9_\-]*(?:api[_-]?key|secret|token|password)[A-Za-z0-9_\-]*)
    (?P<sep>\s*[=:]\s*)
    (?P<quote>["']?)
    (?P<value>[^\s"',;]+)
    """
)
_SIMPLE = [
    ("OPENAI_KEY", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("GITHUB_TOKEN", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("SLACK_TOKEN", re.compile(r"xox[baprs]-[A-Za-z0-9\-]+")),
    ("AWS_KEY", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GOOGLE_KEY", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("GROQ_KEY", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
]


def _mask(kind: str) -> str:
    return f"***REDACTED_{kind}***"


def _kv_sub(m: re.Match[str]) -> str:
    value = m.group("value")
    quoted = bool(m.group("quote"))
    if "REDACTED" in value or value.isdigit():
        return m.group(0)
    if not quoted:
        # Unquoted values are usually code (`token = get_token`). Only mask
        # values that look like real secrets: long, with letters and digits.
        looks_secret = (
            len(value) >= 12
            and any(c.isdigit() for c in value)
            and any(c.isalpha() for c in value)
            and re.fullmatch(r"[A-Za-z0-9_\-/+=.]+", value) is not None
        )
        if not looks_secret:
            return m.group(0)
    return f"{m.group('key')}{m.group('sep')}{m.group('quote')}{_mask('SECRET')}"


def redact(text: str) -> str:
    """Return ``text`` with secrets replaced by ``***REDACTED_<TYPE>***``."""

    def _pk(m: re.Match[str]) -> str:
        # Preserve line count so line numbers stay valid.
        return _mask("PRIVATE_KEY") + "\n" * m.group(0).count("\n")

    text = _PRIVATE_KEY.sub(_pk, text)
    for kind, pat in _SIMPLE:
        text = pat.sub(_mask(kind), text)
    return _KEY_VALUE.sub(_kv_sub, text)
