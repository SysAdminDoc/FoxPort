"""Main window — a five-step wizard for one source-to-target migration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
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
        self.resize(960, 680)

        self._ctx = MigrationContext()
        self._detect_thread: QThread | None = None
        self._detect_worker: DetectWorker | None = None
        self._migrate_thread: QThread | None = None
        self._migrate_worker: MigrationWorker | None = None
        self._migration_done = False

        self._build_ui()
        self._build_menu()
        self._start_detection()

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

        # Done-page action wiring
        self._run_page.open_out_btn.clicked.connect(lambda: self._open_path(Path(self._last_out_dir)))
        self._run_page.open_pw_btn.clicked.connect(lambda: self._open_path(Path(self._last_exports.get("passwords", ""))))
        self._run_page.open_bm_btn.clicked.connect(lambda: self._open_path(Path(self._last_exports.get("bookmarks", ""))))
        self._run_page.open_ext_btn.clicked.connect(lambda: self._open_path(Path(self._last_exports.get("extensions", ""))))
        self._last_out_dir: str = ""
        self._last_exports: dict[str, str] = {}

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
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)
        help_menu = menu.addMenu("&Help")
        about = QAction("About FoxPort", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

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
        self._footer.set_can_back(idx > 0 and not (idx == len(STEP_NAMES) - 1 and self._migration_done))
        if idx == len(STEP_NAMES) - 1:
            if self._migration_done:
                self._footer.set_next_label("Close")
                self._footer.set_can_advance(True)
            else:
                self._footer.set_next_label("Run Migration")
                self._footer.set_can_advance(page.can_advance() if hasattr(page, "can_advance") else True)
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
        # Run step: clicking "Run Migration" or "Close"
        if idx == len(STEP_NAMES) - 1:
            if self._migration_done:
                self.close()
            return
        if idx == len(STEP_NAMES) - 2:
            # Preview step → advance into Run AND start the migration.
            self._show_step(idx + 1)
            self._start_migration()
            return
        # Going from Items (index 2) to Preview — populate counts on enter.
        self._show_step(idx + 1)

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
        # Firefox profiles need their browser field stamped from the registry walk.
        self._ctx.chromium_profiles = list(chromium)
        self._ctx.firefox_profiles = list(firefox)
        self._source_page.populate(chromium)
        self._target_page.populate(firefox)
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
        # Push counts into Items page so the user sees them on back-nav too.
        self._items_page.set_counts(
            self._ctx.password_count,
            self._ctx.bookmark_count,
            self._ctx.extension_count,
        )
        request = MigrationRequest(
            source=self._ctx.source,
            target=self._ctx.target,
            out_root=self._ctx.out_root,
            do_passwords=self._ctx.do_passwords,
            do_bookmarks=self._ctx.do_bookmarks,
            do_extensions=self._ctx.do_extensions,
            extensions_online=self._ctx.extensions_online,
        )
        self._run_page.reset()
        self._run_page.set_busy()
        self.statusBar().showMessage("Migration running...")
        worker = MigrationWorker(request)
        thread = make_thread(worker)
        worker.log.connect(self._run_page.append_log)
        worker.step.connect(self._run_page.set_step)
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
