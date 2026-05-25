"""SNSS partial-success guard for ``_extract_urls``.

If Chrome ships a new SNSS command-id / payload-layout combo, the
structural Pickle parser silently returns a small subset of URLs while
the UTF-8 regex fallback would have caught the rest. v1.3 added a
ratio-based union step so partial drift can't silently lose tabs.

These tests exercise that branch by:

* Building a synthetic blob where the structural parser finds ONE URL,
  but the raw bytes also contain many additional URLs the regex
  fallback will pick up.
* Asserting the returned list is the *union* (not just the structural
  result), and that a warning was appended to the ``failures`` list.

We also pin the existing happy-path (structural parse alone) and the
fallback-only path (structural finds zero, regex returns its list).
"""

from __future__ import annotations

import struct

from foxport.migrate.open_tabs import _extract_urls


def _build_snss_with_one_nav(extra_payload: bytes = b"") -> bytes:
    """Construct an SNSS blob with exactly one navigation command whose
    Pickle resolves to https://structural.example, plus a tail of extra
    bytes the structural parser ignores but the regex would scan."""

    url = b"https://structural.example/path"
    url_len = len(url)
    padding = (-url_len) % 4
    pickle_payload = (
        struct.pack("<I", 1)                                # tab_id
        + struct.pack("<I", 12 + 4 + url_len + padding)     # pickle size
        + struct.pack("<I", 0)                              # nav index
        + struct.pack("<I", url_len)                        # url_len
        + url
        + b"\x00" * padding
    )
    cmd_id = 6
    cmd_size = 1 + len(pickle_payload)
    blob = (
        b"SNSS"
        + struct.pack("<I", 3)               # SNSS version
        + struct.pack("<H", cmd_size)
        + bytes([cmd_id])
        + pickle_payload
        + extra_payload
    )
    return blob


def test_extract_urls_structural_only_no_warning():
    """Happy path — structural parser returns enough URLs that the regex
    fallback's count doesn't materially exceed it. No warning emitted."""

    blob = _build_snss_with_one_nav()
    failures: list[str] = []
    urls = _extract_urls(blob, failures=failures)
    assert urls == ["https://structural.example/path"]
    assert failures == []


def test_extract_urls_union_when_regex_far_exceeds_structural():
    """Partial-success branch — structural finds 1, raw bytes contain many
    more URLs the regex picks up. Result is the union and a warning is
    appended to ``failures`` so the GUI/CLI can surface it."""

    extra_urls = b"\n".join([
        b"https://regex-one.example",
        b"https://regex-two.example",
        b"https://regex-three.example",
        b"https://regex-four.example",
        b"https://regex-five.example",
    ])
    blob = _build_snss_with_one_nav(extra_payload=extra_urls)

    failures: list[str] = []
    urls = _extract_urls(blob, failures=failures)

    # Structural URL is preserved alongside the regex hits.
    assert "https://structural.example/path" in urls
    # All five regex-only URLs were rescued.
    for u in [
        "https://regex-one.example",
        "https://regex-two.example",
        "https://regex-three.example",
        "https://regex-four.example",
        "https://regex-five.example",
    ]:
        assert u in urls

    # The drift warning was logged with enough context for the user.
    assert len(failures) == 1
    assert "schema drift" in failures[0].lower()
    assert "structural parser returned" in failures[0]


def test_extract_urls_no_structural_hits_uses_regex():
    """Pure-fallback branch — structural finds zero (e.g. completely new
    command ID layout), regex returns the only URLs we can find."""

    # No SNSS commands at all — just the magic + a free-floating URL.
    blob = b"SNSS" + struct.pack("<I", 3) + b"   https://only-regex.example   "
    failures: list[str] = []
    urls = _extract_urls(blob, failures=failures)
    assert urls == ["https://only-regex.example"]
    # No warning — we fell entirely back to regex, that's the documented
    # path, not a partial-success surprise.
    assert failures == []
