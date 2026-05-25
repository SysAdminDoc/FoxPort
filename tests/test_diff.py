"""diff_profiles() — accounting tests for the CLI ``diff`` subcommand.

The diff comparison is straightforward (set difference per category) but
the wiring touches NSS (passwords), Chromium-side readers (bookmarks,
extensions), and Firefox-side readers (logins, bookmarks, installed
extensions). All of these are mocked here so the test can run without a
real browser profile on disk.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from foxport.browsers.chromium import BookmarkNode, ExtensionInfo, PasswordRow
from foxport.browsers.firefox_read import FirefoxBookmark, FirefoxLogin
from foxport.crypto.nss import NSSError
from foxport import diff as diff_mod


@pytest.fixture
def fake_target_profile(tmp_path: Path):
    from foxport.browsers.detect import FirefoxProfile
    d = tmp_path / "ff"
    d.mkdir()
    return FirefoxProfile(
        browser="Firefox", family="firefox", profile_name="default-release",
        profile_dir=d, is_default=True,
    )


def _patch(monkeypatch, **overrides):
    """Patch every reader in foxport.diff with the supplied callables."""
    for name, fn in overrides.items():
        monkeypatch.setattr(diff_mod, name, fn)


def test_diff_passwords_set_difference(fake_chromium_profile, fake_target_profile, monkeypatch):
    """Passwords keyed by (origin_url, username); duplicates land in `in_both`."""

    source_rows = [
        PasswordRow(origin_url="https://a.example", action_url="https://a.example",
                    username="me", password_blob=b"", date_created=0,
                    date_last_used=0, date_password_modified=0),
        PasswordRow(origin_url="https://b.example", action_url="https://b.example",
                    username="me", password_blob=b"", date_created=0,
                    date_last_used=0, date_password_modified=0),
    ]
    target_logins = [
        FirefoxLogin(
            hostname="https://a.example", form_submit_url="", http_realm=None,
            username="me", password="secret", guid="{x}",
            time_created_ms=0, time_last_used_ms=0,
            time_password_changed_ms=0, times_used=0,
        ),
    ]
    _patch(monkeypatch,
           read_password_rows=lambda _src: source_rows,
           read_firefox_logins=lambda _t, master_password="": target_logins,
           read_bookmarks=lambda _src: [],
           read_firefox_bookmarks=lambda _t: [],
           read_extensions=lambda _src: [],
           read_installed_firefox_extensions=lambda _t: set())

    d = diff_mod.diff_profiles(fake_chromium_profile, fake_target_profile)
    assert d.passwords_in_both == 1
    assert d.passwords_only_in_source == 1
    assert "https://b.example / me" in d.samples["passwords"]


def test_diff_nss_failure_treats_target_as_empty(fake_chromium_profile, fake_target_profile, monkeypatch):
    """When NSS can't open the target (locked / wrong master password) every
    source row should land in `only_in_source` rather than crashing the diff."""

    source_rows = [
        PasswordRow(origin_url="https://a.example", action_url="",
                    username="me", password_blob=b"", date_created=0,
                    date_last_used=0, date_password_modified=0),
    ]
    def boom(_t, master_password=""):
        raise NSSError("locked")
    _patch(monkeypatch,
           read_password_rows=lambda _src: source_rows,
           read_firefox_logins=boom,
           read_bookmarks=lambda _src: [],
           read_firefox_bookmarks=lambda _t: [],
           read_extensions=lambda _src: [],
           read_installed_firefox_extensions=lambda _t: set())

    d = diff_mod.diff_profiles(fake_chromium_profile, fake_target_profile)
    assert d.passwords_only_in_source == 1
    assert d.passwords_in_both == 0


def test_diff_bookmarks_set_difference(fake_chromium_profile, fake_target_profile, monkeypatch):
    source_tree = [
        BookmarkNode(kind="folder", name="Root", url=None,
                     date_added=0, date_modified=0, children=[
                         BookmarkNode(kind="url", name="A",
                                      url="https://a.example",
                                      date_added=0, date_modified=0, children=[]),
                         BookmarkNode(kind="url", name="B",
                                      url="https://b.example",
                                      date_added=0, date_modified=0, children=[]),
                     ]),
    ]
    target_bookmarks = [
        FirefoxBookmark(folder_path=("toolbar",), title="A",
                        url="https://a.example",
                        date_added_us=0, date_modified_us=0),
    ]
    _patch(monkeypatch,
           read_password_rows=lambda _src: [],
           read_firefox_logins=lambda _t, master_password="": [],
           read_bookmarks=lambda _src: source_tree,
           read_firefox_bookmarks=lambda _t: target_bookmarks,
           read_extensions=lambda _src: [],
           read_installed_firefox_extensions=lambda _t: set())

    d = diff_mod.diff_profiles(fake_chromium_profile, fake_target_profile)
    assert d.bookmark_urls_only_in_source == 1
    assert d.bookmark_urls_in_both == 1
    assert d.samples["bookmarks"] == ["https://b.example"]


def test_diff_extensions_uses_gecko_id_when_available(fake_chromium_profile, fake_target_profile, monkeypatch):
    """An extension whose manifest exposes browser_specific_settings.gecko.id
    counts as "already installed" when that GUID is in the target's
    installed_guids set."""

    source_exts = [
        ExtensionInfo(
            extension_id="cjpalhdlnbpafiamejdnhcphjbkeiagm",
            name="uBlock Origin", version="1.0",
            description="", homepage=None,
            gecko_id="uBlock0@raymondhill.net",
            chrome_permissions=(), chrome_host_permissions=(),
        ),
        ExtensionInfo(
            extension_id="unknownidwithoutgecko",
            name="Unmapped", version="1.0",
            description="", homepage=None,
            gecko_id=None,
            chrome_permissions=(), chrome_host_permissions=(),
        ),
    ]
    _patch(monkeypatch,
           read_password_rows=lambda _src: [],
           read_firefox_logins=lambda _t, master_password="": [],
           read_bookmarks=lambda _src: [],
           read_firefox_bookmarks=lambda _t: [],
           read_extensions=lambda _src: source_exts,
           read_installed_firefox_extensions=lambda _t: {"uBlock0@raymondhill.net"})

    d = diff_mod.diff_profiles(fake_chromium_profile, fake_target_profile)
    assert d.extensions_in_both == 1
    assert d.extensions_only_in_source == 1
    assert any("Unmapped" in s for s in d.samples["extensions"])
