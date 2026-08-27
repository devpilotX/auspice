"""The extraction schemas.

Section 6.4 decision: extraction uses schema enforced structured output, never free text that is
parsed afterwards. Free text parsing is where data pipelines go to die.

The schemas are JSON Schema documents rather than Pydantic models, for one reason: they are sent
to the provider as the structured output contract, and they are validated locally against the
same document. One artefact, two uses, no chance of the two drifting apart.

Every schema is versioned, and the version is part of the extraction cache key. Changing a schema
invalidates the cache for that schema and nothing else.

The five rules from section 6.4 appear here as structure, not as instructions:

  1. ``evidence`` has ``minItems: 1``. A fact with no source is rejected by the schema, not by a
     code review.
  2. Quotes are required and are verified separately against the source text.
  3. ``additionalProperties: false`` everywhere, so a model that invents a field fails loudly.
  4. ``unknown`` and ``null`` are always valid members. Guessing is a failure.
  5. ``confidence`` is required, so a low confidence extraction can be routed to review rather
     than silently trusted.
"""

from __future__ import annotations

from typing import Any, Final

from auspice.domain import (
    BODY_KINDS,
    EVENT_TYPES,
    INSTRUMENT_KINDS,
    OBJECTION_GROUNDS,
    OUTCOMES,
    RELIEFS,
    USE_CLASSES,
)

SCHEMA_VERSION: Final = "1.0.0"

_EVIDENCE: Final[dict[str, Any]] = {
    "type": "array",
    "minItems": 1,
    "maxItems": 6,
    "description": (
        "Where this fact came from. Quote the document, do not paraphrase it. Every quote is "
        "checked against the source text character for character, and a quote that is not found "
        "verbatim causes the whole extraction to be discarded."
    ),
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["page", "quote"],
        "properties": {
            "page": {"type": "integer", "minimum": 1},
            "quote": {
                "type": "string",
                "minLength": 10,
                "maxLength": 500,
                "description": "Copied exactly from the document, including punctuation.",
            },
        },
    },
}

_CONFIDENCE: Final[dict[str, Any]] = {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": (
        "How confident you are in this extraction. Below 0.6 it is routed to human review "
        "rather than used. Reporting low confidence is correct behaviour, not failure."
    ),
}


def _nullable(*types: str) -> list[str]:
    return [*types, "null"]


# ---------------------------------------------------------------------------
# Decision events
# ---------------------------------------------------------------------------
DECISION_EVENT_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "decision_event",
    "description": (
        "One thing a public body did to one application. If the document describes several "
        "applications, return one object per application. If it describes none, return an empty "
        "list: that is a correct answer and the common one."
    ),
    "type": "object",
    "additionalProperties": False,
    "required": ["event_type", "outcome", "confidence", "evidence"],
    "properties": {
        "event_type": {"enum": list(EVENT_TYPES)},
        "body": {"enum": [*BODY_KINDS, None]},
        "case_number": {
            "type": _nullable("string"),
            "maxLength": 80,
            "description": "The case number exactly as the document prints it. Null if absent.",
        },
        "applicant": {"type": _nullable("string"), "maxLength": 300},
        "project_name": {"type": _nullable("string"), "maxLength": 300},
        "use_class": {"enum": [*USE_CLASSES, None]},
        "relief_sought": {
            "type": "array",
            "items": {"enum": list(RELIEFS)},
            "maxItems": 8,
            "description": "Every separate approval being asked for. Each one is a failure point.",
        },
        "filed_on": {"type": _nullable("string"), "format": "date"},
        "decided_on": {"type": _nullable("string"), "format": "date"},
        "outcome": {"enum": list(OUTCOMES)},
        "vote": {
            "type": _nullable("string"),
            "pattern": "^[0-9]+-[0-9]+(-[0-9]+)?$",
            "description": (
                "The tally in the direction of the outcome, for example 4-1. Null unless the "
                "document states the numbers. Do not convert the word unanimous into a tally."
            ),
        },
        "staff_recommendation": {
            "enum": ["approve", "approve_with_conditions", "deny", "none", None]
        },
        "conditions": {
            "type": "array",
            "items": {"type": "string", "maxLength": 500},
            "maxItems": 40,
        },
        "objection_grounds": {
            "type": "array",
            "items": {"enum": list(OBJECTION_GROUNDS)},
            "maxItems": 12,
            "description": "Grounds actually raised in the document, not grounds you expect.",
        },
        "organised_opposition": {"type": _nullable("boolean")},
        "speakers_against": {"type": _nullable("integer"), "minimum": 0},
        "acres": {"type": _nullable("number"), "exclusiveMinimum": 0},
        "capacity_mw": {"type": _nullable("number"), "exclusiveMinimum": 0},
        "confidence": _CONFIDENCE,
        "evidence": _EVIDENCE,
    },
}

# ---------------------------------------------------------------------------
# Instruments: the rules, and when they changed
# ---------------------------------------------------------------------------
INSTRUMENT_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "instrument",
    "description": (
        "A rule that was adopted, proposed, or allowed to expire. Moratoria and overlay districts "
        "matter most: a rule change inside the last 180 days is the single most dangerous "
        "condition for a pending application."
    ),
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "adopted", "confidence", "evidence"],
    "properties": {
        "kind": {"enum": list(INSTRUMENT_KINDS)},
        "citation": {"type": _nullable("string"), "maxLength": 120},
        "title": {"type": _nullable("string"), "maxLength": 300},
        "adopted": {
            "type": "boolean",
            "description": (
                "True if the body adopted it. False if it was proposed and failed. A proposal that "
                "failed is a real and useful observation, so record it rather than omitting it."
            ),
        },
        "adopted_on": {"type": _nullable("string"), "format": "date"},
        "effective_on": {"type": _nullable("string"), "format": "date"},
        "expires_on": {"type": _nullable("string"), "format": "date"},
        "vote": {"type": _nullable("string"), "pattern": "^[0-9]+-[0-9]+(-[0-9]+)?$"},
        "applies_to_use_classes": {
            "type": "array",
            "items": {"enum": list(USE_CLASSES)},
            "maxItems": 12,
        },
        "restrictions": {
            "type": "object",
            "additionalProperties": False,
            "description": "Numeric limits stated in the document. Omit anything not stated.",
            "properties": {
                "setback_ft": {"type": _nullable("number"), "minimum": 0},
                "setback_from": {"type": _nullable("string"), "maxLength": 120},
                "height_ft": {"type": _nullable("number"), "minimum": 0},
                "noise_dba": {"type": _nullable("number"), "minimum": 0},
                "noise_measured_at": {"type": _nullable("string"), "maxLength": 120},
                "min_acres": {"type": _nullable("number"), "minimum": 0},
                "max_acres": {"type": _nullable("number"), "minimum": 0},
                "water_gpd_cap": {"type": _nullable("number"), "minimum": 0},
                "capacity_mw_cap": {"type": _nullable("number"), "minimum": 0},
                "stops_acceptance": {"type": _nullable("boolean")},
                "stops_processing": {"type": _nullable("boolean")},
                "stops_approval": {"type": _nullable("boolean")},
                "applies_to_unincorporated_only": {"type": _nullable("boolean")},
            },
        },
        "confidence": _CONFIDENCE,
        "evidence": _EVIDENCE,
    },
}

# ---------------------------------------------------------------------------
# Triage: is this document worth the frontier model at all?
# ---------------------------------------------------------------------------
TRIAGE_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "triage",
    "description": (
        "Cheap first pass. Roughly nine documents in ten are irrelevant to a given use class, and "
        "discovering that with a frontier model costs thirty times more than it needs to."
    ),
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "document_kind", "confidence"],
    "properties": {
        "relevant": {
            "type": "boolean",
            "description": "Does this document contain a decision, a rule change, or an objection "
            "concerning the target use classes?",
        },
        "document_kind": {
            "enum": [
                "agenda",
                "minutes",
                "staff_report",
                "ordinance",
                "resolution",
                "comprehensive_plan",
                "application_packet",
                "legal_notice",
                "other",
            ]
        },
        "target_use_classes_mentioned": {
            "type": "array",
            "items": {"enum": list(USE_CLASSES)},
            "maxItems": 12,
        },
        "pages_of_interest": {
            "type": "array",
            "items": {"type": "integer", "minimum": 1},
            "maxItems": 40,
        },
        "confidence": _CONFIDENCE,
    },
}

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
SCHEMAS: Final[dict[str, dict[str, Any]]] = {
    "decision_event": DECISION_EVENT_SCHEMA,
    "instrument": INSTRUMENT_SCHEMA,
    "triage": TRIAGE_SCHEMA,
}


def array_wrapper(schema_name: str) -> dict[str, Any]:
    """A document usually contains several facts, so the provider is asked for a list.

    Wrapped in an object with one property because most structured output APIs require the root to
    be an object. The empty list is explicitly valid and explicitly correct for the majority of
    documents.
    """
    inner = SCHEMAS[schema_name]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "maxItems": 40,
                "description": f"Zero or more {schema_name} objects. An empty list is correct when "
                "the document contains none.",
                "items": inner,
            }
        },
    }


def get_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMAS:
        raise KeyError(f"unknown extraction schema: {name}. Known: {sorted(SCHEMAS)}")
    return SCHEMAS[name]
