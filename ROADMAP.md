# ROADMAP

Items here are concrete units of work. Check them off as shipped; promote rough
ideas from the bottom of the file as scope firms up.

> **Read this first if you're picking up where the last session left off:**
> `RESEARCH_FEATURE_PLAN.md` is the most recent research output. The
> `v1.2.0` section below is the promoted action list from that file.

## v1.2.0 — Research-driven correctness + trust

### P0 (correctness — three bugs verified live in v1.1.0)
- [ ] **places.sqlite v77 → v86 + correct `url_hash`** — port `mfbt::HashString` to Python; drop MD5/fabricated-scheme-table; add v78–v86 columns. Risk: Firefox `replaceDatabaseOnStartup` on import.
- [ ] **`open_tabs` SNSS Pickle parser** — live run returns 0 URLs from real 2754-byte Chrome session. Replace regex with real parser; also read `Tabs/Tabs_*` files.
- [ ] **Add `tests/` suite** — pytest config, fixtures, round-trip tests for every migrator. CI workflow runs `pytest`.

### P1 (schema gaps + UX trust)
- [x] **`cookies.sqlite` add `updateTime`** column (v17 spec compliance)
- [ ] **`bookmarks.html` toolbar** — stop relying on `PERSONAL_TOOLBAR_FOLDER`; document or implement post-import move
- [x] **Filter `chrome://`, `chrome-extension://`, `edge://`, `brave://`, `about:`** URLs from bookmark + history + tab exports by default
- [x] **`diff` CLI refuses ambiguous profile matches** — multiple substring hits print list and exit 2
- [ ] **Wire drag-and-drop "Manual source" tile** — currently dead code
- [x] **`favicons.sqlite` backup, not delete** in history direct-write
- [ ] **HIBP scan during password migration** — opt-in; produces `compromised-passwords.txt`

### P2 (polish + small features)
- [x] **Password preview dialog masks values by default** (Show-all toggle; per-row eye is a future polish pass)
- [x] **Hide already-installed extensions** in `extensions.html` by default (collapsed `<details>` block)
- [ ] **Settings page** — output dir, mask-passwords, online-AMO, dry-run default, telemetry opt-in
- [x] **Master-password retry loop** (up to 3 attempts)
- [ ] **NSSSession.decrypt method** in `crypto/nss.py` (currently bound inline in `firefox_read.py`)
- [ ] **`formhistory.sqlite` v4 → v5** with `moz_sources` + `moz_history_to_sources`
- [ ] **Reverse-direction matcher coverage** (13 → 60+ AMO_GUID_TO_CHROME entries) via harvester script
- [ ] **History time-range filter dialog** (last N days + custom range)
- [ ] **Path-traversal hardening** on `make_export_dir`
- [x] **Curated map placeholder cleanup** — removed `"{446900e4-…}": ""` and the bad ClearURLs entry
- [x] **`check_curated_map.py --strict-stale` flag** — fail CI on entries older than N months

### P3 (distribution + observability)
- [ ] First-run dialog with opt-in for Glean + Sentry
- [ ] Glean telemetry (categories, durations, error counts; no URLs)
- [ ] Sentry crash reporting (opt-in)
- [ ] Auto-update via WinSparkle / Sparkle
- [ ] Run the release workflow end-to-end + publish the first signed binary
- [ ] Raster logo + Windows EXE icon
- [ ] Monthly curated-map auditor scheduled workflow
- [ ] Per-page screen-reader / keyboard navigation pass
- [ ] Docs: `docs/architecture.md`, `docs/file-formats.md`, `docs/troubleshooting.md`

### Larger bets (Phase 4+)
- [ ] **FIDO CXF v1.0 passkey export** — Chrome `Web Data.webauthn_credentials` → CXF JSON
- [ ] **Downloads migration** — Chrome `History.downloads` → Firefox `moz_annos`
- [ ] **Browser snapshot `.fxport` bundle** + `restore` CLI subcommand
- [ ] **Pocket / Pinboard / OPML bookmark input** via the manual-source tile
- [ ] **Brave / Vivaldi / Edge as reverse target** (parameterize the Chromium write path)



## v0.2.0 — Wizard UI + smarter matching  ✅ shipped 2026-05-23
- [x] Five-step QStackedWidget wizard (Source → Target → Items → Preview → Run)
- [x] Left-rail step indicator with active/completed/future states
- [x] Tile-based source/target pickers
- [x] Drag-and-drop on the source step
- [x] Preview pane with bookmark/extension tree + counts
- [x] Curated extension map externalized to JSON, 63 entries
- [x] Gecko ID probe via AMO detail endpoint
- [x] Permission-overlap confidence scoring
- [x] Already-installed extension detection (reads target `extensions.json`)
- [x] App-Bound Encryption awareness + warning
- [x] Opera Stable / Opera GX flat-profile layout
- [x] Browser-running detection on source
- [x] Firefox profile lock detection on target
- [x] Deterministic password GUIDs for idempotent re-runs
- [x] Richer extensions.html with permissions preview + stats

## v0.3.0 — Cookies + history + ABE bypass  ✅ shipped 2026-05-23
- [x] **Cookies migration** — decrypt with existing AES-GCM key, emit a fresh
      `cookies.sqlite` from scratch (Firefox schema v17). Refuse to write if
      target is locked. Convert chromium µs/1601 → firefox µs/1970 + s/1970 for
      `expiry`. Default `originAttributes=""`, `schemeMap=2` for HTTPS.
- [x] **History migration** — `places.sqlite` direct write with `moz_origins` +
      `moz_places` (`frecency=-1`, `recalc_frecency=1`) + `moz_historyvisits`.
      `url_hash` populated via PlacesUtils-equivalent.
- [x] **App-Bound Encryption bypass** — `tools/abe_sidecar/foxport_abe.cpp`
      ships as C++ source + CMakeLists + manifest; `crypto/abe.py` is the
      Python launcher. `load_master_key()` calls into it automatically when
      only the ABE key is present.
- [x] **Cookie HOST_KEY 32-byte SHA-256 prefix strip** for Chrome 130+
      (detected via `Cookies.meta.version >= 24`).
- [x] **Dry-run mode** — show counts and decrypt-tests, no file writes.

## v0.3.1 — ABE sidecar binary
- [ ] Compile `foxport_abe.exe` with MSVC v143 in CI (GitHub Actions)
- [ ] Authenticode-sign the binary in the release pipeline
- [ ] Ship the signed EXE in the FoxPort release ZIP at `foxport/data/foxport_abe.exe`
- [ ] Document `--browser` flag for additional vendors (Avast Secure Browser,
      etc.) once their IElevator IIDs are confirmed

## v0.4.0 — Direct write mode  ✅ shipped 2026-05-23
- [x] **Passwords via NSS** — link the target Firefox's `libnss3.dll` via
      ctypes; emit encrypted entries straight into `logins.json` (+ matching
      `logins-backup.json`); compute correct `id`/`guid`/`encType=1`.
- [x] **Conflict resolution** — deterministic GUIDs skip existing entries
      by default. Per-item skip/merge/overwrite UI deferred to v0.4.1 (the
      "skip by GUID" default solves the 95% case).
- [x] **CLI mode** (`python -m foxport.cli {list,migrate}` with
      `--source --target --items --all --dry-run --out --no-online`).
- [x] **Per-folder bookmark filter** — `BookmarkFilterDialog` opens from
      the Items step Customize button.
- [x] **Password preview/filter** — `PasswordPreviewDialog` shows
      decrypted rows with search + per-row checkboxes.

## v0.4.1 — Direct-write polish  ✅ shipped 2026-05-23 (per-item conflict UI deferred)
- [x] Master-password prompt in the GUI when source/target has one set
- [ ] Per-item conflict resolution UI (skip / merge / overwrite per duplicate)
- [x] Cookies direct-write into closed target profile
- [x] History direct-write to a closed profile's places.sqlite

## v0.5.0 — Cross-platform  ✅ shipped 2026-05-23
- [x] macOS Chromium support — Keychain unwrap of the AES key
- [x] Linux Chromium support — gnome-keyring / kwallet / plain-text fallback
- [x] macOS Firefox profile detection (`~/Library/Application Support/Firefox`)
- [x] Linux Firefox profile detection (`~/.mozilla/firefox` + per-vendor dotfiles)

## v0.6.0 — Additional data types  ✅ shipped 2026-05-23
- [x] **Open tabs** — see v0.6.1 (URL scanner) and v1.2.0 (Pickle parser fix).
- [x] **Form autofill** — Chromium `Web Data.autofill` → Firefox
      `formhistory.sqlite/moz_formhistory`.
- [x] **Saved cards (CSV-only)** — Chromium `Web Data` cards table; Firefox
      has no native card store so CSV-only output.
- [x] **Search engines** — Chromium `Web Data.keywords` → per-engine
      OpenSearch XML + JSON inventory (writing `search.json.mozlz4`
      directly is too fragile due to per-Firefox-version hash validation).

## v0.6.1 — Open tabs  ✅ shipped 2026-05-23
- [x] URL scanner for Chromium `Sessions/Session_<num>` (UTF-16LE pickle
      regex with RFC-3986 char class)
- [x] Translate to Firefox `sessionstore-backups/recovery.jsonlz4`
      (`b"mozLz40\\0"` magic + lz4-block-compressed JSON)
- [x] Optional direct-write into the closed target profile

## Reverse direction — v1.0.0  ✅ shipped 2026-05-23
- [x] Firefox → Chromium passwords (CSV format Chrome's import accepts)
- [x] Firefox → Chromium bookmarks (Netscape HTML, toolbar promoted)
- [x] AMO → CWS extension mapping (inverted curated + GUID table)
- [x] GUI direction toggle on the Source step (v1.1.0)

## Distribution  ✅ mostly shipped 2026-05-23
- [x] PyInstaller --onedir bundle via `foxport.spec` (bundles
      `foxport_abe.exe` when present)
- [x] GitHub Actions release workflow (`workflow_dispatch`,
      `.github/workflows/release.yml`) — builds the ABE sidecar with
      MSVC v143, runs PyInstaller, zips, creates the GH release
- [x] CI workflow (`.github/workflows/ci.yml`) — AST + import smoke +
      CLI sanity on Windows/macOS/Linux × Python 3.11/3.12
- [x] DPI-aware README screenshots via `scripts/capture_screenshots.py`
- [x] SVG banner header at `assets/banner.svg`
- [ ] Replace SVG banner with proper raster logo + favicon set
      (needs ChatGPT image gen pass — not autonomously generatable)
- [ ] Authenticode-sign the released ZIP and the ABE sidecar EXE
      (needs a code-signing cert)

## Reach goals
- [x] Browser-profile diff viewer (`python -m foxport.cli diff`) — v1.1.0
- [ ] Extension-settings best-effort — only for the small set of cross-browser
      extensions that share storage shape (Stylus userstyles, Bitwarden vault
      URL, uBO filter lists)
- [ ] `--remote-debugging-port` CDP fallback — for the day the ABE bypass
      breaks, launch the user's own browser headless and slurp cookies via CDP

## Curated map upkeep
- [x] Monthly health check (`scripts/check_curated_map.py`) — hits AMO
      for every curated slug, flags `is_disabled` / removed / stale entries
- [ ] Auto-PR generator that proposes new entries from frequently-seen
      "no-match" extensions across users (opt-in telemetry)
