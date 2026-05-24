# Project Research and Feature Plan

> Companion to `ROADMAP.md`. This file is **research output**, not an
> execution checklist — items here have evidence + acceptance criteria
> wired up so a coding agent can implement them later without redoing the
> investigation. The existing `ROADMAP.md` keeps tracking *current
> implementation status*; new items added here should be promoted into
> `ROADMAP.md` only after triage.

---

## Executive Summary

FoxPort is a PyQt6 desktop tool (+ CLI + reverse direction) that migrates
**every storable bit of browser state** between Chromium-family and
Firefox-family browsers across Windows/macOS/Linux. After v1.1.0 it
covers 9 data categories, has a 5-step wizard, DPAPI/Keychain/secret-store
decrypt paths, NSS direct-write, an App-Bound Encryption sidecar (source
only), a four-stage extension matcher with a curated map, dry-run mode, a
profile-diff CLI, and a release pipeline. **No competitor on GitHub does
all of this in one tool** — Mozilla's own ChromeProfileMigrator now ships
*worse* on Windows/Linux for passwords as of Firefox 140 (mid-2025), and
HackBrowserData is extract-only.

The strongest current shape is "the migration tool Mozilla didn't ship."
The highest-value direction is to **stop drifting against Firefox's
internal schemas**, **fix the two silent-failure features**
(`open_tabs` extracts 0 URLs from real Chrome sessions; `places.sqlite`
is 9 schema versions behind and uses a fabricated `url_hash` algorithm),
and **lean into trust** — HIBP scan, FIDO CXF passkey export, browser
snapshot bundle, opt-in Glean telemetry.

### Top 10 opportunities in priority order

1. **P0 — Fix `places.sqlite` schema drift + `url_hash` algorithm.** Verified against `mozilla-central` tip: FoxPort writes v77, Firefox is on v86; `url_hash` uses MD5 + a fabricated scheme-tag table when Firefox uses `mfbt::HashString`. History migration risks a `replaceDatabaseOnStartup` wipe on next Firefox launch.
2. **P0 — Fix `open_tabs` SNSS extractor.** Live run against a real Chrome Default profile returned 0 URLs from a 2754-byte session file. The UTF-16LE regex assumption was wrong; need a real Pickle / SNSS command parser or to read `Tabs/Tabs_*` instead.
3. **P0 — Add a test suite.** Zero `test_*.py` files exist. Every regression we just found would have been caught by one fixture-based round-trip test per migrator.
4. **P1 — Drop `PERSONAL_TOOLBAR_FOLDER` reliance in `bookmarks.html`.** `BookmarkHTMLUtils.sys.mjs` only honors that attribute on `_isImportDefaults=true` (Firefox bootstrap), not on user-triggered "Import from HTML". Toolbar items currently land in "Other Bookmarks" under a nested folder. Promote toolbar contents to the root or use the Places-API path.
5. **P1 — Filter `chrome://`, `chrome-extension://`, `edge://`, `brave://`, `about:` URLs out of bookmark + history exports.** Live diff against a real Brave profile surfaced `chrome://gpu/` in the bookmark output — Firefox can't navigate to it.
6. **P1 — `cookies.sqlite` missing `updateTime` column.** Schema v17 added it; FoxPort omits it.
7. **P1 — Diff CLI silently picks the wrong profile when the user has multiple Firefox profiles.** Live run reported "0 already in target" against a profile that actually had 10,314 bookmark rows in a sibling profile.
8. **P1 — HIBP "compromised passwords" scan during migration.** Free, no key, k-anonymity API. Bitwarden + 1Password set this user expectation; FoxPort already decrypts the cleartext.
9. **P2 — FIDO Credential Exchange Format (CXF) v1.0 passkey export.** Ratified Aug 2025; Bitwarden shipping CXP iOS 26. Chrome stores passkeys in `Web Data.webauthn_credentials`. First desktop tool to ship CXF emit wins the wedge.
10. **P2 — Browser snapshot tarball** (`.fxport`) bundling every emitted artifact + manifest + version stamps. Restore = unpack + replay. No competitor does this.

---

## Evidence Reviewed

### Local files and directories inspected
- `foxport/` — full package: `__init__.py`, `__main__.py`, `app.py`, `cli.py`, `diff.py` (40 .py files, ~7842 LOC by `wc -l`).
- `foxport/browsers/` — `detect.py`, `chromium.py`, `firefox.py`, `firefox_read.py` (per-platform browser registries + read paths).
- `foxport/crypto/` — `dpapi.py`, `keychain.py`, `nss.py`, `abe.py` (master-key recovery across Windows DPAPI/ABE, macOS Keychain, Linux libsecret/kwallet/peanuts).
- `foxport/migrate/` — `passwords.py`, `bookmarks.py`, `extensions.py`, `cookies.py`, `history.py`, `autofill.py`, `cards.py`, `search_engines.py`, `open_tabs.py`, `nss_passwords.py`, `nss_cookies.py`, `nss_history.py`.
- `foxport/migrate_reverse/` — `passwords.py`, `bookmarks.py`, `extensions.py`.
- `foxport/gui/` — `main_window.py` (355 LOC), `pages.py` (877 LOC), `widgets.py`, `theme.py`, `workers.py`, `dialogs.py`.
- `foxport/data/curated_extension_map.json` — 63 verified Chrome ID → AMO slug entries across 14 categories.
- `tools/abe_sidecar/` — `foxport_abe.cpp`, `CMakeLists.txt`, `foxport_abe.exe.manifest`, `README.md` (C++/MSVC sidecar source, **never compiled**).
- `scripts/capture_screenshots.py`, `scripts/check_curated_map.py`.
- `assets/banner.svg`, `assets/screenshots/{1-source,2-target,3-items,4-preview,5-run}.png`.
- `.github/workflows/release.yml`, `.github/workflows/ci.yml`.
- `foxport.spec` (PyInstaller).
- Docs: `README.md` (16 KB), `CHANGELOG.md` (18 KB), `ROADMAP.md` (7 KB), `CLAUDE.md` (6.4 KB), `LICENSE` (MIT).
- Memory: `~/.claude/projects/c--Users----repos/memory/foxport.md`.

### Git history range reviewed
- All 9 release commits from `1bc2151 Initial release: v0.1.0` through `a483edc v1.1.0`.
- No CI history yet (workflows added in the distribution commit but not yet exercised by `workflow_dispatch`).

### Build / test / docs / release artifacts inspected
- `requirements.txt` — PyQt6 6.8.0, cryptography 44.0.0, pywin32 308 (Windows), requests 2.32.3, lz4 4.3.3.
- `foxport.spec` (PyInstaller --onedir) — Verified `datas` list and conditional ABE sidecar bundling.
- `.github/workflows/release.yml` — `workflow_dispatch` only; builds ABE sidecar with MSVC, runs PyInstaller, creates GH release. **Never run.**
- `.github/workflows/ci.yml` — Cross-platform AST+import+CLI smoke matrix. **Never run.**
- **No tests folder, no `test_*.py`, no `pytest`/`unittest` runners anywhere.** `find . -name test_*.py` returns nothing.
- `assets/screenshots/` — 5 PNGs, real wizard captures, DPI-aware.

### External sources reviewed
- `LoginCSVImport.sys.mjs` — `searchfox.org/mozilla-central/source/toolkit/components/passwordmgr/LoginCSVImport.sys.mjs`
- `LoginHelper.sys.mjs` — same path.
- `BookmarkHTMLUtils.sys.mjs` — `toolkit/components/places/BookmarkHTMLUtils.sys.mjs`
- `CookiePersistentStorage.cpp` — `hg-edge.mozilla.org/mozilla-central/raw-file/tip/netwerk/cookie/CookiePersistentStorage.cpp` (current `COOKIES_SCHEMA_VERSION = 17`, includes `updateTime`)
- `Database.cpp` / `nsPlacesTables.h` / `Helpers.cpp` — confirms Places schema **v86 in tip** (FoxPort writes 77) and the actual `url_hash` algorithm (Mozilla `HashString`, NOT MD5).
- `FormHistory.sys.mjs` — `const DB_SCHEMA_VERSION = 5` (FoxPort writes 4).
- `SessionFile.sys.mjs`, `SessionHistory.sys.mjs` — sessionstore IOUtils path and version handling.
- `LoginStore.sys.mjs` — `kDataVersion = 3` (FoxPort matches).
- `ChromeProfileMigrator.sys.mjs`, `MigrationUtils.sys.mjs` — Mozilla's own migrator scope as of Firefox 140.
- `firefox_decrypt` (github.com/unode/firefox_decrypt) — last commit refs Firefox 144 / libnss3 3.113.
- `HackBrowserData` v1.0.0 (April 2026) — feature matrix comparison.
- `hindsight` v2026.04 — forensic-grade extractor.
- FIDO Credential Exchange Specs — `fidoalliance.org/specifications-credential-exchange-specifications/` (CXF v1.0 ratified Aug 2025).
- HIBP Pwned Passwords API v3 — `haveibeenpwned.com/API/v3`.
- AMO API v5 docs — `mozilla.github.io/addons-server/topics/api/addons.html`.
- Mozilla Glean Python SDK 67.1.0 (March 2026).

### Areas that could not be verified
- **Real Firefox 138/140 ingest** of FoxPort outputs end-to-end. The Firefox installed locally on this host is LibreWolf (Gecko-based but not authoritative); a clean Firefox 140 install would be needed to confirm `places.sqlite` direct-import behavior.
- **macOS Keychain path** — code shells to `security find-generic-password` but no macOS host available for a live test. Marked Likely.
- **Linux libsecret + kwallet** paths — same situation.
- **ABE sidecar** — never compiled. C++ source has plausible CLSID/IID values per xaitax research but is **Assumption** until a release build runs in CI.
- **Reverse-direction NSS path** — code binds `PK11SDR_Decrypt` inline; only verified parses, not that decrypted output is byte-equivalent to Firefox's exposed values.

---

## Current Product Map

### Core workflows

1. **Forward migration (Chromium → Firefox)** via 5-step wizard:
   Source → Target → Items → Preview → Run/Done.
2. **Reverse migration (Firefox → Chromium)** via CLI subcommand
   `python -m foxport.cli migrate-reverse`. GUI direction toggle on the
   Source page since v1.1.0.
3. **Profile diff** via CLI subcommand
   `python -m foxport.cli diff --source ... --target ...`.
4. **Dry-run** — checkbox on the Items step; counts and exercises decryption
   without writing anything.
5. **Direct-write** (passwords / cookies / history / open tabs) into a
   *closed* target Firefox profile via NSS or schema-from-scratch sqlite,
   with timestamped backups of the prior files.

### Existing features (9 categories, 3 reverse)

Verified against `foxport/migrate/` and `foxport/migrate_reverse/`:
passwords, bookmarks, extensions, cookies, browsing history, form
autofill, saved credit cards (CSV), search engines (OpenSearch XML),
open tabs (recovery.jsonlz4). Reverse: passwords (Chrome CSV), bookmarks
(Netscape HTML), extensions (AMO GUID → Chrome ID matcher).

### User personas

- **The browser switcher.** Decided to leave Chrome/Brave/Edge for Firefox/LibreWolf, has years of state to move, runs the tool once.
- **The sysadmin doing fleet migrations.** Uses the CLI to run dry-runs on a few profiles, then batch-processes. Cares about exit codes, logs, reproducibility.
- **The forensic / IT investigator.** Cares about decrypt fidelity more than write fidelity. May want JSON dumps, not Firefox-import files. (Not currently a first-class persona — see Opportunity #11.)
- **The privacy-leaver.** Switches *to* LibreWolf or Mullvad specifically. Cares about HIBP scan, that nothing phones home, that decrypted data doesn't leak.

### Platforms and distribution

- **Windows 10/11** — primary target. DPAPI + ABE sidecar (source-only).
- **macOS 12+** — Keychain via `security` CLI. Live ingestion not verified.
- **Linux** — libsecret / kwallet / "peanuts" plaintext fallback. Per-distro NSS path heuristics.
- Distribution: **PyInstaller --onedir** ZIP via GH Actions workflow (`workflow_dispatch`, never run yet); CLI works from a checkout via `python -m foxport.cli`.

### Important integrations, permissions, storage, data flows

- **External network calls** — Optional AMO search (`addons.mozilla.org/api/v5/addons/search/`) + AMO detail endpoint for the extension matcher. **Single User-Agent**, no rate limiting beyond `time.sleep` in the auditor script.
- **Filesystem reads** — Per-platform Chromium + Firefox profile directories, read-only after copy-to-temp.
- **Filesystem writes** — `~/Documents/FoxPort/<timestamp>_<src>__to__<dst>/` by default. Direct-write paths write into the target profile dir with timestamped backups.
- **Process execution** — `tasklist` on Windows / `ps -axo comm=` on Unix for "browser running" detection; `security find-generic-password` on macOS; `secret-tool`/`kwallet-query` on Linux; `foxport_abe.exe` sidecar via `subprocess.run` on Windows (UAC-elevated by manifest).
- **DLL loading via ctypes** — `nss3.dll`/`libnss3.dylib`/`libnss3.so` from the *target Firefox install path*.
- **Persistent state** — None. The app holds no DB, no settings file, no auth state. Output folder is the only durable state.

---

## Feature Inventory

> Maturity legend: **C**omplete · **P**artial · **H**idden · **S**tale · **B**roken · **U**ndocumented

| # | Feature | User value | Entry point | Code | Maturity | Tests/docs | Improvement |
|---|---|---|---|---|---|---|---|
| 1 | Password CSV migration (forward) | Move every saved login | Items step checkbox | `migrate/passwords.py` | **C** | None / README + CHANGELOG | Verify timestamps real-world; add HIBP scan |
| 2 | Password NSS direct-write | Skip CSV import step entirely | Items step "Direct-write passwords" checkbox | `migrate/nss_passwords.py`, `crypto/nss.py` | **P (Likely)** | None | No real-Firefox round-trip test |
| 3 | Bookmarks (Netscape HTML) | Move bookmark tree | Items step | `migrate/bookmarks.py` | **B** | None | `PERSONAL_TOOLBAR_FOLDER` ignored on user import; chrome:// URLs not filtered |
| 4 | Extension mapping (4-stage) | One-click install per Firefox equivalent | Items step | `migrate/extensions.py`, `data/curated_extension_map.json` | **C** | Auditor script `scripts/check_curated_map.py` / README | Add gecko.id → CWS for reverse; refresh map |
| 5 | Cookies (`cookies.sqlite` v17) | Move login sessions | Items step | `migrate/cookies.py` | **P (schema gap)** | None | Missing `updateTime` column |
| 6 | Cookies direct-write | One-step cookies install | Items step "Direct-write cookies" | `migrate/nss_cookies.py` | **P** | None | Same schema gap; no round-trip test |
| 7 | History (`places.sqlite` v77) | Move URL+visit log | Items step | `migrate/history.py` | **B** | None | **Schema 9 versions behind**, **`url_hash` algorithm wrong** |
| 8 | History direct-write | One-step history install | Items step | `migrate/nss_history.py` | **B** | None | Same gap; ALSO deletes `favicons.sqlite` unconditionally |
| 9 | Form autofill (`formhistory.sqlite` v4) | Move typed-string history | Items step | `migrate/autofill.py` | **P (schema gap)** | None | Should be v5 + two new tables |
| 10 | Saved cards CSV | Move credit card numbers to a password manager | Items step | `migrate/cards.py` | **C** | None / README | 1Password-shape only; consider Bitwarden JSON too |
| 11 | Search engines (OpenSearch XML) | Move custom search keywords | Items step | `migrate/search_engines.py` | **C** | None | Doesn't import on Firefox without user-clicking each file |
| 12 | Open tabs (SNSS → recovery.jsonlz4) | Restore browsing session | Items step | `migrate/open_tabs.py` | **B** | None | **Returns 0 URLs on real Chrome session — Verified live** |
| 13 | Reverse: passwords | Move logins back to Chrome | CLI `migrate-reverse` | `migrate_reverse/passwords.py` | **P** | None | CSV only; no NSS verification |
| 14 | Reverse: bookmarks | Move bookmark tree back | CLI `migrate-reverse` | `migrate_reverse/bookmarks.py` | **P** | None | Toolbar promotion via FF-only HTML attribute fails on Chrome too (Chrome looks for `H1 PERSONAL_TOOLBAR_FOLDER`) |
| 15 | Reverse: extensions | Map AMO GUID → Chrome ID | CLI `migrate-reverse` | `migrate_reverse/extensions.py` | **P** | None | Inverted map has 13 hand-curated GUIDs; rest fall through to CWS text search |
| 16 | Profile diff | "What will change?" preview | CLI `diff` | `diff.py` | **P** | None | Silently picks wrong profile when user has multiple FF profiles (live evidence) |
| 17 | Dry-run | Test without writes | Items step checkbox | All migrators accept `dry_run=` | **C** | None | No "dry-run banner" persists into the Run page |
| 18 | Drag-and-drop manual source | Migrate from a tarball / external drive | Source step "Drop a profile folder" tile | `gui/pages.py:SourcePage._on_drop` | **B** | None | Path is stored in `ctx.dropped_source_path` but **never read by migrators** — feature is wired up to the UI but disconnected from the pipeline |
| 19 | Direction toggle (forward/reverse) | One GUI for both directions | Source step | `gui/pages.py:_set_direction` | **C** | None / CHANGELOG | Items step disables 5 categories in reverse — make a "what's not yet supported" tooltip explicit |
| 20 | Browser-running detection | Stale-data warning | Source step banner | `browsers/detect.py:is_chromium_running` | **C** | None | Uses tasklist; consider `psutil` for richer signal |
| 21 | Per-row password preview / filter | Pick what's exported | Items step "Customize…" | `gui/dialogs.py:PasswordPreviewDialog` | **C** | None | Shows plaintext passwords — no "hide passwords" toggle by default |
| 22 | Per-folder bookmark filter | Skip noisy folders | Items step "Customize…" | `gui/dialogs.py:BookmarkFilterDialog` | **C** | None | Doesn't filter Chrome-internal URL leaves |
| 23 | Already-installed detection | Don't re-install AMO add-ons | extensions report | `migrate/extensions.py` + `read_installed_firefox_extensions` | **C** | None | Strikes through but doesn't *hide* — user clicks them anyway |
| 24 | App-Bound Encryption sidecar | Recover Chrome 127+ keys | `foxport_abe.exe` (auto-invoked) | `crypto/abe.py`, `tools/abe_sidecar/foxport_abe.cpp` | **P (source only)** | None | Never compiled or signed; sidecar requires admin |
| 25 | Curated-map auditor | Find dead AMO entries | `scripts/check_curated_map.py` | same | **C** | None | Not wired to a CI cron schedule |
| 26 | Screenshot capture | Re-shoot README assets | `scripts/capture_screenshots.py` | same | **C** | None | Hard-coded window size |

### Hidden / undocumented behavior

- **`FOXPORT_NSS_PATH` environment variable** — undocumented in README, only mentioned in `crypto/nss.py` docstring. Override for portable Firefox installs.
- **`File` menu → "Open output folder"** — wired but only mentioned in About-dialog tour.
- **Status bar messages** — only mentioned in CLAUDE.md, not user docs.

### Stale / dead code

- `gui/pages.py:SourcePage._on_drop` stores the dropped path but no migrator reads `ctx.dropped_source_path`. (Item #18 above.)
- `migrate_reverse/extensions.py:AMO_GUID_TO_CHROME` contains a `"{446900e4-…}"` placeholder entry with empty string value (`{"{446900e4-…}": ""}`) — vestigial demonstration row that never gets used productively.
- `gui/theme.py:STYLESHEET` uses a `data:image/svg+xml` checkmark URL for `QCheckBox::indicator:checked` that **Qt renders as a blank background fill** (PyQt6 QSS doesn't render `image: url(data:...)` reliably). Live screenshot confirms: filled lavender square with no glyph. Cosmetic.

---

## Competitive and Ecosystem Research

> Sourced from a fresh competitive landscape pass (May 2026). See "Evidence Reviewed" above.

### moonD4rk/HackBrowserData

- 14.1k stars, v1.0.0 April 29 2026, actively maintained. CLI only.
- **Has that FoxPort doesn't:** Safari extraction, **downloads** + **localStorage** + **sessionStorage**, 15+ Chromium variants (360, QQ, Sogou, etc.), ABE handling in core not a sidecar.
- **Lacks vs FoxPort:** Entire write side. No Firefox target. No GUI. No reverse direction. No extension matching. No `cookies.sqlite` synthesis, no `places.sqlite` write.
- **Lift:** downloads support (Chromium `History.downloads` table), localStorage migration as a v1.3 candidate.

### Mozilla `ChromeProfileMigrator.sys.mjs` (Firefox 140 source)

- Continuously updated as part of Firefox.
- **Has that FoxPort doesn't:** Hooks into `about:welcome`. Imports search-engine **keywords**, **toolbar ordering**, **zoom levels**, **pop-up settings**, **geolocation permissions**.
- **Lacks vs FoxPort:** As of **Firefox 140 (mid-2025)**, Mozilla **disabled automated Chrome password import on Windows and Linux** — the wizard demands a CSV. FoxPort's NSS direct-write + DPAPI/Keychain decrypt is **strictly more capable** than the shipping migrator on those OSes. No ABE handling at all (zero references to `IElevator`/`v20`/`BrowserDecryptor` in `ChromeProfileMigrator.sys.mjs`). No reverse direction.
- **Lift:** Mozilla's `MigrationUtils.resourceTypes` enum: `PAYMENT_METHODS (0x0100)` is a published category — FoxPort writes Saved-cards CSV but could also emit a Firefox `formautofill` Storage JSON the wizard would understand.

### unode/firefox_decrypt

- Active (Firefox 144 / libnss3 3.113 supported).
- **Has that FoxPort doesn't:** Thunderbird, Waterfox, SeaMonkey profile support. `pass` (passwordstore.org) and JSON exporters.
- **Lift:** Thunderbird profile detection is a low-cost add; same `profiles.ini` parsing as Firefox.

### obsidianforensics/hindsight (v2026.04)

- Forensic-grade extractor.
- **Has that FoxPort doesn't:** **Cache records**, **downloads**, **full `Preferences` JSON** dump.
- **Lift:** downloads table import to Firefox `places.sqlite.moz_annos` (downloads-as-annotated-history).

### KeePassXC / Bitwarden / 1Password

- KeePassXC issue #11363 (CXP support) is still open targeting v2.8.0. Bitwarden shipped CXP iOS 26 in May 2026 — first major vendor.
- **Lift:** FoxPort emits 1Password CSV today. Adding **KeePassXC `.kdbx` direct write via `pykeepass`** and **Bitwarden JSON** would close the password-manager triangle. CXF v1.0 emit (passkeys) is a future-proof play.

### ArchiveBox

- **Lift the pattern, not the feature.** ArchiveBox accepts **Netscape HTML / Pocket / Pinboard / Instapaper / Shaarli / Delicious / Wallabag / RSS / JSON / CSV / plaintext** via pluggable `--parser`. FoxPort could similarly accept **Pocket / Pinboard JSON** as a *source* alongside Chromium — broadens the inbound side without changing the outbound (Firefox).

### What this project should intentionally avoid

- **Don't become a forensic dumper.** Hindsight + HackBrowserData own that space and FoxPort would lose its identity.
- **Don't bundle a custom password manager.** Stay an *interop* tool. Emit standard formats (CSV, JSON, KDBX, CXF) — let users pick their store.
- **Don't ship telemetry without opt-in.** A Firefox-adjacent tool that phones home would be self-defeating. (See "Glean opt-in" in Larger Bets.)
- **Don't try to keep `places.sqlite` schema drift in lock-step with Firefox forever.** Long-term the Places-API-via-WebExtension approach is more sustainable than the schema-from-scratch path.

---

## Highest-Value New Features

### NF-1 — HIBP Pwned Passwords scan during migration

- **User problem solved:** Bitwarden / 1Password trained users to expect a compromised-password report at import time. FoxPort decrypts cleartext on the way through — perfect surface.
- **Evidence:** HIBP API v3 free, no key, k-anonymity SHA-1 prefix lookup ([haveibeenpwned.com/API/v3](https://haveibeenpwned.com/API/v3)). Live confirmation that FoxPort already has cleartext at `migrate/passwords.py:_decrypt_rows`.
- **Proposed behavior:** Items-step opt-in checkbox "Check passwords against HIBP". After decrypt, hash each password to SHA-1, take first 5 chars, request `api.pwnedpasswords.com/range/<prefix>`, scan returned suffix list for the remaining 35 chars. Emit `compromised-passwords.txt` listing every match (URL + username, NOT the password) alongside the standard CSV. Show count on the Done screen.
- **Implementation areas:** `migrate/passwords.py` (after decrypt, before write), new `crypto/hibp.py`, Items wizard step checkbox.
- **Data model:** No persistent change. Per-run report file.
- **Risks/edge cases:** Network failure shouldn't block migration — degrade to "skipped". User must explicitly opt in (privacy). Cache prefix→suffix-list within a session to avoid re-querying for shared prefixes.
- **Verification plan:** Mock the HIBP endpoint in a unit test; manual run against a synthesized profile containing `password123` (always returns hits).
- **Complexity:** S. **Priority:** P1.

### NF-2 — FIDO Credential Exchange Format (CXF) v1.0 passkey export

- **User problem solved:** Users with WebAuthn passkeys in Chrome can't move them today. Apple iOS 26 + Bitwarden ship CXP; desktop tooling is the gap.
- **Evidence:** FIDO CXF v1.0 ratified Aug 2025 ([fidoalliance.org/specifications-credential-exchange-specifications/](https://fidoalliance.org/specifications-credential-exchange-specifications/)). Chrome stores passkeys in `Web Data.webauthn_credentials` (column schema visible in Chromium source). Firefox 138+ supports passkey auth but lacks an import path.
- **Proposed behavior:** New `migrate/passkeys.py` reads `Web Data.webauthn_credentials`, emits a CXF v1.0 JSON file the user imports into Bitwarden / KeePassXC / Apple Passwords / future-Firefox.
- **Implementation areas:** New module, new Items checkbox, new CLI item `passkeys`.
- **Risks/edge cases:** Chrome `webauthn_credentials.private_key` is encrypted with the same AES key — works automatically once decrypted. Schema may drift; pin to current Chrome version and test fixture-based.
- **Verification plan:** Test fixture with a known Web Data file (anonymized). CXF JSON validates against the schema published by FIDO.
- **Complexity:** M. **Priority:** P2.

### NF-3 — Browser snapshot (`.fxport`) bundle

- **User problem solved:** Users want to back up their browser state once and restore later (after an OS reinstall, on a new machine, to send to themselves). No competitor does this.
- **Evidence:** Pattern from Apple Migration Assistant (full Time Machine restore), Bitwarden export, Mozilla Sync. FoxPort already produces a single output folder per run with every artifact — formalizing it as a `.fxport` (zip) bundle with a `manifest.json` versioning each artifact is a free win.
- **Proposed behavior:** A new "Save snapshot…" action on the Done page that zips the output dir into `<source>_<timestamp>.fxport`. A new CLI `python -m foxport.cli restore --snapshot foo.fxport --target Firefox/default-release` un-zips and applies every artifact via the direct-write paths.
- **Implementation areas:** `foxport/snapshot.py`, CLI subcommand `restore`, GUI button on Done page.
- **Risks/edge cases:** Snapshot contains cleartext passwords — encrypt with a user-supplied passphrase (PBKDF2 + AES-256-GCM) when "Encrypt" is checked.
- **Verification plan:** Round-trip test: snapshot a fixture, restore into a clean target dir, diff outputs.
- **Complexity:** M. **Priority:** P2.

### NF-4 — Downloads migration

- **User problem solved:** Users with hundreds of downloads in their browser history lose them on migration. Hindsight surfaces this data; HackBrowserData reads it; FoxPort skips it.
- **Evidence:** Chromium `History.downloads` table is well-known; Firefox stores downloads as annotated `moz_places` entries (`moz_annos.anno_attribute_id = "downloads/destinationFileURI"`).
- **Proposed behavior:** New `migrate/downloads.py`. Items checkbox. Writes annotations into the `places.sqlite` already being emitted by history migration.
- **Implementation areas:** New module, Items checkbox, CLI item `downloads`. **Depends on history-migration fix (P0 above) being done first** since it writes to the same DB.
- **Risks/edge cases:** Local file URIs reference paths that won't exist on the target machine — flag them but include.
- **Verification plan:** Test fixture; query the resulting `places.sqlite` for `moz_annos` entries.
- **Complexity:** S. **Priority:** P2.

### NF-5 — History time-range filter

- **User problem solved:** Spring-cleaning migrators want the last 90 days, not 7 years of crufty URLs.
- **Evidence:** Hindsight has this; the community explicitly asks for it on Codidact and Stack Exchange threads about Firefox imports.
- **Proposed behavior:** New "Customize…" button on the History row (mirrors Passwords / Bookmarks). Dialog with two date pickers + "last N days" presets. Filter rows in `migrate/history.py:_iter_chromium_history` by `last_visit_time`.
- **Implementation areas:** `gui/dialogs.py` (new `HistoryFilterDialog`), `gui/pages.py:ItemsPage._customize_history`, `migrate/history.py` (date-range param).
- **Risks/edge cases:** Visits older than the cutoff for a URL whose latest visit is within the cutoff — keep the URL, drop the older visits.
- **Verification plan:** Test fixture with known timestamps.
- **Complexity:** S. **Priority:** P2.

### NF-6 — Brave / Vivaldi / Edge as a *target*

- **User problem solved:** Reverse direction currently only writes Chrome-import-format files; users explicitly switching from Firefox to Brave/Vivaldi/Edge would want native import.
- **Evidence:** All three are Chromium with the same SQLite schemas as Chrome. Reverse code already exists for Chrome target; parameterizing the path is mechanical.
- **Proposed behavior:** Reverse-direction Target tile picker becomes generic — pick any Chromium-family target, FoxPort writes Brave-compatible CSV (same shape as Chrome's import).
- **Implementation areas:** `gui/pages.py:TargetPage._render_for_direction` already handles this; verify CSV format identity with the three browsers.
- **Risks/edge cases:** Some Chromium forks (Yandex, Opera) bundle their own bookmark/CSV import — verify.
- **Verification plan:** Manual test against each target.
- **Complexity:** S. **Priority:** P2.

### NF-7 — Glean telemetry (strictly opt-in)

- **User problem solved:** No usage signal today — can't tell which categories users actually pick, what fails most often.
- **Evidence:** Mozilla Glean Python SDK 67.1.0 (March 2026). Standard Mozilla-ecosystem solution. Firefox-adjacent tool with Mozilla-native telemetry is a credibility signal.
- **Proposed behavior:** First-run dialog asks "Send anonymous usage metrics to Mozilla Glean?" — default OFF. If enabled, send: which categories the user ticked, run duration per category, decrypt-failure counts (no URLs/usernames), Python/OS/Qt version. Honor `--no-telemetry` CLI flag unconditionally.
- **Implementation areas:** New `foxport/telemetry.py`, first-run dialog on `gui/main_window.py`.
- **Risks/edge cases:** Glean wants `allow_multiprocessing=False` for PyInstaller builds. Document opt-out clearly in README.
- **Risks/edge cases (privacy):** Never send URLs, usernames, password hashes, profile names, or file paths. Only counts and timings.
- **Verification plan:** Manual debug-mode run; inspect emitted metrics.
- **Complexity:** M. **Priority:** P3.

### NF-8 — Crash reporting via Sentry

- **User problem solved:** Silent crashes today; the user just sees the GUI vanish.
- **Evidence:** sentry-sdk has first-class PyQt6 support; self-hosted GlitchTip/Bugsink alternatives exist.
- **Proposed behavior:** Same opt-in dialog as NF-7. On unhandled exception, send a stack trace + Python/OS/Qt version (no user data) to a `foxport.io`-controlled Sentry DSN.
- **Implementation areas:** `foxport/app.py` (install handler), `foxport/telemetry.py`.
- **Complexity:** S. **Priority:** P3.

### NF-9 — Pocket / Pinboard / OPML bookmark *input*

- **User problem solved:** Users with externally-stored bookmark sets want to import them into Firefox via FoxPort's already-polished pipeline.
- **Evidence:** ArchiveBox's pluggable `--parser` model; users will mention "I have a Pinboard export from 2018".
- **Proposed behavior:** New "Manual source" tile already exists in the GUI; wire it to accept Pocket JSON, Pinboard JSON, OPML, and Netscape HTML in addition to Chromium User Data dirs.
- **Implementation areas:** `gui/pages.py:SourcePage._on_drop` — currently dead code (item #18); a new `foxport/import_/` package with one module per source format.
- **Complexity:** M. **Priority:** P2.

### NF-10 — Auto-update via WinSparkle / Sparkle

- **User problem solved:** Users on v0.4 still don't know v1.1 exists.
- **Evidence:** fman.io's PyQt Sparkle guide is the canonical 2026 reference; `pywinsparkle` PyPI package wraps WinSparkle for Windows; macOS Sparkle framework loads via pyobjc.
- **Proposed behavior:** Check `foxport.io/appcast.xml` on launch (or once-per-week). Show a non-modal banner when an update is available. EdDSA-signed updates.
- **Implementation areas:** `foxport/updater.py`, `gui/main_window.py` (banner widget on launch).
- **Risks/edge cases:** Don't auto-update without user consent; show the changelog before installing.
- **Complexity:** L. **Priority:** P3.

---

## Existing Feature Improvements

### EI-1 — `places.sqlite` schema gap (v77 → v86) and `url_hash` algorithm bug

- **Current behavior:** `migrate/history.py:_FIREFOX_PLACES_SCHEMA` declares `PRAGMA user_version = 77` and a column set frozen at Firefox ~115. `_url_hash` builds the upper 16 bits from a hard-coded `{http: 130, https: 131, ftp: 129, file: 128, place: 132}` table and the lower 48 bits from `MD5(url)[:6]`.
- **Problem:** Verified against `mozilla-central` tip (`toolkit/components/places/Database.cpp`, `nsPlacesTables.h`, `Helpers.cpp`): current Places schema is **v86**, not 77. Missing columns: `description`, `preview_image_url`, `site_name`, `alt_frecency`, `recalc_alt_frecency` on `moz_places`; `alt_frecency`, `recalc_alt_frecency`, `block_until_ms`, `block_pages_until_ms` on `moz_origins`; `source`, `triggeringPlaceId` on `moz_historyvisits`. **`url_hash` algorithm is wrong** — Firefox uses `mfbt::HashString` (a non-cryptographic mix, see `mfbt/HashFunctions.h`) for both the scheme prefix and the URL, **not** a fixed integer table + MD5.
- **Recommended change:** (a) bump the schema literal to 86 and add every missing column; or (b) drop schema-from-scratch entirely and switch to a Places-API-via-headless-Firefox approach (long term). Port `HashString` from `mfbt/HashFunctions.h` (≈ 30 lines) to a new `foxport/crypto/mozhash.py` and use it everywhere.
- **Code locations:** `foxport/migrate/history.py:_FIREFOX_PLACES_SCHEMA`, `_url_hash`, `_SCHEME_PREFIX_TAG`.
- **Backward compatibility:** Users with a `places.sqlite` already imported via FoxPort v0.3–v1.1 may have working profiles where AwesomeBar search silently doesn't find imported entries. Migration: re-run import after upgrading.
- **Verification:** Write a test fixture; open the produced `places.sqlite` with a clean Firefox 138 install; navigate to `about:profiles` → "Show in Finder"; relaunch Firefox; verify AwesomeBar finds entries.
- **Complexity:** L. **Priority:** P0.

### EI-2 — `open_tabs` SNSS extractor returns zero URLs on real Chrome data

- **Current behavior:** `migrate/open_tabs.py:_extract_urls` scans the raw SNSS bytes with a UTF-16LE regex for URL-shaped substrings.
- **Problem:** Verified live against a real Chrome `Default/Sessions/Session_13423521964202657` (2754 bytes): the extractor returns **0 URLs**. The file has 4-byte command headers visible (`0d 00 0f 08`, `0d 00 1f 08`, etc.) but no inline URL strings in either UTF-8 or UTF-16LE. Chrome may store URLs in companion `Tabs/Tabs_<id>` files, or pickle the URL field with a length prefix that breaks the regex assumption.
- **Recommended change:** (a) Read `Tabs/Tabs_*` files as well — Chrome 100+ splits tabs from sessions. (b) Write a real SNSS command parser following the protocol in `chrome/browser/sessions/session_service_commands.cc` (Chromium source) — each command is `[4-byte size][1-byte command_id][payload]`, and `SerializedNavigationEntry` payloads have a Pickle-formatted `[url_len][url][title_len][title]` structure.
- **Code locations:** `foxport/migrate/open_tabs.py:_URL_UTF16_RE`, `_latest_session_file`, `_extract_urls`.
- **Backward compatibility:** Output file remains `recovery.jsonlz4` — same format Firefox expects.
- **Verification:** Live run against a real Chrome profile reports >0 URLs. Manual cross-check against `chrome://history/?q=<recent>`.
- **Complexity:** M. **Priority:** P0.

### EI-3 — `bookmarks.html` toolbar promotion silently broken

- **Current behavior:** `migrate/bookmarks.py` tags the toolbar root with `<H3 PERSONAL_TOOLBAR_FOLDER="true">`.
- **Problem:** Verified against `BookmarkHTMLUtils.sys.mjs`: the attribute is **only honored on `_isImportDefaults=true`** (Firefox's first-run default-bookmark bootstrap), not on user-triggered Library → "Import Bookmarks from HTML". Toolbar bookmarks currently land in "Other Bookmarks" under a folder named "Bookmarks Toolbar".
- **Recommended change:** Stop relying on the attribute. After import, surface a "Move imported toolbar items to Bookmarks Toolbar" button on the Done page that uses Firefox's Bookmarks Library + drag-and-drop semantics (i.e., document the manual step). Or — once history direct-write is fixed (EI-1) — populate `moz_bookmarks` directly with `parent = 3` (the toolbar root's ID).
- **Code locations:** `foxport/migrate/bookmarks.py:_emit_folder`, `README.md` (current screenshots say "toolbar landed correctly").
- **Complexity:** S (docs change) / M (direct-write path).
- **Priority:** P1.

### EI-4 — `cookies.sqlite` missing `updateTime` column (v17 schema gap)

- **Current behavior:** `migrate/cookies.py:_FIREFOX_COOKIES_SCHEMA` declares all v17 columns *except* `updateTime INTEGER` (added in the v16→v17 bump).
- **Problem:** Verified against `netwerk/cookie/CookiePersistentStorage.cpp` tip. Firefox 138 will detect the column gap and treat the DB as needing migration; in some code paths this triggers a drop-and-recreate.
- **Recommended change:** Add `updateTime INTEGER` to the schema. Default `NULL` or `creationTime` — both accepted.
- **Code locations:** `foxport/migrate/cookies.py:_FIREFOX_COOKIES_SCHEMA`, the `INSERT OR REPLACE INTO moz_cookies` call (just add a 14th column).
- **Backward compatibility:** None — Firefox auto-migrates.
- **Verification:** `sqlite3 cookies.sqlite '.schema moz_cookies'` shows `updateTime`.
- **Complexity:** S. **Priority:** P1.

### EI-5 — `formhistory.sqlite` v4 → v5 with new `moz_sources` tables

- **Current behavior:** `migrate/autofill.py` writes `PRAGMA user_version = 4`.
- **Problem:** `FormHistory.sys.mjs` is on v5 (added `moz_sources` + `moz_history_to_sources` junction). Firefox 138 auto-migrates but ships with the wrong assumption on first launch (the imported data wasn't recorded as added by any extension).
- **Recommended change:** Bump to v5, add empty `moz_sources` + `moz_history_to_sources` tables.
- **Code locations:** `foxport/migrate/autofill.py:_FIREFOX_FORMHISTORY_SCHEMA`.
- **Complexity:** S. **Priority:** P2.

### EI-6 — Bookmark + history exports include `chrome://`, `chrome-extension://`, `edge://`, `about:` URLs

- **Current behavior:** Live diff against a real Brave Default profile listed `chrome://gpu/` among the new bookmark URLs.
- **Problem:** Firefox can't navigate to `chrome://*` URLs. The bookmark appears, the user clicks, nothing happens.
- **Recommended change:** Filter URLs whose scheme is in `{chrome:, chrome-extension:, edge:, brave:, opera:, vivaldi:, yandex:, about:}` from bookmark + history + open-tab outputs *by default*. Add a "Migrate browser-internal URLs anyway" toggle for the rare case.
- **Code locations:** `foxport/migrate/bookmarks.py:_emit_url`, `foxport/migrate/history.py:_iter_chromium_history`, `foxport/migrate/open_tabs.py:_extract_urls`.
- **Complexity:** S. **Priority:** P1.

### EI-7 — `diff` CLI silently picks the wrong profile when target has multiple

- **Current behavior:** `cli._find_firefox` does substring matching. Live evidence: user has LibreWolf profiles `default-default-1 (10314 bookmarks)`, `default (no places.sqlite)`, `default-default (10314 bookmarks)`. The diff against `--target "LibreWolf/default"` matches the EMPTY second profile and reports "0 already in target" for 4935 bookmarks.
- **Problem:** Substring "default" matches all three; the substring-fallback picks the first.
- **Recommended change:** When more than one profile matches, refuse and print the full list. Require exact `<Browser>/<Profile>` match.
- **Code locations:** `foxport/cli.py:_find_firefox`, `_find_chromium`.
- **Backward compatibility:** Scripts using ambiguous names break loudly — desirable.
- **Complexity:** S. **Priority:** P1.

### EI-8 — Drag-and-drop "Drop a profile folder here" tile is dead code

- **Current behavior:** `SourcePage._on_drop` stores the dropped path in `ctx.dropped_source_path` and updates the banner. No migrator reads `dropped_source_path`.
- **Problem:** Users will drag, see "Manual source selected: …", click Next, and find the migration runs against whatever was previously selected (or fails). Confidence-destroying.
- **Recommended change:** Wire the dropped path into a synthetic `ChromiumProfile` (or `FirefoxProfile` if the path looks like a Gecko profile dir) and use it as the source.
- **Code locations:** `gui/pages.py:SourcePage._on_drop`, `MigrationContext.dropped_source_path`.
- **Complexity:** S. **Priority:** P1.

### EI-9 — No master-password retry path in the GUI

- **Current behavior:** `MainWindow._start_migration` (reverse mode) tries to open NSS, catches `NSSError` containing "master password", prompts once, retries. **If the prompt password is also wrong, the migration aborts silently with a generic "FATAL" log entry.**
- **Problem:** Users mistype passwords; no second-chance prompt.
- **Recommended change:** Loop up to 3 attempts with explicit error messaging on each.
- **Code locations:** `gui/main_window.py:_start_migration`.
- **Complexity:** S. **Priority:** P2.

### EI-10 — Already-installed extensions show in the install page but aren't auto-skipped

- **Current behavior:** `migrate/extensions.py:_build_html` adds a `row-installed` CSS class + strikethrough. The "Install on Firefox" link still renders.
- **Problem:** Users will click "Install" out of habit, opening a redundant AMO page for the same extension.
- **Recommended change:** Hide already-installed rows by default; show a "+N already installed (click to expand)" disclosure at the bottom of the report.
- **Code locations:** `migrate/extensions.py:_build_html`.
- **Complexity:** S. **Priority:** P2.

### EI-11 — Password preview dialog shows plaintext by default

- **Current behavior:** `PasswordPreviewDialog` populates the table with plaintext passwords for every row, with a banner that says "close this dialog before walking away".
- **Problem:** Shoulder-surfing risk. A "•••••" mask with per-row "show" toggle is the password-manager norm.
- **Recommended change:** Mask the password column by default. Add a single "Show all" / per-row "👁" affordance.
- **Code locations:** `gui/dialogs.py:PasswordPreviewDialog._populate`.
- **Complexity:** S. **Priority:** P2.

### EI-12 — `favicons.sqlite` deletion is unconditional in history direct-write

- **Current behavior:** `migrate/nss_history.py:write_history_into_target` calls `favicons.unlink()` whenever it exists.
- **Problem:** User may have spent years building up favicons. The history direct-write wipes them with no backup.
- **Recommended change:** Move `favicons.sqlite` to `favicons.foxport-backup-<mtime>.sqlite` like the other backups, not delete.
- **Code locations:** `migrate/nss_history.py:write_history_into_target`.
- **Complexity:** S. **Priority:** P1.

### EI-13 — Curated extension map has a known-bad placeholder entry

- **Current behavior:** `migrate_reverse/extensions.py:AMO_GUID_TO_CHROME` contains `"{446900e4-…}": ""` — a literal ellipsis-in-GUID placeholder that's never matched and clutters the file.
- **Recommended change:** Delete the placeholder. Audit the rest of `AMO_GUID_TO_CHROME` — some entries (`"Tampermonkey@example.com"`) look fabricated; verify against AMO.
- **Code locations:** `foxport/migrate_reverse/extensions.py`.
- **Complexity:** S. **Priority:** P2.

### EI-14 — `gui/theme.py` checkbox checkmark glyph never renders

- **Current behavior:** QSS sets `image: url("data:image/svg+xml;utf8,<svg …/>")` for `QCheckBox::indicator:checked`. Live screenshots show a solid lavender square with no glyph.
- **Problem:** PyQt6 QSS does not reliably render `image: url(data:…)`. Either inline as a Qt resource (compile a `.qrc` to a Python module) or fall back to drawing a glyph in Python on `paintEvent`.
- **Recommended change:** Compile a small `.qrc` with a check icon, load via `Q_INIT_RESOURCE`, reference as `qrc:/foxport/icons/check.svg`. Or accept the colored-square indicator as deliberate (low effort, slightly worse UX).
- **Code locations:** `foxport/gui/theme.py`.
- **Complexity:** S. **Priority:** P3.

### EI-15 — Reverse-direction extension matcher has minimal coverage

- **Current behavior:** `AMO_GUID_TO_CHROME` holds 13 hand-curated entries; everything else falls through to a Chrome Web Store text-search URL.
- **Problem:** Forward direction has 63 curated entries; reverse has 13. Asymmetric.
- **Recommended change:** During curated-map maintenance, also harvest the AMO GUID for each entry (via the AMO detail API) and persist it back into a single bidirectional JSON.
- **Code locations:** `foxport/data/curated_extension_map.json`, `foxport/migrate/extensions.py`, `foxport/migrate_reverse/extensions.py`.
- **Complexity:** M. **Priority:** P2.

### EI-16 — `scripts/check_curated_map.py` exit code doesn't fail CI on stale entries

- **Current behavior:** `return 1 if broken else 0` — stale (last_updated > 24mo) entries do NOT exit non-zero.
- **Recommended change:** Add `--strict-stale` flag that makes stale entries fail too, separate from `is_disabled`. Wire to a monthly GitHub Action scheduled run.
- **Code locations:** `scripts/check_curated_map.py:main`, new `.github/workflows/curated-map-audit.yml`.
- **Complexity:** S. **Priority:** P3.

### EI-17 — `nss.py` lacks decrypt; `firefox_read.py` binds it inline at runtime

- **Current behavior:** `crypto/nss.py:NSSLibrary` binds `NSS_Init`, `PK11SDR_Encrypt`, etc. but **not** `PK11SDR_Decrypt`. `firefox_read.py` does `dec = session._lib.handle.PK11SDR_Decrypt` and configures argtypes inline (accessing the private attribute).
- **Problem:** Two-way coupling and SLF001 access. Tests can't easily mock.
- **Recommended change:** Add `PK11SDR_Decrypt` bind + `NSSSession.decrypt()` method to `nss.py`. `firefox_read.py` uses the public API.
- **Code locations:** `foxport/crypto/nss.py:load_nss`, `NSSSession`, `foxport/browsers/firefox_read.py:read_firefox_logins`.
- **Complexity:** S. **Priority:** P2.

---

## Reliability, Security, Privacy, and Data Safety

### Bugs / risks found

- **Schema drift on `places.sqlite` and `formhistory.sqlite`** (EI-1, EI-5) — risks Firefox triggering `replaceDatabaseOnStartup` and discarding the import.
- **Open-tabs feature broken on real data** (EI-2) — feature ships but doesn't work.
- **Toolbar bookmark promotion silently fails** (EI-3) — users assume migration worked, finds toolbar empty.
- **`favicons.sqlite` wiped without backup** (EI-12) — data loss.
- **Drag-and-drop tile dead-ended** (EI-8) — confidence-destroying false success.
- **Diff CLI substring matching too permissive** (EI-7) — silent wrong-profile selection.

### Missing guardrails

- **No checksum / digest** on emitted files. A re-run produces different files; users can't verify "is this the same export I ran yesterday?"
- **No "migration log"** persisted per-run beyond the in-memory `QPlainTextEdit`. Closing the window loses the log.
- **No "this category was skipped because X"** explicit status — the user has to read the log to find out passwords failed.
- **`passwords.csv` is plaintext on disk** with no warning beyond a README sentence. Should default to encrypted-CSV (passphrase via Qt prompt) with a "decrypt to plain CSV" option.
- **AMO API requests have no per-host caching across runs** — multiple migrations re-fetch the same extension data.
- **No rate-limit handling on AMO** — `time.sleep(0.5)` in the auditor script; the live extension matcher has none.

### Permission / network / filesystem concerns

- **`pywin32`/`win32crypt`** — already only used for DPAPI on Windows, gated by `sys.platform`. Safe.
- **`subprocess.run(["security", ...])`** on macOS — invokes a user-prompt-issuing system tool. Acceptable.
- **`subprocess.run(["secret-tool", ...])`** on Linux — same.
- **`os.startfile(...)`** on Windows for "Reveal in Explorer" — opens user's chosen path. Validated against the output dir; safe.
- **No path-traversal sanitization** in `make_export_dir`. If `source.label` contains `..`, the export dir could escape `~/Documents/FoxPort/`. Low risk (`source.label` comes from `_CHROMIUM_SPECS` registry) but worth a `os.path.normpath` + bounds check.
- **ABE sidecar** runs elevated via embedded manifest. Source code reviewed but **never compiled or signed**. Until the binary exists, FoxPort's ABE handling is *aspirational*.

### Recovery and rollback needs

- **Direct-write paths back up files** to `*.foxport-backup-<mtime>.*` — verified. But there's no automated "restore last backup" command. Add `python -m foxport.cli restore-backup --target Firefox/default-release --category cookies` that copies the most recent `.foxport-backup-*.sqlite` back over the live file.
- **Snapshot bundle** (NF-3) would solve this generically.

### Logging / diagnostics needs

- **No log-to-file**, only in-memory `QPlainTextEdit`. Hard to diagnose issues users report.
- **No `--verbose` / `--debug`** CLI flag. The CLI has the same output regardless.
- **No structured JSON output** for the CLI. Pipeline consumers can't reliably parse.

---

## UX, Accessibility, and Trust

### Onboarding gaps

- **No first-run dialog** explaining what FoxPort will and won't do. Users meet a profile picker with zero context.
- **No "open the import folder when done"** auto-action; user has to click the button.
- **No "what's next" hand-off** — after the Done page, the user is on their own to find `about:logins` → Import.

### Empty / loading / error / disabled states

- **No empty state for the Source page** beyond a banner — if zero profiles are detected, the page is mostly blank. Add a help illustration + "How FoxPort detects profiles" link.
- **No loading shimmer / spinner** during the initial detection scan. The status bar updates but the page sits empty for 200-800 ms.
- **Error states aren't actionable** — `FATAL: <exception>` is the worst UX outcome. Should suggest "Click here to open the log folder".
- **Disabled categories in reverse mode** get a tooltip but no in-line "not yet supported" badge. A muted "Coming in v1.2" pill would set expectations.

### Destructive / irreversible actions

- **Direct-write checkboxes** carry the warning "close Firefox first" but no confirm dialog at submit time. A "You're about to overwrite cookies.sqlite in Firefox/default-release. A backup will be saved as `cookies.foxport-backup-…sqlite`. Continue?" would catch hasty clicks.
- **Migration auto-starts** the moment the user hits "Run Migration" on Preview. No "are you sure?" confirmation. Acceptable given the dry-run option, but a single confirmation would not hurt.

### Settings clarity

- **No settings page at all.** Output directory is per-wizard; preferences (default dry-run, mask passwords by default, allow online AMO lookup, telemetry opt-in) don't exist.
- **`FOXPORT_NSS_PATH` env var is undocumented** outside the source comment.

### Accessibility

- **No keyboard navigation testing.** Wizard tabs work via Qt default behavior, but Tile widgets aren't focusable (no `setFocusPolicy(StrongFocus)` in `gui/widgets.py:Tile`). Keyboard-only users can't pick a source.
- **Tiles use mouse cursor only** — no `aria-role` equivalent, no announceable selection. Screen readers will read them as generic frames.
- **Color contrast** — Catppuccin Mocha foreground/background ratios meet WCAG AA, but `OVERLAY0` (`#6c7086`) on `BASE` (`#1e1e2e`) is ~3.5:1 — borderline for normal text. Disabled-step rail items will be hard to read for users with low vision.
- **High-contrast / system theme integration** — none. Catppuccin Mocha is hard-coded; users on Windows High Contrast mode get unstyled QSS.

### Microcopy and trust signals

- **"Migration complete"** on the Done page — fine. **"Open output folder"** — should be the primary action, not buried behind "Open passwords.csv".
- **No "FoxPort never modifies the source browser"** statement on the Source page. The README says it; the GUI doesn't.
- **No version stamp on the wizard** (the SVG banner has v1.0.0; the current GUI has no header banner). Users can't tell which version is running.
- **AMO requests should be disclosed** — the "Allow online AMO lookup" checkbox has no link to what's actually fetched.

---

## Architecture and Maintainability

### Module / boundary improvements

- **`foxport/migrate/*` directly imports `foxport/crypto/*`** — fine. But `migrate/nss_passwords.py`, `nss_cookies.py`, `nss_history.py` are three near-identical "back up target, atomic swap, refuse if locked" patterns. **Refactor candidate:** a `foxport/migrate/direct_write.py:DirectWriter` base class with `back_up_target()`, `swap_in()`, `refuse_if_locked()` helpers, leaving per-artifact subclasses to provide the staging file path.
- **`foxport/gui/pages.py` is 877 LOC**, all five wizard pages in one file. Split per-page: `pages/source.py`, `pages/target.py`, `pages/items.py`, `pages/preview.py`, `pages/run.py`, with `pages/context.py` for the shared `MigrationContext`.
- **`foxport/gui/workers.py:MigrationWorker.run`** is one method with a 9-branch tree. Each branch could be its own thin method delegating to migrators.
- **`foxport/migrate_reverse/*`** — three modules, none of which share with `foxport/migrate/*`. Forward and reverse extension matchers have totally separate code but conceptually do the same thing. A shared `foxport/extensions/matcher.py` could host the matching engine; forward + reverse just pick a direction.

### Refactor candidates

- `foxport/migrate/cookies.py:_iter_decrypted_cookies` — generator + side-channel failures list. Cleaner as a dataclass-yielding generator with `(row, plaintext, error_or_None)`.
- `foxport/cli.py:_cmd_migrate` — every "if 'X' in items" block is copy-paste. Build a table `{item_name: (label, migrator, post_action)}` and iterate.
- `foxport/gui/pages.py:ItemsPage._make_row` — proliferating optional kwargs (`customize_callback`, `default_checked`). Inline three or four `QFrame`s manually.

### Test gaps

- **Zero tests.** Critical migration paths (`url_hash`, schema-from-scratch, CSV emission, AES-GCM v10/v11 decrypt, ABE flag-byte parsing) all run blind.
- **Recommended test plan:**
  - `tests/fixtures/` with anonymized `Local State`, `Login Data` (synthesized via DPAPI in a sandbox), `Bookmarks`, `Cookies`, `History`, `Web Data`, `extensions.json`, `places.sqlite`, `logins.json`, `Session_*` files.
  - `tests/migrate/test_passwords.py` — round-trip a fixture, assert CSV columns + timestamps.
  - `tests/migrate/test_bookmarks.py` — round-trip the JSON, assert HTML structure + `ADD_DATE` units.
  - `tests/migrate/test_cookies.py` — round-trip + verify schema PRAGMA + Chrome 130 HOST_KEY strip flag.
  - `tests/migrate/test_history.py` — verify `url_hash` matches Firefox's `HashString` (after EI-1 fix).
  - `tests/migrate/test_open_tabs.py` — fixture-based SNSS Pickle parser test.
  - `tests/migrate/test_extensions.py` — mock AMO + verify confidence tiering.
  - `tests/crypto/test_dpapi.py` — branch on key length (16 vs 32 bytes).
  - `tests/gui/test_wizard.py` — `pytest-qt` for page navigation.
  - GitHub Actions matrix: extend `ci.yml` to run `pytest` cross-platform.

### Documentation gaps

- **`docs/architecture.md`** — none. `CLAUDE.md` exists but is gitignored as an AI-agent note. The README's "How it works" section is good but doesn't go below the level of "DPAPI unwraps the key".
- **`docs/file-formats.md`** — Firefox formats FoxPort produces (CSV columns, Netscape HTML quirks, `places.sqlite` schema notes) deserve their own page so users can debug.
- **`docs/troubleshooting.md`** — "ABE sidecar not found", "master password failed", "places.sqlite import didn't work", "Firefox 138 fresh-installed and didn't pick up the import" — none of these have docs.

### Release / build / deployment gaps

- **`.github/workflows/release.yml` and `ci.yml` exist but have never run.** Trigger one workflow_dispatch to validate them.
- **No tag/release in GitHub yet.** Repo is on `main` only.
- **No published wheel / sdist** on PyPI. `python -m pip install foxport` doesn't work.
- **PyInstaller bundle is untested.** The `foxport.spec` should be exercised once locally + once in CI.
- **No app icon** — the SVG banner is for the README only. Windows EXE has no icon embedded.
- **No code-signing cert** — bundles will trip SmartScreen on Windows and Gatekeeper on macOS.
- **No update channel** — see NF-10.

---

## Prioritized Roadmap

> Pull these into `ROADMAP.md` after triage. Format: checkbox + priority + title + Why / Evidence / Touches / Acceptance / Verify.

### Phase 1 — Correctness (P0)

- [ ] **P0 — Fix `places.sqlite` schema (v77 → v86) and `url_hash` algorithm**
  - Why: History migration silently corrupts / discards on Firefox 138+ launch.
  - Evidence: `mozilla-central/toolkit/components/places/Database.cpp` (`SCHEMA_VERSION = 86`); `Helpers.cpp` (`HashString` algorithm, not MD5).
  - Touches: `foxport/migrate/history.py:_FIREFOX_PLACES_SCHEMA`, `_url_hash`, `_SCHEME_PREFIX_TAG`; new `foxport/crypto/mozhash.py`.
  - Acceptance: A fixture URL passed through `_url_hash` produces the same 64-bit value as Firefox's `Helpers.cpp::computeHash(url)`; `PRAGMA user_version = 86` in emitted file; all v78-v86 columns present.
  - Verify: `pytest tests/migrate/test_history.py::test_url_hash_matches_firefox` + manual `sqlite3 places.sqlite '.schema moz_places'` shows new columns.

- [ ] **P0 — Fix `open_tabs` SNSS extractor**
  - Why: Verified live to return 0 URLs from a real 2754-byte Chrome session file.
  - Evidence: This research pass — `_extract_urls(sess.read_bytes())` returns `[]`.
  - Touches: `foxport/migrate/open_tabs.py` — replace regex with a proper SNSS Pickle command parser; read `Tabs/Tabs_*` files too.
  - Acceptance: Live run against a Chrome profile with at least one open tab returns the URL.
  - Verify: `python -c "from foxport.migrate.open_tabs import migrate_open_tabs, ..."`, count of URLs > 0.

- [ ] **P0 — Add a test suite**
  - Why: Zero existing tests; every regression above ships unnoticed.
  - Evidence: `find . -name test_*.py` returns nothing.
  - Touches: New `tests/` tree with fixtures + pytest config; `.github/workflows/ci.yml` updated to run `pytest`.
  - Acceptance: ≥ 80% coverage on `foxport/migrate/*` and `foxport/crypto/*`; CI matrix is green.
  - Verify: `pytest -q` exits 0 locally; CI badge in README.

### Phase 2 — Schema gaps (P1)

- [ ] **P1 — `cookies.sqlite` add `updateTime` column (v17 spec compliance)**
  - Why: Verified missing.
  - Evidence: `netwerk/cookie/CookiePersistentStorage.cpp` tip.
  - Touches: `foxport/migrate/cookies.py:_FIREFOX_COOKIES_SCHEMA`, INSERT column list.
  - Acceptance: `PRAGMA table_info(moz_cookies)` includes `updateTime`.
  - Verify: `pytest tests/migrate/test_cookies.py::test_schema_includes_updatetime`.

- [ ] **P1 — `bookmarks.html` toolbar — stop relying on `PERSONAL_TOOLBAR_FOLDER`**
  - Why: Firefox only honors it on `_isImportDefaults=true`.
  - Evidence: `BookmarkHTMLUtils.sys.mjs` source.
  - Touches: `foxport/migrate/bookmarks.py:_emit_folder`; user-facing import-instructions text.
  - Acceptance: Manual import into Firefox 138 puts toolbar items on the Toolbar (or docs are updated to instruct manual move).
  - Verify: Manual test against a clean Firefox 138 profile.

- [ ] **P1 — Filter `chrome://`, `about:`, `edge://`, `brave://`, `chrome-extension://` URLs from bookmark + history + tab exports**
  - Why: Firefox can't navigate to them; they pollute output.
  - Evidence: Live diff against real Brave profile.
  - Touches: `migrate/bookmarks.py`, `migrate/history.py`, `migrate/open_tabs.py`. Centralize the predicate.
  - Acceptance: Re-run diff against same profile shows no `chrome://` URLs.
  - Verify: Live re-run.

- [ ] **P1 — `diff` CLI refuses ambiguous profile matches**
  - Why: Live evidence of silent wrong-profile selection.
  - Evidence: This pass.
  - Touches: `foxport/cli.py:_find_chromium`, `_find_firefox`.
  - Acceptance: `python -m foxport.cli diff --source default --target default` prints all matches and exits 2.
  - Verify: Live re-run.

- [ ] **P1 — `favicons.sqlite` backup, not delete**
  - Why: Data loss in history direct-write.
  - Evidence: `foxport/migrate/nss_history.py:write_history_into_target` calls `unlink()`.
  - Touches: same file.
  - Acceptance: `favicons.foxport-backup-<mtime>.sqlite` exists after a history direct-write.
  - Verify: `pytest tests/migrate/test_nss_history.py::test_favicons_backed_up`.

- [ ] **P1 — Wire the drag-and-drop "Manual source" tile**
  - Why: Dead-ended UI promises something it doesn't deliver.
  - Evidence: `gui/pages.py:SourcePage._on_drop` stores path; no migrator reads it.
  - Touches: `gui/pages.py`, `gui/workers.py:MigrationRequest`.
  - Acceptance: Dropping a `User Data` folder → wizard advances → migration runs against that path.
  - Verify: Manual GUI test.

- [ ] **P1 — HIBP scan during password migration**
  - Why: User expectation; FoxPort already has cleartext.
  - Evidence: HIBP API v3 free.
  - Touches: `foxport/crypto/hibp.py`, `migrate/passwords.py`, Items checkbox.
  - Acceptance: `compromised-passwords.txt` lists hits; Done screen shows the count.
  - Verify: Test with a known-pwned password.

### Phase 3 — Trust + polish (P2)

- [ ] **P2 — Password preview dialog masks values by default**
  - Why: Shoulder-surfing risk.
  - Touches: `gui/dialogs.py:PasswordPreviewDialog`.
  - Acceptance: Password column shows `•••` until per-row eye-icon clicked.

- [ ] **P2 — Hide already-installed extensions from `extensions.html` by default**
  - Touches: `migrate/extensions.py:_build_html`.

- [ ] **P2 — Settings page** with output dir, mask passwords, online AMO lookup, dry-run by default, telemetry opt-in.
  - Touches: `gui/main_window.py` (menu item), new `gui/settings.py`, `foxport/config.py`.
  - Acceptance: Settings persist across runs in `%APPDATA%/FoxPort/config.json`.

- [ ] **P2 — Master-password retry loop (up to 3 attempts)**
  - Touches: `gui/main_window.py:_start_migration`.

- [ ] **P2 — Place `NSSSession.decrypt` in `crypto/nss.py`**
  - Touches: `crypto/nss.py`, `browsers/firefox_read.py`.

- [ ] **P2 — `formhistory.sqlite` v4 → v5 with `moz_sources` + `moz_history_to_sources`**
  - Touches: `migrate/autofill.py`.

- [ ] **P2 — Reverse-direction matcher coverage (13 → 60+ entries)**
  - Touches: `migrate_reverse/extensions.py:AMO_GUID_TO_CHROME`, build a script that harvests via AMO API + Chrome listing match.

- [ ] **P2 — History time-range filter dialog**
  - Touches: `gui/dialogs.py`, `gui/pages.py:ItemsPage`, `migrate/history.py`.

- [ ] **P2 — Downloads migration**
  - Touches: new `migrate/downloads.py`, `migrate/history.py` (annotation insertion).

- [ ] **P2 — Brave / Vivaldi as Chromium *target* in reverse direction**
  - Touches: `migrate_reverse/passwords.py`, `gui/pages.py:TargetPage` (already direction-aware).

- [ ] **P2 — FIDO CXF passkey export**
  - Touches: new `migrate/passkeys.py`.

- [ ] **P2 — Browser snapshot `.fxport` bundle + `restore` CLI**
  - Touches: new `foxport/snapshot.py`, `cli.py`.

- [ ] **P2 — Pocket / Pinboard / OPML bookmark input**
  - Touches: new `foxport/import_/` package; `gui/pages.py:SourcePage._on_drop`.

- [ ] **P2 — Path-traversal hardening on `make_export_dir`**
  - Touches: `browsers/firefox.py:make_export_dir`.

### Phase 4 — Distribution + observability (P3)

- [ ] **P3 — First-run dialog with opt-in for Glean + Sentry**
  - Touches: `gui/main_window.py`, new `gui/welcome.py`, `foxport/telemetry.py`.

- [ ] **P3 — Glean telemetry (categories, durations, error counts; never URLs)**
  - Touches: `foxport/telemetry.py`.

- [ ] **P3 — Sentry crash reporting (opt-in)**
  - Touches: `foxport/app.py`, `foxport/telemetry.py`.

- [ ] **P3 — Auto-update via WinSparkle / Sparkle**
  - Touches: `foxport/updater.py`, `gui/main_window.py`.

- [ ] **P3 — Run the release workflow end-to-end + publish the first signed binary**
  - Touches: `.github/workflows/release.yml`, secrets configuration.
  - Acceptance: A GitHub Release exists with `FoxPort-v1.2.0-windows-x64.zip` attached + a working signed `foxport_abe.exe` inside.

- [ ] **P3 — Replace SVG banner with raster logo + Windows EXE icon**
  - Touches: `assets/`, `foxport.spec`.

- [ ] **P3 — Schedule the curated-map auditor monthly via `.github/workflows/curated-map-audit.yml`**
  - Touches: new workflow.

- [ ] **P3 — Per-page screen-reader / keyboard navigation pass**
  - Touches: `gui/widgets.py:Tile` (`setFocusPolicy`), `gui/main_window.py` (Qt accessibility attributes).

- [ ] **P3 — Settings page accepts `FOXPORT_NSS_PATH` override and documents it**
  - Touches: `README.md`, settings page.

- [ ] **P3 — Docs: `docs/architecture.md`, `docs/file-formats.md`, `docs/troubleshooting.md`**
  - Touches: new `docs/`.

---

## Quick Wins

Low-risk changes < 1 hour each:

- **EI-4** — Add `updateTime INTEGER` to `cookies.sqlite` schema. Single-line change.
- **EI-12** — Switch favicons unlink → rename with timestamp. Two-line change.
- **EI-7** — Refuse ambiguous CLI profile matches. Single conditional.
- **EI-13** — Delete the `"{446900e4-…}": ""` placeholder in `AMO_GUID_TO_CHROME`.
- **EI-6** — URL scheme filter. Centralized predicate, three callers.
- **EI-10** — Hide already-installed extensions in `extensions.html` by default (CSS-only).
- **EI-11** — Mask passwords in the preview dialog (one-line `QTableWidgetItem` text replacement + per-row toggle).
- **EI-16** — `--strict-stale` flag in `check_curated_map.py`.
- **EI-9** — Loop master-password prompt 3x.

---

## Larger Bets

- **NF-1 + NF-2 + EI-1 trio** — "Migrate to Firefox safely" identity. HIBP scan + CXF passkeys + corrected `places.sqlite`. Positions FoxPort as the *trustworthy* Chrome-to-Firefox path versus Mozilla's own broken-on-Windows wizard.
- **NF-3 + NF-9** — "Browser archive" identity. `.fxport` snapshot bundle + import from Pocket/Pinboard/OPML. Repositions FoxPort as a backup/restore tool, not just a one-shot migrator.
- **NF-7 + NF-8 + NF-10** — Distribution maturity. Glean + Sentry + WinSparkle. Required for any release positioning beyond "GitHub one-off."
- **EI-1 alternative — Places-API-via-headless-Firefox.** Long-term, schema chasing won't scale. Instead: ship a one-shot WebExtension that runs inside a temporary Firefox instance, takes a FoxPort JSON dump, and uses `browser.bookmarks.create` / `browser.history.addUrl` / `browser.cookies.set` to populate the profile via Firefox's own APIs. Firefox does the schema dance. Higher upfront effort; never breaks again.
- **Test suite + CI** — Without P0 #3, every Phase-2+ item ships blind.

---

## Explicit Non-Goals

- **MV2 → MV3 manifest rewriter** — Chrome dropped MV2 in July 2025; the reverse migration would need MV3 → MV2 (Firefox still allows both). Rabbit hole (declarativeNetRequest vs webRequest). Skip.
- **Built-in password manager** — Don't compete with Bitwarden / 1Password / KeePassXC. Stay an *interop* tool.
- **Real-time sync** — FoxPort is a one-shot migration tool. Continuous sync would require a service. Out of identity.
- **GUI on a server / headless port** — CLI exists for that.
- **Forensic-grade dumping** — HackBrowserData + Hindsight own that space.
- **Anything that requires telemetry without opt-in** — privacy-positioned tool, see Larger Bets.
- **Chrome Web Store text-scraping bot** — fragile, against ToS. The "search CWS for this name" link in reverse-direction extension reports is fine; programmatic scraping isn't.
- **macOS App Store distribution** — sandboxing forbids the Keychain reads FoxPort needs. Ship outside the store.

---

## Open Questions

(Only items that block prioritization — public-source-answerable questions excluded.)

1. **How does Mozilla's own ChromeProfileMigrator handle the no-ABE-key case on Windows in Firefox 140?** Does it silently skip passwords, or does it surface a clear "couldn't import" error? If silent, FoxPort's UX wins by surfacing ABE detection. (Verifiable by installing Firefox 140 and running the wizard against a Chrome 127+ profile.)
2. **Will Firefox 138's `places.sqlite` parser accept FoxPort's emitted v77 schema and *migrate forward*, or will it call `replaceDatabaseOnStartup`?** Research agent flagged the risk; needs a clean-VM end-to-end test to confirm which path Firefox takes.
3. **Is FoxPort's `compromised-passwords.txt` (NF-1) regulated as a security advisory anywhere?** GDPR / CCPA implications of producing a list of weak passwords. Probably no — the user generated it themselves. Worth a one-line legal review.
4. **What Authenticode certificate authority offers the lowest friction for a one-developer Windows code-signing release?** Sectigo / DigiCert / SSL.com — Comparable cost, different EV vs OV vs CSC tradeoffs. Influences whether NF-10 (auto-update) is feasible in Q3 2026.

---

*Generated 2026-05-23 based on FoxPort v1.1.0 (`a483edc`). Research pass is exhaustive against the current codebase; competitive landscape and Firefox internal verification are from primary mozilla-central / AMO API / FIDO / HIBP sources. Items marked Verified are confirmed against code or live runs; items marked Likely / Assumption are flagged inline.*
