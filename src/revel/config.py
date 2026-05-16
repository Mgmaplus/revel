"""Pipeline configuration.

Settings precedence (low → high): YAML file < environment variables < CLI flags.

YAML is loaded explicitly by `Settings.from_yaml()`; env vars are read by
`pydantic-settings` using the `REVEL_` prefix; CLI flags are merged in by the
caller (typically `cli.py`) via `model_copy(update=...)`.

Secret values use `pydantic.SecretStr` so they are redacted in `repr()` and
`model_dump()` by default.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DedupSettings(BaseModel):
    """Tunable thresholds for the dedup stage (Stage 3, implemented in Step 3)."""

    enable_tier_c: bool = False
    geo_match_meters: int = 150
    name_ratio_min: int = 92


class Settings(BaseSettings):
    """Top-level pipeline settings.

    Reads `.env` automatically; env vars use the `REVEL_` prefix
    (e.g. `REVEL_INPUT_PATH`). Nested fields use `__` as the delimiter
    (e.g. `REVEL_DEDUP__ENABLE_TIER_C=true`).
    """

    model_config = SettingsConfigDict(
        env_prefix="REVEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Paths -----------------------------------------------------------------
    input_path: Path = Path("input/restaurants.csv")
    output_dir: Path = Path("output")
    data_dir: Path = Path("data")
    duckdb_path: Path = Path("data/revel.duckdb")

    # --- Logging ---------------------------------------------------------------
    log_level: str = "INFO"

    # --- LLM (Stage 4) ---------------------------------------------------------
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_max_concurrency: int = 4
    llm_cache_dir: Path = Path(".cache/llm")
    gemini_api_key: SecretStr | None = Field(
        default=None,
        # Allow either GEMINI_API_KEY (standard) or REVEL_GEMINI_API_KEY (prefixed).
        validation_alias="GEMINI_API_KEY",
    )

    # --- Stage thresholds ------------------------------------------------------
    dedup: DedupSettings = Field(default_factory=DedupSettings)

    # --- Run modes -------------------------------------------------------------
    dry_run: bool = False
    also_csv: bool = True  # CSV alongside Parquet by default for reviewer access

    @classmethod
    def from_yaml(cls, path: Path | str) -> Settings:
        """Load settings from YAML, then overlay env vars + .env.

        Precedence (low → high): YAML defaults → env vars → CLI flags. The
        caller layers CLI flags on top via `model_copy(update=...)`.

        Implementation: pydantic-settings normally treats kwargs as the
        highest-priority source. To make YAML act as a *default* that env
        can override, we drop YAML keys that are also present in the
        environment before constructing the model.
        """
        yaml_path = Path(path)
        if not yaml_path.is_file():
            return cls()
        with yaml_path.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        env_prefix = (cls.model_config.get("env_prefix") or "").upper()
        non_prefixed_aliases = _collect_validation_aliases(cls)
        kept: dict[str, Any] = {}
        for key, value in raw.items():
            env_name = f"{env_prefix}{key}".upper()
            if env_name in os.environ:
                continue  # env overrides
            if key.upper() in non_prefixed_aliases and key.upper() in os.environ:
                continue
            kept[key] = value

        return cls(**kept)


def _collect_validation_aliases(cls: type[BaseSettings]) -> set[str]:
    """Return validation aliases that are *not* env-prefixed (e.g. GEMINI_API_KEY)."""
    aliases: set[str] = set()
    for field in cls.model_fields.values():
        alias = field.validation_alias
        if isinstance(alias, str):
            aliases.add(alias.upper())
    return aliases
