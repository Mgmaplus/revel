"""Stage 7 (Notify). v1: console + a single overwriting `output/run_report.md`.

Per Step 5 directive: keep it simple, single report file (not per-run-id),
console log only. Pluggable webhook hook is out of scope for v1.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from revel import pipeline_version
from revel.logging_setup import get_logger


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _format_dict(d: dict[str, Any], indent: int = 0) -> str:
    if not d:
        return "  (none)\n"
    pad = "  " * indent
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f"{pad}- **{k}**:")
            out.append(_format_dict(v, indent + 1))
        else:
            out.append(f"{pad}- **{k}**: {v}")
    return "\n".join(out) + "\n"


def write_run_report(
    *,
    run_dir: Path,
    output_dir: Path,
    run_id: str,
    source_csv: Path,
    final_parquet: Path,
    validation_errors: list[str],
    validation_warnings: list[str],
    elapsed_per_stage: dict[str, float],
) -> Path:
    """Render `output/run_report.md` (single file, overwritten each run)."""
    log = get_logger(__name__)

    ingest = _read_json(run_dir / "01_ingest_stats.json")
    clean = _read_json(run_dir / "02_clean_stats.json")
    dedup = _read_json(run_dir / "03_dedup_report.json")
    enrich = _read_json(run_dir / "04_enrichment_report.json")

    lines: list[str] = []
    lines.append("# Revel pipeline run\n")
    lines.append(f"- **run_id**: `{run_id}`")
    lines.append(f"- **pipeline_version**: `{pipeline_version}`")
    lines.append(f"- **produced_at (UTC)**: {datetime.now(UTC).isoformat()}")
    lines.append(f"- **source_csv**: `{source_csv}`")
    lines.append(f"- **published_parquet**: `{final_parquet}`")
    lines.append("")

    lines.append("## Status\n")
    if validation_errors:
        lines.append(f"❌ **FAILED** — {len(validation_errors)} validation error(s).")
    else:
        lines.append("✅ **OK**")
    lines.append("")

    if validation_errors:
        lines.append("### Validation errors\n")
        for e in validation_errors:
            lines.append(f"- {e}")
        lines.append("")
    if validation_warnings:
        lines.append("### Validation warnings\n")
        for w in validation_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Stage timings (seconds)\n")
    for stage, secs in elapsed_per_stage.items():
        lines.append(f"- {stage}: {secs:.2f}")
    lines.append("")

    lines.append("## Stage 1 — Ingest\n")
    lines.append(_format_dict(ingest))
    lines.append("## Stage 2 — Clean\n")
    lines.append(_format_dict(clean))
    lines.append("## Stage 3 — Deduplicate\n")
    lines.append(_format_dict(dedup))
    lines.append("## Stage 4 — Enrichment (cuisine + romance)\n")
    lines.append(_format_dict(enrich))
    lines.append("---")
    lines.append(
        "_Per-run JSON artifacts under `output/<run_id>/`. This report is "
        "overwritten each run; archive it manually if you need history._"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "run_report.md"
    tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(report_path)

    log.info("notify.report_written", path=str(report_path))
    return report_path


def to_serializable(value: Any) -> Any:
    """Best-effort conversion of dataclasses for the report."""
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value
