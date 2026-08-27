"""Let the prediction table record a degenerate training corpus abstention.

``AbstentionReason`` gained ``degenerate_training_corpus``, and the vocabulary check constraint on
``prediction.abstention_reasons`` is generated from that enum. Alembic does not diff check constraints,
so ``alembic check`` reported no pending migration while the live database would have rejected the
insert. The gap was found by reading ``pg_constraint`` directly rather than by trusting the check, and
``tests/unit/test_leakage_and_schema.py`` now asserts every generated vocabulary constraint matches its
enum so the next one is caught by the suite instead of by an operator.

Why the new reason exists: run against the real corpus while it held a single approval, the scorer
reported a 100 percent chance of approval for a neighbouring county. Every level of shrinkage agreed at
1.0 because the prior being shrunk toward was computed from the same one row, and the three thin record
conditions did not fire because the base rate's pooling weight came to exactly 0.8, which is not
greater than 0.8. A model that has only ever seen approvals cannot state the odds of a denial.

Dropping and recreating a check constraint takes an access exclusive lock for the duration of the
validation scan. On this table that is a scan of the published predictions, which is small, and the new
vocabulary is a strict superset of the old one so no existing row can fail it.

Revision ID: 0003_degenerate_corpus_reason
Revises: 0002_constraint_names
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_degenerate_corpus_reason"
down_revision: str | None = "0002_constraint_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_prediction_abstention_reasons_vocabulary"

OLD_VOCABULARY = (
    "thin_local_record",
    "dominated_by_pooling",
    "interval_too_wide",
    "stale_jurisdiction_data",
    "unresolved_jurisdiction_chain",
)

NEW_VOCABULARY = (*OLD_VOCABULARY, "degenerate_training_corpus")


def _condition(vocabulary: tuple[str, ...]) -> str:
    members = ", ".join(f"'{value}'::text" for value in vocabulary)
    return f"abstention_reasons <@ ARRAY[{members}]"


def _replace(vocabulary: tuple[str, ...]) -> None:
    """Swap the constraint using raw SQL rather than the Alembic helpers.

    ``op.drop_constraint`` and ``op.create_check_constraint`` run the name through the MetaData naming
    convention, which prefixes it with ``ck_prediction_`` again and produces the doubled name that
    migration 0002 existed to clean up. Writing the SQL means the name in the database is the name in
    this file.

    The vocabulary values are module constants, not input, so interpolating them is safe here. If this
    ever takes a value from outside the file, it needs binding instead.
    """
    op.execute(f"ALTER TABLE prediction DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE prediction ADD CONSTRAINT {CONSTRAINT} CHECK ({_condition(vocabulary)})")


def upgrade() -> None:
    _replace(NEW_VOCABULARY)


def downgrade() -> None:
    """Refuses to run while a row uses the reason being removed.

    A downgrade that silently deleted published predictions would break the ledger, whose entry hashes
    chain over payloads that reference them. Failing loudly is the only correct behaviour here.
    """
    stranded = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT count(*) FROM prediction "
            "WHERE 'degenerate_training_corpus' = ANY(abstention_reasons)"
        )
        .scalar_one()
    )
    if stranded:
        raise RuntimeError(
            f"{stranded} published prediction(s) cite degenerate_training_corpus. Removing the value "
            "from the vocabulary would require deleting or rewriting them, and both break the ledger "
            "chain. Resolve those rows deliberately before downgrading."
        )

    _replace(OLD_VOCABULARY)