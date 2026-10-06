# -*- mode: python ; coding: utf-8 -*-
import importlib.util

# PyInstaller only warns about modules it can't find, so building with a Python that lacks
# the app's requirements produces an exe that can't start. Stop the build instead.
missing = [name for name in ('PyQt5', 'requests') if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit(
        f"\nThis Python is missing the app's requirements: {', '.join(missing)}.\n"
        "Run build.bat (it sets them up in .venv), or: python -m pip install -r requirements.txt\n")


a = Analysis(
    ['mod_installer.py'],
    pathex=[],
    binaries=[],
    datas=[('logos', 'logos')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WRSR Mod Installer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
