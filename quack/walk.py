"""Shared filesystem walking helpers (used by indexer and safety)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

SKIP_DIRS = frozenset(
    {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".quack", ".tox", "target"}
)
SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".tar", ".lock", ".ico", ".woff", ".woff2", ".pyc", ".db",
     ".pem", ".key", ".p12", ".pfx"}
)
SECRET_NAMES = frozenset({"id_rsa", "id_ed25519", "id_ecdsa", ".npmrc", ".pypirc", ".netrc"})
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template")


def _is_secret_file(name: str) -> bool:
    """Never index real .env files or key material (templates like .env.example are fine)."""
    if name in SECRET_NAMES:
        return True
    return name.startswith(".env") and not name.endswith(_ENV_TEMPLATE_SUFFIXES)
GENERATED_FILES = frozenset({"TASKS.md", "QUACK_HISTORY.md"})
MAX_BYTES = 500 * 1024


def iter_source_files(root: Path) -> Iterator[Path]:
    """Yield indexable files under ``root`` in a stable order."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if name in GENERATED_FILES or name.endswith(".min.js") or _is_secret_file(name):
                continue
            if p.suffix.lower() in SKIP_SUFFIXES:
                continue
            try:
                if p.is_symlink() or p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:1024]
