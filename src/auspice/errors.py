"""Shared error types.

Errors are typed because the pipeline decides what to do based on the kind of failure.
A source that returned 404 goes to the dead letter queue and is retried tomorrow. A quote
that failed verification is discarded and the extraction is retried with a different
prompt. Those are different outcomes and a bare ``Exception`` cannot distinguish them.
"""

from __future__ import annotations


class AuspiceError(Exception):
    """Base class. Nothing raises this directly."""


# ---------------------------------------------------------------------------
# Configuration and environment
# ---------------------------------------------------------------------------
class ConfigurationError(AuspiceError):
    """A required setting is missing or contradictory."""


class StageUnavailableError(AuspiceError):
    """A pipeline stage cannot run because a dependency is absent.

    Raised instead of returning a plausible looking empty result. A stage that silently
    produces nothing looks identical to a stage that found nothing, and those two things
    must never be confused in a corpus.
    """


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
class IngestError(AuspiceError):
    """Base for stage 1 failures."""


class RobotsDisallowedError(IngestError):
    """robots.txt forbids this path. Not retried, and not worked around."""


class FetchError(IngestError):
    """The fetch failed. Carries the status code where there was one."""

    def __init__(self, message: str, *, url: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class RateLimitedError(FetchError):
    """429 or 503. Backs off and retries later rather than pressing on."""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
class ParseError(AuspiceError):
    """A document could not be turned into text by any step of the cascade."""


class IllegibleDocumentError(ParseError):
    """Every step ran and the output failed the legibility gate."""

    def __init__(self, message: str, *, document_id: str, best_score: float) -> None:
        super().__init__(message)
        self.document_id = document_id
        self.best_score = best_score


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
class ExtractionError(AuspiceError):
    """Base for stage 4 failures."""


class SchemaViolationError(ExtractionError):
    """The model returned something the JSON Schema rejects."""

    def __init__(self, message: str, *, errors: list[str]) -> None:
        super().__init__(message)
        self.errors = errors


class QuoteVerificationError(ExtractionError):
    """A quote was not found verbatim in the stored source text.

    Section 6.4 rule 2: the extraction is discarded, not flagged. A citation that does not
    resolve is worse than no citation, because it survives review by looking complete.
    """

    def __init__(self, message: str, *, document_id: str, quote: str) -> None:
        super().__init__(message)
        self.document_id = document_id
        self.quote = quote


# ---------------------------------------------------------------------------
# Modelling and scoring
# ---------------------------------------------------------------------------
class ModelError(AuspiceError):
    """Base for stage 8 and 9 failures."""


class InsufficientDataError(ModelError):
    """There is not enough labelled data to support the operation requested.

    This is a normal outcome, not a bug. The kill test raises it rather than reporting a
    verdict computed on a sample too small to support one.
    """

    def __init__(self, message: str, *, have: int, need: int) -> None:
        super().__init__(message)
        self.have = have
        self.need = need


class LeakageError(ModelError):
    """A feature was computed from information that did not exist on the as-of date."""


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
class LedgerError(AuspiceError):
    """Base for ledger failures."""


class LedgerTamperError(LedgerError):
    """The hash chain does not verify. The ledger is append only and this proves it was not."""
