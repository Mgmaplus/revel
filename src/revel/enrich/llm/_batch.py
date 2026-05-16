"""Tiny shared helper for running LLM batches concurrently.

The Gemini SDK is synchronous. For the v1 workload (~50 batches per run)
threading is the right abstraction: I/O-bound work, GIL-friendly, no need
to restructure the SDK call site as async/await. `concurrent.futures`
gives us a simple semaphore-equivalent via `max_workers`.

Failures are returned as `(batch, exc)` tuples so callers can record
fail counts without losing the batch context.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed


def run_batches_concurrent[B, R](
    batches: Sequence[B],
    fn: Callable[[B], R],
    *,
    max_workers: int = 4,
) -> Iterable[tuple[B, R | Exception]]:
    """Run `fn(batch)` for each batch in `batches`, up to `max_workers` in flight.

    Yields (batch, result_or_exception) in completion order. Caller decides
    how to interpret exceptions (typically: mark all rows in the batch as
    failed and continue).
    """
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_batch = {pool.submit(fn, b): b for b in batches}
        for future in as_completed(future_to_batch):
            batch = future_to_batch[future]
            try:
                yield batch, future.result()
            except Exception as exc:
                # Bare Exception: the caller decides retry / fail policy.
                yield batch, exc
