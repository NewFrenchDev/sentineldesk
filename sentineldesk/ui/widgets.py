"""
sentineldesk – animated & themed widget primitives
"""
from __future__ import annotations

import math
import time as _time
from typing import List, Dict

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QLinearGradient,
    QPainterPath,
)

# ──────────────────────────────────────────────
# Palette
# ──────────────────────────────────────────────
PALETTE = {
    "bg_deep":       "#0a0c10",
    "bg_card":       "#111418",
    "bg_card_hover": "#161b24",
    "border":        "#1e2530",
    "border_glow":   "#2a3a5c",
    "text_primary":  "#e2e6ec",
    "text_muted":    "#6b7280",
    "accent_cyan":   "#22d3ee",
    "accent_blue":   "#3b82f6",
    "accent_purple": "#a78bfa",
    "green":         "#22c55e",
    "yellow":        "#eab308",
    "orange":        "#f97316",
    "red":           "#ef4444",
    "red_glow":      "#ef444440",
}

SEVERITY_COLORS = {
    "info":   PALETTE["accent_cyan"],
    "low":    PALETTE["green"],
    "medium": PALETTE["orange"],
    "high":   PALETTE["red"],
}

KIND_COLORS = {
    "metric":     PALETTE["accent_cyan"],
    "process":    PALETTE["accent_blue"],
    "connection": PALETTE["accent_purple"],
    "integrity":  PALETTE["orange"],
    "alert":      PALETTE["red"],
    "log":        PALETTE["text_muted"],
}

# ──────────────────────────────────────────────
# Process icon map  (exe basename lowercase → emoji)
# ──────────────────────────────────────────────
PROCESS_ICONS: Dict[str, str] = {
    # Browsers
    "chrome.exe":            "🌐",
    "chromium.exe":          "🌐",
    "chromium-browser":      "🌐",
    "firefox.exe":           "🦊",
    "firefox":               "🦊",
    "msedge.exe":            "🌐",
    "safari":                "🌐",
    "brave.exe":             "🛡️",
    "brave-browser":         "🛡️",
    "opera.exe":             "🌐",
    # Communication
    "discord.exe":           "💬",
    "discord":               "💬",
    "slack.exe":             "💬",
    "slack":                 "💬",
    "teams.exe":             "👥",
    "msteams.exe":           "👥",
    "zoom.exe":              "📹",
    "skype.exe":             "📞",
    # Media / Gaming
    "spotify.exe":           "🎵",
    "spotify":               "🎵",
    "vlc.exe":               "🎬",
    "vlc":                   "🎬",
    "steam.exe":             "🎮",
    "steam":                 "🎮",
    "steamwebhelper.exe":    "🎮",
    # Development
    "code.exe":              "💻",
    "code":                  "💻",
    "devenv.exe":            "💻",
    "idea64.exe":            "💻",
    "pycharm64.exe":         "💻",
    "node.exe":              "📦",
    "node":                  "📦",
    "python.exe":            "🐍",
    "python3.exe":           "🐍",
    "python":                "🐍",
    "python3":               "🐍",
    "git.exe":               "🔀",
    "git":                   "🔀",
    "powershell.exe":        "⬛",
    "powershell":            "⬛",
    "cmd.exe":               "⬛",
    # System / Windows
    "explorer.exe":          "📁",
    "svchost.exe":           "⚙️",
    "conhost.exe":           "⬛",
    "dwm.exe":               "🖼️",
    "csrss.exe":             "🖥️",
    "lsass.exe":             "🔐",
    "smss.exe":              "🔐",
    "services.exe":          "⚙️",
    "winlogon.exe":          "🔑",
    "spoolsv.exe":           "🖨️",
    "taskhostw.exe":         "⚙️",
    "ctfmon.exe":            "⌨️",
    "sihost.exe":            "⚙️",
    "wmspawn.exe":           "⚙️",
    "wscript.exe":           "📜",
    "wscript":               "📜",
    "cscript.exe":           "📜",
    # Security
    "msdefender.exe":        "🛡️",
    "mssense.exe":           "🛡️",
    # Network / Web
    "nginx.exe":             "🌀",
    "nginx":                 "🌀",
    "httpd.exe":             "🌀",
    # Database
    "mysql.exe":             "🗄️",
    "mysqld.exe":            "🗄️",
    "postgres.exe":          "🗄️",
    "mongod.exe":            "🗄️",
    # Mail
    "thunderbird.exe":       "📧",
    "thunderbird":           "📧",
    "outlook.exe":           "📧",
    # Other
    "runtimebroker.exe":     "📦",
    "searchui.exe":          "🔍",
    "searchindexer.exe":     "🔍",
    "onedrive.exe":          "☁️",
    "dropbox.exe":           "📦",
}

def get_process_icon(name: str) -> str:
    """Return emoji for a process name, or generic fallback."""
    return PROCESS_ICONS.get(name.lower(), "⬜")


# ──────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────
def fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if abs(x) < 1024.0:
            return f"{x:.1f} {u}"
        x /= 1024.0
    return f"{x:.1f} PB"

def fmt_bps(bps: float) -> str:
    return fmt_bytes(int(bps)) + "/s"


# ──────────────────────────────────────────────
# _PulseHub – ONE shared timer drives ALL PulsingDots
# ──────────────────────────────────────────────
class _PulseHub(QtCore.QObject):
    """Singleton.  A single 60 ms timer pushes a sine-wave value
    to every registered PulsingDot.  Zero per-instance timers."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            obj = super().__new__(cls)
            obj._inited = False
            cls._instance = obj
        return cls._instance

    def __init__(self):
        if self._inited:
            return
        super().__init__()
        self._inited = True
        self._subscribers: List["PulsingDot"] = []
        self._start_time = _time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(60)          # 16 fps – smooth sine, very cheap
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def register(self, dot: "PulsingDot"):
        self._subscribers.append(dot)

    def unregister(self, dot: "PulsingDot"):
        try:
            self._subscribers.remove(dot)
        except ValueError:
            pass

    def _tick(self):
        t = _time.monotonic() - self._start_time
        # Slow sine: full cycle ≈ 2.4 s, range 0…1
        pulse = (math.sin(t * 2.6 - math.pi / 2) + 1.0) * 0.5
        for dot in self._subscribers:
            dot._pulse = pulse
            dot.update()


# ──────────────────────────────────────────────
# PulsingDot  – animated indicator
# ──────────────────────────────────────────────
class PulsingDot(QtWidgets.QWidget):
    def __init__(self, color: str = PALETTE["green"], radius: int = 6, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._radius = radius
        self._pulse = 0.0          # written externally by _PulseHub
        self.setFixedSize(radius * 4, radius * 4)
        _PulseHub().register(self)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def closeEvent(self, e):
        _PulseHub().unregister(self)
        super().closeEvent(e)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r_core = self._radius
        r_ring = r_core + self._pulse * (self._radius * 0.9)

        glow_color = QColor(self._color)
        glow_color.setAlpha(int(60 * (1.0 - self._pulse)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow_color))
        p.drawEllipse(QtCore.QRectF(cx - r_ring, cy - r_ring, r_ring * 2, r_ring * 2))

        p.setBrush(QBrush(self._color))
        p.drawEllipse(QtCore.QRectF(cx - r_core, cy - r_core, r_core * 2, r_core * 2))
        p.end()


# ──────────────────────────────────────────────
# AnimatedCounter – smooth numeric transitions
# ──────────────────────────────────────────────
class AnimatedCounter(QtWidgets.QLabel):
    def __init__(self, fmt: str = "{:.0f}", parent=None):
        super().__init__("0", parent)
        self._fmt = fmt
        self._current = 0.0
        self._target  = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(32)          # ~30 fps, only while moving
        self._timer.timeout.connect(self._step)

    def set_value(self, value: float):
        self._target = value
        if not self._timer.isActive():
            self._timer.start()

    def _step(self):
        diff = self._target - self._current
        if abs(diff) < 0.1:
            self._current = self._target
            self.setText(self._fmt.format(self._current))
            self._timer.stop()               # stops immediately → zero idle cost
        else:
            self._current += diff * 0.22
            self.setText(self._fmt.format(self._current))


# ──────────────────────────────────────────────
# LiveGraph – real-time sparkline with gradient fill
# ──────────────────────────────────────────────
class LiveGraph(QtWidgets.QWidget):
    def __init__(self, max_points: int = 120, color: str = PALETTE["accent_cyan"], parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._max = max_points
        self._data: List[float] = [0.0] * max_points
        self.setMinimumHeight(56)

    def push(self, value: float):
        self._data.append(value)
        if len(self._data) > self._max:
            self._data.pop(0)
        self.update()

    def paintEvent(self, _event):
        if len(self._data) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pad_x, pad_y = 4, 4

        lo  = min(self._data)
        hi  = max(self._data)
        rng = hi - lo if hi != lo else 1.0

        pts = len(self._data)
        step_x = (w - pad_x * 2) / max(pts - 1, 1)

        path = QPainterPath()
        coords = []
        for i, v in enumerate(self._data):
            x = pad_x + i * step_x
            y = h - pad_y - ((v - lo) / rng) * (h - pad_y * 2)
            coords.append((x, y))
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        fill_path = QPainterPath(path)
        fill_path.lineTo(coords[-1][0], h)
        fill_path.lineTo(coords[0][0], h)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        top_color = QColor(self._color)
        top_color.setAlpha(90)
        bot_color = QColor(self._color)
        bot_color.setAlpha(0)
        grad.setColorAt(0, top_color)
        grad.setColorAt(1, bot_color)

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawPath(fill_path)

        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        if coords:
            lx, ly = coords[-1]
            dot_color = QColor(self._color)
            glow = QColor(dot_color)
            glow.setAlpha(50)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QtCore.QRectF(lx - 5, ly - 5, 10, 10))
            p.setBrush(QBrush(dot_color))
            p.drawEllipse(QtCore.QRectF(lx - 3, ly - 3, 6, 6))

        p.end()


# ──────────────────────────────────────────────
# MetricCard – glass-morphism card with live graph
# ──────────────────────────────────────────────
class MetricCard(QtWidgets.QWidget):
    def __init__(self, title: str, icon: str = "", color: str = PALETTE["accent_cyan"], parent=None):
        super().__init__(parent)
        self._color = color
        self._title = title

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(4)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)

        if icon:
            icon_lbl = QtWidgets.QLabel(icon)
            icon_lbl.setStyleSheet(f"font-size: 18px; color: {color};")
            header.addWidget(icon_lbl)

        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setStyleSheet(f"""
            font-size: 11px;
            font-weight: 600;
            color: {PALETTE['text_muted']};
            text-transform: uppercase;
            letter-spacing: 1.5px;
        """)
        header.addWidget(title_lbl, 1)

        self.dot = PulsingDot(color=color, radius=4)
        header.addWidget(self.dot)
        layout.addLayout(header)

        self.value_label = AnimatedCounter("{:.0f}")
        self.value_label.setStyleSheet(f"""
            font-size: 28px;
            font-weight: 700;
            color: {PALETTE['text_primary']};
            font-family: 'Consolas', 'Courier New', monospace;
        """)
        layout.addWidget(self.value_label)

        self.sub_label = QtWidgets.QLabel("")
        self.sub_label.setStyleSheet(f"font-size: 11px; color: {PALETTE['text_muted']}; font-family: monospace;")
        layout.addWidget(self.sub_label)

        self.graph = LiveGraph(max_points=90, color=color)
        self.graph.setMinimumHeight(48)
        layout.addWidget(self.graph, 1)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        p.setPen(QPen(QColor(PALETTE["border"]), 1))
        p.setBrush(QBrush(QColor(PALETTE["bg_card"])))
        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.drawPath(path)

        accent = QColor(self._color)
        accent.setAlpha(180)
        pen = QPen(accent, 2.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(20, 1.5), QtCore.QPointF(rect.width() - 20, 1.5))

        p.end()
        super().paintEvent(event)


# ──────────────────────────────────────────────
# SeverityBadge  – colored pill
# ──────────────────────────────────────────────
class SeverityBadge(QtWidgets.QWidget):
    def __init__(self, severity: str = "info", parent=None):
        super().__init__(parent)
        self._severity = severity
        self.setFixedSize(70, 22)

    def set_severity(self, s: str):
        self._severity = s
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(SEVERITY_COLORS.get(self._severity, PALETTE["text_muted"]))

        bg = QColor(color)
        bg.setAlpha(28)
        p.setPen(QPen(color, 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(self.rect(), 10, 10)

        font = QFont("Consolas", 9, QFont.Bold)
        p.setFont(font)
        p.setPen(QPen(color))
        p.drawText(self.rect(), Qt.AlignCenter, self._severity.upper())
        p.end()


# ──────────────────────────────────────────────
# KindBadge – timeline kind pill
# ──────────────────────────────────────────────
class KindBadge(QtWidgets.QWidget):
    def __init__(self, kind: str = "log", parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(78, 20)

    def set_kind(self, k: str):
        self._kind = k
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(KIND_COLORS.get(self._kind, PALETTE["text_muted"]))

        bg = QColor(color)
        bg.setAlpha(22)
        p.setPen(QPen(color, 1))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(self.rect(), 8, 8)

        font = QFont("Consolas", 8, QFont.Bold)
        p.setFont(font)
        p.setPen(QPen(color))
        p.drawText(self.rect(), Qt.AlignCenter, self._kind.upper())
        p.end()


# ──────────────────────────────────────────────
# NumericSortItem – QTableWidgetItem that sorts by int value
# ──────────────────────────────────────────────
class NumericSortItem(QtWidgets.QTableWidgetItem):
    """Drop-in replacement for QTableWidgetItem in PID columns.
    Overrides the < operator so that Qt's built-in table sort
    compares numerically instead of lexicographically."""

    def __lt__(self, other: QtWidgets.QTableWidgetItem) -> bool:
        try:
            return int(self.text()) < int(other.text())
        except (ValueError, TypeError):
            return self.text() < other.text()
