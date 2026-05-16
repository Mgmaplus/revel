"""End-to-end smoke test for Step 2.

Runs the orchestrator against the 20-row fixture and asserts the staging
view's outputs are sane: name normalization, place_id validation, geohash
agreement on known duplicates, and `_quality_flags` populated correctly.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from pipelines.restaurant_pipeline import run_pipeline
from revel.config import Settings
from revel.dbt_plugin import register_udfs


@pytest.fixture()
def staging_conn(repo_root: Path, fixture_csv: Path, tmp_pipeline_dirs: tuple[Path, Path]):
    """Run the pipeline once on the fixture and yield a read-only DuckDB
    connection with UDFs registered."""
    data_dir, output_dir = tmp_pipeline_dirs
    settings = Settings(
        input_path=fixture_csv,
        output_dir=output_dir,
        data_dir=data_dir,
        duckdb_path=data_dir / "revel.duckdb",
        dry_run=True,
        log_level="WARNING",
    )
    run_pipeline(settings, repo_root=repo_root)
    conn = duckdb.connect(str(data_dir / "revel.duckdb"), read_only=True)
    register_udfs(conn)
    yield conn
    conn.close()


@pytest.mark.integration
def test_traif_clones_share_geohash_and_name_core(staging_conn) -> None:
    rows = staging_conn.sql(
        "SELECT id, name_core, geohash7 FROM stg_restaurants "
        "WHERE id IN (97527, 108742) ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    # Both Traif rows must collapse to the same blocking key.
    assert rows[0][1] == rows[1][1] == "traif"
    assert rows[0][2] == rows[1][2]


@pytest.mark.integration
def test_dirt_candy_clones_collapse(staging_conn) -> None:
    rows = staging_conn.sql(
        "SELECT name_core FROM stg_restaurants WHERE id IN (43717, 108718)"
    ).fetchall()
    assert {r[0] for r in rows} == {"dirt candy"}


@pytest.mark.integration
def test_price_point_canonicalized(staging_conn) -> None:
    # `budget` → `low`; `unknown` → NULL + flag; raw nulls stay NULL.
    rows = staging_conn.sql(
        "SELECT id, price_point FROM stg_restaurants WHERE id IN (73220, 3648) ORDER BY id"
    ).fetchall()
    by_id = dict(rows)
    assert by_id[3648] is None  # 'unknown' → NULL
    assert by_id[73220] == "low"  # 'budget' → 'low'


@pytest.mark.integration
def test_unknown_price_point_flagged(staging_conn) -> None:
    # id 3648 had price_point = 'unknown' in raw; gets nulled + flagged.
    flags = staging_conn.sql(
        "SELECT _quality_flags FROM stg_restaurants__flagged WHERE id = 3648"
    ).fetchone()
    assert flags is not None
    assert "unknown_price_point" in list(flags[0])


@pytest.mark.integration
def test_url_canonicalized_strips_tracking(staging_conn) -> None:
    # id 101075 (Seasons) has UTM-laden URL.
    row = staging_conn.sql(
        "SELECT website_raw, website FROM stg_restaurants WHERE id = 101075"
    ).fetchone()
    assert row is not None
    raw, clean = row
    assert "utm_" in raw  # raw still has tracking
    assert clean is not None
    assert "utm_" not in clean


@pytest.mark.integration
def test_place_id_validation_zero_false_negatives_on_known_good(staging_conn) -> None:
    # Every fixture row whose raw place_id begins with ChIJ + length>=20 should
    # survive validation.
    rejected = staging_conn.sql(
        """
        SELECT google_place_id_raw FROM stg_restaurants
        WHERE google_place_id IS NULL
          AND google_place_id_raw IS NOT NULL
          AND google_place_id_raw LIKE 'ChIJ%'
          AND LENGTH(google_place_id_raw) >= 20
        """
    ).fetchall()
    assert rejected == []


@pytest.mark.integration
def test_quality_flags_are_listvarchar_nonnull(staging_conn) -> None:
    # No row should have NULL _quality_flags (it's a non-null LIST(VARCHAR)).
    null_count = staging_conn.sql(
        "SELECT COUNT(*) FROM stg_restaurants__flagged WHERE _quality_flags IS NULL"
    ).fetchone()
    assert null_count is not None
    assert null_count[0] == 0
