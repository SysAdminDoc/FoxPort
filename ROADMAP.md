# ROADMAP

Items here are concrete units of work. Check them off as shipped; promote rough
ideas from the bottom of the file as scope firms up.

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

## v0.4.1 — Direct-write polish
- [ ] Master-password prompt in the GUI when target has one set
- [ ] Per-item conflict resolution UI (skip / merge / overwrite per duplicate)
- [ ] Cookies direct-write via NSS (use OPgp-equivalent path for cookies)
- [ ] History direct-write to a live (closed) profile's places.sqlite

## v0.5.0 — Cross-platform  ✅ shipped 2026-05-23
- [x] macOS Chromium support — Keychain unwrap of the AES key
- [x] Linux Chromium support — gnome-keyring / kwallet / plain-text fallback
- [x] macOS Firefox profile detection (`~/Library/Application Support/Firefox`)
- [x] Linux Firefox profile detection (`~/.mozilla/firefox` + per-vendor dotfiles)

## v0.6.0 — Additional data types
- [ ] **Open tabs** — Chromium session storage → Firefox `recovery.jsonlz4`
      (`mozLz40\0` magic + lz4-block-compressed JSON; Firefox must be closed).
- [ ] **Form autofill** — Chromium `Web Data.autofill` → Firefox
      `formhistory.sqlite/moz_formhistory`.
- [ ] **Saved cards (CSV-only)** — Chromium `Web Data` cards table; Firefox
      has no native card store so CSV-only output.
- [ ] **Search engines** — Chromium TLD-engine list → `search.json.mozlz4`
      append-only.

## Reverse direction — v1.x
- [ ] Firefox → Chromium port (passwords via Firefox CSV export → re-encrypt
      with target Chromium's DPAPI key)
- [ ] AMO → CWS extension mapping table (inverse of current curated map)

## Distribution
- [ ] PyInstaller --onedir bundle, signed Windows release artifact
- [ ] GitHub Actions release workflow (`workflow_dispatch`, builds + uploads
      `.zip`)
- [ ] Logo / banner art
- [ ] DPI-aware README screenshots of the wizard

## Reach goals
- [ ] Browser-profile diff viewer (what will be migrated vs. what already
      exists in target)
- [ ] Extension-settings best-effort — only for the small set of cross-browser
      extensions that share storage shape (Stylus userstyles, Bitwarden vault
      URL, uBO filter lists)
- [ ] `--remote-debugging-port` CDP fallback — for the day the ABE bypass
      breaks, launch the user's own browser headless and slurp cookies via CDP

## Curated map upkeep
- [ ] Monthly health check that hits AMO for every curated slug and flags
      `is_disabled` / removed entries
- [ ] Auto-PR generator that proposes new entries from frequently-seen
      "no-match" extensions across users (opt-in telemetry)
