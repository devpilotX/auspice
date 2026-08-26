"""Stage 4: extraction into a strict schema, with verbatim quote verification."""

from __future__ import annotations

from auspice.pipeline.extract.client import Completion, LanguageModel, Usage, cache_key
from auspice.pipeline.extract.pipeline import ExtractionReport, extract_document, render_for_model
from auspice.pipeline.extract.prompts import PROMPT_VERSION, Prompt, get_prompt
from auspice.pipeline.extract.schemas import SCHEMA_VERSION, array_wrapper, get_schema
from auspice.pipeline.extract.verify import (
    QuoteLocation,
    VerificationResult,
    quote_verification_rate,
    verify_extraction_evidence,
    verify_quote,
    verify_stored_citations,
)

__all__ = [
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
    "Completion",
    "ExtractionReport",
    "LanguageModel",
    "Prompt",
    "QuoteLocation",
    "Usage",
    "VerificationResult",
    "array_wrapper",
    "cache_key",
    "extract_document",
    "get_prompt",
    "get_schema",
    "quote_verification_rate",
    "render_for_model",
    "verify_extraction_evidence",
    "verify_quote",
    "verify_stored_citations",
]
