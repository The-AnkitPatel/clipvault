"""Authenticated encryption for everything ClipVault keeps on disk.

Design, in short - the reasoning behind each choice is in SECURITY.md:

  * Every file is sealed with AES-256-GCM under one random 256-bit data key.
  * That data key is never in this source. It is generated on first run by the
    OS CSPRNG and stored wrapped: by Windows DPAPI under your account by
    default, or by a key derived from a passphrase with Argon2id if you turn
    that on.
  * The name of the file being sealed is fed in as additional authenticated
    data, so a sealed clip cannot be lifted out and replayed as a different
    entry, and the index cannot be swapped for an older one.
  * The container is versioned. Older containers - including the pre-1.0
    DPAPI-only format and plain unencrypted files - are read transparently and
    rewritten in the current format on the next run.

Being open source does not weaken any of this: there are no secrets in the
code, only in the keyring file, which never leaves the machine.
"""

import base64
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import win32crypt

# -- container format --------------------------------------------------------
MAGIC = b"CLVT"
VERSION = 2
NONCE_LEN = 12          # 96 bits, the size AES-GCM is specified for
KEY_LEN = 32            # AES-256
HEADER_LEN = len(MAGIC) + 1 + NONCE_LEN
AAD_PREFIX = b"clipvault/v2/"

# -- the format this replaces ------------------------------------------------
LEGACY_MAGIC = b"CLPE1\n"
LEGACY_ENTROPY = b"windows-enhancements/clipboard-history/v1"

# -- key wrapping ------------------------------------------------------------
KEYRING_NAME = "keyring.json"
DPAPI_DESCRIPTION = "ClipVault data key"
DPAPI_ENTROPY = b"clipvault/keyring/v2"

# Argon2id parameters. Comfortably above the RFC 9106 second recommended
# option, and still well under a second on a laptop.
ARGON2_TIME_COST = 4
ARGON2_MEMORY_KIB = 131072       # 128 MiB
ARGON2_PARALLELISM = 4
ARGON2_SALT_LEN = 16


class VaultLocked(Exception):
    """Raised when the data key cannot be unwrapped (wrong or no passphrase)."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _derive_kek(passphrase: str, salt: bytes) -> bytes:
    """Passphrase -> key-encryption key, via Argon2id."""
    from argon2.low_level import Type, hash_secret_raw
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_KIB,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def _lock_down(path: Path):
    """Strip inherited permissions so only this account can read the keyring."""
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r",
             "/grant:r", f"{os.environ.get('USERNAME', '')}:F"],
            capture_output=True, creationflags=0x08000000, timeout=10)
    except Exception:
        pass


class Vault:
    """Holds the data key and seals/unseals byte strings with it."""

    # Mirrored here so callers can inspect a container without importing the
    # module-level constants.
    MAGIC = MAGIC
    VERSION = VERSION
    HEADER_LEN = HEADER_LEN
    LEGACY_MAGIC = LEGACY_MAGIC

    def __init__(self, storage_dir):
        self.storage_dir = Path(storage_dir)
        self.keyring_path = self.storage_dir / KEYRING_NAME
        self._key = None
        self._aead = None

    # -- keyring ------------------------------------------------------------
    def _read_keyring(self):
        try:
            if self.keyring_path.is_file():
                data = json.loads(self.keyring_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return None

    def _write_keyring(self, record):
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.keyring_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp.replace(self.keyring_path)
        _lock_down(self.keyring_path)

    def is_passphrase_protected(self) -> bool:
        record = self._read_keyring()
        return bool(record and record.get("wrap") == "argon2id")

    def exists(self) -> bool:
        return self._read_keyring() is not None

    # -- wrapping -----------------------------------------------------------
    @staticmethod
    def _wrap_dpapi(key: bytes) -> dict:
        blob = win32crypt.CryptProtectData(
            key, DPAPI_DESCRIPTION, DPAPI_ENTROPY, None, None, 0)
        return {"wrap": "dpapi", "key": base64.b64encode(blob).decode("ascii")}

    @staticmethod
    def _unwrap_dpapi(record: dict) -> bytes:
        blob = base64.b64decode(record["key"])
        _descr, key = win32crypt.CryptUnprotectData(
            blob, DPAPI_ENTROPY, None, None, 0)
        return bytes(key)

    @staticmethod
    def _wrap_passphrase(key: bytes, passphrase: str) -> dict:
        salt = secrets.token_bytes(ARGON2_SALT_LEN)
        nonce = secrets.token_bytes(NONCE_LEN)
        kek = _derive_kek(passphrase, salt)
        wrapped = AESGCM(kek).encrypt(nonce, key, AAD_PREFIX + b"keyring")
        return {
            "wrap": "argon2id",
            "key": base64.b64encode(wrapped).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "kdf": {
                "name": "argon2id",
                "salt": base64.b64encode(salt).decode("ascii"),
                "time_cost": ARGON2_TIME_COST,
                "memory_kib": ARGON2_MEMORY_KIB,
                "parallelism": ARGON2_PARALLELISM,
            },
        }

    @staticmethod
    def _unwrap_passphrase(record: dict, passphrase: str) -> bytes:
        kdf = record["kdf"]
        kek = _derive_kek(passphrase, base64.b64decode(kdf["salt"]))
        nonce = base64.b64decode(record["nonce"])
        wrapped = base64.b64decode(record["key"])
        try:
            return AESGCM(kek).decrypt(nonce, wrapped, AAD_PREFIX + b"keyring")
        except InvalidTag:
            raise VaultLocked("wrong passphrase")

    # -- lifecycle ----------------------------------------------------------
    def unlock(self, passphrase=None):
        """Load the data key, creating one on first run. Returns self."""
        record = self._read_keyring()

        if record is None:
            key = AESGCM.generate_key(bit_length=KEY_LEN * 8)
            new = self._wrap_dpapi(key)
            new.update({"version": VERSION, "created": _now()})
            self._write_keyring(new)
        elif record.get("wrap") == "argon2id":
            if not passphrase:
                raise VaultLocked("this vault needs a passphrase")
            key = self._unwrap_passphrase(record, passphrase)
        else:
            try:
                key = self._unwrap_dpapi(record)
            except Exception as exc:
                raise VaultLocked(
                    "the data key belongs to a different Windows account") from exc

        self._key = key
        self._aead = AESGCM(key)
        return self

    @property
    def unlocked(self) -> bool:
        return self._aead is not None

    def set_passphrase(self, new_passphrase, current_passphrase=None):
        """Switch between DPAPI wrapping and a passphrase.

        Only the wrapping changes - the data key stays the same, so nothing
        already stored has to be re-encrypted. Pass None to go back to DPAPI.
        """
        if not self.unlocked:
            self.unlock(current_passphrase)
        record = self._read_keyring() or {}
        if new_passphrase:
            new = self._wrap_passphrase(self._key, new_passphrase)
        else:
            new = self._wrap_dpapi(self._key)
        new.update({
            "version": VERSION,
            "created": record.get("created", _now()),
            "rewrapped": _now(),
        })
        self._write_keyring(new)

    def rotate_key(self, reseal):
        """Generate a fresh data key and re-seal everything with it.

        `reseal` is handed the old and new vaults and is expected to rewrite
        the stored files; the keyring is only replaced once it returns.
        """
        if not self.unlocked:
            raise VaultLocked("unlock before rotating")
        old_key = self._key
        new_key = AESGCM.generate_key(bit_length=KEY_LEN * 8)

        previous = Vault(self.storage_dir)
        previous._key, previous._aead = old_key, AESGCM(old_key)
        upcoming = Vault(self.storage_dir)
        upcoming._key, upcoming._aead = new_key, AESGCM(new_key)

        reseal(previous, upcoming)

        record = self._wrap_dpapi(new_key)
        if self.is_passphrase_protected():
            raise VaultLocked("re-enter the passphrase after rotating")
        record.update({"version": VERSION, "created": _now(), "rotated": _now()})
        self._write_keyring(record)
        self._key, self._aead = new_key, AESGCM(new_key)

    # -- sealing ------------------------------------------------------------
    def seal(self, data: bytes, label: str) -> bytes:
        if not self.unlocked:
            raise VaultLocked("vault is locked")
        nonce = secrets.token_bytes(NONCE_LEN)
        sealed = self._aead.encrypt(nonce, data, AAD_PREFIX + label.encode("utf-8"))
        return MAGIC + bytes([VERSION]) + nonce + sealed

    def unseal(self, blob: bytes, label: str) -> bytes:
        """Open a container. Understands the two formats that came before."""
        if blob.startswith(MAGIC):
            if not self.unlocked:
                raise VaultLocked("vault is locked")
            version = blob[len(MAGIC)]
            if version != VERSION:
                raise ValueError(f"unknown container version {version}")
            nonce = blob[len(MAGIC) + 1:HEADER_LEN]
            try:
                return self._aead.decrypt(
                    nonce, blob[HEADER_LEN:], AAD_PREFIX + label.encode("utf-8"))
            except InvalidTag:
                raise ValueError(f"{label}: tampered with, or not ours")

        if blob.startswith(LEGACY_MAGIC):
            _descr, data = win32crypt.CryptUnprotectData(
                blob[len(LEGACY_MAGIC):], LEGACY_ENTROPY, None, None, 0)
            return bytes(data)

        # Anything older than that was never encrypted at all.
        return blob

    @staticmethod
    def is_current(blob: bytes) -> bool:
        return blob.startswith(MAGIC) and len(blob) > len(MAGIC) and blob[len(MAGIC)] == VERSION
