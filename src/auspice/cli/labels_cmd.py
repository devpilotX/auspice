"""Label commands: validate, load, stats, verify."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from sqlalchemy import text

from auspice.cli.output import console, fail, heading, note, ok, render_table
from auspice.config import get_settings
from auspice.db import transaction
from auspice.domain import (
    BodyKind,
    InstrumentKind,
    Outcome,
    Relief,
    UseClass,
)
from auspice.models.eval.thresholds import (
    MIN_HELD_OUT_DECISIONS,
    MIN_LABELLED_DECISIONS,
)
from auspice.pipeline.graph import labels as labels_module

app = typer.Typer(
    no_args_is_help=True, help="The labelled decision dataset: hand built ground truth."
)


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
    ok(
        f"{report.decisions} decisions, {report.instruments} instruments, {report.citations} citations"
    )


@app.command("stats")
def stats() -> None:
    """What the graph holds, and how far it is from a usable training set."""
    heading("Label coverage")
    with transaction() as conn:
        by_jurisdiction = (
            conn.execute(
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
            )
            .mappings()
            .all()
        )

        totals = (
            conn.execute(
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
            )
            .mappings()
            .one()
        )

        provenance = (
            conn.execute(
                text(
                    """
                SELECT
                    count(*) AS citations,
                    count(*) FILTER (WHERE verified) AS verified
                FROM fact_evidence
                """
                )
            )
            .mappings()
            .one()
        )

        instruments = (
            conn.execute(
                text(
                    """
                SELECT j.slug, i.kind, count(*) AS n
                FROM instrument i JOIN jurisdiction j ON j.id = i.jurisdiction_id
                GROUP BY j.slug, i.kind ORDER BY j.slug, i.kind
                """
                )
            )
            .mappings()
            .all()
        )

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


@app.command("quote")
def quote(
    url: Annotated[str, typer.Option(help="The source document to quote from")],
    find: Annotated[str, typer.Option(help="A distinctive phrase to search for")],
    limit: Annotated[int, typer.Option(help="How many candidates to show")] = 8,
    context: Annotated[bool, typer.Option(help="Show the surrounding text")] = True,
) -> None:
    """Print quotable sentences from a document, verbatim, ready to paste into a citation.

    This is the repair tool and the fast path. Three citations in this repository failed
    verification, all of them transcription errors, and this is how such a row is fixed: search the
    real document for the phrase, copy the candidate exactly as printed. A quote taken from here
    cannot fail `auspice labels verify`, because it came out of the same parsed text the verifier
    matches against.
    """
    import asyncio

    from auspice.pipeline.extract.verify import verify_quote
    from auspice.pipeline.graph import labelling

    heading("Quote candidates")
    try:
        document = asyncio.run(labelling.fetch_and_parse(url))
    except labelling.LabellingError as exc:
        fail(str(exc))

    note(
        f"document {document.document_id[:12]}, {document.pages} page(s), {document.characters} characters"
    )
    if document.legibility < 0.5:
        note(
            f"legibility {document.legibility}. This looks like a scan. Check any candidate below "
            "reads as the source does before citing it."
        )

    try:
        candidates = labelling.find_quote_candidates(document.parsed, find, limit=limit)
    except labelling.LabellingError as exc:
        fail(str(exc))

    if not candidates:
        console.print()
        note(f"no sentence in this document contains {find!r}.")
        note("Try fewer words, or a number such as a vote tally, which survives rewording.")
        raise typer.Exit(1)

    for index, candidate in enumerate(candidates, start=1):
        console.print()
        console.print(
            f"[{index}] page {candidate.page}, characters {candidate.char_start} to {candidate.char_end}"
        )
        if context and candidate.context_before:
            console.print(f"    before: ...{candidate.context_before[-140:]}")
        console.print(f"    quote:  {candidate.text}")
        if context and candidate.context_after:
            console.print(f"    after:  {candidate.context_after[:140]}...")
        # Belt and braces. The candidate came from the parsed text, so this cannot fail, and it is
        # cheap enough to run anyway rather than assert the invariant in a comment.
        if not verify_quote(document.parsed, candidate.text).verified:
            fail(
                "a candidate did not verify against the document it came from. That is a defect in "
                "find_quote_candidates, not in the document. Do not use this output."
            )

    console.print()
    ok(f"{len(candidates)} candidate(s), every one verified against {document.document_id[:12]}")
    note("Copy a quote exactly as printed. Do not retype it and do not tidy the typography.")


@app.command("add")
def add(
    url: Annotated[str, typer.Option(help="The primary source for this row")],
    labelled_by: Annotated[str, typer.Option(help="Who is doing the labelling")],
    jurisdiction: Annotated[
        str | None, typer.Option(help="Registry slug, for example us-va-loudoun")
    ] = None,
    kind: Annotated[
        str, typer.Option(help="primary for an official record, else secondary")
    ] = "primary",
    section: Annotated[str, typer.Option(help="decisions or instruments")] = "decisions",
) -> None:
    """Add one labelled row, interactively, quoting from the fetched document.

    The order of work is deliberately inverted from hand editing the file. The document is fetched
    and parsed first, then the quote is selected out of the parsed text rather than retyped, so exact
    transcription stops being something a human can get wrong. Everything else is typed against the
    controlled vocabularies in `domain.py`, so a typo is refused at the prompt rather than surfacing
    as a validation failure ten rows later.

    One row is written at a time. A session interrupted at row twenty keeps nineteen.
    """
    import asyncio

    from auspice.pipeline.graph import labelling

    if section not in {"decisions", "instruments"}:
        fail(f"section must be decisions or instruments, not {section!r}")
    if kind not in {"primary", "secondary"}:
        fail(f"citation kind must be primary or secondary, not {kind!r}")

    settings = get_settings()
    path = settings.labels_path / labels_module.DEFAULT_LABELS_FILE
    if not path.exists():
        fail(f"{path} does not exist. This command edits the corpus, it does not create it.")

    heading("Fetching the source")
    try:
        document = asyncio.run(labelling.fetch_and_parse(url))
    except labelling.LabellingError as exc:
        fail(str(exc))

    note(
        f"document {document.document_id[:12]}, {document.pages} page(s), {document.characters} characters"
    )
    if document.legibility < 0.5:
        note(f"legibility {document.legibility}. This is a scan. Read every candidate carefully.")

    taken = labelling.existing_label_ids(path)
    resolved_jurisdiction = jurisdiction or _prompt_jurisdiction()

    payload: dict[str, Any]
    if section == "decisions":
        payload = _prompt_decision(
            document=document,
            jurisdiction=resolved_jurisdiction,
            labelled_by=labelled_by,
            citation_kind=kind,
            taken=taken,
        )
    else:
        payload = _prompt_instrument(
            document=document,
            jurisdiction=resolved_jurisdiction,
            labelled_by=labelled_by,
            citation_kind=kind,
            taken=taken,
        )

    console.print()
    heading("The row as it will be written")
    console.print(labelling.render_row(payload))
    if not typer.confirm("Write this row", default=True):
        note("nothing written")
        raise typer.Exit(0)

    try:
        if section == "decisions":
            label_set = labelling.append_decision(path, payload)
        else:
            label_set = labelling.append_instrument(path, payload)
    except ValidationError as exc:
        heading("Refused")
        for error in exc.errors():
            location = ".".join(str(p) for p in error["loc"])
            console.print(f"  {location}: {error['msg']}")
        fail(f"{len(exc.errors())} problem(s). The file was left unchanged.")
    except labelling.LabellingError as exc:
        fail(str(exc))

    console.print()
    ok(f"written to {path}")
    note(
        f"{len(label_set.terminal_decisions)} terminal decision(s) now held. "
        "Commit the file, then run `auspice labels load` and `auspice labels verify`."
    )
    _print_gap(len(label_set.terminal_decisions))


# ---------------------------------------------------------------------------
# Prompts
#
# Kept here rather than in the labelling module, so that module stays free of input and can be
# tested without driving a terminal. Everything below is the terminal, and nothing below decides
# anything: the vocabularies come from domain.py and the validation from the pydantic models.
# ---------------------------------------------------------------------------
def _prompt_choice(label: str, options: Sequence[str], *, default: str | None = None) -> str:
    """One value from a controlled vocabulary, refused until it is in the vocabulary."""
    console.print()
    console.print(f"{label}")
    for index, option in enumerate(options, start=1):
        console.print(f"  {index:>2}. {option}")
    while True:
        raw = typer.prompt("  number or value", default=default, show_default=default is not None)
        cleaned = str(raw).strip()
        if cleaned.isdigit() and 1 <= int(cleaned) <= len(options):
            return options[int(cleaned) - 1]
        if cleaned in options:
            return cleaned
        console.print(f"  not one of the {len(options)} options")


def _prompt_multi(label: str, options: Sequence[str]) -> list[str]:
    """One or more values, comma separated. Refused until every one is in the vocabulary."""
    while True:
        chosen = _prompt_choice(label, options)
        values = [chosen]
        extra = typer.prompt("  more, comma separated, or blank", default="", show_default=False)
        for token in str(extra).split(","):
            cleaned = token.strip()
            if not cleaned:
                continue
            if cleaned in options:
                values.append(cleaned)
            elif cleaned.isdigit() and 1 <= int(cleaned) <= len(options):
                values.append(options[int(cleaned) - 1])
            else:
                console.print(f"  {cleaned!r} is not one of the options")
                break
        else:
            # dict.fromkeys rather than set, to keep the order the labeller gave.
            return list(dict.fromkeys(values))


def _prompt_optional_date(label: str) -> date | None:
    while True:
        raw = typer.prompt(f"{label} as YYYY-MM-DD, or blank", default="", show_default=False)
        cleaned = str(raw).strip()
        if not cleaned:
            return None
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            console.print("  not a date. Use YYYY-MM-DD.")


def _prompt_optional_number(label: str) -> float | None:
    while True:
        raw = typer.prompt(f"{label}, or blank", default="", show_default=False)
        cleaned = str(raw).strip()
        if not cleaned:
            return None
        try:
            value = float(cleaned)
        except ValueError:
            console.print("  not a number")
            continue
        if value <= 0:
            console.print("  must be greater than zero. Leave blank if it is unknown.")
            continue
        return value


def _prompt_optional_int(label: str) -> int | None:
    while True:
        raw = typer.prompt(f"{label}, or blank", default="", show_default=False)
        cleaned = str(raw).strip()
        if not cleaned:
            return None
        if not cleaned.isdigit():
            console.print("  not a whole number")
            continue
        return int(cleaned)


def _prompt_jurisdiction() -> str:
    """A slug that is actually in the registry. A label for an unknown jurisdiction will not load."""
    from auspice.pipeline.registry import load_registry

    slugs = sorted(j.slug for j in load_registry().jurisdictions)
    return _prompt_choice("Jurisdiction", slugs)


def _prompt_citation(*, document: Any, citation_kind: str, purpose: str) -> dict[str, Any]:
    """One citation, whose quote is selected from the parsed document rather than typed."""
    from auspice.pipeline.graph import labelling

    console.print()
    console.print(f"Quote supporting the {purpose}.")
    note("Search the document for a distinctive phrase. A vote tally survives rewording best.")

    while True:
        phrase = str(typer.prompt("  search for")).strip()
        try:
            candidates = labelling.find_quote_candidates(document.parsed, phrase)
        except labelling.LabellingError as exc:
            console.print(f"  {exc}")
            continue
        if not candidates:
            console.print(f"  no sentence contains {phrase!r}. Try fewer words.")
            continue

        for index, candidate in enumerate(candidates, start=1):
            console.print()
            console.print(f"  [{index}] page {candidate.page}")
            if candidate.context_before:
                console.print(f"      before: ...{candidate.context_before[-120:]}")
            console.print(f"      quote:  {candidate.text}")
            if candidate.context_after:
                console.print(f"      after:  {candidate.context_after[:120]}...")

        console.print()
        chosen = str(
            typer.prompt(
                "  number to use, or blank to search again", default="", show_default=False
            )
        ).strip()
        if not chosen:
            continue
        if not chosen.isdigit() or not 1 <= int(chosen) <= len(candidates):
            console.print("  not one of the candidates")
            continue

        candidate = candidates[int(chosen) - 1]
        default_title = (document.title or document.url)[:300]
        title = str(typer.prompt("  document title", default=default_title)).strip()
        return {
            "url": document.url,
            "document_title": title,
            "quote": candidate.text,
            "page": candidate.page,
            "retrieved_on": date.today(),
            "kind": citation_kind,
        }


def _prompt_decision(
    *,
    document: Any,
    jurisdiction: str,
    labelled_by: str,
    citation_kind: str,
    taken: set[str],
) -> dict[str, Any]:
    from auspice.pipeline.graph import labelling

    heading("The decision")
    case_number = str(
        typer.prompt("Case number as published, or blank", default="", show_default=False)
    ).strip()
    project_name = str(
        typer.prompt("Project name, or blank", default="", show_default=False)
    ).strip()
    applicant = str(typer.prompt("Applicant, or blank", default="", show_default=False)).strip()

    body = _prompt_choice("Deciding body", [b.value for b in BodyKind])
    use_class = _prompt_choice("Use class", [u.value for u in UseClass])
    relief = _prompt_multi("Relief sought", [r.value for r in Relief])
    outcome = _prompt_choice("Outcome", [o.value for o in Outcome])

    filed_on = _prompt_optional_date("Filed on")
    decided_on = _prompt_optional_date("Decided on")
    acres = _prompt_optional_number("Acres")
    capacity_mw = _prompt_optional_number("Capacity in MW")
    vote_for = _prompt_optional_int("Votes for")
    vote_against = _prompt_optional_int("Votes against")
    vote_abstain = _prompt_optional_int("Abstentions")

    subject = project_name or case_number or use_class
    suggested = labelling.suggest_label_id(
        jurisdiction=jurisdiction, subject=subject, on=decided_on, taken=sorted(taken)
    )
    label_id = str(typer.prompt("Label id", default=suggested)).strip()
    if label_id in taken:
        fail(f"label_id {label_id!r} is already used. Ids are never reused.")

    citation = _prompt_citation(document=document, citation_kind=citation_kind, purpose="outcome")

    notes = str(typer.prompt("Notes, or blank", default="", show_default=False)).strip()

    payload: dict[str, Any] = {
        "label_id": label_id,
        "jurisdiction": jurisdiction,
        "labelled_by": labelled_by,
        "labelled_on": date.today(),
        "case_number": case_number or None,
        "body": body,
        "applicant": applicant or None,
        "project_name": project_name or None,
        "use_class": use_class,
        "relief_sought": relief,
        "acres": acres,
        "capacity_mw": capacity_mw,
        "filed_on": filed_on,
        "decided_on": decided_on,
        "outcome": outcome,
        "vote_for": vote_for,
        "vote_against": vote_against,
        "vote_abstain": vote_abstain,
        "notes": notes or None,
        "citations": [citation],
    }
    return {key: value for key, value in payload.items() if value is not None}


def _prompt_instrument(
    *,
    document: Any,
    jurisdiction: str,
    labelled_by: str,
    citation_kind: str,
    taken: set[str],
) -> dict[str, Any]:
    from auspice.pipeline.graph import labelling

    heading("The instrument")
    title = str(typer.prompt("Title")).strip()
    instrument_kind = _prompt_choice("Instrument kind", [k.value for k in InstrumentKind])
    body = _prompt_choice("Adopting body", [b.value for b in BodyKind])
    adopted_on = _prompt_optional_date("Adopted on")
    effective_on = _prompt_optional_date("Effective on")
    expires_on = _prompt_optional_date("Expires on")
    applies_to = _prompt_multi("Applies to use classes", [u.value for u in UseClass])
    vote_for = _prompt_optional_int("Votes for")
    vote_against = _prompt_optional_int("Votes against")

    suggested = labelling.suggest_label_id(
        jurisdiction=jurisdiction, subject=title, on=adopted_on, taken=sorted(taken)
    )
    label_id = str(typer.prompt("Label id", default=suggested)).strip()
    if label_id in taken:
        fail(f"label_id {label_id!r} is already used. Ids are never reused.")

    citation = _prompt_citation(document=document, citation_kind=citation_kind, purpose="adoption")
    notes = str(typer.prompt("Notes, or blank", default="", show_default=False)).strip()

    payload: dict[str, Any] = {
        "label_id": label_id,
        "jurisdiction": jurisdiction,
        "labelled_by": labelled_by,
        "labelled_on": date.today(),
        "kind": instrument_kind,
        "body": body,
        "title": title,
        "adopted_on": adopted_on,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "applies_to_use_classes": applies_to,
        "vote_for": vote_for,
        "vote_against": vote_against,
        "notes": notes or None,
        "citations": [citation],
    }
    return {key: value for key, value in payload.items() if value is not None}


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
