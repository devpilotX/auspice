"""Pipeline commands for stages 1 to 6 and 11.

These wrap code that already exists. Each is written so that running it twice is the same as running it
once, and so that the summary it prints is the thing an operator needs rather than everything that happened.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Annotated, Any

import typer
from sqlalchemy import text

from auspice.cli.output import ABSENT, console, fail, heading, note, ok, render_table
from auspice.db import transaction
from auspice.domain import UseClass

ingest_app = typer.Typer(no_args_is_help=True, help="Stage 1: fetch, hash, store, dead letter.")
parse_app = typer.Typer(no_args_is_help=True, help="Stage 2: the document cascade.")
extract_app = typer.Typer(no_args_is_help=True, help="Stage 4: facts with verified provenance.")
resolve_app = typer.Typer(no_args_is_help=True, help="Stage 5: entity resolution.")
transcribe_app = typer.Typer(
    no_args_is_help=True, help="Stage 3: hearing audio to a citable transcript."
)
monitor_app = typer.Typer(no_args_is_help=True, help="Stage 11: diffing, materiality, alerts.")


# ===========================================================================
# Stage 1
# ===========================================================================
@ingest_app.command("run")
def ingest_run(
    jurisdiction: Annotated[str, typer.Option(help="Limit to one registry slug")] = "",
    days: Annotated[int, typer.Option(help="How far back to enumerate meetings")] = 30,
    limit: Annotated[
        int, typer.Option(help="Stop after this many documents. 0 means no limit.")
    ] = 0,
) -> None:
    """Enumerate meetings through the platform adapters and store every document they point at.

    Every fetch is recorded whether it succeeded or not, and repeated failures land in the dead letter
    queue. Re-running on unchanged content costs nothing, because the raw store is keyed by the hash of the
    bytes and a matching hash means no downstream work.
    """
    from auspice.pipeline.adapters import for_platform
    from auspice.pipeline.ingest import (
        Fetcher,
        mark_source_result,
        record_attempt,
        record_dead_letter,
        register_document,
    )

    since = date.today() - timedelta(days=days)
    heading(f"Ingesting from {since.isoformat()}")

    with transaction() as conn:
        sources = (
            conn.execute(
                text(
                    """
                SELECT s.id, s.url, s.kind, s.platform, s.platform_config,
                       j.id AS jurisdiction_id, j.slug, j.name
                FROM source s
                JOIN jurisdiction j ON j.id = s.jurisdiction_id
                WHERE s.enabled
                  AND (:slug = '' OR j.slug = :slug)
                ORDER BY j.slug
                """
                ).bindparams(slug=jurisdiction)
            )
            .mappings()
            .all()
        )

        if not sources:
            fail(
                "no enabled sources match",
                hint="Run `auspice registry load`, and `auspice registry probe` to detect platforms.",
            )

        rows: list[dict[str, Any]] = []
        stored = 0

        async def crawl() -> None:
            nonlocal stored
            async with Fetcher() as fetcher:
                for source in sources:
                    adapter = for_platform(str(source["platform"]))
                    if adapter is None:
                        rows.append(
                            {
                                "jurisdiction": source["slug"],
                                "platform": source["platform"],
                                "meetings": ABSENT,
                                "documents": ABSENT,
                                "note": "no adapter, so this county produces nothing and shows as never fetched",
                            }
                        )
                        continue

                    config = dict(source["platform_config"] or {})
                    try:
                        meetings = await adapter.enumerate_meetings(
                            base_url=str(source["url"]),
                            config=config,
                            since=since,
                            client=fetcher._client,
                        )
                    except Exception as exc:
                        mark_source_result(conn, int(source["id"]), ok=False)
                        record_dead_letter(
                            conn,
                            stage="ingest",
                            subject=str(source["url"]),
                            jurisdiction_id=int(source["jurisdiction_id"]),
                            error_type=type(exc).__name__,
                            error_message=str(exc)[:400],
                        )
                        rows.append(
                            {
                                "jurisdiction": source["slug"],
                                "platform": source["platform"],
                                "meetings": 0,
                                "documents": 0,
                                "note": f"failed: {str(exc)[:60]}",
                            }
                        )
                        continue

                    documents = 0
                    for meeting in meetings:
                        if limit and stored >= limit:
                            break
                        refs = await adapter.documents_for(
                            meeting=meeting, config=config, client=fetcher._client
                        )
                        for ref in refs:
                            if limit and stored >= limit:
                                break
                            outcome = await fetcher.fetch(
                                ref.url,
                                jurisdiction_id=int(source["jurisdiction_id"]),
                                source_id=int(source["id"]),
                                kind=ref.kind.value,
                            )
                            document_id = register_document(
                                conn,
                                outcome,
                                jurisdiction_id=int(source["jurisdiction_id"]),
                                source_id=int(source["id"]),
                                kind=ref.kind.value,
                                title=ref.title,
                                published_on=ref.published_on,
                            )
                            record_attempt(
                                conn, outcome, source_id=int(source["id"]), document_id=document_id
                            )
                            if outcome.ok:
                                documents += 1
                                stored += 1

                    mark_source_result(conn, int(source["id"]), ok=True)
                    rows.append(
                        {
                            "jurisdiction": source["slug"],
                            "platform": source["platform"],
                            "meetings": len(meetings),
                            "documents": documents,
                            "note": ABSENT,
                        }
                    )

        asyncio.run(crawl())

    render_table(rows, numeric=("meetings", "documents"))
    console.print()
    ok(f"{stored} document(s) stored")
    note("Re-running costs nothing for content that has not changed.")


@ingest_app.command("freshness")
def ingest_freshness() -> None:
    """Per source staleness against its own SLA. Published, not internal."""
    from auspice.pipeline.ingest import freshness_report

    heading("Source freshness")
    with transaction() as conn:
        rows = freshness_report(conn)
    if not rows:
        note("no enabled sources")
        return
    render_table(
        [
            {
                "jurisdiction": row["slug"],
                "kind": row["kind"],
                "platform": row["platform"],
                "sla_hours": row["refresh_hours"],
                "hours_since": row["hours_since_success"],
                "failures": row["consecutive_failures"],
                "status": row["status"],
            }
            for row in rows
        ],
        numeric=("sla_hours", "hours_since", "failures"),
    )


@ingest_app.command("dead-letters")
def ingest_dead_letters(
    stage: Annotated[str, typer.Option(help="Limit to one stage")] = "",
) -> None:
    """The dead letter queue. Drained weekly to zero, because a queue nobody drains hides a broken adapter."""
    heading("Dead letters")
    with transaction() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT dl.stage, dl.subject, dl.error_type, dl.error_message, dl.attempts,
                       dl.first_seen_at, dl.last_seen_at, j.slug
                FROM dead_letter dl
                LEFT JOIN jurisdiction j ON j.id = dl.jurisdiction_id
                WHERE dl.resolved_at IS NULL AND (:stage = '' OR dl.stage = :stage)
                ORDER BY dl.attempts DESC, dl.last_seen_at DESC
                """
                ).bindparams(stage=stage)
            )
            .mappings()
            .all()
        )

    if not rows:
        ok("the queue is empty")
        return
    render_table(
        [
            {
                "stage": row["stage"],
                "jurisdiction": row["slug"] or ABSENT,
                "subject": str(row["subject"])[:60],
                "error": row["error_type"],
                "attempts": row["attempts"],
                "message": str(row["error_message"])[:70],
            }
            for row in rows
        ],
        numeric=("attempts",),
    )


# ===========================================================================
# Stage 2
# ===========================================================================
@parse_app.command("run")
def parse_run(
    limit: Annotated[
        int, typer.Option(help="Stop after this many documents. 0 means no limit.")
    ] = 0,
    reparse: Annotated[bool, typer.Option(help="Re-parse documents already parsed")] = False,
) -> None:
    """Run the cost ordered cascade over stored documents.

    PyMuPDF, then pdfplumber, then Tesseract, escalating only when the legibility gate fails. The escalation
    rate per jurisdiction is worth watching: a sudden rise means a source changed format.
    """
    from auspice.errors import IllegibleDocumentError, ParseError
    from auspice.pipeline.ingest import get_raw_store, record_dead_letter
    from auspice.pipeline.parse import parse_bytes, persist_parsed, tesseract_available

    heading("Parsing")
    if not tesseract_available():
        note(
            "Tesseract is not installed, so scanned pages will fail the legibility gate and be recorded"
        )
        note("as illegible rather than silently skipped.")

    store = get_raw_store()
    parsed_count = 0
    escalations = 0
    failures = 0

    with transaction() as conn:
        documents = (
            conn.execute(
                text(
                    """
                SELECT d.id, d.storage_key, d.media_type, d.kind, j.slug
                FROM document d
                LEFT JOIN jurisdiction j ON j.id = d.jurisdiction_id
                WHERE (:reparse OR d.parsed_at IS NULL)
                  AND d.storage_key NOT LIKE 'pending/%'
                ORDER BY d.fetched_at DESC
                """
                ).bindparams(reparse=reparse)
            )
            .mappings()
            .all()
        )

        for document in documents[: limit or None]:
            try:
                data = store.get(str(document["storage_key"]))
                parsed = parse_bytes(
                    data,
                    document_id=str(document["id"]),
                    media_type=document["media_type"],
                )
            except (ParseError, IllegibleDocumentError, FileNotFoundError, OSError) as exc:
                failures += 1
                record_dead_letter(
                    conn,
                    stage="parse",
                    subject=str(document["id"]),
                    jurisdiction_id=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc)[:400],
                )
                continue

            persist_parsed(conn, parsed)
            parsed_count += 1
            escalations += parsed.escalations

    render_table(
        [
            {"metric": "documents parsed", "value": parsed_count},
            {"metric": "page escalations", "value": escalations},
            {"metric": "failures", "value": failures},
        ],
        columns=("metric", "value"),
    )
    console.print()
    if failures:
        note(
            f"{failures} document(s) went to the dead letter queue. Run `auspice ingest dead-letters`."
        )
    ok(f"{parsed_count} document(s) parsed")


# ===========================================================================
# Stage 3
# ===========================================================================
@transcribe_app.command("status")
def transcribe_status() -> None:
    """Whether the transcription stage can run, and what it holds."""
    from auspice.config import get_settings
    from auspice.pipeline.transcribe import ffmpeg_available

    heading("Transcription")
    settings = get_settings()
    ffmpeg = ffmpeg_available(settings)

    try:
        import faster_whisper  # noqa: F401

        model_available = True
    except ImportError:
        model_available = False

    with transaction() as conn:
        held = (
            conn.execute(
                text(
                    """
                SELECT count(DISTINCT document_id) AS documents, count(*) AS segments
                FROM transcript_segment
                """
                )
            )
            .mappings()
            .one()
        )

    render_table(
        [
            {
                "requirement": "ffmpeg",
                "state": "available" if ffmpeg else f"not at {settings.ffmpeg_path}",
            },
            {
                "requirement": "faster-whisper",
                "state": "installed" if model_available else "install with --extra transcribe",
            },
            {"requirement": "model", "state": settings.whisper_model},
            {"requirement": "device", "state": settings.whisper_device},
            {"requirement": "transcripts held", "state": str(held["documents"])},
            {"requirement": "segments held", "state": str(held["segments"])},
        ],
        columns=("requirement", "state"),
    )
    console.print()
    if ffmpeg and model_available:
        ok("the stage can run")
    else:
        note(
            "The stage reports as unavailable rather than producing empty transcripts, because an empty"
        )
        note("transcript and a silent hearing are not the same thing.")


# ===========================================================================
# Stage 4
# ===========================================================================
@extract_app.command("run")
def extract_run(
    limit: Annotated[
        int, typer.Option(help="Stop after this many documents. 0 means no limit.")
    ] = 0,
    single_pass: Annotated[bool, typer.Option(help="Skip the verification pass")] = False,
) -> None:
    """Extract facts with verified provenance.

    Needs a language model key. Without one it reports the stage as unavailable rather than returning empty
    results, because an empty result and a missing key are different things and a corpus must not confuse
    them.
    """
    from auspice.errors import StageUnavailableError
    from auspice.pipeline.extract import ExtractionReport, LanguageModel, extract_document

    heading("Extraction")
    report = ExtractionReport()

    with transaction() as conn, LanguageModel() as model:
        if not model.available:
            note("No language model is configured, so this stage cannot run.")
            note("Set AUSPICE_LLM_PROVIDER and AUSPICE_LLM_API_KEY.")
            note("")
            note(
                "The stage reports unavailable rather than producing nothing, because a stage that"
            )
            note("silently yields no facts looks identical to one that found none.")
            raise typer.Exit(0)

        documents = (
            conn.execute(
                text(
                    """
                SELECT d.id, d.kind, d.published_on, j.id AS jurisdiction_id, j.name, j.region,
                       j.admin_codes
                FROM document d
                JOIN jurisdiction j ON j.id = d.jurisdiction_id
                WHERE d.parsed_at IS NOT NULL
                ORDER BY d.published_on DESC NULLS LAST
                """
                )
            )
            .mappings()
            .all()
        )

        for document in documents[: limit or None]:
            use_classes = [
                UseClass(value)
                for value in (document["admin_codes"] or {}).get("target_use_classes", [])
                if value in {member.value for member in UseClass}
            ] or [UseClass.data_center_hyperscale]

            try:
                extract_document(
                    conn,
                    document_id=str(document["id"]),
                    jurisdiction_id=int(document["jurisdiction_id"]),
                    jurisdiction_name=str(document["name"]),
                    region=str(document["region"] or ""),
                    document_kind=str(document["kind"]),
                    published_on=document["published_on"],
                    use_classes=use_classes,
                    model=model,
                    report=report,
                    two_pass=not single_pass,
                )
            except StageUnavailableError as exc:
                fail(str(exc))

    render_table(
        [
            {"metric": key, "value": value}
            for key, value in report.as_dict().items()
            if value is not None
        ],
        columns=("metric", "value"),
    )
    console.print()
    if report.quote_failures:
        note(
            f"{report.quote_failures} extraction(s) were discarded because a quote was not found verbatim. "
            "That is the mechanism working, not a failure."
        )
    ok(f"{report.facts_landed} fact(s) landed, every one with a verified quote")


@extract_app.command("verification-rate")
def extract_verification_rate(
    hours: Annotated[int, typer.Option(help="Window in hours")] = 24,
) -> None:
    """The section 16.2 metric. Below 99 percent, extraction is unsafe and the pipeline stops."""
    from auspice.pipeline.extract import quote_verification_rate

    heading(f"Quote verification, last {hours} hours")
    with transaction() as conn:
        result = quote_verification_rate(conn, hours=hours)

    render_table(
        [
            {"metric": key, "value": value if value is not None else ABSENT}
            for key, value in result.items()
        ],
        columns=("metric", "value"),
    )
    console.print()
    if result["total"] == 0:
        note("no citations recorded in this window")
    elif result["safe"]:
        ok(f"{result['rate']:.2%} verified, above the 99 percent floor")
    else:
        fail(
            f"{result['rate']:.2%} verified, below the 99 percent floor",
            hint="Extraction is unsafe at this rate. Find out whether it is the model or a source.",
        )


# ===========================================================================
# Stage 5
# ===========================================================================
@resolve_app.command("run")
def resolve_run() -> None:
    """Cluster applicant strings and attach applications to their cluster."""
    from auspice.pipeline.resolve import precision_estimate, resolve_applicants

    heading("Entity resolution")
    with transaction() as conn:
        report = resolve_applicants(conn)
        precision = precision_estimate(conn)

    render_table(
        [{"metric": key, "value": value} for key, value in report.as_dict().items()],
        columns=("metric", "value"),
    )

    if report.candidates:
        console.print()
        render_table(
            report.candidates,
            columns=("kind", "normalised", "nearest", "score"),
            numeric=("score",),
            title="Queued for adjudication, not merged",
        )

    console.print()
    render_table(
        [
            {"metric": key, "value": value if value is not None else ABSENT}
            for key, value in precision.items()
            if key != "note"
        ],
        columns=("metric", "value"),
    )
    console.print()
    note(str(precision["note"]))


# ===========================================================================
# Stage 11
# ===========================================================================
@monitor_app.command("run")
def monitor_run(
    days: Annotated[int, typer.Option(help="How far back to look for changes")] = 1,
) -> None:
    """Detect changes, score them for materiality, and record an alert per affected watch."""
    from auspice.monitor import daily_run

    heading(f"Monitoring, looking back {days} day(s)")
    with transaction() as conn:
        report = daily_run(conn, lookback_days=days)

    render_table(
        [{"metric": key, "value": value} for key, value in report.as_dict().items()],
        columns=("metric", "value"),
    )
    console.print()
    if report.alerts_suppressed:
        note(
            f"{report.alerts_suppressed} alert(s) were recorded and not delivered, each with a reason. "
            "An alert system that cries wolf gets muted in a week."
        )
    ok(f"{report.alerts_created} alert(s) to deliver")


@monitor_app.command("pending")
def monitor_pending() -> None:
    """Alerts created and not yet delivered, most material first."""
    from auspice.monitor import pending_alerts

    heading("Pending alerts")
    with transaction() as conn:
        rows = pending_alerts(conn)

    if not rows:
        note("nothing to deliver")
        return

    render_table(
        [
            {
                "subscriber": row["subscriber"],
                "site": row["label"],
                "jurisdiction": row["slug"],
                "materiality": row["materiality"],
                "headline": row["headline"],
            }
            for row in rows
        ],
        numeric=("materiality",),
    )


@monitor_app.command("watch")
def monitor_watch(
    subscriber: Annotated[str, typer.Argument(help="API key label, until billing exists")],
    label: Annotated[str, typer.Argument(help="What the customer calls this site")],
    jurisdiction: Annotated[str, typer.Argument(help="Registry slug")],
    use_class: Annotated[
        str, typer.Option(help="Use class to watch for")
    ] = "data_center_hyperscale",
) -> None:
    """Add a site to the watchlist. Monitoring is what turns a report into a subscription."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from auspice.db import schema

    heading("Adding a watch")
    with transaction() as conn:
        jurisdiction_id = conn.execute(
            text("SELECT id FROM jurisdiction WHERE slug = :slug").bindparams(slug=jurisdiction)
        ).scalar()
        if jurisdiction_id is None:
            fail(
                f"{jurisdiction} is not in the registry",
                hint="Run `auspice registry status` for the twelve counties covered.",
            )
        resolved_id = int(jurisdiction_id)

        statement = pg_insert(schema.watch).values(
            subscriber=subscriber,
            label=label,
            jurisdiction_id=resolved_id,
            site={"use_class": use_class},
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[schema.watch.c.subscriber, schema.watch.c.label],
                set_={"jurisdiction_id": resolved_id, "active": True},
            )
        )

    ok(f"{subscriber} is now watching {label} in {jurisdiction}")
