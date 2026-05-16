"""Typer CLI entrypoint.

Usage examples (also run via `just pipeline-run ...`):

    uv run revel pipeline run --input input/restaurants.csv
    uv run revel pipeline run --dry-run
    uv run revel pipeline run --config configs/local.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from revel import pipeline_version
from revel.config import Settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Revel — restaurant CSV → production-grade dataset pipeline.",
)
pipeline_app = typer.Typer(no_args_is_help=True, help="Pipeline operations.")
app.add_typer(pipeline_app, name="pipeline")


def _repo_root() -> Path:
    """Repo root = current working directory.

    The CLI is intended to be invoked from the repo root (`just` does this).
    Anchoring on cwd keeps the tool relocatable.
    """
    return Path.cwd()


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(pipeline_version)


@pipeline_app.command("run")
def pipeline_run(
    input_path: Annotated[
        Path | None,
        typer.Option("--input", "-i", help="Source CSV path. Overrides config + env."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Run-artifact root dir. Overrides config + env."),
    ] = None,
    config: Annotated[Path, typer.Option("--config", "-c", help="YAML config file.")] = Path(
        "configs/local.yaml"
    ),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Skip LLM calls (Stage 4 only).")
    ] = False,
    csv: Annotated[
        bool | None,
        typer.Option(
            "--csv/--no-csv",
            help="Publish CSV alongside Parquet (default: True; pass --no-csv to disable).",
        ),
    ] = None,
) -> None:
    """Run the v1 pipeline end-to-end.

    Step 1 implements only Stage 1 (Ingest). Later stages are stubs.
    """
    # Local import to keep CLI startup snappy and avoid loading dbt subprocess
    # machinery when the user just runs `revel version`.
    from pipelines.restaurant_pipeline import run_pipeline

    settings = Settings.from_yaml(config)
    overrides: dict[str, object] = {"dry_run": dry_run}
    if csv is not None:
        overrides["also_csv"] = csv
    if input_path is not None:
        overrides["input_path"] = input_path
    if output_dir is not None:
        overrides["output_dir"] = output_dir
    settings = settings.model_copy(update=overrides)

    run_dir = run_pipeline(settings, repo_root=_repo_root())
    typer.echo(str(run_dir))


if __name__ == "__main__":
    app()
