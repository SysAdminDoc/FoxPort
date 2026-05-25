"""Search-engine OpenSearch + JSON inventory export tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from foxport.migrate.search_engines import (
    _build_opensearch,
    _slugify,
    migrate_search_engines,
)


def _seed_web_data(profile, rows: list[tuple]) -> None:
    """Build a Web Data DB with the ``keywords`` table the migrator reads.

    Each row: ``(short_name, keyword, url, suggest_url, last_visited,
    usage_count, is_active)``.
    """

    db = profile.profile_dir / "Web Data"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE keywords (
                id INTEGER PRIMARY KEY,
                short_name VARCHAR,
                keyword VARCHAR,
                url VARCHAR,
                suggest_url VARCHAR,
                last_visited INTEGER,
                usage_count INTEGER,
                is_active INTEGER
            );
        """)
        for short_name, keyword, url, suggest, last, count, active in rows:
            conn.execute(
                "INSERT INTO keywords (short_name, keyword, url, suggest_url, "
                "last_visited, usage_count, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (short_name, keyword, url, suggest, last, count, active),
            )
        conn.commit()
    finally:
        conn.close()


def test_slugify_handles_special_chars():
    # The slug becomes a filename; spaces and punctuation should collapse to
    # hyphens. Empty name falls back to "engine" so we never produce an
    # invalid file like ".xml".
    assert _slugify("My Search!") == "my-search"
    assert _slugify("DuckDuckGo / HTML") == "duckduckgo-html"
    assert _slugify("") == "engine"
    assert _slugify("   ") == "engine"


def test_build_opensearch_strips_chrome_tokens():
    """Chrome's templates embed brand tokens like {google:baseURL} which mean
    nothing in Firefox. The OpenSearch XML must not carry them through."""

    xml = _build_opensearch(
        "Google", "g",
        "{google:baseURL}search?q={searchTerms}&{google:RLZ}{google:originalQueryForSuggestion}",
        "{google:baseSuggestURL}complete/search?client=chrome&q={searchTerms}",
    )
    assert "{google:" not in xml
    # The standard OpenSearch token is preserved.
    assert "{searchTerms}" in xml
    # Required XML elements present.
    assert "<ShortName>Google</ShortName>" in xml
    assert "<Url" in xml


def test_migrate_search_engines_no_web_data(tmp_path: Path, fake_chromium_profile):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_search_engines(fake_chromium_profile, out_dir)
    assert result.total == 0
    assert result.written == 0
    assert not (out_dir / "search-engines.json").exists()


def test_migrate_search_engines_writes_xml_and_inventory(tmp_path: Path, fake_chromium_profile):
    _seed_web_data(fake_chromium_profile, [
        ("Google", "g", "https://www.google.com/search?q={searchTerms}",
         "https://www.google.com/complete?q={searchTerms}", 0, 100, 1),
        ("DuckDuckGo", "d", "https://duckduckgo.com/?q={searchTerms}", "", 0, 5, 1),
        # Empty short_name → skipped silently.
        ("", "x", "https://x.example/?q={searchTerms}", "", 0, 0, 1),
        # Empty URL → skipped silently.
        ("Empty URL", "e", "", "", 0, 0, 1),
    ])

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_search_engines(fake_chromium_profile, out_dir)

    # Only 2 of the 4 rows produce inventory entries (the empty-name and
    # empty-URL rows are dropped). The XML count should match.
    assert result.total == 2
    assert result.written == 2

    inv = json.loads((out_dir / "search-engines.json").read_text(encoding="utf-8"))
    assert [e["name"] for e in inv] == ["Google", "DuckDuckGo"]
    assert all("opensearch_file" in e for e in inv)

    # XML files match the slugs.
    xml_dir = out_dir / "search-engines"
    assert (xml_dir / "google.xml").is_file()
    assert (xml_dir / "duckduckgo.xml").is_file()


def test_migrate_search_engines_dry_run_writes_nothing(tmp_path: Path, fake_chromium_profile):
    _seed_web_data(fake_chromium_profile, [
        ("X", "x", "https://x.example/?q={searchTerms}", "", 0, 0, 1),
    ])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = migrate_search_engines(fake_chromium_profile, out_dir, dry_run=True)
    assert result.total == 1
    assert result.written == 0
    assert not (out_dir / "search-engines.json").exists()
    assert not (out_dir / "search-engines").exists()
