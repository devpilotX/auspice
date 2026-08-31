"""External anchoring, and the claims it is allowed to make.

The hash chain proves internal consistency: no entry can be altered without breaking every hash after
it. It cannot prove the chain existed before today, because we hold all of it and could rebuild and
rehash it, and the result would verify perfectly. An anchor puts the head in a third party's hands at a
known time, which is what makes that impossible.

`AUSPICE_LEDGER_ANCHOR_URL` and `ledger_entry.anchor_reference` existed since the first migration and
nothing wrote to either.

Most of these tests are about refusals, because for a published accuracy record the dangerous failure
is not a missing anchor, it is a claimed one. An anchor command that appears to work while anchoring
nothing puts a false statement on the page the whole business rests on.
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import Connection, text

from auspice import ledger
from auspice.errors import LedgerTamperError, StageUnavailableError
from auspice.ledger import anchor as anchor_module
from auspice.ledger.anchor import AnchorError, AnchorStatus, Receipt
from tests.conftest import requires_db


class _Notary:
    """An anchoring service that returns a deterministic receipt."""

    name = "test-notary"

    def __init__(
        self, *, body: bytes = b"receipt-bytes", digest_override: str | None = None
    ) -> None:
        self.body = body
        self.digest_override = digest_override
        self.submitted: list[str] = []

    def submit(self, digest: str) -> Receipt:
        self.submitted.append(digest)
        return Receipt(
            service="test-notary",
            submitted_digest=self.digest_override or digest,
            receipt_sha256=hashlib.sha256(self.body).hexdigest(),
            receipt_bytes=len(self.body),
            received_at="2026-08-31T05:00:00+00:00",
        )


class _Refuses:
    name = "refuses"

    def submit(self, digest: str) -> Receipt:
        raise AnchorError("the service is down")


def _publish(conn: Connection, *, n: int = 1) -> None:
    """Publish n entries the way the real path does, through ledger.publish.

    Mirrors the seed in test_ledger.py rather than inventing a shorter INSERT, because the prediction
    table carries a model run and a features hash and a shortcut that omits them tests a row shape the
    product never produces.
    """
    jurisdiction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework)
                VALUES ('us-va-loudoun', 'Loudoun County', 'county', 'US', 'VA', 'dillons_rule')
                ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """
            )
        ).scalar_one()
    )
    existing = int(conn.execute(text("SELECT count(*) FROM ledger_entry")).scalar_one())
    for offset in range(n):
        # Unique across calls. model_run.version is unique, and publishing twice in one test with a
        # fixed version fails on the constraint rather than on anything under test.
        index = existing + offset
        model_run_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO model_run (kind, version, feature_set_version, dataset_hash,
                                           train_cutoff, n_train, n_test)
                    VALUES ('hierarchical', :version, '1.0.0', :hash, '2026-01-01', 400, 60)
                    RETURNING id
                    """
                ).bindparams(version=f"0.1.{index}", hash="d" * 64)
            ).scalar_one()
        )
        prediction_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO prediction (
                        public_id, jurisdiction_id, site, model_run_id,
                        approval_probability, ci80_low, ci80_high, abstained, abstention_reasons,
                        provenance, features_hash, data_as_of
                    ) VALUES (
                        :public_id, :jid, '{}'::jsonb, :run,
                        0.34, 0.25, 0.44, false, '{}',
                        '{}'::jsonb, :fhash, '2026-08-01'
                    ) RETURNING id
                    """
                ).bindparams(
                    public_id=f"scr_anchor{index:04d}",
                    jid=jurisdiction_id,
                    run=model_run_id,
                    fhash="e" * 64,
                )
            ).scalar_one()
        )
        ledger.publish(
            conn,
            prediction_id=prediction_id,
            payload={"public_id": f"scr_anchor{index:04d}", "approval_probability": 0.34},
        )


@requires_db
class TestAnchoringRefusals:
    def test_an_empty_ledger_is_refused_because_genesis_attests_to_nothing(
        self, clean_db: Connection
    ) -> None:
        with pytest.raises(AnchorError, match="empty"):
            ledger.anchor_head(clean_db, anchor=_Notary())

    def test_a_broken_chain_is_refused_before_anything_is_submitted(
        self, clean_db: Connection
    ) -> None:
        """Anchoring a broken chain would put it beyond dispute, which is the opposite of the point."""
        _publish(clean_db, n=2)
        # A schema valid hash that is the wrong hash. The column has a format constraint, so a short
        # string like "deadbeef" fails on the constraint rather than on the verification under test.
        clean_db.execute(
            text("UPDATE ledger_entry SET entry_hash = :h WHERE seq = 1"), {"h": "a" * 64}
        )
        ledger.reset_verification_cache()

        notary = _Notary()
        with pytest.raises(LedgerTamperError, match="refusing to anchor"):
            ledger.anchor_head(clean_db, anchor=notary)
        assert notary.submitted == [], "nothing may be submitted for a chain that does not verify"

    def test_anchoring_the_same_head_twice_is_refused(self, clean_db: Connection) -> None:
        """The earlier receipt is the valuable one, so it is not replaced by a later, weaker one."""
        _publish(clean_db, n=1)
        ledger.anchor_head(clean_db, anchor=_Notary())
        with pytest.raises(AnchorError, match="already anchored"):
            ledger.anchor_head(clean_db, anchor=_Notary())

    def test_a_service_returning_a_different_digest_records_nothing(
        self, clean_db: Connection
    ) -> None:
        _publish(clean_db, n=1)
        with pytest.raises(AnchorError, match="different digest"):
            ledger.anchor_head(clean_db, anchor=_Notary(digest_override="0" * 64))
        assert (
            clean_db.execute(
                text("SELECT count(*) FROM ledger_entry WHERE anchor_reference IS NOT NULL")
            ).scalar()
            == 0
        )

    def test_a_failing_service_leaves_the_entry_unanchored(self, clean_db: Connection) -> None:
        _publish(clean_db, n=1)
        with pytest.raises(AnchorError, match="service is down"):
            ledger.anchor_head(clean_db, anchor=_Refuses())
        assert (
            clean_db.execute(
                text("SELECT count(*) FROM ledger_entry WHERE anchor_reference IS NOT NULL")
            ).scalar()
            == 0
        )

    def test_no_configured_url_refuses_rather_than_silently_succeeding(self) -> None:
        """There is no null anchor. One would put a false claim on the accuracy page."""
        from auspice.config import get_settings

        if get_settings().ledger_anchor_url:
            pytest.skip("AUSPICE_LEDGER_ANCHOR_URL is set in this environment")
        with pytest.raises(StageUnavailableError, match="AUSPICE_LEDGER_ANCHOR_URL"):
            ledger.get_anchor()


@requires_db
class TestAnchoringSucceeds:
    def test_the_receipt_is_recorded_against_the_head(self, clean_db: Connection) -> None:
        _publish(clean_db, n=2)
        seq, digest = ledger.head(clean_db)
        receipt = ledger.anchor_head(clean_db, anchor=_Notary())

        assert receipt.submitted_digest == digest
        stored = clean_db.execute(
            text("SELECT anchor_reference FROM ledger_entry WHERE seq = :s"), {"s": seq}
        ).scalar()
        assert stored is not None
        fields = Receipt.parse(str(stored))
        assert fields["digest"] == digest
        assert fields["receipt_sha256"] == receipt.receipt_sha256

    def test_only_the_head_is_anchored_not_earlier_entries(self, clean_db: Connection) -> None:
        """An anchor covers everything before it through the chain, so it is recorded once."""
        _publish(clean_db, n=3)
        ledger.anchor_head(clean_db, anchor=_Notary())
        anchored = clean_db.execute(
            text("SELECT count(*) FROM ledger_entry WHERE anchor_reference IS NOT NULL")
        ).scalar()
        assert anchored == 1

    def test_the_chain_still_verifies_after_anchoring(self, clean_db: Connection) -> None:
        """anchor_reference is not part of the hashed payload, so writing it must not break the chain."""
        _publish(clean_db, n=2)
        ledger.anchor_head(clean_db, anchor=_Notary())
        ledger.reset_verification_cache()
        assert ledger.verify(clean_db).ok

    def test_publishing_again_leaves_a_new_unanchored_head(self, clean_db: Connection) -> None:
        _publish(clean_db, n=1)
        ledger.anchor_head(clean_db, anchor=_Notary())
        _publish(clean_db, n=1)

        status = ledger.anchor_status(clean_db)
        assert status.anchored == 1
        assert status.entries == 2
        assert not status.head_is_anchored
        assert "internal guarantee only" in status.statement()


@requires_db
class TestStatus:
    def test_an_empty_ledger_says_there_is_nothing_to_anchor(self, clean_db: Connection) -> None:
        status = ledger.anchor_status(clean_db)
        assert status.entries == 0
        assert "nothing to anchor" in status.statement()

    def test_an_unanchored_ledger_states_the_internal_guarantee_and_its_limit(
        self, clean_db: Connection
    ) -> None:
        _publish(clean_db, n=2)
        statement = ledger.anchor_status(clean_db).statement()
        assert "not anchored to any external service" in statement
        assert "does not prove when the chain came into existence" in statement

    def test_an_anchored_head_says_so_and_names_the_sequence(self, clean_db: Connection) -> None:
        _publish(clean_db, n=1)
        ledger.anchor_head(clean_db, anchor=_Notary())
        status = ledger.anchor_status(clean_db)
        assert status.head_is_anchored
        assert "cannot be rewritten without contradicting a receipt held by a third party" in (
            status.statement()
        )

    def test_a_reference_that_does_not_describe_its_entry_is_reported(
        self, clean_db: Connection
    ) -> None:
        """A stored reference for the wrong digest proves nothing, and hiding that would be worse."""
        _publish(clean_db, n=1)
        ledger.anchor_head(clean_db, anchor=_Notary())
        clean_db.execute(
            text(
                "UPDATE ledger_entry SET anchor_reference = "
                "'service=x digest=0000 receipt_sha256=y bytes=1 at=2026-01-01' "
                "WHERE anchor_reference IS NOT NULL"
            )
        )
        status = ledger.anchor_status(clean_db)
        assert status.anchors[0]["digest_matches_entry"] is False


class TestReceiptReference:
    def test_a_reference_round_trips(self) -> None:
        receipt = Receipt(
            service="https://a.pool.opentimestamps.org/digest",
            submitted_digest="a" * 64,
            receipt_sha256="b" * 64,
            receipt_bytes=412,
            received_at="2026-08-31T05:00:00+00:00",
            detail="Sun, 31 Aug 2026 05:00:00 GMT",
        )
        fields = Receipt.parse(receipt.as_reference())
        assert fields["digest"] == "a" * 64
        assert fields["receipt_sha256"] == "b" * 64
        assert fields["bytes"] == "412"

    def test_a_reference_is_one_line_so_the_raw_export_stays_readable(self) -> None:
        reference = Receipt("s", "a" * 64, "b" * 64, 1, "2026-08-31T05:00:00+00:00").as_reference()
        assert "\n" not in reference

    def test_parsing_junk_yields_no_fields_rather_than_raising(self) -> None:
        assert Receipt.parse("not a reference at all") == {}


class TestStatusStatements:
    """No database. These sentences go on the accuracy page, so their exact claims matter."""

    def test_a_configured_service_with_nothing_anchored_does_not_claim_an_anchor(self) -> None:
        status = AnchorStatus(configured=True, service="https://x/", entries=3, anchored=0)
        assert "still internal only" in status.statement()
        assert "third party" not in status.statement()

    def test_a_partially_anchored_ledger_reports_the_gap(self) -> None:
        status = AnchorStatus(
            configured=True,
            service="https://x/",
            entries=10,
            anchored=1,
            latest_seq=4,
            unanchored_since_seq=4,
        )
        statement = status.statement()
        assert "1 of 10" in statement
        assert "internal guarantee only" in statement

    def test_head_is_anchored_is_false_when_a_later_entry_exists(self) -> None:
        assert not AnchorStatus(
            configured=True,
            service="https://x/",
            entries=10,
            anchored=1,
            latest_seq=4,
            unanchored_since_seq=4,
        ).head_is_anchored

    def test_head_is_anchored_is_false_on_an_empty_ledger(self) -> None:
        assert not AnchorStatus(
            configured=True, service="https://x/", entries=0, anchored=0
        ).head_is_anchored


class TestReceiptBounds:
    def test_the_cap_is_small_enough_to_be_a_receipt_and_not_a_page(self) -> None:
        """An unbounded write from an external endpoint into a database column is a denial of service."""
        assert anchor_module.MAX_RECEIPT_BYTES <= 128 * 1024
