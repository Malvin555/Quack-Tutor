"""Ask the model, parse structured output, ground it in the repo, and cache."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from pydantic import ValidationError

from .config import Config
from .errors import TutorError
from .models import TutorResponse
from .prompts import ASK_SYSTEM, EXPLAIN_SYSTEM, REVIEW_SYSTEM, USER_TEMPLATE
from .providers import LLMClient, OllamaClient  # noqa: F401  (re-exported per spec)
from .redact import redact
from .safety import assert_writable
from .symbols import extract_symbols

__all__ = [
    "LLMClient",
    "OllamaClient",
    "TutorError",
    "ask",
    "explain_file",
    "review_batch",
    "cache_key",
    "cache_get",
    "cache_put",
    "parse_response",
    "ground",
    "estimate_tokens",
]

OUTPUT_RESERVE = 700


def estimate_tokens(text: str) -> int:
    """Cheap ~4 chars/token estimate, used when a provider reports no usage."""
    return max(1, len(text) // 4)


def _render(question: str, context: str) -> str:
    values = {"question": question, "context": context}
    return re.sub(
        r"\{(question|context)\}", lambda m: values[m.group(1)], USER_TEMPLATE
    )


def _fit(system: str, question: str, context: str, config: Config) -> str:
    """Trim ``context`` so the prompt fits the per-ask token budget."""
    budget_chars = max(0, (config.max_tokens_per_ask - OUTPUT_RESERVE) * 4)
    overhead = len(system) + len(_render(question, ""))
    allowed = max(400, budget_chars - overhead)
    if len(context) > allowed:
        context = (
            context[:allowed].rstrip() + "\n...[context trimmed to fit token budget]"
        )
    return _render(question, context)


def parse_response(raw: str) -> TutorResponse:
    """Parse model output into a TutorResponse, tolerating fences and missing optional keys."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    obj = None
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1]):
        try:
            obj = json.loads(candidate)
            break
        except ValueError:
            continue
    if not isinstance(obj, dict):
        raise TutorError(
            "The model did not return valid JSON. Try again, or use a larger model (--model)."
        )
    obj.setdefault("tasks", [])
    obj.setdefault("concept_tags", [])
    obj.setdefault("related_files", [])
    conf = str(obj.get("confidence", "low")).lower()
    obj["confidence"] = conf if conf in {"high", "medium", "low"} else "low"
    for t in obj["tasks"] if isinstance(obj["tasks"], list) else []:
        if isinstance(t, dict):
            sev = str(t.get("severity", "suggestion")).lower()
            t["severity"] = sev if sev in {"critical", "suggestion"} else "suggestion"
            t.setdefault("why", "")
    try:
        return TutorResponse.model_validate(obj)
    except ValidationError as e:
        raise TutorError(
            f"The model's JSON did not match the TutorResponse schema: {e.errors()[0]['loc']}"
        ) from e


def ground(resp: TutorResponse, root: Path) -> TutorResponse:
    """Drop tasks that point at files that don't exist; clamp impossible line numbers."""
    root = Path(root).resolve()

    def norm(f: str) -> tuple[str, int] | None:
        p = Path(f.replace("\\", "/"))
        try:
            rel = (
                p.resolve().relative_to(root)
                if p.is_absolute()
                else (root / p).resolve().relative_to(root)
            )
        except (ValueError, OSError):
            return None
        full = root / rel
        if not full.is_file():
            return None
        try:
            n = sum(1 for _ in full.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            return None
        return rel.as_posix(), n

    kept = []
    for t in resp.tasks:
        hit = norm(t.file)
        if hit:
            kept.append(
                t.model_copy(
                    update={"file": hit[0], "line": min(max(1, t.line), max(1, hit[1]))}
                )
            )
    related = [r for r in (norm(f) for f in resp.related_files) if r]
    update: dict[str, object] = {
        "tasks": kept,
        "related_files": [r[0] for r in related],
    }
    if resp.tasks and not kept:
        update["confidence"] = "low"
    return resp.model_copy(update=update)


def _run(
    client: LLMClient, system: str, question: str, context: str, config: Config
) -> tuple[TutorResponse, int]:
    user = _fit(system, question, redact(context), config)
    try:
        raw = client.complete(system, user)
    except TutorError:
        raise
    except Exception as e:  # noqa: BLE001
        raise TutorError(f"LLM call failed: {e}") from e
    resp = ground(parse_response(raw), config.root)
    tokens = getattr(client, "last_tokens", 0) or estimate_tokens(system + user + raw)
    return resp, tokens


def ask(
    client: LLMClient, question: str, context: str, config: Config
) -> tuple[TutorResponse, int]:
    """Ask the duck. Returns ``(response, tokens_used)``."""
    return _run(client, ASK_SYSTEM, question, context, config)


def _head_context(root: Path, path: Path, head: int, max_symbols: int) -> str:
    full = path if path.is_absolute() else root / path
    rel = full.resolve().relative_to(root.resolve()).as_posix()
    text = full.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    n = min(len(lines), head)
    body = "\n".join(f"{i:>4}| {lines[i - 1]}" for i in range(1, n + 1))
    syms = extract_symbols(Path(rel), text)[:max_symbols]
    sym_txt = "\n".join(
        f"- {s.kind} {s.name} L{s.start_line}-{s.end_line}: {s.signature}" for s in syms
    )
    return f"### FILE: {rel} (lines 1-{n})\n{body}\n### SYMBOLS in {rel}\n{sym_txt}\n"


def explain_file(
    client: LLMClient, root: Path, path: Path, config: Config
) -> tuple[TutorResponse, int]:
    head = {1: 15, 2: 30, 3: 60}.get(config.depth, 30)
    ctx = _head_context(Path(root), Path(path), head, 60)
    return _run(client, EXPLAIN_SYSTEM, f"Explain {Path(path).as_posix()}", ctx, config)


def review_batch(
    client: LLMClient, root: Path, paths: list[Path], config: Config
) -> tuple[TutorResponse, int]:
    ctx = "\n".join(_head_context(Path(root), Path(p), 60, 25) for p in paths)
    names = ", ".join(Path(p).as_posix() for p in paths)
    return _run(client, REVIEW_SYSTEM, f"Review these files: {names}", ctx, config)


def cache_key(
    question: str, depth: int, file_hashes: list[str], model: str = ""
) -> str:
    raw = f"{question}|{depth}|{','.join(sorted(file_hashes))}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(key: str, cache_dir: Path, ttl: int) -> TutorResponse | None:
    path = Path(cache_dir) / f"{key}.json"
    try:
        if time.time() - path.stat().st_mtime > ttl:
            return None
        return TutorResponse.model_validate(
            json.loads(path.read_text(encoding="utf-8"))["response"]
        )
    except (OSError, ValueError, KeyError, ValidationError):
        return None


def cache_put(key: str, response: TutorResponse, tokens: int, cache_dir: Path) -> None:
    path = Path(cache_dir) / f"{key}.json"
    assert_writable(path)
    path.write_text(
        json.dumps(
            {"response": response.model_dump(), "tokens": tokens, "ts": time.time()}
        ),
        encoding="utf-8",
    )
