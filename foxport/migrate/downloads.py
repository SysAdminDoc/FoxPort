"""Downloads migration — Chromium ``History.downloads`` → Firefox CSV.

Firefox stores downloads as annotated ``moz_places`` rows
(``moz_annos.anno_attribute_id = "downloads/destinationFileURI"``), which
requires the history-direct-write path. Without direct-write we'd be
manipulating the user's live profile, which we don't do.

For the non-direct-write case we emit a **CSV** of downloads (filename,
source URL, target path, size, mime type, completion time) the user can
keep for reference or import into a download manager.

When downloads are selected alongside history direct-write, the history
migrator also annotates matching ``moz_places`` rows with Firefox's
``downloads/destinationFileURI`` + ``downloads/metaData`` records. This
module still emits the portable CSV as the audit/reference artifact.
"""

from __future__ import annotations

import csv
import io
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from foxport.browsers.detect import ChromiumProfile
from foxport.fileops import write_text_atomic


# Chromium time = µs since 1601-01-01 UTC.
_CHROME_EPOCH_OFFSET_MICROS = 11_644_473_600 * 1_000_000


_CSV_HEADER = [
    "filename",
    "source_url",
    "target_path",
    "received_bytes",
    "total_bytes",
    "mime_type",
    "start_time_iso",
    "end_time_iso",
    "state",                 # complete / interrupted / cancelled / in_progress
]


@dataclass
class DownloadsResult:
    csv_path: Path
    total: int
    written: int
    failures: list[str] = field(default_factory=list)


def _chrome_micros_to_iso(chrome_us: int) -> str:
    if chrome_us <= 0:
        return ""
    unix_us = chrome_us - _CHROME_EPOCH_OFFSET_MICROS
    if unix_us <= 0:
        return ""
    return datetime.fromtimestamp(unix_us / 1_000_000, tz=timezone.utc).isoformat()


# Chromium History.downloads.state mapping (per chrome/browser/download
# /download_history.cc): 0=in_progress, 1=complete, 2=cancelled,
# 3=interrupted (4=interrupted resumable in some versions).
_STATE_LABEL = {0: "in_progress", 1: "complete", 2: "cancelled", 3: "interrupted",
                4: "interrupted_resumable"}


def _history_db_path(profile: ChromiumProfile) -> Path | None:
    candidate = profile.profile_dir / "History"
    return candidate if candidate.is_file() else None


def _copy_for_read(src: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foxport_downloads_"))
    dest = tmp / src.name
    shutil.copy2(src, dest)
    for suffix in ("-wal", "-shm"):
        sibling = src.with_name(src.name + suffix)
        if sibling.exists():
            shutil.copy2(sibling, dest.with_name(dest.name + suffix))
    return dest


def migrate_downloads(
    profile: ChromiumProfile,
    out_dir: Path,
    *,
    dry_run: bool = False,
) -> DownloadsResult:
    """Read Chromium downloads and emit a portable CSV."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "downloads.csv"
    failures: list[str] = []

    src = _history_db_path(profile)
    if not src:
        return DownloadsResult(csv_path=csv_path, total=0, written=0, failures=failures)

    copy = _copy_for_read(src)
    try:
        conn = sqlite3.connect(str(copy))
        try:
            cur = conn.execute(
                "SELECT id, current_path, target_path, start_time, end_time, "
                "received_bytes, total_bytes, mime_type, state, tab_url FROM downloads"
            )
            rows = cur.fetchall()
            # downloads_url_chains has the real source URL by download id.
            chains = {}
            try:
                for d_id, _idx, url in conn.execute(
                    "SELECT id, chain_index, url FROM downloads_url_chains "
                    "ORDER BY id, chain_index"
                ).fetchall():
                    chains.setdefault(d_id, url)  # first chain entry wins
            except sqlite3.DatabaseError:
                pass
        except sqlite3.DatabaseError as exc:
            failures.append(f"{exc}")
            rows = []
            chains = {}
        finally:
            conn.close()
    finally:
        shutil.rmtree(copy.parent, ignore_errors=True)

    if dry_run:
        return DownloadsResult(csv_path=csv_path, total=len(rows), written=0, failures=failures)

    written = 0
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
    writer.writerow(_CSV_HEADER)
    for row in rows:
        (d_id, current_path, target_path, start_time, end_time,
         received_bytes, total_bytes, mime_type, state, tab_url) = row
        filename = Path(target_path or current_path or "").name
        source_url = chains.get(d_id) or tab_url or ""
        writer.writerow([
            filename,
            source_url,
            target_path or current_path or "",
            int(received_bytes or 0),
            int(total_bytes or 0),
            mime_type or "",
            _chrome_micros_to_iso(start_time or 0),
            _chrome_micros_to_iso(end_time or 0),
            _STATE_LABEL.get(int(state or 0), str(state)),
        ])
        written += 1
    if written > 0:
        write_text_atomic(csv_path, buf.getvalue())

    return DownloadsResult(
        csv_path=csv_path,
        total=len(rows),
        written=written,
        failures=failures,
    )
