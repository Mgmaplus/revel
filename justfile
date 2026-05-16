# Revel pipeline task runner.
# `just` shows this list. Run `just <recipe>` to execute one.

set dotenv-load := true

# Default target lists recipes.
default:
    @just --list

# Install / sync the Python environment via uv (lockfile committed).
sync:
    uv sync

# Run the full pipeline. Step 1 only wires up Stage 1 (Ingest).
# Pass --dry-run to skip LLM calls (Stage 4 only; harmless in Step 1).
pipeline-run *ARGS:
    uv run revel pipeline run {{ARGS}}

# Run a single dbt build/test command, scoped to a selector.
dbt *ARGS:
    cd dbt && DBT_PROFILES_DIR=. uv run dbt {{ARGS}}

# Convenience: just dbt-parse to validate the dbt project compiles.
dbt-parse:
    cd dbt && DBT_PROFILES_DIR=. uv run dbt parse

# Lint + format check.
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint + format.
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Strict type check (mypy).
typecheck:
    uv run mypy

# Unit + integration tests.
test *ARGS:
    uv run pytest {{ARGS}}

# Full local check (matches CI).
check: lint typecheck dbt-parse test
