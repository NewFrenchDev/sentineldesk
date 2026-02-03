from __future__ import annotations
import hashlib
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from .models import Alert
from .store import Store
from .config import AppConfig

@dataclass(frozen=True)
class FileMeta:
    size_bytes: int
    mtime_ns: int

def _file_meta(path: str) -> Optional[FileMeta]:
    try:
        st = os.stat(path)
        return FileMeta(size_bytes=int(st.st_size), mtime_ns=int(st.st_mtime_ns))
    except Exception:
        return None

def sha256_file(path: str, chunk_mb: int = 1) -> str:
    h = hashlib.sha256()
    chunk_size = max(256 * 1024, chunk_mb * 1024 * 1024)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()

class IntegrityEngine:
    """
    Maintains integrity cache in SQLite with rate-limited hashing.
    - Stores (sha256, size, mtime)
    - Only hashes if metadata changed
    - Rate limits to max N new hashes per tick to avoid UI freezes
    """
    def __init__(self, store: Store, cfg: AppConfig):
        self.store = store
        self.cfg = cfg
        self._hash_budget = 0  # Reset each tick
        self._max_hashes_per_tick = 5  # Don't hash more than 5 files per second

    def reset_budget(self):
        """Call this at start of each tick."""
        self._hash_budget = self._max_hashes_per_tick

    def check_exe(self, ts: int, exe_path: str, pid: int, user: str) -> Optional[Alert]:
        if not exe_path:
            return None

        meta = _file_meta(exe_path)
        if not meta:
            return None  # exe inaccessible

        row = self.store.get_file_integrity(exe_path)
        if row is None:
            # first seen: compute hash and store (if budget allows)
            if self._hash_budget <= 0:
                return None  # Skip for now, will catch on next tick
            
            try:
                h = sha256_file(exe_path, chunk_mb=self.cfg.integrity_hash_chunk_mb)
                self._hash_budget -= 1
            except Exception:
                return None
            self.store.upsert_file_integrity(exe_path, h, meta.size_bytes, meta.mtime_ns, ts, pid, user, trusted=1)
            self.store.add_timeline(ts, "integrity", "New executable baseline", exe_path)
            return None

        old_hash, old_size, old_mtime_ns, trusted = row
        metadata_changed = (int(old_size) != meta.size_bytes) or (int(old_mtime_ns) != meta.mtime_ns)

        if self.cfg.integrity_rehash_on_metadata_change and metadata_changed:
            if self._hash_budget <= 0:
                # Mark as changed but don't hash yet
                return None
            
            try:
                new_hash = sha256_file(exe_path, chunk_mb=self.cfg.integrity_hash_chunk_mb)
                self._hash_budget -= 1
            except Exception:
                return None

            if new_hash != old_hash:
                # Update DB with new hash but mark untrusted until approved
                self.store.upsert_file_integrity(exe_path, new_hash, meta.size_bytes, meta.mtime_ns, ts, pid, user, trusted=0)
                self.store.add_timeline(ts, "integrity", "Executable hash changed", exe_path)

                return Alert(
                    ts=ts,
                    severity="high",
                    rule_id="INTEGRITY_HASH_CHANGED",
                    summary=f"Executable modified: {os.path.basename(exe_path)}",
                    exe_path=exe_path,
                    pid=pid,
                    user=user,
                    details=f"old_sha256={old_hash} new_sha256={new_hash}",
                )
            else:
                # Metadata changed but hash same => just refresh metadata
                self.store.upsert_file_integrity(exe_path, old_hash, meta.size_bytes, meta.mtime_ns, ts, pid, user, trusted=int(trusted))
        else:
            # No change
            self.store.upsert_file_integrity(exe_path, old_hash, meta.size_bytes, meta.mtime_ns, ts, pid, user, trusted=int(trusted))

        return None
