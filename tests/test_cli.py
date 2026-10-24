"""End-to-end CLI tests with a fake LLM. No network, no model."""

import json

import pytest
from typer.testing import CliRunner

from quack import cli
from quack.errors import ProviderError

from .conftest import FakeLLM

runner = CliRunner()


def run(repo, *args, **kw):
    return runner.invoke(cli.app, ["-C", str(repo), *args], **kw)


@pytest.fixture()
def fake(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(cli, "build_client", lambda *a, **k: llm)
    return llm


def test_help_lists_commands():
    out = runner.invoke(cli.app, ["--help"]).output
    for name in ("index", "ask", "explain", "review", "tasks", "history", "verify",
                 "init", "providers", "doctor", "config", "export", "cache"):
        assert name in out


def test_full_pipeline_cache_and_verify(repo, fake):
    before = {p.name: p.read_text() for p in repo.glob("*.py")}
    r = run(repo, "ask", "why does session_valid reject valid sessions?")
    assert r.exit_code == 0, r.output
    assert "1234 tokens" in r.output
    tasks_md = (repo / "TASKS.md").read_text()
    assert "auth.py:24" in tasks_md and "does_not_exist" not in tasks_md

    r2 = run(repo, "ask", "why does session_valid reject valid sessions?")
    assert "cached, 0 tokens" in r2.output and fake.calls == 1

    v = run(repo, "verify")
    assert v.exit_code == 0 and "PASS" in v.output
    assert before == {p.name: p.read_text() for p in repo.glob("*.py")}

    h = run(repo, "history")
    assert "Questions asked: 2" in h.output
    e = run(repo, "export", "-o", "-")
    assert "session_valid" in e.output


def test_json_output(repo, fake):
    r = run(repo, "ask", "login bug", "--json")
    data = json.loads(r.output[r.output.index("{"):])
    assert data["tokens"] == 1234 and data["tasks"][0]["file"] == "auth.py"


def test_provider_down_exits_2_and_writes_nothing(repo, monkeypatch):
    class Down:
        label = "ollama:gemma3:4b"
        last_tokens = 0

        def complete(self, s, u):
            raise ProviderError("Ollama is not reachable")

    monkeypatch.setattr(cli, "build_client", lambda *a, **k: Down())
    r = run(repo, "ask", "why does login fail")
    assert r.exit_code == 2 and "not reachable" in r.output
    assert not (repo / "TASKS.md").exists() and not (repo / "QUACK_HISTORY.md").exists()


def test_remote_provider_needs_opt_in(repo, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    r = run(repo, "ask", "why does login fail", "--provider", "openrouter")
    assert r.exit_code == 2 and "blocked" in r.output


def test_dry_run_writes_no_tasks(repo, fake):
    r = run(repo, "ask", "login bug", "--dry-run")
    assert r.exit_code == 0 and "source files: never" in r.output
    assert fake.calls == 0 and not (repo / "TASKS.md").exists()


def test_stdin_traceback_pins_file(repo, fake):
    tb = f'Traceback...\n  File "{repo}/api.py", line 12, in run_query\nsqlite3.OperationalError: no such table'
    r = run(repo, "ask", "why does this crash", "--stdin", "--dry-run", input=tb)
    assert "api.py" in r.output


def test_init_openrouter_then_config(repo):
    r = run(repo, "init", "--provider", "openrouter", "--fallback", "ollama")
    assert r.exit_code == 0 and "remote" in r.output
    assert run(repo, "config", "get", "allow_remote").output.strip() == "True"
    assert run(repo, "config", "get", "provider").output.strip() == "openrouter"
    assert run(repo, "config", "set", "depth", "3").exit_code == 0
    assert run(repo, "config", "set", "nope", "1").exit_code == 1


def test_init_local_stays_local(repo):
    run(repo, "init", "--provider", "ollama")
    assert run(repo, "config", "get", "allow_remote").output.strip() == "False"


def test_explain_no_llm_and_tasks_empty(repo):
    r = run(repo, "explain", "auth.py", "--no-llm")
    assert r.exit_code == 0 and "check_password" in r.output
    assert "No tasks yet." in run(repo, "tasks").output


def test_review_dry_run(repo, fake):
    r = run(repo, "review", "--dry-run", "--max-files", "2")
    assert r.exit_code == 0 and "Dry run" in r.output and fake.calls == 0


def test_compare_runs_each_target_and_writes_no_tasks(repo, monkeypatch):
    llms = {"ollama": FakeLLM(tokens=500), "groq": FakeLLM(tokens=900)}
    llms["ollama"].label, llms["groq"].label = "ollama:gemma3:4b", "groq:llama"

    def fake_build(cfg, provider=None, model=None, allow_remote=None):
        if provider == "broken":
            raise ProviderError("no key for broken")
        return llms[provider]

    monkeypatch.setattr(cli, "build_client", fake_build)
    r = run(repo, "compare", "why does session_valid fail", "-w", "ollama", "-w", "groq", "-w", "broken")
    assert r.exit_code == 0, r.output
    for text in ("ollama:gemma3:4b", "groq:llama", "500", "900", "no key for broken"):
        assert text in r.output
    assert not (repo / "TASKS.md").exists()
    j = run(repo, "compare", "login bug", "-w", "ollama", "--json")
    assert '"tokens": 500' in j.output


def test_chat_keeps_memory_and_writes_tasks(repo, monkeypatch):
    seen = []

    class Spy(FakeLLM):
        def complete(self, system, user):
            seen.append(user)
            return super().complete(system, user)

    llm = Spy()
    monkeypatch.setattr(cli, "build_client", lambda *a, **k: llm)
    r = run(repo, "chat", input="why does session_valid fail\n/depth 1\nand what about login?\n/quit\n")
    assert r.exit_code == 0, r.output
    assert len(seen) == 2 and "Earlier question: why does session_valid fail" in seen[1]
    assert "auth.py:24" in (repo / "TASKS.md").read_text()


def test_doctor_reports_env_files(repo, monkeypatch):
    import os

    monkeypatch.setattr(os, "environ", dict(os.environ))  # keep the .env load from leaking
    (repo / ".env").write_text("QUACK_T_DOCTOR=1\n")
    out = run(repo, "doctor").output
    assert ".env files" in out and "repo" in out


def test_cache_and_providers_commands(repo, fake):
    run(repo, "ask", "login bug")
    assert "1 cached" in run(repo, "cache", "stats").output
    assert "cleared 1" in run(repo, "cache", "clear").output
    assert "openrouter" in run(repo, "providers").output


def test_bare_quack_shows_cheatsheet():
    r = runner.invoke(cli.app, [])
    assert r.exit_code == 0 and "quack ask" in r.output and "quack doctor" in r.output


def test_piped_output_has_no_box_drawing_or_ansi(repo, fake):
    r = run(repo, "ask", "login bug")
    assert "\x1b[" not in r.output and "╭" not in r.output and "Quack asks" in r.output


def test_chat_slash_commands(repo, monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr(cli, "build_client", lambda *a, **k: llm)
    r = run(repo, "chat", input="/help\nwhy does session_valid fail\n/files\n/verify\n/model nope\n/clear\n/bogus\n/quit\n")
    assert r.exit_code == 0, r.output
    assert "/clear" in r.output                     # help text
    assert "reading: " in r.output and "auth.py" in r.output
    assert "PASS" in r.output and "unknown command /bogus" in r.output
    assert "1 question(s), 1234 tokens" in r.output


def test_mascot_moods_and_command():
    from quack import ui

    assert set(ui.MOODS) == {"idle", "happy", "think", "worried", "no"}
    assert all(len(art) == 4 for art in ui.MOODS.values())
    r = runner.invoke(cli.app, ["duck"])
    assert r.exit_code == 0 and "( ^)>" in r.output and "( x)>" in r.output
