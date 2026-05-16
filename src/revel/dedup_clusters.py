"""Stage 3 — duplicate detection + cluster assignment.

Pipeline within Stage 3:

  1. dbt builds `int_restaurants__dedup_candidates` (Tier B candidate pairs).
  2. THIS module reads candidates + the staging frame, computes:
       Tier A — exact `google_place_id` match (SQL group-by, in Python)
       Tier B — score candidates via rapidfuzz + haversine, filter
       Tier C — website match (off by default, see ADR)
     and writes one `dedup_edges` table + a `dedup_cluster_map(id, cluster_id)`
     table back into the same DuckDB file.
  3. dbt builds `int_restaurants__deduped` from the cluster map.

We compute connected components in Python because DuckDB has no native
graph primitives and because the operation is well under a millisecond
on the v1 dataset size (~1k rows, ~hundred edges). See ADR-001 for the
reasoning behind keeping this single Python step inside an otherwise-SQL
pipeline.

All thresholds come from `Settings.dedup` so they can be tuned per-run
via YAML / env without touching code.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import duckdb
import networkx as nx
from rapidfuzz import fuzz

from revel.config import DedupSettings
from revel.dbt_plugin import register_udfs
from revel.logging_setup import get_logger

# --- pure scoring primitives --------------------------------------------------

# Earth radius in meters. Used for haversine distance.
_EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance between two coordinates, in meters.

    Pure function — no side effects, no external state. Used both
    in production (Tier B scoring) and in tests.
    """
    phi_a = math.radians(lat_a)
    phi_b = math.radians(lat_b)
    d_phi = math.radians(lat_b - lat_a)
    d_lambda = math.radians(lon_b - lon_a)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


def name_similarity(a: str, b: str) -> float:
    """Token-set ratio (0–100). Order-insensitive, set-based.

    Wraps `rapidfuzz.fuzz.token_set_ratio` so callers don't need to know
    which specific scorer we use.
    """
    return float(fuzz.token_set_ratio(a, b))


# --- edge dataclasses --------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Edge:
    """A match between two `id`s with a tier label and confidence."""

    id_a: int
    id_b: int
    tier: str  # 'A', 'B', or 'C'
    confidence: float


# --- tier implementations ----------------------------------------------------


def edges_tier_a(rows: Sequence[tuple[int, str | None]]) -> list[Edge]:
    """Tier A — exact place_id match. Pure function: input → output.

    rows : iterable of (id, google_place_id) for the staging frame.
    Returns: list of edges (one per pair within each place_id group),
    confidence 1.0.
    """
    by_place: dict[str, list[int]] = {}
    for row_id, place_id in rows:
        if place_id is None or place_id == "":
            continue
        by_place.setdefault(place_id, []).append(row_id)

    edges: list[Edge] = []
    for ids in by_place.values():
        if len(ids) < 2:
            continue
        ids_sorted = sorted(ids)
        for i, id_a in enumerate(ids_sorted):
            for id_b in ids_sorted[i + 1 :]:
                edges.append(Edge(id_a=id_a, id_b=id_b, tier="A", confidence=1.0))
    return edges


# Type alias for the candidate-pair tuple from int_restaurants__dedup_candidates.
# (id_a, name_core_a, lat_a, lon_a, state_a, id_b, name_core_b, lat_b, lon_b, state_b)
CandidatePair = tuple[int, str, float, float, str | None, int, str, float, float, str | None]


def edges_tier_b(
    candidates: Iterable[CandidatePair],
    *,
    name_ratio_min: int,
    geo_match_meters: int,
) -> list[Edge]:
    """Tier B — geo + name match. Scores each candidate and keeps survivors.

    candidates: tuples of (id_a, name_a, lat_a, lon_a, state_a,
                           id_b, name_b, lat_b, lon_b, state_b)
                produced by `int_restaurants__dedup_candidates`.
    name_ratio_min: rapidfuzz threshold (0–100). Per plan default: 92.
    geo_match_meters: haversine threshold. Per plan default: 150.

    Confidence formula (per plan): 0.85 + (ratio − 92) * 0.01, clamped to [0.85, 1.0).
    """
    edges: list[Edge] = []
    for id_a, name_a, lat_a, lon_a, state_a, id_b, name_b, lat_b, lon_b, state_b in candidates:
        # State sanity: same state OR one is null. Different non-null states
        # is a hard reject (e.g., two `Carbone` rows in NYC vs Vegas).
        if state_a is not None and state_b is not None and state_a != state_b:
            continue

        ratio = name_similarity(name_a, name_b)
        if ratio < name_ratio_min:
            continue

        distance = haversine_meters(lat_a, lon_a, lat_b, lon_b)
        if distance > geo_match_meters:
            continue

        confidence = min(0.99, 0.85 + (ratio - name_ratio_min) * 0.01)
        edges.append(Edge(id_a=id_a, id_b=id_b, tier="B", confidence=confidence))
    return edges


def edges_tier_c(
    rows: Sequence[tuple[int, str | None, str | None]],
) -> list[Edge]:
    """Tier C — website match within same canonical city.

    Off by default in v1 (config-gated). Chains like Uchi, Carbone, and
    Le Jardinier legitimately share websites across cities, so we only
    enable Tier C when geo signals are missing on both sides AND the
    operator has consciously turned it on.

    rows: (id, website, city_canonical).
    """
    by_key: dict[tuple[str, str], list[int]] = {}
    for row_id, website, city in rows:
        if not website or not city:
            continue
        by_key.setdefault((website, city), []).append(row_id)

    edges: list[Edge] = []
    for ids in by_key.values():
        if len(ids) < 2:
            continue
        ids_sorted = sorted(ids)
        for i, id_a in enumerate(ids_sorted):
            for id_b in ids_sorted[i + 1 :]:
                edges.append(Edge(id_a=id_a, id_b=id_b, tier="C", confidence=0.80))
    return edges


# --- connected components --------------------------------------------------


def cluster_ids(all_ids: Iterable[int], edges: Iterable[Edge]) -> dict[int, int]:
    """Compute connected-components and return id → cluster_id.

    cluster_id is `min(component)` so it's stable across reruns: as long
    as the underlying ids are stable, identical input → identical cluster_ids.
    Singletons (rows in no edge) get their own id as cluster_id.
    """
    g: nx.Graph = nx.Graph()
    g.add_nodes_from(all_ids)
    for e in edges:
        g.add_edge(e.id_a, e.id_b)

    mapping: dict[int, int] = {}
    for component in nx.connected_components(g):
        canonical = min(component)
        for node in component:
            mapping[node] = canonical
    return mapping


# --- DuckDB I/O wrapper -----------------------------------------------------


@dataclass(slots=True, frozen=True)
class DedupReport:
    edge_count_by_tier: dict[str, int]
    cluster_count: int
    singleton_count: int
    largest_cluster_size: int
    cluster_size_histogram: dict[int, int]


def run_dedup(duckdb_path: str, settings: DedupSettings) -> DedupReport:
    """Read staging tables, compute edges + clusters, write back.

    Side effects (all inside `data/revel.duckdb`):
      - drops + recreates `dedup_edges(id_a, id_b, tier, confidence)`
      - drops + recreates `dedup_cluster_map(id, cluster_id)`

    Idempotent given the same inputs + settings.
    """
    log = get_logger(__name__)

    with duckdb.connect(duckdb_path) as conn:
        register_udfs(conn)

        # --- Tier A: place_id group-by ---
        rows_a = conn.sql("SELECT id, google_place_id FROM stg_restaurants__flagged").fetchall()
        edges_a = edges_tier_a([(int(r[0]), r[1]) for r in rows_a])

        # --- Tier B: read candidates from the dbt-built view, score in Python ---
        candidates = conn.sql(
            "SELECT id_a, name_core_a, lat_a, lon_a, state_a, "
            "       id_b, name_core_b, lat_b, lon_b, state_b "
            "FROM int_restaurants__dedup_candidates"
        ).fetchall()
        edges_b = edges_tier_b(
            (
                (
                    int(c[0]),
                    str(c[1]),
                    float(c[2]),
                    float(c[3]),
                    c[4],
                    int(c[5]),
                    str(c[6]),
                    float(c[7]),
                    float(c[8]),
                    c[9],
                )
                for c in candidates
            ),
            name_ratio_min=settings.name_ratio_min,
            geo_match_meters=settings.geo_match_meters,
        )

        # --- Tier C: optional, website match ---
        edges_c: list[Edge] = []
        if settings.enable_tier_c:
            rows_c = conn.sql(
                "SELECT id, website, city_canonical FROM stg_restaurants__flagged"
            ).fetchall()
            edges_c = edges_tier_c([(int(r[0]), r[1], r[2]) for r in rows_c])

        all_edges: list[Edge] = [*edges_a, *edges_b, *edges_c]

        # --- All ids, including singletons that have no edges ---
        all_ids_rows = conn.sql("SELECT id FROM stg_restaurants__flagged").fetchall()
        all_ids = [int(r[0]) for r in all_ids_rows]

        cluster_map = cluster_ids(all_ids, all_edges)

        # --- Persist edges + cluster map back into DuckDB ---
        # We use staging tables + INSERT so the column types are explicit and
        # don't depend on DuckDB's pandas inference.
        conn.execute("DROP TABLE IF EXISTS dedup_edges")
        conn.execute(
            """
            CREATE TABLE dedup_edges (
                id_a       BIGINT NOT NULL,
                id_b       BIGINT NOT NULL,
                tier       VARCHAR NOT NULL,
                confidence DOUBLE NOT NULL,
                PRIMARY KEY (id_a, id_b, tier)
            )
            """
        )
        if all_edges:
            conn.executemany(
                "INSERT INTO dedup_edges (id_a, id_b, tier, confidence) VALUES (?, ?, ?, ?)",
                [(e.id_a, e.id_b, e.tier, e.confidence) for e in all_edges],
            )

        conn.execute("DROP TABLE IF EXISTS dedup_cluster_map")
        conn.execute(
            """
            CREATE TABLE dedup_cluster_map (
                id         BIGINT PRIMARY KEY,
                cluster_id BIGINT NOT NULL
            )
            """
        )
        conn.executemany(
            "INSERT INTO dedup_cluster_map (id, cluster_id) VALUES (?, ?)",
            list(cluster_map.items()),
        )

    # --- Build a small report (stats only — no row data) -------------------
    cluster_sizes: dict[int, int] = {}
    for cluster_id in cluster_map.values():
        cluster_sizes[cluster_id] = cluster_sizes.get(cluster_id, 0) + 1

    histogram: dict[int, int] = {}
    for size in cluster_sizes.values():
        histogram[size] = histogram.get(size, 0) + 1

    edge_count_by_tier: dict[str, int] = {}
    for e in all_edges:
        edge_count_by_tier[e.tier] = edge_count_by_tier.get(e.tier, 0) + 1

    largest = max(cluster_sizes.values()) if cluster_sizes else 0
    singleton_count = sum(1 for s in cluster_sizes.values() if s == 1)

    log.info(
        "dedup.complete",
        edges_a=edge_count_by_tier.get("A", 0),
        edges_b=edge_count_by_tier.get("B", 0),
        edges_c=edge_count_by_tier.get("C", 0),
        clusters=len(cluster_sizes),
        singletons=singleton_count,
        largest_cluster=largest,
    )

    return DedupReport(
        edge_count_by_tier=edge_count_by_tier,
        cluster_count=len(cluster_sizes),
        singleton_count=singleton_count,
        largest_cluster_size=largest,
        cluster_size_histogram={k: v for k, v in sorted(histogram.items())},
    )


def write_dedup_report(report: DedupReport, out_path: Any) -> None:
    """Atomic write of dedup report JSON to `output/<run_id>/03_dedup_report.json`."""
    import json
    from pathlib import Path

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "edge_count_by_tier": report.edge_count_by_tier,
        "cluster_count": report.cluster_count,
        "singleton_count": report.singleton_count,
        "largest_cluster_size": report.largest_cluster_size,
        "cluster_size_histogram": report.cluster_size_histogram,
    }
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(out)
