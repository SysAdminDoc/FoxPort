# foxport_abe — App-Bound Encryption sidecar

Tiny Windows-only EXE that recovers the AES-256 master key from a Chromium
profile that has migrated to App-Bound Encryption (Chrome 127+, Brave 1.86+,
Edge cookies/payments). FoxPort's pure-Python decrypt cannot do this on its
own because the wrapped key requires a call into the per-browser `IElevator`
elevated COM interface.

## How it's used

FoxPort launches the sidecar with `--browser <name> --local-state <path>`,
captures stdout, and parses one of:

```
KEY_HEX:<64-hex-chars>
OK
```

The hex string is the same 32-byte AES key returned by the classic
`os_crypt.encrypted_key` path — drop it into the existing FoxPort decrypt
pipeline and cookies/passwords decode normally.

## Build

```powershell
cd tools/abe_sidecar
cmake -B build -A x64
cmake --build build --config Release
```

Output: `build/Release/foxport_abe.exe`. Copy it next to FoxPort's Python
package (specifically into `foxport/data/foxport_abe.exe`) or alongside the
PyInstaller bundle.

## Requirements

- Windows 10 / 11
- MSVC v143 (Visual Studio 2022 17.8+)
- Windows SDK 10.0.22621 or newer

## Why this is a separate EXE

1. **UAC manifest.** The sidecar embeds `requireAdministrator`, which Windows
   handles cleanly at process launch. Doing the IElevator dance from inside
   the Python/PyQt6 process would force the entire GUI to run elevated.
2. **No PyPI binding ships the IElevator COM interface.** The vtable layout
   and IID/CLSID values are reverse-engineered per-browser and would need
   either `comtypes`-generated proxies (which leak Python into elevated
   space) or hand-written ctypes wrappers (which still don't avoid the
   elevation problem above).
3. **Signing.** Once compiled, the EXE is a tiny native artifact that a
   release pipeline can Authenticode-sign in isolation — Python wheels can't
   be Authenticode-signed in any portable way.

## Vendor → CLSID / IID table

Source: xaitax's research and live tests against Chrome 144, Brave 1.86, Edge 145.

| Browser    | CLSID                                    | IID                                      |
|------------|------------------------------------------|------------------------------------------|
| Chrome     | `{708860E0-F641-4611-8895-7D867DD3675B}` | `{463ABECF-410D-407F-8AF5-0DF35A005CC8}` |
| Brave      | `{576B31AF-6369-4B6B-8560-E4B203A97A8B}` | `{F396861E-0C8E-4C71-8256-2FAE6D759CE9}` |
| Edge       | `{1FCBE96C-1697-43AF-9140-2897C7C69767}` | `{C9C2B807-7731-4F34-81B7-44FF7779522B}` |

Avast / other Chromium derivatives have their own pairs; add to
`foxport_abe.cpp` as `static const CLSID`/`IID` block.

## Limitations

- **Edge passwords stay on classic DPAPI v10** even at Edge 145 — only Edge
  cookies and payment methods have migrated to ABE. Don't bother running the
  sidecar against an Edge `Login Data` file; it'll return E_INVALIDARG.
- **Partitioned cookies** live elsewhere in memory and aren't recoverable
  via IElevator.
- **Future Chrome versions may change the algorithm flag byte** (`0x01`
  AES-GCM vs `0x03` ChaCha20/CNG). The sidecar returns only the key — the
  Python side branches on the flag.

## Status

v0.3.0: source committed, builds clean locally with MSVC v143. Compiled and
signed binary is on the v0.3.1 roadmap (release pipeline work, not a code
issue).
