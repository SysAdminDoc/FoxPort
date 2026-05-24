"""Tests for the cookies.sqlite emitter."""

import sqlite3

from foxport.migrate.cookies import _FIREFOX_COOKIES_SCHEMA


def test_schema_pragma_version():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_FIREFOX_COOKIES_SCHEMA)
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    assert ver == 17


def test_schema_includes_updateTime_column():
    """v17 added updateTime — Firefox 138 silently triggers re-create otherwise."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_FIREFOX_COOKIES_SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(moz_cookies)").fetchall()]
    assert "updateTime" in cols, cols


def test_schema_unique_constraint():
    """UNIQUE (name, host, path, originAttributes) must exist or imports dupe."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_FIREFOX_COOKIES_SCHEMA)
    # sqlite enforces the constraint via an auto-generated index; check the
    # behavior directly by inserting a duplicate row and expecting IntegrityError.
    conn.execute(
        "INSERT INTO moz_cookies (originAttributes, name, host, path) "
        "VALUES ('', 'sid', 'example.com', '/')"
    )
    try:
        conn.execute(
            "INSERT INTO moz_cookies (originAttributes, name, host, path) "
            "VALUES ('', 'sid', 'example.com', '/')"
        )
    except sqlite3.IntegrityError:
        return  # constraint fires
    raise AssertionError("Duplicate insert succeeded — UNIQUE constraint missing")
