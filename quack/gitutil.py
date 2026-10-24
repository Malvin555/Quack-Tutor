"""Read-only git helpers. GitPython if installed, plain `git` otherwise."""

from __future__ import annotations

import subprocess
from pathlib import Path


def changed_files(root: Path, since: str) -> set[str] | None:
    """Files changed (or untracked) relative to ``since``; ``None`` if git is unavailable."""
    root = Path(root)
    try:
        import git  # type: ignore[import-not-found]

        g = git.Git(str(root))
        names = set(g.diff("--name-only", "--relative", since).splitlines())
        names |= set(g.ls_files("--others", "--exclude-standard").splitlines())
        return {n for n in names if n}
    except Exception:  # noqa: BLE001 - any failure falls through to subprocess
        pass
    try:
        a = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "--relative", since],
            capture_output=True, text=True, timeout=30, check=True,
        )
        b = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return {n for n in (a.stdout.splitlines() + b.stdout.splitlines()) if n}
