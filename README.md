# ClipVault

A clipboard that remembers, on Windows - and keeps what it remembers
encrypted.

Press **Win+V** and your last 200 clips are there in about 38 milliseconds:
text, images, screenshots, files you copied in Explorer. Pin the ones you want
to keep. Pick several and paste them in order. Everything it writes down is
sealed with AES-256-GCM.

Built because Windows' own clipboard history is slow to open, stores your
clips in plain text, and forgets images the moment you reboot.

---

## Install

Download **`ClipVaultSetup.exe`** from
[Releases](https://github.com/The-AnkitPatel/clipvault/releases) and run it.

That is the whole setup. One file, no Python, no options to pick. It installs
itself, takes Win+V and PrtScn back from Windows, starts at login from then
on, and opens straight away. You never configure it again.

To remove it:

```cmd
ClipVaultSetup.exe --uninstall
```

Windows 10 or 11, 64-bit. [Flameshot](https://flameshot.org/) is optional - if
you have it, PrtScn opens its screenshot overlay and the result lands in your
history.

---

## Using it

| | |
|---|---|
| **Win+V** / **Alt+V** | open the vault, or close it again |
| **Type** | filter by text or by the app it came from |
| **Up / Down** | move through the list |
| **Enter** | paste the highlighted clip, or the whole selection |
| **Tab** | add the highlighted clip to the selection |
| **Delete** | remove the highlighted clip |
| **Esc** | close |
| **PrtScn** | Flameshot screenshot, straight into the history |

With the mouse: click a row to paste it. Click ***** to pin, **x** to delete,
the circle to add it to a selection.

**Glide to select.** Press on a row and drag **down** - every row you pass
joins the selection, numbered in the order you picked them. Drag back **up**
and they drop out again, so overshooting costs nothing. The list scrolls
itself as you reach the edge. Then **Enter**, or "Paste selected".

Text clips picked this way are joined and pasted once, so a single undo
reverses the lot. Images and files are pasted one after another in order.

**Pinned clips never expire** and survive "Clear all". While you have a
selection, a red **Cancel** appears next to **Clear all** - one drops the
selection, the other wipes unpinned history. They are never the same button.

The tray icon has: open, pause capture, clear history, quit.

---

## What it keeps

- **Text**, with its **HTML and RTF** versions alongside it - paste something
  copied from Word or a browser and the formatting comes back, instead of
  collapsing to flat text.
- **Images**, including screenshots, with real thumbnails and the file size.
- **Files** copied in Explorer - pasting puts the actual files back on the
  clipboard, not their names.
- **Where it came from**: `from chrome`, `from vscode`, `from screenshot`.

**What it refuses to keep:** clips that the source application marks as
not-for-history. Password managers, browser password fields and remote desktop
clients all set that flag, and ClipVault honours it - your passwords are never
written to disk.

---

## Security

Everything in the store is sealed with **AES-256-GCM** under a random 256-bit
key, generated on your machine on first run. That key is wrapped by **Windows
DPAPI** under your account - so the store is unreadable to another user, and
useless if the drive is taken out or a backup is restored elsewhere. Each
file's own path is authenticated along with its contents, so entries cannot be
swapped or replayed.

If you want more, you can wrap the key with a **passphrase** instead, derived
with **Argon2id**. ClipVault then asks for it at startup.

There are things this does not protect against - malware already running as
you, most of all. [SECURITY.md](SECURITY.md) spells out the threat model
honestly, including the limits, and the whole of the cryptography is one
300-line file you can read in a sitting:
[`clipvault_crypto.py`](clipboard/clipvault_crypto.py).

---

## Why the download is 70 MB

Fair question for something this small in scope. Almost none of it is
ClipVault:

| | |
|---|---|
| Qt (Core, Gui, Widgets, Svg + PyQt bindings) | ~38 MB |
| `cryptography` (its Rust core and OpenSSL) | ~14 MB |
| The Python runtime | ~8 MB |
| Pillow, pywin32, psutil | ~5 MB |
| **ClipVault itself** | **~120 KB of Python** |

The build already drops what is never used - the 20 MB software OpenGL
rasteriser, Qt's PDF and networking modules, and image codecs for formats that
never reach the clipboard. That took it from 117 MB to 75 MB. The prune list
is at the top of [`clipboard/clipboard.spec`](clipboard/clipboard.spec).

UPX would roughly halve it again, and is deliberately not used: antivirus
engines treat packed executables as a malware signal, and a download people
are warned about is worse than a large one.

Getting below ~10 MB means not shipping Qt and Python at all - a rewrite
against the Win32 API in a compiled language. That is a different project, not
a build flag. The resident footprint is ~85 MB, which is the price of keeping
the window built and ready so Win+V is instant.

## Why it is fast

The window is built once, when the daemon starts, and kept warm. Win+V shows
an existing window instead of starting a process - 820 ms became 38 ms.
Clipboard changes arrive as Windows events rather than being polled for, so it
costs nothing while you are not copying. Rows render in chunks and thumbnails
are cached.

[ARCHITECTURE.md](ARCHITECTURE.md) goes through how it fits together.

---

## Building it yourself

```cmd
git clone https://github.com/The-AnkitPatel/clipvault.git
cd clipvault
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt

clipboard\build-exe.bat        rem bin\clipvault.exe and bin\clipvault-popup.exe
setup\build-installer.bat      rem release\ClipVaultSetup.exe
```

To run it from source while working on it, without building:

```cmd
.venv\Scripts\python clipboard\clipboard_daemon.pyw
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Where it puts things

| | |
|---|---|
| Program | `%LOCALAPPDATA%\ClipVault` |
| Clips, index, key | `%APPDATA%\ClipVault` |
| Starts at login via | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` |

Uninstalling leaves your clips where they are. Delete `%APPDATA%\ClipVault`
yourself if you want them gone.

---

## License

MIT - see [LICENSE](LICENSE).

Copyright (c) 2026 Ankit Patel.
