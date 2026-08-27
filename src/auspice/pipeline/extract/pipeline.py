"""Stage 4: extraction.

The pipeline that turns a parsed document into facts with verified provenance.

The sequence per document is:

    triage (cheap model)  ->  extract (frontier)  ->  verify quotes  ->  second pass  ->  land

Anything that fails quote verification is discarded and the extraction is retried. Anything where
the two passes disagree goes to the review queue rather than into the graph. Nothing lands without
at least one quote that was found verbatim in the stored source text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from dateutil.parser import ParserError
from dateutil.parser import parse as parse_date
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.domain import (
    Outcome,
    Relief,
    UseClass,
    competing_risk_for,
    parse_vote,
)
from auspice.errors import QuoteVerificationError, SchemaViolationError, StageUnavailableError
from auspice.logging import get_logger
from auspice.pipeline.extract.client import LanguageModel, cache_key
from auspice.pipeline.extract.prompts import get_prompt
from auspice.pipeline.extract.schemas import SCHEMA_VERSION, array_wrapper
from auspice.pipeline.extract.verify import verify_extraction_evidence
from auspice.pipeline.parse import ParsedDocument, load_parsed

log = get_logger(__name__, _stage="extract")

# Below this the fact is queued for human review rather than landed.
REVIEW_CONFIDENCE = 0.6

# How much document text to send. Page markers are inserted so the model can cite a page.
MAX_DOCUMENT_CHARS = 180_000


@dataclass(slots=True)
class ExtractionReport:
    documents: int = 0
    triaged_out: int = 0
    facts_landed: int = 0
    facts_discarded: int = 0
    quote_failures: int = 0
    schema_failures: int = 0
    queued_for_review: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unavailable_reason: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "triaged_out": self.triaged_out,
            "facts_landed": self.facts_landed,
            "facts_discarded": self.facts_discarded,
            "quote_failures": self.quote_failures,
            "schema_failures": self.schema_failures,
            "queued_for_review": self.queued_for_review,
            "cache_hits": self.cache_hits,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "unavailable_reason": self.unavailable_reason,
        }


def render_for_model(parsed: ParsedDocument, *, max_chars: int = MAX_DOCUMENT_CHARS) -> str:
    """Insert page markers so a quote can be attributed to a page.

    The markers are on their own lines and are stripped from consideration during verification,
    because they are not part of the source text. Verification runs against ``parsed.full_text``,
    which has no markers, so a model that quotes a marker fails verification, which is correct.
    """
    parts: list[str] = []
    used = 0
    for page in parsed.pages:
        marker = f"\n[page {page.page}]\n"
        if used + len(marker) + len(page.text) > max_chars:
            parts.append(f"\n[truncated after page {page.page - 1} of {len(parsed.pages)}]\n")
            break
        parts.append(marker)
        parts.append(page.text)
        used += len(marker) + len(page.text)
    return "".join(parts)


def _coerce_date(value: object) -> date | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return parse_date(str(value)).date()
    except (ParserError, ValueError, OverflowError):
        return None


def _cached_run(conn: Connection, key: str, pass_number: int) -> Any:
    return conn.execute(
        select(schema.extraction_run.c.id, schema.extraction_run.c.status)
        .where(schema.extraction_run.c.cache_key == key)
        .where(schema.extraction_run.c.pass_number == pass_number)
    ).first()


def _record_run(
    conn: Connection,
    *,
    document_id: str,
    key: str,
    schema_name: str,
    prompt_version: str,
    model: str,
    pass_number: int,
    status: str,
    facts_extracted: int = 0,
    facts_discarded: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    raw_response: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    statement = pg_insert(schema.extraction_run).values(
        document_id=document_id,
        cache_key=key,
        schema_name=schema_name,
        schema_version=SCHEMA_VERSION,
        prompt_version=prompt_version,
        model=model,
        pass_number=pass_number,
        status=status,
        facts_extracted=facts_extracted,
        facts_discarded=facts_discarded,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw_response=raw_response,
        error=error,
    )
    conn.execute(
        statement.on_conflict_do_update(
            index_elements=[schema.extraction_run.c.cache_key, schema.extraction_run.c.pass_number],
            set_={
                "status": statement.excluded.status,
                "facts_extracted": statement.excluded.facts_extracted,
                "facts_discarded": statement.excluded.facts_discarded,
                "input_tokens": statement.excluded.input_tokens,
                "output_tokens": statement.excluded.output_tokens,
                "raw_response": statement.excluded.raw_response,
                "error": statement.excluded.error,
            },
        )
    )


def extract_document(
    conn: Connection,
    *,
    document_id: str,
    jurisdiction_id: int,
    jurisdiction_name: str,
    region: str,
    document_kind: str,
    published_on: date | None,
    use_classes: list[UseClass],
    model: LanguageModel,
    report: ExtractionReport,
    two_pass: bool = True,
) -> None:
    """Extract decisions and instruments from one parsed document."""
    parsed = load_parsed(conn, document_id)
    if parsed is None:
        report.notes.append(f"{document_id[:12]} has not been parsed")
        return

    report.documents += 1
    document_text = render_for_model(parsed)
    variables: dict[str, object] = {
        "jurisdiction_name": jurisdiction_name,
        "region": region,
        "document_kind": document_kind,
        "published_on": published_on.isoformat() if published_on else "unknown",
        "use_classes": ", ".join(u.value for u in use_classes),
        "document_text": document_text,
    }

    # --- Triage on the cheap tier ------------------------------------------
    triage_prompt = get_prompt("triage")
    triage_key = cache_key(
        document_id=document_id,
        schema_name="triage",
        schema_version=SCHEMA_VERSION,
        prompt=triage_prompt,
        model=model.model_for("cheap"),
    )
    cached = _cached_run(conn, triage_key, 1)
    if cached is not None and cached.status == "refused":
        report.cache_hits += 1
        report.triaged_out += 1
        return

    if cached is None:
        from auspice.pipeline.extract.schemas import TRIAGE_SCHEMA

        try:
            triage = model.complete_structured(
                prompt=triage_prompt,
                schema=TRIAGE_SCHEMA,
                variables={k: v for k, v in variables.items() if k != "document_kind"}
                | {"document_kind": document_kind},
                tier="cheap",
            )
        except SchemaViolationError as exc:
            report.schema_failures += 1
            _record_run(
                conn,
                document_id=document_id,
                key=triage_key,
                schema_name="triage",
                prompt_version=triage_prompt.version,
                model=model.model_for("cheap"),
                pass_number=1,
                status="schema_violation",
                error="; ".join(exc.errors[:3]),
            )
            return

        report.input_tokens += triage.usage.input_tokens
        report.output_tokens += triage.usage.output_tokens
        relevant = bool(triage.payload.get("relevant"))
        _record_run(
            conn,
            document_id=document_id,
            key=triage_key,
            schema_name="triage",
            prompt_version=triage_prompt.version,
            model=triage.model,
            pass_number=1,
            status="ok" if relevant else "refused",
            input_tokens=triage.usage.input_tokens,
            output_tokens=triage.usage.output_tokens,
            raw_response=triage.payload,
        )
        if not relevant:
            report.triaged_out += 1
            return
    else:
        report.cache_hits += 1

    # --- Extract on the frontier tier -------------------------------------
    for schema_name in ("decision_event", "instrument"):
        prompt = get_prompt(schema_name)
        wrapper = array_wrapper(schema_name)
        key = cache_key(
            document_id=document_id,
            schema_name=schema_name,
            schema_version=SCHEMA_VERSION,
            prompt=prompt,
            model=model.model_for("frontier"),
        )
        if _cached_run(conn, key, 1) is not None:
            report.cache_hits += 1
            continue

        try:
            completion = model.complete_structured(
                prompt=prompt, schema=wrapper, variables=variables, tier="frontier"
            )
        except SchemaViolationError as exc:
            report.schema_failures += 1
            _record_run(
                conn,
                document_id=document_id,
                key=key,
                schema_name=schema_name,
                prompt_version=prompt.version,
                model=model.model_for("frontier"),
                pass_number=1,
                status="schema_violation",
                error="; ".join(exc.errors[:3]),
            )
            continue

        report.input_tokens += completion.usage.input_tokens
        report.output_tokens += completion.usage.output_tokens
        items = list(completion.payload.get("items", []))

        landed = 0
        discarded = 0
        for item in items:
            try:
                locations = verify_extraction_evidence(parsed, item.get("evidence", []))
            except QuoteVerificationError as exc:
                discarded += 1
                report.quote_failures += 1
                report.facts_discarded += 1
                log.warning(
                    "extraction discarded, quote not verified",
                    document_id=document_id[:12],
                    schema=schema_name,
                    quote=exc.quote,
                )
                continue

            confidence = float(item.get("confidence", 0.0))
            if confidence < REVIEW_CONFIDENCE:
                report.queued_for_review += 1
                from auspice.pipeline.ingest import record_dead_letter

                record_dead_letter(
                    conn,
                    stage="extract",
                    subject=f"{document_id}:{schema_name}:{landed + discarded}",
                    jurisdiction_id=jurisdiction_id,
                    error_type="low_confidence",
                    error_message=f"confidence {confidence} below {REVIEW_CONFIDENCE}",
                    payload=item,
                )
                continue

            if schema_name == "decision_event":
                landed += _land_decision(
                    conn,
                    item=item,
                    locations=locations,
                    document_id=document_id,
                    jurisdiction_id=jurisdiction_id,
                    prompt_version=prompt.version,
                )
            else:
                landed += _land_instrument(
                    conn,
                    item=item,
                    locations=locations,
                    document_id=document_id,
                    jurisdiction_id=jurisdiction_id,
                    prompt_version=prompt.version,
                )

        report.facts_landed += landed
        _record_run(
            conn,
            document_id=document_id,
            key=key,
            schema_name=schema_name,
            prompt_version=prompt.version,
            model=completion.model,
            pass_number=1,
            status="ok",
            facts_extracted=landed,
            facts_discarded=discarded,
            input_tokens=completion.usage.input_tokens,
            output_tokens=completion.usage.output_tokens,
        )

        # --- Second pass on anything that landed --------------------------
        if two_pass and landed:
            _second_pass(
                conn,
                model=model,
                items=items,
                variables=variables,
                schema_name=schema_name,
                key=key,
                jurisdiction_id=jurisdiction_id,
                document_id=document_id,
                report=report,
            )


def _land_decision(
    conn: Connection,
    *,
    item: dict[str, Any],
    locations: list[Any],
    document_id: str,
    jurisdiction_id: int,
    prompt_version: str,
) -> int:
    use_class_raw = item.get("use_class")
    if use_class_raw is None:
        # Without a use class the row cannot join to a base rate, so it is not usable as a
        # training example. It is kept as an event so the timeline is complete.
        _write_event(conn, item, jurisdiction_id=jurisdiction_id, application_id=None)
        return 0

    outcome = Outcome(item.get("outcome", Outcome.unknown.value))
    relief = [Relief(r) for r in item.get("relief_sought", [])] or [Relief.other]
    vote = parse_vote(str(item.get("vote") or ""))

    case_number = item.get("case_number")
    external_id = (
        case_number or f"extracted:{document_id[:16]}:{item.get('project_name') or 'unnamed'}"
    )

    statement = (
        pg_insert(schema.application)
        .values(
            jurisdiction_id=jurisdiction_id,
            external_id=external_id,
            applicant_raw=item.get("applicant"),
            use_class=UseClass(use_class_raw).value,
            relief_sought=[r.value for r in relief],
            capacity_mw=item.get("capacity_mw"),
            acres=item.get("acres"),
            filed_on=_coerce_date(item.get("filed_on")),
            decided_on=_coerce_date(item.get("decided_on")),
            outcome=outcome.value,
            vote_for=vote[0] if vote else None,
            vote_against=vote[1] if vote else None,
            vote_abstain=vote[2] if vote else None,
            conditions={"list": item["conditions"]} if item.get("conditions") else None,
            staff_recommendation=item.get("staff_recommendation"),
            censored=competing_risk_for(outcome).value == "censored",
            label_source="extracted",
        )
        .on_conflict_do_update(
            index_elements=[schema.application.c.jurisdiction_id, schema.application.c.external_id],
            set_={
                "outcome": outcome.value,
                "decided_on": _coerce_date(item.get("decided_on")),
                "vote_for": vote[0] if vote else None,
                "vote_against": vote[1] if vote else None,
                "updated_at": datetime.now(tz=None).astimezone(),
            },
        )
        .returning(schema.application.c.id)
    )
    application_id = int(conn.execute(statement).scalar_one())

    for evidence, location in zip(item.get("evidence", []), locations, strict=False):
        conn.execute(
            schema.fact_evidence.insert().values(
                subject_table="application",
                subject_id=application_id,
                field="outcome",
                document_id=document_id,
                page=location.page,
                char_start=location.char_start,
                char_end=location.char_end,
                quote=evidence["quote"],
                extractor_version=f"llm:{prompt_version}",
                verified=True,
                verified_at=datetime.now(tz=None).astimezone(),
            )
        )

    if item.get("objection_grounds"):
        conn.execute(
            schema.objection.insert().values(
                application_id=application_id,
                jurisdiction_id=jurisdiction_id,
                observed_on=_coerce_date(item.get("decided_on")),
                organised=item.get("organised_opposition"),
                grounds=item["objection_grounds"],
                speakers=item.get("speakers_against"),
            )
        )

    _write_event(conn, item, jurisdiction_id=jurisdiction_id, application_id=application_id)
    return 1


def _land_instrument(
    conn: Connection,
    *,
    item: dict[str, Any],
    locations: list[Any],
    document_id: str,
    jurisdiction_id: int,
    prompt_version: str,
) -> int:
    adopted = bool(item.get("adopted"))
    adopted_on = _coerce_date(item.get("adopted_on"))

    if not adopted or adopted_on is None:
        conn.execute(
            schema.event.insert().values(
                jurisdiction_id=jurisdiction_id,
                event_type="moratorium_proposed"
                if item.get("kind") == "moratorium"
                else "ordinance_proposed",
                occurred_on=_coerce_date(item.get("effective_on")) or date.today(),
                known_from=_coerce_date(item.get("effective_on")) or date.today(),
                detail={"adopted": adopted, "title": item.get("title"), "vote": item.get("vote")},
            )
        )
        return 0

    instrument_id = int(
        conn.execute(
            schema.instrument.insert()
            .values(
                jurisdiction_id=jurisdiction_id,
                kind=item["kind"],
                citation=item.get("citation"),
                title=item.get("title"),
                adopted_on=adopted_on,
                effective_on=_coerce_date(item.get("effective_on")) or adopted_on,
                expires_on=_coerce_date(item.get("expires_on")),
                applies_to_use_classes=item.get("applies_to_use_classes", []),
                restrictions={
                    k: v for k, v in (item.get("restrictions") or {}).items() if v is not None
                },
                full_text_document_id=document_id,
            )
            .returning(schema.instrument.c.id)
        ).scalar_one()
    )

    for evidence, location in zip(item.get("evidence", []), locations, strict=False):
        conn.execute(
            schema.fact_evidence.insert().values(
                subject_table="instrument",
                subject_id=instrument_id,
                field="adopted_on",
                document_id=document_id,
                page=location.page,
                char_start=location.char_start,
                char_end=location.char_end,
                quote=evidence["quote"],
                extractor_version=f"llm:{prompt_version}",
                verified=True,
                verified_at=datetime.now(tz=None).astimezone(),
            )
        )

    conn.execute(
        schema.event.insert().values(
            jurisdiction_id=jurisdiction_id,
            instrument_id=instrument_id,
            event_type="moratorium_enacted"
            if item["kind"] == "moratorium"
            else "ordinance_adopted",
            occurred_on=adopted_on,
            known_from=adopted_on,
            detail={"citation": item.get("citation"), "vote": item.get("vote")},
        )
    )
    return 1


def _write_event(
    conn: Connection,
    item: dict[str, Any],
    *,
    jurisdiction_id: int,
    application_id: int | None,
) -> None:
    occurred = (
        _coerce_date(item.get("decided_on")) or _coerce_date(item.get("filed_on")) or date.today()
    )
    conn.execute(
        schema.event.insert().values(
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            event_type=item.get("event_type", "decision_rendered"),
            occurred_on=occurred,
            known_from=occurred,
            detail={
                "outcome": item.get("outcome"),
                "vote": item.get("vote"),
                "project_name": item.get("project_name"),
            },
        )
    )


def _second_pass(
    conn: Connection,
    *,
    model: LanguageModel,
    items: list[dict[str, Any]],
    variables: dict[str, object],
    schema_name: str,
    key: str,
    jurisdiction_id: int,
    document_id: str,
    report: ExtractionReport,
) -> None:
    """Section 6.4 rule 3: a second pass with a different prompt, at temperature zero.

    Disagreement sends the fact to a human. That is a cheap outcome. Agreeing with something the
    document does not say is expensive and irreversible.
    """
    import json

    prompt = get_prompt("verification")
    check_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["assessments"],
        "properties": {
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["index", "supported"],
                    "properties": {
                        "index": {"type": "integer", "minimum": 0},
                        "supported": {"type": "boolean"},
                        "problem": {"type": ["string", "null"], "maxLength": 400},
                    },
                },
            }
        },
    }

    try:
        completion = model.complete_structured(
            prompt=prompt,
            schema=check_schema,
            variables={
                "jurisdiction_name": variables["jurisdiction_name"],
                "region": variables["region"],
                "candidate_facts": json.dumps(items, indent=2, default=str)[:60_000],
                "document_text": variables["document_text"],
            },
            tier="frontier",
        )
    except (SchemaViolationError, StageUnavailableError) as exc:
        log.warning("second pass unavailable", error=str(exc))
        return

    report.input_tokens += completion.usage.input_tokens
    report.output_tokens += completion.usage.output_tokens

    disagreements = [a for a in completion.payload.get("assessments", []) if not a.get("supported")]
    if not disagreements:
        return

    from auspice.pipeline.ingest import record_dead_letter

    for assessment in disagreements:
        index = int(assessment["index"])
        if index >= len(items):
            continue
        report.queued_for_review += 1
        record_dead_letter(
            conn,
            stage="extract",
            subject=f"{document_id}:{schema_name}:disagreement:{index}",
            jurisdiction_id=jurisdiction_id,
            error_type="pass_disagreement",
            error_message=str(assessment.get("problem") or "second pass did not support the fact"),
            payload=items[index],
        )

    _record_run(
        conn,
        document_id=document_id,
        key=key,
        schema_name=schema_name,
        prompt_version=prompt.version,
        model=completion.model,
        pass_number=2,
        status="disagreement",
        facts_discarded=len(disagreements),
        input_tokens=completion.usage.input_tokens,
        output_tokens=completion.usage.output_tokens,
    )
