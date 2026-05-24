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

## v0.3.0 — Cookies + history + ABE bypass
- [ ] **Cookies migration** — decrypt with existing AES-GCM key, emit a fresh
      `cookies.sqlite` from scratch (Firefox schema v17). Refuse to write if
      target is locked. Convert chromium µs/1601 → firefox µs/1970 + s/1970 for
      `expiry`. Default `originAttributes=""`, `schemeMap=2` for HTTPS.
- [ ] **History migration** — `places.sqlite` direct write with `moz_origins` +
      `moz_places` (`frecency=-1`, `recalc_frecency=1`) + `moz_historyvisits`.
      `url_hash` populated via PlacesUtils-equivalent.
- [ ] **App-Bound Encryption bypass** — ship a small C++/MSVC sidecar EXE that
      performs the SYSTEM-DPAPI + user-DPAPI + IElevator2 dance for Chrome
      127+/Brave. Bundle into the release artifact.
- [ ] **Cookie HOST_KEY 32-byte SHA-256 prefix strip** for Chrome 130+
      (detect via `Cookies.meta.version >= 24`).
- [ ] **Dry-run mode** — show counts and decrypt-tests, no file writes.

## v0.4.0 — Direct write mode
- [ ] **Passwords via NSS** — link the target Firefox's `libnss3.dll` via
      ctypes; emit encrypted entries straight into `logins.json` (+ matching
      `logins-backup.json`); compute correct `id`/`guid`/`encType=1`.
- [ ] **Conflict resolution UI** — per-item skip/merge/overwrite for duplicates.
- [ ] **CLI mode** (`python -m foxport --source "Brave/Default" --target
      "Firefox/default-release" --all --dry-run`).
- [ ] **Per-folder bookmark filter** — skip / rename folders before export.
- [ ] **Password search/filter** in the preview pane.

## v0.5.0 — Cross-platform
- [ ] macOS Chromium support — Keychain unwrap of the AES key
- [ ] Linux Chromium support — gnome-keyring / kwallet / plain-text fallback
- [ ] macOS Firefox profile detection (`~/Library/Application Support/Firefox`)
- [ ] Linux Firefox profile detection (`~/.mozilla/firefox`)

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
