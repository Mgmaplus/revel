---
inclusion: always
---

# Project Overview — Pipeline Automation Exercise

> **How to use this file:** This is the always-included steering doc Kiro reads on every interaction in this repo. Keep it concise, factual, and current. Replace every `TODO:` placeholder before starting real development. Anything left as `TODO:` signals to Kiro that the topic is unresolved.

## 1. Goal & Context

**One-line goal:**
You'll receive a CSV of ~1,000 US restaurants. Your job is to turn it into a cleaner, richer dataset suitable for production. 

**Why it exists:** 
A fully autonomous pipeline that can be reusable and adapt to common changes of csv source files.

**Scope (in):**
Your tasks

1) Deduplicate the dataset. Produce an output where duplicates are resolved and inconsistencies are normalized. You decide what "duplicate" means, how to merge complementary information across duplicate rows, and which records to keep, drop, or transform. Be explicit about judgment calls and confidence.

2) Populate data where it is missing. Fill in the blanks with the most likely value.

3) Add a cuisine column. Classify each row by cuisine where appropriate.

4) Score romantic date suitability. Add a column (or columns) capturing how suitable each venue is for a romantic date. The datatype, scoring scheme, and methodology are entirely up to you — boolean, ordinal score, continuous, multi-dimensional, with or without justification text. You also decide what signals to use and how to weight them. Document your reasoning.

Do not simply provide a one-off fixed CSV. 

**Scope (out / non-goals):**
The code should provide a repeatable data pipeline that can be applied to future similar datasets. No need for going beyond automating the customized transformation of any given csv following the schema in primary inputs section below.

## 2. Pipeline Shape

High-level data/control flow. Replace the placeholder with an ASCII diagram once known.

```
[Trigger] → [Ingest] → [Clean] → [Deduplicate] → [Fill & Transform] → [Validate] → [Publish] → [Notify]
```

**Trigger(s):** Manual CLI 

**Stages (v1 — see `architecture-decisions.md` for rationale):**
| # | Stage         | Purpose                                                              | Implementation                                | Inputs            | Outputs                |
|---|---------------|----------------------------------------------------------------------|-----------------------------------------------|-------------------|------------------------|
| 1 | Ingest        | Read CSV with strict typing, fail loudly on schema drift             | dbt source + `raw_restaurants` (view)         | csv               | DuckDB view            |
| 2 | Clean         | Per-column normalization + `_quality_flags`                          | dbt `staging/` models (view)                  | DuckDB view       | DuckDB view + tests    |
| 3 | Deduplicate   | 3-tier match (place_id → geo+name → website), merge with provenance  | dbt `int_restaurants__deduped` + Python CC    | DuckDB view       | DuckDB table + tests   |
| 4 | Fill & Tran   | Deterministic enrichment in dbt; LLM fallback in Python              | dbt `int_*__enriched_det` + Python `enrich/`  | DuckDB table      | Parquet (pre→post)     |
| 5 | Validate      | Patito schema + integrity checks on the post-agent frame             | Python `validate.py`                          | Parquet           | Validation report      |
| 6 | Publish       | Atomic Parquet write with embedded metadata                          | Python `publish.py`                           | Parquet           | `output/<run_id>/...`  |
| 7 | Notify        | Console + `run_report.md`; pluggable webhook (off by default)        | Python `notify.py`                            | run summary       | log line + report      |



## 3. Tech Stack (v1)

**Language / runtime**
- Python 3.12, environment managed by `uv` (lockfile committed)
- Task runner: `just`

**Data layer**
- `dbt-core` + `dbt-duckdb` for Ingest → Clean → Dedup → deterministic Fill (see ADR-001)
- DuckDB as an **embedded, in-process engine** — no database server, just the file `data/revel.duckdb`
- Polars for Python-side dataframe ops (post-agent enrichment, validation, publish)
- Parquet (zstd) used **only at three boundaries**: input handoff, pre-agent handoff, final publish (see ADR-004)

**Schema & validation**
- Pydantic v2 for config and LLM I/O contracts
- Patito (Polars-native Pydantic) for Python-side dataframe schema validation
- dbt schema tests (`not_null`, `unique`, `accepted_values`, range expressions) for SQL-side validation

**Agent / LLM**
- **Google Gemini** via `google-genai` SDK, model `gemini-2.5-flash-lite`, `temperature=0`, JSON-schema-enforced structured outputs (`response_schema` with Pydantic models)
- Provider-agnostic `LLMClient` protocol; swappable via `LLM_PROVIDER` env var
- `diskcache` for content-hashed response caching (reruns are free + deterministic)
- **No agent framework in v1** (no LangGraph, no LangChain agents) — see ADR-002

**Auxiliary**
- `rapidfuzz` (string similarity, dedup Tier B), `unidecode` (transliteration)
- `networkx` (connected-components for dedup clusters)
- `pygeohash` (geo blocking), `reverse_geocoder` (offline lat/lng → city seed)
- `structlog` (JSON logs with `run_id` correlation), `typer` (CLI), `python-dotenv` (.env loading), `pyyaml` (config)

**Quality**
- `ruff` (lint + format), `mypy --strict` (types), `pytest` + `hypothesis` (tests)
- Pre-commit hook: ruff, mypy, dbt parse

**External dependencies in v1**: exactly one network call — Gemini API. Everything else runs against local files. See ADR-004.

## 4. Repository Layout (v1)

```
.
├── pipelines/
│   └── restaurant_pipeline.py    # Python orchestrator: dbt run → enrich → validate → publish → notify
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml              # DuckDB target; path = data/revel.duckdb (from env)
│   ├── seeds/
│   │   ├── cuisine_taxonomy.csv
│   │   ├── city_canonical.csv
│   │   ├── price_point_mapping.csv
│   │   ├── place_id_prefixes.csv
│   │   └── cities_by_geohash5.csv
│   ├── macros/
│   │   └── canonicalize_url.sql
│   └── models/
│       ├── sources.yml
│       ├── raw/raw_restaurants.sql                      # view
│       ├── staging/
│       │   ├── stg_restaurants.sql                      # view
│       │   ├── stg_restaurants__flagged.sql             # view
│       │   └── schema.yml
│       ├── intermediate/
│       │   ├── int_restaurants__dedup_edges.sql         # view
│       │   ├── int_restaurants__deduped.sql             # table
│       │   ├── int_restaurants__enriched_det.sql        # table
│       │   └── schema.yml
│       └── marts/
│           ├── dim_restaurants__pre_agent.sql           # external Parquet
│           └── schema.yml
├── src/revel/
│   ├── __init__.py               # exports `pipeline_version`
│   ├── cli.py                    # typer entrypoint
│   ├── config.py                 # Pydantic Settings (YAML + env + flags)
│   ├── logging_setup.py          # structlog JSON, run_id propagation, secret redaction
│   ├── schemas.py                # Patito models for stage boundaries
│   ├── dedup_clusters.py         # Python connected-components helper invoked between dbt steps
│   ├── enrich/
│   │   ├── fills.py              # post-dedup deterministic fills not handled in dbt
│   │   ├── cuisine.py            # rule-based + LLM fallback
│   │   ├── romance.py            # rubric + LLM for ambiguous rows
│   │   └── llm/
│   │       ├── client.py         # LLMClient protocol + GeminiClient impl + StubClient
│   │       ├── cache.py          # diskcache wrapper
│   │       └── schemas.py        # Pydantic structured-output models
│   ├── validate.py               # Patito + cross-row checks
│   ├── publish.py                # atomic Parquet write, metadata embedding
│   └── notify.py                 # console + report; webhook hook (opt-in)
├── configs/
│   └── local.yaml                # default config; no secrets
├── tests/
│   ├── unit/                     # mirrors src/
│   ├── dbt/                      # dbt test fixtures + custom singular tests
│   ├── integration/test_pipeline.py
│   └── fixtures/
│       └── restaurants_sample.csv
├── docs/
│   ├── adr/                      # ADRs promoted from `architecture-decisions.md`
│   ├── dedup-judgment.md
│   ├── romance-scoring.md
│   ├── cuisine-taxonomy.md
│   └── schema-versions.md
├── input/
│   └── restaurants.csv           # source data (current run)
├── data/
│   ├── revel.duckdb              # embedded DB; all staging + intermediate models live here
│   └── pre_agent/restaurants.parquet   # external mart, read by Python enrichment
├── output/                       # run artifacts; `output/latest` symlink to most recent
├── .cache/                       # diskcache dir for LLM responses (gitignored)
├── .env.example
├── .gitignore
├── justfile
├── pyproject.toml                # uv-managed deps
└── README.md
```

## 5. Environments & Configuration

| Environment   | Purpose | Where it runs |
|---------------|---------|---------------|
| local         | dev + the only v1 environment | developer laptop |

**Local-only guarantee (v1)**: the pipeline runs end-to-end on a single laptop with no managed services. Required: `uv sync`, a `.env` with `GEMINI_API_KEY` (or `--dry-run` to bypass LLM), `just pipeline run`. No Postgres, no Snowflake, no Docker, no Airflow, no cloud storage.

**Config strategy:** 
- env vars
- YAML per env

**Secrets:** 
- use .env.example
- .env only never commited
- v1 secrets: `GEMINI_API_KEY` (only when not running in `--dry-run`)

## 6. Data Contracts

**Primary inputs:** 

restaurants.csv

id — internal identifier
name
city
display_address
google_place_id — Google's canonical place identifier
latitude, longitude
price_point — pricing tier
primary_type — Google Places category


**Primary outputs:** 
Working contract for v1 (finalized when publish step lands; mirrored in `docs/schema-versions.md`):
- `output/<run_id>/restaurants.parquet` (zstd, row-groups 50k) — canonical dataset
- `output/<run_id>/run_report.md` — human-readable run summary
- `output/<run_id>/0N_*.json` — per-stage stats (counts, flag tallies)
- `output/latest` symlink → most recent successful run

Intermediate state is **not** materialized as Parquet per stage. It lives inside `data/revel.duckdb` and can be inspected directly with `duckdb data/revel.duckdb -c "SELECT ..."` (see ADR-004).

**Schema evolution policy:**
- Output schema is versioned via `pipeline_version` (in `src/revel/__init__.py`) embedded in Parquet metadata.
- Backwards-compatible additions (new nullable columns, new enum values) → minor version bump; consumers keep working.
- Breaking changes (renames, removals, type changes, narrowed enums) → major bump + a migration note in `docs/schema-versions.md` + an entry in the run report.
- Input CSV schema drift fails the run at `raw_restaurants` (dbt source test) — explicit human action required to bump.

## 8. Quality Gates Specific to This Project

In addition to the always-on rules in `workflow-and-quality.md`:

Known issues to investigate:

This is real-world data. Things you should expect to find (and probably others we haven't listed):

• Duplicates rows. The same venue may appear more than once. Some are obvious; some require judgment.
• Missing values. Some rows have blanks where there should be data.
• Other issues you discover. The list above is not exhaustive.

Bullet proof against the above on Clean, Deduplicate and Fill & Transform steps.

Important: Always review your solutions and provide code that is only production grade ready.

## 9. Versioning

Pipeline is explicitly versioned. We are on **v1**. **v2 is not in development.** The roadmap below exists so v1 stays forward-compatible — do not implement v2 work until v1 ships and a stakeholder explicitly asks. Detailed roadmap and ADRs in `architecture-decisions.md`; v2 backlog at the bottom of that file.

| Concern | v1 (now) | v2 (next) | v3+ (if scale demands) |
|---|---|---|---|
| Trigger | Python CLI via `just` | Dagster scheduled/sensor job | API + event triggers |
| Orchestration | Python script + dbt subprocess | `dagster-dbt` software-defined assets | Multi-tenant Dagster |
| Storage | DuckDB file + 3 Parquet boundaries, all local | Same DuckDB behind Dagster IO managers, partitioned by run_id | Warehouse adapter (Snowflake/BigQuery) |
| Staging tests | Basic schema tests | `dbt-expectations`, source freshness, snapshots | Data contracts, SLAs |
| Agent layer | Plain async + Gemini structured outputs | LangGraph nodes (if multi-step reasoning needed) | LangGraph + tools |
| Validation | Patito + dbt tests | + Great Expectations across stages | + automated data contracts |
| Notification | Console + `run_report.md` | Slack/webhook on threshold breaches | PagerDuty SLA breaches |
| Observability | structlog JSON | Dagster runtime metrics + OTEL traces | Full APM |

`pipeline_version` lives in `src/revel/__init__.py`, is embedded in Parquet metadata and the run report, and gates schema-evolution decisions per §6.




