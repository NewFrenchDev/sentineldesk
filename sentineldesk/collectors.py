from __future__ import annotations
import time
import os
import sys
import subprocess
import csv
import io
import psutil
from typing import List, Dict
from collections import defaultdict
from pathlib import Path

from .models import ProcSample, ConnSample, SystemSample


def now_ts() -> int:
    return int(time.time())


# ──────────────────────────────────────────────
# Sampler – process / connection / system metrics
# ──────────────────────────────────────────────
class Sampler:
    def __init__(self):
        self._cpu_count = psutil.cpu_count(logical=True) or 1

        # warmup for per-process cpu%
        for p in psutil.process_iter():
            try:
                p.cpu_percent(None)
            except Exception:
                pass
        self._last_net = psutil.net_io_counters()
        self._last_ts  = time.time()

    # ── system ────────────────────────────────
    def system_sample(self) -> SystemSample:
        ts = now_ts()
        cpu_total = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()

        cur_net = psutil.net_io_counters()
        t = time.time()
        dt = max(0.001, t - self._last_ts)
        up_bps   = (cur_net.bytes_sent - self._last_net.bytes_sent) / dt
        down_bps = (cur_net.bytes_recv - self._last_net.bytes_recv) / dt
        self._last_net = cur_net
        self._last_ts  = t

        return SystemSample(
            ts=ts,
            cpu_total_pct=float(cpu_total),
            mem_used_bytes=int(mem.used),
            mem_total_bytes=int(mem.total),
            net_up_bps=float(up_bps),
            net_down_bps=float(down_bps),
        )

    # ── processes ─────────────────────────────
    def process_samples(self, max_rows: int = 50) -> List[ProcSample]:
        ts   = now_ts()
        rows: List[ProcSample] = []
        
        # First pass: build PID -> process info map for parent lookup
        pid_map = {}
        for p in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid_map[int(p.info["pid"])] = {
                    "name": p.info.get("name") or "",
                    "exe": p.info.get("exe") or "",
                }
            except Exception:
                continue
        
        # Second pass: collect samples with parent info
        for p in psutil.process_iter(["pid", "ppid", "name", "exe", "username"]):
            try:
                cpu = p.cpu_percent(interval=None) / self._cpu_count
                mi  = p.memory_info()
                pid = int(p.info["pid"])
                ppid = int(p.info.get("ppid") or 0)
                
                # Lookup parent info
                parent_info = pid_map.get(ppid, {})
                parent_name = parent_info.get("name", "")
                parent_exe = parent_info.get("exe", "")
                
                rows.append(ProcSample(
                    ts=ts,
                    pid=pid,
                    ppid=ppid,
                    name=p.info.get("name") or "",
                    exe=p.info.get("exe")  or "",
                    user=p.info.get("username") or "",
                    cpu_pct=float(cpu),
                    rss_bytes=int(mi.rss),
                    parent_name=parent_name,
                    parent_exe=parent_exe,
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        rows.sort(key=lambda r: r.cpu_pct, reverse=True)
        return rows[:max_rows]

    # ── connections ───────────────────────────
    def connection_samples(self, max_rows: int = 200) -> List[ConnSample]:
        ts     = now_ts()
        by_pid: Dict[int, list] = defaultdict(list)

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

        rows: List[ConnSample] = []
        for pid, lst in by_pid.items():
            try:
                p    = psutil.Process(pid)
                name = p.name()
                exe  = ""
                user = ""
                try:
                    exe  = p.exe()
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

        rows.sort(key=lambda r: (0 if r.status == "ESTABLISHED" else 1, r.name))
        return rows[:max_rows]


# ──────────────────────────────────────────────
# PersistenceCollector – Run keys / Startup / Tasks
# ──────────────────────────────────────────────
# Only meaningful on Windows; returns {} silently on other OS.

def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _read_run_keys() -> Dict[str, str]:
    """Read HKCU & HKLM Run / RunOnce keys. Returns {label: data}."""
    if not _is_windows():
        return {}
    try:
        import winreg
    except ImportError:
        return {}

    result: Dict[str, str] = {}
    _HIVES = [
        (winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_CURRENT_USER,  r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        # Wow6432Node (32-bit apps on 64-bit Windows)
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\RunOnce"),
    ]

    for hive, subkey in _HIVES:
        hive_name = "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(key, i)
                    label = f"run:{hive_name}\\{subkey}\\{name}"
                    result[label] = str(data)
                    i += 1
                except OSError:
                    break
        finally:
            winreg.CloseKey(key)

    return result


def _read_startup_folders() -> Dict[str, str]:
    """Enumerate files in per-user & All Users Startup folders."""
    if not _is_windows():
        return {}

    result: Dict[str, str] = {}
    folders = []

    # Per-user Startup
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        folders.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")

    # All Users Startup
    prog_data = os.environ.get("PROGRAMDATA", "")
    if prog_data:
        folders.append(Path(prog_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup")

    for folder in folders:
        try:
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if f.is_file():
                    label = f"startup:{folder.name}\\{f.name}"
                    result[label] = str(f)
        except Exception:
            continue

    return result


def _read_scheduled_tasks() -> Dict[str, str]:
    """
    Parse schtasks /query output (NO /v for speed).
    Filters out Microsoft\Windows tasks.
    Returns {task_name: status}.
    """
    if not _is_windows():
        return {}

    result: Dict[str, str] = {}
    try:
        # CREATE_NO_WINDOW constant for Windows
        CREATE_NO_WINDOW = 0x08000000
        
        proc = subprocess.run(
            ["schtasks", "/query", "/fo", "CSV", "/nh"],
            capture_output=True, text=True, timeout=3,  # Reduced timeout
            creationflags=CREATE_NO_WINDOW if _is_windows() else 0,
        )
        if proc.returncode != 0:
            return {}
        reader = csv.reader(io.StringIO(proc.stdout))
        for row in reader:
            if len(row) < 1:
                continue
            task_name = row[0].strip().strip('"')
            
            # Filter out system tasks EARLY to reduce parsing overhead
            if not task_name or task_name.startswith("TaskName"):
                continue
            if task_name.startswith("\\Microsoft\\Windows\\"):
                continue
            
            # schtasks CSV: TaskName, Status, LastRun, NextRun
            status = row[1].strip().strip('"') if len(row) > 1 else ""
            label  = f"task:{task_name}"
            result[label] = status
    except Exception:
        pass

    return result


class PersistenceCollector:
    """
    Collects all persistence mechanisms in one dict.
    Uses caching for scheduled tasks to avoid freezing.
    """
    def __init__(self):
        self._task_cache: Dict[str, str] = {}
        self._task_cache_ts: float = 0
        self._task_cache_ttl: int = 30  # Refresh every 30 seconds

    def collect(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        out.update(_read_run_keys())
        out.update(_read_startup_folders())
        
        # Cached task reading to avoid calling schtasks every second
        now = time.time()
        if now - self._task_cache_ts >= self._task_cache_ttl:
            self._task_cache = _read_scheduled_tasks()
            self._task_cache_ts = now
        
        out.update(self._task_cache)
        return out
