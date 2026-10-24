"""Build a compact context string from top files + line windows."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .models import FileRecord
from .redact import redact
from .symbols import extract_symbols, tokenize

LINE_CAPS = {1: 30, 2: 80, 3: 150}
SYMBOL_MARGIN = {1: 2, 2: 10, 3: 15}
HEAD_LINES = 30
TERM_MARGIN = 20

_TRACE_PY = re.compile(r'File "(?P<f>[^"]+)", line (?P<n>\d+)')
_PATH_LINE = re.compile(r"(?P<f>[\w./\\\-]+\.(?:py|js|jsx|ts|tsx|go|rs|java|rb))(?::(?P<n>\d+))?")
_LINE_NUM = re.compile(r"(?:\bline\s+|:)(\d+)\b", re.I)


def extract_file_refs(text: str, root: Path, db_path: Path | None = None) -> dict[str, list[int]]:
    """Find repo files (and line numbers) mentioned in ``text``, e.g. in a traceback."""
    root = Path(root).resolve()
    candidates: list[tuple[str, int | None]] = []
    for m in _TRACE_PY.finditer(text):
        candidates.append((m.group("f"), int(m.group("n"))))
    for m in _PATH_LINE.finditer(text):
        candidates.append((m.group("f"), int(m.group("n")) if m.group("n") else None))

    conn = sqlite3.connect(db_path) if db_path and Path(db_path).exists() else None
    refs: dict[str, list[int]] = {}
    try:
        for cand, line in candidates:
            rel = _resolve(cand, root, conn)
            if rel is None:
                continue
            lines = refs.setdefault(rel, [])
            if line is not None and line not in lines:
                lines.append(line)
    finally:
        if conn:
            conn.close()
    return refs


def _resolve(cand: str, root: Path, conn: sqlite3.Connection | None) -> str | None:
    cand = cand.replace("\\", "/")
    p = Path(cand)
    try:
        if p.is_absolute():
            rel = p.resolve().relative_to(root)
            return rel.as_posix() if (root / rel).is_file() else None
        full = (root / p).resolve()
        full.relative_to(root)
        if full.is_file():
            return full.relative_to(root).as_posix()
    except (ValueError, OSError):
        pass
    if conn is not None:
        row = conn.execute(
            "SELECT path FROM files WHERE path = ? OR path LIKE ? LIMIT 1", (cand, "%/" + cand)
        ).fetchone()
        if row:
            return row[0]
    return None


def _merge(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(windows):
        if out and s <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def build_context(
    root: Path,
    files: list[FileRecord],
    query: str,
    depth: int,
    db_path: Path | None = None,  # kept for API symmetry; symbols are re-extracted on the fly
    focus_lines: dict[str, list[int]] | None = None,
) -> str:
    """Return ``### QUERY`` + per-file numbered line windows. Never reads a whole large file."""
    root = Path(root).resolve()
    depth = depth if depth in LINE_CAPS else 2
    cap, margin = LINE_CAPS[depth], SYMBOL_MARGIN[depth]
    qterms = set(tokenize(query, min_len=2))
    query_lines = {int(n) for n in _LINE_NUM.findall(query)}
    parts = [f"### QUERY: {query}\n"]

    for rec in files:
        full = (root / rec.path).resolve()
        try:
            full.relative_to(root)
            text = full.read_text(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue
        lines = text.splitlines()
        total = len(lines)
        if not total:
            continue
        focus = set((focus_lines or {}).get(rec.path, [])) | query_lines

        windows: list[tuple[int, int]] = []
        for sym in extract_symbols(Path(rec.path), text):
            name_terms = set(tokenize(sym.name, min_len=2)) | {sym.name.lower()}
            hit_name = bool(qterms & name_terms)
            hit_line = any(sym.start_line <= ln <= sym.end_line for ln in focus)
            if hit_name or hit_line:
                windows.append((max(1, sym.start_line - margin), min(total, sym.end_line + margin)))
        if not windows:
            windows.append((1, min(total, HEAD_LINES)))
            for i, line in enumerate(lines, 1):
                if qterms & set(tokenize(line, min_len=2)):
                    windows.append((max(1, i - TERM_MARGIN), min(total, i + TERM_MARGIN)))
        for ln in focus:
            if 1 <= ln <= total:
                windows.append((max(1, ln - margin), min(total, ln + margin)))

        budget = cap
        for s, e in _merge(windows):
            if budget <= 0:
                break
            e = min(e, s + budget - 1)
            budget -= e - s + 1
            body = "\n".join(f"{n:>4}| {lines[n - 1]}" for n in range(s, e + 1))
            parts.append(f"### FILE: {rec.path} (lines {s}-{e})\n{body}\n")
    return redact("\n".join(parts))
