"""structlog setup with JSON output and run_id propagation.

Every log line carries `run_id` (set once per pipeline run via `bind_run_id`).
Secrets are never logged: pydantic `SecretStr` redacts in `repr()`, and the
`SECRET_KEYS` set below scrubs anything that slips through as a raw string.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

# Keys whose values must never appear in logs, even by accident.
SECRET_KEYS: frozenset[str] = frozenset(
    {"gemini_api_key", "api_key", "authorization", "password", "token"}
)


def _redact_secrets(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor that replaces sensitive values with `***`."""
    for key in list(event_dict.keys()):
        if key.lower() in SECRET_KEYS:
            event_dict[key] = "***"
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging for JSON output to stderr.

    Idempotent: calling twice is safe.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
        force=True,
    )

    # Quiet third-party noise so our structured progress logs are readable.
    # `httpx` emits one INFO line per HTTP request; in Stage 4 with concurrency
    # that drowns out our progress lines. Demote to WARNING.
    for noisy in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_secrets,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


@contextmanager
def bind_run_id(run_id: str) -> Iterator[None]:
    """Bind a `run_id` to all log lines emitted within the context."""
    bind_contextvars(run_id=run_id)
    try:
        yield
    finally:
        clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger. Use module `__name__` as `name` by convention."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
