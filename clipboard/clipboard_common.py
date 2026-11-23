"""
Shared constants, path resolvers, and Windows API utilities for the Clipboard Enhancement Suite.
"""

import os
import sys
import time
import json
import struct
import psutil
import hashlib
from io import BytesIO
from pathlib import Path
from datetime import datetime
from PIL import Image, BmpImagePlugin

import win32gui
import win32process
import win32api
import win32con
import win32clipboard

# Storage locations
APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
HISTORY_DIR = APPDATA_DIR / "ClipVault"
LEGACY_DIR  = APPDATA_DIR / "clipboard-history"
INDEX_FILE  = HISTORY_DIR / "index.json"
LOG_FILE    = HISTORY_DIR / "clipvault.log"
MAX_ITEMS   = 200


def _adopt_legacy_store():
    """Take over the store used before the rename, in one move.

    A rename on the same volume, so there is no window where the clips exist
    in two places or in neither.
    """
    try:
        if HISTORY_DIR.is_dir() and any(HISTORY_DIR.iterdir()):
            return
        if not (LEGACY_DIR.is_dir() and any(LEGACY_DIR.iterdir())):
            return
        if HISTORY_DIR.is_dir():
            HISTORY_DIR.rmdir()          # only reached when it is empty
        LEGACY_DIR.rename(HISTORY_DIR)
    except Exception:
        pass


_adopt_legacy_store()
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# The log kept its old name until the rename; carry it across so history of
# what the daemon did is not split across two files.
try:
    _old_log = HISTORY_DIR / "daemon.log"
    if _old_log.is_file() and not LOG_FILE.exists():
        _old_log.rename(LOG_FILE)
except Exception:
    pass

# -- Encryption at rest ------------------------------------------------------
# All of it lives in clipvault_crypto; this is just the file-level plumbing.
# Every stored file is sealed with AES-256-GCM under a random data key that is
# itself wrapped by DPAPI (or by an Argon2id-derived key, if a passphrase is
# set). The file's path inside the store is authenticated along with the
# contents, so entries cannot be swapped around.

from clipvault_crypto import Vault, VaultLocked

_VAULT = Vault(HISTORY_DIR)

# Files that must stay readable without the key, or that hold the key itself.
UNSEALED_NAMES = ("keyring.json", "keyring.tmp")
SKIP_SUFFIXES = (".log", ".tmp", ".log.1", ".log.2")


def vault() -> Vault:
    """The process-wide vault, unlocked on first use."""
    if not _VAULT.unlocked:
        _VAULT.unlock()
    return _VAULT


def unlock_vault(passphrase=None):
    """Explicit unlock, for the daemon's startup path."""
    return _VAULT.unlock(passphrase)


def vault_needs_passphrase() -> bool:
    return _VAULT.is_passphrase_protected()


def seal_label(path) -> str:
    """What gets authenticated alongside the contents: the path within the
    store, so a thumbnail cannot stand in for the full image it came from."""
    path = Path(path)
    try:
        return path.relative_to(HISTORY_DIR).as_posix()
    except ValueError:
        return path.name


def write_secure(path, data: bytes):
    """Seal, then swap into place so a reader never sees a half-written file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(vault().seal(data, seal_label(path)))
    tmp.replace(path)


def read_secure(path) -> bytes:
    path = Path(path)
    try:
        return vault().unseal(path.read_bytes(), seal_label(path))
    except Exception:
        return b""


def is_encrypted(path) -> bool:
    """True when the file is already in the current sealed format."""
    try:
        with open(path, "rb") as handle:
            return Vault.is_current(handle.read(len(Vault.MAGIC) + 1))
    except Exception:
        return False


def migrate_history():
    """Bring every stored file up to the current format.

    Handles both plain files from before any encryption and the first-format
    DPAPI containers. Safe to run on every start; it only touches what is out
    of date.
    """
    converted = 0
    targets = []
    try:
        targets += [p for p in HISTORY_DIR.iterdir() if p.is_file()]
        thumbs = HISTORY_DIR / "thumbs"
        if thumbs.is_dir():
            targets += [p for p in thumbs.iterdir() if p.is_file()]
    except Exception:
        return 0
    for path in targets:
        if path.name in UNSEALED_NAMES:
            continue
        if any(path.name.endswith(sfx) for sfx in SKIP_SUFFIXES):
            continue
        try:
            if is_encrypted(path):
                continue
            raw = path.read_bytes()
            if not raw:
                continue
            opened = vault().unseal(raw, seal_label(path))
            if not opened:
                continue
            write_secure(path, opened)
            converted += 1
        except Exception:
            pass
    return converted


# -- Rich clipboard flavours --------------------------------------------------
# Keeping only CF_UNICODETEXT means a clip copied out of Word or a browser comes
# back as flat text. These formats ride along with it.

RICH_FORMATS = ("HTML Format", "Rich Text Format")


def get_clip_rich():
    """Extra text formats on the clipboard right now, as {name: bytes}."""
    out = {}
    opened = False
    try:
        win32clipboard.OpenClipboard()
        opened = True
        for name in RICH_FORMATS:
            fmt = win32clipboard.RegisterClipboardFormat(name)
            if win32clipboard.IsClipboardFormatAvailable(fmt):
                data = win32clipboard.GetClipboardData(fmt)
                if isinstance(data, str):
                    data = data.encode("utf-8", errors="replace")
                if data:
                    out[name] = data
    except Exception:
        pass
    finally:
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    return out


def get_clip_files():
    """Paths behind a file copy in Explorer (CF_HDROP)."""
    opened = False
    try:
        win32clipboard.OpenClipboard()
        opened = True
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            data = win32clipboard.GetClipboardData(win32con.CF_HDROP)
            return [str(x) for x in data] if data else []
    except Exception:
        pass
    finally:
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    return []


def _make_hdrop(paths):
    """DROPFILES header followed by a double-null-terminated wide path list."""
    header = struct.pack("<IiiII", 20, 0, 0, 0, 1)   # pFiles, pt.x, pt.y, fNC, fWide
    body = "".join(p + "\0" for p in paths) + "\0"
    return header + body.encode("utf-16-le")


def set_clip_files(paths):
    paths = [p for p in paths if p]
    if not paths:
        return False
    blob = _make_hdrop(paths)
    for _ in range(5):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, blob)
            return True
        except Exception:
            time.sleep(0.02)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
    return False


def set_clip_text_rich(text, rich=None):
    """Put text back along with whatever formatting travelled with it."""
    rich = rich or {}
    for _ in range(5):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            for name, payload in rich.items():
                try:
                    fmt = win32clipboard.RegisterClipboardFormat(name)
                    win32clipboard.SetClipboardData(fmt, payload)
                except Exception:
                    pass
            return True
        except Exception:
            time.sleep(0.02)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
    return False


# Process name mapping for human-readable app badges
APP_NAMES = {
    "code": "vscode",
    "code-insiders": "vscode",
    "windowsterminal": "terminal",
    "powershell": "terminal",
    "pwsh": "terminal",
    "cmd": "terminal",
    "mintty": "terminal",
    "chrome": "chrome",
    "msedge": "edge",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
    "vivaldi": "vivaldi",
    "explorer": "files",
    "snippingtool": "screenshot",
    "screenclippinghost": "screenshot",
    "flameshot": "screenshot",
    "lightshot": "screenshot",
    "sharex": "screenshot",
    "spotify": "spotify",
    "notepad": "notepad",
    "notepad++": "notepad",
    "slack": "slack",
    "discord": "discord",
    "telegram": "telegram",
}

def find_flameshot_exe() -> str:
    """Find the path to flameshot.exe on the system."""
    candidates = [
        r"C:\Program Files\Flameshot\bin\flameshot.exe",
        r"C:\Program Files (x86)\Flameshot\bin\flameshot.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Flameshot\bin\flameshot.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Flameshot\bin\flameshot.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    import shutil
    which = shutil.which("flameshot")
    return which if which else ""

def load_index():
    """Read the index fresh from disk, decrypting it."""
    try:
        if INDEX_FILE.exists():
            raw = read_secure(INDEX_FILE)
            if raw:
                data = json.loads(raw.decode("utf-8"))
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []

def save_index(index_list):
    """Encrypt and write the index atomically."""
    write_secure(INDEX_FILE,
                 json.dumps(index_list, indent=2, ensure_ascii=False).encode("utf-8"))

def active_app():
    """Detect the active window process name (source app)."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "app"
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid <= 0:
            return "app"
        proc = psutil.Process(pid)
        name = proc.name().lower()
        if name.endswith(".exe"):
            name = name[:-4]
        return APP_NAMES.get(name, name or "app")
    except Exception:
        return "app"

def fmt_label(app):
    """e.g. screenshot-27/08/2026-9:45 AM"""
    now = datetime.now()
    hour = now.strftime("%I").lstrip("0") or "12"
    return f"{app}-{now.strftime('%d/%m/%Y')}-{hour}:{now.strftime('%M %p')}"

def clip_is_sensitive():
    """True when the app that owns the clipboard asked for this clip to stay
    out of clipboard history.

    Password managers, browser password fields, RDP and banking apps all set
    these formats; Windows' own clipboard history honours them, and so must
    this one, or secrets end up sitting in plain text under %APPDATA%.
    """
    exclude_fmt = win32clipboard.RegisterClipboardFormat(
        "ExcludeClipboardContentFromMonitorProcessing")
    history_fmt = win32clipboard.RegisterClipboardFormat(
        "CanIncludeInClipboardHistory")
    opened = False
    try:
        win32clipboard.OpenClipboard()
        opened = True
        if win32clipboard.IsClipboardFormatAvailable(exclude_fmt):
            return True
        if win32clipboard.IsClipboardFormatAvailable(history_fmt):
            raw = win32clipboard.GetClipboardData(history_fmt)
            if isinstance(raw, bytes) and len(raw) >= 4:
                # DWORD 0 == "keep this out of clipboard history"
                if int.from_bytes(raw[:4], "little") == 0:
                    return True
        return False
    except Exception:
        return False
    finally:
        if opened:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass


def get_clip_text():
    """Safely get text from clipboard with guaranteed cleanup."""
    for _ in range(3):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return data
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
                raw = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                if isinstance(raw, bytes):
                    return raw.decode("utf-8", errors="replace")
                return str(raw)
            return None
        except Exception:
            time.sleep(0.03)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
    return None

def get_clip_image_bytes():
    """Safely extract image bytes (PNG) from clipboard without PIL ImageGrab lock issues."""
    png_fmt = win32clipboard.RegisterClipboardFormat("PNG")
    for _ in range(4):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            # 1. Direct PNG format (used by Chrome, Flameshot, etc.)
            if win32clipboard.IsClipboardFormatAvailable(png_fmt):
                data = win32clipboard.GetClipboardData(png_fmt)
                if data:
                    return data
            # 2. CF_DIB format (standard Windows clipboard format)
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                dib_data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                if dib_data:
                    im = BmpImagePlugin.DibImageFile(BytesIO(dib_data))
                    buf = BytesIO()
                    im.save(buf, format="PNG")
                    return buf.getvalue()
            return None
        except Exception:
            time.sleep(0.04)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
    return None

def set_clip_text(text: str):
    """Set text on clipboard safely."""
    for _ in range(5):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            return True
        except Exception:
            time.sleep(0.02)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
    return False

def set_clip_image(image_path: Path):
    """Set image on clipboard using both CF_DIB and PNG formats for maximum compatibility."""
    if not image_path.exists():
        return False

    png_data = read_secure(image_path)
    if not png_data:
        return False
    try:
        im = Image.open(BytesIO(png_data))
        bmp_io = BytesIO()
        im.convert("RGB").save(bmp_io, "BMP")
        dib_data = bmp_io.getvalue()[14:]  # Strip 14-byte BITMAPFILEHEADER to leave CF_DIB
        bmp_io.close()
    except Exception:
        dib_data = None

    png_fmt = win32clipboard.RegisterClipboardFormat("PNG")

    for _ in range(5):
        opened = False
        try:
            win32clipboard.OpenClipboard()
            opened = True
            win32clipboard.EmptyClipboard()
            if dib_data:
                win32clipboard.SetClipboardData(win32con.CF_DIB, dib_data)
            win32clipboard.SetClipboardData(png_fmt, png_data)
            return True
        except Exception:
            time.sleep(0.02)
        finally:
            if opened:
                try:
                    win32clipboard.CloseClipboard()
                except Exception:
                    pass
    return False

def activate_target_window(hwnd):
    """Restore and bring target window to foreground, attaching thread inputs if needed."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        cur_thread = win32api.GetCurrentThreadId()
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_thread, _ = win32process.GetWindowThreadProcessId(fg_hwnd)
        if cur_thread != fg_thread:
            win32process.AttachThreadInput(cur_thread, fg_thread, True)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
            win32process.AttachThreadInput(cur_thread, fg_thread, False)
        else:
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
    except Exception:
        pass

def send_ctrl_v():
    """Release any modifier keys and simulate Ctrl+V."""
    # Ensure modifiers are released
    for vk in (win32con.VK_LWIN, win32con.VK_RWIN, win32con.VK_MENU, win32con.VK_SHIFT, win32con.VK_CONTROL):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)
    # Press Ctrl+V
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord('V'), 0, 0, 0)
    win32api.keybd_event(ord('V'), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
