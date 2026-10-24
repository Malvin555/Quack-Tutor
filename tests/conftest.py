"""Shared fixtures: a throwaway copy of mini_repo and a fake LLM client."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "mini_repo"

CANNED = {
    "socratic_question": "What should happen when the stored expiry is later than the current time?",
    "explanation": "Quack. session_valid compares the expiry with '<' so live sessions look expired (auth.py:24).",
    "tasks": [
        {"file": "auth.py", "line": 24, "severity": "critical",
         "description": "Flip the comparison in session_valid", "why": "Valid sessions are rejected."},
        {"file": "does_not_exist.py", "line": 3, "severity": "suggestion",
         "description": "Invented file", "why": "Should be dropped by grounding."},
    ],
    "concept_tags": ["auth", "token-expiry"],
    "confidence": "high",
    "related_files": ["auth.py"],
}


class FakeLLM:
    """Returns a canned TutorResponse and counts calls. No network."""

    def __init__(self, payload: dict | None = None, tokens: int = 1234) -> None:
        self.payload = payload or CANNED
        self.last_tokens = tokens
        self.label = "fake:test-model"
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return json.dumps(self.payload)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture()
def fake_llm() -> FakeLLM:
    return FakeLLM()
