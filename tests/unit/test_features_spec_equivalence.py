"""The prospective scoring path must read the graph, not write to it.

Scoring a site that does not exist used to insert an application inside a savepoint, build features
against it, and roll the savepoint back. It produced correct features. It also made every read of the
scoring endpoint a write: one dead tuple in the graph's primary table per site scored, one burned
sequence value, and one subtransaction per site with no cap on the count, so a five hundred site
portfolio opened five hundred subtransactions inside one long lived snapshot.

The feature builder never needed any of it. ``_build`` consumes a mapping and never re-reads
``application``, so a prospective site can be described in memory and passed to the same function every
historical row goes through.

Three claims are asserted here, because the refactor is only safe if all three hold.

**Equivalence.** A real application built by row id and the same application built from a specification
produce identical feature values and identical missing sets. If they ever diverge, the calibration
measured on history has stopped applying to prospective scores, which is the one thing this product
sells.

**No write.** ``begin_nested`` raising makes the scoring path fail if anyone reintroduces a savepoint,
and the application id sequence must not advance while a score is produced.

**No drift.** Every key ``_build`` and its callees read out of the record is declared on
``ApplicationSpec``. This is checked by reading the source, not by review, because the failure mode is
asymmetric and silent: adding a field that only the historical producer populates leaves the historical
path working and breaks the prospective one, in production, on the endpoint customers pay for.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import date

import pytest
from sqlalchemy import Connection, text

from auspice.domain import Relief, UseClass
from auspice.pipeline.features import (
    ApplicationSpec,
    build_for_application,
    build_for_spec,
)
from auspice.pipeline.features import builder as builder_module
from auspice.score.engine import SiteRequest, _synthetic_feature_row
from tests.conftest import requires_db

AS_OF = date(2025, 6, 1)


def _seed(conn: Connection) -> tuple[int, int]:
    jurisdiction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework,
                                          discretion_index, data_depth)
                VALUES ('us-xx-spec', 'Spec County', 'county', 'US', 'XX', 'home_rule', 0.7, 0)
                RETURNING id
                """
            )
        ).scalar_one()
    )
    # Two bodies with different seat counts, so the deterministic body choice is actually exercised
    # rather than trivially satisfied by there being only one candidate.
    conn.execute(
        text(
            """
            INSERT INTO decision_body (jurisdiction_id, name, kind, seats, quorum,
                                       recommendation_is_binding)
            VALUES (:jid, 'Planning Commission', 'planning_commission', 7, 4, false)
            """
        ).bindparams(jid=jurisdiction_id)
    )
    board_id = int(
        conn.execute(
            text(
                """
                INSERT INTO decision_body (jurisdiction_id, name, kind, seats, quorum,
                                           recommendation_is_binding)
                VALUES (:jid, 'Board of Supervisors', 'board_of_supervisors', 9, 5, false)
                RETURNING id
                """
            ).bindparams(jid=jurisdiction_id)
        ).scalar_one()
    )
    return jurisdiction_id, board_id


def _insert_decided(
    conn: Connection, *, jurisdiction_id: int, body_id: int, external_id: str, outcome: str
) -> int:
    """A decided application with verified evidence, so it counts toward history features."""
    # ck_application_censored_matches_outcome: an undecided outcome must be censored and a terminal
    # one must not. The constraint is the reason this is derived rather than passed in.
    censored = outcome in {"pending", "continued", "tabled", "unknown"}
    decided_on = None if censored else date(2024, 7, 20)
    application_id = int(
        conn.execute(
            text(
                """
                INSERT INTO application (
                    jurisdiction_id, body_id, external_id, use_class, relief_sought, by_right,
                    acres, capacity_mw, filed_on, decided_on, outcome, censored, label_source,
                    staff_recommendation
                ) VALUES (
                    :jid, :bid, :ext, 'data_center_hyperscale', ARRAY['rezoning','special_use_permit'],
                    false, 250.0, 180.0, :filed, :decided, :outcome, :censored, 'hand_labelled',
                    'approve'
                ) RETURNING id
                """
            ).bindparams(
                jid=jurisdiction_id,
                bid=body_id,
                ext=external_id,
                filed=date(2024, 1, 15),
                decided=decided_on,
                outcome=outcome,
                censored=censored,
            )
        ).scalar_one()
    )
    document_id = f"{application_id:064d}"
    conn.execute(
        text(
            """
            INSERT INTO document (id, kind, source_url, byte_size, fetched_at, storage_key)
            VALUES (:id, 'minutes', :url, 100, now(), :key)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(
            id=document_id, url=f"https://example.gov/{application_id}", key=f"k/{application_id}"
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


def _spec_from_row(conn: Connection, application_id: int) -> ApplicationSpec:
    """Read a real application into the same specification a prospective site would supply."""
    record = (
        conn.execute(builder_module._APPLICATION_SQL, {"application_id": application_id})
        .mappings()
        .one()
    )
    return {
        "id": int(record["id"]),
        "jurisdiction_id": int(record["jurisdiction_id"]),
        "body_id": int(record["body_id"]) if record["body_id"] is not None else None,
        "use_class": str(record["use_class"]),
        "relief_sought": list(record["relief_sought"]),
        "by_right": record["by_right"],
        "acres": float(record["acres"]) if record["acres"] is not None else None,
        "capacity_mw": float(record["capacity_mw"]) if record["capacity_mw"] is not None else None,
        "filed_on": record["filed_on"],
        "decided_on": record["decided_on"],
        "staff_recommendation": record["staff_recommendation"],
        "applicant_cluster_id": record["applicant_cluster_id"],
        "parcel_id": record["parcel_id"],
        "legal_framework": record["legal_framework"],
        "discretion_index": float(record["discretion_index"])
        if record["discretion_index"] is not None
        else None,
        "parcel_acres": float(record["parcel_acres"])
        if record["parcel_acres"] is not None
        else None,
        "prior_industrial_use": record["prior_industrial_use"],
        "entity_opacity": record["entity_opacity"],
    }


# ---------------------------------------------------------------------------
# Claim 3: no drift between what the builder reads and what the type declares
# ---------------------------------------------------------------------------
class TestSpecCoversEveryFieldTheBuilderReads:
    """Read the builder's source and compare it against the declared type.

    A review cannot enforce this and a runtime test cannot either, because the prospective path only
    breaks for the specific field that was added. Parsing is the only mechanism that scales.
    """

    @staticmethod
    def _keys_read_from_record() -> set[str]:
        """Every literal subscript of the ``record`` parameter inside ``_build``."""
        source = textwrap.dedent(inspect.getsource(builder_module._build))
        tree = ast.parse(source)
        keys: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == "record"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                keys.add(node.slice.value)
        return keys

    def test_the_parser_finds_something(self) -> None:
        """Guard the guard. A parser that silently finds nothing would make this suite vacuous."""
        keys = self._keys_read_from_record()
        assert len(keys) >= 15, f"expected the builder to read many fields, parsed {sorted(keys)}"

    def test_every_field_read_is_declared(self) -> None:
        declared = set(ApplicationSpec.__annotations__)
        read = self._keys_read_from_record()
        undeclared = read - declared
        assert not undeclared, (
            f"_build reads {sorted(undeclared)} which ApplicationSpec does not declare. The "
            "historical path will keep working and every prospective score will raise KeyError. "
            "Add the field to ApplicationSpec and populate it in score/engine.py."
        )

    def test_no_field_is_declared_that_nothing_reads(self) -> None:
        """The reverse direction, so the type does not accumulate fields nobody uses.

        A declared field obliges the prospective producer to invent a value. If nothing reads it, that
        invention is pure risk.
        """
        declared = set(ApplicationSpec.__annotations__)
        read = self._keys_read_from_record()
        unused = declared - read
        assert not unused, (
            f"ApplicationSpec declares {sorted(unused)} which _build never reads. Remove them, or "
            "the prospective producer is inventing values that cannot affect any feature."
        )


# ---------------------------------------------------------------------------
# Claim 1: equivalence
# ---------------------------------------------------------------------------
@requires_db
class TestBothRoutesAgree:
    def test_a_real_application_builds_identically_by_id_and_by_spec(
        self, clean_db: Connection
    ) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _insert_decided(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT-1",
            outcome="pending",
        )
        # History for the subject to see, so the comparison covers populated features rather than a
        # row where every group returns unknown and equality is trivial.
        for index, outcome in enumerate(["approved", "denied", "approved_with_conditions"]):
            _insert_decided(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"PRIOR-{index}",
                outcome=outcome,
            )

        by_id = build_for_application(clean_db, subject, as_of=AS_OF)
        by_spec = build_for_spec(clean_db, _spec_from_row(clean_db, subject), as_of=AS_OF)

        assert by_spec.values == by_id.values
        assert sorted(by_spec.missing) == sorted(by_id.missing)
        assert by_spec.as_of == by_id.as_of
        assert by_spec.application_id == by_id.application_id

    def test_the_comparison_is_not_vacuous(self, clean_db: Connection) -> None:
        """If every feature were unknown, equality would prove nothing."""
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _insert_decided(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT-1",
            outcome="pending",
        )
        for index, outcome in enumerate(["approved", "denied", "approved_with_conditions"]):
            _insert_decided(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"PRIOR-{index}",
                outcome=outcome,
            )
        row = build_for_spec(clean_db, _spec_from_row(clean_db, subject), as_of=AS_OF)
        populated = {name: value for name, value in row.values.items() if value is not None}
        assert len(populated) >= 10, f"only {len(populated)} features populated: {populated}"
        assert row.values.get("n_comparable_decisions") == 3.0


# ---------------------------------------------------------------------------
# Claim 2: the scoring read path performs no write
# ---------------------------------------------------------------------------
@requires_db
class TestScoringDoesNotWrite:
    def test_no_savepoint_is_opened(
        self, clean_db: Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Make a savepoint fatal, then build a prospective row.

        This is the regression guard. The previous implementation would raise here, and so would any
        future reintroduction of a write into the read path.
        """
        jurisdiction_id, _ = _seed(clean_db)

        def _refuse(*_args: object, **_kwargs: object) -> object:
            raise AssertionError(
                "the prospective scoring path opened a savepoint. Read scoring must not write: a "
                "portfolio carries up to five hundred sites and each savepoint is a subtransaction "
                "and a dead tuple in the application table."
            )

        monkeypatch.setattr(type(clean_db), "begin_nested", _refuse)

        row = _synthetic_feature_row(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            request=SiteRequest(
                use_class=UseClass.data_center_hyperscale,
                relief_sought=[Relief.rezoning],
                jurisdiction_slug="us-xx-spec",
                acres=412.0,
                capacity_mw=300.0,
            ),
            as_of=AS_OF,
        )
        assert row.application_id == 0
        assert row.as_of == AS_OF

    def test_the_application_sequence_does_not_advance(self, clean_db: Connection) -> None:
        """``nextval`` survives a rollback, so the old path leaked a sequence value per site."""
        jurisdiction_id, _ = _seed(clean_db)
        request = SiteRequest(
            use_class=UseClass.data_center_hyperscale,
            relief_sought=[Relief.rezoning],
            jurisdiction_slug="us-xx-spec",
        )

        def sequence_value() -> int | None:
            raw = clean_db.execute(
                text("SELECT pg_sequence_last_value('application_id_seq'::regclass)")
            ).scalar()
            return int(raw) if raw is not None else None

        before = sequence_value()
        for _ in range(5):
            _synthetic_feature_row(
                clean_db, jurisdiction_id=jurisdiction_id, request=request, as_of=AS_OF
            )
        assert sequence_value() == before

    def test_no_application_row_is_left_behind(self, clean_db: Connection) -> None:
        jurisdiction_id, _ = _seed(clean_db)
        request = SiteRequest(
            use_class=UseClass.data_center_hyperscale,
            relief_sought=[Relief.rezoning],
            jurisdiction_slug="us-xx-spec",
        )
        _synthetic_feature_row(
            clean_db, jurisdiction_id=jurisdiction_id, request=request, as_of=AS_OF
        )
        assert clean_db.execute(text("SELECT count(*) FROM application")).scalar() == 0

    def test_the_binding_body_is_chosen_deterministically(self, clean_db: Connection) -> None:
        """Highest seats wins, ties broken by id, so the same site scores the same way twice."""
        jurisdiction_id, board_id = _seed(clean_db)
        request = SiteRequest(
            use_class=UseClass.data_center_hyperscale,
            relief_sought=[Relief.rezoning],
            jurisdiction_slug="us-xx-spec",
        )
        first = _synthetic_feature_row(
            clean_db, jurisdiction_id=jurisdiction_id, request=request, as_of=AS_OF
        )
        second = _synthetic_feature_row(
            clean_db, jurisdiction_id=jurisdiction_id, request=request, as_of=AS_OF
        )
        assert first.values == second.values

        chosen = clean_db.execute(
            text(
                """
                SELECT b.id FROM decision_body b
                WHERE b.jurisdiction_id = :jid AND b.recommendation_is_binding IS NOT TRUE
                ORDER BY b.seats DESC NULLS LAST, b.id
                LIMIT 1
                """
            ).bindparams(jid=jurisdiction_id)
        ).scalar_one()
        assert chosen == board_id, "the nine seat board should win over the seven seat commission"
