"""
ClipVault - clipboard history daemon for Windows — monitors clipboard via native WM_CLIPBOARDUPDATE,
saves text and images (including Flameshot screenshots) to %APPDATA%/clipboard-history/
with active window app metadata.
Provides global Win+V, Alt+V, and PrintScreen (Flameshot) hotkey handling.

Architecture:
  - WH_KEYBOARD_LL hook intercepts Win+V, Alt+V, PrtScn BEFORE Windows processes them
  - WM_CLIPBOARDUPDATE via AddClipboardFormatListener for zero-poll clipboard monitoring
  - Single-thread ctypes GetMessage loop pumps both LL hook callbacks and window messages
"""

import os
import sys
from pathlib import Path

class _NullWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None: sys.stdout = _NullWriter()
if sys.stderr is None: sys.stderr = _NullWriter()

# Ensure package directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import time
import base64
import hashlib
import json
import logging
import logging.handlers
import threading
import subprocess
from datetime import datetime

import ctypes
from ctypes import wintypes
import win32gui
import win32process
import win32api
import win32con
import win32event
import winerror

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import QTimer, Qt, QRect
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QAction

# Shared definitions
from clipboard_common import (
    HISTORY_DIR, INDEX_FILE, LOG_FILE, MAX_ITEMS,
    load_index, save_index, active_app, fmt_label,
    get_clip_text, get_clip_image_bytes, find_flameshot_exe, clip_is_sensitive,
    get_clip_rich, get_clip_files, write_secure, migrate_history,
    unlock_vault, vault_needs_passphrase
)
from clipvault_crypto import VaultLocked

# Rotating, so a machine left running for months does not end up with a
# multi-megabyte log file.
_handler = logging.handlers.RotatingFileHandler(
    str(LOG_FILE), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logging.basicConfig(level=logging.INFO, handlers=[_handler])

# ── Global State ─────────────────────────────────────────────────────────────
last_hash = None
popup_proc = None       # only used by the subprocess fallback
qt_app = None
popup_window = None
tray_icon = None
capture_paused = False
listener_hwnd = None
_c_proc_holder = None
_wndclass_holder = None
_mutex_holder = None
_h_ll_hook = None
_ll_proc_holder = None

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_USER_POPUP = 0x0400 + 101
WM_USER_FLAMESHOT = 0x0400 + 102

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_ulonglong),
    ]

# ── ctypes prototypes (64-bit safe) ──────────────────────────────────────────
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_longlong
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = ctypes.c_longlong

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.AddClipboardFormatListener.argtypes = [wintypes.HWND]
user32.AddClipboardFormatListener.restype = wintypes.BOOL
user32.RemoveClipboardFormatListener.argtypes = [wintypes.HWND]
user32.RemoveClipboardFormatListener.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL

# Which combos RegisterHotKey actually claimed. Where it succeeded, Windows
# both delivers WM_HOTKEY and swallows the keystroke for us, so the low-level
# hook must stay out of the way.
hotkey_owned = {"winv": False, "altv": False, "prtscn": False}

VK_NONAME = 0xFC  # unassigned VK, reserved: safe to inject

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', ctypes.c_uint),
        ('style', ctypes.c_uint),
        ('lpfnWndProc', WNDPROCTYPE),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HICON),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
        ('hIconSm', wintypes.HICON),
    ]

user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.CreateWindowExW.restype = wintypes.HWND


def safe_print(*args, **kwargs):
    if sys.stdout:
        try:
            print(*args, **kwargs, flush=True)
        except Exception:
            pass


def acquire_single_instance():
    mutex_name = "Global\\ClipVaultDaemon"
    mutex = win32event.CreateMutex(None, False, mutex_name)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        safe_print("ClipVault is already running -- exiting.")
        sys.exit(0)
    return mutex


def save_item(data: bytes, kind: str, ext: str, preview: str, app: str = "",
              rich: dict = None):
    index = load_index()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{ts}.{ext}"
    filepath = HISTORY_DIR / filename

    write_secure(filepath, data)

    # HTML / RTF travel in a sidecar so pasting back into Word or a browser
    # keeps its formatting instead of collapsing to flat text.
    rich_name = ""
    if rich:
        try:
            payload = {k: base64.b64encode(v).decode("ascii") for k, v in rich.items()}
            rich_name = f"{ts}.fmt"
            write_secure(HISTORY_DIR / rich_name, json.dumps(payload).encode("utf-8"))
        except Exception as e:
            rich_name = ""
            logging.warning("could not store rich formats: %s", e)

    index.insert(0, {
        "id": ts, "type": kind, "file": filename,
        "time": datetime.now().isoformat(timespec="seconds"),
        "preview": preview, "app": app, "pin": False, "rich": rich_name,
    })

    unpinned = [i for i in index if not i.get("pin")]
    while len(unpinned) > MAX_ITEMS:
        old = unpinned.pop()
        index.remove(old)
        try:
            (HISTORY_DIR / old["file"]).unlink(missing_ok=True)
            if old.get("rich"):
                (HISTORY_DIR / old["rich"]).unlink(missing_ok=True)
        except Exception:
            pass

    save_index(index)


def process_clipboard_update():
    global last_hash
    if capture_paused:
        return
    time.sleep(0.04)

    # Never record a clip the source app flagged as secret.
    try:
        if clip_is_sensitive():
            logging.info("Skipped a clip marked as not-for-history")
            return
    except Exception as e:
        logging.warning("sensitivity check failed: %s", e)

    # Files copied in Explorer come through as paths, not bytes.
    try:
        paths = get_clip_files()
        if paths:
            raw = "\n".join(paths).encode("utf-8")
            h = hashlib.md5(raw).hexdigest()
            if h != last_hash:
                last_hash = h
                app = active_app()
                names = ", ".join(Path(p).name for p in paths[:4])
                if len(paths) > 4:
                    names += f" +{len(paths) - 4} more"
                preview = f"{len(paths)} file(s): {names}"
                save_item(json.dumps(paths).encode("utf-8"), "files", "files", preview, app)
                logging.info("Saved %d copied file path(s) from %s", len(paths), app)
            return
    except Exception as e:
        logging.warning("process files update error: %s", e)

    try:
        img_bytes = get_clip_image_bytes()
        if img_bytes:
            h = hashlib.md5(img_bytes[:4096]).hexdigest()
            if h != last_hash:
                last_hash = h
                app = active_app()
                preview = f"{fmt_label(app)}  ({len(img_bytes)//1024}KB)"
                save_item(img_bytes, "image", "png", preview, app)
                logging.info(f"Saved image from {app} ({len(img_bytes)} bytes)")
            return
    except Exception as e:
        logging.warning("process image update error: %s", e)

    try:
        text = get_clip_text()
        if text and text.strip():
            raw = text.encode("utf-8")
            h = hashlib.md5(raw).hexdigest()
            if h != last_hash:
                last_hash = h
                app = active_app()
                preview = text[:300].replace("\r\n", " ").replace("\n", " ").strip()
                save_item(raw, "text", "txt", preview, app, rich=get_clip_rich())
                # Never the clip itself: this log sits in the same folder as
                # the sealed store, in plain text, and a preview is still the
                # user's data. Length and source are enough to debug with.
                logging.info("Saved %d chars of text from %s", len(text), app)
    except Exception as e:
        logging.warning("process text update error: %s", e)


def resolve_popup_cmd():
    """Base command that starts the popup.

    When PyInstaller has frozen this daemon, sys.executable is
    clipboard-daemon.exe and __file__ points inside the bundle — feeding
    either to Popen just restarts the daemon (which then exits on the
    single-instance mutex) and no popup ever appears. So resolve the sibling
    clipvault-popup.exe when frozen, and the venv interpreter when running
    from source.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for cand in (exe_dir / "clipvault-popup.exe",
                     exe_dir.parent / "bin" / "clipvault-popup.exe"):
            if cand.is_file():
                return [str(cand)]
        logging.error("frozen build could not find clipvault-popup.exe near %s", exe_dir)
        return None

    here = Path(__file__).resolve().parent
    root = here.parent
    script = here / "clipboard_popup.pyw"
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if pythonw.is_file() and script.is_file():
        return [str(pythonw), str(script)]
    packaged = root / "bin" / "clipvault-popup.exe"
    if packaged.is_file():
        return [str(packaged)]
    if script.is_file():
        return [sys.executable, str(script)]
    logging.error("could not resolve a popup command from %s", here)
    return None


def toggle_popup(target_hwnd):
    """Win+V handler. Runs on the Qt main thread via QTimer.singleShot.

    The window is built once at startup and kept hidden, so this is a show,
    not a process start - which is the whole difference between Win+V feeling
    instant and feeling like it hangs.
    """
    global popup_window
    if popup_window is None:
        launch_popup(target_hwnd)
        return
    try:
        if popup_window.isVisible():
            popup_window.hide()
            return
        popup_window.reopen(target_hwnd)
    except Exception as e:
        logging.exception("toggle_popup failed, falling back to a process: %s", e)
        launch_popup(target_hwnd)


def request_popup(target_hwnd):
    """Called from the hook / window proc: never do GUI work inside a Win32
    callback, hand it to the event loop instead."""
    QTimer.singleShot(0, lambda: toggle_popup(target_hwnd))


def launch_popup(target_hwnd):
    """Fallback: start the separate popup process (used only if the in-process
    window could not be created)."""
    global popup_proc
    try:
        # Win+V while the popup is open closes it again.
        if popup_proc and popup_proc.poll() is None:
            try:
                popup_proc.kill()
                popup_proc = None
                return
            except Exception:
                pass

        cmd = resolve_popup_cmd()
        if not cmd:
            return
        if target_hwnd:
            cmd = cmd + ["--target-hwnd", str(target_hwnd)]

        logging.info(f"Spawning popup: {cmd}")
        popup_proc = subprocess.Popen(cmd)
        logging.info(f"Popup PID: {popup_proc.pid}")

        # Best effort: let the popup claim the foreground even though it is
        # being started by a background process.
        try:
            user32.AllowSetForegroundWindow(popup_proc.pid)
        except Exception:
            pass
    except Exception as e:
        logging.warning("failed to launch popup: %s", e)


def launch_flameshot():
    flameshot_exe = find_flameshot_exe()
    if flameshot_exe and os.path.isfile(flameshot_exe):
        try:
            logging.info(f"Launching Flameshot: {flameshot_exe}")
            subprocess.Popen([flameshot_exe, "gui"])
        except Exception as e:
            logging.warning("failed to launch flameshot: %s", e)


def swallow_win_key():
    """Stop a swallowed Win+V from opening the Start menu.

    The hook eats the "V", so Windows sees the Win key pressed and released
    with nothing in between and pops the Start menu. Injecting one unassigned
    keystroke while Win is still down makes it a combination instead.
    """
    try:
        win32api.keybd_event(VK_NONAME, 0, 0, 0)
        win32api.keybd_event(VK_NONAME, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


def ll_keyboard_proc(nCode, wParam, lParam):
    """Low-level keyboard hook — runs on the message-pump thread.
    Fallback path for the combos RegisterHotKey could not claim."""
    try:
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kbd = KBDLLHOOKSTRUCT.from_address(lParam)
            vk = kbd.vkCode

            # PrtScn → Flameshot
            if vk == win32con.VK_SNAPSHOT and not hotkey_owned["prtscn"]:
                logging.info("LL_HOOK: PrtScn -> Flameshot")
                threading.Thread(target=launch_flameshot, daemon=True).start()
                return 1

            # V key with Win or Alt → Clipboard Popup
            if vk == ord('V'):
                lwin = user32.GetAsyncKeyState(win32con.VK_LWIN) & 0x8000
                rwin = user32.GetAsyncKeyState(win32con.VK_RWIN) & 0x8000
                alt  = user32.GetAsyncKeyState(win32con.VK_MENU) & 0x8000
                win_down = bool(lwin or rwin)
                if win_down or alt:
                    # Where RegisterHotKey succeeded, let Windows deliver
                    # WM_HOTKEY: it suppresses the keystroke cleanly, with no
                    # Start-menu side effect.
                    if win_down and hotkey_owned["winv"]:
                        return user32.CallNextHookEx(None, nCode, wParam, lParam)
                    if alt and not win_down and hotkey_owned["altv"]:
                        return user32.CallNextHookEx(None, nCode, wParam, lParam)

                    fg = user32.GetForegroundWindow()
                    which = 'Win+V' if win_down else 'Alt+V'
                    logging.info(f"LL_HOOK: {which} -> popup, target={fg}")
                    if win_down:
                        swallow_win_key()
                    request_popup(fg)
                    return 1
    except Exception as e:
        logging.exception("LL_HOOK exception: %s", e)

    return user32.CallNextHookEx(None, nCode, wParam, lParam)


def wndproc(hwnd, msg, wparam, lparam):
    try:
        if msg == 0x031D:  # WM_CLIPBOARDUPDATE
            threading.Thread(target=process_clipboard_update, daemon=True).start()
            return 0
        elif msg == 0x0312:  # WM_HOTKEY (secondary mechanism)
            hid = int(wparam)
            if hid in (1, 2):
                fg = user32.GetForegroundWindow()
                logging.info(f"WM_HOTKEY id={hid} -> popup, target={fg}")
                request_popup(fg)
                return 0
            elif hid in (3, 4):
                logging.info(f"WM_HOTKEY id={hid} -> flameshot")
                threading.Thread(target=launch_flameshot, daemon=True).start()
                return 0
        elif msg in (0x0002, 0x0082, 0x0012, 0x0010):
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    except Exception as e:
        logging.exception("wndproc exception: %s", e)
        return 0


def setup():
    """Create window, install clipboard listener, install LL hook, register hotkeys."""
    global _c_proc_holder, _wndclass_holder, _h_ll_hook, _ll_proc_holder, listener_hwnd

    _c_proc_holder = WNDPROCTYPE(wndproc)

    _wndclass_holder = WNDCLASSEXW()
    _wndclass_holder.cbSize = ctypes.sizeof(WNDCLASSEXW)
    _wndclass_holder.lpfnWndProc = _c_proc_holder
    _wndclass_holder.lpszClassName = "ClipVaultListener"
    _wndclass_holder.hInstance = kernel32.GetModuleHandleW(None)

    atom = user32.RegisterClassExW(ctypes.byref(_wndclass_holder))
    logging.info(f"RegisterClassExW atom={atom}")

    hwnd = user32.CreateWindowExW(
        0, "ClipVaultListener", "ClipVaultListenerWindow",
        0, 0, 0, 0, 0,
        wintypes.HWND(-3), None, _wndclass_holder.hInstance, None
    )
    logging.info(f"CreateWindowExW hwnd={hwnd}")

    if hwnd:
        listener_hwnd = hwnd
        res = user32.AddClipboardFormatListener(hwnd)
        logging.info(f"AddClipboardFormatListener={res}")

        # Install LL keyboard hook — MUST be on this thread, and this thread
        # MUST run a GetMessage loop (not PumpMessages) for the hook to fire.
        _ll_proc_holder = HOOKPROC(ll_keyboard_proc)
        _h_ll_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _ll_proc_holder, None, 0)
        logging.info(f"WH_KEYBOARD_LL hook handle={_h_ll_hook} (nonzero=OK)")

        # Secondary: try to register hotkeys (may fail if Windows owns Win+V)
        MOD_WIN = 0x0008; MOD_ALT = 0x0001; MOD_NOREPEAT = 0x4000
        r1 = user32.RegisterHotKey(hwnd, 1, MOD_WIN | MOD_NOREPEAT, ord('V'))
        r2 = user32.RegisterHotKey(hwnd, 2, MOD_ALT | MOD_NOREPEAT, ord('V'))
        r3 = user32.RegisterHotKey(hwnd, 3, MOD_NOREPEAT, win32con.VK_SNAPSHOT)
        hotkey_owned["winv"] = bool(r1)
        hotkey_owned["altv"] = bool(r2)
        hotkey_owned["prtscn"] = bool(r3)
        logging.info(f"RegisterHotKey Win+V={r1} Alt+V={r2} PrtScn={r3} "
                     f"(unclaimed combos fall back to the LL hook)")
    else:
        logging.error("Failed to create listener window")

    return hwnd


def ask_passphrase(attempt):
    """Prompt for the vault passphrase. Only reached if one has been set.

    Uses the app's own dialog rather than QInputDialog, so the first thing a
    user sees at login is not a system-framed box with a title bar.
    """
    from clipboard_ui import ask_secret
    head = ("Unlock ClipVault" if attempt == 0
            else "That passphrase did not open the vault")
    body = ("Your clipboard history is encrypted. Enter the passphrase to "
            "unlock it." if attempt == 0 else "Try again.")
    return ask_secret(None, head, body)


def open_the_vault():
    """Unlock the data key before anything touches the store.

    With the default DPAPI wrapping this is silent. If the user has set a
    passphrase, ask for it - three tries, then give up rather than run with an
    unreadable history.
    """
    if not vault_needs_passphrase():
        try:
            unlock_vault()
            return True
        except Exception as exc:
            logging.exception("could not unlock the vault: %s", exc)
            return False

    for attempt in range(3):
        passphrase = ask_passphrase(attempt)
        if passphrase is None:
            logging.info("passphrase prompt cancelled, exiting")
            return False
        try:
            unlock_vault(passphrase)
            logging.info("vault unlocked with passphrase")
            return True
        except VaultLocked:
            continue
        except Exception as exc:
            logging.exception("unlock failed: %s", exc)
            return False
    logging.warning("three wrong passphrases, exiting")
    return False


def ensure_autostart():
    """Keep this thing starting itself at login, with no help from the user.

    The Startup shortcut the installer made can be removed by cleanup tools or
    go stale if the folder moves, so the daemon also keeps an HKCU Run entry
    pointing at wherever it is actually running from. Both firing is harmless:
    the second instance exits on the single-instance mutex.
    """
    if not getattr(sys, "frozen", False):
        return
    import winreg
    exe = f'"{Path(sys.executable).resolve()}"'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            try:
                current, _ = winreg.QueryValueEx(key, "ClipVault")
            except FileNotFoundError:
                current = None
            if current != exe:
                winreg.SetValueEx(key, "ClipVault", 0, winreg.REG_SZ, exe)
                logging.info("autostart entry written -> %s", exe)
            # Drop the entry used before the rename, so it cannot start a
            # stale copy alongside this one.
            try:
                winreg.DeleteValue(key, "ClipboardEnhancementDaemon")
                logging.info("removed the pre-rename autostart entry")
            except FileNotFoundError:
                pass
    except Exception as e:
        logging.warning("could not ensure autostart: %s", e)


def ensure_windows_settings():
    """Re-assert the two settings this suite depends on, in case Windows or a
    settings sync turned them back on."""
    import winreg
    wanted = [
        (r"Software\Microsoft\Clipboard", "EnableClipboardHistory", 0),
        (r"Control Panel\Keyboard", "PrintScreenKeyForSnippingEnabled", 0),
    ]
    for sub, name, value in wanted:
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, sub, 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:
                    current, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    current = None
                if current != value:
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                    logging.info("reset %s key %s -> %s", sub, name, value)
        except Exception as e:
            logging.warning("could not set %s: %s", name, e)


def make_tray_pixmap():
    """Draw the tray glyph at runtime - a clipboard outline, square corners."""
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    painter.setPen(QColor("#f0f0f0"))
    painter.setBrush(QColor("#101010"))
    painter.drawRect(QRect(12, 12, 40, 46))        # board
    painter.setBrush(QColor("#f0f0f0"))
    painter.drawRect(QRect(24, 4, 16, 12))         # clip
    painter.setPen(QColor("#9a9a9a"))
    for i, y in enumerate((28, 36, 44)):
        painter.drawLine(20, y, 44 - i * 6, y)     # lines of text
    painter.end()
    return pix


def on_tray_activated(reason):
    if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                  QSystemTrayIcon.ActivationReason.DoubleClick):
        toggle_popup(user32.GetForegroundWindow())


def toggle_capture(checked):
    global capture_paused
    capture_paused = bool(checked)
    logging.info("clipboard capture %s", "paused" if capture_paused else "resumed")
    if tray_icon:
        tray_icon.setToolTip("ClipVault - capture paused" if capture_paused
                             else "ClipVault - Win+V for history")


def tray_clear_history():
    index = load_index()
    kept = []
    for it in index:
        if it.get("pin"):
            kept.append(it)
        else:
            try:
                (HISTORY_DIR / it["file"]).unlink(missing_ok=True)
            except Exception:
                pass
    save_index(kept)
    logging.info("history cleared from tray, %d pinned item(s) kept", len(kept))
    if popup_window is not None:
        try:
            popup_window.populate("")
        except Exception:
            pass


def build_tray_icon():
    """Give the daemon a face, so it can be opened and quit without the
    Task Manager."""
    global tray_icon
    try:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logging.warning("no system tray available")
            return
        tray_icon = QSystemTrayIcon(QIcon(make_tray_pixmap()))
        tray_icon.setToolTip("ClipVault - Win+V for history")

        menu = QMenu()
        act_open = QAction("Open clipboard	Win+V", menu)
        act_open.triggered.connect(lambda: toggle_popup(user32.GetForegroundWindow()))
        menu.addAction(act_open)
        menu.addSeparator()

        act_pause = QAction("Pause capture", menu)
        act_pause.setCheckable(True)
        act_pause.toggled.connect(toggle_capture)
        menu.addAction(act_pause)

        act_clear = QAction("Clear history (keep pinned)", menu)
        act_clear.triggered.connect(tray_clear_history)
        menu.addAction(act_clear)
        menu.addSeparator()

        act_quit = QAction("Quit", menu)
        act_quit.triggered.connect(lambda: qt_app.quit())
        menu.addAction(act_quit)

        tray_icon.setContextMenu(menu)
        tray_icon.activated.connect(on_tray_activated)
        tray_icon.show()
        logging.info("tray icon ready")
    except Exception as e:
        logging.exception("could not create tray icon: %s", e)


def build_popup_window():
    """Create the popup once, hidden, so the first Win+V is fast too."""
    global popup_window
    try:
        from clipboard_ui import ClipboardPopup
        popup_window = ClipboardPopup(target_hwnd=None, standalone=False)
        logging.info("popup window prebuilt and held warm")
    except Exception as e:
        popup_window = None
        logging.exception("could not prebuild the popup window: %s", e)


def main():
    global _mutex_holder, qt_app

    _mutex_holder = acquire_single_instance()

    safe_print(f"ClipVault started, storage: {HISTORY_DIR}")

    # Qt's event loop pumps the same message queue as GetMessage, so the
    # low-level keyboard hook and the clipboard listener window both keep
    # working while the popup lives in this process.
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)

    ensure_autostart()
    ensure_windows_settings()

    if not open_the_vault():
        return

    try:
        converted = migrate_history()
        if converted:
            logging.info("re-sealed %d stored file(s) in the current format", converted)
    except Exception as e:
        logging.warning("history migration failed: %s", e)

    hwnd = setup()
    build_popup_window()
    build_tray_icon()

    threading.Thread(target=process_clipboard_update, daemon=True).start()

    flameshot = "OK" if find_flameshot_exe() else "NOT FOUND"
    logging.info(f"ClipVault ready. Flameshot: {flameshot}")
    safe_print(f"[OK] Win+V / Alt+V -> Clipboard | PrtScn -> Flameshot ({flameshot})")

    try:
        qt_app.exec()
    except KeyboardInterrupt:
        pass
    finally:
        if _h_ll_hook:
            user32.UnhookWindowsHookEx(_h_ll_hook)
        if hwnd:
            user32.RemoveClipboardFormatListener(hwnd)


if __name__ == "__main__":
    main()
