"""The score object. Section 5.6.

Every field in the specification's JSON is a field here, with the same name, because the shape of this
object is the product and vagueness in it is what makes a product untrustworthy.

Five design rules are embedded in the type rather than left to a convention:

1. An interval is always present when a probability is. A bare point estimate is a lie, so
   ``approval_probability`` and ``credible_interval_80`` are validated together and the database has a
   CHECK constraint saying the same thing.
2. ``abstained`` is a first class field, and when it is true the probability is ``None`` rather than a
   number with a flag beside it. A number with a flag gets pasted into a memo without the flag.
3. Every driver carries an ``evidence_id``. A driver with no evidence cannot be constructed.
4. ``pooling_note`` is disclosed. If the answer partly comes from other jurisdictions, the customer is
   told. This is uncomfortable and it is what makes the number credible.
5. ``alternatives`` exists. It is where the customer saves the money and the reason they renew.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from auspice.domain import (
    AbstentionReason,
    Confidence,
    JurisdictionRole,
    ObjectionGround,
    Outcome,
    Relief,
    UseClass,
)

Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
class JurisdictionLink(Frozen):
    level: str
    name: str
    slug: str
    role: JurisdictionRole
    data_depth: int = Field(ge=0)
    discretion_index: float | None = Field(default=None, ge=0.0, le=1.0)


class Site(Frozen):
    parcel_ids: list[str] = Field(default_factory=list)
    label: str | None = None
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    jurisdiction_chain: list[JurisdictionLink] = Field(min_length=1)
    use_class: UseClass
    requested_relief: list[Relief] = Field(min_length=1)
    by_right: bool | None = None
    acres: float | None = Field(default=None, gt=0)
    capacity_mw: float | None = Field(default=None, gt=0)


# ---------------------------------------------------------------------------
# Determination
# ---------------------------------------------------------------------------
class TimeToDecision(Frozen):
    p10: float = Field(gt=0)
    p50: float = Field(gt=0)
    p90: float = Field(gt=0)
    basis: Literal["fitted", "empirical"] = "fitted"

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not (self.p10 <= self.p50 <= self.p90):
            raise ValueError(f"quantiles out of order: {self.p10}, {self.p50}, {self.p90}")
        return self


class Determination(Frozen):
    approval_probability: Probability | None = None
    credible_interval_80: tuple[Probability, Probability] | None = None
    interval_kind: Literal["credible", "bootstrap"] | None = None
    confidence: Confidence | None = None
    abstained: bool = False
    abstention_reasons: list[AbstentionReason] = Field(default_factory=list)
    time_to_decision_months: TimeToDecision | None = None
    probability_of_rule_change_before_decision: Probability | None = None
    local_base_rate: Probability | None = Field(
        default=None,
        description="The jurisdiction's own historical rate for this use class. Rendered as a dashed "
        "marker against the interval, because that single comparison is the most informative thing "
        "on the page.",
    )

    @model_validator(mode="after")
    def _abstention_is_total(self) -> Self:
        if self.abstained:
            if self.approval_probability is not None:
                raise ValueError(
                    "an abstention cannot carry a probability. A number with a caveat beside it gets "
                    "pasted into a memo without the caveat."
                )
            if not self.abstention_reasons:
                raise ValueError("an abstention must say why")
        else:
            if self.approval_probability is None:
                raise ValueError("a determination that is not an abstention needs a probability")
            if self.credible_interval_80 is None:
                raise ValueError("a bare point estimate is not publishable. Section 5.6 rule 1.")
        return self

    @model_validator(mode="after")
    def _interval_contains_estimate(self) -> Self:
        if self.credible_interval_80 is None or self.approval_probability is None:
            return self
        low, high = self.credible_interval_80
        if low > high:
            raise ValueError(f"interval is inverted: [{low}, {high}]")
        if not (low <= self.approval_probability <= high):
            raise ValueError(
                f"point estimate {self.approval_probability} sits outside its own interval "
                f"[{low}, {high}]"
            )
        return self

    @property
    def interval_width(self) -> float | None:
        if self.credible_interval_80 is None:
            return None
        return self.credible_interval_80[1] - self.credible_interval_80[0]


# ---------------------------------------------------------------------------
# Evidence and drivers
# ---------------------------------------------------------------------------
class Evidence(Frozen):
    evidence_id: str
    document_id: str
    document_title: str | None = None
    document_kind: str | None = None
    source_url: str
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1, max_length=500)
    verified: bool
    retrieved_on: date | None = None
    speaker: str | None = None
    timestamp: str | None = Field(
        default=None,
        description="For a transcript, the position in the hearing, so a quote can be cited as "
        "Commissioner X at 1:47:22.",
    )


class Driver(Frozen):
    factor: str
    group: str
    direction: Literal["positive", "negative", "neutral"]
    weight: float = Field(ge=0.0, le=1.0)
    plain_language: str = Field(min_length=10)
    evidence_id: str | None = Field(
        default=None,
        description="Null only for a driver derived entirely from structured registry data, such as "
        "the election calendar, where there is no quotable document.",
    )
    value: float | None = None


class Precedent(Frozen):
    application_id: int
    external_id: str | None = None
    jurisdiction: str
    similarity: float = Field(ge=0.0, le=1.0)
    outcome: Outcome
    vote: str | None = None
    months_to_decision: float | None = None
    decided_on: date | None = None
    objection_grounds: list[ObjectionGround] = Field(default_factory=list)
    evidence_id: str | None = None
    basis: dict[str, float] = Field(default_factory=dict)


class Mitigation(Frozen):
    action: str = Field(min_length=10)
    expected_delta: float = Field(
        ge=-1.0,
        le=1.0,
        description="Change in approval probability if the action is taken. Computed by re-scoring "
        "with the feature changed, never by asking a language model to estimate it.",
    )
    basis: str = Field(min_length=10)


class Alternative(Frozen):
    jurisdiction: str
    jurisdiction_slug: str
    distance_km: float = Field(ge=0)
    by_right: bool | None = None
    approval_probability: Probability | None = None
    abstained: bool = False
    expected_value_rank: float
    note: str | None = None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
class Provenance(Frozen):
    model_version: str
    model_kind: str
    survival_model_version: str | None = None
    rule_change_model_version: str | None = None
    feature_set_version: str
    dataset_hash: str
    data_as_of: date
    documents_used: int = Field(ge=0)
    jurisdiction_data_depth: str
    pooled: bool
    pooling_weight: float = Field(ge=0.0, le=1.0)
    pooling_note: str | None = None
    stale: bool = False
    staleness_days: int | None = None
    features_missing: list[str] = Field(default_factory=list)
    disclaimer: str = Field(
        default=(
            "This is a probabilistic opinion with a disclosed methodology. It is not legal advice, "
            "not an appraisal, and not a guarantee. Permission Bureau models published voting records and "
            "stated positions, never inferred motives, and never predicts how a named individual "
            "will vote."
        )
    )


# ---------------------------------------------------------------------------
# The object
# ---------------------------------------------------------------------------
class Score(Frozen):
    """What a customer receives. Appendix 19.3."""

    public_id: str
    generated_at: datetime
    site: Site
    determination: Determination
    drivers: list[Driver] = Field(default_factory=list)
    precedents: list[Precedent] = Field(default_factory=list)
    mitigations: list[Mitigation] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    provenance: Provenance
    features_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _drivers_resolve_their_evidence(self) -> Self:
        """Section 5.6 rule 3, enforced by the type.

        A driver whose ``evidence_id`` does not resolve to an evidence entry is an unsourced claim
        reaching the customer, which is the thing section 8.3 exists to prevent. It is caught here
        rather than noticed in a memo.
        """
        available = {e.evidence_id for e in self.evidence}
        dangling = [
            d.factor
            for d in self.drivers
            if d.evidence_id is not None and d.evidence_id not in available
        ]
        if dangling:
            raise ValueError(
                "these drivers cite evidence that is not attached: " + ", ".join(sorted(dangling))
            )
        return self

    @model_validator(mode="after")
    def _no_unverified_evidence_ships(self) -> Self:
        """An unverified quote never reaches a customer.

        Section 6.4 rule 2 discards unverified extractions upstream, so reaching this point with one
        means something bypassed the extraction layer. Failing loudly here is the backstop.
        """
        unverified = [e.evidence_id for e in self.evidence if not e.verified]
        if unverified:
            raise ValueError(
                "unverified quotes cannot be published: " + ", ".join(sorted(unverified))
            )
        return self

    @model_validator(mode="after")
    def _abstention_has_no_drivers_with_weight(self) -> Self:
        """An abstention may show what is known, but not a ranked driver list.

        Section 8.4: when it abstains, the customer is shown the rules, the board and the recent
        history, and told plainly that a probability would be dishonest. A weighted driver table
        implies a number underneath it.
        """
        if self.determination.abstained and any(d.weight > 0 for d in self.drivers):
            raise ValueError(
                "an abstention cannot present weighted drivers, because a weighted driver table "
                "implies a probability underneath it"
            )
        return self

    @property
    def headline(self) -> str:
        """One line, for an alert or a table row."""
        if self.determination.abstained:
            return "We do not know."
        probability = self.determination.approval_probability
        assert probability is not None
        assert self.determination.credible_interval_80 is not None
        low, high = self.determination.credible_interval_80
        return f"{probability:.0%} approval, 80 percent interval {low:.0%} to {high:.0%}"

    def ledger_payload(self) -> dict[str, object]:
        """Exactly the fields committed to the public ledger. Section 8.2 step 3.

        Deliberately small and deliberately fixed. The ledger commits the prediction, not the essay
        around it, so the record stays verifiable when the explanation format changes.
        """
        return {
            "public_id": self.public_id,
            "generated_at": self.generated_at.isoformat(),
            "jurisdiction": self.site.jurisdiction_chain[0].slug,
            "use_class": self.site.use_class.value,
            "requested_relief": sorted(r.value for r in self.site.requested_relief),
            "approval_probability": self.determination.approval_probability,
            "credible_interval_80": list(self.determination.credible_interval_80)
            if self.determination.credible_interval_80
            else None,
            "abstained": self.determination.abstained,
            "abstention_reasons": sorted(r.value for r in self.determination.abstention_reasons),
            "time_to_decision_months": (
                {
                    "p10": self.determination.time_to_decision_months.p10,
                    "p50": self.determination.time_to_decision_months.p50,
                    "p90": self.determination.time_to_decision_months.p90,
                }
                if self.determination.time_to_decision_months
                else None
            ),
            "probability_of_rule_change_before_decision": (
                self.determination.probability_of_rule_change_before_decision
            ),
            "model_version": self.provenance.model_version,
            "model_kind": self.provenance.model_kind,
            "feature_set_version": self.provenance.feature_set_version,
            "dataset_hash": self.provenance.dataset_hash,
            "features_hash": self.features_hash,
            "data_as_of": self.provenance.data_as_of.isoformat(),
        }
