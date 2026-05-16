-- raw_restaurants
--
-- Typed pull from the source CSV. No transforms, no filters; this is the
-- ingest boundary contract.
--
-- The source table is read by dbt-duckdb as `all_varchar=true` so DuckDB
-- never silently guesses types differently across runs. We do the casting
-- here, in SQL, with explicit error handling: a malformed `id`, latitude
-- or longitude will fail dbt with a clear error message naming the column.

{{ config(materialized='view') }}

SELECT
    CAST(id           AS BIGINT)  AS id,
    CAST(name         AS VARCHAR) AS name,
    CAST(city         AS VARCHAR) AS city,
    CAST(display_address AS VARCHAR) AS display_address,
    CAST(google_place_id AS VARCHAR) AS google_place_id,
    TRY_CAST(latitude  AS DOUBLE) AS latitude,
    TRY_CAST(longitude AS DOUBLE) AS longitude,
    CAST(price_point  AS VARCHAR) AS price_point,
    CAST(primary_type AS VARCHAR) AS primary_type,
    CAST(website      AS VARCHAR) AS website
FROM {{ source('raw', 'restaurants') }}
