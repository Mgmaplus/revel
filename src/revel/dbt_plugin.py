"""dbt-duckdb plugin: registers Python UDFs into the DuckDB connection.

Loaded by `dbt/profiles.yml` via the `plugins` block. Plugins run at
connection creation time, so anything we register here is available to
every model that runs in this dbt invocation — and only this one (the
DuckDB file itself is not modified).

We use Python UDFs for transforms that are awkward or dangerous in pure
SQL — see `.plan.md` Step 2 risks. Keeping these in one place means there's
one obvious file to read when a transform's behavior is unclear.

Registered UDFs:
  - `clean_url(raw VARCHAR) -> VARCHAR`
        URL canonicalization: lowercase scheme+host, strip `www.`, drop
        fragments + tracking query params, URL-decode path, no trailing
        slash, keep first 2 path segments.
  - `geohash(lat DOUBLE, lon DOUBLE, precision INT) -> VARCHAR`
        Geohash encode. Returns NULL if either coordinate is NULL.
  - `name_core(raw VARCHAR) -> VARCHAR`
        Lowercase, accent-stripped, leading "the " removed, punctuation
        replaced with spaces, whitespace collapsed. Used as the dedup
        blocking key (Step 3).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, ClassVar
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import pygeohash
from dbt.adapters.duckdb.plugins import BasePlugin

# --- url canonicalization ----------------------------------------------------

# Tracking-style query params we strip from URLs before storage. Order is
# arbitrary; matching is case-insensitive and prefix-aware (`utm_*`).
_TRACKING_PARAM_PREFIXES: tuple[str, ...] = ("utm_",)
_TRACKING_PARAM_EXACT: frozenset[str] = frozenset(
    {
        "gclid",
        "fbclid",
        "scid",
        "y_source",
        "ecid",
        "icid",
        "cmp",
        "seo_id",
        "msclkid",
        "_ga",
        "ref",
    }
)


def clean_url(raw: str | None) -> str | None:
    """Canonicalize a URL for use as a stable identifier.

    Returns NULL on falsy input or unparseable URLs (defensive — bad URLs
    in the source CSV must not crash the build).
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None

    # If the URL has no scheme, prepend `http://` so urlsplit can parse it.
    if "://" not in raw:
        raw = "http://" + raw

    try:
        parts = urlsplit(raw)
    except ValueError:
        return None

    scheme = (parts.scheme or "http").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if not netloc:
        return None

    # Path: URL-decode, keep only first two non-empty segments. This collapses
    # deep landing-page URLs into a stable handle while preserving locality
    # signals like `/locations/austin`.
    decoded_path = unquote(parts.path or "")
    segments = [s for s in decoded_path.split("/") if s]
    kept_segments = segments[:2]
    path = "/" + "/".join(kept_segments) if kept_segments else ""

    # Query: drop tracking params, keep order-stable for the rest.
    if parts.query:
        kept_query: list[tuple[str, str]] = []
        for key, value in parse_qsl(parts.query, keep_blank_values=False):
            key_lc = key.lower()
            if key_lc in _TRACKING_PARAM_EXACT:
                continue
            if any(key_lc.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES):
                continue
            kept_query.append((key, value))
        query = urlencode(kept_query)
    else:
        query = ""

    # Drop fragment unconditionally (no canonical info there for our needs).
    canonical = urlunsplit((scheme, netloc, path, query, ""))

    # No trailing slash unless the URL is just scheme://netloc/.
    if canonical.endswith("/") and len(canonical) > len(f"{scheme}://{netloc}/"):
        canonical = canonical.rstrip("/")
    return canonical


# --- geohash -----------------------------------------------------------------


def geohash(lat: float | None, lon: float | None, precision: int = 7) -> str | None:
    """Geohash a coordinate pair. Defensive: NULL → NULL."""
    if lat is None or lon is None:
        return None
    return pygeohash.encode(latitude=float(lat), longitude=float(lon), precision=int(precision))


# --- name normalization ------------------------------------------------------

_LEADING_ARTICLE = re.compile(r"^(the|el|la|los|las)\s+", flags=re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_WHITESPACE = re.compile(r"\s+")


def name_core(raw: str | None) -> str | None:
    """Normalize a restaurant name into a dedup-friendly blocking key."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    # Decompose accents and drop combining marks.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _LEADING_ARTICLE.sub("", text)
    text = _NON_ALNUM.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()
    return text or None


# --- dbt-duckdb plugin entry-point ------------------------------------------


class Plugin(BasePlugin):
    """Registers the UDFs above into every DuckDB connection dbt opens.

    dbt-duckdb instantiates this once per connection. We register UDFs
    eagerly in `configure_connection`; they're scoped to the connection
    and don't pollute the .duckdb file.
    """

    UDF_NAMES: ClassVar[tuple[str, ...]] = ("clean_url", "geohash", "name_core")

    def configure_connection(self, conn: Any) -> None:  # type: ignore[override]
        # Late import so the dbt CLI can introspect the project without
        # needing duckdb importable.
        import duckdb

        conn.create_function(
            "clean_url",
            clean_url,
            [duckdb.typing.VARCHAR],
            duckdb.typing.VARCHAR,
            null_handling="special",  # let our function see NULLs and decide
        )
        conn.create_function(
            "geohash",
            geohash,
            [duckdb.typing.DOUBLE, duckdb.typing.DOUBLE, duckdb.typing.INTEGER],
            duckdb.typing.VARCHAR,
            null_handling="special",
        )
        conn.create_function(
            "name_core",
            name_core,
            [duckdb.typing.VARCHAR],
            duckdb.typing.VARCHAR,
            null_handling="special",
        )
