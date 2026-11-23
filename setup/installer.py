r"""One-file installer for ClipVault.

Everything the suite needs is packed inside this executable. Running it:

  1. copies ClipVault into %LOCALAPPDATA%\ClipVault
  2. frees Win+V by turning off the built-in Windows clipboard history
  3. frees PrtScn by turning off the Snipping Tool takeover
  4. registers itself to start at login
  5. starts it right away

No Python, no virtualenv, nothing to click through. Run with --uninstall to
reverse all of it, or --check to verify the payload without installing.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

APP_NAME = "ClipVault"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ClipVault"
DAEMON_EXE = "clipvault.exe"
NO_WINDOW = 0x08000000

MB_OK = 0x40
MB_ERROR = 0x10
MB_YESNO = 0x24
IDYES = 6


def message(text, title="ClipVault", flags=MB_OK):
    return ctypes.windll.user32.MessageBoxW(0, text, title, flags)


def payload_dir():
    """Where the bundled copy of the suite lives."""
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "payload"
    # running from source: use the built output next door
    return Path(__file__).resolve().parent.parent / "bin"


def install_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
    return Path(base) / APP_NAME


def stop_running():
    for exe in (DAEMON_EXE, "clipvault-popup.exe"):
        subprocess.run(["taskkill", "/F", "/IM", exe],
                       capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1.0)


def set_dword(subkey, name, value):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def free_the_hotkeys():
    """Win+V and PrtScn belong to Windows by default; take them back."""
    set_dword(r"Software\Microsoft\Clipboard", "EnableClipboardHistory", 0)
    set_dword(r"Control Panel\Keyboard", "PrintScreenKeyForSnippingEnabled", 0)


def restore_the_hotkeys():
    set_dword(r"Software\Microsoft\Clipboard", "EnableClipboardHistory", 1)
    set_dword(r"Control Panel\Keyboard", "PrintScreenKeyForSnippingEnabled", 1)


def set_autostart(exe_path):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, '"%s"' % exe_path)


def clear_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except Exception:
        pass


def start_menu_shortcut(target):
    """A .lnk in the Start Menu. Best effort - the Run entry is what matters."""
    try:
        import win32com.client
    except Exception:
        return
    try:
        programs = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
        programs.mkdir(parents=True, exist_ok=True)
        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortcut(str(programs / "ClipVault.lnk"))
        link.TargetPath = str(target)
        link.WorkingDirectory = str(target.parent)
        link.Description = "ClipVault - clipboard history, press Win+V"
        link.Save()
    except Exception:
        pass


def install():
    source = payload_dir()
    daemon = source / DAEMON_EXE
    if not daemon.is_file():
        message("This installer is missing its payload.\n\nExpected:\n%s" % daemon,
                flags=MB_ERROR)
        return 1

    target = install_dir()
    stop_running()

    try:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
    except Exception as exc:
        message("Could not write to:\n%s\n\n%s" % (target, exc), flags=MB_ERROR)
        return 1

    installed_daemon = target / DAEMON_EXE
    try:
        free_the_hotkeys()
        set_autostart(installed_daemon)
        start_menu_shortcut(installed_daemon)
    except Exception as exc:
        message("Installed, but could not finish registering it:\n\n%s" % exc,
                flags=MB_ERROR)

    try:
        subprocess.Popen([str(installed_daemon)], cwd=str(target),
                         creationflags=NO_WINDOW)
    except Exception as exc:
        message("Installed, but could not start it:\n\n%s" % exc, flags=MB_ERROR)
        return 1

    message(
        "ClipVault is installed and running.\n\n"
        "  Win+V      open your clipboard history\n"
        "  PrtScn     Flameshot screenshot (if Flameshot is installed)\n"
        "  Tray icon  pause capture, clear history, or quit\n\n"
        "It starts itself at login from now on. Your history is encrypted\n"
        "with your Windows account under %APPDATA%\\ClipVault.\n\n"
        "To remove it later, run this installer again with --uninstall."
    )
    return 0


def uninstall():
    if message("Remove ClipVault?\n\n"
               "Your saved clipboard history will be left where it is.",
               flags=MB_YESNO) != IDYES:
        return 0
    stop_running()
    clear_autostart()
    restore_the_hotkeys()
    try:
        shortcut = (Path(os.environ["APPDATA"]) /
                    "Microsoft/Windows/Start Menu/Programs/Clipboard Enhancement.lnk")
        shortcut.unlink(missing_ok=True)
    except Exception:
        pass
    shutil.rmtree(install_dir(), ignore_errors=True)
    message("Removed. Windows clipboard history and PrtScn are back to normal.\n\n"
            "Your saved clips are still in %APPDATA%\\ClipVault -\n"
            "delete that folder yourself if you want them gone.")
    return 0


def check():
    """Unpack somewhere harmless and report, without changing anything."""
    source = payload_dir()
    tmp = Path(tempfile.mkdtemp(prefix="clipcheck-"))
    try:
        shutil.copytree(source, tmp / "payload")
        daemon = tmp / "payload" / DAEMON_EXE
        files = [f for f in (tmp / "payload").rglob("*") if f.is_file()]
        lines = [
            "payload source  : %s" % source,
            "files unpacked  : %d" % len(files),
            "daemon present  : %s (%d bytes)" % (
                daemon.is_file(), daemon.stat().st_size if daemon.is_file() else 0),
            "would install to: %s" % install_dir(),
        ]
        report = chr(10).join(lines)
        print(report)
        # The installer is a windowed exe with nowhere to print, so leave
        # the report where a verification run can pick it up.
        try:
            out = Path(tempfile.gettempdir()) / "clipvault-installer-check.txt"
            out.write_text(report, encoding="utf-8")
        except Exception:
            pass
        return 0 if daemon.is_file() else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "--uninstall" in args or "/uninstall" in args:
        return uninstall()
    if "--check" in args:
        return check()
    return install()


if __name__ == "__main__":
    sys.exit(main())
