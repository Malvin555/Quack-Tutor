"""Terminal interface: ASCII duck, panels, spinner.

Rich output is used only on a real terminal. When output is piped (or `--json`,
CI, tests) everything falls back to the plain text the rest of Quack prints, so
scripts never see box-drawing characters or colour codes.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Any, Iterator

from .models import TutorResponse

def _duck(eye: str, extra: str = "") -> list[str]:
    return ["    __", f"___( {eye})>{extra}", "\\ <_. )", " `---'"]


# Original mascot, one face per mood.
MOODS: dict[str, list[str]] = {
    "idle": _duck("o"),
    "happy": _duck("^"),
    "think": _duck("·", "  ..."),
    "worried": _duck("°", "  ?"),
    "no": _duck("x", "  !"),
}
DUCK = "\n".join(MOODS["idle"])  # kept for callers that want the plain art

TIPS = [
    "I never edit your files. Not even if you ask nicely.",
    "Indexing costs 0 tokens. I counted.",
    "Pipe the traceback:  pytest -x 2>&1 | quack ask \"why?\" --stdin",
    "Ask the same question twice. The second answer is free.",
    "One question at a time. I'm a duck.",
    "quack verify proves I kept my wings to myself.",
]
REMARKS = {
    "high": ("happy", "Quack. I'm fairly sure about this one."),
    "medium": ("idle", "Quack. Worth a second look."),
    "low": ("worried", "Quack... show me more files."),
}

TAGLINE = "the rubber duck that can't touch your code"
BADGES = "read-only  ·  token-frugal  ·  local-first"

# (panel, [(command, description)])
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Ask the duck", [
        ("ask \"...\"", "explain a bug, write TASKS.md  (--stdin to pipe an error)"),
        ("chat", "talk it through with follow-ups"),
        ("compare \"...\" -w A -w B", "same question to several models, side by side"),
        ("explain FILE", "what does this file do  (--no-llm: no model needed)"),
        ("review", "batch review of the riskiest files"),
    ]),
    ("Track", [
        ("tasks", "your to-do list"),
        ("history", "what you've been asking, and mini-lessons"),
        ("verify", "prove no source file changed  (--audit lists write sites)"),
        ("export", "readable session log"),
    ]),
    ("Set up", [
        ("doctor", "check Ollama, model, keys, index"),
        ("init", "choose a provider and model"),
        ("providers", "list supported AI providers"),
        ("config", "show / get / set settings"),
        ("index", "build the index (0 tokens)"),
        ("cache", "inspect or clear cached answers"),
    ]),
]


def rich_ok() -> bool:
    """True when we should draw fancy output: a real terminal, rich installed, not disabled."""
    if os.environ.get("QUACK_PLAIN") or not sys.stdout.isatty():
        return False
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def console() -> Any:
    from rich.console import Console

    return Console()


def banner(version: str, extra: str = "") -> None:
    """Print the duck + tagline (terminal only)."""
    if not rich_ok():
        return
    from rich.text import Text

    con = console()
    duck = MOODS["idle"]
    side = [f"Quack v{version}", TAGLINE, BADGES, extra]
    for i, line in enumerate(duck):
        t = Text(line.ljust(10), style="bold yellow")
        t.append(side[i] if i < len(side) else "", style=["bold", "", "dim", "cyan"][i] if i < 4 else "")
        con.print(t)
    con.print()


def cheatsheet() -> None:
    """The screen shown by bare `quack`."""
    if rich_ok():
        from rich.table import Table

        con = console()
        for title, rows in GROUPS:
            t = Table(show_header=False, box=None, padding=(0, 2), title=title, title_style="bold cyan", title_justify="left")
            t.add_column(style="bold green", no_wrap=True, min_width=36)
            t.add_column()
            for cmd, desc in rows:
                t.add_row(f"quack {cmd}", desc)
            con.print(t)
        con.print("\n[dim]First time? Run [bold]quack doctor[/bold]. Full help: [bold]quack --help[/bold][/dim]")
        return
    print("Quack: the rubber duck that can't touch your code\n")
    for title, rows in GROUPS:
        print(f"{title}:")
        for cmd, desc in rows:
            print(f"  quack {cmd:<26} {desc}")
        print()
    print("First time? Run `quack doctor`. Full help: `quack --help`")


@contextmanager
def working(message: str) -> Iterator[None]:
    """Spinner on a terminal; silent otherwise."""
    if not rich_ok():
        yield
        return
    with console().status(f"[yellow]{message}[/yellow]", spinner="dots"):
        yield


def show_response(resp: TutorResponse, tokens: int, cached: bool, label: str) -> bool:
    """Draw an answer with panels. Returns False if plain output should be used instead."""
    if not rich_ok():
        return False
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    con = console()
    con.print(Panel(Text(resp.socratic_question, style="bold yellow"), title="🦆 Quack asks", title_align="left",
                    border_style="yellow", padding=(1, 2)))
    con.print(Panel(resp.explanation, title="Likely cause", title_align="left", border_style="blue", padding=(1, 2)))
    if resp.tasks:
        t = Table(title="Your tasks (the duck never edits your code)", title_style="bold green", title_justify="left",
                  header_style="bold", expand=True)
        t.add_column("", no_wrap=True)
        t.add_column("where", style="cyan", no_wrap=True)
        t.add_column("do this")
        t.add_column("why", style="dim")
        for task in resp.tasks:
            sev = "[bold red]critical[/]" if task.severity == "critical" else "[yellow]suggest[/]"
            t.add_row(sev, f"{task.file}:{task.line}", task.description, task.why)
        con.print(t)
    else:
        con.print("[green]No tasks. Nothing worth fixing here.[/green]")
    conf = {"high": "green", "medium": "yellow", "low": "red"}[resp.confidence]
    cost = "cached, 0 tokens" if cached else f"{tokens} tokens"
    tags = ", ".join(resp.concept_tags) or "-"
    mood, remark = REMARKS[resp.confidence]
    duck_says(mood, remark)
    con.print(f"[dim]concepts: {tags}  |  confidence: [/dim][{conf}]{resp.confidence}[/{conf}]"
              f"[dim]  |  {cost}  |  {label}[/dim]")
    return True


def duck_says(mood: str, text: str) -> None:
    """Print the mascot with a line of text (terminal: coloured; piped: plain)."""
    art = MOODS.get(mood, MOODS["idle"])
    if rich_ok():
        from rich.text import Text

        con = console()
        for i, line in enumerate(art):
            t = Text(line.ljust(16), style="bold yellow")
            if i == 1:
                t.append(text, style="italic")
            con.print(t)
        return
    for i, line in enumerate(art):
        print(line.ljust(16) + (text if i == 1 else ""))
