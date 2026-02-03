from __future__ import annotations
from PySide6 import QtCore, QtWidgets
import sys
import time

from .config import load_config, DB_PATH
from .store import Store
from .integrity import IntegrityEngine
from .detectors import DetectionEngine
from .workers import SampleWorker
from .ui.main_window import MainWindow


class _TickRunnable(QtCore.QRunnable):
    """Runs one full sample cycle on a pool thread."""
    def __init__(self, worker: SampleWorker):
        super().__init__()
        self._worker = worker
        self.setAutoDelete(True)

    def run(self):
        self._worker.tick()


class Controller(QtCore.QObject):
    def __init__(self, cfg, store: Store, integrity: IntegrityEngine, 
                 detector: DetectionEngine, win: MainWindow):
        super().__init__()
        self.cfg       = cfg
        self.store     = store
        self.win       = win

        # Worker now does ALL heavy lifting on pool thread
        self.worker = SampleWorker(
            cfg.processes_max_rows, cfg.connections_max_rows,
            store, integrity, detector
        )

        # Connect signals - all queued automatically from pool → GUI thread
        self.worker.system_ready.connect(self.on_system)
        self.worker.procs_ready.connect(self.on_procs)
        self.worker.conns_ready.connect(self.on_conns)
        self.worker.persistence_ready.connect(self.on_persistence)
        self.worker.alerts_ready.connect(self.on_alerts)
        self.worker.timeline_event.connect(self.on_timeline)

        self._pool = QtCore.QThreadPool.globalInstance()

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(cfg.sample_interval_ms)
        self.timer.timeout.connect(self._schedule_tick)
        self.timer.start()

    def _schedule_tick(self):
        self._pool.start(_TickRunnable(self.worker))

    # ── signal handlers (NOW LIGHTWEIGHT - just UI updates) ───────────────────────
    @QtCore.Slot(object)
    def on_system(self, s):
        self.win.update_system(s)

    @QtCore.Slot(list)
    def on_procs(self, procs):
        self.win.update_processes(procs)

    @QtCore.Slot(list)
    def on_conns(self, conns):
        self.win.update_connections(conns)

    @QtCore.Slot(dict)
    def on_persistence(self, snapshot: dict):
        self.win.update_persistence_table()

    @QtCore.Slot(list)
    def on_alerts(self, alerts):
        """Batch-insert alerts into DB (fast - single commit)."""
        if alerts:
            self.store.add_alerts_batch(alerts)

    @QtCore.Slot(int, str, str, str)
    def on_timeline(self, ts, kind, summary, details):
        self.store.add_timeline(ts, kind, summary, details)


def main():
    cfg   = load_config()
    store = Store(str(DB_PATH))

    app = QtWidgets.QApplication(sys.argv)
    integrity = IntegrityEngine(store, cfg)
    detector  = DetectionEngine(store, cfg)
    win       = MainWindow(store, integrity, detector, cfg)

    controller = Controller(cfg, store, integrity, detector, win)
    win.show()

    code = app.exec()
    store.close()
    sys.exit(code)
