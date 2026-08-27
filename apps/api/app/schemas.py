"""Request and response bodies.

The response models reuse ``auspice.score.models`` directly rather than restating them. One definition
means the OpenAPI document, the generated TypeScript, the database CHECK constraints and the memo all
describe the same object, and a field cannot drift between the model and the wire.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from auspice.domain import Relief, UseClass
from auspice.score.models import Score


class ScoreRequest(BaseModel):
    """One site. Either a coordinate pair or a jurisdiction slug, and a use class."""

    model_config = ConfigDict(extra="forbid")

    use_class: UseClass
    relief_sought: list[Relief] = Field(min_length=1, max_length=8)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    jurisdiction: str | None = Field(default=None, description="Registry slug, e.g. us-va-loudoun")
    parcel_ids: list[str] = Field(default_factory=list, max_length=50)
    label: str | None = Field(default=None, max_length=120)
    acres: float | None = Field(default=None, gt=0, le=1_000_000)
    capacity_mw: float | None = Field(default=None, gt=0, le=100_000)
    by_right: bool | None = None
    include_alternatives: bool = True
    as_of: date | None = Field(
        default=None,
        description="Score as the world was known on this date. Used for back testing, not for a live "
        "quote. Omitting it means today.",
    )

    @model_validator(mode="after")
    def _locatable(self) -> ScoreRequest:
        if self.jurisdiction is None and (self.longitude is None or self.latitude is None):
            raise ValueError("provide either a jurisdiction slug or both longitude and latitude")
        return self


class PortfolioRequest(BaseModel):
    """Section 5.4 product 2, the wedge feature. Up to 500 sites in, ranked out."""

    model_config = ConfigDict(extra="forbid")

    sites: list[ScoreRequest] = Field(min_length=1, max_length=500)


class PortfolioRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str | None
    jurisdiction: str
    approval_probability: float | None
    credible_interval_80: tuple[float, float] | None
    abstained: bool
    months_p50: float | None
    rule_change_probability: float | None
    data_depth: int
    stale: bool
    public_id: str


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ranked: list[PortfolioRow]
    scored: int
    abstained: int
    note: str = Field(
        default=(
            "Ranked by approval probability. Abstentions sort last and carry no number, because a "
            "ranked list that quietly treats an abstention as a low score would make refusing to "
            "answer indistinguishable from answering badly."
        )
    )


class JurisdictionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    kind: str
    region: str | None
    legal_framework: str | None
    civic_platform: str | None
    data_depth: int
    discretion_index: float | None
    bodies: int
    elections_known: int
    has_boundary: bool
    freshness: Literal["fresh", "stale", "broken", "never"]
    hours_since_refresh: float | None


class JurisdictionProfile(BaseModel):
    """The public jurisdiction profile. Indexed, no login. Section 10.4."""

    model_config = ConfigDict(frozen=True)

    summary: JurisdictionSummary
    approval_rate_by_use_class: dict[str, float | None]
    decisions: int
    instruments: list[dict[str, Any]]
    bodies: list[dict[str, Any]]
    next_elections: list[dict[str, Any]]


class AccuracyResponse(BaseModel):
    """The public accuracy record. Section 8.1, free and open.

    ``brier_score`` is null until predictions resolve, and the page says so in words. A bureau with no
    resolved calls has no accuracy, and pretending otherwise would be the first dishonest thing it did.
    """

    model_config = ConfigDict(frozen=True)

    published: int
    resolved: int
    pending: int
    answered: int
    abstained: int
    brier_score: float | None
    chain: dict[str, Any]
    misses: list[dict[str, Any]]
    reliability: dict[str, Any] | None
    kill_test: dict[str, Any] | None
    statement: str


class FreshnessRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    jurisdiction: str
    kind: str
    platform: str
    refresh_hours: int
    hours_since_success: float | None
    consecutive_failures: int
    status: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "degraded"]
    version: str
    database: bool
    models_loaded: bool
    serving_model: str | None
    ledger_intact: bool | None
    decisions_held: int
    detail: list[str]


ScoreResponse = Annotated[Score, Field(description="The section 5.6 score object.")]
