"""Romance scoring fallback for rows the deterministic rubric missed.

Same shape as `cuisine.py`: read pre-agent frame, find rows where
`_needs_llm_romance == TRUE`, batch-call Gemini concurrently, validate, merge.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import polars as pl

from revel.enrich.llm._batch import run_batches_concurrent
from revel.enrich.llm.client import LLMClient
from revel.enrich.llm.schemas import RomanceLLMBatch, RomanceLLMResult
from revel.logging_setup import get_logger

# Romance output is heavier than cuisine (5 sub-scores + rationale per row),
# so we cap the batch a bit smaller to stay well under the model's output
# token cap. 25 was chosen so the typical batch produces ~3 KB of JSON.
DEFAULT_BATCH_SIZE = 25
DEFAULT_MAX_CONCURRENCY = 4

# Composite weights — match the deterministic rubric in
# `int_restaurants__enriched_det.sql`. Sub-scores ∈ [0, 10].
# Composite ∈ [0, 100].
DEFAULT_WEIGHTS: dict[str, float] = {
    "ambiance": 0.25,
    "intimacy": 0.20,
    "quietness": 0.15,
    "dining_experience": 0.20,
    "cuisine_fit": 0.20,
}


def composite_score(
    ambiance: int,
    intimacy: int,
    quietness: int,
    dining_experience: int,
    cuisine_fit: int,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> int:
    """Pure function: collapse 5 sub-scores into a single 0–100 integer."""
    raw = (
        weights["ambiance"] * ambiance
        + weights["intimacy"] * intimacy
        + weights["quietness"] * quietness
        + weights["dining_experience"] * dining_experience
        + weights["cuisine_fit"] * cuisine_fit
    )
    return round(10 * raw)


def _build_prompt(rows: list[dict[str, object]]) -> str:
    lines = [
        "TASK: ROMANCE_BATCH_REQUEST",
        "Score each restaurant for romantic-date suitability across 5 dimensions:",
        " - ambiance: lighting, decor, atmosphere",
        " - intimacy: table spacing, noise level, privacy",
        " - quietness: 10 = library, 0 = nightclub",
        " - dining_experience: pacing, service, course progression",
        " - cuisine_fit: how well the cuisine fits a romantic date",
        "All scores are integers 0–10. Provide a 1–2 sentence rationale.",
        "Return JSON matching the response schema.",
        "",
        "Rows:",
    ]
    for row in rows:
        cid = row["canonical_id"]
        name = row.get("name") or ""
        ptype = row.get("primary_type") or ""
        price = row.get("price_point") or "(unknown)"
        city = row.get("city_canonical") or ""
        addr = row.get("display_address") or ""
        lines.append(
            f"- canonical_id={cid} | name={name!r} | primary_type={ptype!r} | "
            f"price_point={price!r} | "
            f"city={city!r} | address={addr!r}"
        )
    return "\n".join(lines)


def _chunked(items: list[dict[str, object]], size: int) -> Iterable[list[dict[str, object]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fill_romance(
    df: pl.DataFrame,
    *,
    client: LLMClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> tuple[pl.DataFrame, dict[str, int]]:
    log = get_logger(__name__)

    needs_llm_mask = df["_needs_llm_romance"]
    needs_llm = df.filter(needs_llm_mask)
    deterministic_count = int((~needs_llm_mask).sum())

    if needs_llm.height == 0:
        # Add the rationale column so the schema stays consistent.
        if "romance_rationale" not in df.columns:
            df = df.with_columns(romance_rationale=pl.lit(None, dtype=pl.String))
        return df, {
            "rows_total": df.height,
            "rows_deterministic": deterministic_count,
            "rows_llm_resolved": 0,
            "rows_llm_failed": 0,
        }

    rows = needs_llm.select(
        [
            "canonical_id",
            "name",
            "primary_type",
            "price_point",
            "city_canonical",
            "display_address",
        ]
    ).to_dicts()

    resolved: dict[int, RomanceLLMResult] = {}
    failed_ids: set[int] = set()

    batches = list(_chunked(rows, batch_size))

    def _call_one(batch: list[dict[str, object]]) -> RomanceLLMBatch:
        return client.complete_json(_build_prompt(batch), RomanceLLMBatch)

    total_batches = len(batches)
    log.info(
        "romance.start",
        batches=total_batches,
        batch_size=batch_size,
        concurrency=max_concurrency,
        rows_to_resolve=len(rows),
    )

    completed = 0
    succeeded = 0
    for batch, result in run_batches_concurrent(batches, _call_one, max_workers=max_concurrency):
        completed += 1
        if isinstance(result, Exception):
            log.warning(
                "romance.batch_failed",
                progress=f"{completed}/{total_batches}",
                batch_size=len(batch),
                error_type=type(result).__name__,
                error=str(result)[:200],
            )
            for row in batch:
                failed_ids.add(cast(int, row["canonical_id"]))
            continue

        succeeded += 1
        returned_ids = {r.canonical_id for r in result.results}
        expected_ids = {cast(int, r["canonical_id"]) for r in batch}
        for r in result.results:
            resolved[r.canonical_id] = r
        for missing in expected_ids - returned_ids:
            failed_ids.add(missing)

        log.info(
            "romance.batch_done",
            progress=f"{completed}/{total_batches}",
            succeeded=succeeded,
            rows_resolved_so_far=len(resolved),
        )

    update_rows: list[dict[str, object]] = []
    for cid, r in resolved.items():
        update_rows.append(
            {
                "canonical_id": cid,
                "_amb_new": r.ambiance,
                "_int_new": r.intimacy,
                "_qui_new": r.quietness,
                "_din_new": r.dining_experience,
                "_cui_new": r.cuisine_fit,
                "_score_new": composite_score(
                    r.ambiance, r.intimacy, r.quietness, r.dining_experience, r.cuisine_fit, weights
                ),
                "_rationale_new": r.rationale,
                "_romance_flag": None,
            }
        )
    for cid in failed_ids:
        update_rows.append(
            {
                "canonical_id": cid,
                "_amb_new": None,
                "_int_new": None,
                "_qui_new": None,
                "_din_new": None,
                "_cui_new": None,
                "_score_new": None,
                "_rationale_new": None,
                "_romance_flag": "llm_romance_failed",
            }
        )

    if "romance_rationale" not in df.columns:
        df = df.with_columns(romance_rationale=pl.lit(None, dtype=pl.String))

    if update_rows:
        updates = pl.DataFrame(
            update_rows,
            schema_overrides={
                "canonical_id": pl.Int64,
                "_amb_new": pl.Int64,
                "_int_new": pl.Int64,
                "_qui_new": pl.Int64,
                "_din_new": pl.Int64,
                "_cui_new": pl.Int64,
                "_score_new": pl.Int64,
                "_rationale_new": pl.String,
                "_romance_flag": pl.String,
            },
        )
        df = df.join(updates, on="canonical_id", how="left")
        df = df.with_columns(
            ambiance=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_amb_new"))
            .otherwise(pl.col("ambiance")),
            intimacy=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_int_new"))
            .otherwise(pl.col("intimacy")),
            quietness=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_qui_new"))
            .otherwise(pl.col("quietness")),
            dining_experience=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_din_new"))
            .otherwise(pl.col("dining_experience")),
            cuisine_fit=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_cui_new"))
            .otherwise(pl.col("cuisine_fit")),
            romance_score=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_score_new"))
            .otherwise(pl.col("romance_score")),
            romance_rationale=pl.when(pl.col("_needs_llm_romance"))
            .then(pl.col("_rationale_new"))
            .otherwise(pl.col("romance_rationale")),
            _quality_flags=pl.when(pl.col("_romance_flag").is_not_null())
            .then(
                pl.col("_quality_flags").list.concat(
                    pl.col("_romance_flag").cast(pl.List(pl.String))
                )
            )
            .otherwise(pl.col("_quality_flags")),
        ).drop(
            [
                "_amb_new",
                "_int_new",
                "_qui_new",
                "_din_new",
                "_cui_new",
                "_score_new",
                "_rationale_new",
                "_romance_flag",
            ]
        )

    stats = {
        "rows_total": df.height,
        "rows_deterministic": deterministic_count,
        "rows_llm_resolved": len(resolved),
        "rows_llm_failed": len(failed_ids),
    }
    log.info("romance.complete", **stats)
    return df, stats
