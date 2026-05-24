# Troubleshooting FoxPort

Common failure modes + how to resolve them.

## Password decryption fails on Chrome 127+ (Windows)

**Symptom:** the migrator logs `App-Bound Encryption only (Chrome 127+);
ABE recovery was skipped` or `foxport_abe.exe is not bundled with this
install`.

**Cause:** Chrome 127 added App-Bound Encryption for the password +
cookie master key. FoxPort's pure-Python DPAPI path can't unwrap it on
its own — the `foxport_abe.exe` sidecar handles it via the per-browser
`IElevator` COM interface.

**Fix:**

1. Build the sidecar from `tools/abe_sidecar/`:
   ```powershell
   cd tools\abe_sidecar
   cmake -B build -A x64
   cmake --build build --config Release
   ```
2. Copy `build/Release/foxport_abe.exe` to `foxport/data/foxport_abe.exe`.
3. Re-run the migration. FoxPort auto-detects the sidecar and invokes it
   (UAC prompt on first run).

**Workaround:** if your old passwords were saved before Chrome 127, the
classic key may still be present in `Local State.os_crypt.encrypted_key`
— FoxPort uses it preferentially when both keys exist.

## Master password rejected (reverse direction)

**Symptom:** `Master password rejected 3 times — migration cancelled.`

**Cause:** the source Firefox profile has a master password set and the
prompted value didn't match.

**Fix:** open the source Firefox, go to Settings → Privacy & Security
→ Use a Primary Password → enter the correct one or unset it, then
re-run FoxPort.

## Diff CLI reports "0 already in target"

**Symptom:** `python -m foxport.cli diff` shows all source entries as
new even though you know the target has data.

**Cause:** ambiguous substring match. If you have profiles `default`,
`default-default`, `default-default-1`, the substring `default` matches
all three.

**Fix:** specify the full `<Browser>/<Profile>` label:

```bash
python -m foxport.cli diff --source "Brave/Default" --target "Firefox/default-release"
```

When matches are ambiguous, FoxPort 1.2.0+ exits with code 2 and lists
the matching profiles.

## Firefox import doesn't see my toolbar bookmarks

**Symptom:** after `Library → Import Bookmarks from HTML`, your toolbar
bookmarks land under "Other Bookmarks > Bookmarks Toolbar" rather than
on the actual Bookmarks Bar.

**Cause:** Firefox's `PERSONAL_TOOLBAR_FOLDER` HTML attribute is only
honored on first-run bootstrap, not on user-triggered imports. The
attribute is in our HTML but Firefox ignores it.

**Fix:** in the Library window (Ctrl+Shift+O), expand the imported
"Bookmarks Toolbar" folder under "Other Bookmarks", select all its
contents (Ctrl+A), and drag them to the real "Bookmarks Toolbar" root
on the left.

## `places.sqlite` direct-write seemed to work but AwesomeBar can't find anything

**Symptom:** history is visible in `about:history` but the AwesomeBar
returns no matches when you type known URLs.

**Cause:** before v1.2.0, FoxPort used a fabricated `url_hash` algorithm
(MD5 + scheme-int table). Firefox uses `mfbt::HashString`. Mismatched
hashes silently disable AwesomeBar lookups.

**Fix:** upgrade to v1.2.0+ and re-run the history migration.

## `cookies.sqlite` direct-write triggered Firefox to re-create the DB

**Symptom:** after swapping in FoxPort's cookies.sqlite and launching
Firefox, the cookies are gone.

**Cause:** Firefox 138's schema v17 requires an `updateTime` column that
older FoxPort versions omitted.

**Fix:** upgrade to v1.2.0+.

## `open_tabs` migration produces an empty `recovery.jsonlz4`

**Symptom:** Firefox shows no "Restore Previous Session" button after
swapping in the file.

**Cause:** the source Chrome profile genuinely had no open tabs at
session-save time (small `Sessions/Session_*` file). FoxPort 1.2.0+ also
reads `Sessions/Tabs_*` files, which often have URLs when `Session_*`
files don't.

**Fix:** re-open a few tabs in Chrome, close Chrome cleanly, re-run
FoxPort. Verify with:

```bash
python -m foxport.cli migrate --source "Brave/Default" \
    --items open_tabs --dry-run
```

If the count is still 0, check `~/AppData/Local/<vendor>/User Data/
Default/Sessions/` for non-zero-sized files.

## "FoxPort never modifies the source browser" — verify

Every read path goes through `_copy_for_read(path)`. You can grep:

```bash
grep -r "_copy_for_read" foxport/
```

The only writes outside of `out_dir` are the opt-in direct-write paths
(`migrate/nss_passwords.py`, `migrate/nss_cookies.py`,
`migrate/nss_history.py`, `migrate/open_tabs.write_session_into_target`)
— all of which target the *Firefox* profile, not the Chromium source.

## CI workflow is broken

Run pytest locally:

```bash
pip install -r requirements.txt pytest==8.3.4
pytest -ra -q
```

`tests/conftest.py` provides synthetic Chromium fixtures so tests don't
require a real browser install. If pytest fails locally, the CI failure
will be the same root cause.

## ABE sidecar fails with `IElevator::DecryptData failed: hr=0x80070005`

**Cause:** access denied — usually because the sidecar wasn't elevated.
The embedded manifest requests `requireAdministrator` but some Windows
configurations override this.

**Fix:** right-click `foxport_abe.exe` → "Run as administrator" once to
ensure UAC processes the manifest. Alternatively, run FoxPort itself
elevated (Run as administrator).

## Where are my output files?

Default location:

* Windows: `%USERPROFILE%\Documents\FoxPort\`
* macOS / Linux: `~/Documents/FoxPort/`

Each migration creates a subfolder named
`YYYYMMDD-HHMMSS_<source>__to__<target>/`. Override via File → Settings…
in the GUI, or `--out <path>` on the CLI.
