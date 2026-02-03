"""
sentineldesk – main window  (Sprint A: Process Tree, Persistence, sorting)
"""
from __future__ import annotations

import os
import time
from typing import List, Dict

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor, QPainter, QPen, QBrush, QPainterPath,
    QFont, QLinearGradient,
)

from ..models import ProcSample, ConnSample, SystemSample
from ..store import Store
from ..integrity import IntegrityEngine
from ..detectors import DetectionEngine
from ..config import AppConfig

from .widgets import (
    PALETTE, SEVERITY_COLORS, KIND_COLORS,
    fmt_bytes, fmt_bps,
    MetricCard, PulsingDot, SeverityBadge, KindBadge,
    get_process_icon, NumericSortItem,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _set_cell(table: QtWidgets.QTableWidget, row: int, col: int, text: str):
    item = QtWidgets.QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    table.setItem(row, col, item)


def _set_pid_cell(table: QtWidgets.QTableWidget, row: int, col: int, pid_text: str):
    """Insert a NumericSortItem so the PID column sorts as integers."""
    item = NumericSortItem(pid_text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    table.setItem(row, col, item)


# ──────────────────────────────────────────────
# TopBar
# ──────────────────────────────────────────────
class TopBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(12)

        # Single-label logo with two HTML spans flush together
        logo = QtWidgets.QLabel()
        logo.setText(
            f'<span style="font-family:Consolas,monospace;font-size:20px;'
            f'font-weight:800;color:{PALETTE["accent_cyan"]};letter-spacing:4px;">'
            f'SENTINEL</span>'
            f'<span style="font-family:Consolas,monospace;font-size:20px;'
            f'font-weight:300;color:{PALETTE["text_muted"]};letter-spacing:4px;">'
            f'DESK</span>'
        )
        lay.addWidget(logo)
        lay.addStretch(1)

        # LIVE badge
        live_row = QtWidgets.QHBoxLayout()
        live_row.setSpacing(6)
        self._live_dot = PulsingDot(color=PALETTE["green"], radius=5)
        live_row.addWidget(self._live_dot)
        live_lbl = QtWidgets.QLabel("LIVE")
        live_lbl.setStyleSheet(f"""
            font-family: 'Consolas', monospace;
            font-size: 11px; font-weight: 700;
            color: {PALETTE['green']}; letter-spacing: 2px;
        """)
        live_row.addWidget(live_lbl)
        lay.addLayout(live_row)

        # Clock
        self._clock = QtWidgets.QLabel("")
        self._clock.setStyleSheet(f"""
            font-family: 'Consolas', monospace;
            font-size: 13px; color: {PALETTE['text_muted']};
        """)
        lay.addWidget(self._clock)

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

    def _update_clock(self):
        self._clock.setText(time.strftime("%H:%M:%S"))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(PALETTE["bg_card"])))
        p.drawRect(0, 0, w, h)

        grad = QLinearGradient(0, h - 1, w, h - 1)
        grad.setColorAt(0,   QColor("#00000000"))
        grad.setColorAt(0.3, QColor(PALETTE["accent_cyan"]))
        grad.setColorAt(0.5, QColor(PALETTE["accent_cyan"]))
        grad.setColorAt(0.7, QColor(PALETTE["accent_cyan"]))
        grad.setColorAt(1,   QColor("#00000000"))
        p.setPen(QPen(QBrush(grad), 1.5))
        p.drawLine(0, h - 1, w, h - 1)
        p.end()
        super().paintEvent(_event)


# ──────────────────────────────────────────────
# AlertFlash – bottom status bar
# ──────────────────────────────────────────────
class AlertFlash(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        self._dot = PulsingDot(color=PALETTE["green"], radius=4)
        lay.addWidget(self._dot)

        self._label = QtWidgets.QLabel("System monitoring active …")
        self._label.setStyleSheet(f"""
            font-family: 'Consolas', monospace;
            font-size: 11px; color: {PALETTE['text_muted']};
        """)
        lay.addWidget(self._label, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._reset)

    def flash(self, msg: str, color: str = PALETTE["green"]):
        self._dot.set_color(color)
        self._label.setText(msg)
        self._label.setStyleSheet(f"""
            font-family: 'Consolas', monospace;
            font-size: 11px; color: {color};
        """)
        self._timer.stop()
        self._timer.setSingleShot(True)
        self._timer.setInterval(3500)
        self._timer.start()

    def _reset(self):
        self._dot.set_color(PALETTE["green"])
        self._label.setText("System monitoring active …")
        self._label.setStyleSheet(f"""
            font-family: 'Consolas', monospace;
            font-size: 11px; color: {PALETTE['text_muted']};
        """)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(PALETTE["bg_card"])))
        p.drawRect(self.rect())
        p.setPen(QPen(QColor(PALETTE["border"]), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()
        super().paintEvent(_event)


# ──────────────────────────────────────────────
# MainWindow
# ──────────────────────────────────────────────
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, store: Store, integrity: IntegrityEngine,
                 detector: DetectionEngine, cfg: AppConfig):
        super().__init__()
        self.store     = store
        self.integrity = integrity
        self.detector  = detector
        self.cfg       = cfg

        self.setWindowTitle("SentinelDesk")
        self.resize(1400, 820)
        self.setMinimumSize(1100, 680)

        self._last_procs: List[ProcSample] = []
        self._last_conns: List[ConnSample] = []

        self._build_ui()
        self._apply_global_style()

        # Periodic DB refresh (alerts / timeline / persistence)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1500)
        self._refresh_timer.timeout.connect(self._refresh_from_db)
        self._refresh_timer.start()
        self._refresh_from_db()

    # ═══════════════════════════════════════════
    # Layout
    # ═══════════════════════════════════════════
    def _build_ui(self):
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        root.setStyleSheet(f"background: {PALETTE['bg_deep']};")

        vroot = QtWidgets.QVBoxLayout(root)
        vroot.setContentsMargins(0, 0, 0, 0)
        vroot.setSpacing(0)

        # Top bar
        self.topbar = TopBar()
        vroot.addWidget(self.topbar)

        # Body
        body = QtWidgets.QWidget()
        body.setStyleSheet(f"background: {PALETTE['bg_deep']};")
        body_lay = QtWidgets.QVBoxLayout(body)
        body_lay.setContentsMargins(18, 16, 18, 8)
        body_lay.setSpacing(14)
        vroot.addWidget(body, 1)

        # ── Metric cards ──
        cards_row = QtWidgets.QHBoxLayout()
        cards_row.setSpacing(14)
        self.card_cpu = MetricCard("CPU Usage",  icon="⚡", color=PALETTE["accent_cyan"])
        self.card_mem = MetricCard("Memory",     icon="💾", color=PALETTE["accent_blue"])
        self.card_net = MetricCard("Network",    icon="🌐", color=PALETTE["accent_purple"])
        cards_row.addWidget(self.card_cpu, 1)
        cards_row.addWidget(self.card_mem, 1)
        cards_row.addWidget(self.card_net, 1)
        body_lay.addLayout(cards_row)

        # ── Tabs ──
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabPosition(QtWidgets.QTabWidget.North)
        body_lay.addWidget(self.tabs, 1)

        self._build_dashboard_tab()
        self._build_tree_tab()
        self._build_alerts_tab()
        self._build_persistence_tab()
        self._build_timeline_tab()

        # Refresh persistence table when user switches to that tab
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Status bar
        self.status_bar = AlertFlash()
        vroot.addWidget(self.status_bar)

    # ── Dashboard ─────────────────────────────
    def _build_dashboard_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.tbl_procs = self._make_sortable_table(
            ["Name", "PID", "User", "CPU %", "RAM", "Exe Path"],
            pid_col=1
        )
        self.tbl_conns = self._make_sortable_table(
            ["Process", "PID", "User", "Local Addr", "Remote Addr", "Status"],
            pid_col=1
        )

        lay.addWidget(self._card_wrap("⟳  Top Processes",        self.tbl_procs), 1)
        lay.addWidget(self._card_wrap("⟳  Active Connections",   self.tbl_conns), 1)
        self.tabs.addTab(w, "  Dashboard")

    # ── Process Tree ──────────────────────────
    def _build_tree_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        self.tree_procs = QtWidgets.QTreeWidget()
        self.tree_procs.setHeaderLabels(["Process", "PID", "PPID", "User", "CPU %", "RAM"])
        self.tree_procs.setRootIsDecorated(True)
        self.tree_procs.setAlternatingRowColors(True)
        self.tree_procs.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tree_procs.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.tree_procs.setIndentation(22)
        self.tree_procs.setFrameShape(QtWidgets.QFrame.NoFrame)

        # Make Name column sortable; expand on load
        hdr = self.tree_procs.header()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for c in (1, 2, 3):
            hdr.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        self.tree_procs.setSortingEnabled(True)
        self.tree_procs.sortByColumn(0, Qt.AscendingOrder)

        lay.addWidget(self.tree_procs, 1)
        self.tabs.addTab(w, "  Process Tree")

    # ── Alerts ────────────────────────────────
    def _build_alerts_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.tbl_alerts = self._make_table(
            ["Time", "Sev", "Rule", "Summary", "Executable", "PID", "User", "Status"]
        )
        self.tbl_alerts.setColumnWidth(1, 72)
        lay.addWidget(self.tbl_alerts, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_trust = self._make_button("✔  Approve & Trust Exe", PALETTE["green"])
        self.btn_trust.clicked.connect(self._trust_selected)
        btn_row.addWidget(self.btn_trust)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tabs.addTab(w, "  Alerts")

    # ── Persistence ───────────────────────────
    def _build_persistence_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.tbl_persist = self._make_table(
            ["Type", "Name", "Value", "First Seen", "Status"]
        )
        self.tbl_persist.setColumnWidth(4, 80)
        lay.addWidget(self.tbl_persist, 1)

        # Acknowledge button
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_ack_persist = self._make_button("✔  Acknowledge Entry", PALETTE["accent_cyan"])
        self.btn_ack_persist.clicked.connect(self._ack_persistence)
        btn_row.addWidget(self.btn_ack_persist)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tabs.addTab(w, "  Persistence")

    # ── Timeline ──────────────────────────────
    def _build_timeline_tab(self):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        self.tbl_timeline = self._make_table(["Time", "Kind", "Summary", "Details"])
        self.tbl_timeline.setColumnWidth(1, 90)
        lay.addWidget(self.tbl_timeline, 1)

        self.tabs.addTab(w, "  Timeline")

    def _on_tab_changed(self, index: int):
        """Called when user switches tabs. Refresh persistence if switching to that tab."""
        if index == 3:  # Persistence tab (Dashboard=0, Tree=1, Alerts=2, Persistence=3)
            self.update_persistence_table()

    # ═══════════════════════════════════════════
    # Widget factories
    # ═══════════════════════════════════════════
    def _make_table(self, headers: List[str]) -> QtWidgets.QTableWidget:
        t = QtWidgets.QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setStretchLastSection(True)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        t.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.setFrameShape(QtWidgets.QFrame.NoFrame)
        t.verticalHeader().setVisible(False)
        t.setFocusPolicy(Qt.StrongFocus)
        t.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    def _make_sortable_table(self, headers: List[str], pid_col: int = -1) -> QtWidgets.QTableWidget:
        """Same as _make_table but with sorting enabled."""
        t = self._make_table(headers)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.AscendingOrder)
        # Store pid_col index as attribute for use in update methods
        t._pid_col = pid_col  # type: ignore[attr-defined]
        return t

    def _card_wrap(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        card = QtWidgets.QWidget()
        card.setStyleSheet(f"""
            QWidget {{
                background: {PALETTE['bg_card']};
                border: 1px solid {PALETTE['border']};
                border-radius: 12px;
            }}
        """)
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        strip = QtWidgets.QWidget()
        strip.setFixedHeight(36)
        strip.setStyleSheet(f"""
            background: {PALETTE['bg_card']};
            border-bottom: 1px solid {PALETTE['border']};
            border-radius: 12px 12px 0px 0px;
        """)
        strip_lay = QtWidgets.QHBoxLayout(strip)
        strip_lay.setContentsMargins(14, 0, 14, 0)
        lbl = QtWidgets.QLabel(title)
        lbl.setStyleSheet(f"""
            font-family: 'Consolas', monospace;
            font-size: 11px; font-weight: 600;
            color: {PALETTE['accent_cyan']}; letter-spacing: 1px;
        """)
        strip_lay.addWidget(lbl)
        lay.addWidget(strip)
        lay.addWidget(widget, 1)
        return card

    def _make_button(self, text: str, accent: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {accent}18; color: {accent};
                border: 1px solid {accent}60;
                padding: 8px 18px; border-radius: 8px;
                font-family: 'Consolas', monospace;
                font-size: 12px; font-weight: 600;
            }}
            QPushButton:hover  {{ background: {accent}30; border-color: {accent}; }}
            QPushButton:pressed {{ background: {accent}45; }}
        """)
        return btn

    # ═══════════════════════════════════════════
    # Global stylesheet
    # ═══════════════════════════════════════════
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background: {PALETTE['bg_deep']}; }}

            /* Tabs */
            QTabBar {{ background: {PALETTE['bg_deep']}; border: none; spacing: 4px; }}
            QTabBar::tab {{
                background: transparent; color: {PALETTE['text_muted']};
                padding: 8px 18px;
                font-family: 'Consolas', monospace;
                font-size: 12px; font-weight: 600;
                letter-spacing: 1px; border-radius: 6px; margin-bottom: 4px;
            }}
            QTabBar::tab:selected {{
                background: {PALETTE['bg_card']}; color: {PALETTE['accent_cyan']};
                border: 1px solid {PALETTE['border']};
            }}
            QTabBar::tab:hover:!selected {{
                background: {PALETTE['bg_card']}80; color: {PALETTE['text_primary']};
            }}
            QTabWidget::pane {{ border: none; background: transparent; }}

            /* Tables */
            QTableWidget {{
                background: transparent; color: {PALETTE['text_primary']};
                border: none; border-radius: 0;
                font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;
                selection-background-color: {PALETTE['border_glow']};
                selection-color: {PALETTE['text_primary']};
                alternate-background-color: #12161c;
            }}
            QTableWidget::item {{
                padding: 7px 10px; border: none;
                border-bottom: 1px solid {PALETTE['border']};
            }}
            QTableWidget::item:selected {{
                background: {PALETTE['border_glow']}; color: {PALETTE['text_primary']};
            }}

            /* Tree widget */
            QTreeWidget {{
                background: {PALETTE['bg_card']}; color: {PALETTE['text_primary']};
                border: 1px solid {PALETTE['border']}; border-radius: 10px;
                font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;
                alternate-background-color: #12161c;
                selection-background-color: {PALETTE['border_glow']};
            }}
            QTreeWidget::item {{
                padding: 5px 8px; border: none;
                border-bottom: 1px solid {PALETTE['border']};
            }}
            QTreeWidget::item:selected {{
                background: {PALETTE['border_glow']}; color: {PALETTE['text_primary']};
            }}
            QTreeWidget::branch {{
                background: transparent;
            }}
            QTreeWidget::branch:has-siblings:!haschild:!has-next-sibling,
            QTreeWidget::branch:closed:has-children:!has-next-sibling,
            QTreeWidget::branch:open:has-children:!has-next-sibling,
            QTreeWidget::branch:has-siblings:!haschild:has-next-sibling,
            QTreeWidget::branch:closed:has-children:has-next-sibling,
            QTreeWidget::branch:open:has-children:has-next-sibling {{
                image: none;
            }}

            /* Headers (shared) */
            QHeaderView {{ background: {PALETTE['bg_card']}; border: none; }}
            QHeaderView::section {{
                background: {PALETTE['bg_card']}; color: {PALETTE['text_muted']};
                padding: 8px 10px; border: none;
                border-bottom: 1px solid {PALETTE['border']};
                font-family: 'Consolas', monospace;
                font-size: 10px; font-weight: 700;
                letter-spacing: 1.5px; text-transform: uppercase;
            }}
            QHeaderView::section:first {{ border-top-left-radius: 0; }}
            /* Sort indicator colour */
            QHeaderView::section::down-arrow {{ color: {PALETTE['accent_cyan']}; }}
            QHeaderView::section::up-arrow   {{ color: {PALETTE['accent_cyan']}; }}

            /* Scrollbar */
            QScrollBar:vertical {{ background: {PALETTE['bg_deep']}; width: 8px; }}
            QScrollBar::handle:vertical {{
                background: {PALETTE['border']}; border-radius: 4px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {PALETTE['border_glow']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

            MetricCard {{ border: none; background: transparent; }}
        """)

    # ═══════════════════════════════════════════
    # Data update hooks
    # ═══════════════════════════════════════════
    def update_system(self, s: SystemSample):
        cpu = s.cpu_total_pct
        self.card_cpu.value_label.set_value(cpu)
        self.card_cpu.sub_label.setText("")
        self.card_cpu.graph.push(cpu)

        if cpu > 85:
            self.card_cpu.dot.set_color(PALETTE["red"])
        elif cpu > 60:
            self.card_cpu.dot.set_color(PALETTE["orange"])
        else:
            self.card_cpu.dot.set_color(PALETTE["accent_cyan"])

        mem_pct = (s.mem_used_bytes / max(s.mem_total_bytes, 1)) * 100
        self.card_mem.value_label.set_value(mem_pct)
        self.card_mem.sub_label.setText(
            f"{fmt_bytes(s.mem_used_bytes)}  /  {fmt_bytes(s.mem_total_bytes)}"
        )
        self.card_mem.graph.push(mem_pct)

        total_bps = s.net_up_bps + s.net_down_bps
        self.card_net.value_label.set_value(total_bps / 1024)
        self.card_net.sub_label.setText(
            f"↑ {fmt_bps(s.net_up_bps)}   ↓ {fmt_bps(s.net_down_bps)}"
        )
        self.card_net.graph.push(total_bps / 1024)
        self.card_net.value_label._fmt = "{:.1f}"
        self.card_net.value_label.setText(f"{total_bps / 1024:.1f}")

    # ── Processes (Dashboard flat table) ──────
    def update_processes(self, procs: List[ProcSample]):
        self._last_procs = procs
        t = self.tbl_procs

        t.blockSignals(True)
        t.setSortingEnabled(False)         # disable while rebuilding
        t.setRowCount(len(procs))

        for r, p in enumerate(procs):
            icon = get_process_icon(p.name)
            _set_cell(t, r, 0, f"{icon}  {p.name}")
            _set_pid_cell(t, r, 1, str(p.pid))
            _set_cell(t, r, 2, p.user)

            cpu_txt = f"{p.cpu_pct:.1f}"
            _set_cell(t, r, 3, cpu_txt)
            item3 = t.item(r, 3)
            if item3:
                if p.cpu_pct > 85:
                    item3.setForeground(QColor(PALETTE["red"]))
                elif p.cpu_pct > 60:
                    item3.setForeground(QColor(PALETTE["orange"]))

            _set_cell(t, r, 4, fmt_bytes(p.rss_bytes))
            _set_cell(t, r, 5, p.exe)

        t.setSortingEnabled(True)          # re-enable → preserves user's chosen sort
        t.blockSignals(False)
        t.viewport().update()

        # Also refresh the process-tree tab
        self._update_process_tree(procs)

    # ── Connections ───────────────────────────
    def update_connections(self, conns: List[ConnSample]):
        self._last_conns = conns
        t = self.tbl_conns

        t.blockSignals(True)
        t.setSortingEnabled(False)
        t.setRowCount(len(conns))

        status_colors = {
            "ESTABLISHED": PALETTE["green"],
            "LISTEN":      PALETTE["accent_cyan"],
            "TIME_WAIT":   PALETTE["text_muted"],
            "CLOSE_WAIT":  PALETTE["orange"],
            "SYN_SENT":    PALETTE["yellow"],
        }

        for r, c in enumerate(conns):
            icon = get_process_icon(c.name)
            _set_cell(t, r, 0, f"{icon}  {c.name}")
            _set_pid_cell(t, r, 1, str(c.pid))
            _set_cell(t, r, 2, c.user)
            _set_cell(t, r, 3, c.laddr)
            _set_cell(t, r, 4, c.raddr)
            _set_cell(t, r, 5, c.status)

            col = status_colors.get(c.status, PALETTE["text_muted"])
            item = t.item(r, 5)
            if item:
                item.setForeground(QColor(col))

        t.setSortingEnabled(True)
        t.blockSignals(False)
        t.viewport().update()

    # ── Process Tree ──────────────────────────
    def _update_process_tree(self, procs: List[ProcSample]):
        tree = self.tree_procs
        tree.blockSignals(True)
        tree.setSortingEnabled(False)
        tree.clear()

        # Build maps
        by_pid: Dict[int, ProcSample] = {p.pid: p for p in procs}
        children_map: Dict[int, List[ProcSample]] = {}
        for p in procs:
            children_map.setdefault(p.ppid, []).append(p)

        # Identify which PIDs are suspicious (for coloring)
        suspicious_pids = self._get_suspicious_pids(procs, by_pid)

        # Root nodes = processes whose ppid is NOT in the current snapshot
        roots = [p for p in procs if p.ppid not in by_pid]

        def _make_item(p: ProcSample) -> QtWidgets.QTreeWidgetItem:
            icon = get_process_icon(p.name)
            item = QtWidgets.QTreeWidgetItem()
            item.setText(0, f"{icon}  {p.name}")
            item.setText(1, str(p.pid))
            item.setText(2, str(p.ppid))
            item.setText(3, p.user)
            item.setText(4, f"{p.cpu_pct:.1f}")
            item.setText(5, fmt_bytes(p.rss_bytes))

            # Colour suspicious nodes
            if p.pid in suspicious_pids:
                for col in range(6):
                    item.setForeground(col, QColor(PALETTE["red"]))
                # Subtle red background tint
                item.setBackground(0, QColor("#ef444415"))
                item.setBackground(1, QColor("#ef444415"))
                item.setBackground(2, QColor("#ef444415"))
                item.setBackground(3, QColor("#ef444415"))
                item.setBackground(4, QColor("#ef444415"))
                item.setBackground(5, QColor("#ef444415"))

            # CPU colour on column 4
            if p.cpu_pct > 85:
                item.setForeground(4, QColor(PALETTE["red"]))
            elif p.cpu_pct > 60:
                item.setForeground(4, QColor(PALETTE["orange"]))

            return item

        def _add_children(parent_item: QtWidgets.QTreeWidgetItem, ppid: int):
            for child in children_map.get(ppid, []):
                child_item = _make_item(child)
                parent_item.addChild(child_item)
                _add_children(child_item, child.pid)

        for root_proc in roots:
            root_item = _make_item(root_proc)
            tree.addTopLevelItem(root_item)
            _add_children(root_item, root_proc.pid)

        tree.expandToDepth(1)              # show first two levels expanded
        tree.setSortingEnabled(True)
        tree.blockSignals(False)

    def _get_suspicious_pids(self, procs: List[ProcSample],
                             by_pid: Dict[int, ProcSample]) -> set:
        """Return set of PIDs that match parentage rules (for tree colouring)."""
        suspicious: set = set()
        _OFFICE = {"winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe",
                   "onenote.exe", "access.exe", "soffice.exe", "soffice.bin"}
        _SHELLS = {"cmd.exe", "powershell.exe", "powershell_ise.exe",
                   "wscript.exe", "cscript.exe", "mshta.exe", "rundll32.exe"}
        _TEMP   = _get_suspicious_dirs_lower()

        for p in procs:
            if not p.exe:
                continue
            base = os.path.basename(p.exe).lower()
            parent = by_pid.get(p.ppid)
            parent_base = os.path.basename(parent.exe).lower() if parent and parent.exe else ""

            # Office → shell
            if base in _SHELLS and parent_base in _OFFICE:
                suspicious.add(p.pid)

            # Exe from suspicious dir
            d = os.path.dirname(p.exe).lower()
            for sd in _TEMP:
                if d.startswith(sd):
                    suspicious.add(p.pid)
                    break
        return suspicious

    # ── Persistence table ─────────────────────
    def update_persistence_table(self):
        """
        Refresh persistence table from DB.
        Called every 30s by timer - NOT on every tick.
        Uses batching to avoid UI freeze.
        """
        rows = self.store.list_persistence(limit=300)
        t = self.tbl_persist

        t.blockSignals(True)
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))

        # Process in batches asynchronously
        BATCH_SIZE = 100  # Larger batches since we only do this every 30s
        batch_index = [0]
        new_count_total = [0]

        def process_batch():
            start = batch_index[0]
            end = min(start + BATCH_SIZE, len(rows))
            
            for r in range(start, end):
                key, value, first_seen, _last_seen, ack = rows[r]
                
                # Decompose key → type + name
                if key.startswith("run:"):
                    kind = "Run Key"
                    name = key[4:]
                elif key.startswith("startup:"):
                    kind = "Startup"
                    name = key[8:]
                elif key.startswith("task:"):
                    kind = "Task"
                    name = key[5:]
                else:
                    kind = "Other"
                    name = key

                _set_cell(t, r, 0, kind)
                _set_cell(t, r, 1, name)
                _set_cell(t, r, 2, value)
                _set_cell(t, r, 3, time.strftime("%H:%M:%S", time.localtime(first_seen)))

                if ack:
                    status_text = "known"
                    status_color = PALETTE["green"]
                else:
                    status_text = "NEW"
                    status_color = PALETTE["orange"]
                    new_count_total[0] += 1

                _set_cell(t, r, 4, status_text)
                item = t.item(r, 4)
                if item:
                    item.setForeground(QColor(status_color))

                # Colour the whole row if NEW
                if not ack:
                    for c in range(5):
                        it = t.item(r, c)
                        if it and c != 4:
                            it.setBackground(QColor("#f9731620"))

            batch_index[0] = end
            
            # Schedule next batch or finalize
            if batch_index[0] < len(rows):
                QTimer.singleShot(0, process_batch)
            else:
                t.setSortingEnabled(True)
                t.blockSignals(False)
                t.viewport().update()

                persist_idx = 3
                if new_count_total[0] > 0:
                    self.tabs.setTabText(persist_idx, f"  Persistence  ({new_count_total[0]})")
                else:
                    self.tabs.setTabText(persist_idx, "  Persistence")

        # Start processing
        if rows:
            process_batch()
        else:
            t.setSortingEnabled(True)
            t.blockSignals(False)
            self.tabs.setTabText(3, "  Persistence")

    # ── DB refresh (alerts + timeline) ────────
    def _refresh_from_db(self):
        # ── Alerts ──
        alerts = self.store.list_alerts(limit=200)
        t = self.tbl_alerts
        t.blockSignals(True)
        t.setRowCount(len(alerts))

        open_count = 0
        for r, (ts, sev, rule, summary, exe, pid, user, details, status) in enumerate(alerts):
            if status == "open":
                open_count += 1

            _set_cell(t, r, 0, time.strftime("%H:%M:%S", time.localtime(ts)))

            badge = SeverityBadge(sev)
            t.setCellWidget(r, 1, badge)

            _set_cell(t, r, 2, rule)
            _set_cell(t, r, 3, summary)
            _set_cell(t, r, 4, exe or "")
            _set_cell(t, r, 5, "" if pid is None else str(pid))
            _set_cell(t, r, 6, user or "")

            st_text = status or "open"
            _set_cell(t, r, 7, st_text)
            st_colors = {
                "open": PALETTE["orange"], "ack": PALETTE["yellow"],
                "closed": PALETTE["green"], "trusted": PALETTE["accent_cyan"],
            }
            item = t.item(r, 7)
            if item:
                item.setForeground(QColor(st_colors.get(st_text, PALETTE["text_muted"])))

        t.blockSignals(False)
        t.viewport().update()

        # Alerts tab counter
        alerts_idx = 2
        if open_count > 0:
            self.tabs.setTabText(alerts_idx, f"  Alerts  ({open_count})")
        else:
            self.tabs.setTabText(alerts_idx, "  Alerts")

        # ── Timeline ──
        tl = self.store.list_timeline(limit=200)
        tt = self.tbl_timeline
        tt.blockSignals(True)
        tt.setRowCount(len(tl))

        for r, (ts, kind, summary, details) in enumerate(tl):
            _set_cell(tt, r, 0, time.strftime("%H:%M:%S", time.localtime(ts)))
            kb = KindBadge(kind)
            tt.setCellWidget(r, 1, kb)
            _set_cell(tt, r, 2, summary)
            _set_cell(tt, r, 3, details or "")

        tt.blockSignals(False)
        tt.viewport().update()

    # ── Trust / Ack actions ───────────────────
    def _trust_selected(self):
        row = self.tbl_alerts.currentRow()
        if row < 0:
            self.status_bar.flash("⚠  Select an alert row first.", PALETTE["orange"])
            return
        exe_item = self.tbl_alerts.item(row, 4)
        exe = exe_item.text().strip() if exe_item else ""
        if not exe:
            self.status_bar.flash("⚠  No executable path on this alert.", PALETTE["orange"])
            return
        self.store.mark_exe_trusted(exe, note="approved by user")
        self.store.add_timeline(int(time.time()), "integrity", "User approved update", exe)
        self.status_bar.flash(f"✔  Trusted: {exe}", PALETTE["green"])
        self._refresh_from_db()

    def _ack_persistence(self):
        row = self.tbl_persist.currentRow()
        if row < 0:
            self.status_bar.flash("⚠  Select a persistence row first.", PALETTE["orange"])
            return
        name_item = self.tbl_persist.item(row, 1)
        kind_item = self.tbl_persist.item(row, 0)
        if not name_item or not kind_item:
            return

        # Reconstruct the key from Kind + Name
        kind = kind_item.text().strip()
        name = name_item.text().strip()
        prefix_map = {"Run Key": "run:", "Startup": "startup:", "Task": "task:"}
        prefix = prefix_map.get(kind, "")
        key = f"{prefix}{name}"

        self.store.ack_persistence(key)
        self.status_bar.flash(f"✔  Acknowledged: {name}", PALETTE["green"])
        self.update_persistence_table()


# ──────────────────────────────────────────────
# Module-level helper (avoids re-computing env vars every frame)
# ──────────────────────────────────────────────
def _get_suspicious_dirs_lower() -> List[str]:
    dirs: List[str] = []
    for var in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
        v = os.environ.get(var, "")
        if v:
            dirs.append(v.lower().rstrip(os.sep) + os.sep)
    home = os.environ.get("USERPROFILE", "")
    if home:
        dirs.append(os.path.join(home, "Downloads").lower() + os.sep)
    return dirs
