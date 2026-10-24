import os

import pytest

from quack.config import load_config
from quack.envfile import parse_env
from quack.indexer import index_repo


@pytest.fixture()
def clean_env(monkeypatch, tmp_path):
    """Isolate os.environ so env-file loading can't leak between tests."""
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return os.environ


def test_parse_env_formats():
    env = parse_env('# c\nA=1\nexport B="two words"\nC=\'x\'\nD=val # comment\nbad line\n1X=no\n')
    assert env == {"A": "1", "B": "two words", "C": "x", "D": "val"}


def test_env_loaded_and_real_env_wins(repo, clean_env):
    (repo / ".env").write_text("QUACK_T_ONE=from_file\nQUACK_T_TWO=from_file\n")
    clean_env["QUACK_T_TWO"] = "from_shell"
    cfg = load_config(repo)
    assert clean_env["QUACK_T_ONE"] == "from_file" and clean_env["QUACK_T_TWO"] == "from_shell"
    assert cfg.env_files == [repo / ".env"]


def test_project_quack_env_beats_dotenv_and_user_file(repo, clean_env, tmp_path):
    (tmp_path / "xdg" / "quack").mkdir(parents=True)
    (tmp_path / "xdg" / "quack" / ".env").write_text("QUACK_T_P=user\nQUACK_T_Q=user\n")
    (repo / ".env").write_text("QUACK_T_P=dotenv\n")
    (repo / ".quack").mkdir(exist_ok=True)
    (repo / ".quack" / ".env").write_text("QUACK_T_P=quack\n")
    load_config(repo)
    assert clean_env["QUACK_T_P"] == "quack" and clean_env["QUACK_T_Q"] == "user"


def test_env_can_select_provider(repo, clean_env):
    (repo / ".env").write_text("QUACK_PROVIDER=groq\nQUACK_MODEL=llama-x\n")
    cfg = load_config(repo)
    assert (cfg.provider, cfg.model) == ("groq", "llama-x")


def test_secret_files_are_never_indexed(repo, clean_env):
    (repo / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnopqrstuvwxyz\n")
    (repo / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n")
    (repo / ".env.example").write_text("OPENROUTER_API_KEY=\n")
    cfg = load_config(repo)
    index_repo(repo, cfg)
    import sqlite3

    paths = {r[0] for r in sqlite3.connect(cfg.index_db_path).execute("SELECT path FROM files")}
    assert ".env" not in paths and "server.pem" not in paths and ".env.example" in paths
