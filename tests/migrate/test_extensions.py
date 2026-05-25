"""Tests for the extension matcher's pure-function pieces."""

from foxport import __version__
from foxport.browsers.chromium import ExtensionInfo
from foxport.migrate.extensions import (
    CURATED_MAP,
    _USER_AGENT,
    _normalize,
    _permission_overlap,
    _resolve_amo_name,
    load_curated_map,
)


def test_curated_map_loaded():
    assert len(CURATED_MAP) >= 50, "Curated map shrank unexpectedly"


def test_user_agent_reflects_running_version():
    """The AMO User-Agent must include the live ``__version__`` — a hardcoded
    string here misrepresents FoxPort's identity across upgrades.

    Mirrors the same invariant ``crypto/hibp.py:_USER_AGENT`` carries.
    """
    assert __version__ in _USER_AGENT, (
        f"AMO User-Agent header {_USER_AGENT!r} is missing the running "
        f"version {__version__!r} — refresh the literal in extensions.py."
    )


def test_curated_map_keys_are_chromium_ids():
    """Chrome IDs are 32 lowercase letters; smoke-check shape."""
    for ext_id in list(CURATED_MAP.keys()):
        assert len(ext_id) == 32, ext_id
        assert ext_id.isalpha() and ext_id.islower(), ext_id


def test_normalize_strips_punctuation_and_case():
    assert _normalize("uBlock Origin!") == "ublockorigin"
    assert _normalize("Refined GitHub") == "refinedgithub"


def test_resolve_amo_name_accepts_string():
    assert _resolve_amo_name("Dark Reader") == "Dark Reader"


def test_resolve_amo_name_accepts_dict():
    assert _resolve_amo_name({"en-US": "Dark Reader", "de": "Dunkler Leser"}) == "Dark Reader"


def test_resolve_amo_name_falls_back_to_first_value_when_no_en_us():
    assert _resolve_amo_name({"de": "DLeser"}) == "DLeser"


def test_resolve_amo_name_handles_none():
    assert _resolve_amo_name(None) == ""


def test_permission_overlap_identical_sets():
    a = ("storage", "tabs", "https://*/*")
    assert _permission_overlap(a, a) == 1.0


def test_permission_overlap_disjoint_sets():
    assert _permission_overlap(("storage",), ("tabs",)) == 0.0


def test_permission_overlap_empty_sets():
    assert _permission_overlap((), ()) == 1.0


def test_permission_overlap_partial():
    a = ("storage", "tabs")
    b = ("storage", "history")
    # Jaccard: |{storage}| / |{storage, tabs, history}| = 1/3
    assert abs(_permission_overlap(a, b) - 1 / 3) < 1e-9


def test_load_curated_map_dedupes_collisions():
    """If two Chrome IDs map to the same slug, both keys survive."""
    flat = load_curated_map()
    slugs = list(flat.values())
    # uBlock Origin has multiple Chrome IDs all → ublock-origin slug.
    assert slugs.count("ublock-origin") >= 2
