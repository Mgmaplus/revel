-- dim_restaurants__pre_agent
--
-- Stage 4a output. The ONLY intermediate Parquet boundary in v1 (see
-- ADR-004). Materialized as `external` Parquet at `data/pre_agent/...`
-- so the Python LLM enrichment in Stage 4b can read it via Polars
-- without holding a DuckDB connection (and therefore without needing
-- the UDFs registered).
--
-- Selects the columns Stage 4b actually needs, plus the `_needs_llm_*`
-- flags that drive its routing (LLM path vs deterministic pass-through).

{{ config(
    materialized='external',
    location=env_var('REVEL_PRE_AGENT_PARQUET', '../data/pre_agent/restaurants.parquet'),
    format='parquet'
) }}

SELECT
    canonical_id,
    source_ids,
    name,
    name_core,
    city_canonical,
    state_code,
    display_address,
    postal_code,
    google_place_id,
    latitude,
    longitude,
    geohash7,
    price_point,
    primary_type,
    region_hint,
    website,
    website_raw,
    cuisine,
    cuisine_secondary,
    ambiance,
    intimacy,
    quietness,
    dining_experience,
    cuisine_fit,
    romance_score,
    _needs_llm_cuisine,
    _needs_llm_romance,
    _quality_flags,
    dedup_confidence,
    dedup_tier
FROM {{ ref('int_restaurants__enriched_det') }}
