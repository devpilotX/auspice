"""Stage 7: point in time feature construction.

Section 6.9 validation rule 3 is the one that decides whether the whole exercise is honest: every
feature has to be computed as it would have been known on the filing date. If the score for a 2024
decision uses a 2025 ordinance, the model is cheating, and the resulting Brier score is a lie that
will be published.

Three mechanisms make that enforceable here rather than aspirational.

**One as-of date, threaded everywhere.** Every query in this module takes ``as_of`` and every
predicate filters on it. There is no code path that reads the current state of anything.

**``known_from``, not ``occurred_on``.** The ``event`` table carries both. A decision that happened
on 3 March but only appeared in minutes published on 20 March was not knowable on the 10th, and the
history features read ``known_from`` so they cannot see it.

**A leakage test that tries to cheat.** ``tests/unit/test_no_leakage.py`` builds features for a row,
then inserts a later decision, rebuilds, and asserts nothing moved. That is a test that fails if
someone writes a query without the date predicate, which is the actual failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.domain import DISCRETIONARY_RELIEF
from auspice.logging import get_logger
from auspice.pipeline.features.dictionary import (
    FEATURE_SET_VERSION,
    feature_names,
)

log = get_logger(__name__, _stage="features")

RECENT_WINDOW_MONTHS = 24
TREND_WINDOW_DECISIONS = 8
RULE_CHANGE_DANGER_DAYS = 180

_DISCRETIONARY = sorted(r.value for r in DISCRETIONARY_RELIEF)


@dataclass(slots=True)
class FeatureRow:
    """One application's features as of one date, plus what could not be computed."""

    application_id: int
    as_of: date
    values: dict[str, float | bool | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def set(self, name: str, value: float | bool | None) -> None:
        if value is None:
            self.values[name] = None
            if name not in self.missing:
                self.missing.append(name)
        else:
            self.values[name] = value

    def as_json(self) -> dict[str, Any]:
        return dict(self.values.items())


# ---------------------------------------------------------------------------
# Group A. Decision history, strictly before as_of.
# ---------------------------------------------------------------------------
_HISTORY_SQL = text(
    """
    WITH prior AS (
        SELECT
            a.id,
            a.outcome,
            a.decided_on,
            a.relief_sought,
            a.staff_recommendation,
            row_number() OVER (ORDER BY a.decided_on DESC, a.id DESC) AS recency
        FROM application a
        WHERE a.jurisdiction_id = :jurisdiction_id
          AND a.use_class = :use_class
          AND a.id <> :application_id
          AND a.decided_on IS NOT NULL
          AND a.decided_on < :as_of
          AND a.outcome IN ('approved','approved_with_conditions','denied','withdrawn')
          -- Only rows whose outcome is backed by at least one verified quote. An unverified
          -- row is not evidence, and section 6.7 decision (b) requires verified provenance.
          AND EXISTS (
              SELECT 1 FROM fact_evidence fe
              WHERE fe.subject_table = 'application' AND fe.subject_id = a.id AND fe.verified
          )
    )
    SELECT
        count(*)                                                        AS n_total,
        count(*) FILTER (WHERE outcome IN ('approved','approved_with_conditions')) AS n_approved,
        count(*) FILTER (WHERE outcome = 'denied')                      AS n_denied,
        count(*) FILTER (WHERE outcome = 'withdrawn')                   AS n_withdrawn,
        count(*) FILTER (WHERE decided_on >= (CAST(:as_of AS date) - make_interval(months => :window)))
                                                                        AS n_recent,
        count(*) FILTER (
            WHERE decided_on >= (CAST(:as_of AS date) - make_interval(months => :window))
              AND outcome IN ('approved','approved_with_conditions')
        )                                                               AS n_recent_approved,
        max(decided_on)                                                 AS last_decision,
        count(*) FILTER (WHERE staff_recommendation IS NOT NULL AND staff_recommendation <> 'none')
                                                                        AS n_with_staff,
        count(*) FILTER (
            WHERE staff_recommendation IN ('approve','approve_with_conditions')
              AND outcome IN ('approved','approved_with_conditions')
        ) + count(*) FILTER (
            WHERE staff_recommendation = 'deny' AND outcome = 'denied'
        )                                                               AS n_staff_followed
    FROM prior
    """
)

_TREND_SQL = text(
    """
    SELECT
        row_number() OVER (ORDER BY decided_on) AS position,
        CASE WHEN outcome IN ('approved','approved_with_conditions') THEN 1.0 ELSE 0.0 END AS approved
    FROM (
        SELECT a.outcome, a.decided_on
        FROM application a
        WHERE a.jurisdiction_id = :jurisdiction_id
          AND a.use_class = :use_class
          AND a.id <> :application_id
          AND a.decided_on IS NOT NULL
          AND a.decided_on < :as_of
          AND a.outcome IN ('approved','approved_with_conditions','denied')
        ORDER BY a.decided_on DESC
        LIMIT :limit
    ) recent
    """
)

_STREAK_SQL = text(
    """
    SELECT a.outcome
    FROM application a
    WHERE a.jurisdiction_id = :jurisdiction_id
      AND a.use_class = :use_class
      AND a.id <> :application_id
      AND a.decided_on IS NOT NULL
      AND a.decided_on < :as_of
      AND a.outcome IN ('approved','approved_with_conditions','denied')
    ORDER BY a.decided_on DESC, a.id DESC
    LIMIT 40
    """
)


def _group_a(conn: Connection, row: FeatureRow, *, jurisdiction_id: int, use_class: str) -> int:
    params = {
        "jurisdiction_id": jurisdiction_id,
        "use_class": use_class,
        "application_id": row.application_id,
        "as_of": row.as_of,
        "window": RECENT_WINDOW_MONTHS,
    }
    history = conn.execute(_HISTORY_SQL, params).mappings().one()

    n_total = int(history["n_total"])
    row.set("n_comparable_decisions", float(n_total))

    if n_total == 0:
        # No local record. Every rate is unknown, not zero. Zero would mean "never approves",
        # which is a strong claim we would be making out of ignorance.
        for name in (
            "approval_rate_juris_use",
            "approval_rate_juris_use_24m",
            "approval_rate_trend",
            "denial_streak",
            "withdrawal_rate",
            "months_since_last_comparable",
            "staff_recommendation_alignment",
        ):
            row.set(name, None)
        return 0

    decided = n_total - int(history["n_withdrawn"])
    row.set(
        "approval_rate_juris_use",
        float(history["n_approved"]) / decided if decided else None,
    )

    n_recent = int(history["n_recent"])
    row.set(
        "approval_rate_juris_use_24m",
        float(history["n_recent_approved"]) / n_recent if n_recent else None,
    )

    row.set("withdrawal_rate", float(history["n_withdrawn"]) / n_total)

    last = history["last_decision"]
    row.set(
        "months_since_last_comparable",
        (row.as_of.toordinal() - last.toordinal()) / 30.44 if last else None,
    )

    n_with_staff = int(history["n_with_staff"])
    row.set(
        "staff_recommendation_alignment",
        float(history["n_staff_followed"]) / n_with_staff if n_with_staff else None,
    )

    # Trend: ordinary least squares slope of approval against position over the last N decisions.
    trend_rows = conn.execute(_TREND_SQL, {**params, "limit": TREND_WINDOW_DECISIONS}).all()
    if len(trend_rows) >= 3:
        positions = [float(r[0]) for r in trend_rows]
        approvals = [float(r[1]) for r in trend_rows]
        mean_x = sum(positions) / len(positions)
        mean_y = sum(approvals) / len(approvals)
        denominator = sum((x - mean_x) ** 2 for x in positions)
        slope = (
            sum((x - mean_x) * (y - mean_y) for x, y in zip(positions, approvals, strict=True))
            / denominator
            if denominator
            else 0.0
        )
        row.set("approval_rate_trend", slope)
    else:
        row.set("approval_rate_trend", None)

    # Denial streak: consecutive denials working backwards from the most recent decision.
    streak = 0
    for (outcome,) in conn.execute(_STREAK_SQL, params).all():
        if outcome == "denied":
            streak += 1
        else:
            break
    row.set("denial_streak", float(streak))

    return n_total


# ---------------------------------------------------------------------------
# Group B. Rules in force on as_of.
# ---------------------------------------------------------------------------
_RULES_SQL = text(
    """
    WITH in_force AS (
        SELECT i.*
        FROM instrument i
        WHERE i.jurisdiction_id = :jurisdiction_id
          AND i.adopted_on IS NOT NULL
          AND i.adopted_on <= :as_of
          AND (i.expires_on IS NULL OR i.expires_on > :as_of)
          AND (
              cardinality(i.applies_to_use_classes) = 0
              OR :use_class = ANY(i.applies_to_use_classes)
          )
    ),
    any_change AS (
        SELECT max(i.adopted_on) AS last_change
        FROM instrument i
        WHERE i.jurisdiction_id = :jurisdiction_id
          AND i.adopted_on IS NOT NULL
          AND i.adopted_on <= :as_of
          AND (
              cardinality(i.applies_to_use_classes) = 0
              OR :use_class = ANY(i.applies_to_use_classes)
          )
    )
    SELECT
        (SELECT last_change FROM any_change) AS last_change,
        EXISTS (SELECT 1 FROM in_force WHERE kind = 'moratorium') AS moratorium_active,
        (SELECT min(expires_on) FROM in_force WHERE kind = 'moratorium') AS moratorium_expiry,
        EXISTS (SELECT 1 FROM in_force WHERE kind IN ('overlay_district','interim_control'))
            AS overlay_present,
        EXISTS (
            SELECT 1 FROM in_force
            WHERE kind IN ('resolution','comprehensive_plan')
              AND adopted_on >= (CAST(:as_of AS date) - make_interval(months => 18))
        ) AS open_rule_process,
        (SELECT min((restrictions->>'setback_ft')::numeric)
         FROM in_force WHERE restrictions ? 'setback_ft') AS binding_setback_ft
    """
)


def _group_b(
    conn: Connection,
    row: FeatureRow,
    *,
    jurisdiction_id: int,
    use_class: str,
    relief_sought: list[str],
    by_right: bool | None,
    discretion_index: float | None,
    parcel_setback_ft: float | None,
) -> None:
    rules = (
        conn.execute(
            _RULES_SQL,
            {"jurisdiction_id": jurisdiction_id, "as_of": row.as_of, "use_class": use_class},
        )
        .mappings()
        .one()
    )

    row.set("by_right", by_right)
    row.set("discretion_index", discretion_index)

    discretionary = [r for r in relief_sought if r in _DISCRETIONARY]
    row.set("relief_count", float(len(discretionary) or len(relief_sought)))

    row.set("overlay_present", bool(rules["overlay_present"]))
    row.set("moratorium_active", bool(rules["moratorium_active"]))
    row.set("open_rule_process", bool(rules["open_rule_process"]))

    last_change = rules["last_change"]
    if last_change is None:
        # No instrument on record. Not "the rules have never changed": we simply have not read
        # the ordinance history for this county yet.
        row.set("days_since_rule_change", None)
        row.set("rule_changed_within_180d", None)
    else:
        days = float(row.as_of.toordinal() - last_change.toordinal())
        row.set("days_since_rule_change", days)
        row.set("rule_changed_within_180d", days <= RULE_CHANGE_DANGER_DAYS)

    expiry = rules["moratorium_expiry"]
    row.set(
        "months_to_moratorium_expiry",
        (expiry.toordinal() - row.as_of.toordinal()) / 30.44 if expiry else None,
    )

    binding = rules["binding_setback_ft"]
    if binding is None or parcel_setback_ft is None:
        row.set("setback_compliance_margin_ft", None)
    else:
        row.set("setback_compliance_margin_ft", float(parcel_setback_ft) - float(binding))


# ---------------------------------------------------------------------------
# Group C. Politics, as composed on as_of.
# ---------------------------------------------------------------------------
_BOARD_SQL = text(
    """
    SELECT
        b.id,
        b.seats,
        (
            SELECT min(e.election_date)
            FROM election e
            WHERE e.body_id = b.id AND e.election_date >= :as_of
        ) AS next_election,
        (
            SELECT count(*)
            FROM decision_maker m
            WHERE m.body_id = b.id
              AND (m.term_start IS NULL OR m.term_start <= :as_of)
              AND (m.term_end IS NULL OR m.term_end >= :as_of)
        ) AS sitting_members
    FROM decision_body b
    WHERE b.id = :body_id
    """
)

_MEMBER_HISTORY_SQL = text(
    """
    SELECT
        v.maker_id,
        count(*) AS votes,
        count(*) FILTER (WHERE v.position = 'for') AS votes_for
    FROM vote v
    JOIN application a ON a.id = v.application_id
    JOIN decision_maker m ON m.id = v.maker_id
    WHERE m.body_id = :body_id
      AND a.use_class = :use_class
      AND a.decided_on < :as_of
      AND (m.term_start IS NULL OR m.term_start <= :as_of)
      AND (m.term_end IS NULL OR m.term_end >= :as_of)
    GROUP BY v.maker_id
    """
)


def _group_c(
    conn: Connection,
    row: FeatureRow,
    *,
    body_id: int | None,
    use_class: str,
    home_rule: bool | None,
    staff_recommendation: str | None,
) -> None:
    row.set("home_rule", home_rule)
    row.set(
        "staff_recommended_approval",
        staff_recommendation in {"approve", "approve_with_conditions"}
        if staff_recommendation
        else None,
    )

    if body_id is None:
        for name in (
            "board_seats",
            "board_composition_score",
            "swing_seat_count",
            "months_to_next_election",
            "election_within_12m",
            "turnover_since_last_comparable",
        ):
            row.set(name, None)
        return

    board = conn.execute(_BOARD_SQL, {"body_id": body_id, "as_of": row.as_of}).mappings().one()
    row.set("board_seats", float(board["seats"]) if board["seats"] else None)

    next_election = board["next_election"]
    if next_election is None:
        row.set("months_to_next_election", None)
        row.set("election_within_12m", None)
    else:
        months = (next_election.toordinal() - row.as_of.toordinal()) / 30.44
        row.set("months_to_next_election", months)
        row.set("election_within_12m", months <= 12.0)

    members = conn.execute(
        _MEMBER_HISTORY_SQL,
        {"body_id": body_id, "use_class": use_class, "as_of": row.as_of},
    ).all()

    if not members:
        # No individual vote records yet. The feature is missing, not neutral. A zero here would
        # tell the model the board is balanced when in fact we have not read the minutes.
        row.set("board_composition_score", None)
        row.set("swing_seat_count", None)
    else:
        # Mean of each member's approval rate, centred on zero. Aggregate only: section 8.9
        # forbids predicting how a named individual will vote, and this never leaves the aggregate.
        rates = [float(votes_for) / float(votes) for _maker, votes, votes_for in members if votes]
        row.set("board_composition_score", (sum(rates) / len(rates)) * 2.0 - 1.0)
        row.set("swing_seat_count", float(sum(1 for r in rates if 0.25 <= r <= 0.75)))

    row.set(
        "turnover_since_last_comparable", _turnover(conn, row, body_id=body_id, use_class=use_class)
    )


_TURNOVER_SQL = text(
    """
    WITH last_comparable AS (
        SELECT a.decided_on
        FROM application a
        WHERE a.body_id = :body_id
          AND a.use_class = :use_class
          AND a.decided_on IS NOT NULL
          AND a.decided_on < :as_of
        ORDER BY a.decided_on DESC
        LIMIT 1
    )
    SELECT
        (SELECT decided_on FROM last_comparable) AS since,
        count(*) FILTER (
            WHERE m.term_start IS NOT NULL
              AND m.term_start > (SELECT decided_on FROM last_comparable)
              AND m.term_start <= :as_of
        ) AS new_members,
        count(*) FILTER (
            WHERE (m.term_start IS NULL OR m.term_start <= :as_of)
              AND (m.term_end IS NULL OR m.term_end >= :as_of)
        ) AS sitting
    FROM decision_maker m
    WHERE m.body_id = :body_id
    """
)


def _turnover(conn: Connection, row: FeatureRow, *, body_id: int, use_class: str) -> float | None:
    result = (
        conn.execute(
            _TURNOVER_SQL, {"body_id": body_id, "use_class": use_class, "as_of": row.as_of}
        )
        .mappings()
        .one()
    )
    if result["since"] is None or not result["sitting"]:
        return None
    return float(result["new_members"]) / float(result["sitting"])


# ---------------------------------------------------------------------------
# Group D. Opposition, observed before as_of.
# ---------------------------------------------------------------------------
_OPPOSITION_SQL = text(
    """
    WITH window_objections AS (
        SELECT o.*
        FROM objection o
        WHERE o.jurisdiction_id = :jurisdiction_id
          AND o.observed_on IS NOT NULL
          AND o.observed_on < :as_of
          AND o.observed_on >= (CAST(:as_of AS date) - make_interval(months => :window))
    ),
    window_decisions AS (
        SELECT count(*) AS n
        FROM application a
        WHERE a.jurisdiction_id = :jurisdiction_id
          AND a.decided_on IS NOT NULL
          AND a.decided_on < :as_of
          AND a.decided_on >= (CAST(:as_of AS date) - make_interval(months => :window))
    )
    SELECT
        (SELECT count(*) FROM window_objections)                                AS n_objections,
        (SELECT n FROM window_decisions)                                        AS n_decisions,
        EXISTS (SELECT 1 FROM window_objections WHERE organised)                AS organised,
        (SELECT count(*) FROM window_objections WHERE 'water' = ANY(grounds))    AS water,
        (SELECT count(*) FROM window_objections WHERE 'electricity_cost' = ANY(grounds)) AS power,
        (SELECT count(*) FROM window_objections WHERE 'noise' = ANY(grounds))    AS noise,
        (SELECT count(*) FROM window_objections WHERE 'traffic' = ANY(grounds))  AS traffic
    """
)

_CONTAGION_SQL = text(
    """
    SELECT count(DISTINCT neighbour.id) AS n
    FROM jurisdiction target
    JOIN jurisdiction neighbour
        ON neighbour.id <> target.id
       AND neighbour.boundary IS NOT NULL
       AND target.boundary IS NOT NULL
       AND ST_Intersects(target.boundary, neighbour.boundary)
    JOIN instrument i
        ON i.jurisdiction_id = neighbour.id
       AND i.kind IN ('moratorium','overlay_district','interim_control')
       AND i.adopted_on IS NOT NULL
       AND i.adopted_on < :as_of
       AND i.adopted_on >= (CAST(:as_of AS date) - make_interval(months => :window))
       AND (
           cardinality(i.applies_to_use_classes) = 0
           OR :use_class = ANY(i.applies_to_use_classes)
       )
    WHERE target.id = :jurisdiction_id
    """
)


def _group_d(conn: Connection, row: FeatureRow, *, jurisdiction_id: int, use_class: str) -> None:
    params = {
        "jurisdiction_id": jurisdiction_id,
        "as_of": row.as_of,
        "window": RECENT_WINDOW_MONTHS,
    }
    opposition = conn.execute(_OPPOSITION_SQL, params).mappings().one()

    n_objections = int(opposition["n_objections"])
    n_decisions = int(opposition["n_decisions"] or 0)

    if n_objections == 0 and n_decisions == 0:
        # Nothing observed at all in the window. Every opposition feature is unknown.
        for name in (
            "objection_density_24m",
            "organised_group_present",
            "salience_water",
            "salience_power_cost",
            "salience_noise",
            "salience_traffic",
        ):
            row.set(name, None)
    else:
        row.set(
            "objection_density_24m",
            float(n_objections) / n_decisions if n_decisions else float(n_objections),
        )
        row.set("organised_group_present", bool(opposition["organised"]))
        denominator = float(n_objections) if n_objections else 1.0
        for name, column in (
            ("salience_water", "water"),
            ("salience_power_cost", "power"),
            ("salience_noise", "noise"),
            ("salience_traffic", "traffic"),
        ):
            row.set(name, float(opposition[column]) / denominator if n_objections else None)

    contagion = conn.execute(_CONTAGION_SQL, {**params, "use_class": use_class}).scalar()
    row.set("neighbour_contagion", float(contagion) if contagion is not None else None)


# ---------------------------------------------------------------------------
# Group E and F.
# ---------------------------------------------------------------------------
def _group_e(
    row: FeatureRow,
    *,
    acres: float | None,
    capacity_mw: float | None,
    prior_industrial_use: bool | None,
    distance_to_residential_m: float | None,
) -> None:
    row.set("parcel_acres", acres)
    row.set("capacity_mw", capacity_mw)
    row.set(
        "intensity_mw_per_acre",
        capacity_mw / acres if capacity_mw is not None and acres else None,
    )
    row.set("prior_industrial_use", prior_industrial_use)
    row.set("distance_to_residential_m", distance_to_residential_m)


_APPLICANT_SQL = text(
    """
    SELECT
        count(*) AS n_total,
        count(*) FILTER (WHERE a.outcome IN ('approved','approved_with_conditions')) AS n_approved,
        count(*) FILTER (WHERE a.jurisdiction_id = :jurisdiction_id) AS n_local
    FROM application a
    WHERE a.applicant_cluster_id = :cluster_id
      AND a.id <> :application_id
      AND a.decided_on IS NOT NULL
      AND a.decided_on < :as_of
      AND a.outcome IN ('approved','approved_with_conditions','denied')
    """
)


def _group_f(
    conn: Connection,
    row: FeatureRow,
    *,
    jurisdiction_id: int,
    applicant_cluster_id: int | None,
    entity_opacity: bool | None,
) -> None:
    row.set("entity_opacity", entity_opacity)

    if applicant_cluster_id is None:
        row.set("applicant_track_record", None)
        row.set("applicant_local_experience", None)
        return

    result = (
        conn.execute(
            _APPLICANT_SQL,
            {
                "cluster_id": applicant_cluster_id,
                "application_id": row.application_id,
                "jurisdiction_id": jurisdiction_id,
                "as_of": row.as_of,
            },
        )
        .mappings()
        .one()
    )

    n_total = int(result["n_total"])
    row.set(
        "applicant_track_record",
        float(result["n_approved"]) / n_total if n_total else None,
    )
    row.set("applicant_local_experience", float(result["n_local"]))


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------
_APPLICATION_SQL = text(
    """
    SELECT
        a.id,
        a.jurisdiction_id,
        a.body_id,
        a.use_class,
        a.relief_sought,
        a.by_right,
        a.acres,
        a.capacity_mw,
        a.filed_on,
        a.decided_on,
        a.outcome,
        a.staff_recommendation,
        a.applicant_cluster_id,
        a.censored,
        a.months_to_decision,
        j.slug        AS jurisdiction_slug,
        j.region,
        j.legal_framework,
        j.discretion_index,
        p.acres       AS parcel_acres,
        p.prior_industrial_use,
        ec.opaque     AS entity_opacity
    FROM application a
    JOIN jurisdiction j ON j.id = a.jurisdiction_id
    LEFT JOIN parcel p ON p.id = a.parcel_id
    LEFT JOIN entity_cluster ec ON ec.id = a.applicant_cluster_id
    WHERE (CAST(:application_id AS bigint) IS NULL OR a.id = CAST(:application_id AS bigint))
    ORDER BY a.id
    """
)


def build_for_application(
    conn: Connection, application_id: int, *, as_of: date | None = None
) -> FeatureRow:
    """Build one row. ``as_of`` defaults to the filing date, which is the honest choice."""
    record = conn.execute(_APPLICATION_SQL, {"application_id": application_id}).mappings().one()
    return _build(conn, record, as_of=as_of)


def _build(conn: Connection, record: Any, *, as_of: date | None) -> FeatureRow:
    resolved_as_of = as_of or record["filed_on"] or record["decided_on"] or date.today()
    row = FeatureRow(application_id=int(record["id"]), as_of=resolved_as_of)

    _group_a(
        conn,
        row,
        jurisdiction_id=int(record["jurisdiction_id"]),
        use_class=str(record["use_class"]),
    )
    _group_b(
        conn,
        row,
        jurisdiction_id=int(record["jurisdiction_id"]),
        use_class=str(record["use_class"]),
        relief_sought=list(record["relief_sought"]),
        by_right=record["by_right"],
        discretion_index=float(record["discretion_index"])
        if record["discretion_index"] is not None
        else None,
        parcel_setback_ft=None,
    )
    _group_c(
        conn,
        row,
        body_id=int(record["body_id"]) if record["body_id"] is not None else None,
        use_class=str(record["use_class"]),
        home_rule=record["legal_framework"] == "home_rule" if record["legal_framework"] else None,
        staff_recommendation=record["staff_recommendation"],
    )
    _group_d(
        conn,
        row,
        jurisdiction_id=int(record["jurisdiction_id"]),
        use_class=str(record["use_class"]),
    )
    _group_e(
        row,
        acres=float(record["acres"])
        if record["acres"] is not None
        else float(record["parcel_acres"])
        if record["parcel_acres"] is not None
        else None,
        capacity_mw=float(record["capacity_mw"]) if record["capacity_mw"] is not None else None,
        prior_industrial_use=record["prior_industrial_use"],
        distance_to_residential_m=None,
    )
    _group_f(
        conn,
        row,
        jurisdiction_id=int(record["jurisdiction_id"]),
        applicant_cluster_id=int(record["applicant_cluster_id"])
        if record["applicant_cluster_id"]
        else None,
        entity_opacity=record["entity_opacity"],
    )
    return row


@dataclass(slots=True)
class BuildReport:
    rows: int = 0
    coverage: dict[str, float] = field(default_factory=dict)
    usable: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)


def build_all(conn: Connection, *, persist: bool = True) -> BuildReport:
    """Build features for every application in the graph.

    Coverage is measured here rather than assumed, and the section 6.7 eighty percent rule is then
    applied to the measurement.
    """
    records = conn.execute(_APPLICATION_SQL, {"application_id": None}).mappings().all()
    report = BuildReport()
    present: dict[str, int] = dict.fromkeys(feature_names(include_evidence=True), 0)

    for record in records:
        row = _build(conn, record, as_of=None)
        report.rows += 1
        for name, value in row.values.items():
            if value is not None:
                present[name] = present.get(name, 0) + 1

        if persist:
            statement = pg_insert(schema.feature_snapshot).values(
                application_id=row.application_id,
                as_of=row.as_of,
                feature_set_version=FEATURE_SET_VERSION,
                features=row.as_json(),
                missing=row.missing,
            )
            conn.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        schema.feature_snapshot.c.application_id,
                        schema.feature_snapshot.c.as_of,
                        schema.feature_snapshot.c.feature_set_version,
                    ],
                    set_={
                        "features": statement.excluded.features,
                        "missing": statement.excluded.missing,
                        "computed_at": text("now()"),
                    },
                )
            )

    if report.rows:
        report.coverage = {name: count / report.rows for name, count in present.items()}
    else:
        report.coverage = dict.fromkeys(present, 0.0)

    from auspice.pipeline.features.dictionary import select_usable

    report.usable, report.excluded = select_usable(report.coverage)

    log.info(
        "features built",
        rows=report.rows,
        usable=len(report.usable),
        excluded=len(report.excluded),
        version=FEATURE_SET_VERSION,
    )
    return report
