# META REELS SCHEDULER — Enterprise Desktop Automation Center

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![Tests 30/30 Passed](https://img.shields.io/badge/tests-30%2F30%20green-brightgreen.svg)](test_suite.py)
[![Architecture Standalone](https://img.shields.io/badge/architecture-zero--dependency%20standalone-purple.svg)](meta_reels_scheduler.py)

**Meta Reels Scheduler** is a consolidated, enterprise-grade desktop automation platform, native Windows Task Scheduler engine, and autonomous publisher for Facebook & Meta Business Suite Reels across multiple brands and destination pages.

Operating natively on Windows with Chrome Profile orchestration, Computer Vision (OpenCV), and low-level Win32 input shielding, it enables 24/7 autonomous scheduling and high-frequency publishing without cloud dependencies or subscription APIs.

---

## 🌟 Key Capabilities

### 1. 🏢 Multi-Brand Workspace Architecture
* Manage multiple business brands (e.g. *Loan & Finance*, *Patpedhi*, *Automotive*) independently.
* Per-brand Chrome profile targeting, destination Facebook pages, custom media folders, captions, and scheduling rules.
* Three-tier configuration inheritance: **Page Override ➔ Brand Settings ➔ Global Defaults**.

### 2. 🎲 Dynamic Random Media & Caption Folder Pairing
* Assign a media folder with multiple `.mp4` videos and matching `.txt` caption files (e.g., `loan (1).mp4` automatically paired with `loan (1).txt`).
* Dynamically draws a random video and its corresponding caption on each scheduled run with anti-repeat memory.
* Seamless static file fallback if no media folder is assigned.

### 3. 🛡️ Anti-Spam Safety Capping & Multi-Daily Schedules
* Configure multiple daily schedules (e.g., `12:05 AM`, `01:10 AM`, `03:15 AM`, `04:15 AM`, `05:20 AM`) that execute sequentially across all brands.
* **Smart Daily Rate Limiting**: Capping threshold (default: `7` reels/day per page; `0` = unlimited) prevents Meta Business Suite spam flagging while allowing multiple automated daily runs.
* Real-time destination table badging: `⏳ PENDING (0/7)`, `✅ PUBLISHED (1/7)`, `🛑 CAPPED (7/7)`.

### 4. 🔒 Zero-RAM Automation Shield (Physical Input Lock)
* Automatically blocks physical keyboard and mouse input during reel publishing via low-level Windows hooks (`WH_KEYBOARD_LL`, `WH_MOUSE_LL`).
* Prevents accidental clicks, window focus loss, or interruptions while automation is executing.
* **Instant Auto-Release**: Frees input immediately upon batch completion or timeout.
* **Emergency Override**: Press `Esc` or `Ctrl+Alt+Del` anytime to immediately release the shield.

### 5. ⏰ Native Windows Task Scheduler (`schtasks.exe`)
* Direct two-way sync with the Windows Task Scheduler service.
* Supports exact trigger times and recurring minute intervals (e.g. repeat every 15m, 30m, 45m, 60m for 2h–24h).
* Operates headlessly in the background even if the desktop GUI is completely closed.

### 6. 🧠 Computer Vision & Autonomous Self-Healing Engine
* Real-time visual element detection powered by OpenCV template matching and PIL image variance analysis.
* Automatically identifies composer state changes (Upload Complete, Edit Step, Share Step, Done Modal).
* Self-healing remediation agent learns target coordinates and records heuristics in SQLite WAL memory (`logs/learning_memory.db`).

### 7. 🔌 FastAPI REST API & Command-Line Interface (CLI Node)
* Embedded FastAPI server running on `http://127.0.0.1:8765` for external orchestrations, webhooks, or companion tools.
* Comprehensive CLI commands for headless scheduling, emergency unlocking, and status inspection.

---

## 🖥️ Desktop Control Center GUI

The native Tkinter GUI features a modern, clean fintech aesthetic with zero horizontal scroll enforcement:

* **Tab 1: 🕒 Schedules & Destinations**: Unified brand switcher, destination table with live badges, manual batch trigger, Windows task synchronization, and profile selectors.
* **Tab 2: ✍️ Video Media & Caption Editor**: Brand content folder picker, random pair test drawer, fallback video selector, and caption character counter.
* **Tab 3: 🛠️ Chrome Extension & Diagnostics**: Profile manager, self-healing heuristic tables, and step-by-step debug actions.
* **Tab 4: ⚙️ Global Configuration**: Daily publication limit spinbox (0–50), Automation Shield toggle, and queue pacing parameters.

---

## 🚀 Quick Start

### Prerequisites
* Windows 10 or 11
* Python 3.10+
* Google Chrome (with desired signed-in profile, e.g. Profile 15)

### Installation
```powershell
# Clone repository
git clone https://github.com/balajifinancemachine-lab/META-REELS-SCHEDULER.git
cd META-REELS-SCHEDULER

# Install dependencies
pip install -r requirements_meta_reels.txt
```

### Running the Application

#### 1. Launch Native Desktop Control Center:
```powershell
python meta_reels_scheduler.py
```

#### 2. Check System Status via CLI Node:
```powershell
python meta_reels_scheduler.py --status
```

#### 3. Set Daily Publication Safety Cap:
```powershell
python meta_reels_scheduler.py --set-max-uploads 7
```

#### 4. Trigger Autonomous Scheduled Batch:
```powershell
python meta_reels_scheduler.py --scheduled-batch --schedule-id sched_0005
```

#### 5. Emergency Physical Input Release:
```powershell
python meta_reels_scheduler.py --unlock-input
```

---

## 🧪 Verification & Testing

The repository includes a comprehensive 30-stage automated audit suite and live REST API test runner:

```powershell
# Run full 30-stage audit test suite (100% offline, zero network dependencies)
python test_suite.py

# Run live FastAPI REST API verification suite
python test_live_api.py
```

### Test Coverage Highlights
* Dynamic local path isolation & asset discovery
* Manifest V3 Chrome Extension state-machine verification
* Win32DialogEngine native Windows message passing
* Computer Vision template matching & image variance analysis
* SQLite WAL persistent learning memory & self-healing episodes
* Windows Task Scheduler creation, execution, and deletion
* Multi-Brand CRUD, scoping, and task resolution
* Input Restriction Manager dual-layer hook blocking & safety timeouts
* Multi-Publish per day and anti-spam safety capping

---

## 📁 Repository Structure

```
META-REELS-SCHEDULER/
├── meta_reels_scheduler.py     # Unified primary application, GUI, API server & engine
├── config.json                 # Brand configurations, pages, and daily schedule matrix
├── state.json                  # Runtime publication tracking and daily counters
├── requirements_meta_reels.txt # Python package requirements
├── test_suite.py               # Comprehensive 30-stage automated verification suite
├── test_live_api.py            # Live REST API and endpoint integration tests
├── add_video_btn.png           # Visual CV template for composer video upload button
├── check_click_target.png      # Visual CV template for composer checkmark target
├── exact_button_in_page2.png   # Visual CV template for composer next button
├── ChromeExtension/            # Autonomous Meta Reels Chrome extension (Manifest V3)
│   ├── manifest.json
│   ├── content.js
│   └── background.js
├── loan/                       # Sample brand media assets and paired captions
│   ├── loan (1).mp4 ... (7).mp4
│   └── loan (1).txt ... (7).txt
└── README.md                   # Enterprise documentation
```

---

## 🔒 Security & Safe Operation

* **No Hardcoded Secrets**: Does not store or require Meta passwords or account API tokens; operates securely through your authenticated local Chrome browser profile.
* **Self-Contained Execution**: All heuristics and logs remain strictly on the local machine (`logs/` directory).
* **Emergency Input Safety**: Dual-layer input lock automatically releases on batch completion, timeouts (watchdog safety), or user emergency keys (`Esc` / `Ctrl+Alt+Del`).

---

## 📄 License

Proprietary enterprise automation framework developed for high-volume automated social publishing. All rights reserved.
