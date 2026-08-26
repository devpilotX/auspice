"""Label commands: validate, load, stats, verify."""

from __future__ import annotations

from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy import text

from auspice.cli.output import console, fail, heading, note, ok, render_table
from auspice.config import get_settings
from auspice.db import transaction
from auspice.models.eval.thresholds import (
    MIN_HELD_OUT_DECISIONS,
    MIN_LABELLED_DECISIONS,
)
from auspice.pipeline.graph import labels as labels_module

app = typer.Typer(no_args_is_help=True, help="The labelled decision dataset: hand built ground truth.")


@app.command("validate")
def validate() -> None:
    """Check the labels file without touching the database."""
    settings = get_settings()
    path = settings.labels_path / labels_module.DEFAULT_LABELS_FILE
    try:
        label_set = labels_module.load_label_set(path)
    except ValidationError as exc:
        heading("Labels are not valid")
        for error in exc.errors():
            location = ".".join(str(p) for p in error["loc"])
            console.print(f"  {location}: {error['msg']}")
        fail(f"{len(exc.errors())} problem(s) in {path}")
    except FileNotFoundError as exc:
        fail(str(exc))

    heading(f"Labels {label_set.version}")
    render_table(
        [
            {
                "label_id": d.label_id,
                "jurisdiction": d.jurisdiction,
                "use_class": d.use_class.value,
                "relief": [r.value for r in d.relief_sought],
                "decided_on": d.decided_on,
                "outcome": d.outcome.value,
                "vote": (
                    f"{d.vote_for}-{d.vote_against}"
                    if d.vote_for is not None and d.vote_against is not None
                    else None
                ),
                "citations": len(d.citations),
                "primary": sum(1 for c in d.citations if c.kind == "primary"),
            }
            for d in label_set.decisions
        ],
        numeric=("citations", "primary"),
        title="Decisions",
    )
    console.print()
    render_table(
        [
            {
                "label_id": i.label_id,
                "jurisdiction": i.jurisdiction,
                "kind": i.kind.value,
                "adopted_on": i.adopted_on,
                "expires_on": i.expires_on,
                "adopted": not i.proposed_but_not_adopted,
                "margin": i.margin,
                "citations": len(i.citations),
            }
            for i in label_set.instruments
        ],
        numeric=("margin", "citations"),
        title="Instruments",
    )
    console.print()
    ok(
        f"{len(label_set.decisions)} decisions and {len(label_set.instruments)} instruments, "
        "every row cited"
    )
    _print_gap(len(label_set.terminal_decisions))


@app.command("load")
def load() -> None:
    """Load hand labels into the graph, then recompute the derived registry fields."""
    from auspice.pipeline.registry import loader as registry_loader

    heading("Loading labels")
    with transaction() as conn:
        report = labels_module.load(conn)
        summary = registry_loader.recompute_derived(conn)

    render_table(
        [{"metric": k, "value": v} for k, v in report.as_dict().items()],
        columns=("metric", "value"),
    )
    if report.unknown_jurisdictions:
        console.print()
        note(f"labels reference jurisdictions not in the registry: {report.unknown_jurisdictions}")
    if report.unmatched_bodies:
        note(f"labels reference bodies not in the registry: {report.unmatched_bodies}")

    console.print()
    render_table(
        [
            {"slug": slug, "data_depth": v["data_depth"], "discretion_index": v["discretion_index"]}
            for slug, v in summary.items()
            if v["data_depth"]
        ],
        numeric=("data_depth", "discretion_index"),
        title="Jurisdictions with a decision record",
    )
    console.print()
    ok(f"{report.decisions} decisions, {report.instruments} instruments, {report.citations} citations")


@app.command("stats")
def stats() -> None:
    """What the graph holds, and how far it is from a usable training set."""
    heading("Label coverage")
    with transaction() as conn:
        by_jurisdiction = conn.execute(
            text(
                """
                SELECT
                    j.slug,
                    j.region,
                    count(*) AS total,
                    count(*) FILTER (WHERE a.outcome IN ('approved','approved_with_conditions')) AS approved,
                    count(*) FILTER (WHERE a.outcome = 'denied') AS denied,
                    count(*) FILTER (WHERE a.outcome = 'withdrawn') AS withdrawn,
                    count(*) FILTER (WHERE a.censored) AS pending,
                    round(avg(a.months_to_decision), 1) AS mean_months
                FROM application a
                JOIN jurisdiction j ON j.id = a.jurisdiction_id
                GROUP BY j.slug, j.region
                ORDER BY total DESC, j.slug
                """
            )
        ).mappings().all()

        totals = conn.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE outcome IN
                        ('approved','approved_with_conditions','denied','withdrawn')) AS terminal,
                    count(*) FILTER (WHERE censored) AS censored,
                    count(*) AS total
                FROM application
                """
            )
        ).mappings().one()

        provenance = conn.execute(
            text(
                """
                SELECT
                    count(*) AS citations,
                    count(*) FILTER (WHERE verified) AS verified
                FROM fact_evidence
                """
            )
        ).mappings().one()

        instruments = conn.execute(
            text(
                """
                SELECT j.slug, i.kind, count(*) AS n
                FROM instrument i JOIN jurisdiction j ON j.id = i.jurisdiction_id
                GROUP BY j.slug, i.kind ORDER BY j.slug, i.kind
                """
            )
        ).mappings().all()

    if not by_jurisdiction:
        note("The graph holds no decisions. Run `auspice labels load`.")
        raise typer.Exit(0)

    render_table(
        [dict(row) for row in by_jurisdiction],
        numeric=("total", "approved", "denied", "withdrawn", "pending", "mean_months"),
        title="By jurisdiction",
    )
    console.print()
    render_table([dict(row) for row in instruments], numeric=("n",), title="Instruments held")
    console.print()
    render_table(
        [
            {"metric": "terminal decisions", "value": totals["terminal"]},
            {"metric": "censored decisions", "value": totals["censored"]},
            {"metric": "citations", "value": provenance["citations"]},
            {"metric": "citations verified", "value": provenance["verified"]},
        ],
        columns=("metric", "value"),
    )
    _print_gap(int(totals["terminal"]))


def _print_gap(terminal: int) -> None:
    console.print()
    if terminal >= MIN_LABELLED_DECISIONS:
        ok(f"{terminal} terminal decisions. The kill test can run.")
        return
    heading("Not enough labels to run the kill test")
    console.print(
        f"  {terminal} terminal decisions held. {MIN_LABELLED_DECISIONS} are needed, with at least "
        f"{MIN_HELD_OUT_DECISIONS} after the cutoff."
    )
    console.print(
        f"  Gap: {MIN_LABELLED_DECISIONS - terminal} rows. `auspice eval kill-test` will print "
        "INSUFFICIENT DATA until it closes."
    )
    console.print()
    note("Two routes, and they are complementary. Hand labelling from agendas and minutes, which")
    note("is roughly 30 to 60 rows a day. Or the extraction pipeline with a language model key")
    note("configured, producing candidate rows a human confirms. There is no third route.")


@app.command("verify")
def verify(
    limit: Annotated[int, typer.Option(help="Stop after this many citations")] = 0,
    offline: Annotated[
        bool, typer.Option(help="Report what would be fetched without reaching the network")
    ] = False,
) -> None:
    """Fetch every citation and check the quote appears verbatim in the source.

    This applies the section 6.4 rule to human work. A quote that does not match leaves the row
    unverified, and the training query excludes unverified rows.
    """
    from auspice.pipeline.extract.verify import verify_stored_citations

    heading("Citation verification")
    if offline:
        note("offline: listing citations without fetching")
    with transaction() as conn:
        result = verify_stored_citations(conn, limit=limit or None, offline=offline)

    render_table(
        result.rows,
        columns=("subject", "document_title", "status", "detail"),
    )
    console.print()
    render_table(
        [
            {"metric": "checked", "value": result.checked},
            {"metric": "verified", "value": result.verified},
            {"metric": "quote not found", "value": result.quote_missing},
            {"metric": "unreachable", "value": result.unreachable},
            {"metric": "skipped", "value": result.skipped},
        ],
        columns=("metric", "value"),
    )
    console.print()
    if result.checked and result.verified == result.checked:
        ok("every quote resolves to its source")
    elif result.quote_missing:
        note(
            f"{result.quote_missing} quote(s) did not appear verbatim. Those rows stay excluded "
            "from training until the quote is corrected or the citation replaced."
        )
