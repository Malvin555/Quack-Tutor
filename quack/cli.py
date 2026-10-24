"""Typer entry point. Thin orchestration only; the logic lives in the other modules."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

import typer

from . import __version__, gitutil, ui
from .config import SETTABLE_KEYS, Config, load_config, write_config_values
from .context import build_context, extract_file_refs
from .doctor import run_checks
from .errors import QuackError
from .history import export_session_log, log_query, log_session, sync_completed, write_history_md
from .indexer import index_repo
from .models import FileRecord, TutorResponse
from .providers import PRESETS, build_client, resolve_spec
from .redact import redact
from .retriever import get_record, rank
from .safety import assert_writable, audit_write_sites, verify_no_source_changes
from .symbols import extract_symbols
from .tasks import append_tasks, parse_completed
from .telemetry import span
from .tutor import ask as tutor_ask
from .tutor import cache_get, cache_key, cache_put, estimate_tokens, explain_file, review_batch

try:  # optional prettier tables
    from rich.console import Console
    from rich.table import Table

    _console: Any = Console()
except ImportError:  # pragma: no cover
    _console = None

app = typer.Typer(
    add_completion=False,
    help="Quack: the rubber duck tutor that can't touch your code. Read-only, token-frugal, local-first.",
    epilog="Examples:  quack ask \"why does login fail?\"  |  pytest -x 2>&1 | quack ask \"why?\" --stdin  |  quack doctor",
)


def _say(msg: str = "", fg: str | None = None, err: bool = False) -> None:
    typer.secho(msg, fg=fg, err=err)


def _fail(msg: str, code: int = 2) -> "typer.Exit":
    _say(f"quack: {msg}", fg="red", err=True)
    return typer.Exit(code)


def _table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    if _console is not None:
        t = Table(title=title)
        for h in headers:
            t.add_column(h)
        for r in rows:
            t.add_row(*r)
        # Piped output has no real width; avoid wrapping cells mid-word.
        Console(width=None if _console.is_terminal else 160).print(t)
        return
    _say(title, fg="cyan")
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    _say("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for r in rows:
        _say("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def _version(value: bool) -> None:
    if value:
        typer.echo(f"quack {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    root: Path = typer.Option(Path("."), "--root", "-C", help="Repository to work on."),
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Show version."),
) -> None:
    ctx.obj = {"root": root.resolve()}
    if ctx.invoked_subcommand is None:
        ui.banner(__version__)
        ui.cheatsheet()
        raise typer.Exit()


def _cfg(ctx: typer.Context) -> Config:
    try:
        return load_config(ctx.obj["root"])
    except QuackError as e:
        raise _fail(str(e)) from e


def _ensure_index(cfg: Config) -> None:
    """Build the index on first use, otherwise refresh only changed files. 0 LLM tokens."""
    if not cfg.index_db_path.exists():
        stats = index_repo(cfg.root, cfg, progress=lambda m: _say(m, err=True))
        _say(f"indexed {stats.files} files, {stats.symbols} symbols in {stats.duration_ms} ms (0 tokens)", err=True)
    else:
        index_repo(cfg.root, cfg, changed_only=True)


def _client(cfg: Config, provider: Optional[str], model: Optional[str], remote: bool):
    try:
        client = build_client(cfg, provider=provider, model=model, allow_remote=True if remote else None)
    except QuackError as e:
        raise _fail(str(e)) from e
    spec_name = provider or cfg.provider
    spec = resolve_spec(spec_name, cfg) if spec_name in PRESETS else None
    if spec is not None and not spec.local:
        _say(f"-> sending redacted, compact context to {spec_name} ({client.label.split(':', 1)[-1]})", fg="blue", err=True)
    return client


def _print_response(resp: TutorResponse, tokens: int, cached: bool, label: str) -> None:
    if ui.show_response(resp, tokens, cached, label):
        return
    _say("\n🦆 Quack asks:", fg="yellow")
    _say(f"  {resp.socratic_question}", fg="yellow")
    _say(f"\n{resp.explanation}\n")
    if resp.tasks:
        _say("Tasks for you (the duck never edits your code):", fg="green")
        for t in resp.tasks:
            _say(f"  [{t.severity}] {t.file}:{t.line} - {t.description}", fg="green")
            if t.why:
                _say(f"      why: {t.why}")
    else:
        _say("No tasks. Nothing worth fixing here.", fg="green")
    tags = ", ".join(resp.concept_tags) or "-"
    mark = "cached, 0 tokens" if cached else f"{tokens} tokens"
    _say(f"\nconcepts: {tags} | confidence: {resp.confidence} | {mark} | {label}")


def _json_out(resp: TutorResponse, tokens: int, cached: bool, label: str) -> None:
    typer.echo(json.dumps({**resp.model_dump(), "tokens": tokens, "cached": cached, "model": label}, indent=2))


def _validate_depth(depth: Optional[int]) -> None:
    if depth is not None and depth not in (1, 2, 3):
        raise typer.BadParameter("depth must be 1, 2 or 3")


@app.command(rich_help_panel="Set up")
def index(
    ctx: typer.Context,
    root: Optional[Path] = typer.Argument(None, help="Directory to index (default: --root)."),
    since: Optional[str] = typer.Option(None, "--since", help="Only reindex files changed since this git rev."),
    changed: bool = typer.Option(False, "--changed", help="Only reindex files whose hash changed."),
) -> None:
    """Build or update .quack/index.db. Costs 0 LLM tokens."""
    base = (root or ctx.obj["root"]).resolve()
    cfg = load_config(base)
    stats = index_repo(base, cfg, since=since, changed_only=changed, progress=lambda m: _say(m, err=True))
    _say(f"files: {stats.files}  symbols: {stats.symbols}  mentions: {stats.mentions}  "
         f"todos: {stats.todos}  time: {stats.duration_ms} ms  tokens: 0")


@app.command(rich_help_panel="Ask the duck")
def ask(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="What's going wrong?"),
    depth: Optional[int] = typer.Option(None, "--depth", "-d", help="Context depth 1|2|3."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be read and written, then exit."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Skip the 24h answer cache."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name."),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="ollama, openrouter, openai, groq, ..."),
    remote: bool = typer.Option(False, "--remote", help="Allow a remote provider for this run."),
    use_stdin: bool = typer.Option(False, "--stdin", help="Also read an error/traceback from stdin."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    files: Optional[int] = typer.Option(None, "--files", "-k", help="How many files to retrieve."),
) -> None:
    """Ask the duck about a bug. Writes TASKS.md. Never touches source."""
    _validate_depth(depth)
    cfg = _cfg(ctx)
    cfg.depth = depth or cfg.depth
    k = files or cfg.k_files
    assert_writable(cfg.tasks_md_path)

    extra = redact(sys.stdin.read()[-3000:]).strip() if use_stdin else ""
    full_q = f"{question}\n\nError output:\n{extra}" if extra else question
    last_line = extra.splitlines()[-1] if extra else ""
    retrieval_q = f"{question} {last_line}".strip()

    _ensure_index(cfg)
    ranked = rank(retrieval_q, cfg.index_db_path, k)
    refs = extract_file_refs(full_q, cfg.root, cfg.index_db_path)
    have = {r.path for r in ranked}
    pinned: list[FileRecord] = []
    for rel in refs:
        if rel not in have:
            rec = get_record(cfg.index_db_path, rel, score=999.0)
            if rec:
                pinned.append(rec)
    selected = pinned + ranked
    if not selected:
        _say("Nothing in the index matches. Mention a file, function or error message and try again.")
        raise typer.Exit(0)

    context = build_context(cfg.root, selected, retrieval_q, cfg.depth, cfg.index_db_path, focus_lines=refs)
    label_guess = f"{provider or cfg.provider}:{model or cfg.model}"

    if dry_run:
        _say("Dry run. The duck would read:", fg="cyan")
        for r in selected:
            _say(f"  {r.path} (score {r.score})")
        _say(f"context: {len(context)} chars (~{estimate_tokens(context)} tokens), depth {cfg.depth}, model {label_guess}")
        _say(f"would write: {cfg.tasks_md_path.name}, {cfg.history_md_path.name}, .quack/ (index, cache, history)")
        _say("source files: never.")
        raise typer.Exit(0)

    key = cache_key(full_q, cfg.depth, [r.hash for r in selected], label_guess)
    resp = None if no_cache else cache_get(key, cfg.cache_dir, cfg.cache_ttl_seconds)
    cached, tokens, label = resp is not None, 0, label_guess
    t0 = time.perf_counter()
    if resp is None:
        client = _client(cfg, provider, model, remote)
        try:
            with span(cfg, "ask", provider=client.label) as rec, ui.working(f"Asking {client.label}..."):
                resp, tokens = tutor_ask(client, full_q, context, cfg)
                label = client.label
                rec.update(tokens=tokens, files=len(selected), depth=cfg.depth)
        except QuackError as e:
            raise _fail(str(e)) from e
        cache_put(key, resp, tokens, cfg.cache_dir)
    latency = int((time.perf_counter() - t0) * 1000)

    task_ids = append_tasks(cfg.tasks_md_path, resp.tasks, question)
    log_query(cfg.history_db_path, question, [r.path for r in selected], tokens, task_ids, resp.concept_tags)
    prov, _, mdl = label.partition(":")
    log_session(cfg.history_db_path, "ask", prov, mdl, question, resp, tokens, latency, cached)

    if as_json:
        _json_out(resp, tokens, cached, label)
    else:
        _print_response(resp, tokens, cached, label)
        if tokens > cfg.max_tokens_per_ask:
            _say(f"warning: {tokens} tokens exceeded the {cfg.max_tokens_per_ask} budget; try --depth 1", fg="red", err=True)


@app.command(rich_help_panel="Ask the duck")
def explain(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="File to explain."),
    depth: Optional[int] = typer.Option(None, "--depth", "-d"),
    no_llm: bool = typer.Option(False, "--no-llm", help="List symbols without calling a model."),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    remote: bool = typer.Option(False, "--remote"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Explain a single file from its signatures."""
    _validate_depth(depth)
    cfg = _cfg(ctx)
    cfg.depth = depth or cfg.depth
    full = (file if file.is_absolute() else cfg.root / file).resolve()
    try:
        rel = full.relative_to(cfg.root)
    except ValueError:
        raise _fail(f"{file} is outside the repository") from None
    if not full.is_file():
        raise _fail(f"{file} not found", 1)

    if no_llm:
        syms = extract_symbols(rel, full.read_text(encoding="utf-8", errors="replace"))
        _say(f"{rel.as_posix()}: {len(syms)} symbols", fg="cyan")
        for s in syms:
            _say(f"  {s.kind:<8} {s.name}  L{s.start_line}-{s.end_line}  {s.signature}")
        raise typer.Exit(0)

    client = _client(cfg, provider, model, remote)
    t0 = time.perf_counter()
    try:
        with span(cfg, "explain", provider=client.label) as rec, ui.working(f"Reading {rel.as_posix()}..."):
            resp, tokens = explain_file(client, cfg.root, rel, cfg)
            rec["tokens"] = tokens
    except QuackError as e:
        raise _fail(str(e)) from e
    ids = append_tasks(cfg.tasks_md_path, resp.tasks, f"explain {rel}")
    log_query(cfg.history_db_path, f"explain {rel.as_posix()}", [rel.as_posix()], tokens, ids, resp.concept_tags)
    prov, _, mdl = client.label.partition(":")
    log_session(cfg.history_db_path, "explain", prov, mdl, f"explain {rel.as_posix()}", resp, tokens,
                int((time.perf_counter() - t0) * 1000), False)
    if as_json:
        _json_out(resp, tokens, False, client.label)
    else:
        _print_response(resp, tokens, False, client.label)


def _pick_review_files(cfg: Config, since: Optional[str], max_files: int) -> list[str]:
    conn = sqlite3.connect(cfg.index_db_path)
    try:
        rows = conn.execute(
            "SELECT f.path, f.line_count, (SELECT COUNT(*) FROM symbols s WHERE s.file = f.path), "
            "(SELECT COUNT(*) FROM todos t WHERE t.file = f.path) FROM files f WHERE f.language != 'other'"
        ).fetchall()
    finally:
        conn.close()
    changed = gitutil.changed_files(cfg.root, since) if since else None
    if since and changed is None:
        _say("warning: git unavailable for --since; reviewing the most complex files instead", err=True)
    if changed is not None:
        rows = [r for r in rows if r[0] in changed]
    rows.sort(key=lambda r: r[1] / 50 + r[2] + 2 * r[3], reverse=True)
    return [r[0] for r in rows[:max_files]]


@app.command(rich_help_panel="Ask the duck")
def review(
    ctx: typer.Context,
    since: Optional[str] = typer.Option(None, "--since", help="Review files changed since this git rev."),
    max_files: Optional[int] = typer.Option(None, "--max-files"),
    batch_size: Optional[int] = typer.Option(None, "--batch-size"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    remote: bool = typer.Option(False, "--remote"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Batch review of recent or most complex files."""
    cfg = _cfg(ctx)
    assert_writable(cfg.tasks_md_path)
    _ensure_index(cfg)
    paths = _pick_review_files(cfg, since, max_files or cfg.max_review_files)
    size = max(1, min(3, batch_size or cfg.batch_size))
    if not paths:
        _say("No files to review.")
        raise typer.Exit(0)
    batches = [paths[i:i + size] for i in range(0, len(paths), size)]
    if dry_run:
        _say(f"Dry run: {len(paths)} files in {len(batches)} batches (~1000 tokens per file):", fg="cyan")
        for b in batches:
            _say("  " + ", ".join(b))
        raise typer.Exit(0)

    client = _client(cfg, provider, model, remote)
    total, added, all_tasks = 0, 0, []
    for n, batch in enumerate(batches, 1):
        _say(f"[{n}/{len(batches)}] {', '.join(batch)}", err=True)
        try:
            with span(cfg, "review", provider=client.label) as rec:
                resp, tokens = review_batch(client, cfg.root, [Path(p) for p in batch], cfg)
                rec["tokens"] = tokens
        except QuackError as e:
            _say(f"stopped after {n - 1} batches: {e}", fg="red", err=True)
            raise typer.Exit(2) from e
        total += tokens
        ids = append_tasks(cfg.tasks_md_path, resp.tasks, f"review {','.join(batch)}")
        added += len(ids)
        all_tasks += resp.tasks
        log_query(cfg.history_db_path, f"review {','.join(batch)}", batch, tokens, ids, resp.concept_tags)
    if as_json:
        typer.echo(json.dumps({"tasks": [t.model_dump() for t in all_tasks], "tokens": total}, indent=2))
    else:
        for t in sorted(all_tasks, key=lambda t: t.severity):
            _say(f"  [{t.severity}] {t.file}:{t.line} - {t.description}", fg="green")
        _say(f"\nreviewed {len(paths)} files, {added} tasks written to {cfg.tasks_md_path.name} | {total} tokens | {client.label}")


@app.command(rich_help_panel="Track")
def tasks(ctx: typer.Context) -> None:
    """Print TASKS.md."""
    cfg = _cfg(ctx)
    done = parse_completed(cfg.tasks_md_path)
    if done:
        sync_completed(cfg.history_db_path, done)
    if not cfg.tasks_md_path.exists():
        _say("No tasks yet.")
        return
    typer.echo(cfg.tasks_md_path.read_text(encoding="utf-8"))


@app.command(rich_help_panel="Track")
def history(ctx: typer.Context) -> None:
    """Regenerate and print QUACK_HISTORY.md."""
    cfg = _cfg(ctx)
    sync_completed(cfg.history_db_path, parse_completed(cfg.tasks_md_path))
    write_history_md(cfg.history_db_path, cfg.history_md_path)
    typer.echo(cfg.history_md_path.read_text(encoding="utf-8"))


@app.command(rich_help_panel="Track")
def verify(ctx: typer.Context, audit: bool = typer.Option(False, "--audit", help="List every write site.")) -> None:
    """Prove no source files were modified."""
    cfg = _cfg(ctx)
    ok, changed = verify_no_source_changes(cfg.root)
    if audit:
        _say("Write sites in the Quack package:", fg="cyan")
        for site in audit_write_sites(Path(__file__).parent):
            _say(f"  {site}")
    if ok:
        _say("PASS: no source files were modified.", fg="green")
        if not (cfg.quack_dir / "last_hash.json").exists() and not (cfg.root / ".git").exists():
            _say("(no baseline yet; run `quack index` to record one)", err=True)
        return
    _say(f"FAIL: {len(changed)} path(s) differ (may include your own edits):", fg="red")
    for c in changed:
        _say(f"  {c}")
    raise typer.Exit(1)


@app.command(rich_help_panel="Set up")
def init(
    ctx: typer.Context,
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="ollama, openrouter, openai, groq, gemini, custom, ..."),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="For provider=custom (or a remote Ollama)."),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="Env var holding the API key."),
    fallback: Optional[str] = typer.Option(None, "--fallback", help="Provider to try if the first fails, e.g. ollama."),
) -> None:
    """Choose a provider and write .quack/config.toml (keys stay in your environment)."""
    cfg = _cfg(ctx)
    if provider is None:
        provider = typer.prompt("Provider", default=cfg.provider) if sys.stdin.isatty() else cfg.provider
    if provider not in PRESETS:
        raise _fail(f"unknown provider '{provider}'. Options: {', '.join(PRESETS)}", 1)
    spec = PRESETS[provider]
    updates: dict[str, Any] = {"provider": provider, "model": model or spec.default_model or cfg.model}
    if base_url:
        updates["base_url"] = base_url
    if api_key_env:
        updates["api_key_env"] = api_key_env
    if fallback:
        if fallback not in PRESETS:
            raise _fail(f"unknown fallback '{fallback}'", 1)
        updates["fallback"] = fallback
    check = spec if not base_url else resolve_spec("custom", cfg) if provider == "custom" else spec
    remote = not check.local and not (base_url and base_url.startswith(("http://localhost", "http://127.")))
    updates["allow_remote"] = remote
    write_config_values(cfg, updates)
    _say(f"wrote {cfg.quack_dir / 'config.toml'}: provider={provider} model={updates['model']}", fg="green")
    if remote:
        env = api_key_env or spec.key_env or "YOUR_API_KEY"
        _say(f"This provider is remote. Quack will send redacted, compact context (~2-3k tokens per ask) to it.", fg="yellow")
        _say(f"Export your key (never stored by Quack):  export {env}=...")
    else:
        _say("Local provider: nothing leaves your machine.")
    _say("Tip: add `.quack/` to your .gitignore (Quack won't edit it for you).")


@app.command(rich_help_panel="Set up")
def providers(ctx: typer.Context) -> None:
    """List supported providers and which are ready."""
    import os

    cfg = _cfg(ctx)
    rows = []
    for name, s in PRESETS.items():
        ready = "yes" if (not s.key_env or os.environ.get(s.key_env)) else f"set {s.key_env}"
        rows.append([("* " if name == cfg.provider else "  ") + name, "local" if s.local else "remote",
                     s.default_model or "-", s.key_env or "-", ready, s.note])
    _table("Quack providers (* = active)", ["provider", "where", "default model", "key env", "ready", "note"], rows)


@app.command(hidden=True)
def duck() -> None:
    """Meet the mascot."""
    import random

    for mood in ("idle", "happy", "think", "worried", "no"):
        ui.duck_says(mood, mood)
        _say()
    _say(random.choice(ui.TIPS), fg="yellow")


@app.command(rich_help_panel="Set up")
def doctor(ctx: typer.Context) -> None:
    """Check your setup (Ollama, models, keys, index)."""
    cfg = _cfg(ctx)
    checks = run_checks(cfg)
    _table("Quack doctor", ["check", "status", "detail"], [[c.name, "ok" if c.ok else "!!", c.detail] for c in checks])


@app.command(rich_help_panel="Set up")
def config(
    ctx: typer.Context,
    action: str = typer.Argument("show", help="show | get | set"),
    key: Optional[str] = typer.Argument(None),
    value: Optional[str] = typer.Argument(None),
) -> None:
    """Show or change .quack/config.toml."""
    cfg = _cfg(ctx)
    if action == "show":
        _table("Quack config", ["key", "value"], [[k, str(getattr(cfg, k))] for k in SETTABLE_KEYS])
    elif action == "get" and key in SETTABLE_KEYS:
        typer.echo(str(getattr(cfg, key)))
    elif action == "set" and key and value is not None:
        try:
            write_config_values(cfg, {key: value})
        except ValueError as e:
            raise _fail(str(e), 1) from e
        _say(f"{key} = {value}", fg="green")
    else:
        raise _fail("usage: quack config show | get KEY | set KEY VALUE", 1)


@app.command(rich_help_panel="Track")
def export(
    ctx: typer.Context,
    days: int = typer.Option(30, "--days"),
    out: str = typer.Option(".quack/session.log", "--out", "-o", help="Destination under .quack/, or - for stdout."),
) -> None:
    """Export a readable session log (share it, e.g. with Entire)."""
    cfg = _cfg(ctx)
    text = export_session_log(cfg.history_db_path, days)
    if out == "-":
        typer.echo(text)
        return
    path = (cfg.root / out).resolve()
    assert_writable(path)
    path.write_text(text, encoding="utf-8")
    _say(f"wrote {path.relative_to(cfg.root)}", fg="green")


@app.command(rich_help_panel="Set up")
def cache(ctx: typer.Context, action: str = typer.Argument("stats", help="stats | clear")) -> None:
    """Inspect or clear the answer cache."""
    cfg = _cfg(ctx)
    entries = list(cfg.cache_dir.glob("*.json"))
    if action == "clear":
        for p in entries:
            assert_writable(p)
            p.unlink()
        _say(f"cleared {len(entries)} cached answers")
    elif action == "stats":
        saved = 0
        for p in entries:
            try:
                saved += int(json.loads(p.read_text(encoding="utf-8")).get("tokens", 0))
            except (OSError, ValueError):
                pass
        _say(f"{len(entries)} cached answers; re-asking them costs 0 tokens (~{saved} tokens saved per replay)")
    else:
        raise _fail("usage: quack cache stats | clear", 1)


def _gather(cfg: Config, text: str, full_q: str) -> tuple[list[FileRecord], str]:
    """Retrieve files and build the compact context for ``text`` (shared by compare and chat)."""
    ranked = rank(text, cfg.index_db_path, cfg.k_files)
    refs = extract_file_refs(full_q, cfg.root, cfg.index_db_path)
    have = {r.path for r in ranked}
    pinned = [rec for rel in refs if rel not in have
              for rec in [get_record(cfg.index_db_path, rel, score=999.0)] if rec]
    selected = pinned + ranked
    if not selected:
        return [], ""
    return selected, build_context(cfg.root, selected, text, cfg.depth, cfg.index_db_path, focus_lines=refs)


@app.command(rich_help_panel="Ask the duck")
def compare(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="The bug to ask every model about."),
    targets: list[str] = typer.Option(..., "--with", "-w", help="provider[:model]; repeat for each, e.g. -w ollama -w openrouter:google/gemma-3-27b-it"),
    depth: Optional[int] = typer.Option(None, "--depth", "-d"),
    remote: bool = typer.Option(False, "--remote", help="Allow remote providers for this run."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Ask the same question to several models side by side (read-only: writes no tasks)."""
    _validate_depth(depth)
    cfg = _cfg(ctx)
    cfg.depth = depth or cfg.depth
    _ensure_index(cfg)
    selected, context = _gather(cfg, question, question)
    if not selected:
        _say("Nothing in the index matches. Mention a file, function or error message and try again.")
        raise typer.Exit(0)

    results: list[dict[str, Any]] = []
    for tgt in targets:
        prov, _, mdl = tgt.partition(":")
        rec: dict[str, Any] = {"target": tgt}
        t0 = time.perf_counter()
        try:
            client = build_client(cfg, provider=prov, model=mdl or None, allow_remote=True if remote else None)
            spec = resolve_spec(prov, cfg) if prov in PRESETS else None
            if spec is not None and not spec.local:
                _say(f"-> sending redacted context to {prov}", fg="blue", err=True)
            with ui.working(f"Asking {tgt}..."):
                resp, tokens = tutor_ask(client, question, context, cfg)
            rec.update(label=client.label, resp=resp, tokens=tokens)
        except QuackError as e:
            rec["error"] = str(e)
        rec["ms"] = int((time.perf_counter() - t0) * 1000)
        results.append(rec)

    if as_json:
        typer.echo(json.dumps([
            {"target": r["target"], "label": r.get("label"), "tokens": r.get("tokens"), "ms": r["ms"],
             "error": r.get("error"), "response": r["resp"].model_dump() if "resp" in r else None}
            for r in results], indent=2))
        return
    rows = []
    for r in results:
        if "resp" in r:
            x = r["resp"]
            rows.append([r["label"], x.confidence, str(r["tokens"]), f"{r['ms']} ms", str(len(x.tasks)),
                         ", ".join(sorted({t.file + ':' + str(t.line) for t in x.tasks})) or "-"])
        else:
            rows.append([r["target"], "error", "-", f"{r['ms']} ms", "-", r["error"][:60]])
    _table("Quack compare", ["model", "confidence", "tokens", "latency", "tasks", "where it points"], rows)
    for r in results:
        if "resp" in r:
            _say(f"\n== {r['label']} ==", fg="cyan")
            _say(f"Q: {r['resp'].socratic_question}", fg="yellow")
            _say(r["resp"].explanation)
        else:
            _say(f"\n== {r['target']} failed: {r['error']}", fg="red")


CHAT_HELP = [
    ("/help", "this list"),
    ("/files", "files the duck read for the last answer"),
    ("/tasks", "show TASKS.md"),
    ("/depth N", "context depth 1|2|3"),
    ("/model P[:M]", "switch provider/model, e.g. /model groq or /model openrouter:google/gemma-3-27b-it"),
    ("/verify", "prove no source file changed"),
    ("/clear", "forget the conversation (keeps index and tasks)"),
    ("/quit", "leave"),
]


@app.command(rich_help_panel="Ask the duck")
def chat(
    ctx: typer.Context,
    depth: Optional[int] = typer.Option(None, "--depth", "-d"),
    model: Optional[str] = typer.Option(None, "--model", "-m"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p"),
    remote: bool = typer.Option(False, "--remote"),
) -> None:
    """Talk it through: follow-up questions, with the last two exchanges as memory."""
    _validate_depth(depth)
    cfg = _cfg(ctx)
    cfg.depth = depth or cfg.depth
    assert_writable(cfg.tasks_md_path)
    _ensure_index(cfg)
    client = _client(cfg, provider, model, remote)
    try:  # arrow-key history, if the platform has readline
        import readline  # noqa: F401
    except ImportError:
        pass
    ui.banner(__version__, f"chat · {client.label} · depth {cfg.depth}")
    _say(f"🦆 Quack chat ({client.label}). Describe a bug, or type /help.", fg="cyan")
    memory: list[tuple[str, str]] = []
    last_files: list[str] = []
    total_tokens = asked = 0
    while True:
        try:
            line = input("🦆> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            cmd, _, arg = line.partition(" ")
            arg = arg.strip()
            if cmd in {"/quit", "/exit", "/q"}:
                break
            elif cmd == "/help":
                for c, d in CHAT_HELP:
                    _say(f"  {c:<14} {d}")
            elif cmd == "/files":
                _say("\n".join(f"  {f}" for f in last_files) if last_files else "No files read yet.")
            elif cmd == "/tasks":
                _say(cfg.tasks_md_path.read_text(encoding="utf-8") if cfg.tasks_md_path.exists() else "No tasks yet.")
            elif cmd == "/depth":
                if arg in {"1", "2", "3"}:
                    cfg.depth = int(arg)
                    _say(f"depth = {cfg.depth}")
                else:
                    _say("usage: /depth 1|2|3")
            elif cmd == "/model":
                if not arg:
                    _say(f"current: {client.label}")
                    continue
                prov, _, mdl = arg.partition(":")
                try:
                    client = build_client(cfg, provider=prov, model=mdl or None, allow_remote=True if remote else None)
                    _say(f"now using {client.label}", fg="green")
                except QuackError as e:
                    _say(f"quack: {e}", fg="red", err=True)
            elif cmd == "/verify":
                ok, changed = verify_no_source_changes(cfg.root)
                _say("PASS: no source files were modified." if ok else f"FAIL: {', '.join(changed)}",
                     fg="green" if ok else "red")
            elif cmd == "/clear":
                memory.clear()
                last_files = []
                _say("memory cleared")
            else:
                _say(f"unknown command {cmd}. Type /help.")
            continue

        prior = "\n".join(f"Earlier question: {q}\nEarlier answer: {a[:300]}" for q, a in memory[-2:])
        full_q = f"{line}\n\n{prior}" if prior else line
        selected, context = _gather(cfg, f"{line} {memory[-1][0] if memory else ''}".strip(), full_q)
        if not selected:
            _say("Nothing in the index matches that. Name a file, function or error.")
            continue
        last_files = [r.path for r in selected]
        _say(f"reading: {', '.join(last_files)}", fg="blue")
        t0 = time.perf_counter()
        try:
            with span(cfg, "chat", provider=client.label) as rec, ui.working(f"Asking {client.label}..."):
                resp, tokens = tutor_ask(client, full_q, context, cfg)
                rec["tokens"] = tokens
        except QuackError as e:
            _say(f"quack: {e}", fg="red", err=True)
            continue
        ids = append_tasks(cfg.tasks_md_path, resp.tasks, line)
        log_query(cfg.history_db_path, line, last_files, tokens, ids, resp.concept_tags)
        prov, _, mdl = client.label.partition(":")
        log_session(cfg.history_db_path, "chat", prov, mdl, line, resp, tokens,
                    int((time.perf_counter() - t0) * 1000), False)
        _print_response(resp, tokens, False, client.label)
        memory.append((line, resp.explanation))
        total_tokens += tokens
        asked += 1
    _say(f"Quack. {asked} question(s), {total_tokens} tokens this session. Good luck out there.")


if __name__ == "__main__":  # pragma: no cover
    app()
