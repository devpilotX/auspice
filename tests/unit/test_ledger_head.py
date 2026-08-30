"""The constant cost ledger probe.

``verify`` reads every row and rehashes every payload, so its cost grows with the ledger. The health
endpoint called it, and that endpoint is unauthenticated and deliberately exempt from rate limiting, so
the denial of service surface grew in exact proportion to the one metric the specification says must
never stall. ``verify_head`` is the cheap check that replaced it there.

The property these tests are for is not that the cheap check is cheap. It is that being cheap did not
make it wrong about the two things it claims to catch, and that it is honest about the one it does not.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Connection, text

from auspice import ledger
from tests.conftest import requires_db

# Imported rather than reimplemented. The prediction table carries several not null columns including a
# jurisdiction foreign key, and a second copy of that insert here would be a second thing to update when
# the schema moves. A first attempt at writing it fresh failed on jurisdiction_id, which is the argument
# for reuse: the helper already knows what the table requires.
from tests.unit.test_ledger import _payload, _seed_prediction

pytestmark = requires_db


def _publish(conn: Connection, count: int) -> None:
    """Append ``count`` entries, each with its own prediction row and a distinct payload."""
    for index in range(count):
        prediction_id = _seed_prediction(conn, index)
        ledger.publish(conn, prediction_id=prediction_id, payload=_payload(index))


class TestItAgreesWithTheFullWalk:
    def test_on_an_empty_ledger(self, clean_db: Connection) -> None:
        full = ledger.verify(clean_db)
        head = ledger.verify_head(clean_db)
        assert full.ok is True
        assert head.ok is True
        assert head.scope == "head"
        assert full.scope == "full"

    def test_on_an_intact_chain(self, clean_db: Connection) -> None:
        _publish(clean_db, 5)
        full = ledger.verify(clean_db)
        head = ledger.verify_head(clean_db)
        assert full.ok is True
        assert head.ok is True
        # The head hash is the one value both must agree on, because it commits every entry before it.
        assert head.head == full.head

    def test_the_report_says_which_check_produced_it(self, clean_db: Connection) -> None:
        # A shallow ok is not a full ok, and without this field the difference is invisible exactly where
        # someone would quote it.
        _publish(clean_db, 2)
        assert ledger.verify_head(clean_db).as_dict()["scope"] == "head"
        assert ledger.verify(clean_db).as_dict()["scope"] == "full"


class TestItCatchesWhatItClaimsTo:
    def test_a_tail_deletion(self, clean_db: Connection) -> None:
        """The deletion someone would actually make, because the newest calls are the disproved ones."""
        _publish(clean_db, 4)
        clean_db.execute(
            text("DELETE FROM ledger_entry WHERE seq = (SELECT max(seq) FROM ledger_entry)")
        )

        head = ledger.verify_head(clean_db)
        assert head.ok is False
        assert head.reason is not None
        assert "deleted from the end" in head.reason
        # The full walk must reach the same verdict, which is the point of sharing one detector.
        assert ledger.verify(clean_db).ok is False

    def test_a_deletion_of_the_entire_ledger(self, clean_db: Connection) -> None:
        # An empty table is intact only if nothing was ever issued. The sequence remembers otherwise.
        _publish(clean_db, 3)
        clean_db.execute(text("DELETE FROM ledger_entry"))
        assert ledger.verify_head(clean_db).ok is False

    def test_corruption_of_the_most_recent_payload(self, clean_db: Connection) -> None:
        _publish(clean_db, 3)
        clean_db.execute(
            text(
                """
                UPDATE ledger_entry SET payload = payload || '{"tampered": true}'::jsonb
                WHERE seq = (SELECT max(seq) FROM ledger_entry)
                """
            )
        )
        head = ledger.verify_head(clean_db)
        assert head.ok is False
        assert head.reason is not None
        assert "no longer hashes" in head.reason

    def test_corruption_of_the_most_recent_entry_hash(self, clean_db: Connection) -> None:
        _publish(clean_db, 3)
        clean_db.execute(
            text(
                """
                UPDATE ledger_entry SET entry_hash = repeat('0', 64)
                WHERE seq = (SELECT max(seq) FROM ledger_entry)
                """
            )
        )
        head = ledger.verify_head(clean_db)
        assert head.ok is False
        assert head.reason is not None
        assert "not the link" in head.reason


class TestItIsHonestAboutWhatItMisses:
    def test_mid_chain_tampering_is_missed_by_the_probe_and_caught_by_the_walk(
        self, clean_db: Connection
    ) -> None:
        """This is the documented limitation, asserted so it stays documented.

        If a future change makes the cheap probe catch this too, this test fails and the docstring on
        ``verify_head`` has to be corrected. That is the intended outcome: the comment and the behaviour
        cannot drift apart silently.
        """
        _publish(clean_db, 5)
        # Tamper with an entry that is not the last one.
        clean_db.execute(
            text(
                """
                UPDATE ledger_entry SET payload = payload || '{"tampered": true}'::jsonb
                WHERE seq = (SELECT min(seq) + 1 FROM ledger_entry)
                """
            )
        )

        assert ledger.verify(clean_db).ok is False, "the full walk must catch mid chain tampering"
        assert ledger.verify_head(clean_db).ok is True, (
            "the cheap probe is documented as not catching this. If it now does, update the docstring "
            "on verify_head and this test, rather than leaving the two disagreeing."
        )


class TestCostIsConstant:
    def test_the_probe_reads_one_row_regardless_of_size(
        self, clean_db: Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Counts statements rather than timing, because a timing assertion on a local database flakes."""
        _publish(clean_db, 12)

        executed: list[str] = []
        original = Connection.execute

        def counting(self: Connection, statement: Any, *args: Any, **kwargs: Any) -> Any:
            # The whole statement, not a prefix. An earlier version truncated to 60 characters, which cut
            # off the LIMIT clause the assertion below looks for and failed for a reason that had nothing
            # to do with the code under test.
            executed.append(" ".join(str(statement).split()))
            return original(self, statement, *args, **kwargs)

        monkeypatch.setattr(Connection, "execute", counting)
        ledger.verify_head(clean_db)
        head_statements = list(executed)

        executed.clear()
        ledger.verify(clean_db)
        full_statements = list(executed)

        # Two statements: the head row and the sequence check. Constant, whatever the ledger holds.
        assert len(head_statements) == 2, f"expected two statements, got {head_statements}"
        # The row cap is what makes it constant, so assert the SQL actually carries one.
        assert any("LIMIT" in statement.upper() for statement in head_statements), (
            f"the head probe must bound its result set, sent: {head_statements}"
        )
        # The full walk selects without a limit. If this ever stops being true the probe has lost its
        # reason to exist and this whole module should be reconsidered.
        assert not any("LIMIT" in statement.upper() for statement in full_statements[:1])
