"""CLI ``import-bookmarks`` subcommand + the shared Netscape HTML emitter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foxport.cli import main
from foxport.import_.adapters import BookmarkImport, write_netscape_html


def _make_pinboard(path: Path, entries: list[dict]) -> Path:
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_write_netscape_html_groups_by_folder(tmp_path: Path):
    entries = [
        BookmarkImport(url="https://a.example", title="A", folder_path=("Pinboard",), added_unix_secs=1_700_000_000),
        BookmarkImport(url="https://b.example", title="B", folder_path=("Pinboard",), tags=("foo", "bar")),
        BookmarkImport(url="https://c.example", title="C", folder_path=("Pocket",)),
    ]
    out = tmp_path / "out.html"
    write_netscape_html(entries, out)

    html = out.read_text(encoding="utf-8")
    # File header is the Netscape doctype Firefox keys on.
    assert "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in html
    # Both source folders appear as H3 nodes so the user can spot them post-
    # import in their bookmarks Library.
    assert "<H3>Pinboard</H3>" in html
    assert "<H3>Pocket</H3>" in html
    # ADD_DATE only emitted when present; tags surface as the optional TAGS attr.
    assert 'ADD_DATE="1700000000"' in html
    assert 'TAGS="foo,bar"' in html
    # No leftover atomic-write tempfile.
    assert not list(tmp_path.glob(".out.html.foxport-*"))


def test_write_netscape_html_escapes_special_chars(tmp_path: Path):
    entries = [
        BookmarkImport(
            url='https://example.com/?q=a&b="x"',
            title="<script>alert(1)</script>",
            folder_path=("Imported",),
        ),
    ]
    out = tmp_path / "out.html"
    write_netscape_html(entries, out)
    html = out.read_text(encoding="utf-8")
    # Title must be escaped — the file is HTML the user opens, and an XSS
    # in their Bookmarks Library would be a textbook own-goal.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    # URL is quote-escaped inside HREF="...".
    assert "&quot;" in html


def test_cli_import_bookmarks_round_trip_pinboard(tmp_path: Path, capsys):
    pin = _make_pinboard(tmp_path / "pin.json", [
        {"href": "https://a.example", "description": "A entry", "tags": "foo bar",
         "time": "2024-01-01T00:00:00Z"},
        {"href": "https://b.example", "description": "B entry", "tags": "", "time": ""},
    ])

    rc = main(["import-bookmarks", "--input", str(pin)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Detected format: pinboard-json" in out
    assert "Parsed:  2 bookmark(s)" in out
    # Default --out is sibling with .firefox.html suffix.
    expected_out = pin.with_suffix(pin.suffix + ".firefox.html")
    assert expected_out.is_file()
    html = expected_out.read_text(encoding="utf-8")
    assert "https://a.example" in html
    assert "https://b.example" in html


def test_cli_import_bookmarks_explicit_format(tmp_path: Path, capsys):
    # Build a Pocket-shaped JSON but pass --format opml on purpose — that
    # should produce zero entries and exit non-zero. This tests the
    # format-override path against a file shape the detector would normally
    # classify correctly.
    pocket = tmp_path / "ril.json"
    pocket.write_text(json.dumps([
        {"resolved_url": "https://x.example", "resolved_title": "X", "time_added": "1700000000"},
    ]), encoding="utf-8")

    rc = main([
        "import-bookmarks",
        "--input", str(pocket),
        "--format", "opml",   # wrong on purpose
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "parsed 0 bookmarks" in err


def test_cli_import_bookmarks_missing_input(tmp_path: Path, capsys):
    rc = main(["import-bookmarks", "--input", str(tmp_path / "nope.html")])
    err = capsys.readouterr().err
    assert rc == 2
    assert "is not a file" in err
