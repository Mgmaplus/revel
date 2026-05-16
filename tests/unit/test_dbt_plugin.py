"""Unit tests for the Python UDFs registered into DuckDB by `revel.dbt_plugin`.

These run directly against the Python functions; the integration test
in `tests/integration/test_pipeline_step2.py` exercises them through dbt.
"""

from __future__ import annotations

import pytest

from revel.dbt_plugin import clean_url, geohash, name_core


class TestCleanUrl:
    def test_none_in_none_out(self) -> None:
        assert clean_url(None) is None
        assert clean_url("") is None
        assert clean_url("   ") is None

    def test_strips_www_and_lowercases_host(self) -> None:
        assert clean_url("HTTPS://WWW.Example.COM/path") == "https://example.com/path"

    def test_drops_tracking_params(self) -> None:
        url = "https://x.com/y?utm_source=g&utm_campaign=foo&keep=this"
        assert clean_url(url) == "https://x.com/y?keep=this"

    def test_drops_fragment(self) -> None:
        assert clean_url("https://x.com/y#nav") == "https://x.com/y"

    def test_decodes_path(self) -> None:
        # Percent-encoded space → real space → re-encoded by urlencode.
        assert clean_url("https://x.com/foo%20bar/baz") == "https://x.com/foo bar/baz"

    def test_keeps_first_two_path_segments(self) -> None:
        assert clean_url("https://x.com/a/b/c/d/e") == "https://x.com/a/b"

    def test_no_trailing_slash(self) -> None:
        assert clean_url("https://x.com/a/") == "https://x.com/a"
        # Root-only URL also gets normalized (no trailing slash).
        assert clean_url("https://x.com/") == "https://x.com"

    def test_idempotent(self) -> None:
        url = "https://www.example.com/foo/bar?utm_source=x&y=z#frag"
        once = clean_url(url)
        twice = clean_url(once)
        assert once == twice

    def test_handles_no_scheme(self) -> None:
        # Some sources omit https://; we add it.
        assert clean_url("example.com/foo") == "http://example.com/foo"

    def test_unparseable_returns_none(self) -> None:
        # urlsplit is permissive; this case mostly catches "no host" errors.
        assert clean_url("http://") is None


class TestGeohash:
    def test_none_in_none_out(self) -> None:
        assert geohash(None, None) is None
        assert geohash(40.7, None) is None
        assert geohash(None, -73.9) is None

    def test_default_precision_is_7(self) -> None:
        h = geohash(40.7, -73.9)
        assert h is not None
        assert len(h) == 7

    def test_close_points_share_prefix(self) -> None:
        # 40.7128, -74.0060  (NYC)
        # 40.7129, -74.0061  (~10m north)
        a = geohash(40.7128, -74.0060)
        b = geohash(40.7129, -74.0061)
        assert a is not None and b is not None
        # Same 6-char cell at this proximity.
        assert a[:6] == b[:6]


class TestNameCore:
    def test_none_in_none_out(self) -> None:
        assert name_core(None) is None
        assert name_core("") is None
        assert name_core("   ") is None

    def test_drops_leading_article(self) -> None:
        assert name_core("The Modern") == "modern"
        assert name_core("the modern") == "modern"
        assert name_core("THE MODERN") == "modern"

    def test_strips_accents(self) -> None:
        assert name_core("Café Carmellini") == "cafe carmellini"
        assert name_core("dLeña") == "dlena"

    def test_collapses_punctuation(self) -> None:
        # "n/naka" should keep the n and naka with a single space.
        assert name_core("n/naka") == "n naka"
        assert name_core("Hav & Mar") == "hav mar"

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Traif", "traif"),
            ("RPM Italian", "RPM Italian Cafe"),  # different but core overlaps via blocking
            ("Carbone", "CARBONE"),
        ],
    )
    def test_case_invariance(self, a: str, b: str) -> None:
        # Same name with different casing → identical core.
        assert name_core(a) == name_core(a.lower())
        # b is a *different* string; we only assert that name_core is
        # deterministic per-input, not that a and b collapse together.
        assert name_core(b) == name_core(b.lower())
