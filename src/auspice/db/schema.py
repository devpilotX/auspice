"""The Permission Graph.

Section 6.6 of the specification is the abridged DDL. This is the full version, and it is
the single source of truth for the schema: the Alembic migrations are generated from this
metadata, and ``tests/unit/test_schema_matches_database.py`` fails if the live database has
drifted from it.

Three rules are enforced structurally rather than by convention.

1.  **Nothing is ever overwritten.** ``document`` is keyed by the SHA-256 of the raw bytes,
    so re-fetching an unchanged page is a no-op and a changed page is a new row. Instrument
    supersession is a foreign key, not an UPDATE.

2.  **Every fact carries provenance.** ``fact_evidence`` points at a document, a page and a
    character range, and carries the boolean that says whether the quote was found verbatim
    in the stored source text. Section 6.4: an unverified quote is discarded, not shipped.

3.  **Every feature is reconstructible as of a date.** ``parcel`` and ``instrument`` are
    bi-temporal, and ``feature_snapshot`` records the as-of date it was computed for. This
    is what makes the leakage rule in section 6.9 enforceable instead of aspirational.

Column comments are set on the columns that would otherwise need a comment in every query
that touches them.
"""

from __future__ import annotations

from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from auspice.domain import (
    ABSTENTION_REASONS,
    ALERT_TRIGGERS,
    BODY_KINDS,
    CIVIC_PLATFORMS,
    CONFIDENCES,
    DOCUMENT_KINDS,
    EVENT_TYPES,
    INSTRUMENT_KINDS,
    JURISDICTION_KINDS,
    JURISDICTION_ROLES,
    LEGAL_FRAMEWORKS,
    MODEL_KINDS,
    OBJECTION_GROUNDS,
    OUTCOMES,
    PARSE_METHODS,
    RELIEFS,
    USE_CLASSES,
    VOTE_POSITIONS,
)

EMBEDDING_DIMENSIONS = 1536

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _one_of(
    column: str, values: tuple[str, ...], *, name: str, nullable: bool = False
) -> CheckConstraint:
    """A CHECK constraint generated from a domain enum.

    Generating these from the Python enums means the vocabulary cannot drift between the
    application and the database without a migration failing.
    """
    quoted = ", ".join(f"'{v}'" for v in values)
    expression = f"{column} IN ({quoted})"
    if nullable:
        expression = f"{column} IS NULL OR {expression}"
    return CheckConstraint(expression, name=name)


def _array_subset(column: str, values: tuple[str, ...], *, name: str) -> CheckConstraint:
    """Every element of a text[] column must be a member of the vocabulary."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} <@ ARRAY[{quoted}]::text[]", name=name)


_now = func.now()


# ===========================================================================
# STAGE 0 - THE JURISDICTION REGISTRY
# "Who actually decides for this parcel?" Everything downstream is worthless
# without a correct answer, so this table is hand built and version controlled.
# ===========================================================================

jurisdiction = Table(
    "jurisdiction",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("slug", Text, nullable=False, comment="Stable human readable key, e.g. us-va-loudoun"),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("country", Text, nullable=False, server_default=text("'US'")),
    Column("region", Text, nullable=True, comment="State or province code"),
    Column(
        "admin_codes",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="FIPS, GEOID, ONS or equivalent official identifiers",
    ),
    Column(
        "legal_framework",
        Text,
        nullable=True,
        comment="Dillon's Rule versus home rule. Determines whether the state can pre-empt.",
    ),
    Column(
        "boundary",
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        nullable=True,
        comment="Official boundary. Null only while the registry entry is being built.",
    ),
    Column("population", Integer, nullable=True),
    Column("land_area_sq_km", Numeric(12, 2), nullable=True),
    Column("civic_platform", Text, nullable=True),
    Column(
        "discretion_index",
        Numeric(4, 3),
        nullable=True,
        comment="0 fully by right, 1 fully discretionary. The channel politics arrives through.",
    ),
    Column(
        "data_depth",
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Usable historical decisions held. Drives the abstention rule in section 8.4.",
    ),
    Column("notes", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("slug", name="uq_jurisdiction_slug"),
    UniqueConstraint("country", "kind", "name", name="uq_jurisdiction_country_kind_name"),
    _one_of("kind", JURISDICTION_KINDS, name="kind_vocabulary"),
    _one_of("legal_framework", LEGAL_FRAMEWORKS, name="framework_vocabulary", nullable=True),
    _one_of("civic_platform", CIVIC_PLATFORMS, name="platform_vocabulary", nullable=True),
    CheckConstraint(
        "discretion_index IS NULL OR (discretion_index >= 0 AND discretion_index <= 1)",
        name="discretion_range",
    ),
    CheckConstraint("data_depth >= 0", name="data_depth_nonneg"),
)
Index("ix_jurisdiction_boundary", jurisdiction.c.boundary, postgresql_using="gist")
Index("ix_jurisdiction_region_kind", jurisdiction.c.region, jurisdiction.c.kind)
Index(
    "ix_jurisdiction_name_trgm",
    jurisdiction.c.name,
    postgresql_using="gin",
    postgresql_ops={"name": "gin_trgm_ops"},
)


decision_body = Table(
    "decision_body",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "jurisdiction_id",
        BigInteger,
        ForeignKey("jurisdiction.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("seats", Integer, nullable=True),
    Column("quorum", Integer, nullable=True),
    Column(
        "vote_threshold",
        Text,
        nullable=True,
        comment="simple_majority, supermajority_two_thirds, supermajority_three_quarters, unanimity",
    ),
    Column(
        "recommendation_is_binding",
        Boolean,
        nullable=True,
        comment="Whether this body's recommendation binds the body above it. Appendix 19.2 group A.",
    ),
    Column("meeting_cadence", Text, nullable=True),
    Column(
        "statutory_decision_days",
        Integer,
        nullable=True,
        comment="Statutory deadline where one exists. Enforcement in practice is a separate feature.",
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("jurisdiction_id", "name", name="uq_decision_body_jurisdiction_id_name"),
    _one_of("kind", BODY_KINDS, name="kind_vocabulary"),
    CheckConstraint("seats IS NULL OR seats > 0", name="seats_positive"),
    CheckConstraint("quorum IS NULL OR seats IS NULL OR quorum <= seats", name="quorum_lte_seats"),
)


decision_maker = Table(
    "decision_maker",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "body_id", BigInteger, ForeignKey("decision_body.id", ondelete="CASCADE"), nullable=False
    ),
    Column("display_name", Text, nullable=False),
    Column(
        "name_variants",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
        comment="Every spelling seen in a source. Never destroyed. Section 6.5.",
    ),
    Column("seat_label", Text, nullable=True),
    Column("term_start", Date, nullable=True),
    Column("term_end", Date, nullable=True, comment="Election proximity is a live feature"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    CheckConstraint(
        "term_end IS NULL OR term_start IS NULL OR term_end >= term_start",
        name="term_ordered",
    ),
)
Index("ix_decision_maker_body_id", decision_maker.c.body_id)
Index(
    "ix_decision_maker_display_name_trgm",
    decision_maker.c.display_name,
    postgresql_using="gin",
    postgresql_ops={"display_name": "gin_trgm_ops"},
)


election = Table(
    "election",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "body_id", BigInteger, ForeignKey("decision_body.id", ondelete="CASCADE"), nullable=False
    ),
    Column("election_date", Date, nullable=False),
    Column("seats_contested", Integer, nullable=True),
    Column("filing_deadline", Date, nullable=True),
    Column("kind", Text, nullable=True, comment="general, primary, special, runoff"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("body_id", "election_date", name="uq_election_body_id_election_date"),
    CheckConstraint("seats_contested IS NULL OR seats_contested >= 0", name="seats_nonneg"),
)
Index("ix_election_election_date", election.c.election_date)


source = Table(
    "source",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "jurisdiction_id",
        BigInteger,
        ForeignKey("jurisdiction.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", Text, nullable=False, comment="Which DocumentKind this source yields"),
    Column("platform", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column(
        "platform_config",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Adapter specific handles: Legistar client name, CivicPlus module id, and so on",
    ),
    Column(
        "refresh_hours",
        Integer,
        nullable=False,
        server_default=text("24"),
        comment="Freshness SLA from section 6.12, in hours",
    ),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("robots_allowed", Boolean, nullable=True, comment="Null means not yet checked"),
    Column("last_checked_at", DateTime(timezone=True), nullable=True),
    Column("last_success_at", DateTime(timezone=True), nullable=True),
    Column("consecutive_failures", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("jurisdiction_id", "kind", "url", name="uq_source_jurisdiction_id_kind_url"),
    _one_of("kind", DOCUMENT_KINDS, name="kind_vocabulary"),
    _one_of("platform", CIVIC_PLATFORMS, name="platform_vocabulary"),
    CheckConstraint("refresh_hours > 0", name="refresh_positive"),
)
Index("ix_source_enabled_last_success_at", source.c.enabled, source.c.last_success_at)


# ===========================================================================
# STAGE 1 - INGESTION
# Content addressed, immutable, never overwritten, never deleted.
# ===========================================================================

document = Table(
    "document",
    metadata,
    Column(
        "id",
        String(64),
        primary_key=True,
        comment="Lowercase hex SHA-256 of the raw bytes. Re-fetching unchanged content is a no-op.",
    ),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=True),
    Column("source_id", BigInteger, ForeignKey("source.id"), nullable=True),
    Column("kind", Text, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("title", Text, nullable=True),
    Column("media_type", Text, nullable=True),
    Column("byte_size", BigInteger, nullable=False),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("published_on", Date, nullable=True),
    Column(
        "storage_key",
        Text,
        nullable=False,
        comment="Key in the raw object store. Layout is sha256[0:2]/sha256[2:4]/sha256",
    ),
    Column(
        "response_headers",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Kept so a later dispute about what a source said on a date is answerable",
    ),
    Column("page_count", Integer, nullable=True),
    Column("parse_method", Text, nullable=True),
    Column("parsed_at", DateTime(timezone=True), nullable=True),
    Column("legibility", Numeric(4, 3), nullable=True, comment="Mean page legibility, 0 to 1"),
    Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    _one_of("kind", DOCUMENT_KINDS, name="kind_vocabulary"),
    _one_of("parse_method", PARSE_METHODS, name="parse_method_vocabulary", nullable=True),
    CheckConstraint("byte_size > 0", name="byte_size_positive"),
    CheckConstraint("id ~ '^[0-9a-f]{64}$'", name="ck_document_id_is_sha256"),
    CheckConstraint(
        "legibility IS NULL OR (legibility >= 0 AND legibility <= 1)",
        name="legibility_range",
    ),
)
Index(
    "ix_document_jurisdiction_id_kind_published_on",
    document.c.jurisdiction_id,
    document.c.kind,
    document.c.published_on,
)
Index("ix_document_source_url", document.c.source_url)
Index("ix_document_fetched_at", document.c.fetched_at)
Index(
    "ix_document_embedding_hnsw",
    document.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_with={"m": 16, "ef_construction": 64},
)


fetch_attempt = Table(
    "fetch_attempt",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("source_id", BigInteger, ForeignKey("source.id", ondelete="SET NULL"), nullable=True),
    Column("url", Text, nullable=False),
    Column("attempted_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("status_code", Integer, nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("document_id", String(64), ForeignKey("document.id"), nullable=True),
    Column(
        "outcome",
        Text,
        nullable=False,
        comment="stored, unchanged, robots_disallowed, http_error, timeout, parse_refused",
    ),
    Column("error", Text, nullable=True),
    CheckConstraint(
        "outcome IN ('stored','unchanged','robots_disallowed','http_error','timeout','parse_refused')",
        name="outcome_vocabulary",
    ),
)
Index(
    "ix_fetch_attempt_source_id_attempted_at",
    fetch_attempt.c.source_id,
    fetch_attempt.c.attempted_at,
)


dead_letter = Table(
    "dead_letter",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("stage", Text, nullable=False, comment="ingest, parse, transcribe, extract, resolve"),
    Column("subject", Text, nullable=False, comment="A URL, a document id, or an application id"),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=True),
    Column("error_type", Text, nullable=False),
    Column("error_message", Text, nullable=False),
    Column(
        "payload",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("attempts", Integer, nullable=False, server_default=text("1")),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("resolution", Text, nullable=True),
    UniqueConstraint("stage", "subject", name="uq_dead_letter_stage_subject"),
    CheckConstraint(
        "stage IN ('ingest','parse','transcribe','extract','resolve','feature','score')",
        name="stage_vocabulary",
    ),
)
Index(
    "ix_dead_letter_open",
    dead_letter.c.stage,
    dead_letter.c.last_seen_at,
    postgresql_where=text("resolved_at IS NULL"),
)


# ===========================================================================
# STAGE 2 - DOCUMENT PROCESSING
# Page and character offsets are preserved because that is what makes citation
# possible later, and it is not retrofittable.
# ===========================================================================

document_page = Table(
    "document_page",
    metadata,
    Column(
        "document_id", String(64), ForeignKey("document.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("page", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column(
        "char_start",
        Integer,
        nullable=False,
        comment="Offset of this page within the concatenated document text",
    ),
    Column("char_end", Integer, nullable=False),
    Column("parse_method", Text, nullable=False),
    Column("legibility", Numeric(4, 3), nullable=False),
    Column("escalated", Boolean, nullable=False, server_default=text("false")),
    _one_of("parse_method", PARSE_METHODS, name="parse_method_vocabulary"),
    CheckConstraint("page >= 1", name="page_positive"),
    CheckConstraint("char_end >= char_start", name="offsets_ordered"),
    CheckConstraint("legibility >= 0 AND legibility <= 1", name="legibility_range"),
)


document_chunk = Table(
    "document_chunk",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "document_id", String(64), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    ),
    Column("ordinal", Integer, nullable=False),
    Column(
        "heading",
        Text,
        nullable=True,
        comment="The structural boundary this chunk was split on: section, agenda item, motion block",
    ),
    Column("page_start", Integer, nullable=False),
    Column("page_end", Integer, nullable=False),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("token_estimate", Integer, nullable=True),
    Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=True),
    UniqueConstraint("document_id", "ordinal", name="uq_document_chunk_document_id_ordinal"),
    CheckConstraint("char_end > char_start", name="offsets_ordered"),
    CheckConstraint("page_end >= page_start", name="pages_ordered"),
)
Index(
    "ix_document_chunk_embedding_hnsw",
    document_chunk.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_with={"m": 16, "ef_construction": 64},
)
Index(
    "ix_document_chunk_text_fts",
    text("to_tsvector('english', text)"),
    postgresql_using="gin",
    _table=document_chunk,
)


# ===========================================================================
# STAGE 3 - TRANSCRIPTION
# The minutes say "Motion denied, 1-4". The video says why. The second sentence
# generalises to the next four decisions and the first does not.
# ===========================================================================

transcript_segment = Table(
    "transcript_segment",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "document_id", String(64), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    ),
    Column("ordinal", Integer, nullable=False),
    Column("start_ms", Integer, nullable=False),
    Column("end_ms", Integer, nullable=False),
    Column(
        "speaker_label",
        Text,
        nullable=True,
        comment="Diarisation output, e.g. SPEAKER_03. Never presented to a customer on its own.",
    ),
    Column(
        "maker_id",
        BigInteger,
        ForeignKey("decision_maker.id", ondelete="SET NULL"),
        nullable=True,
        comment="Resolved only when the attribution is supported by the record",
    ),
    Column("text", Text, nullable=False),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("agenda_item", Text, nullable=True),
    Column("confidence", Numeric(4, 3), nullable=True),
    UniqueConstraint("document_id", "ordinal", name="uq_transcript_segment_document_id_ordinal"),
    CheckConstraint("end_ms >= start_ms", name="time_ordered"),
    CheckConstraint("char_end >= char_start", name="offsets_ordered"),
)
Index("ix_transcript_segment_maker_id", transcript_segment.c.maker_id)
Index(
    "ix_transcript_segment_text_fts",
    text("to_tsvector('english', text)"),
    postgresql_using="gin",
    _table=transcript_segment,
)


# ===========================================================================
# STAGE 4 - EXTRACTION
# ===========================================================================

extraction_run = Table(
    "extraction_run",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "document_id", String(64), ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    ),
    Column(
        "cache_key",
        String(64),
        nullable=False,
        comment="SHA-256 of document id, prompt version, schema version and model. "
        "Reprocessing unchanged input costs nothing.",
    ),
    Column("schema_name", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("pass_number", SmallInteger, nullable=False, server_default=text("1")),
    Column(
        "status",
        Text,
        nullable=False,
        comment="ok, schema_violation, quote_unverified, refused, provider_error, disagreement",
    ),
    Column("facts_extracted", Integer, nullable=False, server_default=text("0")),
    Column("facts_discarded", Integer, nullable=False, server_default=text("0")),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("raw_response", JSONB, nullable=True),
    Column("error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("cache_key", "pass_number", name="uq_extraction_run_cache_key_pass_number"),
    CheckConstraint(
        "status IN ('ok','schema_violation','quote_unverified','refused','provider_error','disagreement')",
        name="status_vocabulary",
    ),
)
Index("ix_extraction_run_document_id", extraction_run.c.document_id)
Index("ix_extraction_run_status_created_at", extraction_run.c.status, extraction_run.c.created_at)


fact_evidence = Table(
    "fact_evidence",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("subject_table", Text, nullable=False),
    Column("subject_id", BigInteger, nullable=False),
    Column("field", Text, nullable=True),
    Column("document_id", String(64), ForeignKey("document.id"), nullable=False),
    Column("page", Integer, nullable=True),
    Column("char_start", Integer, nullable=True),
    Column("char_end", Integer, nullable=True),
    Column("quote", Text, nullable=False),
    Column("extractor_version", Text, nullable=False),
    Column(
        "verified",
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="The quote was found verbatim in the stored source text. Unverified rows are "
        "deleted by the extraction layer, so a false here means an audit is in progress.",
    ),
    Column("verified_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    CheckConstraint("length(quote) BETWEEN 1 AND 500", name="quote_length"),
    CheckConstraint(
        "subject_table IN ('application','instrument','objection','decision_maker','vote',"
        "'jurisdiction','decision_body','election','parcel')",
        name="subject_table_vocabulary",
    ),
)
Index(
    "ix_fact_evidence_subject_table_subject_id",
    fact_evidence.c.subject_table,
    fact_evidence.c.subject_id,
)
Index("ix_fact_evidence_document_id", fact_evidence.c.document_id)
Index(
    "ix_fact_evidence_unverified",
    fact_evidence.c.created_at,
    postgresql_where=text("verified = false"),
)


# ===========================================================================
# STAGE 5 - ENTITY RESOLUTION
# Every merge is recorded and reversible. The original strings are never destroyed.
# ===========================================================================

entity_cluster = Table(
    "entity_cluster",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False, comment="applicant, owner, objection_group"),
    Column("canonical_name", Text, nullable=False),
    Column(
        "beneficial_owner_name",
        Text,
        nullable=True,
        comment="Where the record discloses the principal behind a single purpose entity",
    ),
    Column("opaque", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    CheckConstraint("kind IN ('applicant','owner','objection_group')", name="kind_vocabulary"),
)
Index(
    "ix_entity_cluster_canonical_name_trgm",
    entity_cluster.c.canonical_name,
    postgresql_using="gin",
    postgresql_ops={"canonical_name": "gin_trgm_ops"},
)


entity_alias = Table(
    "entity_alias",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "cluster_id",
        BigInteger,
        ForeignKey("entity_cluster.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "raw_string",
        Text,
        nullable=False,
        comment="Exactly as it appeared. Never normalised in place.",
    ),
    Column("normalised", Text, nullable=False),
    Column("first_seen_document_id", String(64), ForeignKey("document.id"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("cluster_id", "raw_string", name="uq_entity_alias_cluster_id_raw_string"),
)
Index(
    "ix_entity_alias_normalised_trgm",
    entity_alias.c.normalised,
    postgresql_using="gin",
    postgresql_ops={"normalised": "gin_trgm_ops"},
)


merge_audit = Table(
    "merge_audit",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("entity_kind", Text, nullable=False),
    Column("absorbed_id", BigInteger, nullable=False),
    Column("survivor_id", BigInteger, nullable=False),
    Column(
        "method",
        Text,
        nullable=False,
        comment="exact, trigram, embedding, llm_adjudication, manual",
    ),
    Column("score", Numeric(5, 4), nullable=True),
    Column("rationale", Text, nullable=True),
    Column("merged_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("reversed_at", DateTime(timezone=True), nullable=True),
    Column("reversed_reason", Text, nullable=True),
    CheckConstraint(
        "method IN ('exact','trigram','embedding','llm_adjudication','manual')",
        name="method_vocabulary",
    ),
    CheckConstraint("absorbed_id <> survivor_id", name="not_self"),
)


# ===========================================================================
# STAGE 6 - THE RULES, THE LAND, THE ASK
# ===========================================================================

instrument = Table(
    "instrument",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "jurisdiction_id",
        BigInteger,
        ForeignKey("jurisdiction.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", Text, nullable=False),
    Column("citation", Text, nullable=True),
    Column("title", Text, nullable=True),
    Column("adopted_on", Date, nullable=True),
    Column("effective_on", Date, nullable=True),
    Column("expires_on", Date, nullable=True, comment="Moratoria expire. That date is a feature."),
    Column(
        "supersedes_id",
        BigInteger,
        ForeignKey("instrument.id", ondelete="SET NULL"),
        nullable=True,
        comment="Lets the system know the rules changed last month, which section 6.6 names as "
        "the most common cause of a wrong forecast",
    ),
    Column(
        "applies_to_use_classes",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
        comment="Empty means it applies to everything",
    ),
    Column(
        "restrictions",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Structured limits: setback_ft, height_ft, noise_dba, water_gpd_cap, "
        "min_acres, mw_cap. Converts legal text into continuous numbers.",
    ),
    Column("full_text_document_id", String(64), ForeignKey("document.id"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    _one_of("kind", INSTRUMENT_KINDS, name="kind_vocabulary"),
    _array_subset("applies_to_use_classes", USE_CLASSES, name="use_classes_vocabulary"),
    CheckConstraint(
        "expires_on IS NULL OR effective_on IS NULL OR expires_on >= effective_on",
        name="dates_ordered",
    ),
    CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id", name="not_self_superseding"),
)
Index(
    "ix_instrument_jurisdiction_id_kind_effective_on",
    instrument.c.jurisdiction_id,
    instrument.c.kind,
    instrument.c.effective_on,
)
Index(
    "ix_instrument_live_moratorium",
    instrument.c.jurisdiction_id,
    instrument.c.expires_on,
    postgresql_where=text("kind = 'moratorium'"),
)


parcel = Table(
    "parcel",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=True),
    Column("external_id", Text, nullable=True, comment="Assessor parcel number as published"),
    Column(
        "geom",
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        nullable=False,
    ),
    Column("acres", Numeric(12, 3), nullable=True),
    Column("current_zoning", Text, nullable=True),
    Column("overlays", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("owner_raw", Text, nullable=True),
    Column(
        "owner_cluster_id",
        BigInteger,
        ForeignKey("entity_cluster.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("prior_industrial_use", Boolean, nullable=True),
    Column(
        "valid_from",
        Date,
        nullable=False,
        comment="Parcels split, merge and get renumbered. Bi-temporal so a 2024 score sees the "
        "2024 geometry.",
    ),
    Column("valid_to", Date, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity_ordered"),
    CheckConstraint("acres IS NULL OR acres > 0", name="acres_positive"),
)
Index("ix_parcel_geom", parcel.c.geom, postgresql_using="gist")
Index("ix_parcel_jurisdiction_id_external_id", parcel.c.jurisdiction_id, parcel.c.external_id)
Index("ix_parcel_owner_cluster_id", parcel.c.owner_cluster_id)


application = Table(
    "application",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=False),
    Column(
        "body_id", BigInteger, ForeignKey("decision_body.id", ondelete="SET NULL"), nullable=True
    ),
    Column(
        "external_id", Text, nullable=True, comment="Case number as the jurisdiction publishes it"
    ),
    Column("applicant_raw", Text, nullable=True),
    Column(
        "applicant_cluster_id",
        BigInteger,
        ForeignKey("entity_cluster.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("parcel_id", BigInteger, ForeignKey("parcel.id", ondelete="SET NULL"), nullable=True),
    Column("use_class", Text, nullable=False),
    Column("relief_sought", ARRAY(Text), nullable=False),
    Column("by_right", Boolean, nullable=True),
    Column("capacity_mw", Numeric(10, 2), nullable=True),
    Column("acres", Numeric(12, 3), nullable=True),
    Column("filed_on", Date, nullable=True),
    Column("decided_on", Date, nullable=True),
    Column("outcome", Text, nullable=False, server_default=text("'pending'")),
    Column("vote_for", Integer, nullable=True),
    Column("vote_against", Integer, nullable=True),
    Column("vote_abstain", Integer, nullable=True),
    Column("conditions", JSONB, nullable=True),
    Column(
        "staff_recommendation",
        Text,
        nullable=True,
        comment="approve, approve_with_conditions, deny, none. Whether the body overruled its own "
        "staff is one of the stronger features.",
    ),
    Column(
        "months_to_decision",
        Numeric(8, 3),
        Computed(
            "CASE WHEN decided_on IS NOT NULL AND filed_on IS NOT NULL "
            "THEN (decided_on - filed_on) / 30.44 END",
            persisted=True,
        ),
        nullable=True,
    ),
    Column(
        "censored",
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="Still pending. Right censored, not missing. Section 6.8 model 2.",
    ),
    Column(
        "label_source",
        Text,
        nullable=False,
        server_default=text("'extracted'"),
        comment="hand_labelled or extracted. Hand labelled rows are the training ground truth.",
    ),
    Column("notes", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint(
        "jurisdiction_id", "external_id", name="uq_application_jurisdiction_id_external_id"
    ),
    _one_of("use_class", USE_CLASSES, name="use_class_vocabulary"),
    _one_of("outcome", OUTCOMES, name="outcome_vocabulary"),
    _array_subset("relief_sought", RELIEFS, name="relief_vocabulary"),
    CheckConstraint("cardinality(relief_sought) >= 1", name="relief_not_empty"),
    CheckConstraint(
        "label_source IN ('hand_labelled','extracted')", name="label_source_vocabulary"
    ),
    CheckConstraint(
        "staff_recommendation IS NULL OR staff_recommendation IN "
        "('approve','approve_with_conditions','deny','none')",
        name="staff_recommendation_vocabulary",
    ),
    CheckConstraint(
        "decided_on IS NULL OR filed_on IS NULL OR decided_on >= filed_on",
        name="dates_ordered",
    ),
    CheckConstraint(
        "(censored = true) = (outcome IN ('pending','continued','tabled','unknown'))",
        name="censored_matches_outcome",
    ),
    CheckConstraint(
        "outcome NOT IN ('approved','approved_with_conditions','denied') OR decided_on IS NOT NULL",
        name="decided_has_date",
    ),
)
Index(
    "ix_application_jurisdiction_id_use_class_decided_on",
    application.c.jurisdiction_id,
    application.c.use_class,
    application.c.decided_on,
)
Index("ix_application_filed_on", application.c.filed_on)
Index("ix_application_outcome_decided_on", application.c.outcome, application.c.decided_on)
Index("ix_application_applicant_cluster_id", application.c.applicant_cluster_id)
Index(
    "ix_application_pending",
    application.c.jurisdiction_id,
    application.c.filed_on,
    postgresql_where=text("censored = true"),
)


vote = Table(
    "vote",
    metadata,
    Column(
        "application_id",
        BigInteger,
        ForeignKey("application.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "maker_id",
        BigInteger,
        ForeignKey("decision_maker.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("position", Text, nullable=False),
    Column("voted_on", Date, nullable=True),
    _one_of("position", VOTE_POSITIONS, name="position_vocabulary"),
)
Index("ix_vote_maker_id", vote.c.maker_id)


objection = Table(
    "objection",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "application_id",
        BigInteger,
        ForeignKey("application.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=False),
    Column("observed_on", Date, nullable=True),
    Column("organised", Boolean, nullable=True),
    Column(
        "group_cluster_id",
        BigInteger,
        ForeignKey("entity_cluster.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("group_name_raw", Text, nullable=True),
    Column("retained_counsel", Boolean, nullable=True),
    Column("grounds", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("speakers", Integer, nullable=True),
    Column("media_mentions", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    _array_subset("grounds", OBJECTION_GROUNDS, name="grounds_vocabulary"),
    CheckConstraint("speakers IS NULL OR speakers >= 0", name="speakers_nonneg"),
)
Index(
    "ix_objection_jurisdiction_id_observed_on", objection.c.jurisdiction_id, objection.c.observed_on
)
Index("ix_objection_application_id", objection.c.application_id)


event = Table(
    "event",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "jurisdiction_id",
        BigInteger,
        ForeignKey("jurisdiction.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "application_id",
        BigInteger,
        ForeignKey("application.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column(
        "instrument_id", BigInteger, ForeignKey("instrument.id", ondelete="CASCADE"), nullable=True
    ),
    Column(
        "body_id", BigInteger, ForeignKey("decision_body.id", ondelete="SET NULL"), nullable=True
    ),
    Column("event_type", Text, nullable=False),
    Column("occurred_on", Date, nullable=False),
    Column(
        "known_from",
        Date,
        nullable=False,
        comment="The date this became publicly knowable. Point in time features read this, not "
        "occurred_on, so a feature cannot see an event before the record existed.",
    ),
    Column("detail", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    _one_of("event_type", EVENT_TYPES, name="event_type_vocabulary"),
    CheckConstraint("known_from >= occurred_on", name="known_after_occurred"),
)
Index(
    "ix_event_jurisdiction_id_event_type_known_from",
    event.c.jurisdiction_id,
    event.c.event_type,
    event.c.known_from,
)
Index("ix_event_application_id", event.c.application_id)


precedent_link = Table(
    "precedent_link",
    metadata,
    Column("a_id", BigInteger, ForeignKey("application.id", ondelete="CASCADE"), primary_key=True),
    Column("b_id", BigInteger, ForeignKey("application.id", ondelete="CASCADE"), primary_key=True),
    Column("similarity", Numeric(5, 4), nullable=False),
    Column(
        "basis",
        JSONB,
        nullable=False,
        comment="Which dimensions matched, and by how much. Shown to the customer as the "
        "comparable set, so it has to be legible rather than a bare score.",
    ),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=_now),
    CheckConstraint("similarity >= 0 AND similarity <= 1", name="similarity_range"),
    CheckConstraint("a_id <> b_id", name="not_self"),
)
Index("ix_precedent_link_b_id", precedent_link.c.b_id)


jurisdiction_chain = Table(
    "jurisdiction_chain",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "application_id",
        BigInteger,
        ForeignKey("application.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=False),
    Column("role", Text, nullable=False),
    Column("ordinal", Integer, nullable=False),
    UniqueConstraint(
        "application_id",
        "jurisdiction_id",
        "role",
        name="uq_jurisdiction_chain_application_id_jurisdiction_id_role",
    ),
    _one_of("role", JURISDICTION_ROLES, name="role_vocabulary"),
)


# ===========================================================================
# STAGE 7 - FEATURES
# One row per application per as-of date. Recomputing a 2024 decision's features
# in 2026 must produce what was knowable in 2024, and this table is how that is
# checked rather than assumed.
# ===========================================================================

feature_snapshot = Table(
    "feature_snapshot",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "application_id",
        BigInteger,
        ForeignKey("application.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("as_of", Date, nullable=False, comment="Almost always the filing date"),
    Column("feature_set_version", Text, nullable=False),
    Column("features", JSONB, nullable=False),
    Column(
        "missing",
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
        comment="Named features that could not be computed. Never silently zero filled.",
    ),
    Column("computed_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint(
        "application_id",
        "as_of",
        "feature_set_version",
        name="uq_feature_snapshot_application_id_as_of_feature_set_version",
    ),
)
Index("ix_feature_snapshot_as_of", feature_snapshot.c.as_of)


# ===========================================================================
# STAGES 8 AND 9 - MODELS AND EVALUATION
# ===========================================================================

model_run = Table(
    "model_run",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("kind", Text, nullable=False),
    Column("version", Text, nullable=False, comment="Semantic version of the model definition"),
    Column("feature_set_version", Text, nullable=False),
    Column(
        "dataset_hash",
        String(64),
        nullable=False,
        comment="SHA-256 over the sorted training rows. Two runs with the same hash saw the "
        "same data, which is what makes the public accuracy record reproducible.",
    ),
    Column("train_cutoff", Date, nullable=False),
    Column("n_train", Integer, nullable=False),
    Column("n_test", Integer, nullable=False),
    Column("params", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("metrics", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("calibrator", JSONB, nullable=True, comment="Fitted isotonic or Platt parameters"),
    Column("artifact_path", Text, nullable=True),
    Column("trained_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column("promoted_at", DateTime(timezone=True), nullable=True, comment="When it began serving"),
    Column("retired_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "kind", "version", "dataset_hash", name="uq_model_run_kind_version_dataset_hash"
    ),
    _one_of("kind", MODEL_KINDS, name="kind_vocabulary"),
    CheckConstraint("n_train >= 0 AND n_test >= 0", name="counts_nonneg"),
)
Index(
    "ix_model_run_serving",
    model_run.c.kind,
    model_run.c.promoted_at,
    postgresql_where=text("retired_at IS NULL"),
)


# ===========================================================================
# STAGE 10 - OUTPUT
# ===========================================================================

prediction = Table(
    "prediction",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "public_id",
        Text,
        nullable=False,
        comment="Opaque identifier used in the ledger and in URLs",
    ),
    Column(
        "application_id",
        BigInteger,
        ForeignKey("application.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("jurisdiction_id", BigInteger, ForeignKey("jurisdiction.id"), nullable=False),
    Column("site", JSONB, nullable=False, comment="Parcel ids, use class, relief sought, by_right"),
    Column("model_run_id", BigInteger, ForeignKey("model_run.id"), nullable=False),
    Column("survival_run_id", BigInteger, ForeignKey("model_run.id"), nullable=True),
    Column("rule_change_run_id", BigInteger, ForeignKey("model_run.id"), nullable=True),
    Column("approval_probability", Numeric(6, 5), nullable=True),
    Column("ci80_low", Numeric(6, 5), nullable=True),
    Column("ci80_high", Numeric(6, 5), nullable=True),
    Column("confidence", Text, nullable=True),
    Column("abstained", Boolean, nullable=False, server_default=text("false")),
    Column("abstention_reasons", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("months_p10", Numeric(7, 2), nullable=True),
    Column("months_p50", Numeric(7, 2), nullable=True),
    Column("months_p90", Numeric(7, 2), nullable=True),
    Column("rule_change_probability", Numeric(6, 5), nullable=True),
    Column("drivers", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("precedents", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("mitigations", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("alternatives", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("provenance", JSONB, nullable=False),
    Column(
        "features_hash",
        String(64),
        nullable=False,
        comment="Committed to the ledger so a prediction cannot be quietly re-based later",
    ),
    Column("data_as_of", Date, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("public_id", name="uq_prediction_public_id"),
    _one_of("confidence", CONFIDENCES, name="confidence_vocabulary", nullable=True),
    _array_subset("abstention_reasons", ABSTENTION_REASONS, name="abstention_reasons_vocabulary"),
    CheckConstraint(
        "(abstained = true AND approval_probability IS NULL) OR "
        "(abstained = false AND approval_probability IS NOT NULL)",
        name="abstention_excludes_probability",
    ),
    CheckConstraint(
        "abstained = false OR cardinality(abstention_reasons) >= 1",
        name="abstention_has_reason",
    ),
    CheckConstraint(
        "approval_probability IS NULL OR (approval_probability >= 0 AND approval_probability <= 1)",
        name="probability_range",
    ),
    CheckConstraint(
        "ci80_low IS NULL OR ci80_high IS NULL OR ci80_low <= ci80_high",
        name="interval_ordered",
    ),
    CheckConstraint(
        "approval_probability IS NULL OR ci80_low IS NOT NULL",
        name="point_estimate_needs_interval",
    ),
    CheckConstraint(
        "months_p10 IS NULL OR months_p50 IS NULL OR months_p90 IS NULL OR "
        "(months_p10 <= months_p50 AND months_p50 <= months_p90)",
        name="months_ordered",
    ),
)
Index("ix_prediction_application_id", prediction.c.application_id)
Index(
    "ix_prediction_jurisdiction_id_created_at",
    prediction.c.jurisdiction_id,
    prediction.c.created_at,
)


ledger_entry = Table(
    "ledger_entry",
    metadata,
    Column("seq", BigInteger, primary_key=True, autoincrement=True),
    Column("prediction_id", BigInteger, ForeignKey("prediction.id"), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False, server_default=_now),
    Column(
        "payload",
        JSONB,
        nullable=False,
        comment="The exact record that was hashed. Stored verbatim so anyone can recompute.",
    ),
    Column("payload_hash", String(64), nullable=False),
    Column("prev_hash", String(64), nullable=False, comment="64 zeros for the genesis entry"),
    Column("entry_hash", String(64), nullable=False, comment="sha256(prev_hash || payload_hash)"),
    Column("anchor_reference", Text, nullable=True, comment="Independent timestamping receipt"),
    Column("resolved_outcome", Text, nullable=True),
    Column("resolved_on", Date, nullable=True),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("grading", JSONB, nullable=True, comment="Brier contribution, interval hit, note"),
    Column(
        "miss_note",
        Text,
        nullable=True,
        comment="Section 8.5. Written explanation of what the model missed, published as is.",
    ),
    UniqueConstraint("prediction_id", name="uq_ledger_entry_prediction_id"),
    UniqueConstraint("entry_hash", name="uq_ledger_entry_entry_hash"),
    _one_of("resolved_outcome", OUTCOMES, name="resolved_outcome_vocabulary", nullable=True),
    CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_format"),
    CheckConstraint("entry_hash ~ '^[0-9a-f]{64}$'", name="entry_hash_format"),
    CheckConstraint("prev_hash ~ '^[0-9a-f]{64}$'", name="prev_hash_format"),
)
Index("ix_ledger_entry_published_at", ledger_entry.c.published_at)
Index(
    "ix_ledger_entry_unresolved",
    ledger_entry.c.published_at,
    postgresql_where=text("resolved_at IS NULL"),
)


# ===========================================================================
# STAGE 11 - MONITORING
# ===========================================================================

watch = Table(
    "watch",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("subscriber", Text, nullable=False, comment="API key label until billing exists"),
    Column("label", Text, nullable=False),
    Column(
        "jurisdiction_id",
        BigInteger,
        ForeignKey("jurisdiction.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("site", JSONB, nullable=False),
    Column(
        "last_prediction_id",
        BigInteger,
        ForeignKey("prediction.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("subscriber", "label", name="uq_watch_subscriber_label"),
)
Index("ix_watch_jurisdiction_id_active", watch.c.jurisdiction_id, watch.c.active)


change_event = Table(
    "change_event",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "jurisdiction_id",
        BigInteger,
        ForeignKey("jurisdiction.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("trigger", Text, nullable=False),
    Column("detected_on", Date, nullable=False),
    Column("document_id", String(64), ForeignKey("document.id"), nullable=True),
    Column("before", JSONB, nullable=True),
    Column("after", JSONB, nullable=True),
    Column(
        "materiality",
        Numeric(4, 3),
        nullable=False,
        comment="0 to 1. Alerts below the send threshold are recorded but not delivered, because "
        "an alert system that cries wolf gets muted in a week.",
    ),
    Column("summary", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    _one_of("trigger", ALERT_TRIGGERS, name="trigger_vocabulary"),
    CheckConstraint("materiality >= 0 AND materiality <= 1", name="materiality_range"),
)
Index(
    "ix_change_event_jurisdiction_id_detected_on",
    change_event.c.jurisdiction_id,
    change_event.c.detected_on,
)


alert = Table(
    "alert",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("watch_id", BigInteger, ForeignKey("watch.id", ondelete="CASCADE"), nullable=False),
    Column(
        "change_event_id",
        BigInteger,
        ForeignKey("change_event.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("materiality", Numeric(4, 3), nullable=False),
    Column("headline", Text, nullable=False),
    Column("body", Text, nullable=False),
    Column("score_before", Numeric(6, 5), nullable=True),
    Column("score_after", Numeric(6, 5), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    # Delivery bookkeeping. An alert product whose queue can be blocked by one permanently failing
    # recipient is an alert product that stops delivering, silently, and nobody notices because the
    # symptom is an absence. The attempt count is what lets a poison row be skipped rather than
    # retried forever, and the last error is what lets an operator see why without reading logs.
    Column("delivery_attempts", Integer, nullable=False, server_default=text("0")),
    Column("delivery_error", Text, nullable=True),
    Column("delivery_channel", Text, nullable=True),
    Column("suppressed_reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_now),
    UniqueConstraint("watch_id", "change_event_id", name="uq_alert_watch_id_change_event_id"),
)
Index(
    "ix_alert_undelivered",
    alert.c.created_at,
    postgresql_where=text("delivered_at IS NULL AND suppressed_reason IS NULL"),
)


# ===========================================================================
# Convenience groupings used by the loaders and the tests
# ===========================================================================

REGISTRY_TABLES = (jurisdiction, decision_body, decision_maker, election, source)
GRAPH_TABLES = (
    instrument,
    parcel,
    entity_cluster,
    entity_alias,
    application,
    vote,
    objection,
    event,
    precedent_link,
    jurisdiction_chain,
)
PROVENANCE_TABLES = (document, document_page, document_chunk, transcript_segment, fact_evidence)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "GRAPH_TABLES",
    "PROVENANCE_TABLES",
    "REGISTRY_TABLES",
    "alert",
    "application",
    "change_event",
    "dead_letter",
    "decision_body",
    "decision_maker",
    "document",
    "document_chunk",
    "document_page",
    "election",
    "entity_alias",
    "entity_cluster",
    "event",
    "extraction_run",
    "fact_evidence",
    "feature_snapshot",
    "fetch_attempt",
    "instrument",
    "jurisdiction",
    "jurisdiction_chain",
    "ledger_entry",
    "merge_audit",
    "metadata",
    "model_run",
    "parcel",
    "precedent_link",
    "prediction",
    "source",
    "transcript_segment",
    "vote",
    "watch",
]
