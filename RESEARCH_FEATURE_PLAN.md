# Project Research and Feature Plan

Generated: 2026-05-25 (refresh pass on `main` at `0a027a4`, post-v1.3.0).

Status baseline: 36 commits on `main`; `pytest` reports **163 passed in <2s**;
`python -m foxport.cli --help`, `--version`, and `list` all succeed under default
Windows PowerShell encoding. Working tree clean.

This file replaces the 2026-05-24 research plan. That plan was authored against
an uncommitted working tree; v1.3.0 has since shipped most of its P0/P1 and
~half of its P2/P3 list. The Phase A/B/C/D arc of the v1.3 ROADMAP is largely
closed (see [ROADMAP.md](ROADMAP.md) — only Phase C signing-cert provisioning,
Phase D telemetry/crash/update placeholders, and macOS/Linux distribution
remain). This refresh re-audits the shipped state, calls out the bugs the v1.3
batch left behind, and proposes the v1.3.1 → v1.4 arc.

## Executive Summary

FoxPort is a Windows-first cross-platform Python/PyQt6 desktop and CLI tool for
moving browser data between Chromium-family and Firefox-family profiles. v1.3.0
turned it from "complete migration tool" into "trust-instrumented migration
tool": the wizard's Done screen and Items badges now render every artifact the
worker produces, every staging emitter and every direct-write goes through an
atomic-replace helper, `manifest.json` ships next to `README.txt` on every run,
pre-flight conflict counts log before destructive direct-writes, a first-run
trust dialog discloses optional network endpoints, NSS direct-write refuses on
major-version mismatch, GUI snapshot + restore-with-inspect is live, and the
release workflow has Authenticode scaffolding (cert provisioning is the only
outstanding gate).

What stayed behind in the v1.3 ship:

1. **Signed Windows release with cert + icon.** Workflow is wired; the
   `WINDOWS_CERT_BASE64` / `WINDOWS_CERT_PASSWORD` secrets aren't configured,
   `assets/icon.ico` doesn't exist, and `foxport/data/foxport_abe.exe` is
   build-only — no local binary, no signed binary. Distribution is the single
   biggest blocker before non-developer install.
2. **Conflict-review dialog (Phase 2).** Pre-flight analyzers ship counts to the
   run log; the modal review UI with skip/merge/overwrite/backup-only policy
   selection and the matching `--direct-write-policy` CLI flag aren't built.
3. **Three doc/code bugs the audit pass introduced.** Curated map count drift
   (docs say 67, file has 63 — see Reliability section); stale User-Agent in
   `extensions.py` (`FoxPort/1.2.0` literal, ignores `__version__`); open-tabs
   direct-write creates a backup but never emits its path to the Done screen.
4. **Status drift in CLAUDE.md.** Says "v1.2.1 shipped" — actually v1.3.0
   shipped, with 13 follow-on commits.

Highest-value next opportunities (priority order):

1. **Fix the three regressions the v1.3 audit batch introduced** (curated count,
   `extensions.py` User-Agent, open-tabs backup wiring). Quick wins, all P1.
2. **Land the signing cert + icon and ship the first signed Windows release.**
   This is the single biggest user-facing wall.
3. **Phase 2 conflict review:** modal dialog + per-category skip/merge/
   overwrite/backup-only policy + CLI `--direct-write-policy`. The pre-flight
   analyzers already produce the data; the dialog is the missing surface.
4. **Snapshot inspect dialog reads the inner `manifest.json` too**, so the
   restore UX surfaces per-artifact sensitivity/network/direct-write metadata
   instead of just file sha256s. This is one half-day of plumbing on top of the
   existing two-manifest model.
5. **CLI `migrate --json`** for IT/support automation (the `list --json`
   shape is the precedent). Manifest already has the right shape; the CLI
   just needs to emit it.
6. **Refresh the 2026-05-23 screenshots** — they predate the network-activity
   tree, the 4 direct-write checkboxes, the dry-run banner, and the Done-screen
   action bar layout. They're materially misleading.
7. **HIBP "unchecked due to network failure" distinction.** Today the run log
   prints "no passwords found" even when the scan died on a timeout. The data
   is in `result.failures`; the UX just needs to surface it.
8. **Settings clean-up:** the telemetry/crash placeholder checkboxes have been
   disabled-but-visible for three minor releases. Either ship the opt-in
   plumbing (Glean/Sentry) or hide them from the dialog until they're real.
9. **Downloads → `places.sqlite.moz_annos` direct-write** when history
   direct-write is selected. ROADMAP item Phase D P2; the missing piece keeps
   downloads as a CSV-only artifact when the same migration is already
   touching places.sqlite.
10. **Two Phase D test gaps from the ROADMAP**: an all-artifact Done UI render
    test, and an atomic-replace failure recovery test (NSS version monkeypatch
    already shipped — 11 tests in `tests/crypto/test_nss_version.py`).

Larger bets — see "Larger Bets" section: signed appcast + opt-in telemetry
(Glean) + opt-in Sentry, the macOS/Linux distribution path, extension-settings
allowlist for uBO/Stylus/Bitwarden, passkey inventory prototype against FIDO
CXF, and a Chromium "merge" mode for history/cookies (replacing wholesale
replace).

## Evidence Reviewed

Local files and directories inspected this pass:

- Root: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `CLAUDE.md`, `LICENSE`,
  `requirements.txt`, `pyproject.toml`, `foxport.spec`.
- Workflows: `.github/workflows/ci.yml`, `release.yml`, `curated-map-audit.yml`.
- Package: `foxport/__init__.py` (`__version__ = "1.3.0"`), `__main__.py`,
  `app.py`, `cli.py` (16 KB, 7 subcommands + 1 since prior pass), `config.py`,
  `diff.py`, `fileops.py`, `manifest.py` (**new**), `snapshot.py`.
- Browsers: `browsers/detect.py`, `chromium.py`, `firefox.py`, `firefox_read.py`.
- Crypto: `crypto/abe.py`, `dpapi.py`, `hibp.py`, `keychain.py`, `mozhash.py`,
  `nss.py` (now version-guarded).
- GUI: `gui/dialogs.py` (with new `FirstRunDialog` + `RestoreInspectDialog`),
  `main_window.py`, `pages.py` (`RunPage.ARTIFACT_ACTIONS` + `BACKUP_ACTION`
  + `CREATE_SNAPSHOT_KEY`), `theme.py`, `widgets.py`, `workers.py`
  (now emits `directWriteBackups` + writes manifest).
- Migrators: `migrate/*.py` (10 forward + 4 nss_* + new `conflicts.py`),
  `migrate_reverse/*.py`.
- Adapters: `import_/adapters.py` (with new `write_netscape_html`).
- Data: `foxport/data/curated_extension_map.json` (**verified 63 entries** —
  see Reliability bug section).
- Scripts: `capture_screenshots.py`, `check_curated_map.py`,
  `harvest_reverse_map.py`.
- Sidecar: `tools/abe_sidecar/foxport_abe.cpp`, `CMakeLists.txt`,
  `foxport_abe.exe.manifest` (sidecar binary not present locally).
- Tests: 28 test files; `pytest --collect-only` reports **163 tests collected**.

Git history reviewed:

- `git log --since="2026-05-23"` → 36 commits, all 2026-05-23/24. v1.3.0 tag
  at `5763c83`; 13 follow-on commits up through `0a027a4` (pre-flight
  conflict analyzers). Working tree clean.
- Most recent commit cluster (2026-05-24) closes ROADMAP Phase A/B/C/D items
  in dependency order: manifest → atomic emitters → NSS version guard →
  external bookmark adapters → reverse tests → settings polish → audit →
  CLI JSON → snapshot + restore + signing scaffolding → trust dialog →
  Done-screen reveal-backup → conflict analyzers.

Build / test / release artifacts validated this pass:

- `python -m pytest -q` → **163 passed in 1.7s** (up from 97 in the prior plan).
- `python -m foxport.cli --version` → `FoxPort 1.3.0`.
- `python -m foxport.cli --help` → ASCII-safe under cp1252, no Unicode arrow.
- `python -m foxport.cli list` → enumerates this VM's profiles cleanly.
- CI workflow `parse + import + CLI help/list/version + pytest` on
  Windows/macOS/Linux × Python 3.11/3.12.
- Release workflow now: MSVC ABE build → `assets/version_info.txt` generator →
  PyInstaller → optional Authenticode sign → smoke-test (EXE FileVersion +
  curated_extension_map.json presence) → ZIP + `.sha256` → GH release.
- Monthly curated-map audit: now passes `--include-reverse` and the issue body
  reports forward + reverse breakage in separate tables.

External sources re-consulted:

- [Mozilla Firefox source docs, Migrators reference](https://firefox-source-docs.mozilla.org/browser/components/migration/docs/migrators.html)
- Mozilla `logins.json` v3 schema reference (PK11SDR_Encrypt blob layout).
- [Mozilla NSS reference](https://firefox-source-docs.mozilla.org/security/nss/) — `NSS_GetVersion` / `PK11SDR_*`.
- [HIBP API v3](https://haveibeenpwned.com/API/V3) — padding header + k-anonymity.
- [Google Chrome 127+ App-Bound Encryption](https://security.googleblog.com/2024/07/improving-security-of-chrome-cookies-on.html).
- [FIDO CXF v1.0 ready draft](https://fidoalliance.org/specs/cx/cxf-v1.0-rd-20250313.html) (passkey export proposal still relevant for v1.4).
- [Microsoft SignTool](https://learn.microsoft.com/en-us/dotnet/framework/tools/signtool-exe) + [PyInstaller versioning](https://pyinstaller.org/en/stable/usage.html) docs.
- [WinSparkle](https://winsparkle.org/) / NetSparkle for signed update appcasts.
- [Mozilla Glean (Python)](https://mozilla.github.io/glean/python/glean/index.html) + [Sentry Python SDK](https://docs.sentry.io/platforms/python/) for declared-metrics + crash.
- [SignPath](https://signpath.org/) — open-source code-signing path candidate for the Authenticode block.

Not verified this pass:

- ABE sidecar end-to-end (no Chrome 127+ ABE-only profile on this VM; no
  signed binary built locally).
- Authenticode-signed release artifact (no cert configured).
- Live Firefox/Chrome import acceptance for each emitted SQLite/JSONLZ4.
- AMO curated-map live audit (left to the monthly cron).
- macOS Keychain + Linux libsecret/kwallet on real OS (only unit-tested).

## Current Product Map

### Core workflows

- **Forward GUI migration** — Detect → Source tile (with reverse-direction
  toggle) → Target tile (optional) → Items (10 categories + 5 customize
  buttons + 4 direct-write + HIBP + dry-run + output dir) → Preview tree
  (counts + network-activity sub-tree) → Run (live log + progress + Done
  action bar generated per artifact + Save-as-snapshot button).
- **Reverse GUI migration** — direction toggle on the Source page swaps
  source/target families; passwords/bookmarks/extensions supported in
  reverse (CSV/HTML output only — no reverse direct-write).
- **CLI** — 7 subcommands: `list` (`--detail`, `--json`), `migrate`,
  `migrate-reverse`, `diff`, `snapshot`, `restore` (`--overwrite`),
  `import-bookmarks` (`--format`).
- **First-run trust dialog** — Shown once per install (gated by
  `Settings.first_run_acked_iso`). Explains source-read-only, plaintext-
  output cleanup, opt-in AMO + HIBP, no telemetry/crash/update.
- **Snapshot / restore** — `.fxport` ZIP with PBKDF2-SHA256(200k) →
  AES-256-GCM, SHA-256-per-file, atomic-replace on restore, refuse non-empty
  output without `--overwrite`, GUI inspect dialog with file list.
- **Curated extension map** — 63 Chrome → AMO entries across 14 categories
  (NB: docs claim 67; see Reliability bug). Monthly cron auditor for both
  forward and reverse curated maps.

### Existing user-visible features (now ~37 distinct surfaces)

Profile detection × ~20 browsers (Chrome stable/Beta/Canary, Chromium, Brave
stable/Beta/Nightly, Edge stable/Beta/Dev, Vivaldi, Opera, Opera GX, Yandex,
Arc, Thorium, plus Firefox stable/Nightly/ESR, LibreWolf, Waterfox, Floorp,
Mullvad, Tor, Zen). Direction toggle. Manual source drag-drop (including
auto-detect for Pocket/Pinboard/OPML/Netscape bookmark exports). 10
forward categories: passwords, bookmarks, extensions, cookies, history,
autofill, cards, search engines, open tabs, downloads. HIBP opt-in.
Direct-write × 4 categories: passwords, cookies, history, open tabs. Dry-run
with persistent banner on the Run page. Customize dialogs: per-row password
filter + Show/Hide toggle, per-folder bookmark filter, per-range history
filter. Preview tree with counts + network-activity sub-tree. ABE detection +
graceful downgrade with copy. Settings dialog with output dir, mask-by-
default, AMO default, dry-run default, HIBP default, NSS path override,
Reset-to-defaults, disabled telemetry/crash placeholders. File menu: Rescan,
Open output folder, **Restore snapshot…**, Settings, Quit. Help menu: View
change log, Report a problem, About. closeEvent guard mid-migration with 3s
graceful wait. Done-screen artifact buttons (open/reveal per file +
Reveal X backup per direct-write category + Save as snapshot). Run log +
progress bar + dry-run banner. `manifest.json` per non-dry-run run (next
to README.txt) with per-artifact sha256/size/sensitivity/direct-write
status + network usage + warnings. NSS version guard + override env var.
External bookmark adapters (Pocket/Pinboard/OPML/Netscape) reachable via
both CLI and GUI drop.

### User personas

- Windows users migrating from a Chromium browser to Firefox-family.
- Privacy-conscious users who want local-only operation and a clear network
  surface (the first-run dialog + Preview network sub-tree are aimed here).
- Power users with portable Firefox installs (NSS path override in Settings).
- IT/support operators who need repeatable migration output, logs, snapshots,
  and machine-readable manifests for downstream automation.
- Maintainers extending categories or browser support (curated map + monthly
  audit + reverse curated-map auditor).

### Platforms and distribution

- Runtime: Python 3.11+; CI matrix Windows/macOS/Linux × 3.11/3.12.
- Distribution: GitHub Releases → Windows ZIP via `workflow_dispatch`.
  Authenticode scaffolding present; cert provisioning pending.
- macOS/Linux distribution: **not represented** in `release.yml` — runtime
  works cross-platform but the only release artifact is the Windows ZIP.
- Settings: `%APPDATA%/FoxPort/config.json` (Windows),
  `~/Library/Application Support/FoxPort` (macOS),
  `$XDG_CONFIG_HOME/FoxPort` (Linux).

### Network surface

- AMO: `addons.mozilla.org/api/v5/{search,addons/addon}` — extension
  metadata. Opt-in (default ON), can be disabled per-run.
- HIBP: `api.pwnedpasswords.com/range/<5-char>` — k-anonymity pwd scan.
  Opt-in (default OFF), can be disabled per-run, `Add-Padding: true`.
- No telemetry, crash reporting, update checks, or external endpoints in
  v1.3.0. Settings dialog has disabled placeholders for telemetry/crash.

## Feature Inventory

Confidence labels: **Verified** (this pass), **Likely** (consistent with code
but not exercised), **Assumption** (needs live validation).

### Profile Detection
- Value: zero-config discovery of ~20 browsers + flat-layout Opera + locked-
  profile / running-process detection.
- Code: [foxport/browsers/detect.py](foxport/browsers/detect.py)
  (`_CHROMIUM_SPECS_WIN/_MAC/_LINUX`, `is_chromium_running`,
  `is_firefox_profile_locked`).
- Maturity: **Verified** complete; no `tests/test_detect.py`.
- Improvements: custom-profile path entry in Settings; portable-Firefox /
  Thunderbird coverage; regression fixtures for Opera GX flat layout.

### Source/Target wizard + direction toggle
- Code: [foxport/gui/pages.py:160-530](foxport/gui/pages.py#L160-L530).
- Maturity: **Verified** complete. Drop tile auto-detects bookmark exports.
- Improvements: refresh stale 2026-05-23 screenshots (UI has materially
  changed since); GUI smoke test for direction-toggle.

### Items page (10 categories)
- Code: [foxport/gui/pages.py:534-924](foxport/gui/pages.py#L534-L924).
- Maturity: **Verified** complete. `_make_row` + `_rows` registry + dict-
  keyed `set_counts()` correctly handle all 10 categories.
- Improvements: the wizard hides direct-write checkboxes on the no-target
  ("Skip") path implicitly; could surface "files-only mode → direct-write
  unavailable" copy.

### Password export (CSV + NSS direct-write + HIBP)
- Code: [foxport/migrate/passwords.py](foxport/migrate/passwords.py),
  [nss_passwords.py](foxport/migrate/nss_passwords.py),
  [crypto/dpapi.py](foxport/crypto/dpapi.py),
  [crypto/nss.py](foxport/crypto/nss.py),
  [crypto/hibp.py](foxport/crypto/hibp.py).
- Maturity: **Verified** strong. Deterministic GUIDs, accounting invariant,
  refusal on unparseable target `logins.json`, atomic write of both
  `logins.json` + `logins-backup.json`, pre-flight conflict count, NSS
  version guard, manifest sensitivity flag + per-run backup path.
- Tests: `tests/migrate/test_passwords.py`, `test_nss_passwords.py`,
  `tests/migrate/test_conflicts.py`, `tests/crypto/test_nss_version.py`
  (11 tests), `tests/crypto/test_hibp.py`.
- Improvements: surface "Delete passwords.csv after import" reminder in
  the Done screen (only README.txt mentions it today); HIBP "unchecked due
  to network failure" distinction (see Reliability section).

### Bookmarks (HTML + folder filter + external adapters)
- Code: [foxport/migrate/bookmarks.py](foxport/migrate/bookmarks.py),
  [import_/adapters.py](foxport/import_/adapters.py),
  [gui/dialogs.py:560-650](foxport/gui/dialogs.py#L560-L650).
- Maturity: **Verified** complete. Folder filter + per-row filter via
  customize dialogs; reverse direction promotes Firefox toolbar to Chrome
  bookmarks bar; external adapters reachable from GUI drop + CLI
  `import-bookmarks`.
- Tests: `tests/migrate/test_bookmarks.py`, `test_import_adapters.py`,
  `test_import_bookmarks_cli.py`, `test_bookmarks_reverse.py`.
- Improvements: bookmarks count badge could exclude folders (today it's
  total URLs).

### Extension mapping (curated + AMO + permission overlap)
- Code: [foxport/migrate/extensions.py](foxport/migrate/extensions.py),
  `foxport/data/curated_extension_map.json` (63 entries × 14 categories),
  `scripts/check_curated_map.py`, `harvest_reverse_map.py`.
- Maturity: **Verified** strong; **Verified bug** in stale User-Agent
  literal (see Reliability). Monthly audit workflow now covers reverse map.
- Tests: `tests/migrate/test_extensions.py` (12 tests).
- Improvements: fix the curated count documentation drift; fix the
  hardcoded `FoxPort/1.2.0` User-Agent; in-run AMO cache (P3); distinct
  "lookup unavailable (offline)" tag vs. "no match" so the user can
  retry with online enabled.

### Cookies (export + direct-write + pre-flight)
- Code: [migrate/cookies.py](foxport/migrate/cookies.py),
  [migrate/nss_cookies.py](foxport/migrate/nss_cookies.py).
- Maturity: **Verified** complete. WAL/SHM cleared on direct-write,
  pre-flight count logged, manifest carries backup_path.
- Improvements: per-host conflict preview in the future conflict dialog.

### History (export + direct-write + range filter + favicons backup)
- Code: [migrate/history.py](foxport/migrate/history.py),
  [migrate/nss_history.py](foxport/migrate/nss_history.py),
  [crypto/mozhash.py](foxport/crypto/mozhash.py).
- Maturity: **Verified** strong. v86 schema, mozhash ported, favicons.sqlite
  is **moved aside** (not deleted), atomic-replace, pre-flight count.
- Improvements: downloads-direct-write into `moz_annos` when history
  direct-write selected (ROADMAP P2, still open).

### Autofill (formhistory.sqlite v5)
- Code: [migrate/autofill.py](foxport/migrate/autofill.py).
- Maturity: **Verified** complete; direct-write not offered (ROADMAP gap).

### Saved cards (CSV — 1Password/Bitwarden import shape)
- Code: [migrate/cards.py](foxport/migrate/cards.py).
- Maturity: **Verified** complete; column dedup landed in v1.3 (now
  `Type, Cardholder name, Number, Expiration, Notes`).
- Improvements: `manifest.json` flags this as `financial` already; the
  `_DEFAULT_ACTION` keeps it as `"open"` — given the default-CSV-handler
  may be Excel and the file contains plaintext PAN, a `"reveal"` default
  is safer.

### Search engines (OpenSearch XML + JSON inventory)
- Code: [migrate/search_engines.py](foxport/migrate/search_engines.py).
- Maturity: **Verified** complete with 5 dedicated tests.

### Open tabs (SNSS Pickle + UTF-8 fallback + direct-write)
- Code: [migrate/open_tabs.py](foxport/migrate/open_tabs.py).
- Maturity: **Verified** strong. Partial-success warning when the
  structural parser undercounts vs the regex fallback (3 dedicated tests).
- **Verified bug**: `write_session_into_target()` creates a backup file
  but returns only the target path — the worker never picks up the
  backup path, so the Done UI's "Reveal open_tabs backup" button never
  renders even when there was a previous recovery.jsonlz4 to back up.
  See Reliability section.

### Downloads (CSV)
- Code: [migrate/downloads.py](foxport/migrate/downloads.py).
- Maturity: **Verified** at CSV; direct-write into `places.sqlite.moz_annos`
  remains ROADMAP P2.

### Reverse Firefox → Chromium
- Code: [migrate_reverse/*.py](foxport/migrate_reverse/),
  [browsers/firefox_read.py](foxport/browsers/firefox_read.py).
- Maturity: **Verified** narrow by design (passwords/bookmarks/extensions
  only); now goes through atomic writers; bookmarks reverse has 3 tests.
- Improvements: surface pre-flight counts in reverse direction too (today
  conflict analyzers are forward-only).

### Diff CLI
- Code: [foxport/diff.py](foxport/diff.py).
- Maturity: **Verified** complete. 4 dedicated tests cover the set-diff
  math, NSS-failure fail-open, gecko-id-vs-installed-guid.
- Improvements: `--json` output (ROADMAP P2).

### Snapshot + restore (`.fxport`)
- Code: [foxport/snapshot.py](foxport/snapshot.py),
  [gui/dialogs.py:81-220](foxport/gui/dialogs.py#L81-L220).
- Maturity: **Verified** strong. Atomic write, overwrite policy on restore,
  SHA-256 integrity check pre-extract, GUI inspect dialog with passphrase
  prompt + file list.
- **Verified gap**: The `SnapshotManifest` schema is independent from
  `RunManifest`. The inner `manifest.json` lives inside the ZIP transparently
  (it's just another file), but the GUI inspect dialog reads only the outer
  shape (file list + sha256 prefixes). It could read the inner
  `manifest.json` too and surface per-artifact sensitivity, network usage,
  direct-write status, and counts.
- Tests: `tests/test_snapshot.py` (11 tests).

### Settings dialog
- Code: [foxport/config.py](foxport/config.py),
  [gui/dialogs.py:780-967](foxport/gui/dialogs.py#L780-L967).
- Maturity: **Verified** complete. Output dir, mask default, AMO default,
  dry-run default, HIBP default, NSS path override, Reset-to-defaults,
  disabled telemetry/crash placeholders.
- Tests: `tests/test_config.py` (10 tests).
- Improvements: hide the two disabled placeholder checkboxes until the
  telemetry/crash plumbing actually lands. Three minor releases of "off
  until then" is enough.

### Release / packaging
- Code: [.github/workflows/release.yml](.github/workflows/release.yml),
  [foxport.spec](foxport.spec), [tools/abe_sidecar/](tools/abe_sidecar/).
- Maturity: **Verified partial**. ABE compile + PyInstaller + version_info
  generator + optional SignTool + smoke test + ZIP + .sha256 + GH release
  all in workflow. **Outstanding**: `WINDOWS_CERT_BASE64` secret not set,
  `assets/icon.ico` doesn't exist, `foxport/data/foxport_abe.exe` not built
  locally. Signed Windows release is one cert provisioning + one icon away.

## Competitive and Ecosystem Research

### Firefox built-in import wizard
- Behavior: pulls bookmarks/history/passwords/extensions/autofill from a
  small set of browsers; Mozilla now mostly points users at CSV for Chrome.
- Learn: closed-profile + checklist + reassurance copy. FoxPort matches
  this with the first-run dialog + Preview network sub-tree.
- Avoid: promising silent-import where platform restrictions force CSV.

### Google Chrome / Takeout
- Account-side archive of bookmarks/history/autofill/extensions/...
- Learn: per-class manifests + dates. FoxPort's `manifest.json` matches.
- Avoid: conflating account exports with local secrets — FoxPort's value
  is the local stuff Takeout can't reach.

### HackBrowserData
- Cross-browser local extraction with CSV/JSON/ZIP + `list -kind`.
- Learn: machine-readable output (FoxPort `list --json` exists; should
  cover `migrate`, `diff`, `migrate-reverse`, `snapshot`, `restore` too).
- Avoid: stealth-extraction framing; FoxPort is consent-driven migration.

### Hindsight
- Forensic browser-artifact parser with strong provenance.
- Learn: artifact provenance + schema version per parse + structured
  failure context. FoxPort's manifest schema_version + per-artifact
  metadata matches.
- Avoid: timeline UI; migration stays the product.

### Mozilla AMO API
- Public detail + search endpoints, GUID/slug, ratings, permissions, status.
- Learn: current use is appropriate; cache per-run.
- Avoid: auto-install; keep browser-mediated install consent.

### Have I Been Pwned Pwned Passwords
- Free k-anonymity API + `Add-Padding`.
- Learn: current usage is aligned; distinguish "not checked" from "no hits";
  offline corpus is an option for high-privacy users.

### App-Bound Encryption (Chrome 127+, Brave 1.86+)
- Service-mediated key wrap on Windows for cookies/passwords.
- Learn: sidecar must be signed and trust-messaged. FoxPort already
  surfaces ABE detection and degrades to bookmarks/extensions; signed
  sidecar is the gate.
- Avoid: shipping unsigned elevated helper as a default.

### FIDO CXF / CXP
- Emerging credential-exchange standard + protocol. Currently the only
  credible path for passkey migration.
- Learn: passkey work should start as inventory + standards alignment;
  export only when destination supports it.

### Glean / Sentry / WinSparkle / SignPath
- Patterns for declared metrics, error reporting, signed app-cast updates,
  open-source code signing.
- Learn: consent + data dictionary + local off-switch + signature
  verification are table stakes; SignPath provides an open-source signing
  path that might fit FoxPort.

## Highest-Value New Features

These supersede items the prior plan flagged; the v1.3 batch overtook half
of them. The ones below are either net-new or substantially deepened by
the new evidence.

### 1. Signed Windows release + bundled signed ABE sidecar + app icon
- User problem solved: Distribution is the wall between FoxPort and
  non-developers. Today no signed binary exists; `foxport_abe.exe` ships
  only if it happened to be built locally.
- Evidence: [foxport.spec:25](foxport.spec#L25) conditional bundling;
  [release.yml:107-133](.github/workflows/release.yml#L107-L133) signing
  step gated by `WINDOWS_CERT_BASE64`; no `assets/icon.ico` present;
  `foxport/data/foxport_abe.exe` missing locally.
- Proposed behavior: provision a signing cert (SignPath OSS program or
  Sectigo/Certum commercial), set the workflow secrets, drop a real
  `assets/icon.ico` (raster set + favicon), execute one prerelease
  workflow_dispatch, attach the signed `FoxPort-vX.Y.Z-windows-x64.zip`
  + `.sha256` to a GH release. ABE sidecar gets signed in the same step.
- Implementation areas: `assets/icon.ico` (new), GH org secrets
  (`WINDOWS_CERT_BASE64`, `WINDOWS_CERT_PASSWORD`), release workflow
  exercise on a `v1.3.1` tag.
- Risks: AV false positives on a new signed binary; sidecar elevation
  trust copy must precede UAC. Both are mitigated by surfacing the
  first-run trust dialog and the Preview network sub-tree.
- Verification: `Get-AuthenticodeSignature dist/FoxPort/FoxPort.exe`,
  manual UAC prompt on Chrome 127+ ABE-only profile, SHA-256 sidecar
  validates against download.
- Complexity: M (the workflow is wired; this is provisioning + smoke).
- Priority: **P0**.

### 2. Conflict review dialog + per-category direct-write policy
- User problem solved: Today the user sees pre-flight counts in the run
  log ("12 of 50 already in target, 38 new") but can't change policy.
  Cookies/history direct-write replaces the target wholesale even when
  the user might prefer "back up only and let me decide".
- Evidence: [foxport/migrate/conflicts.py](foxport/migrate/conflicts.py)
  ships analyzers but only logs; ROADMAP Phase 2 is explicitly open.
- Proposed behavior: between Preview and Run, a "Direct-write review"
  modal appears (only when direct-write is enabled for any category).
  Shows per-category counts + samples + a drop-down: skip / merge /
  overwrite / backup-only. CLI gets `--direct-write-policy=...` and
  `--yes` for non-interactive runs. Policy persists in `MigrationContext`
  + `MigrationRequest`, flows into nss_*; manifest records the chosen
  policy per category.
- Implementation: new `foxport/gui/dialogs.py:DirectWritePolicyDialog`,
  worker policy-aware loops in `nss_passwords`/`nss_cookies`/`nss_history`,
  CLI flag + test, manifest schema bump (additive — schema_version stays
  1 if only optional fields land).
- Risks: cookies/history "merge" semantics are non-trivial (cookie
  uniqueness is `host_key + path + name`; history merge needs URL +
  visit-time dedup). Ship skip/overwrite/backup-only first; defer
  merge as a P2 follow-up.
- Verification: synthetic target fixtures with conflicts; manual
  flow exercising every policy; locked-profile abort still works.
- Complexity: L.
- Priority: **P1**.

### 3. Snapshot inspect dialog surfaces inner RunManifest
- User problem solved: The GUI Restore inspect dialog shows file list +
  sha256 prefixes, but the per-run `manifest.json` inside the ZIP carries
  much richer metadata (per-artifact sensitivity, network usage,
  direct-write status with absolute backup paths, counts, warnings) that
  the user can't see before they commit to restoring.
- Evidence: [gui/dialogs.py:113-162](foxport/gui/dialogs.py#L113-L162)
  reads only the outer SnapshotManifest; the inner `manifest.json` is in
  the ZIP but ignored.
- Proposed behavior: When the bundle includes `manifest.json` at the
  archive root (snapshots created from v1.3+ runs do), load it via
  `foxport.manifest.load_manifest`, render a "Run details" section above
  the file list with: created_iso, source/target, direction, items
  requested, network usage, warnings, per-artifact sensitivity badges.
  Old bundles without a RunManifest fall back to today's behavior.
- Implementation: read the inner JSON in `RestoreInspectDialog.__init__`,
  add a render section, no schema change.
- Risks: a tampered inner manifest must not crash the dialog — use
  `load_manifest` which already filters unknown keys.
- Verification: round-trip test (create → restore → inspect shows the
  inner manifest data).
- Complexity: S.
- Priority: **P1**.

### 4. CLI `--json` on migrate / migrate-reverse / diff / snapshot / restore
- User problem solved: `list --json` is the precedent for IT/support
  automation. The other commands still print human text only, so callers
  have to scrape stdout (fragile) or read the manifest from disk (works
  but two-step).
- Evidence: [foxport/cli.py:142-194](foxport/cli.py#L142-L194) is the only
  `--json` path today.
- Proposed behavior: every action subcommand accepts `--json` and emits
  the same `manifest.json` shape (for migrate/migrate-reverse) or a
  command-specific schema_versioned payload (for diff/snapshot/restore).
  No secrets in the output; absolute paths only when explicitly opted in
  with `--json-include-paths`.
- Implementation: factor a `_emit_json(payload)` helper, update each
  subcommand. Snapshot test the shapes with `pytest`.
- Risks: schema bumps must be additive.
- Verification: schema snapshot tests; manual PowerShell + Bash
  consumer scripts.
- Complexity: M.
- Priority: **P1**.

### 5. HIBP "unchecked due to network failure" distinction
- User problem solved: Today when the user enables HIBP and the network
  call fails, the run log emits "HIBP: no passwords found in known
  breaches." even though the scan never ran. The failures list contains
  the network error but the headline message is misleading.
- Evidence: [workers.py:214-223](foxport/gui/workers.py#L214-L223) +
  [migrate/passwords.py:222-235](foxport/migrate/passwords.py#L222-L235) —
  network failure appends to `failures` and leaves `hibp_hits = 0`; the
  worker treats `hibp_hits == 0` as success.
- Proposed behavior: track a tri-state in `PasswordResult`:
  `hibp_status ∈ {"disabled", "checked-clean", "checked-hits",
  "network-error"}`. Worker emits a "scan failed: <reason> — passwords
  were NOT checked against HIBP" line for `network-error`. Manifest
  records the same tri-state under `network` so a consumer can tell
  "user opted in but the check didn't happen".
- Implementation: small dataclass change + 3 call sites + 1 test +
  copy update.
- Risks: none.
- Verification: monkeypatch HIBP client to raise; assert log + manifest
  reflect the failure correctly.
- Complexity: S.
- Priority: **P1**.

### 6. First-run dialog re-prompt on trust-model change
- User problem solved: A future version that adds telemetry/crash/update
  needs to re-prompt. Today the dialog is gated by a single
  `first_run_acked_iso` timestamp without any way to invalidate it.
- Evidence: [foxport/config.py:46](foxport/config.py#L46),
  [gui/main_window.py:69-72](foxport/gui/main_window.py#L69-L72).
- Proposed behavior: bump `Settings` to `first_run_acked_for_trust_revision: int = 0`
  and `_TRUST_REVISION` constant in `config.py`. Re-prompt when stored
  revision < current. The dialog updates the stored revision on accept.
- Implementation: small Settings change + dialog plumbing + test.
- Risks: existing acks must not re-prompt (set the constant to 0 in
  v1.3.x, bump to 1 when telemetry first appears).
- Complexity: S.
- Priority: **P2** (build now; revision bump comes with the first
  network feature that warrants it).

### 7. Downloads → moz_annos direct-write
- User problem solved: When the user enables history direct-write, the
  downloads category emits a CSV that the user can't easily import
  separately. Firefox stores download metadata as annotated moz_places
  rows — directly writable.
- Evidence: [migrate/downloads.py:1-14](foxport/migrate/downloads.py#L1-L14)
  comments "v1.3 candidate that depends on the history migrator already
  running"; ROADMAP Phase D P2 still open.
- Proposed behavior: when `do_history`, `direct_write_history`, and
  `do_downloads` are all on, the worker inserts each download as a
  `moz_annos` row keyed by the source URL's place_id.
- Implementation: new `write_downloads_into_target` helper next to
  `write_history_into_target`; manifest records `direct_write: true`.
- Risks: downloads can be enabled without history; in that case the
  CSV path stays. Document the "downloads direct-write requires history"
  constraint in the Items tooltip.
- Verification: synthetic fixture history + downloads; restore-and-check
  the annotations land.
- Complexity: M.
- Priority: **P2**.

### 8. Extension settings allowlist (uBO filter lists, Stylus userstyles,
     Bitwarden vault URL)
- User problem solved: Today a "matched" extension only resolves the
  install link. Power users with curated uBO filter lists / Stylus
  userstyles / Bitwarden self-hosted vault lose all their configuration.
- Evidence: ROADMAP D-P3 + the per-extension WebExtension storage layouts
  are stable for these three.
- Proposed behavior: opt-in per-extension dataset transformer for the
  three highest-value extensions. Each transformer reads the Chromium
  side (`Local Extension Settings/<id>/`), normalizes, and emits a
  Firefox-side import the user can drop into the target profile manually
  (or direct-write into the target profile's `storage-sync-v2.sqlite`
  for the rare cases that's safe).
- Implementation: new `foxport/migrate/extension_settings/`, per-
  extension module + tests + manifest sensitivity flag (`sensitive` for
  Bitwarden, `normal` for uBO/Stylus).
- Risks: per-extension format drift; ship narrowly + with clear
  "best-effort" copy.
- Complexity: L.
- Priority: **P2**.

### 9. Passkey inventory prototype (FIDO CXF aligned)
- User problem solved: Passkeys are increasingly the credential of
  record; FoxPort migrates passwords but is silent on passkeys.
- Evidence: ROADMAP D-P3 + FIDO CXF v1.0 ready draft.
- Proposed behavior: a `passkeys inventory` CLI subcommand that detects
  Chromium's `Web Data.webauthn_credentials` (presence + counts) and
  emits a feasibility report. **No export** until CXF/CXP destination
  support lands — this is research surface only.
- Implementation: new `foxport/migrate/passkeys.py` (read-only inventory),
  CLI flag, docs + tests with synthetic fixtures.
- Risks: passkey private key material may not be exportable at all
  (hardware-bound); inventory is the right surface to start.
- Complexity: M.
- Priority: **P3**.

### 10. macOS DMG / Linux AppImage distribution
- User problem solved: Mac/Linux users have no install path other than
  cloning the repo.
- Evidence: `release.yml` is Windows-only; runtime + CI cover three OSes.
- Proposed behavior: per-OS PyInstaller in `release.yml`; macOS path
  needs Apple Developer ID + notarization (or DMG with "right-click →
  Open"); Linux ships an AppImage.
- Implementation: parallel jobs in `release.yml`, signed/notarized macOS
  path, AppImage tooling, per-OS smoke tests.
- Risks: macOS notarization is a non-trivial Apple program; AppImage
  needs to bundle NSS or document `FOXPORT_NSS_PATH`.
- Complexity: XL.
- Priority: **P3**.

## Existing Feature Improvements

### Done-screen action defaults: `cards` should reveal not open
- Current: [foxport/manifest.py:67](foxport/manifest.py#L67) +
  [gui/pages.py:1190](foxport/gui/pages.py#L1190) both set
  `cards → "open"`. The CSV contains plaintext PAN; default-launching
  it (Excel, default CSV handler) is risky.
- Recommended: change `_DEFAULT_ACTION["cards"]` and the matching
  `ARTIFACT_ACTIONS` row to `"reveal"`. The user can still open with the
  Open-output-folder + the file action.
- Complexity: XS. Priority: **P2**.

### Hide telemetry/crash placeholder checkboxes until they ship
- Current: [gui/dialogs.py:852-865](foxport/gui/dialogs.py#L852-L865)
  shows them as disabled — third minor release with this state.
- Recommended: comment out (or feature-flag with a `_FUTURE_TELEMETRY`
  constant) until the Glean/Sentry plumbing lands. The first-run dialog
  already says "no telemetry / crash / update".
- Complexity: XS. Priority: **P2**.

### Manifest absolute-path privacy in support uploads
- Current: [foxport/manifest.py:139-148](foxport/manifest.py#L139-L148)
  records `backup_path` as an absolute filesystem string. If the user
  uploads the manifest for support, this exposes the local username.
- Recommended: keep absolute paths for the user's own use but offer a
  `--privacy-redact` CLI flag (or Help-menu "Copy diagnostics" that
  redacts user paths). Document in the manifest schema.
- Complexity: S. Priority: **P3**.

### `CHANGELOG.md` candidate fallback path bug
- Current: [gui/main_window.py:598](foxport/gui/main_window.py#L598) uses
  `Path("") / "CHANGELOG.md"` = `Path("CHANGELOG.md")` when `_MEIPASS` is
  unset, which `.is_file()` resolves against the cwd. If the user happens
  to launch from a directory containing a CHANGELOG.md, they get that one.
- Recommended: guard the `_MEIPASS` fallback with `if hasattr(sys, "_MEIPASS")`
  and only emit a real path inside the conditional.
- Complexity: XS. Priority: **P3**.

### Status block in `CLAUDE.md` says "v1.2.1 shipped"
- Current: [CLAUDE.md:99-126](CLAUDE.md#L99-L126) status block is pre-v1.3.
- Recommended: rewrite to reflect v1.3.0 + the 13 follow-on commits.
  Include the manifest.json, first-run dialog, NSS version guard, GUI
  snapshot, conflict pre-flight as the headline list.
- Complexity: S. Priority: **P2**.

### Screenshots predate v1.3 UI
- Current: `assets/screenshots/{1..5}-*.png` are all dated 2026-05-23,
  before the downloads row, the 4 direct-write checkboxes, the dry-run
  banner, the network-activity preview sub-tree, and the per-artifact
  Done action bar.
- Recommended: re-run `scripts/capture_screenshots.py` on a real Brave
  → Firefox flow.
- Complexity: S. Priority: **P2**.

### Pre-flight conflict analysis for open_tabs
- Current: [foxport/migrate/conflicts.py](foxport/migrate/conflicts.py)
  exposes analyzers for passwords/cookies/history. Open-tabs direct-write
  also replaces the target's `recovery.jsonlz4` but has no pre-flight.
- Recommended: add `analyze_open_tabs()` that counts URLs in the target's
  existing `sessionstore-backups/recovery.jsonlz4` (decode the
  mozLz40-wrapped JSON) and surfaces a "target had N tabs in its last
  session; will be replaced with M source tabs" line.
- Complexity: M. Priority: **P2**.

### Document the curated map's "63 entries" reality
- Current: docs say 67 (see Reliability bug). The auditor reports per-slug
  counts but no top-level total. The CHANGELOG line "curated-map count
  corrected to 67 entries (was 63 pre-audit)" introduced the drift.
- Recommended: either grow the map to 67 (genuine additions), or revert
  the doc count to 63. Add a `_meta.entry_count` field updated by
  `check_curated_map.py` so it can't drift again.
- Complexity: S. Priority: **P1** (it's a documentation honesty issue).

## Reliability, Security, Privacy, and Data Safety

Bugs / risks found this pass:

- **Verified — curated map docs lie**: docs (README, CLAUDE.md, CHANGELOG,
  prior RESEARCH_FEATURE_PLAN.md) all claim 67 entries; the file actually
  has **63 entries across 14 categories**. The "doc-refresh" batch in
  v1.3.0 corrected 63 → 67 based on a wrong count in the prior research
  plan. Either grow the map to 67 (real additions) or revert the docs.
- **Verified — stale User-Agent**: [foxport/migrate/extensions.py:44](foxport/migrate/extensions.py#L44)
  hardcodes `_USER_AGENT = "FoxPort/1.2.0 (...)"`. HIBP already uses
  `__version__` (see [crypto/hibp.py:32](foxport/crypto/hibp.py#L32)).
  Mirror the same pattern for extensions.
- **Verified — open-tabs backup path lost**:
  [migrate/open_tabs.py:315-321](foxport/migrate/open_tabs.py#L315-L321)
  creates a `recovery.foxport-backup-<mtime>.jsonlz4` next to the target
  but returns only the target path. [workers.py:443-449](foxport/gui/workers.py#L443-L449)
  never populates `direct_write_backups["open_tabs"]`. So the "Reveal
  open_tabs backup" Done button never appears even when there was a
  previous file to back up. Fix: change `write_session_into_target` to
  return `(target_path, backup_path)` (or a small dataclass) and have the
  worker stash the backup the same way it does for cookies/history.
- **Verified — `_DEFAULT_ACTION["cards"] = "open"`**: opens a plaintext
  PAN CSV with the OS default handler. `"reveal"` is the safer default.
- **Verified — HIBP "no hits" copy on network failure**: see Feature #5.
- **Verified — manifest absolute paths**: `backup_path` records `C:\Users\
  <username>\AppData\...` strings that leak the local username if the
  user uploads the manifest for support.
- **Verified — release artifacts unsigned**: `WINDOWS_CERT_BASE64` secret
  not configured; `assets/icon.ico` doesn't exist. The Authenticode
  scaffolding is wired but inert.
- **Verified — `foxport_abe.exe` absent locally**: built only in CI, and
  not built+attached to a release until the signing flow runs.
- **Likely — large-bundle GUI snapshot blocks the UI thread**: the create
  digests every file synchronously before zipping. For a Documents/FoxPort
  folder with multiple historic runs this can hang the main window. Move
  to a background worker.

Missing guardrails:

- Conflict review dialog (P1 — analyzers exist, dialog doesn't).
- macOS Keychain test coverage (no `tests/crypto/test_keychain.py`).
- Atomic-replace failure recovery test (ROADMAP D P2 still open).
- All-artifact Done UI render test (ROADMAP D P2 still open).
- Privacy redaction helper for support manifests.
- "Direct-write requires closed Firefox" copy is in Items tooltip but
  not in the Run page log when the worker detects the lock — could
  promote a clearer error.

Permission / network / file-system concerns:

- ABE sidecar elevation: still requires unsigned binary (until release
  cert lands). The trust dialog warns; the sidecar should refuse to run
  if the signature is invalid (verify with `Get-AuthenticodeSignature`
  inside `crypto/abe.py`).
- AMO + HIBP: both opt-in, both disclosed in the Preview tree. Good.
- Snapshot encryption: PBKDF2-SHA256(200k) → AES-256-GCM with random
  salt + nonce. Reasonable for v1.3; consider Argon2id for v1.4 if the
  passphrase corpus is unknown.

Recovery / rollback needs:

- Manifest backups dictionary captures absolute paths for passwords/
  cookies/history; **needs to also capture open_tabs** (see bug above).
- The Done-screen "Reveal X backup" buttons cover the three current
  direct-write categories that succeed in surfacing the path; open_tabs
  is the missing fourth.
- No "Restore backup" wizard yet — the user has to manually copy the
  `*.foxport-backup-<mtime>.*` file back. A small wizard would close
  the loop on direct-write regret.

Logging / diagnostics needs:

- Run log already structured (per-category counts, failures, network
  status). Manifest persists it. Good.
- "Copy diagnostics" Help-menu action would let users paste a
  redacted summary into a GH issue. The manifest + redactor is the
  source of truth.
- Failed-network reason categories for AMO/HIBP (timeout, 5xx, dns,
  schema mismatch). Currently only "scan: <exc>" gets logged.

## UX, Accessibility, and Trust

Onboarding gaps:

- First-run dialog is in place; covers the four trust claims and lets
  the user pre-set AMO + HIBP defaults. Good baseline.
- Detection happens after the main window paints (the trust dialog
  runs on a 0-ms timer). On a system with many browsers, the user can
  read the dialog while detection finishes — good interleaving.
- "No Firefox target detected" empty state is plain copy; could link
  to firefox.com + portable-Firefox tutorials. Minor.

Empty / loading / error / disabled states:

- Source/Target tile empty states are handled (`No Chromium browsers
  detected — drop a folder`).
- Preview counts are synchronous; a large History DB will block briefly
  on the temp-copy + COUNT. Background worker is worth doing for v1.4.
- Direct-write checkboxes correctly disable on reverse and when their
  category is unchecked. A11y labels stay accurate (tested).

Destructive / irreversible actions:

- Cookies/history/open-tabs direct-write replaces target files. Backups
  exist; pre-flight counts log; "Reveal backup" actions on Done UI
  (except open_tabs — see bug). The conflict review dialog (Feature #2)
  closes the remaining gap.
- Plaintext exports persist after import; the first-run dialog says
  "delete them"; the Done screen doesn't currently surface a
  "Delete plaintext outputs" affordance. Minor.

Settings clarity:

- Disabled telemetry/crash checkboxes have been advisory for three minor
  releases. Either ship the feature or hide them (Improvement above).
- NSS path override surfaced + file picker. Good.
- Reset-to-defaults button works and persists. Good.

Accessibility:

- v1.2.1 added `:focus` styling and keyboard activation for tiles.
- A `tests/test_accessibility.py` smoke pass would assert
  `accessibleName/Description` on key widgets — not present today.
- Extension HTML reports should pass basic semantic checks (heading
  levels, link text) — not verified.

Microcopy / trust signals:

- First-run dialog covers all the right claims.
- Preview "Network activity" tree explicitly lists each endpoint and
  whether this run will hit it. Excellent surface.
- Direct-write checkboxes could be relabeled "Install into closed
  Firefox profile" (technical subtitle ok) for non-technical users.
  The tooltip already explains it.
- "Sensitive files in this run" callout on Done screen would help
  remind users about cleanup (manifest already tracks sensitivity).

## Architecture and Maintainability

Module or boundary improvements:

- Two distinct manifest schemas (`SnapshotManifest` for the bundle,
  `RunManifest` for the per-run output). The snapshot ZIP transparently
  preserves the inner `manifest.json`, but the GUI inspect dialog
  doesn't read it. See Feature #3.
- `MigrationRequest` and `MigrationContext` carry the same flag set
  in parallel; the dataclass-with-converter consolidation flagged in the
  prior plan still applies. Not urgent; both are private.
- `migrate/conflicts.py` analyzes 3 of the 4 direct-write categories;
  add `analyze_open_tabs` for parity (Improvement above).
- The `_backup_path_for` helper is duplicated in nss_cookies +
  nss_history. Lift to `fileops.py` (the prior plan flagged this; still
  open).

Refactor candidates:

- `RunPage.ARTIFACT_ACTIONS` is the data-driven Done-screen surface;
  good shape. Action defaults could be sourced from `manifest._DEFAULT_ACTION`
  so there's one truth (today they happen to match).
- `ItemsPage._make_row` × 10 calls could be a loop over an
  `ITEM_DEFINITIONS` table. The prior plan flagged this; still optional.
- `firefox.py:import_instructions` is now ~140 lines of if-chains.
  Could be manifest-driven (consume `RunManifest.artifacts` and emit
  per-key blocks) — would close the "instructions vs manifest are two
  sources of truth" loop the prior plan called out.

Test gaps (from ROADMAP Phase D + this pass):

- All-artifact Done UI render test (mock `set_done` with all 11 keys).
- Atomic-replace failure recovery test (force write-error mid-replace;
  assert target unchanged + no orphan tmp files).
- Open-tabs partial-success warning ALREADY HAS coverage in
  `tests/migrate/test_open_tabs_partial_success.py` (3 tests).
- NSS version monkeypatch ALREADY HAS coverage in
  `tests/crypto/test_nss_version.py` (11 tests).
- Profile detection has no test file.
- macOS keychain has no test file.
- Manifest "no secrets in serialized form" guard — `tests/test_manifest.py`
  has 8 tests; verify it includes a "no plaintext password / cookie /
  card value appears anywhere in the JSON" assertion.

Documentation gaps:

- README install snippet says "Requires Python 3.11+ on Windows" while
  the badges and CI matrix support cross-platform. Soften to "Windows-
  first; macOS/Linux supported via the same install steps".
- CLAUDE.md status block predates v1.3 (above).
- Documentation for the conflict-review surface needs to be written
  alongside Feature #2.
- `docs/troubleshooting.md` doesn't yet cover the "open-tabs backup
  button is missing" scenario (because the bug exists; once fixed, this
  is moot).

Release / build / deployment gaps:

- Authenticode cert provisioning (P0).
- Real `assets/icon.ico` (raster) and favicon set.
- macOS/Linux release artifacts (P3).
- SBOM / supply-chain attestation (P3) — cosign + GitHub OIDC could
  attest the release artifact provenance.
- No published release artifact verified this pass (no signed build
  to inspect).

## Prioritized Roadmap

Phase A — v1.3.1 patch (this week)

- [ ] **P1** Fix curated-map documentation drift (63 vs 67)
  - Why: README/CLAUDE.md/CHANGELOG/RESEARCH_FEATURE_PLAN.md all say 67;
    the file has 63. Either grow the map or revert the docs.
  - Evidence: live `len(load_curated_map())` returns 63;
    [README.md:272](README.md#L272) + [CLAUDE.md:35](CLAUDE.md#L35) +
    CHANGELOG.md:265 + this plan above.
  - Touches: README.md, CLAUDE.md, CHANGELOG.md, ROADMAP.md history
    entries, curated_extension_map.json (`_meta.entry_count` field
    optional), `scripts/check_curated_map.py` (emit total).
  - Acceptance: docs match `load_curated_map()` length; auditor reports
    the total.
  - Verify: `python -c "from foxport.migrate.extensions import load_curated_map; print(len(load_curated_map()))"`
    matches every doc claim.

- [ ] **P1** Fix `extensions.py` hardcoded User-Agent (1.2.0 → __version__)
  - Why: every AMO call sends a stale UA; trivial fix; matches HIBP pattern.
  - Evidence: [extensions.py:44](foxport/migrate/extensions.py#L44) vs
    [hibp.py:32](foxport/crypto/hibp.py#L32).
  - Touches: `foxport/migrate/extensions.py` (one line); regression test
    in `tests/migrate/test_extensions.py` asserting `__version__` in UA.
  - Acceptance: AMO requests carry `FoxPort/1.3.x` UA.
  - Verify: monkeypatch `requests.Session.get`; assert UA header.

- [ ] **P1** Fix open-tabs direct-write backup path emission
  - Why: backup is created but the worker never receives the path, so
    the Done UI's "Reveal open_tabs backup" button never appears even
    when there's a backup to reveal.
  - Evidence: [open_tabs.py:297-322](foxport/migrate/open_tabs.py#L297-L322)
    returns Path; [workers.py:443-449](foxport/gui/workers.py#L443-L449)
    never populates `direct_write_backups["open_tabs"]`.
  - Touches: `foxport/migrate/open_tabs.py` (return a small dataclass
    with `target_path` + `backup_path`), `foxport/gui/workers.py`
    (stash backup), `tests/migrate/test_open_tabs.py` (assert backup
    path returned when target existed).
  - Acceptance: a target with a pre-existing recovery.jsonlz4 surfaces
    a "Reveal open_tabs backup" Done button after the run.
  - Verify: synthetic target fixture + `set_done` smoke test.

- [ ] **P2** Update CLAUDE.md status block to v1.3.0 + 13 follow-ons
  - Why: status reads "v1.2.1 shipped"; reality is v1.3.0 + the entire
    Phase A/B/C/D arc.
  - Touches: `CLAUDE.md` (status section + key paths line for
    curated count).
  - Acceptance: `grep "1.2.1" CLAUDE.md` returns no live entries.

Phase B — Distribution (v1.3.2 → v1.3.3)

- [ ] **P0** Provision signing cert + drop assets/icon.ico
  - Why: only blocker to a non-developer install path.
  - Evidence: release.yml lines 107-133 + foxport.spec lines 17-18;
    cert secrets unset; `assets/icon.ico` absent.
  - Touches: org-level GH secrets (`WINDOWS_CERT_BASE64`,
    `WINDOWS_CERT_PASSWORD`), `assets/icon.ico` (new — needs image-gen
    or a designer pass), prerelease tag `v1.3.2-rc1`.
  - Acceptance: `Get-AuthenticodeSignature dist/FoxPort/FoxPort.exe`
    returns Valid; FoxPort.exe + foxport_abe.exe both signed; release
    notes draft from CHANGELOG section.
  - Verify: workflow_dispatch on `v1.3.2-rc1`; verify both EXEs;
    download the ZIP; check sha256.

Phase C — Trust + completeness arc continues (v1.4 prep)

- [ ] **P1** Conflict review dialog + per-category direct-write policy
  - Why: pre-flight counts already exist; the missing UX is the modal.
  - Evidence: ROADMAP Phase C P1 explicitly open at "Phase 2".
  - Touches: new `DirectWritePolicyDialog`, worker policy-aware loops,
    CLI `--direct-write-policy` flag, manifest schema (additive),
    `tests/migrate/test_conflicts.py` (new policy tests).
  - Acceptance: every direct-write run surfaces the modal; user can
    pick skip/merge/overwrite/backup-only per category; manifest
    records the choice.
  - Verify: synthetic conflict fixtures × every policy + CLI flag.

- [ ] **P1** Snapshot inspect reads inner RunManifest
  - Why: bundle's inner manifest carries 10x richer metadata than the
    outer SnapshotManifest the dialog reads today.
  - Touches: `gui/dialogs.py:RestoreInspectDialog.__init__` to also
    `load_manifest(manifest.json)` and render a "Run details" section.
  - Acceptance: round-trip test (create snapshot from a v1.3+ run,
    restore-inspect, see source/target/items/network/sensitivity).

- [ ] **P1** CLI `--json` on migrate / migrate-reverse / diff /
       snapshot / restore
  - Why: `list --json` is the precedent; downstream automation needs
    the same shape elsewhere.
  - Touches: `foxport/cli.py` per-subcommand + 4 schema snapshot tests.
  - Acceptance: every command supports `--json`; secrets never appear.

- [ ] **P1** HIBP "unchecked" tri-state
  - Why: misleading "no hits" copy on network failure.
  - Touches: `PasswordResult.hibp_status`, worker log, manifest network
    block, test.

- [ ] **P2** All-artifact Done UI render test
- [ ] **P2** Atomic-replace failure recovery test
- [ ] **P2** Pre-flight conflict analysis for open_tabs
- [ ] **P2** `_backup_path_for()` lifted into `foxport/fileops.py`
- [ ] **P2** Re-run screenshots after the polish lands
- [ ] **P2** Hide telemetry/crash placeholder checkboxes
- [ ] **P2** `_DEFAULT_ACTION["cards"] = "reveal"`
- [ ] **P2** Downloads direct-write into moz_annos when history
       direct-write selected (ROADMAP D P2)

Phase D — Larger bets (v1.4+)

- [ ] **P2** Extension settings allowlist (uBO / Stylus / Bitwarden)
- [ ] **P3** Opt-in Glean telemetry with declared metrics
- [ ] **P3** Opt-in Sentry crash reporting (path-stripped)
- [ ] **P3** Signed update appcast (WinSparkle / NetSparkle)
- [ ] **P3** Passkey inventory CXF prototype
- [ ] **P3** macOS DMG + Linux AppImage distribution
- [ ] **P3** Manifest privacy redactor (Help → Copy diagnostics)
- [ ] **P3** Curated map hot-reload + in-run AMO cache
- [ ] **P3** Profile detection test fixtures (incl. Opera GX flat,
       Thunderbird, portable installs)
- [ ] **P3** macOS Keychain + Linux libsecret/kwallet test coverage
- [ ] **P3** "Merge mode" for cookies/history direct-write (preserve
       target rows + add source rows by uniqueness key) — partial of
       Feature #2's merge policy
- [ ] **P3** Restore-from-backup wizard step (regret-undo UI)
- [ ] **P3** Background-worker preview counts for large profiles

## Quick Wins

- Curated-map count fix (P1, doc bug).
- `extensions.py` User-Agent fix (P1, one-line).
- Open-tabs direct-write backup path emission (P1, ~15 lines).
- CLAUDE.md status block refresh (P2, doc).
- `_DEFAULT_ACTION["cards"]` → `"reveal"` (P2, two lines).
- Hide disabled telemetry/crash checkboxes (P2, few lines).
- README install snippet softening for cross-platform (P2, doc).
- Background-thread snapshot create to avoid GUI block (P3, M).
- Restore inspect dialog reads inner `manifest.json` (P1, ~30 lines).
- Lift `_backup_path_for` to `fileops.py` (P2, ~10 lines).

## Larger Bets

- Signed Windows release with provisioned cert + bundled signed ABE
  helper + raster icon set.
- Conflict-review modal + per-category direct-write policy + CLI flag
  + manifest schema growth.
- Glean (declared metrics) + Sentry (crash) + signed appcast
  (WinSparkle) — three independent opt-in tracks with first-run dialog
  re-prompt on trust-model change.
- macOS DMG + Linux AppImage release pipeline; per-OS smoke tests;
  Apple Developer notarization.
- Extension-settings allowlist for the three highest-value WebExtensions
  (uBO filter lists, Stylus userstyles, Bitwarden vault URL).
- Passkey inventory + FIDO CXF alignment; export blocked until
  destination side supports.
- Profile detection breadth: portable Firefox installs, Thunderbird,
  SeaMonkey, and the long-tail Chromium forks not yet in the spec table.

## Explicit Non-Goals

- Not a Firefox Sync replacement; FoxPort migrates local state, not
  ongoing sync.
- Never silently modify source Chromium profiles.
- Never silently write target Firefox/Chromium profiles while they
  are running.
- Never auto-install extensions or bypass browser install consent.
- Never upload passwords, cookies, browsing history, URLs, profile
  paths, or extension lists.
- No proprietary passkey export format; passkey work waits for FIDO
  CXF/CXP destination support.
- No full browser-forensics UI; provenance + diagnostics are useful,
  migration remains the product.
- No unsigned elevated ABE helper as a polished user-facing default.
- No telemetry / crash / update without first-run consent + a declared
  data dictionary + a documented privacy policy.
- No obscure source browsers (Maxthon, Coc Coc, etc.) until the supported
  set has a signed release and conflict UI.
- No "merge mode" for direct-write before the skip/overwrite/backup-only
  modal ships (we need the safer baseline before the riskier behavior).

## Open Questions

- Which Authenticode certificate path will FoxPort take? SignPath's
  open-source program is free for OSS but requires a project review;
  Sectigo/Certum commercial certs are ~$200/year. SignPath is the
  recommended path for an MIT project.
- Should the v1.3.2 signed release also gate-out unsigned local builds
  (i.e. should `crypto/abe.py` refuse to launch an unsigned
  `foxport_abe.exe`)? The trust improvement is real but it locks out
  source-build forks.
- macOS distribution: Apple Developer ID + notarization (~$99/year and
  some friction) or DMG-only with right-click → Open? Notarization is
  the user-facing standard.
- Linux distribution: AppImage, Flatpak, or per-distro packages?
  AppImage gives the broadest reach at the cost of bundling NSS.
- For conflict-review defaults, which policy is the safe default per
  category? Proposal: passwords=skip (deterministic GUID match makes
  this trivially correct), cookies=backup-only (don't replace; just
  back up the target), history=backup-only, open_tabs=backup-only.
  Users opt into more destructive policies explicitly.
- Should `manifest.json` schema_version bump to 2 when the conflict
  policy fields land, or stay 1 with additive fields? Additive (stay 1)
  reduces consumer friction; a bump signals the new fields to clients
  that want them.
- Where do the next 4 curated-map entries come from to honor the "67"
  doc claim? Top candidates the audit pass identified: Mozilla's own
  "Multi-Account Containers" if a popular Chrome equivalent exists,
  Wappalyzer, Vimium-FF, ColorZilla. None of these is automatic — each
  needs a real AMO slug verification before landing.
