# -*- mode: python ; coding: utf-8 -*-
# Packs the whole built suite into one redistributable installer executable.
import os

BASE = os.path.abspath(os.path.join(SPECPATH, ".."))
PAYLOAD = os.path.join(BASE, "bin")

a = Analysis(
    [os.path.join(SPECPATH, "installer.py")],
    pathex=[SPECPATH],
    binaries=[],
    datas=[(PAYLOAD, "payload")],
    hiddenimports=["win32com.client", "winreg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt6", "PIL", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ClipboardEnhancementSetup",
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
