"""Stage 4b — Python LLM enrichment.

Reads `data/pre_agent/restaurants.parquet`, fills in cuisine + romance
for rows the deterministic stage left blank, and writes
`data/enriched/restaurants.parquet`.

See `cuisine.py`, `romance.py`, and `llm/` for the moving parts.
"""
