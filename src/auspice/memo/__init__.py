"""The committee memo. Templated HTML rendered to PDF by headless Chromium.

Section 5.3(c): the most underrated surface in the product. The buyer's real job is not to understand
risk, it is to defend a decision to a committee. Sell the artefact, not the dashboard.
"""

from __future__ import annotations

from auspice.memo.generator import TEMPLATE_VERSION, Memo, render, to_pdf

__all__ = ["TEMPLATE_VERSION", "Memo", "render", "to_pdf"]
