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

## v1.3.1 — Audit-batch regressions  🚧 in progress

Phase A of the post-v1.3.0 plan. Three real bugs the v1.3 audit pass left
behind plus a doc refresh.

- [ ] **P1** Fix curated-map documentation drift (63 vs 67)
      Docs claim 67 entries; `load_curated_map()` returns 63. Either grow
      the map to 67 (real AMO-verified slugs) or revert the docs to 63.
      Add `_meta.entry_count` so the auditor catches drift next time.
- [ ] **P1** Fix `extensions.py` hardcoded User-Agent
      Mirror `crypto/hibp.py:32`'s pattern: `f"FoxPort/{__version__} (...)"`.
      Touches `foxport/migrate/extensions.py:44`.
- [ ] **P1** Fix open-tabs direct-write backup path emission
      `write_session_into_target()` creates `recovery.foxport-backup-*.jsonlz4`
      but returns only the target path. Worker can't surface a Reveal-backup
      button. Change the return to a small dataclass with `target_path` +
      `backup_path`; wire `direct_write_backups["open_tabs"]` in the worker.
- [ ] **P2** Refresh CLAUDE.md status block to v1.3.0
      Today says "v1.2.1 shipped 2026-05-24"; reality is v1.3.0 + 13
      follow-on commits.

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

## v1.3.3 — Trust + completeness arc continues

Phase C of the v1.3 plan — most of it shipped in v1.3.0, these are the
follow-ons.

- [ ] **P1** Conflict review dialog + per-category direct-write policy
      Pre-flight analyzers (`foxport/migrate/conflicts.py`) already produce
      counts; add a modal between Preview and Run when direct-write is on
      for any category. Per-category policy: skip / overwrite / backup-only
      (merge defers to v1.4). CLI: `--direct-write-policy=... --yes`.
      Manifest records the chosen policy per category.
- [x] **P1** Snapshot inspect reads inner `RunManifest`
      `RestoreInspectDialog` now picks up the bundled per-run manifest
      (when present) and renders direction / items / network / warnings
      + per-artifact sensitivity badges above the file list. Pre-v1.3
      bundles without an inner manifest fall back to today's behavior.
      Untrusted fields are HTML-escaped. Four tests in
      `tests/test_restore_inspect_inner_manifest.py`.
- [ ] **P1** CLI `--json` on migrate / migrate-reverse / diff / snapshot / restore
      `list --json` is the precedent. Same shape as `manifest.json` for
      migrate/migrate-reverse; command-specific schema_versioned payloads
      for diff/snapshot/restore. No secrets in output.
- [ ] **P1** HIBP tri-state ("unchecked" vs "checked-clean" vs "checked-hits")
      `PasswordResult.hibp_status` tri-state replaces the silent
      "0 hits == success" assumption. Worker emits an explicit
      "scan failed — passwords NOT checked" line when applicable.
- [ ] **P2** Pre-flight conflict analysis for open_tabs
      `analyze_open_tabs()` reads target `sessionstore-backups/recovery.jsonlz4`
      (decode mozLz40), counts URLs, logs replacement before mutation.
- [ ] **P2** All-artifact Done UI render test
      Mock `set_done` with all 11 keys; assert every artifact gets a button.
- [ ] **P2** Atomic-replace failure recovery test
      Force write-error mid-replace; assert target unchanged + no orphan
      `.foxport-*` tmpfiles.
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
- [ ] **P2** Manifest privacy: `--privacy-redact` flag
      Strip `C:\Users\<name>` from backup_path strings on demand.
- [ ] **P2** README install snippet: cross-platform softening
      Says "Requires Python 3.11+ on Windows" while CI matrix covers
      Windows/macOS/Linux.
- [ ] **P2** Re-run `scripts/capture_screenshots.py`
      Current PNGs are 2026-05-23 — predate the downloads row, 4 direct-
      write checkboxes, dry-run banner, network-activity sub-tree, and the
      per-artifact Done action bar.
- [ ] **P3** First-run trust dialog re-prompt on trust-model change
      `Settings.first_run_acked_for_trust_revision: int` with module-level
      `_TRUST_REVISION` constant. Bumps trigger re-prompt.

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
- [ ] **P3** Profile detection test fixtures (Opera GX flat,
       Thunderbird, portable Firefox)
- [ ] **P3** macOS Keychain + Linux libsecret/kwallet test coverage
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
