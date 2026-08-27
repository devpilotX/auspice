"""Give the check constraints their intended names.

The MetaData naming convention prefixes check constraints with ``ck_<table>_``, and the first
migration also carried that prefix inside each constraint's own name, so 49 constraints landed as
``ck_prediction_ck_prediction_interval_ordered`` rather than ``ck_prediction_interval_ordered``.

Nothing was broken by it: every constraint was enforcing the right thing. It is worth a migration
anyway, because a constraint violation surfaces to an operator as its name, and a doubled name in a
production error message is the kind of small sloppiness that makes someone doubt the rest.

ALTER TABLE ... RENAME CONSTRAINT is metadata only and takes no table lock beyond an access exclusive
lock held for the duration of the catalogue update, so this is safe on a live database.

Revision ID: 0002_constraint_names
Revises: 0001_permission_graph
Created: 2026-08-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_constraint_names"
down_revision: str | None = "0001_permission_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, old name, new name)
RENAMES: tuple[tuple[str, str, str], ...] = (
    ("jurisdiction", "ck_jurisdiction_ck_jurisdiction_discretion_range", "ck_jurisdiction_discretion_range"),
    ("jurisdiction", "ck_jurisdiction_ck_jurisdiction_data_depth_nonneg", "ck_jurisdiction_data_depth_nonneg"),
    ("decision_body", "ck_decision_body_ck_decision_body_seats_positive", "ck_decision_body_seats_positive"),
    ("decision_body", "ck_decision_body_ck_decision_body_quorum_lte_seats", "ck_decision_body_quorum_lte_seats"),
    ("decision_maker", "ck_decision_maker_ck_decision_maker_term_ordered", "ck_decision_maker_term_ordered"),
    ("election", "ck_election_ck_election_seats_nonneg", "ck_election_seats_nonneg"),
    ("source", "ck_source_ck_source_refresh_positive", "ck_source_refresh_positive"),
    ("document", "ck_document_ck_document_byte_size_positive", "ck_document_byte_size_positive"),
    ("document", "ck_document_ck_document_legibility_range", "ck_document_legibility_range"),
    ("fetch_attempt", "ck_fetch_attempt_ck_fetch_attempt_outcome_vocabulary", "ck_fetch_attempt_outcome_vocabulary"),
    ("dead_letter", "ck_dead_letter_ck_dead_letter_stage_vocabulary", "ck_dead_letter_stage_vocabulary"),
    ("document_page", "ck_document_page_ck_document_page_page_positive", "ck_document_page_page_positive"),
    ("document_page", "ck_document_page_ck_document_page_offsets_ordered", "ck_document_page_offsets_ordered"),
    ("document_page", "ck_document_page_ck_document_page_legibility_range", "ck_document_page_legibility_range"),
    ("document_chunk", "ck_document_chunk_ck_document_chunk_offsets_ordered", "ck_document_chunk_offsets_ordered"),
    ("document_chunk", "ck_document_chunk_ck_document_chunk_pages_ordered", "ck_document_chunk_pages_ordered"),
    ("transcript_segment", "ck_transcript_segment_ck_transcript_segment_time_ordered", "ck_transcript_segment_time_ordered"),
    ("transcript_segment", "ck_transcript_segment_ck_transcript_segment_offsets_ordered", "ck_transcript_segment_offsets_ordered"),
    ("extraction_run", "ck_extraction_run_ck_extraction_run_status_vocabulary", "ck_extraction_run_status_vocabulary"),
    ("fact_evidence", "ck_fact_evidence_ck_fact_evidence_quote_length", "ck_fact_evidence_quote_length"),
    ("fact_evidence", "ck_fact_evidence_ck_fact_evidence_subject_table_vocabulary", "ck_fact_evidence_subject_table_vocabulary"),
    ("entity_cluster", "ck_entity_cluster_ck_entity_cluster_kind_vocabulary", "ck_entity_cluster_kind_vocabulary"),
    ("merge_audit", "ck_merge_audit_ck_merge_audit_method_vocabulary", "ck_merge_audit_method_vocabulary"),
    ("merge_audit", "ck_merge_audit_ck_merge_audit_not_self", "ck_merge_audit_not_self"),
    ("instrument", "ck_instrument_ck_instrument_dates_ordered", "ck_instrument_dates_ordered"),
    ("instrument", "ck_instrument_ck_instrument_not_self_superseding", "ck_instrument_not_self_superseding"),
    ("parcel", "ck_parcel_ck_parcel_validity_ordered", "ck_parcel_validity_ordered"),
    ("parcel", "ck_parcel_ck_parcel_acres_positive", "ck_parcel_acres_positive"),
    ("application", "ck_application_ck_application_relief_not_empty", "ck_application_relief_not_empty"),
    ("application", "ck_application_ck_application_label_source_vocabulary", "ck_application_label_source_vocabulary"),
    ("application", "ck_application_ck_application_staff_recommendation_vocabulary", "ck_application_staff_recommendation_vocabulary"),
    ("application", "ck_application_ck_application_dates_ordered", "ck_application_dates_ordered"),
    ("application", "ck_application_ck_application_censored_matches_outcome", "ck_application_censored_matches_outcome"),
    ("application", "ck_application_ck_application_decided_has_date", "ck_application_decided_has_date"),
    ("objection", "ck_objection_ck_objection_speakers_nonneg", "ck_objection_speakers_nonneg"),
    ("event", "ck_event_ck_event_known_after_occurred", "ck_event_known_after_occurred"),
    ("precedent_link", "ck_precedent_link_ck_precedent_link_similarity_range", "ck_precedent_link_similarity_range"),
    ("precedent_link", "ck_precedent_link_ck_precedent_link_not_self", "ck_precedent_link_not_self"),
    ("model_run", "ck_model_run_ck_model_run_counts_nonneg", "ck_model_run_counts_nonneg"),
    ("prediction", "ck_prediction_ck_prediction_abstention_excludes_probability", "ck_prediction_abstention_excludes_probability"),
    ("prediction", "ck_prediction_ck_prediction_abstention_has_reason", "ck_prediction_abstention_has_reason"),
    ("prediction", "ck_prediction_ck_prediction_probability_range", "ck_prediction_probability_range"),
    ("prediction", "ck_prediction_ck_prediction_interval_ordered", "ck_prediction_interval_ordered"),
    ("prediction", "ck_prediction_ck_prediction_point_estimate_needs_interval", "ck_prediction_point_estimate_needs_interval"),
    ("prediction", "ck_prediction_ck_prediction_months_ordered", "ck_prediction_months_ordered"),
    ("ledger_entry", "ck_ledger_entry_ck_ledger_entry_payload_hash_format", "ck_ledger_entry_payload_hash_format"),
    ("ledger_entry", "ck_ledger_entry_ck_ledger_entry_entry_hash_format", "ck_ledger_entry_entry_hash_format"),
    ("ledger_entry", "ck_ledger_entry_ck_ledger_entry_prev_hash_format", "ck_ledger_entry_prev_hash_format"),
    ("change_event", "ck_change_event_ck_change_event_materiality_range", "ck_change_event_materiality_range"),
)


def _rename(table: str, old: str, new: str) -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            """
            SELECT 1 FROM pg_constraint
            WHERE conname = :old AND conrelid = CAST(:table AS regclass)
            """
        ).bindparams(old=old, table=table)
    ).scalar()
    if exists:
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT "{old}" TO "{new}"')


def upgrade() -> None:
    for table, old, new in RENAMES:
        _rename(table, old, new)


def downgrade() -> None:
    for table, old, new in RENAMES:
        _rename(table, new, old)
