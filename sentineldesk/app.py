from __future__ import annotations
from PySide6 import QtCore, QtWidgets
import sys

from .config import load_config, DB_PATH
from .store import Store
from .sampler import LightweightSampler
from .analyzer import BackgroundAnalyzer
from .ui.main_window import MainWindow


class _SampleRunnable(QtCore.QRunnable):
    """Runs one fast sample on pool thread."""
    def __init__(self, sampler: LightweightSampler):
        super().__init__()
        self._sampler = sampler
        self.setAutoDelete(True)
    
    def run(self):
        self._sampler.tick()


class Controller(QtCore.QObject):
    """
    Lightweight controller:
    - Fast sampling every 1s (UI updates)
    - Heavy analysis every 60s (background thread)
    """
    def __init__(self, cfg, store: Store, win: MainWindow):
        super().__init__()
        self.cfg = cfg
        self.store = store
        self.win = win
        
        # Fast sampler - runs every second on pool thread
        self.sampler = LightweightSampler(cfg.processes_max_rows, cfg.connections_max_rows)
        self.sampler.system_ready.connect(self.on_system)
        self.sampler.procs_ready.connect(self.on_procs)
        self.sampler.conns_ready.connect(self.on_conns)
        
        # Background analyzer - runs every 60s on separate thread
        self.analyzer = BackgroundAnalyzer(store, cfg)
        self.analyzer.alerts_found.connect(self.on_alerts_found)
        self.analyzer.start()  # Start background thread
        
        self._pool = QtCore.QThreadPool.globalInstance()
        
        # Fast sampling timer (1s)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(cfg.sample_interval_ms)
        self.timer.timeout.connect(self._schedule_sample)
        self.timer.start()
        
        # UI refresh timer for persistence tab (30s)
        self.ui_refresh_timer = QtCore.QTimer(self)
        self.ui_refresh_timer.setInterval(30000)  # 30 seconds
        self.ui_refresh_timer.timeout.connect(self.refresh_persistence_ui)
        self.ui_refresh_timer.start()
        
        print("[Controller] Initialized - fast sampling every 1s, analysis every 60s")
    
    def _schedule_sample(self):
        """Schedule fast sample on pool thread"""
        self._pool.start(_SampleRunnable(self.sampler))
    
    def refresh_persistence_ui(self):
        """Refresh persistence tab UI from DB every 30s"""
        self.win.update_persistence_table()
    
    # ── Signal handlers (lightweight - just UI updates) ───────
    @QtCore.Slot(object)
    def on_system(self, s):
        self.win.update_system(s)
        self.store.add_timeline(
            s.ts, "metric",
            f"CPU {s.cpu_total_pct:.0f}% | NET ↑{int(s.net_up_bps)}B/s ↓{int(s.net_down_bps)}B/s"
        )
    
    @QtCore.Slot(list)
    def on_procs(self, procs):
        self.win.update_processes(procs)
    
    @QtCore.Slot(list)
    def on_conns(self, conns):
        self.win.update_connections(conns)
    
    @QtCore.Slot(int)
    def on_alerts_found(self, count):
        """Called when background analyzer finds new alerts"""
        print(f"[Controller] {count} new alerts from background analysis")
        # Refresh alerts tab
        self.win._refresh_from_db()


def main():
    cfg = load_config()
    store = Store(str(DB_PATH))
    
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(store, None, None, cfg)  # No integrity/detector needed in UI anymore
    
    controller = Controller(cfg, store, win)
    win.show()
    
    code = app.exec()
    
    # Cleanup
    controller.analyzer.stop()
    store.close()
    sys.exit(code)
