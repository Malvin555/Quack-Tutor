from quack.models import Task
from quack.tasks import append_tasks, parse_completed


def _t(file="auth.py", line=24, sev="critical", desc="Flip the comparison"):
    return Task(file=file, line=line, severity=sev, description=desc, why="Because it is inverted.")


def test_append_format_and_grouping(tmp_path):
    md = tmp_path / "TASKS.md"
    ids = append_tasks(md, [_t(), _t("api.py", 3, "suggestion", "Close the connection")], "q")
    text = md.read_text()
    assert text.startswith("# Quack Tasks")
    assert "The duck never modifies your code" in text
    assert text.index("## Critical") < text.index("## Suggestions")
    assert "- [ ] `auth.py:24` — Flip the comparison" in text
    assert "  - Why: Because it is inverted." in text and "  - Asked: " in text
    assert len(ids) == 2 and ids[0].startswith("auth.py:24:")


def test_duplicates_are_skipped(tmp_path):
    md = tmp_path / "TASKS.md"
    append_tasks(md, [_t()], "q")
    before = md.read_text()
    append_tasks(md, [_t()], "q again")
    assert md.read_text() == before


def test_parse_completed(tmp_path):
    md = tmp_path / "TASKS.md"
    ids = append_tasks(md, [_t(), _t("api.py", 3, "suggestion", "Close it")], "q")
    md.write_text(md.read_text().replace("- [ ] `auth.py:24`", "- [x] `auth.py:24`"))
    assert parse_completed(md) == [ids[0]]


def test_new_tasks_keep_existing_ones(tmp_path):
    md = tmp_path / "TASKS.md"
    append_tasks(md, [_t()], "q")
    append_tasks(md, [_t(desc="A different problem", line=30)], "q2")
    assert md.read_text().count("- [ ]") == 2
