"""Small file-operation helpers for data-bearing migration paths."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


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
