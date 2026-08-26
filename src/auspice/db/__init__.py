"""Database access.

SQLAlchemy 2.0 Core, not the ORM. The queries that matter here are spatial joins,
recursive CTEs and window functions over decision history, and an ORM hides exactly those.
Core gives typed query construction without pretending SQL is not happening.
"""

from __future__ import annotations

from auspice.db.engine import (
    connection,
    dispose_engine,
    get_engine,
    transaction,
)
from auspice.db.schema import metadata

__all__ = ["connection", "dispose_engine", "get_engine", "metadata", "transaction"]
