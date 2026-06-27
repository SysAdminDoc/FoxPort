# PyInstaller spec for FoxPort. Build with:
#   pyinstaller foxport.spec --noconfirm --clean
#
# Produces dist/FoxPort/ (--onedir) containing FoxPort.exe + Qt runtimes +
# all bundled data files. If a built foxport_abe.exe exists at
# foxport/data/foxport_abe.exe, it gets bundled too. The CHANGELOG.md is
# also bundled so the Help menu's "View change log" entry finds it inside
# a packaged install.

from pathlib import Path

block_cipher = None

# Optional Windows EXE branding. PyInstaller picks these up when present;
# assets/version_info.txt must match __version__ before each local release
# build so the EXE's File Version metadata matches the tag.
_icon = Path("assets/icon.ico")
_version_info = Path("assets/version_info.txt")

datas = [
    ("foxport/data/curated_extension_map.json", "foxport/data"),
    ("foxport/data/glean_metrics.yaml", "foxport/data"),
    ("foxport/data/glean_pings.yaml", "foxport/data"),
]
# Optional ABE sidecar — only bundled if a build artifact exists.
_abe = Path("foxport/data/foxport_abe.exe")
if _abe.is_file():
    datas.append((str(_abe), "foxport/data"))
# Bundle CHANGELOG.md when present so the Help menu can render it inside
# a packaged install (the Help menu probes _MEIPASS for this filename).
_changelog = Path("CHANGELOG.md")
if _changelog.is_file():
    datas.append((str(_changelog), "."))
# Bundle the runtime window icon. The EXE resource icon is set below via
# `exe_kwargs["icon"]`; this entry is what foxport.app.resolve_app_icon_path
# loads at runtime so the title bar + taskbar pick up the same artwork
# inside a packaged install.
if _icon.is_file():
    datas.append((str(_icon), "assets"))

a = Analysis(
    ["foxport/__main__.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # PyQt6 has dynamic imports under the hood; pin the ones we touch.
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        # cryptography backends are loaded lazily.
        "cryptography.hazmat.backends.openssl",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PyQt5",
        "PySide6",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_kwargs = {
    "name": "FoxPort",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "console": False,                    # GUI app — no console window
    "disable_windowed_traceback": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
}
# Apply the branding hooks only when the source files exist so a local
# `pyinstaller foxport.spec` build still works without a checked-in icon.
if _icon.is_file():
    exe_kwargs["icon"] = str(_icon)
if _version_info.is_file():
    exe_kwargs["version"] = str(_version_info)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    **exe_kwargs,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FoxPort",
)
