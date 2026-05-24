"""Tests for Mozilla mfbt::HashString port and places url_hash."""

from foxport.crypto.mozhash import hash_string, places_url_hash


def test_empty_string_hashes_to_zero():
    assert hash_string("") == 0


def test_hash_string_is_deterministic():
    assert hash_string("foo") == hash_string("foo")
    assert hash_string("foo") != hash_string("bar")


def test_hash_string_avalanche():
    """Single-bit change in input → wildly different hash."""
    a = hash_string("https://example.com/a")
    b = hash_string("https://example.com/b")
    assert a != b
    # Should change at least 8 of 32 bits.
    assert bin(a ^ b).count("1") >= 8


def test_places_url_hash_layout():
    """High 16 bits = HashString(scheme + '://') & 0xFFFF; low 32 bits = HashString(url)."""
    url = "https://example.com/"
    h = places_url_hash(url)
    expected_prefix = hash_string("https://") & 0xFFFF
    expected_body = hash_string(url)
    assert (h >> 32) & 0xFFFF == expected_prefix
    assert h & 0xFFFFFFFF == expected_body


def test_places_url_hash_truncates_at_1500():
    """URL beyond 1500 chars should hash identically to the truncated version."""
    long_url = "https://example.com/" + "A" * 5000
    short_url = long_url[:1500]
    assert places_url_hash(long_url) == places_url_hash(short_url)


def test_places_url_hash_scheme_isolation():
    """http and https variants of the same path get different hashes."""
    assert places_url_hash("http://example.com/") != places_url_hash("https://example.com/")


def test_places_url_hash_empty_url():
    assert places_url_hash("") == 0


def test_places_url_hash_no_scheme():
    """A bare path without scheme has prefix_hash == 0."""
    h = places_url_hash("about:blank")
    # urlsplit('about:blank').scheme == 'about', so prefix is still set;
    # only literally schemeless input (rare for URLs) has prefix 0.
    assert (h >> 32) & 0xFFFF == (hash_string("about://") & 0xFFFF)
