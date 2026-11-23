"""Rich text and copied files must survive a round trip through history."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clipboard"))
import sys, time, os
import win32clipboard, win32con
from clipboard_common import (get_clip_rich, set_clip_text_rich, get_clip_files,
                              set_clip_files, get_clip_text)

original = get_clip_text() or ""
results = []

# --- 1. HTML travels with the text ------------------------------------------
HTML = ("Version:0.9\r\nStartHTML:00000097\r\nEndHTML:00000210\r\n"
        "StartFragment:00000131\r\nEndFragment:00000174\r\n"
        "<html><body><!--StartFragment--><b>bold text</b><!--EndFragment--></body></html>")
set_clip_text_rich("bold text", {"HTML Format": HTML.encode("utf-8")})
time.sleep(0.3)
rich = get_clip_rich()
got_html = "HTML Format" in rich and b"<b>bold text</b>" in rich["HTML Format"]
results.append(("HTML format round trip", got_html))
print(f"HTML kept with the clip : {got_html}  (formats seen: {list(rich)})")
print(f"plain text still there  : {get_clip_text()!r}")

# --- 2. RTF -----------------------------------------------------------------
RTF = br"{\rtf1\ansi {\b bold text}}"
set_clip_text_rich("bold text", {"Rich Text Format": RTF})
time.sleep(0.3)
rich2 = get_clip_rich()
got_rtf = "Rich Text Format" in rich2 and b"rtf1" in rich2["Rich Text Format"]
results.append(("RTF round trip", got_rtf))
print(f"RTF kept with the clip  : {got_rtf}")

# --- 3. Copied files --------------------------------------------------------
repo = Path(__file__).resolve().parent.parent
paths = [str(repo / "README.md"), str(repo / "LICENSE")]
paths = [p for p in paths if os.path.isfile(p)]
set_clip_files(paths)
time.sleep(0.3)
back = get_clip_files()
got_files = [p.lower() for p in back] == [p.lower() for p in paths]
results.append(("CF_HDROP round trip", got_files))
print(f"copied files round trip : {got_files}")
print(f"  wrote {paths}")
print(f"  read  {back}")

set_clip_text_rich(original if original else " ")
ok = all(r[1] for r in results)
print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
for name, good in results:
    print(f"  {'ok ' if good else 'FAIL'} {name}")
sys.exit(0 if ok else 1)
