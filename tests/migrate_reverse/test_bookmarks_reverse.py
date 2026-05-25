"""Reverse direction: Firefox → Chromium bookmark HTML export.

The forward direction is exercised heavily; the reverse path had no
dedicated test before v1.3. These tests cover:

* The Bookmarks Bar (Firefox ``toolbar`` root) is emitted **first** and
  tagged ``PERSONAL_TOOLBAR_FOLDER="true"`` so Chrome promotes it to the
  Bookmarks Bar on import.
* Sub-folder hierarchies are preserved through ``folder_path``.
* HTML escaping protects against XSS-in-bookmark-import; URL quote
  escaping protects HREF attributes.
* dry_run does not write the HTML file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from foxport.browsers.firefox_read import FirefoxBookmark
from foxport.migrate_reverse import bookmarks as reverse_bookmarks
from foxport.migrate_reverse.bookmarks import migrate_bookmarks_reverse


@pytest.fixture
def fake_firefox_profile(tmp_path: Path):
    """Build a minimal FirefoxProfile rooted at ``tmp_path/profile``.

    The reverse-bookmarks migrator calls ``read_firefox_bookmarks`` which
    opens places.sqlite. Tests stub that function out via monkeypatch so we
    don't need a real Firefox places DB.
    """
    from foxport.browsers.detect import FirefoxProfile

    profile_dir = tmp_path / "ff_profile"
    profile_dir.mkdir()
    (profile_dir / "compatibility.ini").write_text("[Compatibility]\n", encoding="utf-8")
    return FirefoxProfile(
        browser="Firefox",
        family="firefox",
        profile_name="default-release",
        profile_dir=profile_dir,
        is_default=True,
    )


def test_reverse_bookmarks_toolbar_first_and_tagged(tmp_path: Path, fake_firefox_profile, monkeypatch):
    sample = [
        FirefoxBookmark(folder_path=("menu", "Mozilla"), title="MDN",
                        url="https://developer.mozilla.org",
                        date_added_us=1_700_000_000_000_000, date_modified_us=0),
        FirefoxBookmark(folder_path=("toolbar",), title="GitHub",
                        url="https://github.com",
                        date_added_us=1_700_000_000_000_000, date_modified_us=0),
        FirefoxBookmark(folder_path=("toolbar", "Dev"), title="Stack",
                        url="https://stackoverflow.com",
                        date_added_us=0, date_modified_us=0),
    ]
    monkeypatch.setattr(reverse_bookmarks, "read_firefox_bookmarks", lambda _p: sample)

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_bookmarks_reverse(fake_firefox_profile, out_dir)

    html = result.html_path.read_text(encoding="utf-8")
    # The toolbar root must come BEFORE the menu root so Chrome's first-
    # PERSONAL_TOOLBAR_FOLDER-wins rule promotes our Bookmarks Bar entries.
    toolbar_pos = html.find('PERSONAL_TOOLBAR_FOLDER="true"')
    menu_pos = html.find("Other bookmarks")
    assert toolbar_pos > 0
    assert menu_pos > toolbar_pos
    # Bar label renders.
    assert "Bookmarks Bar" in html
    # All three URLs present.
    assert "https://github.com" in html
    assert "https://stackoverflow.com" in html
    assert "https://developer.mozilla.org" in html
    # Sub-folder "Dev" inside toolbar renders as an H3.
    assert ">Dev<" in html
    # Counts add up: toolbar + Dev + menu + Mozilla = 4 folders, 3 URLs.
    assert result.folders == 4
    assert result.urls == 3


def test_reverse_bookmarks_escapes_titles_and_urls(tmp_path: Path, fake_firefox_profile, monkeypatch):
    sample = [
        FirefoxBookmark(folder_path=("menu",), title='<img src=x onerror="alert(1)">',
                        url='https://example.com/?q=a&b="x"',
                        date_added_us=0, date_modified_us=0),
    ]
    monkeypatch.setattr(reverse_bookmarks, "read_firefox_bookmarks", lambda _p: sample)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_bookmarks_reverse(fake_firefox_profile, out_dir)
    html = result.html_path.read_text(encoding="utf-8")
    assert "<img" not in html         # title escaped
    assert "&lt;img" in html
    assert "&quot;" in html            # quote inside URL escaped


def test_reverse_bookmarks_dry_run_writes_nothing(tmp_path: Path, fake_firefox_profile, monkeypatch):
    monkeypatch.setattr(reverse_bookmarks, "read_firefox_bookmarks", lambda _p: [])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_bookmarks_reverse(fake_firefox_profile, out_dir, dry_run=True)
    assert not result.html_path.exists()
