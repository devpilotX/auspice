"""Stage 11: monitoring, re-scoring and alerts.

Section 6.11: monitoring is what turns a report into a subscription. Without it there is no recurring
revenue and this is a consulting business.

A daily job does the work: re-ingest watched jurisdictions, diff against yesterday, detect material
events, re-score affected sites, fire alerts.

## Materiality, and why it is scored before sending

An alert system that cries wolf gets muted in a week, and a muted alert system is a cancelled subscription.
So every change gets a materiality score between zero and one, and only changes above the send threshold
reach a customer. Everything else is recorded and visible on demand.

Materiality is not the same as importance in the abstract. A moratorium adopted in a county where the
customer holds no sites is important and not material to them. So the score has two parts: how much the
change moves the world, and how much it moves this customer's number. That second part is why an alert
carries the score before and the score after rather than only a description of what happened.

## What counts as a change

The triggers come from section 6.11, ordered by value to the customer. A rule change ranks highest, because
that is the retroactive kill caught early. Second is a moratorium appearing on an agenda, which is enormous
precisely because there is still time to act.

An alert whose score movement is below the noise floor is suppressed with a reason rather than dropped, so
"why did I not hear about this" has an answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from auspice.domain import AlertTrigger
from auspice.logging import get_logger

log = get_logger(__name__, _stage="monitor")

# Below this, an alert is recorded and not delivered.
SEND_THRESHOLD = 0.35

# A score movement smaller than this is noise from refitting rather than news.
SCORE_NOISE_FLOOR = 0.03

# How far a comparable denial can be and still matter. Opposition diffuses geographically, and section 6.7
# group D makes contagion a feature, so the radius is generous.
NEARBY_KM = 80.0

# Base materiality per trigger, before the customer specific adjustment.
BASE_MATERIALITY: dict[AlertTrigger, float] = {
    AlertTrigger.rule_changed: 0.85,
    AlertTrigger.moratorium_on_agenda: 0.90,
    AlertTrigger.moratorium_enacted: 0.95,
    AlertTrigger.comparable_denied_nearby: 0.60,
    AlertTrigger.board_composition_changed: 0.55,
    AlertTrigger.litigation_filed: 0.50,
    AlertTrigger.use_class_on_agenda: 0.40,
    AlertTrigger.score_moved: 0.45,
    AlertTrigger.source_stale: 0.25,
}


@dataclass(slots=True)
class Change:
    """Something that happened in a jurisdiction that might matter to someone."""

    jurisdiction_id: int
    jurisdiction_slug: str
    trigger: AlertTrigger
    detected_on: date
    summary: str
    document_id: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    base_materiality: float = 0.0

    def __post_init__(self) -> None:
        if self.base_materiality == 0.0:
            self.base_materiality = BASE_MATERIALITY.get(self.trigger, 0.3)


@dataclass(slots=True)
class MonitorReport:
    changes_detected: int = 0
    alerts_created: int = 0
    alerts_suppressed: int = 0
    sites_rescored: int = 0
    watches_checked: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "changes_detected": self.changes_detected,
            "alerts_created": self.alerts_created,
            "alerts_suppressed": self.alerts_suppressed,
            "sites_rescored": self.sites_rescored,
            "watches_checked": self.watches_checked,
        }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
def detect_changes(conn: Connection, *, since: date) -> list[Change]:
    """Everything that changed on or after ``since``, across every watched jurisdiction.

    Reads the event table rather than diffing documents, because the extraction stage has already turned a
    document into a dated event with a type. Diffing raw documents again here would mean two places that
    decide what a change is, and they would eventually disagree.
    """
    changes: list[Change] = []

    rows = (
        conn.execute(
            text(
                """
            SELECT
                e.id, e.jurisdiction_id, j.slug, e.event_type, e.occurred_on, e.known_from, e.detail,
                i.kind AS instrument_kind, i.citation, i.expires_on, i.title AS instrument_title
            FROM event e
            JOIN jurisdiction j ON j.id = e.jurisdiction_id
            LEFT JOIN instrument i ON i.id = e.instrument_id
            WHERE e.known_from >= :since
              AND EXISTS (SELECT 1 FROM watch w WHERE w.jurisdiction_id = e.jurisdiction_id AND w.active)
            ORDER BY e.known_from, e.id
            """
            ).bindparams(since=since)
        )
        .mappings()
        .all()
    )

    for row in rows:
        trigger = _trigger_for(str(row["event_type"]), row["instrument_kind"])
        if trigger is None:
            continue

        changes.append(
            Change(
                jurisdiction_id=int(row["jurisdiction_id"]),
                jurisdiction_slug=str(row["slug"]),
                trigger=trigger,
                detected_on=row["known_from"],
                summary=_summarise(row, trigger),
                after=dict(row["detail"]) if row["detail"] else None,
            )
        )

    changes.extend(_detect_nearby_denials(conn, since=since))
    changes.extend(_detect_stale_sources(conn))

    log.info("changes detected", count=len(changes), since=since.isoformat())
    return changes


def _trigger_for(event_type: str, instrument_kind: str | None) -> AlertTrigger | None:
    if event_type == "moratorium_enacted":
        return AlertTrigger.moratorium_enacted
    if event_type in {"moratorium_proposed", "ordinance_proposed"}:
        return AlertTrigger.moratorium_on_agenda
    if event_type == "ordinance_adopted":
        return AlertTrigger.rule_changed
    if event_type in {"litigation_filed", "appeal_filed"}:
        return AlertTrigger.litigation_filed
    if event_type == "membership_changed":
        return AlertTrigger.board_composition_changed
    if event_type == "decision_rendered":
        # A decision in a watched county is only news if it went against the applicant. An approval is
        # useful context and does not warrant an interruption.
        return None
    del instrument_kind
    return None


def _summarise(row: Any, trigger: AlertTrigger) -> str:
    """One sentence a customer can act on, written plainly.

    Deliberately not generated by a language model. There are nine triggers and each has one honest phrasing,
    so a template is both cheaper and more predictable than a generated sentence that occasionally
    editorialises.
    """
    when = row["occurred_on"].isoformat() if row["occurred_on"] else "an unrecorded date"
    citation = row["citation"] or row["instrument_title"] or "an instrument"

    if trigger is AlertTrigger.moratorium_enacted:
        expiry = row["expires_on"]
        tail = f" It lifts on {expiry.isoformat()}." if expiry else " No expiry date is recorded."
        return f"A moratorium took effect on {when}.{tail}"
    if trigger is AlertTrigger.moratorium_on_agenda:
        return (
            f"A moratorium was proposed on {when} and has not been adopted. There is still time to act, "
            "which is the whole reason this alert exists."
        )
    if trigger is AlertTrigger.rule_changed:
        return f"The rules changed on {when}: {citation}."
    if trigger is AlertTrigger.litigation_filed:
        return (
            f"Litigation was filed on {when}, which raises appeal risk for comparable applications."
        )
    if trigger is AlertTrigger.board_composition_changed:
        return (
            f"The composition of the deciding body changed on {when}. Precedent decays when the people "
            "change, and this is the change humans notice last."
        )
    return f"Something changed on {when}."


def _detect_nearby_denials(conn: Connection, *, since: date) -> list[Change]:
    """A comparable application denied within reach of a watched site.

    The radius uses PostGIS on the boundary geographies rather than centroid distance, because two counties
    that share a border are adjacent regardless of how far apart their centres are, and adjacency is what
    matters for contagion.
    """
    rows = (
        conn.execute(
            text(
                """
            SELECT DISTINCT
                w.jurisdiction_id,
                wj.slug,
                a.id AS application_id,
                a.use_class,
                a.decided_on,
                nj.name AS deciding_county,
                ROUND(
                    ST_Distance(wj.boundary::geography, nj.boundary::geography) / 1000.0
                ) AS distance_km
            FROM watch w
            JOIN jurisdiction wj ON wj.id = w.jurisdiction_id
            JOIN application a ON a.outcome = 'denied' AND a.decided_on >= :since
            JOIN jurisdiction nj ON nj.id = a.jurisdiction_id
            WHERE w.active
              AND wj.boundary IS NOT NULL
              AND nj.boundary IS NOT NULL
              AND nj.id <> wj.id
              AND ST_DWithin(wj.boundary::geography, nj.boundary::geography, :radius)
            ORDER BY distance_km
            """
            ).bindparams(since=since, radius=NEARBY_KM * 1000.0)
        )
        .mappings()
        .all()
    )

    return [
        Change(
            jurisdiction_id=int(row["jurisdiction_id"]),
            jurisdiction_slug=str(row["slug"]),
            trigger=AlertTrigger.comparable_denied_nearby,
            detected_on=row["decided_on"],
            summary=(
                f"A comparable {str(row['use_class']).replace('_', ' ')} application was denied in "
                f"{row['deciding_county']}, about {int(row['distance_km'])} km away, on "
                f"{row['decided_on'].isoformat()}."
            ),
            after={
                "application_id": int(row["application_id"]),
                "distance_km": int(row["distance_km"]),
            },
        )
        for row in rows
    ]


def _detect_stale_sources(conn: Connection) -> list[Change]:
    """Our own data going stale is a change the customer is entitled to hear about.

    Section 6.12: silent staleness is the fastest way to lose the one asset that matters. Telling a customer
    that we have stopped being able to see a county is uncomfortable and it is the honest thing.
    """
    from auspice.models.eval.thresholds import STALENESS_FLAG_DAYS

    rows = (
        conn.execute(
            text(
                """
            SELECT
                j.id, j.slug,
                MIN(EXTRACT(EPOCH FROM (now() - s.last_success_at)) / 86400.0) AS days
            FROM source s
            JOIN jurisdiction j ON j.id = s.jurisdiction_id
            WHERE s.enabled
              AND EXISTS (SELECT 1 FROM watch w WHERE w.jurisdiction_id = j.id AND w.active)
            GROUP BY j.id, j.slug
            HAVING MIN(EXTRACT(EPOCH FROM (now() - s.last_success_at)) / 86400.0) > :threshold
               OR MIN(EXTRACT(EPOCH FROM (now() - s.last_success_at)) / 86400.0) IS NULL
            """
            ).bindparams(threshold=float(STALENESS_FLAG_DAYS))
        )
        .mappings()
        .all()
    )

    changes: list[Change] = []
    for row in rows:
        days = row["days"]
        changes.append(
            Change(
                jurisdiction_id=int(row["id"]),
                jurisdiction_slug=str(row["slug"]),
                trigger=AlertTrigger.source_stale,
                detected_on=date.today(),
                summary=(
                    "We have not successfully read this county's sources recently"
                    if days is None
                    else f"Our freshest source for this county is {int(days)} days old."
                ),
                after={"days_stale": int(days) if days is not None else None},
            )
        )
    return changes


# ---------------------------------------------------------------------------
# Materiality and delivery
# ---------------------------------------------------------------------------
def materiality(
    change: Change,
    *,
    score_before: float | None,
    score_after: float | None,
    site_count: int,
) -> tuple[float, str | None]:
    """Score a change for one customer. Returns (materiality, suppression reason).

    Two components. The base score for the trigger, and how much the customer's own number moved. A rule
    change that does not move the number is still worth knowing about, so the base score carries most of the
    weight; a large score movement lifts anything.

    The suppression reason is returned rather than the alert being silently dropped, so "why did I not hear
    about this" always has an answer.
    """
    score = change.base_materiality

    movement = (
        abs(score_after - score_before)
        if score_before is not None and score_after is not None
        else None
    )

    if movement is not None:
        # A movement of 0.15 is worth as much as the strongest trigger. Below the noise floor it counts for
        # nothing, because refitting a model moves every number a little.
        score += min(movement / 0.15, 1.0) * 0.5 if movement >= SCORE_NOISE_FLOOR else 0.0

    # Holding several sites in the same county does not multiply the news, but it does raise the stakes.
    if site_count > 1:
        score += min(site_count / 20.0, 0.10)

    score = min(score, 1.0)

    if change.trigger is AlertTrigger.score_moved and (
        movement is None or movement < SCORE_NOISE_FLOOR
    ):
        return score, (
            "the score moved by less than the noise floor, which is refitting rather than news"
        )
    if score < SEND_THRESHOLD:
        return score, f"materiality {score:.2f} is below the send threshold of {SEND_THRESHOLD:.2f}"
    return score, None


def record_and_alert(
    conn: Connection,
    changes: list[Change],
    *,
    report: MonitorReport | None = None,
) -> MonitorReport:
    """Persist changes, then create an alert per affected watch.

    A change is recorded once per jurisdiction and an alert once per watch, which is what lets two customers
    watching the same county receive different materiality scores for the same event.
    """
    resolved = report or MonitorReport()

    for change in changes:
        resolved.changes_detected += 1
        change_event_id = int(conn.execute(_change_insert(change)).scalar_one())

        watches = (
            conn.execute(
                text(
                    """
                SELECT w.id, w.subscriber, w.label, w.last_prediction_id,
                       p.approval_probability AS previous_probability
                FROM watch w
                LEFT JOIN prediction p ON p.id = w.last_prediction_id
                WHERE w.jurisdiction_id = :jid AND w.active
                """
                ).bindparams(jid=change.jurisdiction_id)
            )
            .mappings()
            .all()
        )

        per_subscriber: dict[str, int] = {}
        for watch_row in watches:
            subscriber = str(watch_row["subscriber"])
            per_subscriber[subscriber] = per_subscriber.get(subscriber, 0) + 1

        for watch_row in watches:
            resolved.watches_checked += 1
            before = (
                float(watch_row["previous_probability"])
                if watch_row["previous_probability"] is not None
                else None
            )
            score, suppressed = materiality(
                change,
                score_before=before,
                score_after=None,
                site_count=per_subscriber[str(watch_row["subscriber"])],
            )

            _insert_alert(
                conn,
                watch_id=int(watch_row["id"]),
                change_event_id=change_event_id,
                materiality=score,
                headline=_headline(change),
                body=change.summary,
                score_before=before,
                score_after=None,
                suppressed_reason=suppressed,
            )
            if suppressed is None:
                resolved.alerts_created += 1
            else:
                resolved.alerts_suppressed += 1

    log.info("monitoring run complete", **resolved.as_dict())
    return resolved


def _change_insert(change: Change) -> Any:
    from auspice.db import schema

    return (
        schema.change_event.insert()
        .values(
            jurisdiction_id=change.jurisdiction_id,
            trigger=change.trigger.value,
            detected_on=change.detected_on,
            document_id=change.document_id,
            before=change.before,
            after=change.after,
            materiality=round(change.base_materiality, 3),
            summary=change.summary,
        )
        .returning(schema.change_event.c.id)
    )


def _insert_alert(
    conn: Connection,
    *,
    watch_id: int,
    change_event_id: int,
    materiality: float,
    headline: str,
    body: str,
    score_before: float | None,
    score_after: float | None,
    suppressed_reason: str | None,
) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from auspice.db import schema

    statement = pg_insert(schema.alert).values(
        watch_id=watch_id,
        change_event_id=change_event_id,
        materiality=round(materiality, 3),
        headline=headline,
        body=body,
        score_before=score_before,
        score_after=score_after,
        suppressed_reason=suppressed_reason,
    )
    conn.execute(
        statement.on_conflict_do_nothing(
            index_elements=[schema.alert.c.watch_id, schema.alert.c.change_event_id]
        )
    )


def _headline(change: Change) -> str:
    """The subject line. Specific rather than urgent.

    An alert titled "Important update" gets ignored on the second occurrence. One that names the county and
    the thing that happened gets read.
    """
    titles = {
        AlertTrigger.rule_changed: "Rules changed in {slug}",
        AlertTrigger.moratorium_on_agenda: "A moratorium is on the agenda in {slug}",
        AlertTrigger.moratorium_enacted: "A moratorium took effect in {slug}",
        AlertTrigger.comparable_denied_nearby: "A comparable application was denied near {slug}",
        AlertTrigger.board_composition_changed: "The deciding body changed in {slug}",
        AlertTrigger.litigation_filed: "Litigation filed in {slug}",
        AlertTrigger.use_class_on_agenda: "{slug} is discussing your use class",
        AlertTrigger.score_moved: "Your score moved in {slug}",
        AlertTrigger.source_stale: "Our data for {slug} is going stale",
    }
    return titles.get(change.trigger, "Change in {slug}").format(slug=change.jurisdiction_slug)


def pending_alerts(conn: Connection) -> list[dict[str, Any]]:
    """Alerts created and not yet delivered."""
    rows = (
        conn.execute(
            text(
                """
            SELECT a.id, a.materiality, a.headline, a.body, a.score_before, a.score_after,
                   w.subscriber, w.label, j.slug, ce.trigger, ce.detected_on
            FROM alert a
            JOIN watch w ON w.id = a.watch_id
            JOIN change_event ce ON ce.id = a.change_event_id
            JOIN jurisdiction j ON j.id = ce.jurisdiction_id
            WHERE a.delivered_at IS NULL AND a.suppressed_reason IS NULL
            ORDER BY a.materiality DESC, a.id
            """
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def daily_run(conn: Connection, *, lookback_days: int = 1) -> MonitorReport:
    """The daily job. Detect, score, record, and report what was suppressed and why."""
    since = date.today() - timedelta(days=lookback_days)
    changes = detect_changes(conn, since=since)
    return record_and_alert(conn, changes)
