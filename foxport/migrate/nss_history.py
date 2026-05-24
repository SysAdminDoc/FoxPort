"""Direct-write history migration — install a fresh places.sqlite straight
into a *closed* target Firefox profile, backing up the existing file first.

Same safety pattern as :mod:`nss_cookies`: refuse on locked profile, back up,
swap. Firefox rebuilds favicons.sqlite on next launch when the places.sqlite
mtime changes, so we delete favicons.sqlite to force the rebuild.
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
    backup_path: Path
    favicons_deleted: bool
    written: HistoryResult


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
    backup_path = target_path.with_name(
        f"places.foxport-backup-{int(target_path.stat().st_mtime)}.sqlite"
    ) if target_path.exists() else target_path.with_suffix(".no-backup-needed")
    if target_path.exists():
        shutil.copy2(target_path, backup_path)
        for suffix in ("-wal", "-shm"):
            sibling = target_path.with_name(target_path.name + suffix)
            if sibling.exists():
                sibling.unlink()
    shutil.copy2(history_result.sqlite_path, target_path)

    favicons = target.profile_dir / "favicons.sqlite"
    favicons_deleted = False
    if favicons.exists():
        try:
            favicons.unlink()
            favicons_deleted = True
        except OSError:
            favicons_deleted = False

    return HistoryDirectWriteResult(
        target_path=target_path,
        backup_path=backup_path,
        favicons_deleted=favicons_deleted,
        written=history_result,
    )
