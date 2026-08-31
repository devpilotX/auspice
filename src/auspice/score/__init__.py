"""Stage 10: output generation.

The score object, the abstention rule, plain language explanations, and the alternative site ranker.
"""

from __future__ import annotations

from auspice.score.abstention import (
    AbstentionDecision,
    AbstentionInput,
    confidence_for,
    decide,
    explain,
    pooling_note,
)
from auspice.score.engine import (
    ServingModels,
    SiteRequest,
    abstention_notice,
    load_serving_models,
    require_models,
    score_site,
)
from auspice.score.models import (
    Alternative,
    Determination,
    Driver,
    Evidence,
    JurisdictionLink,
    Mitigation,
    Precedent,
    Provenance,
    Score,
    Site,
    TimeToDecision,
)

__all__ = [
    "AbstentionDecision",
    "AbstentionInput",
    "Alternative",
    "Determination",
    "Driver",
    "Evidence",
    "JurisdictionLink",
    "Mitigation",
    "Precedent",
    "Provenance",
    "Score",
    "ServingModels",
    "Site",
    "SiteRequest",
    "TimeToDecision",
    "abstention_notice",
    "confidence_for",
    "decide",
    "explain",
    "load_serving_models",
    "pooling_note",
    "require_models",
    "score_site",
]
