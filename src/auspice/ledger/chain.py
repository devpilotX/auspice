"""The prediction ledger. Section 8.2.

This is the moat. Everything else is execution.

The mechanism, verbatim from the specification:

1. Identify pending public applications, filed and not yet decided.
2. Score them before any decision exists.
3. Publish the record and the SHA-256 of it to a public, append only ledger.
4. Optionally anchor the daily ledger hash to an independent timestamping authority.
5. When reality resolves, grade it publicly. No edits, no deletions, no retroactive changes.

The append only property is not a policy here, it is a structure. Each entry commits
``sha256(prev_hash || payload_hash)``, so altering any historical payload changes every entry after it
and ``verify`` reports the exact sequence number where the chain breaks. That is what makes the record
worth anything: a competitor cannot buy twelve months of correct calls, and we cannot quietly improve
them either.

The specification rejects a blockchain and it is right to. A published hash chain plus an optional
third party timestamp achieves the same credibility with none of the cost.

Grading is separate from publishing, and grading writes to fields the payload hash does not cover. That
is deliberate: the outcome was not known when the prediction was made, so folding it into the committed
payload would be a retroactive change to the thing being committed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.domain import APPROVAL_OUTCOMES, Outcome
from auspice.errors import LedgerTamperError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="ledger")

GENESIS_HASH = "0" * 64


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic serialisation.

    Sorted keys, no insignificant whitespace, ASCII escaped. Anyone recomputing a hash from the
    published payload has to get the same bytes we did, so the encoding is pinned rather than left to a
    library default that could change.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    )


def hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def link(prev_hash: str, payload_hash: str) -> str:
    """sha256(prev_hash || payload_hash), over the hex strings."""
    return hashlib.sha256((prev_hash + payload_hash).encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    seq: int
    prediction_id: int
    published_at: datetime
    payload: dict[str, Any]
    payload_hash: str
    prev_hash: str
    entry_hash: str
    anchor_reference: str | None = None
    resolved_outcome: str | None = None
    resolved_on: date | None = None
    grading: dict[str, Any] | None = None
    miss_note: str | None = None

    @property
    def resolved(self) -> bool:
        return self.resolved_outcome is not None


@dataclass(slots=True)
class VerificationReport:
    entries: int = 0
    ok: bool = True
    broken_at: int | None = None
    reason: str | None = None
    head: str | None = None
    daily_roots: dict[str, str] = field(default_factory=dict)
    scope: str = "full"
    """Which check produced this: ``full`` for the whole chain, ``head`` for the constant cost probe.

    Carried on the report rather than left to the caller to remember, because the two answer different
    questions and a shallow ok is not a full ok. A consumer that publishes an accuracy claim needs the
    full walk; a liveness probe does not. Without this field the difference is invisible at the point it
    matters, which is where someone would quote it.
    """

    def as_dict(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "ok": self.ok,
            "broken_at": self.broken_at,
            "reason": self.reason,
            "head": self.head,
            "daily_roots": self.daily_roots,
            "scope": self.scope,
        }


def head(conn: Connection) -> tuple[int, str]:
    """The last sequence number and entry hash. (0, genesis) on an empty ledger."""
    row = conn.execute(
        select(schema.ledger_entry.c.seq, schema.ledger_entry.c.entry_hash)
        .order_by(schema.ledger_entry.c.seq.desc())
        .limit(1)
    ).first()
    if row is None:
        return 0, GENESIS_HASH
    return int(row.seq), str(row.entry_hash)


def publish(conn: Connection, *, prediction_id: int, payload: dict[str, Any]) -> LedgerEntry:
    """Append one prediction. Raises if that prediction is already published.

    Refusing the duplicate rather than updating it is the whole point. A prediction can be published
    once and never revised, and section 8.9 says never quietly revise a published prediction.
    """
    existing = conn.execute(
        select(schema.ledger_entry.c.seq).where(
            schema.ledger_entry.c.prediction_id == prediction_id
        )
    ).first()
    if existing is not None:
        raise ValueError(
            f"prediction {prediction_id} is already in the ledger at sequence {existing.seq}. "
            "The ledger is append only: publish a new prediction instead of revising this one."
        )

    _, prev_hash = head(conn)
    payload_hash = hash_payload(payload)
    entry_hash = link(prev_hash, payload_hash)

    seq = int(
        conn.execute(
            schema.ledger_entry.insert()
            .values(
                prediction_id=prediction_id,
                payload=payload,
                payload_hash=payload_hash,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            .returning(schema.ledger_entry.c.seq)
        ).scalar_one()
    )

    log.info("published", seq=seq, prediction_id=prediction_id, entry_hash=entry_hash[:16])
    return LedgerEntry(
        seq=seq,
        prediction_id=prediction_id,
        published_at=datetime.now(UTC),
        payload=payload,
        payload_hash=payload_hash,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )


def _completeness_breach(conn: Connection, highest_present: int) -> tuple[int, str] | None:
    """Detect entries deleted from the end of the chain. Constant cost, regardless of ledger size.

    Everything the hash walk proves is that the entries present are internally consistent and correctly
    chained, which is not the same as proving none are missing.

    A deletion in the middle breaks the next entry's ``prev_hash``, so the walk already catches it. A
    deletion at the tail is not caught: entries 1 to 3 of an original 1 to 4 form a shorter chain that
    verifies perfectly. That is the deletion someone would actually make, because the most recent
    predictions are the ones that have just been proved wrong.

    The sequence generator is the check. Postgres only advances it, so it remembers the highest sequence
    ever issued even after the row is gone. If it has issued more than the table holds, entries were
    removed from the end.

    This is evidence, not proof: someone with the right to run ``setval`` can rewind the counter, and
    someone who can do that can do anything. Detecting the deletion is what matters, and the external
    anchor in ``daily_root`` is what makes it undeniable.

    Extracted from ``verify`` so that the cheap head check and the full walk apply the identical rule. A
    second copy of this would be a second chance to get it wrong, and the cheap path exists precisely to
    be run often, which makes it the one more likely to be trusted.

    Returns ``(broken_at, reason)`` when entries are missing, or None when the tail is intact.
    """
    issued = (
        conn.execute(text("SELECT last_value, is_called FROM ledger_entry_seq_seq"))
        .mappings()
        .first()
    )
    if issued is None or not issued["is_called"]:
        return None

    highest_issued = int(issued["last_value"])
    if highest_present >= highest_issued:
        return None

    missing = highest_issued - highest_present
    return (
        highest_present + 1,
        (
            f"the ledger ends at sequence {highest_present}, but sequence {highest_issued} has been "
            f"issued. {missing} entry or entries were deleted from the end of the chain."
        ),
    )


def verify_head(conn: Connection) -> VerificationReport:
    """A constant cost integrity check. What a health probe can afford to run on every request.

    ``verify`` reads every row and rehashes every payload, so its cost grows with the ledger. That is
    correct for publishing and for the accuracy page, and wrong for a liveness probe: the health endpoint
    is unauthenticated and deliberately exempt from rate limiting, so an O(entries) body there means the
    denial of service surface grows in exact proportion to the one metric the specification says must
    never stall. The better the company does at publishing predictions, the cheaper it becomes to hurt.

    What this catches: a tail deletion, by the same rule the full walk uses, and corruption of the most
    recent entry, by rehashing it. Both are constant cost.

    What it does not catch, stated plainly rather than left to be assumed: tampering in the middle of the
    chain. Only the full walk finds that, and it still runs at startup through ``require_intact``, before
    every publish, and behind the rate limiter on the accuracy page. This is a cheap smoke test, not a
    replacement, and ``scope`` on the report says which one produced it.
    """
    report = VerificationReport(scope="head")

    row = conn.execute(
        select(
            schema.ledger_entry.c.seq,
            schema.ledger_entry.c.payload,
            schema.ledger_entry.c.payload_hash,
            schema.ledger_entry.c.prev_hash,
            schema.ledger_entry.c.entry_hash,
        )
        .order_by(schema.ledger_entry.c.seq.desc())
        .limit(1)
    ).first()

    if row is None:
        # An empty ledger is intact. It is also the state a tail deletion of everything would leave, which
        # is why the completeness check still runs against a highest_present of zero.
        breach = _completeness_breach(conn, 0)
        if breach is not None:
            report.ok, report.broken_at, report.reason = False, breach[0], breach[1]
        return report

    report.entries = int(row.seq)
    report.head = str(row.entry_hash)

    if hash_payload(dict(row.payload)) != row.payload_hash:
        report.ok = False
        report.broken_at = int(row.seq)
        report.reason = "the stored payload no longer hashes to its recorded payload hash"
        return report

    if link(str(row.prev_hash), str(row.payload_hash)) != row.entry_hash:
        report.ok = False
        report.broken_at = int(row.seq)
        report.reason = "entry_hash is not the link of prev_hash and payload_hash"
        return report

    breach = _completeness_breach(conn, int(row.seq))
    if breach is not None:
        report.ok, report.broken_at, report.reason = False, breach[0], breach[1]

    return report


def verify(conn: Connection) -> VerificationReport:
    """Recompute the whole chain. Reports the first sequence number that does not check out.

    Three things are checked per entry: the payload still hashes to its recorded ``payload_hash``, the
    recorded ``prev_hash`` matches the previous entry's ``entry_hash``, and the ``entry_hash`` is the
    correct link of the two. Any one of them failing means the ledger was edited.
    """
    report = VerificationReport()
    rows = conn.execute(
        select(
            schema.ledger_entry.c.seq,
            schema.ledger_entry.c.payload,
            schema.ledger_entry.c.payload_hash,
            schema.ledger_entry.c.prev_hash,
            schema.ledger_entry.c.entry_hash,
            schema.ledger_entry.c.published_at,
        ).order_by(schema.ledger_entry.c.seq)
    ).all()

    expected_prev = GENESIS_HASH
    for row in rows:
        report.entries += 1

        recomputed_payload = hash_payload(dict(row.payload))
        if recomputed_payload != row.payload_hash:
            report.ok = False
            report.broken_at = int(row.seq)
            report.reason = "the stored payload no longer hashes to its recorded payload hash"
            return report

        if row.prev_hash != expected_prev:
            report.ok = False
            report.broken_at = int(row.seq)
            report.reason = (
                f"prev_hash is {row.prev_hash[:16]} but the previous entry hashes to "
                f"{expected_prev[:16]}"
            )
            return report

        recomputed_entry = link(row.prev_hash, row.payload_hash)
        if recomputed_entry != row.entry_hash:
            report.ok = False
            report.broken_at = int(row.seq)
            report.reason = "entry_hash is not the link of prev_hash and payload_hash"
            return report

        expected_prev = str(row.entry_hash)
        day = row.published_at.date().isoformat()
        report.daily_roots[day] = str(row.entry_hash)

    report.head = expected_prev if rows else None

    # Completeness. See _completeness_breach for why the hash walk above is not sufficient on its own and
    # why the sequence generator is the check. Shared with verify_head so the two cannot diverge.
    breach = _completeness_breach(conn, int(rows[-1].seq) if rows else 0)
    if breach is not None:
        report.ok = False
        report.broken_at = breach[0]
        report.reason = breach[1]
        return report

    return report


def require_intact(conn: Connection) -> VerificationReport:
    """Verify, and raise if the chain is broken.

    Called before anything is published and before the accuracy page is rendered. Publishing on top of
    a broken chain would extend a record that cannot be trusted, and serving an accuracy page from one
    would make a public claim on the same basis.
    """
    report = verify(conn)
    if not report.ok:
        raise LedgerTamperError(
            f"the ledger does not verify at sequence {report.broken_at}: {report.reason}"
        )
    return report


def daily_root(conn: Connection, day: date) -> str | None:
    """The entry hash at the end of ``day``. This is the value worth anchoring externally.

    A Merkle root over the day's entries would be equivalent here, and the running chain head is
    strictly stronger: it commits every entry ever published, not just the day's.
    """
    row = conn.execute(
        select(schema.ledger_entry.c.entry_hash)
        .where(func.date(schema.ledger_entry.c.published_at) <= day)
        .order_by(schema.ledger_entry.c.seq.desc())
        .limit(1)
    ).first()
    return str(row.entry_hash) if row else None


def grade(
    conn: Connection,
    *,
    seq: int,
    outcome: Outcome,
    resolved_on: date,
    miss_note: str | None = None,
) -> dict[str, Any]:
    """Record what actually happened, and score the call.

    Writes to ``resolved_*`` and ``grading`` only. The committed payload is never touched, because the
    outcome was not known when the prediction was made and folding it in would be a retroactive change
    to the thing being committed.

    ``miss_note`` is the section 8.5 public misses log. A wrong call gets a written explanation of what
    the model missed, published as it stands. Nobody who is hiding results volunteers their failures,
    which is exactly why publishing them is credible.
    """
    row = conn.execute(
        select(
            schema.ledger_entry.c.seq,
            schema.ledger_entry.c.payload,
            schema.ledger_entry.c.resolved_outcome,
        ).where(schema.ledger_entry.c.seq == seq)
    ).first()
    if row is None:
        raise ValueError(f"no ledger entry at sequence {seq}")
    if row.resolved_outcome is not None:
        raise ValueError(
            f"sequence {seq} is already graded as {row.resolved_outcome}. Grading happens once."
        )

    payload = dict(row.payload)
    observed = 1.0 if outcome in APPROVAL_OUTCOMES else 0.0
    predicted = payload.get("approval_probability")
    abstained = bool(payload.get("abstained"))

    grading: dict[str, Any] = {
        "observed": observed,
        "abstained": abstained,
        "graded_at": datetime.now(UTC).isoformat(),
    }

    if abstained or predicted is None:
        grading["note"] = (
            "abstained, so this entry contributes to the abstention record and not to the Brier score"
        )
    else:
        predicted = float(predicted)
        grading["predicted"] = predicted
        grading["brier_contribution"] = round((predicted - observed) ** 2, 6)
        grading["direction_correct"] = bool((predicted >= 0.5) == (observed == 1.0))
        interval = payload.get("credible_interval_80")
        if interval:
            low, high = float(interval[0]), float(interval[1])
            # A single binary outcome is not "inside" a probability interval. What can be said is
            # whether the interval left room for what happened, and that is what is recorded.
            grading["interval_admitted_outcome"] = bool(
                high >= 0.5 if observed == 1.0 else low <= 0.5
            )

        months = payload.get("time_to_decision_months")
        if months and payload.get("generated_at"):
            generated = datetime.fromisoformat(str(payload["generated_at"])).date()
            actual_months = (resolved_on.toordinal() - generated.toordinal()) / 30.44
            grading["actual_months_from_prediction"] = round(actual_months, 2)
            grading["months_inside_interval"] = bool(
                float(months["p10"]) <= actual_months <= float(months["p90"])
            )

    conn.execute(
        update(schema.ledger_entry)
        .where(schema.ledger_entry.c.seq == seq)
        .values(
            resolved_outcome=outcome.value,
            resolved_on=resolved_on,
            resolved_at=datetime.now(UTC),
            grading=grading,
            miss_note=miss_note,
        )
    )

    log.info("graded", seq=seq, outcome=outcome.value, brier=grading.get("brier_contribution"))
    return grading


def public_record(conn: Connection) -> dict[str, Any]:
    """Everything the public accuracy page shows. No login, no filtering, no omissions.

    Section 5.3: the single most important page on the website is public and free, and it is
    simultaneously the product proof, the marketing engine and the moat.
    """
    report = verify(conn)

    rows = conn.execute(
        select(
            schema.ledger_entry.c.seq,
            schema.ledger_entry.c.published_at,
            schema.ledger_entry.c.payload,
            schema.ledger_entry.c.payload_hash,
            schema.ledger_entry.c.entry_hash,
            schema.ledger_entry.c.resolved_outcome,
            schema.ledger_entry.c.resolved_on,
            schema.ledger_entry.c.grading,
            schema.ledger_entry.c.miss_note,
        ).order_by(schema.ledger_entry.c.seq)
    ).all()

    resolved = [r for r in rows if r.resolved_outcome is not None]
    answered = [
        r for r in resolved if r.grading and r.grading.get("brier_contribution") is not None
    ]

    brier = (
        round(sum(float(r.grading["brier_contribution"]) for r in answered) / len(answered), 5)
        if answered
        else None
    )

    return {
        "chain": report.as_dict(),
        "published": len(rows),
        "resolved": len(resolved),
        "pending": len(rows) - len(resolved),
        "answered": len(answered),
        "abstained": len(resolved) - len(answered),
        "brier_score": brier,
        "misses": [
            {
                "seq": int(r.seq),
                "public_id": r.payload.get("public_id"),
                "jurisdiction": r.payload.get("jurisdiction"),
                "predicted": r.payload.get("approval_probability"),
                "outcome": r.resolved_outcome,
                "note": r.miss_note,
            }
            for r in answered
            if r.grading and not r.grading.get("direction_correct", True)
        ],
        "entries": [
            {
                "seq": int(r.seq),
                "published_at": r.published_at.isoformat(),
                "payload": r.payload,
                "payload_hash": r.payload_hash,
                "entry_hash": r.entry_hash,
                "resolved_outcome": r.resolved_outcome,
                "resolved_on": r.resolved_on.isoformat() if r.resolved_on else None,
                "grading": r.grading,
                "miss_note": r.miss_note,
            }
            for r in rows
        ],
    }


def export_jsonl(conn: Connection) -> str:
    """The ledger as newline delimited JSON, for anyone who wants to verify it themselves.

    Published alongside the accuracy page. A record that can only be checked through our own interface
    is not a public record.
    """
    rows = conn.execute(
        select(
            schema.ledger_entry.c.seq,
            schema.ledger_entry.c.published_at,
            schema.ledger_entry.c.payload,
            schema.ledger_entry.c.payload_hash,
            schema.ledger_entry.c.prev_hash,
            schema.ledger_entry.c.entry_hash,
            schema.ledger_entry.c.resolved_outcome,
            schema.ledger_entry.c.resolved_on,
        ).order_by(schema.ledger_entry.c.seq)
    ).all()

    lines = [
        canonical_json(
            {
                "seq": int(r.seq),
                "published_at": r.published_at.isoformat(),
                "payload": dict(r.payload),
                "payload_hash": r.payload_hash,
                "prev_hash": r.prev_hash,
                "entry_hash": r.entry_hash,
                "resolved_outcome": r.resolved_outcome,
                "resolved_on": r.resolved_on.isoformat() if r.resolved_on else None,
            }
        )
        for r in rows
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def unresolved_older_than(conn: Connection, *, days: int) -> list[dict[str, Any]]:
    """Predictions still waiting on an outcome. The queue the grading job works from."""
    rows = (
        conn.execute(
            text(
                """
            SELECT le.seq, le.published_at, le.payload, p.application_id
            FROM ledger_entry le
            JOIN prediction p ON p.id = le.prediction_id
            WHERE le.resolved_at IS NULL
              AND le.published_at < now() - make_interval(days => :days)
            ORDER BY le.seq
            """
            ).bindparams(days=days)
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
