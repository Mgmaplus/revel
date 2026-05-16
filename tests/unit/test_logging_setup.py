"""Logging: secrets must never appear in JSON output, run_id must propagate."""

from __future__ import annotations

import json

from revel.logging_setup import bind_run_id, configure_logging, get_logger


def test_secret_is_redacted_in_log(capsys) -> None:
    configure_logging("INFO")
    log = get_logger("test")
    # `gemini_api_key` is in the SECRET_KEYS allow-list and must be redacted.
    log.info("calling_llm", gemini_api_key="should-be-redacted", model="gemini-2.0-flash")
    captured = capsys.readouterr().err.strip().splitlines()
    assert captured, "expected a log line on stderr"
    payload = json.loads(captured[-1])
    assert payload["gemini_api_key"] == "***"
    assert "should-be-redacted" not in captured[-1]


def test_run_id_propagates(capsys) -> None:
    configure_logging("INFO")
    log = get_logger("test")
    with bind_run_id("test-run-123"):
        log.info("in_run")
    captured = capsys.readouterr().err.strip().splitlines()
    payload = json.loads(captured[-1])
    assert payload["run_id"] == "test-run-123"
    # After the context exits, run_id is gone.
    log.info("after_run")
    captured_after = capsys.readouterr().err.strip().splitlines()
    if captured_after:
        assert "run_id" not in json.loads(captured_after[-1])
