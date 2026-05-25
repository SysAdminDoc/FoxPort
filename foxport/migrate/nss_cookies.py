"""Direct-write cookies migration — install a fresh cookies.sqlite straight
into a *closed* target Firefox profile, backing up the existing file first.

This is the cookies counterpart to :mod:`foxport.migrate.nss_passwords`. NSS
isn't involved (Firefox stores cookies unencrypted in this DB), but we
borrow the same safety pattern: refuse on locked profile, back up the
previous file with a timestamped name, then replace.
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
from foxport.fileops import replace_file_atomic
from foxport.migrate.cookies import CookieResult, migrate_cookies


class ProfileLockedError(RuntimeError):
    """Target profile is in use; bailing out."""


@dataclass
class CookieDirectWriteResult:
    target_path: Path
    backup_path: Path | None     # None when the target had nothing to back up
    written: CookieResult


def _backup_path_for(target_path: Path) -> Path | None:
    """Return the timestamped backup path for an existing file, or None."""
    if not target_path.exists():
        return None
    mtime = int(target_path.stat().st_mtime)
    return target_path.with_name(
        f"{target_path.stem}.foxport-backup-{mtime}{target_path.suffix}"
    )


def write_cookies_into_target(
    source: ChromiumProfile,
    target: FirefoxProfile,
    staging_dir: Path,
) -> CookieDirectWriteResult:
    """Run the normal cookies migrator into ``staging_dir`` and then atomically
    swap the result into ``target/cookies.sqlite``, backing up the previous file.
    """
    if is_firefox_profile_locked(target):
        raise ProfileLockedError(
            f"target profile {target.label} is locked — close Firefox before importing"
        )
    cookies_result = migrate_cookies(source, staging_dir)
    target_path = target.profile_dir / "cookies.sqlite"

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
    replace_file_atomic(cookies_result.sqlite_path, target_path)
    return CookieDirectWriteResult(
        target_path=target_path,
        backup_path=backup_path,
        written=cookies_result,
    )
