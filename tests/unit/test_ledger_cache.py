"""The verification cache.

``verify`` pulls every payload into Python and rehashes it, and it sat behind the unauthenticated accuracy
page, so its cost grew with the ledger. ``verify_cached`` reuses a previous result when nothing has
changed, keyed on a digest Postgres computes from the live rows.

A cache in front of an integrity check is dangerous in exactly one way: it could return a stale "intact"
after someone tampered. Every test here is about that. The performance property is secondary and is
asserted last.

Why there is no persisted checkpoint, since that is what a reader might expect: a row saying "verified up
to sequence N" is writable, and anyone who can write it can make the verifier skip the region they
tampered with. That converts the ledger's one hard property into a property of whatever protects that row.
The cache key is derived from the data on every call instead, so there is nothing to poison.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Connection, text

from auspice import ledger
from tests.conftest import requires_db
from tests.unit.test_ledger import _payload, _seed_prediction

pytestmark = requires_db


@pytest.fixture(autouse=True)
def _empty_cache() -> Any:
    """Every test starts from a cold cache, and leaves one behind.

    The cache is process wide by design. Without this, a test that populates it changes the result of the
    next one, and the failure would look like a flake rather than pollution.
    """
    ledger.reset_verification_cache()
    yield
    ledger.reset_verification_cache()


def _publish(conn: Connection, count: int, *, start: int = 0) -> None:
    """Append ``count`` entries, numbered from ``start``.

    The offset matters. ``_seed_prediction`` derives a model_run version from the index, and model_run
    carries a unique constraint on kind, version and dataset hash, so publishing a second batch from zero
    fails on a duplicate key rather than on anything to do with the ledger.
    """
    for index in range(start, start + count):
        ledger.publish(conn, prediction_id=_seed_prediction(conn, index), payload=_payload(index))


class TestItCannotMaskTampering:
    def test_a_payload_edit_after_a_clean_verification_is_still_caught(
        self, clean_db: Connection
    ) -> None:
        """The whole point. Warm the cache on a clean chain, then tamper, then ask again."""
        _publish(clean_db, 5)
        assert ledger.verify_cached(clean_db).ok is True

        clean_db.execute(
            text(
                """
                UPDATE ledger_entry SET payload = payload || '{"tampered": true}'::jsonb
                WHERE seq = (SELECT min(seq) + 1 FROM ledger_entry)
                """
            )
        )

        assert ledger.verify_cached(clean_db).ok is False, (
            "the cache returned a stale intact verdict after a payload was edited. The digest key is "
            "supposed to change with any payload, which is the only reason caching this is safe."
        )

    def test_a_mid_chain_edit_is_caught_even_though_the_head_is_untouched(
        self, clean_db: Connection
    ) -> None:
        # A cache keyed only on the head hash and the row count would miss this, because neither changes
        # when an earlier payload is edited. That was the first design and it was wrong.
        _publish(clean_db, 6)
        before = ledger.verify_cached(clean_db)
        head_before = before.head

        clean_db.execute(
            text(
                """
                UPDATE ledger_entry SET payload = payload || '{"x": 1}'::jsonb
                WHERE seq = (SELECT min(seq) + 2 FROM ledger_entry)
                """
            )
        )
        after = ledger.verify_cached(clean_db)

        assert after.ok is False
        # Proof the naive key would have collided: the head hash is unchanged and so is the count.
        row = (
            clean_db.execute(
                text(
                    "SELECT count(*) AS n, max(entry_hash) FILTER (WHERE seq = (SELECT max(seq) FROM ledger_entry)) AS h FROM ledger_entry"
                )
            )
            .mappings()
            .one()
        )
        assert int(row["n"]) == 6
        assert str(row["h"]) == head_before

    def test_a_tail_deletion_after_a_clean_verification_is_still_caught(
        self, clean_db: Connection
    ) -> None:
        _publish(clean_db, 4)
        assert ledger.verify_cached(clean_db).ok is True
        clean_db.execute(
            text("DELETE FROM ledger_entry WHERE seq = (SELECT max(seq) FROM ledger_entry)")
        )
        assert ledger.verify_cached(clean_db).ok is False

    def test_a_new_entry_invalidates_the_cache(self, clean_db: Connection) -> None:
        _publish(clean_db, 2)
        first = ledger.verify_cached(clean_db)
        assert first.entries == 2

        _publish(clean_db, 1, start=2)
        second = ledger.verify_cached(clean_db)
        assert second.entries == 3, "publishing must not be hidden by a cached count"
        assert second.head != first.head

    def test_a_failure_is_never_cached(self, clean_db: Connection) -> None:
        """A repaired ledger must stop reporting a break without a process restart."""
        _publish(clean_db, 3)
        clean_db.execute(
            text(
                """
                UPDATE ledger_entry SET entry_hash = repeat('0', 64)
                WHERE seq = (SELECT max(seq) FROM ledger_entry)
                """
            )
        )
        assert ledger.verify_cached(clean_db).ok is False

        # Repair it by recomputing the correct link, the way an operator restoring from the published
        # export would.
        row = (
            clean_db.execute(
                text(
                    """
                SELECT seq, prev_hash, payload_hash FROM ledger_entry
                WHERE seq = (SELECT max(seq) FROM ledger_entry)
                """
                )
            )
            .mappings()
            .one()
        )
        clean_db.execute(
            text("UPDATE ledger_entry SET entry_hash = :h WHERE seq = :s").bindparams(
                h=ledger.link(str(row["prev_hash"]), str(row["payload_hash"])), s=int(row["seq"])
            )
        )
        assert ledger.verify_cached(clean_db).ok is True


class TestItAgreesWithTheUncachedWalk:
    @pytest.mark.parametrize("count", [0, 1, 7])
    def test_same_verdict_and_same_head(self, clean_db: Connection, count: int) -> None:
        _publish(clean_db, count)
        ledger.reset_verification_cache()
        full = ledger.verify(clean_db)
        cached = ledger.verify_cached(clean_db)
        assert cached.ok == full.ok
        assert cached.head == full.head
        assert cached.entries == full.entries
        assert cached.scope == "full", "a cached full walk is still a full walk"


class TestItActuallyAvoidsTheWork:
    def test_a_repeat_call_does_not_rehash_every_payload(
        self, clean_db: Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Counts calls to hash_payload, which is the expensive part, rather than timing anything."""
        _publish(clean_db, 8)
        ledger.reset_verification_cache()

        calls: list[int] = []
        original = ledger.hash_payload

        def counting(payload: dict[str, Any]) -> str:
            calls.append(1)
            return original(payload)

        monkeypatch.setattr(ledger.chain, "hash_payload", counting)

        ledger.verify_cached(clean_db)
        cold = len(calls)
        calls.clear()
        ledger.verify_cached(clean_db)
        warm = len(calls)

        assert cold >= 8, f"the cold call should hash every payload, it hashed {cold}"
        assert warm == 0, f"the warm call should hash nothing, it hashed {warm}"
