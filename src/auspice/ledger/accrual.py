"""Making the ledger accrue.

The ledger holds published predictions. `grade` records what actually happened against one of them, by
sequence number, supplied by hand. Nothing connected the two ends: an application in the graph could reach
a terminal outcome and the prediction made about it would sit unresolved forever, so the accuracy page
would keep saying nothing has resolved while the answer was already in the database.

That is worse than an empty accuracy record. An empty record is honest about being empty. A record that
stays empty while outcomes arrive is a record that has quietly stopped working, and nobody notices, because
the symptom is the same in both cases.

`reconcile` closes it. Every published prediction carries `application_id`. Any whose application now has a
terminal outcome is gradeable, and grading is what turns a published guess into a measured one.

## Three properties that matter more than the mechanism

**It grades once.** `grade` refuses a second grading of the same sequence, and this respects that rather
than working around it. A prediction regraded after the fact is a prediction whose score moved without the
outcome changing.

**It never invents an outcome.** An application still pending, continued or tabled is not resolved, and
reconciliation skips it. A withdrawal is terminal and is graded as one, because the withdrawal rate is a
real feature measuring hidden denials, not a missing value.

**A miss gets a written note or none at all.** Section 8.5 publishes the misses log. This writes a factual
note naming the predicted probability and the observed outcome, because a generated explanation of what
the model missed would be a guess presented as analysis. The human explanation is added by editing the
entry, and `docs/METHODOLOGY.md` says the note is written by a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from auspice.domain import APPROVAL_OUTCOMES, TERMINAL_OUTCOMES, Outcome
from auspice.logging import get_logger

log = get_logger(__name__, _stage="ledger")

# A prediction whose observed outcome contradicts it this strongly is a miss worth a note. At 0.5 nothing
# is a miss, because a coin flip cannot be wrong, so the threshold has to sit away from it.
MISS_THRESHOLD = 0.65


_RESOLVABLE_SQL = text(
    """
    SELECT
        le.seq,
        le.published_at,
        le.payload,
        p.public_id,
        p.application_id,
        p.approval_probability,
        p.abstained,
        a.outcome,
        a.decided_on,
        a.external_id,
        j.slug
    FROM ledger_entry le
    JOIN prediction p ON p.id = le.prediction_id
    JOIN application a ON a.id = p.application_id
    JOIN jurisdiction j ON j.id = a.jurisdiction_id
    WHERE le.resolved_at IS NULL
      AND a.outcome = ANY(:terminal)
      AND a.decided_on IS NOT NULL
    ORDER BY le.seq
    """
)


@dataclass(frozen=True, slots=True)
class Resolvable:
    """A published prediction whose application has since reached a terminal outcome."""

    seq: int
    public_id: str
    application_id: int
    jurisdiction: str
    external_id: str | None
    outcome: Outcome
    decided_on: date
    predicted: float | None
    abstained: bool

    @property
    def observed(self) -> float:
        return 1.0 if self.outcome in APPROVAL_OUTCOMES else 0.0

    @property
    def is_miss(self) -> bool:
        """Confidently wrong, rather than merely wrong.

        An abstention is never a miss. Refusing to answer is a successful response, and counting it as an
        error would push the system toward answering when it should not, which is the incentive this whole
        design exists to avoid.
        """
        if self.abstained or self.predicted is None:
            return False
        return abs(self.predicted - self.observed) > MISS_THRESHOLD

    def miss_note(self) -> str | None:
        """A factual note, or none.

        Deliberately not an explanation. A generated account of what the model missed would be a guess
        presented as analysis, on the one page whose value is that it is not doing that. This states the
        numbers and says a person has to write the rest.
        """
        if not self.is_miss or self.predicted is None:
            return None
        direction = "approval" if self.observed == 1.0 else "denial"
        return (
            f"Predicted {self.predicted:.0%} approval and the body recorded a {direction} on "
            f"{self.decided_on.isoformat()}. Recorded automatically on reconciliation. The explanation "
            "of what the model missed is written by a person and is not yet added."
        )


@dataclass(slots=True)
class ReconcileReport:
    considered: int = 0
    graded: int = 0
    misses: int = 0
    skipped: int = 0
    dry_run: bool = False
    rows: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "graded": self.graded,
            "misses": self.misses,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
        }


def resolvable(conn: Connection) -> list[Resolvable]:
    """Published predictions whose application has a terminal outcome and a decision date.

    Both conditions are required. A terminal outcome with no date cannot be graded, because the ledger
    records when the answer became known and inventing that date would falsify the timeline the survival
    model is measured against.
    """
    rows = conn.execute(
        _RESOLVABLE_SQL, {"terminal": [o.value for o in TERMINAL_OUTCOMES]}
    ).mappings()
    out: list[Resolvable] = []
    for row in rows:
        out.append(
            Resolvable(
                seq=int(row["seq"]),
                public_id=str(row["public_id"]),
                application_id=int(row["application_id"]),
                jurisdiction=str(row["slug"]),
                external_id=row["external_id"],
                outcome=Outcome(row["outcome"]),
                decided_on=row["decided_on"],
                predicted=float(row["approval_probability"])
                if row["approval_probability"] is not None
                else None,
                abstained=bool(row["abstained"]),
            )
        )
    return out


def reconcile(
    conn: Connection, *, dry_run: bool = False, limit: int | None = None
) -> ReconcileReport:
    """Grade every published prediction whose application has since resolved.

    Failures are isolated per entry. One entry that cannot be graded, because it was graded already or
    because its payload is malformed, must not stop the rest: an accuracy record that stops accruing
    because of one bad row is an accuracy record that is quietly wrong.
    """
    from auspice.ledger import chain

    report = ReconcileReport(dry_run=dry_run)
    queue = resolvable(conn)
    if limit is not None:
        queue = queue[:limit]
    report.considered = len(queue)

    for item in queue:
        row = {
            "seq": item.seq,
            "public_id": item.public_id,
            "jurisdiction": item.jurisdiction,
            "case": item.external_id,
            "outcome": item.outcome.value,
            "predicted": item.predicted,
            "miss": item.is_miss,
        }
        if dry_run:
            report.rows.append(row)
            continue

        try:
            chain.grade(
                conn,
                seq=item.seq,
                outcome=item.outcome,
                resolved_on=item.decided_on,
                miss_note=item.miss_note(),
            )
        except ValueError as exc:
            # Already graded, or no such entry. Both are conditions to report rather than to raise on,
            # because the queue is derived and can lag a concurrent manual grading.
            report.skipped += 1
            report.failures.append({"seq": item.seq, "reason": str(exc)[:200]})
            continue

        report.graded += 1
        if item.is_miss:
            report.misses += 1
        report.rows.append(row)

    log.info(
        "ledger reconciled",
        considered=report.considered,
        graded=report.graded,
        misses=report.misses,
        skipped=report.skipped,
        dry_run=dry_run,
    )
    return report


def accrual_status(conn: Connection) -> dict[str, Any]:
    """Whether the ledger is actually accruing, which is a different question from whether it is intact.

    ``gradeable_now`` is the number that matters. Anything above zero means an outcome is sitting in the
    graph unrecorded on the public record, and the accuracy page is understating what is known.
    """
    row = (
        conn.execute(
            text(
                """
            SELECT
                count(*)                                              AS published,
                count(*) FILTER (WHERE resolved_at IS NOT NULL)        AS resolved,
                count(*) FILTER (WHERE resolved_at IS NULL)            AS pending,
                min(published_at) FILTER (WHERE resolved_at IS NULL)   AS oldest_pending,
                max(published_at)                                      AS latest_published
            FROM ledger_entry
            """
            )
        )
        .mappings()
        .one()
    )
    gradeable = len(resolvable(conn))
    return {
        "published": int(row["published"]),
        "resolved": int(row["resolved"]),
        "pending": int(row["pending"]),
        "gradeable_now": gradeable,
        "oldest_pending": row["oldest_pending"].date().isoformat()
        if row["oldest_pending"]
        else None,
        "latest_published": row["latest_published"].date().isoformat()
        if row["latest_published"]
        else None,
    }
