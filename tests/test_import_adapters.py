"""Tests for the external-source bookmark adapters."""

import json
from pathlib import Path

from foxport.import_ import detect_format, parse_file


def test_pinboard_json_round_trip(tmp_path):
    path = tmp_path / "pin.json"
    path.write_text(json.dumps([
        {"href": "https://example.com/a", "description": "Example A",
         "tags": "tag1 tag2", "time": "2024-01-01T00:00:00Z"},
        {"href": "https://example.com/b", "description": "Example B", "tags": "", "time": ""},
    ]), encoding="utf-8")
    fmt, entries = parse_file(path)
    assert fmt == "pinboard-json"
    assert len(entries) == 2
    assert entries[0].url == "https://example.com/a"
    assert entries[0].tags == ("tag1", "tag2")
    assert entries[0].added_unix_secs > 0
    assert entries[0].folder_path == ("Pinboard",)


def test_pocket_json_round_trip(tmp_path):
    path = tmp_path / "pocket.json"
    path.write_text(json.dumps([
        {"item_id": "1", "resolved_url": "https://x.com",
         "resolved_title": "X Title", "tags": {"news": {}, "tech": {}},
         "time_added": "1700000000", "given_url": "https://x.com"},
    ]), encoding="utf-8")
    fmt, entries = parse_file(path)
    assert fmt == "pocket-json"
    assert entries[0].url == "https://x.com"
    assert entries[0].title == "X Title"
    assert set(entries[0].tags) == {"news", "tech"}
    assert entries[0].added_unix_secs == 1700000000


def test_netscape_html_round_trip(tmp_path):
    path = tmp_path / "bookmarks.html"
    path.write_text(
        '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
        '<TITLE>Bookmarks</TITLE>\n'
        '<DL><p>\n'
        '  <DT><A HREF="https://github.com/" ADD_DATE="1700000000">GitHub</A>\n'
        '  <DT><A HREF="https://mozilla.org/">Mozilla</A>\n'
        '</DL><p>\n',
        encoding="utf-8",
    )
    fmt, entries = parse_file(path)
    assert fmt == "netscape-html"
    assert len(entries) == 2
    urls = {e.url for e in entries}
    assert urls == {"https://github.com/", "https://mozilla.org/"}


def test_opml_round_trip(tmp_path):
    path = tmp_path / "feeds.opml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        '<opml version="2.0"><body>\n'
        '  <outline type="rss" text="Mozilla Blog" '
        'xmlUrl="https://blog.mozilla.org/rss" '
        'htmlUrl="https://blog.mozilla.org/"/>\n'
        '</body></opml>',
        encoding="utf-8",
    )
    fmt, entries = parse_file(path)
    assert fmt == "opml"
    assert len(entries) == 1
    assert entries[0].url == "https://blog.mozilla.org/rss"
    assert entries[0].title == "Mozilla Blog"


def test_unknown_format(tmp_path):
    path = tmp_path / "rando.txt"
    path.write_text("not a bookmark export at all", encoding="utf-8")
    fmt, entries = parse_file(path)
    assert fmt == "unknown"
    assert entries == []
