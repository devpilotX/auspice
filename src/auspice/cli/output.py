"""Shared console output.

One place that knows how to draw a table, so every command looks the same and the CLI reads
like one program rather than twelve. The style follows the design system: no colour used to
carry meaning, hairline separators, numbers right aligned in a monospace column.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import typer
from rich.console import Console
from rich.table import Table
from rich.theme import Theme

# Brass is the only chromatic colour, matching the interface. Status colours exist for state
# and are never used for judgement.
THEME = Theme(
    {
        "heading": "bold",
        "muted": "dim",
        "brass": "#A8802C",
        "fresh": "#3F7D58",
        "stale": "#B3862B",
        "broken": "#9C3B32",
    }
)


def _force_utf8() -> None:
    """Windows consoles still default to cp1252, which cannot encode a box drawing character.

    Reconfiguring here rather than asking every caller to set PYTHONIOENCODING.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - a closed or exotic stream
                pass


_force_utf8()

# When output is piped the terminal width is unknown and rich falls back to 80 columns, which
# folds every table into an unreadable mess. Dense tables are the whole point here, so a
# captured run gets a usable width instead.
_WIDTH = None if sys.stdout.isatty() else 150

console = Console(theme=THEME, highlight=False, soft_wrap=False, width=_WIDTH)
err_console = Console(theme=THEME, stderr=True, highlight=False, width=_WIDTH)

# A hairline, in a terminal. The design system uses one pixel rules for all separation, and a
# row of hyphens is the honest equivalent here. No box drawing, so it survives a cp1252 pipe.
RULE_CHAR = "-"

# Placeholder for a value that is genuinely absent. Not a dash: the writing rules forbid them,
# and a dash in a numeric column reads as a minus sign.
ABSENT = "."


def heading(text: str) -> None:
    console.print()
    console.print(text, style="heading")
    console.print(RULE_CHAR * min(len(text), 78), style="muted")


def note(text: str) -> None:
    console.print(text, style="muted")


def render_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str] | None = None,
    numeric: Iterable[str] = (),
    title: str | None = None,
) -> None:
    if not rows:
        note("no rows")
        return

    resolved = list(columns) if columns else list(rows[0].keys())
    numeric_set = set(numeric)

    table = Table(
        title=title,
        show_edge=False,
        box=None,
        pad_edge=False,
        header_style="muted",
        title_style="heading",
        title_justify="left",
    )
    for name in resolved:
        table.add_column(
            name.replace("_", " "),
            justify="right" if name in numeric_set else "left",
            overflow="fold",
        )

    for row in rows:
        table.add_row(*(_format(row.get(name)) for name in resolved))

    console.print(table)


def _format(value: Any) -> str:
    if value is None:
        return ABSENT
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.4g}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else ABSENT
    return str(value)


def fail(message: str, *, hint: str | None = None, code: int = 1) -> None:
    """Print an error and exit. Errors say what to do next, not just what went wrong."""
    err_console.print(f"error: {message}", style="broken")
    if hint:
        err_console.print(f"       {hint}", style="muted")
    raise typer.Exit(code)


def ok(message: str) -> None:
    console.print(f"  {message}", style="fresh")
