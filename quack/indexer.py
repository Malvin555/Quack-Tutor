"""Walk the repo and build .quack/index.db. Zero LLM tokens."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from . import gitutil
from .config import Config
from .models import IndexStats
from .redact import redact
from .safety import assert_writable
from .symbols import detect_language, extract_mentions, extract_symbols, extract_todos
from .walk import is_binary, iter_source_files, sha256_bytes

DDL = [
    "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, language TEXT NOT NULL, line_count INTEGER NOT NULL, hash TEXT NOT NULL, mtime REAL NOT NULL);",
    "CREATE TABLE IF NOT EXISTS symbols (id INTEGER PRIMARY KEY AUTOINCREMENT, file TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, signature TEXT NOT NULL);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);",
    "CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);",
    "CREATE TABLE IF NOT EXISTS mentions (file TEXT NOT NULL, term TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(file, term));",
    "CREATE INDEX IF NOT EXISTS idx_mentions_term ON mentions(term);",
    "CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, file TEXT NOT NULL, line INTEGER NOT NULL, text TEXT NOT NULL);",
]


def connect(db_path: Path) -> sqlite3.Connection:
    assert_writable(db_path)
    conn = sqlite3.connect(db_path)
    for stmt in DDL:
        conn.execute(stmt)
    return conn


def index_repo(
    root: Path,
    config: Config,
    since: str | None = None,
    changed_only: bool = False,
    progress: Callable[[str], None] | None = None,
) -> IndexStats:
    """Index ``root`` into ``config.index_db_path`` using only the filesystem and regex."""
    t0 = time.perf_counter()
    root = Path(root).resolve()
    emit = progress or (lambda _m: None)
    conn = connect(config.index_db_path)

    only: set[str] | None = None
    if since:
        only = gitutil.changed_files(root, since)
        if only is None:
            emit("warning: git not available for --since; doing a full index")

    existing = dict(conn.execute("SELECT path, hash FROM files").fetchall())
    hashes: dict[str, str] = {}
    n = 0
    for p in iter_source_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            continue
        n += 1
        if n % 100 == 0:
            emit(f"indexed {n} files...")
        h = sha256_bytes(data)
        hashes[rel] = h

        reindex = True
        if changed_only:
            reindex = existing.get(rel) != h
        if only is not None:
            reindex = reindex and (rel in only or rel not in existing)
        if not reindex:
            continue

        text = data.decode("utf-8", errors="replace")
        safe = redact(text)
        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        rel_path = Path(rel)
        for table, col in (("files", "path"), ("symbols", "file"), ("mentions", "file"), ("todos", "file")):
            conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (rel,))
        conn.execute(
            "INSERT INTO files VALUES (?,?,?,?,?)",
            (rel, detect_language(rel_path), line_count, h, p.stat().st_mtime),
        )
        conn.executemany(
            "INSERT INTO symbols (file,name,kind,start_line,end_line,signature) VALUES (?,?,?,?,?,?)",
            [(rel, s.name, s.kind, s.start_line, s.end_line, s.signature) for s in extract_symbols(rel_path, safe)],
        )
        conn.executemany(
            "INSERT INTO mentions VALUES (?,?,?)",
            [(rel, term, c) for term, c in extract_mentions(safe).items()],
        )
        conn.executemany(
            "INSERT INTO todos (file,line,text) VALUES (?,?,?)",
            [(rel, ln, txt) for ln, txt in extract_todos(safe)],
        )

    # Prune files that disappeared.
    for gone in set(existing) - set(hashes):
        for table, col in (("files", "path"), ("symbols", "file"), ("mentions", "file"), ("todos", "file")):
            conn.execute(f"DELETE FROM {table} WHERE {col} = ?", (gone,))
    conn.commit()

    count = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: E731
    stats = IndexStats(
        files=count("files"), symbols=count("symbols"), mentions=count("mentions"), todos=count("todos"),
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )
    conn.close()

    baseline = config.quack_dir / "last_hash.json"
    assert_writable(baseline)
    baseline.write_text(json.dumps(hashes, indent=0), encoding="utf-8")
    return stats
