"""Alert delivery, and the three ways an alert product dies quietly.

`watcher.py` detected changes, scored them for materiality and wrote rows to `alert`. Nothing sent
them. Section 6.11 calls monitoring the reason revenue recurs, so this was the gap between a report
and a subscription.

The failure modes worth testing are not "does it send". They are the ones whose symptom is an
absence, because an absence is what nobody notices.

**One bad recipient blocks the queue.** If the loop stops on the first failure, or retries the head
forever, every later alert waits behind it and no alert arrives.

**A permanently failing alert is retried forever.** Tested by asserting the row leaves the queue
after the attempt limit and appears in the abandoned list instead, which is the list an operator is
told to read.

**A failed send is recorded as delivered.** The worst of the three, because it is silent and
irreversible. Tested by asserting `delivered_at` stays null and the error is stored.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import Connection, text

from auspice.monitor import delivery
from auspice.monitor.delivery import LogChannel, PendingAlert, WebhookChannel
from tests.conftest import requires_db


@pytest.fixture
def seeded(clean_db: Connection) -> Connection:
    """Two watches on two jurisdictions, one change event each, one alert each."""
    for index, slug in enumerate(("us-xx-alpha", "us-xx-beta")):
        jurisdiction_id = int(
            clean_db.execute(
                text(
                    """
                    INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework,
                                              discretion_index, data_depth)
                    VALUES (:slug, :name, 'county', 'US', 'XX', 'home_rule', 0.5, 0)
                    RETURNING id
                    """
                ).bindparams(slug=slug, name=f"County {index}")
            ).scalar_one()
        )
        watch_id = int(
            clean_db.execute(
                text(
                    """
                    INSERT INTO watch (subscriber, label, jurisdiction_id, site)
                    VALUES (:sub, :label, :jid, '{"use_class": "data_center_hyperscale"}'::jsonb)
                    RETURNING id
                    """
                ).bindparams(sub=f"subscriber-{index}", label=f"Site {index}", jid=jurisdiction_id)
            ).scalar_one()
        )
        change_id = int(
            clean_db.execute(
                text(
                    """
                    INSERT INTO change_event (jurisdiction_id, trigger, detected_on, summary,
                                              materiality)
                    VALUES (:jid, 'rule_changed', :on, :summary, 0.8)
                    RETURNING id
                    """
                ).bindparams(
                    jid=jurisdiction_id,
                    on=date(2026, 8, 30),
                    summary=f"The ordinance changed in County {index}",
                )
            ).scalar_one()
        )
        clean_db.execute(
            text(
                """
                INSERT INTO alert (watch_id, change_event_id, materiality, headline, body,
                                   score_before, score_after)
                VALUES (:wid, :cid, 0.8, :headline, :body, 0.62, 0.41)
                """
            ).bindparams(
                wid=watch_id,
                cid=change_id,
                headline=f"Rules changed in {slug}",
                body=f"The ordinance changed in County {index}. Your score moved.",
            )
        )
    return clean_db


class _Recorder:
    """A channel that records what it was given."""

    name = "recorder"

    def __init__(self) -> None:
        self.sent: list[PendingAlert] = []

    def send(self, alert: PendingAlert) -> None:
        self.sent.append(alert)


class _FailsFor:
    """A channel that fails for one subscriber and works for everyone else."""

    name = "fails-for"

    def __init__(self, subscriber: str) -> None:
        self.subscriber = subscriber
        self.sent: list[PendingAlert] = []

    def send(self, alert: PendingAlert) -> None:
        if alert.subscriber == self.subscriber:
            raise RuntimeError("mailbox does not exist")
        self.sent.append(alert)


def _alert_row(conn: Connection, alert_id: int) -> Any:
    return (
        conn.execute(
            text(
                """
                SELECT delivered_at, delivery_attempts, delivery_error, delivery_channel
                FROM alert WHERE id = :id
                """
            ).bindparams(id=alert_id)
        )
        .mappings()
        .one()
    )


def _sample_alert(**overrides: Any) -> PendingAlert:
    base: dict[str, Any] = {
        "id": 7,
        "subscriber": "acme",
        "label": "Northgate",
        "jurisdiction_slug": "us-va-loudoun",
        "trigger": "rule_changed",
        "materiality": 0.82,
        "headline": "Rules changed in us-va-loudoun",
        "body": "Data centres became a special exception use.",
        "score_before": 0.62,
        "score_after": 0.41,
        "detected_on": date(2026, 8, 30),
        "attempts": 0,
    }
    base.update(overrides)
    return PendingAlert(**base)


@requires_db
class TestTheQueue:
    def test_undelivered_returns_what_was_recorded(self, seeded: Connection) -> None:
        queue = delivery.undelivered(seeded)
        assert len(queue) == 2
        assert {a.subscriber for a in queue} == {"subscriber-0", "subscriber-1"}
        assert all(a.attempts == 0 for a in queue)

    def test_the_most_material_goes_first(self, seeded: Connection) -> None:
        """If a run is cut short, the alerts that mattered most have already gone."""
        seeded.execute(
            text("UPDATE alert SET materiality = 0.95 WHERE id = (SELECT max(id) FROM alert)")
        )
        queue = delivery.undelivered(seeded)
        assert queue[0].materiality == pytest.approx(0.95)

    def test_a_suppressed_alert_is_not_in_the_queue(self, seeded: Connection) -> None:
        seeded.execute(text("UPDATE alert SET suppressed_reason = 'below threshold'"))
        assert delivery.undelivered(seeded) == []

    def test_a_delivered_alert_is_not_in_the_queue(self, seeded: Connection) -> None:
        seeded.execute(text("UPDATE alert SET delivered_at = now()"))
        assert delivery.undelivered(seeded) == []

    def test_the_limit_is_respected(self, seeded: Connection) -> None:
        assert len(delivery.undelivered(seeded, limit=1)) == 1


@requires_db
class TestDelivery:
    def test_every_alert_is_sent_and_marked(self, seeded: Connection) -> None:
        channel = _Recorder()
        report = delivery.deliver_pending(seeded, channel=channel)

        assert report.considered == 2
        assert report.delivered == 2
        assert report.failed == 0
        assert len(channel.sent) == 2
        assert delivery.undelivered(seeded) == []

        for alert in channel.sent:
            row = _alert_row(seeded, alert.id)
            assert row["delivered_at"] is not None
            assert row["delivery_attempts"] == 1
            assert row["delivery_error"] is None
            assert row["delivery_channel"] == "recorder"

    def test_a_dry_run_sends_nothing_and_marks_nothing(self, seeded: Connection) -> None:
        channel = _Recorder()
        report = delivery.deliver_pending(seeded, channel=channel, dry_run=True)

        assert report.considered == 2
        assert report.delivered == 0
        assert channel.sent == []
        assert len(delivery.undelivered(seeded)) == 2

    def test_one_failing_recipient_does_not_block_the_others(self, seeded: Connection) -> None:
        """The failure mode whose symptom is an absence of alerts."""
        channel = _FailsFor("subscriber-0")
        report = delivery.deliver_pending(seeded, channel=channel)

        assert report.delivered == 1
        assert report.failed == 1
        assert [a.subscriber for a in channel.sent] == ["subscriber-1"]

        still_pending = delivery.undelivered(seeded)
        assert [a.subscriber for a in still_pending] == ["subscriber-0"]
        assert still_pending[0].attempts == 1

    def test_a_failed_send_is_never_marked_delivered(self, seeded: Connection) -> None:
        """The worst failure available, because it is silent and cannot be undone."""
        delivery.deliver_pending(seeded, channel=_FailsFor("subscriber-0"))

        failed_id = int(
            seeded.execute(
                text(
                    """
                    SELECT a.id FROM alert a JOIN watch w ON w.id = a.watch_id
                    WHERE w.subscriber = 'subscriber-0'
                    """
                )
            ).scalar_one()
        )
        row = _alert_row(seeded, failed_id)
        assert row["delivered_at"] is None
        assert row["delivery_attempts"] == 1
        assert "mailbox does not exist" in row["delivery_error"]
        assert row["delivery_channel"] == "fails-for"

    def test_the_error_is_reported_rather_than_swallowed(self, seeded: Connection) -> None:
        report = delivery.deliver_pending(seeded, channel=_FailsFor("subscriber-0"))
        assert len(report.failures) == 1
        assert report.failures[0]["subscriber"] == "subscriber-0"
        assert "RuntimeError" in report.failures[0]["error"]

    def test_a_channel_that_raises_anything_does_not_end_the_run(self, seeded: Connection) -> None:
        """A channel is third party code and may raise any Exception subclass."""

        class _Awkward:
            name = "awkward"

            def send(self, alert: PendingAlert) -> None:
                raise ValueError("no")

        report = delivery.deliver_pending(seeded, channel=_Awkward())
        assert report.failed == 2
        assert report.delivered == 0


@requires_db
class TestGivingUp:
    def test_a_row_leaves_the_queue_after_the_attempt_limit(self, seeded: Connection) -> None:
        channel = _FailsFor("subscriber-0")
        for _ in range(6):
            delivery.deliver_pending(seeded, channel=channel)

        assert delivery.undelivered(seeded) == [], (
            "a permanently failing alert must stop blocking the queue"
        )

    def test_it_appears_in_the_abandoned_list_instead(self, seeded: Connection) -> None:
        channel = _FailsFor("subscriber-0")
        for _ in range(6):
            delivery.deliver_pending(seeded, channel=channel)

        rows = delivery.abandoned(seeded)
        assert len(rows) == 1
        assert rows[0]["subscriber"] == "subscriber-0"
        assert rows[0]["delivery_attempts"] >= 5
        assert "mailbox does not exist" in rows[0]["delivery_error"]

    def test_resetting_the_count_puts_it_back(self, seeded: Connection) -> None:
        """The abandoned list says the alerts are not lost. That has to be true."""
        for _ in range(6):
            delivery.deliver_pending(seeded, channel=_FailsFor("subscriber-0"))
        assert delivery.undelivered(seeded) == []

        seeded.execute(text("UPDATE alert SET delivery_attempts = 0 WHERE delivered_at IS NULL"))
        recovered = delivery.deliver_pending(seeded, channel=_Recorder())
        assert recovered.delivered == 1


@requires_db
class TestHealth:
    def test_it_counts_what_an_operator_needs(self, seeded: Connection) -> None:
        health = delivery.delivery_health(seeded)
        assert health["pending"] == 2
        assert health["delivered"] == 0
        assert health["abandoned"] == 0
        assert health["oldest_pending_hours"] is not None

    def test_delivering_moves_the_counts(self, seeded: Connection) -> None:
        delivery.deliver_pending(seeded, channel=_Recorder())
        health = delivery.delivery_health(seeded)
        assert health["pending"] == 0
        assert health["delivered"] == 2
        assert health["oldest_pending_hours"] is None

    def test_abandonment_is_counted_separately_from_pending(self, seeded: Connection) -> None:
        for _ in range(6):
            delivery.deliver_pending(seeded, channel=_FailsFor("subscriber-0"))
        health = delivery.delivery_health(seeded)
        assert health["abandoned"] == 1
        assert health["delivered"] == 1
        assert health["pending"] == 0


class TestRendering:
    """No database. The rendered forms are what a human or a webhook actually receives."""

    def test_the_text_form_names_the_site_and_the_county(self) -> None:
        text_form = _sample_alert().as_text()
        assert "Northgate" in text_form
        assert "us-va-loudoun" in text_form
        assert "special exception" in text_form

    def test_a_score_movement_is_stated_in_words(self) -> None:
        assert "moved down from 62% to 41%" in _sample_alert().as_text()

    def test_no_movement_is_claimed_when_there_is_nothing_to_compare(self) -> None:
        alert = _sample_alert(score_before=None, score_after=None)
        assert alert.score_movement is None
        assert "moved" not in alert.as_text()

    def test_an_upward_movement_says_up(self) -> None:
        alert = _sample_alert(score_before=0.41, score_after=0.62)
        assert alert.score_movement is not None
        assert "moved up" in alert.score_movement

    def test_the_payload_carries_the_identifier_so_a_webhook_can_deduplicate(self) -> None:
        """Delivery is at least once, so the receiver needs a key to deduplicate on."""
        payload = _sample_alert().as_payload()
        assert payload["alert_id"] == 7
        assert payload["jurisdiction"] == "us-va-loudoun"
        assert payload["materiality"] == 0.82

    def test_the_json_preview_is_the_payload(self) -> None:
        import json

        assert json.loads(delivery.render_json(_sample_alert())) == _sample_alert().as_payload()


class TestChannelResolution:
    """`Settings` is frozen, so these override the accessor with a copy rather than mutating it.

    That the model is frozen is the reason the CLI `--channel` override builds a channel directly
    instead of temporarily rewriting configuration, which an earlier draft did.
    """

    @staticmethod
    def _with(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
        from auspice.config import get_settings

        patched = get_settings().model_copy(update=overrides)
        monkeypatch.setattr(delivery, "get_settings", lambda: patched)

    def test_the_default_channel_needs_no_credentials(self) -> None:
        """An unconfigured deployment must still be observably doing the right thing."""
        assert isinstance(delivery.get_channel(), LogChannel)

    def test_a_webhook_without_a_url_refuses_rather_than_falling_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falling back to the log would hide a misconfiguration for months."""
        from auspice.errors import StageUnavailableError

        self._with(monkeypatch, alert_channel="webhook", alert_webhook_url="")
        with pytest.raises(StageUnavailableError, match="AUSPICE_ALERT_WEBHOOK_URL"):
            delivery.get_channel()

    def test_a_configured_webhook_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._with(
            monkeypatch, alert_channel="webhook", alert_webhook_url="https://hooks.example/x"
        )
        channel = delivery.get_channel()
        assert isinstance(channel, WebhookChannel)
        assert channel.url == "https://hooks.example/x"

    def test_smtp_without_a_host_refuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from auspice.errors import StageUnavailableError

        self._with(monkeypatch, alert_channel="smtp", alert_smtp_host="")
        with pytest.raises(StageUnavailableError, match="AUSPICE_ALERT_SMTP_HOST"):
            delivery.get_channel()

    def test_a_configured_smtp_channel_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from auspice.monitor.delivery import SmtpChannel

        self._with(
            monkeypatch,
            alert_channel="smtp",
            alert_smtp_host="mail.example.com",
            alert_sender="alerts@example.com",
        )
        channel = delivery.get_channel()
        assert isinstance(channel, SmtpChannel)
        assert channel.host == "mail.example.com"

    def test_settings_is_frozen(self) -> None:
        """Load bearing. Configuration that can be mutated at runtime is configuration that is."""
        from auspice.config import get_settings

        with pytest.raises(Exception, match="frozen"):
            get_settings().alert_channel = "smtp"


class TestSmtpRecipient:
    """`watch.subscriber` is an API key label, not reliably an address."""

    @staticmethod
    def _channel(fallback: str = "ops@example.com") -> Any:
        from auspice.monitor.delivery import SmtpChannel

        return SmtpChannel(
            host="mail.example.com",
            port=587,
            username="u",
            password="p",
            sender="alerts@example.com",
            fallback_recipient=fallback,
        )

    def test_a_subscriber_that_is_an_address_is_used(self) -> None:
        alert = _sample_alert(subscriber="buyer@fund.example")
        assert self._channel().recipient_for(alert) == "buyer@fund.example"

    def test_a_label_falls_back_to_the_operator(self) -> None:
        alert = _sample_alert(subscriber="acme-tier-enterprise")
        assert self._channel().recipient_for(alert) == "ops@example.com"

    def test_with_no_fallback_it_fails_loudly_rather_than_dropping_the_alert(self) -> None:
        alert = _sample_alert(subscriber="acme-tier-enterprise")
        with pytest.raises(RuntimeError, match="nowhere to send"):
            self._channel(fallback="").recipient_for(alert)
