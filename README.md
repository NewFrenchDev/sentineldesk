# 🛡️ SentinelDesk — Local EDR for Windows

**Modern, user-friendly endpoint detection & response system for protecting your personal computer.**

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)
![PySide6](https://img.shields.io/badge/PySide6-6.0+-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows-blue.svg)

---

## 🎯 What It Does

SentinelDesk continuously monitors your Windows system for suspicious activity using **behavioral detection rules** that catch real-world attack patterns:

### Core Features

✅ **Process Monitoring** — Real-time tracking of all running processes (CPU, RAM, executables, users)  
✅ **Network Surveillance** — TCP connection monitoring with process attribution  
✅ **File Integrity** — SHA-256 hashing of executables with change detection  
✅ **Process Tree Visualization** — Parent→child relationships (who launched what)  
✅ **Persistence Monitoring** — Watches Registry Run keys, Startup folders, Scheduled Tasks  
✅ **Hash Blacklist** — Alert on known malware SHA-256 signatures  
✅ **Suspicious Parentage Detection** — Detects Office docs launching shells, exe from Temp, etc.  
✅ **Alerts & Timeline** — All events logged to SQLite with full forensic history  
✅ **Modern UI** — Dark cyber-security theme with glass-morphism, live graphs, sortable tables  

---

## 🚀 Quick Start

### Prerequisites

- **Windows 10/11** (64-bit)
- **Python 3.10+** ([download](https://www.python.org/downloads/))

### Installation

```bash
# 1. Clone or download this repository
git clone https://github.com/yourname/sentineldesk.git
cd sentineldesk

# 2. Install dependencies
pip install PySide6 psutil

# 3. Run
python -m sentineldesk
```

The app will create `~/.sentineldesk/` with:
- `sentineldesk.db` — SQLite database (alerts, timeline, baselines)
- `config.json` — User settings
- `blacklist_sha256.txt` — Hash blacklist (one SHA-256 per line)

---

## 📊 User Interface

### Dashboard Tab
- **Top Processes** table (sortable by Name, PID, CPU%, RAM)
- **Active Connections** table (sortable, with emoji process icons)
- **Metric Cards** showing CPU, Memory, Network (live animated graphs)

### Process Tree Tab
- **Hierarchical view** showing parent→child relationships
- **Suspicious nodes** highlighted in **red** (Office→shell, exe from Temp)
- Sortable columns: Process, PID, PPID, User, CPU%, RAM
- Click headers to sort by any column

### Alerts Tab
- All security events with severity badges (🔴 High, 🟠 Medium, 🟡 Low)
- **Approve & Trust Exe** button to whitelist legitimate files

### Persistence Tab
- Live view of Registry Run keys, Startup folder, Scheduled Tasks
- **New entries** automatically highlighted
- **Acknowledge Entry** button to mark as reviewed

### Timeline Tab
- Complete event log (metrics, process starts, alerts, integrity changes)
- Searchable and filterable

---

## 🔒 Security Features

### Detection Rules (Sprint A)

#### 1. **Suspicious Parentage**
Detects when dangerous processes are spawned by unexpected parents:

| Pattern | Severity | Why It Matters |
|---------|----------|----------------|
| `powershell.exe` launched by `WINWORD.EXE` | 🔴 High | #1 malware delivery method |
| `cmd.exe` launched by `EXCEL.EXE` | 🔴 High | Macro-based payload execution |
| `rundll32.exe` launched by non-system process | 🟠 Medium | DLL injection technique |
| Executable from `%TEMP%` or `%APPDATA%` | 🟠 Medium | Common malware staging location |

#### 2. **Hash Blacklist**
- Compares running processes against SHA-256 hash database
- Default blacklist: `~/.sentineldesk/blacklist_sha256.txt`
- **Update yours** with hashes from:
  - [VirusTotal](https://www.virustotal.com/)
  - [Malware Bazaar](https://bazaar.abuse.ch/)
  - [MITRE ATT&CK](https://attack.mitre.org/)

#### 3. **Persistence Monitoring**
Watches auto-start mechanisms for new entries:
- Registry: `HKCU/HKLM\Software\Microsoft\Windows\CurrentVersion\Run`
- Startup folders (user + All Users)
- Scheduled Tasks (filters out Microsoft system tasks)

#### 4. **File Integrity**
- SHA-256 hash computed for every running executable on first sight
- Alerts if executable is **modified while running** (rare but critical)

#### 5. **CPU Spike Detection**
- Sustained high CPU (>85% for 15+ seconds) triggers alert
- Helps catch cryptominers and runaway processes

---

## ⚙️ Configuration

Edit `~/.sentineldesk/config.json`:

```json
{
  "sample_interval_ms": 1000,               // How often to sample (milliseconds)
  "processes_max_rows": 50,                 // Top N processes to show
  "connections_max_rows": 200,              // Max connections to show
  
  "integrity_rehash_on_metadata_change": true,  // Re-hash if exe mtime changes
  "integrity_hash_chunk_mb": 1,             // SHA-256 chunk size
  
  "cpu_spike_threshold_pct": 85.0,          // CPU% to trigger spike alert
  "cpu_spike_sustain_seconds": 15,          // How long spike must sustain
  
  "suspicious_parent_alert": true,          // Enable parentage rules
  "blacklist_path": "",                     // Custom blacklist (blank = use default)
  "persistence_watch_enabled": true,        // Monitor Run keys / Startup / Tasks
  
  "new_network_process_alert": true,        // Alert on first network activity
  "new_remote_for_process_alert": true      // Alert on new remote endpoint
}
```

---

## 🎨 UI Features

### Sortable Tables
**All tables support sorting** — just click any column header:
- **Process tables**: Name (alphabetical), PID (numeric), CPU% (numeric), RAM (numeric)
- **Connection tables**: Process, PID, Local/Remote addresses, Status
- **Process tree**: Sortable hierarchy with parent→child arrows

### Color-Coded Data
- 🔴 **High CPU** (>85%) in red
- 🟠 **Medium CPU** (60-85%) in orange
- 🟢 **Network ESTABLISHED** in green
- 🟡 **SYN_SENT** in yellow
- **Suspicious processes** in the tree have red text + pink background tint

### Emoji Icons
80+ process icons for instant recognition:
- 🌐 Browsers (Chrome, Edge, Firefox)
- 🦊 Firefox
- 🎮 Steam
- 💬 Discord
- 🐍 Python
- ⚙️ System processes (svchost, explorer)
- 📁 File managers
- 🛡️ Security tools

---

## 🗂️ Database Schema

All data is stored in `~/.sentineldesk/sentineldesk.db` (SQLite):

### Tables
- `file_integrity` — SHA-256, size, mtime for all seen executables
- `process_seen` — Baseline of known processes (first/last seen timestamps)
- `process_remote_seen` — Baseline of (process, remote_ip:port) pairs
- `persistence_baseline` — Run keys, Startup items, Scheduled Tasks
- `timeline` — Every event (metrics, process spawns, alerts, integrity changes)
- `alerts` — All security alerts with severity, rule_id, exe_path, details

### Export
Currently manual via SQLite CLI:
```bash
sqlite3 ~/.sentineldesk/sentineldesk.db ".mode csv" ".once export.csv" "SELECT * FROM alerts;"
```

---

## 🛠️ Development Roadmap

### ✅ Sprint A (Implemented)
1. Process tree parent→child visualization
2. Suspicious parentage detection (Office→shell, exe from Temp)
3. Hash blacklist integration
4. Persistence monitoring (Run keys, Startup, Tasks)

### 🔜 Sprint B (Planned)
5. DNS monitoring (UDP 53) for C2 detection
6. Port-based anomaly detection
7. File system watcher (real-time monitoring of Temp/Downloads/AppData)
8. Privilege escalation detection (user→SYSTEM transition)

### 🔮 Sprint C (Future)
9. IP geolocation (private vs public detection)
10. Export/reporting (CSV, JSON, HTML daily reports)
11. Data retention & rotation
12. Database integrity signing

---

## 🧪 Testing Tips

To test detection rules without actual malware:

### 1. Test Suspicious Parentage
Open Word/Excel, then:
```vbnet
' In VBA editor (Alt+F11):
Sub TestShell()
    Shell "cmd.exe /c echo test > %TEMP%\test.txt", vbHide
End Sub
```
Run the macro → **SentinelDesk will alert** on `cmd.exe` spawned by Office.

### 2. Test Hash Blacklist
1. Compute SHA-256 of any benign exe (e.g., `certutil -hashfile C:\Windows\notepad.exe SHA256`)
2. Add that hash to `~/.sentineldesk/blacklist_sha256.txt`
3. Launch `notepad.exe` → **Blacklist alert fires**

### 3. Test Persistence Detection
1. Create a Registry Run key: `reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v TestEntry /t REG_SZ /d "C:\test.exe"`
2. SentinelDesk detects it within 1 second → **Persistence alert**

---

## 📝 Known Limitations

- **Windows only** (Linux/Mac support planned via systemd/cron/LaunchAgents)
- **No DNS monitoring yet** (only TCP, not UDP)
- **No file system watcher** (only checks running executables)
- **schtasks may require admin** to read all scheduled tasks
- **No YARA rules** (currently pattern-based, not signature-based)

---

## 🤝 Contributing

Feature requests and PRs welcome! Key areas:

1. **New detection rules** (add to `detectors.py`)
2. **Port scanning detection**
3. **DNS query monitoring**
4. **File system watcher** (`watchdog` library)
5. **Export features** (CSV/JSON/HTML reports)
6. **Linux/Mac support** (systemd, cron, LaunchAgents)

---

## 📜 License

MIT License — see `LICENSE` file.

---

## 🙏 Acknowledgments

Built with:
- [PySide6](https://doc.qt.io/qtforpython/) — UI framework
- [psutil](https://github.com/giampaolo/psutil) — Cross-platform system monitoring
- [SQLite](https://www.sqlite.org/) — Embedded database

Inspired by commercial EDR systems but designed for personal use with **zero telemetry** and **100% local processing**.

---

**Stay vigilant. Stay protected. 🛡️**
