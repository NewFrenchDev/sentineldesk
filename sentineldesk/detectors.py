from __future__ import annotations
import os
import time
from typing import List, Dict, Set, Optional
from collections import defaultdict, deque
from pathlib import Path

from .models import ProcSample, ConnSample, Alert
from .store import Store
from .config import AppConfig, DEFAULT_BLACKLIST


# ──────────────────────────────────────────────
# Static sets used by parentage rules
# ──────────────────────────────────────────────
_OFFICE_PARENTS = {
    "winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe",
    "onenote.exe", "access.exe", "publisher.exe", "msword.exe",
    # LibreOffice equivalents
    "soffice.exe", "soffice.bin",
}

_SHELL_CHILDREN = {
    "cmd.exe", "powershell.exe", "powershell_ise.exe",
    "wscript.exe", "cscript.exe", "mshta.exe",
    "rundll32.exe", "regsvr32.exe",
}

_SYSTEM_PARENTS_FOR_RUNDLL = {
    "explorer.exe", "svchost.exe", "services.exe", "csrss.exe",
    "winlogon.exe", "lsass.exe", "sihost.exe", "taskhostw.exe",
    "wmspawn.exe", "conhost.exe", "ctfmon.exe", "dwm.exe",
    "searchui.exe", "startmenuexperience.exe",
}


class DetectionEngine:
    def __init__(self, store: Store, cfg: AppConfig):
        self.store = store
        self.cfg   = cfg

        # CPU-spike rolling window per PID
        self._cpu_hist: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=max(5, cfg.cpu_spike_sustain_seconds))
        )

        # Blacklist cache
        self._bl_path:    str       = ""
        self._bl_mtime:   float     = 0.0
        self._bl_hashes:  Set[str]  = set()

        # Parentage: track which (parent_pid, child_pid) pairs we already alerted
        # so we don't spam the same alert every second.
        self._alerted_parentage: Set[tuple] = set()

    # ══════════════════════════════════════════
    # PUBLIC entry-points  (called by Controller)
    # ══════════════════════════════════════════

    def on_processes(self, procs: List[ProcSample]) -> List[Alert]:
        alerts: List[Alert] = []
        alerts.extend(self._check_cpu_spike(procs))
        alerts.extend(self._check_new_exe(procs))
        if self.cfg.suspicious_parent_alert:
            alerts.extend(self._check_parentage(procs))
        alerts.extend(self._check_blacklist(procs))
        return alerts

    def on_connections(self, conns: List[ConnSample]) -> List[Alert]:
        ts     = int(time.time())
        alerts: List[Alert] = []

        for c in conns:
            if not c.exe or not c.raddr:
                continue
            remote = c.raddr
            if self.cfg.new_network_process_alert:
                if not self.store.has_process_seen(c.exe):
                    self.store.upsert_process_seen(c.exe, ts)
            if self.cfg.new_remote_for_process_alert:
                if not self.store.has_remote_seen(c.exe, remote):
                    self.store.upsert_remote_seen(c.exe, remote, ts)
                    base  = os.path.basename(c.exe).lower()
                    noisy = {"chrome.exe", "msedge.exe", "firefox.exe", "steam.exe", "discord.exe"}
                    sev   = "low" if base in noisy else "medium"
                    alerts.append(Alert(
                        ts=ts, severity=sev, rule_id="NEW_REMOTE_ENDPOINT",
                        summary=f"New remote endpoint for {c.name}",
                        exe_path=c.exe, pid=c.pid, user=c.user,
                        details=f"{c.laddr} -> {c.raddr} ({c.status})",
                    ))
        return alerts

    def on_persistence(self, current: Dict[str, str]) -> List[Alert]:
        """Compare live persistence snapshot vs DB baseline → alert on NEW entries."""
        if not self.cfg.persistence_watch_enabled:
            return []

        ts      = int(time.time())
        alerts: List[Alert] = []
        baseline = self.store.get_persistence_baseline()   # {key: (value, first_seen, ack)}

        for key, value in current.items():
            if key not in baseline:
                # Brand new persistence entry — high severity
                alerts.append(Alert(
                    ts=ts, severity="high", rule_id="NEW_PERSISTENCE",
                    summary=f"New persistence entry detected",
                    exe_path=value,
                    details=f"key={key}  value={value}",
                ))
                self.store.add_timeline(ts, "integrity", "New persistence entry", key)
            # Always upsert so last_seen stays fresh
            self.store.upsert_persistence(key, value, ts)

        return alerts

    # ══════════════════════════════════════════
    # PRIVATE rule implementations
    # ══════════════════════════════════════════

    # ── CPU spike ─────────────────────────────
    def _check_cpu_spike(self, procs: List[ProcSample]) -> List[Alert]:
        ts     = int(time.time())
        alerts: List[Alert] = []

        for p in procs:
            if not p.exe:
                continue
            h = self._cpu_hist[p.pid]
            h.append(p.cpu_pct)
            if len(h) >= self.cfg.cpu_spike_sustain_seconds:
                window = list(h)[-self.cfg.cpu_spike_sustain_seconds:]
                if all(v >= self.cfg.cpu_spike_threshold_pct for v in window):
                    alerts.append(Alert(
                        ts=ts, severity="medium", rule_id="PROC_CPU_SPIKE",
                        summary=f"CPU spike sustained: {p.name} (PID {p.pid})",
                        exe_path=p.exe, pid=p.pid, user=p.user,
                        details=f"cpu_pct~{p.cpu_pct:.1f} threshold={self.cfg.cpu_spike_threshold_pct}",
                    ))
                    h.clear()
        return alerts

    # ── new exe baseline ──────────────────────
    def _check_new_exe(self, procs: List[ProcSample]) -> List[Alert]:
        ts = int(time.time())
        for p in procs:
            if not p.exe:
                continue
            if not self.store.has_process_seen(p.exe):
                self.store.upsert_process_seen(p.exe, ts)
                self.store.add_timeline(ts, "process", "New executable observed", p.exe)
            else:
                self.store.upsert_process_seen(p.exe, ts)
        return []   # intentionally no alert; too noisy

    # ── parentage rules ───────────────────────
    def _check_parentage(self, procs: List[ProcSample]) -> List[Alert]:
        ts = int(time.time())
        alerts: List[Alert] = []

        # Build pid → sample map
        by_pid: Dict[int, ProcSample] = {p.pid: p for p in procs}

        # Resolve suspicious temp / downloads paths once
        _temp_paths = _get_suspicious_dirs()

        for child in procs:
            if not child.exe:
                continue
            child_base = os.path.basename(child.exe).lower()
            parent = by_pid.get(child.ppid)
            parent_base = os.path.basename(parent.exe).lower() if parent and parent.exe else ""

            # ── Rule A: shell spawned by Office ──
            if child_base in _SHELL_CHILDREN and parent_base in _OFFICE_PARENTS:
                key = (child.ppid, child.pid, "OFFICE_SHELL")
                if key not in self._alerted_parentage:
                    self._alerted_parentage.add(key)
                    alerts.append(Alert(
                        ts=ts, severity="high", rule_id="SUSPICIOUS_PARENTAGE_OFFICE",
                        summary=f"Shell spawned by Office: {child_base} ← {parent_base}",
                        exe_path=child.exe, pid=child.pid, user=child.user,
                        details=f"child={child.exe}  parent_pid={child.ppid} parent={parent.exe if parent else '?'}",
                    ))

            # ── Rule B: exe launched from Temp / Downloads / AppData ──
            child_dir = os.path.dirname(child.exe).lower()
            for sus_dir in _temp_paths:
                if child_dir.startswith(sus_dir):
                    key = (child.ppid, child.pid, "TEMP_EXE")
                    if key not in self._alerted_parentage:
                        self._alerted_parentage.add(key)
                        alerts.append(Alert(
                            ts=ts, severity="medium", rule_id="EXE_FROM_SUSPICIOUS_DIR",
                            summary=f"Exe launched from suspicious dir: {child_base}",
                            exe_path=child.exe, pid=child.pid, user=child.user,
                            details=f"path={child.exe}  suspicious_prefix={sus_dir}",
                        ))
                    break   # one alert per child

            # ── Rule C: rundll32 with non-system parent ──
            if child_base == "rundll32.exe" and parent_base and parent_base not in _SYSTEM_PARENTS_FOR_RUNDLL:
                key = (child.ppid, child.pid, "RUNDLL_SUSPECT")
                if key not in self._alerted_parentage:
                    self._alerted_parentage.add(key)
                    alerts.append(Alert(
                        ts=ts, severity="medium", rule_id="RUNDLL32_SUSPICIOUS_PARENT",
                        summary=f"rundll32 spawned by non-system process: {parent_base}",
                        exe_path=child.exe, pid=child.pid, user=child.user,
                        details=f"parent_pid={child.ppid} parent={parent.exe if parent else '?'}",
                    ))

        # Prune stale entries (PIDs that are no longer alive)
        live_pairs = {(p.ppid, p.pid) for p in procs}
        self._alerted_parentage = {
            k for k in self._alerted_parentage
            if (k[0], k[1]) in live_pairs
        }

        return alerts

    # ── hash blacklist ────────────────────────
    def _load_blacklist(self) -> None:
        """Load / reload the blacklist file if it changed on disk."""
        path = self.cfg.blacklist_path or DEFAULT_BLACKLIST
        if not path or not os.path.isfile(path):
            self._bl_hashes = set()
            return
        try:
            mtime = os.path.getmtime(path)
            if mtime == self._bl_mtime and self._bl_path == path:
                return   # no change
            self._bl_path   = path
            self._bl_mtime  = mtime
            hashes: Set[str] = set()
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    h = line.strip().lower()
                    if len(h) == 64:          # valid SHA-256
                        hashes.add(h)
            self._bl_hashes = hashes
        except Exception:
            self._bl_hashes = set()

    def _check_blacklist(self, procs: List[ProcSample]) -> List[Alert]:
        self._load_blacklist()
        if not self._bl_hashes:
            return []

        ts     = int(time.time())
        alerts: List[Alert] = []

        for p in procs:
            if not p.exe:
                continue
            row = self.store.get_file_integrity(p.exe)
            if row is None:
                continue
            sha, *_ = row
            if sha and sha.lower() in self._bl_hashes:
                alerts.append(Alert(
                    ts=ts, severity="high", rule_id="BLACKLISTED_HASH",
                    summary=f"Blacklisted executable running: {os.path.basename(p.exe)}",
                    exe_path=p.exe, pid=p.pid, user=p.user,
                    details=f"sha256={sha}",
                ))
        return alerts


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _get_suspicious_dirs() -> List[str]:
    """Return lowercased paths that are considered suspicious launch dirs."""
    dirs: List[str] = []
    for var in ("TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
        v = os.environ.get(var, "")
        if v:
            dirs.append(v.lower().rstrip(os.sep) + os.sep)
    # Downloads
    home = os.environ.get("USERPROFILE", "")
    if home:
        dirs.append(os.path.join(home, "Downloads").lower() + os.sep)
    return dirs
