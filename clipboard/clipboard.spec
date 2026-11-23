# -*- mode: python ; coding: utf-8 -*-
"""Builds clipvault.exe and clipvault-popup.exe.

The two share one COLLECT, so Qt and the Python runtime are on disk once.

A stock PyQt6 bundle is around 116 MB, most of it things this program never
touches: a software OpenGL rasteriser, a PDF engine, Qt's network stack, and
image codecs for formats that never reach the clipboard. The prune list below
takes those out. Anything removed here that turns out to be needed shows up
immediately as a failure to start, not as a subtle bug - so if you add a
feature that uses one of these, delete it from the list.
"""

import os

block_cipher = None

HIDDEN = [
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtSvg',
    'PIL', 'win32gui', 'win32process', 'win32api', 'win32con', 'win32clipboard',
    'win32event', 'win32crypt', 'winreg',
    'clipboard_ui', 'clipboard_common', 'clipvault_crypto',
    'cryptography', 'argon2',
]

# Pulled in by default, never imported by this program.
EXCLUDES = [
    # Python's OpenSSL bindings: nothing here opens a socket, and the only
    # hashing is md5 for de-duplicating clips, which hashlib does with its
    # built-in _md5. Dropping these takes libcrypto-3.dll with them.
    # cryptography is unaffected - it links its own OpenSSL inside _rust.pyd.
    # Not urllib/http/email/xml: pathlib imports urllib, and PyInstaller's
    # own bootstrap imports pathlib, so removing it breaks start-up.
    'ssl', '_ssl', '_hashlib',
    'tkinter', 'unittest', 'pydoc', 'doctest', 'test', 'xmlrpc',
    'numpy', 'PySide6', 'PyQt5', 'matplotlib', 'setuptools', 'pip',
    'PIL.ImageTk', 'PIL.ImageQt', 'PIL.ImageShow',
    'PyQt6.QtNetwork', 'PyQt6.QtPdf', 'PyQt6.QtQml', 'PyQt6.QtQuick',
    'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets', 'PyQt6.QtPrintSupport',
    'PyQt6.QtDBus', 'PyQt6.QtTest', 'PyQt6.QtSql',
]

# Binaries to drop from the finished bundle, by file name.
#   opengl32sw  - 20 MB software GL rasteriser; the UI is plain QWidget and
#                 paints through Qt's raster engine, never OpenGL
#   Qt6Pdf      - PDF rendering
#   Qt6Network  - no sockets anywhere in this program
#   _avif/_webp - image codecs; clips are stored as PNG
#   q*.dll      - image format plugins for formats we neither read nor write
PRUNE = {
    'opengl32sw.dll',
    'qt6pdf.dll', 'qpdf.dll',
    'qt6network.dll',
    'qt6opengl.dll', 'qt6openglwidgets.dll',
    'qt6printsupport.dll', 'qt6dbus.dll', 'qt6sql.dll', 'qt6test.dll',
    'qtuiotouchplugin.dll',
    'qicns.dll', 'qtga.dll', 'qtiff.dll', 'qwbmp.dll', 'qwebp.dll', 'qjpeg.dll',
    '_avif.cp312-win_amd64.pyd',
    '_webp.cp312-win_amd64.pyd',
    '_imagingtk.cp312-win_amd64.pyd',
    '_imagingcms.cp312-win_amd64.pyd',
    '_imagingmath.cp312-win_amd64.pyd',
    'libcrypto-3.dll', 'libssl-3.dll',
}


def prune(entries):
    kept = []
    for entry in entries:
        name = os.path.basename(entry[0]).lower()
        if name in PRUNE:
            continue
        kept.append(entry)
    return kept


def analysis(script):
    return Analysis(
        [script],
        pathex=['.'],
        binaries=[],
        datas=[],
        hiddenimports=HIDDEN,
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=EXCLUDES,
        win_no_prefer_redirects=False,
        win_private_assemblies=False,
        cipher=block_cipher,
        noarchive=False,
    )


a_popup = analysis('clipboard_popup.pyw')
pyz_popup = PYZ(a_popup.pure, a_popup.zipped_data, cipher=block_cipher)
exe_popup = EXE(
    pyz_popup, a_popup.scripts, [],
    exclude_binaries=True,
    name='clipvault-popup',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

a_daemon = analysis('clipboard_daemon.pyw')
pyz_daemon = PYZ(a_daemon.pure, a_daemon.zipped_data, cipher=block_cipher)
exe_daemon = EXE(
    pyz_daemon, a_daemon.scripts, [],
    exclude_binaries=True,
    name='clipvault',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

coll = COLLECT(
    exe_daemon,
    prune(a_daemon.binaries), a_daemon.zipfiles, a_daemon.datas,
    exe_popup,
    prune(a_popup.binaries), a_popup.zipfiles, a_popup.datas,
    strip=False,
    # UPX would roughly halve this, but packed binaries get flagged by
    # antivirus engines, and a download people are warned about is worse
    # than a large one.
    upx=False,
    upx_exclude=[],
    name='clipvault',
)
