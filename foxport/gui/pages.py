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
    QSizePolicy,
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
    OptionRow,
    Tile,
    WizardPage,
)


# ----------------------------------------------------------- shared model

class MigrationContext:
    """Per-run state passed between wizard pages."""

    DIRECTION_FORWARD = "forward"   # Chromium → Firefox (default)
    DIRECTION_REVERSE = "reverse"   # Firefox → Chromium

    def __init__(self) -> None:
        self.chromium_profiles: list[ChromiumProfile] = []
        self.firefox_profiles: list[FirefoxProfile] = []
        # In forward mode source = ChromiumProfile, target = FirefoxProfile.
        # In reverse mode source = FirefoxProfile, target = ChromiumProfile.
        # The fields stay typed loosely so the existing page code keeps working.
        self.source = None
        self.target = None
        self.dropped_source_path: Path | None = None
        self.direction: str = self.DIRECTION_FORWARD
        self.master_password: str = ""
        self.do_passwords: bool = True
        self.do_bookmarks: bool = True
        self.do_extensions: bool = True
        self.do_cookies: bool = False
        self.do_history: bool = False
        self.do_autofill: bool = False
        self.do_cards: bool = False
        self.do_search_engines: bool = False
        self.do_open_tabs: bool = False
        self.do_downloads: bool = False
        self.extensions_online: bool = True
        self.dry_run: bool = False
        self.direct_write_passwords: bool = False
        self.direct_write_cookies: bool = False
        self.direct_write_history: bool = False
        self.direct_write_open_tabs: bool = False
        # Per-category direct-write policy. Default ``"apply"`` preserves
        # the v1.3 behavior. Set by the conflict-review dialog (which
        # opens between Preview and Run when any direct_write_* flag is
        # True) before the worker runs.
        self.policy_passwords: str = "apply"
        self.policy_cookies: str = "apply"
        self.policy_history: str = "apply"
        self.policy_open_tabs: str = "apply"
        self.hibp_scan: bool = False
        self.mask_passwords_in_preview: bool = True
        self.out_root: Path = Path.home() / "Documents" / "FoxPort"
        # Preview counts, keyed by item slug. PreviewPage fills this in;
        # ItemsPage reads it on back-nav to show per-row count badges.
        self.counts: dict[str, int] = {}
        # ABE warning
        self.source_uses_abe: bool = False
        self.source_has_classic_key: bool = True
        # Filters
        self.password_include_keys: set[str] | None = None
        self.bookmark_excluded_paths: set[tuple[str, ...]] = set()
        self.history_date_from_us: int | None = None
        self.history_date_to_us: int | None = None


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


def _safe_sqlite_count(src: Path, queries: tuple[str, ...]) -> list[int]:
    """Run COUNT-style queries on a locked Chromium SQLite file safely.

    Copies the DB + its ``-wal``/``-shm`` siblings to a fresh temp dir
    (Chromium holds an exclusive lock on the live file, and skipping the
    WAL produces a stale snapshot), runs the queries, and tears the
    tempdir down — even if the copy or the connect fails. Returns one
    int per query, or ``[]`` on any error. Never raises.
    """
    import shutil
    import tempfile

    tmp_dir: str | None = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="foxport_count_")
        dest = Path(tmp_dir) / src.name
        shutil.copy2(src, dest)
        for suffix in ("-wal", "-shm"):
            sibling = src.with_name(src.name + suffix)
            if sibling.exists():
                try:
                    shutil.copy2(sibling, Path(tmp_dir) / sibling.name)
                except OSError:
                    # Sibling could be locked; the main file alone is still
                    # a usable (if slightly stale) snapshot.
                    pass
        conn = sqlite3.connect(str(dest))
        try:
            out: list[int] = []
            for q in queries:
                row = conn.execute(q).fetchone()
                out.append(int(row[0]) if row and row[0] is not None else 0)
            return out
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError, sqlite3.OperationalError):
        return []
    finally:
        if tmp_dir is not None:
            import shutil as _sh
            _sh.rmtree(tmp_dir, ignore_errors=True)


# ----------------------------------------------------------- Step 1: Source

class SourcePage(WizardPage):
    """Tile picker for source profiles (Chromium or Firefox) + drag-drop fallback."""

    detectionRequested = pyqtSignal()
    directionChanged = pyqtSignal()

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Pick your source browser",
            "Select the profile you want to migrate from. The direction selector "
            "above flips between Chromium → Firefox and Firefox → Chromium.",
            parent,
        )
        self._ctx = ctx
        self._tiles: dict[int, Tile] = {}

        # Direction selector — segmented control implemented as two buttons.
        direction_row = QHBoxLayout()
        direction_row.setSpacing(0)
        direction_row.addWidget(QLabel("Direction:"))
        direction_row.addSpacing(10)
        from PyQt6.QtWidgets import QPushButton
        self._forward_btn = QPushButton("Chromium → Firefox")
        self._reverse_btn = QPushButton("Firefox → Chromium")
        self._forward_btn.setCheckable(True)
        self._reverse_btn.setCheckable(True)
        self._forward_btn.setChecked(True)
        for btn in (self._forward_btn, self._reverse_btn):
            btn.setObjectName("DirectionToggle")
        self._forward_btn.clicked.connect(lambda: self._set_direction(MigrationContext.DIRECTION_FORWARD))
        self._reverse_btn.clicked.connect(lambda: self._set_direction(MigrationContext.DIRECTION_REVERSE))
        direction_row.addWidget(self._forward_btn)
        direction_row.addWidget(self._reverse_btn)
        direction_row.addStretch(1)
        direction_widget = QFrame()
        direction_widget.setLayout(direction_row)
        self.add_content(direction_widget)

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

    def populate(self, chromium: list[ChromiumProfile], firefox: list[FirefoxProfile]) -> None:
        # Cache both lists; only render the one matching the current direction.
        self._ctx.chromium_profiles = chromium
        self._ctx.firefox_profiles = firefox
        self._render_for_direction()

    def _render_for_direction(self) -> None:
        # Clear any prior tiles.
        for tile in self._tiles.values():
            tile.setParent(None)
        self._tiles.clear()
        while self._tile_layout.count():
            self._tile_layout.takeAt(0)

        if self._ctx.direction == MigrationContext.DIRECTION_REVERSE:
            profiles = self._ctx.firefox_profiles
            family_name = "Firefox-family"
            running_helper = is_firefox_profile_locked
            running_label = "⚠ locked (Firefox is open)"
        else:
            profiles = self._ctx.chromium_profiles
            family_name = "Chromium"
            running_helper = is_chromium_running
            running_label = "⚠ currently running"

        if not profiles:
            self._banner.set_text(
                f"No {family_name} browsers were detected on this account. "
                "You can still drag a profile folder onto the manual tile below."
            )
            self._tile_layout.addStretch(1)
            return
        running = any(running_helper(p) for p in profiles)
        if running:
            self._banner.set_text(
                f"One or more {family_name} source profiles are in use. "
                "Close them for the best result — FoxPort will copy database files safely."
            )
        else:
            self._banner.set_text(
                f"{len(profiles)} {family_name} profile(s) found. None are currently in use."
            )
        for i, prof in enumerate(profiles):
            subtitle_parts = [str(prof.profile_dir)]
            if running_helper(prof):
                subtitle_parts.append(running_label)
            tile = Tile(prof.label, "  ·  ".join(subtitle_parts))
            tile.clicked.connect(lambda i=i: self._on_pick(i))
            self._tile_layout.addWidget(tile)
            self._tiles[i] = tile
        self._tile_layout.addStretch(1)
        # Restore prior selection if any (only if it's of the right type).
        if self._ctx.source in profiles:
            self._select(profiles.index(self._ctx.source))

    def _set_direction(self, direction: str) -> None:
        if self._ctx.direction == direction:
            return
        self._ctx.direction = direction
        self._forward_btn.setChecked(direction == MigrationContext.DIRECTION_FORWARD)
        self._reverse_btn.setChecked(direction == MigrationContext.DIRECTION_REVERSE)
        # Clear the prior source/target — they were of the wrong family.
        self._ctx.source = None
        self._ctx.target = None
        self._render_for_direction()
        self.directionChanged.emit()
        self.canAdvanceChanged.emit(False)

    def _on_pick(self, index: int) -> None:
        self._select(index)
        if self._ctx.direction == MigrationContext.DIRECTION_REVERSE:
            self._ctx.source = self._ctx.firefox_profiles[index]
        else:
            self._ctx.source = self._ctx.chromium_profiles[index]
            self._refresh_abe_check()
        self.canAdvanceChanged.emit(True)

    def _select(self, index: int) -> None:
        for i, tile in self._tiles.items():
            tile.set_selected(i == index)

    def _on_drop(self, path: str) -> None:
        """Promote a dropped folder/file into a synthetic source profile.

        Accepts:
          * A Chromium profile dir (contains ``Preferences``) — promoted directly.
          * A Chromium User Data dir (contains ``Local State`` AND
            ``Default/Preferences``) — promoted via the Default subdir.
          * A standalone ``Login Data`` file — wrap the parent dir.
          * A bookmark export (Pocket / Pinboard / OPML / Netscape HTML) —
            converted on the spot to a Firefox-importable HTML sibling and
            reported via the banner; no source-profile selection happens for
            this branch because there's no profile to migrate from, just
            bookmarks to convert.

        The synthetic profile is appended to the source tile list, auto-selected,
        and pushed into `ctx.source` so the rest of the wizard reads it like any
        detected profile.
        """
        from foxport.browsers.detect import ChromiumProfile
        p = Path(path)
        if not p.exists():
            return
        # Try the bookmark-import path first when the drop is a file but
        # doesn't look like Chromium's Login Data — saves a round-trip
        # through the "couldn't recognize" branch for OPML / Pocket / etc.
        if p.is_file() and p.name != "Login Data":
            try:
                from foxport.import_.adapters import parse_file, write_netscape_html
                fmt, entries = parse_file(p)
            except Exception:  # noqa: BLE001 — adapter import or parse failure shouldn't abort
                fmt, entries = "unknown", []
            if fmt != "unknown" and entries:
                out_path = p.with_suffix(p.suffix + ".firefox.html")
                try:
                    write_netscape_html(entries, out_path)
                except OSError as exc:
                    self._banner.set_text(
                        f"Couldn't write converted bookmarks to {out_path}: {exc}"
                    )
                    return
                self._banner.set_text(
                    f"Converted {len(entries)} bookmark(s) from {fmt} -> {out_path}. "
                    "Open Firefox Library (Ctrl+Shift+O), then Import and Backup -> "
                    "Import Bookmarks from HTML."
                )
                return
        profile_dir: Path | None = None
        user_data_dir: Path | None = None
        if p.is_file() and p.name == "Login Data":
            profile_dir = p.parent
        elif p.is_dir():
            # User Data dir?
            if (p / "Local State").is_file() and (p / "Default" / "Preferences").is_file():
                profile_dir = p / "Default"
                user_data_dir = p
            # Profile dir?
            elif (p / "Preferences").is_file():
                profile_dir = p
        if profile_dir is None:
            self._banner.set_text(
                f"Couldn't recognize {p} as a Chromium profile, User Data folder, "
                "or a supported bookmark export (Pocket / Pinboard / OPML / Netscape)."
            )
            return
        if user_data_dir is None:
            # Profile-dir-only case: walk up to find the parent containing Local State.
            user_data_dir = profile_dir.parent
        local_state = user_data_dir / "Local State"
        if not local_state.is_file():
            # Last-ditch: place a synthetic empty Local State next to it.
            local_state = profile_dir / "Local State.foxport-synthetic"
            local_state.write_text('{"os_crypt": {"encrypted_key": ""}}', encoding="utf-8")

        synthetic = ChromiumProfile(
            browser="Dropped",
            family="chromium",
            profile_name=profile_dir.name,
            profile_dir=profile_dir,
            local_state=local_state,
            user_data_dir=user_data_dir,
        )
        self._ctx.dropped_source_path = p
        # Append to the source list and the tile rendering.
        self._ctx.chromium_profiles = list(self._ctx.chromium_profiles) + [synthetic]
        # Switch to forward direction (drag-drop only supports Chromium sources today).
        if self._ctx.direction != MigrationContext.DIRECTION_FORWARD:
            self._set_direction(MigrationContext.DIRECTION_FORWARD)
        self._render_for_direction()
        new_idx = len(self._ctx.chromium_profiles) - 1
        self._on_pick(new_idx)
        self._banner.set_text(
            f"Manual source selected: {profile_dir}. Continue to the next step."
        )

    def _refresh_abe_check(self) -> None:
        if not self._ctx.source or not hasattr(self._ctx.source, "local_state"):
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
    """Pick the target profile — the family swaps based on context direction."""

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Pick your target browser",
            "Choose where the import files should be aimed. The output folder "
            "always gets the import-ready files even when no target is selected.",
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

    def populate(self) -> None:
        self._render_for_direction()

    def _render_for_direction(self) -> None:
        for tile in self._tiles.values():
            tile.setParent(None)
        self._tiles.clear()
        while self._tile_layout.count():
            self._tile_layout.takeAt(0)
        if self._ctx.direction == MigrationContext.DIRECTION_REVERSE:
            profiles = self._ctx.chromium_profiles
            lock_helper = is_chromium_running
            locked_label = "⚠ currently running"
            empty_msg = ("No Chromium-family targets found — you can still run the "
                          "migration without a target.")
            busy_msg = ("One or more Chromium browsers are running. "
                        "Close them before applying the import files.")
        else:
            profiles = self._ctx.firefox_profiles
            lock_helper = is_firefox_profile_locked
            locked_label = "⚠ locked (Firefox is open)"
            empty_msg = ("No Firefox profiles found — you can still run the migration "
                          "without a target.")
            busy_msg = ("One or more Firefox profiles are currently open. "
                        "Close them before importing — Firefox won't open the import "
                        "dialog otherwise.")
        self._banner.setVisible(False)
        if not profiles:
            self._banner.setVisible(True)
            self._banner.set_text(empty_msg)
            self._tile_layout.addStretch(1)
            return
        if any(lock_helper(p) for p in profiles):
            self._banner.setVisible(True)
            self._banner.set_text(busy_msg)
        for i, prof in enumerate(profiles):
            subtitle_parts = [str(prof.profile_dir)]
            if lock_helper(prof):
                subtitle_parts.append(locked_label)
            tile = Tile(prof.label, "  ·  ".join(subtitle_parts))
            tile.clicked.connect(lambda i=i: self._on_pick(i))
            self._tile_layout.addWidget(tile)
            self._tiles[i] = tile
        self._tile_layout.addStretch(1)
        if self._ctx.target in profiles:
            self._select(profiles.index(self._ctx.target))
        elif self._ctx.direction == MigrationContext.DIRECTION_FORWARD:
            default_idx = next((i for i, p in enumerate(profiles)
                                  if getattr(p, "is_default", False)), None)
            if default_idx is not None:
                self._on_pick(default_idx)

    def _on_pick(self, index: int) -> None:
        if self._ctx.direction == MigrationContext.DIRECTION_REVERSE:
            self._ctx.target = self._ctx.chromium_profiles[index]
        else:
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
            "Select the data to export. FoxPort keeps the source profile read-only.",
            parent,
        )
        self._ctx = ctx
        # Per-category row registry. _make_row appends to this in declaration
        # order so set_counts() can iterate by key and the wizard doesn't have
        # to remember 10 attribute names.
        self._rows: dict[str, tuple] = {}
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._body)
        self.add_content(scroll, stretch=1)

        card = QFrame()
        card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(6)
        self._passwords_row = self._make_row("passwords", "Passwords",
            "Export saved logins to a CSV for Firefox about:logins import.",
            customize_callback=self._customize_passwords,
            customize_label="Review")
        self._bookmarks_row = self._make_row("bookmarks", "Bookmarks",
            "Create a Netscape HTML file for Firefox Library import.",
            customize_callback=self._customize_bookmarks,
            customize_label="Folders")
        self._extensions_row = self._make_row("extensions", "Extensions",
            "Map installed Chrome extensions to Firefox Add-ons install links.")
        self._cookies_row = self._make_row("cookies", "Cookies",
            "Create a Firefox cookies.sqlite for a closed target profile.",
            default_checked=False)
        self._history_row = self._make_row("history", "Browsing history",
            "Create a Firefox places.sqlite from source URLs and visits.",
            default_checked=False,
            customize_callback=self._customize_history,
            customize_label="Range")
        self._autofill_row = self._make_row("autofill", "Form autofill",
            "Translate saved form entries into Firefox formhistory.sqlite.",
            default_checked=False)
        self._cards_row = self._make_row("cards", "Saved credit cards (CSV)",
            "Write card records to CSV for password-manager import.",
            default_checked=False)
        self._search_engines_row = self._make_row("search_engines", "Search engines",
            "Export custom search engines as Firefox-installable OpenSearch XML.",
            default_checked=False)
        self._open_tabs_row = self._make_row("open_tabs", "Open tabs",
            "Recover current session URLs into Firefox recovery.jsonlz4.",
            default_checked=False)
        self._downloads_row = self._make_row("downloads", "Downloads (CSV)",
            "Export download history with source URL, path, and completion time.",
            default_checked=False)
        for key in ("passwords", "bookmarks", "extensions", "cookies", "history",
                    "autofill", "cards", "search_engines", "open_tabs", "downloads"):
            card_layout.addWidget(self._rows[key][0])
        body_layout.addWidget(card)

        # Online lookup checkbox
        self._online_cb = QCheckBox("Allow online Add-ons lookup for unknown extensions")
        self._online_cb.setChecked(True)
        self._online_cb.setToolTip("Looks up public Firefox Add-ons metadata. Passwords and profile data stay local.")
        self._online_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._online_cb)

        # HIBP scan checkbox — opt-in; sends 5-char SHA-1 prefix only.
        self._hibp_cb = QCheckBox(
            "Check passwords for known breaches (k-anonymity; no plaintext leaves this machine)"
        )
        self._hibp_cb.setChecked(False)
        self._hibp_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._hibp_cb)

        # Direct-write password checkbox (NSS)
        self._direct_cb = QCheckBox(
            "Write passwords directly into the target profile"
        )
        self._direct_cb.setChecked(False)
        self._direct_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._direct_cb)

        # Direct-write cookies/history into the target profile.
        self._direct_cookies_cb = QCheckBox(
            "Write cookies.sqlite directly into the target profile"
        )
        self._direct_cookies_cb.setChecked(False)
        self._direct_cookies_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._direct_cookies_cb)

        self._direct_history_cb = QCheckBox(
            "Write places.sqlite directly into the target profile"
        )
        self._direct_history_cb.setChecked(False)
        self._direct_history_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._direct_history_cb)

        self._direct_open_tabs_cb = QCheckBox(
            "Write open tabs directly into the target profile"
        )
        self._direct_open_tabs_cb.setChecked(False)
        self._direct_open_tabs_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._direct_open_tabs_cb)

        # Dry-run checkbox
        self._dry_cb = QCheckBox("Dry run: count and test decryption without writing files")
        self._dry_cb.setChecked(False)
        self._dry_cb.stateChanged.connect(self._sync)  # type: ignore[arg-type]
        body_layout.addWidget(self._dry_cb)

        # Output folder picker
        out_card = QFrame()
        out_card.setObjectName("Card")
        out_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
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
        body_layout.addWidget(out_card)

        body_layout.addStretch(1)

    def _make_row(self, key: str, title: str, subtitle: str, *,
                   default_checked: bool = True,
                   customize_callback=None,
                   customize_label: str = "Customize"):
        row = OptionRow()
        row.setAccessibleName(title)
        row.setAccessibleDescription(subtitle)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(14)
        cb = QCheckBox()
        cb.setChecked(default_checked)
        cb.setToolTip(f"Include {title.lower()} in this migration.")
        layout.addWidget(cb)
        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("OptionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("OptionSubtitle")
        subtitle_label.setWordWrap(False)
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)
        layout.addLayout(text_box, 1)
        badge = CountBadge("—")
        badge.setVisible(False)
        layout.addWidget(badge)
        customize_btn = None
        if customize_callback is not None:
            customize_btn = QPushButton(customize_label)
            customize_btn.setObjectName("QuietButton")
            customize_btn.setToolTip(f"Adjust {title.lower()} before export.")
            customize_btn.clicked.connect(customize_callback)  # type: ignore[arg-type]
            layout.addWidget(customize_btn)

        def toggle_from_row() -> None:
            if cb.isEnabled():
                cb.toggle()

        def on_checkbox_changed(_state: int) -> None:
            row.set_checked(cb.isChecked())
            self._sync()

        row.clicked.connect(toggle_from_row)  # type: ignore[arg-type]
        cb.stateChanged.connect(on_checkbox_changed)  # type: ignore[arg-type]
        row.set_checked(default_checked)
        row_tuple = (row, cb, badge, customize_btn)
        self._rows[key] = row_tuple
        return row_tuple

    def _pick_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Output folder", str(self._ctx.out_root))
        if chosen:
            self._ctx.out_root = Path(chosen)
            self._out_label.setText(str(self._ctx.out_root))

    def _sync(self) -> None:
        self._refresh_dependent_options()
        self._ctx.do_passwords = self._passwords_row[1].isChecked()
        self._ctx.do_bookmarks = self._bookmarks_row[1].isChecked()
        self._ctx.do_extensions = self._extensions_row[1].isChecked()
        self._ctx.do_cookies = self._cookies_row[1].isChecked()
        self._ctx.do_history = self._history_row[1].isChecked()
        self._ctx.do_autofill = self._autofill_row[1].isChecked()
        self._ctx.do_cards = self._cards_row[1].isChecked()
        self._ctx.do_search_engines = self._search_engines_row[1].isChecked()
        self._ctx.do_open_tabs = self._open_tabs_row[1].isChecked()
        self._ctx.do_downloads = self._downloads_row[1].isChecked()
        self._ctx.extensions_online = self._online_cb.isChecked()
        self._ctx.dry_run = self._dry_cb.isChecked()
        self._ctx.direct_write_passwords = self._direct_cb.isChecked()
        self._ctx.direct_write_cookies = self._direct_cookies_cb.isChecked()
        self._ctx.direct_write_history = self._direct_history_cb.isChecked()
        self._ctx.direct_write_open_tabs = self._direct_open_tabs_cb.isChecked()
        self._ctx.hibp_scan = self._hibp_cb.isChecked()
        self.canAdvanceChanged.emit(self.can_advance())

    # Suffix shown next to each badge — visits read better than "found"
    # for History; the rest are uniform.
    _COUNT_SUFFIX = {
        "history": "visits",
        "open_tabs": "tabs",
    }

    def set_counts(self, counts: dict[str, int]) -> None:
        """Update per-row count badges from a preview pass.

        Keys are item slugs (``passwords``, ``bookmarks``, ..., ``downloads``);
        unknown keys are ignored, and missing keys leave the existing badge
        alone. The dict version replaced the positional 5-arg signature when
        the Items step grew the five "advanced" categories.
        """
        for key, count in counts.items():
            row = self._rows.get(key)
            if row is None:
                continue
            suffix = self._COUNT_SUFFIX.get(key, "found")
            self._set_badge(row[2], f"{count:,} {suffix}")
        if self._ctx.source_uses_abe and not self._ctx.source_has_classic_key:
            self._set_row_available(
                self._rows["passwords"],
                False,
                "Disabled because this source profile only exposes App-Bound Encryption.",
            )
            self._set_row_available(
                self._rows["cookies"],
                False,
                "Disabled because this source profile only exposes App-Bound Encryption.",
            )

    @staticmethod
    def _set_badge(badge: CountBadge, text: str) -> None:
        badge.setText(text)
        badge.setVisible(True)

    def _set_row_available(self, row_tuple, enabled: bool, tooltip: str = "") -> None:
        row, cb = row_tuple[0], row_tuple[1]
        row.set_enabled_state(enabled, tooltip)
        cb.blockSignals(True)
        if not enabled:
            cb.setChecked(False)
        cb.setEnabled(enabled)
        cb.blockSignals(False)
        cb.setToolTip(tooltip or f"Include {row.accessibleName().lower()} in this migration.")
        row.set_checked(cb.isChecked())
        if len(row_tuple) > 3 and row_tuple[3] is not None:
            row_tuple[3].setEnabled(enabled)

    @staticmethod
    def _set_checkbox_available(cb: QCheckBox, enabled: bool, tooltip: str = "") -> None:
        cb.blockSignals(True)
        if not enabled:
            cb.setChecked(False)
        cb.setEnabled(enabled)
        cb.blockSignals(False)
        cb.setToolTip(tooltip)

    def _refresh_dependent_options(self) -> None:
        reverse = self._ctx.direction == MigrationContext.DIRECTION_REVERSE
        hibp_enabled = self._passwords_row[1].isChecked() and not reverse
        if not self._passwords_row[1].isChecked():
            hibp_tooltip = "Select passwords first."
        elif reverse:
            hibp_tooltip = "Reverse mode exports Firefox passwords without the breach check."
        else:
            hibp_tooltip = "Checks only the SHA-1 prefix through the k-anonymity API."
        self._set_checkbox_available(
            self._hibp_cb,
            hibp_enabled,
            hibp_tooltip,
        )
        self._online_cb.setEnabled(self._extensions_row[1].isChecked())
        self._online_cb.setToolTip(
            "Looks up public Firefox Add-ons metadata. Passwords and profile data stay local."
            if self._extensions_row[1].isChecked()
            else "Select extensions first."
        )
        direct_tooltip = (
            "Requires the matching category and a closed Firefox target profile."
        )
        reverse_tooltip = (
            "Reverse direction currently writes export files only; direct-write is disabled."
        )
        self._set_checkbox_available(
            self._direct_cb,
            self._passwords_row[1].isChecked() and not reverse,
            direct_tooltip if not reverse else reverse_tooltip,
        )
        self._set_checkbox_available(
            self._direct_cookies_cb,
            self._cookies_row[1].isChecked() and not reverse,
            direct_tooltip if not reverse else reverse_tooltip,
        )
        self._set_checkbox_available(
            self._direct_history_cb,
            self._history_row[1].isChecked() and not reverse,
            direct_tooltip if not reverse else reverse_tooltip,
        )
        self._set_checkbox_available(
            self._direct_open_tabs_cb,
            self._open_tabs_row[1].isChecked() and not reverse,
            direct_tooltip if not reverse else reverse_tooltip,
        )

    def can_advance(self) -> bool:
        return any(row[1].isChecked() for row in self._rows.values())

    def apply_context_defaults(self) -> None:
        """Push the migration context's per-flag defaults INTO the checkboxes.

        Called once after the wizard is built (settings → UI) and again
        whenever the user changes settings via the Settings dialog. The
        usual on_enter direction is widgets → ctx via :meth:`_sync`.
        """
        self._online_cb.setChecked(self._ctx.extensions_online)
        self._dry_cb.setChecked(self._ctx.dry_run)
        self._hibp_cb.setChecked(self._ctx.hibp_scan)
        self._refresh_dependent_options()

    def on_enter(self) -> None:
        self._sync()
        reverse = self._ctx.direction == MigrationContext.DIRECTION_REVERSE
        # Categories without a reverse implementation get disabled + unchecked.
        for row in (self._cookies_row, self._history_row, self._autofill_row,
                    self._cards_row, self._search_engines_row, self._open_tabs_row,
                    self._downloads_row):
            if reverse:
                self._set_row_available(
                    row,
                    False,
                    "Not yet supported in Firefox to Chromium direction (passwords, bookmarks, and extensions only).",
                )
            else:
                self._set_row_available(row, True)
        self._refresh_dependent_options()
        self._sync()

    def _customize_passwords(self) -> None:
        if not self._ctx.source:
            return
        from foxport.gui.dialogs import PasswordPreviewDialog
        dlg = PasswordPreviewDialog(
            self._ctx.source,
            selected_keys=self._ctx.password_include_keys,
            mask_passwords=self._ctx.mask_passwords_in_preview,
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

    def _customize_history(self) -> None:
        from foxport.gui.dialogs import HistoryFilterDialog
        dlg = HistoryFilterDialog(
            self._ctx.history_date_from_us,
            self._ctx.history_date_to_us,
            parent=self,
        )
        if dlg.exec():
            self._ctx.history_date_from_us, self._ctx.history_date_to_us = dlg.selected_range()


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
        self._tree.setAlternatingRowColors(True)
        self.add_content(self._tree, stretch=1)
        self._note = Banner("", variant="info")
        self.add_content(self._note)

    def on_enter(self) -> None:
        self._tree.clear()
        ctx = self._ctx
        ctx.counts = {}

        source_node = QTreeWidgetItem([f"Source: {ctx.source.label if ctx.source else '(manual)'}", ""])
        source_node.addChild(QTreeWidgetItem(
            ["Target", ctx.target.label if ctx.target else "(no target selected — files only)"]
        ))
        source_node.addChild(QTreeWidgetItem([
            "Direction",
            "Firefox → Chromium" if ctx.direction == MigrationContext.DIRECTION_REVERSE else "Chromium → Firefox",
        ]))
        source_node.addChild(QTreeWidgetItem(["Output", str(ctx.out_root)]))
        if ctx.dry_run:
            source_node.addChild(QTreeWidgetItem(["Mode", "DRY RUN (nothing will be written)"]))
        self._tree.addTopLevelItem(source_node)

        # Reverse mode: source is a FirefoxProfile, the chromium read helpers
        # don't apply. Show item categories with placeholder counts and tell
        # the user real counts will appear in the Run log.
        if ctx.direction == MigrationContext.DIRECTION_REVERSE:
            if ctx.do_passwords:
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    "Passwords",
                    "chrome-passwords.csv → Chrome Settings → Passwords → Import",
                ]))
            if ctx.do_bookmarks:
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    "Bookmarks",
                    "chrome-bookmarks.html → Chrome Bookmark Manager → Import",
                ]))
            if ctx.do_extensions:
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    "Extensions",
                    "chrome-extensions.html → click each Install on Chrome link",
                ]))
            source_node.setExpanded(True)
            self._note.set_variant("warn")
            self._note.set_text(
                "Counts will appear in the Run log. The source Firefox profile must be "
                "closed (NSS holds the same lock Firefox does)."
            )
            return

        if ctx.source:
            if ctx.do_passwords:
                count = sum(1 for _ in read_password_rows(ctx.source))
                ctx.counts["passwords"] = count
                node = QTreeWidgetItem([f"Passwords ({count:,})", "passwords.csv → about:logins"])
                self._tree.addTopLevelItem(node)
            if ctx.do_bookmarks:
                roots = read_bookmarks(ctx.source)
                count = _count_bookmarks(roots)
                ctx.counts["bookmarks"] = count
                node = QTreeWidgetItem([f"Bookmarks ({count:,})", "bookmarks.html → Library import"])
                for root in roots:
                    child = QTreeWidgetItem([f"   {root.name}", f"{_count_bookmarks([root])} entries"])
                    node.addChild(child)
                self._tree.addTopLevelItem(node)
                node.setExpanded(True)
            if ctx.do_extensions:
                extensions = read_extensions(ctx.source)
                ctx.counts["extensions"] = len(extensions)
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
                ctx.counts["cookies"] = cookie_count
                node = QTreeWidgetItem([f"Cookies ({cookie_count:,})", "cookies.sqlite → swap into closed Firefox profile"])
                self._tree.addTopLevelItem(node)
            if ctx.do_history:
                hist_urls, hist_visits = self._count_history(ctx.source)
                # History badge shows visit count — that's what gets migrated.
                ctx.counts["history"] = hist_visits
                node = QTreeWidgetItem(
                    [f"History ({hist_urls:,} URLs / {hist_visits:,} visits)",
                     "places.sqlite → swap into closed Firefox profile"],
                )
                self._tree.addTopLevelItem(node)
            if ctx.do_autofill:
                count = self._count_web_data(ctx.source, (
                    "SELECT COUNT(*) FROM autofill WHERE name <> '' AND value <> ''",
                ))
                ctx.counts["autofill"] = count
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    f"Form autofill ({count:,})",
                    "formhistory.sqlite -> closed Firefox profile",
                ]))
            if ctx.do_cards:
                count = self._count_web_data(ctx.source, (
                    "SELECT COUNT(*) FROM credit_cards",
                ))
                ctx.counts["cards"] = count
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    f"Saved cards ({count:,})",
                    "saved-cards.csv -> password-manager review/import",
                ]))
            if ctx.do_search_engines:
                count = self._count_web_data(ctx.source, (
                    "SELECT COUNT(*) FROM keywords WHERE keyword IS NOT NULL AND keyword <> ''",
                ))
                ctx.counts["search_engines"] = count
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    f"Search engines ({count:,})",
                    "search-engines.json + OpenSearch XML files",
                ]))
            if ctx.do_open_tabs:
                tabs, failures = self._count_open_tabs(ctx.source)
                ctx.counts["open_tabs"] = tabs
                detail = "recovery.jsonlz4 -> Firefox session restore"
                if failures:
                    detail += f" ({failures} warning(s))"
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    f"Open tabs ({tabs:,})",
                    detail,
                ]))
            if ctx.do_downloads:
                count = self._count_downloads(ctx.source)
                ctx.counts["downloads"] = count
                self._tree.addTopLevelItem(QTreeWidgetItem([
                    f"Downloads ({count:,})",
                    "downloads.csv -> portable reference",
                ]))

        source_node.setExpanded(True)

        # Network-activity disclosure: lists every optional outbound
        # endpoint and whether this run will hit it. Always present so the
        # user can confirm "no network" runs really won't make calls — a
        # disabled state is just as load-bearing as an enabled one.
        net_node = QTreeWidgetItem(["Network activity", ""])
        amo_enabled = ctx.extensions_online and ctx.do_extensions and ctx.direction == MigrationContext.DIRECTION_FORWARD
        net_node.addChild(QTreeWidgetItem([
            "  addons.mozilla.org",
            ("ENABLED — extension name/GUID lookup"
             if amo_enabled else "disabled"),
        ]))
        hibp_enabled = ctx.hibp_scan and ctx.do_passwords and ctx.direction == MigrationContext.DIRECTION_FORWARD
        net_node.addChild(QTreeWidgetItem([
            "  api.pwnedpasswords.com",
            ("ENABLED — k-anonymity prefix (SHA-1 first 5 chars)"
             if hibp_enabled else "disabled"),
        ]))
        net_node.addChild(QTreeWidgetItem([
            "  telemetry / crash / update",
            "off (no opt-in surface in v1.3)",
        ]))
        self._tree.addTopLevelItem(net_node)
        net_node.setExpanded(True)

        notes: list[str] = []
        has_warning = False
        if ctx.source_uses_abe:
            notes.append(
                "App-Bound Encryption detected on source — some newer passwords/cookies may fail to decrypt."
            )
            has_warning = True
        if ctx.target and is_firefox_profile_locked(ctx.target):
            notes.append("Target Firefox profile is locked — close Firefox before importing.")
            has_warning = True
        if ctx.do_cookies or ctx.do_history:
            notes.append("cookies.sqlite / places.sqlite must be swapped into a CLOSED Firefox profile.")
            has_warning = True
        notes.append("The source browser will not be modified.")
        self._note.set_variant("warn" if has_warning else "info")
        self._note.set_text("  ·  ".join(notes))

    def _count_cookies(self, profile: ChromiumProfile) -> int:
        for path in (profile.profile_dir / "Network" / "Cookies", profile.profile_dir / "Cookies"):
            if path.is_file():
                rows = _safe_sqlite_count(path, ("SELECT COUNT(*) FROM cookies",))
                if rows:
                    return rows[0]
        return 0

    def _count_history(self, profile: ChromiumProfile) -> tuple[int, int]:
        path = profile.profile_dir / "History"
        if not path.is_file():
            return 0, 0
        rows = _safe_sqlite_count(
            path,
            ("SELECT COUNT(*) FROM urls", "SELECT COUNT(*) FROM visits"),
        )
        if len(rows) < 2:
            return 0, 0
        return rows[0], rows[1]

    def _count_web_data(self, profile: ChromiumProfile, queries: tuple[str, ...]) -> int:
        path = profile.profile_dir / "Web Data"
        if not path.is_file():
            return 0
        rows = _safe_sqlite_count(path, queries)
        return rows[0] if rows else 0

    def _count_downloads(self, profile: ChromiumProfile) -> int:
        path = profile.profile_dir / "History"
        if not path.is_file():
            return 0
        rows = _safe_sqlite_count(path, ("SELECT COUNT(*) FROM downloads",))
        return rows[0] if rows else 0

    def _count_open_tabs(self, profile: ChromiumProfile) -> tuple[int, int]:
        import tempfile

        from foxport.migrate.open_tabs import migrate_open_tabs

        with tempfile.TemporaryDirectory(prefix="foxport_tabs_preview_") as tmp:
            result = migrate_open_tabs(profile, Path(tmp), dry_run=True)
        return result.tabs, len(result.failures)


# ----------------------------------------------------------- Step 5: Run

class RunPage(WizardPage):
    """Live progress + log + Done screen.

    Done-screen actions are generated from the artifact metadata below, so a
    new export category gets a button as soon as the worker emits it. Each
    button fires :pyattr:`artifactActionRequested` with ``(key, action_kind)``
    — ``action_kind`` is ``"open"`` (launch the file) or ``"reveal"`` (open
    the parent folder with the file selected, used for SQLite databases
    that aren't meant to be double-clicked).
    """

    # Declared order is the on-screen order. Keys mirror the worker `exports`
    # dict. Action kind: "open" launches the file; "reveal" opens the
    # containing folder with the file selected (use for *.sqlite where
    # double-clicking would otherwise launch a registered SQLite app).
    ARTIFACT_ACTIONS: list[tuple[str, str, str]] = [
        ("passwords", "Open passwords.csv", "open"),
        ("hibp", "Open compromised-passwords.txt", "open"),
        ("bookmarks", "Open bookmarks.html", "open"),
        ("extensions", "Open extensions.html", "open"),
        ("cookies", "Reveal cookies.sqlite", "reveal"),
        ("history", "Reveal places.sqlite", "reveal"),
        ("autofill", "Reveal formhistory.sqlite", "reveal"),
        # Reveal instead of open: saved-cards.csv contains plaintext PANs.
        # See manifest._DEFAULT_ACTION for the rationale.
        ("cards", "Reveal saved-cards.csv", "reveal"),
        ("search_engines", "Open search-engines.json", "open"),
        ("open_tabs", "Reveal recovery.jsonlz4", "reveal"),
        ("downloads", "Open downloads.csv", "open"),
    ]

    # Sentinel "key" the open-output-folder button emits.
    OUTPUT_FOLDER_KEY = "_out"
    # Sentinel "key" emitted by the "Save as snapshot..." Done button.
    CREATE_SNAPSHOT_KEY = "_snapshot"
    # Action kind for "Reveal backup" buttons; routed separately so
    # MainWindow can resolve the path from the backups map instead of the
    # exports map.
    BACKUP_ACTION = "reveal-backup"

    artifactActionRequested = pyqtSignal(str, str)  # (key, action_kind)

    def __init__(self, ctx: MigrationContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Run migration",
            "FoxPort will work through each selected category and report progress below.",
            parent,
        )
        self._ctx = ctx
        # Persistent dry-run banner — visible the whole time the user is on
        # the Run page in dry-run mode, so they can't mistake the "Done"
        # state for a real migration. Hidden by default; toggled on_enter().
        self._dry_banner = Banner(
            "DRY RUN — counts and decrypt-tests only. No files will be "
            "written. Uncheck dry-run on the Items step to perform a real "
            "migration.",
            variant="warn",
        )
        self._dry_banner.setVisible(False)
        self.add_content(self._dry_banner)
        self._status = QLabel("Ready to run")
        self._status.setObjectName("RunStatus")
        self.add_content(self._status)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setFormat("Ready")
        self.add_content(self._progress)

        self._summary = Banner("", variant="info")
        self._summary.setVisible(False)
        self.add_content(self._summary)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Migration details will appear here as each category completes.")
        self.add_content(self._log, stretch=1)

        # Done-screen action bar. Buttons are rebuilt on every set_done() so
        # newly-shipped artifact keys appear without code changes here. The
        # bar is hidden until set_done(ok=True, exports=non-empty).
        self._actions = QFrame()
        self._actions_layout = QHBoxLayout(self._actions)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(10)
        self._actions.setVisible(False)
        self.add_content(self._actions)
        # Track button widgets so reset() can dispose of them deterministically.
        self._action_buttons: list[QPushButton] = []
        # Direct-write backups keyed by item slug; set per run via
        # set_direct_write_backups() and consumed by set_done().
        self._direct_write_backups: dict[str, str] = {}

    def on_enter(self) -> None:
        self._dry_banner.setVisible(bool(self._ctx.dry_run))

    def append_log(self, text: str) -> None:
        self._log.appendPlainText(text)

    def _clear_action_buttons(self) -> None:
        for btn in self._action_buttons:
            btn.setParent(None)
        self._action_buttons.clear()
        # Remove the trailing stretch too if it's there; it gets re-added when
        # the next set_done() runs.
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def reset(self) -> None:
        self._log.clear()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("Ready")
        self._status.setText("Ready to run")
        self._summary.setVisible(False)
        self._actions.setVisible(False)
        self._clear_action_buttons()
        # Stale backups from a prior run would render incorrect Reveal
        # buttons after a Back -> Run sequence; clear on every reset.
        self._direct_write_backups = {}
        # Re-sync the dry-run banner in case the user changed the setting
        # between runs without leaving the Run page (rare but possible via
        # the Back → Items → Forward path).
        self._dry_banner.setVisible(bool(self._ctx.dry_run))

    def set_busy(self) -> None:
        self._progress.setRange(0, 0)
        self._progress.setFormat("Working…")
        self._status.setText("Preparing migration...")

    def set_step(self, current: int, total: int) -> None:
        if total <= 0:
            self.set_busy()
            return
        self._progress.setRange(0, total)
        self._progress.setValue(current)
        self._progress.setFormat(f"Step {current} of {total}")
        self._status.setText(f"Running step {current} of {total}")

    def set_direct_write_backups(self, backups: dict[str, str]) -> None:
        """Stash the per-category backup paths produced by direct-write so
        ``set_done`` can render "Reveal backup" buttons next to the
        matching artifact actions. Called once per run before ``set_done``.

        Empty string values mean "direct-write ran but there was no prior
        target file to back up" — we omit the button in that case rather
        than reveal a non-existent path.
        """

        self._direct_write_backups = {k: v for k, v in backups.items() if v}

    def set_done(self, ok: bool, summary: str, exports: dict[str, Path]) -> None:
        self._progress.setRange(0, 1)
        if ok:
            self._progress.setValue(1)
            self._progress.setFormat("Done")
            self._status.setText("Migration complete")
            self._summary.set_variant("success")
            self._summary.set_text(f"Export complete. Output folder: {summary}")
        else:
            self._progress.setValue(0)
            self._progress.setFormat("Failed")
            self._status.setText("Migration failed")
            self._summary.set_variant("error")
            self._summary.set_text(f"Migration failed: {summary}")
        self._summary.setVisible(True)
        self._clear_action_buttons()
        if ok:
            # Open-output-folder button always comes first when the run
            # produced any artifacts (or succeeded but emitted nothing in
            # dry-run mode; covered by the outer ok check).
            out_btn = QPushButton("Open output folder")
            out_btn.clicked.connect(
                lambda _checked=False, k=self.OUTPUT_FOLDER_KEY: self.artifactActionRequested.emit(k, "open")
            )  # type: ignore[arg-type]
            self._actions_layout.addWidget(out_btn)
            self._action_buttons.append(out_btn)
            for key, title, action_kind in self.ARTIFACT_ACTIONS:
                if key not in exports:
                    continue
                btn = QPushButton(title)
                # Bind key + action_kind at definition time so the lambda
                # captures the *current* iteration's values, not the last.
                btn.clicked.connect(
                    lambda _checked=False, k=key, a=action_kind: self.artifactActionRequested.emit(k, a)
                )  # type: ignore[arg-type]
                self._actions_layout.addWidget(btn)
                self._action_buttons.append(btn)
                # When direct-write produced a backup for this category,
                # surface a "Reveal backup" button right next to the
                # artifact button so a regret-undo is one click away.
                if key in self._direct_write_backups:
                    backup_btn = QPushButton(f"Reveal {key} backup")
                    backup_btn.clicked.connect(
                        lambda _checked=False, k=key: self.artifactActionRequested.emit(
                            k, self.BACKUP_ACTION,
                        )
                    )  # type: ignore[arg-type]
                    self._actions_layout.addWidget(backup_btn)
                    self._action_buttons.append(backup_btn)
            # Save as snapshot is always last so it sits at the end of the
            # row visually. Hidden when there's nothing in the output dir
            # to bundle (dry-run with no exports).
            if exports:
                snap_btn = QPushButton("Save as snapshot…")
                snap_btn.clicked.connect(
                    lambda _checked=False: self.artifactActionRequested.emit(
                        self.CREATE_SNAPSHOT_KEY, "snapshot",
                    )
                )  # type: ignore[arg-type]
                self._actions_layout.addWidget(snap_btn)
                self._action_buttons.append(snap_btn)
            self._actions_layout.addStretch(1)
            self._actions.setVisible(bool(self._action_buttons))
        else:
            self._actions.setVisible(False)
