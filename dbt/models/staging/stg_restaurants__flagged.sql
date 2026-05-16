-- stg_restaurants__flagged
--
-- Adds `_quality_flags LIST(VARCHAR)` to stg_restaurants. Each flag is a
-- short snake_case label naming a specific quality concern; the union of
-- these labels per row is the contract downstream stages depend on.
--
-- Flag catalog (extend as new checks land):
--   unknown_city            — city present in raw but not in city_canonical
--   missing_city            — city was NULL after trim/null-string handling
--   missing_address         — display_address NULL after cleaning
--   invalid_place_id        — non-NULL raw place_id was rejected
--   missing_place_id        — raw place_id NULL or empty
--   invalid_coords          — non-NULL raw lat/lon failed bbox / origin check
--   missing_coords          — coords NULL in source
--   unknown_price_point     — non-NULL raw price_point not in mapping
--   missing_price_point     — price_point NULL in source
--   missing_website         — website NULL in source
--
-- Implementation note: we re-read raw_restaurants to compute "was the
-- *raw* value non-NULL?" — without that join we couldn't distinguish
-- "missing in source" from "rejected during cleaning".

{{ config(materialized='view') }}

WITH base AS (
    SELECT
        s.*,
        r.city AS raw_city,
        r.display_address AS raw_display_address,
        r.google_place_id AS raw_google_place_id,
        r.latitude AS raw_latitude,
        r.longitude AS raw_longitude,
        r.price_point AS raw_price_point,
        r.website AS raw_website
    FROM {{ ref('stg_restaurants') }} s
    INNER JOIN {{ ref('raw_restaurants') }} r USING (id)
)

SELECT
    id, name, name_core,
    city_raw, city_canonical,
    display_address, state_code, postal_code,
    google_place_id, google_place_id_raw,
    latitude, longitude, geohash7,
    price_point, primary_type, region_hint,
    website, website_raw,

    -- Build the flag list. NULL-safe equality (`IS DISTINCT FROM`) keeps
    -- the SQL terse; we filter empty strings out at the end.
    LIST_FILTER(
        [
            CASE WHEN raw_city IS NOT NULL AND city_canonical IS NULL
                 THEN 'unknown_city' END,
            CASE WHEN raw_city IS NULL
                 THEN 'missing_city' END,
            CASE WHEN raw_display_address IS NULL
                 THEN 'missing_address' END,
            CASE WHEN raw_google_place_id IS NOT NULL AND google_place_id IS NULL
                 THEN 'invalid_place_id' END,
            CASE WHEN raw_google_place_id IS NULL
                 THEN 'missing_place_id' END,
            CASE WHEN (raw_latitude IS NOT NULL AND raw_longitude IS NOT NULL)
                  AND latitude IS NULL
                 THEN 'invalid_coords' END,
            CASE WHEN raw_latitude IS NULL OR raw_longitude IS NULL
                 THEN 'missing_coords' END,
            CASE WHEN raw_price_point IS NOT NULL AND price_point IS NULL
                 THEN 'unknown_price_point' END,
            CASE WHEN raw_price_point IS NULL
                 THEN 'missing_price_point' END,
            CASE WHEN raw_website IS NULL
                 THEN 'missing_website' END
        ],
        x -> x IS NOT NULL
    ) AS _quality_flags
FROM base
