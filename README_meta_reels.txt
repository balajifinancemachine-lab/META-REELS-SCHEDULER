META REELS SCHEDULER - ENTERPRISE AUTOMATION & TASK SCHEDULER CONTROL CENTER
==================================================================================

This package provides a completely consolidated, standalone Python desktop control
center, Windows Task Scheduler engine, and autonomous publisher for Meta Reels across
all your Facebook/Meta pages using your signed-in Google Chrome Profile 15.

--------------------------------------------------------------------------------
1. ARCHITECTURE & KEY CAPABILITIES
--------------------------------------------------------------------------------
The entire application is unified and operates locally with zero external dependencies:
  • Primary Application:        ./meta_reels_scheduler.py
  • Automated Test Suite:       ./test_suite.py (18/18 Tests Green)
  • Master Configuration:       ./config.json
  • Daily Execution State:      ./state.json
  • Embedded Chrome Helper:     Auto-installed into Chrome Profile 15 & Windows Registry
  • Autonomous Reasoning:       Instant zero-RAM self-healing engine + OpenCV CV inspection
  • Persistent Learning DB:     ./logs/learning_memory.db (SQLite WAL mode)
  • Telemetry Research Logs:    ./logs/execution_research.jsonl
  • Console Logs:               ./logs/meta_reels.log

Key Capabilities:
  • Windows Task Scheduler Integration (schtasks.exe):
    - Schedules are automatically created as native Windows tasks.
    - Minute Repetition Intervals: Set any start time (e.g. 18:00 / 6:00 PM) and repeat
      every N minutes (e.g., 15m, 30m, 45m, 60m, or custom) for a set duration (2h - 24h).
    - Runs completely autonomously in the background even if the desktop GUI is closed.
  • Zero-Touch Chrome Extension Management:
    - Auto-unpacks, installs, and updates the Chrome extension in Profile 15.
    - Sets developer mode in Chrome Preferences and registers in Windows Registry.
  • Streamlined 3-Tab Desktop GUI (Fintech Dark Aesthetic, Zero Horizontal Scroll):
    - Tab 1: 🕒 Schedules & Destinations (Windows Task Sync, Multi-Schedule Manager, Pages)
    - Tab 2: ✍️ Video Media & Caption Editor (Hashtag chips, counter, step sequence)
    - Tab 3: 🛠️ Chrome Extension & Diagnostics (Auto-reinstall, CV inspector, heuristics)
  • Persistent Telemetry & Log Console:
    - Live execution stream with search filter, autoscroll, and log export.

--------------------------------------------------------------------------------
2. RUNNING THE APPLICATION
--------------------------------------------------------------------------------
Launch GUI Desktop Control Center:
  & .\.llm_env\Scripts\python.exe meta_reels_scheduler.py

Run Autonomous Scheduled Batch via CLI (used by Windows Task Scheduler):
  & .\.llm_env\Scripts\python.exe meta_reels_scheduler.py --scheduled-batch --schedule-id <ID>

Run Headless API-Only Daemon:
  & .\.llm_env\Scripts\python.exe meta_reels_scheduler.py --api-only

Run Complete Automated Test Suite:
  & .\.llm_env\Scripts\python.exe test_suite.py
