"""History migration — Chromium ``History`` SQLite → Firefox ``places.sqlite``.

Source DB: ``%LOCALAPPDATA%\\<browser>\\User Data\\<profile>\\History``
Tables read: ``urls`` (one row per distinct URL) and ``visits`` (one row per
hit; FK to ``urls.id``).

Firefox's Places database is built from three intertwined tables:

* ``moz_origins`` — one row per ``(prefix, host)`` — must exist before
  ``moz_places`` so the trigger that resolves ``origin_id`` fires.
* ``moz_places`` — one row per URL. We set ``frecency = -1`` and
  ``recalc_frecency = 1`` so Firefox computes a real score on next idle.
* ``moz_historyvisits`` — one row per visit. Without these, the Places
  maintenance task expires the orphan ``moz_places`` rows.

We **write a fresh** ``places.sqlite`` from scratch (Firefox v77 schema) so
the user can swap it in cleanly while Firefox is closed. The bookmarks tree
is left empty here — bookmarks have their own dedicated migrator that targets
the HTML import flow.

URL hash (``url_hash``): Firefox uses a custom 64-bit function — the high
16 bits are ``HashString(scheme + "://") & 0xFFFF`` and the low 32 bits
are ``HashString(url)`` capped at 1500 chars. ``HashString`` itself is
the multiply-rotate-xor mix from ``mfbt/HashFunctions.h`` — see
:mod:`foxport.crypto.mozhash` for the byte-for-byte Python port.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from foxport.browsers.chromium import is_browser_internal_url
from foxport.browsers.detect import ChromiumProfile
from foxport.crypto.mozhash import places_url_hash

_CHROME_TO_UNIX_MICROS = 11_644_473_600_000_000


def _chrome_micros_to_unix_micros(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    return max(0, chrome_us - _CHROME_TO_UNIX_MICROS)


# Firefox places.sqlite v77 schema — minimum required tables, triggers, and
# indexes so a fresh DB is recognized by Firefox 115+. We deliberately omit
# moz_bookmarks (FoxPort still uses the HTML import path), moz_keywords, and
# moz_anno_attributes — Firefox creates them on first launch if absent.
_FIREFOX_PLACES_SCHEMA = """
PRAGMA page_size = 32768;
PRAGMA journal_mode = wal;

CREATE TABLE moz_origins (
    id INTEGER PRIMARY KEY,
    prefix TEXT NOT NULL,
    host TEXT NOT NULL,
    frecency INTEGER NOT NULL,
    recalc_frecency INTEGER NOT NULL DEFAULT 0,
    alt_frecency INTEGER,
    recalc_alt_frecency INTEGER NOT NULL DEFAULT 0,
    block_until_ms INTEGER NOT NULL DEFAULT 0,
    block_pages_until_ms INTEGER NOT NULL DEFAULT 0,
    UNIQUE (prefix, host)
);

CREATE TABLE moz_places (
    id INTEGER PRIMARY KEY,
    url LONGVARCHAR,
    title LONGVARCHAR,
    rev_host LONGVARCHAR,
    visit_count INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0 NOT NULL,
    typed INTEGER DEFAULT 0 NOT NULL,
    favicon_id INTEGER,
    frecency INTEGER DEFAULT -1 NOT NULL,
    last_visit_date INTEGER,
    guid TEXT,
    foreign_count INTEGER DEFAULT 0 NOT NULL,
    url_hash INTEGER DEFAULT 0 NOT NULL,
    description TEXT,
    preview_image_url TEXT,
    site_name TEXT,
    origin_id INTEGER REFERENCES moz_origins (id),
    recalc_frecency INTEGER NOT NULL DEFAULT 0,
    alt_frecency INTEGER,
    recalc_alt_frecency INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX moz_places_url_hashindex ON moz_places (url_hash);
CREATE INDEX moz_places_hostindex ON moz_places (rev_host);
CREATE INDEX moz_places_visitcount ON moz_places (visit_count);
CREATE INDEX moz_places_frecencyindex ON moz_places (frecency);
CREATE INDEX moz_places_lastvisitdateindex ON moz_places (last_visit_date);
CREATE UNIQUE INDEX moz_places_guid_uniqueindex ON moz_places (guid);
CREATE INDEX moz_places_originidindex ON moz_places (origin_id);

CREATE TABLE moz_historyvisits (
    id INTEGER PRIMARY KEY,
    from_visit INTEGER,
    place_id INTEGER,
    visit_date INTEGER,
    visit_type INTEGER,
    session INTEGER,
    source INTEGER DEFAULT 0 NOT NULL,
    triggeringPlaceId INTEGER
);
CREATE INDEX moz_historyvisits_placedateindex ON moz_historyvisits (place_id, visit_date);
CREATE INDEX moz_historyvisits_fromindex ON moz_historyvisits (from_visit);
CREATE INDEX moz_historyvisits_dateindex ON moz_historyvisits (visit_date);

CREATE TABLE moz_inputhistory (
    place_id INTEGER NOT NULL,
    input LONGVARCHAR NOT NULL,
    use_count INTEGER,
    PRIMARY KEY (place_id, input)
);

CREATE TABLE moz_bookmarks (
    id INTEGER PRIMARY KEY,
    type INTEGER,
    fk INTEGER DEFAULT NULL,
    parent INTEGER,
    position INTEGER,
    title LONGVARCHAR,
    keyword_id INTEGER,
    folder_type TEXT,
    dateAdded INTEGER,
    lastModified INTEGER,
    guid TEXT,
    syncStatus INTEGER NOT NULL DEFAULT 0,
    syncChangeCounter INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX moz_bookmarks_itemindex ON moz_bookmarks (fk, type);
CREATE INDEX moz_bookmarks_parentindex ON moz_bookmarks (parent, position);
CREATE INDEX moz_bookmarks_itemlastmodifiedindex ON moz_bookmarks (fk, lastModified);
CREATE UNIQUE INDEX moz_bookmarks_guid_uniqueindex ON moz_bookmarks (guid);

CREATE TABLE moz_bookmarks_deleted (
    guid TEXT PRIMARY KEY,
    dateRemoved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE moz_meta (
    key TEXT PRIMARY KEY,
    value NOT NULL
) WITHOUT ROWID;

PRAGMA user_version = 86;
"""

# Trigger that auto-resolves moz_places.origin_id whenever a place is
# inserted/updated. Mirrors Firefox's nsPlacesTriggers.h.
_FIREFOX_PLACES_TRIGGERS = """
CREATE TRIGGER moz_places_afterinsert_trigger
AFTER INSERT ON moz_places FOR EACH ROW
BEGIN
    INSERT OR IGNORE INTO moz_origins (prefix, host, frecency, recalc_frecency)
        VALUES (get_prefix(NEW.url), get_host_and_port(NEW.url), 0, 1);
    UPDATE moz_places SET origin_id = (
        SELECT id FROM moz_origins
         WHERE prefix = get_prefix(NEW.url) AND host = get_host_and_port(NEW.url)
    ) WHERE id = NEW.id;
END;
"""

# Visit types per nsINavHistoryService.idl:
_VISIT_TYPE_MAP = {
    # Chromium PageTransition LSB values -> Firefox visit_type
    0: 1,   # LINK
    1: 2,   # TYPED
    2: 3,   # AUTO_BOOKMARK (manual_subframe? -> bookmark)
    3: 4,   # AUTO_SUBFRAME -> EMBED
    4: 8,   # MANUAL_SUBFRAME -> FRAMED_LINK
    5: 1,   # GENERATED -> LINK
    6: 1,   # AUTO_TOPLEVEL -> LINK
    7: 1,   # FORM_SUBMIT -> LINK
    8: 9,   # RELOAD
    9: 1,   # KEYWORD -> LINK
    10: 1,  # KEYWORD_GENERATED -> LINK
}


@dataclass
class HistoryResult:
    """Outcome of a history migration run."""

    sqlite_path: Path
    urls: int
    visits: int
    failures: list[str] = field(default_factory=list)


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_history_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def _rev_host(host: str) -> str:
    """Firefox's reversed-host format: lowercase, reversed, trailing '.'.

    ``www.example.com`` -> ``moc.elpmaxe.www.``
    """
    if not host:
        return ""
    return host.lower()[::-1] + "."


def _get_prefix(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme:
        return ""
    return f"{parts.scheme}://"


def _get_host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _iter_chromium_history(profile: ChromiumProfile):
    """Yield (url_row, visit_rows) tuples from this profile's History DB."""
    src = profile.profile_dir / "History"
    if not src.is_file():
        return
    copy = _copy_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            url_cur = conn.execute(
                "SELECT id, url, title, visit_count, typed_count, last_visit_time, hidden "
                "FROM urls ORDER BY id"
            )
            urls = url_cur.fetchall()
            visit_cur = conn.execute(
                "SELECT id, url, visit_time, from_visit, transition FROM visits ORDER BY id"
            )
            visits_by_url: dict[int, list[tuple]] = {}
            for v in visit_cur:
                visits_by_url.setdefault(v[1], []).append(v)
            for u in urls:
                yield u, visits_by_url.get(u[0], [])
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)


def migrate_history(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
    include_internal: bool = False,
) -> HistoryResult:
    """Write a fresh ``places.sqlite`` to ``out_dir`` populated with the
    source profile's URLs and visits. Bookmarks are left empty (the
    bookmarks migrator uses the HTML import path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = out_dir / "places.sqlite"
    if sqlite_path.exists() and not dry_run:
        sqlite_path.unlink()

    failures: list[str] = []
    url_count = 0
    visit_count = 0

    if dry_run:
        for url_row, visit_rows in _iter_chromium_history(profile):
            _id, url, *_ = url_row
            if not url or (not include_internal and is_browser_internal_url(url)):
                continue
            url_count += 1
            visit_count += len(visit_rows)
        return HistoryResult(
            sqlite_path=sqlite_path,
            urls=url_count,
            visits=visit_count,
            failures=failures,
        )

    # Cannot use the trigger that calls Firefox-internal get_prefix() /
    # get_host_and_port() — those are C++ functions we don't have. Instead we
    # populate moz_origins manually and set origin_id directly.
    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.executescript(_FIREFOX_PLACES_SCHEMA)
        conn.commit()
        with conn:
            origin_cache: dict[tuple[str, str], int] = {}

            def origin_id_for(url: str) -> int | None:
                prefix = _get_prefix(url)
                host = _get_host(url)
                if not prefix or not host:
                    return None
                key = (prefix, host)
                if key in origin_cache:
                    return origin_cache[key]
                cur = conn.execute(
                    "INSERT OR IGNORE INTO moz_origins (prefix, host, frecency, recalc_frecency) "
                    "VALUES (?, ?, -1, 1)",
                    (prefix, host),
                )
                if cur.lastrowid:
                    origin_cache[key] = cur.lastrowid
                else:
                    row = conn.execute(
                        "SELECT id FROM moz_origins WHERE prefix = ? AND host = ?",
                        (prefix, host),
                    ).fetchone()
                    origin_cache[key] = row[0] if row else 0
                return origin_cache[key]

            for url_row, visit_rows in _iter_chromium_history(profile):
                (_chrome_url_id, url, title, visit_count_src, typed_count,
                 last_visit_time, hidden) = url_row
                if not url:
                    continue
                if not include_internal and is_browser_internal_url(url):
                    continue
                try:
                    origin_id = origin_id_for(url)
                    cur = conn.execute(
                        "INSERT INTO moz_places "
                        "(url, title, rev_host, visit_count, hidden, typed, frecency, "
                        " last_visit_date, guid, foreign_count, url_hash, origin_id, "
                        " recalc_frecency) "
                        "VALUES (?, ?, ?, ?, ?, ?, -1, ?, ?, 0, ?, ?, 1)",
                        (
                            url,
                            title or "",
                            _rev_host(_get_host(url)),
                            visit_count_src or 0,
                            1 if hidden else 0,
                            1 if (typed_count or 0) > 0 else 0,
                            _chrome_micros_to_unix_micros(last_visit_time or 0) or None,
                            "{" + str(uuid.uuid4()) + "}"[1:-1][:12],
                            places_url_hash(url),
                            origin_id,
                        ),
                    )
                    place_id = cur.lastrowid
                    url_count += 1
                    for v in visit_rows:
                        (_chrome_visit_id, _chrome_url_fk, visit_time, _from_visit,
                         transition) = v
                        chromium_core = int(transition or 0) & 0xFF
                        firefox_type = _VISIT_TYPE_MAP.get(chromium_core, 1)
                        conn.execute(
                            "INSERT INTO moz_historyvisits "
                            "(from_visit, place_id, visit_date, visit_type, session, source) "
                            "VALUES (0, ?, ?, ?, 0, 0)",
                            (
                                place_id,
                                _chrome_micros_to_unix_micros(visit_time or 0),
                                firefox_type,
                            ),
                        )
                        visit_count += 1
                except sqlite3.IntegrityError as exc:
                    failures.append(f"{url}: {exc}")
    finally:
        conn.close()

    return HistoryResult(
        sqlite_path=sqlite_path,
        urls=url_count,
        visits=visit_count,
        failures=failures,
    )
