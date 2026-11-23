"""
Launcher entry point for clipboard-popup.
"""
import os
import sys
from pathlib import Path

# Ensure directory is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

import clipboard_popup

if __name__ == "__main__":
    clipboard_popup.main()
