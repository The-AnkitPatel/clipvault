"""A normal clip must NOT be seen as sensitive, or capture stops entirely."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clipboard"))
import sys, time
import win32clipboard, win32con
from clipboard_common import clip_is_sensitive, set_clip_text, get_clip_text

original = get_clip_text() or ""

set_clip_text("ordinary clipboard text, nothing secret here")
time.sleep(0.3)
plain = clip_is_sensitive()
print(f"normal clip   -> sensitive={plain}   (must be False)")

# Now write a clip flagged the way a password manager does
excl = win32clipboard.RegisterClipboardFormat("ExcludeClipboardContentFromMonitorProcessing")
hist = win32clipboard.RegisterClipboardFormat("CanIncludeInClipboardHistory")
for _ in range(5):
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, "hunter2-should-never-be-stored")
        win32clipboard.SetClipboardData(excl, b"\x00\x00\x00\x00")
        win32clipboard.SetClipboardData(hist, b"\x00\x00\x00\x00")
        win32clipboard.CloseClipboard()
        break
    except Exception:
        try: win32clipboard.CloseClipboard()
        except Exception: pass
        time.sleep(0.05)
time.sleep(0.3)
flagged = clip_is_sensitive()
print(f"flagged clip  -> sensitive={flagged}   (must be True)")

set_clip_text(original if original else " ")
print(f"\nRESULT: {'PASS' if (plain is False and flagged is True) else 'FAIL'}")
