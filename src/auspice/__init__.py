"""Permission Bureau: a rating bureau for the right to build.

The package is one installable distribution whose subpackages map one to one onto
the pipeline stages in section 6 of the master specification.

    auspice.pipeline.registry    stage 0   who actually decides
    auspice.pipeline.adapters    stage 1   civic platform connectors
    auspice.pipeline.ingest      stage 1   fetch, hash, store, dead letter
    auspice.pipeline.parse       stage 2   document cascade and chunking
    auspice.pipeline.transcribe  stage 3   hearing audio to citable transcript
    auspice.pipeline.extract     stage 4   schema enforced facts with verified quotes
    auspice.pipeline.resolve     stage 5   entity resolution
    auspice.pipeline.graph       stage 6   the Permission Graph
    auspice.pipeline.features    stage 7   point in time feature builders
    auspice.models               stage 8   base rate, boosted, hierarchical, survival, hazard
    auspice.models.eval          stage 9   calibration, backtests, the kill test
    auspice.score                stage 10  score object, abstention, explanations, alternatives
    auspice.monitor              stage 11  diffing, materiality, alerts
    auspice.ledger                         the hash committed public prediction ledger
    auspice.memo                           HTML to PDF committee memo
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
