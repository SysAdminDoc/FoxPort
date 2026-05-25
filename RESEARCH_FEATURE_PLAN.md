# Project Research and Feature Plan

Generated: 2026-05-24 (refresh pass over the v1.2.1 baseline + uncommitted polish working tree).

Status baseline: `main` at `069a057` (v1.2.1) plus the in-progress working tree that adds `foxport/fileops.py`, atomic snapshot/direct-write paths, the ASCII-safe CLI help, a generalized `import_instructions()`, and three new test files. `pytest` reports **97 passed in 1.60s**; `python -m foxport.cli --help` and `--version` both succeed under default Windows PowerShell encoding.

This file replaces the previous plan, which was authored against the v1.2.1 baseline and is now stale because the working tree has already shipped roughly the first half of its P0/P1 list.

## Executive Summary

FoxPort is a Windows-first but cross-platform Python/PyQt6 desktop and CLI tool for moving browser data between Chromium-family and Firefox-family profiles. The product has matured fast: ten forward export categories, three reverse categories, direct-write into closed Firefox profiles for passwords/cookies/history/open-tabs, encrypted `.fxport` snapshots, an HIBP scan, settings persistence, three docs files, and a 67-entry curated AMO map (recently grown from 63). The strongest current shape is a privacy-oriented migration assistant with serious data-safety thinking — backups instead of deletes, atomic replacement on the riskiest paths, accounting invariants, deterministic GUIDs, ABE awareness, and a closeEvent guard mid-migration.

The highest-value direction is **finishing the trust-and-completeness arc** that the working tree started, then turning the app into something a non-developer can confidently install and rely on. Concretely:

1. **Land the working tree.** It already addresses last pass's P0s (CLI help crash, README parity, atomic snapshot, atomic direct-write, open-tabs direct-write wiring, snapshot overwrite policy). Commit and tag v1.3.0-rc.
2. **Make the Done screen and Items badges match the ten categories the wizard actually offers.** [`foxport/gui/main_window.py:114-121`](foxport/gui/main_window.py#L114-L121) still wires only five hardcoded buttons; [`foxport/gui/pages.py:724-742`](foxport/gui/pages.py#L724-L742) accepts only five counts.
3. **Emit `manifest.json` per run** — a single structured registry that Done screen, generated README, snapshot bundling, support diagnostics, and a future `--json` CLI can all read from.
4. **Ship a signed Windows release with the ABE sidecar bundled.** [`foxport.spec:11`](foxport.spec#L11) conditionally bundles `foxport_abe.exe` but the binary is absent locally and CI doesn't sign it.
5. **Atomic-replace the rest of the writers** that produce sensitive on-disk artifacts (`passwords.csv`, `cookies.sqlite`, `places.sqlite`, etc. into the staging folder). Today only the *target-profile* paths got the atomic helper; the *staging* outputs that snapshot later bundles still write directly.
6. **Add NSS `nss3.dll` version-skew protection** before any direct-write into `logins.json`. The current ctypes loader has no version validation.
7. **Surface external bookmark adapters and `.fxport` snapshot from the GUI**, not only via CLI.
8. **First-run trust dialog + Network Activity preview row.** Optional AMO and HIBP calls exist; future Sentry/Glean/update calls are roadmap'd. Consent has to land before any of them ship.
9. **Conflict review and rollback manifest for direct-write paths.** The product's highest data-safety risk is target replacement; the user currently can't preview what will be overwritten.
10. **Refresh docs + screenshots.** README claims 63 curated entries (it is now 67); CLAUDE.md repeats the stale figure; `assets/screenshots/` predates the downloads row added on the Items page.

Five-to-ten top opportunities in priority order are detailed in the prioritized roadmap below.

## Evidence Reviewed

Local files and directories inspected (working tree state at the time of this pass, on `main` plus uncommitted polish edits):

- `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `CLAUDE.md`
- `docs/architecture.md`, `docs/file-formats.md`, `docs/troubleshooting.md`
- `.github/workflows/ci.yml`, `release.yml`, `curated-map-audit.yml`
- `foxport.spec`, `requirements.txt`, `pyproject.toml`, `assets/banner.svg`, `assets/screenshots/*.png`
- `foxport/__init__.py`, `__main__.py`, `app.py`, `cli.py`, `config.py`, `diff.py`, `snapshot.py`, **new** `fileops.py`
- `foxport/browsers/detect.py`, `chromium.py`, `firefox.py`, `firefox_read.py`
- `foxport/crypto/abe.py`, `dpapi.py`, `hibp.py`, `keychain.py`, `mozhash.py`, `nss.py`
- `foxport/gui/dialogs.py`, `main_window.py`, `pages.py`, `theme.py`, `widgets.py`, `workers.py`
- `foxport/migrate/*.py` (10 emitters + nss_passwords/cookies/history)
- `foxport/migrate_reverse/{bookmarks,extensions,passwords}.py`
- `foxport/import_/adapters.py`
- `foxport/data/curated_extension_map.json`
- `scripts/capture_screenshots.py`, `check_curated_map.py`, `harvest_reverse_map.py`
- `tools/abe_sidecar/README.md`, `CMakeLists.txt`, `foxport_abe.cpp`, `foxport_abe.exe.manifest`
- `tests/conftest.py`, `tests/migrate/test_*.py`, `tests/crypto/test_*.py`, `tests/test_*.py`, **new** `test_cli_help.py`, `test_fileops.py`, `test_import_instructions.py`

Git history reviewed:

- `git log --oneline` from `069a057 chore: bump to v1.2.1` back through v1.2.0, v1.1.0, v1.0.0, and the v0.x sprints. 22 commits total on `main`.
- `git status` against working tree: 14 files modified + 4 new files (the polish-in-progress branch). No staged commits yet.

Build / test / release artifacts validated this pass:

- `python -m pytest` → **97 passed in 1.60s** (up from the previous pass's 89; the new file adds suites for CLI help ASCII safety, atomic fileops, and import-instructions coverage).
- `python -m foxport.cli --version` → `FoxPort 1.2.1`.
- `python -m foxport.cli --help` → **succeeds under default PowerShell encoding** (the Unicode arrow in the description was replaced with ` - `).
- `python -m foxport.cli list` → enumerates Chromium/Firefox profiles cleanly.
- `foxport/data/foxport_abe.exe` → still absent locally; `foxport.spec:11-13` bundles it only if present.
- `.github/workflows/ci.yml` runs AST parse + import smoke + CLI `--version`/`list` + `pytest -ra -q` on Windows/macOS/Linux × Python 3.11/3.12. GUI bootstrap skipped on Linux.
- `.github/workflows/release.yml` builds MSVC v143 ABE sidecar, runs PyInstaller, zips, hashes via `Get-FileHash`, creates GH release. **No Authenticode signing step.**
- `.github/workflows/curated-map-audit.yml` is the monthly cron + workflow_dispatch issue filer for the curated forward map.

External sources reviewed:

- Mozilla Firefox source docs, Migrators Reference: https://firefox-source-docs.mozilla.org/browser/components/migration/docs/migrators.html
- Mozilla support, import data from another browser: https://support.mozilla.org/en-US/kb/import-data-another-browser
- Mozilla Add-ons external API: https://mozilla.github.io/addons-server/topics/api/addons.html
- Mozilla NSS reference (PK11SDR): https://firefox-source-docs.mozilla.org/security/nss/
- Have I Been Pwned API v3: https://haveibeenpwned.com/API/V3 (Padding header, k-anonymity)
- Google Chrome export: https://support.google.com/chrome/answer/10248834
- Google Online Security Blog, Chrome App-Bound Encryption: https://security.googleblog.com/2024/07/improving-security-of-chrome-cookies-on.html
- FIDO Credential Exchange Format (CXF) ready draft: https://fidoalliance.org/specs/cx/cxf-v1.0-rd-20250313.html
- FIDO Credential Exchange Protocol (CXP) working draft: https://fidoalliance.org/specs/cx/cxp-v1.0-wd-20241003.html
- HackBrowserData repo: https://github.com/moonD4rk/HackBrowserData
- Hindsight forensic parser: https://github.com/RyanDFIR/hindsight
- Mozilla Glean (Python): https://mozilla.github.io/glean/python/glean/index.html
- Sentry Python SDK: https://docs.sentry.io/platforms/python/
- WinSparkle (Windows AppCast updates): https://winsparkle.org/
- PyInstaller versioning / icon / signing docs: https://pyinstaller.org/en/stable/usage.html
- SignPath (open-source code signing path): https://signpath.org/
- Microsoft SignTool documentation: https://learn.microsoft.com/en-us/dotnet/framework/tools/signtool-exe

Areas not fully verified this pass:

- Live Firefox import acceptance for every generated SQLite/JSONLZ4 artifact — no real Firefox profile was driven end-to-end.
- ABE sidecar end-to-end (no binary built locally; no Chrome 127+ ABE-only profile under test on this VM).
- AMO curated-map audit not re-run live (fans out across 67 entries; left to monthly cron).
- Release workflow was inspected but not executed (no signing cert available).
- Real-screen GUI render and keyboard navigation not piloted under accessibility tools; theme polish only inspected via QSS.
- macOS Keychain / Linux libsecret paths exercised only via unit tests, not on real profiles.

## Current Product Map

### Core workflows

- **GUI forward migration**: detect Chromium + Firefox profiles → choose source → choose target or files-only → select categories → review preview → run → open generated artifacts. Five-step wizard with left-rail step indicator.
- **GUI reverse migration**: direction toggle on Source page swaps source/target families; passwords/bookmarks/extensions supported.
- **CLI**: `list`, `migrate`, `migrate-reverse`, `diff`, `snapshot`, `restore`. Substring-matched profile names with ambiguity refusal.
- **Curated extension-map maintenance**: monthly cron auditor + `scripts/check_curated_map.py --strict-stale` + reverse harvester `harvest_reverse_map.py`.
- **Snapshot/restore**: `.fxport` ZIP-or-PBKDF2-AES-GCM bundles with SHA-256-per-file integrity and (now) overwrite policy on restore.
- **Release packaging**: `workflow_dispatch` Windows-only PyInstaller onedir ZIP via GitHub Actions.

### Existing features (33 user-visible)

1. Profile discovery for ~20 Chromium- and Firefox-family browsers, with running/locked surfacing.
2. Direction toggle (forward / reverse).
3. Manual source drag-and-drop (Chromium profile dir, User Data dir, or `Login Data` file → synthetic profile).
4. Items step with ten categories: passwords, bookmarks, extensions, cookies, history, autofill, cards, search engines, open tabs, downloads.
5. Allow-online-AMO toggle.
6. HIBP opt-in scan.
7. Direct-write checkboxes: passwords (NSS), cookies, history, open tabs.
8. Dry-run mode (with persistent warn banner on the Run page).
9. Output folder picker.
10. Customize dialogs: password preview/filter (with mask), bookmark folder filter, history time-range filter.
11. Preview tree with counts per category (passwords, bookmarks, extensions, cookies, history, autofill, cards, search engines, open tabs, downloads).
12. ABE detection + downgrade with warning copy (passwords/cookies disabled when only ABE key present).
13. Run page log + progress bar + dry-run banner.
14. Done state with action buttons (currently only 5 categories; see gap below).
15. Settings dialog with output-dir / mask-default / AMO-default / dry-run-default / HIBP-default + two disabled future flags.
16. File menu: Rescan, Open output folder, Settings, Quit.
17. Help menu: About.
18. closeEvent guard mid-migration (3 s thread wait).
19. Encrypted/plain `.fxport` snapshot creation (CLI).
20. `.fxport` restore with overwrite policy (CLI).
21. Profile diff CLI.
22. Generated `README.txt` per migration (now covers all artifact keys + reverse).
23. Curated extension map (67 Chrome IDs across 14 categories) — `_meta` block with version stamps.
24. AMO Gecko-ID probe + name-search + permission-overlap scoring.
25. Already-installed extension detection + collapsed `<details>` UI in `extensions.html`.
26. NSS direct-write into `logins.json` + `logins-backup.json` with timestamped backup + corruption refusal.
27. Cookies/history direct-write with WAL/SHM sibling clearing and timestamped backups.
28. Open-tabs SNSS Pickle parser + UTF-8 regex fallback + mozLz40 recovery.jsonlz4 emit.
29. Form autofill v5 schema with `moz_sources` + `moz_history_to_sources`.
30. Saved cards CSV in 1Password-importable layout.
31. Search engines OpenSearch XML per engine + JSON inventory.
32. Downloads CSV export.
33. External bookmark adapters (Pocket / Pinboard / OPML / Netscape) — present and tested but not surfaced.

### User personas

- Windows users migrating from a Chromium browser to Firefox-family.
- Privacy-conscious users who want local-only operation and a clear network surface.
- Power users with many profiles or portable Firefox installs.
- IT/support operators who need repeatable migration output, logs, and snapshots.
- Maintainers extending categories or browser support.

### Platforms and distribution

- Runtime: Python 3.11+; CI matrix Windows/macOS/Linux × 3.11/3.12.
- Distribution: GitHub Releases → Windows ZIP. macOS/Linux packaging not represented in `release.yml`.
- Settings file: `%APPDATA%/FoxPort/config.json`, `~/Library/Application Support/FoxPort`, `$XDG_CONFIG_HOME/FoxPort` (per `foxport/config.py`).

### Integrations, permissions, storage, data flows

- Source profiles are read-only: SQLite is copied to a temp dir before connection; WAL/SHM siblings copied too.
- Decrypt path: DPAPI on Windows (with ABE sidecar fallback for Chrome 127+), Keychain + PBKDF2-SHA1(1003) on macOS, libsecret/kwallet/peanuts + PBKDF2-SHA1(1) on Linux.
- Firefox decrypt path: NSS via ctypes against the **target** install's `nss3.dll`; profile must be closed.
- Optional network: `addons.mozilla.org/api/v5/...` for extension metadata; `api.pwnedpasswords.com/range/<5char>` for HIBP.
- No telemetry, crash reporting, or update checks today; the Settings dialog has disabled placeholders for the first two.
- Output: dated subdir under the configured output root containing per-category artifacts + `README.txt`.
- Snapshot: separate `.fxport` file with ZIP + manifest, optionally encrypted.

## Feature Inventory

Each feature lists user value, entry point, main code locations, maturity, tests/docs, and improvement opportunities. Confidence labels: **Verified** (this pass), **Likely** (consistent with code but not exercised), **Assumption** (needs live validation).

### Profile Detection
- Value: zero-config discovery of installed browsers.
- Entry point: GUI startup `DetectWorker`; CLI `list`/`migrate`/`diff`/`migrate-reverse`.
- Code: [`foxport/browsers/detect.py`](foxport/browsers/detect.py), [`foxport/gui/workers.py:72-86`](foxport/gui/workers.py#L72-L86).
- Maturity: **Verified** complete across registered vendors; **Likely** brittle for user-installed portable variants and Thunderbird/SeaMonkey not covered.
- Tests/docs: README + `docs/architecture.md`; no `tests/test_detect.py`.
- Improvements: custom profile path entry; `list --detail` with per-category cheap counts; fixture tests for `profiles.ini` flat vs profile layout; Opera GX flat-layout regression test.

### Source / Target Wizard + Direction Toggle
- Value: high-confidence picking + bi-directional support.
- Entry point: `SourcePage`, `TargetPage`.
- Code: [`foxport/gui/pages.py:163-503`](foxport/gui/pages.py#L163-L503), [`foxport/gui/main_window.py:83-99`](foxport/gui/main_window.py#L83-L99).
- Maturity: **Verified** complete in working tree.
- Tests/docs: README screenshots (stale); no GUI automation.
- Improvements: refresh screenshots after downloads-row UI change; test direction switching; surface a "No profiles found, here's how to drop a folder" empty-state link.

### Manual Source Drag-and-Drop
- Value: migrate from copied profiles + future external bookmark sources.
- Entry point: manual tile on `SourcePage`.
- Code: [`foxport/gui/pages.py:307-369`](foxport/gui/pages.py#L307-L369).
- Maturity: **Verified** works for Chromium profile / User Data / `Login Data`; **Verified** *does not* accept external bookmark formats (Pocket/Pinboard/OPML/Netscape) despite their adapters existing.
- Tests/docs: no GUI test; adapters tested in isolation.
- Improvements: extend to dropped bookmark files via `foxport.import_.adapters`; route to a new "Import bookmarks only" path.

### Category Selection (Items)
- Value: scope control.
- Entry point: `ItemsPage`, CLI `--items` / `--all`.
- Code: [`foxport/gui/pages.py:507-895`](foxport/gui/pages.py#L507-L895), [`foxport/cli.py:120-133`](foxport/cli.py#L120-L133).
- Maturity: **Verified** 10 categories selectable; **Verified** `set_counts()` only accepts five (passwords/bookmarks/extensions/cookies/history) — the other five badges never update on back-nav.
- Tests/docs: no GUI test; mention in README.
- Improvements: extend `set_counts()` to all 10; persist counts on `MigrationContext`; consider a `count_dict: dict[str, int]` instead of positional args.

### Password Export (CSV + Direct-Write via NSS)
- Value: portable CSV + opt-in `logins.json` install.
- Entry point: Items checkbox; "Review" customize; CLI `migrate`.
- Code: [`foxport/migrate/passwords.py`](foxport/migrate/passwords.py), [`foxport/migrate/nss_passwords.py`](foxport/migrate/nss_passwords.py), [`foxport/crypto/dpapi.py`](foxport/crypto/dpapi.py), [`foxport/crypto/nss.py`](foxport/crypto/nss.py).
- Maturity: **Verified** mature; deterministic GUIDs, accounting invariant, `LoginsCorruptError`, atomic `_atomic_write` in nss_passwords, refusal on locked target.
- Tests/docs: `tests/migrate/test_passwords.py`, `test_nss_passwords.py`; docs/architecture.
- Improvements: NSS version validation pre-encrypt; conflict review (skip/merge/overwrite per duplicate); manifest entry with sensitivity flag; CSV cleanup-after-import reminder copy already exists in instructions but not surfaced in GUI Done state.

### HIBP Password Scan
- Value: opt-in breach intelligence with no plaintext disclosure.
- Entry point: Items checkbox, settings default, CLI `--hibp`.
- Code: [`foxport/crypto/hibp.py`](foxport/crypto/hibp.py), passwords migrator integration.
- Maturity: **Verified** complete; UA reflects `__version__`; `Add-Padding: true` honored.
- Tests/docs: `tests/crypto/test_hibp.py`; README "What's new" but README "Security notes" still mention only AMO.
- Improvements: distinguish "no hits" vs "unchecked due to network failure" in run log and manifest; expose offline corpus path for high-privacy users.

### Bookmark Export
- Value: durable Netscape HTML import path.
- Entry point: Items + "Folders" customize; CLI.
- Code: [`foxport/migrate/bookmarks.py`](foxport/migrate/bookmarks.py), [`foxport/gui/dialogs.py:258-345`](foxport/gui/dialogs.py#L258-L345).
- Maturity: **Verified** complete forward; reverse via `migrate_reverse/bookmarks.py`.
- Tests/docs: `tests/migrate/test_bookmarks.py`.
- Improvements: external bookmark adapter surface; merged multi-source imports; pre-existing toolbar relocation note already in `import_instructions`.

### Extension Mapping
- Value: bridges Chrome IDs → AMO with confidence metadata.
- Entry point: Items; monthly auditor.
- Code: [`foxport/migrate/extensions.py`](foxport/migrate/extensions.py), `foxport/data/curated_extension_map.json` (67 Chrome IDs), `scripts/check_curated_map.py`, `scripts/harvest_reverse_map.py`.
- Maturity: **Verified** strong; **Verified** curated map loaded at import time only (`extensions.py` module-level `load_curated_map()`).
- Tests/docs: `tests/migrate/test_extensions.py`; CI monthly audit.
- Improvements: in-process cache for AMO results within a single run; explicit "lookup unavailable" downgrade label distinct from "no match"; "Refresh curated map" action in Settings; correct README/CLAUDE.md "63 entries" claim (now 67).

### Cookies Export and Direct-Write
- Value: session continuity.
- Entry point: Items checkbox + direct-write checkbox.
- Code: [`foxport/migrate/cookies.py`](foxport/migrate/cookies.py), [`foxport/migrate/nss_cookies.py`](foxport/migrate/nss_cookies.py).
- Maturity: **Verified** complete; **Verified** atomic replace into target; **Verified** WAL/SHM clean.
- Tests/docs: `tests/migrate/test_cookies.py`.
- Improvements: per-host conflict preview; rollback manifest; ensure SHA-256 HOST_KEY prefix strip path is gated on `Cookies.meta.version >= 24` not platform (current behavior is version-gated which is correct, but the comment in CLAUDE.md should reflect it).

### History Export and Direct-Write
- Value: Awesome Bar continuity post-migration.
- Entry point: Items + "Range" customize + direct-write checkbox.
- Code: [`foxport/migrate/history.py`](foxport/migrate/history.py), [`foxport/migrate/nss_history.py`](foxport/migrate/nss_history.py), [`foxport/crypto/mozhash.py`](foxport/crypto/mozhash.py).
- Maturity: **Verified** strong after v1.2.0 schema/hash fixes; favicons backed up not deleted.
- Tests/docs: `tests/migrate/test_history.py`, `test_mozhash.py`.
- Improvements: integrate `downloads` into `moz_annos` when history direct-write is selected; surface time-range chip in Preview when active; rollback manifest.

### Autofill Export
- Value: form recall preservation.
- Entry point: Items.
- Code: [`foxport/migrate/autofill.py`](foxport/migrate/autofill.py).
- Maturity: **Verified** complete (formhistory.sqlite v5 with new `moz_sources` tables).
- Tests/docs: `tests/migrate/test_autofill.py`.
- Improvements: optional direct-write toggle with locked-profile checks (currently CSV-shaped sqlite only ships to staging); preview count is wired.

### Saved Cards Export
- Value: recover plaintext card data into a password manager flow.
- Entry point: Items.
- Code: [`foxport/migrate/cards.py`](foxport/migrate/cards.py).
- Maturity: **Verified** at CSV level; **Likely** redundant column (cardholder appears twice — Name and Cardholder name).
- Tests/docs: **no `test_cards.py`**.
- Improvements: add tests; clarify column duplication; sensitivity label in manifest; richer instructions for Bitwarden + 1Password import; cleanup reminder in Done UX.

### Search Engines Export
- Value: keep custom engines + keywords.
- Entry point: Items.
- Code: [`foxport/migrate/search_engines.py`](foxport/migrate/search_engines.py).
- Maturity: **Verified** complete at file level.
- Tests/docs: **no dedicated test**.
- Improvements: add tests; validate generated OpenSearch XML; Done-screen "Reveal search-engines folder" action.

### Open Tabs Export and Direct-Write
- Value: recover the active session.
- Entry point: Items + direct-write checkbox (newly wired in working tree).
- Code: [`foxport/migrate/open_tabs.py`](foxport/migrate/open_tabs.py), [`foxport/gui/workers.py:367-384`](foxport/gui/workers.py#L367-L384), [`foxport/gui/main_window.py:317`](foxport/gui/main_window.py#L317).
- Maturity: **Verified** working; **Likely** silent failure mode — if the structural Pickle parser returns *some* URLs but the regex fallback would have returned more, the fallback never fires.
- Tests/docs: `tests/migrate/test_open_tabs.py`.
- Improvements: emit a warning when structural parser yields suspiciously few URLs; add a sanity ratio check against regex output; expand SNSS test fixtures for new Chrome versions.

### Downloads Export
- Value: portable downloads inventory.
- Entry point: Items.
- Code: [`foxport/migrate/downloads.py`](foxport/migrate/downloads.py).
- Maturity: **Verified** at CSV level; direct-write into `moz_annos` is queued but not implemented.
- Tests/docs: **no dedicated test**.
- Improvements: add tests; implement annotations write when history direct-write is selected.

### Reverse Firefox → Chromium
- Value: enable round-trips and seed Chromium profiles.
- Entry point: direction toggle; CLI `migrate-reverse`.
- Code: [`foxport/browsers/firefox_read.py`](foxport/browsers/firefox_read.py), [`foxport/migrate_reverse/*.py`](foxport/migrate_reverse/).
- Maturity: **Verified** narrow by design (passwords/bookmarks/extensions); **Verified** no reverse-specific tests.
- Tests/docs: README; no `tests/migrate_reverse/`.
- Improvements: reverse-specific unit tests; reverse preview counts; future direct-write blocked behind conflict design.

### Diff CLI
- Value: pre-flight comparison.
- Entry point: CLI `diff`.
- Code: [`foxport/diff.py`](foxport/diff.py), [`foxport/cli.py:421-449`](foxport/cli.py#L421-L449).
- Maturity: **Verified** useful; narrow scope.
- Tests/docs: README; no `test_diff.py`.
- Improvements: JSON output; cookies-by-host and history-by-day summary; GUI "Compare first" affordance.

### Snapshot + Restore (`.fxport`)
- Value: portable migration archive with passphrase.
- Entry point: CLI `snapshot` / `restore`.
- Code: [`foxport/snapshot.py`](foxport/snapshot.py), `tests/test_snapshot.py`.
- Maturity: **Verified** good security baseline (PBKDF2-HMAC-SHA256 200k, AES-256-GCM, SHA-256-per-file); **Verified** atomic snapshot creation (uses `write_bytes_atomic`); **Verified** overwrite policy on restore.
- Tests/docs: `tests/test_snapshot.py` (42 new lines added in working tree).
- Improvements: GUI snapshot/restore; bundle contents preview before restore; PBKDF2 iteration count carried in the encrypted header is correct, but consider tracking schema-version of the manifest for forward compat; nested-`.fxport` detection.

### Settings Dialog
- Value: persisted defaults.
- Entry point: File → Settings.
- Code: [`foxport/config.py`](foxport/config.py), [`foxport/gui/dialogs.py:480-594`](foxport/gui/dialogs.py#L480-L594).
- Maturity: **Verified** baseline; disabled telemetry/crash checkboxes still visible.
- Tests/docs: `tests/test_config.py`.
- Improvements: add NSS path override (currently env var only); "Reset to defaults"; move disabled future flags out of UI until they ship.

### Release / Packaging
- Value: non-developer install.
- Entry point: GitHub Actions release workflow + `foxport.spec`.
- Code: [`.github/workflows/release.yml`](.github/workflows/release.yml), [`foxport.spec`](foxport.spec).
- Maturity: **Verified** partial. Builds + ABE compile + ZIP + GH release; **Verified** no Authenticode signing; no app icon; no version resource; no signed appcast.
- Tests/docs: README install snippet.
- Improvements: signing, icon, version resource, packaged smoke test, checksum file as separate artifact.

## Competitive and Ecosystem Research

### Firefox built-in import wizard
- Imports bookmarks/history/passwords/extensions/autofill from a small set of browsers; Mozilla now points Chrome users to CSV.
- Learn: set expectations around closed-profile + checklist + reassurance copy.
- Avoid: promising silent-import when platform restrictions force CSV.

### Google Chrome / Google Takeout export
- Account-side archive of bookmarks/history/autofill/extensions/etc.
- Learn: "archive" language + per-class manifests + dates.
- Avoid: conflating account exports with local secrets — FoxPort's value is the local stuff.

### HackBrowserData
- Broad cross-browser local extraction (passwords/cookies/history/cards/etc.) with CSV/JSON/ZIP output and `list --detail`.
- Learn: machine-readable output, custom profile path, ZIP bundling, per-vendor matrix.
- Avoid: stealth-extraction framing; FoxPort is consent-driven migration, not exfil.

### Hindsight
- Forensic browser-artifact parser with strong provenance.
- Learn: artifact provenance, schema version per parse, structured failure context.
- Avoid: timeline UI; migration stays the product.

### Mozilla Add-ons API (AMO)
- Public detail + search endpoints, GUID/slug, ratings, permissions, statuses.
- Learn: current use is appropriate; cache lookups per run; flag stale curated rows.
- Avoid: auto-install; keep browser-mediated install consent.

### Have I Been Pwned Pwned Passwords
- Free k-anonymity prefix API + `Add-Padding`.
- Learn: current usage is aligned; distinguish "not checked" from "no hits"; offline corpus integration possible.
- Avoid: incremental / non-anonymized queries.

### App-Bound Encryption (Chrome 127+)
- New service-mediated key wrap on Windows for cookies/passwords.
- Learn: sidecar must be signed and trust-messaged; explain elevation before use.
- Avoid: shipping unsigned elevated helper as a default.

### FIDO CXF / CXP
- Emerging credential-exchange standard + protocol — currently the only credible path for passkey migration.
- Learn: any passkey work should start as inventory + standards alignment; export only when the destination side supports it.
- Avoid: inventing a proprietary passkey format.

### Glean / Sentry / WinSparkle / PyInstaller
- Patterns for declared metrics, error reporting, signed app-cast updates, packaged binaries.
- Learn: consent + data dictionary + local off switch + signature verification are table stakes.
- Avoid: silent enablement of any of the above.

## Highest-Value New Features

Items the prior plan also flagged remain valid; the entries below either deepen them with new evidence or replace them where the working tree has overtaken them.

### 1. Done Screen + Items Badges Parity with All Ten Categories
- User problem solved: A successful run may produce six artifacts the Done screen can't open, and the user's "back to Items" view shows count badges for only five of them.
- Evidence: [`foxport/gui/main_window.py:114-121`](foxport/gui/main_window.py#L114-L121) hardcodes six buttons (output, passwords, bookmarks, extensions, cookies, history); [`foxport/gui/pages.py:1149-1165`](foxport/gui/pages.py#L1149-L1165) and `set_done()` toggles only those keys; [`foxport/gui/pages.py:724-742`](foxport/gui/pages.py#L724-L742) accepts five count args.
- Proposed behavior: Replace the static button bar with a vertical list rendered from a `RunArtifact` data model (one row per produced artifact with title, path, action, sensitivity). Replace `set_counts(positional)` with `set_counts(dict[str, int])` and badge every selectable row.
- Implementation areas: `foxport/gui/main_window.py`, `foxport/gui/pages.py`, `foxport/gui/widgets.py`, `foxport/gui/workers.py`.
- Data model: `RunArtifact { key, path, kind, sensitivity, action (open|reveal), instructions_key }`.
- Risks / edge cases: keep the existing Reveal-vs-Open distinction for `.sqlite` files; respect dry-run (no artifacts).
- Verification: mock-run worker `finished` with all ten keys + `hibp`; manual GUI flow; tests asserting all keys produce a row.
- Complexity: M
- Priority: **P0**

### 2. `manifest.json` per Migration Run
- User problem solved: Support, rollback, snapshot, GUI Done screen, generated README, and a future JSON CLI all need one trustworthy artifact registry. Today the worker emits a `dict[str, Path]` consumed by README only.
- Evidence: [`foxport/gui/workers.py:118`](foxport/gui/workers.py#L118), [`foxport/cli.py:193`](foxport/cli.py#L193); no `manifest.json` is written today.
- Proposed behavior: Every non-dry-run run writes `manifest.json` next to `README.txt` containing schema version, FoxPort version, source/target labels, direction, items selected, per-artifact { key, relative path, byte size, SHA-256, count, sensitivity, import method, direct-write status, warnings }, network calls made (AMO yes/no, HIBP yes/no/unchecked), and dry-run flag.
- Implementation: new `foxport/manifest.py`, integrate in worker + CLI + snapshot; add validation in tests; carry the manifest into `.fxport` bundle so snapshot has both per-file digests *and* artifact metadata.
- Risks: never write plaintext passwords or cookie values; emit relative paths only; treat as the single source of truth for instructions/Done screen.
- Verification: per-artifact-key fixture tests; manual all-items run inspection; snapshot/restore round-trip with manifest reuse.
- Complexity: M
- Priority: **P0**

### 3. Signed Windows Release with Bundled ABE Sidecar
- User problem solved: Distribution is the wall between FoxPort and non-developers. Today no signed binary exists and `foxport_abe.exe` ships only if it happens to be present locally.
- Evidence: `foxport.spec:11-13` conditional bundle; no signing step in `.github/workflows/release.yml`; no `assets/icon.ico`; no version resource in `EXE(...)`.
- Proposed behavior: Release workflow builds `foxport_abe.exe` via MSVC v143 (already wired), Authenticode-signs both `FoxPort.exe` and `foxport_abe.exe` with a timestamp authority, embeds version + icon resources in `foxport.spec`, emits `FoxPort-vX.Y.Z-windows-x64.zip` plus a `*.sha256` file as a separate artifact, smoke-runs the packaged app to print `--version`, and uploads release notes derived from the matching `CHANGELOG.md` section instead of the whole file.
- Implementation: `assets/icon.ico` + `assets/version_info.txt`, `foxport.spec` (add `icon=`, `version=` for `EXE()`), `release.yml` (add SignTool step + smoke step + per-section release notes), `tools/abe_sidecar/CMakeLists.txt` (consume `signtool` post-build if cert path env present).
- Risks: cert availability; AV false positives; elevated helper trust copy must be visible *before* the sidecar runs.
- Verification: `workflow_dispatch` on a prerelease tag; `Get-AuthenticodeSignature dist/FoxPort/FoxPort.exe`; manual elevation prompt under Chrome 127+.
- Complexity: L
- Priority: **P0**

### 4. NSS `nss3.dll` Version-Skew Guard
- User problem solved: Direct-write into a target Firefox `logins.json` can corrupt the user's logins if the NSS library FoxPort loads is from a wildly different Firefox version than the profile expects. The current ctypes loader does no version check.
- Evidence: [`foxport/crypto/nss.py`](foxport/crypto/nss.py); no `NSS_VersionCheck` / `NSS_GetVersion` call; the loader searches per-browser DLL paths and uses the first match.
- Proposed behavior: On `open_session()`, capture `NSS_GetVersion` and `PK11_GetVersion`. Refuse if the major.minor differs from the Firefox profile's expected NSS pin by more than N (or if the version is missing). Log version into manifest. Allow override via env var for power users.
- Implementation: `foxport/crypto/nss.py`, regression test against a mocked NSS library, `MigrationRequest.nss_version_warning` field threaded to GUI.
- Risks: portable Firefox installs sometimes ship custom NSS; provide an override; do not block files-only / CSV mode.
- Verification: test that monkeypatches `NSS_GetVersion` and asserts refusal; manual run against a mismatched Firefox.
- Complexity: S/M
- Priority: **P1**

### 5. Direct-Write Conflict Review + Rollback Manifest
- User problem solved: Today, cookies/history direct-write replaces target DBs wholesale (after backup) and passwords merge by deterministic GUID with no user-visible policy. The product's biggest data-safety risk is the target side.
- Evidence: `nss_passwords` dedups by GUID; cookies/history replace; no preview shows target-side conflicts; rollback is implicit ("there's a backup somewhere").
- Proposed behavior: A pre-write analysis pass returns conflict sets (per category) without mutation; a dialog presents counts + samples + per-category policy (skip / merge / overwrite / backup-only); post-write manifest lists every backup and exact restore steps. CLI gets `--direct-write-policy=skip|merge|overwrite|backup-only` and `--yes`.
- Implementation: new `foxport/migrate/conflicts.py` (`analyze_passwords()`, `analyze_cookies()`, `analyze_history()`), new dialog, manifest entries.
- Risks: large cookie/history sets — keep summaries by host/day; never log plaintext.
- Verification: synthetic target fixtures; locked-profile failure case; GUI manual smoke.
- Complexity: XL
- Priority: **P1**

### 6. GUI Snapshot + Restore (with Bundle Inspect)
- User problem solved: `.fxport` is one of FoxPort's highest-leverage features and CLI-only today.
- Evidence: `snapshot.py` is tested; `RunPage` has no snapshot action; File menu has no Restore.
- Proposed behavior: Done screen offers "Save as snapshot…" (passphrase optional, with strength meter). File menu adds "Restore from snapshot…": pick file → inspect (manifest + file list) → choose staging output dir (refuses non-empty unless user confirms) → run with integrity check and progress.
- Implementation: `foxport/gui/dialogs.py` (passphrase dialog + bundle viewer), `foxport/gui/pages.py`, `foxport/gui/main_window.py`, `foxport/snapshot.py` (return file list pre-extract).
- Risks: wrong-passphrase UX; nested `.fxport` exclusion; partial restore interruption.
- Verification: GUI manual snapshot/restore using fixture output folder; encrypted/plain round-trip; large-bundle responsiveness.
- Complexity: M
- Priority: **P1**

### 7. External Bookmark Import Surface
- User problem solved: Pocket/Pinboard/OPML/Netscape support exists in `foxport/import_/adapters.py` and is tested, but no user can reach it. The drag tile only accepts Chromium profiles.
- Evidence: [`foxport/import_/adapters.py`](foxport/import_/adapters.py); `tests/test_import_adapters.py`; no production caller.
- Proposed behavior: Two surfaces — (a) CLI `import-bookmarks --input <file> --out bookmarks.html [--format auto|pocket|pinboard|opml|netscape]`; (b) GUI manual drop tile detects bookmark file by suffix/content and routes to a "Convert bookmarks" path that writes a single-purpose Netscape HTML with folder paths preserved where the source had them.
- Implementation: shared emitter (`bookmarks._write_netscape_html(roots)` could lift the inner emitter into a reusable function), new CLI subcommand, GUI drag handler branch, tests.
- Risks: OPML is often feeds, not bookmarks — be explicit in UI.
- Verification: CLI subcommand on every adapter fixture; GUI drop with each format; round-trip test.
- Complexity: M
- Priority: **P1**

### 8. First-Run Trust Dialog + Network Activity Preview Row
- User problem solved: FoxPort markets local-only but optional AMO and HIBP calls exist, telemetry/crash/update are roadmap'd, and there's no centralized network disclosure.
- Evidence: Settings has disabled telemetry/crash placeholders ([`foxport/gui/dialogs.py:550-563`](foxport/gui/dialogs.py#L550-L563)); README security notes only mention AMO; no first-run UX.
- Proposed behavior: On first launch (no `first_run_acked: true` in `config.json`), show a modal that explains: source is read-only; sensitive outputs are listed; optional network calls are AMO + HIBP; future telemetry/crash/update are off and require opt-in. Add a "Network activity for this run" section to Preview listing every optional endpoint and what gets sent.
- Implementation: `foxport/config.py` (consent timestamps + version), new `FirstRunDialog`, Preview page network section.
- Risks: consent fatigue; do not block offline use.
- Verification: fresh config flow; tests for consent persistence; no network calls when all toggles off.
- Complexity: M
- Priority: **P1**

### 9. CLI `--json` and `list --detail`
- User problem solved: IT/support automation can't parse human prints. HackBrowserData covers this idiom well.
- Evidence: [`foxport/cli.py:136-516`](foxport/cli.py#L136-L516); no `--json` flag.
- Proposed behavior: `--json` on `list`, `migrate`, `migrate-reverse`, `diff`, `snapshot`, `restore`. Stable schema with version. `list --detail` adds per-category cheap counts when achievable without decryption. Never include plaintext secrets.
- Implementation: `foxport/cli.py`, count helpers reused from preview, schema test snapshots.
- Risks: schema bumps must be additive; secret leakage prevention.
- Verification: schema snapshot tests under pytest; manual PowerShell + Bash runs.
- Complexity: M
- Priority: **P2**

### 10. Passkey Inventory Prototype + Extension Settings Allowlist
- User problem solved: Passwords aren't the whole identity story anymore (passkeys), and extension *settings* are higher-effort than mere reinstall.
- Evidence: ROADMAP mentions FIDO CXF + extension-settings best-effort.
- Proposed behavior: Two narrow, opt-in tracks — a `passkeys inventory` CLI that detects `Web Data.webauthn_credentials` presence + counts and emits a feasibility report (no export until CXF/CXP destination support); an `extension-settings` allowlist for ~2 high-value extensions (e.g. uBlock Origin filter lists; Stylus userstyles) where the format is stable and consent is explicit.
- Implementation: `foxport/migrate/passkeys.py` (inventory only), `foxport/migrate/extension_settings.py` (allowlist with per-extension exporter), docs, tests.
- Risks: passkey private key material may not be exportable; extension storage may contain tokens; consent must be explicit per item.
- Verification: synthetic `Web Data.webauthn_credentials` fixtures; fixture extension storage; review against FIDO drafts.
- Complexity: XL (combined)
- Priority: **P2** (passkey inventory) / **P2** (extension-settings allowlist)

## Existing Feature Improvements

### Atomic-Replace for Staging Writers (not only target-profile writers)
- Current behavior: The working tree introduced `foxport/fileops.py` and routed `nss_cookies`/`nss_history`/`open_tabs` direct-writes through `replace_file_atomic()`. But the **staging-folder** emitters (`passwords.py` → CSV, `bookmarks.py` → HTML, `cookies.py` → SQLite, `history.py` → SQLite, `autofill.py` → SQLite, `cards.py` → CSV, `downloads.py` → CSV, `search_engines.py` → JSON+XML, `open_tabs.py` non-direct-write recovery.jsonlz4) still write directly to the final filename.
- Problem: A crash mid-write leaves a corrupt artifact at the final name; the README.txt then references it; snapshot bundles can include partially written files.
- Recommended change: Either route every staging writer through `write_bytes_atomic()` (small overhead) or wrap each emitter in a tmpfile-then-replace helper.
- Code locations: all of `foxport/migrate/*.py` non-`nss_*` emitters.
- Backward compat: none (file names unchanged).
- Verification: unit test with monkeypatched write failure; ensure no `.foxport-*` orphans remain.
- Complexity: M
- Priority: **P1**

### `ItemsPage.set_counts()` Accepts All Ten Categories
- Current: positional args for five categories; the other five appear in Preview but not in Items badges on back-nav.
- Problem: Items counts get stale relative to what Preview actually computes.
- Recommended change: `set_counts(counts: dict[str, int])` keyed by item slug; persist on `MigrationContext.counts: dict[str, int]`.
- Code locations: [`foxport/gui/pages.py:724-742`](foxport/gui/pages.py#L724-L742), [`foxport/gui/main_window.py:287-293`](foxport/gui/main_window.py#L287-L293).
- Backward compat: none (private API).
- Verification: Test driving `set_counts` with all ten keys; manual back-nav.
- Complexity: S
- Priority: **P1**

### Open-Tabs Partial-Success Warning
- Current: structural Pickle parser; if it returns ≥1 URL, the UTF-8 fallback never runs.
- Problem: Chrome SNSS schema drift can cause silent under-count.
- Recommended change: Always run both parsers internally; if regex would have returned >1.5× the structural URLs, log a warning, surface it on the run page, and prefer the regex result (or take the union and dedupe by URL).
- Code locations: [`foxport/migrate/open_tabs.py`](foxport/migrate/open_tabs.py).
- Verification: synthetic SNSS fixture where structural returns 2 and regex returns 10; assert the warn path.
- Complexity: S
- Priority: **P2**

### Documentation Drift (curated map entry count + Security notes)
- Current: README says "63-entry curated map" / CLAUDE.md "63-entry"; the file actually has 67 Chrome IDs across 14 categories. README "Security notes" only mentions AMO, not HIBP. `foxport/browsers/firefox.py:6` docstring claims FoxPort "writes Firefox-native import files" only — but direct-write modules exist.
- Problem: Trust-product needs accurate docs.
- Recommended change: Replace fixed counts with a dynamic check (or just update to 67 and refresh on each map PR); update Security notes to mention HIBP; correct docstring; rerun screenshots.
- Code locations: `README.md`, `CLAUDE.md`, `foxport/browsers/firefox.py:1-9`, `assets/screenshots/`.
- Verification: docs grep + screenshot diff.
- Complexity: S
- Priority: **P2**

### Cards CSV Column Duplication
- Current: `migrate_cards()` emits "Type, Name, Number, Expiration, Cardholder name, Notes" where Name and Cardholder are the same value (per the audit).
- Problem: Importers may dedupe; signals sloppy CSV.
- Recommended change: Drop the redundant column or differentiate (Name = network display; Cardholder = the actual name).
- Code locations: `foxport/migrate/cards.py`.
- Verification: add `tests/migrate/test_cards.py` asserting column shape.
- Complexity: S
- Priority: **P2**

### Curated Map Hot-Reload + In-Run Cache
- Current: `extensions.py` loads curated JSON at import time; no in-run cache for AMO lookups (each unmatched ID hits the network once per run, but if the user clicks "back" + "next" the worker re-runs lookups).
- Problem: Curated map updates require app restart; AMO calls aren't memoized across worker runs.
- Recommended change: Lazy-load + reload-on-stat-change; a module-level dict cache keyed by Chrome ID; clear-on-Settings-action.
- Code locations: `foxport/migrate/extensions.py`.
- Complexity: S
- Priority: **P3**

### Reverse Curated-Map Auditor
- Current: `harvest_reverse_map.py` populates `AMO_GUID_TO_CHROME`; `check_curated_map.py --strict-stale` audits only the **forward** map.
- Problem: Reverse direction degrades silently when GUIDs go missing.
- Recommended change: Extend the monthly audit workflow to also verify reverse GUIDs against AMO; surface entries in the issue body.
- Code locations: `scripts/check_curated_map.py`, `.github/workflows/curated-map-audit.yml`.
- Complexity: S
- Priority: **P2**

### Test Coverage Gaps (downloads, cards, search engines, diff, reverse)
- Current: 97 tests pass; the audit confirmed no `test_cards.py`, no `test_downloads.py`, no `test_search_engines.py`, no `test_diff.py`, no `tests/migrate_reverse/`.
- Problem: New writers shipped without regression coverage.
- Recommended change: Add focused tests with synthetic Web Data / History fixtures.
- Code locations: `tests/migrate/`, `tests/migrate_reverse/`, `tests/test_diff.py`.
- Complexity: M
- Priority: **P1**

### Generated README → Manifest-Driven (consolidates with #2)
- Current: `import_instructions()` now covers all artifact keys (verified in `test_import_instructions.py`), but it's a separate hand-written switch from the manifest the run produces.
- Recommended change: After landing `manifest.json` (#2), generate README sections from manifest entries plus a small per-artifact template; remove the hand-written switch.
- Complexity: S after #2
- Priority: **P2**

### Done-Screen "Reveal backups" Action (post direct-write)
- Current: Backups are created with timestamped names but the Done UI doesn't surface them.
- Recommended change: When the manifest reports a `backup_path`, render a "Reveal backup" action and a "Restore from backup" instructions block.
- Complexity: S
- Priority: **P2**

### Settings: NSS Path Override + Reset to Defaults
- Current: `FOXPORT_NSS_PATH` env var is documented but not exposed in Settings; Settings has no Reset action.
- Recommended change: Add an Advanced section with an NSS path field and a "Reset to defaults" button.
- Code locations: `foxport/config.py`, `foxport/gui/dialogs.py`, `foxport/crypto/nss.py`.
- Complexity: M
- Priority: **P2**

### Refresh Screenshots + Docs After UI Stabilization
- Current: `assets/screenshots/3-items.png` predates the downloads row.
- Recommended change: Re-run `scripts/capture_screenshots.py` after the working tree theme polish lands and the Items/Run pages stabilize.
- Complexity: S
- Priority: **P2**

### Help Menu Affordances
- Current: Help menu contains only "About". No "Open documentation", "Report a problem", "Check for updates", "View change log".
- Recommended change: Add docs link (file-or-URL), `Open output folder`, "Report a problem" (preformatted GitHub issue with manifest summary), and a stub for "Check for updates" guarded by a feature flag until the appcast lands.
- Complexity: S
- Priority: **P3**

## Reliability, Security, Privacy, and Data Safety

Bugs / risks found this pass:

- **Verified** Done-screen UI only opens five categories; `set_counts()` accepts five — the wizard offers ten.
- **Verified** Staging-folder emitters are non-atomic (only target-profile writers got `replace_file_atomic`).
- **Verified** No NSS version-skew guard before direct-write into `logins.json`.
- **Verified** Open-tabs structural-parser-fallback gate suppresses regex when structural returns any URL.
- **Verified** No `manifest.json` per run.
- **Verified** No first-run trust dialog; no centralized network-activity surface.
- **Verified** ABE sidecar binary absent locally; release workflow does not Authenticode-sign.
- **Verified** `foxport.spec` lacks icon and version resource.
- **Verified** Reverse curated map has no auditor; forward auditor exists.
- **Verified** Documentation drift: 63 vs 67 curated entries; security notes lag HIBP; firefox.py docstring says "import files" only.
- **Likely** Cards CSV redundant column.
- **Likely** Extension settings format drift if expanded — needs explicit allowlist (current scope safe).

Missing guardrails:

- Per-category conflict review before direct-write.
- Rollback manifest with backup paths and explicit restore steps.
- Atomic-replace in staging emitters.
- NSS version validation.
- First-run consent + network disclosure.
- Release artifact smoke test inside the workflow (verify packaged EXE starts, contains `foxport_abe.exe`, signature good).

Permission / network / file-system concerns:

- ABE sidecar elevation must be explained pre-run; FoxPort must not silently invoke an unsigned helper.
- AMO + HIBP usage is opt-in but disclosure is split (Items checkboxes + README post-hoc). Surface both in Preview.
- Plaintext outputs (`passwords.csv`, `saved-cards.csv`) need stronger cleanup affordances in the GUI Done state, not only in `README.txt`.
- Snapshot passphrases are user-managed; mistyped passphrase UX is CLI-only ("encrypted bundle requires --passphrase").

Recovery / rollback needs:

- Manifest must enumerate every backup file the migration produced, with absolute paths and a one-line restore command per file.
- Snapshot restore should be dry-run-able: inspect manifest + filelist + total bytes before extraction.
- Direct-write should expose a "Reveal backups" Done action and a "Restore backup" wizard step that copies the timestamped backup back over the live file with a confirm.

Logging / diagnostics needs:

- Run log should write structured entries (parser versions, counts, failures, target-lock status, online lookup status, artifact hashes) — most are present in console output but not persisted.
- `--json` for CLI and exportable GUI log.
- Failed-network reason categories for AMO/HIBP (timeout, 5xx, dns, schema mismatch).

## UX, Accessibility, and Trust

Onboarding gaps:

- No first-run trust explanation. New users land on Source step with no context for "source stays read-only", "no plaintext leaves this machine", "network calls are optional and listed".
- "No Firefox target detected" empty state is plain copy; could link to Firefox install + portable-Firefox tutorials.

Empty / loading / error / disabled states:

- Detection runs in background but Source/Target empty states could be stronger when zero profiles found.
- Preview counts are synchronous; large profiles may feel frozen — measure and consider a background preview worker.
- Direct-write checkboxes correctly disable on reverse and when their category is unchecked; verify a11y labels stay accurate.

Destructive / irreversible actions:

- Cookies/history/open-tabs direct-write replaces target files; backups exist but no conflict preview.
- Plaintext exports persist after import; cleanup is left to user.

Settings clarity:

- Disabled telemetry/crash checkboxes are transparent but noisy in the dialog. Move them into a future "Data" surface tied to first-run when the features land.

Accessibility:

- v1.2.1 added `:focus` styling and Tile keyboard activation. Verify with screen-reader (Narrator/NVDA) + keyboard-only run; add a `tests/test_accessibility.py` smoke with `QApplication` + assert `accessibleName/Description` on key widgets.
- Extension HTML reports should pass basic semantic checks (heading levels, link text).

Microcopy / trust signals:

- Replace "direct-write" with "Install into closed Firefox profile" (technical subtitle ok).
- Surface "Source profile stays read-only" on Preview and Run pages, not only Items.
- Add a "Sensitive files in this run" callout listing plaintext outputs.
- Add a "Network requests in this run" callout listing AMO / HIBP and the exact data sent.

## Architecture and Maintainability

Module or boundary improvements:

- Centralize artifact metadata via #2's manifest model; today the artifact-key list is repeated in CLI (`ALL_ITEMS`), worker (`MigrationRequest.do_*`), Items page checkboxes, Preview counters, Done buttons, and `import_instructions`.
- Promote `replace_file_atomic()`/`write_bytes_atomic()` from `fileops.py` to the canonical writer for all on-disk emitters.
- `MigrationRequest` and `MigrationContext` should be kept in sync (or share fields via a single dataclass with a converter); mapper test if not.
- `import_/adapters.py` needs a production emitter glue path to the Netscape HTML writer (currently each adapter has its own normalized shape).
- GUI preview counts should move to a background worker; large History/Cookies probe is synchronous today.

Refactor candidates:

- `RunPage` action bar → metadata-driven artifact list widget.
- `ItemsPage._make_row` is a 50-line helper — fine, but combine the 10 row construction calls into a data-driven loop using `ITEM_DEFINITIONS` to reduce churn when a new category lands.
- `firefox.py:import_instructions` → manifest-driven generator after #2.
- `nss_cookies.py` and `nss_history.py` duplicate the `_backup_path_for()` helper — lift it.

Test gaps:

- CLI subcommand help under Windows encoding (we have the top-level; add subcommand recursive — `test_cli_help.py` already loops through subparsers, but assert encode-to-`'mbcs'` succeeds, not only ASCII).
- All-artifact Done UI render test (mock `set_done`).
- Atomic-replace failure recovery (force write-error mid-replace; assert original target unchanged).
- Reverse migrators end-to-end.
- Downloads, cards, search engines, diff.
- NSS version monkeypatch.
- Open-tabs partial-success warning.
- Snapshot restore non-empty refusal + overwrite branch — partially covered by new working-tree tests; verify edge cases (target is symlink, target contains a `.fxport`).

Documentation gaps:

- README install snippet implies Windows-only Python despite badges/code being cross-platform; soften with "Windows-first, macOS/Linux supported with the same install steps".
- Security notes section should add HIBP.
- `foxport/browsers/firefox.py:1-9` docstring should reflect direct-write reality.
- ABE sidecar docs should separate source-built helper from shipped signed helper once release work lands.

Release / build / deployment gaps:

- No `foxport_abe.exe` locally; not bundled unless built.
- No Authenticode signing.
- No icon or version resource in `foxport.spec`.
- No published release artifact verified during this pass.
- Release workflow is Windows-only despite cross-platform runtime claims; macOS/Linux distribution path is unstated.
- No SBOM / supply-chain attestation.

## Prioritized Roadmap

Land the working tree first — it already addresses items the previous plan called P0. The list below assumes those commits have shipped.

### Phase A — Commit the working tree (immediate)

- [ ] P0 — Commit the working tree on `main` and tag `v1.3.0-rc`
  - Why: All P0 items from the previous research pass are implemented but uncommitted; they include the CLI help fix, atomic snapshot, atomic direct-write, snapshot overwrite policy, generalized `import_instructions()`, and `direct_write_open_tabs` wiring.
  - Evidence: `git status` lists 14 modified + 4 new files; `pytest` reports 97 passed.
  - Touches: `RESEARCH_FEATURE_PLAN.md` (this file), `CHANGELOG.md`, all uncommitted source files.
  - Acceptance: Commit message describes the trust + safety pass; CHANGELOG has a v1.3.0 section; `pytest` passes on `main`.
  - Verify: `git log --oneline -1` after commit; CI run on PR.

### Phase B — Finish the Done/preview parity arc (next 1-2 days of work)

- [ ] P0 — Done screen + Items badges parity with all ten categories
  - Why: New artifacts produced today are unreachable from the Done screen and invisible on back-nav.
  - Evidence: `main_window.py:114-121`, `pages.py:724-742`, `pages.py:1149-1165`.
  - Touches: `foxport/gui/main_window.py`, `foxport/gui/pages.py`, `foxport/gui/widgets.py`, tests.
  - Acceptance: Every produced artifact appears with an Open/Reveal action and sensitivity label; `set_counts(counts: dict[str, int])` updates all selectable badges.
  - Verify: mock `set_done(True, ..., {key: path for key in ALL_KEYS})`; manual all-items run.

- [ ] P0 — Emit `manifest.json` per non-dry-run migration
  - Why: Single registry for Done screen, README, support, snapshot, future `--json`.
  - Evidence: `workers.py:118` + `cli.py:193` carry artifacts as plain `dict[str, Path]`; no manifest is emitted.
  - Touches: new `foxport/manifest.py`, `workers.py`, `cli.py`, `snapshot.py`, `firefox.py` (import_instructions consumes manifest), tests.
  - Acceptance: `manifest.json` next to `README.txt`; schema-version'd; never contains plaintext secrets; `.fxport` carries the manifest.
  - Verify: per-key fixture tests; `python -m foxport.cli migrate ... && jq < manifest.json`.

### Phase C — Trust and release path (next 1-2 weeks)

- [ ] P0 — Signed Windows release with bundled ABE sidecar + icon + version resource
  - Why: Distribution gates everything else.
  - Evidence: `foxport.spec:11-13`; `release.yml` has no SignTool; no `assets/icon.ico`.
  - Touches: `assets/icon.ico`, `assets/version_info.txt`, `foxport.spec`, `.github/workflows/release.yml`, `tools/abe_sidecar/CMakeLists.txt`.
  - Acceptance: Built `FoxPort.exe` is signed, has icon, has version resource matching `__version__`; ABE sidecar bundled and signed; `*.sha256` artifact separate.
  - Verify: `Get-AuthenticodeSignature dist/FoxPort/FoxPort.exe`; manual UAC prompt on a Chrome 127+ profile.

- [ ] P1 — First-run trust dialog + Preview "Network activity" section
  - Why: Local-only product needs centralized network disclosure.
  - Evidence: optional AMO + HIBP exist; future telemetry/crash/update placeholders in Settings.
  - Touches: `foxport/config.py`, `foxport/gui/dialogs.py` (new `FirstRunDialog`), `foxport/gui/pages.py` (Preview).
  - Acceptance: First launch shows trust dialog; Preview lists every optional call; off-by-default toggles persist.
  - Verify: fresh config flow; `test_config.py` updated.

- [ ] P1 — NSS version-skew guard
  - Why: Highest-value defensive line for direct-write into `logins.json`.
  - Evidence: `foxport/crypto/nss.py` does not call `NSS_VersionCheck`/`NSS_GetVersion`.
  - Touches: `foxport/crypto/nss.py`, `migrate/nss_passwords.py`, tests.
  - Acceptance: Refusal on major.minor mismatch unless `FOXPORT_NSS_FORCE` is set; manifest records NSS version.
  - Verify: monkeypatched library test; manual run against mismatched portable Firefox.

- [ ] P1 — Direct-write conflict review + rollback manifest
  - Why: The product's biggest data-safety risk.
  - Evidence: `nss_passwords` dedups by GUID; cookies/history replace; no preview shows target-side conflicts.
  - Touches: new `foxport/migrate/conflicts.py`, GUI dialog, CLI flags, tests.
  - Acceptance: Pre-write dialog shows counts/samples; per-category policy; rollback instructions in manifest.
  - Verify: synthetic target fixtures with conflicts; locked-profile abort; manual all-direct-write flow.

- [ ] P1 — Atomic-replace for staging emitters
  - Why: Crash mid-write leaves corrupt artifacts that snapshot then bundles.
  - Evidence: `passwords.py`, `bookmarks.py`, `cookies.py`, `history.py`, `autofill.py`, `cards.py`, `downloads.py`, `search_engines.py`, `open_tabs.py` non-direct paths write to final filenames.
  - Touches: every `foxport/migrate/*.py` non-`nss_*` emitter; `foxport/fileops.py` helper reuse; tests.
  - Acceptance: All emitters stage-then-replace; orphan `.foxport-*` tmpfiles cleaned on failure.
  - Verify: monkeypatched write-error test per emitter.

- [ ] P1 — Tests for downloads, cards, search engines, diff, reverse
  - Why: Recent shippers lack regression coverage.
  - Evidence: No `test_downloads.py`, `test_cards.py`, `test_search_engines.py`, `test_diff.py`, `tests/migrate_reverse/`.
  - Touches: `tests/migrate/`, `tests/migrate_reverse/`, `tests/test_diff.py`.
  - Acceptance: Synthetic-fixture suites covering success, empty, dry-run, malformed sources.
  - Verify: `pytest`.

- [ ] P1 — GUI snapshot + restore with bundle inspector
  - Why: `.fxport` is high-value and CLI-only.
  - Evidence: `RunPage` has no snapshot action; File menu has no Restore.
  - Touches: `foxport/gui/dialogs.py`, `pages.py`, `main_window.py`, `snapshot.py`.
  - Acceptance: Done screen "Save as snapshot…" works (encrypted/plain); File menu Restore inspects manifest, refuses non-empty dirs.
  - Verify: GUI manual snapshot/restore; large-bundle responsiveness.

- [ ] P1 — Surface external bookmark adapters (CLI + GUI)
  - Why: Tested adapters have no production caller.
  - Evidence: `foxport/import_/adapters.py`, `tests/test_import_adapters.py`; no production callsites.
  - Touches: new CLI subcommand `import-bookmarks`, GUI drop handler branch, shared Netscape emitter.
  - Acceptance: CLI converts each format to bookmarks.html; GUI accepts dropped bookmark files.
  - Verify: `python -m foxport.cli import-bookmarks --input fixture.opml --out out.html`.

### Phase D — Polish + observability (P2 / P3)

- [ ] P2 — CLI `--json` + `list --detail`
- [ ] P2 — Cards CSV column cleanup + `test_cards.py`
- [ ] P2 — Open-tabs partial-success warning
- [ ] P2 — Reverse curated-map auditor + monthly workflow update
- [ ] P2 — Documentation + screenshot refresh (curated count, HIBP in security notes, firefox.py docstring, Items page screenshot)
- [ ] P2 — Settings: NSS path override + Reset to defaults
- [ ] P2 — Done "Reveal backups" action
- [ ] P2 — Downloads direct-write into `moz_annos` when history direct-write is selected
- [ ] P2 — All-artifact Done UI render test; atomic-replace failure recovery test; NSS version monkeypatch test

- [ ] P3 — Opt-in Glean telemetry with declared metrics
- [ ] P3 — Opt-in Sentry crash reporting (path-stripped)
- [ ] P3 — Signed update appcast (WinSparkle/NetSparkle)
- [ ] P3 — Passkey inventory CXF prototype
- [ ] P3 — Extension settings allowlist (uBlock Origin, Stylus)
- [ ] P3 — Help menu affordances (docs, change log, report a problem)
- [ ] P3 — Curated map hot-reload + in-run AMO cache
- [ ] P3 — macOS/Linux distribution path (PyInstaller per OS + signed/notarized macOS app)

## Quick Wins

- Commit the working tree as the v1.3.0-rc baseline.
- Update README/CLAUDE.md to say "67 curated entries" (or load the count dynamically).
- Update README "Security notes" to mention optional HIBP network calls.
- Fix `foxport/browsers/firefox.py:1-9` docstring to acknowledge direct-write modules.
- Add `set_counts(counts: dict[str, int])` signature with the existing five plus the new five.
- Replace the six fixed Done buttons with an iteration over `exports`.
- Add a CI step that runs `python -m foxport.cli --help` and asserts `"->"` in the description (no Unicode arrow regression).
- Re-run `scripts/capture_screenshots.py` after Items/Run polish.
- Lift `_backup_path_for()` into a shared `fileops` helper.
- Add `test_cards.py`, `test_downloads.py`, `test_search_engines.py`, `test_diff.py` shells with smoke assertions; expand later.

## Larger Bets

- Signed Windows release with bundled signed ABE helper + icon + version resource + checksum + smoke test.
- Manifest-driven Done/README/snapshot/CLI-JSON architecture replacing today's `dict[str, Path]`.
- Direct-write conflict resolution and rollback model across passwords/cookies/history/open-tabs.
- GUI snapshot/restore with passphrase UX, dry-run inspection, and safe extraction.
- macOS/Linux distribution path (PyInstaller per OS; signed/notarized macOS; AppImage or `.deb` on Linux).
- Standards-led passkey inventory/export once CXF/CXP and browser local data constraints are verified.
- Narrow extension settings allowlist for two high-value extensions.
- Opt-in telemetry/crash/update infrastructure with declared data dictionary and strong privacy docs.

## Explicit Non-Goals

- Do not become a Firefox Sync replacement; FoxPort migrates local state, not ongoing sync.
- Do not silently modify source Chromium profiles.
- Do not silently write target Firefox/Chromium profiles while they are running.
- Do not auto-install extensions or bypass browser install consent.
- Do not upload passwords, cookies, browsing history, URLs, profile paths, or extension lists.
- Do not invent a proprietary passkey export format.
- Do not broaden into full browser forensics UI; provenance and diagnostics are useful, but migration remains the product.
- Do not ship an unsigned elevated ABE helper as a polished user-facing default.
- Do not enable telemetry, crash reporting, or update checks without first-run consent and a declared data dictionary.
- Do not chase obscure source browsers (Maxthon, Coc Coc, etc.) until the supported set has signed releases and conflict UI.

## Open Questions

- What signing certificate and timestamping service will be available for Authenticode-signing `FoxPort.exe`, `foxport_abe.exe`, and release ZIP/checksum files? (SignPath has an open-source program; certum/Sectigo are commercial paths.)
- Should the first distributable target remain GitHub ZIP, or should FoxPort add a Windows installer / MSIX once signing exists? Installer makes auto-update easier; MSIX requires Store presence or sideload trust.
- Where will update appcast and (later) telemetry/crash endpoints be hosted? Who owns the privacy policy?
- For direct-write conflict defaults, should the safe default be "skip duplicates" for every category, or "backup-only plus files-only output" unless the user explicitly chooses merge/overwrite?
- Is enterprise-managed browser migration a target persona (policy detection, group-policy export, admin documentation)? Or should FoxPort stay consumer/power-user focused for now?
- Should the `manifest.json` schema be JSON Schema v2020-12 (codegen-friendly) or stay informal? The former gives `--json` clients a contract; the latter is lighter to evolve.
- macOS distribution: full notarization path (Apple Developer ID, hardened runtime, gatekeeper assessment) or DMG-only with a clear "right-click → Open" instruction?
- Linux distribution: AppImage, Flatpak, or per-distro packages? AppImage is the lowest barrier; Flatpak gets more sandboxing but complicates `nss3` loading.
