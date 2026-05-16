"""Stage 5 (Validate). v1: minimal Polars-based integrity checks.

Failure semantics: any **error** aborts publish (fail-closed). Warnings
are logged but pass through. Per `architecture-decisions.md` §6 and
`security-rules.md` (fail securely).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from revel.enrich.llm.schemas import CUISINE_VALUES
from revel.logging_setup import get_logger

# US-region bbox (matches staging).
_US_LAT = (17.0, 72.0)
_US_LON = (-180.0, -65.0)
_PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
_VALID_PRICE = {"low", "medium", "high"}


@dataclass(slots=True)
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_published_frame(df: pl.DataFrame) -> ValidationReport:
    """Run cross-row + column-shape checks. Pure: input → report."""
    log = get_logger(__name__)
    report = ValidationReport()

    # Required columns present?
    required = {
        "canonical_id", "name", "city_canonical", "latitude", "longitude",
        "price_point", "cuisine", "romance_score", "google_place_id",
        "source_ids",
    }
    missing = required - set(df.columns)
    if missing:
        report.errors.append(f"missing required columns: {sorted(missing)}")
        return report  # nothing else is meaningful

    # 1. canonical_id non-null + unique.
    n_null_id = int(df.select(pl.col("canonical_id").is_null().sum()).item())
    if n_null_id:
        report.errors.append(f"{n_null_id} rows have NULL canonical_id")
    n = df.height
    n_distinct = df.select(pl.col("canonical_id").n_unique()).item()
    if n_distinct != n:
        report.errors.append(f"canonical_id not unique ({n} rows, {n_distinct} distinct)")

    # 2. name non-empty.
    n_empty_name = int(
        df.select(
            (pl.col("name").is_null() | (pl.col("name").str.strip_chars() == "")).sum()
        ).item()
    )
    if n_empty_name:
        report.errors.append(f"{n_empty_name} rows have NULL or empty name")

    # 3. lat/lon both null OR both in US bbox.
    bad_geo = df.filter(
        (pl.col("latitude").is_null() != pl.col("longitude").is_null())
        | (
            pl.col("latitude").is_not_null()
            & ~(pl.col("latitude").is_between(_US_LAT[0], _US_LAT[1]))
        )
        | (
            pl.col("longitude").is_not_null()
            & ~(pl.col("longitude").is_between(_US_LON[0], _US_LON[1]))
        )
    )
    if bad_geo.height:
        report.errors.append(f"{bad_geo.height} rows have invalid lat/lon")

    # 4. price_point ∈ closed set or NULL.
    bad_price = int(
        df.select(
            (pl.col("price_point").is_not_null() & ~pl.col("price_point").is_in(list(_VALID_PRICE)))
            .sum()
        ).item()
    )
    if bad_price:
        report.errors.append(f"{bad_price} rows have invalid price_point")

    # 5. cuisine ∈ taxonomy or NULL.
    bad_cuisine = int(
        df.select(
            (pl.col("cuisine").is_not_null() & ~pl.col("cuisine").is_in(list(CUISINE_VALUES))).sum()
        ).item()
    )
    if bad_cuisine:
        report.errors.append(f"{bad_cuisine} rows have invalid cuisine")

    # 6. romance_score ∈ [0,100] or NULL.
    bad_score = int(
        df.select(
            (
                pl.col("romance_score").is_not_null()
                & ~pl.col("romance_score").is_between(0, 100)
            ).sum()
        ).item()
    )
    if bad_score:
        report.errors.append(f"{bad_score} rows have invalid romance_score")

    # 7. google_place_id format if non-null.
    bad_place = (
        df.filter(pl.col("google_place_id").is_not_null())
        .select(
            (~pl.col("google_place_id").str.contains(_PLACE_ID_RE.pattern)).sum()
        )
        .item()
    )
    if bad_place:
        report.errors.append(f"{bad_place} rows have malformed google_place_id")

    # 8. No duplicate non-null place_id post-dedup.
    pid_groups = (
        df.filter(pl.col("google_place_id").is_not_null())
        .group_by("google_place_id")
        .len()
        .filter(pl.col("len") > 1)
    )
    if pid_groups.height:
        report.errors.append(f"{pid_groups.height} place_ids have >1 row post-dedup")

    # 9. Cuisine null-rate warning.
    null_cuisine_rate = float(df.select(pl.col("cuisine").is_null().mean()).item() or 0.0)
    if null_cuisine_rate > 0.05:
        report.warnings.append(
            f"cuisine null rate {null_cuisine_rate:.1%} exceeds 5% threshold"
        )

    log.info(
        "validate.complete",
        errors=len(report.errors),
        warnings=len(report.warnings),
        cuisine_null_rate=round(null_cuisine_rate, 4),
    )
    return report


def validate_parquet(path: Path) -> ValidationReport:
    return validate_published_frame(pl.read_parquet(path))
