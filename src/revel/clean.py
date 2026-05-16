"""Stage 2 — clean-stage stats produced after dbt builds the staging models.

Mirrors `ingest.compute_ingest_stats`: connects to the DuckDB warehouse
read-only, runs aggregate queries, and writes a small JSON summary to
`output/<run_id>/02_clean_stats.json`. No row data ever leaves DuckDB.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb


@dataclass(slots=True, frozen=True)
class CleanStats:
    """Stage 2 summary: counts of cleaning outcomes per column."""

    row_count: int
    flag_counts: dict[str, int] = field(default_factory=dict)
    null_after_clean: dict[str, int] = field(default_factory=dict)
    distinct_values: dict[str, int] = field(default_factory=dict)
    rejected_place_id_samples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# Columns where post-cleaning null counts are most informative.
_NULL_TRACKED: tuple[str, ...] = (
    "name_core",
    "city_canonical",
    "state_code",
    "postal_code",
    "google_place_id",
    "latitude",
    "longitude",
    "geohash7",
    "price_point",
    "primary_type",
    "website",
)

# Columns whose distinct counts go in the run report.
_DISTINCT_TRACKED: tuple[str, ...] = ("city_canonical", "price_point", "primary_type")


def compute_clean_stats(
    duckdb_path: Path, model_name: str = "stg_restaurants__flagged"
) -> CleanStats:
    if not duckdb_path.is_file():
        raise FileNotFoundError(
            f"DuckDB file not found at {duckdb_path}. "
            f"Run `just dbt build --select {model_name}` first."
        )

    null_select = ", ".join(
        f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS null__{col}" for col in _NULL_TRACKED
    )
    distinct_select = ", ".join(
        f"COUNT(DISTINCT {col}) AS distinct__{col}" for col in _DISTINCT_TRACKED
    )

    with duckdb.connect(str(duckdb_path), read_only=True) as conn:
        # Row count.
        row_count_row = conn.sql(f"SELECT COUNT(*) FROM {model_name}").fetchone()
        if row_count_row is None:
            raise RuntimeError(f"Could not read row count from {model_name}")
        row_count = int(row_count_row[0])

        # Flag counts: explode the LIST(VARCHAR) and group.
        flag_rows = conn.sql(
            f"""
            SELECT flag, COUNT(*) AS n
            FROM {model_name}, UNNEST(_quality_flags) AS t(flag)
            GROUP BY flag
            ORDER BY n DESC
            """
        ).fetchall()
        flag_counts = {str(flag): int(n) for flag, n in flag_rows}

        # Per-column nulls + distincts in a single round-trip each.
        null_row = conn.sql(f"SELECT {null_select} FROM {model_name}").fetchone()
        if null_row is None:
            raise RuntimeError(f"Could not read null counts from {model_name}")
        null_after_clean = {col: int(val) for col, val in zip(_NULL_TRACKED, null_row, strict=True)}

        distinct_row = conn.sql(f"SELECT {distinct_select} FROM {model_name}").fetchone()
        if distinct_row is None:
            raise RuntimeError(f"Could not read distinct counts from {model_name}")
        distinct_values = {
            col: int(val) for col, val in zip(_DISTINCT_TRACKED, distinct_row, strict=True)
        }

        # Surface a small sample of rejected place_ids so a human can spot-check.
        # Per .plan.md Step 2 risk mitigation.
        sample_rows = conn.sql(
            f"""
            SELECT DISTINCT google_place_id_raw
            FROM {model_name}
            WHERE google_place_id IS NULL
              AND google_place_id_raw IS NOT NULL
            LIMIT 10
            """
        ).fetchall()
        rejected_place_id_samples = [str(r[0]) for r in sample_rows]

    return CleanStats(
        row_count=row_count,
        flag_counts=flag_counts,
        null_after_clean=null_after_clean,
        distinct_values=distinct_values,
        rejected_place_id_samples=rejected_place_id_samples,
    )


def write_clean_stats(stats: CleanStats, out_path: Path) -> None:
    """Atomic write of stats JSON next to the rest of the run artifacts."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(stats.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(out_path)
