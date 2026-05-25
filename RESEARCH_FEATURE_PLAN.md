# Project Research and Feature Plan

Generated: 2026-05-25 (refresh pass on `main` at `88830b3`, post-v1.3.1 batch).

Status baseline: 42 commits on `main`; `pytest` reports **182 passed** in
~2 s; `python -m foxport.cli --help`, `--version`, and `list` all succeed
under default Windows PowerShell encoding. Working tree clean.

This file replaces the 2026-05-25 research plan that was authored before
the v1.3.1 batch landed. Six commits since that file (`f3db0a7` through
`88830b3`) closed the v1.3.1 audit regressions plus most of the v1.3.3
P1/P2 list. This refresh re-audits the post-batch state, surfaces the
new findings the live curated-map audit produced, and proposes v1.3.2 /
v1.3.3 / v1.4 work.

## Executive Summary

FoxPort is a Windows-first cross-platform Python/PyQt6 desktop and CLI
tool for moving browser data between Chromium-family and Firefox-family
profiles. The product is in its strongest shape yet: every staging
emitter is atomic-replace, every direct-write category logs a pre-flight
conflict count before mutation, the Done screen renders an Open/Reveal
+ Reveal-backup button per artifact, the snapshot inspect dialog reads
the inner per-run manifest and labels artifact sensitivity, HIBP
distinguishes scan-clean from scan-failed, the CLI emits a
schema-versioned JSON payload on every action subcommand, and the
release workflow has Authenticode scaffolding waiting on cert
provisioning.

Net-new findings this pass:

1. **Curated map has 7 broken AMO entries right now.** Live audit at
   `2026-05-25T...` flags `vpn_proxy/touch-vpn` (http-401),
   `shopping_coupons/rakuten` (404), `ai_assistants/perplexity-companion`
   (404), `ad_tracker_privacy/i-still-dont-care-about-cookies` (404),
   `github_dev_workflow/zotero-connector` (http-401),
   `github_dev_workflow/bukubrow` (404), `vpn_proxy/browsec-vpn`
   (http-401). 11 stale (>24 months) including `productivity_tabs/auto-tab-discard`
   and `shopping_coupons/honey`. The monthly cron is supposed to file a
   GH issue but the dead links are user-visible in every migration run
   today. This is the single highest-value v1.3.2 patch — a docs-only
   release won't fix it.
2. **Version bump pending.** `foxport/__init__.py:__version__ = "1.3.0"`
   but the v1.3.1 batch is feature-complete and pushed. CLI still
   reports `FoxPort 1.3.0`. CHANGELOG section is still
   `[Unreleased] — v1.3.1 (in progress)`; needs to become `[1.3.1] — 2026-05-25`
   before tagging.
3. **ROADMAP checkbox drift.** v1.3.1 section header still reads
   "🚧 in progress" with all four boxes unchecked even though commit
   `f3db0a7` + `4ffa0ae` closed every item. `Pre-flight conflict analysis
   for open_tabs` and `README install snippet cross-platform softening`
   are also shown unchecked in v1.3.3 / v1.3.1 sections but landed in
   batches 1 and 2.
4. **`docs/architecture.md` doesn't cover v1.3 additions.** Missing
   `foxport/manifest.py`, `foxport/migrate/conflicts.py`,
   `foxport/fileops.py`. The doc lists `snapshot.py` but not the
   per-run manifest writer or the conflict pre-flight analyzers.
5. **`import-bookmarks` is the only action subcommand without `--json`.**
   Every other action command grew `--json` in commit `97b9930`;
   import-bookmarks was missed.
6. **`ResourceWarning` in `tests/migrate/test_downloads.py:119`.** A
   `csv_path.open(...)` isn't closed; surfaces only when warnings are
   escalated to errors (`pytest -W error::ResourceWarning`) but is real
   lint.
7. **Screenshots still 2026-05-23.** Pre-date the downloads row,
   network-activity preview sub-tree, "Reveal backup" buttons, restore-
   inspect run-details panel, and HIBP tri-state copy.

Highest-value next opportunities in priority order:

1. **Curated map cleanup** — remove or re-slug the 7 broken entries
   (P1). Without this, every migration emits a few extensions.html
   rows that link to dead AMO pages.
2. **Version bump to 1.3.1 + tag the release** (P1) — promote
   CHANGELOG `[Unreleased]` to `[1.3.1]`, bump `__version__`, fix the
   ROADMAP staleness, tag `v1.3.1`. No code-shipping risk.
3. **Conflict review dialog + per-category direct-write policy** (P1) —
   the last big v1.3.3 piece. Pre-flight analyzers ship counts; the
   modal that lets the user pick skip / overwrite / backup-only per
   category, plus the matching CLI `--direct-write-policy` flag, is
   still open.
4. **Signed Windows release + bundled ABE sidecar** (P0) — distribution
   is still the single biggest wall before non-developer install.
   Cert + icon provisioning blocks workflow exercise.
5. **docs/architecture.md refresh** (P2) — surface `manifest.py`,
   `conflicts.py`, `fileops.py` so the next contributor can navigate.
6. **`import-bookmarks --json`** (P2) — completes the CLI JSON arc.
7. **Manifest privacy redact flag** (P2) — `--privacy-redact` strips
   `C:\Users\<name>` from backup paths so support uploads don't leak
   the username.
8. **Re-run screenshots** (P2) — current UI has materially changed
   since 2026-05-23.
9. **First-run dialog re-prompt on trust-model change** (P3) —
   scaffolding for the future v1.4 telemetry/crash opt-in surfaces.
10. **macOS DMG + Linux AppImage distribution** (P3) — runtime works
    cross-platform but only the Windows ZIP gets a release artifact.

Larger bets unchanged (v1.4): downloads → moz_annos direct-write,
extension-settings allowlist (uBO / Stylus / Bitwarden), opt-in Glean +
Sentry + WinSparkle appcast, passkey inventory aligned with FIDO CXF,
per-host conflict preview ("merge mode"), restore-from-backup wizard,
background-worker preview counts for large profiles.

## Evidence Reviewed

Local files and directories inspected this pass:

- Root: `README.md`, `CHANGELOG.md`, `ROADMAP.md`, `CLAUDE.md`,
  `LICENSE`, `requirements.txt`, `pyproject.toml`, `foxport.spec`,
  `.gitignore`.
- Workflows: `.github/workflows/ci.yml`, `release.yml`,
  `curated-map-audit.yml`.
- Package (`foxport/`): `__init__.py` (still `1.3.0`), `__main__.py`,
  `app.py`, `cli.py` (now 7 subcommands × `--json` for 6),
  `config.py`, `diff.py`, `fileops.py` (with new
  `timestamped_backup_path` helper), `manifest.py`, `snapshot.py`.
- Browsers: `browsers/detect.py`, `chromium.py`, `firefox.py`,
  `firefox_read.py`.
- Crypto: `crypto/abe.py`, `dpapi.py`, `hibp.py` (with new
  `HibpScanResult` + tri-state), `keychain.py`, `mozhash.py`,
  `nss.py`.
- GUI: `gui/dialogs.py` (with new `RestoreInspectDialog.run_manifest`
  + `_try_read_inner_run_manifest` + `_build_run_details_widget` +
  hidden telemetry placeholders), `main_window.py`, `pages.py`,
  `theme.py`, `widgets.py`, `workers.py` (with HIBP tri-state +
  open-tabs backup wiring).
- Migrators: `migrate/*.py` (10 forward + 4 nss_* + `conflicts.py`
  with new `analyze_open_tabs()`), `migrate_reverse/*.py`.
- Adapters: `import_/adapters.py`.
- Data: `foxport/data/curated_extension_map.json` (verified **63
  entries** + new `_meta.entry_count: 63` + `_meta.category_count: 14`).
- Scripts: `capture_screenshots.py`, `check_curated_map.py` (with new
  meta self-check, exit 3 on drift), `harvest_reverse_map.py`.
- Sidecar: `tools/abe_sidecar/foxport_abe.cpp`, `CMakeLists.txt`.
- Tests: 32 test files; `pytest --collect-only` reports **182 tests
  collected**.
- Docs: `docs/architecture.md` (139 lines, pre-v1.3),
  `docs/file-formats.md` (216 lines), `docs/troubleshooting.md`
  (163 lines).

Git history reviewed:

- `git log --oneline` 42 commits total. Most recent 6 are today's
  v1.3.1 batch landing:
  - `88830b3` test: atomic-replace failure recovery + close Phase D test gaps
  - `97b9930` feat(cli): --json on migrate / migrate-reverse / diff / snapshot / restore
  - `afb838b` feat(hibp): tri-state status — distinguish scan-clean from scan-failed
  - `76e74fd` feat(gui): restore-inspect dialog reads inner RunManifest
  - `4ffa0ae` feat(v1.3.1): quick wins — cards reveal, hide telemetry, lift backup helper
  - `f3db0a7` fix(v1.3.1): three audit-batch regressions + open-tabs conflict pre-flight
- Working tree clean.

Live verification performed this pass:

- `python -m pytest -ra -q` → **182 passed** in 2 s.
- `python -m foxport.cli --version` → `FoxPort 1.3.0` (version bump pending).
- `python -m foxport.cli --help` → ASCII-safe under cp1252.
- `python -m foxport.cli list` → enumerates this VM's profiles cleanly.
- `python -m foxport.cli migrate --help` shows `--json` flag with full
  description; `import-bookmarks --help` does NOT.
- `python -W error::ResourceWarning -m pytest` → fails on
  `tests/migrate/test_downloads.py:119` (unclosed file handle).
- `python scripts/check_curated_map.py --sleep 0.1` → live audit
  reports `63 total, 7 broken/disabled, 11 stale (>24 months)`.
- Curated meta self-check: `_meta.entry_count == 63`, `category_count
  == 14`, matches `load_curated_map()` length.

External sources re-consulted (links unchanged from prior pass):

- [Mozilla Firefox source docs, Migrators reference](https://firefox-source-docs.mozilla.org/browser/components/migration/docs/migrators.html)
- [Mozilla NSS reference](https://firefox-source-docs.mozilla.org/security/nss/) — `NSS_GetVersion` / `PK11SDR_*`.
- [HIBP API v3](https://haveibeenpwned.com/API/V3) — padding header + k-anonymity.
- [Google Chrome 127+ App-Bound Encryption](https://security.googleblog.com/2024/07/improving-security-of-chrome-cookies-on.html).
- [FIDO CXF v1.0 ready draft](https://fidoalliance.org/specs/cx/cxf-v1.0-rd-20250313.html).
- [Microsoft SignTool](https://learn.microsoft.com/en-us/dotnet/framework/tools/signtool-exe) + [PyInstaller versioning](https://pyinstaller.org/en/stable/usage.html).
- [WinSparkle](https://winsparkle.org/) for signed update appcasts.
- [Mozilla Glean (Python)](https://mozilla.github.io/glean/python/glean/index.html) + [Sentry Python SDK](https://docs.sentry.io/platforms/python/).
- [SignPath](https://signpath.org/) — open-source code-signing path.

Not verified this pass:

- ABE sidecar end-to-end (no Chrome 127+ ABE-only profile on this VM;
  no signed binary locally).
- Authenticode-signed release artifact (no cert configured).
- Live Firefox/Chrome import acceptance for each emitted SQLite/JSONLZ4.
- AMO reverse curated-map audit (only forward exercised this pass).
- macOS Keychain + Linux libsecret/kwallet on real OS (unit tests only).

## Current Product Map

### Core workflows

- **Forward GUI migration** (Chromium → Firefox-family): detect → Source
  tile + direction toggle → Target tile (optional) → Items (10
  categories + 5 customize buttons + 4 direct-write toggles + HIBP +
  dry-run + output dir) → Preview tree (per-category counts + network-
  activity sub-tree) → Run (live log + progress + Done action bar
  per-artifact + Save-as-snapshot).
- **Reverse GUI migration** (Firefox → Chromium): direction toggle on
  Source page swaps source/target families; passwords/bookmarks/
  extensions supported in reverse (CSV/HTML output only — no reverse
  direct-write).
- **CLI**: 7 subcommands — `list` (`--detail`, `--json`), `migrate`
  (`--json`), `migrate-reverse` (`--json`), `diff` (`--json`),
  `snapshot` (`--json`), `restore` (`--overwrite`, `--json`),
  `import-bookmarks` (`--format`; no `--json` yet).
- **First-run trust dialog** — single-shot on first GUI launch (gated
  by `Settings.first_run_acked_iso`). Discloses source-read-only,
  plaintext-output cleanup, opt-in AMO + HIBP, no telemetry/crash/
  update.
- **Snapshot / restore** — `.fxport` ZIP, PBKDF2-SHA256(200k) →
  AES-256-GCM, SHA-256-per-file integrity, atomic-replace, refuse
  non-empty output without `--overwrite`. GUI inspect dialog renders
  run details from the inner per-run manifest (post-v1.3.1).
- **Curated extension map**: 63 Chrome → AMO entries × 14 categories;
  monthly cron auditor with `--include-reverse`; new `_meta.entry_count`
  self-check guards against doc drift.

### User personas

- Windows users migrating from a Chromium browser to Firefox-family.
- Privacy-conscious users (first-run dialog + Preview network sub-tree
  aimed here).
- Power users with portable Firefox installs (NSS path override).
- IT / support operators needing repeatable output + manifests + JSON
  CLI for downstream automation.
- Maintainers extending categories or browser support (curated map +
  monthly audit).

### Platforms and distribution

- Runtime: Python 3.11+; CI matrix Windows/macOS/Linux × 3.11/3.12.
- Distribution: GitHub Releases → Windows ZIP via `workflow_dispatch`.
  Authenticode scaffolding present; cert provisioning pending.
- macOS / Linux distribution: not represented in `release.yml`.
- Settings: `%APPDATA%/FoxPort/config.json` (Windows),
  `~/Library/Application Support/FoxPort` (macOS),
  `$XDG_CONFIG_HOME/FoxPort` (Linux).

### Network surface

- AMO: `addons.mozilla.org/api/v5/{search,addons/addon}` — extension
  metadata. Opt-in (default ON), can be disabled per-run.
- HIBP: `api.pwnedpasswords.com/range/<5-char>` — k-anonymity password
  scan. Opt-in (default OFF), `Add-Padding: true`. Worker now reports
  tri-state (`checked-clean` / `checked-hits` / `network-error` /
  `disabled`); manifest records the live status.
- No telemetry, crash reporting, or update checks in v1.3.1. Settings
  dialog placeholders hidden behind a `_FUTURE_TELEMETRY = False`
  feature flag.

## Feature Inventory

Confidence labels: **Verified** (this pass), **Likely** (consistent
with code but not exercised), **Assumption** (needs live validation).

### Profile Detection
- Value: zero-config discovery of ~20 browsers + Opera flat layout
  + locked-profile / running-process detection.
- Code: [foxport/browsers/detect.py](foxport/browsers/detect.py).
- Maturity: **Verified** complete; no `tests/test_detect.py`.
- Improvements: profile detection test fixtures (Opera GX flat,
  Thunderbird, portable Firefox) — ROADMAP v1.4 P3.

### Source / Target wizard + direction toggle
- Code: [foxport/gui/pages.py:160-530](foxport/gui/pages.py#L160-L530).
- Maturity: **Verified** complete. Drag-drop tile auto-detects
  Pocket/Pinboard/OPML/Netscape exports.

### Items page (10 categories, dict-keyed badges)
- Code: [foxport/gui/pages.py:534-924](foxport/gui/pages.py#L534-L924).
- Maturity: **Verified** complete; `set_counts(dict[str, int])` covers
  all 10 categories.

### Password export (CSV + NSS direct-write + HIBP tri-state)
- Code: [foxport/migrate/passwords.py](foxport/migrate/passwords.py),
  [nss_passwords.py](foxport/migrate/nss_passwords.py),
  [crypto/nss.py](foxport/crypto/nss.py),
  [crypto/hibp.py](foxport/crypto/hibp.py) (now `HibpScanResult`).
- Maturity: **Verified** strong; deterministic GUIDs, accounting
  invariant, refusal on unparseable target `logins.json`, atomic
  write of `logins.json` + `logins-backup.json`, pre-flight conflict
  count, NSS version guard, manifest sensitivity flag + per-run
  backup path, **tri-state HIBP status**.

### Bookmarks (HTML + folder filter + external adapters)
- Code: [foxport/migrate/bookmarks.py](foxport/migrate/bookmarks.py),
  [import_/adapters.py](foxport/import_/adapters.py).
- Maturity: **Verified** complete. Reverse direction promotes Firefox
  toolbar to Chrome bookmarks bar; external adapters reachable via
  CLI `import-bookmarks` + GUI drop.

### Extension mapping (curated + AMO + permission overlap)
- Code: [foxport/migrate/extensions.py](foxport/migrate/extensions.py),
  `foxport/data/curated_extension_map.json` (**63 entries × 14
  categories** with `_meta.entry_count`).
- Maturity: **Verified** strong; **Verified bug** — 7 curated entries
  return 404/401 on live AMO right now. UA is now `__version__`-aware.
- Improvements: curated map cleanup (the single biggest user-facing
  quality gap in v1.3.1).

### Cookies / History / Open tabs (export + direct-write + pre-flight)
- Code: `migrate/cookies.py`, `nss_cookies.py`, `migrate/history.py`,
  `nss_history.py`, `migrate/mozhash.py`, `migrate/open_tabs.py`,
  `migrate/conflicts.py:analyze_*`.
- Maturity: **Verified** complete. All four destructive direct-write
  categories (passwords, cookies, history, open_tabs) log pre-flight
  counts; all four surface Done-screen Reveal-backup buttons.

### Autofill / Cards / Search engines / Downloads
- Code: `migrate/autofill.py`, `migrate/cards.py`,
  `migrate/search_engines.py`, `migrate/downloads.py`.
- Maturity: **Verified** complete. Cards CSV defaults to `"reveal"`
  in `_DEFAULT_ACTION` (plaintext PAN — safer than auto-launching).
- Improvements: downloads → `places.sqlite.moz_annos` when history
  direct-write selected (v1.4 P2); autofill direct-write toggle (v1.4 P3).

### Reverse Firefox → Chromium
- Code: `migrate_reverse/*.py`, `browsers/firefox_read.py`.
- Maturity: **Verified** narrow by design — passwords/bookmarks/
  extensions only.

### CLI (now 7 subcommands × `--json` for 6)
- Code: [foxport/cli.py](foxport/cli.py),
  `tests/test_cli_json.py` (5 tests).
- Maturity: **Verified** strong; **Verified gap** — `import-bookmarks`
  does NOT have `--json`. `_JSON_SCHEMA_VERSIONS` constant pins
  schema versions in one place.

### Snapshot + restore (`.fxport`)
- Code: [foxport/snapshot.py](foxport/snapshot.py),
  [gui/dialogs.py:RestoreInspectDialog](foxport/gui/dialogs.py).
- Maturity: **Verified** strong. Atomic write, overwrite policy,
  SHA-256 integrity, GUI inspect dialog renders run-details from the
  inner per-run manifest (v1.3.1 addition).

### Settings dialog
- Code: [foxport/config.py](foxport/config.py),
  [gui/dialogs.py:SettingsDialog](foxport/gui/dialogs.py).
- Maturity: **Verified** complete. Output dir, mask default, AMO
  default, dry-run default, HIBP default, NSS path override,
  Reset-to-defaults. Telemetry/crash placeholders feature-flagged off
  (post-v1.3.1).

### Release / packaging
- Code: [.github/workflows/release.yml](.github/workflows/release.yml),
  [foxport.spec](foxport.spec).
- Maturity: **Verified partial**. Authenticode scaffolding wired;
  `WINDOWS_CERT_BASE64` secret unset, `assets/icon.ico` absent.

### Configuration / atomic helpers
- Code: [foxport/fileops.py](foxport/fileops.py) (now exports
  `timestamped_backup_path` + `write_bytes_atomic` +
  `replace_file_atomic` + atomic-replace failure recovery tests).
- Maturity: **Verified** strong; 7 tests in `tests/test_fileops.py`.

### Per-run manifest (`manifest.json`)
- Code: [foxport/manifest.py](foxport/manifest.py).
- Maturity: **Verified** complete. Schema v1; never carries plaintext;
  `network.api.pwnedpasswords.com` now records the live HIBP tri-state.

## Competitive and Ecosystem Research

Unchanged from the previous pass — the prior `RESEARCH_FEATURE_PLAN.md`
listed Firefox built-in import wizard, Google Takeout, HackBrowserData,
Hindsight, Mozilla AMO API, HIBP, Chrome 127+ ABE, FIDO CXF/CXP, and
Glean/Sentry/WinSparkle. The 2026-05-25 batch didn't change which
products this project competes with or learns from. One incremental
note:

### Mozilla AMO API — curated-map liability
- The forward auditor surfaces real breakage today (7 broken / 11
  stale entries). The cron is supposed to file an issue but the
  monthly schedule means the broken slugs sit in users' migrations
  between runs. Tighter cadence (weekly?) or in-app warning when a
  curated lookup 404s would help.

## Highest-Value New Features

### 1. Curated map cleanup batch
- User problem solved: 7 extensions in users' migrations link to dead
  AMO pages right now. The extensions.html report shows a curated
  match with a slug that returns 404 / 401.
- Evidence: live `scripts/check_curated_map.py --sleep 0.1` reports
  `63 total, 7 broken/disabled, 11 stale (>24 months)`:
  - `vpn_proxy/touch-vpn` (http-401)
  - `shopping_coupons/rakuten` (404)
  - `ai_assistants/perplexity-companion` (404)
  - `ad_tracker_privacy/i-still-dont-care-about-cookies` (404 — note:
    `i-dont-care-about-cookies` is a distinct, live slug)
  - `github_dev_workflow/zotero-connector` (http-401)
  - `github_dev_workflow/bukubrow` (404)
  - `vpn_proxy/browsec-vpn` (http-401)
- Proposed behavior: for each broken slug, either (a) find the new
  AMO slug for the same extension, (b) drop the entry, or (c) replace
  with a known good alternative. Bump `_meta.entry_count` and
  `_meta.last_verified`. Touch-VPN and Browsec-VPN may be AMO-side
  VPN-extension restrictions (commonly auth-walled); investigate.
- Implementation areas: `foxport/data/curated_extension_map.json`
  (data edits only), `_meta.entry_count` bump, monthly cron continues
  unchanged.
- Risks: low — JSON edits with auditor self-check.
- Verification: `python scripts/check_curated_map.py` returns 0
  broken / 0 disabled afterwards.
- Complexity: S.
- Priority: **P1** (real user-visible quality regression sitting in
  every migration today).

### 2. Promote v1.3.1 release (version bump + CHANGELOG + ROADMAP + tag)
- User problem solved: v1.3.1 is feature-complete and pushed but
  remains unreleased. `__version__` still says 1.3.0; CHANGELOG section
  is still `[Unreleased]`; ROADMAP v1.3.1 section still shows
  unchecked boxes for items that were committed in `f3db0a7` /
  `4ffa0ae`.
- Evidence: `foxport/__init__.py:3` is `__version__ = "1.3.0"`;
  `CHANGELOG.md:7` is `## [Unreleased] — v1.3.1 (in progress, 2026-05-25)`;
  `ROADMAP.md:16` says `## v1.3.1 — Audit-batch regressions 🚧 in progress`;
  ROADMAP boxes 21–35 unchecked despite the commits closing them.
- Proposed behavior: bump `__version__` to `1.3.1`, promote
  CHANGELOG header to `## [1.3.1] — 2026-05-25`, mark v1.3.1 ROADMAP
  section ✅ + tick the four checkboxes + collapse into "Historical
  milestones", tag `v1.3.1` (signed cert won't sign yet — okay for
  source release; signed Windows binary waits for v1.3.2).
- Implementation areas: `foxport/__init__.py`, `CHANGELOG.md`,
  `ROADMAP.md`. No code changes.
- Risks: none — docs + version literal only.
- Verification: `python -m foxport.cli --version` → `FoxPort 1.3.1`.
- Complexity: XS.
- Priority: **P1**.

### 3. Conflict review dialog + per-category direct-write policy
- User problem solved: today the user sees pre-flight counts in the
  run log ("12 of 50 already in target, 38 new" / "100 source cookies
  will REPLACE 200 existing rows") but can't change policy. The user
  can only choose to enable or skip the direct-write entirely.
- Evidence: [foxport/migrate/conflicts.py](foxport/migrate/conflicts.py)
  ships analyzers for passwords/cookies/history/open_tabs and the
  worker logs the counts; ROADMAP v1.3.3 P1 still open.
- Proposed behavior: between Preview and Run, a "Direct-write review"
  modal appears (only when direct-write is enabled for any category).
  Shows per-category counts + samples + per-category policy dropdown:
  skip / overwrite / backup-only (merge defers to v1.4). CLI gets
  `--direct-write-policy=...` and `--yes`. Worker reads the policy
  per category and the manifest records the choice.
- Implementation areas: new `foxport/gui/dialogs.py:DirectWritePolicyDialog`,
  worker policy-aware loops in `nss_passwords`/`nss_cookies`/
  `nss_history`/`open_tabs`, CLI flag, manifest schema (additive),
  tests.
- Risks: merge semantics for cookies/history are non-trivial; ship
  skip/overwrite/backup-only first and defer merge as a v1.4 follow-up.
- Verification: synthetic conflict fixtures × every policy + CLI
  flag; manual flow exercising each policy.
- Complexity: L.
- Priority: **P1**.

### 4. Signed Windows release + bundled signed ABE sidecar + app icon
- User problem solved: distribution is still the single biggest wall
  before non-developer install. The workflow is wired; secrets +
  icon are the only gates.
- Evidence: [release.yml:107-133](.github/workflows/release.yml#L107-L133)
  signing step gated by `WINDOWS_CERT_BASE64`; `assets/icon.ico`
  absent; `foxport/data/foxport_abe.exe` not built locally.
- Proposed behavior: provision a signing cert (SignPath OSS or
  Sectigo/Certum commercial), set workflow secrets, drop
  `assets/icon.ico`, run `workflow_dispatch v1.3.2-rc1`. ABE sidecar
  gets signed in the same step.
- Implementation areas: `assets/icon.ico` (new), GH org secrets,
  workflow exercise.
- Risks: AV false positives on a new signed binary.
- Verification: `Get-AuthenticodeSignature dist/FoxPort/FoxPort.exe`
  → Valid; manual UAC on Chrome 127+ ABE-only profile.
- Complexity: M (workflow wired; this is provisioning).
- Priority: **P0**.

### 5. `import-bookmarks --json`
- User problem solved: completeness — every other action subcommand
  now emits a schema-versioned JSON payload, but the bookmark
  converter still prints human text only.
- Evidence: [foxport/cli.py:_cmd_import_bookmarks](foxport/cli.py#L685-L745).
- Proposed behavior: `--json` emits `{schema_version, command,
  input_format, parsed_count, out_path}`.
- Implementation areas: `foxport/cli.py` (one branch),
  `tests/test_cli_json.py` (one test).
- Risks: none.
- Complexity: XS.
- Priority: **P2**.

### 6. Manifest privacy redact flag
- User problem solved: `manifest.json` records `backup_path` as an
  absolute string like `C:\Users\<username>\AppData\...`. Uploading
  the manifest for support exposes the username.
- Evidence: `foxport/manifest.py:142-148` stores backups as `str(backup_path)`.
- Proposed behavior: `python -m foxport.cli migrate --privacy-redact`
  swaps `C:\Users\<name>` / `/home/<name>` / `/Users/<name>` for a
  `<redacted>` token in the on-disk manifest. The Help menu's "Report
  a problem" action gets a "Copy redacted summary" affordance.
- Implementation areas: `foxport/manifest.py` (redactor), `foxport/cli.py`
  flag, GUI menu, tests.
- Risks: redaction must not break path-resolution for the user's own
  rollback; the in-memory backups dict in workers stays absolute.
- Complexity: S.
- Priority: **P2**.

### 7. docs/architecture.md refresh
- User problem solved: doc lists `snapshot.py` but not the v1.3
  additions (`manifest.py`, `conflicts.py`, `fileops.py`). Next
  contributor mapping the codebase hits stale signposts.
- Evidence: [docs/architecture.md](docs/architecture.md) has no
  matches for "manifest" / "conflicts" / "fileops".
- Proposed behavior: add per-file one-liner blocks for manifest.py,
  conflicts.py, fileops.py; refresh the layer diagram; mention the
  per-run manifest as a sibling of README.txt.
- Implementation areas: `docs/architecture.md`.
- Complexity: S.
- Priority: **P2**.

### 8. Re-run `scripts/capture_screenshots.py`
- User problem solved: `assets/screenshots/*.png` dated 2026-05-23
  pre-date the downloads row, the 4 direct-write checkboxes, the
  dry-run banner, the network-activity preview sub-tree, the
  per-artifact Done action bar, the Restore-inspect run-details
  panel, and the HIBP tri-state copy. The README screenshots
  materially misrepresent the v1.3.1 UI.
- Evidence: file mtime check; live UI inspection vs. PNGs.
- Proposed behavior: run the existing `scripts/capture_screenshots.py`
  helper after a real migration to a fresh Firefox profile.
- Implementation areas: `assets/screenshots/*.png`.
- Risks: requires a real browser profile to look populated.
- Complexity: S (manual).
- Priority: **P2**.

### 9. First-run dialog re-prompt on trust-model change
- User problem solved: a future version that adds telemetry/crash/
  update needs to re-prompt the user. Today the dialog is gated by a
  single `first_run_acked_iso` timestamp with no revision counter.
- Evidence: [foxport/config.py:46](foxport/config.py#L46),
  [gui/main_window.py:69-72](foxport/gui/main_window.py#L69-L72).
- Proposed behavior: add `Settings.first_run_acked_for_trust_revision: int = 0`
  + module-level `_TRUST_REVISION = 0` in `config.py`. Re-prompt when
  the stored revision is below current; the dialog updates the stored
  revision on accept. Bumps land in lockstep with new optional
  network/storage features.
- Implementation areas: `foxport/config.py`, GUI plumbing, test.
- Risks: existing acks must not re-prompt (set revision to 0 in
  v1.3.x, bump to 1 when telemetry first appears).
- Complexity: S.
- Priority: **P3** (build now; bump comes with the first network
  feature that warrants it).

### 10. macOS DMG + Linux AppImage distribution
- User problem solved: Mac/Linux users have no install path other
  than cloning the repo.
- Evidence: `release.yml` is Windows-only; runtime + CI cover three
  OSes.
- Proposed behavior: per-OS PyInstaller in `release.yml`; macOS path
  needs Apple Developer ID + notarization (or DMG with right-click →
  Open); Linux ships an AppImage that bundles libnss3 or documents
  `FOXPORT_NSS_PATH`.
- Implementation areas: parallel jobs in `release.yml`, signed/
  notarized macOS path, AppImage tooling, per-OS smoke tests.
- Risks: macOS notarization is a non-trivial Apple program; AppImage
  must bundle NSS or document the path override.
- Complexity: XL.
- Priority: **P3**.

## Existing Feature Improvements

### Bump `__version__` from 1.3.0 → 1.3.1
- Current: `foxport/__init__.py:3` is `__version__ = "1.3.0"`.
- Problem: every CLI invocation reports the wrong version; AMO + HIBP
  User-Agent headers also under-report.
- Recommended: bump on the next commit; tag `v1.3.1`.
- Complexity: XS. Priority: **P1**.

### Promote CHANGELOG `[Unreleased]` → `[1.3.1] — 2026-05-25`
- Current: header is `## [Unreleased] — v1.3.1 (in progress, 2026-05-25)`.
- Recommended: rename to `## [1.3.1] — 2026-05-25`, prepend a fresh
  `## [Unreleased]` block for the next batch.
- Complexity: XS. Priority: **P1**.

### Reconcile ROADMAP v1.3.1 + v1.3.3 checkboxes
- Current: v1.3.1 section header still "🚧 in progress" with all four
  boxes unchecked. v1.3.3 boxes for "Pre-flight conflict analysis for
  open_tabs" and "README install snippet cross-platform softening" are
  also stale.
- Evidence: commit `f3db0a7` closed the v1.3.1 items + open-tabs
  pre-flight; commit `4ffa0ae` softened the README install snippet.
- Recommended: tick all six boxes, change v1.3.1 header to "✅ shipped
  2026-05-25", collapse into Historical milestones at next refresh.
- Complexity: XS. Priority: **P1**.

### Fix `test_downloads.py` ResourceWarning (file leak)
- Current: [tests/migrate/test_downloads.py:119](tests/migrate/test_downloads.py#L119)
  has `list(_csv.reader(csv_path.open(encoding="utf-8")))` — leaks
  the file handle. Surfaces only under `pytest -W error::ResourceWarning`
  but is real lint.
- Recommended: wrap in `with csv_path.open(...) as fh:` and pass `fh`
  to `csv.reader`.
- Complexity: XS. Priority: **P2**.

### Tighten curated-map cron cadence + in-app warning
- Current: monthly cron files an issue; users see the dead AMO links
  between runs.
- Recommended: (a) tighten cron to weekly, (b) when AMO returns 404
  for a curated slug during a live migration, downgrade to "no-match"
  with a "(curated entry stale — please report)" tag in the
  extensions.html row.
- Code locations: `.github/workflows/curated-map-audit.yml`,
  `foxport/migrate/extensions.py:_match_one` (graceful 404 path).
- Complexity: S. Priority: **P2**.

### Curated-map "lookup unavailable" tag distinct from "no match"
- Current: a 404 on a curated slug during a real migration silently
  degrades the row to `no-match` confidence — indistinguishable from
  "we have no curated mapping at all".
- Recommended: surface a third confidence tier like `curated-stale`
  in extensions.html so the user knows to refresh the curated map.
- Complexity: S. Priority: **P2** (depends on the curated-map cron
  hardening above).

### Verify auditor handles AMO 401 cleanly
- Current: the cron is supposed to file an issue on any non-OK
  status, but the live audit shows three http-401 results — possibly
  rate-limiting, possibly AMO-side restrictions on VPN-extension
  enumeration.
- Recommended: distinguish "deny-listed by AMO" from "AMO temporarily
  down" via the response body and retry on 5xx only.
- Code locations: `scripts/check_curated_map.py:_check_slug`.
- Complexity: S. Priority: **P3**.

### Background-worker preview counts
- Current: `_safe_sqlite_count` runs synchronously on the GUI thread.
  Large History DBs (>1M rows) make the Preview page feel frozen.
- Recommended: move count loop into a `QThread` with progress
  emission; show "Counting…" spinner.
- Complexity: M. Priority: **P3**.

### Snapshot create runs synchronously
- Current: GUI Save-as-snapshot blocks the main window while digest +
  zip runs.
- Recommended: thread the work via the same `make_thread` helper the
  migration worker uses; emit progress.
- Complexity: M. Priority: **P3**.

## Reliability, Security, Privacy, and Data Safety

Bugs / risks found this pass:

- **Verified — 7 broken curated-map slugs** (live AMO data, this pass).
  See Feature #1 for full enumeration.
- **Verified — `__version__` mismatch**: CLI + AMO/HIBP UA report
  `1.3.0`, repo state is `1.3.1`-equivalent.
- **Verified — ResourceWarning** in tests/migrate/test_downloads.py.
- **Verified — Manifest absolute paths leak username** in backup_path
  fields when uploaded for support (Feature #6).
- **Verified — Release artifacts unsigned**: `WINDOWS_CERT_BASE64` not
  set; `assets/icon.ico` absent; `foxport_abe.exe` not pre-built.
- **Verified — `import-bookmarks` missing `--json`**.
- **Verified — `docs/architecture.md` stale** (missing 3 v1.3 modules).
- **Verified — Screenshots stale** (2026-05-23).

Missing guardrails:

- Conflict review dialog (P1).
- macOS Keychain test coverage.
- Profile detection test fixtures.

Permission / network / file-system concerns:

- ABE sidecar elevation: still requires unsigned binary until cert
  provisioning lands.
- AMO + HIBP: both opt-in, both disclosed. HIBP now tri-state so
  scan-failed surfaces explicitly.

Recovery / rollback needs:

- "Restore-from-backup" wizard step still missing (v1.4 P3) — users
  who direct-write and then regret it can locate the timestamped
  backup via the Done screen but must copy it back manually.

Logging / diagnostics needs:

- "Copy redacted diagnostics" Help-menu action (Feature #6 dependency).

## UX, Accessibility, and Trust

Onboarding gaps:

- First-run dialog in place; pre-sets AMO + HIBP defaults; tracks
  acknowledgement timestamp. Re-prompt-on-revision is not yet wired
  (Feature #9).

Empty / loading / error / disabled states:

- Source/Target tile empty states present.
- Preview counts synchronous (background-worker improvement above).
- Direct-write checkboxes correctly disable on reverse + when
  category unchecked.

Destructive / irreversible actions:

- Cookies/history/open-tabs direct-write replaces target files;
  backups exist; Done screen now surfaces "Reveal X backup" for all
  four categories (open_tabs caught up in v1.3.1). Pre-flight count
  logs before mutation for all four.
- Plaintext exports persist after import; the first-run dialog says
  "delete them"; the Done screen could surface a "Delete plaintext
  outputs" affordance (deferred).

Settings clarity:

- Telemetry/crash placeholders hidden behind `_FUTURE_TELEMETRY` flag.
- NSS path override + file picker present.

Accessibility:

- `:focus` styling + keyboard activation present.
- `accessibleName` / `accessibleDescription` smoke test not yet
  written.

Microcopy / trust signals:

- First-run dialog covers all four claims.
- Preview "Network activity" tree lists every endpoint with live
  ENABLED / disabled label including the new HIBP tri-state surface.
- Restore inspect dialog now surfaces per-artifact sensitivity badges
  before the user clicks Restore.

## Architecture and Maintainability

Module or boundary improvements:

- Two distinct manifest schemas remain: `SnapshotManifest` (snapshot
  file list) and `RunManifest` (per-migration). The snapshot ZIP
  carries the inner per-run manifest verbatim; the inspect dialog
  now reads both. This split is intentional and worth keeping —
  consolidation would entangle two unrelated concerns.
- `MigrationRequest` and `MigrationContext` still carry the same
  flag set in parallel. Could share a converter; not urgent.

Refactor candidates:

- `RunPage.ARTIFACT_ACTIONS` and `manifest._DEFAULT_ACTION` happen to
  align; could be sourced from one truth. Minor.
- `ItemsPage._make_row` × 10 calls could be a data-driven loop; minor.

Test gaps:

- macOS Keychain has no test file.
- Profile detection has no test file.
- Linux libsecret/kwallet has no test file.
- Accessibility smoke test (`accessibleName` on key widgets) absent.
- `import-bookmarks --json` (once implemented).

Documentation gaps:

- `docs/architecture.md` missing manifest.py / conflicts.py /
  fileops.py (Feature #7).
- `docs/file-formats.md` could explain `manifest.json` schema.
- `docs/troubleshooting.md` could cover the HIBP tri-state and the
  curated-map "lookup unavailable" cases.

Release / build / deployment gaps:

- Authenticode cert provisioning (Feature #4 / P0).
- `assets/icon.ico` (Feature #4 dependency).
- macOS / Linux release artifacts (Feature #10 / P3).
- SBOM / supply-chain attestation (cosign + GitHub OIDC, P3).

## Prioritized Roadmap

### Phase A — v1.3.1 release prep (this session)

- [ ] **P1** Bump `__version__` 1.3.0 → 1.3.1 + promote CHANGELOG
      `[Unreleased]` → `[1.3.1] — 2026-05-25`
  - Why: feature-complete and pushed; CLI + UA strings under-report.
  - Evidence: `foxport/__init__.py:3`; CHANGELOG header line 7.
  - Touches: `foxport/__init__.py`, `CHANGELOG.md`.
  - Acceptance: `python -m foxport.cli --version` → `FoxPort 1.3.1`.
  - Verify: `python -m foxport.cli --version`; `grep "1.3.1" CHANGELOG.md`.

- [ ] **P1** Reconcile ROADMAP v1.3.1 + stray checkboxes
  - Why: 6 boxes marked unchecked despite the commits closing them.
  - Evidence: ROADMAP lines 21–35; lines 85–87; line 111.
  - Touches: `ROADMAP.md`.
  - Acceptance: v1.3.1 section reads "✅ shipped 2026-05-25" + 0
    unchecked boxes in that section.

- [ ] **P1** Curated map cleanup (7 broken slugs)
  - Why: every migration today emits dead AMO links in extensions.html.
  - Evidence: `scripts/check_curated_map.py` reports 7 broken/disabled.
  - Touches: `foxport/data/curated_extension_map.json`,
    `_meta.entry_count` + `_meta.last_verified` refresh.
  - Acceptance: `python scripts/check_curated_map.py` returns
    `0 broken/disabled` (stale entries can remain — separate signal).
  - Verify: monthly cron green; live audit zero-broken.

- [ ] **P1** Tag `v1.3.1` (source-only release; signed Windows binary
      waits for v1.3.2)
  - Why: closes the v1.3.1 release cycle.
  - Touches: git tag.
  - Acceptance: `git tag -l v1.3.1` resolves; GH release notes
    quote the CHANGELOG section.

### Phase B — v1.3.2 distribution path

- [ ] **P0** Provision signing cert + drop `assets/icon.ico`
  - Why: only blocker to non-developer install.
  - Evidence: `release.yml:107-133`; `assets/` lacks `icon.ico`.
  - Touches: GH org secrets, `assets/icon.ico` (new).
  - Acceptance: `Get-AuthenticodeSignature dist/FoxPort/FoxPort.exe`
    → Valid; sidecar also signed.

- [ ] **P0** Run `workflow_dispatch` on `v1.3.2-rc1` and verify
  - Acceptance: ZIP + `.sha256` attached to GH release; both EXEs
    signed.

### Phase C — v1.3.3 trust + completeness

- [ ] **P1** Conflict review dialog + per-category direct-write policy
  - Why: pre-flight counts log; the modal that lets the user pick
    skip / overwrite / backup-only per category is the missing piece.
  - Evidence: `foxport/migrate/conflicts.py` analyzers exist; the
    worker logs counts but no policy enforcement.
  - Touches: new `DirectWritePolicyDialog` in `gui/dialogs.py`;
    worker policy-aware loops in `nss_passwords`, `nss_cookies`,
    `nss_history`, `open_tabs`; CLI `--direct-write-policy`,
    `--yes`; manifest schema (additive); tests.
  - Acceptance: every direct-write run surfaces the modal; user
    picks skip/overwrite/backup-only per category; manifest records.
  - Verify: synthetic conflict fixtures × every policy + CLI flag.

- [ ] **P2** `import-bookmarks --json`
  - Why: completeness — every other action subcommand has it.
  - Touches: `foxport/cli.py:_cmd_import_bookmarks`,
    `tests/test_cli_json.py`.
  - Acceptance: `python -m foxport.cli import-bookmarks --input x.opml --json`
    emits a schema-versioned payload.

- [ ] **P2** Manifest privacy redact flag
  - Why: support uploads leak `C:\Users\<name>`.
  - Touches: `foxport/manifest.py` redactor, `foxport/cli.py` flag,
    GUI menu, tests.
  - Acceptance: `migrate --privacy-redact` swaps user-dir prefixes for
    `<redacted>` token in the on-disk manifest.

- [ ] **P2** `docs/architecture.md` refresh
  - Why: missing 3 v1.3 modules.
  - Touches: `docs/architecture.md`.
  - Acceptance: doc has matches for "manifest" / "conflicts" / "fileops".

- [ ] **P2** Re-run `scripts/capture_screenshots.py`
  - Why: PNGs from 2026-05-23 don't reflect post-v1.3 UI.
  - Touches: `assets/screenshots/*.png`.
  - Acceptance: file mtime ≥ 2026-05-25; new shots show downloads
    row + network-activity sub-tree + Reveal-backup buttons.

- [ ] **P2** Tighten curated-map cron cadence + in-app "lookup
      unavailable" tag
  - Why: monthly cadence is too slow for slug breakage; the user has
    no signal during a live run.
  - Touches: `.github/workflows/curated-map-audit.yml`,
    `foxport/migrate/extensions.py`.

- [ ] **P2** Fix `tests/migrate/test_downloads.py:119` ResourceWarning
  - Touches: `tests/migrate/test_downloads.py`.
  - Acceptance: `pytest -W error::ResourceWarning` returns 0.

- [ ] **P3** First-run dialog re-prompt on trust-model change
  - Touches: `foxport/config.py`, `foxport/gui/main_window.py`, test.

### Phase D — v1.4 larger bets

- [ ] **P2** Downloads → `places.sqlite.moz_annos` direct-write
- [ ] **P2** Extension settings allowlist (uBO / Stylus / Bitwarden)
- [ ] **P3** Opt-in Glean telemetry with declared metrics
- [ ] **P3** Opt-in Sentry crash reporting (path-stripped)
- [ ] **P3** Signed update appcast (WinSparkle)
- [ ] **P3** Passkey inventory CXF prototype
- [ ] **P3** macOS DMG + Linux AppImage distribution
- [ ] **P3** Curated map hot-reload + in-run AMO cache
- [ ] **P3** Profile detection / macOS Keychain / Linux secret store
       test fixtures
- [ ] **P3** "Merge mode" for cookies/history direct-write
- [ ] **P3** Restore-from-backup wizard step (regret-undo UI)
- [ ] **P3** Background-worker preview counts for large profiles
- [ ] **P3** Background-thread snapshot create with progress
- [ ] **P3** Raster logo / favicon set

## Quick Wins

- Version bump 1.3.0 → 1.3.1 (P1, one literal).
- Promote CHANGELOG `[Unreleased]` → `[1.3.1] — 2026-05-25` (P1, doc).
- Tick ROADMAP v1.3.1 checkboxes + collapse section (P1, doc).
- `import-bookmarks --json` (P2, ~30 lines).
- Fix `test_downloads.py:119` ResourceWarning (P2, two lines).
- `docs/architecture.md` per-module refresh (P2, doc).
- Curated-map cleanup: remove or re-slug the 7 broken entries (P1,
  JSON data edits).
- Re-run `capture_screenshots.py` after a populated migration (P2,
  manual).
- Bump `_meta.last_verified` after the curated-map cleanup (P2, doc).
- `restore_snapshot` Done message could include the resolved
  source/target labels (XS, P3).

## Larger Bets

- Conflict-review modal + per-category direct-write policy + CLI flag
  + manifest schema growth (P1, L).
- Signed Windows release with provisioned cert + bundled signed ABE
  helper + raster icon set (P0, M).
- Manifest privacy redactor + "Copy diagnostics" Help-menu action
  (P2, S).
- Glean (declared metrics) + Sentry (crash) + signed appcast
  (WinSparkle) — three independent opt-in tracks, each with first-run
  dialog re-prompt on trust-model change (P3, each M).
- macOS DMG + Linux AppImage release pipeline; per-OS smoke tests;
  Apple notarization (P3, XL).
- Extension-settings allowlist for three high-value WebExtensions
  (P2, L).
- Passkey inventory + FIDO CXF alignment; export blocked until
  destination side supports (P3, L).
- "Merge mode" for cookies/history direct-write building on
  v1.3.3's policy framework (P3, L).
- Restore-from-backup wizard step closing the regret-undo loop
  on direct-write (P3, M).

## Explicit Non-Goals

- Not a Firefox Sync replacement; FoxPort migrates local state.
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
- No telemetry / crash / update without first-run consent + declared
  data dictionary + documented privacy policy.
- No obscure source browsers (Maxthon, Coc Coc, etc.) until the
  supported set has signed releases and conflict UI.
- No "merge mode" for direct-write before the skip/overwrite/backup-
  only modal ships — the safer baseline lands first.

## Open Questions

- Which Authenticode cert path does the project take? SignPath's OSS
  program is free for OSS but requires a project review; Sectigo /
  Certum commercial certs cost ~$200/year. SignPath fits an MIT
  project.
- Should the v1.3.2 signed release also gate-out unsigned local
  builds — i.e. should `crypto/abe.py` refuse to launch an unsigned
  `foxport_abe.exe`? Real trust improvement but locks out source-build
  forks.
- macOS distribution path: Apple Developer ID + notarization (~$99/
  year and some friction) or DMG-only with right-click → Open?
  Notarization is the user-facing standard.
- Linux distribution: AppImage, Flatpak, or per-distro packages?
  AppImage gives the broadest reach at the cost of bundling NSS.
- For the conflict-review modal, what should the safe default per
  category be? Proposal: `passwords=skip` (deterministic GUID match
  makes this trivially correct), `cookies=backup-only`,
  `history=backup-only`, `open_tabs=backup-only`. The user opts into
  destructive policies explicitly.
- Should `manifest.json` schema_version bump to 2 when the conflict-
  policy fields land, or stay 1 with additive optional fields?
  Additive (stay 1) is friendlier to existing consumers.
- For the curated-map AMO 401 cases (Touch-VPN, Browsec-VPN,
  Zotero-Connector): are these AMO-side restrictions on
  VPN/research-tool extensions or temporary rate limits? Worth
  inspecting the response body before deleting the entries.
- For the curated-map cleanup, do we replace removed entries with
  alternatives (e.g. Honey → Slickdeals?, Bukubrow → bookmark sync
  alternatives?) or just delete? Default proposal: delete the dead
  entries, document the policy in `_meta.description`, and let users
  contribute new entries via PRs guided by the auditor.
