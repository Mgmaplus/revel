"""End-to-end smoke test for Step 1.

Runs the orchestrator against the 20-row fixture in `--dry-run` mode and
asserts that:
1. dbt build of `raw_restaurants` succeeds.
2. The DuckDB file is created and the view is queryable.
3. `01_ingest_stats.json` is written with the expected shape.

This is the canary that breaks first if dbt/profiles.yml/sources.yml drift
out of sync. Slow-ish (~1–2s per run) but invaluable.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from pipelines.restaurant_pipeline import run_pipeline
from revel.config import Settings


@pytest.mark.integration
def test_pipeline_runs_stage1_on_fixture(
    repo_root: Path, fixture_csv: Path, tmp_pipeline_dirs: tuple[Path, Path]
) -> None:
    data_dir, output_dir = tmp_pipeline_dirs
    settings = Settings(
        input_path=fixture_csv,
        output_dir=output_dir,
        data_dir=data_dir,
        duckdb_path=data_dir / "revel.duckdb",
        dry_run=True,
        log_level="WARNING",  # quiet test output
    )

    run_dir = run_pipeline(settings, repo_root=repo_root)

    assert run_dir.is_dir()
    stats_path = run_dir / "01_ingest_stats.json"
    assert stats_path.is_file(), f"expected stats at {stats_path}"

    payload = json.loads(stats_path.read_text())
    assert payload["row_count"] == 22, "fixture has 22 data rows"
    # All input columns must show up in the null-count map.
    for col in (
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
    ):
        assert col in payload["null_counts"], f"missing null count for {col}"
    # The fixture deliberately includes a row with null `city` (id 108739).
    assert payload["null_counts"]["city"] >= 1
    # Distinct counts only collected for the report-relevant columns.
    assert set(payload["distinct_counts"].keys()) == {"price_point", "primary_type", "city"}

    # Confirm DuckDB is queryable post-run.
    with duckdb.connect(str(data_dir / "revel.duckdb"), read_only=True) as conn:
        row = conn.sql("SELECT COUNT(*) FROM raw_restaurants").fetchone()
        assert row is not None
        assert int(row[0]) == 22
