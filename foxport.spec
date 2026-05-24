# PyInstaller spec for FoxPort. Build with:
#   pyinstaller foxport.spec --noconfirm --clean
#
# Produces dist/FoxPort/ (--onedir) containing FoxPort.exe + Qt runtimes +
# all bundled data files. If a built foxport_abe.exe exists at
# foxport/data/foxport_abe.exe, it gets bundled too.

from pathlib import Path

block_cipher = None

datas = [
    ("foxport/data/curated_extension_map.json", "foxport/data"),
]
# Optional ABE sidecar — only bundled if a build artifact exists.
_abe = Path("foxport/data/foxport_abe.exe")
if _abe.is_file():
    datas.append((str(_abe), "foxport/data"))

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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FoxPort",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon will be added once branding lands at assets/icon.ico
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
