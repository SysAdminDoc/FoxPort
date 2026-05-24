"""Background workers — keep the UI responsive while migrations run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    detect_chromium,
    detect_firefox,
    read_installed_firefox_extensions,
)
from foxport.browsers.firefox import import_instructions, make_export_dir
from foxport.crypto.dpapi import DecryptionError
from foxport.migrate.bookmarks import migrate_bookmarks
from foxport.migrate.cookies import migrate_cookies
from foxport.migrate.extensions import migrate_extensions
from foxport.migrate.history import migrate_history
from foxport.migrate.nss_passwords import (
    ProfileLockedError,
    migrate_passwords_via_nss,
)
from foxport.migrate.passwords import migrate_passwords


@dataclass
class MigrationRequest:
    """Inputs collected from the wizard before kicking off a run."""

    source: ChromiumProfile
    target: FirefoxProfile | None
    out_root: Path
    do_passwords: bool
    do_bookmarks: bool
    do_extensions: bool
    do_cookies: bool = False
    do_history: bool = False
    extensions_online: bool = True
    dry_run: bool = False
    password_include_keys: set[str] | None = None
    bookmark_excluded_paths: set[tuple[str, ...]] = field(default_factory=set)
    direct_write_passwords: bool = False


class DetectWorker(QObject):
    """One-shot detection pass on a background thread."""

    finished = pyqtSignal(list, list)  # (chromium_profiles, firefox_profiles)
    log = pyqtSignal(str)

    def run(self) -> None:
        self.log.emit("Scanning %LOCALAPPDATA% / %APPDATA% for Chromium browsers...")
        chromium = detect_chromium()
        self.log.emit(f"  Found {len(chromium)} Chromium profile(s).")
        self.log.emit("Scanning %APPDATA% for Firefox-family browsers...")
        firefox = detect_firefox()
        self.log.emit(f"  Found {len(firefox)} Firefox profile(s).")
        self.finished.emit(chromium, firefox)


class MigrationWorker(QObject):
    """Run the full migration pipeline. Emits granular progress."""

    log = pyqtSignal(str)
    step = pyqtSignal(int, int)  # (current, total)
    finished = pyqtSignal(bool, str, dict)  # (ok, export_dir_or_error, exports map)

    def __init__(self, request: MigrationRequest) -> None:
        super().__init__()
        self._req = request

    def run(self) -> None:
        req = self._req
        steps = sum([
            req.do_passwords, req.do_bookmarks, req.do_extensions,
            req.do_cookies, req.do_history,
        ]) or 1
        target_label = req.target.label if req.target else "firefox"
        if req.dry_run:
            target_label += "_dryrun"
        out_dir = make_export_dir(req.out_root, req.source.label, target_label)
        self.log.emit(f"Output: {out_dir}")
        if req.dry_run:
            self.log.emit("DRY RUN — counts and decrypt tests only; no files will be written.")
        current = 0
        exports: dict[str, Path] = {}

        already_installed: set[str] = set()
        if req.target and not req.dry_run:
            already_installed = read_installed_firefox_extensions(req.target)
            if already_installed:
                self.log.emit(
                    f"  Target already has {len(already_installed)} extension(s); "
                    "matching ones will be flagged in the report."
                )

        try:
            if req.do_passwords:
                current += 1
                self.step.emit(current, steps)
                if req.password_include_keys is not None:
                    self.log.emit(
                        f"Decrypting passwords (filtered to {len(req.password_include_keys)} selected rows)..."
                    )
                else:
                    self.log.emit("Decrypting passwords...")
                row_filter = None
                if req.password_include_keys is not None:
                    keep = req.password_include_keys
                    row_filter = lambda r: f"{r.origin_url}\x00{r.username}" in keep  # noqa: E731

                if req.direct_write_passwords and req.target and not req.dry_run:
                    self.log.emit("  Direct-write mode: encrypting via target profile's NSS...")
                    try:
                        nss_result = migrate_passwords_via_nss(req.source, req.target)
                    except ProfileLockedError as exc:
                        self.log.emit(f"  Direct-write aborted: {exc}")
                    except Exception as exc:  # noqa: BLE001
                        self.log.emit(f"  Direct-write failed: {exc} — falling back to CSV.")
                    else:
                        self.log.emit(
                            f"  Wrote {nss_result.written} new login(s) into {nss_result.target_logins_json}; "
                            f"{nss_result.skipped_existing} already present, {nss_result.failed} failed."
                        )
                        if nss_result.backup_file.exists():
                            self.log.emit(f"  Previous logins.json backed up to {nss_result.backup_file.name}")
                        # Also emit CSV alongside for safety/audit.
                try:
                    result = migrate_passwords(
                        req.source, out_dir, dry_run=req.dry_run, row_filter=row_filter,
                    )
                except DecryptionError as exc:
                    self.log.emit(f"  Password decryption failed: {exc}")
                else:
                    if not req.dry_run:
                        exports["passwords"] = result.csv_path
                    self.log.emit(
                        f"  {result.decrypted} decrypted, {result.skipped_empty} empty, "
                        f"{result.failed} failed out of {result.total} total."
                    )
                    if result.failures:
                        for line in result.failures[:5]:
                            self.log.emit(f"    ! {line}")
                        if len(result.failures) > 5:
                            self.log.emit(f"    ... +{len(result.failures) - 5} more")

            if req.do_bookmarks:
                current += 1
                self.step.emit(current, steps)
                if req.bookmark_excluded_paths:
                    self.log.emit(
                        f"Converting bookmarks (skipping {len(req.bookmark_excluded_paths)} folder(s))..."
                    )
                else:
                    self.log.emit("Converting bookmarks...")
                excluded = req.bookmark_excluded_paths
                folder_filter = None
                if excluded:
                    def folder_filter(path: list[str]) -> bool:
                        t = tuple(path)
                        # Skip the node itself and anything under any excluded ancestor.
                        for i in range(1, len(t) + 1):
                            if t[:i] in excluded:
                                return False
                        return True
                bookmark_result = migrate_bookmarks(
                    req.source, out_dir, dry_run=req.dry_run, folder_filter=folder_filter,
                )
                if not req.dry_run:
                    exports["bookmarks"] = bookmark_result.html_path
                self.log.emit(
                    f"  {bookmark_result.urls} URLs across {bookmark_result.folders} folders."
                )

            if req.do_extensions:
                current += 1
                self.step.emit(current, steps)
                mode = "online (AMO lookup)" if req.extensions_online else "offline (curated only)"
                self.log.emit(f"Mapping extensions, {mode}...")
                ext_result = migrate_extensions(
                    req.source,
                    out_dir,
                    online=req.extensions_online,
                    already_installed_guids=already_installed,
                    dry_run=req.dry_run,
                )
                if not req.dry_run:
                    exports["extensions"] = ext_result.html_path
                if already_installed:
                    self.log.emit(
                        f"  {ext_result.matched} matched ({ext_result.already_installed} already installed), "
                        f"{ext_result.unmatched} unmatched of {len(ext_result.matches)} installed."
                    )
                else:
                    self.log.emit(
                        f"  {ext_result.matched} matched, {ext_result.unmatched} unmatched "
                        f"out of {len(ext_result.matches)} installed."
                    )

            if req.do_cookies:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Decrypting cookies...")
                try:
                    cookie_result = migrate_cookies(req.source, out_dir, dry_run=req.dry_run)
                except DecryptionError as exc:
                    self.log.emit(f"  Cookie decryption failed: {exc}")
                else:
                    if not req.dry_run:
                        exports["cookies"] = cookie_result.sqlite_path
                    self.log.emit(
                        f"  {cookie_result.decrypted} decrypted, {cookie_result.failed} failed "
                        f"out of {cookie_result.total} total."
                    )

            if req.do_history:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Migrating history...")
                history_result = migrate_history(req.source, out_dir, dry_run=req.dry_run)
                if not req.dry_run:
                    exports["history"] = history_result.sqlite_path
                self.log.emit(
                    f"  {history_result.urls} URLs / {history_result.visits} visits "
                    f"({len(history_result.failures)} failed)."
                )

            if not req.dry_run:
                instructions_path = out_dir / "README.txt"
                instructions_path.write_text(
                    import_instructions(req.target, exports), encoding="utf-8"
                )
                self.log.emit(f"Instructions written to {instructions_path.name}")
            else:
                self.log.emit("Dry-run complete. No files were written.")
            self.finished.emit(True, str(out_dir), {k: str(v) for k, v in exports.items()})

        except Exception as exc:
            self.log.emit(f"FATAL: {exc}")
            self.finished.emit(False, str(exc), {})


def make_thread(worker: QObject) -> QThread:
    """Move ``worker`` onto a new QThread and wire teardown."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)  # type: ignore[attr-defined]
    return thread
