"""Unit tests for the dedup pure-function primitives.

Per Step 3 directive: keep tests minimal and mandatory only. We pin:
  - haversine returns 0 for the same point and grows monotonically
  - name_similarity is symmetric
  - tier A groups by place_id correctly
  - tier B respects all three thresholds (ratio, distance, state)
  - cluster_ids handles singletons + transitive merges
"""

from __future__ import annotations

from revel.dedup_clusters import (
    Edge,
    cluster_ids,
    edges_tier_a,
    edges_tier_b,
    haversine_meters,
    name_similarity,
)


def test_haversine_zero_for_same_point() -> None:
    assert haversine_meters(40.0, -73.0, 40.0, -73.0) == 0.0


def test_haversine_within_150m_for_close_points() -> None:
    # Two points ~70m apart in NYC.
    d = haversine_meters(40.7128, -74.0060, 40.7134, -74.0060)
    assert 50 < d < 100


def test_haversine_large_for_distant_points() -> None:
    # NYC ↔ LA is ~3,940 km.
    d = haversine_meters(40.7128, -74.0060, 34.0522, -118.2437)
    assert 3_900_000 < d < 4_000_000


def test_name_similarity_symmetric() -> None:
    assert name_similarity("Traif", "traif") == name_similarity("traif", "Traif")


def test_tier_a_groups_by_place_id() -> None:
    edges = edges_tier_a(
        [
            (1, "ChIJabc"),
            (2, "ChIJabc"),
            (3, "ChIJxyz"),
            (4, None),
            (5, "ChIJabc"),
        ]
    )
    # ids {1,2,5} share place_id → 3 unordered pairs.
    pairs = {(e.id_a, e.id_b) for e in edges}
    assert pairs == {(1, 2), (1, 5), (2, 5)}
    assert all(e.tier == "A" and e.confidence == 1.0 for e in edges)


def test_tier_b_filters_low_ratio() -> None:
    candidates = [
        # name very different — ratio < 92.
        (1, "soba house", 40.0, -73.0, "NY", 2, "ramen palace", 40.0001, -73.0001, "NY"),
    ]
    edges = edges_tier_b(candidates, name_ratio_min=92, geo_match_meters=150)
    assert edges == []


def test_tier_b_filters_far_distance() -> None:
    candidates = [
        # Same name, but ~1km apart (way over 150m threshold).
        (1, "ivan ramen", 40.7128, -74.0060, "NY", 2, "ivan ramen", 40.7218, -74.0060, "NY"),
    ]
    edges = edges_tier_b(candidates, name_ratio_min=92, geo_match_meters=150)
    assert edges == []


def test_tier_b_filters_different_state() -> None:
    candidates = [
        # Same name + close coords but different states (impossible in
        # reality at this distance, but the rule must still hold).
        (1, "carbone", 40.0, -73.0, "NY", 2, "carbone", 40.0001, -73.0001, "NV"),
    ]
    edges = edges_tier_b(candidates, name_ratio_min=92, geo_match_meters=150)
    assert edges == []


def test_tier_b_accepts_match() -> None:
    # Identical name, ~10m apart, same state.
    candidates = [
        (1, "ivan ramen", 40.7128, -74.0060, "NY", 2, "ivan ramen", 40.7129, -74.0060, "NY"),
    ]
    edges = edges_tier_b(candidates, name_ratio_min=92, geo_match_meters=150)
    assert len(edges) == 1
    assert edges[0].tier == "B"
    assert edges[0].confidence >= 0.85


def test_cluster_ids_singletons_and_chain() -> None:
    # 1-2 connected, 3 alone, 4-5-6 chain.
    edges = [
        Edge(1, 2, "A", 1.0),
        Edge(4, 5, "B", 0.9),
        Edge(5, 6, "B", 0.9),
    ]
    mapping = cluster_ids([1, 2, 3, 4, 5, 6], edges)
    # canonical_id = min(component)
    assert mapping == {1: 1, 2: 1, 3: 3, 4: 4, 5: 4, 6: 4}


def test_cluster_ids_transitive_via_different_tiers() -> None:
    # A-B via Tier A, B-C via Tier B → all three end up in one cluster.
    edges = [Edge(1, 2, "A", 1.0), Edge(2, 3, "B", 0.9)]
    assert cluster_ids([1, 2, 3], edges) == {1: 1, 2: 1, 3: 1}
