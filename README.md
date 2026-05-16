# Revel — restaurant CSV → production-grade dataset pipeline

A repeatable, automated pipeline that turns a CSV of US restaurants into a
cleaner, deduplicated, enriched Parquet dataset. v1 runs entirely on a
single laptop; the only external dependency is the Gemini API (used only
in Stage 4).

For the full design, see:

- `.kiro/steering/project-overview.md` — pipeline shape, repo layout, versioning
- `.kiro/steering/architecture-decisions.md` — ADR-001/002/003/004
- `.design.md` — design phase reasoning
- `.plan.md` — implementation plan, step by step

## Quickstart

```bash
uv sync                              # install Python deps
cp .env.example .env                 # add GEMINI_API_KEY when you reach Step 4
just pipeline-run --dry-run          # runs the implemented stages end-to-end
```

Run a smaller demo on the test fixture:

```bash
just pipeline-run --input tests/fixtures/restaurants_sample.csv --dry-run
```

Inspect the embedded warehouse:

```bash
duckdb data/revel.duckdb -c "SELECT * FROM raw_restaurants LIMIT 5"
```

## Repo structure

See `.kiro/steering/project-overview.md` §4 — the directory layout is the
single source of truth and is kept current with the implementation.

## Status

Step 1 (Stage 1 — Ingest) is implemented. Stages 2–7 are stubs scheduled
for Steps 2–5 in `.plan.md`.

## Common tasks

| Goal | Command |
|---|---|
| Run pipeline | `just pipeline-run` |
| dbt build | `just dbt build` |
| dbt parse only | `just dbt-parse` |
| Lint + format check | `just lint` |
| Auto-fix lint + format | `just fix` |
| Type check | `just typecheck` |
| Tests | `just test` |
| Full local CI | `just check` |
