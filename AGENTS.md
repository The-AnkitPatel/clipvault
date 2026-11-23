# Agent Protocol for ClipVault

This repository (`ClipVault`) is a lightweight, secure, high-performance clipboard history tool for Windows.

## Non-Negotiable Core Rules

1. **Core Code Freeze:** Do not modify the core engine files (`clipboard/clipboard_daemon.pyw`, `clipboard/clipboard_common.py`, `clipboard/clipboard_ui.py`, `clipboard/clipvault_crypto.py`, `setup/installer.py`) unless specifically and explicitly requested by the user.
2. **Crypto & Security Invariants:**
   - Any changes touching security must maintain AES-256-GCM authenticated encryption at rest with random 96-bit nonces.
   - Additional Authenticated Data (AAD) MUST bind entry file paths to their payloads to prevent swap/replay attacks.
   - DPAPI and Argon2id key-wrapping mechanisms must never write raw plaintext DEKs to disk.
   - Sensitive clipboard formats (`ExcludeClipboardContentFromMonitorProcessing` and `CanIncludeInClipboardHistory`) must always be respected.
   - Always run `tests/test_vault.py` if anything related to data storage or crypto is modified.
3. **No Heavy Dependencies:** Maintain the minimal dependency footprint (PyQt6, Pillow, pywin32, psutil, cryptography, argon2-cffi). Never introduce heavyweight dependencies (e.g. web engines, OpenGL backends, remote telemetry) into the runtime.
4. **Documentation & Visuals:** Keep `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, and visual assets (`assets/`) aligned with actual implementation details.
