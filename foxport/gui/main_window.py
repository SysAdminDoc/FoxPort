"""Main window — a five-step wizard for one source-to-target migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from foxport import __app_name__, __version__
from foxport.browsers.detect import ChromiumProfile, FirefoxProfile
from foxport.config import Settings, load_settings
from foxport.gui.pages import (
    ItemsPage,
    MigrationContext,
    PreviewPage,
    RunPage,
    SourcePage,
    TargetPage,
)
from foxport.gui.theme import STYLESHEET, apply_palette
from foxport.gui.widgets import FooterBar, StepRail
from foxport.gui.workers import (
    DetectWorker,
    MigrationRequest,
    MigrationWorker,
    make_thread,
)


STEP_NAMES = ["Source", "Target", "Items", "Preview", "Run"]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.resize(1040, 720)
        self.setMinimumSize(900, 620)

        self._settings: Settings = load_settings()
        self._ctx = MigrationContext()
        self._apply_settings_defaults()
        self._detect_thread: QThread | None = None
        self._detect_worker: DetectWorker | None = None
        self._migrate_thread: QThread | None = None
        self._migrate_worker: MigrationWorker | None = None
        self._migration_done = False
        # True once a migration has been kicked off. Used by ``_refresh_footer``
        # to distinguish "never started" from "started, failed" — the latter
        # turns the footer button into "Try Again".
        self._migration_attempted = False

        self._build_ui()
        self._build_menu()
        self._start_detection()
        # First-run trust + network disclosure. Runs on a 0-ms timer so the
        # main window paints first and the modal lands on top instead of
        # racing the Qt event loop. Users who already acked the *current*
        # trust revision skip the dialog; bumping ``_TRUST_REVISION`` in
        # foxport.config re-prompts a user whose ack predates the change.
        from foxport.config import _TRUST_REVISION
        already_acked = (
            bool(self._settings.first_run_acked_iso)
            and self._settings.first_run_acked_trust_revision >= _TRUST_REVISION
        )
        if not already_acked:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._show_first_run_dialog)

    # --------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Top: step rail | stacked pages
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        self._rail = StepRail(STEP_NAMES)
        self._stack = QStackedWidget()

        self._source_page = SourcePage(self._ctx)
        self._target_page = TargetPage(self._ctx)
        self._items_page = ItemsPage(self._ctx)
        self._preview_page = PreviewPage(self._ctx)
        self._run_page = RunPage(self._ctx)

        for page in (self._source_page, self._target_page, self._items_page,
                     self._preview_page, self._run_page):
            self._stack.addWidget(page)
            page.canAdvanceChanged.connect(self._refresh_footer)
        # When the user flips Source → Target direction, the target tiles need
        # to re-render against the swapped profile list.
        self._source_page.directionChanged.connect(self._target_page._render_for_direction)
        # Settings defaults already populated ctx; push them into the widgets
        # so the user sees them on first wizard view.
        self._items_page.apply_context_defaults()

        top_layout.addWidget(self._rail)
        top_layout.addWidget(self._stack, 1)
        outer.addWidget(top, 1)

        self._footer = FooterBar()
        self._footer.backClicked.connect(self._on_back)
        self._footer.nextClicked.connect(self._on_next)
        outer.addWidget(self._footer)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Scanning for installed browsers...")
        self._show_step(0)

        # Done-page action wiring. RunPage emits (key, action_kind) and we
        # resolve the path from the most recent exports map. Decoupling the
        # button widget from the file routing keeps RunPage free of any
        # filesystem / process-launch logic (testable headless) and lets us
        # add new artifact keys without touching MainWindow.
        self._last_out_dir: str = ""
        self._last_exports: dict[str, str] = {}
        self._last_direct_write_backups: dict[str, str] = {}
        self._run_page.artifactActionRequested.connect(self._on_artifact_action)

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        rescan = QAction("Rescan browsers", self)
        rescan.triggered.connect(self._start_detection)
        file_menu.addAction(rescan)
        open_out = QAction("Open output folder", self)
        open_out.triggered.connect(self._open_output_root)
        file_menu.addAction(open_out)
        file_menu.addSeparator()
        # Snapshot/restore — File menu hosts the global Restore entry. The
        # Done screen exposes Create Snapshot from the current run.
        restore_act = QAction("Restore snapshot…", self)
        restore_act.triggered.connect(self._restore_snapshot)
        file_menu.addAction(restore_act)
        # Restore-from-backup — the "regret undo" surface for a direct-
        # write run. Picks a *.foxport-backup-<mtime>.* file and copies
        # it back over its original target.
        restore_backup_act = QAction("Restore direct-write backup…", self)
        restore_backup_act.triggered.connect(self._restore_direct_write_backup)
        file_menu.addAction(restore_backup_act)
        file_menu.addSeparator()
        settings = QAction("Settings…", self)
        settings.triggered.connect(self._open_settings)
        file_menu.addAction(settings)
        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        help_menu = menu.addMenu("&Help")
        # "View change log" — opens the repo CHANGELOG.md so the user can
        # see what's new since their last run without leaving the app.
        # We resolve the path from the foxport package so a PyInstaller
        # bundle finds it inside the unpacked _MEIPASS dir.
        changelog_act = QAction("View change log", self)
        changelog_act.triggered.connect(self._open_changelog)
        help_menu.addAction(changelog_act)
        report_act = QAction("Report a problem (GitHub)", self)
        report_act.triggered.connect(self._open_issue_tracker)
        help_menu.addAction(report_act)
        help_menu.addSeparator()
        about = QAction("About FoxPort", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    def _apply_settings_defaults(self) -> None:
        """Pre-populate MigrationContext from persisted settings."""
        s = self._settings
        if s.output_dir:
            self._ctx.out_root = Path(s.output_dir)
        self._ctx.extensions_online = s.allow_online_amo_lookup
        self._ctx.dry_run = s.default_dry_run
        self._ctx.hibp_scan = s.hibp_scan_default
        self._ctx.mask_passwords_in_preview = s.mask_passwords_in_preview

    def _show_first_run_dialog(self) -> None:
        """Show the trust + network disclosure dialog on first launch.

        The dialog saves the user's AMO + HIBP defaults plus the
        first_run_acked_iso timestamp so subsequent launches skip it.
        We refresh the local Settings + context immediately so the very
        next click on Items already reflects the chosen defaults.
        """

        from foxport.gui.dialogs import FirstRunDialog
        dialog = FirstRunDialog(self._settings, parent=self)
        dialog.exec()
        self._settings = dialog.settings()
        self._apply_settings_defaults()
        self._items_page.apply_context_defaults()

    def _open_settings(self) -> None:
        from foxport.gui.dialogs import SettingsDialog
        dlg = SettingsDialog(self._settings, parent=self)
        if dlg.exec():
            self._settings = dlg.settings()
            self._apply_settings_defaults()
            # Push new defaults into the Items page widgets.
            self._items_page.apply_context_defaults()

    # --------------------------------------------------------------- Step nav

    def _show_step(self, index: int) -> None:
        # Leaving hook for the previous page.
        prior = self._stack.currentWidget()
        if hasattr(prior, "on_leave"):
            prior.on_leave()
        self._stack.setCurrentIndex(index)
        self._rail.set_current(index)
        page = self._stack.currentWidget()
        if hasattr(page, "on_enter"):
            page.on_enter()
        self._refresh_footer()

    def _refresh_footer(self) -> None:
        idx = self._stack.currentIndex()
        page = self._stack.currentWidget()
        running = self._migrate_thread is not None and self._migrate_thread.isRunning()
        on_run_step = idx == len(STEP_NAMES) - 1
        failed = on_run_step and not running and not self._migration_done and self._migration_attempted
        # Back is allowed everywhere except a finished run (where the user
        # should click Close instead) and while a migration is actively
        # running (the in-flight thread mustn't be orphaned).
        self._footer.set_can_back(
            idx > 0 and not (on_run_step and (self._migration_done or running))
        )
        if on_run_step:
            if self._migration_done:
                self._footer.set_next_label("Close")
                self._footer.set_can_advance(True)
            elif failed:
                # Pre-v1.3.2 this still said "Run Migration" but clicking did
                # nothing — user could only retry via Back. Now the click
                # restarts the migration from this step so the label keeps
                # its promise.
                self._footer.set_next_label("Try Again")
                self._footer.set_can_advance(not running)
            else:
                # Either running or never attempted (rare; can_advance gates).
                self._footer.set_next_label("Run Migration")
                self._footer.set_can_advance(
                    (page.can_advance() if hasattr(page, "can_advance") else True)
                    and not running
                )
        elif idx == len(STEP_NAMES) - 2:
            self._footer.set_next_label("Run Migration")
            self._footer.set_can_advance(page.can_advance() if hasattr(page, "can_advance") else True)
        else:
            self._footer.set_next_label("Next")
            self._footer.set_can_advance(page.can_advance() if hasattr(page, "can_advance") else True)

    def _on_back(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._show_step(idx - 1)

    def _on_next(self) -> None:
        idx = self._stack.currentIndex()
        # Run step: clicking "Run Migration" / "Try Again" / "Close"
        if idx == len(STEP_NAMES) - 1:
            if self._migration_done:
                self.close()
                return
            running = self._migrate_thread is not None and self._migrate_thread.isRunning()
            if not running and self._migration_attempted:
                # Failed → retry. Reset the run page so the previous log /
                # action buttons / banner don't bleed into the new run.
                self._run_page.reset()
                self._migration_attempted = False
                self._start_migration()
            return
        if idx == len(STEP_NAMES) - 2:
            # Preview step → show the conflict-review modal first when
            # any direct-write category is on (the v1.3.3 P1
            # deliverable). Cancelling the modal keeps the user on
            # Preview; accepting advances into Run and starts the
            # migration with the chosen per-category policies.
            if not self._maybe_show_direct_write_policy_dialog():
                return
            self._show_step(idx + 1)
            self._start_migration()
            return
        # Going from Items (index 2) to Preview — populate counts on enter.
        self._show_step(idx + 1)

    def _maybe_show_direct_write_policy_dialog(self) -> bool:
        """Open the conflict-review modal when at least one direct-write
        category is enabled and the run is destructive.

        Returns ``True`` when the user proceeded (no dialog needed, OR
        accepted), ``False`` when they cancelled. The dialog writes its
        chosen policies onto ``self._ctx`` so ``_start_migration``
        picks them up via the existing ``MigrationRequest`` plumbing.

        Skipped for: dry-run mode, reverse direction (no direct-write
        target), no direct-write categories enabled.
        """

        ctx = self._ctx
        if ctx.dry_run:
            return True
        if ctx.direction != "forward":
            return True
        if ctx.target is None:
            return True
        if not any((
            ctx.direct_write_passwords,
            ctx.direct_write_cookies,
            ctx.direct_write_history,
            ctx.direct_write_open_tabs,
        )):
            return True
        from foxport.gui.dialogs import DirectWritePolicyDialog
        dialog = DirectWritePolicyDialog(ctx, parent=self)
        return bool(dialog.exec())

    # --------------------------------------------------------------- Detection

    def _start_detection(self) -> None:
        if self._detect_thread is not None:
            return
        self.statusBar().showMessage("Detecting installed browsers...")
        worker = DetectWorker()
        thread = make_thread(worker)
        worker.log.connect(lambda line: self.statusBar().showMessage(line, 4000))
        worker.finished.connect(self._on_detected)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_detect_refs)
        self._detect_worker = worker
        self._detect_thread = thread
        thread.start()

    def _clear_detect_refs(self) -> None:
        self._detect_thread = None
        self._detect_worker = None

    def _on_detected(self, chromium: list, firefox: list) -> None:
        self._ctx.chromium_profiles = list(chromium)
        self._ctx.firefox_profiles = list(firefox)
        self._source_page.populate(chromium, firefox)
        self._target_page.populate()
        self.statusBar().showMessage(
            f"Detected {len(chromium)} Chromium profile(s), {len(firefox)} Firefox profile(s)."
        )
        self._refresh_footer()

    # --------------------------------------------------------------- Migration

    def _start_migration(self) -> None:
        if not self._ctx.source:
            QMessageBox.warning(self, "FoxPort", "No source selected.")
            self._show_step(0)
            return
        if self._migrate_thread is not None:
            return
        # Reverse mode: source is a Firefox profile — prompt for master password
        # if NSS will need one. We probe by attempting a no-op NSS open and
        # allow up to 3 retries on wrong passwords (mistypes are common).
        if self._ctx.direction == "reverse":
            from foxport.crypto.nss import open_session, NSSError
            from foxport.gui.dialogs import prompt_master_password
            for attempt in range(3):
                try:
                    sess = open_session(self._ctx.source, master_password=self._ctx.master_password)
                    sess.close()
                    break
                except NSSError as exc:
                    if "master password" not in str(exc).lower():
                        raise
                    suffix = "" if attempt == 0 else f" (attempt {attempt + 1} of 3)"
                    pw = prompt_master_password(self, self._ctx.source.label + suffix)
                    if pw is None:
                        QMessageBox.information(
                            self, "FoxPort",
                            "Migration cancelled — master password required.",
                        )
                        return
                    self._ctx.master_password = pw
            else:
                QMessageBox.critical(
                    self, "FoxPort",
                    "Master password rejected 3 times — migration cancelled.",
                )
                return
        # Push counts into Items page so the user sees them on back-nav too.
        # PreviewPage filled ctx.counts on the way in; this just forwards.
        self._items_page.set_counts(dict(self._ctx.counts))
        request = MigrationRequest(
            source=self._ctx.source,
            target=self._ctx.target,
            out_root=self._ctx.out_root,
            do_passwords=self._ctx.do_passwords,
            do_bookmarks=self._ctx.do_bookmarks,
            do_extensions=self._ctx.do_extensions,
            do_cookies=self._ctx.do_cookies,
            do_history=self._ctx.do_history,
            do_autofill=self._ctx.do_autofill,
            do_cards=self._ctx.do_cards,
            do_search_engines=self._ctx.do_search_engines,
            do_open_tabs=self._ctx.do_open_tabs,
            do_downloads=self._ctx.do_downloads,
            extensions_online=self._ctx.extensions_online,
            dry_run=self._ctx.dry_run,
            password_include_keys=self._ctx.password_include_keys,
            bookmark_excluded_paths=set(self._ctx.bookmark_excluded_paths),
            history_date_from_us=self._ctx.history_date_from_us,
            history_date_to_us=self._ctx.history_date_to_us,
            direct_write_passwords=self._ctx.direct_write_passwords,
            direct_write_cookies=self._ctx.direct_write_cookies,
            direct_write_history=self._ctx.direct_write_history,
            direct_write_open_tabs=self._ctx.direct_write_open_tabs,
            policy_passwords=self._ctx.policy_passwords,
            policy_cookies=self._ctx.policy_cookies,
            policy_history=self._ctx.policy_history,
            policy_open_tabs=self._ctx.policy_open_tabs,
            hibp_scan=self._ctx.hibp_scan,
            direction=self._ctx.direction,
            master_password=self._ctx.master_password,
            privacy_redact_manifest=self._settings.privacy_redact_manifest,
        )
        self._run_page.reset()
        self._run_page.set_busy()
        # ``_migration_attempted`` flips to True the moment the worker
        # thread starts — used by the footer state-machine to render
        # "Try Again" if the run later fails.
        self._migration_attempted = True
        self._migration_done = False
        self.statusBar().showMessage("Migration running...")
        worker = MigrationWorker(request)
        thread = make_thread(worker)
        worker.log.connect(self._run_page.append_log)
        worker.step.connect(self._run_page.set_step)
        # directWriteBackups fires BEFORE finished, so set_direct_write_backups
        # runs first and set_done() sees the backups dict when it builds the
        # Done action bar.
        worker.directWriteBackups.connect(self._on_direct_write_backups)
        worker.finished.connect(self._on_migration_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_migrate_refs)
        self._migrate_worker = worker
        self._migrate_thread = thread
        thread.start()

    def _clear_migrate_refs(self) -> None:
        self._migrate_thread = None
        self._migrate_worker = None

    def closeEvent(self, event) -> None:
        """Don't tear down the window mid-migration — direct-write paths can
        leave a half-imported logins.json / places.sqlite if killed between
        the backup and the atomic replace. Block the close until the user
        confirms abort; if confirmed, give the worker thread a bounded
        window to wind down cleanly.
        """
        if self._migrate_thread is not None and self._migrate_thread.isRunning():
            answer = QMessageBox.question(
                self,
                "FoxPort",
                "A migration is still running. Closing now may leave the target "
                "profile in a partial state. Quit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # Migration worker doesn't expose a cooperative cancel today; the
            # most we can do is wait briefly for the in-flight step to finish
            # before letting Qt destroy the thread.
            self._migrate_thread.quit()
            self._migrate_thread.wait(3000)
        if self._detect_thread is not None and self._detect_thread.isRunning():
            self._detect_thread.quit()
            self._detect_thread.wait(2000)
        super().closeEvent(event)

    def _on_direct_write_backups(self, backups: dict) -> None:
        """Record direct-write backup paths + forward them to the Run page.

        Stashed on the window so ``_on_artifact_action`` can resolve a
        Reveal-backup click later; forwarded to the Run page so
        ``set_done`` renders the Reveal buttons next to their categories.
        """

        self._last_direct_write_backups = {k: v for k, v in backups.items() if v}
        self._run_page.set_direct_write_backups(self._last_direct_write_backups)

    def _on_migration_finished(self, ok: bool, payload: str, exports: dict) -> None:
        self._migration_done = ok
        if ok:
            self._last_out_dir = payload
            self._last_exports = dict(exports)
            self._run_page.set_done(True, payload, {k: Path(v) for k, v in exports.items()})
            self.statusBar().showMessage(f"Done. Output: {payload}")
        else:
            self._run_page.set_done(False, payload, {})
            self.statusBar().showMessage("Migration failed.")
        self._refresh_footer()

    # --------------------------------------------------------------- Helpers

    def _open_output_root(self) -> None:
        self._ctx.out_root.mkdir(parents=True, exist_ok=True)
        self._open_path(self._ctx.out_root)

    def _on_artifact_action(self, key: str, action_kind: str) -> None:
        """Resolve a Done-screen button click to a filesystem action.

        ``key == RunPage.OUTPUT_FOLDER_KEY`` opens the most recent run's
        output directory. ``key == RunPage.CREATE_SNAPSHOT_KEY`` launches
        the snapshot save flow. Any other key looks up the path from
        ``self._last_exports`` and either launches it (``open``) or reveals
        it in the OS file manager (``reveal``). Silent no-op for unknown
        keys — the worker's exports map is the single source of truth.
        """
        from foxport.gui.pages import RunPage
        if key == RunPage.OUTPUT_FOLDER_KEY:
            if self._last_out_dir:
                self._open_path(Path(self._last_out_dir))
            return
        if key == RunPage.CREATE_SNAPSHOT_KEY:
            self._create_snapshot_from_last_run()
            return
        if action_kind == RunPage.BACKUP_ACTION:
            backup_path = self._last_direct_write_backups.get(key, "")
            if backup_path:
                self._reveal_path(backup_path)
            return
        raw_path = self._last_exports.get(key, "")
        if not raw_path:
            return
        if action_kind == "reveal":
            self._reveal_path(raw_path)
        else:
            self._open_path(Path(raw_path))

    def _open_path(self, path: Path) -> None:
        if not path or str(path) == "":
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            QMessageBox.warning(self, "FoxPort", f"Could not open {path}:\n{exc}")

    def _reveal_path(self, raw_path: str) -> None:
        """Open Explorer/Finder with the file selected, instead of launching it."""
        if not raw_path:
            return
        path = Path(raw_path)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                # Most Linux file managers don't have a select primitive; open parent.
                subprocess.Popen(["xdg-open", str(path.parent)])
        except OSError as exc:
            QMessageBox.warning(self, "FoxPort", f"Could not reveal {path}:\n{exc}")

    def _restore_direct_write_backup(self) -> None:
        """Regret-undo a direct-write run via the File menu.

        Picks a ``*.foxport-backup-<mtime>.*`` file from the user's
        filesystem, resolves the original target name via
        :func:`foxport.fileops.original_from_backup`, asks for
        confirmation (showing exactly which file will be overwritten),
        then performs the atomic-replace.

        Falls open with a per-failure-mode message when the backup is
        missing, doesn't match the naming convention, or can't be
        written over.
        """

        from foxport.fileops import original_from_backup, restore_from_backup

        # Default the picker to the user's Firefox install path if we
        # can guess one — otherwise to the standard output folder.
        # Either way the user can navigate from there.
        start_dir = str(self._ctx.out_root)
        backup_str, _ = QFileDialog.getOpenFileName(
            self,
            "Pick a *.foxport-backup-* file to restore",
            start_dir,
            "FoxPort direct-write backups (*.foxport-backup-*);;All files (*)",
        )
        if not backup_str:
            return
        backup = Path(backup_str)
        resolved = original_from_backup(backup)
        if resolved is None:
            QMessageBox.warning(
                self,
                "FoxPort",
                f"{backup.name} doesn't match the FoxPort backup naming "
                "convention (expected ``<name>.foxport-backup-<mtime>.<ext>``). "
                "If this really is a FoxPort backup, restore it manually "
                "by copying it over the live file.",
            )
            return
        answer = QMessageBox.question(
            self,
            "FoxPort",
            f"Restore {backup.name}\n\nover\n\n{resolved}?\n\n"
            "This overwrites the current file. The backup itself is left "
            "in place so you can re-undo if needed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = restore_from_backup(backup)
        except (FileNotFoundError, ValueError, OSError) as exc:
            QMessageBox.critical(self, "FoxPort", f"Restore failed: {exc}")
            return
        QMessageBox.information(
            self, "FoxPort",
            f"Restored {backup.name} -> {restored}.",
        )

    def _restore_snapshot(self) -> None:
        """Pick a .fxport bundle, prompt for the passphrase (encrypted
        bundles only), open the inspect dialog."""

        from foxport.gui.dialogs import (
            RestoreInspectDialog,
            prompt_snapshot_passphrase,
        )
        bundle, _ = QFileDialog.getOpenFileName(
            self,
            "Pick a .fxport snapshot to restore",
            str(self._ctx.out_root),
            "FoxPort snapshot (*.fxport);;All files (*)",
        )
        if not bundle:
            return
        bundle_path = Path(bundle)
        # Peek at the magic bytes to decide whether to prompt for a
        # passphrase. We don't actually decrypt here; the inspect dialog
        # owns the full open path.
        from foxport.snapshot import _MAGIC_ENCRYPTED
        try:
            head = bundle_path.read_bytes()[: len(_MAGIC_ENCRYPTED)]
        except OSError as exc:
            QMessageBox.critical(self, "FoxPort", f"Could not read {bundle_path}: {exc}")
            return
        passphrase = ""
        if head == _MAGIC_ENCRYPTED:
            passphrase_value = prompt_snapshot_passphrase(self, mode="restore")
            if passphrase_value is None:
                return
            passphrase = passphrase_value
        dialog = RestoreInspectDialog(bundle_path, passphrase=passphrase, parent=self)
        dialog.exec()

    def _create_snapshot_from_last_run(self) -> None:
        """Bundle the most recent run's output folder into a .fxport file.

        Run page wires this to the Done screen action. Empty exports or a
        missing output dir surface a short notice instead of crashing.
        """

        if not self._last_out_dir:
            QMessageBox.information(
                self, "FoxPort",
                "No completed migration to snapshot. Run a migration first.",
            )
            return
        in_dir = Path(self._last_out_dir)
        if not in_dir.is_dir():
            QMessageBox.warning(self, "FoxPort", f"Output folder {in_dir} is gone.")
            return
        default_name = f"{in_dir.name}.fxport"
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Save .fxport snapshot",
            str(in_dir.parent / default_name),
            "FoxPort snapshot (*.fxport);;All files (*)",
        )
        if not chosen:
            return
        out_path = Path(chosen)
        from foxport.gui.dialogs import prompt_snapshot_passphrase
        passphrase = prompt_snapshot_passphrase(self, mode="create")
        if passphrase is None:
            return
        from foxport.snapshot import create_snapshot
        try:
            manifest = create_snapshot(
                in_dir, out_path,
                source_label=self._ctx.source.label if self._ctx.source else "(unknown)",
                target_label=self._ctx.target.label if self._ctx.target else "(unknown)",
                passphrase=passphrase or None,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "FoxPort", f"Snapshot failed: {exc}")
            return
        QMessageBox.information(
            self, "FoxPort",
            f"Wrote {len(manifest.files)} file(s) into {out_path}.\n"
            f"Encrypted: {manifest.encrypted}",
        )

    def _open_changelog(self) -> None:
        """Open CHANGELOG.md in the registered OS handler.

        Tries the development repo location first (one level up from the
        installed package), then falls back to the bundled CHANGELOG that
        PyInstaller drops alongside the executable. Falls open with a
        QMessageBox if neither is reachable.
        """

        from foxport import __file__ as _foxport_init

        package_dir = Path(_foxport_init).resolve().parent
        candidates = [
            package_dir.parent / "CHANGELOG.md",
            package_dir / "CHANGELOG.md",
            Path(getattr(sys, "_MEIPASS", "")) / "CHANGELOG.md" if hasattr(sys, "_MEIPASS") else Path(),
        ]
        for path in candidates:
            if path and path.is_file():
                self._open_path(path)
                return
        QMessageBox.information(
            self, "FoxPort",
            "Could not locate CHANGELOG.md alongside this install.\n"
            "See https://github.com/SysAdminDoc/FoxPort/blob/main/CHANGELOG.md",
        )

    def _open_issue_tracker(self) -> None:
        """Open the GitHub issue tracker in the user's default browser."""

        import webbrowser
        webbrowser.open("https://github.com/SysAdminDoc/FoxPort/issues/new")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {__app_name__}",
            f"<b>{__app_name__} v{__version__}</b><br><br>"
            "Migrate passwords, bookmarks, and extensions from Chromium-family "
            "browsers to Firefox-family browsers.<br><br>"
            "MIT licensed. The source browser is never modified.",
        )


def install_theme(app) -> None:
    """Apply the dark palette + stylesheet to the QApplication."""
    apply_palette(app)
    app.setStyleSheet(STYLESHEET)
