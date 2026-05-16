---
inclusion: always
---

# Architecture Decisions (v1)

> Permanent record of load-bearing architectural choices for the restaurant pipeline. Full reasoning lives in `/.design.md`. Future Kiro sessions should treat these as **decided** unless a new ADR supersedes them.
>
> **v2 status: not currently in development.** The "v2" column in ADR-003 + the "v2 backlog" at the bottom of this file are forward-looking only. No v2 code lands until v1 is shipped and a stakeholder explicitly asks. Treat any v2 entry as "do not build now."

## ADR-001 — Staging with dbt-core + dbt-duckdb (Parquet-backed)

- **Status**: Accepted (v1)
- **Decision**: Deterministic stages (Ingest, Clean, Deduplicate, deterministic Fill) are dbt models against DuckDB, materializing Parquet for the pre-agent handoff.
- **Layer plan**:
  - `models/raw/raw_restaurants.sql` — typed pull from CSV source (view)
  - `models/staging/stg_restaurants*.sql` — column-level cleaning + `_quality_flags` (view)
  - `models/intermediate/int_restaurants__deduped.sql` — 3-tier dedup + merge (table)
  - `models/intermediate/int_restaurants__enriched_det.sql` — deterministic cuisine + city fill (table)
  - `models/marts/dim_restaurants__pre_agent.sql` — final pre-agent Parquet (external)
- **Seeds**: `cuisine_taxonomy.csv`, `city_canonical.csv`, `price_point_mapping.csv`, `place_id_prefixes.csv`, `cities_by_geohash5.csv` (precomputed offline reverse-geocode lookup).
- **Tests v1** (in `schema.yml`): `not_null`, `unique`, `accepted_values`, lat/lon range, post-dedup uniqueness on `canonical_id` and on `google_place_id` where not null.
- **Connected-components for dedup** is a small Python helper that runs between dbt's staging and intermediate steps. This is the only code-side piece in the otherwise-SQL pipeline; flagged for v2 reconsideration.
- **Migration paths**:
  - v2: wrap with `dagster-dbt` (each model becomes a Dagster asset).
  - v3: swap `profiles.yml` adapter to Snowflake/BigQuery.

## ADR-002 — Agent layer: structured-output LLM (Gemini), no agent framework in v1

- **Status**: Accepted (v1)
- **Decision**: Fill & Transform's LLM portion is a Python module of plain async functions calling LLMs via a `LLMClient` protocol with Pydantic-validated structured outputs. **No LangGraph, no LangChain agents** in v1.
- **Reasoning**: Workload is row-wise with one-shot, structured calls; no branching reasoning, no tool use, no multi-turn state. LangGraph's value comes from those features; adopting it now adds dependencies and test surface for no functional gain.
- **Provider**: **Google Gemini** via the `google-genai` SDK. Default model `gemini-2.0-flash` (cheap, fast, strong structured-output support via `response_schema` + Pydantic). Behind `LLMClient` protocol; `LLM_PROVIDER` env var swaps providers (OpenAI / Anthropic / local Ollama swappable without touching enrichment code). `temperature=0`, JSON-schema-enforced structured outputs.
- **Auth**: `GEMINI_API_KEY` from `.env`. Never logged. The only network dependency in v1.
- **Caching**: `diskcache`, key = `sha256(provider + model + messages + schema_version)`. Reruns are free and deterministic.
- **Concurrency**: `asyncio.Semaphore`, default 4.
- **Determinism boundary**: ~85% of cuisine classification and most romance scoring happen in deterministic code (rule-based + dbt joins). LLM is fallback-only, with closed-taxonomy validation on outputs.
- **Migration paths**:
  - v2: each enrichment function becomes a LangGraph node if multi-step reasoning emerges (e.g., infer cuisine by reading the restaurant's website).
  - v3: full LangGraph with tool use if dynamic agent behavior is needed.

## ADR-003 — Versioning roadmap

- **Status**: Accepted (v1)
- **Decision**: Pipeline is explicitly versioned. v1 is the smallest correct pipeline; future versions are additive.

| Concern | v1 (now) | v2 (next) | v3+ (if scale demands) |
|---|---|---|---|
| Trigger | Python CLI via `just` | Dagster scheduled/sensor job | API + event triggers |
| Orchestration | Python script + dbt subprocess | `dagster-dbt` software-defined assets | Multi-tenant Dagster |
| Staging tests | Basic schema tests | `dbt-expectations`, source freshness, snapshots | Data contracts, SLAs |
| Agent layer | Plain async + structured-output LLM | LangGraph nodes (if needed) | LangGraph + tools |
| Storage | Local Parquet, atomic rename | Dagster IO managers, partitioned by run_id | Warehouse + Parquet exports |
| Validation | Patito + dbt tests | + Great Expectations across stages | + automated data contracts |
| Notification | Console + `run_report.md` | Slack/webhook on threshold breaches | PagerDuty SLA breaches |
| Observability | structlog JSON | Dagster runtime metrics + OTEL traces | Full APM |

- **Mechanics**:
  - `pipeline_version` constant in `src/revel/__init__.py`. Embedded in Parquet metadata + `run_report.md`.
  - Output schema versions tracked in `docs/schema-versions.md`.
  - Each ADR moves to `docs/adr/000N-*.md` once implemented; superseded ADRs are kept and marked.

## ADR-004 — Local-only execution + DuckDB-as-storage in v1

- **Status**: Accepted (v1)
- **Decision**: The entire pipeline runs end-to-end on a single developer laptop, with no managed services. Storage between dbt models is the embedded DuckDB file `data/revel.duckdb`. External Parquet is used **only at three boundaries**: input handoff (CSV → DuckDB), pre-agent handoff (DuckDB → Polars), and final publish (Parquet to consumers).
- **Why this matters**: dbt-duckdb does **not require a database server**. DuckDB is an in-process embedded engine; a "warehouse" here is just a `.duckdb` file. There is no Postgres, no Snowflake, no cloud storage, no Docker, no Airflow in v1.
- **External network calls in v1**: exactly one — Gemini API (`generativelanguage.googleapis.com`). All other operations are local file I/O.
- **Materialization rules** (final for v1):
  - `raw_restaurants`, `stg_restaurants*` → **`view`** (no physical bytes; recomputed each run)
  - `int_restaurants__deduped`, `int_restaurants__enriched_det` → **`table`** (lives inside `data/revel.duckdb`; survives across runs for debugging)
  - `dim_restaurants__pre_agent` → **`external`** Parquet at `data/pre_agent/restaurants.parquet` (Python reads via `pl.read_parquet` without a DuckDB connection)
  - Final published artifact → Parquet at `output/<run_id>/restaurants.parquet`
- **No per-stage debug Parquet snapshots.** DuckDB is already queryable. To inspect any intermediate model: `duckdb data/revel.duckdb -c "SELECT * FROM main.stg_restaurants LIMIT 20"`. Per-stage **JSON stats** (counts, flag tallies) are still written to `output/<run_id>/0N_*.json` for the run report.
- **Required for "works locally" guarantee**:
  - `.env` with `GEMINI_API_KEY` set (or `--dry-run` to bypass LLM entirely)
  - `uv sync` installs all deps including `dbt-duckdb`
  - `just pipeline run` performs every stage without any service running
  - Tests + CI run with `--dry-run`; no API key required
- **Migration paths**:
  - v2: same DuckDB file behind Dagster IO managers; no transform changes needed.
  - v3: switch dbt adapter to a real warehouse (Snowflake/BigQuery); `external` Parquet boundary stays.

## Working rules derived from the ADRs

1. **Don't add LangGraph to v1.** If a task seems to need it, write it as a plain function first; revisit only if the function genuinely needs branching/tooling/state.
2. **Don't add a new SQL adapter, warehouse, or service to v1.** DuckDB-as-file is the v1 target; the only external dependency is Gemini.
3. **Every new transform belongs in dbt** unless it's pure Python interop (e.g., LLM calls, networkx). Default to SQL.
4. **No dbt model ships without at least one schema test.** `not_null` on key columns is the floor.
5. **No LLM call ships without a Pydantic schema** validating the output shape and a closed-set check on enum-like fields.
6. **Reruns must be deterministic** given the same input + cache. New LLM calls add to the cache key only via `schema_version` bumps when prompts change.
7. **Materialize Parquet only at the three documented boundaries** (input, pre-agent, publish). Everything else lives in `data/revel.duckdb` as views or tables.

## v2 backlog (not in development)

These items are deferred to v2 by ADR. Do **not** implement them in v1 even if a request seems to ask for them — flag and escalate per `escalation.md`. Each item has a documented v1 workaround.

- **Google Places API enrichment** for missing `display_address` / `latitude` / `longitude`. Would break the local-only guarantee (ADR-004) and add a second runtime network dependency. v1 workaround: deterministic city fill via the offline `cities_by_geohash5` seed (Step 4a); rows that still lack coords are flagged with `missing_coords` and pass through.
- **Dagster orchestration.** v1 trigger is a Python CLI (ADR-003 v1 column). v2 will wrap with `dagster-dbt`.
- **Threshold-based notifications** (Slack/PagerDuty on data-quality regressions). v1 emits a structured run report only.
- **Warehouse adapter swap** (Snowflake/BigQuery). v1 stays on dbt-duckdb.
- **LangGraph / multi-step agent reasoning.** v1 keeps LLM calls one-shot and structured (ADR-002).
- **Source freshness tests + snapshots** (`dbt-expectations`). v1 ships with basic schema tests only.
