from pathlib import Path

from quack.symbols import detect_language, extract_mentions, extract_symbols, extract_todos, tokenize

from .conftest import FIXTURE


def _auth():
    return Path("auth.py"), (FIXTURE / "auth.py").read_text()


def test_detect_language():
    assert detect_language(Path("x.py")) == "python"
    assert detect_language(Path("x.tsx")) == "javascript"
    assert detect_language(Path("x.md")) == "other"


def test_extract_symbols_start_lines_and_ends():
    path, text = _auth()
    syms = {s.name: s for s in extract_symbols(path, text)}
    assert {"check_password", "create_session", "login", "session_valid"} <= set(syms)
    lines = text.splitlines()
    assert lines[syms["check_password"].start_line - 1].startswith("def check_password")
    assert syms["check_password"].end_line < syms["create_session"].start_line
    assert syms["session_valid"].end_line == len(lines)


def test_nested_methods_end_inside_class():
    src = "class A:\n    def f(self):\n        pass\n\n    def g(self):\n        pass\n\ndef h():\n    pass\n"
    syms = {s.name: s for s in extract_symbols(Path("m.py"), src)}
    assert syms["A"].end_line == 6 and syms["f"].end_line == 3 and syms["A"].kind == "class"


def test_mentions_exclude_stopwords_and_split_identifiers():
    m = extract_mentions("def check_password(the, supplied): return supplied")
    assert "the" not in m and "def" not in m and "return" not in m
    assert m["supplied"] == 2 and "password" in m and "check_password" in m


def test_tokenize_camel_case():
    assert "server" in tokenize("HTTPServer")


def test_todos_found():
    _path, text = _auth()
    todos = extract_todos(text)
    assert todos and "constant-time" in todos[0][1]
