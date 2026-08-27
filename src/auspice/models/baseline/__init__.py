"""Base rate benchmark and the gradient boosted floor."""

from __future__ import annotations

from auspice.models.baseline.base_rate import BaseRateModel
from auspice.models.baseline.boosted import BoostedModel, default_params

__all__ = ["BaseRateModel", "BoostedModel", "default_params"]
