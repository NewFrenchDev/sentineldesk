from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ProcSample:
    ts: int
    pid: int
    ppid: int
    name: str
    exe: str
    user: str
    cpu_pct: float
    rss_bytes: int
    parent_name: str = ""
    parent_exe: str = ""

@dataclass(frozen=True)
class ConnSample:
    ts: int
    pid: int
    name: str
    exe: str
    user: str
    laddr: str
    raddr: str
    status: str

@dataclass(frozen=True)
class SystemSample:
    ts: int
    cpu_total_pct: float
    mem_used_bytes: int
    mem_total_bytes: int
    net_up_bps: float
    net_down_bps: float

@dataclass(frozen=True)
class Alert:
    ts: int
    severity: str       # info|low|medium|high
    rule_id: str
    summary: str
    exe_path: str = ""
    pid: Optional[int] = None
    user: str = ""
    details: str = ""
