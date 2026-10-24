# Contributing

Quack has one rule that matters more than any feature: **it must never write to source files.**

- Every write goes through `quack.safety.assert_writable` (only `TASKS.md`, `QUACK_HISTORY.md`, `.quack/`).
- Run `quack verify --audit` to list write sites; new ones need a test in `tests/test_safety.py`.
- Remote hosts are opt-in only. Keep `providers._guard` on every network path.
- Redact before anything reaches the index or a model (`quack/redact.py`).
- Tests must run offline: use `FakeLLM` from `tests/conftest.py` or a local `HTTPServer`.

```bash
pip install -e ".[dev]" && pytest -q
```
