from __future__ import annotations
import sqlite3
import time
from typing import Optional, Any, List, Tuple, Dict

from .config import DB_PATH, ensure_dirs
from .models import Alert

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_integrity (
  exe_path   TEXT PRIMARY KEY,
  sha256     TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  mtime_ns   INTEGER NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen  INTEGER NOT NULL,
  last_pid   INTEGER,
  last_user  TEXT,
  trust_note TEXT,
  trusted    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS process_seen (
  exe_path TEXT PRIMARY KEY,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS process_remote_seen (
  exe_path TEXT NOT NULL,
  remote TEXT NOT NULL,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  PRIMARY KEY (exe_path, remote)
);

CREATE TABLE IF NOT EXISTS timeline (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  details TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  severity TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  summary TEXT NOT NULL,
  exe_path TEXT,
  pid INTEGER,
  user TEXT,
  details TEXT,
  status TEXT DEFAULT 'open'
);

-- Sprint A: persistence baseline
CREATE TABLE IF NOT EXISTS persistence_baseline (
  key        TEXT PRIMARY KEY,   -- e.g. "run:HKCU\\...", "startup:foo.lnk", "task:MyTask"
  value      TEXT NOT NULL,     -- exe path / command line
  first_seen INTEGER NOT NULL,
  last_seen  INTEGER NOT NULL,
  ack        INTEGER DEFAULT 0  -- 1 = user acknowledged
);

-- Index to speed up ORDER BY first_seen DESC queries
CREATE INDEX IF NOT EXISTS idx_persistence_first_seen ON persistence_baseline(first_seen DESC);
"""


class Store:
    def __init__(self, db_path: str):
        ensure_dirs()
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def now_ts(self) -> int:
        return int(time.time())

    # ── meta ──────────────────────────────────
    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        cur = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    # ── timeline ──────────────────────────────
    def add_timeline(self, ts: int, kind: str, summary: str, details: str = "") -> None:
        self._conn.execute(
            "INSERT INTO timeline(ts,kind,summary,details) VALUES(?,?,?,?)",
            (ts, kind, summary, details),
        )
        self._conn.commit()

    def list_timeline(self, limit: int = 200) -> List[Tuple[Any, ...]]:
        cur = self._conn.execute(
            "SELECT ts, kind, summary, details FROM timeline ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    # ── alerts ────────────────────────────────
    def add_alert(self, a: Alert) -> None:
        self._conn.execute(
            "INSERT INTO alerts(ts,severity,rule_id,summary,exe_path,pid,user,details) VALUES(?,?,?,?,?,?,?,?)",
            (a.ts, a.severity, a.rule_id, a.summary, a.exe_path, a.pid, a.user, a.details),
        )
        self._conn.commit()
        self.add_timeline(a.ts, "alert", f"[{a.severity}] {a.summary}", a.details)

    def add_alerts_batch(self, alerts: List[Alert]) -> None:
        """Batch insert alerts with single commit - much faster."""
        if not alerts:
            return
        
        # Insert all alerts
        self._conn.executemany(
            "INSERT INTO alerts(ts,severity,rule_id,summary,exe_path,pid,user,details) VALUES(?,?,?,?,?,?,?,?)",
            [(a.ts, a.severity, a.rule_id, a.summary, a.exe_path, a.pid, a.user, a.details) for a in alerts]
        )
        
        # Insert timeline entries
        self._conn.executemany(
            "INSERT INTO timeline(ts,kind,summary,details) VALUES(?,?,?,?)",
            [(a.ts, "alert", f"[{a.severity}] {a.summary}", a.details) for a in alerts]
        )
        
        # Single commit for all
        self._conn.commit()

    def list_alerts(self, limit: int = 200) -> List[Tuple[Any, ...]]:
        cur = self._conn.execute(
            "SELECT ts,severity,rule_id,summary,exe_path,pid,user,details,status "
            "FROM alerts ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def mark_exe_trusted(self, exe_path: str, note: str = "trusted update") -> None:
        self._conn.execute(
            "UPDATE file_integrity SET trusted=1, trust_note=?, last_seen=? WHERE exe_path=?",
            (note, self.now_ts(), exe_path),
        )
        self._conn.commit()

    # ── seen tables ───────────────────────────
    def upsert_process_seen(self, exe_path: str, ts: int) -> None:
        self._conn.execute(
            "INSERT INTO process_seen(exe_path,first_seen,last_seen) VALUES(?,?,?) "
            "ON CONFLICT(exe_path) DO UPDATE SET last_seen=excluded.last_seen",
            (exe_path, ts, ts),
        )
        self._conn.commit()

    def has_process_seen(self, exe_path: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM process_seen WHERE exe_path=?", (exe_path,))
        return cur.fetchone() is not None

    def upsert_remote_seen(self, exe_path: str, remote: str, ts: int) -> None:
        self._conn.execute(
            "INSERT INTO process_remote_seen(exe_path,remote,first_seen,last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(exe_path,remote) DO UPDATE SET last_seen=excluded.last_seen",
            (exe_path, remote, ts, ts),
        )
        self._conn.commit()

    def has_remote_seen(self, exe_path: str, remote: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM process_remote_seen WHERE exe_path=? AND remote=?",
            (exe_path, remote),
        )
        return cur.fetchone() is not None

    # ── file integrity ────────────────────────
    def get_file_integrity(self, exe_path: str) -> Optional[Tuple[Any, ...]]:
        cur = self._conn.execute(
            "SELECT sha256,size_bytes,mtime_ns,trusted FROM file_integrity WHERE exe_path=?",
            (exe_path,),
        )
        return cur.fetchone()

    def upsert_file_integrity(
        self, exe_path: str, sha256: str, size_bytes: int, mtime_ns: int,
        ts: int, pid: int, user: str, trusted: int = 1,
    ) -> None:
        self._conn.execute(
            "INSERT INTO file_integrity(exe_path,sha256,size_bytes,mtime_ns,first_seen,last_seen,last_pid,last_user,trusted) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(exe_path) DO UPDATE SET "
            "sha256=excluded.sha256, size_bytes=excluded.size_bytes, mtime_ns=excluded.mtime_ns, "
            "last_seen=excluded.last_seen, last_pid=excluded.last_pid, last_user=excluded.last_user, trusted=excluded.trusted",
            (exe_path, sha256, size_bytes, mtime_ns, ts, ts, pid, user, trusted),
        )
        self._conn.commit()

    # ── persistence baseline (Sprint A) ───────
    def get_persistence_baseline(self) -> Dict[str, Tuple[str, int, int]]:
        """Returns {key: (value, first_seen, ack)}"""
        cur = self._conn.execute(
            "SELECT key, value, first_seen, ack FROM persistence_baseline"
        )
        return {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}

    def upsert_persistence(self, key: str, value: str, ts: int) -> None:
        self._conn.execute(
            "INSERT INTO persistence_baseline(key,value,first_seen,last_seen,ack) VALUES(?,?,?,?,0) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, last_seen=excluded.last_seen",
            (key, value, ts, ts),
        )
        self._conn.commit()

    def ack_persistence(self, key: str) -> None:
        self._conn.execute(
            "UPDATE persistence_baseline SET ack=1 WHERE key=?", (key,)
        )
        self._conn.commit()

    def list_persistence(self, limit: int = 300) -> List[Tuple[Any, ...]]:
        """Returns list of (key, value, first_seen, last_seen, ack) ordered by first_seen DESC"""
        cur = self._conn.execute(
            "SELECT key, value, first_seen, last_seen, ack FROM persistence_baseline ORDER BY first_seen DESC LIMIT ?",
            (limit,)
        )
        return cur.fetchall()
