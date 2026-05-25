# Firefox file formats FoxPort writes

Reference for the on-disk shapes FoxPort produces. Useful for debugging
"why didn't Firefox accept my import" or for porting the same emitters
into another tool.

## `passwords.csv` — `about:logins` import

Comma-delimited, RFC 4180 quoting (every field double-quoted via
`csv.QUOTE_ALL`). Headers are case-insensitive in Firefox's
`LoginCSVImport.sys.mjs`.

| Column | Source | Notes |
|--------|--------|-------|
| `url` | Chromium `logins.origin_url` | Required. |
| `username` | `logins.username_value` | Required. |
| `password` | `logins.password_value` → AES-256-GCM decrypt | Required. |
| `httpRealm` | always empty | Firefox treats `""` as `null` (form login). |
| `formActionOrigin` | `logins.action_url` | Empty for HTTP-Basic auth. |
| `guid` | `uuid5(NS, origin\x00username)` | Deterministic for idempotent re-runs. |
| `timeCreated` | Chromium µs → ms | Firefox uses ms; verified against `LoginCSVImport`. |
| `timeLastUsed` | µs → ms | |
| `timePasswordChanged` | µs → ms | |

Reference: `toolkit/components/passwordmgr/LoginCSVImport.sys.mjs`.

## `bookmarks.html` — Netscape Bookmark File

```html
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="..." LAST_MODIFIED="..." PERSONAL_TOOLBAR_FOLDER="true">Bookmarks Toolbar</H3>
    <DL><p>
        <DT><A HREF="https://..." ADD_DATE="...">Title</A>
    </DL><p>
</DL><p>
```

**Date attributes are Unix seconds**, not ms or µs. Chromium dates
(µs since 1601-01-01 UTC) are converted via `(chrome_us // 1_000_000)
- 11_644_473_600`.

**`PERSONAL_TOOLBAR_FOLDER="true"` is silently ignored** in Firefox's
user-import path (only honored when `_isImportDefaults=true`, which is
the first-run default-bookmark bootstrap). The README instructions tell
users to manually drag the imported toolbar contents up to the real
Toolbar root.

`chrome://`, `about:`, `edge://`, etc. URLs are filtered by default —
they aren't navigable in Firefox.

## `cookies.sqlite` — Firefox schema v17

```sql
CREATE TABLE moz_cookies (
    id INTEGER PRIMARY KEY,
    originAttributes TEXT NOT NULL DEFAULT '',
    name TEXT, value TEXT, host TEXT, path TEXT,
    expiry INTEGER,
    lastAccessed INTEGER,
    creationTime INTEGER,
    isSecure INTEGER,
    isHttpOnly INTEGER,
    inBrowserElement INTEGER DEFAULT 0,
    sameSite INTEGER DEFAULT 0,
    rawSameSite INTEGER DEFAULT 0,
    schemeMap INTEGER DEFAULT 0,
    isPartitionedAttributeSet INTEGER DEFAULT 0,
    updateTime INTEGER,
    CONSTRAINT moz_uniqueid UNIQUE (name, host, path, originAttributes)
);
CREATE INDEX moz_basedomain ON moz_cookies (host);
PRAGMA user_version = 17;
```

| Field | Unit | Notes |
|-------|------|-------|
| `creationTime` | µs since 1970 | Chrome `creation_utc` − 11644473600·10⁶ |
| `lastAccessed` | µs since 1970 | Same conversion as `creationTime` |
| `updateTime` | µs since 1970 | We set ≈ `creationTime` at import |
| `expiry` | **seconds** since 1970 | NB: not µs despite what the C++ inline comment suggests |
| `originAttributes` | `""` for normal cookies | `"^firstPartyDomain=..."` for FPI; `"^partitionKey=..."` for partitioned |
| `host` | Domain cookies need leading `.` | Host-only: bare `example.com` |
| `sameSite` | 0=None, 1=Lax, 2=Strict | |
| `schemeMap` | bitfield: 1=http, 2=https, 4=file | We default to 2 for HTTPS |

Chrome 130+ prepends `SHA-256(host_key)` to the AES-GCM plaintext (32
bytes). FoxPort strips when `Cookies.meta.value WHERE key='version' >=
24`. Only applies to the Windows GCM path; macOS/Linux CBC blobs don't
carry it.

## `places.sqlite` — Firefox schema v86

Key tables (subset of what we populate):

* `moz_origins` — `(id, prefix, host, frecency, recalc_frecency,
  alt_frecency, recalc_alt_frecency, block_until_ms, block_pages_until_ms)`
  — populated **before** `moz_places` so the trigger that links
  `moz_places.origin_id` works.
* `moz_places` — `(id, url, title, rev_host, visit_count, hidden, typed,
  frecency, last_visit_date, guid, foreign_count, url_hash,
  description, preview_image_url, site_name, origin_id, recalc_frecency,
  alt_frecency, recalc_alt_frecency)` — set `frecency = -1` and
  `recalc_frecency = 1` so Firefox computes a real score on next idle.
* `moz_historyvisits` — `(id, from_visit, place_id, visit_date,
  visit_type, session, source, triggeringPlaceId)` — at least one per
  place_id or Firefox's maintenance task expires the orphan place row.
* `moz_anno_attributes` + `moz_annos` — present in every generated
  `places.sqlite`; populated only when Downloads are selected with
  history direct-write `apply`. FoxPort writes the Firefox download
  annotations `downloads/destinationFileURI` (a `file://` URI) and
  `downloads/metaData` (JSON with `state`, `endTime`, and `fileSize`)
  for source URLs that match imported `moz_places` rows.

### `url_hash` algorithm

Firefox uses a custom 64-bit hash. High 16 bits are
`HashString(scheme + "://") & 0xFFFF`. Low 32 bits are `HashString(url)`
on the URL capped at 1500 characters. `HashString` is **not** MD5 / SHA
/ SipHash — it's the multiply-rotate-xor mix from
`mfbt/HashFunctions.h`:

```python
GOLDEN_RATIO_U32 = 0x9E3779B9

def rotate_left_5(x):
    return ((x << 5) | (x >> 27)) & 0xFFFFFFFF

def add_u32_to_hash(h, v):
    return (GOLDEN_RATIO_U32 * (rotate_left_5(h) ^ v)) & 0xFFFFFFFF

def hash_string(s):
    h = 0
    for byte in s.encode("utf-8"):
        h = add_u32_to_hash(h, byte)
    return h
```

See `foxport/crypto/mozhash.py` for the production port; `Helpers.cpp`
in mozilla-central is the canonical reference.

### `rev_host`

Reversed lowercase host with a trailing dot. `www.example.com` →
`moc.elpmaxe.www.`.

## `formhistory.sqlite` — Firefox schema v5

```sql
CREATE TABLE moz_formhistory (id, fieldname, value, timesUsed, firstUsed, lastUsed, guid);
CREATE TABLE moz_deleted_formhistory (id, timeDeleted, guid);
CREATE TABLE moz_sources (id INTEGER PRIMARY KEY, source TEXT NOT NULL UNIQUE);
CREATE TABLE moz_history_to_sources (history_id, source_id, PRIMARY KEY (history_id, source_id));
PRAGMA user_version = 5;
```

Times are **microseconds since 1970** (note: not seconds). Chromium
`autofill.date_created` is seconds-since-1601 — see `migrate/autofill.py`
for the conversion.

GUIDs are base64 of 9 random bytes (matches
`PlacesUtils.history.makeGuid()` shape).

## `logins.json` — direct-write path

```json
{
  "nextId": 5,
  "version": 3,
  "logins": [
    {
      "id": 1,
      "hostname": "https://example.com",
      "httpRealm": null,
      "formSubmitURL": "https://example.com/login",
      "usernameField": "",
      "passwordField": "",
      "encryptedUsername": "<base64 NSS blob>",
      "encryptedPassword": "<base64 NSS blob>",
      "guid": "{uuid5-derived}",
      "encType": 1,
      "timeCreated": 1700000000000,
      "timeLastUsed": 1700000000000,
      "timePasswordChanged": 1700000000000,
      "timesUsed": 0
    }
  ],
  "potentiallyVulnerablePasswords": [],
  "dismissedBreachAlertsByLoginGUID": {}
}
```

Always write `logins-backup.json` with identical content — Firefox
re-reads the backup on next launch if it differs from `logins.json`.

NSS encryption: open the target's `nss3.dll`/`libnss3.dylib`/
`libnss3.so` via ctypes, call `NSS_Init(profile_path)`, then
`PK11SDR_Encrypt(keyid=empty SECItem, data, result, ctx=NULL)`. Base64
the resulting blob.

## `recovery.jsonlz4` — sessionstore

```
b"mozLz40\0"  +  uint32_le(uncompressed_size)  +  lz4.block.compress(json, store_size=False)
```

JSON shape (minimum Firefox accepts):

```json
{
  "version": ["sessionrestore", 1],
  "windows": [{"tabs": [
    {"entries": [{"url": "...", "title": "", "triggeringPrincipal_base64": ""}],
     "index": 1, "hidden": false, "pinned": false}
  ], "selected": 1, "_closedTabs": []}],
  "_closedWindows": [],
  "session": {"lastUpdate": 0, "startTime": 0, "recentCrashes": 0}
}
```
