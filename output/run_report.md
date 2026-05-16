# Revel pipeline run

- **run_id**: `20260516T202409Z-020d7cdc`
- **pipeline_version**: `0.1.0`
- **produced_at (UTC)**: 2026-05-16T20:25:02.374940+00:00
- **source_csv**: `input/restaurants.csv`
- **published_parquet**: `output/20260516T202409Z-020d7cdc/restaurants.parquet`

## Status

✅ **OK**

## Stage timings (seconds)

- ingest: 2.58
- clean: 2.82
- deduplicate: 5.21
- enrich_deterministic: 1.85
- enrich_llm: 40.51
- validate_publish: 0.00

## Stage 1 — Ingest

- **distinct_counts**:
  - **city**: 22
  - **price_point**: 5
  - **primary_type**: 102

- **null_counts**:
  - **city**: 4
  - **display_address**: 108
  - **google_place_id**: 5
  - **id**: 0
  - **latitude**: 1
  - **longitude**: 1
  - **name**: 0
  - **price_point**: 206
  - **primary_type**: 0
  - **website**: 15

- **row_count**: 1073

## Stage 2 — Clean

- **distinct_values**:
  - **city_canonical**: 22
  - **price_point**: 3
  - **primary_type**: 102

- **flag_counts**:
  - **missing_address**: 108
  - **missing_city**: 4
  - **missing_coords**: 1
  - **missing_place_id**: 5
  - **missing_price_point**: 206
  - **missing_website**: 15
  - **unknown_price_point**: 2

- **null_after_clean**:
  - **city_canonical**: 4
  - **geohash7**: 1
  - **google_place_id**: 5
  - **latitude**: 1
  - **longitude**: 1
  - **name_core**: 0
  - **postal_code**: 108
  - **price_point**: 208
  - **primary_type**: 0
  - **state_code**: 0
  - **website**: 15

- **rejected_place_id_samples**: []
- **row_count**: 1073

## Stage 3 — Deduplicate

- **cluster_count**: 987
- **cluster_size_histogram**:
  - **1**: 912
  - **2**: 64
  - **3**: 11

- **edge_count_by_tier**:
  - **A**: 38
  - **B**: 90

- **largest_cluster_size**: 3
- **singleton_count**: 912

## Stage 4 — Enrichment (cuisine + romance)

- **cuisine**:
  - **rows_deterministic**: 546
  - **rows_llm_failed**: 0
  - **rows_llm_low_confidence**: 5
  - **rows_llm_resolved**: 436
  - **rows_total**: 987

- **cuisine_distribution**:
  - **African**: 7
  - **American**: 278
  - **Asian Fusion**: 24
  - **Chinese**: 22
  - **Dessert**: 1
  - **European**: 18
  - **Filipino**: 4
  - **French**: 72
  - **Indian**: 25
  - **Italian**: 100
  - **Japanese**: 126
  - **Korean**: 29
  - **Latin American**: 24
  - **Mediterranean**: 40
  - **Mexican**: 39
  - **Middle Eastern**: 8
  - **Other**: 49
  - **Pizza**: 9
  - **Seafood**: 28
  - **Southeast Asian**: 6
  - **Spanish**: 14
  - **Steakhouse**: 40
  - **Thai**: 7
  - **Vegetarian/Vegan**: 6
  - **Vietnamese**: 6
  - **__null__**: 5

- **romance**:
  - **rows_deterministic**: 459
  - **rows_llm_failed**: 0
  - **rows_llm_resolved**: 528
  - **rows_total**: 987

- **romance_score_histogram**:
  - **0**: 3
  - **10**: 1
  - **20**: 13
  - **30**: 25
  - **40**: 34
  - **50**: 90
  - **60**: 236
  - **70**: 292
  - **80**: 279
  - **90**: 14

- **rows_total**: 987

---
_Per-run JSON artifacts under `output/<run_id>/`. This report is overwritten each run; archive it manually if you need history._