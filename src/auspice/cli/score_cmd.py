"""Score and memo commands. Stages 10 and the delivery surface.

``score site`` produces the full section 5.6 object for a site and can publish it to the ledger. ``memo
render`` turns a score into the document that goes into a deal file.

Publishing is a separate flag rather than the default, and that is the one decision in this module worth
stating. A ledger entry cannot be revised or deleted, so committing one has to be something an operator did
on purpose. Section 8.2 also means the opposite mistake is expensive: every day a prediction is not published
is a day of the only advantage in this business that money cannot shortcut. The flag exists to make the
choice deliberate in both directions, not to discourage it.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from auspice.cli.output import ABSENT, console, fail, heading, note, ok, render_table
from auspice.db import transaction
from auspice.domain import Relief, UseClass

score_app = typer.Typer(no_args_is_help=True, help="Stage 10: the score object, and publishing it.")
memo_app = typer.Typer(
    no_args_is_help=True, help="The committee memo. HTML always, PDF when Chromium is present."
)


def _parse_relief(raw: str) -> list[Relief]:
    values: list[Relief] = []
    for token in raw.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        try:
            values.append(Relief(cleaned))
        except ValueError:
            fail(
                f"unknown relief: {cleaned}",
                hint="One of " + ", ".join(sorted(r.value for r in Relief)),
            )
    if not values:
        fail("a site needs at least one relief", hint="For example: rezoning,special_use_permit")
    return values


def _render(score: Any) -> None:
    """Print the score the way the report screen orders it."""
    determination = score.determination
    head = score.site.jurisdiction_chain[0]

    heading(f"{score.site.label or head.name}")
    note(f"{score.site.use_class.value.replace('_', ' ')} in {head.name}")
    console.print()

    if determination.abstained:
        console.print("We do not know.", style="heading")
        console.print()
        for reason in determination.abstention_reasons:
            console.print(f"  {reason.value.replace('_', ' ')}")
        console.print()
        from auspice.score import abstention_notice

        for line in abstention_notice(score).split(". "):
            if line.strip():
                note(f"  {line.strip().rstrip('.')}.")
    else:
        interval = determination.credible_interval_80
        assert determination.approval_probability is not None
        assert interval is not None
        console.print(
            f"  {determination.approval_probability:.0%} approval",
            style="heading",
        )
        console.print(
            f"  80 percent interval {interval[0]:.0%} to {interval[1]:.0%}"
            f"  ({determination.interval_kind} interval)"
        )
        if determination.confidence is not None:
            console.print(f"  confidence {determination.confidence.value}")

    console.print()
    render_table(
        [
            {
                "quantity": "months to a decision",
                "value": (
                    f"p10 {determination.time_to_decision_months.p10:.0f}"
                    f"  p50 {determination.time_to_decision_months.p50:.0f}"
                    f"  p90 {determination.time_to_decision_months.p90:.0f}"
                    f"  ({determination.time_to_decision_months.basis})"
                    if determination.time_to_decision_months
                    else ABSENT
                ),
            },
            {
                "quantity": "rules change before a decision",
                "value": (
                    f"{determination.probability_of_rule_change_before_decision:.1%}"
                    if determination.probability_of_rule_change_before_decision is not None
                    else ABSENT
                ),
            },
            {
                "quantity": "county base rate, this use class",
                "value": (
                    f"{determination.local_base_rate:.0%}"
                    if determination.local_base_rate is not None
                    else "no decisions on record"
                ),
            },
            {"quantity": "comparable decisions", "value": head.data_depth},
            {"quantity": "pooling weight", "value": f"{score.provenance.pooling_weight:.2f}"},
            {"quantity": "serving model", "value": score.provenance.model_kind},
            {"quantity": "data as of", "value": score.provenance.data_as_of.isoformat()},
            {"quantity": "features not known", "value": len(score.provenance.features_missing)},
        ],
        columns=("quantity", "value"),
    )

    if score.drivers:
        console.print()
        render_table(
            [
                {
                    "factor": driver.factor,
                    "direction": driver.direction,
                    "weight": driver.weight,
                    "plain language": driver.plain_language,
                    "evidence": driver.evidence_id or "registry data",
                }
                for driver in score.drivers
            ],
            numeric=("weight",),
            title="What moves the number",
        )

    if score.precedents:
        console.print()
        render_table(
            [
                {
                    "case": precedent.external_id or precedent.application_id,
                    "decided": precedent.decided_on,
                    "outcome": precedent.outcome.value,
                    "vote": precedent.vote or ABSENT,
                    "similarity": precedent.similarity,
                }
                for precedent in score.precedents
            ],
            numeric=("similarity",),
            title="The decisions this rests on",
        )

    if score.alternatives:
        console.print()
        render_table(
            [
                {
                    "jurisdiction": alternative.jurisdiction,
                    "km": alternative.distance_km,
                    "probability": (
                        f"{alternative.approval_probability:.0%}"
                        if alternative.approval_probability is not None
                        else "we do not know"
                    ),
                    "rank": alternative.expected_value_rank,
                }
                for alternative in score.alternatives
            ],
            numeric=("km", "rank"),
            title="Where else this could go",
        )

    if score.provenance.pooling_note:
        console.print()
        note(score.provenance.pooling_note)
    if score.provenance.features_missing:
        console.print()
        note(
            f"not known for this site: {', '.join(score.provenance.features_missing).replace('_', ' ')}"
        )
        note("These are recorded as unknown rather than filled with a default.")


@score_app.command("site")
def score_site_command(
    longitude: Annotated[float | None, typer.Option(help="Longitude, WGS84")] = None,
    latitude: Annotated[float | None, typer.Option(help="Latitude, WGS84")] = None,
    jurisdiction: Annotated[str, typer.Option(help="Registry slug, instead of a coordinate")] = "",
    use_class: Annotated[str, typer.Option(help="Use class")] = "data_center_hyperscale",
    relief: Annotated[str, typer.Option(help="Comma separated relief sought")] = "rezoning",
    acres: Annotated[float | None, typer.Option(help="Site area in acres")] = None,
    capacity_mw: Annotated[float | None, typer.Option(help="Load in megawatts")] = None,
    label: Annotated[str, typer.Option(help="What you call this site")] = "",
    as_of: Annotated[str, typer.Option(help="Score as the world was known on this date")] = "",
    publish: Annotated[
        bool,
        typer.Option(help="Commit the prediction to the append only ledger. Cannot be undone."),
    ] = False,
    json_out: Annotated[str, typer.Option(help="Write the full score object to this path")] = "",
) -> None:
    """Score one site. Section 5.6.

    Returns an abstention when the evidence is too thin, which is a successful answer rather than an error.
    """
    from auspice.score import SiteRequest, load_serving_models, score_site

    try:
        resolved_use_class = UseClass(use_class)
    except ValueError:
        fail(
            f"unknown use class: {use_class}",
            hint="One of " + ", ".join(sorted(u.value for u in UseClass)),
        )

    if not jurisdiction and (longitude is None or latitude is None):
        fail(
            "a site needs either a jurisdiction slug or both a longitude and a latitude",
            hint="For example: --jurisdiction us-va-loudoun, or --longitude -77.4874 --latitude 39.0438",
        )

    resolved_as_of = date.fromisoformat(as_of) if as_of else date.today()

    with transaction() as conn:
        models = load_serving_models(conn, cutoff=resolved_as_of)
        for message in models.notes or []:
            note(message)

        score = score_site(
            conn,
            SiteRequest(
                use_class=resolved_use_class,
                relief_sought=_parse_relief(relief),
                longitude=longitude,
                latitude=latitude,
                jurisdiction_slug=jurisdiction or None,
                label=label or None,
                acres=acres,
                capacity_mw=capacity_mw,
            ),
            models=models,
            as_of=resolved_as_of,
        )

        _render(score)

        if json_out:
            Path(json_out).write_text(score.model_dump_json(indent=2), encoding="utf-8")
            console.print()
            note(f"written to {json_out}")

        if publish:
            _publish(conn, score)
        else:
            console.print()
            note(
                "Not published. Pass --publish to commit this to the ledger, which cannot be undone."
            )
            note(
                "Section 8.2: every day a prediction is not published is a day of moat that cannot be"
            )
            note(
                "recovered, so the flag is there to make the choice deliberate rather than to discourage it."
            )


def _publish(conn: Any, score: Any) -> None:
    """Store the prediction and append it to the ledger.

    The prediction row is written first, then the ledger entry, in one transaction. A ledger entry pointing at
    a prediction that does not exist would break the export, and a prediction with no ledger entry is simply
    an unpublished score, which is a normal state.
    """
    from auspice import ledger
    from auspice.db import schema

    ledger.require_intact(conn)

    determination = score.determination
    interval = determination.credible_interval_80
    months = determination.time_to_decision_months

    model_run_id = conn.execute(
        schema.model_run.select()
        .where(schema.model_run.c.dataset_hash == score.provenance.dataset_hash)
        .order_by(schema.model_run.c.trained_at.desc())
        .limit(1)
    ).first()

    if model_run_id is None:
        fail(
            "no model run matches this score's dataset hash",
            hint="Run `auspice train all` so the run that produced this number is on record.",
        )

    jurisdiction_id = conn.execute(
        schema.jurisdiction.select().where(
            schema.jurisdiction.c.slug == score.site.jurisdiction_chain[0].slug
        )
    ).first()
    if jurisdiction_id is None:
        fail("the score's jurisdiction is not in the registry, so it cannot be published")

    prediction_id = int(
        conn.execute(
            schema.prediction.insert()
            .values(
                public_id=score.public_id,
                jurisdiction_id=jurisdiction_id.id,
                site=json.loads(score.site.model_dump_json()),
                model_run_id=model_run_id.id,
                approval_probability=determination.approval_probability,
                ci80_low=interval[0] if interval else None,
                ci80_high=interval[1] if interval else None,
                confidence=determination.confidence.value if determination.confidence else None,
                abstained=determination.abstained,
                abstention_reasons=[r.value for r in determination.abstention_reasons],
                months_p10=months.p10 if months else None,
                months_p50=months.p50 if months else None,
                months_p90=months.p90 if months else None,
                rule_change_probability=determination.probability_of_rule_change_before_decision,
                drivers=json.loads(
                    json.dumps([d.model_dump() for d in score.drivers], default=str)
                ),
                precedents=json.loads(
                    json.dumps([p.model_dump() for p in score.precedents], default=str)
                ),
                mitigations=json.loads(
                    json.dumps([m.model_dump() for m in score.mitigations], default=str)
                ),
                alternatives=json.loads(
                    json.dumps([a.model_dump() for a in score.alternatives], default=str)
                ),
                provenance=json.loads(score.provenance.model_dump_json()),
                features_hash=score.features_hash,
                data_as_of=score.provenance.data_as_of,
            )
            .returning(schema.prediction.c.id)
        ).scalar_one()
    )

    entry = ledger.publish(conn, prediction_id=prediction_id, payload=score.ledger_payload())

    console.print()
    heading("Published")
    render_table(
        [
            {"field": "sequence", "value": entry.seq},
            {"field": "public id", "value": score.public_id},
            {"field": "payload hash", "value": entry.payload_hash[:32]},
            {"field": "entry hash", "value": entry.entry_hash[:32]},
            {"field": "links to", "value": entry.prev_hash[:32]},
        ],
        columns=("field", "value"),
    )
    console.print()
    ok("committed to the ledger. This cannot be revised or deleted.")


@memo_app.command("render")
def memo_render(
    public_id: Annotated[str, typer.Argument(help="The score's public identifier")],
    out: Annotated[str, typer.Option(help="Output path without an extension")] = "artifacts/memo",
    prepared_for: Annotated[str, typer.Option(help="Who the memo is addressed to")] = "",
    pdf: Annotated[bool, typer.Option(help="Also render a PDF with headless Chromium")] = True,
) -> None:
    """Render a published score as the committee memo.

    The HTML is the artefact of record and is written whether or not Chromium is available. Rendering is
    deterministic: the same score and template version produce byte identical HTML, so a memo regenerated
    years later can be compared against the copy in the deal file.
    """
    from auspice.errors import StageUnavailableError
    from auspice.memo import render, to_pdf

    with transaction() as conn:
        score = _load_published(conn, public_id)

    memo = render(
        score,
        generated_at=datetime.now(UTC),
        prepared_for=prepared_for or None,
    )

    destination = Path(out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    html_path = destination.with_suffix(".html")
    html_path.write_text(memo.html, encoding="utf-8")

    heading("Memo")
    render_table(
        [
            {"field": "score", "value": memo.score_public_id},
            {"field": "template", "value": memo.template_version},
            {"field": "content hash", "value": memo.content_hash[:32]},
            {"field": "html", "value": str(html_path)},
        ],
        columns=("field", "value"),
    )

    if not pdf:
        console.print()
        ok(f"written to {html_path}")
        return

    try:
        pdf_path = to_pdf(memo, destination.with_suffix(".pdf"))
    except StageUnavailableError as exc:
        console.print()
        note(str(exc))
        ok(f"the HTML is complete at {html_path}")
        return

    console.print()
    ok(f"written to {pdf_path}")


def _load_published(conn: Any, public_id: str) -> Any:
    """Read a published score back out of the graph.

    Retrieval rather than recomputation. A memo has to show the number that was published, and recomputing
    would quietly revise a prediction the ledger has already committed.
    """
    from sqlalchemy import text

    from auspice.score.models import Score

    row = (
        conn.execute(
            text(
                """
            SELECT p.public_id, p.created_at, p.site, p.approval_probability, p.ci80_low, p.ci80_high,
                   p.confidence, p.abstained, p.abstention_reasons, p.months_p10, p.months_p50, p.months_p90,
                   p.rule_change_probability, p.drivers, p.precedents, p.mitigations, p.alternatives,
                   p.provenance, p.features_hash
            FROM prediction p WHERE p.public_id = :public_id
            """
            ).bindparams(public_id=public_id)
        )
        .mappings()
        .first()
    )

    if row is None:
        fail(
            f"no published score with the identifier {public_id}",
            hint="Run `auspice score site --publish` first, or `auspice ledger status` to see what exists.",
        )

    def as_float(value: Any) -> float | None:
        return None if value is None else float(value)

    determination: dict[str, Any] = {
        "approval_probability": as_float(row["approval_probability"]),
        "credible_interval_80": (
            (as_float(row["ci80_low"]), as_float(row["ci80_high"]))
            if row["ci80_low"] is not None and row["ci80_high"] is not None
            else None
        ),
        "interval_kind": "credible",
        "confidence": row["confidence"],
        "abstained": bool(row["abstained"]),
        "abstention_reasons": list(row["abstention_reasons"] or []),
        "time_to_decision_months": (
            {
                "p10": as_float(row["months_p10"]),
                "p50": as_float(row["months_p50"]),
                "p90": as_float(row["months_p90"]),
                "basis": "fitted",
            }
            if row["months_p50"] is not None
            else None
        ),
        "probability_of_rule_change_before_decision": as_float(row["rule_change_probability"]),
        "local_base_rate": None,
    }

    return Score.model_validate(
        {
            "public_id": row["public_id"],
            "generated_at": row["created_at"],
            "site": row["site"],
            "determination": determination,
            "drivers": list(row["drivers"] or []),
            "precedents": list(row["precedents"] or []),
            "mitigations": list(row["mitigations"] or []),
            "alternatives": list(row["alternatives"] or []),
            "evidence": [],
            "provenance": row["provenance"],
            "features_hash": row["features_hash"],
        }
    )
