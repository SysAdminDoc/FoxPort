"""The five wizard pages: Source, Target, Items, Preview, Run."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import sqlite3

from foxport.browsers.chromium import (
    ExtensionInfo,
    read_bookmarks,
    read_extensions,
    read_password_rows,
)
from foxport.browsers.detect import (
    ChromiumProfile,
    FirefoxProfile,
    detect_chromium,
    detect_firefox,
    is_chromium_running,
    is_firefox_profile_locked,
)
from foxport.crypto.dpapi import inspect_local_state
from foxport.gui.widgets import (
    Banner,
    CountBadge,
    Tile,
    WizardPage,
)


# ----------------------------------------------------------- shared model

class MigrationContext:
    """Per-run state passed between wizard pages."""

    def __init__(self) -> None:
        self.chromium_profiles: list[ChromiumProfile] = []
        self.firefox_profiles: list[FirefoxProfile] = []
        self.source: ChromiumProfile | None = None
        self.target: FirefoxProfile | None = None
        self.dropped_source_path: Path | None = None
        self.do_passwords: bool = True
        self.do_bookmarks: bool = True
        self.do_extensions: bool = True
        self.do_cookies: bool = False
        self.do_history: bool = False
        self.extensions_online: bool = True
        self.dry_run: bool = False
        self.direct_write_passwords: bool = False
        self.out_root: Path = Path.home() / "Documents" / "FoxPort"
        # Preview counts
        self.password_count: int = 0
        self.bookmark_count: int = 0
        self.extension_count: int = 0
        self.cookie_count: int = 0
        self.history_count: int = 0
        # ABE warning
        self.source_uses_abe: bool = False
        self.source_has_classic_key: bool = True
        # Filters
        self.password_include_keys: set[str] | None = None
        self.bookmark_excluded_paths: set[tuple[str, ...]] = set()


def _count_bookmarks(roots) -> int:
    total = 0
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node.kind == "url":
            total += 1
        else:
            stack.extend(node.children)
    return total


# ----------------------------------------------------------- Step 1: Source

class SourcePage(WizardPage):
    """Tile picker for Chromium-family source profiles + drag-drop fallback."""

    detectionRequested = pyqtSignal()

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Pick your source browser",
            "Select the Chromium-family profile you want to migrate from. "
            "Detected profiles appear below. You can also drag a profile folder "
            "or a `Login Data` file onto the manual tile.",
            parent,
        )
        self._ctx = ctx
        self._tiles: dict[int, Tile] = {}

        self._banner = Banner(
            "Scanning for installed browsers…",
            variant="info",
        )
        self.add_content(self._banner)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tile_container = QWidget()
        self._tile_layout = QVBoxLayout(self._tile_container)
        self._tile_layout.setContentsMargins(0, 0, 0, 0)
        self._tile_layout.setSpacing(8)
        self._scroll.setWidget(self._tile_container)
        self.add_content(self._scroll, stretch=1)

        # Always-on manual drop tile
        self._manual = Tile(
            "Drop a profile folder here",
            "Drag a Chromium User Data folder, a profile folder, or a Login Data file onto this tile.",
            accept_drops=True,
        )
        self._manual.fileDropped.connect(self._on_drop)
        self.add_content(self._manual)

    def populate(self, profiles: list[ChromiumProfile]) -> None:
        # Clear any prior tiles.
        for tile in self._tiles.values():
            tile.setParent(None)
        self._tiles.clear()
        # Clear stretch + repopulate.
        while self._tile_layout.count():
            self._tile_layout.takeAt(0)
        if not profiles:
            self._banner.set_text(
                "No Chromium browsers were detected on this account. "
                "You can still drag a User Data folder onto the manual tile below."
            )
            self._tile_layout.addStretch(1)
            return
        running = any(is_chromium_running(p) for p in profiles)
        if running:
            self._banner.set_text(
                "One or more source browsers are running. Data may be incomplete or locked. "
                "Close them for the best result — FoxPort will copy the database files safely."
            )
        else:
            self._banner.set_text(
                f"{len(profiles)} Chromium profile(s) found. None are currently running."
            )
        for i, prof in enumerate(profiles):
            subtitle_parts = [str(prof.profile_dir)]
            if is_chromium_running(prof):
                subtitle_parts.append("⚠ currently running")
            tile = Tile(prof.label, "  ·  ".join(subtitle_parts))
            tile.clicked.connect(lambda i=i: self._on_pick(i))
            self._tile_layout.addWidget(tile)
            self._tiles[i] = tile
        self._tile_layout.addStretch(1)
        # Restore prior selection if any.
        if self._ctx.source in profiles:
            self._select(profiles.index(self._ctx.source))

    def _on_pick(self, index: int) -> None:
        self._select(index)
        self._ctx.source = self._ctx.chromium_profiles[index]
        self._refresh_abe_check()
        self.canAdvanceChanged.emit(True)

    def _select(self, index: int) -> None:
        for i, tile in self._tiles.items():
            tile.set_selected(i == index)

    def _on_drop(self, path: str) -> None:
        # Accept either: (a) a Login Data file, (b) a profile dir, (c) a User Data dir.
        p = Path(path)
        if not p.exists():
            return
        self._ctx.dropped_source_path = p
        self._banner.set_text(
            f"Manual source selected: {p}. The wizard will try to use it as-is."
        )

    def _refresh_abe_check(self) -> None:
        if not self._ctx.source:
            return
        info = inspect_local_state(self._ctx.source.local_state)
        self._ctx.source_uses_abe = info.has_app_bound_key
        self._ctx.source_has_classic_key = info.has_classic_key
        if info.has_app_bound_key and not info.has_classic_key:
            self._banner.set_text(
                "Heads up: this profile uses App-Bound Encryption only (Chrome 127+). "
                "Passwords cannot be decrypted in this version — bookmarks and extensions still work. "
                "A full ABE bypass is on the v0.3 roadmap."
            )
        elif info.has_app_bound_key:
            self._banner.set_text(
                "This profile uses App-Bound Encryption alongside the classic key. "
                "Older passwords will decrypt; some newer entries may fail."
            )

    def can_advance(self) -> bool:
        return self._ctx.source is not None or self._ctx.dropped_source_path is not None


# ----------------------------------------------------------- Step 2: Target

class TargetPage(WizardPage):
    """Pick the Firefox-family target profile (or skip — exports are still useful)."""

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Pick your target browser",
            "Choose where the import files should be aimed. FoxPort never writes into "
            "the target profile directly — files land in an output folder you'll import manually.",
            parent,
        )
        self._ctx = ctx
        self._tiles: dict[int, Tile] = {}

        self._banner = Banner("", variant="info")
        self._banner.setVisible(False)
        self.add_content(self._banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tile_container = QWidget()
        self._tile_layout = QVBoxLayout(self._tile_container)
        self._tile_layout.setContentsMargins(0, 0, 0, 0)
        self._tile_layout.setSpacing(8)
        scroll.setWidget(self._tile_container)
        self.add_content(scroll, stretch=1)

        self._skip_tile = Tile(
            "Skip — no specific target",
            "Generate the export files anyway. You can import them later into any Firefox-family browser.",
        )
        self._skip_tile.clicked.connect(self._on_skip)
        self.add_content(self._skip_tile)

    def populate(self, profiles: list[FirefoxProfile]) -> None:
        for tile in self._tiles.values():
            tile.setParent(None)
        self._tiles.clear()
        while self._tile_layout.count():
            self._tile_layout.takeAt(0)
        if not profiles:
            self._banner.setVisible(True)
            self._banner.set_text("No Firefox profiles found — you can still run the migration without a target.")
            self._tile_layout.addStretch(1)
            return
        any_locked = any(is_firefox_profile_locked(p) for p in profiles)
        if any_locked:
            self._banner.setVisible(True)
            self._banner.set_text(
                "One or more Firefox profiles are currently open. "
                "Close them before importing — Firefox won't open the import dialog otherwise."
            )
        for i, prof in enumerate(profiles):
            subtitle_parts = [str(prof.profile_dir)]
            if is_firefox_profile_locked(prof):
                subtitle_parts.append("⚠ locked (Firefox is open)")
            tile = Tile(prof.label, "  ·  ".join(subtitle_parts))
            tile.clicked.connect(lambda i=i: self._on_pick(i))
            self._tile_layout.addWidget(tile)
            self._tiles[i] = tile
        self._tile_layout.addStretch(1)
        if self._ctx.target in profiles:
            self._select(profiles.index(self._ctx.target))
        else:
            default_idx = next((i for i, p in enumerate(profiles) if p.is_default), None)
            if default_idx is not None:
                self._on_pick(default_idx)

    def _on_pick(self, index: int) -> None:
        self._ctx.target = self._ctx.firefox_profiles[index]
        self._skip_tile.set_selected(False)
        self._select(index)
        self.canAdvanceChanged.emit(True)

    def _on_skip(self) -> None:
        self._ctx.target = None
        for tile in self._tiles.values():
            tile.set_selected(False)
        self._skip_tile.set_selected(True)
        self.canAdvanceChanged.emit(True)

    def _select(self, index: int) -> None:
        for i, tile in self._tiles.items():
            tile.set_selected(i == index)

    def can_advance(self) -> bool:
        return True  # Target is optional


# ----------------------------------------------------------- Step 3: Items

class ItemsPage(WizardPage):
    """Big checkboxes for the three artifact categories + an output picker."""

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Choose what to migrate",
            "Each category produces a file in the output folder that you import in Firefox.",
            parent,
        )
        self._ctx = ctx

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(14)
        self._passwords_row = self._make_row("Passwords",
            "Decrypt every saved login with DPAPI and write a CSV your target browser imports via about:logins.",
            customize_callback=self._customize_passwords)
        self._bookmarks_row = self._make_row("Bookmarks",
            "Convert the entire bookmark tree to Netscape HTML for Library → Import Bookmarks from HTML.",
            customize_callback=self._customize_bookmarks)
        self._extensions_row = self._make_row("Extensions",
            "Map each installed Chrome extension to its closest Firefox AMO equivalent and emit a one-click install page.")
        self._cookies_row = self._make_row("Cookies",
            "Decrypt all cookies and emit a fresh Firefox cookies.sqlite. Drop it into a closed Firefox profile.",
            default_checked=False)
        self._history_row = self._make_row("Browsing history",
            "Convert the source URL+visit log to a fresh Firefox places.sqlite for swap-in.",
            default_checked=False)
        card_layout.addWidget(self._passwords_row[0])
        card_layout.addWidget(self._bookmarks_row[0])
        card_layout.addWidget(self._extensions_row[0])
        card_layout.addWidget(self._cookies_row[0])
        card_layout.addWidget(self._history_row[0])
        self.add_content(card)

        # Online lookup checkbox
        self._online_cb = QCheckBox("Allow online AMO lookup for unknown extensions  (recommended)")
        self._online_cb.setChecked(True)
        self.add_content(self._online_cb)

        # Direct-write password checkbox (NSS)
        self._direct_cb = QCheckBox(
            "Direct-write passwords into the target profile (close Firefox first; uses target's NSS)"
        )
        self._direct_cb.setChecked(False)
        self._direct_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        self.add_content(self._direct_cb)

        # Dry-run checkbox
        self._dry_cb = QCheckBox("Dry run — count items and test decryption, but do not write any files")
        self._dry_cb.setChecked(False)
        self._dry_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        self.add_content(self._dry_cb)

        # Output folder picker
        out_card = QFrame()
        out_card.setObjectName("Card")
        out_layout = QHBoxLayout(out_card)
        out_layout.setContentsMargins(20, 14, 20, 14)
        out_layout.setSpacing(10)
        out_layout.addWidget(QLabel("Output folder:"))
        self._out_label = QLabel(str(self._ctx.out_root))
        self._out_label.setStyleSheet("color: #a6adc8;")
        self._out_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        out_layout.addWidget(self._out_label, 1)
        self._out_btn = QPushButton("Change…")
        self._out_btn.clicked.connect(self._pick_dir)
        out_layout.addWidget(self._out_btn)
        self.add_content(out_card)

        self.add_stretch(1)

    def _make_row(self, title: str, subtitle: str, *,
                   default_checked: bool = True,
                   customize_callback=None):
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        cb = QCheckBox()
        cb.setChecked(default_checked)
        cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        layout.addWidget(cb)
        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #cdd6f4; font-size: 14px; font-weight: 700;")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        subtitle_label.setWordWrap(True)
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)
        layout.addLayout(text_box, 1)
        badge = CountBadge("—")
        layout.addWidget(badge)
        if customize_callback is not None:
            customize_btn = QPushButton("Customize…")
            customize_btn.setFlat(False)
            customize_btn.clicked.connect(customize_callback)  # type: ignore[arg-type]
            layout.addWidget(customize_btn)
        return row, cb, badge

    def _pick_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Output folder", str(self._ctx.out_root))
        if chosen:
            self._ctx.out_root = Path(chosen)
            self._out_label.setText(str(self._ctx.out_root))

    def _sync(self) -> None:
        self._ctx.do_passwords = self._passwords_row[1].isChecked()
        self._ctx.do_bookmarks = self._bookmarks_row[1].isChecked()
        self._ctx.do_extensions = self._extensions_row[1].isChecked()
        self._ctx.do_cookies = self._cookies_row[1].isChecked()
        self._ctx.do_history = self._history_row[1].isChecked()
        self._ctx.extensions_online = self._online_cb.isChecked()
        self._ctx.dry_run = self._dry_cb.isChecked()
        self._ctx.direct_write_passwords = self._direct_cb.isChecked()
        self.canAdvanceChanged.emit(self.can_advance())

    def set_counts(self, passwords: int, bookmarks: int, extensions: int,
                   cookies: int = 0, history: int = 0) -> None:
        self._passwords_row[2].setText(f"{passwords:,}")
        self._bookmarks_row[2].setText(f"{bookmarks:,}")
        self._extensions_row[2].setText(f"{extensions:,}")
        self._cookies_row[2].setText(f"{cookies:,}")
        self._history_row[2].setText(f"{history:,}")
        if self._ctx.source_uses_abe and not self._ctx.source_has_classic_key:
            self._passwords_row[1].setChecked(False)
            self._passwords_row[1].setEnabled(False)
            self._passwords_row[1].setToolTip("Disabled — source profile uses App-Bound Encryption only.")
            self._cookies_row[1].setChecked(False)
            self._cookies_row[1].setEnabled(False)
            self._cookies_row[1].setToolTip("Disabled — source profile uses App-Bound Encryption only.")

    def can_advance(self) -> bool:
        return any([
            self._passwords_row[1].isChecked(),
            self._bookmarks_row[1].isChecked(),
            self._extensions_row[1].isChecked(),
            self._cookies_row[1].isChecked(),
            self._history_row[1].isChecked(),
        ])

    def on_enter(self) -> None:
        self._sync()

    def _customize_passwords(self) -> None:
        if not self._ctx.source:
            return
        from foxport.gui.dialogs import PasswordPreviewDialog
        dlg = PasswordPreviewDialog(
            self._ctx.source,
            selected_keys=self._ctx.password_include_keys,
            parent=self,
        )
        if dlg.exec():
            self._ctx.password_include_keys = dlg.selected_keys()

    def _customize_bookmarks(self) -> None:
        if not self._ctx.source:
            return
        from foxport.gui.dialogs import BookmarkFilterDialog
        dlg = BookmarkFilterDialog(
            self._ctx.source,
            excluded=self._ctx.bookmark_excluded_paths,
            parent=self,
        )
        if dlg.exec():
            self._ctx.bookmark_excluded_paths = dlg.excluded_paths()


# ----------------------------------------------------------- Step 4: Preview

class PreviewPage(WizardPage):
    """Summary tree showing what's about to land in the output folder."""

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Preview",
            "Review what FoxPort is about to write. Nothing has been generated yet — "
            "click Run Migration when you're ready.",
            parent,
        )
        self._ctx = ctx
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Item", "Detail"])
        self._tree.setColumnWidth(0, 320)
        self.add_content(self._tree, stretch=1)
        self._note = QLabel("")
        self._note.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self._note.setWordWrap(True)
        self.add_content(self._note)

    def on_enter(self) -> None:
        self._tree.clear()
        ctx = self._ctx
        ctx.password_count = 0
        ctx.bookmark_count = 0
        ctx.extension_count = 0
        ctx.cookie_count = 0
        ctx.history_count = 0

        source_node = QTreeWidgetItem([f"Source: {ctx.source.label if ctx.source else '(manual)'}", ""])
        source_node.addChild(QTreeWidgetItem(
            ["Target", ctx.target.label if ctx.target else "(no target selected — files only)"]
        ))
        source_node.addChild(QTreeWidgetItem(["Output", str(ctx.out_root)]))
        if ctx.dry_run:
            source_node.addChild(QTreeWidgetItem(["Mode", "DRY RUN (nothing will be written)"]))
        self._tree.addTopLevelItem(source_node)

        if ctx.source:
            if ctx.do_passwords:
                count = sum(1 for _ in read_password_rows(ctx.source))
                ctx.password_count = count
                node = QTreeWidgetItem([f"Passwords ({count:,})", "passwords.csv → about:logins"])
                self._tree.addTopLevelItem(node)
            if ctx.do_bookmarks:
                roots = read_bookmarks(ctx.source)
                count = _count_bookmarks(roots)
                ctx.bookmark_count = count
                node = QTreeWidgetItem([f"Bookmarks ({count:,})", "bookmarks.html → Library import"])
                for root in roots:
                    child = QTreeWidgetItem([f"   {root.name}", f"{_count_bookmarks([root])} entries"])
                    node.addChild(child)
                self._tree.addTopLevelItem(node)
                node.setExpanded(True)
            if ctx.do_extensions:
                extensions = read_extensions(ctx.source)
                ctx.extension_count = len(extensions)
                node = QTreeWidgetItem([f"Extensions ({len(extensions):,})", "extensions.html → click each Install link"])
                for ext in extensions[:10]:
                    child = QTreeWidgetItem([f"   {ext.name}", f"{ext.extension_id} · v{ext.version}"])
                    node.addChild(child)
                if len(extensions) > 10:
                    node.addChild(QTreeWidgetItem([f"   …+{len(extensions) - 10} more", ""]))
                self._tree.addTopLevelItem(node)
                node.setExpanded(True)
            if ctx.do_cookies:
                cookie_count = self._count_cookies(ctx.source)
                ctx.cookie_count = cookie_count
                node = QTreeWidgetItem([f"Cookies ({cookie_count:,})", "cookies.sqlite → swap into closed Firefox profile"])
                self._tree.addTopLevelItem(node)
            if ctx.do_history:
                hist_urls, hist_visits = self._count_history(ctx.source)
                ctx.history_count = hist_visits
                node = QTreeWidgetItem(
                    [f"History ({hist_urls:,} URLs / {hist_visits:,} visits)",
                     "places.sqlite → swap into closed Firefox profile"],
                )
                self._tree.addTopLevelItem(node)

        source_node.setExpanded(True)
        notes: list[str] = []
        if ctx.source_uses_abe:
            notes.append(
                "App-Bound Encryption detected on source — some newer passwords/cookies may fail to decrypt."
            )
        if ctx.target and is_firefox_profile_locked(ctx.target):
            notes.append("Target Firefox profile is locked — close Firefox before importing.")
        if ctx.do_cookies or ctx.do_history:
            notes.append("cookies.sqlite / places.sqlite must be swapped into a CLOSED Firefox profile.")
        notes.append("The source browser will not be modified.")
        self._note.setText("  ·  ".join(notes))

    def _count_cookies(self, profile: ChromiumProfile) -> int:
        for path in (profile.profile_dir / "Network" / "Cookies", profile.profile_dir / "Cookies"):
            if path.is_file():
                try:
                    import shutil, tempfile
                    tmp = tempfile.mkdtemp(prefix="foxport_cookies_count_")
                    dest = Path(tmp) / path.name
                    shutil.copy2(path, dest)
                    conn = sqlite3.connect(str(dest))
                    try:
                        row = conn.execute("SELECT COUNT(*) FROM cookies").fetchone()
                        return int(row[0]) if row else 0
                    finally:
                        conn.close()
                        shutil.rmtree(tmp, ignore_errors=True)
                except (OSError, sqlite3.DatabaseError):
                    return 0
        return 0

    def _count_history(self, profile: ChromiumProfile) -> tuple[int, int]:
        path = profile.profile_dir / "History"
        if not path.is_file():
            return 0, 0
        try:
            import shutil, tempfile
            tmp = tempfile.mkdtemp(prefix="foxport_history_count_")
            dest = Path(tmp) / path.name
            shutil.copy2(path, dest)
            conn = sqlite3.connect(str(dest))
            try:
                urls = conn.execute("SELECT COUNT(*) FROM urls").fetchone()
                visits = conn.execute("SELECT COUNT(*) FROM visits").fetchone()
                return int(urls[0]) if urls else 0, int(visits[0]) if visits else 0
            finally:
                conn.close()
                shutil.rmtree(tmp, ignore_errors=True)
        except (OSError, sqlite3.DatabaseError):
            return 0, 0


# ----------------------------------------------------------- Step 5: Run

class RunPage(WizardPage):
    """Live progress + log + Done screen."""

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Run migration",
            "FoxPort will work through each selected category and report progress below.",
            parent,
        )
        self._ctx = ctx
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setFormat("Ready")
        self.add_content(self._progress)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Activity will appear here once you press Start.")
        self.add_content(self._log, stretch=1)

        # Done-screen button bar (hidden until done).
        self._actions = QFrame()
        actions_layout = QHBoxLayout(self._actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(10)
        self.open_out_btn = QPushButton("Open output folder")
        self.open_pw_btn = QPushButton("Open passwords.csv")
        self.open_bm_btn = QPushButton("Open bookmarks.html")
        self.open_ext_btn = QPushButton("Open extensions.html")
        self.open_cookies_btn = QPushButton("Reveal cookies.sqlite")
        self.open_history_btn = QPushButton("Reveal places.sqlite")
        for btn in (self.open_out_btn, self.open_pw_btn, self.open_bm_btn,
                    self.open_ext_btn, self.open_cookies_btn, self.open_history_btn):
            actions_layout.addWidget(btn)
        actions_layout.addStretch(1)
        self._actions.setVisible(False)
        self.add_content(self._actions)

    def append_log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def reset(self) -> None:
        self._log.clear()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("Ready")
        self._actions.setVisible(False)

    def set_busy(self) -> None:
        self._progress.setRange(0, 0)
        self._progress.setFormat("Working…")

    def set_step(self, current: int, total: int) -> None:
        if total <= 0:
            self.set_busy()
            return
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._progress.setFormat(f"Step {current} of {total}")

    def set_done(self, ok: bool, summary: str, exports: dict[str, Path]) -> None:
        self._progress.setRange(0, 1)
        if ok:
            self._progress.setValue(1)
            self._progress.setFormat("Done")
        else:
            self._progress.setValue(0)
            self._progress.setFormat("Failed")
        self._actions.setVisible(ok and bool(exports))
        # Show/hide per-file buttons based on what got produced.
        self.open_pw_btn.setVisible("passwords" in exports)
        self.open_bm_btn.setVisible("bookmarks" in exports)
        self.open_ext_btn.setVisible("extensions" in exports)
        self.open_cookies_btn.setVisible("cookies" in exports)
        self.open_history_btn.setVisible("history" in exports)
