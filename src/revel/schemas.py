"""Schema contracts at stage boundaries.

Step 1 only defines the *input* contract: the column set we expect from
`raw_restaurants` after dbt has parsed and cast it. Patito models for
later stages (CleanRestaurant, DedupedRestaurant, PublishedRestaurant)
will be added in their respective steps.

We intentionally do not use Patito here yet — the column-presence check
is delegated to dbt source tests in Step 1, and Patito only earns its
keep once we're validating Polars dataframes in the Python enrichment
stage (Step 4b).
"""

from __future__ import annotations

from typing import Final

# Canonical column order produced by `raw_restaurants`. Source-of-truth
# for the ingest stats step and integration tests.
RAW_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "name",
    "city",
    "display_address",
    "google_place_id",
    "latitude",
    "longitude",
    "price_point",
    "primary_type",
    "website",
)

# DuckDB types after `raw_restaurants.sql` casts.
RAW_DUCKDB_TYPES: Final[dict[str, str]] = {
    "id": "BIGINT",
    "name": "VARCHAR",
    "city": "VARCHAR",
    "display_address": "VARCHAR",
    "google_place_id": "VARCHAR",
    "latitude": "DOUBLE",
    "longitude": "DOUBLE",
    "price_point": "VARCHAR",
    "primary_type": "VARCHAR",
    "website": "VARCHAR",
}
