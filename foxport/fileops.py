"""Small file-operation helpers for data-bearing migration paths."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path


# Pattern that matches the timestamped backup names produced by every
# direct-write helper. Group 1 is the stem (everything before
# ``.foxport-backup-<mtime>``); group 2 is the optional suffix.
#
# Examples:
#   logins.foxport-backup-1700000000.json           → stem="logins" suffix=".json"
#   cookies.foxport-backup-1700000000.sqlite        → stem="cookies" suffix=".sqlite"
#   places.foxport-backup-1700000000.sqlite         → stem="places" suffix=".sqlite"
#   recovery.foxport-backup-1700000000.jsonlz4      → stem="recovery" suffix=".jsonlz4"
#   Login Data.foxport-backup-1700000000            → stem="Login Data" suffix=""
_BACKUP_NAME_RE = re.compile(
    r"^(?P<stem>.+?)\.foxport-backup-\d+(?P<suffix>\..+)?$"
)


def write_text_atomic(path: Path, payload: str, *, encoding: str = "utf-8") -> None:
    """Write text through a sibling temp file, then atomically replace target.

    Thin wrapper over :func:`write_bytes_atomic` so emitters that build a
    string in memory (CSV, HTML, JSON) don't have to handle the encode step
    themselves. ``newline=""`` is not configurable here — the CSV writer
    handles line endings before we get a finished string.
    """

    write_bytes_atomic(path, payload.encode(encoding))


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    """Write bytes through a sibling temp file, then atomically replace target."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.foxport-", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fd = -1
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        tmp.replace(path)
    except Exception:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def timestamped_backup_path(target_path: Path) -> Path | None:
    """Return the timestamped backup path for an existing file, or ``None``.

    Convention shared by every direct-write helper: a file backed up at
    write time becomes ``{stem}.foxport-backup-{mtime}{suffix}`` next to
    the original. Returns ``None`` when the target doesn't exist
    (nothing to back up — caller skips the copy step).
    """

    target_path = Path(target_path)
    if not target_path.exists():
        return None
    mtime = int(target_path.stat().st_mtime)
    return target_path.with_name(
        f"{target_path.stem}.foxport-backup-{mtime}{target_path.suffix}"
    )


def original_from_backup(backup_path: Path) -> Path | None:
    """Reverse :func:`timestamped_backup_path`: given a ``*.foxport-
    backup-<mtime>.*`` file, return the path it was originally a copy
    of (the live file the direct-write step replaced).

    Returns ``None`` when ``backup_path`` doesn't match the naming
    convention. Doesn't check whether the resolved path exists — the
    caller (typically the restore-from-backup wizard) can decide
    whether a missing target file means "fresh restore" or "wrong
    bundle".
    """

    backup_path = Path(backup_path)
    match = _BACKUP_NAME_RE.match(backup_path.name)
    if match is None:
        return None
    stem = match.group("stem")
    suffix = match.group("suffix") or ""
    return backup_path.with_name(f"{stem}{suffix}")


def restore_from_backup(
    backup_path: Path,
    *,
    target_path: Path | None = None,
) -> Path:
    """Copy ``backup_path`` over its original target via atomic replace.

    The "regret undo" for any direct-write run. Resolves the original
    target via :func:`original_from_backup` (so the caller doesn't need
    to remember it) unless ``target_path`` is explicitly supplied for
    paranoid callers who want to be sure.

    Returns the absolute path of the restored target. Raises
    :class:`FileNotFoundError` when the backup file is gone and
    :class:`ValueError` when the backup name doesn't match the
    convention and no explicit ``target_path`` was given.
    """

    backup_path = Path(backup_path)
    if not backup_path.is_file():
        raise FileNotFoundError(f"backup file {backup_path} not found")
    if target_path is None:
        resolved = original_from_backup(backup_path)
        if resolved is None:
            raise ValueError(
                f"{backup_path.name} does not match the foxport-backup naming "
                "convention; pass target_path= explicitly to restore."
            )
        target_path = resolved
    target_path = Path(target_path)
    replace_file_atomic(backup_path, target_path)
    return target_path


def replace_file_atomic(source: Path, target: Path) -> None:
    """Copy source bytes through a temp file, then atomically replace target."""

    source = Path(source)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as inp:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.foxport-", dir=str(target.parent))
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                fd = -1
                shutil.copyfileobj(inp, out, length=1024 * 1024)
                out.flush()
                try:
                    os.fsync(out.fileno())
                except OSError:
                    pass
            tmp.replace(target)
        except Exception:
            if fd != -1:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
