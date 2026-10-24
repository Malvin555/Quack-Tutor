"""Read-only enforcement and `quack verify`."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .walk import is_binary, iter_source_files, sha256_bytes

ALLOWED_WRITES: frozenset[str] = frozenset({"TASKS.md", "QUACK_HISTORY.md"})


class SafetyError(Exception):
    """Raised when something tries to write outside the allowlist."""


def assert_writable(path: Path) -> None:
    """Allow only TASKS.md, QUACK_HISTORY.md and anything under ``.quack/``."""
    path = Path(path)
    if path.name in ALLOWED_WRITES or ".quack" in path.parts:
        return
    raise SafetyError(f"Quack refuses to write {path}: only TASKS.md, QUACK_HISTORY.md and .quack/ are writable.")


def _is_generated(rel: str) -> bool:
    parts = Path(rel).parts
    return bool(parts) and (parts[0] == ".quack" or Path(rel).name in ALLOWED_WRITES)


def verify_no_source_changes(root: Path) -> tuple[bool, list[str]]:
    """Return ``(clean, changed_paths)``.

    Uses ``git status --porcelain`` when ``root`` is a git repo, otherwise
    compares file hashes with the baseline recorded at last index time.
    """
    root = Path(root).resolve()
    if (root / ".git").exists():
        try:
            res = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        else:
            changed: list[str] = []
            for line in res.stdout.splitlines():
                path = line[3:].strip().strip('"')
                if " -> " in path:
                    path = path.split(" -> ")[-1]
                if not _is_generated(path):
                    changed.append(path)
            return (not changed, changed)

    baseline_path = root / ".quack" / "last_hash.json"
    if not baseline_path.exists():
        return (True, [])
    baseline: dict[str, str] = json.loads(baseline_path.read_text(encoding="utf-8"))
    current: dict[str, str] = {}
    for p in iter_source_files(root):
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            continue
        current[p.relative_to(root).as_posix()] = sha256_bytes(data)
    drift = [f"{rel} (modified)" for rel, h in baseline.items() if rel in current and current[rel] != h]
    drift += [f"{rel} (deleted)" for rel in baseline if rel not in current]
    return (not drift, sorted(drift))


_WRITE_SITE = re.compile(
    r"""open\([^)]*,\s*['"][wax]b?\+?['"]|\.write_text\(|\.write_bytes\(|\.unlink\(|os\.(?:remove|rename)\(|shutil\.(?:rmtree|move|copy)"""
)


def audit_write_sites(package_root: Path) -> list[str]:
    """List every place in the package that can write to disk."""
    sites: list[str] = []
    for py in sorted(Path(package_root).rglob("*.py")):
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if _WRITE_SITE.search(line):
                sites.append(f"{py.name}:{n}: {line.strip()}")
    return sites
