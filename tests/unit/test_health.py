"""The health check.

This endpoint exists to tell a monitor which of two different things is wrong, and it could not do it.
``database`` was initialised to ``True`` and never assigned in the failure path, and the connection
arrived through a dependency that raises before the handler body runs, so an unreachable database
produced a 500 rather than the degraded body the handler was written to return. A monitor reads 500 as
"the service is broken" and a degraded body as "the database is down", and those wake different people.

The tests here are about that distinction, not about the happy path.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import main
from tests.conftest import requires_db

# A host, an address and a port that must never appear in an unauthenticated response.
LEAKY_HOST = "db.internal"
LEAKY_ADDRESS = "10.0.0.5"
LEAKY_PORT = "5432"


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    # Deliberately not used as a context manager. The lifespan fits the serving models and verifies the
    # ledger, which is what these tests simulate the failure of, so running it would either refuse to
    # start or do the same work twice.
    return TestClient(app)


class _Unreachable:
    """A stand in for ``transaction()`` that fails the way an unreachable database fails.

    The message carries a host, an address and a port on purpose, so the disclosure test has something
    real to look for rather than asserting against a sanitised string.
    """

    def __enter__(self) -> Any:
        raise OperationalError(
            f'connection to server at "{LEAKY_HOST}" ({LEAKY_ADDRESS}), port {LEAKY_PORT} failed',
            params=None,
            orig=Exception("could not connect"),
        )

    def __exit__(self, *_: object) -> None:
        return None


@pytest.fixture
def unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the connection factory with one that fails. Patched on the module that calls it."""
    monkeypatch.setattr(main, "transaction", _Unreachable)


@pytest.mark.usefixtures("unreachable_database")
class TestAnUnreachableDatabase:
    def test_it_answers_rather_than_raising(self, client: TestClient) -> None:
        # The whole point. Not a 500, and no exception escaping to the caller.
        assert client.get("/healthz").status_code == 200

    def test_it_says_the_database_is_down(self, client: TestClient) -> None:
        body = client.get("/healthz").json()
        assert body["database"] is False, "database must be False when the connection failed"
        assert body["status"] == "degraded"
        assert "database unreachable" in body["detail"]

    def test_it_does_not_leak_the_host_the_address_or_the_port(self, client: TestClient) -> None:
        # This endpoint is unauthenticated. The driver's message names the host and port, which is
        # infrastructure disclosure for no benefit: the operator reads it in the log instead.
        serialised = repr(client.get("/healthz").json())
        for secret in (LEAKY_HOST, LEAKY_ADDRESS, LEAKY_PORT):
            assert secret not in serialised, f"{secret} leaked into an unauthenticated response"

    def test_the_ledger_verdict_is_unknown_rather_than_false(self, client: TestClient) -> None:
        # A ledger that could not be read is not a broken ledger. Reporting False would be a public claim
        # that the chain failed verification, which is not what happened.
        assert client.get("/healthz").json()["ledger_intact"] is None


@pytest.fixture
def models_loaded() -> Iterator[None]:
    """Put a stand in for the serving models on application state.

    Without this the ledger test below depended on whether some earlier test had run the lifespan. It
    passed in isolation because ``models`` was absent, which makes the verdict degraded for a reason that
    has nothing to do with the ledger, so it was passing for the wrong reason and would have kept passing
    if the ledger contribution had been removed entirely.

    Only the two attributes ``healthz`` reads are provided. A real ``ServingModels`` needs a fitted model
    and a corpus, neither of which this test is about.
    """
    from app.main import app

    decided = SimpleNamespace(height=1)
    previous = getattr(app.state, "models", None)
    app.state.models = SimpleNamespace(
        dataset=SimpleNamespace(decided=decided),
        primary_kind="base_rate",
        trained_at=None,
    )
    try:
        yield
    finally:
        if previous is None:
            del app.state.models
        else:
            app.state.models = previous


@requires_db
@pytest.mark.usefixtures("models_loaded")
class TestAReachableDatabaseWithAnUnreadableLedger:
    def test_the_two_failures_are_reported_separately(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A database that answers and a ledger that cannot be read is a different fault."""
        from auspice import ledger

        def explode(_conn: object) -> None:
            raise RuntimeError("the ledger table is unreadable")

        # verify_head, not verify. The handler uses the constant cost probe, because a full walk on an
        # unauthenticated and rate limit exempt endpoint grows its own denial of service surface with the
        # ledger. Patching the wrong one here would leave this test passing while asserting nothing.
        monkeypatch.setattr(ledger, "verify_head", explode)
        body = client.get("/healthz").json()

        assert body["database"] is True, "the database answered, so it must not be reported as down"
        assert "database unreachable" not in body["detail"]
        assert "ledger verification failed" in body["detail"]
        assert body["status"] == "degraded"


class TestTheHandlerIsNotOnTheEventLoop:
    def test_healthz_is_a_plain_function(self) -> None:
        """Everything it does is synchronous, so it must not be a coroutine function.

        A synchronous database round trip plus a full ledger verification on the event loop blocks every
        other request in the process. FastAPI dispatches a plain ``def`` to its threadpool. Asserted
        rather than trusted, because the difference is one keyword and it is invisible in review.
        """
        import inspect

        assert not inspect.iscoroutinefunction(main.healthz)


@requires_db
class TestTheHappyPathStillWorks:
    def test_a_reachable_database_reports_itself_as_reachable(self, client: TestClient) -> None:
        body = client.get("/healthz").json()
        assert body["database"] is True
        # status may legitimately be degraded here, because the serving models are not loaded without the
        # lifespan and the corpus holds one decision. What must hold is that the database is not blamed.
        assert "database unreachable" not in body["detail"]
