-- int_restaurants__dedup_candidates
--
-- Stage 3 (Deduplicate) — emits the Tier B candidate-pair list. This view
-- is consumed by `revel.dedup_clusters` (Python), which scores each pair
-- with rapidfuzz + haversine and filters down to actual matches.
--
-- Tier A (exact place_id) and Tier C (website match, off by default in v1)
-- are computed entirely in Python from `stg_restaurants__flagged`. Only
-- Tier B needs the SQL self-join because the blocking key (geohash6)
-- compresses ~1.1M potential pairs to a few hundred.
--
-- Block on:
--   geohash6           — first 6 chars of the geohash7 column (~1.2km cell)
--   city_canonical     — same canonical city
--   id_a < id_b        — emit each unordered pair only once
--   both lat/lon known — skip rows where bbox check nulled coords
--
-- See `.plan.md` Step 3 for the matching thresholds applied downstream.

{{ config(materialized='view') }}

WITH eligible AS (
    SELECT
        id,
        name_core,
        SUBSTRING(geohash7, 1, 6) AS geohash6,
        city_canonical,
        state_code,
        latitude,
        longitude
    FROM {{ ref('stg_restaurants__flagged') }}
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND geohash7 IS NOT NULL
      AND city_canonical IS NOT NULL
      AND name_core IS NOT NULL
)

SELECT
    a.id            AS id_a,
    a.name_core     AS name_core_a,
    a.latitude      AS lat_a,
    a.longitude     AS lon_a,
    a.state_code    AS state_a,
    b.id            AS id_b,
    b.name_core     AS name_core_b,
    b.latitude      AS lat_b,
    b.longitude     AS lon_b,
    b.state_code    AS state_b
FROM eligible a
INNER JOIN eligible b
    ON a.geohash6 = b.geohash6
    AND a.city_canonical = b.city_canonical
WHERE a.id < b.id
