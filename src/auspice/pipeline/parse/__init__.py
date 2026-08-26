"""Stage 2: document processing."""

from __future__ import annotations

from auspice.pipeline.parse.cascade import (
    LEGIBILITY_THRESHOLD,
    ParsedChunk,
    ParsedDocument,
    ParsedPage,
    chunk_pages,
    legibility,
    normalise_text,
    parse_bytes,
    parse_html,
    parse_pdf,
    parse_plain_text,
    tesseract_available,
)
from auspice.pipeline.parse.persist import load_parsed, persist_parsed

__all__ = [
    "LEGIBILITY_THRESHOLD",
    "ParsedChunk",
    "ParsedDocument",
    "ParsedPage",
    "chunk_pages",
    "legibility",
    "load_parsed",
    "normalise_text",
    "parse_bytes",
    "parse_html",
    "parse_pdf",
    "parse_plain_text",
    "persist_parsed",
    "tesseract_available",
]
