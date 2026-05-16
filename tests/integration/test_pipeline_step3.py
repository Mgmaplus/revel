"""End-to-end smoke test for Step 3.

Per Step 3 directive: keep tests minimal. We assert:
  - the known fixture duplicates collapse to single canonical rows
  - canonical_id is unique post-dedup
  - dedup_tier values come from the closed set
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from pipelines.restaurant_pipeline import run_pipeline
from revel.config import Settings
from revel.dbt_plugin import register_udfs


@pytest.fixture()
def deduped_conn(repo_root: Path, fixture_csv: Path, tmp_pipeline_dirs: tuple[Path, Path]):
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
def test_canonical_id_unique(deduped_conn) -> None:
    row = deduped_conn.sql(
        "SELECT COUNT(*), COUNT(DISTINCT canonical_id) FROM int_restaurants__deduped"
    ).fetchone()
    assert row is not None
    assert row[0] == row[1]  # rows == distinct canonicals


@pytest.mark.integration
def test_known_dup_pairs_collapse(deduped_conn) -> None:
    """Each pair below should land in a single cluster (one row in the
    deduped table containing both source ids)."""
    pairs = [
        (97527, 108742, "A"),  # Traif/traif — Tier A (same place_id)
        (43717, 108718, "A"),  # Dirt Candy — Tier A
        (74275, 108766, "A"),  # Antoine's typo — Tier A
    ]
    for id_a, id_b, expected_tier in pairs:
        row = deduped_conn.sql(
            "SELECT canonical_id, source_ids, dedup_tier FROM int_restaurants__deduped "
            "WHERE list_contains(source_ids, ?) OR list_contains(source_ids, ?)",
            params=[id_a, id_b],
        ).fetchall()
        assert len(row) == 1, f"expected 1 cluster for ({id_a},{id_b}); got {len(row)}"
        sources = list(row[0][1])
        assert id_a in sources and id_b in sources, f"both ids missing: {sources}"
        assert row[0][2] == expected_tier


@pytest.mark.integration
def test_ivan_ramen_three_way_collapse(deduped_conn) -> None:
    row = deduped_conn.sql(
        "SELECT canonical_id, source_ids, dedup_tier FROM int_restaurants__deduped "
        "WHERE list_contains(source_ids, 7788)"
    ).fetchone()
    assert row is not None
    sources = list(row[1])
    assert {7788, 108719, 108720}.issubset(set(sources))


@pytest.mark.integration
def test_dedup_tier_in_closed_set(deduped_conn) -> None:
    bad = deduped_conn.sql(
        "SELECT COUNT(*) FROM int_restaurants__deduped "
        "WHERE dedup_tier NOT IN ('A','B','C','singleton')"
    ).fetchone()
    assert bad is not None and bad[0] == 0
