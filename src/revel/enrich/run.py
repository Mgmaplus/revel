"""Stage 4b orchestrator: read pre-agent Parquet, fill, write enriched."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from revel.config import Settings
from revel.enrich.cuisine import fill_cuisine
from revel.enrich.llm.client import make_client
from revel.enrich.romance import fill_romance
from revel.logging_setup import get_logger


@dataclass(slots=True)
class EnrichmentReport:
    cuisine_stats: dict[str, int] = field(default_factory=dict)
    romance_stats: dict[str, int] = field(default_factory=dict)
    cuisine_distribution: dict[str, int] = field(default_factory=dict)
    romance_score_histogram: dict[int, int] = field(default_factory=dict)
    rows_total: int = 0


def run_enrichment(
    settings: Settings,
    pre_agent_parquet: Path,
    enriched_parquet: Path,
) -> EnrichmentReport:
    """Read → fill cuisine → fill romance → write."""
    log = get_logger(__name__)

    df = pl.read_parquet(pre_agent_parquet)
    log.info("enrich.loaded", rows=df.height)

    api_key = (
        settings.gemini_api_key.get_secret_value() if settings.gemini_api_key is not None else None
    )
    client = make_client(
        provider=settings.llm_provider,
        model=settings.llm_model,
        cache_dir=settings.llm_cache_dir,
        api_key=api_key,
        dry_run=settings.dry_run,
    )

    df, cuisine_stats = fill_cuisine(df, client=client)
    df, romance_stats = fill_romance(df, client=client)

    # Distribution + histogram for the run report. Buckets: 0–9, 10–19, ...
    cuisine_dist = {
        row[0]: int(row[1]) for row in df.group_by("cuisine").len().rows() if row[0] is not None
    }
    null_cuisine = int(df.select(pl.col("cuisine").is_null().sum()).item())
    if null_cuisine:
        cuisine_dist["__null__"] = null_cuisine

    histogram_df = (
        df.filter(pl.col("romance_score").is_not_null())
        .with_columns(bucket=(pl.col("romance_score") // 10) * 10)
        .group_by("bucket")
        .len()
        .sort("bucket")
    )
    histogram = {int(b): int(n) for b, n in histogram_df.rows()}

    enriched_parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp = enriched_parquet.with_suffix(enriched_parquet.suffix + ".tmp")
    df.write_parquet(tmp, compression="zstd", compression_level=3)
    tmp.replace(enriched_parquet)
    log.info("enrich.wrote", path=str(enriched_parquet), rows=df.height)

    return EnrichmentReport(
        cuisine_stats=cuisine_stats,
        romance_stats=romance_stats,
        cuisine_distribution=cuisine_dist,
        romance_score_histogram=histogram,
        rows_total=df.height,
    )


def write_enrichment_report(report: EnrichmentReport, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "rows_total": report.rows_total,
        "cuisine": report.cuisine_stats,
        "romance": report.romance_stats,
        "cuisine_distribution": report.cuisine_distribution,
        "romance_score_histogram": report.romance_score_histogram,
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(out_path)
