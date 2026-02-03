from __future__ import annotations
from PySide6 import QtCore
from typing import List, Dict
import time

from .collectors import Sampler, PersistenceCollector
from .models import ProcSample, ConnSample, SystemSample, Alert
from .store import Store
from .integrity import IntegrityEngine
from .detectors import DetectionEngine


class SampleWorker(QtCore.QObject):
    """
    Runs all heavy operations (sampling, hashing, detection) on thread pool.
    Emits only UI-ready data and alerts to GUI thread.
    """
    system_ready      = QtCore.Signal(object)   # SystemSample
    procs_ready       = QtCore.Signal(list)     # List[ProcSample]
    conns_ready       = QtCore.Signal(list)     # List[ConnSample]
    persistence_ready = QtCore.Signal(dict)     # Dict[str, str]
    alerts_ready      = QtCore.Signal(list)     # List[Alert] - new signal for alerts
    timeline_event    = QtCore.Signal(int, str, str, str)  # ts, kind, summary, details

    def __init__(self, max_procs: int, max_conns: int, store: Store, 
                 integrity: IntegrityEngine, detector: DetectionEngine):
        super().__init__()
        self.max_procs  = max_procs
        self.max_conns  = max_conns
        self._sampler   = Sampler()
        self._persist   = PersistenceCollector()
        self.store      = store
        self.integrity  = integrity
        self.detector   = detector
        
        # Cache last persistence snapshot to avoid emitting unchanged data
        self._last_persistence_snapshot = {}
        self._last_persistence_emit = 0
        self._persistence_emit_interval = 30  # Only emit every 30s max

    @QtCore.Slot()
    def tick(self):
        """
        RUNS ON POOL THREAD - do all heavy work here.
        Only emit UI-ready data at the end.
        """
        ts = int(time.time())
        alerts = []

        # Reset integrity hashing budget (prevents freezes from too many hashes)
        self.integrity.reset_budget()

        # 1. Collect samples (fast)
        sys_s   = self._sampler.system_sample()
        procs   = self._sampler.process_samples(max_rows=self.max_procs)
        conns   = self._sampler.connection_samples(max_rows=self.max_conns)
        persist = self._persist.collect()

        # 2. Run integrity checks (HEAVY - SHA-256 hashing, but rate-limited)
        for p in procs:
            a = self.integrity.check_exe(ts, p.exe, p.pid, p.user)
            if a:
                alerts.append(a)

        # 3. Run detection rules (HEAVY - registry reads, parentage checks, blacklist)
        alerts.extend(self.detector.on_processes(procs))
        alerts.extend(self.detector.on_connections(conns))
        alerts.extend(self.detector.on_persistence(persist))

        # 4. Emit timeline event for system metrics
        self.timeline_event.emit(
            sys_s.ts, "metric",
            f"CPU {sys_s.cpu_total_pct:.0f}% | NET ↑{int(sys_s.net_up_bps)}B/s ↓{int(sys_s.net_down_bps)}B/s",
            ""
        )

        # 5. Emit all results to GUI thread (queued automatically)
        self.system_ready.emit(sys_s)
        self.procs_ready.emit(procs)
        self.conns_ready.emit(conns)
        
        # CRITICAL: Only emit persistence_ready if data changed OR 30s elapsed
        # This prevents flooding the GUI with unchanged persistence snapshots
        if (persist != self._last_persistence_snapshot or 
            ts - self._last_persistence_emit >= self._persistence_emit_interval):
            self.persistence_ready.emit(persist)
            self._last_persistence_snapshot = persist.copy()
            self._last_persistence_emit = ts
        
        if alerts:
            self.alerts_ready.emit(alerts)
