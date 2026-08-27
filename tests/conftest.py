"""Shared fixtures.

Database tests run against ``AUSPICE_TEST_DATABASE_URL`` and are skipped, not failed, when it is
absent. A developer without a local cluster should still be able to run the pure logic tests, and the
database tests are the ones CI exists to run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date

import polars as pl
import pytest
from sqlalchemy import Connection, text

from auspice.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_rate_limiter() -> Iterator[None]:
    """Give every test its own rate limit allowance.

    The limiter is one object in the process, which is the point of it in production and a problem in a test
    run: a test that floods a public endpoint to prove the limit works leaves the bucket empty, and the next
    test to touch the API gets a 429 that has nothing to do with what it is testing. That happened, and it
    presented as an unrelated tile test failing only when the whole suite ran.

    Cleared rather than disabled. Switching the limiter off in tests would mean the middleware is never
    exercised by anything except its own tests, and the thing worth knowing is that it sits in the real
    request path without breaking the real endpoints.
    """
    from app.ratelimit import limiter

    limiter.buckets.clear()
    limiter.last_sweep = 0.0
    yield
    limiter.buckets.clear()


def _test_database_available() -> bool:
    try:
        return get_settings().test_database_url is not None
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _test_database_available(),
    reason="AUSPICE_TEST_DATABASE_URL is not set. Run infra/scripts/bootstrap-postgres.ps1.",
)


@pytest.fixture(scope="session")
def migrated_test_database() -> Iterator[None]:
    """Bring the test database to head once per session."""
    if not _test_database_available():
        pytest.skip("no test database configured")

    from alembic import command
    from alembic.config import Config

    from auspice.config import REPO_ROOT

    config = Config(str(REPO_ROOT / "infra" / "alembic.ini"))
    os.environ["AUSPICE_ALEMBIC_TEST"] = "1"
    try:
        command.upgrade(config, "head")
        yield
    finally:
        os.environ.pop("AUSPICE_ALEMBIC_TEST", None)


@pytest.fixture
def db(migrated_test_database: None) -> Iterator[Connection]:
    """A connection inside a transaction that is always rolled back.

    Every database test therefore starts from the same state and leaves nothing behind, which matters
    because several of them insert applications and would otherwise change each other's base rates.
    """
    from auspice.db import get_engine

    engine = get_engine(test=True)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def clean_db(db: Connection) -> Connection:
    """A connection with every graph table emptied, for tests that count rows."""
    db.execute(
        text(
            """
            TRUNCATE ledger_entry, prediction, alert, change_event, watch, model_run,
                     feature_snapshot, precedent_link, jurisdiction_chain, vote, objection,
                     event, application, parcel, instrument, entity_alias, entity_cluster,
                     merge_audit, fact_evidence, extraction_run, transcript_segment,
                     document_chunk, document_page, document, dead_letter, fetch_attempt,
                     source, election, decision_maker, decision_body, jurisdiction
            RESTART IDENTITY CASCADE
            """
        )
    )
    return db


@pytest.fixture
def synthetic_corpus():  # type: ignore[no-untyped-def]
    """A corpus with a known truth. Cached per session because generation is not free."""
    from tests.synthetic import generate

    return generate()


@pytest.fixture
def synthetic_dataset(synthetic_corpus):  # type: ignore[no-untyped-def]
    from auspice.models.dataset import dataset_from_frame

    return dataset_from_frame(synthetic_corpus.frame, synthetic_corpus.feature_columns)


@pytest.fixture
def synthetic_split(synthetic_dataset) -> tuple[pl.DataFrame, pl.DataFrame]:  # type: ignore[no-untyped-def]
    train, test = synthetic_dataset.temporal_split(date(2024, 1, 1))
    return train, test
