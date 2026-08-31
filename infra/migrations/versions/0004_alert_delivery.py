"""Alert delivery bookkeeping.

`monitor/watcher.py` wrote alert rows and nothing delivered them, so `alert.delivered_at` existed and
was never set by anything. These three columns are what a delivery loop needs to be safe.

`delivery_attempts` exists so one permanently failing recipient cannot block the queue. Without it the
loop retries the head of the queue forever and every later alert waits behind it, and the symptom is an
absence of alerts, which nobody notices.

`delivery_error` exists so an operator can see why a row is stuck without reading application logs,
which on this deployment are not aggregated anywhere.

`delivery_channel` records which channel actually delivered, because the channel is configurable and an
alert delivered to a log in development must be distinguishable from one delivered by mail in
production. Otherwise `delivered_at` means two different things depending on configuration.

Revision ID: 0004_alert_delivery
Revises: 0003_degenerate_corpus_reason
Created: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_alert_delivery"
down_revision: str | None = "0003_degenerate_corpus_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alert",
        sa.Column("delivery_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("alert", sa.Column("delivery_error", sa.Text(), nullable=True))
    op.add_column("alert", sa.Column("delivery_channel", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("alert", "delivery_channel")
    op.drop_column("alert", "delivery_error")
    op.drop_column("alert", "delivery_attempts")
