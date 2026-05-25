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
    read_extensions,
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
from foxport.migrate.extension_settings import (
    SUPPORTED_EXTENSION_SETTINGS,
    installed_supported_settings,
)
from foxport.telemetry import TELEMETRY_HOST

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


def _try_read_inner_run_manifest(zf) -> dict | None:
    """Return the per-run ``manifest.json`` from inside the snapshot ZIP.

    v1.3+ migration runs emit a ``manifest.json`` next to ``README.txt``
    inside the output folder; that file is bundled verbatim into the
    snapshot ZIP. Older bundles (or snapshots built from non-migration
    folders) don't have it — return ``None`` and the inspect dialog
    skips the "Run details" section.

    The outer ``manifest.json`` (the snapshot's own manifest) lives at
    the archive root; the run manifest lives one level deeper. We
    walk every name to find it without making assumptions about the
    timestamped run-folder prefix.
    """

    import json as _json
    for name in zf.namelist():
        # archive root manifest.json is the snapshot's own; skip it.
        if name == "manifest.json":
            continue
        if name.endswith("/manifest.json"):
            try:
                data = _json.loads(zf.read(name).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None
            # Sanity-check: the per-run shape carries a ``schema_version``
            # and an ``artifacts`` list; the outer snapshot shape doesn't.
            if isinstance(data, dict) and "schema_version" in data:
                return data
    return None


def _build_run_details_widget(run_manifest: dict) -> QWidget:
    """Render the per-run manifest fields as a compact two-column block.

    Surfaces direction, items requested, optional network usage,
    warnings, and a per-artifact sensitivity badge list. All values are
    HTML-escaped because the manifest is untrusted (came out of the
    bundle the user just opened).
    """

    from html import escape as _escape

    direction = run_manifest.get("direction", "forward")
    items = run_manifest.get("items_requested", []) or []
    network = run_manifest.get("network", {}) or {}
    warnings = run_manifest.get("warnings", []) or []
    artifacts = run_manifest.get("artifacts", []) or []

    items_str = ", ".join(_escape(str(i)) for i in items) if items else "(none)"
    network_lines = "; ".join(
        f"{_escape(k)}={_escape(v)}" for k, v in network.items()
    ) or "(none)"
    warning_html = ""
    if warnings:
        joined = "<br>".join(f"⚠ {_escape(str(w))}" for w in warnings)
        warning_html = (
            f"<br><span style='color: #f9e2af;'>Warnings:</span><br>{joined}"
        )

    sens_chips = ""
    if artifacts:
        chips = []
        for a in artifacts:
            key = _escape(str(a.get("key", "?")))
            sens = str(a.get("sensitivity", "normal"))
            color = {
                "sensitive": "#f38ba8",
                "financial": "#fab387",
                "normal": "#a6adc8",
            }.get(sens, "#a6adc8")
            chips.append(
                f"<span style='color: {color};'>{key}({_escape(sens)})</span>"
            )
        sens_chips = " · ".join(chips)

    label = QLabel(
        f"Direction: <code>{_escape(direction)}</code><br>"
        f"Items: <code>{items_str}</code><br>"
        f"Network: <code>{network_lines}</code><br>"
        f"Artifacts: {sens_chips or '(none)'}"
        f"{warning_html}"
    )
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setStyleSheet("color: #cdd6f4;")
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class RestoreInspectDialog(QDialog):
    """Pre-extract inspection for a .fxport bundle.

    The user picks the snapshot file, the dialog opens the manifest
    (decrypting first if the bundle is encrypted), shows the artifact list
    + per-file SHA-256, then offers Restore vs Cancel. Restore opens a
    second file picker for the (empty) target dir. Snapshot integrity is
    verified per-file before any byte hits the chosen target — a
    corrupted bundle fails fast.

    When the bundle carries an inner per-run ``manifest.json`` (v1.3+
    migration runs do), the dialog also surfaces direction / items /
    network usage / warnings / per-artifact sensitivity above the file
    list so the user sees what's about to land before clicking Restore.
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

        run_manifest: dict | None = None
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
                # v1.3+ migration runs drop a richer `manifest.json` next
                # to README.txt inside the snapshot. When the bundle was
                # created from one of those runs, surface it next to the
                # outer snapshot meta. Older bundles ship without it and
                # we just skip the section.
                run_manifest = _try_read_inner_run_manifest(zf)
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

        # Run details — only when the bundle carries a v1.3+ inner
        # manifest.json. Surfaces direction, items, network usage,
        # warnings, and per-artifact sensitivity so the user can see
        # what's about to land before they click Restore.
        if run_manifest is not None:
            run_label = QLabel("Run details")
            run_label.setStyleSheet(
                "color: #f9e2af; font-size: 13px; font-weight: 600; margin-top: 6px;"
            )
            layout.addWidget(run_label)
            layout.addWidget(_build_run_details_widget(run_manifest))

        # File list with SHA-256 prefixes so the user can spot anything
        # suspicious before clicking Restore. Sensitivity comes from the
        # inner run manifest when present so cards / passwords / cookies
        # get a visible label.
        sensitivity_by_path: dict[str, str] = {}
        if run_manifest is not None:
            for artifact in run_manifest.get("artifacts", []) or []:
                rel = artifact.get("path")
                sens = artifact.get("sensitivity")
                if isinstance(rel, str) and isinstance(sens, str):
                    sensitivity_by_path[rel] = sens
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["File", "Size", "SHA-256", "Sensitivity"])
        self._tree.setColumnWidth(0, 320)
        self._tree.setColumnWidth(1, 80)
        self._tree.setColumnWidth(2, 140)
        for entry in manifest.get("files", []):
            rel_path = entry.get("path", "?")
            self._tree.addTopLevelItem(QTreeWidgetItem([
                rel_path,
                f"{entry.get('size', 0):,} B",
                (entry.get("sha256", "") or "")[:16] + "...",
                sensitivity_by_path.get(rel_path, ""),
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


class FirstRunDialog(QDialog):
    """Trust + network disclosure shown the first time the GUI launches.

    Explains the four claims the security-conscious user wants verified
    before they hand FoxPort their browser profiles:

    1. Source profiles are read-only.
    2. Output files contain plaintext credentials and should be deleted
       after import.
    3. The outbound network requests are AMO, HIBP, and Glean telemetry —
       all opt-in, all able to be disabled before the run.
    4. There is no crash reporting or update check.

    The dialog also lets the user pre-set the two optional toggles
    (AMO + HIBP defaults) so they don't have to repeat the choice on
    every Items page. Persisted via ``Settings.allow_online_amo_lookup``
    and ``Settings.hibp_scan_default``.

    Acknowledging the dialog writes the current ISO timestamp into
    ``Settings.first_run_acked_iso`` so the next launch skips the
    dialog. A future version that materially changes the trust model
    (e.g. v1.4 turns on opt-in telemetry) re-prompts by bumping the
    trust revision.
    """

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to FoxPort")
        self.setModal(True)
        self.resize(600, 540)
        self._settings = settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        title = QLabel("Before you migrate, here's how FoxPort handles your data:")
        title.setStyleSheet("font-size: 15px; font-weight: 600; color: #f5c2e7;")
        title.setWordWrap(True)
        outer.addWidget(title)

        # Bulleted trust claims. The visual style is plain HTML so screen
        # readers announce each as a list item rather than a series of
        # paragraphs.
        claims = QLabel(
            "<ul style='margin-top: 0; color: #cdd6f4;'>"
            "<li><b>Source profile stays read-only.</b> We copy SQLite files"
            " to a temp dir before reading — your browser keeps every"
            " bookmark, password, and cookie exactly where it was.</li>"
            "<li><b>Output files contain plaintext credentials.</b>"
            " <code>passwords.csv</code>, <code>saved-cards.csv</code>, and"
            " <code>compromised-passwords.txt</code> are exported in the"
            " clear. Delete them after the import succeeds.</li>"
            "<li><b>Direct-write only into a closed Firefox profile</b>,"
            " always via atomic replace with a timestamped backup of the"
            " previous file.</li>"
            "<li><b>App-Bound Encryption</b> (Chrome 127+) needs the signed"
            " <code>foxport_abe.exe</code> sidecar — a UAC prompt will"
            " appear when it runs.</li>"
            "</ul>"
        )
        claims.setTextFormat(Qt.TextFormat.RichText)
        claims.setWordWrap(True)
        outer.addWidget(claims)

        # Network disclosure card. Two endpoints, both opt-in.
        net_label = QLabel("Optional network requests")
        net_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #f9e2af;")
        outer.addWidget(net_label)

        net = QLabel(
            "<table style='color: #cdd6f4;' cellpadding='4'>"
            "<tr><td><b>addons.mozilla.org</b></td><td>Looks up Firefox"
            " Add-ons that match your installed Chrome extensions. No"
            " personal data; just the AMO slug.</td></tr>"
            "<tr><td><b>api.pwnedpasswords.com</b></td><td>HIBP breach"
            " scan. <i>K-anonymity</i> — only the first five hex characters"
            " of each <code>SHA-1(password)</code> are sent; plaintext"
            " never leaves the box.</td></tr>"
            f"<tr><td><b>{TELEMETRY_HOST}</b></td><td>Optional Glean"
            " telemetry. Sends only selected category slugs, aggregate"
            " counts, direction, dry-run/direct-write flags, and outcome;"
            " never paths, profile labels, URLs, hostnames, usernames,"
            " filenames, or secrets.</td></tr>"
            "</table>"
        )
        net.setTextFormat(Qt.TextFormat.RichText)
        net.setWordWrap(True)
        outer.addWidget(net)

        self._amo_cb = QCheckBox("Allow the AMO lookup by default")
        self._amo_cb.setChecked(settings.allow_online_amo_lookup)
        self._hibp_cb = QCheckBox("Run the HIBP scan by default")
        self._hibp_cb.setChecked(settings.hibp_scan_default)
        self._telemetry_cb = QCheckBox("Send anonymous migration metrics by default")
        self._telemetry_cb.setChecked(settings.telemetry_opt_in)
        self._telemetry_cb.setToolTip(
            "Opt-in Glean telemetry to incoming.telemetry.mozilla.org. "
            "Only aggregate category counts and run flags are sent."
        )
        outer.addWidget(self._amo_cb)
        outer.addWidget(self._hibp_cb)
        outer.addWidget(self._telemetry_cb)

        no_crash_update = QLabel(
            "FoxPort still does not send crash reports or version update"
            " probes. Those stay wired off until separate opt-in surfaces"
            " ship."
        )
        no_crash_update.setStyleSheet("color: #94e2d5; font-style: italic;")
        no_crash_update.setWordWrap(True)
        outer.addWidget(no_crash_update)

        outer.addStretch(1)

        buttons = QDialogButtonBox()
        self._ok_btn = QPushButton("Got it — let's go")
        self._ok_btn.setObjectName("PrimaryButton")
        self._ok_btn.setDefault(True)
        buttons.addButton(self._ok_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        self._ok_btn.clicked.connect(self._save_and_accept)  # type: ignore[arg-type]
        outer.addWidget(buttons)

    def _save_and_accept(self) -> None:
        from datetime import datetime, timezone
        from foxport.config import _TRUST_REVISION
        self._settings.allow_online_amo_lookup = self._amo_cb.isChecked()
        self._settings.hibp_scan_default = self._hibp_cb.isChecked()
        self._settings.telemetry_opt_in = self._telemetry_cb.isChecked()
        self._settings.first_run_acked_iso = datetime.now(timezone.utc).isoformat()
        # Pin the revision so a future bump (e.g. v1.4 adds telemetry)
        # triggers a fresh re-prompt instead of silently inheriting the
        # ack made against an older trust surface.
        self._settings.first_run_acked_trust_revision = _TRUST_REVISION
        save_settings(self._settings)
        self.accept()

    def settings(self) -> Settings:
        return self._settings


class DirectWritePolicyDialog(QDialog):
    """Conflict-review modal shown between Preview and Run.

    Renders the pre-flight conflict counts (from
    :mod:`foxport.migrate.conflicts`) for each direct-write category
    the user enabled, alongside a dropdown of:

    * ``apply``       — current behavior (merge for passwords, replace
                        cookies/history/open_tabs after backup).
    * ``skip``        — leave the target untouched; staging output only.
    * ``backup-only`` — copy the target file aside but don't write new
                        content.

    Defaults to ``apply`` for every category so a user who clicks
    through gets exactly the v1.3.0–v1.3.2 behavior. Cancelling the
    dialog aborts the migration (returns to Preview); accepting writes
    the chosen policies onto the :class:`MigrationContext` so
    ``MainWindow._start_migration`` picks them up.

    The dialog runs the analyzers on the GUI thread; for typical
    profiles each call is a single read-only SQLite COUNT and finishes
    in <100 ms.
    """

    def __init__(
        self,
        ctx,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review direct-write changes")
        self.setModal(True)
        self.resize(680, 460)
        self._ctx = ctx
        self._dropdowns: dict[str, QComboBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        title = QLabel(
            "You enabled direct-write for one or more categories. Pick a "
            "policy per category — the default keeps the v1.3 behavior; "
            "the other two are safer choices when you want to inspect "
            "the target before committing."
        )
        title.setWordWrap(True)
        title.setStyleSheet("color: #cdd6f4;")
        outer.addWidget(title)

        # Each enabled category gets a row: name + count summary + dropdown.
        # The pre-flight analyzers are wrapped in try/except so a corrupt
        # target file doesn't block the dialog — the dropdown still
        # appears with a "(pre-flight unavailable)" subtitle.
        from foxport.migrate.conflicts import (
            DIRECT_WRITE_POLICIES,
            DIRECT_WRITE_POLICY_LABELS,
            analyze_cookies,
            analyze_history,
            analyze_open_tabs,
            analyze_passwords,
        )

        enabled: list[tuple[str, str, str]] = []  # (key, label, ctx_attr)
        if ctx.direct_write_passwords:
            enabled.append(("passwords", "Passwords (logins.json)", "policy_passwords"))
        if ctx.direct_write_cookies:
            enabled.append(("cookies", "Cookies (cookies.sqlite)", "policy_cookies"))
        if ctx.direct_write_history:
            enabled.append(("history", "History (places.sqlite)", "policy_history"))
        if ctx.direct_write_open_tabs:
            enabled.append(("open_tabs", "Open tabs (recovery.jsonlz4)", "policy_open_tabs"))

        analyzers = {
            "passwords": analyze_passwords,
            "cookies": analyze_cookies,
            "history": analyze_history,
            "open_tabs": analyze_open_tabs,
        }

        for key, label, attr in enabled:
            row = QFrame()
            row.setObjectName("Card")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(14, 12, 14, 12)
            row_layout.setSpacing(6)

            name_label = QLabel(label)
            name_label.setStyleSheet("font-weight: 600; color: #cdd6f4;")
            row_layout.addWidget(name_label)

            count_text = "(pre-flight unavailable)"
            try:
                conflicts = analyzers[key](ctx.source, ctx.target)
                if key == "passwords":
                    count_text = (
                        f"{conflicts.duplicates} of {conflicts.source_total} "
                        f"already in target; {conflicts.new} new would be merged."
                    )
                else:
                    count_text = (
                        f"{conflicts.source_total} source rows would REPLACE "
                        f"{conflicts.duplicates} existing rows."
                    )
                if conflicts.failures:
                    count_text += f" ({len(conflicts.failures)} pre-flight warning(s))"
            except Exception:  # noqa: BLE001
                pass
            count_label = QLabel(count_text)
            count_label.setStyleSheet("color: #a6adc8;")
            count_label.setWordWrap(True)
            row_layout.addWidget(count_label)

            dropdown = QComboBox()
            for policy in DIRECT_WRITE_POLICIES:
                dropdown.addItem(DIRECT_WRITE_POLICY_LABELS[policy], userData=policy)
            current = getattr(ctx, attr, "apply") or "apply"
            try:
                idx = list(DIRECT_WRITE_POLICIES).index(current)
            except ValueError:
                idx = 0
            dropdown.setCurrentIndex(idx)
            dropdown.setAccessibleName(f"{label} direct-write policy")
            row_layout.addWidget(dropdown)

            self._dropdowns[attr] = dropdown
            outer.addWidget(row)

        outer.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
        )
        accept_btn = QPushButton("Continue with these policies")
        accept_btn.setObjectName("PrimaryButton")
        accept_btn.setDefault(True)
        accept_btn.clicked.connect(self._save_and_accept)  # type: ignore[arg-type]
        buttons.addButton(accept_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        outer.addWidget(buttons)

    def _save_and_accept(self) -> None:
        for attr, dropdown in self._dropdowns.items():
            chosen = dropdown.currentData()
            if isinstance(chosen, str):
                setattr(self._ctx, attr, chosen)
        self.accept()


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


class ExtensionSettingsDialog(QDialog):
    """Opt-in picker for allowlisted extension settings exports."""

    def __init__(
        self,
        profile: ChromiumProfile,
        *,
        selected: set[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extension settings")
        self.resize(560, 320)
        self._checks: dict[str, QCheckBox] = {}
        selected = set(selected or set())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = QLabel(
            "Export only allowlisted settings for installed extensions. "
            "Raw extension storage and secrets are not copied."
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #a6adc8;")
        layout.addWidget(header)

        installed = installed_supported_settings(read_extensions(profile))
        if not installed:
            empty = QLabel("No supported extension settings found in this source profile.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #a6adc8;")
            layout.addWidget(empty)
        for key, spec in SUPPORTED_EXTENSION_SETTINGS.items():
            ext = installed.get(key)
            cb = QCheckBox(f"{spec.label} — {spec.notes}")
            cb.setEnabled(ext is not None)
            cb.setChecked(key in selected and ext is not None)
            if ext is None:
                cb.setToolTip("This extension was not found in the selected source profile.")
            else:
                cb.setToolTip(f"Source: {ext.name} ({ext.extension_id})")
            layout.addWidget(cb)
            self._checks[key] = cb

        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)  # type: ignore[arg-type]
        buttons.rejected.connect(self.reject)  # type: ignore[arg-type]
        layout.addWidget(buttons)

    def selected_keys(self) -> set[str]:
        return {key for key, cb in self._checks.items() if cb.isChecked()}


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

        # Privacy redact: strip C:\Users\<name> (or the macOS / Linux
        # equivalents) from the on-disk manifest's backup_path / label
        # strings so a manifest uploaded for support doesn't leak the
        # username. Local backups + on-disk artifacts are untouched —
        # this only changes the JSON that you might share with someone
        # else.
        self._privacy_redact_cb = QCheckBox(
            "Redact my username from the run manifest (for support uploads)"
        )
        self._privacy_redact_cb.setChecked(settings.privacy_redact_manifest)
        self._privacy_redact_cb.setToolTip(
            "When enabled, manifest.json scrubs C:/Users/<name> "
            "(or the macOS/Linux equivalent) from backup_path strings. "
            "The actual backup files are not moved or renamed."
        )
        privacy_layout.addWidget(self._privacy_redact_cb)

        self._telemetry_cb = QCheckBox(
            "Send anonymous migration metrics (category counts, no URLs)"
        )
        self._telemetry_cb.setChecked(settings.telemetry_opt_in)
        self._telemetry_cb.setToolTip(
            f"Opt-in Glean telemetry to {TELEMETRY_HOST}. Sends only "
            "selected item slugs, aggregate counts, direction, dry-run/"
            "direct-write flags, and outcome."
        )
        privacy_layout.addWidget(self._telemetry_cb)

        # Future-wired Sentry flag. Hidden until the crash-reporting task
        # ships; the placeholder preserves the stored value so _save() can
        # keep the field round-tripping without branching.
        _FUTURE_CRASH_REPORTING = False
        if _FUTURE_CRASH_REPORTING:
            self._crash_cb = QCheckBox("Send crash reports (no user data)")
            self._crash_cb.setChecked(settings.crash_reporting_opt_in)
            privacy_layout.addWidget(self._crash_cb)
        else:
            self._crash_cb = QCheckBox()
            self._crash_cb.setChecked(settings.crash_reporting_opt_in)

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
        self._settings.privacy_redact_manifest = self._privacy_redact_cb.isChecked()
        self._settings.telemetry_opt_in = self._telemetry_cb.isChecked()
        self._settings.crash_reporting_opt_in = self._crash_cb.isChecked()
        self._settings.nss_path_override = self._nss_edit.text().strip()
        save_settings(self._settings)
        self.accept()

    def settings(self) -> Settings:
        return self._settings
