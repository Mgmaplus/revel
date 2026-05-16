"""LLM client protocol + Gemini and Stub implementations.

The protocol is provider-agnostic: callers pass a Pydantic model class as
the response schema and receive a validated instance back. The Gemini
SDK enforces the schema server-side via `response_schema`; we additionally
re-validate with `model_validate_json` for defense-in-depth.

`StubLLMClient` returns deterministic canned outputs for tests + `--dry-run`.
It never opens a network connection.

Security: prompt content is *never* logged. Counts and token totals only.
This is a hard rule per `.kiro/steering/security-rules.md`.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from revel.logging_setup import get_logger

from .cache import LLMCache
from .schemas import (
    SCHEMA_VERSION,
    CuisineLLMBatch,
    CuisineLLMResult,
    RomanceLLMBatch,
    RomanceLLMResult,
)

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    """Provider-agnostic structured-output LLM client."""

    provider: str
    model: str

    def complete_json(
        self,
        prompt: str,
        response_schema: type[T],
        max_retries: int = 2,
    ) -> T:
        """Send `prompt`, get back a validated instance of `response_schema`.

        Raises `LLMError` if the model fails to produce valid JSON after
        `max_retries`. Cache hits short-circuit the network call.
        """
        ...


class LLMError(RuntimeError):
    """Raised when the LLM fails to produce valid output after retries."""


# --- Gemini implementation ---------------------------------------------------


class GeminiClient:
    """Gemini implementation of `LLMClient`. Caches via `LLMCache`."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.0-flash",
        cache: LLMCache,
    ) -> None:
        # Local import to keep test/dry-run paths free of the dependency.
        from google import genai

        self.provider = "gemini"
        self.model = model
        self._cache = cache
        self._client = genai.Client(api_key=api_key)

    def complete_json(
        self,
        prompt: str,
        response_schema: type[T],
        max_retries: int = 2,
    ) -> T:
        log = get_logger(__name__)
        cache_key = LLMCache.make_key(self.provider, self.model, prompt, SCHEMA_VERSION)

        cached = self._cache.get(cache_key)
        if cached is not None:
            log.info("llm.cache_hit", model=self.model)
            return response_schema.model_validate(cached)

        # Local import — avoids loading google.genai when only the stub is used.
        from google.genai import types as gen_types

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=gen_types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                    ),
                )
                # The SDK returns `response.text` as raw JSON when
                # response_schema is set. Validate explicitly anyway.
                if not response.text:
                    raise LLMError("empty response")
                parsed = response_schema.model_validate_json(response.text)
                self._cache.set(cache_key, parsed.model_dump(mode="json"))
                usage = getattr(response, "usage_metadata", None)
                log.info(
                    "llm.cache_miss",
                    model=self.model,
                    retries=attempt,
                    prompt_tokens=getattr(usage, "prompt_token_count", None),
                    completion_tokens=getattr(usage, "candidates_token_count", None),
                )
                return parsed
            except (ValidationError, LLMError) as exc:
                last_err = exc
                log.warning(
                    "llm.validation_failed", attempt=attempt, error_type=type(exc).__name__
                )
            except Exception as exc:
                # Bare Exception is intentional: the SDK can raise from
                # transport, auth, rate-limit, etc. We treat all of them
                # as retryable up to `max_retries`.
                last_err = exc
                log.warning("llm.error", attempt=attempt, error_type=type(exc).__name__)

        raise LLMError(f"LLM failed after {max_retries + 1} attempts: {last_err}")


# --- Stub implementation -----------------------------------------------------


class StubLLMClient:
    """Deterministic canned outputs for tests + `--dry-run`.

    Routing: we inspect the prompt for the marker tokens
    `CUISINE_BATCH_REQUEST` or `ROMANCE_BATCH_REQUEST` (set by the
    enrichment functions) and return shape-compatible fillers.

    For each canonical_id mentioned in the prompt, we emit:
      - cuisine: 'Other' with confidence 0.5
      - romance: middle-of-the-road sub-scores (5,5,5,5,5)
    """

    provider = "stub"
    model = "stub"

    def complete_json(
        self,
        prompt: str,
        response_schema: type[T],
        max_retries: int = 2,
    ) -> T:
        del max_retries  # required by Protocol; stub does no retries
        ids = _extract_ids_from_prompt(prompt)

        if response_schema is CuisineLLMBatch:
            payload = CuisineLLMBatch(
                results=[
                    CuisineLLMResult(
                        canonical_id=cid,
                        cuisine="Other",
                        cuisine_secondary=None,
                        confidence=0.5,
                    )
                    for cid in ids
                ]
            )
            return payload  # type: ignore[return-value]

        if response_schema is RomanceLLMBatch:
            payload = RomanceLLMBatch(  # type: ignore[assignment]
                results=[
                    RomanceLLMResult(
                        canonical_id=cid,
                        ambiance=5,
                        intimacy=5,
                        quietness=5,
                        dining_experience=5,
                        cuisine_fit=5,
                        rationale="stub: deterministic mid-range score",
                    )
                    for cid in ids
                ]
            )
            return payload  # type: ignore[return-value]

        raise LLMError(f"StubLLMClient cannot handle response_schema={response_schema!r}")


def _extract_ids_from_prompt(prompt: str) -> list[int]:
    """Pull `canonical_id` integers out of the structured prompt block.

    Both cuisine and romance prompts include lines like
    `- canonical_id=12345` for each row. We grep those out so the stub
    can produce a same-length response without needing JSON parsing.
    """
    ids: list[int] = []
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if line.startswith("- canonical_id="):
            try:
                ids.append(int(line.split("=", 1)[1].split()[0]))
            except (ValueError, IndexError):
                continue
    return ids


# --- factory ----------------------------------------------------------------


def make_client(
    *,
    provider: str,
    model: str,
    cache_dir: Any,
    api_key: str | None,
    dry_run: bool,
) -> LLMClient:
    """Build the right client given config + dry-run flag.

    Always returns the stub when `dry_run=True` so CI + local test runs
    never need credentials. Required env vars for the live path:
      - provider='gemini' → `GEMINI_API_KEY`
    """
    if dry_run:
        return StubLLMClient()
    if provider == "gemini":
        if not api_key:
            # Fall back to the env var directly; Settings should already
            # have read it but this keeps the function self-contained.
            api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise LLMError(
                "GEMINI_API_KEY is required for live Gemini calls. "
                "Use --dry-run to bypass LLM enrichment."
            )
        cache = LLMCache(cache_dir)
        return GeminiClient(api_key=api_key, model=model, cache=cache)
    raise LLMError(f"unknown provider: {provider!r}")


# Kept for callers that want the cache-key construction without a client.
def make_cache_key(provider: str, model: str, prompt: str) -> str:
    return LLMCache.make_key(provider, model, prompt, SCHEMA_VERSION)


# Re-export so callers don't have to dig.
__all__ = [
    "GeminiClient",
    "LLMClient",
    "LLMError",
    "StubLLMClient",
    "make_cache_key",
    "make_client",
]
