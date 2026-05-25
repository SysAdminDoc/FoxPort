# ROADMAP

Single source of truth for actionable work. Items here are concrete units of
work — check them off as shipped. `RESEARCH_FEATURE_PLAN.md` is the deeper
analysis backing each entry; `CHANGELOG.md` records what shipped. This file
is the to-do list and nothing else.

> **Read this first if you're picking up where the last session left off:**
> `RESEARCH_FEATURE_PLAN.md` is the most recent research output (refreshed
> 2026-05-25, post-v1.3.0). The Phase A v1.3.1 batch below is the next active
> work; v1.3.0 + the 13 follow-on commits collapsed in the v1.3 entry under
> "Historical milestones".

---

## v1.3.1 — Audit-batch regressions + curated cleanup  ✅ shipped 2026-05-25

Six commits closed Phase A of the post-v1.3.0 plan. Three regressions
the v1.3 audit pass left behind plus the open-tabs pre-flight, the
restore-inspect inner-manifest read, HIBP tri-state, CLI --json on every
action subcommand, atomic-replace failure recovery tests, the curated-
map cleanup that removed 7 broken AMO slugs (63 → 56), and the version
bump. See CHANGELOG.md.

- [x] **P1** Fix curated-map documentation drift (was 67 vs 63)
- [x] **P1** Fix `extensions.py` hardcoded User-Agent
- [x] **P1** Fix open-tabs direct-write backup path emission
- [x] **P1** Curated-map cleanup — drop 7 broken AMO slugs
      (touch-vpn, rakuten, perplexity-companion, i-still-dont-care-
      about-cookies, zotero-connector, bukubrow, browsec-vpn).
      `_meta.entry_count` 63 → 56; `_meta.last_verified` refreshed.
      `_meta.description` documents the "drop on 404/401" policy.
- [x] **P1** Bump `__version__` 1.3.0 → 1.3.1
- [x] **P2** Refresh CLAUDE.md status block

## v1.3.2 — Distribution path  ⏸ blocked on cert + icon

Requires a human-provisioned signing cert and a real `assets/icon.ico`.
The release workflow is already wired (`release.yml:107-133` + signing
secrets); these two are the only remaining gates.

- [ ] **P0** Signed Windows release
      Set `WINDOWS_CERT_BASE64` / `WINDOWS_CERT_PASSWORD` org secrets
      (SignPath OSS program recommended). Drop `assets/icon.ico` (raster +
      favicon). Run `workflow_dispatch v1.3.2-rc1` and verify.
- [ ] **P0** Bundle the ABE sidecar in the release
      `foxport/data/foxport_abe.exe` ships only when the MSVC step has
      already produced it locally; the release workflow does build it.
      Verify the signed build attaches a signed sidecar to the release.

## v1.3.2 — Deep audit hardening  ✅ shipped 2026-05-25

Four commits closed an extreme-audit pass on top of v1.3.1. Real
correctness bugs in destructive paths plus UX/robustness polish across
the GUI + CLI + parser surfaces. See CHANGELOG.md for details.

- [x] **P0** Cookies Chrome 130+ HOST_KEY prefix strip in *bytes-space*
      (was stripping characters; SHA-256 bytes can include multi-byte
      UTF-8 sequences so the slice chewed the wrong amount and
      corrupted Chrome 130+ cookie values on Windows). New
      `decrypt_value_bytes` / `decrypt_value_v10_bytes` helpers.
- [x] **P1** `nss_passwords._atomic_write` was missing
      `flush()` + `fsync()` before rename; replaced with
      `foxport.fileops.write_text_atomic`.
- [x] **P1** GUID compare in passwords merge + pre-flight analyzer is
      now case-insensitive (`uuid.uuid5` emits lowercase but
      `logins.json` may carry mixed case from older Firefox / 3rd-party
      tools).
- [x] **P1** Snapshot wrong-passphrase / truncated-bundle now raises
      `ValueError` (the CLI's catch) instead of an uncaught
      `cryptography.exceptions.InvalidTag` traceback.
- [x] **P1** Failed-migration footer state machine: dead "Run
      Migration" button on a failed run now relabels to "Try Again" and
      restarts in-place. Back-button is also gated while a migration
      is actively running.
- [x] **P1** `_parse_profiles_ini` defensive: tolerates
      `IsRelative=yes`, hand-edited values, `UnicodeDecodeError`,
      and `OSError`. Five new tests.
- [x] **P2** Cards CSV filename: migrator wrote `saved_cards.csv`
      (underscore) while every user-facing surface said
      `saved-cards.csv` (hyphen); migrator renamed for consistency.
- [x] **P2** Cookies samesite clamp: Chromium `samesite=-1`
      (unspecified) → Firefox `0` (no SameSite attribute), keeping
      `moz_cookies.sameSite` within Firefox's valid `[0..3]` range.
- [x] **P2** `import-bookmarks --json` completes the CLI JSON arc.
- [x] **P2** `tests/migrate/test_downloads.py:119` ResourceWarning fix
      (file handle leak under `pytest -W error::ResourceWarning`).
- [x] **P2** `docs/architecture.md` refresh covering `manifest.py`,
      `conflicts.py`, `fileops.py`, the per-run manifest schema, the
      `.fxport` bundle layout, the HIBP tri-state, and the
      `decrypt_value_bytes` cookie-decryption helper.

## v1.3.3 — Trust + completeness arc closeout  ✅ shipped 2026-05-25

Phase C of the v1.3 plan — most of it shipped in v1.3.0; v1.3.3 closes
the last P1 (conflict-review dialog) plus the P2/P3 follow-ons.
**207 tests pass.** See CHANGELOG.md.

- [x] **P1** Conflict review dialog + per-category direct-write policy
      `DirectWritePolicyDialog` opens between Preview and Run (gated on
      `forward + non-dry-run + target + any direct_write_*`). Each
      enabled category gets a card with pre-flight counts + a dropdown
      of `{apply, skip, backup-only}`. Default is `apply` (v1.3
      behavior). Worker reads the policy per category and branches:
      `skip` leaves the target untouched, `backup-only` takes the
      timestamped backup but doesn't write the new content, `apply`
      runs the existing nss_*_into_target paths. Manifest records the
      policy verbatim in `RunArtifact.direct_write_policy` (additive
      to schema v1; legacy manifests default to empty). CLI
      `--direct-write-policy {apply,skip,backup-only}` + `--yes` flags
      reserved. Seven new tests in
      `tests/test_direct_write_policy.py`.
- [x] **P1** Snapshot inspect reads inner `RunManifest`
      `RestoreInspectDialog` now picks up the bundled per-run manifest
      (when present) and renders direction / items / network / warnings
      + per-artifact sensitivity badges above the file list. Pre-v1.3
      bundles without an inner manifest fall back to today's behavior.
      Untrusted fields are HTML-escaped. Four tests in
      `tests/test_restore_inspect_inner_manifest.py`.
- [x] **P1** CLI `--json` on migrate / migrate-reverse / diff / snapshot / restore
      `--json` now suppresses per-category text output and emits a
      schema-versioned payload on stdout for every subcommand that
      supports it. Errors stay on stderr. `_JSON_SCHEMA_VERSIONS`
      constant + 5 new tests in `tests/test_cli_json.py` exercise the
      shapes end-to-end via `main()`.
- [x] **P1** HIBP tri-state ("checked-clean" vs "checked-hits" vs
      "network-error" vs "disabled")
      `scan_passwords` now returns `HibpScanResult` with hits + queries +
      network_errors + `.status` property; `PasswordResult.hibp_status`
      threads it through; worker emits an explicit "scan failed —
      passwords were NOT checked" line when applicable; manifest
      `network.api.pwnedpasswords.com` records the live status so
      snapshot consumers can tell "scan ran cleanly" from "scan
      failed". 4 new tests in `tests/crypto/test_hibp.py`.
- [x] **P2** Pre-flight conflict analysis for open_tabs
      `analyze_open_tabs()` reads target `sessionstore-backups/recovery.jsonlz4`
      via mozLz40 decode, counts URLs, logs "N source tabs will REPLACE M
      existing session tab(s)" before the destructive write. Worker wires
      it alongside the existing passwords/cookies/history pre-flight calls.
- [x] **P2** All-artifact Done UI render test
      Already covered by `test_run_page_done_renders_action_per_artifact`
      in `tests/test_gui_run_actions.py` — exhausts all 11 artifact keys
      and asserts open/reveal action kinds round-trip via the signal.
- [x] **P2** Atomic-replace failure recovery test
      Two new tests in `tests/test_fileops.py` monkeypatch
      `Path.replace` to raise, then assert (a) original target intact
      and (b) no orphan `.{name}.foxport-*` tmpfiles. Covers both
      `write_bytes_atomic` (in-memory write path) and
      `replace_file_atomic` (source-file copy path).
- [x] **P2** Lift `_backup_path_for()` into `foxport/fileops.py`
      Lifted to `timestamped_backup_path()`; nss_cookies + nss_history
      keep backward-compat alias. Three new tests in
      `tests/test_fileops.py`.
- [x] **P2** `_DEFAULT_ACTION["cards"]` → `"reveal"`
      Plaintext PAN CSV — default-launching with Excel is unsafe.
      Mirrored in `foxport/gui/pages.py:ARTIFACT_ACTIONS`.
- [x] **P2** Hide disabled telemetry/crash placeholder checkboxes
      Feature-flagged behind a `_FUTURE_TELEMETRY = False` constant in
      `SettingsDialog`. The hidden QCheckBox objects still hold the
      persisted value so `_save()` doesn't need a hasattr() dance.
- [x] **P2** Manifest privacy: `--privacy-redact` flag
      `foxport.manifest.redact_manifest()` strips the running user's
      home-dir prefix (per-platform: `C:\Users\<name>\`, `/Users/...`,
      `/home/...`) from `backup_path` + label strings, swapping for
      `<redacted>`. Exposed three ways: CLI `--privacy-redact` on
      `migrate` + `migrate-reverse`; persistent
      `Settings.privacy_redact_manifest` toggle in the Privacy section
      of the Settings dialog; `write_manifest(..., privacy_redact=True)`
      kwarg for programmatic callers. Six new tests in
      `tests/test_manifest.py` + 2 new tests in `tests/test_config.py`.
- [x] **P2** README install snippet: cross-platform softening
      Was "Requires Python 3.11+ on Windows" despite the cross-platform
      CI matrix; now reflects Windows-first with macOS / Linux via the
      same install steps (different venv activation command noted).
- [ ] **P2** Re-run `scripts/capture_screenshots.py`
      Current PNGs are 2026-05-23 — predate the downloads row, 4 direct-
      write checkboxes, dry-run banner, network-activity sub-tree, and the
      per-artifact Done action bar. Requires a populated source profile;
      blocked on manual environment.
- [x] **P2** Tighten curated-map cron cadence + in-app stale-match warning
      Auditor cron bumped from monthly to weekly (Monday 06:00 UTC) so
      AMO slug rot is caught within ~7 days instead of ~30. Runtime
      side: `extensions._curated_map_warnings()` surfaces a `⚠ curated
      extension map is N days old` advisory in the GUI run log + CLI
      migrate output when the bundled `_meta.last_verified` exceeds
      90 days. Helps users on older releases know when to update.
      Three new tests in `tests/migrate/test_extensions.py`.
- [x] **P3** First-run trust dialog re-prompt on trust-model change
      `Settings.first_run_acked_trust_revision: int = 0` field +
      module-level `foxport.config._TRUST_REVISION` constant. The
      dialog persists the current revision on accept; MainWindow
      gates on `acked_iso AND acked_revision >= current` so a user
      who acked the v1.3 trust surface gets a fresh consent moment
      when v1.4 bumps the revision (with the introduction of opt-in
      telemetry / crash reporting / update appcast). Backward-
      compatible: legacy configs without the field default to 0.

## v1.4 — Larger bets

- [ ] **P2** Downloads → `places.sqlite.moz_annos` direct-write
      When history direct-write is selected. ROADMAP Phase D P2; the
      missing piece keeps downloads as CSV-only when the same migration
      is already touching places.sqlite.
- [ ] **P2** Extension settings allowlist
      uBO filter lists, Stylus userstyles, Bitwarden vault URL. Three
      stable WebExtension storage formats; opt-in per extension.
- [ ] **P3** Opt-in Glean telemetry with declared metrics
- [ ] **P3** Opt-in Sentry crash reporting (path-stripped)
- [ ] **P3** Signed update appcast (WinSparkle)
- [ ] **P3** Passkey inventory CXF prototype
      `passkeys inventory` CLI; presence + counts only. No export until
      FIDO CXF/CXP destination support lands.
- [ ] **P3** macOS DMG + Linux AppImage distribution
      Apple Developer ID + notarization for macOS; AppImage for Linux
      (bundle NSS or document `FOXPORT_NSS_PATH`).
- [ ] **P3** Curated map hot-reload + in-run AMO cache
- [x] **P3** Profile detection test fixtures
       Seven new tests in `tests/test_detect_layouts.py` exercise
       `_enumerate_profile_subdirs` (Default + Profile N, Guest
       Profile, missing-marker rejection, non-profile-name filter)
       and `_parse_profiles_ini` (Install-default promotion,
       absolute-path / portable Firefox layout).
- [x] **P3** macOS Keychain + Linux libsecret/kwallet test coverage
       Nine new tests in `tests/crypto/test_keychain.py` mock the
       per-platform CLIs (`security`, `secret-tool`, `kwallet-query`)
       and pin the canonical happy paths, the Google-Chrome short-name
       fallback, the `OSError`-on-missing-binary branch, the
       multi-tool Linux degradation chain ending in `"peanuts"`, and
       the per-platform PBKDF2 iteration counts (1003 mac vs 1
       linux).
- [ ] **P3** "Merge mode" for cookies/history direct-write
      Preserve target rows + add source rows by uniqueness key
      (cookies = `host_key+path+name`; history = URL+visit_time).
      Builds on v1.3.3's skip/overwrite/backup-only policy framework.
- [ ] **P3** Restore-from-backup wizard step
      Regret-undo UI that copies a `*.foxport-backup-<mtime>.*` file
      back over the live file with a confirm.
- [ ] **P3** Background-worker preview counts for large profiles
      Today `_safe_sqlite_count` is synchronous on the GUI thread for the
      Preview page.
- [ ] **P3** Raster logo / favicon set
      Banner is SVG only; signed release expects an `.ico`.

## Open items inherited from earlier roadmaps

- [ ] **Reach** `--remote-debugging-port` CDP fallback for the day the
      ABE bypass breaks.
- [ ] **Reach** Curated map auto-PR generator that proposes new entries
      from frequently-seen "no-match" extensions (requires opt-in
      telemetry; see v1.4 Glean).
- [ ] **Distribution** SBOM / supply-chain attestation
      cosign + GitHub OIDC for release-artifact provenance.

---

## Historical milestones (collapsed for reference)

<details>
<summary>v1.3.0 — Trust + completeness foundations  ✅ 2026-05-24</summary>

13 commits closed Phase A/B/C/D of the v1.3 plan: atomic fileops,
ASCII-safe CLI help, `import_instructions()` parity for all 11 artifact
keys, atomic snapshot create + overwrite policy on restore, open-tabs
direct-write wiring, Done + Items dict-based parity for all 10
categories, `manifest.json` per non-dry-run migration (`foxport/manifest.py`),
atomic-replace for every staging emitter, NSS version-skew guard with
override, GUI snapshot save / restore with inspect dialog, first-run
trust dialog + Preview network-activity sub-tree, Done-screen "Reveal
backup" actions, Settings NSS path override + Reset, Help-menu change log
+ issue tracker links, CLI `list --json` + `list --detail`, reverse
curated-map auditor (`--include-reverse`), open-tabs partial-success
warning, regression test suites for downloads / cards / search engines /
diff / bookmarks reverse, release workflow Authenticode scaffolding
(cert provisioning pending), pre-flight conflict analyzers for direct-
write paths. **163 tests pass.** See CHANGELOG.md.
</details>

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

`places.sqlite` v77 → v86 with `crypto/mozhash.py`; open-tabs SNSS
Pickle parser (0 → 12 URLs); 48-test pytest suite; HIBP scan; drag-drop
manual source; cookies `updateTime`; favicons backup not delete;
chrome:// filter; ambiguous diff refusal; password preview masks;
settings page; path-traversal hardening; formhistory v5; reverse
harvester; history time-range.
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
