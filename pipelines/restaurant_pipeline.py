"""Restaurant pipeline orchestrator.

v1 contract (per ADR-003): a Python function called from a typer CLI. Stage 1
is implemented; later stages are stubs that will be filled in Steps 2–5.

The orchestrator's only jobs are:
1.  Resolve config + run_id and bind logging context.
2.  Run dbt as a subprocess (per ADR-001) with the right --vars / --target.
3.  Read the resulting DuckDB tables/views with DuckDB or Polars and produce
    per-stage JSON stats / reports under `output/<run_id>/`.

It deliberately does *not* import dbt programmatically: dbt-core's Python API
is unstable and the subprocess form is the documented contract.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from revel.clean import compute_clean_stats, write_clean_stats
from revel.config import Settings
from revel.dedup_clusters import run_dedup, write_dedup_report
from revel.enrich.run import run_enrichment, write_enrichment_report
from revel.ingest import compute_ingest_stats, write_ingest_stats
from revel.logging_setup import bind_run_id, configure_logging, get_logger
from revel.notify import write_run_report
from revel.publish import publish
from revel.validate import validate_published_frame

# Repo-relative path to the dbt project. Resolved against the current working
# directory at runtime so the orchestrator can be invoked from anywhere via
# `uv run revel ...`.
DBT_PROJECT_DIR_NAME = "dbt"


def _dbt_project_dir(repo_root: Path) -> Path:
    return repo_root / DBT_PROJECT_DIR_NAME


def _make_run_id() -> str:
    """`YYYYMMDDTHHMMSSZ-<short-uuid>` — sortable + unique."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


def _run_dbt(
    args: Sequence[str], project_dir: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke `dbt` from the dbt project directory with the given args.

    Output is captured and surfaced via structlog. Non-zero exit raises.
    """
    log = get_logger(__name__)
    cmd = ["dbt", *args]
    log.info("dbt.invoke", cmd=" ".join(cmd), cwd=str(project_dir))

    result = subprocess.run(
        cmd,
        cwd=str(project_dir),
        env={**os.environ, **(env or {})},
        check=False,
        capture_output=True,
        text=True,
    )

    if result.stdout:
        log.debug("dbt.stdout", text=result.stdout)
    if result.stderr:
        log.debug("dbt.stderr", text=result.stderr)

    if result.returncode != 0:
        # Surface dbt's own message at error level so users see it without
        # turning on debug logs.
        log.error(
            "dbt.failed",
            returncode=result.returncode,
            stdout_tail=result.stdout[-2000:] if result.stdout else "",
            stderr_tail=result.stderr[-2000:] if result.stderr else "",
        )
        raise RuntimeError(f"dbt {' '.join(args)} exited {result.returncode}")

    return result


def run_pipeline(
    settings: Settings,
    repo_root: Path,
    *,
    run_id: str | None = None,
) -> Path:
    """Execute the v1 pipeline end-to-end.

    Returns the path to the run directory under `output/`.

    Step 1 implements only Stage 1 (Ingest). Stages 2–7 are stubs that log
    a "not yet implemented" warning and exit cleanly so downstream wiring
    (CLI, tests, CI) can be exercised.
    """
    configure_logging(settings.log_level)
    log = get_logger(__name__)

    rid = run_id or _make_run_id()
    run_dir = settings.output_dir / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    project_dir = _dbt_project_dir(repo_root)
    if not project_dir.is_dir():
        raise FileNotFoundError(f"dbt project directory not found at {project_dir}")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # Stage 4 writes Parquet under these subdirs; dbt-duckdb expects the
    # directories to exist before it materializes external marts.
    (settings.data_dir / "pre_agent").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "enriched").mkdir(parents=True, exist_ok=True)

    with bind_run_id(rid):
        log.info(
            "pipeline.start",
            input_path=str(settings.input_path),
            duckdb_path=str(settings.duckdb_path),
            run_dir=str(run_dir),
            dry_run=settings.dry_run,
        )

        dbt_env = {
            # Variables consumed by `dbt/profiles.yml` and `dbt_project.yml`.
            "REVEL_DUCKDB_PATH": str(settings.duckdb_path.resolve()),
            "REVEL_INPUT_PATH": str(settings.input_path.resolve()),
            # Stage 4a's external mart writes Parquet here; absolute path
            # so the model is independent of dbt's cwd.
            "REVEL_PRE_AGENT_PARQUET": str(
                (settings.data_dir / "pre_agent" / "restaurants.parquet").resolve()
            ),
            # Tell dbt to look for profiles.yml inside the project dir, not ~/.dbt.
            "DBT_PROFILES_DIR": str(project_dir.resolve()),
        }

        # ---- Stage 1: Ingest ------------------------------------------------
        # Selecting `source:raw` runs the source-level tests (not_null/unique
        # on the raw CSV) so a malformed input fails fast before any model is
        # built.
        t0 = time.monotonic()
        _run_dbt(
            ["build", "--select", "source:raw", "raw_restaurants"],
            project_dir=project_dir,
            env=dbt_env,
        )
        stats = compute_ingest_stats(settings.duckdb_path)
        write_ingest_stats(stats, run_dir / "01_ingest_stats.json")
        log.info(
            "pipeline.stage_complete",
            stage="ingest",
            row_count=stats.row_count,
            elapsed_s=round(time.monotonic() - t0, 3),
        )

        # ---- Stage 2: Clean -------------------------------------------------
        # Build seeds + the staging chain. Seeds are idempotent — dbt skips
        # them if the underlying CSV hasn't changed.
        t1 = time.monotonic()
        _run_dbt(
            [
                "build",
                "--select",
                "path:seeds",
                "stg_restaurants",
                "stg_restaurants__flagged",
            ],
            project_dir=project_dir,
            env=dbt_env,
        )
        clean_stats = compute_clean_stats(settings.duckdb_path)
        write_clean_stats(clean_stats, run_dir / "02_clean_stats.json")
        log.info(
            "pipeline.stage_complete",
            stage="clean",
            row_count=clean_stats.row_count,
            top_flags=dict(list(clean_stats.flag_counts.items())[:5]),
            elapsed_s=round(time.monotonic() - t1, 3),
        )

        # ---- Stage 3: Deduplicate ------------------------------------------
        # Three sub-steps:
        #   1. dbt builds `int_restaurants__dedup_candidates` (Tier B blocking).
        #   2. Python computes Tier A/B(/C) edges + connected components,
        #      writing `dedup_edges` and `dedup_cluster_map` tables to DuckDB.
        #   3. dbt builds `int_restaurants__deduped` from the cluster map.
        t2 = time.monotonic()
        _run_dbt(
            ["build", "--select", "int_restaurants__dedup_candidates"],
            project_dir=project_dir,
            env=dbt_env,
        )
        dedup_report = run_dedup(str(settings.duckdb_path), settings.dedup)
        write_dedup_report(dedup_report, run_dir / "03_dedup_report.json")
        _run_dbt(
            ["build", "--select", "int_restaurants__deduped"],
            project_dir=project_dir,
            env=dbt_env,
        )
        elapsed_dedup = round(time.monotonic() - t2, 3)
        log.info(
            "pipeline.stage_complete",
            stage="deduplicate",
            clusters=dedup_report.cluster_count,
            singletons=dedup_report.singleton_count,
            edges=dedup_report.edge_count_by_tier,
            largest_cluster=dedup_report.largest_cluster_size,
            elapsed_s=elapsed_dedup,
        )

        # ---- Stage 4a: Deterministic enrichment + pre-agent mart -----------
        t3 = time.monotonic()
        _run_dbt(
            [
                "build",
                "--select",
                "int_restaurants__enriched_det",
                "dim_restaurants__pre_agent",
            ],
            project_dir=project_dir,
            env=dbt_env,
        )
        elapsed_4a = round(time.monotonic() - t3, 3)
        log.info("pipeline.stage_complete", stage="enrich_deterministic", elapsed_s=elapsed_4a)

        # ---- Stage 4b: LLM enrichment (Gemini in live runs; Stub in --dry-run)
        t4 = time.monotonic()
        pre_agent_parquet = settings.data_dir / "pre_agent" / "restaurants.parquet"
        enriched_parquet = settings.data_dir / "enriched" / "restaurants.parquet"
        enrichment = run_enrichment(settings, pre_agent_parquet, enriched_parquet)
        write_enrichment_report(enrichment, run_dir / "04_enrichment_report.json")
        elapsed_4b = round(time.monotonic() - t4, 3)
        log.info(
            "pipeline.stage_complete",
            stage="enrich_llm",
            rows_total=enrichment.rows_total,
            cuisine=enrichment.cuisine_stats,
            romance=enrichment.romance_stats,
            elapsed_s=elapsed_4b,
        )

        # ---- Stage 5: Validate + Stage 6: Publish + Stage 7: Notify --------
        # All three are quick — keep them inline, no extra logging boundaries.
        import polars as pl  # local import; polars is heavy and only needed here

        t5 = time.monotonic()
        enriched_df = pl.read_parquet(enriched_parquet)
        validation = validate_published_frame(enriched_df)
        if not validation.ok:
            for err in validation.errors:
                log.error("validate.error", message=err)
            # Still write a report so the user sees the failure summary.
            write_run_report(
                run_dir=run_dir,
                output_dir=settings.output_dir,
                run_id=rid,
                source_csv=settings.input_path,
                final_parquet=Path("(not published)"),
                validation_errors=validation.errors,
                validation_warnings=validation.warnings,
                elapsed_per_stage={
                    "ingest": round(t1 - t0, 3),
                    "clean": round(t2 - t1, 3),
                    "deduplicate": elapsed_dedup,
                    "enrich_deterministic": elapsed_4a,
                    "enrich_llm": elapsed_4b,
                    "validate_publish": round(time.monotonic() - t5, 3),
                },
            )
            raise RuntimeError(
                f"Stage 5 validation failed with {len(validation.errors)} error(s); "
                f"see {settings.output_dir / 'run_report.md'}"
            )
        for w in validation.warnings:
            log.warning("validate.warning", message=w)

        final_parquet = publish(
            enriched_df,
            run_dir=run_dir,
            repo_root=repo_root,
            source_csv=settings.input_path,
            run_id=rid,
            also_csv=settings.also_csv,
        )
        elapsed_5 = round(time.monotonic() - t5, 3)
        log.info(
            "pipeline.stage_complete",
            stage="validate_publish",
            published=str(final_parquet),
            elapsed_s=elapsed_5,
        )

        write_run_report(
            run_dir=run_dir,
            output_dir=settings.output_dir,
            run_id=rid,
            source_csv=settings.input_path,
            final_parquet=final_parquet,
            validation_errors=validation.errors,
            validation_warnings=validation.warnings,
            elapsed_per_stage={
                "ingest": round(t1 - t0, 3),
                "clean": round(t2 - t1, 3),
                "deduplicate": elapsed_dedup,
                "enrich_deterministic": elapsed_4a,
                "enrich_llm": elapsed_4b,
                "validate_publish": elapsed_5,
            },
        )

        log.info("pipeline.done", run_dir=str(run_dir))

    return run_dir
