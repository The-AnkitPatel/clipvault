"""
ClipVault - clipboard history popup UI — AMOLED Dark PyQt6 window.

Imported by both clipvault-popup.exe (standalone) and clipvault.exe, which
keeps one instance warm so Win+V has no process to start.
Matches Linux GTK3 clipboard-popup 1:1 in features, shortcuts, and styling.
"""

import sys
import os
from pathlib import Path

class _NullWriter:
    def write(self, s): pass
    def flush(self): pass

if sys.stdout is None: sys.stdout = _NullWriter()
if sys.stderr is None: sys.stderr = _NullWriter()

# Ensure package directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import time
import json
import base64
import argparse
import ctypes
from ctypes import wintypes

from PyQt6.QtCore import (Qt, QTimer, QSize, pyqtSignal, QEvent, QPoint,
                          QPointF, QRect, QBuffer, QByteArray, QIODevice)
from PyQt6.QtGui import (QIcon, QPixmap, QImage, QColor, QFont, QKeySequence,
                         QAction, QPainter, QTextLayout, QTextOption)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QFrame, QMessageBox,
    QSizePolicy
)

import win32gui
import win32process
import win32api
import win32con
import win32event
import winerror

# Shared definitions
from clipboard_common import (
    HISTORY_DIR, INDEX_FILE, MAX_ITEMS,
    load_index, save_index, set_clip_text, set_clip_image,
    activate_target_window, send_ctrl_v,
    read_secure, write_secure, set_clip_text_rich, set_clip_files
)


def read_item_text(item):
    return read_secure(HISTORY_DIR / item["file"]).decode("utf-8", errors="replace")


def read_item_rich(item):
    """HTML / RTF stored alongside a text clip, as {format name: bytes}."""
    name = item.get("rich")
    if not name:
        return {}
    try:
        raw = read_secure(HISTORY_DIR / name)
        if not raw:
            return {}
        return {k: base64.b64decode(v) for k, v in json.loads(raw.decode("utf-8")).items()}
    except Exception:
        return {}


def read_item_paths(item):
    try:
        return json.loads(read_secure(HISTORY_DIR / item["file"]).decode("utf-8"))
    except Exception:
        return []


def put_item_on_clipboard(item, suffix=""):
    """Restore one history item to the clipboard in every format it was saved
    with, so pasting it is indistinguishable from the original copy."""
    kind = item.get("type")
    if kind == "files":
        return set_clip_files(read_item_paths(item))
    if kind == "text":
        return set_clip_text_rich(read_item_text(item) + suffix, read_item_rich(item))
    return set_clip_image(HISTORY_DIR / item["file"])

MAX_SHOW = 100

# -- Icons -------------------------------------------------------------------
# Drawn as SVG rather than pulled from the emoji font: emoji render at the
# mercy of whatever colour font Windows ships, and these have to sit at a fixed
# weight next to 12px text. Square line caps to match the rest of the UI.

CANCEL_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="#ff6b6b" stroke-width="2.6" stroke-linecap="square">
  <line x1="5" y1="5" x2="19" y2="19"/>
  <line x1="19" y1="5" x2="5" y2="19"/>
</svg>"""

TRASH_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
     fill="none" stroke="#c4c4c4" stroke-width="1.8" stroke-linecap="square">
  <line x1="4" y1="6" x2="20" y2="6"/>
  <path d="M9 6V3.6h6V6"/>
  <path d="M6 6v14.4h12V6"/>
  <line x1="10" y1="10" x2="10" y2="17"/>
  <line x1="14" y1="10" x2="14" y2="17"/>
</svg>"""

_ICON_CACHE = {}


def svg_icon(markup: bytes, size: int = 15) -> QIcon:
    key = (id(markup), size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    QSvgRenderer(QByteArray(markup)).render(painter)
    painter.end()
    icon = QIcon(pix)
    _ICON_CACHE[key] = icon
    return icon

SETTINGS_FILE = HISTORY_DIR / "popup-settings.json"


def load_settings():
    """Small per-user UI state. The window may be rebuilt at any time, so
    anything the user collapses has to live on disk to stick.

    Goes through the vault like everything else in the store - it was being
    written sealed and read as plain text, which quietly threw the state away.
    """
    try:
        if SETTINGS_FILE.exists():
            raw = read_secure(SETTINGS_FILE)
            if raw:
                data = json.loads(raw.decode("utf-8"))
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def save_settings(data):
    try:
        write_secure(SETTINGS_FILE, json.dumps(data, indent=2).encode("utf-8"))
    except Exception:
        pass

FIRST_PAINT_ROWS = 12   # enough to fill the window before it is shown
CHUNK_ROWS = 20         # streamed in afterwards, a batch per event loop pass

POPUP_QSS = """
QWidget#PopupWindow {
    background-color: #000000;
    border: 1px solid #1a1a1a;
    border-radius: 0px;
}

QLabel.header-title {
    color: #f4f4f4;
    font-size: 17px;
    font-weight: 700;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

QLabel.count-pill {
    background-color: #0d0d0d;
    color: #777777;
    border-radius: 0px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.clear-btn {
    background-color: #0d0d0d;
    border: 1px solid #1e1e1e;
    border-radius: 0px;
    padding: 6px 14px;
    color: #c4c4c4;
    font-size: 12px;
    font-weight: 600;
}
QPushButton.clear-btn:hover {
    background-color: #241818;
    border-color: #3a2424;
    color: #d98080;
}

QPushButton.cancel-btn {
    background-color: #241313;
    border: 1px solid #5a2727;
    border-radius: 0px;
    padding: 6px 14px;
    color: #ff6b6b;
    font-size: 12px;
    font-weight: 600;
}
QPushButton.cancel-btn:hover {
    background-color: #341a1a;
    border-color: #7d3535;
    color: #ff8f8f;
}

QLineEdit#search {
    background-color: #080808;
    color: #f2f2f2;
    border: 1.5px solid #1e1e1e;
    border-radius: 0px;
    padding: 10px 14px;
    font-size: 14px;
    selection-background-color: #333333;
}
QLineEdit#search:focus {
    border: 1.5px solid #3a3a3a;
    background-color: #0c0c0c;
}

QScrollArea {
    background: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background: transparent;
}
QScrollBar:vertical {
    border: none;
    background: #080808;
    width: 6px;
    margin: 0px;
    border-radius: 0px;
}
QScrollBar::handle:vertical {
    background: #252525;
    min-height: 20px;
    border-radius: 0px;
}
QScrollBar::handle:vertical:hover {
    background: #404040;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QFrame.section-header {
    background: transparent;
    border: none;
}
QFrame.section-header:hover {
    background-color: #0d0d0d;
}

QLabel.section-caret {
    color: #b4b4b4;
    font-size: 11px;
    min-width: 13px;
    max-width: 13px;
    padding: 0px;
    margin: 0px;
}

QLabel.section-label {
    color: #6e6e6e;
    font-size: 10px;
    font-weight: 700;
    padding: 0px;
    margin: 0px;
    letter-spacing: 0.5px;
}

QFrame.item-row {
    background-color: #0a0a0a;
    border: 1px solid transparent;
    border-radius: 0px;
}
QFrame.item-row:hover {
    background-color: #141414;
    border: 1px solid #232323;
}
QFrame.item-row[selected="true"] {
    background-color: #1a1a1a;
    border: 1px solid #333333;
}
QFrame.item-row[pinned="true"] {
    background-color: #0d0d0d;
    border-left: 3px solid #5c5c5c;
}
QFrame.item-row[pinned="true"]:hover {
    background-color: #161616;
}
QFrame.item-row[queued="true"] {
    background-color: #121212;
    border: 1px solid #3a3a3a;
}

QPushButton.sel-badge {
    background: transparent;
    border: 1px solid #2a2a2a;
    border-radius: 0px;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    color: #5a5a5a;
    font-size: 11px;
    font-weight: 700;
    padding: 0px;
}
QPushButton.sel-badge:hover {
    border-color: #444444;
    color: #cfcfcf;
    background-color: #161616;
}
QPushButton.sel-badge[active="true"] {
    background-color: #ededed;
    color: #000000;
    border: 1px solid #ededed;
}

QLabel.type-badge {
    background-color: #161616;
    color: #8a8a8a;
    border-radius: 0px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 700;
}

QLabel.title-text {
    color: #ededed;
    font-size: 13px;
}

QLabel.sub-text {
    color: #767676;
    font-size: 11px;
}

QPushButton.act-btn {
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 4px 6px;
    color: #6a6a6a;
    font-size: 16px;
}
QPushButton.act-btn:hover {
    background-color: #1e1e1e;
    color: #e8e8e8;
}
QPushButton.act-btn[pinned="true"] {
    color: #e6e6e6;
}
QPushButton.del-btn:hover {
    background-color: #241818;
    color: #d96b6b;
}

QFrame.footer-bar {
    border-top: 1px solid #1e1e1e;
}
QLabel.footer-count {
    color: #8a8a8a;
    font-size: 12px;
}

QPushButton.paste-btn {
    background-color: #2c2c2c;
    color: #ffffff;
    border: 1px solid #4a4a4a;
    border-radius: 0px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton.paste-btn:hover {
    background-color: #3a3a3a;
    border-color: #6a6a6a;
}
QPushButton.paste-btn:pressed {
    background-color: #484848;
}

QPushButton.clear-sel {
    background-color: #161616;
    color: #ffffff;
    border: 1px solid #2a2a2a;
    border-radius: 0px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton.clear-sel:hover {
    background-color: #232323;
    border-color: #3a3a3a;
}
QPushButton.clear-sel:disabled {
    color: #4a4a4a;
    border-color: #181818;
    background-color: #0d0d0d;
}

QLabel.empty-note {
    color: #585858;
    font-size: 13px;
    padding-top: 30px;
}

QMessageBox {
    background-color: #000000;
    color: #ededed;
}
QMessageBox QLabel {
    color: #ededed;
}
QMessageBox QPushButton {
    background-color: #1a1a1a;
    color: #ededed;
    border: 1px solid #333333;
    border-radius: 0px;
    padding: 6px 14px;
}
QMessageBox QPushButton:hover {
    background-color: #2a2a2a;
}
"""

_PIXMAP_CACHE = {}

THUMB_DIR = HISTORY_DIR / "thumbs"
THUMB_W, THUMB_H = 76, 52


def load_thumbnail(img_path: Path):
    """76x52 preview for an image clip, cached on disk.

    A fresh popup process otherwise re-decodes every full-resolution
    screenshot on each open, which is what made the first Win+V after a
    reboot take seconds. The cached PNGs are a couple of KB each.
    """
    key = str(img_path)
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]

    thumb_path = THUMB_DIR / f"{img_path.stem}.png"
    try:
        if thumb_path.is_file() and thumb_path.stat().st_mtime >= img_path.stat().st_mtime:
            cached = QPixmap()
            if cached.loadFromData(read_secure(thumb_path)) and not cached.isNull():
                _PIXMAP_CACHE[key] = cached
                return cached
    except Exception:
        pass

    pix = QPixmap()
    if not pix.loadFromData(read_secure(img_path)) or pix.isNull():
        return None
    scaled = pix.scaled(THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
    _PIXMAP_CACHE[key] = scaled
    try:
        THUMB_DIR.mkdir(parents=True, exist_ok=True)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled.save(buf, "PNG")
        buf.close()
        write_secure(thumb_path, bytes(buf.data()))
    except Exception:
        pass
    return scaled

class SectionHeader(QFrame):
    """PINNED / RECENT heading with a disclosure triangle that folds the section."""

    toggled = pyqtSignal(str)

    TRI_OPEN = "▼"       # disclosure triangle, section open
    TRI_SHUT = "▶"       # disclosure triangle, section folded

    def __init__(self, name, collapsed, count, parent=None):
        super().__init__(parent)
        self.name = name
        self.setProperty("class", "section-header")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 9, 6, 3)
        lay.setSpacing(7)

        self.caret = QLabel(self.TRI_SHUT if collapsed else self.TRI_OPEN)
        self.caret.setProperty("class", "section-caret")
        self.caret.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.caret, 0, Qt.AlignmentFlag.AlignVCenter)

        self.label = QLabel(f"{name}  ({count})")
        self.label.setProperty("class", "section-label")
        self.label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggled.emit(self.name)
        super().mouseReleaseEvent(event)


class ClipLabel(QLabel):
    """Preview text, clamped to two lines with a trailing ellipsis.

    Qt elides single lines only, and a word-wrapped QLabel just clips whatever
    does not fit - which is what pushed long clips off the right edge. Laying
    the text out by hand keeps every row exactly two lines tall.
    """

    MAX_LINES = 2

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text or ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        # Ignored width: the label must never ask the row to be as wide as the
        # text, which is what pushed the pin/delete buttons off the row.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(self.fontMetrics().lineSpacing())

    def setText(self, text):
        self._full = text or ""
        self.update()
        self._apply_height()

    def _wrap_option(self):
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        return opt

    def _line_count(self, width):
        """How many lines the text needs at this width, capped at MAX_LINES."""
        layout = QTextLayout(self._full, self.font())
        layout.setTextOption(self._wrap_option())
        layout.beginLayout()
        lines = 0
        while lines < self.MAX_LINES:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            lines += 1
        layout.endLayout()
        return max(1, lines)

    def _apply_height(self):
        """One line for short clips, two for long ones — so rows stay compact."""
        wanted = self.fontMetrics().lineSpacing() * self._line_count(max(1, self.width()))
        if wanted != self.height():
            self.setFixedHeight(wanted)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_height()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        fm = self.fontMetrics()
        width = max(1, self.width())

        layout = QTextLayout(self._full, self.font())
        layout.setTextOption(self._wrap_option())
        layout.beginLayout()
        y = 0.0
        drawn = 0
        while drawn < self.MAX_LINES:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            drawn += 1
            if drawn == self.MAX_LINES:
                start = line.textStart()
                rest = self._full[start:]
                if len(rest) > line.textLength():
                    painter.drawText(
                        QPointF(0, y + fm.ascent()),
                        fm.elidedText(rest, Qt.TextElideMode.ElideRight, width))
                    break
            line.draw(painter, QPointF(0, y))
            y += fm.lineSpacing()
        layout.endLayout()
        painter.end()


class ItemRow(QFrame):
    clicked = pyqtSignal(str)
    toggle_queue = pyqtSignal(str)
    toggle_pin = pyqtSignal(str)
    delete_item = pyqtSignal(str)
    drag_begin = pyqtSignal(str)
    drag_over = pyqtSignal(QPoint)
    drag_finish = pyqtSignal()

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.item_id = item["id"]
        self.setProperty("class", "item-row")
        self.setProperty("pinned", "true" if item.get("pin") else "false")
        self.setProperty("selected", "false")
        self.setProperty("queued", "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._press_pos = None
        self._dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # Multi-paste select badge
        self.sel_btn = QPushButton("○")
        self.sel_btn.setProperty("class", "sel-badge")
        self.sel_btn.setToolTip("Add to multi-paste (or press Tab)")
        self.sel_btn.clicked.connect(lambda: self.toggle_queue.emit(self.item_id))
        layout.addWidget(self.sel_btn)

        # Thumbnail / Badge if image
        if item.get("type") == "image":
            img_path = HISTORY_DIR / item["file"]
            if img_path.exists():
                thumb_lbl = QLabel()
                scaled = load_thumbnail(img_path)
                if scaled:
                    thumb_lbl.setPixmap(scaled)
                    thumb_lbl.setStyleSheet("border-radius: 0px;")
                    layout.addWidget(thumb_lbl)

            type_badge = QLabel("IMG")
            type_badge.setProperty("class", "type-badge")
            layout.addWidget(type_badge)

        elif item.get("type") == "files":
            type_badge = QLabel("FILES")
            type_badge.setProperty("class", "type-badge")
            layout.addWidget(type_badge)

        # Text column
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)

        title_str = item.get("preview", "").replace("\r\n", " ↵ ").replace("\n", " ↵ ")[:400]
        self.title_lbl = ClipLabel(title_str or "(empty)")
        self.title_lbl.setProperty("class", "title-text")
        col.addWidget(self.title_lbl)

        sub_str = item.get("app", "")
        if sub_str:
            self.sub_lbl = QLabel(f"from {sub_str}")
            self.sub_lbl.setProperty("class", "sub-text")
            col.addWidget(self.sub_lbl)

        layout.addLayout(col, 1)

        # Pin button
        self.pin_btn = QPushButton("★" if item.get("pin") else "☆")
        self.pin_btn.setProperty("class", "act-btn")
        self.pin_btn.setProperty("pinned", "true" if item.get("pin") else "false")
        self.pin_btn.setToolTip("Unpin" if item.get("pin") else "Pin (keep forever)")
        self.pin_btn.clicked.connect(lambda: self.toggle_pin.emit(self.item_id))
        layout.addWidget(self.pin_btn)

        # Delete button
        self.del_btn = QPushButton("✕")
        self.del_btn.setProperty("class", "act-btn del-btn")
        self.del_btn.setToolTip("Delete this item")
        self.del_btn.clicked.connect(lambda: self.delete_item.emit(self.item_id))
        layout.addWidget(self.del_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._dragging = False
            self.drag_begin.emit(self.item_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Qt grabs the mouse for this row on press, so the popup resolves which
        # row is under the cursor from the global position.
        if getattr(self, "_press_pos", None) is not None:
            here = event.globalPosition().toPoint()
            if not self._dragging:
                moved = (here - self._press_pos).manhattanLength()
                if moved >= QApplication.startDragDistance():
                    self._dragging = True
            if self._dragging:
                self.drag_over.emit(here)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, "_press_pos", None) is not None:
            was_drag = self._dragging
            self._press_pos = None
            self._dragging = False
            self.drag_finish.emit()
            # A plain click still pastes; only a glide selects.
            if not was_drag:
                self.clicked.emit(self.item_id)
        super().mouseReleaseEvent(event)

    def set_queued(self, in_queue: bool, order_num: int = 0):
        self.setProperty("queued", "true" if in_queue else "false")
        self.sel_btn.setProperty("active", "true" if in_queue else "false")
        self.sel_btn.setText(str(order_num) if in_queue else "○")
        self.style().unpolish(self.sel_btn)
        self.style().polish(self.sel_btn)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_highlighted(self, hl: bool):
        self.setProperty("selected", "true" if hl else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class ClipboardPopup(QWidget):
    def __init__(self, target_hwnd=None, standalone=True):
        super().__init__()
        self.target_hwnd = target_hwnd
        # standalone=False means the daemon owns this window and keeps it
        # alive between uses, so dismissing must hide it, never quit the app.
        self.standalone = standalone
        self._index_mtime = None
        self.setObjectName("PopupWindow")
        self.setWindowTitle("ClipVault")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.queue = []           # List of queued item_ids
        self.row_widgets = []     # Currently rendered ItemRow widgets
        self.highlighted_idx = 0  # Keyboard navigation index
        self.focus_out_ready = False
        self.is_pasting = False
        self.activated_once = False
        self._render_gen = 0      # bumped per populate(), cancels stale chunks
        self._plan = []
        self._plan_pos = 0
        self._query = ""
        self._drag_anchor = None
        self._drag_mode = None
        self._drag_last_y = None
        self._drag_armed = False

        settings = load_settings()
        collapsed = settings.get("collapsed", {})
        self.collapsed = {
            "PINNED": bool(collapsed.get("PINNED", False)),
            "RECENT": bool(collapsed.get("RECENT", False)),
        }

        self.items = load_index()

        self._build_ui()
        self._position_window()
        self.populate()

        # Install application event filter to catch outside clicks & escape key
        QApplication.instance().installEventFilter(self)

        # Enable focus loss dismissal after short startup delay
        # Mirrors the Linux popup: focus grab at 100 ms, focus-out armed at 600 ms.
        QTimer.singleShot(600, self._enable_focus_out)
        QTimer.singleShot(100, self._force_focus)
        QTimer.singleShot(320, self._force_focus)

    def _enable_focus_out(self):
        self.focus_out_ready = True

    def _force_focus(self):
        """Claim the foreground. A process that does not already own the
        foreground window is refused by SetForegroundWindow, so borrow the
        current foreground thread's input queue for the call."""
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
        try:
            hwnd = int(self.winId())
            cur_thread = win32api.GetCurrentThreadId()
            fg_hwnd = win32gui.GetForegroundWindow()
            fg_thread = 0
            if fg_hwnd:
                fg_thread, _ = win32process.GetWindowThreadProcessId(fg_hwnd)
            attached = False
            if fg_thread and fg_thread != cur_thread:
                try:
                    win32process.AttachThreadInput(cur_thread, fg_thread, True)
                    attached = True
                except Exception:
                    attached = False
            try:
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetActiveWindow(hwnd)
            finally:
                if attached:
                    try:
                        win32process.AttachThreadInput(cur_thread, fg_thread, False)
                    except Exception:
                        pass
            if win32gui.GetForegroundWindow() == hwnd:
                self.activated_once = True
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                return True
        elif event.type() == QEvent.Type.MouseButtonPress:
            if self.focus_out_ready and not self.is_pasting:
                # Check if click was outside this window geometry
                click_pos = event.globalPosition().toPoint()
                if not self.geometry().contains(click_pos):
                    self.close()
                    return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                self.activated_once = True
            else:
                self._maybe_dismiss()
        super().changeEvent(event)

    def _maybe_dismiss(self):
        """Close on focus loss, but only once the popup has actually held
        focus — otherwise a failed foreground grab closes it instantly."""
        if self.focus_out_ready and self.activated_once and not self.is_pasting:
            self.close()

    def nativeEvent(self, eventType, message):
        """Win32 message hook.

        Two hard rules here, both learned the hard way:
          * NEVER call super().nativeEvent() — PyQt6 6.11 faults inside the
            base implementation (STATUS_FATAL_USER_CALLBACK_EXCEPTION), which
            killed the popup before it was ever painted. Return (False, 0) so
            Qt keeps its normal processing.
          * NEVER let a Python exception escape — this runs inside the window
            procedure, where an unhandled exception aborts the process.
        """
        try:
            if eventType == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == win32con.WM_ACTIVATE:
                    if (msg.wParam & 0xFFFF) != win32con.WA_INACTIVE:
                        self.activated_once = True
                    else:
                        self._maybe_dismiss()
                elif msg.message == win32con.WM_KILLFOCUS:
                    self._maybe_dismiss()
        except Exception:
            pass
        return False, 0

    def closeEvent(self, event):
        if self.standalone:
            QApplication.quit()
            super().closeEvent(event)
        else:
            event.ignore()
            self.hide()

    def _dismiss(self):
        """End this showing: quit when we are our own process, hide when the
        daemon is holding us warm for the next Win+V."""
        if self.standalone:
            QApplication.quit()
        else:
            self.hide()

    def _read_index_mtime(self):
        try:
            return INDEX_FILE.stat().st_mtime_ns
        except Exception:
            return None

    def reopen(self, target_hwnd=None):
        """Show an already-built window. This is the fast path: no process
        start, no Qt start, and no rebuild unless the history actually moved."""
        self.target_hwnd = target_hwnd
        self.is_pasting = False
        self.focus_out_ready = False
        self.activated_once = False
        self.queue.clear()

        if self.search.text():
            self.search.clear()                     # fires populate("")
        elif self._index_mtime != self._read_index_mtime():
            self.populate("")
        else:
            self.highlighted_idx = 0
            self._update_highlight()
            self._refresh_selection_ui()

        self._position_window()
        self.show()
        self._force_focus()
        QTimer.singleShot(120, self._force_focus)
        QTimer.singleShot(600, self._enable_focus_out)

    def _position_window(self):
        cursor_pos = win32api.GetCursorPos()
        q_pos = QPoint(cursor_pos[0], cursor_pos[1])
        screen = QApplication.screenAt(q_pos) or QApplication.primaryScreen()
        geo = screen.geometry()
        w, h = min(720, geo.width() - 40), min(560, geo.height() - 80)
        self.resize(w, h)
        x = geo.x() + (geo.width() - w) // 2
        y = geo.y() + 56
        self.move(x, y)

    def _build_ui(self):
        self.setStyleSheet(POPUP_QSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # Header: title + count + Clear all
        header = QHBoxLayout()
        header.setSpacing(10)

        title = QLabel("ClipVault")
        title.setProperty("class", "header-title")
        header.addWidget(title)

        self.count_lbl = QLabel("0 · ★ 0")
        self.count_lbl.setProperty("class", "count-pill")
        header.addWidget(self.count_lbl)

        header.addStretch(1)

        # Only shown while a multi-paste selection is live.
        self.cancel_btn = QPushButton("  Cancel")
        self.cancel_btn.setProperty("class", "cancel-btn")
        self.cancel_btn.setIcon(svg_icon(CANCEL_SVG))
        self.cancel_btn.setToolTip("Drop the current selection")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._clear_queue)
        self.cancel_btn.hide()
        header.addWidget(self.cancel_btn)

        self.header_btn = QPushButton("  Clear all")
        self.header_btn.setProperty("class", "clear-btn")
        self.header_btn.setIcon(svg_icon(TRASH_SVG))
        self.header_btn.setToolTip("Delete every unpinned item")
        self.header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_btn.clicked.connect(self._on_clear_all)
        header.addWidget(self.header_btn)

        outer.addLayout(header)

        # Search Bar
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search clipboard history…")
        self.search.textChanged.connect(lambda text: self.populate(text))
        self.search.returnPressed.connect(self._commit)
        outer.addWidget(self.search)

        # Scrollable list area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(2, 2, 2, 2)
        self.list_layout.setSpacing(4)
        self.list_layout.addStretch(1)

        self.scroll.setWidget(self.list_container)
        outer.addWidget(self.scroll, 1)

        # Persistent Footer Bar
        footer = QFrame()
        footer.setProperty("class", "footer-bar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(2, 10, 2, 2)
        footer_layout.setSpacing(10)

        self.sel_lbl = QLabel("○ or Tab to pick several, then Paste")
        self.sel_lbl.setProperty("class", "footer-count")
        footer_layout.addWidget(self.sel_lbl)

        footer_layout.addStretch(1)

        self.clear_sel_btn = QPushButton("Clear")
        self.clear_sel_btn.setProperty("class", "clear-sel")
        self.clear_sel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_sel_btn.setEnabled(False)
        self.clear_sel_btn.clicked.connect(self._clear_queue)
        footer_layout.addWidget(self.clear_sel_btn)

        self.paste_btn = QPushButton("Paste selected  ⏎")
        self.paste_btn.setProperty("class", "paste-btn")
        self.paste_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.paste_btn.clicked.connect(self._commit)
        footer_layout.addWidget(self.paste_btn)

        outer.addWidget(footer)

    def populate(self, query=""):
        self._query = query
        self.items = load_index()
        self._index_mtime = self._read_index_mtime()

        live_ids = {it["id"] for it in self.items}
        self.queue = [qid for qid in self.queue if qid in live_ids]

        for r in self.row_widgets:
            r.setParent(None)
            r.deleteLater()
        self.row_widgets.clear()

        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        ql = query.lower().strip()
        def match(it):
            return (not ql) or ql in it.get("preview", "").lower() or ql in it.get("app", "").lower()

        pinned = [it for it in self.items if it.get("pin") and match(it)]
        recent = [it for it in self.items if not it.get("pin") and match(it)]

        n_total = len(self.items)
        n_pin = len([it for it in self.items if it.get("pin")])
        self.count_lbl.setText(f"{n_total}  ·  ★ {n_pin}")

        # Build the render plan, then draw only what the window shows and
        # stream the rest in afterwards. Rendering all 100 rows up front was
        # most of the delay between Win+V and a window on screen.
        plan = []
        if pinned:
            plan.append(("section", ("PINNED", len(pinned))))
            if not self.collapsed.get("PINNED"):
                plan.extend(("item", it) for it in pinned)
        if recent:
            budget = recent[:max(0, MAX_SHOW - len(pinned))]
            plan.append(("section", ("RECENT", len(budget))))
            if not self.collapsed.get("RECENT"):
                plan.extend(("item", it) for it in budget)

        self._render_gen += 1
        self._plan = plan
        self._plan_pos = 0
        shown = self._render_slice(self._render_gen, FIRST_PAINT_ROWS)

        if not plan:
            empty_lbl = QLabel("Nothing here yet — copy something, or adjust your search.")
            empty_lbl.setProperty("class", "empty-note")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list_layout.addWidget(empty_lbl)

        self.highlighted_idx = 0
        self._update_highlight()
        self._refresh_selection_ui()
        self._schedule_remaining_rows()

    def _render_slice(self, gen, count):
        """Draw up to `count` more rows from the plan. Returns rows drawn."""
        if gen != self._render_gen:
            return 0
        drawn = 0
        while self._plan_pos < len(self._plan) and drawn < count:
            kind, payload = self._plan[self._plan_pos]
            self._plan_pos += 1
            if kind == "section":
                name, count = payload
                header = SectionHeader(name, self.collapsed.get(name, False), count)
                header.toggled.connect(self._toggle_section)
                self.list_layout.addWidget(header)
                continue
            row = self._create_row(payload)
            self.list_layout.addWidget(row)
            self.row_widgets.append(row)
            drawn += 1
        return drawn

    def _schedule_remaining_rows(self):
        if self._plan_pos >= len(self._plan):
            self.list_layout.addStretch(1)
            return
        gen = self._render_gen
        QTimer.singleShot(0, lambda: self._render_rest(gen))

    def _render_rest(self, gen):
        if gen != self._render_gen:
            return
        self._render_slice(gen, CHUNK_ROWS)
        self._schedule_remaining_rows()

    def _create_row(self, item_dict):
        row = ItemRow(item_dict)
        row.clicked.connect(self._on_row_clicked)
        row.toggle_queue.connect(self._toggle_queue)
        row.toggle_pin.connect(self._toggle_pin)
        row.delete_item.connect(self._delete_item)
        row.drag_begin.connect(self._on_drag_begin)
        row.drag_over.connect(self._on_drag_over)
        row.drag_finish.connect(self._on_drag_finish)

        in_queue = item_dict["id"] in self.queue
        order_num = self.queue.index(item_dict["id"]) + 1 if in_queue else 0
        row.set_queued(in_queue, order_num)
        return row

    def _update_highlight(self):
        for idx, row in enumerate(self.row_widgets):
            row.set_highlighted(idx == self.highlighted_idx)

    def _refresh_selection_ui(self):
        for row in self.row_widgets:
            in_queue = row.item_id in self.queue
            order = self.queue.index(row.item_id) + 1 if in_queue else 0
            row.set_queued(in_queue, order)

        n = len(self.queue)
        if n:
            self.sel_lbl.setText(f"{n} selected — pastes in pick order")
            self.clear_sel_btn.setEnabled(True)
            self.cancel_btn.show()
        else:
            self.sel_lbl.setText("○ or Tab to pick several, then Paste")
            self.clear_sel_btn.setEnabled(False)
            self.cancel_btn.hide()

    def _toggle_section(self, name):
        """Fold a section away, and remember it for next time."""
        self.collapsed[name] = not self.collapsed.get(name, False)
        settings = load_settings()
        settings["collapsed"] = self.collapsed
        save_settings(settings)
        self.populate(self._query)
        self.search.setFocus()

    # ── Drag across rows to select them ───────────────────────────────────
    DRAG_EDGE = 44          # px from the viewport edge where auto-scroll kicks in
    DRAG_STEP_MAX = 28      # px per tick at the very edge
    DRAG_DIR_MIN = 3        # px of travel before a direction counts

    def _on_drag_begin(self, item_id):
        self._drag_anchor = item_id
        self._drag_mode = None      # "add" going down, "remove" going up
        self._drag_last_y = None
        self._drag_armed = False

    def _on_drag_over(self, global_pos):
        self._autoscroll(global_pos)

        # Which way the hand is moving decides what the glide does. Dragging
        # back up over rows you just picked takes them out again, so an
        # overshoot is undone by reversing rather than starting over.
        y = global_pos.y()
        if self._drag_last_y is None:
            self._drag_last_y = y
            return
        travel = y - self._drag_last_y
        if abs(travel) >= self.DRAG_DIR_MIN:
            self._drag_mode = "add" if travel > 0 else "remove"
            self._drag_last_y = y
        if self._drag_mode is None:
            return

        if not self._drag_armed:
            # The row the glide started on follows the same direction.
            self._drag_armed = True
            if self._drag_anchor:
                self._apply_drag(self._drag_anchor)

        row = self._row_at(global_pos)
        if row is None:
            return
        if self._apply_drag(row.item_id):
            self.scroll.ensureWidgetVisible(row, 0, 24)

    def _apply_drag(self, item_id):
        """Idempotent, so repeated move events and direction changes both
        behave. Returns True when the selection actually changed."""
        if self._drag_mode == "add":
            return self._queue_add(item_id)
        return self._queue_remove(item_id)

    def _on_drag_finish(self):
        self._drag_anchor = None
        self._drag_mode = None
        self._drag_last_y = None
        self._drag_armed = False

    def _autoscroll(self, global_pos):
        """Scroll the list when the glide reaches the top or bottom edge.

        Without this the selection runs off the bottom of the window and you
        cannot see how far down it has got.
        """
        viewport = self.scroll.viewport()
        top = viewport.mapToGlobal(QPoint(0, 0)).y()
        bottom = top + viewport.height()
        y = global_pos.y()

        delta = 0
        if y > bottom - self.DRAG_EDGE:
            over = y - (bottom - self.DRAG_EDGE)
            delta = min(self.DRAG_STEP_MAX, max(4, int(over)))
        elif y < top + self.DRAG_EDGE:
            over = (top + self.DRAG_EDGE) - y
            delta = -min(self.DRAG_STEP_MAX, max(4, int(over)))

        if delta:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() + delta)

    def _row_at(self, global_pos):
        """Row under this screen point, by geometry.

        Hit-testing with QApplication.widgetAt() would hand back whatever
        child, tooltip or foreign window happens to be on top; comparing
        rectangles keeps the glide tracking the list itself.
        """
        viewport = self.scroll.viewport()
        if not QRect(viewport.mapToGlobal(QPoint(0, 0)), viewport.size()).contains(global_pos):
            return None
        for row in self.row_widgets:
            if QRect(row.mapToGlobal(QPoint(0, 0)), row.size()).contains(global_pos):
                return row
        return None

    def _queue_add(self, item_id):
        if item_id in self.queue:
            return False
        self.queue.append(item_id)
        self._refresh_selection_ui()
        return True

    def _queue_remove(self, item_id):
        if item_id not in self.queue:
            return False
        self.queue.remove(item_id)
        self._refresh_selection_ui()
        return True

    def _toggle_queue(self, item_id):
        if item_id in self.queue:
            self.queue.remove(item_id)
        else:
            self.queue.append(item_id)
        self._refresh_selection_ui()

    def _clear_queue(self):
        self.queue.clear()
        self._refresh_selection_ui()
        self.search.setFocus()

    def _toggle_pin(self, item_id):
        def mutate(lst):
            for it in lst:
                if it["id"] == item_id:
                    it["pin"] = not it.get("pin", False)
                    break
        items = load_index()
        mutate(items)
        save_index(items)
        self.populate(self.search.text())

    def _delete_item(self, item_id):
        items = load_index()
        for it in list(items):
            if it["id"] == item_id:
                try:
                    (HISTORY_DIR / it["file"]).unlink(missing_ok=True)
                    if it.get("rich"):
                        (HISTORY_DIR / it["rich"]).unlink(missing_ok=True)
                except Exception:
                    pass
                items.remove(it)
                break
        save_index(items)
        self.populate(self.search.text())

    def _on_clear_all(self):
        self.focus_out_ready = False
        reply = QMessageBox.question(
            self,
            "Clear all clipboard history?",
            "Pinned items (★) are kept. This cannot be undone.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        self.focus_out_ready = True
        if reply == QMessageBox.StandardButton.Ok:
            items = load_index()
            kept = []
            for it in items:
                if it.get("pin"):
                    kept.append(it)
                else:
                    try:
                        (HISTORY_DIR / it["file"]).unlink(missing_ok=True)
                        if it.get("rich"):
                            (HISTORY_DIR / it["rich"]).unlink(missing_ok=True)
                    except Exception:
                        pass
            save_index(kept)
            self.queue.clear()
            self.populate()
        self.search.setFocus()

    def _on_row_clicked(self, item_id):
        if self.queue:
            self._toggle_queue(item_id)
        else:
            self._paste_single(item_id)

    # ── Pasting Logic ──────────────────────────────────────────────────────────

    def _item_by_id(self, item_id):
        for it in self.items:
            if it["id"] == item_id:
                return it
        return None

    def _commit(self):
        if self.queue:
            self._paste_queue()
        elif self.row_widgets and 0 <= self.highlighted_idx < len(self.row_widgets):
            row = self.row_widgets[self.highlighted_idx]
            self._paste_single(row.item_id)

    def _paste_single(self, item_id):
        item = self._item_by_id(item_id)
        if not item:
            return
        fp = HISTORY_DIR / item["file"]
        if not fp.exists():
            return

        self.is_pasting = True
        self.hide()
        QTimer.singleShot(60, lambda: self._execute_paste(item, fp))

    def _execute_paste(self, item, fp: Path):
        put_item_on_clipboard(item)

        activate_target_window(self.target_hwnd)
        QTimer.singleShot(60, self._finish_paste)

    def _finish_paste(self):
        send_ctrl_v()
        QTimer.singleShot(150, self._dismiss)

    def _paste_queue(self):
        items = [self._item_by_id(qid) for qid in self.queue]
        items = [it for it in items if it and (HISTORY_DIR / it["file"]).exists()]
        if not items:
            return

        self.is_pasting = True
        self.hide()

        has_images = any(it["type"] != "text" for it in items)
        if not has_images:
            # All text: combine with \n into a single clean paste
            combined = "\n".join(read_item_text(it) for it in items)
            QTimer.singleShot(60, lambda: self._execute_paste_combined(combined))
        else:
            # Sequential multi-paste for images / mixed
            QTimer.singleShot(60, lambda: self._execute_seq_paste(items, 0))

    def _execute_paste_combined(self, text):
        set_clip_text(text)
        activate_target_window(self.target_hwnd)
        QTimer.singleShot(60, self._finish_paste)

    def _execute_seq_paste(self, items, idx):
        if idx >= len(items):
            QTimer.singleShot(150, self._dismiss)
            return

        it = items[idx]
        suffix = "\n" if idx < len(items) - 1 else ""
        put_item_on_clipboard(it, suffix)

        if idx == 0:
            activate_target_window(self.target_hwnd)

        QTimer.singleShot(80, lambda: self._step_seq(items, idx))

    def _step_seq(self, items, idx):
        send_ctrl_v()
        QTimer.singleShot(180, lambda: self._execute_seq_paste(items, idx + 1))

    # ── Keyboard Navigation ───────────────────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        elif key == Qt.Key.Key_Down:
            if self.row_widgets:
                self.highlighted_idx = min(len(self.row_widgets) - 1, self.highlighted_idx + 1)
                self._update_highlight()
                self.scroll.ensureWidgetVisible(self.row_widgets[self.highlighted_idx])
            return
        elif key == Qt.Key.Key_Up:
            if self.row_widgets:
                self.highlighted_idx = max(0, self.highlighted_idx - 1)
                self._update_highlight()
                self.scroll.ensureWidgetVisible(self.row_widgets[self.highlighted_idx])
            return
        elif key == Qt.Key.Key_Tab:
            if self.row_widgets and 0 <= self.highlighted_idx < len(self.row_widgets):
                row = self.row_widgets[self.highlighted_idx]
                self._toggle_queue(row.item_id)
            return
        elif key == Qt.Key.Key_Delete:
            if self.row_widgets and 0 <= self.highlighted_idx < len(self.row_widgets):
                row = self.row_widgets[self.highlighted_idx]
                self._delete_item(row.item_id)
            return

        super().keyPressEvent(event)


def main():
    mutex = win32event.CreateMutex(None, False, "Global\\ClipVaultPopupMutex")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        # Bring existing window to front if running
        try:
            hwnd = win32gui.FindWindow(None, "ClipVault")
            if hwnd:
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        sys.exit(0)

    parser = argparse.ArgumentParser(description="ClipVault popup window")
    parser.add_argument("--target-hwnd", type=int, default=None, help="Target window HWND for paste")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    popup = ClipboardPopup(target_hwnd=args.target_hwnd, standalone=True)
    popup.show()
    sys.exit(app.exec())


