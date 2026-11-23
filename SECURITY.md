# Security

ClipVault keeps a copy of everything you copy. That is a sensitive thing to
hold, so this document says exactly what protects it, and - just as
importantly - what does not.

## What is stored

Everything lives under `%APPDATA%\ClipVault`:

| File | Contents |
|---|---|
| `index.json` | the list of clips: id, type, timestamp, preview text, source app, pinned flag |
| `<id>.txt` / `.png` / `.files` | the clip itself |
| `<id>.fmt` | HTML and RTF versions of a text clip |
| `thumbs/<id>.png` | 76x52 preview of an image clip |
| `popup-settings.json` | which sections you collapsed |
| `keyring.json` | the wrapped data key - **not** sealed, see below |
| `clipvault.log` | what the daemon did, not what you copied |

Every one of those except `keyring.json` and the log is sealed. The log
records events ("saved text from chrome"), never clip contents, except for the
first 40 characters of a preview at INFO level.

## How it is sealed

**AES-256-GCM**, one random 256-bit data key for the whole store.

- The data key is generated on first run by the OS CSPRNG
  (`AESGCM.generate_key`). It is never derived from anything in the source, so
  publishing this code does not weaken it.
- Each file gets a fresh random 96-bit nonce. Nonces are never reused, and
  never counted or derived - they come from `secrets.token_bytes`.
- GCM gives integrity as well as confidentiality. A modified file is rejected,
  not silently returned as garbage.
- The file's path inside the store is passed as **additional authenticated
  data**. A sealed clip therefore cannot be renamed into another entry, and a
  thumbnail cannot be swapped for the full image it came from.
- The container is `CLVT` + version + nonce + ciphertext, so the format can
  change without a flag day. Older containers are read transparently and
  rewritten on the next start.

## How the key is kept

The data key is itself wrapped. Two ways:

**DPAPI (the default).** `CryptProtectData` under your Windows account, with
an application-specific entropy value. Windows derives the wrapping key from
your logon credentials. Nothing to remember, nothing to type, and the key file
is useless on another machine or to another user on this one. The key file is
also ACL'd to your account only (`icacls /inheritance:r`).

**A passphrase (opt-in).** The wrapping key is derived with **Argon2id** -
128 MiB, 4 passes, 4 lanes, 16-byte random salt - and the data key is wrapped
with AES-256-GCM under it. ClipVault then asks for the passphrase when it
starts, three attempts, and exits rather than running with a store it cannot
read.

Switching between the two only rewraps the data key. Nothing already stored is
re-encrypted, so it is instant.

> If you set a passphrase and forget it, your history is gone. There is no
> recovery path, by design.

## What this protects against

- Another user on the same machine reading your clips.
- Someone pulling the drive, or restoring a backup or file-sync copy of
  `%APPDATA%` on another machine.
- A file-manager or search-indexer stumbling over your clipboard contents.
- Silent corruption or deliberate modification of a stored clip.

## What it does not protect against

Be clear-eyed about this:

- **Malware running as you, right now.** With DPAPI wrapping, anything running
  under your account can call `CryptUnprotectData` exactly as ClipVault does.
  A passphrase defeats this only while ClipVault is not running - once it is
  unlocked, the key is in the process's memory.
- **Memory.** Python cannot reliably zero a `bytes` object, and the garbage
  collector may copy it. The data key and decrypted clips exist in memory
  while the process runs and may reach a page file or crash dump. This is a
  real limitation of implementing it in Python.
- **The clipboard itself.** Anything on the Windows clipboard is readable by
  every process on your desktop. ClipVault protects the history it writes
  down, not the clipboard.
- **Someone at your unlocked machine.** Press Win+V and the clips are there.
  That is the point of the program.

## Clips that are never stored

Applications can mark a clip as not for clipboard history, using the
`ExcludeClipboardContentFromMonitorProcessing` and `CanIncludeInClipboardHistory`
clipboard formats. Password managers, browser password fields, remote desktop
clients and banking apps all do. ClipVault honours both and never writes those
clips to disk - the same signal Windows' own clipboard history respects.

If you find an application whose secrets are being captured, that application
is not setting the flag. Please open an issue naming it.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Open a GitHub
security advisory on the repository instead, and allow a little time for a fix
before disclosing.

## Auditing it yourself

The whole of the cryptography is in one file,
[`clipboard/clipvault_crypto.py`](clipboard/clipvault_crypto.py) - about 300
lines, no custom primitives, built on
[pyca/cryptography](https://github.com/pyca/cryptography). `tests/test_vault.py`
checks round trips, the additional-data binding, tamper detection, nonce
uniqueness and both wrapping modes.
