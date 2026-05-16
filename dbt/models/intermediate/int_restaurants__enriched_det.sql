-- int_restaurants__enriched_det
--
-- Stage 4a (Deterministic enrichment). Joins the deduped frame against:
--   - `cuisine_taxonomy` seed → `cuisine`, `cuisine_secondary`
--   - `romance_rubric` seed → 5 sub-scores + composite `romance_score`
--
-- Rows where the join misses set `_needs_llm_cuisine` / `_needs_llm_romance`
-- to TRUE, signaling that Stage 4b (Python LLM enrichment) must fill them in.
--
-- v1 NOTE: `cities_by_geohash5` reverse-geocode fill is intentionally not
-- implemented yet. Only 4 rows in the v1 dataset have NULL city_canonical
-- and they already carry `missing_city` flags. Adding offline reverse-geocode
-- is tracked in the v2 backlog (see architecture-decisions.md).

{{ config(materialized='table') }}

WITH base AS (
    SELECT * FROM {{ ref('int_restaurants__deduped') }}
),

with_cuisine AS (
    SELECT
        b.*,
        ct.cuisine,
        ct.cuisine_secondary,
        (ct.cuisine IS NULL) AS _needs_llm_cuisine
    FROM base b
    LEFT JOIN {{ ref('cuisine_taxonomy') }} ct
        ON b.primary_type = ct.primary_type
),

with_romance AS (
    SELECT
        wc.*,
        -- Romance sub-scores from the rubric seed. Deterministic match requires
        -- both primary_type AND price_point to match.
        rr.ambiance,
        rr.intimacy,
        rr.quietness,
        rr.dining_experience,
        rr.cuisine_fit,
        (rr.primary_type IS NULL) AS _needs_llm_romance
    FROM with_cuisine wc
    LEFT JOIN {{ ref('romance_rubric') }} rr
        ON wc.primary_type = rr.primary_type
        AND wc.price_point IS NOT DISTINCT FROM rr.price_point
)

SELECT
    *,
    -- Composite romance_score. Weights are pinned here to match the plan
    -- defaults; configurable weights live in `local.yaml` and are read by
    -- the LLM romance step. v1: deterministic rows use the default weights;
    -- changing them requires a rebuild.
    CASE
        WHEN _needs_llm_romance THEN NULL
        ELSE CAST(ROUND(
            10 * (
                0.25 * ambiance
                + 0.20 * intimacy
                + 0.15 * quietness
                + 0.20 * dining_experience
                + 0.20 * cuisine_fit
            )
        ) AS INTEGER)
    END AS romance_score
FROM with_romance
