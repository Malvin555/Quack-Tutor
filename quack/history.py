"""Log queries and concepts; produce QUACK_HISTORY.md and session exports."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .models import TutorResponse
from .safety import assert_writable

DDL = [
    "CREATE TABLE IF NOT EXISTS queries (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, question TEXT NOT NULL, files TEXT NOT NULL, tokens INTEGER NOT NULL, task_ids TEXT NOT NULL);",
    "CREATE TABLE IF NOT EXISTS concepts (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tag TEXT NOT NULL);",
    "CREATE TABLE IF NOT EXISTS completed (task_id TEXT PRIMARY KEY, completed_at REAL NOT NULL);",
    "CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, command TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, question TEXT NOT NULL, explanation TEXT NOT NULL, tasks_json TEXT NOT NULL, tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL, cached INTEGER NOT NULL);",
]
LESSONS = {
    "async": "Async/await in Python",
    "timezone": "Timezone-aware datetimes",
    "auth": "Session and token handling",
    "sql": "Parameterized SQL and indexing",
    "error": "Exception handling patterns",
}


def _connect(db: Path) -> sqlite3.Connection:
    assert_writable(db)
    conn = sqlite3.connect(db)
    for stmt in DDL:
        conn.execute(stmt)
    return conn


def _norm(tag: str) -> str:
    return "-".join(tag.lower().split())


def log_query(
    history_db: Path, question: str, files: list[str], tokens: int, task_ids: list[str], concepts: list[str],
) -> None:
    conn = _connect(history_db)
    now = time.time()
    with conn:
        conn.execute(
            "INSERT INTO queries (ts, question, files, tokens, task_ids) VALUES (?,?,?,?,?)",
            (now, question, json.dumps(files), tokens, json.dumps(task_ids)),
        )
        conn.executemany("INSERT INTO concepts (ts, tag) VALUES (?,?)", [(now, _norm(c)) for c in concepts if c.strip()])
    conn.close()


def log_session(
    history_db: Path, command: str, provider: str, model: str, question: str, resp: TutorResponse,
    tokens: int, latency_ms: int, cached: bool,
) -> None:
    """Keep a readable transcript (used by `quack export`)."""
    conn = _connect(history_db)
    with conn:
        conn.execute(
            "INSERT INTO sessions (ts, command, provider, model, question, explanation, tasks_json, tokens, latency_ms, cached) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (time.time(), command, provider, model, question,
             f"Q: {resp.socratic_question}\n\n{resp.explanation}",
             json.dumps([t.model_dump() for t in resp.tasks]), tokens, latency_ms, int(cached)),
        )
    conn.close()


def sync_completed(history_db: Path, completed_ids: list[str]) -> None:
    conn = _connect(history_db)
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO completed (task_id, completed_at) VALUES (?,?)",
            [(i, time.time()) for i in completed_ids],
        )
    conn.close()


def write_history_md(history_db: Path, out_path: Path, days: int = 7) -> None:
    assert_writable(out_path)
    conn = _connect(history_db)
    since = time.time() - days * 86400
    queries = conn.execute("SELECT files, tokens FROM queries WHERE ts >= ?", (since,)).fetchall()
    resolved = conn.execute("SELECT COUNT(*) FROM completed WHERE completed_at >= ?", (since,)).fetchone()[0]
    tags = Counter(t for (t,) in conn.execute("SELECT tag FROM concepts WHERE ts >= ?", (since,)).fetchall())
    conn.close()

    files: Counter[str] = Counter()
    for raw, _tok in queries:
        files.update(json.loads(raw))
    lines = [
        "# Quack History", "",
        f"*Generated {datetime.now():%Y-%m-%d %H:%M}. The duck never modifies your code.*", "",
        "## This week", "",
        f"- Questions asked: {len(queries)}",
        f"- Tokens spent: {sum(t for _f, t in queries)}",
        f"- Tasks resolved: {resolved}",
        "- Most-reviewed files:",
    ]
    lines += [f"  {i}. `{f}` ({n}x)" for i, (f, n) in enumerate(files.most_common(3), 1)] or ["  - none yet"]
    lines.append("- Concepts:")
    lines += [f"  - {t} x{n}" for t, n in tags.most_common(5)] or ["  - none yet"]
    lines += ["", "## Mini-lessons suggested", ""]
    lessons = [
        f"- {title} ({tag} x{n})"
        for key, title in LESSONS.items()
        for tag, n in tags.items() if key in tag and n >= 3
    ]
    lines += lessons or ["- Nothing yet. Concepts appearing 3+ times will show up here."]
    Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_session_log(history_db: Path, days: int = 30) -> str:
    """Render the session transcript as readable text (for sharing, e.g. with Entire)."""
    conn = _connect(history_db)
    rows = conn.execute(
        "SELECT ts, command, provider, model, question, explanation, tasks_json, tokens, latency_ms, cached "
        "FROM sessions WHERE ts >= ? ORDER BY ts", (time.time() - days * 86400,),
    ).fetchall()
    conn.close()
    out = ["# Quack session log", ""]
    for ts, cmd, prov, model, q, expl, tasks_json, tok, ms, cached in rows:
        out += [
            f"## {datetime.fromtimestamp(ts):%Y-%m-%d %H:%M} — quack {cmd}",
            f"- Provider: {prov}:{model} | tokens: {tok}{' (cached)' if cached else ''} | latency: {ms} ms",
            f"- Asked: {q}", "", expl, "",
        ]
        for t in json.loads(tasks_json):
            out.append(f"- [{t['severity']}] `{t['file']}:{t['line']}` {t['description']}")
        out.append("")
    if not rows:
        out.append("No sessions recorded yet.")
    return "\n".join(out) + "\n"
