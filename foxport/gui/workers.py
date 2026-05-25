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
from foxport.crash_reporting import (
    crash_reporting_network_host,
    current_crash_reporting_status,
)
from foxport.manifest import (
    RunManifest,
    build_artifact,
    now_iso,
    write_manifest,
)
from foxport.migrate.autofill import migrate_autofill
from foxport.migrate.bookmarks import migrate_bookmarks
from foxport.migrate.cards import migrate_cards
from foxport.migrate.cookies import migrate_cookies
from foxport.migrate.downloads import migrate_downloads
from foxport.migrate.extensions import migrate_extensions
from foxport.migrate.extension_settings import migrate_extension_settings
from foxport.migrate.history import migrate_history
from foxport.migrate.nss_cookies import write_cookies_into_target
from foxport.migrate.nss_history import write_history_into_target
from foxport.migrate.open_tabs import migrate_open_tabs, write_session_into_target
from foxport.migrate.nss_passwords import (
    ProfileLockedError,
    migrate_passwords_via_nss,
)
from foxport.migrate.passwords import migrate_passwords
from foxport.migrate.search_engines import migrate_search_engines
from foxport.migrate_reverse.bookmarks import migrate_bookmarks_reverse
from foxport.migrate_reverse.extensions import migrate_extensions_reverse
from foxport.migrate_reverse.passwords import migrate_passwords_reverse
from foxport.telemetry import (
    TELEMETRY_HOST,
    MigrationTelemetryPayload,
    record_migration,
)


@dataclass
class MigrationRequest:
    """Inputs collected from the wizard before kicking off a run."""

    source: ChromiumProfile | FirefoxProfile
    target: FirefoxProfile | ChromiumProfile | None
    out_root: Path
    do_passwords: bool
    do_bookmarks: bool
    do_extensions: bool
    do_cookies: bool = False
    do_history: bool = False
    do_autofill: bool = False
    do_cards: bool = False
    do_search_engines: bool = False
    do_open_tabs: bool = False
    do_downloads: bool = False
    extension_settings_allowlist: set[str] = field(default_factory=set)
    extensions_online: bool = True
    dry_run: bool = False
    password_include_keys: set[str] | None = None
    bookmark_excluded_paths: set[tuple[str, ...]] = field(default_factory=set)
    history_date_from_us: int | None = None
    history_date_to_us: int | None = None
    direct_write_passwords: bool = False
    direct_write_cookies: bool = False
    direct_write_history: bool = False
    direct_write_open_tabs: bool = False
    # Per-category policy applied when the matching direct_write_* flag
    # is True. See foxport.migrate.conflicts.DirectWritePolicy for the
    # three values. ``apply`` is the v1.3 default; ``skip`` and
    # ``backup-only`` were added in v1.3.3 via the conflict-review
    # dialog so the user can choose a safer disposition without
    # un-toggling the whole category.
    policy_passwords: str = "apply"
    policy_cookies: str = "apply"
    policy_history: str = "apply"
    policy_open_tabs: str = "apply"
    hibp_scan: bool = False
    telemetry_opt_in: bool = False
    crash_reporting_opt_in: bool = False
    direction: str = "forward"      # "forward" (chromium->firefox) or "reverse"
    master_password: str = ""
    # When True, the on-disk manifest.json scrubs the current user's
    # home-dir prefix from backup_path / labels so a manifest uploaded
    # for support doesn't leak the username. Driven by
    # Settings.privacy_redact_manifest in the GUI; the CLI uses
    # ``--privacy-redact`` for the same effect.
    privacy_redact_manifest: bool = False


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
    # Direct-write backups produced this run. Keys are item slugs (passwords,
    # cookies, history, ...); values are str paths to the timestamped backup
    # of the previous file in the target profile, or empty string when the
    # target had nothing to back up. The Done screen reads this to render
    # "Reveal backup" actions next to the direct-write category buttons.
    directWriteBackups = pyqtSignal(dict)

    def __init__(self, request: MigrationRequest) -> None:
        super().__init__()
        self._req = request

    def run(self) -> None:
        req = self._req
        if req.direction == "reverse":
            self._run_reverse()
            return
        steps = sum([
            req.do_passwords, req.do_bookmarks, req.do_extensions,
            req.do_cookies, req.do_history,
            req.do_autofill, req.do_cards, req.do_search_engines,
            req.do_open_tabs, req.do_downloads,
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
        # Per-key count + backup tracking for the run manifest. Workers fill
        # these in as each category finishes; the manifest writer below
        # consumes the snapshot at the end of the try/except block.
        counts: dict[str, int] = {}
        direct_write_backups: dict[str, Path | None] = {}
        # HIBP tri-state ("" until passwords runs with the scan opted in;
        # then "checked-clean" / "checked-hits" / "network-error" / "disabled").
        # Drives both the Run log line above AND the manifest network field
        # so a snapshot consumer can tell scan-failed from scan-clean.
        hibp_status: str = ""

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
                    policy = req.policy_passwords
                    if policy == "skip":
                        self.log.emit(
                            "  Direct-write policy = SKIP — leaving target logins.json "
                            "untouched; staging CSV still produced."
                        )
                    else:
                        # Pre-flight conflict analysis — non-mutating count of
                        # how many source logins already exist in the target.
                        # Surfaces the skip number BEFORE we hit NSS so the
                        # user sees "12 of 50 already exist; will write 38".
                        try:
                            from foxport.migrate.conflicts import analyze_passwords
                            conflicts = analyze_passwords(req.source, req.target)
                            self.log.emit(
                                f"  Pre-flight: {conflicts.duplicates} of {conflicts.source_total} "
                                f"already in target, {conflicts.new} new."
                            )
                        except Exception as exc:  # noqa: BLE001 — informational
                            self.log.emit(f"  Pre-flight skipped: {exc}")
                    if policy == "backup-only":
                        try:
                            from foxport.fileops import timestamped_backup_path
                            logins_json = req.target.profile_dir / "logins.json"
                            backup = timestamped_backup_path(logins_json)
                            if backup is not None:
                                import shutil as _shutil
                                _shutil.copy2(logins_json, backup)
                                direct_write_backups["passwords"] = backup
                                self.log.emit(
                                    f"  Direct-write policy = BACKUP-ONLY — copied "
                                    f"logins.json to {backup.name}; not writing new entries."
                                )
                            else:
                                self.log.emit(
                                    "  Direct-write policy = BACKUP-ONLY — target had "
                                    "no logins.json to back up."
                                )
                        except Exception as exc:  # noqa: BLE001
                            self.log.emit(f"  Backup-only failed: {exc}")
                    elif policy == "skip":
                        pass  # Pre-flight already emitted; nothing to do.
                    else:
                        self.log.emit("  Direct-write mode: encrypting via target profile's NSS...")
                        try:
                            nss_result = migrate_passwords_via_nss(req.source, req.target)
                        except ProfileLockedError as exc:
                            self.log.emit(f"  Direct-write aborted: {exc}")
                            nss_result = None
                        except Exception as exc:  # noqa: BLE001
                            self.log.emit(f"  Direct-write failed: {exc} — falling back to CSV.")
                            nss_result = None
                        if nss_result is not None:
                            self.log.emit(
                                f"  Wrote {nss_result.written} new login(s) into {nss_result.target_logins_json}; "
                                f"{nss_result.skipped_existing} already present, {nss_result.failed} failed."
                            )
                            if nss_result.backup_file is not None:
                                self.log.emit(f"  Previous logins.json backed up to {nss_result.backup_file.name}")
                            direct_write_backups["passwords"] = nss_result.backup_file
                            nss_version = getattr(nss_result, "nss_version", "")
                            if nss_version:
                                self.log.emit(f"  NSS version: {nss_version}")
                            # Also emit CSV alongside for safety/audit.
                try:
                    result = migrate_passwords(
                        req.source, out_dir, dry_run=req.dry_run, row_filter=row_filter,
                        hibp_scan=req.hibp_scan,
                    )
                except DecryptionError as exc:
                    self.log.emit(f"  Password decryption failed: {exc}")
                else:
                    if not req.dry_run:
                        exports["passwords"] = result.csv_path
                    counts["passwords"] = result.decrypted
                    self.log.emit(
                        f"  {result.decrypted} decrypted, {result.skipped_empty} empty, "
                        f"{result.failed} failed out of {result.total} total."
                    )
                    if result.failures:
                        for line in result.failures[:5]:
                            self.log.emit(f"    ! {line}")
                        if len(result.failures) > 5:
                            self.log.emit(f"    ... +{len(result.failures) - 5} more")
                    if req.hibp_scan:
                        # Tri-state — "no hits" + "network error" used to both
                        # log as "no passwords found in known breaches", which
                        # silently hid scan failures. Distinguish them now so
                        # the user knows whether the absence of hits is real.
                        status = getattr(result, "hibp_status", "")
                        hibp_status = status
                        if status == "checked-hits":
                            self.log.emit(
                                f"  HIBP: {result.hibp_hits} passwords found in known breaches "
                                f"— see {result.hibp_report_path.name}"
                            )
                            exports["hibp"] = result.hibp_report_path
                            counts["hibp"] = result.hibp_hits
                        elif status == "checked-clean":
                            self.log.emit("  HIBP: no passwords found in known breaches.")
                        elif status == "network-error":
                            self.log.emit(
                                "  HIBP: scan failed — one or more passwords were NOT checked. "
                                "Retry with a working network or accept the risk."
                            )
                        else:
                            self.log.emit("  HIBP: status unknown.")

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
                counts["bookmarks"] = bookmark_result.urls
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
                counts["extensions"] = len(ext_result.matches)
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
                # Surface curated-map staleness so the user knows to
                # update FoxPort if AMO slugs have rotated since
                # release. Warnings come from extensions._curated_map_warnings.
                for warning in ext_result.warnings:
                    self.log.emit(f"  ⚠ {warning}")
                if req.extension_settings_allowlist:
                    selected = ", ".join(sorted(req.extension_settings_allowlist))
                    self.log.emit(f"  Exporting allowlisted extension settings ({selected})...")
                    settings_result = migrate_extension_settings(
                        req.source,
                        out_dir,
                        selected=req.extension_settings_allowlist,
                        dry_run=req.dry_run,
                    )
                    counts["extension_settings"] = settings_result.count
                    if not req.dry_run and settings_result.json_path.exists():
                        exports["extension_settings"] = settings_result.json_path
                    if settings_result.exported:
                        labels = ", ".join(item.label for item in settings_result.exported)
                        self.log.emit(f"  Extension settings exported for: {labels}.")
                    for line in settings_result.skipped[:5]:
                        self.log.emit(f"    - {line}")
                    for line in settings_result.failures[:5]:
                        self.log.emit(f"    ! {line}")

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
                    counts["cookies"] = cookie_result.decrypted
                    self.log.emit(
                        f"  {cookie_result.decrypted} decrypted, {cookie_result.failed} failed "
                        f"out of {cookie_result.total} total."
                    )
                    if req.direct_write_cookies and req.target and not req.dry_run:
                        policy = req.policy_cookies
                        if policy != "skip":
                            try:
                                from foxport.migrate.conflicts import analyze_cookies
                                ck_conflicts = analyze_cookies(req.source, req.target)
                                if policy == "merge":
                                    self.log.emit(
                                        f"  Pre-flight: {ck_conflicts.source_total} source cookies "
                                        "will MERGE into target; existing target rows are preserved."
                                    )
                                else:
                                    self.log.emit(
                                        f"  Pre-flight: {ck_conflicts.source_total} source cookies will "
                                        f"REPLACE {ck_conflicts.duplicates} existing rows in target."
                                    )
                            except Exception as exc:  # noqa: BLE001
                                self.log.emit(f"  Pre-flight skipped: {exc}")
                        if policy == "skip":
                            self.log.emit(
                                "  Direct-write policy = SKIP — target cookies.sqlite "
                                "untouched; staging file still produced."
                            )
                        elif policy == "backup-only":
                            try:
                                from foxport.fileops import timestamped_backup_path
                                import shutil as _shutil
                                target_db = req.target.profile_dir / "cookies.sqlite"
                                backup = timestamped_backup_path(target_db)
                                if backup is not None:
                                    _shutil.copy2(target_db, backup)
                                    direct_write_backups["cookies"] = backup
                                    self.log.emit(
                                        f"  Direct-write policy = BACKUP-ONLY — copied "
                                        f"cookies.sqlite to {backup.name}; not replacing."
                                    )
                                else:
                                    self.log.emit(
                                        "  Direct-write policy = BACKUP-ONLY — target had "
                                        "no cookies.sqlite to back up."
                                    )
                            except Exception as exc:  # noqa: BLE001
                                self.log.emit(f"  Backup-only failed: {exc}")
                        elif policy == "merge":
                            try:
                                cdw = write_cookies_into_target(
                                    req.source, req.target, out_dir, merge=True,
                                )
                            except ProfileLockedError as exc:
                                self.log.emit(f"  Cookies merge aborted: {exc}")
                            else:
                                direct_write_backups["cookies"] = cdw.backup_path
                                backup_note = (
                                    f"previous backed up as {cdw.backup_path.name}"
                                    if cdw.backup_path is not None
                                    else "no previous file to back up"
                                )
                                self.log.emit(
                                    f"  Merged cookies.sqlite into {cdw.target_path}; "
                                    f"{cdw.inserted} inserted, {cdw.skipped_existing} "
                                    f"already in target; {backup_note}."
                                )
                        else:
                            try:
                                cdw = write_cookies_into_target(req.source, req.target, out_dir)
                            except ProfileLockedError as exc:
                                self.log.emit(f"  Cookies direct-write aborted: {exc}")
                            else:
                                direct_write_backups["cookies"] = cdw.backup_path
                                if cdw.backup_path is not None:
                                    self.log.emit(
                                        f"  Wrote cookies.sqlite into {cdw.target_path}; "
                                        f"previous backed up as {cdw.backup_path.name}"
                                    )
                                else:
                                    self.log.emit(
                                        f"  Wrote cookies.sqlite into {cdw.target_path} "
                                        "(no previous file to back up)"
                                    )

            if req.do_history:
                current += 1
                self.step.emit(current, steps)
                if req.history_date_from_us or req.history_date_to_us:
                    self.log.emit("Migrating history (date-range filter active)...")
                else:
                    self.log.emit("Migrating history...")
                history_result = migrate_history(
                    req.source, out_dir, dry_run=req.dry_run,
                    include_download_annotations=(
                        req.do_downloads
                        and req.direct_write_history
                        and req.policy_history in {"apply", "merge"}
                    ),
                    date_from_us=req.history_date_from_us,
                    date_to_us=req.history_date_to_us,
                )
                if not req.dry_run:
                    exports["history"] = history_result.sqlite_path
                counts["history"] = history_result.visits
                self.log.emit(
                    f"  {history_result.urls} URLs / {history_result.visits} visits "
                    f"({len(history_result.failures)} failed)."
                )
                if req.direct_write_history and req.target and not req.dry_run:
                    policy = req.policy_history
                    if policy != "skip":
                        try:
                            from foxport.migrate.conflicts import analyze_history
                            h_conflicts = analyze_history(req.source, req.target)
                            if policy == "merge":
                                self.log.emit(
                                    f"  Pre-flight: {h_conflicts.source_total} source URLs "
                                    "will MERGE into target; existing target history is preserved."
                                )
                            else:
                                self.log.emit(
                                    f"  Pre-flight: {h_conflicts.source_total} source URLs will "
                                    f"REPLACE {h_conflicts.duplicates} existing places.sqlite rows."
                                )
                        except Exception as exc:  # noqa: BLE001
                            self.log.emit(f"  Pre-flight skipped: {exc}")
                    if policy == "skip":
                        self.log.emit(
                            "  Direct-write policy = SKIP — target places.sqlite "
                            "untouched; staging file still produced."
                        )
                    elif policy == "backup-only":
                        try:
                            from foxport.fileops import timestamped_backup_path
                            import shutil as _shutil
                            target_db = req.target.profile_dir / "places.sqlite"
                            backup = timestamped_backup_path(target_db)
                            if backup is not None:
                                _shutil.copy2(target_db, backup)
                                direct_write_backups["history"] = backup
                                self.log.emit(
                                    f"  Direct-write policy = BACKUP-ONLY — copied "
                                    f"places.sqlite to {backup.name}; not replacing."
                                )
                            else:
                                self.log.emit(
                                    "  Direct-write policy = BACKUP-ONLY — target had "
                                    "no places.sqlite to back up."
                                )
                        except Exception as exc:  # noqa: BLE001
                            self.log.emit(f"  Backup-only failed: {exc}")
                    elif policy == "merge":
                        try:
                            hdw = write_history_into_target(
                                req.source,
                                req.target,
                                out_dir,
                                include_download_annotations=req.do_downloads,
                                merge=True,
                            )
                        except ProfileLockedError as exc:
                            self.log.emit(f"  History merge aborted: {exc}")
                        else:
                            direct_write_backups["history"] = hdw.backup_path
                            backup_note = (
                                f"previous backed up as {hdw.backup_path.name}"
                                if hdw.backup_path is not None
                                else "no previous places.sqlite to back up"
                            )
                            self.log.emit(
                                f"  Merged places.sqlite into {hdw.target_path}; "
                                f"{hdw.places_inserted} new URL(s), "
                                f"{hdw.visits_inserted} visit(s) inserted, "
                                f"{hdw.visits_skipped_existing} already in target; "
                                f"{backup_note}."
                            )
                            if hdw.written.downloads_annotated:
                                self.log.emit(
                                    f"  Annotated {hdw.written.downloads_annotated} "
                                    "download(s) in places.sqlite."
                                )
                    else:
                        try:
                            hdw = write_history_into_target(
                                req.source,
                                req.target,
                                out_dir,
                                include_download_annotations=req.do_downloads,
                            )
                        except ProfileLockedError as exc:
                            self.log.emit(f"  History direct-write aborted: {exc}")
                        else:
                            direct_write_backups["history"] = hdw.backup_path
                            if hdw.backup_path is not None:
                                places_note = f"previous backed up as {hdw.backup_path.name}"
                            else:
                                places_note = "no previous places.sqlite to back up"
                            if hdw.favicons_backup_path is not None:
                                favicons_note = (
                                    f" favicons.sqlite moved aside to "
                                    f"{hdw.favicons_backup_path.name} (Firefox will rebuild)."
                                )
                            else:
                                favicons_note = ""
                            self.log.emit(
                                f"  Wrote places.sqlite into {hdw.target_path}; "
                                f"{places_note}.{favicons_note}"
                            )
                            if hdw.written.downloads_annotated:
                                self.log.emit(
                                    f"  Annotated {hdw.written.downloads_annotated} "
                                    "download(s) in places.sqlite."
                                )

            if req.do_autofill:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Exporting form autofill...")
                autofill_result = migrate_autofill(req.source, out_dir, dry_run=req.dry_run)
                if not req.dry_run:
                    exports["autofill"] = autofill_result.sqlite_path
                counts["autofill"] = autofill_result.written
                self.log.emit(
                    f"  {autofill_result.written} field/value pairs written, "
                    f"{autofill_result.skipped} skipped, "
                    f"{len(autofill_result.failures)} failed."
                )

            if req.do_cards:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Exporting saved cards (CSV — Firefox has no native store)...")
                try:
                    cards_result = migrate_cards(req.source, out_dir, dry_run=req.dry_run)
                except DecryptionError as exc:
                    self.log.emit(f"  Card decryption failed: {exc}")
                else:
                    if not req.dry_run and cards_result.decrypted > 0:
                        exports["cards"] = cards_result.csv_path
                    counts["cards"] = cards_result.decrypted
                    self.log.emit(
                        f"  {cards_result.decrypted} cards decrypted, "
                        f"{cards_result.failed} failed of {cards_result.total} total."
                    )

            if req.do_search_engines:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Exporting search engines...")
                se_result = migrate_search_engines(req.source, out_dir, dry_run=req.dry_run)
                if not req.dry_run:
                    exports["search_engines"] = se_result.json_path
                counts["search_engines"] = se_result.total
                self.log.emit(
                    f"  {se_result.written} OpenSearch XML files written, "
                    f"{se_result.total} total entries."
                )

            if req.do_downloads:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Exporting downloads...")
                dl_result = migrate_downloads(req.source, out_dir, dry_run=req.dry_run)
                if not req.dry_run and dl_result.written > 0:
                    exports["downloads"] = dl_result.csv_path
                counts["downloads"] = dl_result.written
                self.log.emit(
                    f"  {dl_result.written} download(s) written of "
                    f"{dl_result.total} total."
                )

            if req.do_open_tabs:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Reconstructing open tabs from Chromium session...")
                ot_result = migrate_open_tabs(req.source, out_dir, dry_run=req.dry_run)
                counts["open_tabs"] = ot_result.tabs
                self.log.emit(
                    f"  {ot_result.tabs} tab URL(s) recovered "
                    f"({len(ot_result.failures)} failure(s))."
                )
                if not req.dry_run and ot_result.tabs > 0:
                    exports["open_tabs"] = ot_result.out_path
                if req.direct_write_open_tabs and req.target and not req.dry_run and ot_result.tabs > 0:
                    policy = req.policy_open_tabs
                    if policy != "skip":
                        try:
                            from foxport.migrate.conflicts import analyze_open_tabs
                            ot_conflicts = analyze_open_tabs(req.source, req.target)
                            self.log.emit(
                                f"  Pre-flight: {ot_conflicts.source_total} source tabs will "
                                f"REPLACE {ot_conflicts.duplicates} existing session tab(s)."
                            )
                        except Exception as exc:  # noqa: BLE001
                            self.log.emit(f"  Pre-flight skipped: {exc}")
                    if policy == "skip":
                        self.log.emit(
                            "  Direct-write policy = SKIP — target recovery.jsonlz4 "
                            "untouched; staging file still produced."
                        )
                    elif policy == "backup-only":
                        try:
                            from foxport.fileops import timestamped_backup_path
                            import shutil as _shutil
                            target_recovery = (
                                req.target.profile_dir / "sessionstore-backups" / "recovery.jsonlz4"
                            )
                            backup = timestamped_backup_path(target_recovery)
                            if backup is not None:
                                _shutil.copy2(target_recovery, backup)
                                direct_write_backups["open_tabs"] = backup
                                self.log.emit(
                                    f"  Direct-write policy = BACKUP-ONLY — copied "
                                    f"recovery.jsonlz4 to {backup.name}; not replacing."
                                )
                            else:
                                self.log.emit(
                                    "  Direct-write policy = BACKUP-ONLY — target had "
                                    "no recovery.jsonlz4 to back up."
                                )
                        except Exception as exc:  # noqa: BLE001
                            self.log.emit(f"  Backup-only failed: {exc}")
                    else:
                        try:
                            ot_install = write_session_into_target(
                                req.source, req.target, out_dir,
                            )
                        except ProfileLockedError as exc:
                            self.log.emit(f"  Open-tabs direct-write aborted: {exc}")
                        else:
                            direct_write_backups["open_tabs"] = ot_install.backup_path
                            if ot_install.backup_path is not None:
                                self.log.emit(
                                    f"  Wrote recovery.jsonlz4 to {ot_install.target_path}; "
                                    f"previous backed up as {ot_install.backup_path.name}"
                                )
                            else:
                                self.log.emit(
                                    f"  Wrote recovery.jsonlz4 to {ot_install.target_path} "
                                    "(no previous file to back up)"
                                )

            telemetry_status = _record_migration_telemetry(
                req=req,
                counts=counts,
                outcome="dry_run" if req.dry_run else "completed",
                surface="gui",
            )
            if req.telemetry_opt_in:
                self.log.emit(_telemetry_log_line(telemetry_status))

            if not req.dry_run:
                instructions_path = out_dir / "README.txt"
                instructions_path.write_text(
                    import_instructions(req.target, exports), encoding="utf-8"
                )
                self.log.emit(f"Instructions written to {instructions_path.name}")
                manifest_path = _write_run_manifest(
                    out_dir=out_dir,
                    req=req,
                    exports=exports,
                    direct_write_backups=direct_write_backups,
                    counts=counts,
                    hibp_status=hibp_status,
                    telemetry_status=telemetry_status,
                )
                self.log.emit(f"Manifest written to {manifest_path.name}")
            else:
                self.log.emit("Dry-run complete. No files were written.")
            # Surface backup paths to the Done screen. Empty string for keys
            # whose direct-write either didn't run or had no previous file
            # to back up, so the receiver can distinguish "no backup" from
            # "category absent" by key membership.
            self.directWriteBackups.emit({
                k: (str(v) if v is not None else "")
                for k, v in direct_write_backups.items()
            })
            self.finished.emit(True, str(out_dir), {k: str(v) for k, v in exports.items()})

        except Exception as exc:
            telemetry_status = _record_migration_telemetry(
                req=req,
                counts=counts,
                outcome="failed",
                surface="gui",
            )
            if req.telemetry_opt_in:
                self.log.emit(_telemetry_log_line(telemetry_status))
            self.log.emit(f"FATAL: {exc}")
            self.finished.emit(False, str(exc), {})


    def _run_reverse(self) -> None:
        req = self._req
        steps = sum([req.do_passwords, req.do_bookmarks, req.do_extensions]) or 1
        target_label = (req.target.label if req.target else "chrome") + (
            "_dryrun" if req.dry_run else ""
        )
        out_dir = make_export_dir(req.out_root, f"{req.source.label}_reverse", target_label)
        self.log.emit(f"Output: {out_dir}")
        if req.dry_run:
            self.log.emit("DRY RUN — counts only; no files will be written.")
        current = 0
        exports: dict[str, str] = {}
        counts: dict[str, int] = {}
        try:
            if req.do_passwords:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Decrypting Firefox logins via NSS...")
                r = migrate_passwords_reverse(
                    req.source, out_dir,
                    master_password=req.master_password, dry_run=req.dry_run,
                )
                self.log.emit(
                    f"  {r.written} written, {len(r.failures)} failed of {r.total} total."
                )
                counts["passwords"] = r.written
                if not req.dry_run and r.written:
                    exports["passwords"] = str(r.csv_path)
            if req.do_bookmarks:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Converting Firefox bookmarks to Chrome HTML...")
                r = migrate_bookmarks_reverse(req.source, out_dir, dry_run=req.dry_run)
                self.log.emit(f"  {r.urls} URLs across {r.folders} folders.")
                counts["bookmarks"] = r.urls
                if not req.dry_run:
                    exports["bookmarks"] = str(r.html_path)
            if req.do_extensions:
                current += 1
                self.step.emit(current, steps)
                self.log.emit("Mapping Firefox extensions to Chrome Web Store...")
                r = migrate_extensions_reverse(req.source, out_dir, dry_run=req.dry_run)
                self.log.emit(
                    f"  {r.matched} matched, {r.unmatched} unmatched of {len(r.matches)} installed."
                )
                counts["extensions"] = len(r.matches)
                if not req.dry_run:
                    exports["extensions"] = str(r.html_path)
            telemetry_status = _record_migration_telemetry(
                req=req,
                counts=counts,
                outcome="dry_run" if req.dry_run else "completed",
                surface="gui",
            )
            if req.telemetry_opt_in:
                self.log.emit(_telemetry_log_line(telemetry_status))

            if exports and not req.dry_run:
                instructions_path = out_dir / "README.txt"
                instructions_path.write_text(
                    import_instructions(req.target, exports), encoding="utf-8"
                )
                self.log.emit(f"Instructions: {instructions_path}")
                # Reverse path uses str-keyed exports; pass them through
                # build_artifact via the same writer for consistency.
                _write_run_manifest(
                    out_dir=out_dir,
                    req=req,
                    exports={k: Path(v) for k, v in exports.items()},
                    direct_write_backups={},
                    counts=counts,
                    telemetry_status=telemetry_status,
                )
            self.finished.emit(True, str(out_dir), exports)
        except Exception as exc:  # noqa: BLE001
            telemetry_status = _record_migration_telemetry(
                req=req,
                counts=counts,
                outcome="failed",
                surface="gui",
            )
            if req.telemetry_opt_in:
                self.log.emit(_telemetry_log_line(telemetry_status))
            self.log.emit(f"FATAL: {exc}")
            self.finished.emit(False, str(exc), {})


def _selected_items(req: MigrationRequest) -> list[str]:
    """Return the artifact slugs selected by the user, in canonical order."""

    candidates = [
        ("passwords", req.do_passwords),
        ("bookmarks", req.do_bookmarks),
        ("extensions", req.do_extensions),
        ("extension_settings", req.do_extensions and bool(req.extension_settings_allowlist)),
        ("cookies", req.do_cookies),
        ("history", req.do_history),
        ("autofill", req.do_autofill),
        ("cards", req.do_cards),
        ("search_engines", req.do_search_engines),
        ("open_tabs", req.do_open_tabs),
        ("downloads", req.do_downloads),
    ]
    return [key for key, enabled in candidates if enabled]


def _write_run_manifest(
    *,
    out_dir: Path,
    req: MigrationRequest,
    exports: dict[str, Path],
    direct_write_backups: dict[str, Path | None],
    counts: dict[str, int],
    hibp_status: str = "",
    telemetry_status: str = "disabled",
) -> Path:
    """Hash every emitted file and write the run manifest next to README.txt.

    Direct-write target paths live outside ``out_dir`` (they're inside the
    target Firefox profile), so we don't relativize them — they're recorded
    as absolute backup_path strings so a user can locate the rollback
    point from a copy of the manifest alone.
    """

    target_label = req.target.label if req.target else ""
    direct_write_keys = set()
    # Per-category policy lookup matches what the worker actually
    # applied; empty string for categories that didn't go through the
    # direct-write path so the manifest stays accurate.
    direct_write_policy: dict[str, str] = {}
    if req.direct_write_passwords:
        direct_write_keys.add("passwords")
        direct_write_policy["passwords"] = req.policy_passwords
    if req.direct_write_cookies:
        direct_write_keys.add("cookies")
        direct_write_policy["cookies"] = req.policy_cookies
    if req.direct_write_history:
        direct_write_keys.add("history")
        direct_write_policy["history"] = req.policy_history
    if req.direct_write_open_tabs:
        direct_write_keys.add("open_tabs")
        direct_write_policy["open_tabs"] = req.policy_open_tabs

    artifacts = []
    for key, path in exports.items():
        try:
            artifact = build_artifact(
                key,
                Path(path),
                out_dir,
                count=counts.get(key),
                direct_write=key in direct_write_keys,
                backup_path=direct_write_backups.get(key),
                direct_write_policy=direct_write_policy.get(key, ""),
            )
        except (OSError, ValueError):
            # File missing or outside out_dir; skip rather than fail the
            # whole run. The README.txt still references it for the user.
            continue
        artifacts.append(artifact)

    network = {
        "addons.mozilla.org": "enabled" if req.extensions_online and req.do_extensions else "disabled",
        # api.pwnedpasswords.com carries the tri-state outcome
        # (checked-clean / checked-hits / network-error) when the user
        # opted in. The worker passes the live status via the
        # ``hibp_status`` parameter; absent => "disabled".
        "api.pwnedpasswords.com": hibp_status or (
            "enabled" if req.hibp_scan and req.do_passwords else "disabled"
        ),
        TELEMETRY_HOST: telemetry_status,
        crash_reporting_network_host(): current_crash_reporting_status(
            req.crash_reporting_opt_in
        ),
    }

    manifest = RunManifest(
        created_iso=now_iso(),
        source_label=req.source.label if req.source else "",
        target_label=target_label,
        direction=req.direction,
        dry_run=req.dry_run,
        items_requested=_selected_items(req),
        network=network,
        artifacts=artifacts,
    )
    return write_manifest(
        manifest, out_dir,
        privacy_redact=req.privacy_redact_manifest,
    )


def _record_migration_telemetry(
    *,
    req: MigrationRequest,
    counts: dict[str, int],
    outcome: str,
    surface: str,
) -> str:
    result = record_migration(
        MigrationTelemetryPayload(
            direction=req.direction,
            surface=surface,
            outcome=outcome,
            dry_run=req.dry_run,
            direct_write=(
                req.direct_write_passwords
                or req.direct_write_cookies
                or req.direct_write_history
                or req.direct_write_open_tabs
            ),
            items=_selected_items(req),
            counts=counts,
        ),
        enabled=req.telemetry_opt_in,
    )
    return result.status


def _telemetry_log_line(status: str) -> str:
    if status == "submitted":
        return "Telemetry: submitted aggregate migration metrics."
    if status == "unavailable":
        return "Telemetry: Glean SDK unavailable; migration metrics were not sent."
    if status == "failed":
        return "Telemetry: failed to submit migration metrics."
    return "Telemetry: disabled."


def make_thread(worker: QObject) -> QThread:
    """Move ``worker`` onto a new QThread and wire teardown."""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)  # type: ignore[attr-defined]
    return thread
