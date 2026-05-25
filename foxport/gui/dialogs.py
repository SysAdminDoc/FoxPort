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
    QFrame,
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
from foxport.config import (
    Settings,
    config_path,
    reset_to_defaults,
    save_settings,
)
from foxport.crypto.dpapi import decrypt_value, load_master_key

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox


def prompt_snapshot_passphrase(
    parent: QWidget | None,
    *,
    mode: str = "create",
) -> str | None:
    """Ask the user for an optional snapshot passphrase.

    ``mode='create'`` lets an empty string through — that means "no
    encryption, plain ZIP". ``mode='restore'`` likewise lets empty
    through; the snapshot module decides whether the bundle requires
    a passphrase based on its magic bytes.

    Cancel returns ``None`` so callers can distinguish "user backed out"
    from "user chose no encryption".
    """

    prompt = (
        "Enter a passphrase to encrypt the snapshot, or leave blank for an unencrypted ZIP. "
        "PBKDF2-HMAC-SHA256 (200k iterations) -> AES-256-GCM."
        if mode == "create"
        else "Enter the passphrase that was used to encrypt this snapshot, or leave blank if it's a plain ZIP."
    )
    text, ok = QInputDialog.getText(
        parent,
        "Snapshot passphrase",
        prompt,
        QInputDialog.EchoMode.Password,
    )
    if not ok:
        return None
    return text


class RestoreInspectDialog(QDialog):
    """Pre-extract inspection for a .fxport bundle.

    The user picks the snapshot file, the dialog opens the manifest
    (decrypting first if the bundle is encrypted), shows the artifact list
    + per-file SHA-256, then offers Restore vs Cancel. Restore opens a
    second file picker for the (empty) target dir. Snapshot integrity is
    verified per-file before any byte hits the chosen target — a
    corrupted bundle fails fast.
    """

    def __init__(
        self,
        bundle_path: Path,
        *,
        passphrase: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Inspect FoxPort snapshot")
        self.resize(700, 480)
        self._bundle_path = bundle_path
        self._passphrase = passphrase
        self._chosen_out_dir: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(QLabel(f"Bundle: <code>{bundle_path}</code>"))

        # Read manifest WITHOUT extracting anything. The snapshot module
        # already streams the inner ZIP into memory, so this is cheap.
        from foxport.snapshot import _MAGIC_ENCRYPTED, _decrypt_bundle
        import zipfile as _zipfile
        import io as _io
        import json as _json

        try:
            blob = bundle_path.read_bytes()
            if blob.startswith(_MAGIC_ENCRYPTED):
                if not passphrase:
                    raise ValueError("encrypted bundle requires a passphrase")
                inner = _decrypt_bundle(blob, passphrase)
            else:
                inner = blob
            with _zipfile.ZipFile(_io.BytesIO(inner)) as zf:
                manifest = _json.loads(zf.read("manifest.json").decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — surface to the user
            err = QLabel(f"Could not open snapshot: {exc}")
            err.setStyleSheet("color: #f38ba8;")
            err.setWordWrap(True)
            layout.addWidget(err)
            close = QPushButton("Close")
            close.clicked.connect(self.reject)  # type: ignore[arg-type]
            layout.addWidget(close)
            return

        meta_lines = [
            f"Created: <code>{manifest.get('created_iso', '?')}</code>",
            f"FoxPort version: <code>{manifest.get('foxport_version', '?')}</code>",
            f"Source: <code>{manifest.get('source_label', '?')}</code>",
            f"Target: <code>{manifest.get('target_label', '?')}</code>",
            f"Encrypted: <code>{manifest.get('encrypted', False)}</code>",
        ]
        meta = QLabel("<br>".join(meta_lines))
        meta.setStyleSheet("color: #cdd6f4;")
        meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(meta)

        # File list with SHA-256 prefixes so the user can spot anything
        # suspicious before clicking Restore.
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["File", "Size", "SHA-256"])
        self._tree.setColumnWidth(0, 340)
        self._tree.setColumnWidth(1, 90)
        for entry in manifest.get("files", []):
            self._tree.addTopLevelItem(QTreeWidgetItem([
                entry.get("path", "?"),
                f"{entry.get('size', 0):,} B",
                (entry.get("sha256", "") or "")[:16] + "...",
            ]))
        layout.addWidget(self._tree, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel,
        )
        self._restore_btn = QPushButton("Restore…")
        self._restore_btn.setObjectName("PrimaryButton")
        self._restore_btn.clicked.connect(self._on_restore)  # type: ignore[arg-type]
        buttons.addButton(self._restore_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        layout.addWidget(buttons)

    def _on_restore(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Restore into folder (must be empty)",
            str(self._bundle_path.parent),
        )
        if not chosen:
            return
        target = Path(chosen)
        # Non-empty refusal is the same policy as the CLI --overwrite
        # default. The GUI surfaces it as a question instead of just
        # bailing — the user can pick a fresh folder without re-entering
        # the passphrase.
        if target.exists() and any(target.iterdir()):
            answer = QMessageBox.question(
                self, "FoxPort",
                f"{target} is not empty.\n\n"
                "Overwrite existing files with the bundle contents?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        else:
            overwrite = False

        from foxport.snapshot import restore_snapshot
        try:
            manifest = restore_snapshot(
                self._bundle_path, target,
                passphrase=self._passphrase or None,
                overwrite=overwrite,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "FoxPort",
                f"Restore failed: {exc}")
            return
        self._chosen_out_dir = target
        QMessageBox.information(
            self, "FoxPort",
            f"Restored {len(manifest.files)} file(s) into {target}.",
        )
        self.accept()

    def chosen_out_dir(self) -> Path | None:
        return self._chosen_out_dir


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
        mask_passwords: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview & filter passwords")
        self.resize(820, 560)
        self._all_rows: list[PasswordRow] = []
        self._row_visible: list[bool] = []
        self._plaintext: dict[int, str] = {}
        self._show_all = not mask_passwords
        # Persisted set of "<origin>\x00<username>" keys the user has kept ticked.
        # Empty set = include everything (default).
        self._selected_keys: set[str] = set(selected_keys) if selected_keys else set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QLabel(
            "Tick the rows to include in the export. Use the filter to search "
            "by URL or username. Use the visibility button to reveal or mask "
            "passwords while reviewing."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #a6adc8;")
        layout.addWidget(header)

        mask_row = QHBoxLayout()
        mask_row.addStretch(1)
        self._show_all_btn = QPushButton("Hide passwords" if self._show_all else "Show passwords")
        self._show_all_btn.setCheckable(True)
        self._show_all_btn.setChecked(self._show_all)
        self._show_all_btn.toggled.connect(self._toggle_show_all)  # type: ignore[arg-type]
        mask_row.addWidget(self._show_all_btn)
        layout.addLayout(mask_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Search:"))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search URL or username")
        self._filter.textChanged.connect(self._refresh_filter)  # type: ignore[arg-type]
        filter_row.addWidget(self._filter, 1)
        self._all_btn = QPushButton("Select all visible")
        self._none_btn = QPushButton("Deselect all visible")
        self._all_btn.clicked.connect(lambda: self._set_visible_checked(True))   # type: ignore[arg-type]
        self._none_btn.clicked.connect(lambda: self._set_visible_checked(False))  # type: ignore[arg-type]
        filter_row.addWidget(self._all_btn)
        filter_row.addWidget(self._none_btn)
        layout.addLayout(filter_row)

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
        self._show_all_btn.setText("Hide passwords" if checked else "Show passwords")
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
            self._table.setItem(
                r_idx,
                3,
                QTableWidgetItem(plaintext if self._show_all else self._mask(plaintext)),
            )
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
            f"{visible:,} of {total:,} matching filter · {selected:,} selected for export"
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


def _chrome_us_to_qdate(value: int) -> QDate:
    """Convert Chrome WebKit microseconds since 1601-01-01 UTC to QDate."""
    import datetime as _dt
    unix_us = value - _CHROME_EPOCH_OFFSET_US
    py_dt = _dt.datetime.fromtimestamp(unix_us / 1_000_000, tz=_dt.timezone.utc)
    return QDate(py_dt.year, py_dt.month, py_dt.day)


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

        if existing_from_us is not None and existing_to_us is not None:
            self._preset.setCurrentIndex(len(self.PRESETS) - 1)
            self._from_edit.setDate(_chrome_us_to_qdate(existing_from_us))
            self._to_edit.setDate(_chrome_us_to_qdate(existing_to_us))
            self._set_custom_enabled(True)
        else:
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

        defaults_label = QLabel("Export defaults")
        defaults_label.setObjectName("SectionLabel")
        layout.addWidget(defaults_label)

        defaults_card = QFrame()
        defaults_card.setObjectName("Card")
        defaults_layout = QVBoxLayout(defaults_card)
        defaults_layout.setContentsMargins(16, 14, 16, 14)
        defaults_layout.setSpacing(10)

        path_label = QLabel(f"Settings file: <code>{config_path()}</code>")
        path_label.setStyleSheet("color: #a6adc8;")
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        defaults_layout.addWidget(path_label)

        # Output dir row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output folder:"))
        self._out_edit = QLineEdit(settings.output_dir or "")
        self._out_edit.setPlaceholderText(str(__import__("pathlib").Path.home() / "Documents" / "FoxPort"))
        out_row.addWidget(self._out_edit, 1)
        self._out_btn = QPushButton("Choose…")
        self._out_btn.clicked.connect(self._pick_dir)  # type: ignore[arg-type]
        out_row.addWidget(self._out_btn)
        defaults_layout.addLayout(out_row)

        # Behavior checkboxes
        self._mask_cb = QCheckBox("Mask passwords in the preview dialog by default")
        self._mask_cb.setChecked(settings.mask_passwords_in_preview)
        defaults_layout.addWidget(self._mask_cb)

        self._amo_cb = QCheckBox("Allow online Add-ons lookup for unknown extensions by default")
        self._amo_cb.setChecked(settings.allow_online_amo_lookup)
        defaults_layout.addWidget(self._amo_cb)

        self._dry_cb = QCheckBox("Run in dry-run mode by default (count + decrypt-test, no writes)")
        self._dry_cb.setChecked(settings.default_dry_run)
        defaults_layout.addWidget(self._dry_cb)

        layout.addWidget(defaults_card)

        privacy_label = QLabel("Privacy checks")
        privacy_label.setObjectName("SectionLabel")
        layout.addWidget(privacy_label)

        privacy_card = QFrame()
        privacy_card.setObjectName("Card")
        privacy_layout = QVBoxLayout(privacy_card)
        privacy_layout.setContentsMargins(16, 14, 16, 14)
        privacy_layout.setSpacing(10)

        self._hibp_cb = QCheckBox(
            "Check passwords against haveibeenpwned.com by default (k-anonymity API)"
        )
        self._hibp_cb.setChecked(settings.hibp_scan_default)
        privacy_layout.addWidget(self._hibp_cb)

        # Future-wired flags (Glean / Sentry). Off + advisory.
        self._telemetry_cb = QCheckBox(
            "Send anonymous usage metrics (category counts, no URLs) — v1.3+ feature, off until then"
        )
        self._telemetry_cb.setChecked(settings.telemetry_opt_in)
        self._telemetry_cb.setEnabled(False)
        privacy_layout.addWidget(self._telemetry_cb)

        self._crash_cb = QCheckBox(
            "Send crash reports (no user data) — v1.3+ feature, off until then"
        )
        self._crash_cb.setChecked(settings.crash_reporting_opt_in)
        self._crash_cb.setEnabled(False)
        privacy_layout.addWidget(self._crash_cb)

        layout.addWidget(privacy_card)

        # Advanced section — surfaces the NSS path override (previously only
        # available as the FOXPORT_NSS_PATH env var) plus the Reset action.
        advanced_label = QLabel("Advanced")
        advanced_label.setObjectName("SectionLabel")
        layout.addWidget(advanced_label)

        advanced_card = QFrame()
        advanced_card.setObjectName("Card")
        advanced_layout = QVBoxLayout(advanced_card)
        advanced_layout.setContentsMargins(16, 14, 16, 14)
        advanced_layout.setSpacing(10)

        nss_help = QLabel(
            "Path to a portable Firefox's nss3.dll / libnss3.dylib / libnss3.so. "
            "Leave blank to autodetect from the standard install locations. "
            "The FOXPORT_NSS_PATH environment variable always overrides this field."
        )
        nss_help.setStyleSheet("color: #a6adc8;")
        nss_help.setWordWrap(True)
        advanced_layout.addWidget(nss_help)

        nss_row = QHBoxLayout()
        nss_row.addWidget(QLabel("NSS path:"))
        self._nss_edit = QLineEdit(settings.nss_path_override or "")
        self._nss_edit.setPlaceholderText("(autodetect)")
        nss_row.addWidget(self._nss_edit, 1)
        nss_btn = QPushButton("Choose…")
        nss_btn.clicked.connect(self._pick_nss)  # type: ignore[arg-type]
        nss_row.addWidget(nss_btn)
        advanced_layout.addLayout(nss_row)

        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setObjectName("QuietButton")
        reset_btn.clicked.connect(self._reset)  # type: ignore[arg-type]
        advanced_layout.addWidget(reset_btn)

        layout.addWidget(advanced_card)

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

    def _pick_nss(self) -> None:
        """File picker scoped to ``nss3`` library files for the target browser.

        The picker filter lets the user spot the right file inside a
        portable Firefox install; it doesn't validate that the chosen file
        is actually an NSS library (that happens at session-open time via
        the version guard).
        """

        from pathlib import Path
        start = self._nss_edit.text() or str(Path.home())
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Pick nss3 library",
            start,
            "NSS library (nss3.dll libnss3.dylib libnss3.so);;All files (*)",
        )
        if chosen:
            self._nss_edit.setText(chosen)

    def _reset(self) -> None:
        """Replace the current Settings with the v1.3 defaults + persist.

        Closes the dialog with ``Accepted`` so the caller picks up the new
        Settings via :meth:`settings`. Configurations the user has built
        up over time (HIBP defaults, output dirs, NSS overrides) all
        return to factory values.
        """

        self._settings = reset_to_defaults()
        self.accept()

    def _save(self) -> None:
        self._settings.output_dir = self._out_edit.text().strip()
        self._settings.mask_passwords_in_preview = self._mask_cb.isChecked()
        self._settings.allow_online_amo_lookup = self._amo_cb.isChecked()
        self._settings.default_dry_run = self._dry_cb.isChecked()
        self._settings.hibp_scan_default = self._hibp_cb.isChecked()
        self._settings.nss_path_override = self._nss_edit.text().strip()
        # Future flags persist current value (disabled checkbox doesn't change it).
        save_settings(self._settings)
        self.accept()

    def settings(self) -> Settings:
        return self._settings
