"""Synthetic corpora for testing model mathematics against a known ground truth.

Never used for a published claim. See generator.py for the full explanation.
"""

from __future__ import annotations

from tests.synthetic.generator import (
    FEATURE_COLUMNS,
    SYNTHETIC_MARKER,
    TRUE_COEFFICIENTS,
    SyntheticCorpus,
    generate,
)

__all__ = [
    "FEATURE_COLUMNS",
    "SYNTHETIC_MARKER",
    "TRUE_COEFFICIENTS",
    "SyntheticCorpus",
    "generate",
]
