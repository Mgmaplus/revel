"""Stage 1 — ingest-stage helpers invoked by the orchestrator after dbt.

dbt does the actual ingestion: `raw_restaurants` is a view over the source
CSV with explicit casts. This module only computes the per-stage stats
that the run report needs (row count, null counts, distinct counts).

Per ADR-004 we don't write a Parquet snapshot here; intermediate state
lives in DuckDB. We do write a small JSON stats file under the run dir.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

from revel.dbt_plugin import register_udfs

from .schemas import RAW_COLUMNS

# Columns we care to profile distinctly in the run report.
DISTINCT_REPORT_COLUMNS: tuple[str, ...] = ("price_point", "primary_type", "city")


@dataclass(slots=True, frozen=True)
class IngestStats:
    """Summary of what arrived from the source CSV after dbt parsing."""

    row_count: int
    null_counts: dict[str, int]
    distinct_counts: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def compute_ingest_stats(duckdb_path: Path, model_name: str = "raw_restaurants") -> IngestStats:
    """Connect to the DuckDB file (read-only) and profile the raw view.

    Raises if the model is missing — that means dbt didn't run successfully.
    """
    if not duckdb_path.is_file():
        raise FileNotFoundError(
            f"DuckDB file not found at {duckdb_path}. "
            f"Run `just dbt build --select {model_name}` first."
        )

    null_select = ", ".join(
        f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null__{col}" for col in RAW_COLUMNS
    )
    distinct_select = ", ".join(
        f"COUNT(DISTINCT {col}) AS distinct__{col}" for col in DISTINCT_REPORT_COLUMNS
    )

    with duckdb.connect(str(duckdb_path), read_only=True) as conn:
        register_udfs(conn)
        row_count_row = conn.sql(f"SELECT COUNT(*) AS n FROM {model_name}").fetchone()
        if row_count_row is None:
            raise RuntimeError(f"Could not read row count from {model_name}")
        row_count = int(row_count_row[0])

        null_row = conn.sql(f"SELECT {null_select} FROM {model_name}").fetchone()
        if null_row is None:
            raise RuntimeError(f"Could not read null counts from {model_name}")
        null_counts = {col: int(val) for col, val in zip(RAW_COLUMNS, null_row, strict=True)}

        distinct_row = conn.sql(f"SELECT {distinct_select} FROM {model_name}").fetchone()
        if distinct_row is None:
            raise RuntimeError(f"Could not read distinct counts from {model_name}")
        distinct_counts = {
            col: int(val) for col, val in zip(DISTINCT_REPORT_COLUMNS, distinct_row, strict=True)
        }

    return IngestStats(
        row_count=row_count,
        null_counts=null_counts,
        distinct_counts=distinct_counts,
    )


def write_ingest_stats(stats: IngestStats, out_path: Path) -> None:
    """Atomic write of the stats JSON next to the rest of the run artifacts."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(stats.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(out_path)
