"""Stage 11: monitoring and re-scoring.

Section 6.11: monitoring is what turns a report into a subscription. Alerts are scored for materiality
before sending, because an alert system that cries wolf gets muted in a week.
"""

from __future__ import annotations

from auspice.monitor.delivery import (
    Channel,
    DeliveryReport,
    LogChannel,
    PendingAlert,
    SmtpChannel,
    WebhookChannel,
    abandoned,
    deliver_pending,
    delivery_health,
    get_channel,
    undelivered,
)
from auspice.monitor.watcher import (
    BASE_MATERIALITY,
    NEARBY_KM,
    SCORE_NOISE_FLOOR,
    SEND_THRESHOLD,
    Change,
    MonitorReport,
    daily_run,
    detect_changes,
    materiality,
    pending_alerts,
    record_and_alert,
)

__all__ = [
    "BASE_MATERIALITY",
    "NEARBY_KM",
    "SCORE_NOISE_FLOOR",
    "SEND_THRESHOLD",
    "Change",
    "Channel",
    "DeliveryReport",
    "LogChannel",
    "MonitorReport",
    "PendingAlert",
    "SmtpChannel",
    "WebhookChannel",
    "abandoned",
    "daily_run",
    "deliver_pending",
    "delivery_health",
    "detect_changes",
    "get_channel",
    "materiality",
    "pending_alerts",
    "record_and_alert",
    "undelivered",
]
