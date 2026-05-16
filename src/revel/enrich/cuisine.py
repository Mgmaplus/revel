"""Cuisine fallback for rows the deterministic taxonomy missed.

Process: read `data/pre_agent/restaurants.parquet`, find rows where
`_needs_llm_cuisine == TRUE`, batch them, ask Gemini to classify each
into the closed `CuisineLiteral` taxonomy. Confidence < 0.6 yields NULL
+ a flag (per security rules, fail closed).

Concurrency: batches run in a ThreadPoolExecutor with `max_workers=N`
so we get N batches in flight at once. The Gemini SDK is sync so this
is the right shape (avoids restructuring as asyncio).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import polars as pl

from revel.enrich.llm._batch import run_batches_concurrent
from revel.enrich.llm.client import LLMClient
from revel.enrich.llm.schemas import (
    CUISINE_VALUES,
    CuisineLLMBatch,
    CuisineLLMResult,
)
from revel.logging_setup import get_logger

# Batch size — bigger means fewer round-trips (better throughput) but
# larger output tokens per call (closer to the model's output cap and
# more chance of partial truncation). 40 is a sweet spot for cuisine
# (the per-row output is small: a literal + optional secondary + float).
DEFAULT_BATCH_SIZE = 40
DEFAULT_MAX_CONCURRENCY = 4
MIN_CONFIDENCE = 0.6


def _build_prompt(rows: list[dict[str, object]]) -> str:
    """Render a deterministic prompt for a batch of rows.

    The prompt embeds the closed taxonomy and asks for one classification
    per row with a confidence score. We include `name`, `primary_type`,
    `website` host, `city_canonical`, and `display_address` so the LLM
    has multiple signals; `name_core` is omitted because it's lossy.
    """
    cuisine_list = ", ".join(CUISINE_VALUES)
    lines = [
        "TASK: CUISINE_BATCH_REQUEST",
        "Classify each restaurant into ONE of the cuisines below.",
        f"Allowed cuisines: {cuisine_list}",
        "Return JSON matching the response schema. For each row, set",
        "`cuisine_secondary` only if a clear sub-cuisine applies (e.g.,",
        "'Sushi' under Japanese). Set `confidence` to your honest 0–1 estimate.",
        "Use 'Other' ONLY when no listed cuisine applies.",
        "",
        "Rows:",
    ]
    for row in rows:
        cid = row["canonical_id"]
        name = row.get("name") or ""
        ptype = row.get("primary_type") or ""
        city = row.get("city_canonical") or ""
        addr = row.get("display_address") or ""
        website = row.get("website") or ""
        lines.append(
            f"- canonical_id={cid} | name={name!r} | primary_type={ptype!r} | "
            f"city={city!r} | address={addr!r} | website={website!r}"
        )
    return "\n".join(lines)


def _chunked(items: list[dict[str, object]], size: int) -> Iterable[list[dict[str, object]]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fill_cuisine(
    df: pl.DataFrame,
    *,
    client: LLMClient,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Return a copy of `df` with cuisine filled in for LLM-needed rows.

    Stats returned (used by the run report):
      - rows_total / rows_deterministic / rows_llm_resolved / rows_llm_failed
      - rows_llm_low_confidence
    """
    log = get_logger(__name__)

    df = df.with_columns(_quality_flags=pl.col("_quality_flags"))  # ensure col present

    needs_llm_mask = df["_needs_llm_cuisine"]
    # Sort by canonical_id to make batch composition stable across runs
    # — Polars `filter` doesn't guarantee row order, so without sort the
    # same input data can produce different prompts → cache misses.
    needs_llm = df.filter(needs_llm_mask).sort("canonical_id")
    deterministic_count = int((~needs_llm_mask).sum())

    if needs_llm.height == 0:
        log.info(
            "cuisine.no_llm_rows",
            rows_total=df.height,
            rows_deterministic=deterministic_count,
        )
        return df, {
            "rows_total": df.height,
            "rows_deterministic": deterministic_count,
            "rows_llm_resolved": 0,
            "rows_llm_low_confidence": 0,
            "rows_llm_failed": 0,
        }

    rows = needs_llm.select(
        ["canonical_id", "name", "primary_type", "city_canonical", "display_address", "website"]
    ).to_dicts()

    batches = list(_chunked(rows, batch_size))
    resolved: dict[int, CuisineLLMResult] = {}
    failed_ids: set[int] = set()

    def _call_one(batch: list[dict[str, object]]) -> CuisineLLMBatch:
        return client.complete_json(_build_prompt(batch), CuisineLLMBatch)

    total_batches = len(batches)
    log.info(
        "cuisine.start",
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
                "cuisine.batch_failed",
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
            "cuisine.batch_done",
            progress=f"{completed}/{total_batches}",
            succeeded=succeeded,
            rows_resolved_so_far=len(resolved),
        )

    # Count low-confidence so we can flag them; null them out.
    low_conf_ids = {cid for cid, r in resolved.items() if r.confidence < MIN_CONFIDENCE}

    # Build update frame keyed on canonical_id.
    update_rows: list[dict[str, object]] = []
    for cid, r in resolved.items():
        if r.confidence < MIN_CONFIDENCE:
            update_rows.append(
                {
                    "canonical_id": cid,
                    "_cuisine_new": None,
                    "_cuisine_secondary_new": None,
                    "_cuisine_flag": "low_llm_cuisine_confidence",
                }
            )
        else:
            update_rows.append(
                {
                    "canonical_id": cid,
                    "_cuisine_new": r.cuisine,
                    "_cuisine_secondary_new": r.cuisine_secondary,
                    "_cuisine_flag": None,
                }
            )
    for cid in failed_ids:
        update_rows.append(
            {
                "canonical_id": cid,
                "_cuisine_new": None,
                "_cuisine_secondary_new": None,
                "_cuisine_flag": "llm_cuisine_failed",
            }
        )

    if update_rows:
        updates = pl.DataFrame(
            update_rows,
            schema_overrides={
                "canonical_id": pl.Int64,
                "_cuisine_new": pl.String,
                "_cuisine_secondary_new": pl.String,
                "_cuisine_flag": pl.String,
            },
        )
        # `maintain_order='left'` is critical: without it, Polars reshuffles
        # rows after a join, which breaks Stage 4b's cache (see plan §Step 4
        # cache notes — fill_romance reads `df` after this join and the
        # new ordering changes the per-batch prompts → cache misses).
        df = df.join(updates, on="canonical_id", how="left", maintain_order="left")
        df = df.with_columns(
            cuisine=pl.when(pl.col("_needs_llm_cuisine"))
            .then(pl.col("_cuisine_new"))
            .otherwise(pl.col("cuisine")),
            cuisine_secondary=pl.when(pl.col("_needs_llm_cuisine"))
            .then(pl.col("_cuisine_secondary_new"))
            .otherwise(pl.col("cuisine_secondary")),
            _quality_flags=pl.when(pl.col("_cuisine_flag").is_not_null())
            .then(
                pl.col("_quality_flags").list.concat(
                    pl.col("_cuisine_flag").cast(pl.List(pl.String))
                )
            )
            .otherwise(pl.col("_quality_flags")),
        ).drop(["_cuisine_new", "_cuisine_secondary_new", "_cuisine_flag"])

    stats = {
        "rows_total": df.height,
        "rows_deterministic": deterministic_count,
        "rows_llm_resolved": len(resolved) - len(low_conf_ids),
        "rows_llm_low_confidence": len(low_conf_ids),
        "rows_llm_failed": len(failed_ids),
    }
    log.info("cuisine.complete", **stats)
    return df, stats
