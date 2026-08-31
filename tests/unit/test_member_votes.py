"""Per member votes, and the three features that had no route to a value.

`board_composition_score`, `swing_seat_count` and `turnover_since_last_comparable` are all computed from
the `vote` and `decision_maker` tables. Nothing wrote to either from a hand label: `DecisionLabel`
carried `vote_for`, `vote_against` and `vote_abstain`, which are aggregates, and the loader stored them
on the application row. So those three features returned unknown for every row no matter how much
labelling was done, and the only route to them was the extraction pipeline, which needs a language model
key nobody has configured.

`member_votes` closes that. The tests here are in three groups.

**Validation.** A label may carry the aggregate tally, the per member list, or both. When it carries both
they are two transcriptions of one event, so a disagreement means one is wrong, and loading both without
checking would put a contradiction into the training set and into the evidence a customer reads.

**Loading.** Minutes spell the same person several ways. Matching on the normalised name is what makes
the vote history work at all, because two spellings of one supervisor would otherwise look like two
members with half the record each. Every spelling seen is kept.

**The features.** The point of the exercise. Asserted by building features and requiring a number where
there was None before.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, text

from auspice.pipeline.features import build_for_application
from auspice.pipeline.graph.labels import DecisionLabel, MemberVote
from tests.conftest import requires_db


def _label(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "label_id": "test-board-votes-2024",
        "jurisdiction": "us-va-loudoun",
        "labelled_by": "Test Labeller",
        "labelled_on": date(2026, 8, 31),
        "body": "board_of_supervisors",
        "use_class": "data_center_hyperscale",
        "relief_sought": ["rezoning"],
        "decided_on": date(2024, 3, 12),
        "outcome": "approved",
        "citations": [
            {
                "url": "https://www.loudoun.gov/minutes/2024-03-12",
                "document_title": "Board of Supervisors minutes, 12 March 2024",
                "quote": "The motion carried on a vote of five to three, with one absent.",
                "retrieved_on": date(2026, 8, 31),
                "kind": "primary",
            }
        ],
    }
    base.update(overrides)
    return base


def _members(*positions: str) -> list[dict[str, object]]:
    return [
        {"name": f"Supervisor {chr(65 + index)}", "position": position}
        for index, position in enumerate(positions)
    ]


class TestValidation:
    def test_a_label_with_no_member_votes_is_still_valid(self) -> None:
        """The field is optional. Most minutes do not name who voted which way."""
        assert DecisionLabel.model_validate(_label()).member_votes == []

    def test_member_votes_load_without_an_aggregate_tally(self) -> None:
        row = DecisionLabel.model_validate(
            _label(member_votes=_members("for", "for", "for", "against", "abstain"))
        )
        assert len(row.member_votes) == 5

    def test_an_agreeing_tally_and_list_are_both_accepted(self) -> None:
        row = DecisionLabel.model_validate(
            _label(
                vote_for=3,
                vote_against=1,
                vote_abstain=1,
                member_votes=_members("for", "for", "for", "against", "abstain"),
            )
        )
        assert row.vote_for == 3
        assert len(row.member_votes) == 5

    @pytest.mark.parametrize(
        ("field", "value"),
        [("vote_for", 4), ("vote_against", 2), ("vote_abstain", 0)],
    )
    def test_a_disagreement_between_the_two_transcriptions_is_refused(
        self, field: str, value: int
    ) -> None:
        """One vote, two records. If they disagree one of them is wrong."""
        payload = _label(
            vote_for=3,
            vote_against=1,
            vote_abstain=1,
            member_votes=_members("for", "for", "for", "against", "abstain"),
        )
        payload[field] = value
        with pytest.raises(ValidationError, match="disagree"):
            DecisionLabel.model_validate(payload)

    def test_the_same_member_twice_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="appears twice"):
            DecisionLabel.model_validate(
                _label(
                    member_votes=[
                        {"name": "Supervisor A", "position": "for"},
                        {"name": "supervisor a  ", "position": "against"},
                    ]
                )
            )

    def test_an_unknown_position_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="vote position must be one of"):
            DecisionLabel.model_validate(
                _label(member_votes=[{"name": "Supervisor A", "position": "maybe"}])
            )

    @pytest.mark.parametrize("position", ["for", "against", "abstain", "absent", "recused"])
    def test_every_schema_position_is_accepted(self, position: str) -> None:
        row = DecisionLabel.model_validate(
            _label(member_votes=[{"name": "Supervisor A", "position": position}])
        )
        assert row.member_votes[0].position == position

    def test_absent_and_recused_do_not_count_toward_the_tally(self) -> None:
        """They are not votes. Counting them would make the tally disagree with the minutes.

        The tally is two to one rather than one to one, because a tie is not an approval and the
        pre-existing outcome validator correctly refuses that combination.
        """
        row = DecisionLabel.model_validate(
            _label(
                vote_for=2,
                vote_against=1,
                member_votes=_members("for", "for", "against", "absent", "recused"),
            )
        )
        assert len(row.member_votes) == 5
        assert row.vote_for == 2
        assert sum(1 for v in row.member_votes if v.position in {"absent", "recused"}) == 2

    def test_a_term_starting_after_the_decision_is_refused(self) -> None:
        """Otherwise the row loads, looks complete, and quietly contributes nothing to the features."""
        with pytest.raises(ValidationError, match="cannot have voted on it"):
            DecisionLabel.model_validate(
                _label(
                    member_votes=[
                        {
                            "name": "Supervisor A",
                            "position": "for",
                            "term_start": date(2025, 1, 1),
                        }
                    ]
                )
            )

    def test_a_term_ending_before_the_decision_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="cannot have voted on it"):
            DecisionLabel.model_validate(
                _label(
                    member_votes=[
                        {"name": "Supervisor A", "position": "for", "term_end": date(2023, 1, 1)}
                    ]
                )
            )

    def test_a_term_covering_the_decision_is_accepted(self) -> None:
        row = DecisionLabel.model_validate(
            _label(
                member_votes=[
                    {
                        "name": "Supervisor A",
                        "position": "for",
                        "term_start": date(2020, 1, 1),
                        "term_end": date(2028, 1, 1),
                        "seat": "Broad Run District",
                    }
                ]
            )
        )
        assert row.member_votes[0].seat == "Broad Run District"

    def test_an_inverted_term_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="term_end precedes term_start"):
            MemberVote.model_validate(
                {
                    "name": "Supervisor A",
                    "position": "for",
                    "term_start": date(2024, 1, 1),
                    "term_end": date(2020, 1, 1),
                }
            )

    def test_an_unknown_field_is_refused(self) -> None:
        """extra=forbid, so a typo in a key is caught rather than silently dropped."""
        with pytest.raises(ValidationError):
            MemberVote.model_validate({"name": "Supervisor A", "position": "for", "postion": "for"})


# ---------------------------------------------------------------------------
# Loading, and the features it unblocks
# ---------------------------------------------------------------------------
def _seed(conn: Connection) -> tuple[int, int]:
    jurisdiction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework,
                                          discretion_index, data_depth)
                VALUES ('us-va-votes', 'Votes County', 'county', 'US', 'VA', 'dillons_rule', 0.6, 0)
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


def _decided_application(
    conn: Connection,
    *,
    jurisdiction_id: int,
    body_id: int,
    external_id: str,
    outcome: str,
    decided_on: date,
) -> int:
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
                filed=date(decided_on.year - 1, 6, 1),
                decided=None
                if outcome in {"pending", "continued", "tabled", "unknown"}
                else decided_on,
                outcome=outcome,
                censored=outcome in {"pending", "continued", "tabled", "unknown"},
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
            id=document_id, url=f"https://x.gov/{application_id}", key=f"k/{application_id}"
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
            sid=application_id, doc=document_id, quote=f"The board decided {external_id} of record."
        )
    )
    return application_id


def _member(conn: Connection, *, body_id: int, name: str, term_start: date | None = None) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO decision_maker (body_id, display_name, name_variants, term_start)
                VALUES (:bid, :name, ARRAY[:name], :start)
                RETURNING id
                """
            ).bindparams(bid=body_id, name=name, start=term_start)
        ).scalar_one()
    )


def _vote(conn: Connection, *, application_id: int, maker_id: int, position: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO vote (application_id, maker_id, position)
            VALUES (:aid, :mid, :pos)
            """
        ).bindparams(aid=application_id, mid=maker_id, pos=position)
    )


@requires_db
class TestTheFeaturesNowPopulate:
    def test_board_composition_is_unknown_without_vote_records(self, clean_db: Connection) -> None:
        """The state before this work: unknown, not neutral, for every row."""
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            outcome="pending",
            decided_on=date(2024, 6, 1),
        )
        row = build_for_application(clean_db, subject, as_of=date(2024, 6, 1))
        assert row.values["board_composition_score"] is None
        assert row.values["swing_seat_count"] is None

    def test_vote_records_produce_a_composition_score(self, clean_db: Connection) -> None:
        """The point of the exercise. A number where there was None."""
        jurisdiction_id, body_id = _seed(clean_db)

        # Three prior decisions, so members have a history to compute a rate from.
        priors = [
            _decided_application(
                clean_db,
                jurisdiction_id=jurisdiction_id,
                body_id=body_id,
                external_id=f"PRIOR-{index}",
                outcome=outcome,
                decided_on=date(2023, 3 + index, 1),
            )
            for index, outcome in enumerate(["approved", "denied", "approved"])
        ]
        always_for = _member(clean_db, body_id=body_id, name="Supervisor Yes")
        always_against = _member(clean_db, body_id=body_id, name="Supervisor No")
        swings = _member(clean_db, body_id=body_id, name="Supervisor Maybe")

        for application_id in priors:
            _vote(clean_db, application_id=application_id, maker_id=always_for, position="for")
            _vote(
                clean_db, application_id=application_id, maker_id=always_against, position="against"
            )
        _vote(clean_db, application_id=priors[0], maker_id=swings, position="for")
        _vote(clean_db, application_id=priors[1], maker_id=swings, position="against")

        subject = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            outcome="pending",
            decided_on=date(2024, 6, 1),
        )
        row = build_for_application(clean_db, subject, as_of=date(2024, 6, 1))

        score = row.values["board_composition_score"]
        assert score is not None, "the feature must populate once vote records exist"
        # Rates are 1.0, 0.0 and 0.5. Mean 0.5, centred on zero gives 0.0.
        assert float(score) == pytest.approx(0.0, abs=0.001)

        swing = row.values["swing_seat_count"]
        assert swing is not None
        assert float(swing) == 1.0, "only the member with a 0.5 rate is a swing seat"

    def test_a_vote_after_the_as_of_date_cannot_move_the_score(self, clean_db: Connection) -> None:
        """Same leakage discipline as the history features. The query filters on decided_on."""
        jurisdiction_id, body_id = _seed(clean_db)
        early = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="EARLY",
            outcome="approved",
            decided_on=date(2023, 3, 1),
        )
        late = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="LATE",
            outcome="denied",
            decided_on=date(2025, 3, 1),
        )
        member = _member(clean_db, body_id=body_id, name="Supervisor Yes")
        _vote(clean_db, application_id=early, maker_id=member, position="for")
        _vote(clean_db, application_id=late, maker_id=member, position="against")

        subject = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            outcome="pending",
            decided_on=date(2024, 6, 1),
        )
        row = build_for_application(clean_db, subject, as_of=date(2024, 6, 1))
        score = row.values["board_composition_score"]
        assert score is not None
        # Only the 2023 vote is visible, so the rate is 1.0 and the centred score is 1.0.
        assert float(score) == pytest.approx(1.0, abs=0.001)


@requires_db
class TestLoaderWritesMembersAndVotes:
    def test_a_label_with_member_votes_creates_both_rows(self, clean_db: Connection) -> None:
        from auspice.pipeline.graph import labels as labels_module

        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="SUBJECT",
            outcome="approved",
            decided_on=date(2024, 3, 12),
        )
        row = DecisionLabel.model_validate(
            _label(member_votes=_members("for", "for", "against"), vote_for=2, vote_against=1)
        )
        written = labels_module._record_member_votes(
            clean_db, application_id=application_id, body_id=body_id, row=row
        )
        assert written == 3
        assert (
            clean_db.execute(
                text("SELECT count(*) FROM vote WHERE application_id = :a"),
                {"a": application_id},
            ).scalar()
            == 3
        )
        assert (
            clean_db.execute(
                text("SELECT count(*) FROM decision_maker WHERE body_id = :b"), {"b": body_id}
            ).scalar()
            == 3
        )

    def test_a_second_spelling_reuses_the_member_and_keeps_both_names(
        self, clean_db: Connection
    ) -> None:
        """Two spellings of one supervisor would otherwise be two members with half the record each."""
        from auspice.pipeline.graph import labels as labels_module

        jurisdiction_id, body_id = _seed(clean_db)
        first = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="ONE",
            outcome="approved",
            decided_on=date(2024, 3, 12),
        )
        second = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="TWO",
            outcome="denied",
            decided_on=date(2024, 6, 12),
        )

        labels_module._record_member_votes(
            clean_db,
            application_id=first,
            body_id=body_id,
            row=DecisionLabel.model_validate(
                _label(member_votes=[{"name": "Supervisor Ellery", "position": "for"}], vote_for=1)
            ),
        )
        labels_module._record_member_votes(
            clean_db,
            application_id=second,
            body_id=body_id,
            row=DecisionLabel.model_validate(
                _label(
                    label_id="test-second-2024",
                    outcome="denied",
                    decided_on=date(2024, 6, 12),
                    member_votes=[{"name": "supervisor ELLERY", "position": "against"}],
                    vote_against=1,
                )
            ),
        )

        makers = clean_db.execute(
            text("SELECT display_name, name_variants FROM decision_maker WHERE body_id = :b"),
            {"b": body_id},
        ).all()
        assert len(makers) == 1, "one person, however the minutes spelled them"
        assert set(makers[0].name_variants) == {"Supervisor Ellery", "supervisor ELLERY"}
        assert clean_db.execute(text("SELECT count(*) FROM vote")).scalar() == 2

    def test_a_term_is_widened_never_narrowed(self, clean_db: Connection) -> None:
        """A later label showing an earlier vote means the recorded term was incomplete."""
        from auspice.pipeline.graph import labels as labels_module

        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="ONE",
            outcome="approved",
            decided_on=date(2024, 3, 12),
        )
        _member(clean_db, body_id=body_id, name="Supervisor Ellery", term_start=date(2022, 1, 1))

        labels_module._record_member_votes(
            clean_db,
            application_id=application_id,
            body_id=body_id,
            row=DecisionLabel.model_validate(
                _label(
                    member_votes=[
                        {
                            "name": "Supervisor Ellery",
                            "position": "for",
                            "term_start": date(2020, 1, 1),
                            "term_end": date(2028, 1, 1),
                        }
                    ],
                    vote_for=1,
                )
            ),
        )
        member = (
            clean_db.execute(
                text("SELECT term_start, term_end FROM decision_maker WHERE body_id = :b"),
                {"b": body_id},
            )
            .mappings()
            .one()
        )
        assert member["term_start"] == date(2020, 1, 1), "the earlier start is the better one"
        assert member["term_end"] == date(2028, 1, 1)

    def test_no_member_votes_writes_nothing(self, clean_db: Connection) -> None:
        from auspice.pipeline.graph import labels as labels_module

        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="ONE",
            outcome="approved",
            decided_on=date(2024, 3, 12),
        )
        written = labels_module._record_member_votes(
            clean_db,
            application_id=application_id,
            body_id=body_id,
            row=DecisionLabel.model_validate(_label()),
        )
        assert written == 0
        assert clean_db.execute(text("SELECT count(*) FROM vote")).scalar() == 0

    def test_an_unmatched_body_writes_nothing_rather_than_raising(
        self, clean_db: Connection
    ) -> None:
        """A label naming a body the registry does not hold is already reported by the loader."""
        from auspice.pipeline.graph import labels as labels_module

        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _decided_application(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            body_id=body_id,
            external_id="ONE",
            outcome="approved",
            decided_on=date(2024, 3, 12),
        )
        written = labels_module._record_member_votes(
            clean_db,
            application_id=application_id,
            body_id=None,
            row=DecisionLabel.model_validate(_label(member_votes=_members("for"), vote_for=1)),
        )
        assert written == 0
