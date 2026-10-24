import json

import pytest

from quack.config import load_config
from quack.errors import TutorError
from quack.tutor import ask, cache_get, cache_key, cache_put, ground, parse_response

from .conftest import CANNED, FakeLLM


def test_ask_grounds_invented_files(repo, fake_llm):
    cfg = load_config(repo)
    resp, tokens = ask(fake_llm, "why is login failing", "### FILE: auth.py", cfg)
    assert tokens == 1234
    assert [t.file for t in resp.tasks] == ["auth.py"]


def test_all_invented_tasks_lowers_confidence(repo):
    payload = {**CANNED, "tasks": [CANNED["tasks"][1]]}
    resp, _ = ask(FakeLLM(payload), "q", "ctx", load_config(repo))
    assert resp.tasks == [] and resp.confidence == "low"


def test_parse_tolerates_fences_and_missing_optionals():
    raw = "```json\n" + json.dumps({"socratic_question": "Why?", "explanation": "Because."}) + "\n```"
    resp = parse_response(raw)
    assert resp.tasks == [] and resp.confidence == "low" and resp.related_files == []


def test_parse_rejects_garbage():
    with pytest.raises(TutorError):
        parse_response("not json at all")


def test_context_is_trimmed_to_budget(repo, fake_llm):
    cfg = load_config(repo)
    cfg.max_tokens_per_ask = 1500
    seen = {}
    fake_llm.complete = lambda s, u: (seen.setdefault("u", u), json.dumps(CANNED))[1]
    ask(fake_llm, "q", "x" * 50_000, cfg)
    assert len(seen["u"]) < 5000


def test_clamps_line_numbers(repo):
    resp = parse_response(json.dumps({**CANNED, "tasks": [{**CANNED["tasks"][0], "line": 9999}]}))
    assert ground(resp, repo).tasks[0].line < 9999


def test_cache_roundtrip_and_ttl(repo, tmp_path):
    cfg = load_config(repo)
    resp = parse_response(json.dumps(CANNED))
    key = cache_key("q", 2, ["b", "a"], "m")
    assert key == cache_key("q", 2, ["a", "b"], "m")
    assert cache_get(key, cfg.cache_dir, 60) is None
    cache_put(key, resp, 10, cfg.cache_dir)
    assert cache_get(key, cfg.cache_dir, 60) == resp
    assert cache_get(key, cfg.cache_dir, -1) is None
