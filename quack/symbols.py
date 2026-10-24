"""Regex-based symbol extraction. Pure functions, no I/O."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .models import Symbol

_LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "javascript", ".tsx": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby",
}

STOPWORDS = frozenset(
    "a an the is are was were be been to of in on for and or not it this that with as if else return def class "
    "function var let const new".split()
)

_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    lang: [re.compile(p) for p in pats]
    for lang, pats in {
        "python": [r"^(?P<indent>\s*)(async\s+def|def|class)\s+(?P<name>\w+)"],
        "javascript": [
            r"^(?P<indent>\s*)(export\s+)?(async\s+)?(function|class)\s+(?P<name>\w+)",
            r"^(?P<indent>\s*)(const|let|var)\s+(?P<name>\w+)\s*=\s*(\([^)]*\)\s*=>|function|async)",
        ],
        "go": [
            r"^(?P<indent>\s*)func\s+(\([^)]*\)\s+)?(?P<name>\w+)",
            r"^(?P<indent>\s*)type\s+(?P<name>\w+)\s+(struct|interface)",
        ],
        "rust": [
            r"^(?P<indent>\s*)(pub\s+)?(async\s+)?fn\s+(?P<name>\w+)",
            r"^(?P<indent>\s*)(pub\s+)?(struct|enum|trait)\s+(?P<name>\w+)",
        ],
        "ruby": [r"^(?P<indent>\s*)(def|class|module)\s+(?P<name>\w+)"],
        "java": [
            r"^(?P<indent>\s*)(public|private|protected)?\s*(static\s+)?(class|interface|enum)\s+(?P<name>\w+)",
            r"^(?P<indent>\s*)(public|private|protected)\s+(?:static\s+|final\s+)*[\w<>\[\]]+\s+(?P<name>\w+)\s*\(",
        ],
    }.items()
}
_CLASS_WORDS = re.compile(r"\b(class|struct|interface|enum|trait|module|type)\b")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_TODO = re.compile(r"(?i)\b(TODO|FIXME|XXX|HACK)\b")


def detect_language(path: Path) -> str:
    return _LANG_BY_EXT.get(Path(path).suffix.lower(), "other")


def tokenize(text: str, min_len: int = 3) -> list[str]:
    """Lowercase tokens plus snake_case / camelCase sub-tokens, minus stopwords."""
    out: list[str] = []
    for w in _WORD.findall(text):
        lw = w.lower()
        subs = [p.lower() for chunk in w.split("_") for p in _CAMEL.findall(chunk)]
        for tok in [lw] + [s for s in subs if s != lw]:
            if len(tok) >= min_len and tok not in STOPWORDS and not tok.isdigit():
                out.append(tok)
    return out


def extract_symbols(path: Path, text: str) -> list[Symbol]:
    """Find top-level and nested definitions with start/end lines."""
    pats = _PATTERNS.get(detect_language(path))
    if not pats:
        return []
    lines = text.splitlines()
    found: list[tuple[int, int, str, str, str]] = []
    for i, line in enumerate(lines, 1):
        for pat in pats:
            m = pat.match(line)
            if m:
                prefix = line[m.start():m.start("name")]
                kind = "class" if _CLASS_WORDS.search(prefix) else "function"
                found.append((i, len(m.group("indent").expandtabs(4)), m.group("name"), kind, line.strip()))
                break
    out: list[Symbol] = []
    for idx, (ln, ind, name, kind, sig) in enumerate(found):
        end = len(lines)
        for nxt in found[idx + 1:]:
            if nxt[1] <= ind:
                end = nxt[0] - 1
                break
        while end > ln and not lines[end - 1].strip():
            end -= 1
        out.append(
            Symbol(file=Path(path).as_posix(), name=name, kind=kind, start_line=ln, end_line=end, signature=sig)
        )
    return out


def extract_mentions(text: str) -> dict[str, int]:
    """Term frequencies used for BM25."""
    return dict(Counter(tokenize(text)))


def extract_todos(text: str) -> list[tuple[int, str]]:
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1) if _TODO.search(line)]
