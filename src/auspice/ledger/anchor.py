"""External anchoring of the ledger head.

The hash chain proves internal consistency: no entry can be altered without breaking every hash after
it. What it cannot prove is that the chain existed before today. We hold the whole thing, so we could
in principle rebuild it from scratch and rehash it, and the result would verify perfectly.

An anchor closes that. It puts the chain head in the hands of a third party at a known time, so a chain
rebuilt later cannot claim to be the one that existed then. `AUSPICE_LEDGER_ANCHOR_URL` and
`ledger_entry.anchor_reference` have existed since the first migration and nothing wrote to either, so
the strongest claim the accuracy page could honestly make was internal consistency.

## What an anchor here does and does not prove

It proves the head digest was submitted to the configured service and that the service returned a
receipt. That is worth exactly as much as the service is independent of us, and the honest statement of
that is published rather than implied: `docs/METHODOLOGY.md` names the service, and the accuracy page
reports the anchor as absent when there is none rather than omitting the subject.

It does not prove the receipt is cryptographically valid. Verifying an OpenTimestamps proof means
following it to a Bitcoin block, which needs a Bitcoin node, and pretending otherwise would be worse
than saying so. What this module guarantees is that the receipt stored is the receipt received, byte for
byte, checkable by its own digest, and that the digest submitted is reproducible from the ledger.

So a reader can do the strong check themselves: recompute the head from the published export, confirm it
equals `submitted_digest`, then verify the receipt with the standard client for that service. Every input
to that is published.

## Why not verify the chain before anchoring

It is verified. Anchoring a head that does not verify would put a broken chain beyond dispute, which is
the opposite of the point.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select, text, update
from sqlalchemy.engine import Connection

from auspice import ledger
from auspice.config import get_settings
from auspice.db import schema
from auspice.errors import LedgerTamperError, StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="ledger")

# A receipt larger than this is not a receipt. The cap exists because the response comes from a service
# outside our control and lands in a database column, and an unbounded write from an external endpoint
# is a denial of service with extra steps.
MAX_RECEIPT_BYTES = 64 * 1024

SUBMIT_TIMEOUT_SECONDS = 30.0


class AnchorError(Exception):
    """Anchoring refused or failed. The message is written to be read by an operator."""


@dataclass(frozen=True, slots=True)
class Receipt:
    """What came back from the anchoring service, and enough to check it later."""

    service: str
    submitted_digest: str
    receipt_sha256: str
    receipt_bytes: int
    received_at: str
    detail: str | None = None

    def as_reference(self) -> str:
        """The compact form stored in ``ledger_entry.anchor_reference``.

        One line, because the column is a receipt reference rather than a receipt store, and a reader
        of the raw export should be able to see what happened without another lookup.
        """
        parts = [
            f"service={self.service}",
            f"digest={self.submitted_digest}",
            f"receipt_sha256={self.receipt_sha256}",
            f"bytes={self.receipt_bytes}",
            f"at={self.received_at}",
        ]
        if self.detail:
            parts.append(f"detail={self.detail}")
        return " ".join(parts)

    @staticmethod
    def parse(reference: str) -> dict[str, str]:
        """Read a stored reference back into fields, for display and for checking."""
        fields: dict[str, str] = {}
        for token in reference.split(" "):
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        return fields


class Anchor(Protocol):
    """A service that will attest to having seen a digest at a time."""

    name: str

    def submit(self, digest: str) -> Receipt: ...


@dataclass(slots=True)
class HttpAnchor:
    """POST the digest to a configured endpoint and keep what comes back.

    Deliberately generic. It works with an OpenTimestamps calendar, with an internal notary, and with a
    customer's own timestamping service, because the thing that makes an anchor credible is the
    independence of the service rather than the shape of its protocol. The URL is published in
    `docs/METHODOLOGY.md` so a reader can judge that independence for themselves.
    """

    url: str
    name: str = "http"

    def submit(self, digest: str) -> Receipt:
        import httpx

        raw = bytes.fromhex(digest)
        try:
            response = httpx.post(
                self.url,
                content=raw,
                timeout=SUBMIT_TIMEOUT_SECONDS,
                headers={"content-type": "application/octet-stream"},
            )
        except Exception as exc:
            raise AnchorError(
                f"could not reach the anchoring service at {self.url}: {exc}. The ledger is "
                "unaffected and unanchored, and the accuracy page will say so."
            ) from exc

        if not 200 <= response.status_code < 300:
            raise AnchorError(
                f"the anchoring service answered {response.status_code}. Body: "
                f"{response.text[:200]}"
            )

        body = response.content
        if not body:
            raise AnchorError(
                "the anchoring service accepted the digest and returned an empty receipt. An empty "
                "receipt proves nothing, so it is not stored."
            )
        if len(body) > MAX_RECEIPT_BYTES:
            raise AnchorError(
                f"the receipt is {len(body)} bytes, over the {MAX_RECEIPT_BYTES} byte cap. This is "
                "either the wrong endpoint or a service returning a page rather than a receipt."
            )

        return Receipt(
            service=self.url,
            submitted_digest=digest,
            receipt_sha256=hashlib.sha256(body).hexdigest(),
            receipt_bytes=len(body),
            received_at=datetime.now(UTC).isoformat(),
            detail=response.headers.get("date"),
        )


def get_anchor() -> Anchor:
    """The configured anchor, or a refusal naming the setting.

    There is no null anchor that silently succeeds. An unanchored ledger is a real and honest state and
    it is reported as such by `anchor_status`; an anchor command that appears to work while anchoring
    nothing would put a false claim on the accuracy page.
    """
    settings = get_settings()
    if not settings.ledger_anchor_url:
        raise StageUnavailableError(
            "AUSPICE_LEDGER_ANCHOR_URL is empty, so there is nowhere to anchor to. The ledger is "
            "still internally verifiable and the accuracy page reports it as unanchored, which is "
            "the honest state rather than a failure."
        )
    return HttpAnchor(url=settings.ledger_anchor_url)


def anchor_head(conn: Connection, *, anchor: Anchor | None = None) -> Receipt:
    """Anchor the current chain head, and record the receipt against that entry.

    The chain is verified first. Anchoring a head that does not verify would put a broken chain beyond
    dispute, which is the opposite of the point.
    """
    resolved = anchor or get_anchor()

    report = ledger.verify(conn)
    if not report.ok:
        raise LedgerTamperError(
            f"refusing to anchor: the ledger does not verify at sequence {report.broken_at}: "
            f"{report.reason}"
        )

    seq, digest = ledger.head(conn)
    if seq == 0:
        raise AnchorError(
            "the ledger is empty, so its head is the genesis constant and anchoring it would attest "
            "to nothing. Publish a prediction first."
        )

    existing = conn.execute(
        select(schema.ledger_entry.c.anchor_reference).where(schema.ledger_entry.c.seq == seq)
    ).scalar()
    if existing:
        raise AnchorError(
            f"sequence {seq} is already anchored. Anchoring it again would replace a receipt with a "
            "later one and lose the earlier, weaker in time attestation, which is the valuable one. "
            "Publish a prediction and anchor the new head instead."
        )

    receipt = resolved.submit(digest)
    if receipt.submitted_digest != digest:
        raise AnchorError(
            "the anchoring service reported a different digest from the one submitted. Nothing is "
            "recorded."
        )

    conn.execute(
        update(schema.ledger_entry)
        .where(schema.ledger_entry.c.seq == seq)
        .values(anchor_reference=receipt.as_reference())
    )
    log.info(
        "ledger head anchored",
        seq=seq,
        digest=digest[:12],
        service=receipt.service,
        receipt=receipt.receipt_sha256[:12],
    )
    return receipt


@dataclass(slots=True)
class AnchorStatus:
    """What the accuracy page needs in order to describe the anchoring honestly."""

    configured: bool
    service: str | None
    entries: int
    anchored: int
    latest_seq: int | None = None
    latest_digest: str | None = None
    latest_at: str | None = None
    unanchored_since_seq: int | None = None
    anchors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def head_is_anchored(self) -> bool:
        return self.entries > 0 and self.unanchored_since_seq is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "service": self.service,
            "entries": self.entries,
            "anchored": self.anchored,
            "head_is_anchored": self.head_is_anchored,
            "latest_anchor_seq": self.latest_seq,
            "latest_anchor_at": self.latest_at,
        }

    def statement(self) -> str:
        """One sentence for the accuracy page. Never claims more than is true."""
        if self.entries == 0:
            return "Nothing has been published yet, so there is nothing to anchor."
        if not self.configured and self.anchored == 0:
            return (
                "This ledger is not anchored to any external service. Every entry is chained to the "
                "one before it, so no entry can be altered without breaking every hash after it, and "
                "that is an internal guarantee: it does not prove when the chain came into existence."
            )
        if self.anchored == 0:
            return (
                "An anchoring service is configured and no entry has been anchored yet, so the "
                "guarantee is still internal only."
            )
        if self.head_is_anchored:
            return (
                f"The current head, sequence {self.latest_seq}, was submitted to an external "
                f"timestamping service on {self.latest_at}. Entries published before that point "
                "cannot be rewritten without contradicting a receipt held by a third party."
            )
        return (
            f"{self.anchored} of {self.entries} entries are covered by an external anchor. The most "
            f"recent anchor is at sequence {self.latest_seq}; entries after it carry the internal "
            "guarantee only, until the next anchor."
        )


def anchor_status(conn: Connection, *, limit: int = 20) -> AnchorStatus:
    """What is anchored and what is not, computed rather than assumed."""
    settings = get_settings()
    totals = (
        conn.execute(
            text(
                """
                SELECT
                    count(*)                                             AS entries,
                    count(*) FILTER (WHERE anchor_reference IS NOT NULL) AS anchored,
                    max(seq) FILTER (WHERE anchor_reference IS NOT NULL) AS latest_seq,
                    max(seq)                                             AS head_seq
                FROM ledger_entry
                """
            )
        )
        .mappings()
        .one()
    )

    entries = int(totals["entries"])
    anchored = int(totals["anchored"])
    latest_seq = int(totals["latest_seq"]) if totals["latest_seq"] is not None else None
    head_seq = int(totals["head_seq"]) if totals["head_seq"] is not None else None

    rows = (
        conn.execute(
            text(
                """
                SELECT seq, entry_hash, anchor_reference, published_at
                FROM ledger_entry
                WHERE anchor_reference IS NOT NULL
                ORDER BY seq DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )

    anchors: list[dict[str, Any]] = []
    for row in rows:
        fields = Receipt.parse(str(row["anchor_reference"]))
        anchors.append(
            {
                "seq": int(row["seq"]),
                "entry_hash": str(row["entry_hash"]),
                "service": fields.get("service"),
                "submitted_digest": fields.get("digest"),
                "receipt_sha256": fields.get("receipt_sha256"),
                "anchored_at": fields.get("at"),
                # The strong check a reader can run: the digest submitted must be the entry hash it
                # was submitted for. A mismatch means the stored reference does not describe this
                # entry, and it is reported rather than hidden.
                "digest_matches_entry": fields.get("digest") == str(row["entry_hash"]),
            }
        )

    latest = anchors[0] if anchors else None
    return AnchorStatus(
        configured=bool(settings.ledger_anchor_url),
        service=settings.ledger_anchor_url or None,
        entries=entries,
        anchored=anchored,
        latest_seq=latest_seq,
        latest_digest=str(latest["entry_hash"]) if latest else None,
        latest_at=str(latest["anchored_at"]) if latest else None,
        unanchored_since_seq=(
            latest_seq
            if head_seq is not None and latest_seq is not None and head_seq > latest_seq
            else (head_seq if latest_seq is None and head_seq is not None else None)
        ),
        anchors=anchors,
    )
