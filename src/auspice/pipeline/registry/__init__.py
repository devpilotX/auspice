"""Stage 0: the jurisdiction registry.

Section 6.0 makes a decision that looks like procrastination and is not: build the registry
by hand before writing a single scraper. Three days of manual work that prevents three weeks
of building pipelines into the wrong places.

The registry is a version controlled YAML file, not a database table that someone edited
once. `data/registry/jurisdictions.yaml` is reviewable, diffable, and every non obvious
assertion in it carries a source. Boundary geometry is the exception: it is fetched from the
Census TIGERweb service rather than typed in, because a hand entered polygon has no
provenance and cannot be checked.
"""

from __future__ import annotations

from auspice.pipeline.registry.elections import derive_elections, general_election_date
from auspice.pipeline.registry.models import (
    BodySpec,
    ElectionRule,
    JurisdictionSpec,
    Registry,
    SourceSpec,
    load_registry,
)

__all__ = [
    "BodySpec",
    "ElectionRule",
    "JurisdictionSpec",
    "Registry",
    "SourceSpec",
    "derive_elections",
    "general_election_date",
    "load_registry",
]
