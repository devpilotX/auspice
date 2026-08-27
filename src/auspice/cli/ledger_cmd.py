"""Ledger commands: verify, status, export, grade.

Publishing happens through ``auspice score`` because a ledger entry is the commitment of a score, not a
thing you write by hand. What lives here is everything anyone needs to check the record.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

import typer

from auspice.cli.output import ABSENT, console, fail, heading, note, ok, render_table
from auspice.db import transaction
from auspice.domain import Outcome

app = typer.Typer(no_args_is_help=True, help="The hash committed public prediction ledger.")


@app.command("verify")
def verify() -> None:
    """Recompute the whole hash chain and report the first sequence that does not check out."""
    from auspice import ledger

    heading("Ledger verification")
    with transaction() as conn:
        report = ledger.verify(conn)

    render_table(
        [
            {"quantity": "entries", "value": report.entries},
            {"quantity": "chain intact", "value": report.ok},
            {"quantity": "head", "value": (report.head or ABSENT)[:32]},
        ],
        columns=("quantity", "value"),
    )
    console.print()
    if report.ok:
        ok("every entry hashes to its recorded value and links to the one before it")
        return
    fail(
        f"the chain breaks at sequence {report.broken_at}: {report.reason}",
        hint="The ledger is append only. A break means an entry was edited or removed.",
    )


@app.command("status")
def status() -> None:
    """The public accuracy record, as the website shows it."""
    from auspice import ledger

    heading("Public record")
    with transaction() as conn:
        record = ledger.public_record(conn)

    render_table(
        [
            {"quantity": "predictions published", "value": record["published"]},
            {"quantity": "resolved", "value": record["resolved"]},
            {"quantity": "still pending", "value": record["pending"]},
            {"quantity": "answered", "value": record["answered"]},
            {"quantity": "abstained", "value": record["abstained"]},
            {
                "quantity": "brier score",
                "value": record["brier_score"] if record["brier_score"] is not None else ABSENT,
            },
            {"quantity": "chain intact", "value": record["chain"]["ok"]},
        ],
        columns=("quantity", "value"),
    )

    if record["misses"]:
        console.print()
        heading("Misses, published as they stand")
        render_table(record["misses"], numeric=("seq", "predicted"))

    console.print()
    if record["published"] == 0:
        note("Nothing published yet. Section 8.2: every day of delay is a day of moat that cannot")
        note("be recovered, and the record cannot be backdated by anyone, ever.")
    elif record["resolved"] == 0:
        note(
            "Nothing has resolved yet, so no accuracy number is published. That is the honest state"
        )
        note("of a ledger in its first months and it is what the accuracy page will say.")


@app.command("export")
def export(
    path: Annotated[str, typer.Argument(help="Where to write the newline delimited JSON")] = "-",
) -> None:
    """Export the ledger so anyone can verify it without using our interface."""
    from pathlib import Path

    from auspice import ledger

    with transaction() as conn:
        payload = ledger.export_jsonl(conn)

    if path == "-":
        console.print(payload, end="")
        return
    Path(path).write_text(payload, encoding="utf-8")
    ok(f"written to {path}")


@app.command("grade")
def grade(
    seq: Annotated[int, typer.Argument(help="The ledger sequence number")],
    outcome: Annotated[str, typer.Argument(help="What actually happened")],
    resolved_on: Annotated[str, typer.Argument(help="The decision date, ISO format")],
    miss_note: Annotated[
        str,
        typer.Option(help="If the call was wrong, what the model missed. Published as written."),
    ] = "",
) -> None:
    """Record what actually happened and score the call. Happens once, never revised."""
    from auspice import ledger

    try:
        resolved_outcome = Outcome(outcome)
    except ValueError:
        fail(f"unknown outcome: {outcome}", hint=f"One of {[o.value for o in Outcome]}")

    heading(f"Grading sequence {seq}")
    with transaction() as conn:
        ledger.require_intact(conn)
        grading = ledger.grade(
            conn,
            seq=seq,
            outcome=resolved_outcome,
            resolved_on=date.fromisoformat(resolved_on),
            miss_note=miss_note or None,
        )

    render_table(
        [{"field": k, "value": v} for k, v in sorted(grading.items())],
        columns=("field", "value"),
    )
    console.print()
    if grading.get("direction_correct") is False:
        note("This call was wrong and it is now in the public misses log. Section 8.5: publishing")
        note("misses is a costly signal, and costly signals are the only credible ones.")
    else:
        ok("graded")


@app.command("pending")
def pending(
    days: Annotated[int, typer.Option(help="Only entries older than this")] = 30,
) -> None:
    """Predictions still waiting on an outcome. The queue the grading job works from."""
    from auspice import ledger

    heading(f"Unresolved for more than {days} days")
    with transaction() as conn:
        rows = ledger.unresolved_older_than(conn, days=days)

    if not rows:
        note("nothing outstanding")
        return

    render_table(
        [
            {
                "seq": row["seq"],
                "published": row["published_at"].date(),
                "jurisdiction": row["payload"].get("jurisdiction"),
                "public_id": row["payload"].get("public_id"),
                "predicted": row["payload"].get("approval_probability"),
            }
            for row in rows
        ],
        numeric=("seq", "predicted"),
    )
