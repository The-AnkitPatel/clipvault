# Contributing to ClipVault

Patches are welcome. The project is small on purpose - read the whole thing in
an afternoon, change it without fear.

## Getting set up

You need Windows 10 or 11 (64-bit) and Python 3.12.

```cmd
git clone https://github.com/The-AnkitPatel/clipvault.git
cd clipvault
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Run it straight from source while you work on it - no build step:

```cmd
.venv\Scripts\python clipboard\clipboard_daemon.pyw
```

That gives you a console with the daemon's output. Press **Win+V** to open the
window. `Ctrl+C` stops it.

To look at only the window, without the daemon:

```cmd
.venv\Scripts\python clipboard\clipboard_popup.pyw
```

## Building

```cmd
clipboard\build-exe.bat        rem bin\clipvault.exe and bin\clipvault-popup.exe
setup\build-installer.bat      rem release\ClipVaultSetup.exe
```

The installer is just the `bin\` directory packed into one executable, so
build the suite first.

## Tests

The tests live in `tests\` and run against the real Windows clipboard, so they
are not hermetic - they set and read the clipboard of whoever runs them, and
restore it afterwards. Run them one at a time:

```cmd
.venv\Scripts\python tests\test_vault.py
.venv\Scripts\python tests\test_clipboard_formats.py
```

`test_vault.py` is the one that matters most. If you touch anything in
`clipvault_crypto.py`, it must still pass, and new behaviour needs a new check
in it.

## House style

- Standard library and `cryptography` over new dependencies. Every dependency
  ends up inside an 85 MB executable that somebody downloads.
- Comments explain *why*, not *what*. If a line needs a comment to say what it
  does, rewrite the line.
- Anything that runs inside a Win32 callback - window procedures, the
  low-level keyboard hook, `nativeEvent` - must not raise. An exception there
  takes down the process with no traceback. Wrap the body in `try/except`.
- Never call `super().nativeEvent()` in PyQt6. See the comment on
  `ClipboardPopup.nativeEvent` for what that cost.

## Reporting a security issue

Please read [SECURITY.md](SECURITY.md) and report privately rather than in a
public issue.
