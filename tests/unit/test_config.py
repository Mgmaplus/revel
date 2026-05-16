"""Config loading: YAML → env override → CLI override (model_copy)."""

from __future__ import annotations

from pathlib import Path

from revel.config import Settings


def test_yaml_loads_and_env_overrides(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "local.yaml"
    cfg.write_text(
        "input_path: input/restaurants.csv\nlog_level: INFO\nllm_provider: gemini\n",
        encoding="utf-8",
    )
    # Env should override YAML.
    monkeypatch.setenv("REVEL_LOG_LEVEL", "DEBUG")
    s = Settings.from_yaml(cfg)
    assert s.input_path == Path("input/restaurants.csv")
    assert s.log_level == "DEBUG"


def test_missing_yaml_yields_defaults(tmp_path: Path, monkeypatch) -> None:
    # Make sure no env vars from the test environment bleed in.
    for var in ("REVEL_INPUT_PATH", "REVEL_LOG_LEVEL", "REVEL_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_yaml(tmp_path / "does-not-exist.yaml")
    assert s.input_path == Path("input/restaurants.csv")
    assert s.log_level == "INFO"
    assert s.llm_provider == "gemini"


def test_secret_is_redacted(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-do-not-leak")
    s = Settings()
    assert s.gemini_api_key is not None
    # Confirm SecretStr hides the value in str/repr.
    assert "test-secret" not in str(s.gemini_api_key)
    assert "test-secret" not in repr(s)


def test_cli_override_via_model_copy() -> None:
    s = Settings()
    overridden = s.model_copy(update={"dry_run": True, "input_path": Path("/tmp/x.csv")})
    assert overridden.dry_run is True
    assert overridden.input_path == Path("/tmp/x.csv")
    # Original is untouched (immutable copy semantics).
    assert s.dry_run is False
