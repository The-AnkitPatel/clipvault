# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

a_popup = Analysis(
    ['clipboard_popup.pyw'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtSvg', 'PIL', 'win32gui', 'win32process', 'win32api', 'win32con', 'win32clipboard', 'win32event', 'clipboard_ui', 'clipboard_common', 'win32crypt', 'winreg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_popup = PYZ(a_popup.pure, a_popup.zipped_data, cipher=block_cipher)

exe_popup = EXE(
    pyz_popup,
    a_popup.scripts,
    [],
    exclude_binaries=True,
    name='clipboard-popup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

a_daemon = Analysis(
    ['clipboard_daemon.pyw'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtSvg', 'PIL', 'win32gui', 'win32process', 'win32api', 'win32con', 'win32clipboard', 'win32event', 'clipboard_ui', 'clipboard_common', 'win32crypt', 'winreg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz_daemon = PYZ(a_daemon.pure, a_daemon.zipped_data, cipher=block_cipher)

exe_daemon = EXE(
    pyz_daemon,
    a_daemon.scripts,
    [],
    exclude_binaries=True,
    name='clipboard-daemon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_daemon,
    a_daemon.binaries,
    a_daemon.zipfiles,
    a_daemon.datas,
    exe_popup,
    a_popup.binaries,
    a_popup.zipfiles,
    a_popup.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='clipboard',
)
