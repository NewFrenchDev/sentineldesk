from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import json

APP_DIR = Path.home() / ".sentineldesk"
DB_PATH = APP_DIR / "sentineldesk.db"
CFG_PATH = APP_DIR / "config.json"

# Default blacklist ships beside the app; user can point to their own.
DEFAULT_BLACKLIST = str(APP_DIR / "blacklist_sha256.txt")

@dataclass
class AppConfig:
    sample_interval_ms: int = 1000
    connections_max_rows: int = 200
    processes_max_rows: int = 50

    # Integrity
    integrity_rehash_on_metadata_change: bool = True
    integrity_periodic_rehash_minutes: int = 0   # 0 = disabled
    integrity_hash_chunk_mb: int = 1

    # Detection – existing
    cpu_spike_threshold_pct: float = 85.0
    cpu_spike_sustain_seconds: int = 15
    new_network_process_alert: bool = True
    new_remote_for_process_alert: bool = True

    # Detection – Sprint A
    suspicious_parent_alert: bool = True          # parentage rules
    blacklist_path: str = ""                      # "" → uses DEFAULT_BLACKLIST if it exists
    persistence_watch_enabled: bool = True        # Run keys / Startup / Tasks

def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)

def load_config() -> AppConfig:
    ensure_dirs()
    if not CFG_PATH.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    try:
        data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
        known = {k: data[k] for k in data if k in AppConfig.__dataclass_fields__}
        return AppConfig(**known)
    except Exception:
        cfg = AppConfig()
        save_config(cfg)
        return cfg

def save_config(cfg: AppConfig) -> None:
    ensure_dirs()
    CFG_PATH.write_text(json.dumps(cfg.__dict__, indent=2), encoding="utf-8")
