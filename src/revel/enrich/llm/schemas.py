"""Pydantic schemas for structured LLM outputs.

Both Gemini's `response_schema` and our own validation use these models.
The `Literal[...]` annotations on enum-like fields are the authoritative
contract — anything not in the literal is a bug or a hallucination, and
we reject it with retry → null + flag (per security rules).

`SCHEMA_VERSION` is part of every cache key. Bump it when prompt or
schema semantics change so old cached responses are not returned.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Bump on any change to prompt text, model output shape, or this file.
SCHEMA_VERSION = "v1.1"

# Closed cuisine taxonomy. Must stay in sync with
# `dbt/seeds/cuisine_taxonomy.csv`'s `cuisine` column.
CuisineLiteral = Literal[
    "Italian",
    "French",
    "Japanese",
    "Chinese",
    "Korean",
    "Indian",
    "Thai",
    "Vietnamese",
    "Filipino",
    "Southeast Asian",
    "Asian Fusion",
    "Mexican",
    "Latin American",
    "Spanish",
    "Mediterranean",
    "Middle Eastern",
    "African",
    "American",
    "Steakhouse",
    "Seafood",
    "Pizza",
    "Vegetarian/Vegan",
    "European",
    "Dessert",
    "Other",
]

CUISINE_VALUES: tuple[str, ...] = tuple(CuisineLiteral.__args__)  # type: ignore[attr-defined]


class CuisineLLMResult(BaseModel):
    """One row of LLM cuisine output."""

    canonical_id: int
    cuisine: CuisineLiteral
    cuisine_secondary: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class CuisineLLMBatch(BaseModel):
    """Output schema for a batched cuisine call. One item per input row."""

    results: list[CuisineLLMResult]


class RomanceLLMResult(BaseModel):
    """One row of LLM romance scoring."""

    canonical_id: int
    ambiance: int = Field(ge=0, le=10)
    intimacy: int = Field(ge=0, le=10)
    quietness: int = Field(ge=0, le=10)
    dining_experience: int = Field(ge=0, le=10)
    cuisine_fit: int = Field(ge=0, le=10)
    rationale: str = Field(max_length=400)


class RomanceLLMBatch(BaseModel):
    """Output schema for a batched romance scoring call."""

    results: list[RomanceLLMResult]
