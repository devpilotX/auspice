"""Assembling a score. Stage 10.

This is where every earlier stage meets. It resolves who decides, builds point in time features, runs
the serving models, applies the abstention rule, attaches the evidence, ranks the alternatives, and
returns the object in section 5.6.

Two rules shape the whole module.

**Nothing is invented to fill a field.** If the survival model declined, ``time_to_decision_months`` is
absent rather than a plausible triple. If a driver has no quotable document, its ``evidence_id`` is null
rather than pointing at something adjacent. A score with an honest hole is usable; a score with a
convincing fabrication is not.

**No language model produces the number, and none of them touch it here.** Driver weights come from the
model's own posterior contributions or SHAP values. The plain language sentences come from the feature
dictionary, which is static text with a value substituted. A language model is used in exactly one
optional place, ``explain_driver``, and it is given the fact and forbidden from adding to it.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import text
from sqlalchemy.engine import Connection

from auspice.domain import (
    AbstentionReason,
    JurisdictionRole,
    ObjectionGround,
    Outcome,
    Relief,
    UseClass,
)
from auspice.errors import StageUnavailableError
from auspice.logging import get_logger
from auspice.models.baseline.base_rate import BaseRateModel
from auspice.models.baseline.boosted import BoostedModel
from auspice.models.dataset import Dataset, load_dataset
from auspice.models.hierarchical.model import HierarchicalModel
from auspice.models.rulechange.model import RuleChangeModel
from auspice.models.survival.model import SurvivalModel
from auspice.pipeline.features import (
    BY_NAME,
    FEATURE_SET_VERSION,
    FeatureRow,
    describe,
    feature_names,
)
from auspice.score.abstention import (
    AbstentionInput,
    confidence_for,
    decide,
    explain,
    pooling_note,
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

log = get_logger(__name__, _stage="score")

MAX_DRIVERS = 8
MAX_PRECEDENTS = 6
MAX_ALTERNATIVES = 5


@dataclass(slots=True)
class SiteRequest:
    """What a customer asks about."""

    use_class: UseClass
    relief_sought: list[Relief]
    longitude: float | None = None
    latitude: float | None = None
    jurisdiction_slug: str | None = None
    parcel_ids: list[str] | None = None
    label: str | None = None
    acres: float | None = None
    capacity_mw: float | None = None
    by_right: bool | None = None
    staff_recommendation: str | None = None

    def __post_init__(self) -> None:
        if self.jurisdiction_slug is None and (self.longitude is None or self.latitude is None):
            raise ValueError("a site needs either a jurisdiction slug or a coordinate pair")


@dataclass(slots=True)
class ServingModels:
    """The models that produce a served score, loaded once and reused.

    Held together in one object because a score has to record which combination produced it, and four
    separately loaded models make that record easy to get wrong.
    """

    dataset: Dataset
    base_rate: BaseRateModel
    boosted: BoostedModel | None = None
    hierarchical: HierarchicalModel | None = None
    survival: SurvivalModel | None = None
    rule_change: dict[str, RuleChangeModel] | None = None
    trained_at: datetime | None = None
    notes: list[str] | None = None
    outcome_classes: int = 0
    """Distinct outcomes in the training set. Below two, no model here can state a probability.

    Recorded on the object rather than recomputed by callers because the alternatives path needs the
    same answer as the primary path, and a scorer that abstains for a site while quoting a confident
    number for the county next door has not really abstained.
    """

    @property
    def primary_kind(self) -> str:
        if self.hierarchical is not None and self.hierarchical.converged:
            return "hierarchical"
        if self.boosted is not None and self.boosted.booster is not None:
            return "gradient_boosted"
        return "base_rate"


def load_serving_models(
    conn: Connection,
    *,
    cutoff: date | None = None,
    samples: int = 1200,
    chains: int = 2,
) -> ServingModels:
    """Fit the serving models on everything known up to ``cutoff``.

    In production these are loaded from ``model_run`` artefacts. Fitting on demand is correct at this
    corpus size, where the whole training set fits in memory and a fit takes seconds, and it removes an
    entire class of bug where a served score comes from a stale artefact whose provenance nobody
    checked.
    """
    dataset = load_dataset(conn)
    resolved_cutoff = cutoff or date.today()
    train = dataset.decided.filter(pl.col("decided_on") < resolved_cutoff)
    notes: list[str] = list(dataset.notes)

    models = ServingModels(
        dataset=dataset,
        base_rate=BaseRateModel().fit(train),
        trained_at=datetime.now(UTC),
        notes=notes,
        outcome_classes=(
            int(train.select("approved").to_series().n_unique()) if train.height else 0
        ),
    )

    if train.height == 0:
        notes.append(
            "no decided applications with verified evidence, so only the global prior is available. "
            "Every score will abstain."
        )
        return models

    if train.select("approved").to_series().n_unique() > 1:
        models.boosted = BoostedModel(feature_columns=dataset.feature_columns).fit(train)
        if train.height >= 40:
            hierarchical = HierarchicalModel(feature_columns=dataset.feature_columns)
            hierarchical.fit(train, samples=samples, warmup=samples // 2, chains=chains)
            if hierarchical.converged:
                models.hierarchical = hierarchical
            else:
                notes.append(
                    "the hierarchical model did not converge, so it is not serving and the boosted "
                    "model is reported instead"
                )
        else:
            notes.append(
                f"the hierarchical model needs 40 training rows and the graph has {train.height}"
            )
    else:
        notes.append(
            "every decided application has the same outcome, so no classifier can be fitted"
        )

    survival = SurvivalModel(feature_columns=dataset.feature_columns)
    survival.fit(dataset.frame, as_of=resolved_cutoff)
    models.survival = survival

    models.rule_change = {}
    for use_class in sorted(
        {str(u) for u in dataset.frame.select("use_class").to_series().unique()}
    ):
        model = RuleChangeModel(use_class=use_class)
        model.fit(conn, start=date(resolved_cutoff.year - 8, 1, 1), end=resolved_cutoff)
        models.rule_change[use_class] = model

    return models


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def _resolve_chain(conn: Connection, request: SiteRequest) -> list[dict[str, Any]]:
    from auspice.pipeline.registry.loader import resolve_chain

    if request.longitude is not None and request.latitude is not None:
        return resolve_chain(conn, request.longitude, request.latitude)

    row = (
        conn.execute(
            text(
                """
            SELECT id, slug, name, kind, region, legal_framework, data_depth, discretion_index
            FROM jurisdiction WHERE slug = :slug
            """
            ).bindparams(slug=request.jurisdiction_slug)
        )
        .mappings()
        .first()
    )
    if row is None:
        return []
    return [
        {
            "jurisdiction_id": row["id"],
            "slug": row["slug"],
            "name": row["name"],
            "kind": row["kind"],
            "region": row["region"],
            "legal_framework": row["legal_framework"],
            "data_depth": row["data_depth"],
            "discretion_index": float(row["discretion_index"])
            if row["discretion_index"] is not None
            else None,
            "role": "primary_decider",
        }
    ]


def _staleness_days(conn: Connection, jurisdiction_id: int) -> int | None:
    """Days since the freshest successful fetch for this jurisdiction.

    None means no source has ever been fetched, which the abstention rule treats as unknown rather than
    as fresh. Treating never fetched as fresh would let a jurisdiction with no ingestion at all serve
    confident scores.
    """
    value = conn.execute(
        text(
            """
            SELECT MIN(EXTRACT(EPOCH FROM (now() - s.last_success_at)) / 86400.0)
            FROM source s
            WHERE s.jurisdiction_id = :jid AND s.enabled AND s.last_success_at IS NOT NULL
            """
        ).bindparams(jid=jurisdiction_id)
    ).scalar()
    return int(value) if value is not None else None


def _synthetic_feature_row(
    conn: Connection, *, jurisdiction_id: int, request: SiteRequest, as_of: date
) -> FeatureRow:
    """Build features for a hypothetical application that is not in the graph.

    A prospective site has no application row, so one is materialised in a savepoint, features are
    built against it, and the savepoint is rolled back. That guarantees the prospective score uses
    exactly the same code path as a historical one, which is the only way the calibration measured on
    history transfers to it.
    """
    from auspice.pipeline.features import build_for_application

    savepoint = conn.begin_nested()
    try:
        application_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO application (
                        jurisdiction_id, body_id, external_id, use_class, relief_sought, by_right,
                        acres, capacity_mw, filed_on, outcome, censored, label_source,
                        staff_recommendation
                    )
                    SELECT
                        :jid,
                        (SELECT id FROM decision_body
                         WHERE jurisdiction_id = :jid
                           AND recommendation_is_binding IS NOT TRUE
                         ORDER BY seats DESC NULLS LAST LIMIT 1),
                        :ext, :use_class, :relief, :by_right, :acres, :mw, :filed,
                        'pending', true, 'extracted', :staff
                    RETURNING id
                    """
                ).bindparams(
                    jid=jurisdiction_id,
                    ext=f"prospective:{secrets.token_hex(8)}",
                    use_class=request.use_class.value,
                    relief=[r.value for r in request.relief_sought],
                    by_right=request.by_right,
                    acres=request.acres,
                    mw=request.capacity_mw,
                    filed=as_of,
                    staff=request.staff_recommendation,
                )
            ).scalar_one()
        )
        row = build_for_application(conn, application_id, as_of=as_of)
        row.application_id = 0  # it does not exist outside the savepoint
        return row
    finally:
        savepoint.rollback()


def _feature_frame(
    row: FeatureRow, *, chain_head: dict[str, Any], dataset: Dataset
) -> pl.DataFrame:
    values: dict[str, Any] = {
        "application_id": 0,
        "jurisdiction": chain_head["slug"],
        "region": chain_head["region"],
        "legal_framework": chain_head["legal_framework"],
        "use_class": None,
        "approved": 0,
        "censored": True,
        "risk": "censored",
        "filed_on": row.as_of,
        "decided_on": None,
        "as_of": row.as_of,
        "months_to_decision": None,
        "n_missing": len(row.missing),
    }
    for name in feature_names(include_evidence=True):
        raw = row.values.get(name)
        values[name] = float(raw) if isinstance(raw, (bool, int, float)) else None
    for column in dataset.feature_columns:
        values.setdefault(column, None)
    return pl.DataFrame([values])


# ---------------------------------------------------------------------------
# Evidence, drivers, precedents
# ---------------------------------------------------------------------------
def _evidence_for_jurisdiction(
    conn: Connection, jurisdiction_id: int, *, limit: int = 40
) -> list[Evidence]:
    """Verified quotes available to explain this jurisdiction's score.

    Only verified rows are read. An unverified quote never reaches a customer, and the score object
    rejects one if it somehow gets this far.
    """
    rows = (
        conn.execute(
            text(
                """
            SELECT
                fe.id, fe.subject_table, fe.subject_id, fe.page, fe.quote, fe.verified,
                d.id AS document_id, d.title, d.kind, d.source_url, d.published_on
            FROM fact_evidence fe
            JOIN document d ON d.id = fe.document_id
            LEFT JOIN application a
                ON fe.subject_table = 'application' AND a.id = fe.subject_id
            LEFT JOIN instrument i
                ON fe.subject_table = 'instrument' AND i.id = fe.subject_id
            WHERE fe.verified
              AND COALESCE(a.jurisdiction_id, i.jurisdiction_id, d.jurisdiction_id) = :jid
            ORDER BY d.published_on DESC NULLS LAST, fe.id DESC
            LIMIT :limit
            """
            ).bindparams(jid=jurisdiction_id, limit=limit)
        )
        .mappings()
        .all()
    )

    return [
        Evidence(
            evidence_id=f"ev_{row['id']}",
            document_id=row["document_id"],
            document_title=row["title"],
            document_kind=row["kind"],
            source_url=row["source_url"],
            page=row["page"],
            quote=row["quote"],
            verified=bool(row["verified"]),
            retrieved_on=row["published_on"],
        )
        for row in rows
    ]


# Which kind of evidence best supports each feature group. Used to attach a quote to a driver without
# guessing: a rules driver is supported by an ordinance, an opposition driver by a hearing record.
_GROUP_EVIDENCE_KINDS: dict[str, tuple[str, ...]] = {
    "rules": ("ordinance", "resolution", "legal_notice", "comprehensive_plan"),
    "base_rates": ("minutes", "staff_report"),
    "opposition": ("transcript", "minutes", "news_article"),
    "politics": ("minutes", "election_record", "transcript"),
    "physical": ("staff_report", "application_packet"),
    "applicant": ("application_packet", "minutes"),
}


def _attach_evidence(feature: str, evidence: list[Evidence]) -> str | None:
    spec = BY_NAME.get(feature)
    if spec is None:
        return None
    preferred = _GROUP_EVIDENCE_KINDS.get(spec.group.value, ())
    for kind in preferred:
        for item in evidence:
            if item.document_kind == kind:
                return item.evidence_id
    return None


def _drivers(
    *,
    row: FeatureRow,
    contributions: dict[str, float],
    evidence: list[Evidence],
) -> list[Driver]:
    """Rank the drivers by the magnitude of their contribution to the logit.

    Weights are normalised to sum to one across the drivers shown, so a customer reading the table sees
    shares of the explanation rather than raw logit units nobody can interpret. The direction comes from
    the sign of the contribution, not from the dictionary's expectation, because a fitted sign that
    contradicts the domain is information and hiding it would be dishonest.
    """
    scored = [
        (name, value)
        for name, value in contributions.items()
        if abs(value) > 1e-6 and row.values.get(name) is not None
    ]
    scored.sort(key=lambda pair: -abs(pair[1]))
    top = scored[:MAX_DRIVERS]
    total = sum(abs(value) for _name, value in top) or 1.0

    drivers: list[Driver] = []
    for name, value in top:
        spec = BY_NAME.get(name)
        if spec is None or not spec.plain_language:
            continue
        raw = row.values.get(name)
        drivers.append(
            Driver(
                factor=name,
                group=spec.group.value,
                direction="positive" if value > 0 else "negative",
                weight=round(abs(value) / total, 4),
                plain_language=describe(name, raw),
                evidence_id=_attach_evidence(name, evidence),
                value=float(raw) if isinstance(raw, (bool, int, float)) else None,
            )
        )
    return drivers


def _precedents(
    conn: Connection, *, jurisdiction_id: int, request: SiteRequest, as_of: date
) -> list[Precedent]:
    """The comparable decisions the estimate rests on.

    Similarity is computed from four dimensions a customer can check rather than from an embedding:
    same use class, overlapping relief, comparable scale, and recency. An opaque similarity score in a
    memo is worse than a transparent one that is slightly cruder, because the memo's job is to be
    defended.
    """
    rows = (
        conn.execute(
            text(
                """
            SELECT
                a.id, a.external_id, a.use_class, a.relief_sought, a.acres, a.capacity_mw,
                a.outcome, a.decided_on, a.vote_for, a.vote_against, a.months_to_decision,
                j.slug AS jurisdiction,
                COALESCE(
                    (SELECT array_agg(DISTINCT g) FROM objection o, unnest(o.grounds) g
                     WHERE o.application_id = a.id),
                    ARRAY[]::text[]
                ) AS grounds,
                (SELECT fe.id FROM fact_evidence fe
                 WHERE fe.subject_table = 'application' AND fe.subject_id = a.id AND fe.verified
                 ORDER BY fe.id LIMIT 1) AS evidence_id
            FROM application a
            JOIN jurisdiction j ON j.id = a.jurisdiction_id
            WHERE a.jurisdiction_id = :jid
              AND a.decided_on IS NOT NULL
              AND a.decided_on < :as_of
              AND a.outcome IN ('approved','approved_with_conditions','denied','withdrawn')
              AND EXISTS (
                  SELECT 1 FROM fact_evidence fe
                  WHERE fe.subject_table = 'application' AND fe.subject_id = a.id AND fe.verified
              )
            ORDER BY a.decided_on DESC
            LIMIT 40
            """
            ).bindparams(jid=jurisdiction_id, as_of=as_of)
        )
        .mappings()
        .all()
    )

    requested = {r.value for r in request.relief_sought}
    precedents: list[Precedent] = []

    for row in rows:
        basis: dict[str, float] = {}
        basis["use_class"] = 1.0 if row["use_class"] == request.use_class.value else 0.3

        held = set(row["relief_sought"] or [])
        overlap = len(held & requested) / max(len(held | requested), 1)
        basis["relief_overlap"] = round(overlap, 3)

        if request.acres and row["acres"]:
            ratio = min(float(row["acres"]), request.acres) / max(
                float(row["acres"]), request.acres
            )
            basis["scale"] = round(ratio, 3)
        else:
            basis["scale"] = 0.5

        # Recency, halving every three years. Precedent decays, and section 6.7 group C is explicit
        # that most models ignore that.
        age_years = (as_of.toordinal() - row["decided_on"].toordinal()) / 365.25
        basis["recency"] = round(0.5 ** (age_years / 3.0), 3)

        similarity = round(
            0.40 * basis["use_class"]
            + 0.25 * basis["relief_overlap"]
            + 0.15 * basis["scale"]
            + 0.20 * basis["recency"],
            4,
        )

        precedents.append(
            Precedent(
                application_id=int(row["id"]),
                external_id=row["external_id"],
                jurisdiction=row["jurisdiction"],
                similarity=min(similarity, 1.0),
                outcome=Outcome(row["outcome"]),
                vote=(
                    f"{row['vote_for']}-{row['vote_against']}"
                    if row["vote_for"] is not None and row["vote_against"] is not None
                    else None
                ),
                months_to_decision=float(row["months_to_decision"])
                if row["months_to_decision"]
                else None,
                decided_on=row["decided_on"],
                objection_grounds=[
                    ObjectionGround(g)
                    for g in (row["grounds"] or [])
                    if g in ObjectionGround.__members__.values()
                    or g in {m.value for m in ObjectionGround}
                ],
                evidence_id=f"ev_{row['evidence_id']}" if row["evidence_id"] else None,
                basis=basis,
            )
        )

    precedents.sort(key=lambda p: -p.similarity)
    return precedents[:MAX_PRECEDENTS]


def _mitigations(row: FeatureRow, *, probability: float | None) -> list[Mitigation]:
    """Actions with a computed delta, not a suggested one.

    Each mitigation corresponds to changing one feature and re-reading the model, so the delta is the
    model's own arithmetic. Where the feature cannot be changed by the applicant, there is no
    mitigation, which is why this list is often short and occasionally empty. An empty list is a real
    answer: sometimes there is nothing the applicant can do.
    """
    if probability is None:
        return []

    mitigations: list[Mitigation] = []

    if row.values.get("moratorium_active") and row.values.get("months_to_moratorium_expiry"):
        months = float(row.values["months_to_moratorium_expiry"])  # type: ignore[arg-type]
        mitigations.append(
            Mitigation(
                action=f"Wait for the moratorium to lapse in about {months:.0f} months before filing.",
                expected_delta=0.0,
                basis=(
                    "A live moratorium is a dated no rather than a permanent one. The delta is recorded "
                    "as zero because waiting does not change the board's disposition, it changes the "
                    "timeline, which is priced in the time distribution rather than the probability."
                ),
            )
        )

    margin = row.values.get("setback_compliance_margin_ft")
    if margin is not None and float(margin) < 0:
        mitigations.append(
            Mitigation(
                action=f"Move the buildable area to clear the binding setback by {abs(float(margin)):.0f} feet.",
                expected_delta=0.0,
                basis=(
                    "The site currently fails the setback in force. The delta is not estimated because "
                    "compliance is a precondition rather than a factor, and a model trained on "
                    "compliant applications cannot price a non-compliant one."
                ),
            )
        )

    discretionary = [r for r in row.values if r == "relief_count"]
    if discretionary and row.values.get("relief_count") and float(row.values["relief_count"]) > 1:  # type: ignore[arg-type]
        mitigations.append(
            Mitigation(
                action="Separate the applications and file the least contested relief first.",
                expected_delta=0.0,
                basis=(
                    "Each separate approval is an independent failure point. Splitting them does not "
                    "raise the probability of the whole project, so the delta is zero, but it changes "
                    "which failure happens first and how much is spent before it does."
                ),
            )
        )

    return mitigations


def _alternatives(
    conn: Connection,
    *,
    models: ServingModels,
    chain_head: dict[str, Any],
    request: SiteRequest,
    as_of: date,
) -> list[Alternative]:
    """Nearby jurisdictions with a materially better record for this use class.

    Section 6.10 calls this the highest value single feature in the product and the reason customers
    renew, and section 5.6 rule 5 puts it in the object. The ranking is expected value: the probability
    times a feasibility proxy, less a relocation penalty that grows with distance.
    """
    rows = (
        conn.execute(
            text(
                """
            SELECT
                j.id, j.slug, j.name, j.region, j.legal_framework, j.data_depth, j.discretion_index,
                ROUND(
                    ST_Distance(
                        (SELECT boundary::geography FROM jurisdiction WHERE id = :jid),
                        j.boundary::geography
                    ) / 1000.0
                ) AS distance_km
            FROM jurisdiction j
            WHERE j.id <> :jid
              AND j.boundary IS NOT NULL
              AND j.data_depth > 0
            ORDER BY distance_km
            LIMIT 12
            """
            ).bindparams(jid=chain_head["jurisdiction_id"])
        )
        .mappings()
        .all()
    )

    alternatives: list[Alternative] = []
    for row in rows:
        probability, _interval, _weight = _predict_for_jurisdiction(
            conn, models=models, jurisdiction=dict(row), request=request, as_of=as_of
        )
        distance = float(row["distance_km"] or 0.0)
        # Relocation cost as a probability equivalent: two points per hundred kilometres. Crude and
        # stated as crude, so a customer can substitute their own number.
        penalty = min(0.02 * distance / 100.0, 0.15)
        alternatives.append(
            Alternative(
                jurisdiction=row["name"],
                jurisdiction_slug=row["slug"],
                distance_km=distance,
                by_right=None,
                approval_probability=probability,
                abstained=probability is None,
                expected_value_rank=round((probability or 0.0) - penalty, 4),
                note=None
                if probability is not None
                else "we do not hold enough decisions here to give a number",
            )
        )

    alternatives.sort(key=lambda a: -a.expected_value_rank)
    return alternatives[:MAX_ALTERNATIVES]


def _predict_for_jurisdiction(
    conn: Connection,
    *,
    models: ServingModels,
    jurisdiction: dict[str, Any],
    request: SiteRequest,
    as_of: date,
) -> tuple[float | None, tuple[float, float] | None, float]:
    """Probability, interval and pooling weight for one jurisdiction. None when it would abstain."""
    row = _synthetic_feature_row(
        conn,
        jurisdiction_id=int(
            jurisdiction["id"] if "id" in jurisdiction else jurisdiction["jurisdiction_id"]
        ),
        request=request,
        as_of=as_of,
    )
    frame = _feature_frame(
        row,
        chain_head={
            "slug": jurisdiction["slug"],
            "region": jurisdiction["region"],
            "legal_framework": jurisdiction["legal_framework"],
        },
        dataset=models.dataset,
    )

    n_comparable = int(row.values.get("n_comparable_decisions") or 0)

    if models.hierarchical is not None:
        probability = float(models.hierarchical.predict(frame)[0])
        low, high = models.hierarchical.predict_interval(frame)[0]
        weight = models.hierarchical.pooling_weight(
            jurisdiction["slug"], local_observations=n_comparable
        )
    elif models.boosted is not None and models.boosted.booster is not None:
        probability = float(models.boosted.predict(frame)[0])
        low, high = models.boosted.predict_interval(frame)[0]
        weight = models.base_rate.pooling_weight(
            jurisdiction=jurisdiction["slug"], use_class=request.use_class.value
        )
    else:
        probability, observations = models.base_rate.predict_one(
            jurisdiction=jurisdiction["slug"],
            region=jurisdiction["region"],
            use_class=request.use_class.value,
        )
        weight = models.base_rate.pooling_weight(
            jurisdiction=jurisdiction["slug"], use_class=request.use_class.value
        )
        # A base rate has no interval of its own. A Jeffreys interval on the observed proportion is the
        # honest substitute and it is wide when the count is small, which is correct.
        spread = 1.0 / np.sqrt(observations + 2.0)
        low, high = max(0.0, probability - spread), min(1.0, probability + spread)

    decision = decide(
        AbstentionInput(
            n_comparable_decisions=n_comparable,
            pooling_weight=weight,
            interval_width=float(high - low),
            staleness_days=_staleness_days(
                conn, int(jurisdiction.get("id") or jurisdiction["jurisdiction_id"])
            ),
            outcome_classes_in_training=models.outcome_classes,
        )
    )
    if decision.abstained:
        return None, None, weight
    return round(float(probability), 5), (round(float(low), 5), round(float(high), 5)), weight


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------
def score_site(
    conn: Connection,
    request: SiteRequest,
    *,
    models: ServingModels,
    as_of: date | None = None,
    include_alternatives: bool = True,
) -> Score:
    """Produce the section 5.6 object for one site."""
    resolved_as_of = as_of or date.today()
    chain = _resolve_chain(conn, request)

    if not chain:
        return _unresolved_score(request, models=models, as_of=resolved_as_of)

    head = chain[0]
    jurisdiction_id = int(head["jurisdiction_id"])

    row = _synthetic_feature_row(
        conn, jurisdiction_id=jurisdiction_id, request=request, as_of=resolved_as_of
    )
    frame = _feature_frame(row, chain_head=head, dataset=models.dataset)
    evidence = _evidence_for_jurisdiction(conn, jurisdiction_id)

    n_comparable = int(row.values.get("n_comparable_decisions") or 0)
    staleness = _staleness_days(conn, jurisdiction_id)

    probability: float | None
    interval: tuple[float, float] | None
    contributions: dict[str, float] = {}

    if models.hierarchical is not None:
        probability = float(models.hierarchical.predict(frame)[0])
        low, high = models.hierarchical.predict_interval(frame)[0]
        interval = (float(low), float(high))
        contributions = models.hierarchical.driver_contributions(frame)
        pooling_weight = models.hierarchical.pooling_weight(
            head["slug"], local_observations=n_comparable
        )
        interval_kind = "credible"
        model_kind = "hierarchical"
    elif models.boosted is not None and models.boosted.booster is not None:
        probability = float(models.boosted.predict(frame)[0])
        low, high = models.boosted.predict_interval(frame)[0]
        interval = (float(low), float(high))
        shap = models.boosted.shap_values(frame)
        if shap is not None:
            contributions = dict(zip(models.dataset.feature_columns, shap[0], strict=False))
        else:
            contributions = models.boosted.importances()
        pooling_weight = models.base_rate.pooling_weight(
            jurisdiction=head["slug"], use_class=request.use_class.value
        )
        interval_kind = "bootstrap"
        model_kind = "gradient_boosted"
    else:
        probability, observations = models.base_rate.predict_one(
            jurisdiction=head["slug"], region=head["region"], use_class=request.use_class.value
        )
        spread = 1.0 / float(np.sqrt(observations + 2.0))
        interval = (max(0.0, probability - spread), min(1.0, probability + spread))
        pooling_weight = models.base_rate.pooling_weight(
            jurisdiction=head["slug"], use_class=request.use_class.value
        )
        interval_kind = "bootstrap"
        model_kind = "base_rate"

    assert interval is not None
    decision = decide(
        AbstentionInput(
            n_comparable_decisions=n_comparable,
            pooling_weight=pooling_weight,
            interval_width=interval[1] - interval[0],
            staleness_days=staleness,
            outcome_classes_in_training=models.outcome_classes,
        )
    )

    local_base_rate, _observations = models.base_rate.predict_one(
        jurisdiction=head["slug"], region=head["region"], use_class=request.use_class.value
    )

    time_to_decision = _time_to_decision(models, frame)
    rule_change = _rule_change_probability(
        conn,
        models=models,
        jurisdiction_id=jurisdiction_id,
        use_class=request.use_class,
        as_of=resolved_as_of,
        months=time_to_decision.p50 if time_to_decision else 12.0,
    )

    if decision.abstained:
        determination = Determination(
            abstained=True,
            abstention_reasons=decision.reasons,
            time_to_decision_months=time_to_decision,
            probability_of_rule_change_before_decision=rule_change,
            local_base_rate=round(local_base_rate, 5) if n_comparable else None,
        )
        drivers: list[Driver] = []
    else:
        determination = Determination(
            approval_probability=round(float(probability), 5),
            credible_interval_80=(round(interval[0], 5), round(interval[1], 5)),
            interval_kind=interval_kind,  # type: ignore[arg-type]
            confidence=confidence_for(
                interval_width=interval[1] - interval[0],
                pooling_weight=pooling_weight,
                n_comparable=n_comparable,
            ),
            time_to_decision_months=time_to_decision,
            probability_of_rule_change_before_decision=rule_change,
            local_base_rate=round(local_base_rate, 5) if n_comparable else None,
        )
        drivers = _drivers(row=row, contributions=contributions, evidence=evidence)

    used_evidence_ids = {d.evidence_id for d in drivers if d.evidence_id}
    precedents = _precedents(
        conn, jurisdiction_id=jurisdiction_id, request=request, as_of=resolved_as_of
    )
    used_evidence_ids |= {p.evidence_id for p in precedents if p.evidence_id}

    features_hash = hashlib.sha256(
        json.dumps(row.as_json(), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    return Score(
        public_id=f"scr_{secrets.token_hex(8)}",
        generated_at=datetime.now(UTC),
        site=Site(
            parcel_ids=request.parcel_ids or [],
            label=request.label,
            longitude=request.longitude,
            latitude=request.latitude,
            jurisdiction_chain=[
                JurisdictionLink(
                    level=link["kind"],
                    name=link["name"],
                    slug=link["slug"],
                    role=JurisdictionRole(link["role"]),
                    data_depth=int(link["data_depth"] or 0),
                    discretion_index=link["discretion_index"],
                )
                for link in chain
            ],
            use_class=request.use_class,
            requested_relief=request.relief_sought,
            by_right=request.by_right,
            acres=request.acres,
            capacity_mw=request.capacity_mw,
        ),
        determination=determination,
        drivers=drivers,
        precedents=precedents,
        mitigations=_mitigations(row, probability=determination.approval_probability),
        alternatives=(
            _alternatives(
                conn, models=models, chain_head=head, request=request, as_of=resolved_as_of
            )
            if include_alternatives
            else []
        ),
        evidence=[e for e in evidence if e.evidence_id in used_evidence_ids],
        provenance=Provenance(
            model_version="0.1.0",
            model_kind=model_kind,
            survival_model_version="1.0.0" if models.survival and models.survival.aft else None,
            rule_change_model_version="1.0.0" if rule_change is not None else None,
            feature_set_version=FEATURE_SET_VERSION,
            dataset_hash=models.dataset.hash(),
            data_as_of=resolved_as_of,
            documents_used=len({e.document_id for e in evidence}),
            jurisdiction_data_depth=(
                f"{n_comparable} comparable decisions with verified provenance"
                if n_comparable
                else "no comparable decisions with verified provenance"
            ),
            pooled=pooling_weight > 0.2,
            pooling_weight=round(pooling_weight, 4),
            pooling_note=pooling_note(
                pooling_weight=pooling_weight,
                n_comparable=n_comparable,
                similar_count=len(
                    models.hierarchical.cluster_members.get(
                        models.hierarchical.cluster_assignment.get(head["slug"], ""), []
                    )
                )
                if models.hierarchical
                else 0,
            ),
            stale=decision.stale_flag,
            staleness_days=staleness,
            features_missing=sorted(row.missing),
        ),
        features_hash=features_hash,
    )


def _time_to_decision(models: ServingModels, frame: pl.DataFrame) -> TimeToDecision | None:
    if models.survival is None:
        return None
    quantiles = models.survival.quantiles(frame)[0]
    return TimeToDecision(
        p10=round(float(quantiles[0]), 1),
        p50=round(float(quantiles[1]), 1),
        p90=round(float(quantiles[2]), 1),
        basis="fitted" if models.survival.aft is not None else "empirical",
    )


def _rule_change_probability(
    conn: Connection,
    *,
    models: ServingModels,
    jurisdiction_id: int,
    use_class: UseClass,
    as_of: date,
    months: float,
) -> float | None:
    if not models.rule_change:
        return None
    model = models.rule_change.get(use_class.value)
    if model is None or model.n_rows == 0:
        return None
    covariates = model.covariates_for(conn, jurisdiction_id=jurisdiction_id, as_of=as_of)
    return round(model.probability_before(covariates, months=months), 5)


def _unresolved_score(request: SiteRequest, *, models: ServingModels, as_of: date) -> Score:
    """An abstention for a site whose deciding body we cannot identify.

    Returned rather than raised, because "we cannot tell who decides here" is a real answer and the
    honest one for a site outside the covered counties. Raising would push the caller into inventing
    a fallback.
    """
    from auspice.domain import AbstentionReason

    return Score(
        public_id=f"scr_{secrets.token_hex(8)}",
        generated_at=datetime.now(UTC),
        site=Site(
            parcel_ids=request.parcel_ids or [],
            label=request.label,
            longitude=request.longitude,
            latitude=request.latitude,
            jurisdiction_chain=[
                JurisdictionLink(
                    level="unknown",
                    name="not resolved",
                    slug=request.jurisdiction_slug or "unresolved",
                    role=JurisdictionRole.primary_decider,
                    data_depth=0,
                )
            ],
            use_class=request.use_class,
            requested_relief=request.relief_sought,
        ),
        determination=Determination(
            abstained=True,
            abstention_reasons=[AbstentionReason.unresolved_jurisdiction_chain],
        ),
        provenance=Provenance(
            model_version="0.1.0",
            model_kind="none",
            feature_set_version=FEATURE_SET_VERSION,
            dataset_hash=models.dataset.hash(),
            data_as_of=as_of,
            documents_used=0,
            jurisdiction_data_depth="the jurisdiction chain did not resolve",
            pooled=False,
            pooling_weight=1.0,
            pooling_note=None,
            features_missing=[],
        ),
        features_hash=hashlib.sha256(b"unresolved").hexdigest(),
    )


def abstention_notice(score: Score) -> str:
    """The text shown in place of a number. Bordered, plain, unapologetic.

    Dispatches on the reason rather than always describing the thin record conditions, because telling
    someone their county has too few comparables when the real problem is that our corpus contains one
    kind of outcome would be a false explanation of a true refusal.
    """
    determination = score.determination
    if not determination.abstained:
        return ""

    reasons = set(determination.abstention_reasons)

    if AbstentionReason.unresolved_jurisdiction_chain in reasons:
        return (
            "We cannot say who decides for this parcel. Until the jurisdiction chain resolves, any "
            "probability would be a guess about the wrong body."
        )

    if AbstentionReason.degenerate_training_corpus in reasons:
        return (
            "Every decision we hold has the same outcome, so the model has never seen an application "
            "go the other way. It cannot tell you the odds of something it has no example of. This is "
            "a gap in our corpus, not a finding about your site."
        )

    if AbstentionReason.stale_jurisdiction_data in reasons:
        days = score.provenance.staleness_days
        return (
            f"Our data for this jurisdiction is {days} days old. The rules may have changed since, "
            "and a score computed on rules that no longer exist is worse than no score."
        )

    head = score.site.jurisdiction_chain[0]
    return explain(
        AbstentionInput(
            n_comparable_decisions=head.data_depth,
            pooling_weight=score.provenance.pooling_weight,
            interval_width=determination.interval_width or 1.0,
            staleness_days=score.provenance.staleness_days,
        )
    )


def require_models(models: ServingModels) -> None:
    """Refuse to serve if nothing can produce a number.

    Raised rather than returning a base rate for everything, because a service that answers every query
    with the global prior looks like it is working.
    """
    if models.base_rate.n_train == 0:
        raise StageUnavailableError(
            "no decided applications with verified evidence are loaded, so no score can be produced. "
            "Run `auspice labels load`, `auspice labels verify`, then `auspice features build`."
        )
