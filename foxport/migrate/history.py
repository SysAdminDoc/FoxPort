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

import json
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
from foxport.fileops import replace_file_atomic

_CHROME_TO_UNIX_MICROS = 11_644_473_600_000_000


def _chrome_micros_to_unix_micros(chrome_us: int) -> int:
    if chrome_us <= 0:
        return 0
    return max(0, chrome_us - _CHROME_TO_UNIX_MICROS)


# Firefox places.sqlite v77 schema — minimum required tables, triggers, and
# indexes so a fresh DB is recognized by Firefox 115+. We deliberately omit
# moz_bookmarks (FoxPort still uses the HTML import path) and moz_keywords —
# Firefox creates them on first launch if absent. ``moz_anno_attributes`` +
# ``moz_annos`` are created up-front so the optional downloads → moz_annos
# direct-write path (v1.4) can land annotations alongside the visit inserts.
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

CREATE TABLE moz_anno_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(32) UNIQUE NOT NULL
);

CREATE TABLE moz_annos (
    id INTEGER PRIMARY KEY,
    place_id INTEGER NOT NULL,
    anno_attribute_id INTEGER,
    content LONGVARCHAR,
    flags INTEGER DEFAULT 0,
    expiration INTEGER DEFAULT 0,
    type INTEGER DEFAULT 0,
    dateAdded INTEGER DEFAULT 0,
    lastModified INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX moz_annos_placeattributeindex
    ON moz_annos (place_id, anno_attribute_id);

PRAGMA user_version = 86;
"""

# Downloads stored as moz_annos. Firefox's nsIDownloadHistory + about:downloads
# both walk moz_places looking for these anno_attribute names:
#   "downloads/destinationFileURI" — string, value is a file:// URI of the
#                                    saved destination on disk.
#   "downloads/metaData"           — JSON string, value carries {state,
#                                    endTime, fileSize}.
_DOWNLOAD_ANNO_DEST_URI = "downloads/destinationFileURI"
_DOWNLOAD_ANNO_METADATA = "downloads/metaData"

# moz_annos.type values per nsIAnnotationService.idl
_ANNO_TYPE_STRING = 3
_ANNO_EXPIRATION_NEVER = 0

# Firefox download.state mapping — pulled from
# toolkit/components/downloads/DownloadHistory.sys.mjs.
#   1 = succeeded, 4 = canceled, 5 = failed, 6 = in progress (mostly unused in history)
_FIREFOX_DOWNLOAD_STATE_FROM_CHROMIUM = {
    0: 6,   # in_progress
    1: 1,   # complete
    2: 4,   # cancelled
    3: 5,   # interrupted
    4: 5,   # interrupted_resumable
}

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
    downloads_annotated: int = 0
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


def _read_chromium_downloads(profile: ChromiumProfile) -> list[dict]:
    """Read Chromium's ``History.downloads`` + ``downloads_url_chains``.

    Returns a list of dicts with the fields the downloads-as-annotations
    path needs: source_url (the first chain entry), target_path,
    end_time (Chrome µs since 1601), received_bytes, state. Empty list
    on any failure so the augment step degrades to "no downloads
    annotated" instead of aborting the history migration.
    """

    src = profile.profile_dir / "History"
    if not src.is_file():
        return []
    copy = _copy_for_read(src)
    out: list[dict] = []
    try:
        conn = sqlite3.connect(str(copy))
        try:
            # downloads_url_chains has multiple rows per download id (the
            # full redirect chain). The first row (chain_index=0) is the
            # canonical source URL Firefox would have stored on the
            # moz_places row this download annotates.
            chains: dict[int, str] = {}
            try:
                for d_id, _idx, url in conn.execute(
                    "SELECT id, chain_index, url FROM downloads_url_chains "
                    "ORDER BY id, chain_index"
                ).fetchall():
                    chains.setdefault(d_id, url)
            except sqlite3.DatabaseError:
                pass
            try:
                rows = conn.execute(
                    "SELECT id, current_path, target_path, end_time, "
                    "received_bytes, state, tab_url FROM downloads"
                ).fetchall()
            except sqlite3.DatabaseError:
                rows = []
            for (d_id, current_path, target_path, end_time,
                 received_bytes, state, tab_url) in rows:
                source_url = chains.get(d_id) or tab_url or ""
                if not source_url:
                    continue
                out.append({
                    "source_url": source_url,
                    "target_path": target_path or current_path or "",
                    "end_time_chrome_us": int(end_time or 0),
                    "received_bytes": int(received_bytes or 0),
                    "state": int(state or 0),
                })
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)
    return out


def _path_to_file_uri(path: str) -> str:
    """Format a local path as a ``file://`` URI for the destinationFileURI
    annotation. Returns an empty string on missing input.

    We don't use ``pathlib.Path.as_uri`` because Chromium's
    target_path is OS-native (back-slash on Windows) but Firefox
    expects POSIX-style with forward slashes inside the URI.
    """

    if not path:
        return ""
    # Normalize separator and percent-escape only the bytes that matter.
    # urllib.parse.quote with safe="/" preserves the slash hierarchy.
    from urllib.parse import quote
    norm = path.replace("\\", "/")
    # Windows paths look like "C:/Users/..." after the normalize step;
    # the leading drive letter needs an extra slash to become
    # "file:///C:/Users/...". POSIX paths already start with "/" so the
    # double slash becomes "file:///path".
    if len(norm) >= 2 and norm[1] == ":":  # Windows drive
        return "file:///" + quote(norm, safe="/:")
    return "file://" + quote(norm, safe="/")


def _emit_download_annotations(
    conn: sqlite3.Connection,
    profile: ChromiumProfile,
    place_id_by_url: dict[str, int],
) -> int:
    """Insert moz_anno_attributes + moz_annos rows for every Chromium
    download whose source URL matched a moz_places row.

    Returns the number of downloads that were annotated. Downloads
    whose source URL didn't appear in the history (rare — Chrome
    rotates ``urls`` faster than ``downloads`` in some configs) are
    silently skipped; the user still has the standalone CSV.
    """

    downloads = _read_chromium_downloads(profile)
    if not downloads:
        return 0
    # Insert the two anno attribute name rows; ``INSERT OR IGNORE``
    # makes the call idempotent.
    conn.execute(
        "INSERT OR IGNORE INTO moz_anno_attributes (name) VALUES (?)",
        (_DOWNLOAD_ANNO_DEST_URI,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO moz_anno_attributes (name) VALUES (?)",
        (_DOWNLOAD_ANNO_METADATA,),
    )
    dest_id = conn.execute(
        "SELECT id FROM moz_anno_attributes WHERE name = ?",
        (_DOWNLOAD_ANNO_DEST_URI,),
    ).fetchone()[0]
    meta_id = conn.execute(
        "SELECT id FROM moz_anno_attributes WHERE name = ?",
        (_DOWNLOAD_ANNO_METADATA,),
    ).fetchone()[0]

    annotated = 0
    for d in downloads:
        place_id = place_id_by_url.get(d["source_url"])
        if place_id is None:
            continue
        firefox_state = _FIREFOX_DOWNLOAD_STATE_FROM_CHROMIUM.get(d["state"], 1)
        end_chrome = d["end_time_chrome_us"]
        end_unix_ms = 0
        if end_chrome > 0:
            unix_us = end_chrome - _CHROME_TO_UNIX_MICROS
            if unix_us > 0:
                end_unix_ms = unix_us // 1000
        metadata = json.dumps({
            "state": firefox_state,
            "endTime": end_unix_ms,
            "fileSize": d["received_bytes"],
        }, separators=(",", ":"))
        dest_uri = _path_to_file_uri(d["target_path"])
        # Two anno rows per place_id: destinationFileURI + metaData.
        # The moz_annos_placeattributeindex enforces uniqueness, so
        # ``INSERT OR REPLACE`` keeps the annotation idempotent across
        # re-runs of the migrator.
        conn.execute(
            "INSERT OR REPLACE INTO moz_annos "
            "(place_id, anno_attribute_id, content, flags, expiration, type, "
            " dateAdded, lastModified) "
            "VALUES (?, ?, ?, 0, ?, ?, 0, 0)",
            (place_id, dest_id, dest_uri, _ANNO_EXPIRATION_NEVER, _ANNO_TYPE_STRING),
        )
        conn.execute(
            "INSERT OR REPLACE INTO moz_annos "
            "(place_id, anno_attribute_id, content, flags, expiration, type, "
            " dateAdded, lastModified) "
            "VALUES (?, ?, ?, 0, ?, ?, 0, 0)",
            (place_id, meta_id, metadata, _ANNO_EXPIRATION_NEVER, _ANNO_TYPE_STRING),
        )
        annotated += 1
    return annotated


def migrate_history(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
    include_internal: bool = False,
    include_download_annotations: bool = False,
    date_from_us: int | None = None,
    date_to_us: int | None = None,
) -> HistoryResult:
    """Write a fresh ``places.sqlite`` to ``out_dir`` populated with the
    source profile's URLs and visits. When ``include_download_annotations``
    is true, matching Chromium downloads are added as Firefox
    ``moz_annos`` records. Bookmarks are left empty (the bookmarks
    migrator uses the HTML import path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = out_dir / "places.sqlite"

    failures: list[str] = []
    url_count = 0
    visit_count = 0
    downloads_annotated = 0

    def _in_range(visit_us: int) -> bool:
        if date_from_us is not None and visit_us < date_from_us:
            return False
        if date_to_us is not None and visit_us > date_to_us:
            return False
        return True

    if dry_run:
        for url_row, visit_rows in _iter_chromium_history(profile):
            _id, url, *_, last_visit_time, _hidden = url_row
            if not url or (not include_internal and is_browser_internal_url(url)):
                continue
            if not _in_range(int(last_visit_time or 0)):
                continue
            url_count += 1
            visit_count += sum(1 for v in visit_rows if _in_range(int(v[2] or 0)))
        return HistoryResult(
            sqlite_path=sqlite_path,
            urls=url_count,
            visits=visit_count,
            downloads_annotated=0,
            failures=failures,
        )

    # Cannot use the trigger that calls Firefox-internal get_prefix() /
    # get_host_and_port() — those are C++ functions we don't have. Instead we
    # populate moz_origins manually and set origin_id directly.
    #
    # Build into a tempdir then atomic-replace the staging path. A crash
    # during the URL/visit insert loop can't leave a corrupt places.sqlite
    # at the final filename for the README and manifest to point at.
    staging_dir = tempfile.mkdtemp(prefix="foxport_places_build_")
    try:
        staged = Path(staging_dir) / "places.sqlite"
        conn = sqlite3.connect(str(staged))
        try:
            conn.executescript(_FIREFOX_PLACES_SCHEMA)
            conn.commit()
            with conn:
                origin_cache: dict[tuple[str, str], int] = {}
                place_id_by_url: dict[str, int] = {}

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
                    if not _in_range(int(last_visit_time or 0)):
                        continue
                    # Drop individual visits outside the range too; if no visits
                    # remain, skip the entire URL.
                    visit_rows = [v for v in visit_rows if _in_range(int(v[2] or 0))]
                    if not visit_rows:
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
                        place_id_by_url[url] = place_id
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
                if include_download_annotations:
                    downloads_annotated = _emit_download_annotations(
                        conn, profile, place_id_by_url,
                    )
        finally:
            conn.close()
        replace_file_atomic(staged, sqlite_path)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return HistoryResult(
        sqlite_path=sqlite_path,
        urls=url_count,
        visits=visit_count,
        downloads_annotated=downloads_annotated,
        failures=failures,
    )
