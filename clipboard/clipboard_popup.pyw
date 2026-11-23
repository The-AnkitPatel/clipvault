"""Standalone entry point for the clipboard popup window.

The window itself lives in clipboard_ui so the daemon can hold one warm.
"""

import sys
from pathlib import Path


class _NullWriter:
    def write(self, s): pass
    def flush(self): pass


if sys.stdout is None: sys.stdout = _NullWriter()
if sys.stderr is None: sys.stderr = _NullWriter()

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipboard_ui import main

if __name__ == "__main__":
    main()
