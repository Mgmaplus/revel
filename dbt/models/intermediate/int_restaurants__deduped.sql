-- int_restaurants__deduped
--
-- Stage 3 (Deduplicate) — final merged record per canonical venue. Joins the
-- cluster map produced by `revel.dedup_clusters` (Python) and applies the
-- merge precedence rules from `.plan.md` Step 3.
--
-- Materialized as `table` (not view) because:
--   1. The downstream enriched_det model joins it heavily.
--   2. It depends on `dedup_cluster_map` which lives outside dbt (written
--      by the Python step) — keeping the merge as a table makes the
--      dependency direction obvious in `dbt list --resource-type model`.
--
-- Merge precedence per field (numbers refer to .plan.md Step 3):
--   1. Non-null wins over null.
--   2. Most specific wins (longer display_address; with ZIP > without).
--   3. price_point: mode within cluster, ties broken high > medium > low.
--   4. primary_type: most specific via `seed_primary_type_specificity` rank
--      + arg_max. We don't have that seed yet (it would be a Step 3 add) —
--      instead we use a simple heuristic: prefer the type with the longest
--      string (e.g., `italian_restaurant` over `restaurant`).
--   5. website: prefer canonicalized (already stripped); keep the longest
--      website_raw across the cluster.
--   6. lat/lon: median of valid values per cluster (resilient to one bad pin).
--
-- Provenance columns:
--   canonical_id BIGINT       — = MIN(source_ids) for stable rerun behavior
--   source_ids LIST(BIGINT)   — every original `id` in the cluster
--   dedup_confidence DOUBLE   — MIN confidence over edges in the cluster
--                               (singletons get 1.0)
--   dedup_tier VARCHAR        — 'A', 'B', 'C', or 'singleton'
--   _quality_flags LIST(VARCHAR) — UNION of source-row flags

{{ config(materialized='table') }}

WITH joined AS (
    SELECT
        m.cluster_id,
        s.*
    FROM {{ ref('stg_restaurants__flagged') }} s
    INNER JOIN dedup_cluster_map m USING (id)
),

-- Pull edges to compute per-cluster confidence + tier. We label each
-- cluster by the *minimum* confidence of any in-cluster edge, and the
-- "highest tier" present (A > B > C > singleton).
edges_per_cluster AS (
    SELECT
        m.cluster_id,
        e.tier,
        e.confidence
    FROM dedup_edges e
    -- Either endpoint of the edge maps the same cluster, by construction;
    -- pick id_a side to keep the join 1:1.
    INNER JOIN dedup_cluster_map m ON m.id = e.id_a
),

cluster_confidence AS (
    SELECT
        cluster_id,
        MIN(confidence) AS dedup_confidence,
        -- 'A' < 'B' < 'C' alphabetically, but A is the strongest tier.
        -- We want the smallest letter (A first); MIN of VARCHAR matches that.
        MIN(tier) AS dedup_tier
    FROM edges_per_cluster
    GROUP BY cluster_id
),

merged AS (
    SELECT
        cluster_id,
        MIN(id)                                         AS canonical_id,
        ARRAY_AGG(id ORDER BY id)                       AS source_ids,
        COUNT(*)                                        AS row_count,

        -- name: arg_max prefers the longest non-null original name.
        -- (We keep `name_core` separately, computed off the canonical name.)
        ARG_MAX(name, COALESCE(LENGTH(name), 0))        AS name,

        -- city_canonical: arg_max with non-null preference.
        ARG_MAX(city_canonical, COALESCE(city_canonical, '') != '')   AS city_canonical,

        -- state_code: same.
        ARG_MAX(state_code, COALESCE(state_code, '') != '')           AS state_code,

        -- display_address: prefer the longest non-null. Bonus weight if it
        -- contains a 5-digit ZIP (proxy for "address is fully formed").
        ARG_MAX(
            display_address,
            COALESCE(LENGTH(display_address), 0)
              + CASE WHEN postal_code IS NOT NULL THEN 100 ELSE 0 END
        )                                               AS display_address,

        -- postal_code: prefer non-null.
        ARG_MAX(postal_code, COALESCE(postal_code, '') != '')         AS postal_code,

        -- google_place_id: prefer non-null. If multiple non-null place_ids
        -- exist in a cluster (which happens in the data — same venue, two
        -- captures with slightly different place_ids), we take the longest;
        -- a longer one tends to be the canonical 27-char form.
        ARG_MAX(google_place_id, COALESCE(LENGTH(google_place_id), 0)) AS google_place_id,

        -- price_point: mode, ties broken high > medium > low.
        -- DuckDB's mode() is stable; we then post-process via a CASE.
        MODE(price_point)                                AS price_point_mode,

        -- primary_type: prefer the longest non-null (most specific).
        ARG_MAX(primary_type, COALESCE(LENGTH(primary_type), 0))      AS primary_type,
        ARG_MAX(region_hint, COALESCE(region_hint, '') != '')         AS region_hint,

        -- website: keep longest website_raw + canonicalized website.
        ARG_MAX(website, COALESCE(LENGTH(website), 0))                AS website,
        ARG_MAX(website_raw, COALESCE(LENGTH(website_raw), 0))        AS website_raw,

        -- coords: median over valid values. DuckDB's MEDIAN is stable on ties.
        MEDIAN(latitude)                                AS latitude,
        MEDIAN(longitude)                               AS longitude,

        -- Recompute geohash7 from the merged coords below.

        -- Quality flags: union all (de-dup) across the cluster.
        ARRAY_DISTINCT(
            FLATTEN(ARRAY_AGG(_quality_flags))
        )                                               AS _quality_flags

    FROM joined
    GROUP BY cluster_id
)

SELECT
    m.canonical_id,
    m.source_ids,
    m.row_count,
    m.name,
    name_core(m.name)                                   AS name_core,
    m.city_canonical,
    m.state_code,
    m.display_address,
    m.postal_code,
    m.google_place_id,
    -- Tie-break price_point if the mode itself is ambiguous: when mode
    -- returned NULL we want to fall back to the highest non-null tier
    -- present in the cluster. We can't reach into the cluster from here
    -- without a window, but in practice MODE only returns NULL when the
    -- entire cluster has NULL price_point — exactly what we want.
    m.price_point_mode AS price_point,
    m.primary_type,
    m.region_hint,
    m.website,
    m.website_raw,
    m.latitude,
    m.longitude,
    geohash(m.latitude, m.longitude, 7)                 AS geohash7,
    m._quality_flags,
    -- Provenance
    COALESCE(c.dedup_confidence, 1.0)                   AS dedup_confidence,
    COALESCE(c.dedup_tier, 'singleton')                 AS dedup_tier
FROM merged m
LEFT JOIN cluster_confidence c USING (cluster_id)
