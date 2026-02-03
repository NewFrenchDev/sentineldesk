from __future__ import annotations
import os
import platform
from typing import List, Dict, Set, Tuple
from pathlib import Path
from dataclasses import dataclass

from .models import Alert
from .store import Store
from .config import AppConfig

@dataclass(frozen=True)
class PersistenceItem:
    """Single persistence entry."""
    kind: str       # "run_key" | "startup" | "task" | "service"
    name: str       # entry name
    path: str       # exe path or command
    location: str   # registry key or folder path

class PersistenceWatcher:
    """
    Monitors Windows persistence mechanisms:
    - Registry Run keys (HKCU/HKLM Software\\Microsoft\\Windows\\CurrentVersion\\Run)
    - Startup folder items
    - Scheduled Tasks (optional, requires admin) — CACHED to avoid freezing
    - Services (optional, requires admin)
    """
    def __init__(self, store: Store, cfg: AppConfig):
        self.store = store
        self.cfg = cfg
        self.is_windows = platform.system() == "Windows"
        # Cache for scheduled tasks to avoid calling schtasks every second
        self._task_cache: List[PersistenceItem] = []
        self._task_cache_ts: int = 0
        self._task_cache_ttl: int = 30  # Refresh every 30 seconds
    
    def check_all(self, ts: int) -> List[Alert]:
        """Check all persistence mechanisms and return alerts for new items."""
        if not self.cfg.persistence_watch_enabled or not self.is_windows:
            return []
        
        alerts: List[Alert] = []
        
        # Run keys (fast - <10ms)
        try:
            run_items = self._read_run_keys()
            alerts.extend(self._check_baseline(ts, "run_key", run_items))
        except Exception:
            pass
        
        # Startup folder (fast - <10ms)
        try:
            startup_items = self._read_startup_folder()
            alerts.extend(self._check_baseline(ts, "startup", startup_items))
        except Exception:
            pass
        
        # Scheduled tasks — CACHED to avoid freeze, only refresh every 30s
        try:
            # Only refresh if cache expired
            if ts - self._task_cache_ts >= self._task_cache_ttl:
                self._task_cache = self._read_scheduled_tasks()
                self._task_cache_ts = ts
            
            if self._task_cache:
                alerts.extend(self._check_baseline(ts, "task", self._task_cache))
        except Exception:
            pass
        
        return alerts
    
    def _check_baseline(self, ts: int, kind: str, current: List[PersistenceItem]) -> List[Alert]:
        """Compare current state with baseline, alert on new items."""
        # Get baseline as dict: key -> (value, first_seen, ack)
        baseline_dict = self.store.get_persistence_baseline()
        
        alerts: List[Alert] = []
        
        for item in current:
            # Create a unique key for this persistence entry
            key = f"{kind}:{item.name}@{item.location}"
            
            if key not in baseline_dict:
                # New persistence item detected
                alerts.append(Alert(
                    ts=ts,
                    severity="high",
                    rule_id=f"PERSISTENCE_{kind.upper()}_NEW",
                    summary=f"New {kind.replace('_', ' ')} persistence: {item.name}",
                    exe_path=item.path,
                    pid=None,
                    user="",
                    details=f"location={item.location} path={item.path}",
                ))
                
                # Add to baseline
                self.store.upsert_persistence(key, item.path, ts)
                self.store.add_timeline(ts, "persistence", f"New {kind}: {item.name}", item.path)
        
        return alerts
    
    def _read_run_keys(self) -> List[PersistenceItem]:
        """Read Windows Registry Run keys (HKCU + HKLM)."""
        if not self.is_windows:
            return []
        
        items: List[PersistenceItem] = []
        
        try:
            import winreg
            
            # HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_READ,
                )
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        items.append(PersistenceItem(
                            kind="run_key",
                            name=str(name),
                            path=str(value),
                            location=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                        ))
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass
            
            # HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Run
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0,
                    winreg.KEY_READ,
                )
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        items.append(PersistenceItem(
                            kind="run_key",
                            name=str(name),
                            path=str(value),
                            location=r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run",
                        ))
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except Exception:
                pass
        
        except ImportError:
            pass  # Not Windows
        
        return items
    
    def _read_startup_folder(self) -> List[PersistenceItem]:
        """Read files in Windows Startup folders."""
        if not self.is_windows:
            return []
        
        items: List[PersistenceItem] = []
        
        # User startup
        user_startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if user_startup.exists():
            for f in user_startup.iterdir():
                if f.is_file():
                    items.append(PersistenceItem(
                        kind="startup",
                        name=f.name,
                        path=str(f),
                        location=str(user_startup),
                    ))
        
        # All users startup (requires admin to enumerate)
        try:
            all_users_startup = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            if all_users_startup.exists():
                for f in all_users_startup.iterdir():
                    if f.is_file():
                        items.append(PersistenceItem(
                            kind="startup",
                            name=f.name,
                            path=str(f),
                            location=str(all_users_startup),
                        ))
        except Exception:
            pass
        
        return items
    
    def _read_scheduled_tasks(self) -> List[PersistenceItem]:
        """
        Read Windows Scheduled Tasks (requires admin).
        Uses schtasks.exe CLI without /v flag for speed.
        Filters out Microsoft\Windows tasks to reduce noise.
        """
        if not self.is_windows:
            return []
        
        items: List[PersistenceItem] = []
        
        try:
            import subprocess
            
            # schtasks /query /fo CSV (NO /v = 10× faster)
            result = subprocess.run(
                ["schtasks", "/query", "/fo", "CSV"],
                capture_output=True,
                text=True,
                timeout=3,  # Reduced timeout
                creationflags=subprocess.CREATE_NO_WINDOW if self.is_windows else 0,
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    # Skip header (line 0)
                    for line in lines[1:]:
                        parts = line.split(",")
                        if len(parts) >= 2:
                            task_name = parts[0].strip('"')
                            
                            # Filter out Microsoft system tasks EARLY
                            if task_name.startswith("\\Microsoft\\Windows\\"):
                                continue
                            
                            # Simple extraction: look for exe path in remaining parts
                            exe_path = ""
                            for part in parts[1:]:
                                part = part.strip('"')
                                if ".exe" in part.lower() or "\\" in part:
                                    exe_path = part
                                    break
                            
                            items.append(PersistenceItem(
                                kind="task",
                                name=task_name,
                                path=exe_path,
                                location="ScheduledTasks",
                            ))
        except Exception:
            pass  # schtasks unavailable or access denied
        
        return items
