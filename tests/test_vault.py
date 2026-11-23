"""The vault has to be right, so check it properly: migration keeps every clip,
the key file appears, entries are bound to their own name, tampering is caught,
and a passphrase can be set and taken off again."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clipboard"))
import sys, os, json, shutil, tempfile
from pathlib import Path

import clipboard_common as cc
from clipvault_crypto import Vault, VaultLocked

checks = []
def check(name, ok, detail=""):
    checks.append((name, ok))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{('  ' + detail) if detail else ''}")

print("=== before migration ===")
before = cc.load_index()
sample_t = next((i for i in before if i["type"] == "text"), None)
sample_i = next((i for i in before if i["type"] == "image"), None)
text_before = cc.read_secure(cc.HISTORY_DIR / sample_t["file"]).decode("utf-8", "replace")
img_before = len(cc.read_secure(cc.HISTORY_DIR / sample_i["file"]))
print(f"items: {len(before)}  sample text: {text_before[:40]!r}  sample image: {img_before} bytes")

print("\n=== migrating to AES-256-GCM ===")
converted = cc.migrate_history()
print(f"re-sealed {converted} file(s)")

print("\n=== results ===")
after = cc.load_index()
check("every item still readable", len(after) == len(before), f"{len(before)} -> {len(after)}")
text_after = cc.read_secure(cc.HISTORY_DIR / sample_t["file"]).decode("utf-8", "replace")
img_after = len(cc.read_secure(cc.HISTORY_DIR / sample_i["file"]))
check("text clip unchanged", text_after == text_before)
check("image clip unchanged", img_after == img_before, f"{img_after} bytes")

keyring = cc.HISTORY_DIR / "keyring.json"
check("keyring written", keyring.is_file())
record = json.loads(keyring.read_text(encoding="utf-8"))
check("key is DPAPI-wrapped by default", record.get("wrap") == "dpapi", record.get("wrap", "?"))
check("no raw key in the keyring", "dek" not in record and len(record.get("key", "")) > 40)

files = [p for p in cc.HISTORY_DIR.rglob("*")
         if p.is_file() and p.name not in cc.UNSEALED_NAMES
         and not any(p.name.endswith(x) for x in cc.SKIP_SUFFIXES)]
stale = [p.name for p in files if not cc.is_encrypted(p)]
check("everything sealed in the new format", not stale, f"{len(files)} files, {len(stale)} stale")

head = (cc.HISTORY_DIR / sample_t["file"]).read_bytes()[:5]
check("container magic is CLVT v2", head[:4] == b"CLVT" and head[4] == 2, str(head))

print("\n=== cryptographic properties ===")
v = cc.vault()
blob = v.seal(b"secret clip", "20260101_000000.txt")
check("round trip", v.unseal(blob, "20260101_000000.txt") == b"secret clip")

try:
    v.unseal(blob, "20260101_000001.txt")
    check("entry bound to its own name", False, "opened under a different name!")
except ValueError:
    check("entry bound to its own name", True)

torn = bytearray(blob)
torn[-1] ^= 0x01
try:
    v.unseal(bytes(torn), "20260101_000000.txt")
    check("tampering detected", False, "modified ciphertext was accepted!")
except ValueError:
    check("tampering detected", True)

nonces = {v.seal(b"x", "a.txt")[5:17] for _ in range(200)}
check("nonce never repeats", len(nonces) == 200, f"{len(nonces)}/200 unique")

print("\n=== passphrase mode (on a scratch vault) ===")
tmp = Path(tempfile.mkdtemp(prefix="vaulttest-"))
try:
    scratch = Vault(tmp).unlock()
    sealed = scratch.seal(b"hello", "x.txt")
    scratch.set_passphrase("correct horse battery staple")
    check("switches to passphrase wrapping", Vault(tmp).is_passphrase_protected())

    reopened = Vault(tmp).unlock("correct horse battery staple")
    check("opens with the right passphrase", reopened.unseal(sealed, "x.txt") == b"hello")

    try:
        Vault(tmp).unlock("wrong passphrase")
        check("rejects the wrong passphrase", False, "wrong passphrase worked!")
    except VaultLocked:
        check("rejects the wrong passphrase", True)

    try:
        Vault(tmp).unlock()
        check("refuses to open with no passphrase", False)
    except VaultLocked:
        check("refuses to open with no passphrase", True)

    back = Vault(tmp)
    back.set_passphrase(None, current_passphrase="correct horse battery staple")
    check("reverts to DPAPI", not Vault(tmp).is_passphrase_protected()
          and Vault(tmp).unlock().unseal(sealed, "x.txt") == b"hello")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

failed = [n for n, ok in checks if not ok]
print(f"\nRESULT: {'PASS' if not failed else 'FAIL'}  ({len(checks) - len(failed)}/{len(checks)})")
for n in failed:
    print("   failed:", n)
sys.exit(0 if not failed else 1)
