"""Alembic environment.

Two things here are not boilerplate.

First, the target metadata is ``auspice.db.schema.metadata``, so the schema module is the
single source of truth and ``alembic check`` is a real test rather than a formality.

Second, ``include_object`` filters out everything PostGIS creates for itself. The
``spatial_ref_sys`` table and the topology schema belong to the extension, and without the
filter every autogenerate run proposes dropping them.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from auspice.config import get_settings
from auspice.db.schema import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata

# Objects owned by an extension rather than by us.
EXTENSION_TABLES = frozenset({"spatial_ref_sys", "geography_columns", "geometry_columns"})
EXTENSION_SCHEMAS = frozenset({"tiger", "tiger_data", "topology"})


def _database_url() -> str:
    """Prefer an explicit -x url, then the environment, then the ini file."""
    x_args = context.get_x_argument(as_dictionary=True)
    if "url" in x_args:
        return str(x_args["url"])
    if os.environ.get("AUSPICE_ALEMBIC_TEST") == "1":
        return get_settings().sqlalchemy_url(test=True)
    return get_settings().sqlalchemy_url()


def include_object(
    obj: Any,
    name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: Any,
) -> bool:
    if type_ == "table":
        if name in EXTENSION_TABLES:
            return False
        schema = getattr(obj, "schema", None)
        if schema in EXTENSION_SCHEMAS:
            return False
    # PostGIS names its own internal indexes this way.
    return not (type_ == "index" and name is not None and name.startswith(("idx_", "pgis_")))


def include_name(name: str | None, type_: str, _parent_names: dict[str, str | None]) -> bool:
    if type_ == "schema":
        return name in (None, "public")
    return True


def _configure_common() -> dict[str, Any]:
    return {
        "target_metadata": target_metadata,
        "include_object": include_object,
        "include_name": include_name,
        "compare_type": True,
        "compare_server_default": True,
        "render_as_batch": False,
        "transaction_per_migration": True,
    }


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_configure_common(),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section: dict[str, Any] = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, **_configure_common())
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


def _iter_unused() -> Iterable[None]:  # pragma: no cover - keeps linters honest
    return ()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
