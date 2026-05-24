"""Direct-write history migration — install a fresh places.sqlite straight
into a *closed* target Firefox profile, backing up the existing file first.

Same safety pattern as :mod:`nss_cookies`: refuse on locked profile,
back up the previous file with a timestamped name, then atomically copy
the new one in. Firefox rebuilds ``favicons.sqlite`` from the imported
visits on next launch, so we move the user's existing favicons aside
to a timestamped backup (NOT delete — accumulated favicon icons
represent months of browsing and shouldn't be unrecoverable on a
regret path).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    is_firefox_profile_locked,
)
from foxport.migrate.history import HistoryResult, migrate_history
from foxport.migrate.nss_cookies import ProfileLockedError


@dataclass
class HistoryDirectWriteResult:
    target_path: Path
    backup_path: Path | None             # None when the target had nothing to back up
    favicons_backup_path: Path | None    # None when the target had no favicons.sqlite
    written: HistoryResult

    @property
    def favicons_deleted(self) -> bool:
        """Backward-compat shim — old callers asked whether favicons were
        "deleted". The new semantics is "moved aside to a backup", but
        the answer to the original question is True when the move ran."""
        return self.favicons_backup_path is not None


def _backup_path_for(target_path: Path) -> Path | None:
    """Return the timestamped backup path for an existing file, or None."""
    if not target_path.exists():
        return None
    mtime = int(target_path.stat().st_mtime)
    return target_path.with_name(
        f"{target_path.stem}.foxport-backup-{mtime}{target_path.suffix}"
    )


def write_history_into_target(
    source: ChromiumProfile,
    target: FirefoxProfile,
    staging_dir: Path,
) -> HistoryDirectWriteResult:
    if is_firefox_profile_locked(target):
        raise ProfileLockedError(
            f"target profile {target.label} is locked — close Firefox before importing"
        )
    history_result = migrate_history(source, staging_dir)
    target_path = target.profile_dir / "places.sqlite"

    backup_path = _backup_path_for(target_path)
    if backup_path is not None:
        shutil.copy2(target_path, backup_path)
        # Clear WAL/SHM siblings so Firefox doesn't re-merge stale state into
        # the imported DB on next launch.
        for suffix in ("-wal", "-shm"):
            sibling = target_path.with_name(target_path.name + suffix)
            if sibling.exists():
                try:
                    sibling.unlink()
                except OSError:
                    # WAL on a network share can be locked; non-fatal.
                    pass
    shutil.copy2(history_result.sqlite_path, target_path)

    favicons = target.profile_dir / "favicons.sqlite"
    favicons_backup: Path | None = None
    if favicons.exists():
        try:
            mtime = int(favicons.stat().st_mtime)
            favicons_backup = favicons.with_name(
                f"favicons.foxport-backup-{mtime}.sqlite"
            )
            favicons.rename(favicons_backup)
        except OSError:
            favicons_backup = None

    return HistoryDirectWriteResult(
        target_path=target_path,
        backup_path=backup_path,
        favicons_backup_path=favicons_backup,
        written=history_result,
    )
