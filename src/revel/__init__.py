"""Revel — restaurant CSV → production-grade dataset pipeline.

Pipeline architecture: see `.kiro/steering/architecture-decisions.md`.
Implementation plan: see `.plan.md`.
"""

from __future__ import annotations

# `pipeline_version` is embedded in published Parquet metadata + run reports.
# Bump on any change to output schema or transform semantics (see ADR-003).
pipeline_version: str = "0.1.0"

__all__ = ["pipeline_version"]
