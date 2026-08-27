"""Leakage, schema drift, and the isolation of the synthetic corpus.

Three guards against failures that would produce a published number nobody could defend.

**Leakage.** Section 6.9 rule 3 says every feature must be computed as it would have been known on the
filing date. The test here does not inspect the SQL. It inserts a decision that happened *after* the
as-of date, rebuilds the features, and asserts nothing moved. That is a test that fails if anyone writes
a query without the date predicate, which is the actual failure mode.

**Schema drift.** The schema module is the single source of truth and the migrations are generated from
it. ``alembic check`` failing means the two have diverged, which surfaces later as a confusing query
error rather than as a migration problem.

**Synthetic isolation.** The kill test must have no code path that reaches the synthetic generator.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from sqlalchemy import Connection, text

from auspice.pipeline.features import build_for_application
from tests.conftest import requires_db


def _seed_jurisdiction(conn: Connection, *, slug: str = "us-xx-test") -> tuple[int, int]:
    jurisdiction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework,
                                          discretion_index, data_depth)
                VALUES (:slug, 'Test County', 'county', 'US', 'XX', 'home_rule', 0.8, 0)
                RETURNING id
                """
            ).bindparams(slug=slug)
        ).scalar_one()
    )
    body_id = int(
        conn.execute(
            text(
                """
                INSERT INTO decision_body (jurisdiction_id, name, kind, seats, quorum)
                VALUES (:jid, 'Board of Supervisors', 'board_of_supervisors', 5, 3)
                RETURNING id
                """
            ).bindparams(jid=jurisdiction_id)
        ).scalar_one()
    )
    return jurisdiction_id, body_id


def _insert_application(
    conn: Connection,
    *,
    jurisdiction_id: int,
    body_id: int,
    external_id: str,
    filed_on: date | None,
    decided_on: date | None,
    outcome: str,
    verified_evidence: bool = True,
) -> int:
    censored = outcome in {"pending", "continued", "tabled", "unknown"}
    application_id = int(
        conn.execute(
            text(
                """
                INSERT INTO application (
                    jurisdiction_id, body_id, external_id, use_class, relief_sought,
                    filed_on, decided_on, outcome, censored, label_source
                ) VALUES (
                    :jid, :bid, :ext, 'data_center_hyperscale', ARRAY['rezoning'],
                    :filed, :decided, :outcome, :censored, 'hand_labelled'
                ) RETURNING id
                """
            ).bindparams(
                jid=jurisdiction_id,
                bid=body_id,
                ext=external_id,
                filed=filed_on,
                decided=decided_on,
                outcome=outcome,
                censored=censored,
            )
        ).scalar_one()
    )

    if verified_evidence:
        document_id = f"{application_id:064d}"
        conn.execute(
            text(
                """
                INSERT INTO document (id, kind, source_url, byte_size, fetched_at, storage_key)
                VALUES (:id, 'minutes', :url, 100, now(), :key)
                ON CONFLICT (id) DO NOTHING
                """
            ).bindparams(
                id=document_id,
                url=f"https://example.gov/{application_id}",
                key=f"k/{application_id}",
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO fact_evidence (subject_table, subject_id, field, document_id, quote,
                                           extractor_version, verified, verified_at)
                VALUES ('application', :sid, 'outcome', :doc, :quote, 'test:1', true, now())
                """
            ).bindparams(
                sid=application_id,
                doc=document_id,
                quote=f"The board decided application {external_id} on the record.",
            )
        )
    return application_id


@requires_db
class TestNoLeakage:
    def test_a_later_decision_cannot_change_an_earlier_score(self, clean_db: Connection) -> None:
        """The test that catches a missing date predicate.

        Build features for an application filed in 2023, then insert four decisions from 2025 and
        rebuild. If any history feature moves, the query is reading the future.
        """
        jurisdiction_id, body_id = _seed_jurisdiction(clean_db)

        for index in range(4):
            _insert_application(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"OLD-{index}",
                filed_on=date(2021, 1, 1),
                decided_on=date(2021, 6, 1),
                outcome="approved" if index % 2 == 0 else "denied",
            )

        subject = _insert_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            filed_on=date(2023, 3, 1),
            decided_on=None,
            outcome="pending",
        )

        before = build_for_application(clean_db, subject)

        for index in range(4):
            _insert_application(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"FUTURE-{index}",
                filed_on=date(2025, 1, 1),
                decided_on=date(2025, 6, 1),
                outcome="denied",
            )

        after = build_for_application(clean_db, subject)

        assert before.values == after.values, (
            "features moved when future decisions were inserted, which means a query is missing its "
            "as-of predicate"
        )

    def test_a_later_ordinance_cannot_change_an_earlier_score(self, clean_db: Connection) -> None:
        jurisdiction_id, body_id = _seed_jurisdiction(clean_db)
        subject = _insert_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            filed_on=date(2023, 3, 1),
            decided_on=None,
            outcome="pending",
        )
        before = build_for_application(clean_db, subject)
        assert before.values["moratorium_active"] is False

        clean_db.execute(
            text(
                """
                INSERT INTO instrument (jurisdiction_id, kind, adopted_on, effective_on,
                                        applies_to_use_classes)
                VALUES (:jid, 'moratorium', '2025-06-01', '2025-06-01',
                        ARRAY['data_center_hyperscale'])
                """
            ).bindparams(jid=jurisdiction_id)
        )

        after = build_for_application(clean_db, subject)
        assert after.values["moratorium_active"] is False, (
            "a 2025 moratorium became visible to a 2023 filing"
        )

    def test_an_earlier_ordinance_is_visible(self, clean_db: Connection) -> None:
        """The other direction. A point in time build must still see the past."""
        jurisdiction_id, body_id = _seed_jurisdiction(clean_db)
        clean_db.execute(
            text(
                """
                INSERT INTO instrument (jurisdiction_id, kind, adopted_on, effective_on,
                                        expires_on, applies_to_use_classes)
                VALUES (:jid, 'moratorium', '2023-01-15', '2023-01-15', '2024-01-15',
                        ARRAY['data_center_hyperscale'])
                """
            ).bindparams(jid=jurisdiction_id)
        )
        subject = _insert_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            filed_on=date(2023, 3, 1),
            decided_on=None,
            outcome="pending",
        )
        row = build_for_application(clean_db, subject)
        assert row.values["moratorium_active"] is True
        assert row.values["days_since_rule_change"] == pytest.approx(45.0)
        assert row.values["rule_changed_within_180d"] is True

    def test_unverified_rows_do_not_enter_the_history(self, clean_db: Connection) -> None:
        """Section 6.7 decision (b): features come from documents with verified provenance.

        An application whose outcome has no verified quote must not contribute to a base rate. If it
        did, the verifier rejecting a citation would have no effect on the number, and the trust
        architecture would be decoration.
        """
        jurisdiction_id, body_id = _seed_jurisdiction(clean_db)
        for index in range(5):
            _insert_application(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"UNVERIFIED-{index}",
                filed_on=date(2021, 1, 1),
                decided_on=date(2021, 6, 1),
                outcome="approved",
                verified_evidence=False,
            )
        subject = _insert_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            filed_on=date(2023, 3, 1),
            decided_on=None,
            outcome="pending",
        )
        row = build_for_application(clean_db, subject)
        assert row.values["n_comparable_decisions"] == 0.0
        assert row.values["approval_rate_juris_use"] is None
        assert "approval_rate_juris_use" in row.missing

    def test_missing_is_missing_and_never_zero(self, clean_db: Connection) -> None:
        """A rate of zero means never approves. That is a strong claim to make out of ignorance."""
        jurisdiction_id, body_id = _seed_jurisdiction(clean_db)
        subject = _insert_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="ONLY",
            filed_on=date(2023, 3, 1),
            decided_on=None,
            outcome="pending",
        )
        row = build_for_application(clean_db, subject)
        for name in ("approval_rate_juris_use", "approval_rate_trend", "withdrawal_rate"):
            assert row.values[name] is None, f"{name} should be unknown, not zero"
            assert name in row.missing


@requires_db
class TestSchemaMatchesDatabase:
    def test_no_pending_migration(self) -> None:
        """The schema module and the migrations must agree, or drift surfaces as a query bug."""
        from alembic import command
        from alembic.config import Config
        from alembic.util.exc import AutogenerateDiffsDetected

        from auspice.config import REPO_ROOT

        config = Config(str(REPO_ROOT / "infra" / "alembic.ini"))
        os.environ["AUSPICE_ALEMBIC_TEST"] = "1"
        try:
            command.check(config)
        except AutogenerateDiffsDetected as exc:  # pragma: no cover - only on real drift
            pytest.fail(f"the database has drifted from src/auspice/db/schema.py: {exc}")
        finally:
            os.environ.pop("AUSPICE_ALEMBIC_TEST", None)

    def test_the_extensions_the_schema_needs_are_present(self, db: Connection) -> None:
        from auspice.db.engine import assert_extensions

        assert_extensions(db)

    def test_the_generated_duration_column_is_generated(self, db: Connection) -> None:
        """If this becomes an ordinary column, someone can write a wrong duration by hand."""
        value = db.execute(
            text(
                """
                SELECT is_generated FROM information_schema.columns
                WHERE table_name = 'application' AND column_name = 'months_to_decision'
                """
            )
        ).scalar_one()
        assert value == "ALWAYS"

    def test_a_decided_application_cannot_be_censored(self, db: Connection) -> None:
        """The CHECK constraint that keeps the survival label honest."""
        from sqlalchemy.exc import IntegrityError

        jurisdiction_id, body_id = _seed_jurisdiction(db, slug="us-xx-constraint")
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    """
                    INSERT INTO application (jurisdiction_id, body_id, use_class, relief_sought,
                                             filed_on, decided_on, outcome, censored)
                    VALUES (:jid, :bid, 'data_center_hyperscale', ARRAY['rezoning'],
                            '2024-01-01', '2024-06-01', 'approved', true)
                    """
                ).bindparams(jid=jurisdiction_id, bid=body_id)
            )

    def test_a_score_cannot_be_both_abstained_and_numeric(self, db: Connection) -> None:
        """The database enforces the same rule the score object does."""
        from sqlalchemy.exc import IntegrityError

        constraint = db.execute(
            text(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname = 'ck_prediction_abstention_excludes_probability'
                """
            )
        ).scalar_one_or_none()
        assert constraint is not None, "the abstention constraint is missing from the database"
        assert "abstained" in constraint
        del IntegrityError


class TestSyntheticIsolation:
    def test_the_kill_test_does_not_import_the_generator(self) -> None:
        """No code path from the kill test may reach synthetic data.

        Checked by reading the module source rather than by convention, because the whole value of the
        published accuracy record depends on it never having happened.
        """
        from pathlib import Path

        from auspice.models.eval import killtest

        source = Path(killtest.__file__).read_text(encoding="utf-8")
        assert "tests.synthetic" not in source
        assert "synthetic" not in source.replace("synthetic corpus", "")

    def test_a_synthetic_dataset_is_labelled_as_such(self, synthetic_dataset) -> None:  # type: ignore[no-untyped-def]
        assert synthetic_dataset.feature_set_version.startswith("synthetic:")
        assert any("synthetic" in note for note in synthetic_dataset.notes)
        assert not synthetic_dataset.require_verified
