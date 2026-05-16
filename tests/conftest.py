"""Shared pytest fixtures.

Conventions:
- `repo_root` always points at the actual repo root (the directory above
  `tests/`) so tests can resolve scripts and the fixture CSV without
  depending on the cwd they were invoked from.
- `tmp_pipeline_dirs` returns a tuple of (data_dir, output_dir) under tmp
  so each test gets isolated DuckDB + run dirs.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def fixture_csv(repo_root: Path) -> Path:
    path = repo_root / "tests" / "fixtures" / "restaurants_sample.csv"
    if not path.is_file():
        pytest.fail(
            f"Fixture missing at {path}. Run `bash scripts/build_fixture.sh` to regenerate."
        )
    return path


@pytest.fixture()
def tmp_pipeline_dirs(tmp_path: Path) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()
    return data_dir, output_dir
