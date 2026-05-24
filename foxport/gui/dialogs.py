"""Preview / filter dialogs surfaced from the Items wizard step."""

from __future__ import annotations

from typing import Iterable

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from foxport.browsers.chromium import (
    BookmarkNode,
    PasswordRow,
    read_bookmarks,
    read_password_rows,
)
from foxport.browsers.detect import ChromiumProfile
from foxport.config import Settings, config_path, save_settings
from foxport.crypto.dpapi import decrypt_value, load_master_key

from PyQt6.QtWidgets import QFileDialog, QInputDialog


def prompt_master_password(parent: QWidget | None, profile_label: str) -> str | None:
    """Show a one-shot password dialog. Returns the entered string, or None on Cancel."""
    text, ok = QInputDialog.getText(
        parent,
        "Master password required",
        f"The Firefox profile {profile_label} has a master password set.\n"
        "Enter it to decrypt logins (it never leaves this machine).",
        QInputDialog.EchoMode.Password,
    )
    if not ok:
        return None
    return text


class PasswordPreviewDialog(QDialog):
    """Live table of decrypted logins with search + per-row checkboxes.

    Decryption runs at open-time on the calling thread. For large vaults
    (>5,000 entries) this can take a second or two; the dialog stays
    responsive thanks to ``QApplication.processEvents()`` during fill.
    """

    def __init__(
        self,
        profile: ChromiumProfile,
        selected_keys: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview & filter passwords")
        self.resize(820, 560)
        self._all_rows: list[PasswordRow] = []
        self._row_visible: list[bool] = []
        # Persisted set of "<origin>\x00<username>" keys the user has kept ticked.
        # Empty set = include everything (default).
        self._selected_keys: set[str] = set(selected_keys) if selected_keys else set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QLabel(
            "Tick the rows to include in the export. Use the filter to search "
            "by URL or username. Passwords are masked by default — click the "
            "eye in each row to reveal."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #a6adc8;")
        layout.addWidget(header)

        mask_row = QHBoxLayout()
        mask_row.addStretch(1)
        self._show_all_btn = QPushButton("Show all passwords")
        self._show_all_btn.setCheckable(True)
        self._show_all_btn.toggled.connect(self._toggle_show_all)  # type: ignore[arg-type]
        mask_row.addWidget(self._show_all_btn)
        layout.addLayout(mask_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Search:"))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("URL or username substring")
        self._filter.textChanged.connect(self._refresh_filter)  # type: ignore[arg-type]
        filter_row.addWidget(self._filter, 1)
        self._all_btn = QPushButton("Select all visible")
        self._none_btn = QPushButton("Deselect all visible")
        self._all_btn.clicked.connect(lambda: self._set_visible_checked(True))   # type: ignore[arg-type]
        self._none_btn.clicked.connect(lambda: self._set_visible_checked(False))  # type: ignore[arg-type]
        filter_row.addWidget(self._all_btn)
        filter_row.addWidget(self._none_btn)
        layout.addLayout(filter_row)

        self._plaintext: dict[int, str] = {}
        self._show_all = False
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Include", "URL", "Username", "Password"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self._count_label)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)  # type: ignore[arg-type]
        self._buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        layout.addWidget(self._buttons)

        self._populate(profile)
        self._refresh_count()

    @staticmethod
    def _key_for(row: PasswordRow) -> str:
        return f"{row.origin_url}\x00{row.username}"

    @staticmethod
    def _mask(plaintext: str) -> str:
        if not plaintext:
            return ""
        # Show first/last char so the user can sanity-check; mask the rest.
        if len(plaintext) <= 2:
            return "•" * len(plaintext)
        return plaintext[0] + "•" * (len(plaintext) - 2) + plaintext[-1]

    def _toggle_show_all(self, checked: bool) -> None:
        self._show_all = checked
        self._show_all_btn.setText("Hide passwords" if checked else "Show all passwords")
        for r_idx, plain in self._plaintext.items():
            item = self._table.item(r_idx, 3)
            if item is None:
                continue
            item.setText(plain if checked else self._mask(plain))

    def _populate(self, profile: ChromiumProfile) -> None:
        try:
            key = load_master_key(profile.local_state, browser_display=profile.browser)
        except Exception as exc:  # noqa: BLE001
            self._table.setRowCount(1)
            self._table.setItem(0, 0, QTableWidgetItem(""))
            self._table.setItem(0, 1, QTableWidgetItem(f"Decryption failed: {exc}"))
            self._table.setSpan(0, 1, 1, 3)
            return
        from PyQt6.QtWidgets import QApplication

        rows = list(read_password_rows(profile))
        self._all_rows = rows
        self._table.setRowCount(len(rows))
        # If we have no prior selection, default to include-all.
        defaults_include_all = not self._selected_keys
        for r_idx, row in enumerate(rows):
            try:
                plaintext = decrypt_value(row.password_blob, key) if row.password_blob else ""
            except Exception:  # noqa: BLE001
                plaintext = "(decrypt failed)"
            key_str = self._key_for(row)
            included = defaults_include_all or (key_str in self._selected_keys)
            cb = QCheckBox()
            cb.setChecked(included)
            cb.setProperty("rowKey", key_str)
            cb.stateChanged.connect(self._on_checkbox_changed)  # type: ignore[arg-type]
            self._table.setCellWidget(r_idx, 0, cb)
            self._table.setItem(r_idx, 1, QTableWidgetItem(row.origin_url))
            self._table.setItem(r_idx, 2, QTableWidgetItem(row.username))
            self._plaintext[r_idx] = plaintext
            self._table.setItem(r_idx, 3, QTableWidgetItem(self._mask(plaintext)))
            self._row_visible.append(True)
            if r_idx % 200 == 0:
                QApplication.processEvents()
        if defaults_include_all:
            self._selected_keys = {self._key_for(r) for r in rows}

    def _on_checkbox_changed(self, _state: int) -> None:
        # Rebuild _selected_keys from current checkbox state on every change.
        from PyQt6.QtWidgets import QCheckBox
        selected: set[str] = set()
        for r_idx in range(self._table.rowCount()):
            cb = self._table.cellWidget(r_idx, 0)
            if isinstance(cb, QCheckBox) and cb.isChecked():
                key_str = cb.property("rowKey")
                if key_str:
                    selected.add(str(key_str))
        self._selected_keys = selected
        self._refresh_count()

    def _refresh_filter(self, text: str) -> None:
        needle = text.lower().strip()
        for r_idx in range(self._table.rowCount()):
            url_item = self._table.item(r_idx, 1)
            user_item = self._table.item(r_idx, 2)
            url = url_item.text().lower() if url_item else ""
            user = user_item.text().lower() if user_item else ""
            visible = (not needle) or (needle in url) or (needle in user)
            self._table.setRowHidden(r_idx, not visible)
        self._refresh_count()

    def _set_visible_checked(self, checked: bool) -> None:
        from PyQt6.QtWidgets import QCheckBox
        for r_idx in range(self._table.rowCount()):
            if self._table.isRowHidden(r_idx):
                continue
            cb = self._table.cellWidget(r_idx, 0)
            if isinstance(cb, QCheckBox):
                cb.setChecked(checked)
        # _on_checkbox_changed fires for each, which rebuilds the key set + count.

    def _refresh_count(self) -> None:
        total = self._table.rowCount()
        visible = sum(1 for r in range(total) if not self._table.isRowHidden(r))
        selected = len(self._selected_keys)
        self._count_label.setText(
            f"{visible} of {total} matching filter · {selected} selected for export"
        )

    def selected_keys(self) -> set[str]:
        """Final include set (each entry is ``f'{origin_url}\\x00{username}'``)."""
        return set(self._selected_keys)


class BookmarkFilterDialog(QDialog):
    """Folder-tree picker so the user can untick branches they don't want."""

    def __init__(
        self,
        profile: ChromiumProfile,
        excluded: set[tuple[str, ...]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Filter bookmark folders")
        self.resize(620, 540)
        self._excluded: set[tuple[str, ...]] = set(excluded) if excluded else set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = QLabel(
            "Untick any folders you don't want to include in bookmarks.html. "
            "URLs (leaf bookmarks) are always included if their containing folder is."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #a6adc8;")
        layout.addWidget(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Folder", "URLs"])
        self._tree.setColumnWidth(0, 420)
        self._tree.itemChanged.connect(self._on_item_changed)  # type: ignore[arg-type]
        layout.addWidget(self._tree, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)  # type: ignore[arg-type]
        self._buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        layout.addWidget(self._buttons)

        self._suspend_signals = True
        for root in read_bookmarks(profile):
            self._tree.addTopLevelItem(self._build_node(root, [], is_root=True))
        self._tree.expandToDepth(1)
        self._suspend_signals = False

    def _build_node(
        self,
        node: BookmarkNode,
        parent_path: list[str],
        *,
        is_root: bool = False,
    ) -> QTreeWidgetItem:
        url_count = self._count_urls(node)
        item = QTreeWidgetItem([node.name, str(url_count)])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        path = parent_path + [node.name]
        # Roots can't be filtered out; show them ticked + disabled.
        if is_root:
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        else:
            included = tuple(path) not in self._excluded
            item.setCheckState(0, Qt.CheckState.Checked if included else Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, tuple(path))
        for child in node.children:
            if child.kind == "folder":
                item.addChild(self._build_node(child, path))
        return item

    @staticmethod
    def _count_urls(node: BookmarkNode) -> int:
        if node.kind == "url":
            return 1
        return sum(BookmarkFilterDialog._count_urls(c) for c in node.children)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._suspend_signals:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, tuple):
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self._excluded.discard(path)
        else:
            self._excluded.add(path)

    def excluded_paths(self) -> set[tuple[str, ...]]:
        return set(self._excluded)


# Chrome WebKit µs since 1601-01-01 UTC for the Unix epoch.
_CHROME_EPOCH_OFFSET_US = 11_644_473_600 * 1_000_000


def _qdate_to_chrome_us(qdate: QDate, *, end_of_day: bool = False) -> int:
    """Convert a ``QDate`` to Chrome WebKit microseconds since 1601-01-01 UTC."""
    import datetime as _dt
    py_dt = _dt.datetime(qdate.year(), qdate.month(), qdate.day(), tzinfo=_dt.timezone.utc)
    if end_of_day:
        py_dt = py_dt.replace(hour=23, minute=59, second=59, microsecond=999_999)
    unix_us = int(py_dt.timestamp() * 1_000_000)
    return unix_us + _CHROME_EPOCH_OFFSET_US


class HistoryFilterDialog(QDialog):
    """Pick a time window for history migration.

    Presets: Last 7 / 30 / 90 days, last 12 months, All. Custom: two date
    pickers. Returns Chrome WebKit microseconds (since 1601) for the
    migrator, which is the native unit on disk.
    """

    PRESETS = [
        ("All history (no filter)", None),
        ("Last 7 days", 7),
        ("Last 30 days", 30),
        ("Last 90 days", 90),
        ("Last 12 months", 365),
        ("Custom range", -1),
    ]

    def __init__(
        self,
        existing_from_us: int | None,
        existing_to_us: int | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Filter browsing history by date")
        self.resize(440, 220)
        self._from_us = existing_from_us
        self._to_us = existing_to_us

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QLabel(
            "Only visits within the selected range are migrated. URLs whose "
            "last visit is outside the range are skipped entirely."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #a6adc8;")
        layout.addWidget(header)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Range:"))
        self._preset = QComboBox()
        for label, _ in self.PRESETS:
            self._preset.addItem(label)
        self._preset.currentIndexChanged.connect(self._on_preset_changed)  # type: ignore[arg-type]
        preset_row.addWidget(self._preset, 1)
        layout.addLayout(preset_row)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("From:"))
        self._from_edit = QDateEdit(calendarPopup=True)
        self._from_edit.setDate(QDate.currentDate().addYears(-1))
        custom_row.addWidget(self._from_edit)
        custom_row.addSpacing(10)
        custom_row.addWidget(QLabel("To:"))
        self._to_edit = QDateEdit(calendarPopup=True)
        self._to_edit.setDate(QDate.currentDate())
        custom_row.addWidget(self._to_edit)
        custom_row.addStretch(1)
        layout.addLayout(custom_row)
        layout.addStretch(1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)  # type: ignore[arg-type]
        self._buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        layout.addWidget(self._buttons)

        # Default preset = All
        self._preset.setCurrentIndex(0)
        self._set_custom_enabled(False)

    def _set_custom_enabled(self, enabled: bool) -> None:
        self._from_edit.setEnabled(enabled)
        self._to_edit.setEnabled(enabled)

    def _on_preset_changed(self, idx: int) -> None:
        _, days = self.PRESETS[idx]
        if days is None or days == -1:
            self._set_custom_enabled(days == -1)
            if days == -1:
                self._from_edit.setDate(QDate.currentDate().addYears(-1))
                self._to_edit.setDate(QDate.currentDate())
        else:
            self._set_custom_enabled(False)
            self._from_edit.setDate(QDate.currentDate().addDays(-days))
            self._to_edit.setDate(QDate.currentDate())

    def selected_range(self) -> tuple[int | None, int | None]:
        """Return ``(date_from_us, date_to_us)`` for the migrator.

        Returns ``(None, None)`` for the "All history" preset.
        """
        idx = self._preset.currentIndex()
        _, days = self.PRESETS[idx]
        if days is None:
            return None, None
        return (
            _qdate_to_chrome_us(self._from_edit.date()),
            _qdate_to_chrome_us(self._to_edit.date(), end_of_day=True),
        )


class SettingsDialog(QDialog):
    """User-facing FoxPort preferences. Persists to :func:`config_path`."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FoxPort Settings")
        self.resize(560, 420)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        path_label = QLabel(f"Settings file: <code>{config_path()}</code>")
        path_label.setStyleSheet("color: #a6adc8;")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(path_label)

        # Output dir row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output folder:"))
        self._out_edit = QLineEdit(settings.output_dir or "")
        self._out_edit.setPlaceholderText(str(__import__("pathlib").Path.home() / "Documents" / "FoxPort"))
        out_row.addWidget(self._out_edit, 1)
        self._out_btn = QPushButton("Choose…")
        self._out_btn.clicked.connect(self._pick_dir)  # type: ignore[arg-type]
        out_row.addWidget(self._out_btn)
        layout.addLayout(out_row)

        # Behavior checkboxes
        self._mask_cb = QCheckBox("Mask passwords in the preview dialog by default")
        self._mask_cb.setChecked(settings.mask_passwords_in_preview)
        layout.addWidget(self._mask_cb)

        self._amo_cb = QCheckBox("Allow online AMO lookup for unknown extensions by default")
        self._amo_cb.setChecked(settings.allow_online_amo_lookup)
        layout.addWidget(self._amo_cb)

        self._dry_cb = QCheckBox("Run in dry-run mode by default (count + decrypt-test, no writes)")
        self._dry_cb.setChecked(settings.default_dry_run)
        layout.addWidget(self._dry_cb)

        self._hibp_cb = QCheckBox(
            "Check passwords against haveibeenpwned.com by default (k-anonymity API)"
        )
        self._hibp_cb.setChecked(settings.hibp_scan_default)
        layout.addWidget(self._hibp_cb)

        layout.addSpacing(6)

        # Future-wired flags (Glean / Sentry). Off + advisory.
        self._telemetry_cb = QCheckBox(
            "Send anonymous usage metrics (category counts, no URLs) — v1.3+ feature, off until then"
        )
        self._telemetry_cb.setChecked(settings.telemetry_opt_in)
        self._telemetry_cb.setEnabled(False)
        layout.addWidget(self._telemetry_cb)

        self._crash_cb = QCheckBox(
            "Send crash reports (no user data) — v1.3+ feature, off until then"
        )
        self._crash_cb.setChecked(settings.crash_reporting_opt_in)
        self._crash_cb.setEnabled(False)
        layout.addWidget(self._crash_cb)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)  # type: ignore[arg-type]
        buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        layout.addWidget(buttons)

    def _pick_dir(self) -> None:
        from pathlib import Path
        start = self._out_edit.text() or str(Path.home() / "Documents")
        chosen = QFileDialog.getExistingDirectory(self, "Output folder", start)
        if chosen:
            self._out_edit.setText(chosen)

    def _save(self) -> None:
        self._settings.output_dir = self._out_edit.text().strip()
        self._settings.mask_passwords_in_preview = self._mask_cb.isChecked()
        self._settings.allow_online_amo_lookup = self._amo_cb.isChecked()
        self._settings.default_dry_run = self._dry_cb.isChecked()
        self._settings.hibp_scan_default = self._hibp_cb.isChecked()
        # Future flags persist current value (disabled checkbox doesn't change it).
        save_settings(self._settings)
        self.accept()

    def settings(self) -> Settings:
        return self._settings
