"""Smoke tests for the Done-screen action wiring + Items badge parity.

These instantiate Qt widgets under the ``offscreen`` platform plugin so they
run in CI without a display. They cover the v1.3 parity changes:

* ``ItemsPage.set_counts()`` now takes a ``dict[str, int]`` and badges every
  registered category, not only the first five.
* ``RunPage.set_done()`` emits a button + signal for every artifact key the
  worker produced, including the newer ``hibp / autofill / cards /
  search_engines / open_tabs / downloads`` categories the previous version
  silently dropped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

# Offscreen platform plugin runs headless — CI Linux has no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_items_page(qt_app):
    from foxport.gui.pages import ItemsPage, MigrationContext
    ctx = MigrationContext()
    page = ItemsPage(ctx)
    return page, ctx


def test_items_page_set_counts_updates_every_registered_row(qt_app):
    page, _ = _make_items_page(qt_app)
    counts = {
        "passwords": 12,
        "bookmarks": 34,
        "extensions": 5,
        "cookies": 100,
        "history": 9_876,
        "autofill": 17,
        "cards": 2,
        "search_engines": 4,
        "open_tabs": 8,
        "downloads": 25,
    }
    page.set_counts(counts)

    for key, expected in counts.items():
        row = page._rows[key]
        badge_text = row[2].text()
        # Number is formatted with thousands separators; the suffix differs
        # for history/open_tabs but the count is the load-bearing part.
        assert f"{expected:,}" in badge_text, f"{key}: badge={badge_text!r}"
        # isVisible() depends on the parent chain being shown; on a never-
        # rendered widget tree we check the explicit hide flag instead.
        assert not row[2].isHidden()


def test_items_page_set_counts_ignores_unknown_keys(qt_app):
    page, _ = _make_items_page(qt_app)
    # Should not raise, should not modify any registered badge.
    page.set_counts({"nonexistent_category": 99})


def test_run_page_done_renders_action_per_artifact(qt_app):
    from foxport.gui.pages import MigrationContext, RunPage

    ctx = MigrationContext()
    page = RunPage(ctx)
    exports: dict[str, Path] = {
        "passwords": Path("p.csv"),
        "hibp": Path("h.txt"),
        "bookmarks": Path("b.html"),
        "extensions": Path("e.html"),
        "cookies": Path("c.sqlite"),
        "history": Path("places.sqlite"),
        "autofill": Path("a.sqlite"),
        "cards": Path("cards.csv"),
        "search_engines": Path("s.json"),
        "open_tabs": Path("r.jsonlz4"),
        "downloads": Path("d.csv"),
    }
    page.set_done(True, "/tmp/out", exports)

    # Open-output-folder + one button per export key + the trailing
    # "Save as snapshot..." button = 1 + len(exports) + 1.
    assert len(page._action_buttons) == 1 + len(exports) + 1
    assert not page._actions.isHidden()

    # Each button should be wired to artifactActionRequested via the
    # closure binding; verify by collecting the emitted (key, action) tuples.
    received: list[tuple[str, str]] = []
    page.artifactActionRequested.connect(lambda k, a: received.append((k, a)))
    for btn in page._action_buttons:
        btn.click()

    keys_emitted = [k for k, _ in received]
    assert keys_emitted[0] == RunPage.OUTPUT_FOLDER_KEY
    # Trailing snapshot button always wins last position when exports exist.
    assert keys_emitted[-1] == RunPage.CREATE_SNAPSHOT_KEY
    # Middle keys match ARTIFACT_ACTIONS order, filtered to what was in exports.
    expected_order = [k for k, _, _ in RunPage.ARTIFACT_ACTIONS if k in exports]
    assert keys_emitted[1:-1] == expected_order

    # Reveal vs open action kind must round-trip correctly.
    action_by_key = {k: a for k, a in received[1:-1]}
    for key, _, expected_action in RunPage.ARTIFACT_ACTIONS:
        if key in exports:
            assert action_by_key[key] == expected_action, key


def test_run_page_reset_disposes_action_buttons(qt_app):
    from foxport.gui.pages import MigrationContext, RunPage
    page = RunPage(MigrationContext())
    page.set_done(True, "/tmp/out", {"passwords": Path("p.csv")})
    assert page._action_buttons
    page.reset()
    assert page._action_buttons == []
    assert page._actions.isHidden()


def test_run_page_renders_reveal_backup_buttons(qt_app):
    """When set_direct_write_backups is called with paths for cookies +
    history before set_done, the Done action bar grows extra Reveal
    buttons that emit BACKUP_ACTION via artifactActionRequested."""

    from foxport.gui.pages import MigrationContext, RunPage
    page = RunPage(MigrationContext())
    backups = {
        "cookies": "/tmp/firefox/cookies.foxport-backup-1700000000.sqlite",
        "history": "/tmp/firefox/places.foxport-backup-1700000000.sqlite",
        # Empty string should be filtered out — direct-write ran but there
        # was no prior file to back up.
        "passwords": "",
    }
    page.set_direct_write_backups(backups)
    exports = {
        "cookies": Path("c.sqlite"),
        "history": Path("places.sqlite"),
        # passwords export still produced a CSV; its absence of a backup
        # path means no Reveal button should appear.
        "passwords": Path("p.csv"),
    }
    page.set_done(True, "/tmp/out", exports)

    received: list[tuple[str, str]] = []
    page.artifactActionRequested.connect(lambda k, a: received.append((k, a)))
    for btn in page._action_buttons:
        btn.click()

    keys_with_backup_action = [k for k, a in received if a == RunPage.BACKUP_ACTION]
    # Exactly two reveal-backup actions fired — cookies + history. Passwords
    # had a backup_path of "" so the button was suppressed.
    assert sorted(keys_with_backup_action) == ["cookies", "history"]


def test_run_page_done_failure_hides_actions(qt_app):
    from foxport.gui.pages import MigrationContext, RunPage
    page = RunPage(MigrationContext())
    page.set_done(False, "decryption failed", {})
    assert page._actions.isHidden()
    assert page._action_buttons == []
