"""The unauthenticated public endpoints.

Both of these served unbounded work. ``/v1/public/accuracy`` verified the whole ledger and materialised
every payload to count four things, and ``/v1/public/ledger`` assembled the entire record into one string
before sending it. Neither is behind a key, so the cost of asking grew with the ledger: the denial of
service surface grew at the same rate as the moat.

The record itself is not truncated and must not be. Section 5.3 makes it public and complete, and a
publisher that decides how much of its own accuracy record to show has given up the thing the record is
for. What changed is how it is computed and sent, not how much of it exists.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from auspice import ledger
from tests.conftest import requires_db
from tests.unit.test_ledger import _payload, _seed_prediction

pytestmark = requires_db


@pytest.fixture
def client(clean_db: Connection) -> Iterator[TestClient]:
    """A client whose requests run against the test transaction, not against the real database.

    This override is load bearing and its absence is silent. ``app.deps.get_connection`` opens its own
    connection through ``transaction()``, which uses the non test engine, so a ``TestClient`` request reads
    the ``auspice`` database while the ``clean_db`` fixture writes to ``auspice_test`` inside a transaction
    that is rolled back. Without the override these tests published four entries and the endpoint reported
    two, from leftover rows in a different database, and every assertion about counts was meaningless while
    looking like a bug in the endpoint.

    Yielding the same connection also means the endpoint sees uncommitted writes, which is what makes the
    rollback isolation work.
    """
    from app.deps import get_connection
    from app.main import app

    # A generator function, not a lambda returning an iterator. FastAPI inspects the dependency: a
    # generator function is a yield dependency and the yielded value is injected, while anything else is
    # treated as a plain callable and its return value is injected directly. The lambda form produced
    # `AttributeError: 'list_iterator' object has no attribute 'execute'`, because the handler received
    # the iterator rather than the connection.
    def _use_the_test_connection() -> Iterator[Connection]:
        yield clean_db

    app.dependency_overrides[get_connection] = _use_the_test_connection
    try:
        # No lifespan. These endpoints do not need the serving models, and the lifespan would fit them.
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_connection, None)


@pytest.fixture(autouse=True)
def _cold_cache() -> None:
    ledger.reset_verification_cache()


def _publish(conn: Connection, count: int, *, start: int = 0) -> None:
    for index in range(start, start + count):
        ledger.publish(conn, prediction_id=_seed_prediction(conn, index), payload=_payload(index))


class TestTheLedgerExport:
    def test_it_streams_one_line_per_entry(self, clean_db: Connection, client: TestClient) -> None:
        _publish(clean_db, 4)
        response = client.get("/v1/public/ledger")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        lines = [line for line in response.text.splitlines() if line.strip()]
        assert len(lines) == 4

    def test_every_line_is_independently_parseable(
        self, clean_db: Connection, client: TestClient
    ) -> None:
        """Newline delimited means a verifier can read it without holding the whole file."""
        import json

        _publish(clean_db, 3)
        for line in client.get("/v1/public/ledger").text.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            # The fields a third party needs to recompute the chain themselves.
            for field in ("seq", "payload", "payload_hash", "prev_hash", "entry_hash"):
                assert field in entry

    def test_the_export_still_matches_the_in_memory_form(
        self, clean_db: Connection, client: TestClient
    ) -> None:
        # export_jsonl now delegates to the streamer, so the CLI and the endpoint cannot disagree about
        # the bytes. A consumer who verified hashes against one and not the other would be misled.
        _publish(clean_db, 3)
        assert client.get("/v1/public/ledger").text == ledger.export_jsonl(clean_db)

    def test_after_skips_earlier_entries(self, clean_db: Connection, client: TestClient) -> None:
        import json

        _publish(clean_db, 5)
        lines = [
            json.loads(line)
            for line in client.get("/v1/public/ledger?after=2").text.splitlines()
            if line.strip()
        ]
        assert [entry["seq"] for entry in lines] == [3, 4, 5]

    def test_limit_caps_the_slice(self, clean_db: Connection, client: TestClient) -> None:
        import json

        _publish(clean_db, 5)
        lines = [
            json.loads(line)
            for line in client.get("/v1/public/ledger?limit=2").text.splitlines()
            if line.strip()
        ]
        assert [entry["seq"] for entry in lines] == [1, 2]

    def test_the_default_is_everything(self, clean_db: Connection, client: TestClient) -> None:
        # The important one. A public record with a silent default page size is not a public record.
        _publish(clean_db, 12)
        lines = [line for line in client.get("/v1/public/ledger").text.splitlines() if line.strip()]
        assert len(lines) == 12

    def test_a_nonsense_slice_is_refused_rather_than_clamped(self, client: TestClient) -> None:
        assert client.get("/v1/public/ledger?after=-1").status_code == 422
        assert client.get("/v1/public/ledger?limit=0").status_code == 422


class TestCacheValidators:
    def test_the_export_carries_an_etag(self, clean_db: Connection, client: TestClient) -> None:
        _publish(clean_db, 2)
        response = client.get("/v1/public/ledger")
        assert response.headers.get("etag") is not None
        assert response.headers.get("cache-control") == "public, no-cache"

    def test_the_accuracy_page_carries_an_etag(
        self, clean_db: Connection, client: TestClient
    ) -> None:
        _publish(clean_db, 2)
        response = client.get("/v1/public/accuracy")
        assert response.status_code == 200
        assert response.headers.get("etag") is not None
        assert response.headers.get("cache-control") == "public, no-cache"

    def test_the_etag_changes_when_a_prediction_is_published(
        self, clean_db: Connection, client: TestClient
    ) -> None:
        """A validator that does not change is worse than none, because it caches a stale record."""
        _publish(clean_db, 2)
        before = client.get("/v1/public/accuracy").headers["etag"]

        _publish(clean_db, 1, start=2)
        after = client.get("/v1/public/accuracy").headers["etag"]

        assert before != after

    def test_the_etag_is_stable_when_nothing_changes(
        self, clean_db: Connection, client: TestClient
    ) -> None:
        _publish(clean_db, 2)
        first = client.get("/v1/public/accuracy").headers["etag"]
        second = client.get("/v1/public/accuracy").headers["etag"]
        assert first == second


class TestTheAccuracyResponseIsBounded:
    def test_it_does_not_carry_every_entry(self, clean_db: Connection, client: TestClient) -> None:
        # The response never exposed entries, but public_record built the list anyway, so memory grew with
        # the ledger for a field nothing read.
        _publish(clean_db, 6)
        body = client.get("/v1/public/accuracy").json()
        assert "entries" not in body
        assert body["published"] == 6

    def test_the_counts_are_still_complete(self, clean_db: Connection, client: TestClient) -> None:
        # Computing the aggregates in SQL must not change them. This is the equivalence check.
        _publish(clean_db, 7)
        body = client.get("/v1/public/accuracy").json()
        record = ledger.public_record(clean_db)
        for key in ("published", "resolved", "pending", "answered", "abstained", "brier_score"):
            assert body[key] == record[key]
