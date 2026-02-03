from __future__ import annotations
import time
from PySide6 import QtCore
from typing import List

from .store import Store
from .config import AppConfig
from .integrity import IntegrityEngine
from .detectors import DetectionEngine
from .collectors import PersistenceCollector
from .models import Alert


class BackgroundAnalyzer(QtCore.QThread):
    """
    Heavy analysis runs every 60 seconds on separate thread.
    Does NOT block the UI or the fast sampling loop.
    
    Tasks:
    - Integrity checking (SHA-256 hashing of new executables)
    - Persistence monitoring (registry, scheduled tasks)
    - Detection rules (suspicious parentage, blacklist, etc.)
    - Writes alerts to DB
    """
    
    alerts_found = QtCore.Signal(int)  # Emit count of new alerts
    
    def __init__(self, store: Store, cfg: AppConfig):
        super().__init__()
        self.store = store
        self.cfg = cfg
        self.integrity = IntegrityEngine(store, cfg)
        self.detector = DetectionEngine(store, cfg)
        self.persistence = PersistenceCollector()
        
        self._running = True
        self._analysis_interval = 60  # Run every 60 seconds
        
        print("[BackgroundAnalyzer] Initialized - will run every 60s")
    
    def stop(self):
        """Graceful shutdown"""
        self._running = False
        self.wait()
    
    def run(self):
        """
        Main thread loop - runs heavy analysis every 60s.
        """
        print("[BackgroundAnalyzer] Thread started")
        
        while self._running:
            # Wait 60 seconds (but check every second for shutdown)
            for _ in range(self._analysis_interval):
                if not self._running:
                    return
                time.sleep(1)
            
            # Run full analysis
            try:
                print(f"[BackgroundAnalyzer] Starting analysis at {time.time()}")
                start = time.time()
                
                alerts = self._analyze()
                
                elapsed = time.time() - start
                print(f"[BackgroundAnalyzer] Analysis complete in {elapsed:.2f}s, {len(alerts)} alerts")
                
                # Write alerts to DB
                if alerts:
                    self.store.add_alerts_batch(alerts)
                    self.alerts_found.emit(len(alerts))
                
            except Exception as e:
                print(f"[BackgroundAnalyzer] Error during analysis: {e}")
                import traceback
                traceback.print_exc()
    
    def _analyze(self) -> List[Alert]:
        """
        Full analysis cycle - returns list of alerts.
        This is HEAVY and runs on background thread.
        """
        ts = int(time.time())
        alerts = []
        
        # 1. Get recent process samples from current snapshot (not DB)
        # We analyze processes that are CURRENTLY running
        from .sampler import LightweightSampler
        sampler = LightweightSampler()
        
        # Do a quick sample
        procs = sampler._process_samples(ts)
        conns = sampler._connection_samples(ts)
        
        print(f"[BackgroundAnalyzer] Analyzing {len(procs)} processes, {len(conns)} connections")
        
        # 2. Integrity checks (SHA-256 hashing)
        # Reset budget for this analysis cycle
        self.integrity.reset_budget()
        self.integrity._max_hashes_per_tick = 50  # Allow more hashes in background
        
        integrity_start = time.time()
        for p in procs:
            if not p.exe:
                continue
            a = self.integrity.check_exe(ts, p.exe, p.pid, p.user)
            if a:
                alerts.append(a)
        integrity_time = time.time() - integrity_start
        print(f"[BackgroundAnalyzer] Integrity checks: {integrity_time:.2f}s")
        
        # 3. Detection rules
        detection_start = time.time()
        
        # Process-based detections
        proc_alerts = self.detector.on_processes(procs)
        alerts.extend(proc_alerts)
        
        # Connection-based detections
        conn_alerts = self.detector.on_connections(conns)
        alerts.extend(conn_alerts)
        
        detection_time = time.time() - detection_start
        print(f"[BackgroundAnalyzer] Detection rules: {detection_time:.2f}s, {len(proc_alerts)+len(conn_alerts)} alerts")
        
        # 4. Persistence monitoring (registry, scheduled tasks)
        persist_start = time.time()
        persist_snapshot = self.persistence.collect()
        persist_alerts = self.detector.on_persistence(persist_snapshot)
        alerts.extend(persist_alerts)
        persist_time = time.time() - persist_start
        print(f"[BackgroundAnalyzer] Persistence check: {persist_time:.2f}s, {len(persist_alerts)} alerts")
        
        return alerts
