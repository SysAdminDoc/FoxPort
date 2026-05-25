"""Tests for the extension matcher's pure-function pieces."""

import json

from foxport import __version__
from foxport.browsers.chromium import ExtensionInfo
from foxport.migrate.extensions import (
    CURATED_MAP,
    _USER_AGENT,
    _normalize,
    _permission_overlap,
    _resolve_amo_name,
    load_curated_map,
    match_extensions,
)


def _extension(
    extension_id: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    name: str = "Example Extension",
    *,
    gecko_id: str | None = None,
) -> ExtensionInfo:
    return ExtensionInfo(
        extension_id=extension_id,
        name=name,
        version="1.0",
        description="",
        homepage=None,
        gecko_id=gecko_id,
        chrome_permissions=("storage",),
        chrome_host_permissions=(),
    )


def test_curated_map_loaded():
    assert len(CURATED_MAP) >= 50, "Curated map shrank unexpectedly"


def test_curated_map_age_days_reads_meta_field():
    """The age helper drives the v1.3.3 stale-map runtime warning."""

    from foxport.migrate.extensions import _curated_map_age_days

    age = _curated_map_age_days()
    # The bundled map's last_verified is "2026-05-25" by construction;
    # the test runs after that date, so age should always be >= 0.
    assert age is not None and age >= 0


def test_curated_map_warnings_silent_when_fresh(monkeypatch):
    """No warning surfaces when the bundled meta is younger than the
    threshold — keeps the run log clean for users on current releases.
    """
    from foxport.migrate import extensions as ext_mod

    monkeypatch.setattr(ext_mod, "_curated_map_age_days", lambda: 5)
    assert ext_mod._curated_map_warnings() == []


def test_curated_map_warnings_fires_when_stale(monkeypatch):
    """When the bundled map is older than the threshold, a single
    advisory warning is emitted. The text mentions the actual age so
    the user can decide whether to update."""
    from foxport.migrate import extensions as ext_mod

    monkeypatch.setattr(ext_mod, "_curated_map_age_days", lambda: 200)
    warnings = ext_mod._curated_map_warnings()
    assert len(warnings) == 1
    assert "200 days old" in warnings[0]
    assert "extensions.html" in warnings[0]


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


def test_match_extensions_reloads_env_curated_map_each_call(tmp_path, monkeypatch):
    """The active curated map is loaded per run, so overrides can hot-reload."""

    map_path = tmp_path / "curated.json"
    ext_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    monkeypatch.setenv("FOXPORT_CURATED_MAP_PATH", str(map_path))

    def write_map(slug: str) -> None:
        map_path.write_text(json.dumps({
            "_meta": {"last_verified": "2026-05-25"},
            "custom": {ext_id: slug},
        }), encoding="utf-8")

    write_map("first-slug")
    first = match_extensions([_extension(ext_id)], online=False)
    assert first[0].amo_slug == "first-slug"

    write_map("second-slug")
    second = match_extensions([_extension(ext_id)], online=False)
    assert second[0].amo_slug == "second-slug"


def test_curated_map_age_days_uses_env_override(tmp_path, monkeypatch):
    """Runtime warnings inspect the same active map used for matching."""

    from foxport.migrate.extensions import _curated_map_age_days

    map_path = tmp_path / "curated.json"
    map_path.write_text(json.dumps({
        "_meta": {"last_verified": "2026-05-25"},
        "custom": {},
    }), encoding="utf-8")
    monkeypatch.setenv("FOXPORT_CURATED_MAP_PATH", str(map_path))

    assert _curated_map_age_days() is not None


class _FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAmoSession:
    def __init__(self, detail_payload: dict | None = None, search_payload: dict | None = None):
        self.headers: dict[str, str] = {}
        self.detail_payload = detail_payload
        self.search_payload = search_payload
        self.calls: list[tuple[str, dict | None]] = []
        self.closed = False

    def get(self, url: str, params: dict | None = None, timeout: int = 8):
        self.calls.append((url, params))
        if "/addons/addon/" in url:
            assert self.detail_payload is not None
            return _FakeResponse(self.detail_payload)
        if "/addons/search/" in url:
            assert self.search_payload is not None
            return _FakeResponse(self.search_payload)
        raise AssertionError(f"unexpected AMO URL: {url}")

    def close(self) -> None:
        self.closed = True


def test_match_extensions_caches_duplicate_gecko_detail_lookups(monkeypatch):
    """Duplicate Gecko IDs within one run should only hit AMO once."""

    from foxport.migrate import extensions as ext_mod

    session = _FakeAmoSession(detail_payload={
        "slug": "shared-addon",
        "name": {"en-US": "Shared Add-on"},
        "guid": "shared@example.test",
        "average_daily_users": 10,
        "ratings": {"average": 4.5},
        "current_version": {"file": {"permissions": ["storage"], "host_permissions": []}},
        "status": "public",
        "is_disabled": False,
    })
    monkeypatch.setattr(ext_mod.requests, "Session", lambda: session)

    matches = match_extensions([
        _extension("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "One", gecko_id="shared@example.test"),
        _extension("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "Two", gecko_id="shared@example.test"),
    ], online=True, curated_map={})

    detail_calls = [call for call in session.calls if "/addons/addon/" in call[0]]
    assert len(detail_calls) == 1
    assert [m.amo_slug for m in matches] == ["shared-addon", "shared-addon"]
    assert session.closed


def test_match_extensions_caches_duplicate_name_searches(monkeypatch):
    """Duplicate extension names within one run should share the AMO search."""

    from foxport.migrate import extensions as ext_mod

    session = _FakeAmoSession(search_payload={
        "results": [{
            "slug": "same-name",
            "name": {"en-US": "Same Name"},
            "guid": "same@example.test",
            "average_daily_users": 20,
            "ratings": {"average": 4.2},
            "current_version": {"file": {"permissions": ["storage"], "host_permissions": []}},
            "status": "public",
            "is_disabled": False,
        }],
    })
    monkeypatch.setattr(ext_mod.requests, "Session", lambda: session)

    matches = match_extensions([
        _extension("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "Same Name"),
        _extension("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "Same Name"),
    ], online=True, curated_map={})

    search_calls = [call for call in session.calls if "/addons/search/" in call[0]]
    assert len(search_calls) == 1
    assert [m.amo_slug for m in matches] == ["same-name", "same-name"]
