"""The ledger. Section 8.2, and the only asset money cannot shortcut.

The property being tested is that the ledger is append only by structure rather than by policy. If any
historical payload can be changed without ``verify`` reporting it, the published accuracy record is
worthless, so the tampering tests here are the point of the file.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Connection, text

from auspice import ledger
from auspice.domain import Outcome
from auspice.errors import LedgerTamperError
from tests.conftest import requires_db

pytestmark = requires_db


def _payload(
    index: int, *, probability: float | None = 0.34, abstained: bool = False
) -> dict[str, object]:
    return {
        "public_id": f"scr_{index:04d}",
        "generated_at": datetime(2026, 8, 1, 12, 0, tzinfo=UTC).isoformat(),
        "jurisdiction": "us-va-loudoun",
        "use_class": "data_center_hyperscale",
        "requested_relief": ["rezoning"],
        "approval_probability": None if abstained else probability,
        "credible_interval_80": None if abstained else [0.25, 0.44],
        "abstained": abstained,
        "abstention_reasons": ["thin_local_record"] if abstained else [],
        "time_to_decision_months": {"p10": 8.0, "p50": 14.0, "p90": 27.0},
        "probability_of_rule_change_before_decision": 0.22,
        "model_version": "0.1.0",
        "model_kind": "hierarchical",
        "feature_set_version": "1.0.0",
        "dataset_hash": "d" * 64,
        "features_hash": "e" * 64,
        "data_as_of": "2026-08-01",
    }


def _seed_prediction(conn: Connection, index: int, *, abstained: bool = False) -> int:
    jurisdiction_id = conn.execute(
        text(
            """
            INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework)
            VALUES (:slug, :name, 'county', 'US', 'VA', 'dillons_rule')
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ).bindparams(slug="us-va-loudoun", name="Loudoun County")
    ).scalar_one()

    model_run_id = conn.execute(
        text(
            """
            INSERT INTO model_run (kind, version, feature_set_version, dataset_hash,
                                   train_cutoff, n_train, n_test)
            VALUES ('hierarchical', :version, '1.0.0', :hash, '2026-01-01', 400, 60)
            RETURNING id
            """
        ).bindparams(version=f"0.1.{index}", hash="d" * 64)
    ).scalar_one()

    return int(
        conn.execute(
            text(
                """
                INSERT INTO prediction (
                    public_id, jurisdiction_id, site, model_run_id,
                    approval_probability, ci80_low, ci80_high, abstained, abstention_reasons,
                    provenance, features_hash, data_as_of
                ) VALUES (
                    :public_id, :jid, '{}'::jsonb, :run,
                    :p, :lo, :hi, :abstained, :reasons,
                    '{}'::jsonb, :fhash, '2026-08-01'
                ) RETURNING id
                """
            ).bindparams(
                public_id=f"scr_{index:04d}",
                jid=jurisdiction_id,
                run=model_run_id,
                p=None if abstained else 0.34,
                lo=None if abstained else 0.25,
                hi=None if abstained else 0.44,
                abstained=abstained,
                reasons=["thin_local_record"] if abstained else [],
                fhash="e" * 64,
            )
        ).scalar_one()
    )


class TestChain:
    def test_an_empty_ledger_verifies(self, clean_db: Connection) -> None:
        report = ledger.verify(clean_db)
        assert report.ok
        assert report.entries == 0

    def test_the_first_entry_links_to_genesis(self, clean_db: Connection) -> None:
        prediction_id = _seed_prediction(clean_db, 1)
        entry = ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))
        assert entry.prev_hash == ledger.GENESIS_HASH
        assert entry.entry_hash == ledger.link(ledger.GENESIS_HASH, entry.payload_hash)

    def test_a_chain_of_entries_verifies(self, clean_db: Connection) -> None:
        for index in range(1, 6):
            prediction_id = _seed_prediction(clean_db, index)
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))
        report = ledger.verify(clean_db)
        assert report.ok
        assert report.entries == 5
        assert report.head is not None

    def test_each_entry_links_to_the_one_before(self, clean_db: Connection) -> None:
        hashes: list[tuple[str, str]] = []
        for index in range(1, 4):
            prediction_id = _seed_prediction(clean_db, index)
            entry = ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))
            hashes.append((entry.prev_hash, entry.entry_hash))
        assert hashes[1][0] == hashes[0][1]
        assert hashes[2][0] == hashes[1][1]

    def test_publishing_the_same_prediction_twice_is_refused(self, clean_db: Connection) -> None:
        """Section 8.9: never quietly revise a published prediction."""
        prediction_id = _seed_prediction(clean_db, 1)
        ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))
        with pytest.raises(ValueError, match="already in the ledger"):
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))

    def test_the_payload_hash_is_reproducible_by_anyone(self) -> None:
        """Someone recomputing from the published JSON must get our bytes."""
        payload = _payload(1)
        assert ledger.hash_payload(payload) == ledger.hash_payload(
            dict(reversed(list(payload.items())))
        )


class TestTamperEvidence:
    def test_editing_a_payload_breaks_the_chain(self, clean_db: Connection) -> None:
        """The test that matters. A revised prediction must be detectable."""
        for index in range(1, 5):
            prediction_id = _seed_prediction(clean_db, index)
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))

        assert ledger.verify(clean_db).ok

        clean_db.execute(
            text(
                """
                UPDATE ledger_entry
                SET payload = jsonb_set(payload, '{approval_probability}', '0.91')
                WHERE seq = 2
                """
            )
        )

        report = ledger.verify(clean_db)
        assert not report.ok
        assert report.broken_at == 2
        assert "no longer hashes" in (report.reason or "")

    def test_recomputing_the_payload_hash_still_breaks_the_link(self, clean_db: Connection) -> None:
        """A sophisticated forger updates the payload hash too. The link still fails."""
        import json

        for index in range(1, 5):
            prediction_id = _seed_prediction(clean_db, index)
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))

        forged = _payload(2, probability=0.91)
        clean_db.execute(
            text(
                "UPDATE ledger_entry SET payload = CAST(:p AS jsonb), payload_hash = :h WHERE seq = 2"
            ).bindparams(p=json.dumps(forged), h=ledger.hash_payload(forged))
        )

        report = ledger.verify(clean_db)
        assert not report.ok
        assert report.broken_at == 2
        assert "not the link" in (report.reason or "")

    def test_deleting_an_entry_breaks_the_chain(self, clean_db: Connection) -> None:
        for index in range(1, 5):
            prediction_id = _seed_prediction(clean_db, index)
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))

        clean_db.execute(text("DELETE FROM ledger_entry WHERE seq = 2"))

        report = ledger.verify(clean_db)
        assert not report.ok
        assert report.broken_at == 3

    def test_require_intact_raises_on_a_broken_chain(self, clean_db: Connection) -> None:
        prediction_id = _seed_prediction(clean_db, 1)
        ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))
        clean_db.execute(
            text("UPDATE ledger_entry SET payload_hash = :h WHERE seq = 1").bindparams(h="0" * 64)
        )
        with pytest.raises(LedgerTamperError):
            ledger.require_intact(clean_db)


class TestGrading:
    def test_grading_scores_the_call_without_touching_the_payload(
        self, clean_db: Connection
    ) -> None:
        prediction_id = _seed_prediction(clean_db, 1)
        entry = ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))

        grading = ledger.grade(
            clean_db, seq=entry.seq, outcome=Outcome.denied, resolved_on=date(2026, 11, 3)
        )

        assert grading["observed"] == 0.0
        assert grading["predicted"] == 0.34
        assert grading["brier_contribution"] == pytest.approx(0.34**2, abs=1e-6)
        assert grading["direction_correct"] is True, "0.34 predicts denial and denial happened"
        assert ledger.verify(clean_db).ok, "grading must not disturb the committed payload"

    def test_grading_a_wrong_call_records_it(self, clean_db: Connection) -> None:
        prediction_id = _seed_prediction(clean_db, 1)
        entry = ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))
        grading = ledger.grade(
            clean_db,
            seq=entry.seq,
            outcome=Outcome.approved,
            resolved_on=date(2026, 11, 3),
            miss_note="The model did not see the host agreement negotiated after filing.",
        )
        assert grading["direction_correct"] is False

        record = ledger.public_record(clean_db)
        assert len(record["misses"]) == 1
        assert "host agreement" in record["misses"][0]["note"]

    def test_grading_happens_once(self, clean_db: Connection) -> None:
        prediction_id = _seed_prediction(clean_db, 1)
        entry = ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))
        ledger.grade(clean_db, seq=entry.seq, outcome=Outcome.denied, resolved_on=date(2026, 11, 3))
        with pytest.raises(ValueError, match="already graded"):
            ledger.grade(
                clean_db, seq=entry.seq, outcome=Outcome.approved, resolved_on=date(2026, 12, 1)
            )

    def test_an_abstention_does_not_enter_the_brier_score(self, clean_db: Connection) -> None:
        """Section 8.4: abstentions are tracked separately, as an abstention record."""
        prediction_id = _seed_prediction(clean_db, 1, abstained=True)
        entry = ledger.publish(
            clean_db, prediction_id=prediction_id, payload=_payload(1, abstained=True)
        )
        grading = ledger.grade(
            clean_db, seq=entry.seq, outcome=Outcome.approved, resolved_on=date(2026, 11, 3)
        )
        assert "brier_contribution" not in grading

        record = ledger.public_record(clean_db)
        assert record["abstained"] == 1
        assert record["answered"] == 0
        assert record["brier_score"] is None

    def test_approval_with_conditions_counts_as_approval(self, clean_db: Connection) -> None:
        prediction_id = _seed_prediction(clean_db, 1)
        entry = ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(1))
        grading = ledger.grade(
            clean_db,
            seq=entry.seq,
            outcome=Outcome.approved_with_conditions,
            resolved_on=date(2026, 11, 3),
        )
        assert grading["observed"] == 1.0


class TestPublicRecord:
    def test_the_record_includes_everything_published(self, clean_db: Connection) -> None:
        for index in range(1, 4):
            prediction_id = _seed_prediction(clean_db, index)
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))
        ledger.grade(clean_db, seq=1, outcome=Outcome.denied, resolved_on=date(2026, 11, 3))

        # include_entries is opt in. The API never asked for the list and does not return it, so the
        # public endpoint no longer materialises every payload to count four things. This test is about
        # completeness of the record, so it asks for the list on purpose.
        record = ledger.public_record(clean_db, include_entries=True)
        assert record["published"] == 3
        assert record["resolved"] == 1
        assert record["pending"] == 2
        assert record["chain"]["ok"] is True
        assert len(record["entries"]) == 3

        # And the default omits it, so a public request cannot accidentally pull the whole chain.
        assert "entries" not in ledger.public_record(clean_db)

    def test_the_export_is_verifiable_line_by_line(self, clean_db: Connection) -> None:
        """A record that can only be checked through our own interface is not a public record."""
        import json

        for index in range(1, 4):
            prediction_id = _seed_prediction(clean_db, index)
            ledger.publish(clean_db, prediction_id=prediction_id, payload=_payload(index))

        lines = [json.loads(line) for line in ledger.export_jsonl(clean_db).strip().splitlines()]
        assert len(lines) == 3

        previous = ledger.GENESIS_HASH
        for line in lines:
            assert ledger.hash_payload(line["payload"]) == line["payload_hash"]
            assert line["prev_hash"] == previous
            assert ledger.link(line["prev_hash"], line["payload_hash"]) == line["entry_hash"]
            previous = line["entry_hash"]
