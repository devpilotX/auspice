"""Request and response bodies.

The response models reuse ``auspice.score.models`` directly rather than restating them. One definition
means the OpenAPI document, the generated TypeScript, the database CHECK constraints and the memo all
describe the same object, and a field cannot drift between the model and the wire.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from auspice.domain import Relief, UseClass
from auspice.pipeline.registry.models import Slug
from auspice.score.models import Score


class ScoreRequest(BaseModel):
    """One site. Either a coordinate pair or a jurisdiction slug, and a use class."""

    model_config = ConfigDict(extra="forbid")

    use_class: UseClass
    relief_sought: list[Relief] = Field(min_length=1, max_length=8)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    jurisdiction: Slug | None = Field(
        default=None,
        description="Registry slug, e.g. us-va-loudoun",
    )
    """Validated against the registry's own slug type rather than accepted as free text.

    It was `str | None` with no length and no pattern, which meant a caller could send a megabyte where a
    twenty character slug belongs. Nothing was injectable, because the value is always a bound parameter,
    but an unbounded input on a public shape is worth closing on its own. Reusing `Slug` also means the API
    and the registry cannot disagree about what a slug looks like.
    """

    parcel_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = Field(
        default_factory=list, max_length=50
    )
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

    @model_validator(mode="after")
    def an_abstention_carries_no_number(self) -> PortfolioRow:
        """The rules the score object enforces, enforced again on the flat row.

        ``Score`` refuses to construct an abstention with a probability. This is a separate DTO built by
        hand from a score's fields, so it inherited none of that, and it is the shape a ranked table is
        drawn from. An abstention arriving here with a number would render as an ordinary row near the
        bottom of the list, which is the one malformation nobody would spot: it reads as a pessimistic
        answer rather than as no answer.
        """
        if self.abstained and self.approval_probability is not None:
            raise ValueError(
                "an abstention cannot carry a probability. Refusing to answer and answering low are "
                "different claims and a ranked list cannot show the difference."
            )
        if self.abstained and self.credible_interval_80 is not None:
            raise ValueError("an abstention cannot carry an interval")
        if self.approval_probability is not None and self.credible_interval_80 is None:
            raise ValueError(
                "a probability without an interval is a point estimate posing as a range"
            )
        if self.approval_probability is not None and not 0.0 <= self.approval_probability <= 1.0:
            raise ValueError("a probability must be between zero and one")
        if self.credible_interval_80 is not None:
            low, high = self.credible_interval_80
            if low > high:
                raise ValueError("the interval is inverted")
        return self


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ranked: list[PortfolioRow]
    submitted: int = Field(description="How many sites were in the request.")
    scored: int = Field(
        description=(
            "How many carry a probability. Excludes abstentions, so scored plus abstained equals "
            "submitted."
        )
    )
    abstained: int = Field(description="How many we refused to put a number on.")
    note: str = Field(
        default=(
            "Ranked by approval probability. Abstentions sort last and carry no number, because a "
            "ranked list that quietly treats an abstention as a low score would make refusing to "
            "answer indistinguishable from answering badly."
        )
    )

    @model_validator(mode="after")
    def counts_account_for_every_site(self) -> PortfolioResponse:
        """The three counts have to add up, and they have to match the rows.

        ``scored`` previously counted every row including the abstentions, so a portfolio where nothing
        could be scored reported three scored and three abstained out of three sites. Nobody reading the
        API would have caught it; the numbers are only obviously wrong once they are side by side on a
        screen, which is where it was found. Asserting the arithmetic here means the next version of that
        mistake fails at the boundary rather than being rendered.
        """
        if self.scored + self.abstained != self.submitted:
            raise ValueError(
                f"{self.scored} scored plus {self.abstained} abstained does not equal "
                f"{self.submitted} submitted"
            )
        if len(self.ranked) != self.submitted:
            raise ValueError(
                f"{len(self.ranked)} rows for {self.submitted} submitted sites. Every site gets a row, "
                "including the ones we would not score."
            )
        actual_abstentions = sum(1 for row in self.ranked if row.abstained)
        if actual_abstentions != self.abstained:
            raise ValueError(
                f"the summary says {self.abstained} abstentions and the rows contain "
                f"{actual_abstentions}"
            )
        return self


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


class LocateLink(BaseModel):
    """One link in the chain of bodies that can say no to a parcel.

    Named for its endpoint rather than `JurisdictionLink`, which already exists in
    `auspice.score.models`. Two schemas with one name make FastAPI disambiguate both by full module path,
    which renames the existing one in the OpenAPI document and breaks every consumer that referenced it.
    """

    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    kind: str
    role: str
    region: str | None
    legal_framework: str | None
    data_depth: int
    discretion_index: float | None


class LocateResponse(BaseModel):
    """Who decides for a coordinate. The stage 0 question, answered on its own.

    Separate from scoring on purpose. "Which bodies can say no to this parcel" is useful before anyone
    asks for a probability, it is the honest answer for a site outside the covered counties, and it is
    cheap: a spatial join rather than a model fit.

    ``covered`` is false rather than the response being a 404, because a point in an uncovered county is a
    valid question with a real answer. Returning nothing found would read as a malfunction.
    """

    model_config = ConfigDict(frozen=True)

    longitude: float
    latitude: float
    covered: bool
    chain: list[LocateLink]
    note: str

    @model_validator(mode="after")
    def covered_means_a_chain(self) -> LocateResponse:
        if self.covered != (len(self.chain) > 0):
            raise ValueError("covered must say whether the chain resolved, not something else")
        return self


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
    anchor: dict[str, Any]
    """External anchoring of the chain head, and a sentence describing it in words.

    Carried on this page rather than left to the documentation, because the chain field above proves
    internal consistency only. We hold the whole ledger and could rebuild and rehash it, so without an
    external attestation the chain does not prove when it came into existence. A page that showed the
    chain and said nothing about anchoring would invite a reader to assume the stronger guarantee.
    """
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
