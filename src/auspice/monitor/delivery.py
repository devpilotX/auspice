"""Alert delivery.

`watcher.py` detects changes, scores them for materiality, and writes rows to `alert`. Nothing sent
them. Section 6.11 calls monitoring the reason revenue recurs, and a monitoring product that writes
alerts to a table nobody reads is a report with extra steps.

## What this guarantees, and what it does not

Delivery is **at least once**, not exactly once, and that is a choice rather than an oversight. The
send happens, then the row is marked delivered, then the transaction commits. A crash in between
re-sends on the next run. The alternative, marking first, loses an alert silently whenever a send
fails after the mark. For a product whose whole promise is that you find out before the hearing, a
duplicate is an annoyance and a miss is a broken promise.

## Why the attempt count exists

Without it the loop retries the head of the queue forever and every later alert waits behind one
undeliverable address. The failure mode is an absence of alerts, which nobody notices, so the queue
skips a row once it has failed `alert_max_delivery_attempts` times and records why.

## Channels

`log` is the default and needs no credentials, which matters because an unconfigured deployment
should still be observably doing the right thing rather than appearing to work. `webhook` posts JSON,
which covers Slack, Teams and anything with an inbound URL. `smtp` sends mail.

None of the three is the interesting part. The interesting part is that the channel is resolved once,
from configuration, and the loop below does not know which one it has.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.engine import Connection

from auspice.config import get_settings
from auspice.errors import StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="monitor")

# How long a single send may take before it is treated as a failure. An alert channel that hangs must
# not hold the transaction open for the rest of the queue.
SEND_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class PendingAlert:
    """One alert waiting to go out, with everything a channel needs to render it."""

    id: int
    subscriber: str
    label: str
    jurisdiction_slug: str
    trigger: str
    materiality: float
    headline: str
    body: str
    score_before: float | None
    score_after: float | None
    detected_on: Any
    attempts: int

    @property
    def score_movement(self) -> str | None:
        """The movement as a sentence, or None when there is no before and after to compare."""
        if self.score_before is None or self.score_after is None:
            return None
        delta = self.score_after - self.score_before
        direction = "up" if delta > 0 else "down"
        return (
            f"The approval probability moved {direction} from "
            f"{self.score_before:.0%} to {self.score_after:.0%}."
        )

    def as_text(self) -> str:
        """The alert as plain text. One format, used by every channel, so they cannot diverge."""
        lines = [
            self.headline,
            "",
            f"Site: {self.label}",
            f"Jurisdiction: {self.jurisdiction_slug}",
            f"Detected: {self.detected_on}",
            f"Materiality: {self.materiality:.2f}",
            "",
            self.body,
        ]
        movement = self.score_movement
        if movement:
            lines.extend(["", movement])
        return "\n".join(lines)

    def as_payload(self) -> dict[str, Any]:
        """The alert as JSON, for a webhook."""
        return {
            "alert_id": self.id,
            "subscriber": self.subscriber,
            "site": self.label,
            "jurisdiction": self.jurisdiction_slug,
            "trigger": self.trigger,
            "materiality": round(self.materiality, 3),
            "headline": self.headline,
            "body": self.body,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "detected_on": str(self.detected_on),
        }


class Channel(Protocol):
    """Somewhere an alert can be sent. Raises on failure rather than returning a flag.

    Raising is deliberate: a channel that returns False invites a caller to ignore it, and a caller
    that ignores a failed send marks the alert delivered.
    """

    name: str

    def send(self, alert: PendingAlert) -> None: ...


@dataclass(slots=True)
class LogChannel:
    """Writes the alert to the structured log. The default, and it needs no credentials.

    This is not a stub. An unconfigured deployment that logs every alert is observably doing the right
    thing and can be verified by reading the log, which is strictly better than one that appears to
    work because nothing errored.
    """

    name: str = "log"

    def send(self, alert: PendingAlert) -> None:
        log.info(
            "alert",
            alert_id=alert.id,
            subscriber=alert.subscriber,
            jurisdiction=alert.jurisdiction_slug,
            trigger=alert.trigger,
            materiality=round(alert.materiality, 3),
            headline=alert.headline,
        )


@dataclass(slots=True)
class WebhookChannel:
    """Posts the alert as JSON. Covers Slack, Teams and any inbound URL."""

    url: str
    name: str = "webhook"

    def send(self, alert: PendingAlert) -> None:
        import httpx

        response = httpx.post(
            self.url,
            json=alert.as_payload(),
            timeout=SEND_TIMEOUT_SECONDS,
            headers={"content-type": "application/json"},
        )
        # 2xx only. A webhook that answers 302 has not accepted anything.
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"webhook returned {response.status_code}: {response.text[:200]}")


@dataclass(slots=True)
class SmtpChannel:
    """Sends the alert as mail.

    ``watch.subscriber`` is documented in the schema as an API key label until billing exists, so it
    is not reliably an address. If it parses as one it is used, otherwise the configured fallback is,
    and which happened is recorded on the alert. Silently dropping an alert because a subscriber label
    was not an email address would be the worst available behaviour.
    """

    host: str
    port: int
    username: str
    password: str
    sender: str
    fallback_recipient: str
    starttls: bool = True
    name: str = "smtp"

    def recipient_for(self, alert: PendingAlert) -> str:
        candidate = alert.subscriber.strip()
        if "@" in candidate and " " not in candidate:
            return candidate
        if not self.fallback_recipient:
            raise RuntimeError(
                f"subscriber {alert.subscriber!r} is not an email address and "
                "AUSPICE_ALERT_FALLBACK_RECIPIENT is not set, so there is nowhere to send this."
            )
        return self.fallback_recipient

    def send(self, alert: PendingAlert) -> None:
        import smtplib
        from email.message import EmailMessage

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = self.recipient_for(alert)
        message["Subject"] = alert.headline
        message.set_content(alert.as_text())

        with smtplib.SMTP(self.host, self.port, timeout=SEND_TIMEOUT_SECONDS) as server:
            if self.starttls:
                server.starttls()
            if self.username:
                server.login(self.username, self.password)
            server.send_message(message)


def get_channel() -> Channel:
    """Resolve the configured channel, or refuse with the reason.

    Refusing rather than falling back to the log is the right behaviour for a misconfigured
    production deployment: an operator who set the channel to smtp and left the host blank wants to
    hear about it, not to discover months later that alerts went to a log file.
    """
    settings = get_settings()
    channel = settings.alert_channel

    if channel == "log":
        return LogChannel()

    if channel == "webhook":
        if not settings.alert_webhook_url:
            raise StageUnavailableError(
                "AUSPICE_ALERT_CHANNEL is webhook and AUSPICE_ALERT_WEBHOOK_URL is empty. Set the "
                "URL, or set the channel to log."
            )
        return WebhookChannel(url=settings.alert_webhook_url)

    if channel == "smtp":
        missing = [
            name
            for name, value in (
                ("AUSPICE_ALERT_SMTP_HOST", settings.alert_smtp_host),
                ("AUSPICE_ALERT_SENDER", settings.alert_sender),
            )
            if not value
        ]
        if missing:
            raise StageUnavailableError(
                f"AUSPICE_ALERT_CHANNEL is smtp and {', '.join(missing)} is empty. Set it, or set "
                "the channel to log."
            )
        return SmtpChannel(
            host=settings.alert_smtp_host,
            port=settings.alert_smtp_port,
            username=settings.alert_smtp_username,
            password=settings.alert_smtp_password,
            sender=settings.alert_sender,
            fallback_recipient=settings.alert_fallback_recipient,
            starttls=settings.alert_smtp_starttls,
        )

    raise StageUnavailableError(f"unknown alert channel {channel!r}")


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
_PENDING_SQL = text(
    """
    SELECT a.id, a.materiality, a.headline, a.body, a.score_before, a.score_after,
           a.delivery_attempts, w.subscriber, w.label, j.slug, ce.trigger, ce.detected_on
    FROM alert a
    JOIN watch w ON w.id = a.watch_id
    JOIN change_event ce ON ce.id = a.change_event_id
    JOIN jurisdiction j ON j.id = ce.jurisdiction_id
    WHERE a.delivered_at IS NULL
      AND a.suppressed_reason IS NULL
      AND a.delivery_attempts < :max_attempts
    ORDER BY a.materiality DESC, a.id
    LIMIT :limit
    """
)


def undelivered(
    conn: Connection, *, limit: int | None = None, max_attempts: int | None = None
) -> list[PendingAlert]:
    """The delivery queue: material, not yet delivered, not yet given up on.

    Ordered by materiality so that if a run is cut short the alerts that mattered most went first.
    """
    settings = get_settings()
    rows = conn.execute(
        _PENDING_SQL,
        {
            "max_attempts": max_attempts
            if max_attempts is not None
            else settings.alert_max_delivery_attempts,
            "limit": limit,
        },
    ).mappings()
    return [
        PendingAlert(
            id=int(row["id"]),
            subscriber=str(row["subscriber"]),
            label=str(row["label"]),
            jurisdiction_slug=str(row["slug"]),
            trigger=str(row["trigger"]),
            materiality=float(row["materiality"]),
            headline=str(row["headline"]),
            body=str(row["body"]),
            score_before=float(row["score_before"]) if row["score_before"] is not None else None,
            score_after=float(row["score_after"]) if row["score_after"] is not None else None,
            detected_on=row["detected_on"],
            attempts=int(row["delivery_attempts"]),
        )
        for row in rows
    ]


def abandoned(conn: Connection, *, max_attempts: int | None = None) -> list[dict[str, Any]]:
    """Alerts that failed too many times and are no longer being retried.

    These are the ones an operator has to look at. They are not visible in the pending queue by
    design, and a queue that hides its failures is how an alert product dies quietly.
    """
    settings = get_settings()
    rows = conn.execute(
        text(
            """
            SELECT a.id, a.headline, a.delivery_attempts, a.delivery_error, w.subscriber, j.slug
            FROM alert a
            JOIN watch w ON w.id = a.watch_id
            JOIN change_event ce ON ce.id = a.change_event_id
            JOIN jurisdiction j ON j.id = ce.jurisdiction_id
            WHERE a.delivered_at IS NULL
              AND a.suppressed_reason IS NULL
              AND a.delivery_attempts >= :max_attempts
            ORDER BY a.id
            """
        ),
        {
            "max_attempts": max_attempts
            if max_attempts is not None
            else settings.alert_max_delivery_attempts
        },
    ).mappings()
    return [dict(row) for row in rows]


@dataclass(slots=True)
class DeliveryReport:
    channel: str = "none"
    considered: int = 0
    delivered: int = 0
    failed: int = 0
    dry_run: bool = False
    failures: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "considered": self.considered,
            "delivered": self.delivered,
            "failed": self.failed,
            "dry_run": self.dry_run,
        }


def deliver_pending(
    conn: Connection,
    *,
    channel: Channel | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> DeliveryReport:
    """Send every alert in the queue, one at a time, isolating failures.

    One failing recipient must not stop the rest, so each send is attempted independently and its
    error recorded against its own row. The attempt count is incremented whether the send succeeded
    or not, which is what makes the give up rule work.
    """
    resolved = channel or get_channel()
    report = DeliveryReport(channel=resolved.name, dry_run=dry_run)

    queue = undelivered(conn, limit=limit)
    report.considered = len(queue)

    for alert in queue:
        if dry_run:
            continue
        try:
            resolved.send(alert)
        except Exception as exc:  # a channel may raise anything; the loop must survive all of it
            report.failed += 1
            message = f"{type(exc).__name__}: {exc}"[:500]
            report.failures.append(
                {"id": alert.id, "subscriber": alert.subscriber, "error": message}
            )
            conn.execute(
                text(
                    """
                    UPDATE alert
                    SET delivery_attempts = delivery_attempts + 1,
                        delivery_error = :error,
                        delivery_channel = :channel
                    WHERE id = :id
                    """
                ),
                {"error": message, "channel": resolved.name, "id": alert.id},
            )
            log.warning(
                "alert delivery failed",
                alert_id=alert.id,
                channel=resolved.name,
                attempts=alert.attempts + 1,
                error=message,
            )
            continue

        report.delivered += 1
        conn.execute(
            text(
                """
                UPDATE alert
                SET delivered_at = :now,
                    delivery_attempts = delivery_attempts + 1,
                    delivery_error = NULL,
                    delivery_channel = :channel
                WHERE id = :id
                """
            ),
            {"now": datetime.now(UTC), "channel": resolved.name, "id": alert.id},
        )

    log.info(
        "alert delivery complete",
        channel=resolved.name,
        considered=report.considered,
        delivered=report.delivered,
        failed=report.failed,
        dry_run=dry_run,
    )
    return report


def delivery_health(conn: Connection) -> dict[str, Any]:
    """Counts an operator needs to know whether alerts are actually going out.

    ``oldest_pending_hours`` is the number that matters. A queue with a growing oldest entry is a
    delivery outage, and it is the only one of these that a healthy system keeps near zero.
    """
    settings = get_settings()
    row = (
        conn.execute(
            text(
                """
            SELECT
                count(*) FILTER (WHERE delivered_at IS NOT NULL)             AS delivered,
                count(*) FILTER (WHERE suppressed_reason IS NOT NULL)        AS suppressed,
                count(*) FILTER (
                    WHERE delivered_at IS NULL AND suppressed_reason IS NULL
                      AND delivery_attempts < :max_attempts
                )                                                            AS pending,
                count(*) FILTER (
                    WHERE delivered_at IS NULL AND suppressed_reason IS NULL
                      AND delivery_attempts >= :max_attempts
                )                                                            AS abandoned,
                max(EXTRACT(EPOCH FROM (now() - created_at)) / 3600.0) FILTER (
                    WHERE delivered_at IS NULL AND suppressed_reason IS NULL
                      AND delivery_attempts < :max_attempts
                )                                                            AS oldest_pending_hours
            FROM alert
            """
            ),
            {"max_attempts": settings.alert_max_delivery_attempts},
        )
        .mappings()
        .one()
    )
    oldest = row["oldest_pending_hours"]
    return {
        "channel": get_settings().alert_channel,
        "delivered": int(row["delivered"]),
        "suppressed": int(row["suppressed"]),
        "pending": int(row["pending"]),
        "abandoned": int(row["abandoned"]),
        "oldest_pending_hours": round(float(oldest), 1) if oldest is not None else None,
    }


def render_json(alert: PendingAlert) -> str:
    """Used by the CLI preview, so what is shown is what a webhook would receive."""
    return json.dumps(alert.as_payload(), indent=2, sort_keys=True)
