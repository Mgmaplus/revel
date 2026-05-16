-- stg_restaurants
--
-- Stage 2 (Clean & Normalize). Per-column canonicalization of the raw input.
-- Pure SQL except for three Python UDFs registered by `revel.dbt_plugin`:
-- `clean_url`, `geohash`, `name_core`. See plan.md Step 2 for the rule table.
--
-- Originals are preserved where useful (`name`, `website_raw`) so downstream
-- stages can prefer specificity. Quality issues are NOT flagged here; the
-- `stg_restaurants__flagged` view layered on top builds `_quality_flags`.

{{ config(materialized='view') }}

WITH cleaned AS (
    SELECT
        r.id,

        -- Names
        r.name AS name,
        name_core(r.name) AS name_core,

        -- City: normalize via lookup. Trim, strip surrounding quotes,
        -- lowercase before joining. Unknown cities pass through as NULL
        -- canonical + carry their state_code as NULL.
        TRIM(BOTH '"' FROM TRIM(r.city)) AS city_raw,
        cc.canonical AS city_canonical,

        -- Display address: trim, collapse whitespace, drop trailing
        -- ", USA" / ", United States" so address comparisons line up.
        REGEXP_REPLACE(
            REGEXP_REPLACE(
                TRIM(r.display_address),
                '\s+',
                ' ',
                'g'
            ),
            ',\s*(USA|United States)\s*$',
            '',
            'i'
        ) AS display_address,

        -- State + postal code extracted from the cleaned address. We trust
        -- the canonical city's state_code where available; otherwise we
        -- read it off the address pattern "<two upper letters> <5 digits>".
        COALESCE(
            cc.state_code,
            UPPER(REGEXP_EXTRACT(r.display_address, '\b([A-Z]{2})\s+\d{5}', 1))
        ) AS state_code,
        REGEXP_EXTRACT(r.display_address, '\b\d{5}(-\d{4})?\b', 0) AS postal_code,

        -- Place ID: trim. Validity is checked in __flagged; here we just
        -- normalize the surface form and null obvious junk (whitespace).
        NULLIF(TRIM(r.google_place_id), '') AS google_place_id_raw,

        -- Coordinates: range-check inline so downstream stages can trust
        -- non-NULL values without re-validating. The bbox covers continental
        -- US + AK + HI + PR.
        CASE
            WHEN r.latitude IS NULL OR r.longitude IS NULL THEN NULL
            WHEN r.latitude = 0 AND r.longitude = 0 THEN NULL
            WHEN r.latitude < 17 OR r.latitude > 72 THEN NULL
            WHEN r.longitude < -180 OR r.longitude > -65 THEN NULL
            ELSE r.latitude
        END AS latitude,
        CASE
            WHEN r.latitude IS NULL OR r.longitude IS NULL THEN NULL
            WHEN r.latitude = 0 AND r.longitude = 0 THEN NULL
            WHEN r.latitude < 17 OR r.latitude > 72 THEN NULL
            WHEN r.longitude < -180 OR r.longitude > -65 THEN NULL
            ELSE r.longitude
        END AS longitude,

        -- price_point: lookup → canonical or NULL.
        ppm.canonical AS price_point,

        -- primary_type: lowercase, snake-cased already; strip trailing _us /
        -- _restaurant_us into a region_hint for the cuisine step.
        LOWER(
            REGEXP_REPLACE(
                COALESCE(r.primary_type, ''),
                '(_us|_restaurant_us)$',
                '',
                'i'
            )
        ) AS primary_type,
        CASE
            WHEN r.primary_type IS NULL THEN NULL
            WHEN r.primary_type ILIKE '%_us' OR r.primary_type ILIKE '%_restaurant_us' THEN 'us'
            ELSE NULL
        END AS region_hint,

        -- website: keep the raw value for human reference; canonicalize via
        -- our Python UDF (defensive — see dbt_plugin.clean_url for rules).
        r.website AS website_raw,
        clean_url(r.website) AS website,

        -- Geo blocking key — only meaningful when coords passed range check.
        CASE
            WHEN r.latitude IS NULL OR r.longitude IS NULL THEN NULL
            WHEN r.latitude = 0 AND r.longitude = 0 THEN NULL
            WHEN r.latitude < 17 OR r.latitude > 72 THEN NULL
            WHEN r.longitude < -180 OR r.longitude > -65 THEN NULL
            ELSE geohash(r.latitude, r.longitude, 7)
        END AS geohash7

    FROM {{ ref('raw_restaurants') }} r
    LEFT JOIN {{ ref('city_canonical') }} cc
        ON LOWER(TRIM(BOTH '"' FROM TRIM(r.city))) = cc.raw
    LEFT JOIN {{ ref('price_point_mapping') }} ppm
        ON LOWER(TRIM(r.price_point)) = ppm.raw
)

SELECT
    c.id,
    c.name,
    c.name_core,
    c.city_raw,
    c.city_canonical,
    c.display_address,
    c.state_code,
    c.postal_code,
    -- place_id: NULL if too short OR doesn't start with an allowed prefix.
    -- The prefix check is a startswith match against the seed table.
    CASE
        WHEN c.google_place_id_raw IS NULL THEN NULL
        WHEN LENGTH(c.google_place_id_raw) < 20 THEN NULL
        WHEN c.google_place_id_raw !~ '^[A-Za-z0-9_-]+$' THEN NULL
        WHEN NOT EXISTS (
            SELECT 1 FROM {{ ref('place_id_prefixes') }} p
            WHERE c.google_place_id_raw LIKE p.prefix || '%'
        ) THEN NULL
        ELSE c.google_place_id_raw
    END AS google_place_id,
    c.google_place_id_raw,
    c.latitude,
    c.longitude,
    c.geohash7,
    c.price_point,
    c.primary_type,
    c.region_hint,
    c.website,
    c.website_raw
FROM cleaned c
