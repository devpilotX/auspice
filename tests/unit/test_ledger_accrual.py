"""Making the ledger accrue, and the failure whose symptom is silence.

`grade` records what happened against one published prediction, by sequence number, supplied by hand.
Nothing connected the two ends: an application could reach a terminal outcome in the graph and the
prediction made about it would sit unresolved forever, so the accuracy page would keep saying nothing has
resolved while the answer was already in the database.

That is worse than an empty accuracy record. An empty record is honest about being empty. One that stays
empty while outcomes arrive has quietly stopped working, and the two look identical from outside.

Four properties are asserted here, in order of how badly getting them wrong would hurt a published
accuracy claim.

**It never invents an outcome.** Pending, continued and tabled are not resolutions and are skipped. A
terminal outcome with no decision date is skipped too, because the ledger records when the answer became
known and inventing that date would falsify the timeline the survival model is measured against.

**It grades once.** A prediction regraded after the fact is a prediction whose score moved without the
outcome changing.

**An abstention is never a miss.** Refusing to answer is a successful response. Counting it as an error
would push the system toward answering when it should not, which is the incentive the whole design exists
to avoid.

**One bad row does not stop the rest.** An accuracy record that stops accruing because of one malformed
entry is an accuracy record that is quietly wrong.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Connection, text

from auspice import ledger
from auspice.domain import Outcome
from auspice.ledger.accrual import MISS_THRESHOLD, Resolvable
from tests.conftest import requires_db


def _seed(conn: Connection) -> tuple[int, int]:
    jurisdiction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework)
                VALUES ('us-va-accrual', 'Accrual County', 'county', 'US', 'VA', 'dillons_rule')
                RETURNING id
                """
            )
        ).scalar_one()
    )
    body_id = int(
        conn.execute(
            text(
                """
                INSERT INTO decision_body (jurisdiction_id, name, kind, seats, quorum)
                VALUES (:jid, 'Board of Supervisors', 'board_of_supervisors', 9, 5)
                RETURNING id
                """
            ).bindparams(jid=jurisdiction_id)
        ).scalar_one()
    )
    return jurisdiction_id, body_id


def _application(
    conn: Connection,
    *,
    jurisdiction_id: int,
    body_id: int,
    external_id: str,
    outcome: str,
    decided_on: date | None,
) -> int:
    censored = outcome in {"pending", "continued", "tabled", "unknown"}
    return int(
        conn.execute(
            text(
                """
                INSERT INTO application (
                    jurisdiction_id, body_id, external_id, use_class, relief_sought,
                    filed_on, decided_on, outcome, censored, label_source
                ) VALUES (
                    :jid, :bid, :ext, 'data_center_hyperscale', ARRAY['rezoning'],
                    '2024-01-05', :decided, :outcome, :censored, 'hand_labelled'
                ) RETURNING id
                """
            ).bindparams(
                jid=jurisdiction_id,
                bid=body_id,
                ext=external_id,
                decided=decided_on,
                outcome=outcome,
                censored=censored,
            )
        ).scalar_one()
    )


def _publish(
    conn: Connection,
    *,
    jurisdiction_id: int,
    application_id: int,
    index: int,
    probability: float | None,
    abstained: bool = False,
) -> int:
    """Publish a prediction about a specific application, the way the real path does."""
    model_run_id = int(
        conn.execute(
            text(
                """
                INSERT INTO model_run (kind, version, feature_set_version, dataset_hash,
                                       train_cutoff, n_train, n_test)
                VALUES ('hierarchical', :version, '1.0.0', :hash, '2024-01-01', 400, 60)
                RETURNING id
                """
            ).bindparams(version=f"0.9.{index}", hash="c" * 64)
        ).scalar_one()
    )
    prediction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO prediction (
                    public_id, application_id, jurisdiction_id, site, model_run_id,
                    approval_probability, ci80_low, ci80_high, abstained, abstention_reasons,
                    provenance, features_hash, data_as_of
                ) VALUES (
                    :public_id, :aid, :jid, '{}'::jsonb, :run,
                    :p, :lo, :hi, :abstained, :reasons,
                    '{}'::jsonb, :fhash, '2024-02-01'
                ) RETURNING id
                """
            ).bindparams(
                public_id=f"scr_acc{index:05d}",
                aid=application_id,
                jid=jurisdiction_id,
                run=model_run_id,
                p=probability,
                lo=None if probability is None else max(0.0, probability - 0.1),
                hi=None if probability is None else min(1.0, probability + 0.1),
                abstained=abstained,
                reasons=["thin_local_record"] if abstained else [],
                fhash="f" * 64,
            )
        ).scalar_one()
    )
    entry = ledger.publish(
        conn,
        prediction_id=prediction_id,
        payload={
            "public_id": f"scr_acc{index:05d}",
            "approval_probability": probability,
            "abstained": abstained,
        },
    )
    return entry.seq


@requires_db
class TestItNeverInventsAnOutcome:
    @pytest.mark.parametrize("outcome", ["pending", "continued", "tabled", "unknown"])
    def test_an_unresolved_application_is_not_gradeable(
        self, clean_db: Connection, outcome: str
    ) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome=outcome,
            decided_on=None,
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.7,
        )
        assert ledger.resolvable(clean_db) == []
        assert ledger.reconcile(clean_db).graded == 0

    def test_a_terminal_outcome_with_no_date_is_not_gradeable(self, clean_db: Connection) -> None:
        """Inventing the date would falsify the timeline the survival model is measured against."""
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="withdrawn",
            decided_on=None,
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.7,
        )
        assert ledger.resolvable(clean_db) == []

    def test_a_withdrawal_is_terminal_and_is_graded(self, clean_db: Connection) -> None:
        """The withdrawal rate measures hidden denials. Discarding it would erase that signal."""
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="withdrawn",
            decided_on=date(2024, 9, 1),
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.7,
        )
        report = ledger.reconcile(clean_db)
        assert report.graded == 1


@requires_db
class TestGrading:
    def test_a_resolved_application_grades_its_prediction(self, clean_db: Connection) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        seq = _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.82,
        )

        report = ledger.reconcile(clean_db)
        assert report.considered == 1
        assert report.graded == 1
        assert report.misses == 0

        row = (
            clean_db.execute(
                text(
                    "SELECT resolved_outcome, resolved_on, grading FROM ledger_entry WHERE seq = :s"
                ),
                {"s": seq},
            )
            .mappings()
            .one()
        )
        assert row["resolved_outcome"] == "approved"
        assert row["resolved_on"] == date(2024, 9, 1)
        assert row["grading"]["observed"] == 1.0

    def test_a_dry_run_grades_nothing(self, clean_db: Connection) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.82,
        )
        report = ledger.reconcile(clean_db, dry_run=True)
        assert report.considered == 1
        assert report.graded == 0
        assert len(ledger.resolvable(clean_db)) == 1

    def test_grading_happens_once(self, clean_db: Connection) -> None:
        """A prediction regraded is a score that moved without the outcome changing."""
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.82,
        )
        assert ledger.reconcile(clean_db).graded == 1
        second = ledger.reconcile(clean_db)
        assert second.considered == 0, "a graded entry must leave the queue"
        assert second.graded == 0

    def test_an_already_graded_entry_never_enters_the_queue(self, clean_db: Connection) -> None:
        """The queue filters on resolved_at, so a manual grading removes the entry rather than producing
        a skip. Asserted because the first version of this test assumed the opposite and was wrong."""
        jurisdiction_id, body_id = _seed(clean_db)
        first = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        second = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-2",
            outcome="denied",
            decided_on=date(2024, 10, 1),
        )
        seq_one = _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=first,
            index=0,
            probability=0.8,
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=second,
            index=1,
            probability=0.2,
        )

        ledger.grade(clean_db, seq=seq_one, outcome=Outcome.approved, resolved_on=date(2024, 9, 1))
        report = ledger.reconcile(clean_db)
        assert report.considered == 1
        assert report.graded == 1
        assert report.skipped == 0
        assert report.failures == []

    def test_a_stale_queue_skips_rather_than_abandoning_the_rest(
        self, clean_db: Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The race the per entry isolation exists for.

        The queue is read once, then entries are graded one at a time. A concurrent manual grading between
        those two steps makes one entry stale. Without isolation that raises and abandons every later
        entry, so the accuracy record stops accruing because of a race. Simulated by handing reconcile a
        queue built before a manual grading.
        """
        from auspice.ledger import accrual

        jurisdiction_id, body_id = _seed(clean_db)
        first = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        second = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-2",
            outcome="denied",
            decided_on=date(2024, 10, 1),
        )
        seq_one = _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=first,
            index=0,
            probability=0.8,
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=second,
            index=1,
            probability=0.2,
        )

        stale = accrual.resolvable(clean_db)
        assert len(stale) == 2
        ledger.grade(clean_db, seq=seq_one, outcome=Outcome.approved, resolved_on=date(2024, 9, 1))
        monkeypatch.setattr(accrual, "resolvable", lambda _conn: stale)

        report = accrual.reconcile(clean_db)
        assert report.considered == 2
        assert report.graded == 1, "the entry that was still gradeable must still be graded"
        assert report.skipped == 1
        assert report.failures[0]["seq"] == seq_one
        assert "already graded" in report.failures[0]["reason"]

    def test_the_limit_is_respected(self, clean_db: Connection) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        for index in range(3):
            application_id = _application(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"REZ-{index}",
                outcome="approved",
                decided_on=date(2024, 9, 1),
            )
            _publish(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                application_id=application_id,
                index=index,
                probability=0.8,
            )
        assert ledger.reconcile(clean_db, limit=2).graded == 2
        assert len(ledger.resolvable(clean_db)) == 1

    def test_the_chain_still_verifies_after_grading(self, clean_db: Connection) -> None:
        """grading is written outside the committed payload, so it must not disturb the chain."""
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.82,
        )
        ledger.reconcile(clean_db)
        ledger.reset_verification_cache()
        assert ledger.verify(clean_db).ok


@requires_db
class TestAccrualStatus:
    def test_it_reports_an_outcome_waiting_to_be_recorded(self, clean_db: Connection) -> None:
        """gradeable_now above zero means the accuracy page is understating what is known."""
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="REZ-1",
            outcome="approved",
            decided_on=date(2024, 9, 1),
        )
        _publish(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            application_id=application_id,
            index=0,
            probability=0.82,
        )
        status = ledger.accrual_status(clean_db)
        assert status["published"] == 1
        assert status["pending"] == 1
        assert status["gradeable_now"] == 1

        ledger.reconcile(clean_db)
        after = ledger.accrual_status(clean_db)
        assert after["resolved"] == 1
        assert after["gradeable_now"] == 0

    def test_an_empty_ledger_reports_zeroes_rather_than_failing(self, clean_db: Connection) -> None:
        status = ledger.accrual_status(clean_db)
        assert status["published"] == 0
        assert status["gradeable_now"] == 0
        assert status["oldest_pending"] is None


class TestMissClassification:
    """No database. These decide what appears in the published misses log."""

    @staticmethod
    def _item(**overrides: object) -> Resolvable:
        base: dict[str, object] = {
            "seq": 1,
            "public_id": "scr_x",
            "application_id": 1,
            "jurisdiction": "us-va-loudoun",
            "external_id": "REZ-1",
            "outcome": Outcome.denied,
            "decided_on": date(2024, 9, 1),
            "predicted": 0.9,
            "abstained": False,
        }
        base.update(overrides)
        return Resolvable(**base)  # type: ignore[arg-type]

    def test_confidently_wrong_is_a_miss(self) -> None:
        assert self._item(predicted=0.9, outcome=Outcome.denied).is_miss

    def test_confidently_right_is_not_a_miss(self) -> None:
        assert not self._item(predicted=0.9, outcome=Outcome.approved).is_miss

    def test_a_coin_flip_cannot_be_wrong(self) -> None:
        assert not self._item(predicted=0.5, outcome=Outcome.denied).is_miss
        assert not self._item(predicted=0.5, outcome=Outcome.approved).is_miss

    def test_an_abstention_is_never_a_miss(self) -> None:
        """Counting it would push the system toward answering when it should not."""
        assert not self._item(predicted=None, abstained=True, outcome=Outcome.denied).is_miss

    def test_the_threshold_sits_away_from_a_coin_flip(self) -> None:
        assert MISS_THRESHOLD > 0.5

    def test_approval_with_conditions_counts_as_approval(self) -> None:
        """A real modelling choice, and the conditions are kept on the row so a later model can split it."""
        assert self._item(predicted=0.9, outcome=Outcome.approved_with_conditions).observed == 1.0

    def test_a_withdrawal_is_observed_as_not_approved(self) -> None:
        assert self._item(outcome=Outcome.withdrawn).observed == 0.0

    def test_a_miss_note_states_the_numbers_and_does_not_explain(self) -> None:
        """A generated account of what the model missed would be a guess presented as analysis."""
        note = self._item(predicted=0.91, outcome=Outcome.denied).miss_note()
        assert note is not None
        assert "91%" in note
        assert "denial" in note
        assert "2024-09-01" in note
        assert "written by a person" in note

    def test_no_note_when_it_is_not_a_miss(self) -> None:
        assert self._item(predicted=0.9, outcome=Outcome.approved).miss_note() is None
