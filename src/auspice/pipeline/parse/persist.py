"""Persisting parsed text, and reading it back for quote verification.

Pages and chunks are written together in one transaction. A document with pages but no chunks
would be silently unextractable, and a document with chunks but no pages would make quote
verification impossible, so neither state is allowed to exist.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.domain import ParseMethod
from auspice.logging import get_logger
from auspice.pipeline.parse.cascade import ParsedDocument, ParsedPage, chunk_pages

log = get_logger(__name__, _stage="parse")


def persist_parsed(conn: Connection, parsed: ParsedDocument) -> None:
    """Write pages and chunks, replacing any previous parse of the same document.

    Replacing rather than appending is correct here: the raw bytes are immutable and content
    addressed, so re-parsing the same document id means the parser improved, and the old text is
    strictly worse. The raw object is never touched.
    """
    conn.execute(
        delete(schema.document_page).where(schema.document_page.c.document_id == parsed.document_id)
    )
    conn.execute(
        delete(schema.document_chunk).where(
            schema.document_chunk.c.document_id == parsed.document_id
        )
    )

    if parsed.pages:
        conn.execute(
            schema.document_page.insert(),
            [
                {
                    "document_id": parsed.document_id,
                    "page": page.page,
                    "text": page.text,
                    "char_start": page.char_start,
                    "char_end": page.char_end,
                    "parse_method": page.method.value,
                    "legibility": round(page.legibility, 3),
                    "escalated": page.escalated,
                }
                for page in parsed.pages
            ],
        )

    if parsed.chunks:
        conn.execute(
            schema.document_chunk.insert(),
            [
                {
                    "document_id": parsed.document_id,
                    "ordinal": chunk.ordinal,
                    "heading": chunk.heading,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "text": chunk.text,
                    "token_estimate": chunk.token_estimate,
                }
                for chunk in parsed.chunks
            ],
        )

    conn.execute(
        update(schema.document)
        .where(schema.document.c.id == parsed.document_id)
        .values(
            page_count=len(parsed.pages),
            parse_method=parsed.primary_method.value,
            parsed_at=datetime.now(UTC),
            legibility=parsed.mean_legibility,
        )
    )
    log.debug(
        "persisted parse",
        document_id=parsed.document_id[:12],
        pages=len(parsed.pages),
        chunks=len(parsed.chunks),
    )


def load_parsed(conn: Connection, document_id: str) -> ParsedDocument | None:
    """Read a parsed document back out, for quote verification and for extraction.

    Returns None when the document has never been parsed, which the caller has to handle. It is
    not the same thing as a document that parsed to nothing.
    """
    rows = conn.execute(
        select(
            schema.document_page.c.page,
            schema.document_page.c.text,
            schema.document_page.c.char_start,
            schema.document_page.c.char_end,
            schema.document_page.c.parse_method,
            schema.document_page.c.legibility,
            schema.document_page.c.escalated,
        )
        .where(schema.document_page.c.document_id == document_id)
        .order_by(schema.document_page.c.page)
    ).all()

    if not rows:
        return None

    parsed = ParsedDocument(document_id=document_id)
    for page, page_text, char_start, char_end, method, page_legibility, escalated in rows:
        resolved = ParseMethod(method)
        parsed.pages.append(
            ParsedPage(
                page=page,
                text=page_text,
                char_start=char_start,
                char_end=char_end,
                method=resolved,
                legibility=float(page_legibility),
                escalated=escalated,
            )
        )
        parsed.methods_used.add(resolved)
        if escalated:
            parsed.escalations += 1

    chunk_rows = conn.execute(
        select(
            schema.document_chunk.c.ordinal,
            schema.document_chunk.c.heading,
            schema.document_chunk.c.page_start,
            schema.document_chunk.c.page_end,
            schema.document_chunk.c.char_start,
            schema.document_chunk.c.char_end,
            schema.document_chunk.c.text,
        )
        .where(schema.document_chunk.c.document_id == document_id)
        .order_by(schema.document_chunk.c.ordinal)
    ).all()

    if chunk_rows:
        from auspice.pipeline.parse.cascade import ParsedChunk

        parsed.chunks = [
            ParsedChunk(
                ordinal=ordinal,
                heading=heading,
                page_start=page_start,
                page_end=page_end,
                char_start=char_start,
                char_end=char_end,
                text=chunk_text,
            )
            for ordinal, heading, page_start, page_end, char_start, char_end, chunk_text in chunk_rows
        ]
    else:
        parsed.chunks = chunk_pages(parsed.pages)

    return parsed
