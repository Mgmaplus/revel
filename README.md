# Revel — restaurant CSV → production-grade dataset pipeline (v1)

Turns a messy CSV of US restaurants into a deduplicated, cuisine-classified,
romance-scored Parquet dataset. Runs entirely on a single laptop. The only
external dependency is the Gemini API (used in Stage 4 for the rows the
deterministic taxonomy can't classify).

> **Status: v1.** Local-only, manual CLI trigger, ~1k-row dataset. v2 is
> not yet in development — the roadmap (Dagster orchestration, Google
> Places enrichment, threshold notifications, warehouse adapter, LangGraph
> for multi-step agents) lives in `.kiro/steering/architecture-decisions.md`.

---

## Quickstart

```bash
# Requirements: Python 3.12+, uv, just, git
uv sync                                    # install Python deps
cp .env.example .env                       # add GEMINI_API_KEY for live LLM
just pipeline-run --dry-run                # exercises every stage with a stub LLM
```

That writes:

- **`output/<run_id>/restaurants.parquet`** — the canonical dataset (this is what you publish/share)
- **`output/run_report.md`** — single human-readable summary, **overwritten each run** (look here first)
- `output/<run_id>/0N_*.json` — per-stage stats (ingest counts, dedup edges, enrichment distribution)
- `output/<run_id>/metadata.json` — sidecar provenance (pipeline version, git sha, source CSV sha256)
- `output/latest` — symlink to the most recent run

To run with real Gemini calls (drops the `--dry-run` flag):

```bash
echo "GEMINI_API_KEY=your-key-here" >> .env
just pipeline-run                          # ~12s end-to-end on the v1 dataset
```

Cached LLM responses live under `.cache/llm/` — reruns on the same input
are free and deterministic.

### Inspect the published dataset

```bash
# Full Parquet schema + row count
uv run python -c "import polars as pl; df = pl.read_parquet('output/latest/restaurants.parquet'); print(df.schema); print(df.height, 'rows')"

# Look at one venue and its provenance
uv run python -c "import polars as pl; print(pl.read_parquet('output/latest/restaurants.parquet').filter(pl.col('canonical_id') == 7788))"
```

The intermediate DuckDB warehouse at `data/revel.duckdb` is queryable for
debugging. **Note**: `stg_restaurants` references Python UDFs registered
on the connection, so the bare `duckdb` CLI can't query it directly. Use:

```bash
uv run python -c "import duckdb; from revel.dbt_plugin import register_udfs; c = duckdb.connect('data/revel.duckdb', read_only=True); register_udfs(c); print(c.sql('SELECT * FROM stg_restaurants__flagged LIMIT 5').df())"
```

`raw_restaurants` and the `int_*` tables work with the plain CLI.

---

## Pipeline architecture

```
                                       v1 — local only
                                  (single embedded DuckDB file)
┌──────────────────────────────────────────────────────────────────────────────┐
│  input/restaurants.csv                                                       │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               ▼
       ┌──────────────────────────────────────────────────┐
       │  dbt-duckdb (orchestrated by Python subprocess)  │
       │  ┌──────┐    ┌─────────┐    ┌──────────────┐     │
       │  │ raw  │ →  │ staging │ →  │ intermediate │     │
       │  │ view │    │  view   │    │   table      │     │
       │  │      │    │ +tests  │    │ +tests       │     │
       │  └──────┘    └─────────┘    └──────┬───────┘     │
       │                                    ▼             │
       │     ┌──────────────────────────────────────┐     │
       │     │ marts/dim_restaurants__pre_agent     │     │
       │     │ → external Parquet (handoff)         │     │
       │     └──────────────────┬───────────────────┘     │
       └────────────────────────┼─────────────────────────┘
                                ▼
       ┌──────────────────────────────────────────────────┐
       │  Python (Polars + Gemini SDK)                    │
       │  ┌─────────┐  ┌─────────┐                        │
       │  │ cuisine │ →│ romance │  ← LLM cache (diskcache)
       │  │  fill   │  │  fill   │                        │
       │  └─────────┘  └─────────┘                        │
       └──────────────────┬───────────────────────────────┘
                          ▼
       ┌──────────────────────────────────────────────────┐
       │  validate (Patito-style) → publish (atomic       │
       │  Parquet) → notify (run_report.md + log)         │
       └──────────────────────────────────────────────────┘

   The 7 logical stages map to:
   1 Ingest       — dbt source + raw_restaurants
   2 Clean        — dbt staging models + UDF-driven canonicalization
   3 Deduplicate  — dbt candidate-pair view → Python edges + cluster → dbt merge
   4 Fill & Tran  — dbt deterministic enrichment → Python LLM fallback
   5 Validate     — Polars schema + integrity checks
   6 Publish      — atomic Parquet write, embedded provenance metadata
   7 Notify       — single overwriting run_report.md + structured log
```

---

## Stage design decisions (the three that matter)

### Stage 2 — Clean

- **Per-column normalization in pure SQL** wherever it stays readable; three
  Python UDFs (`clean_url`, `geohash`, `name_core`) for transforms that are
  awkward in SQL. UDFs are registered on every dbt connection via the
  `revel.dbt_plugin` plugin.
- **`_quality_flags: LIST(VARCHAR)`** on every row — non-null (possibly empty)
  list of snake_case labels. Downstream stages can rely on this contract.
- **Original values preserved** alongside cleaned ones (`name`, `website_raw`)
  so dedup can prefer specificity and humans can spot-check.
- **Closed-set lookups via dbt seeds**: `city_canonical`, `price_point_mapping`,
  `place_id_prefixes`. Edit a seed, rerun, the change applies uniformly.

### Stage 3 — Deduplicate (3-tier)

- **Tier A — exact `google_place_id`** match. Confidence 1.0. Catches ~95%
  of detectable dupes in the v1 dataset (38 edges).
- **Tier B — geo + name match**. Block by `geohash6` (~1.2km) ∩ same canonical
  city, then score with `rapidfuzz.token_set_ratio` ≥ 92 AND haversine ≤
  150m AND same state code. Catches typo'd / case-variant dupes that don't
  share a place_id (90 edges). SQL does the cheap blocking in
  `int_restaurants__dedup_candidates`; Python does the scoring.
- **Tier C — website match within same city**. **Off by default** — chains
  legitimately share websites across locations.
- **Connected components** via `networkx` in Python; `cluster_id = min(component)`
  for stable rerun behavior. Idempotent: same input + thresholds → identical
  cluster assignments.
- **Merge precedence**: non-null wins, longer/more-specific wins, mode for
  `price_point` (with high > medium > low tiebreak), median for coords
  (resilient to one bad pin), arg_max(LENGTH) for `primary_type`.
- **Provenance kept per row**: `source_ids` (list), `dedup_confidence`,
  `dedup_tier ∈ {A, B, C, singleton}`, `_quality_flags` unioned across cluster.
- v1 dataset signal: 1073 rows → 987 clusters (912 singletons, 64 pairs, 11 triples).

### Stage 4 — Fill & Transform (hybrid)

- **Deterministic-first.** A `cuisine_taxonomy` seed maps `primary_type` →
  one of ~25 closed cuisine categories (Italian, Japanese, Steakhouse, etc.)
  via dbt JOIN. A `romance_rubric` seed maps `(primary_type, price_point)`
  → 5 sub-scores. Together these handle ~55% of cuisines and ~46% of romance
  scoring without an LLM call.
- **LLM fallback for the rest.** Generic types (`restaurant`,
  `fine_dining_restaurant`, `bistro`, `hotel`, `bar`, `cafe`) deliberately
  fall through to Gemini, which gets the **same closed taxonomy as a Pydantic
  `Literal[...]` constraint** so it cannot invent new categories. Confidence
  < 0.6 → NULL + flag (fail closed).
- **Romance scoring is 5-dimensional.** `ambiance`, `intimacy`, `quietness`,
  `dining_experience`, `cuisine_fit` ∈ [0, 10]. Composite =
  `0.25·a + 0.20·i + 0.15·q + 0.20·d + 0.20·c`, scaled to [0, 100]. Weights
  configurable; sub-scores preserved so consumers can re-weight.
- **No agent framework.** Plain Python functions with batched structured-output
  calls. LangGraph/LangChain/agentic routing belong to v2 (see ADR-002).
- **Caching is mandatory.** `diskcache` keyed on
  `sha256(provider + model + prompt + schema_version)`. Reruns are free
  and deterministic.
- **`--dry-run` swaps in `StubLLMClient`.** Tests + CI never need credentials.

---

## Repo layout

See `.kiro/steering/project-overview.md` §4 for the full directory tree
(it's the source of truth and is kept current with the implementation).
TL;DR:

```
.
├── pipelines/restaurant_pipeline.py   # orchestrator (the entry point)
├── dbt/                               # all SQL transforms + seeds + tests
├── src/revel/                         # config, logging, dedup, enrichment, publish
├── configs/local.yaml                 # default config (no secrets)
├── tests/                             # unit + integration
├── input/restaurants.csv              # source data
├── data/revel.duckdb                  # embedded warehouse (gitignored)
├── output/                            # run artifacts (gitignored)
└── .cache/llm/                        # LLM response cache (gitignored)
```

---

## Common tasks

| Goal | Command |
|---|---|
| Run pipeline (dry-run, no API key needed) | `just pipeline-run --dry-run` |
| Run pipeline (live Gemini) | `just pipeline-run` |
| Publish CSV alongside Parquet | `just pipeline-run --also-csv` |
| Inspect a specific dbt model | `just dbt build --select <name>` |
| Validate dbt project parses | `just dbt-parse` |
| Lint + format check | `just lint` |
| Auto-fix lint + format | `just fix` |
| Type check (`mypy --strict`) | `just typecheck` |
| Tests | `just test` |
| Full local CI | `just check` |

---

## Versioning

- v1 (now): everything documented above, runs locally end-to-end.
- v2 (not in development): Dagster orchestration, Google Places API enrichment,
  Slack/webhook notifications on threshold breaches, optional warehouse adapter
  (Snowflake / BigQuery), LangGraph for multi-step agent reasoning.

`pipeline_version` lives in `src/revel/__init__.py` and is embedded in every
published Parquet's metadata + the run report. Bump on any change to output
schema or transform semantics.

---

## Steering & design docs

- `.kiro/steering/project-overview.md` — what we're building, repo layout, versioning
- `.kiro/steering/architecture-decisions.md` — ADR-001 through ADR-004 (load-bearing decisions)
- `.kiro/steering/workflow-and-quality.md` — quality gates, task sizing
- `.kiro/steering/security-rules.md` — secrets, validation, fail-closed
- `.design.md` — design phase reasoning (one-shot)
- `.plan.md` — implementation plan, step by step, with the "lessons learned" notes
  that the next dev should read before touching any stage
