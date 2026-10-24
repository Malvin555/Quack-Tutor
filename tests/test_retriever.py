from quack.config import load_config
from quack.context import build_context, extract_file_refs
from quack.indexer import index_repo
from quack.retriever import rank


def _index(repo):
    cfg = load_config(repo)
    stats = index_repo(repo, cfg)
    return cfg, stats


def test_index_counts(repo):
    _cfg, stats = _index(repo)
    assert stats.files >= 3 and stats.symbols >= 3 and stats.mentions > 0 and stats.todos > 0


def test_rank_auth_login(repo):
    cfg, _ = _index(repo)
    top = [r.path for r in rank("auth login", cfg.index_db_path, k=3)]
    assert "auth.py" in top[:2]


def test_rank_database_query(repo):
    cfg, _ = _index(repo)
    assert "api.py" in [r.path for r in rank("database query", cfg.index_db_path, k=3)]


def test_rank_nothing_matches(repo):
    cfg, _ = _index(repo)
    assert rank("zzzzqqqq", cfg.index_db_path) == []


def test_changed_only_reindexes_only_modified(repo):
    cfg, _ = _index(repo)
    (repo / "auth.py").write_text((repo / "auth.py").read_text() + "\ndef extra():\n    pass\n")
    stats = index_repo(repo, cfg, changed_only=True)
    assert stats.symbols >= 6


def test_context_is_windowed_and_redacted(repo):
    cfg, _ = _index(repo)
    (repo / "auth.py").write_text((repo / "auth.py").read_text() + '\nAPI_KEY = "sk-' + "a1B2" * 8 + '"\n')
    index_repo(repo, cfg, changed_only=True)
    files = rank("session_valid expiry", cfg.index_db_path, k=2)
    ctx = build_context(repo, files, "session_valid expiry", depth=1)
    assert "### FILE: auth.py" in ctx and "session_valid" in ctx
    assert "sk-a1B2" not in ctx


def test_traceback_refs(repo):
    cfg, _ = _index(repo)
    tb = f'File "{repo}/auth.py", line 24, in session_valid\n  File "/usr/lib/python3/os.py", line 3'
    refs = extract_file_refs(tb, repo, cfg.index_db_path)
    assert refs == {"auth.py": [24]}
