# How ClipVault works

Two executables, one of which you normally never see.

```
clipvault.exe          the daemon: hotkeys, capture, and the window itself
clipvault-popup.exe    the same window, standalone (for Open-Popup.bat)
ClipVaultSetup.exe     installer: the above packed into one file
```

## The daemon

`clipboard/clipboard_daemon.pyw` is a single process that runs a Qt event loop.
That one loop does four jobs at once, which is the key design decision in the
program:

1. **A low-level keyboard hook** (`WH_KEYBOARD_LL`) for the combinations
   Windows will not give up.
2. **A message-only window** with `AddClipboardFormatListener`, so clipboard
   changes arrive as `WM_CLIPBOARDUPDATE` rather than being polled for. Zero
   CPU when nothing is copied, and no fighting over the clipboard lock.
3. **The popup window**, built once at startup and kept hidden.
4. **A tray icon**.

Qt's event loop pumps the same Win32 message queue that `GetMessage` would, so
the hook and the listener window keep working inside it. That is why the whole
thing can be one process.

### Why the window lives in the daemon

It used to be a separate executable, started on each Win+V. Python start-up,
Qt start-up and building a hundred rows came to about 820 ms, which feels like
the key did not register.

Now the window is constructed when the daemon starts and simply shown on
Win+V - about 38 ms, measured. It refreshes only when `index.json` has changed
since the last time it was opened. The cost is roughly 80-130 MB of resident
memory, which is the same order as Windows' own clipboard history.

### Hotkeys

`RegisterHotKey` is tried first for Win+V, Alt+V and PrtScn. Where it succeeds,
Windows delivers `WM_HOTKEY` and suppresses the keystroke - clean, and no side
effects. Win+V is only available if the built-in clipboard history is off,
which the installer takes care of.

Where registration fails, the low-level hook handles the combination instead
and swallows the keystroke. Swallowing the "V" of a Win+V leaves Windows
seeing the Win key pressed and released on its own, which opens the Start
menu, so the hook injects one unassigned keystroke to turn it back into a
combination.

GUI work is never done inside the hook or the window procedure. Both post the
request to the event loop with `QTimer.singleShot(0, ...)`; an exception
inside a Win32 callback terminates the process without a traceback.

## Capture

`WM_CLIPBOARDUPDATE` arrives, and `process_clipboard_update` looks at what is
on the clipboard, in this order:

1. **Not-for-history flags** - if present, nothing is stored at all.
2. **Files** (`CF_HDROP`) - the paths are stored, not the file contents.
3. **Images** - the `PNG` format if the application offered one, otherwise
   `CF_DIB` converted to PNG.
4. **Text** - `CF_UNICODETEXT`, and alongside it the `HTML Format` and
   `Rich Text Format` versions if they exist, so formatting survives a paste.

Each clip is hashed to avoid storing the same thing twice in a row.

## Storage

`%APPDATA%\ClipVault`, one file per clip plus `index.json`. Everything is
sealed - see [SECURITY.md](SECURITY.md). The index is written to a temporary
file and renamed into place, so a reader never sees it half-written.

Up to 200 unpinned items are kept. Pinned items never expire and survive
"Clear all".

## The window

`clipboard/clipboard_ui.py`. PyQt6, styled with one stylesheet, no rounded
corners anywhere.

- **Rows are rendered in chunks.** Twelve are built before the window is
  shown, and the rest stream in twenty at a time on the event loop. Building
  all hundred first was most of the delay between the key and a window.
- **Previews are laid out by hand.** `ClipLabel` uses `QTextLayout` to clamp
  text to two lines and ellipsise the second, because Qt only elides single
  lines and a word-wrapped `QLabel` silently clips the overflow - which is
  what used to push the pin and delete buttons off the end of the row.
- **Thumbnails are cached on disk**, sealed like everything else. Decoding
  fifty full-size screenshots to draw 76x52 previews is what made the first
  open after a reboot slow.
- **Glide selection** tracks the direction of travel: downward adds rows to
  the paste queue, upward takes them back out, so an overshoot is undone by
  reversing. The list auto-scrolls near the edges. Hit-testing compares
  rectangles rather than asking `QApplication.widgetAt`, which would return
  whatever tooltip or foreign window happened to be on top.

## Pasting

The window hides itself, puts the clip back on the clipboard in every format
it was saved with, brings the previously focused window to the front - using
`AttachThreadInput`, since a background process is otherwise refused - and
sends Ctrl+V.

Multiple text clips are joined with newlines and pasted once, so a single undo
reverses it. Mixed or image selections are pasted one after another in pick
order.

## Staying installed

The daemon rewrites its own `HKCU\...\Run` entry to wherever it is actually
running from, and re-applies the two Windows settings it depends on, every
time it starts. A cleanup tool, a Windows update or a settings sync cannot
quietly break Win+V, and there is nothing to set up again after a reboot.

## Source map

| File | What it is |
|---|---|
| `clipboard/clipboard_daemon.pyw` | the daemon: hooks, capture, tray, event loop |
| `clipboard/clipboard_ui.py` | the window, rows, selection, pasting |
| `clipboard/clipboard_common.py` | storage, clipboard formats, Win32 helpers |
| `clipboard/clipvault_crypto.py` | all of the cryptography |
| `clipboard/clipboard_popup.pyw` | standalone entry point for the window |
| `clipboard/clipboard.spec` | PyInstaller build for both executables |
| `setup/installer.py` | the one-file installer |
| `tests/` | vault and clipboard-format tests |
