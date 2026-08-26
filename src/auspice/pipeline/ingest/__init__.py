"""Stage 1: ingestion.

Content addressed, immutable, polite. See ``store`` for the corpus and ``fetcher`` for the only
component in the system that reaches a government site.
"""

from __future__ import annotations

from auspice.pipeline.ingest.fetcher import (
    Fetcher,
    FetchOutcome,
    freshness_report,
    mark_source_result,
    record_attempt,
    record_dead_letter,
    register_document,
)
from auspice.pipeline.ingest.store import (
    LocalRawStore,
    RawStore,
    S3RawStore,
    StoredObject,
    content_hash,
    get_raw_store,
    storage_key,
)

__all__ = [
    "FetchOutcome",
    "Fetcher",
    "LocalRawStore",
    "RawStore",
    "S3RawStore",
    "StoredObject",
    "content_hash",
    "freshness_report",
    "get_raw_store",
    "mark_source_result",
    "record_attempt",
    "record_dead_letter",
    "register_document",
    "storage_key",
]
