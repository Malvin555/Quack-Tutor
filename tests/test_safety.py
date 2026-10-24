from pathlib import Path

import pytest

from quack.config import load_config
from quack.indexer import index_repo
from quack.safety import SafetyError, assert_writable, audit_write_sites, verify_no_source_changes


def test_rejects_source_file():
    with pytest.raises(SafetyError):
        assert_writable(Path("src/app.py"))


def test_accepts_allowlist():
    assert_writable(Path("TASKS.md"))
    assert_writable(Path("QUACK_HISTORY.md"))
    assert_writable(Path("/repo/.quack/index.db"))


def test_verify_clean_then_detects_drift(repo):
    cfg = load_config(repo)
    index_repo(repo, cfg)
    assert verify_no_source_changes(repo) == (True, [])
    (repo / "api.py").write_text("# tampered\n")
    ok, changed = verify_no_source_changes(repo)
    assert not ok and any("api.py" in c for c in changed)


def test_audit_lists_write_sites():
    pkg = Path(__file__).parent.parent / "quack"
    sites = audit_write_sites(pkg)
    assert any("tasks.py" in s for s in sites)
