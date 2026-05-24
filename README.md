# FoxPort

[![version](https://img.shields.io/badge/version-0.1.0-f5c2e7?style=flat-square)](CHANGELOG.md)
[![license](https://img.shields.io/badge/license-MIT-89b4fa?style=flat-square)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows-cdd6f4?style=flat-square)](#)
[![python](https://img.shields.io/badge/python-3.11%2B-a6e3a1?style=flat-square)](https://www.python.org/)

**Port Chromium browsers to Firefox.** FoxPort scans your installed Chromium-family browsers (Chrome, Brave, Edge, Vivaldi, Opera, Arc, Thorium, Yandex, ...), decrypts your saved passwords, packages up your bookmarks, and maps your Chrome extensions to their Firefox equivalents on addons.mozilla.org — all in one click.

The source browser is never modified. FoxPort writes Firefox-native import files into an output folder; you import them through the target browser's normal UI.

---

## What gets migrated

| Item | Source | Destination format | How to import |
| --- | --- | --- | --- |
| **Passwords** | `Login Data` SQLite + DPAPI key | Firefox CSV (`url,username,password,...`) | `about:logins` → menu → Import from a File |
| **Bookmarks** | `Bookmarks` JSON | Netscape HTML | Library (`Ctrl+Shift+O`) → Import Bookmarks from HTML |
| **Extensions** | Profile `Extensions/<id>/<ver>/manifest.json` | HTML page of AMO install links | Open the HTML in Firefox, click each link |

---

## Supported source browsers

Google Chrome (stable / Beta / Canary), Chromium, **Brave** (stable / Beta / Nightly), Microsoft Edge (stable / Beta / Dev), Vivaldi, Opera, Opera GX, Yandex, Arc, Thorium.

Any browser that follows the Chrome `User Data\<profile>` layout will be picked up automatically. Each browser's individual profiles (Default, Profile 1, Profile 2, ...) are detected separately.

## Supported destinations

Firefox (stable / Nightly / ESR), **LibreWolf**, Waterfox, Floorp, Mullvad Browser, Tor Browser, Zen Browser.

Any Gecko-based browser that ships a `profiles.ini`.

---

## Install

Requires Python 3.11+ on Windows.

```bash
git clone https://github.com/SysAdminDoc/FoxPort.git
cd FoxPort
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m foxport
```

---

## How it works

### Passwords
Chromium (since v80) wraps the AES-256 master key for the password store with Windows DPAPI and stores it in `Local State` under `os_crypt.encrypted_key`. Each saved password is an AES-256-GCM blob in the `Login Data` SQLite database, tagged with a `v10`/`v11` prefix, nonce, ciphertext, and auth tag.

FoxPort:
1. Loads `Local State`, base64-decodes the wrapped key, strips the `DPAPI` prefix, and calls `CryptUnprotectData`.
2. Copies `Login Data` to a temp directory (so it works even while the browser is running and holds a write-lock), opens it read-only, and decrypts each entry with `cryptography.AESGCM`.
3. Converts each row's Chromium WebKit timestamps (microseconds since 1601-01-01 UTC) to Firefox milliseconds since 1970-01-01 UTC, generates a fresh GUID, and writes the result as a CSV that `about:logins` natively imports.

DPAPI only works on the same Windows user account that originally encrypted the data. Running FoxPort against a copy of someone else's profile won't decrypt their passwords — by design.

### Bookmarks
The `Bookmarks` file is plain JSON. FoxPort walks the `bookmark_bar`, `other`, and `synced` roots, converting them to the Netscape Bookmark HTML format that Firefox (and every other browser) has imported for two decades. The bookmark bar is tagged with `PERSONAL_TOOLBAR_FOLDER="true"` so it lands in Firefox's Bookmarks Toolbar.

### Extensions
Chrome and Firefox both speak WebExtensions, but Chrome's MV3 lockdown means extensions are not byte-for-byte portable. FoxPort instead resolves the **identity** of each Chrome extension:

1. **Curated map** — A built-in table of the most-used Chrome ↔ Firefox pairs (uBlock Origin, Bitwarden, Stylus, Violentmonkey, Vimium, SponsorBlock, Refined GitHub, ...).
2. **AMO search** — For anything else, the extension's manifest name is queried against the public addons.mozilla.org search API. The top hit is used if its name matches well enough.
3. **No match** — Reported as such so you can decide what to do.

Output is an HTML page you open in Firefox and click through. Offline runs (uncheck "Allow AMO online lookup") still produce a usable page from the curated table.

---

## Output layout

```
%USERPROFILE%\Documents\FoxPort\
└── 20260523-114205_Brave_-_Default__to__Firefox_-_default-release\
    ├── passwords.csv         # for about:logins
    ├── bookmarks.html        # for Library import
    ├── extensions.html       # one-click AMO install page
    ├── extensions.json       # machine-readable mapping
    └── README.txt            # step-by-step import instructions
```

The output folder is configurable in the UI.

---

## Security notes

- **Local-only.** Decryption happens on your machine; the only network call is an optional AMO search for extension names. Passwords never leave the box.
- **Output files contain plaintext passwords.** Treat `passwords.csv` like a secret. Delete it after importing.
- **No browser modification.** FoxPort copies SQLite files to a temp dir before reading; it does not write to `Login Data`, `Bookmarks`, or anything else in the source profile.
- **DPAPI scoping.** Decryption only succeeds when running as the Windows user who originally saved the passwords.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
