"""Stage 5: entity resolution. Reversible merges, originals never destroyed."""

from __future__ import annotations

from auspice.pipeline.resolve.entities import (
    ADJUDICATE_SIMILARITY,
    AUTO_MERGE_SIMILARITY,
    ResolveReport,
    looks_like_single_purpose_entity,
    merge_clusters,
    normalise_body,
    normalise_organisation,
    normalise_person,
    precision_estimate,
    resolve_applicants,
    resolve_body_reference,
    resolve_person,
    reverse,
)

__all__ = [
    "ADJUDICATE_SIMILARITY",
    "AUTO_MERGE_SIMILARITY",
    "ResolveReport",
    "looks_like_single_purpose_entity",
    "merge_clusters",
    "normalise_body",
    "normalise_organisation",
    "normalise_person",
    "precision_estimate",
    "resolve_applicants",
    "resolve_body_reference",
    "resolve_person",
    "reverse",
]
