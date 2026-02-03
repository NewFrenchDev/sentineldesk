from __future__ import annotations
import time
import psutil
from typing import List
from PySide6 import QtCore

from .models import ProcSample, ConnSample, SystemSample


class LightweightSampler(QtCore.QObject):
    """
    Ultra-fast sampler - ONLY collects raw data, NO processing.
    - NO hashing
    - NO detection
    - NO registry/schtasks
    Just psutil → emit to UI. Analysis happens in BackgroundAnalyzer.
    """
    
    system_ready = QtCore.Signal(object)   # SystemSample
    procs_ready = QtCore.Signal(list)      # List[ProcSample] - top 50 only
    conns_ready = QtCore.Signal(list)      # List[ConnSample] - top 200 only
    
    def __init__(self, max_procs: int = 50, max_conns: int = 200):
        super().__init__()
        self.max_procs = max_procs
        self.max_conns = max_conns
        self._cpu_count = psutil.cpu_count(logical=True) or 1
        
        # Warmup
        for p in psutil.process_iter():
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        
        self._last_net = psutil.net_io_counters()
        self._last_ts = time.time()
    
    @QtCore.Slot()
    def tick(self):
        """
        Fast tick - just collect and emit. No heavy operations.
        Target: <20ms per tick.
        """
        ts = int(time.time())
        
        # System metrics (fast - 5ms)
        sys_sample = self._system_sample(ts)
        
        # Process samples (fast - 10ms)
        procs = self._process_samples(ts)
        
        # Connection samples (fast - 5ms)
        conns = self._connection_samples(ts)
        
        # Emit to UI (top N only for performance)
        self.system_ready.emit(sys_sample)
        self.procs_ready.emit(procs[:self.max_procs])
        self.conns_ready.emit(conns[:self.max_conns])
    
    def _system_sample(self, ts: int) -> SystemSample:
        cpu_total = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        
        cur_net = psutil.net_io_counters()
        t = time.time()
        dt = max(0.001, t - self._last_ts)
        up_bps = (cur_net.bytes_sent - self._last_net.bytes_sent) / dt
        down_bps = (cur_net.bytes_recv - self._last_net.bytes_recv) / dt
        self._last_net = cur_net
        self._last_ts = t
        
        return SystemSample(
            ts=ts,
            cpu_total_pct=float(cpu_total),
            mem_used_bytes=int(mem.used),
            mem_total_bytes=int(mem.total),
            net_up_bps=float(up_bps),
            net_down_bps=float(down_bps),
        )
    
    def _process_samples(self, ts: int) -> List[ProcSample]:
        rows = []
        
        # Build PID map for parent lookups
        pid_map = {}
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid_map[int(p.info["pid"])] = {
                    "name": p.info.get("name") or "",
                    "exe": p.info.get("exe") or "",
                }
            except Exception:
                continue
        
        # Collect process data
        for p in psutil.process_iter(["pid", "ppid", "name", "exe", "username"]):
            try:
                cpu = p.cpu_percent(interval=None) / self._cpu_count
                mi = p.memory_info()
                pid = int(p.info["pid"])
                ppid = int(p.info.get("ppid") or 0)
                
                parent_info = pid_map.get(ppid, {})
                
                rows.append(ProcSample(
                    ts=ts,
                    pid=pid,
                    ppid=ppid,
                    name=p.info.get("name") or "",
                    exe=p.info.get("exe") or "",
                    user=p.info.get("username") or "",
                    cpu_pct=float(cpu),
                    rss_bytes=int(mi.rss),
                    parent_name=parent_info.get("name", ""),
                    parent_exe=parent_info.get("exe", ""),
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        
        # Sort by CPU (for UI display)
        rows.sort(key=lambda r: r.cpu_pct, reverse=True)
        return rows
    
    def _connection_samples(self, ts: int) -> List[ConnSample]:
        from collections import defaultdict
        
        by_pid = defaultdict(list)
        
        try:
            conns = psutil.net_connections(kind="tcp")
        except Exception:
            conns = []
        
        for c in conns:
            if not c.pid or not c.raddr:
                continue
            laddr = f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else ""
            raddr = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
            by_pid[int(c.pid)].append((laddr, raddr, c.status))
        
        rows = []
        for pid, lst in by_pid.items():
            try:
                p = psutil.Process(pid)
                name = p.name()
                exe = ""
                user = ""
                try:
                    exe = p.exe()
                except Exception:
                    pass
                try:
                    user = p.username()
                except Exception:
                    pass
                
                for (laddr, raddr, status) in lst:
                    rows.append(ConnSample(
                        ts=ts, pid=pid, name=name, exe=exe, user=user,
                        laddr=laddr, raddr=raddr, status=status,
                    ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue
        
        # Sort by status (ESTABLISHED first)
        rows.sort(key=lambda r: (0 if r.status == "ESTABLISHED" else 1, r.name))
        return rows
