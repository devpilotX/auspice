"""Quote verification.

This module is the mechanism behind section 8.3. A quote that is not found verbatim in the stored
source text causes the extraction to be discarded, not flagged. Hallucinated citations are
eliminated structurally rather than by trust.

Two properties matter and both are deliberate.

**The match is exact.** After the normalisation in ``parse.cascade.normalise_text``, which folds
curly quotes and collapses whitespace and nothing else, the comparison is a plain substring
search. There is no fuzzy matching, no token overlap threshold, no embedding similarity. A fuzzy
matcher would quietly convert a fabricated citation into a passing one, which is the exact failure
this exists to prevent.

**Failure is discard, not repair.** The verifier does not try to find the closest real quote and
substitute it. If the model could not quote the document, its reading of the document is not
trustworthy and the extraction is retried from scratch.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.errors import QuoteVerificationError
from auspice.logging import get_logger
from auspice.pipeline.parse import ParsedDocument, load_parsed, normalise_text

log = get_logger(__name__, _stage="extract")

# An ellipsis inside a quote means the model elided a span. That is legitimate for a long
# sentence, so a quote containing one is verified piecewise: every fragment must appear, in order.
_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\[\s*\.\.\.\s*\])\s*")

# Fragments shorter than this are not evidence of anything. "the" appears in every document.
MIN_FRAGMENT_CHARS = 12


@dataclass(frozen=True, slots=True)
class QuoteLocation:
    page: int
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verified: bool
    location: QuoteLocation | None
    reason: str | None = None


def verify_quote(parsed: ParsedDocument, quote: str) -> VerificationResult:
    """Locate a quote in a parsed document, or explain why it is not there."""
    normalised = normalise_text(quote)
    if len(normalised) < MIN_FRAGMENT_CHARS:
        return VerificationResult(
            False, None, f"quote is shorter than {MIN_FRAGMENT_CHARS} characters"
        )

    fragments = [f for f in _ELLIPSIS.split(normalised) if f.strip()]

    if len(fragments) == 1:
        found = parsed.locate(normalised)
        if found is None:
            return VerificationResult(False, None, "quote not found verbatim in the source text")
        page, start, end = found
        return VerificationResult(True, QuoteLocation(page, start, end))

    # Elided quote: every fragment must appear, in order, and each fragment must carry weight.
    cursor = 0
    first_start: int | None = None
    last_end = 0
    for fragment in fragments:
        if len(fragment) < MIN_FRAGMENT_CHARS:
            return VerificationResult(
                False, None, f"elided fragment is shorter than {MIN_FRAGMENT_CHARS} characters"
            )
        found = parsed.locate(fragment, from_offset=cursor)
        if found is None:
            return VerificationResult(False, None, "an elided fragment was not found in order")
        _page, start, end = found
        if first_start is None:
            first_start = start
        cursor = end
        last_end = end

    assert first_start is not None
    return VerificationResult(
        True, QuoteLocation(parsed.page_for_offset(first_start), first_start, last_end)
    )


def verify_extraction_evidence(
    parsed: ParsedDocument, evidence: Sequence[dict[str, Any]]
) -> list[QuoteLocation]:
    """Verify every quote on one extracted fact, or raise.

    Raising rather than returning a partial result is the point. Section 6.4 rule 1 gives evidence
    a minimum of one item, so an extraction whose only quote fails verification has no evidence at
    all, and a fact with no evidence does not exist.
    """
    if not evidence:
        raise QuoteVerificationError(
            "extraction carried no evidence", document_id=parsed.document_id, quote=""
        )

    locations: list[QuoteLocation] = []
    for item in evidence:
        quote = str(item.get("quote", ""))
        result = verify_quote(parsed, quote)
        if not result.verified or result.location is None:
            raise QuoteVerificationError(
                f"quote verification failed: {result.reason}",
                document_id=parsed.document_id,
                quote=quote[:120],
            )
        locations.append(result.location)
    return locations


# ---------------------------------------------------------------------------
# Verifying citations already stored in the graph
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class StoredVerificationReport:
    checked: int = 0
    verified: int = 0
    quote_missing: int = 0
    unreachable: int = 0
    skipped: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)


def verify_stored_citations(
    conn: Connection,
    *,
    limit: int | None = None,
    offline: bool = False,
) -> StoredVerificationReport:
    """Fetch and verify every unverified citation in ``fact_evidence``.

    Hand labels cite a URL whose bytes have not been fetched yet, so this does the fetch, stores
    the bytes in the content addressed corpus, parses them, and then applies the same exact match
    the extraction layer applies. It is the same discipline, applied to human work.

    Where the citation resolves to a different document id than the placeholder (which it always
    does, because the placeholder is the hash of the URL and the real id is the hash of the bytes),
    the evidence row is repointed at the real document and the placeholder is left behind as a
    record of what was originally claimed.
    """
    import asyncio

    report = StoredVerificationReport()

    rows = conn.execute(
        select(
            schema.fact_evidence.c.id,
            schema.fact_evidence.c.subject_table,
            schema.fact_evidence.c.subject_id,
            schema.fact_evidence.c.document_id,
            schema.fact_evidence.c.quote,
            schema.document.c.source_url,
            schema.document.c.title,
            schema.document.c.storage_key,
        )
        .join(schema.document, schema.document.c.id == schema.fact_evidence.c.document_id)
        .where(schema.fact_evidence.c.verified.is_(False))
        .order_by(schema.fact_evidence.c.id)
        .limit(limit)
    ).all()

    if offline:
        for row in rows:
            report.skipped += 1
            report.rows.append(
                {
                    "subject": f"{row.subject_table}:{row.subject_id}",
                    "document_title": (row.title or row.source_url)[:70],
                    "status": "skipped",
                    "detail": "offline",
                }
            )
        return report

    async def _run() -> None:
        from auspice.pipeline.ingest import Fetcher, register_document

        async with Fetcher() as fetcher:
            for row in rows:
                report.checked += 1
                outcome = await fetcher.fetch(row.source_url, kind="news_article")
                if not outcome.ok or outcome.stored is None:
                    report.unreachable += 1
                    report.rows.append(
                        {
                            "subject": f"{row.subject_table}:{row.subject_id}",
                            "document_title": (row.title or row.source_url)[:70],
                            "status": "unreachable",
                            "detail": outcome.error or outcome.outcome,
                        }
                    )
                    continue

                real_document_id = register_document(
                    conn,
                    outcome,
                    jurisdiction_id=None,
                    source_id=None,
                    kind="news_article",
                    title=row.title,
                )
                assert real_document_id is not None

                parsed = load_parsed(conn, real_document_id)
                if parsed is None:
                    from auspice.pipeline.parse import parse_bytes, persist_parsed

                    data = fetcher.store.get(outcome.stored.key)
                    try:
                        parsed = parse_bytes(
                            data,
                            document_id=real_document_id,
                            media_type=outcome.headers.get("content-type"),
                        )
                    except Exception as exc:
                        report.unreachable += 1
                        report.rows.append(
                            {
                                "subject": f"{row.subject_table}:{row.subject_id}",
                                "document_title": (row.title or row.source_url)[:70],
                                "status": "unparseable",
                                "detail": str(exc)[:80],
                            }
                        )
                        continue
                    persist_parsed(conn, parsed)

                result = verify_quote(parsed, row.quote)
                if result.verified and result.location is not None:
                    report.verified += 1
                    conn.execute(
                        update(schema.fact_evidence)
                        .where(schema.fact_evidence.c.id == row.id)
                        .values(
                            document_id=real_document_id,
                            page=result.location.page,
                            char_start=result.location.char_start,
                            char_end=result.location.char_end,
                            verified=True,
                            verified_at=datetime.now(UTC),
                        )
                    )
                    report.rows.append(
                        {
                            "subject": f"{row.subject_table}:{row.subject_id}",
                            "document_title": (row.title or row.source_url)[:70],
                            "status": "verified",
                            "detail": f"page {result.location.page}",
                        }
                    )
                else:
                    report.quote_missing += 1
                    conn.execute(
                        update(schema.fact_evidence)
                        .where(schema.fact_evidence.c.id == row.id)
                        .values(document_id=real_document_id)
                    )
                    report.rows.append(
                        {
                            "subject": f"{row.subject_table}:{row.subject_id}",
                            "document_title": (row.title or row.source_url)[:70],
                            "status": "not found",
                            "detail": result.reason or "",
                        }
                    )

    asyncio.run(_run())

    log.info(
        "citation verification complete",
        checked=report.checked,
        verified=report.verified,
        quote_missing=report.quote_missing,
        unreachable=report.unreachable,
    )
    return report


def quote_verification_rate(conn: Connection, *, hours: int = 24) -> dict[str, Any]:
    """The section 16.2 metric. Below 99 percent, extraction is unsafe and the pipeline stops."""
    row = (
        conn.execute(
            text(
                """
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE verified) AS verified
            FROM fact_evidence
            WHERE created_at > now() - make_interval(hours => :hours)
            """
            ).bindparams(hours=hours)
        )
        .mappings()
        .one()
    )
    total = int(row["total"])
    verified = int(row["verified"])
    return {
        "window_hours": hours,
        "total": total,
        "verified": verified,
        "rate": round(verified / total, 4) if total else None,
        "safe": (verified / total) >= 0.99 if total else None,
    }
