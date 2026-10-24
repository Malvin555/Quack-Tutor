"""BM25 + symbol-name bonus over the index. No embeddings."""

from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .models import FileRecord
from .symbols import tokenize

K1 = 1.5
B = 0.75
SYMBOL_BONUS = 2.0
SYMBOL_BONUS_CAP = 6.0
PATH_BONUS = 1.5
PATH_BONUS_CAP = 3.0
SYNONYMS: dict[str, list[str]] = {
    "login": ["auth", "session"],
    "auth": ["login", "session", "token"],
    "db": ["database", "sql"],
    "api": ["route", "endpoint", "handler"],
    "config": ["settings", "env"],
}


def get_record(db_path: Path, rel: str, score: float = 0.0) -> FileRecord | None:
    """Look up one file in the index."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT path, language, line_count, hash FROM files WHERE path = ?", (rel,)).fetchone()
    finally:
        conn.close()
    return FileRecord(path=row[0], language=row[1], line_count=row[2], hash=row[3], score=score) if row else None


def rank(query: str, db_path: Path, k: int = 3) -> list[FileRecord]:
    """Return the top-``k`` files for ``query`` (score > 0 only)."""
    qtokens = list(dict.fromkeys(tokenize(query, min_len=2)))
    if not qtokens or not Path(db_path).exists():
        return []
    weights = {t: 1.0 for t in qtokens}
    for t in qtokens:
        for s in SYNONYMS.get(t, []):
            weights.setdefault(s, 0.6)

    conn = sqlite3.connect(db_path)
    try:
        n_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if not n_files:
            return []
        dl = dict(conn.execute("SELECT file, SUM(count) FROM mentions GROUP BY file").fetchall())
        avgdl = (sum(dl.values()) / len(dl)) if dl else 1.0
        terms = list(weights)
        ph = ",".join("?" * len(terms))
        rows = conn.execute(f"SELECT file, term, count FROM mentions WHERE term IN ({ph})", terms).fetchall()
        df = Counter(term for _f, term, _c in rows)
        scores: dict[str, float] = defaultdict(float)
        for file, term, f in rows:
            idf = math.log((n_files - df[term] + 0.5) / (df[term] + 0.5) + 1)
            d = dl.get(file, avgdl)
            scores[file] += weights[term] * idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * d / avgdl))

        ph2 = ",".join("?" * len(qtokens))
        matched: dict[str, set[str]] = defaultdict(set)
        for file, name in conn.execute(f"SELECT file, lower(name) FROM symbols WHERE lower(name) IN ({ph2})", qtokens):
            matched[file].add(name)
        for file, names in matched.items():
            scores[file] += min(SYMBOL_BONUS * len(names), SYMBOL_BONUS_CAP)

        qset = set(qtokens)
        for (path,) in conn.execute("SELECT path FROM files").fetchall():
            hits = len(qset & set(tokenize(path, min_len=2)))
            if hits:
                scores[path] += min(PATH_BONUS * hits, PATH_BONUS_CAP)

        top = sorted(((s, p) for p, s in scores.items() if s > 0), reverse=True)[:k]
        out: list[FileRecord] = []
        for score, path in top:
            row = conn.execute(
                "SELECT path, language, line_count, hash FROM files WHERE path = ?", (path,)
            ).fetchone()
            if row:
                out.append(FileRecord(path=row[0], language=row[1], line_count=row[2], hash=row[3], score=round(score, 4)))
        return out
    finally:
        conn.close()
