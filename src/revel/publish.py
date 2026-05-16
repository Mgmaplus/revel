"""Stage 6 (Publish). Atomic write of the canonical Parquet artifact.

We embed pipeline metadata (version, git sha if available, run id, source
sha256) into the Parquet schema so consumers can verify provenance.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from revel import pipeline_version
from revel.logging_setup import get_logger


def _git_sha(repo_root: Path) -> str | None:
    """Return short git SHA, or None if not a git repo / git unavailable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def publish(
    enriched: pl.DataFrame,
    *,
    run_dir: Path,
    repo_root: Path,
    source_csv: Path,
    run_id: str,
    also_csv: bool = False,
) -> Path:
    """Atomic Parquet write. Returns the final published file path."""
    log = get_logger(__name__)
    run_dir.mkdir(parents=True, exist_ok=True)
    final = run_dir / "restaurants.parquet"
    tmp_dir = run_dir / "_tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp = tmp_dir / "restaurants.parquet"

    # Embed provenance in the Parquet file's key/value metadata.
    metadata = {
        "pipeline_version": pipeline_version,
        "run_id": run_id,
        "produced_at": datetime.now(UTC).isoformat(),
        "source_csv_sha256": _file_sha256(source_csv),
        "git_sha": _git_sha(repo_root) or "unknown",
    }

    enriched.write_parquet(
        tmp,
        compression="zstd",
        compression_level=3,
        row_group_size=50_000,
        metadata=metadata,
    )

    # Atomic rename.
    os.replace(tmp, final)
    # tmp_dir may have other files (none in v1, but be defensive).
    with contextlib.suppress(OSError):
        tmp_dir.rmdir()

    if also_csv:
        csv_path = run_dir / "restaurants.csv"
        enriched.write_csv(csv_path)

    # Update `output/latest` symlink to point at this run.
    latest = run_dir.parent / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(run_dir.name, target_is_directory=True)

    log.info(
        "publish.done",
        path=str(final),
        rows=enriched.height,
        bytes=final.stat().st_size,
        metadata=metadata,
    )

    # Drop a sidecar metadata.json so consumers without a Parquet reader
    # can still see provenance without parsing footer bytes.
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    return final
