"""Engine and connection handling.

One engine per process, created lazily. Two context managers:

    ``connection()``  a connection with no transaction semantics beyond autocommit
    ``transaction()`` a connection inside a transaction that commits on clean exit

Loaders use ``transaction()`` so a partial load never lands. A partially loaded registry
is worse than an empty one, because the abstention rule reads ``data_depth`` and would
then abstain on the wrong jurisdictions.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.pool import NullPool

from auspice.config import get_settings
from auspice.logging import get_logger

log = get_logger(__name__)


@functools.lru_cache(maxsize=2)
def get_engine(*, test: bool = False) -> Engine:
    settings = get_settings()
    url = settings.sqlalchemy_url(test=test)

    engine = create_engine(
        url,
        echo=settings.db_echo,
        pool_pre_ping=True,
        # Tests create and drop schemas; a pool that holds connections across those
        # boundaries produces failures that look like schema bugs and are not.
        poolclass=NullPool if test else None,
        pool_size=None if test else settings.db_pool_size,
        future=True,
        connect_args={"application_name": "auspice-test" if test else "auspice"},
    )

    @event.listens_for(engine, "connect")
    def _set_session_defaults(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        # UTC everywhere. A bi-temporal system with a local timezone is a bi-temporal
        # system with a bug that appears twice a year.
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute("SET statement_timeout = '120s'")
        cursor.execute("SET idle_in_transaction_session_timeout = '300s'")
        cursor.close()

    log.debug("engine created", test=test, url=url.split("@")[-1])
    return engine


def dispose_engine() -> None:
    for test in (False, True):
        try:
            engine = get_engine.__wrapped__(test=test)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - nothing to dispose if it never built
            continue
        engine.dispose()
    get_engine.cache_clear()


@contextmanager
def connection(*, test: bool = False) -> Iterator[Connection]:
    engine = get_engine(test=test)
    with engine.connect() as conn:
        yield conn


@contextmanager
def transaction(*, test: bool = False) -> Iterator[Connection]:
    engine = get_engine(test=test)
    with engine.begin() as conn:
        yield conn


def required_extensions(conn: Connection) -> dict[str, str]:
    """Installed extension versions, keyed by name."""
    rows = conn.execute(text("SELECT extname, extversion FROM pg_extension")).all()
    return {name: version for name, version in rows}


def assert_extensions(conn: Connection) -> None:
    """Fail loudly if an extension the schema depends on is absent.

    Extensions need superuser, so they are created by the bootstrap script rather than by
    a migration. That split means the migration has to check rather than assume.
    """
    installed = required_extensions(conn)
    needed = {"postgis", "pg_trgm", "vector", "btree_gist"}
    missing = sorted(needed - installed.keys())
    if missing:
        raise RuntimeError(
            "these PostgreSQL extensions are required and not installed: "
            + ", ".join(missing)
            + ". Run infra/scripts/bootstrap-postgres.ps1 or the docker compose service, "
            "which create them as superuser."
        )
