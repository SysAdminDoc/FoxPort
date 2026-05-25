# ROADMAP

Single source of truth for actionable work. Items here are concrete units of
work — check them off as shipped. `RESEARCH_FEATURE_PLAN.md` is the
deeper analysis backing each entry; this file is the to-do list.

> **Read this first if you're picking up where the last session left off:**
> `RESEARCH_FEATURE_PLAN.md` is the most recent research output. The
> `v1.3.0` and Phase D sections below are the promoted action lists from
> it.

---

## v1.3.0 — Trust + completeness pass  🚧 in progress

Working tree on top of v1.2.1 introducing atomic fileops, the ASCII-safe CLI
help, a generalized `import_instructions()`, snapshot overwrite policy,
open-tabs direct-write wiring, and friends. See the v1.3.0 CHANGELOG entry
for the full list.

### Phase A — Trust + safety foundations  ✅ shipped 2026-05-24
- [x] Atomic fileops helpers (`foxport/fileops.py` with `write_bytes_atomic`,
      `replace_file_atomic`) + `tests/test_fileops.py` coverage.
- [x] CLI top-level help no longer crashes under default Windows encoding
      (`python -m foxport.cli --help` returns 0 in cp1252). ASCII-safe test
      at `tests/test_cli_help.py` recursively checks every subparser.
- [x] `import_instructions()` covers every emitted artifact (passwords, HIBP,
      bookmarks, extensions, cookies, history, autofill, cards, search
      engines, open tabs, downloads) and detects reverse-direction Chrome-
      prefixed filenames. `tests/test_import_instructions.py` pins it.
- [x] `snapshot.create_snapshot()` writes atomically via `write_bytes_atomic`.
- [x] `snapshot.restore_snapshot()` refuses non-empty output dirs unless
      `overwrite=True`; CLI gets `--overwrite`.
- [x] `nss_cookies` / `nss_history` / `open_tabs` direct-writes go through
      `replace_file_atomic` instead of `shutil.copy2`.
- [x] `MigrationContext.direct_write_open_tabs` flows through
      `MigrationRequest` to the worker — the hidden flag is now reachable
      from the Items page.

### Phase B — Wizard + run-artifact parity
- [x] **P0** Done screen + Items badges parity with all ten categories.
      `RunPage.ARTIFACT_ACTIONS` drives generated buttons; one signal
      `artifactActionRequested(key, action_kind)` routes Open vs Reveal
      through `MainWindow._on_artifact_action`. `ItemsPage.set_counts()`
      now accepts `dict[str, int]` keyed by item slug, and
      `MigrationContext.counts` replaces the five positional fields.
      Five new GUI smoke tests in `tests/test_gui_run_actions.py`
      (under `QT_QPA_PLATFORM=offscreen`) pin both surfaces.
- [x] **P0** Emit `manifest.json` per non-dry-run migration.
      `foxport/manifest.py` ships `RunManifest`, `RunArtifact`,
      `build_artifact()`, `write_manifest()`, and `load_manifest()`
      (forward-compatible). GUI worker + CLI forward + CLI reverse
      paths all emit it alongside `README.txt`. Network-call status
      recorded; per-artifact SHA-256 + size + sensitivity; direct-
      write backups captured for passwords / cookies / history.
      Guard test ensures plaintext secrets never appear in the
      serialized form.

### Phase C — Trust + release path
- [ ] **P0** Signed Windows release with bundled signed ABE sidecar,
      app icon, and Windows version resource.
- [ ] **P1** First-run trust dialog + Preview "Network activity"
      section listing optional AMO + HIBP calls + future-feature
      placeholders.
- [x] **P1** NSS `nss3.dll` version-skew guard. `load_nss()` binds
      `NSS_GetVersion()` and stores the reported string on
      `NSSLibrary.version`. `open_session()` accepts a
      `require_compatible_version=True` kwarg and refuses to proceed
      when the major version is below 3 (where PK11SDR ABI has been
      stable). `FOXPORT_NSS_FORCE=1` overrides for portable Firefox
      builds. `migrate_passwords_via_nss()` records the version in
      `DirectWriteResult.nss_version`; the worker logs it.
      `tests/crypto/test_nss_version.py` (11 tests) pins the parsing,
      fail-open behavior, refusal, and env-var override.
- [ ] **P1** Direct-write conflict review + rollback manifest across
      passwords / cookies / history / open-tabs.
- [x] **P1** Atomic-replace for staging-folder emitters. `foxport/fileops.py`
      grew `write_text_atomic`; every non-`nss_*` writer (`passwords.py`,
      `bookmarks.py`, `cookies.py`, `history.py`, `autofill.py`, `cards.py`,
      `downloads.py`, `search_engines.py`, `open_tabs.py`, `extensions.py`)
      now stages bytes / SQLite into a tempdir or in-memory buffer and
      atomic-replaces the final path. A torn write can no longer leave a
      half-written CSV / SQLite / JSON / mozLz40 at the README-referenced
      path.
- [x] **P1** Tests for downloads, cards, search engines, diff, reverse
      migrators. New suites: `tests/migrate/test_downloads.py` (4),
      `tests/migrate/test_cards.py` (4), `tests/migrate/test_search_engines.py`
      (5), `tests/test_diff.py` (4), `tests/migrate_reverse/test_bookmarks_reverse.py`
      (3). Reverse passwords + bookmarks + extensions emitters all go
      through atomic writers as a side effect of the audit.
- [ ] **P1** GUI snapshot creation (Done screen) + GUI restore wizard
      (File menu) with bundle inspector.
- [x] **P1** Surface external bookmark adapters. `foxport/import_/adapters.py`
      grew `write_netscape_html()` — a shared emitter that groups by
      folder, escapes special chars, surfaces tags as the optional
      `TAGS` attr, and routes through `write_text_atomic()`. CLI:
      `python -m foxport.cli import-bookmarks --input pocket.json` with
      auto-detection + `--format` override. GUI: the manual-drop tile
      now tries the bookmark adapters before the Chromium-profile path,
      and converts in place to a `.firefox.html` sibling on success.
      `tests/test_import_bookmarks_cli.py` (5 tests) covers grouping,
      HTML escape, round-trip, format override, and missing-input.

### Phase D — Polish + observability
- [ ] **P2** CLI `--json` flag + `list --detail` with per-category counts.
- [x] **P2** Cards CSV column cleanup — `Name` was a duplicate of
      `Cardholder name` (both sourced from `name_on_card`). New shape:
      `Type, Cardholder name, Number, Expiration, Notes`. Comment
      explains the 1Password / Bitwarden importer expectations.
      Dedicated `tests/migrate/test_cards.py` covers the new shape +
      atomic write.
- [x] **P2** Open-tabs partial-success sanity check. `_extract_urls()`
      always computes the regex fallback now and takes the union when
      the structural parser returns < 50 % of what the regex finds,
      logging a "schema drift" warning to the failures list so the
      GUI/CLI surfaces it. Prevents the silent-undercount bug where a
      new Chrome SNSS layout leaves us with 2 of 40 tabs and no flag.
      `tests/migrate/test_open_tabs_partial_success.py` (3 tests) pins
      happy-path / partial-success / pure-fallback.
- [x] **P2** Reverse curated-map auditor. `scripts/check_curated_map.py
      --include-reverse` walks every entry in `AMO_GUID_TO_CHROME` and
      hits the AMO detail endpoint by URL-encoded GUID. The monthly
      cron workflow passes the flag and reports broken / disabled
      reverse entries in a separate table within the auto-filed issue.
      Forward-compatible JSON output (`{"forward": ..., "reverse": ...}`)
      with a fallback for v1.2-era flat reports.
- [x] **P2** Documentation refresh — curated count 63 → 67, README
      "Security notes" rewritten to mention HIBP + manifest.json +
      atomic direct-write + NSS version guard, `firefox.py` docstring
      reflects direct-write reality, CLAUDE.md curated count synced.
      Screenshot refresh remains pending until the v1.3 Items + Run
      polish UI stabilizes (separate iteration on the polish branch).
- [ ] **P2** Settings: NSS path override + Reset-to-defaults.
- [ ] **P2** Done "Reveal backups" action.
- [ ] **P2** Downloads direct-write into Firefox `moz_annos` when history
      direct-write is selected.
- [ ] **P2** All-artifact Done UI render test + atomic-replace failure
      recovery test + NSS version monkeypatch test.
- [ ] **P3** Opt-in Glean telemetry with declared metrics.
- [ ] **P3** Opt-in Sentry crash reporting (path-stripped).
- [ ] **P3** Signed update appcast (WinSparkle / NetSparkle).
- [ ] **P3** Passkey inventory CXF prototype.
- [ ] **P3** Extension settings allowlist (uBlock Origin filter lists,
      Stylus userstyles).
- [ ] **P3** Help menu affordances (Open documentation, Report a problem,
      Change log).
- [ ] **P3** Curated map hot-reload + in-run AMO cache.
- [ ] **P3** macOS / Linux distribution path (PyInstaller per OS;
      signed/notarized macOS; AppImage or `.deb` on Linux).

---

## Open items inherited from earlier roadmaps

- [ ] **v0.3.1 / Phase C** ABE sidecar binary — compile `foxport_abe.exe`
      with MSVC v143 in CI and Authenticode-sign it. Document
      `--browser` flag for additional vendors once IIDs are confirmed.
- [ ] **Distribution** Replace SVG banner with raster logo + favicon set
      (needs ChatGPT image-gen pass; not autonomously generatable).
- [ ] **Distribution** Authenticode-sign the released ZIP (needs cert).
- [ ] **Reach** Extension-settings best-effort (Stylus userstyles,
      Bitwarden vault URL, uBO filter lists) — see Phase D allowlist.
- [ ] **Reach** `--remote-debugging-port` CDP fallback for the day the
      ABE bypass breaks.
- [ ] **Curated map** Auto-PR generator that proposes new entries from
      frequently-seen "no-match" extensions (requires opt-in
      telemetry; see Phase D Glean).

---

## Historical milestones (collapsed for reference)

<details>
<summary>v1.2.1 — Extreme hardening pass  ✅ 2026-05-24</summary>

Audit-driven follow-up to v1.2.0. Five batches of fixes; no new
user-facing features. 89 tests pass (up from 69). See CHANGELOG.md for
details. Highlights: refused to overwrite unreadable `logins.json`;
HIBP no longer redecrypts; `backup_path: Path | None`; rename
`favicons_deleted` → `favicons_backup_path`; consolidated SQLite
counters; `closeEvent` migration guard; snapshot path-traversal +
sha256 + unknown-key hardening; AMO URL injection fix; HIBP UA
reflects `__version__`; keyboard focus indicators; persistent dry-run
banner; regression tests for every batch.
</details>

<details>
<summary>v1.2.0 — Research-driven correctness + trust  ✅ 2026-05-23</summary>

Research-driven correctness pass. `places.sqlite` v77 → v86 with
`crypto/mozhash.py`; open-tabs SNSS Pickle parser (0 → 12 URLs); 48-
test pytest suite; HIBP scan; drag-drop manual source; cookies
`updateTime`; favicons backup not delete; chrome:// filter; ambiguous
diff refusal; password preview masks; settings page; path-traversal
hardening; formhistory v5; reverse harvester; history time-range.
</details>

<details>
<summary>v1.1.0 — Reverse direction GUI + direct-write extras  ✅ 2026-05-23</summary>

GUI direction toggle, master-password retry loop, direct-write
cookies+history, open-tabs SNSS (URL scanner version), CLI `diff`,
curated-map auditor.
</details>

<details>
<summary>v1.0.0 — Reverse direction (Firefox → Chromium)  ✅ 2026-05-23</summary>

NSS-based Firefox login readers; reverse migrators for passwords /
bookmarks / extensions; AMO_GUID_TO_CHROME table.
</details>

<details>
<summary>v0.x — Foundations  ✅ 2026-05-23</summary>

v0.1–v0.6.1: PyQt6 wizard, four-stage extension matching, ABE
awareness, cookies + history + dry-run + ABE sidecar source, CLI,
per-row/per-folder filters, NSS direct-write passwords, master-
password prompt, cross-platform (macOS Keychain, Linux libsecret /
kwallet), autofill + saved cards + search engines, open tabs via SNSS
URL scanner.
</details>

<details>
<summary>Distribution baseline  ✅ 2026-05-23</summary>

PyInstaller onedir bundle (`foxport.spec`); GH Actions release
(`workflow_dispatch`) building MSVC sidecar + PyInstaller + GH
release; CI workflow with AST + import smoke + CLI sanity on
Windows/macOS/Linux × 3.11/3.12; DPI-aware README screenshots; SVG
banner; monthly curated-map audit cron; per-page screen-reader/
keyboard pass; `docs/architecture.md`, `docs/file-formats.md`,
`docs/troubleshooting.md`.
</details>
