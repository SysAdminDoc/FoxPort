"""Main window — single-page wizard to migrate one Chromium profile to one Firefox profile."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from foxport import __app_name__, __version__
from foxport.browsers.detect import ChromiumProfile, FirefoxProfile
from foxport.gui.theme import STYLESHEET, apply_palette
from foxport.gui.workers import (
    DetectWorker,
    MigrationRequest,
    MigrationWorker,
    make_thread,
)


DEFAULT_OUT_ROOT = Path.home() / "Documents" / "FoxPort"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{__app_name__} v{__version__}")
        self.resize(880, 640)

        self._chromium: list[ChromiumProfile] = []
        self._firefox: list[FirefoxProfile] = []
        self._out_root: Path = DEFAULT_OUT_ROOT
        self._detect_thread: QThread | None = None
        self._detect_worker: DetectWorker | None = None
        self._migrate_thread: QThread | None = None
        self._migrate_worker: MigrationWorker | None = None

        self._build_ui()
        self._build_menu()
        self.statusBar().showMessage("Ready.")
        self._start_detection()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 18, 20, 14)
        outer.setSpacing(10)

        title = QLabel(f"{__app_name__}")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("Migrate passwords, bookmarks, and extensions from Chromium to Firefox.")
        subtitle.setObjectName("SubtitleLabel")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        # Source / target card
        picker_card = QFrame()
        picker_card.setObjectName("Card")
        picker_layout = QVBoxLayout(picker_card)
        picker_layout.setContentsMargins(16, 12, 16, 14)
        picker_layout.setSpacing(8)

        picker_layout.addWidget(self._section_label("Source"))
        source_row = QHBoxLayout()
        source_row.setSpacing(10)
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(360)
        source_row.addWidget(QLabel("Chromium profile:"))
        source_row.addWidget(self.source_combo, 1)
        picker_layout.addLayout(source_row)

        picker_layout.addWidget(self._section_label("Target"))
        target_row = QHBoxLayout()
        target_row.setSpacing(10)
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(360)
        target_row.addWidget(QLabel("Firefox profile:"))
        target_row.addWidget(self.target_combo, 1)
        picker_layout.addLayout(target_row)

        rescan_row = QHBoxLayout()
        rescan_row.addStretch(1)
        self.rescan_btn = QPushButton("Rescan browsers")
        self.rescan_btn.clicked.connect(self._start_detection)  # type: ignore[arg-type]
        rescan_row.addWidget(self.rescan_btn)
        picker_layout.addLayout(rescan_row)

        outer.addWidget(picker_card)

        # Options card
        options_card = QFrame()
        options_card.setObjectName("Card")
        options_layout = QVBoxLayout(options_card)
        options_layout.setContentsMargins(16, 12, 16, 14)
        options_layout.setSpacing(6)
        options_layout.addWidget(self._section_label("What to migrate"))
        self.passwords_cb = QCheckBox("Passwords  (decrypt with DPAPI, write Firefox CSV)")
        self.bookmarks_cb = QCheckBox("Bookmarks  (Netscape HTML for Library import)")
        self.extensions_cb = QCheckBox("Extensions  (map to addons.mozilla.org equivalents)")
        self.online_cb = QCheckBox("Allow AMO online lookup for unknown extensions")
        self.passwords_cb.setChecked(True)
        self.bookmarks_cb.setChecked(True)
        self.extensions_cb.setChecked(True)
        self.online_cb.setChecked(True)
        self.extensions_cb.toggled.connect(self.online_cb.setEnabled)  # type: ignore[arg-type]
        options_layout.addWidget(self.passwords_cb)
        options_layout.addWidget(self.bookmarks_cb)
        options_layout.addWidget(self.extensions_cb)
        options_layout.addWidget(self.online_cb)

        out_row = QHBoxLayout()
        out_row.setSpacing(10)
        out_row.addWidget(QLabel("Output folder:"))
        self.out_label = QLabel(str(self._out_root))
        self.out_label.setStyleSheet("color: #a6adc8;")
        self.out_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        out_row.addWidget(self.out_label, 1)
        self.out_btn = QPushButton("Change…")
        self.out_btn.clicked.connect(self._pick_output_dir)  # type: ignore[arg-type]
        out_row.addWidget(self.out_btn)
        options_layout.addLayout(out_row)

        outer.addWidget(options_card)

        # Run row
        run_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("Idle")
        run_row.addWidget(self.progress, 1)
        self.run_btn = QPushButton("Run Migration")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self._run_migration)  # type: ignore[arg-type]
        run_row.addWidget(self.run_btn)
        outer.addLayout(run_row)

        # Log panel
        outer.addWidget(self._section_label("Activity Log"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Activity will appear here.")
        outer.addWidget(self.log, 1)

        self.setStatusBar(QStatusBar())

    def _build_menu(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        open_out = QAction("Open output folder", self)
        open_out.triggered.connect(self._open_out_root)  # type: ignore[arg-type]
        file_menu.addAction(open_out)
        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.close)  # type: ignore[arg-type]
        file_menu.addAction(quit_act)
        help_menu = menu.addMenu("&Help")
        about = QAction("About FoxPort", self)
        about.triggered.connect(self._about)  # type: ignore[arg-type]
        help_menu.addAction(about)

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        return label

    # --------------------------------------------------------------- Detection

    def _start_detection(self) -> None:
        if self._detect_thread is not None:
            return
        self.rescan_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.source_combo.clear()
        self.target_combo.clear()
        self.statusBar().showMessage("Detecting installed browsers...")

        worker = DetectWorker()
        thread = make_thread(worker)
        worker.log.connect(self._append_log)
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
        self._chromium = chromium
        self._firefox = firefox
        for prof in chromium:
            self.source_combo.addItem(prof.label, prof)
        for prof in firefox:
            self.target_combo.addItem(prof.label, prof)
            if prof.is_default:
                self.target_combo.setCurrentIndex(self.target_combo.count() - 1)
        if not chromium:
            self._append_log("No Chromium browsers detected.")
            self.statusBar().showMessage("No Chromium browsers detected.")
        else:
            self.statusBar().showMessage(
                f"Detected {len(chromium)} Chromium profile(s), {len(firefox)} Firefox profile(s)."
            )
        self.rescan_btn.setEnabled(True)
        self.run_btn.setEnabled(bool(chromium))

    # --------------------------------------------------------------- Migration

    def _run_migration(self) -> None:
        if self._migrate_thread is not None:
            return
        source = self.source_combo.currentData()
        if not isinstance(source, ChromiumProfile):
            QMessageBox.warning(self, "FoxPort", "Pick a Chromium source profile first.")
            return
        target = self.target_combo.currentData() if self.target_combo.count() > 0 else None
        if not (self.passwords_cb.isChecked() or self.bookmarks_cb.isChecked() or self.extensions_cb.isChecked()):
            QMessageBox.warning(self, "FoxPort", "Pick at least one thing to migrate.")
            return

        request = MigrationRequest(
            source=source,
            target=target if isinstance(target, FirefoxProfile) else None,
            out_root=self._out_root,
            do_passwords=self.passwords_cb.isChecked(),
            do_bookmarks=self.bookmarks_cb.isChecked(),
            do_extensions=self.extensions_cb.isChecked(),
            extensions_online=self.online_cb.isChecked(),
        )

        self.run_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self.progress.setFormat("Working…")
        self.progress.setRange(0, 0)  # busy
        self.statusBar().showMessage("Migration running...")

        worker = MigrationWorker(request)
        thread = make_thread(worker)
        worker.log.connect(self._append_log)
        worker.step.connect(self._on_step)
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

    def _on_step(self, current: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.progress.setFormat(f"Step {current} of {total}")

    def _on_migration_finished(self, ok: bool, payload: str) -> None:
        self.run_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        if ok:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.progress.setFormat("Done")
            self.statusBar().showMessage(f"Done. Output: {payload}")
            self._append_log(f"Done. Output: {payload}")
            reply = QMessageBox.information(
                self,
                "FoxPort",
                f"Migration complete.\n\nOutput folder:\n{payload}\n\nOpen it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._open_path(Path(payload))
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.progress.setFormat("Failed")
            self.statusBar().showMessage("Migration failed.")
            QMessageBox.critical(self, "FoxPort", f"Migration failed:\n\n{payload}")

    # --------------------------------------------------------------- Helpers

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def _pick_output_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Output folder", str(self._out_root))
        if chosen:
            self._out_root = Path(chosen)
            self.out_label.setText(str(self._out_root))

    def _open_out_root(self) -> None:
        self._out_root.mkdir(parents=True, exist_ok=True)
        self._open_path(self._out_root)

    def _open_path(self, path: Path) -> None:
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
            "browsers (Chrome, Brave, Edge, Vivaldi, Opera) to Firefox-family "
            "browsers (Firefox, LibreWolf, Waterfox).<br><br>"
            "MIT licensed. The source browser is never modified.",
        )


def install_theme(app) -> None:
    """Apply the dark palette + stylesheet to the QApplication."""
    apply_palette(app)
    app.setStyleSheet(STYLESHEET)
