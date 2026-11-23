# Windows Enhancement Suite
**OS:** Windows 10 / 11 | 1:1 Feature & UI Parity with `E:\linux-enhancements`

## What's included

### 1. Clipboard Manager & Flameshot Integration
- **PrintScreen (PrtScn)**: Triggers the Flameshot screenshot GUI overlay directly. Annotate, box, blur, and hit Enter/Copy — screenshots are instantly captured into the history.
- **Win+V** (or **Alt+V**): Opens the AMOLED clipboard history popup anywhere on screen, and closes it again. The window is built once when the daemon starts and kept warm, so opening it costs about 35 ms — there is no process to launch.
- **Collapsible sections**: A disclosure triangle (▶ / ▼) next to **PINNED** and **RECENT** folds that section away. Your choice is remembered between sessions.
- **Encrypted at rest**: Every clip, thumbnail and the index itself are encrypted with Windows DPAPI, tied to your account. Another user on the machine, or anyone reading the files off the disk, gets ciphertext. Existing history is converted automatically on first run.
- **Keeps formatting**: HTML and RTF are stored next to the plain text, so a clip copied out of Word or a browser pastes back with its formatting rather than as flat text.
- **Copied files**: Copy files in Explorer and they land in the history as a `FILES` entry; pasting them puts the real files back on the clipboard.
- **Tray icon**: Open the popup, pause capture, clear history or quit — no Task Manager needed.
- **Glide to select**: Press on a row and drag **down** the list — every row you pass joins the multi-paste queue in order, and the list scrolls itself as you reach the edge so you can see how far the selection has got. Drag back **up** over them and they drop out again, so an overshoot is undone by reversing rather than starting over. A plain click still pastes.
- **Cancel vs Clear all**: While something is picked, a red ✕ **Cancel** button appears next to **Clear all** — one drops the selection, the other wipes unpinned history. They are never the same button.
- **Two-line previews**: Long clips wrap onto a second line and end in an ellipsis instead of running past the edge of the row.
- **Secrets stay out**: Clips that the source app marks as not-for-history (password managers, browser password fields, RDP) are never written to disk.
- **Auto Capture & Indexing**: Event-driven clipboard listener (`WM_CLIPBOARDUPDATE`) with zero CPU polling and zero clipboard lock contention.
- **Thumbnails & Badges**: Real smooth scaled thumbnails (`76x52`), `IMG` badges, file sizes, and automatic source application tagging (`from vscode`, `from screenshot`, `from chrome`, etc.). Thumbnails are cached on disk so a long history stays quick to open.
- **Square edges**: Every corner in the popup is a hard 90 degrees — no rounding anywhere.
- **Persistence**: Items and images persist across reboots and 10+ hour sessions (up to 200 items).
- **Fast Single Paste**: Click any item or press **Enter** on the highlighted row to paste directly into your active window.
- **Multi-Paste**: Click `○` or press **Tab** on items to queue them (labeled with pick order `1`, `2`, `3`...), then press **Enter** or click "Paste selected ⏎" to paste all in exact sequence (text items combined cleanly with newlines, images pasted in order).
- **Pinning**: Click **★** to pin items so they never expire and survive "Clear all".
- **Delete & Clear All**: Click **✕** to delete individual items, or **Clear all** to wipe unpinned items while keeping pinned ones.
- **Live Search**: Instant filtering by text preview or application name.
- **Keyboard Navigation**: Up / Down arrows to browse, Tab to queue, Delete to remove, Enter to paste, Escape to dismiss.

## Install / Setup

### On a new PC (the easy way)

Download **`ClipboardEnhancementSetup.exe`** from the Releases page and run it.
That one file carries the whole suite - no Python, no virtualenv, nothing to
configure. It copies itself into `%LOCALAPPDATA%\ClipboardEnhancement`, frees
**Win+V** and **PrtScn** from Windows, registers itself to start at login and
launches straight away. Press **Win+V** and it is there.

To remove it, run the same file with `--uninstall`:

```cmd
ClipboardEnhancementSetup.exe --uninstall
```

Flameshot is optional - install it separately if you want **PrtScn** to open the
screenshot overlay. Everything else works without it.

### Building it yourself

```cmd
clipboard\build-exe.bat        rem builds bin\clipboard-daemon.exe and the popup
setup\build-installer.bat      rem packs bin\ into the single setup .exe
```

The first step needs the `.venv` described in `requirements.txt`.

### Installing from this folder (development)


Run `install.bat` inside `E:\windows-enhancements` (or double-click it):

```cmd
cd /d E:\windows-enhancements
install.bat
```

The installer will:
1. Initialize the Python virtual environment with PyQt6, Pillow, and pywin32.
2. Disable the Windows native clipboard history conflict so **Win+V** is dedicated to this suite.
3. Disable Windows Snipping Tool PrintScreen takeover so **PrtScn** triggers Flameshot.
4. Add silent auto-start entries for both the daemon and Flameshot to your Windows Startup folder (`shell:startup`).
5. Start the daemon in the background immediately.

After that it looks after itself. On every start the daemon re-writes its own
`HKCU\...\Run` entry to wherever it is actually installed and re-applies the two
Windows settings above, so a cleanup tool, a Windows update or a settings sync
cannot quietly break Win+V. There is nothing to set up again after a reboot.

## Uninstall / Revert

Run `uninstall.bat` (or double-click it):

```cmd
cd /d E:\windows-enhancements
uninstall.bat
```

This terminates the daemon, removes startup scripts, and restores Windows's built-in clipboard history and PrintScreen settings.

