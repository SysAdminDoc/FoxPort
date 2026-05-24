"""Tests for the Chromium → Firefox bookmarks Netscape-HTML migrator."""

import re

from foxport.migrate.bookmarks import migrate_bookmarks


def test_bookmarks_round_trip_basic(fake_chromium_profile, make_bookmarks_json, tmp_path):
    # Plant a Bookmarks file in the fake profile.
    bookmarks_path = make_bookmarks_json({
        "bookmark_bar": [("GitHub", "https://github.com/")],
        "other": [("Mozilla", "https://mozilla.org/")],
    })
    bookmarks_path.rename(fake_chromium_profile.bookmarks)

    out = tmp_path / "out"
    result = migrate_bookmarks(fake_chromium_profile, out)
    html = result.html_path.read_text(encoding="utf-8")

    assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in html
    assert "https://github.com/" in html
    assert "https://mozilla.org/" in html
    assert result.urls == 2


def test_bookmarks_filters_internal_urls(fake_chromium_profile, make_bookmarks_json, tmp_path):
    """chrome:// / about: / edge:// URLs are filtered by default."""
    bookmarks_path = make_bookmarks_json({
        "bookmark_bar": [
            ("Real", "https://example.com/"),
            ("Internal GPU", "chrome://gpu/"),
            ("About", "about:blank"),
            ("Edge", "edge://settings/"),
        ],
    })
    bookmarks_path.rename(fake_chromium_profile.bookmarks)

    out = tmp_path / "out"
    result = migrate_bookmarks(fake_chromium_profile, out)
    html = result.html_path.read_text(encoding="utf-8")

    assert "https://example.com/" in html
    assert "chrome://gpu/" not in html
    assert "about:blank" not in html
    assert "edge://settings/" not in html
    assert result.urls == 1
    assert result.filtered_internal == 3


def test_bookmarks_dry_run_does_not_write(fake_chromium_profile, make_bookmarks_json, tmp_path):
    bookmarks_path = make_bookmarks_json({"bookmark_bar": [("X", "https://x.com/")]})
    bookmarks_path.rename(fake_chromium_profile.bookmarks)

    out = tmp_path / "out"
    result = migrate_bookmarks(fake_chromium_profile, out, dry_run=True)
    assert result.urls == 1
    assert not result.html_path.exists()


def test_bookmarks_add_date_in_seconds(fake_chromium_profile, make_bookmarks_json, tmp_path):
    """Netscape HTML ADD_DATE is seconds since 1970, not microseconds."""
    bookmarks_path = make_bookmarks_json({"bookmark_bar": [("X", "https://x.com/")]})
    bookmarks_path.rename(fake_chromium_profile.bookmarks)

    out = tmp_path / "out"
    result = migrate_bookmarks(fake_chromium_profile, out)
    html = result.html_path.read_text(encoding="utf-8")
    # date_added in the fixture is the Chrome WebKit µs equivalent of Unix
    # epoch (1970-01-01), so ADD_DATE should be exactly 0.
    match = re.search(r'ADD_DATE="(\d+)"', html)
    assert match is not None
    assert int(match.group(1)) == 0
