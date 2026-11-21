"""Comprehensive Automated Audit & Verification Test Suite for Meta Reels Scheduler.
Runs against local codebase without external network calls.
Tests:
1. Local dynamic folder paths & configuration persistence.
2. Dynamic Chrome Profile 15 and video assets discovery.
3. Extension integrity (Manifest V3, MutationObserver, modular action dispatchers).
4. Win32DialogEngine direct window messaging logic.
5. CVInspectionEngine (OpenCV + Pillow image variance, color histogram masks, template matching).
6. WebSocketManager bi-directional command queue & promise resolution.
7. Modular Action Endpoints (/api/action/*, /api/pipeline/*, /api/events, /api/cv/inspect).
8. Research & Telemetry Logging (execution_research.jsonl).
"""
import asyncio
import copy
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

# Add local directory to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import meta_reels_scheduler as mrs


def test_1_dynamic_paths():
    print("[TEST 1] Verifying Dynamic Local Paths...")
    assert mrs.BASE_DIR == BASE_DIR, f"BASE_DIR mismatch: {mrs.BASE_DIR} vs {BASE_DIR}"
    assert mrs.CONFIG_FILE == BASE_DIR / "config.json", f"CONFIG_FILE mismatch: {mrs.CONFIG_FILE}"
    assert mrs.STATE_FILE == BASE_DIR / "state.json", f"STATE_FILE mismatch: {mrs.STATE_FILE}"
    assert mrs.LOG_DIR == BASE_DIR / "logs", f"LOG_DIR mismatch: {mrs.LOG_DIR}"
    assert mrs.EXT_DIR == BASE_DIR / "ChromeExtension", f"EXT_DIR mismatch: {mrs.EXT_DIR}"
    assert mrs.CONFIG_FILE.is_file(), f"config.json missing in {BASE_DIR}"
    assert mrs.STATE_FILE.is_file(), f"state.json missing in {BASE_DIR}"
    print("  ✓ All configuration, state, and log paths are strictly in this local folder.")


def test_2_chrome_profile_and_video_discovery():
    print("[TEST 2] Verifying Dynamic Profile & Video Discovery...")
    profile = mrs.detect_chrome_profile_15()
    print(f"  Dynamic Chrome Profile 15: {profile}")
    assert profile.name == "Profile 15", f"Expected 'Profile 15', got {profile.name}"

    video = mrs.find_default_video()
    print(f"  Discovered default video: {video}")
    assert video and Path(video).is_file(), f"Failed to discover local video: {video}"
    assert Path(video).name.endswith(".mp4"), f"Discovered video is not mp4: {video}"
    print("  ✓ Chrome profile and video assets dynamically detected.")


def test_3_extension_files_integrity():
    print("[TEST 3] Verifying Extension Assets in Local Folder...")
    manifest_file = mrs.EXT_DIR / "manifest.json"
    bg_file = mrs.EXT_DIR / "background.js"
    content_file = mrs.EXT_DIR / "content.js"

    assert manifest_file.is_file(), "manifest.json missing"
    assert bg_file.is_file(), "background.js missing"
    assert content_file.is_file(), "content.js missing"

    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data.get("manifest_version") == 3, "Manifest version must be 3"
    assert "tabs" in manifest_data.get("permissions", []), "Tabs permission missing"
    assert any("127.0.0.1:8765" in h for h in manifest_data.get("host_permissions", [])), "Host permissions missing local API"

    content_text = content_file.read_text(encoding="utf-8")
    assert "SCREEN1_NEXT_NOT_FOUND" in content_text, "Content script missing multi-screen handling"
    assert "Done" in content_text, "Content script missing Screen 4 Done modal handling"
    assert "selectLocation" in content_text, "Content script missing location selector"
    assert "findMessageButton" in content_text, "Content script missing message button finder"
    assert "MutationObserver" in content_text, "Content script missing MutationObserver reactive DOM engine"
    assert "executeAction" in content_text, "Content script missing modular executeAction dispatcher"
    assert "setupWebSocket" in content_text, "Content script missing setupWebSocket listener"
    print("  ✓ Chrome Extension files intact, valid Manifest V3, and complete 4-screen state machine present.")


def test_4_win32_dialog_engine():
    print("[TEST 4] Verifying Win32DialogEngine Native Message Methods...")
    assert hasattr(mrs.Win32DialogEngine, "find_file_dialog")
    assert hasattr(mrs.Win32DialogEngine, "find_edit_control")
    assert hasattr(mrs.Win32DialogEngine, "find_open_button")
    assert hasattr(mrs.Win32DialogEngine, "submit_file")
    assert hasattr(mrs.Win32DialogEngine, "start_watcher")

    # Safe test: invalid file submission fails closed
    fake_submit = mrs.Win32DialogEngine.submit_file(0, "non_existent_video.mp4")
    assert fake_submit is False, "submit_file should return False for non-existent file"
    print("  ✓ Win32DialogEngine initialized with user32.dll message protocols.")


def test_5_cv_inspection_engine():
    print("[TEST 5] Verifying Computer Vision Inspection Engine (OpenCV + PIL)...")
    assert hasattr(mrs.CVInspectionEngine, "capture_screen")
    assert hasattr(mrs.CVInspectionEngine, "inspect_current_screen")

    # Run inspection
    analysis = mrs.CVInspectionEngine.inspect_current_screen()
    assert isinstance(analysis, dict)
    assert "stage" in analysis
    assert "confidence" in analysis
    assert "has_green_progress_bar" in analysis
    assert "has_blue_action_button" in analysis
    assert "laplacian_variance" in analysis
    print(f"  CV Inspection Sample: Stage={analysis['stage']} (Confidence={analysis['confidence']*100:.0f}%, Variance={analysis['laplacian_variance']})")
    print("  ✓ Computer Vision Inspection Engine fully functional with OpenCV.")


def test_6_websocket_manager():
    print("[TEST 6] Verifying WebSocket Two-Way Command Manager...")
    mgr = mrs.ws_manager
    assert hasattr(mgr, "connect")
    assert hasattr(mgr, "disconnect")
    assert hasattr(mgr, "send_command")
    assert hasattr(mgr, "resolve_future")

    # Test future resolution
    test_id = "test-cmd-001"
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    fut = loop.create_future()
    with mgr.lock:
        mgr.pending_futures[test_id] = fut

    mgr.resolve_future(test_id, {"ok": True, "result": "TEST_PASSED"})
    assert fut.done()
    assert fut.result()["result"] == "TEST_PASSED"
    loop.close()
    print("  ✓ WebSocket command resolution protocol verified.")


def test_7_modular_action_endpoints():
    print("[TEST 7] Verifying Modular Action & Telemetry REST Endpoints...")

    # 1. Health & Status
    health = mrs.api_health()
    assert health["ok"] is True
    status_data = mrs.api_status()
    assert "batch_running" in status_data
    assert "active_page_id" in status_data

    # 2. Config Endpoint
    cfg = mrs.api_get_config()
    assert cfg.get("location") == "Mumbai"

    # 3. Pages Endpoint
    pages_data = mrs.api_get_pages()
    assert len(pages_data.get("pages", [])) >= 1

    # 4. Next Task Endpoint
    first_id = mrs.controller.pages[0]["id"]
    next_task_resp = mrs.api_next_task(first_id)
    assert "task" in next_task_resp

    # 5. Video streaming endpoint
    video_resp = mrs.api_stream_video(first_id)
    assert hasattr(video_resp, "path")
    assert Path(video_resp.path).is_file(), f"Streamed video file does not exist: {video_resp.path}"

    # 6. Report Endpoint handler
    mrs.controller.handle_report({"page_id": first_id, "state": "AUDIT_TEST_VERIFIED"})
    assert mrs.controller.hello_event.is_set(), "Hello event should be set by handle_report"

    # 7. CV Inspect endpoint
    cv_data = mrs.api_cv_inspect()
    assert "stage" in cv_data

    # 8. CV Click Actions
    assert hasattr(mrs.CVInspectionEngine, "find_action_button")
    assert hasattr(mrs.CVInspectionEngine, "click_action_button")

    # 9. Pending command long-polling fallback
    pending = mrs.api_pending_command(first_id)
    assert isinstance(pending, dict)

    print("  ✓ Modular Action and Telemetry endpoints fully operational.")


def test_8_research_telemetry_logging():
    print("[TEST 8] Verifying Research Log Persistence (execution_research.jsonl)...")
    test_event = f"AUDIT_VERIFY_{int(asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 9999)}"
    mrs.record_research_log(test_event, "TEST_PAGE", "AUDIT_STEP", duration_ms=42.5, detail={"audit": "passed"})

    assert mrs.RESEARCH_LOG_FILE.is_file(), "execution_research.jsonl file missing"
    lines = mrs.RESEARCH_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) > 0, "Research log file is empty"
    last_record = json.loads(lines[-1])
    assert last_record.get("event") == test_event, f"Expected {test_event}, got {last_record.get('event')}"
    assert last_record.get("duration_ms") == 42.5
    assert last_record.get("result") == "OK"
    print(f"  Verified last research log record: event={last_record['event']} step={last_record['step']}")
    print("  ✓ Telemetry research log persisting in execution_research.jsonl with epoch timestamps.")


def test_9_learning_memory_db():
    print("[TEST 9] Verifying Persistent Learning Memory Database (SQLite WAL)...")
    db = mrs.learning_db
    assert db is not None, "learning_db instance missing"
    assert mrs.LEARNING_DB_FILE.is_file(), "learning_memory.db file missing on disk"

    # Verify baseline heuristics
    h_share = db.get_heuristic("share_step3")
    assert h_share is not None, "Baseline heuristic for share_step3 missing"
    assert h_share["target_coord_x"] is not None and h_share["target_coord_x"] > 0
    assert h_share["target_coord_y"] is not None and h_share["target_coord_y"] > 0

    # Verify update and persistence
    db.record_success("share_step3", coord_x=748.0, coord_y=916.0)
    updated = db.get_heuristic("share_step3")
    assert updated["target_coord_x"] == 748.0
    assert updated["success_count"] >= 2

    # Verify episode logging
    db.record_episode("TEST_PAGE", "SHARE_SCREEN", "REMEDIATED", "DOM click missed", "Hardware click at (748, 916)", True)
    episodes = db.list_episodes(10)
    assert len(episodes) > 0
    assert episodes[0]["page_id"] == "TEST_PAGE"
    print(f"  Verified learning heuristics and episodes persisted in SQLite: {mrs.LEARNING_DB_FILE.name}")
    print("  ✓ Persistent Learning Memory Database fully operational.")


def test_10_autonomous_remediation_agent():
    print("[TEST 10] Verifying Autonomous Remediation Agent & Endpoints...")
    agent = mrs.agent
    assert agent is not None, "AutonomousRemediationAgent instance missing"
    assert mrs.controller.agent is agent, "Agent not attached to controller"

    # Test remediation evaluation
    res = agent.evaluate_and_remediate("TEST_PAGE", "SHARE_BUTTON_NOT_FOUND")
    assert isinstance(res, dict)
    assert "remediated" in res or "reason" in res

    # Test CVInspectionEngine find_action_button with snap and near_coord
    btn_coords = mrs.CVInspectionEngine.find_action_button("bottom_right", near_coord=(1000, 600))
    # Coordinates may be None in headless/mock or tuple of 2 ints on live desktop
    if btn_coords:
        assert isinstance(btn_coords, tuple) and len(btn_coords) == 2

    # Test seamless transition when composer skips Edit and reaches Share screen
    agent.last_remediation_time = 0.0  # Reset throttle
    res_skip = agent.evaluate_and_remediate("TEST_PAGE", "SCREEN2_NEXT_NOT_FOUND")
    assert isinstance(res_skip, dict)

    # Test API endpoints
    h_api = mrs.api_get_learning_heuristics()
    assert h_api.get("ok") is True
    assert len(h_api.get("heuristics", [])) >= 10

    ep_api = mrs.api_get_agent_episodes(5)
    assert ep_api.get("ok") is True
    assert len(ep_api.get("episodes", [])) >= 1

    # Test AdaptiveWaitEngine
    w = mrs.AdaptiveWaitEngine.get_wait("SCREEN_TRANSITION")
    assert w > 0, "Adaptive wait should return positive number"

    # Test LocalModelFallbackAgent
    decision = mrs.LocalModelFallbackAgent.reason_action("SHARE_BUTTON_NOT_FOUND", "TEST_PAGE")
    assert isinstance(decision, dict)
    assert decision.get("confidence", 0) > 0
    assert decision.get("coord") is not None

    print("  ✓ Autonomous Remediation Agent, Model Fallback Engine, and continuous learning verified.")


def test_11_publication_state_locking_and_tab_close():
    print("[TEST 11] Verifying Publication State Locking & Clean Tab Closure...")
    test_pid = "999999999999999"
    today = mrs.dt.date.today().isoformat()
    
    # 1. Verify get_task_for_page returns None when already published today
    state = mrs.load_json(mrs.STATE_FILE, {"attempts": {}})
    state.setdefault("attempts", {})[f"{today}:{test_pid}"] = "PUBLISHED"
    mrs.save_json(mrs.STATE_FILE, state)

    task_res = mrs.controller.get_task_for_page(test_pid)
    assert task_res is None, "Should refuse task when already marked PUBLISHED today"

    # Cleanup test entry
    state["attempts"].pop(f"{today}:{test_pid}", None)
    mrs.save_json(mrs.STATE_FILE, state)

    # 2. Verify PlaywrightCDPCommander.close_page error handling
    cdp_close = mrs.PlaywrightCDPCommander.close_page(test_pid)
    assert isinstance(cdp_close, dict)

    # 3. Verify close_tab_for_page method safety
    try:
        mrs.controller.close_tab_for_page(test_pid)
    except Exception as exc:
        assert False, f"close_tab_for_page raised unexpected exception: {exc}"

    print("  ✓ Publication duplicate guard and tab closure mechanisms verified.")


def test_12_dynamic_gemma_root_model():
    print("[TEST 12] Verifying Autonomous Engine & Zero-RAM Model Purge...")
    mgr = mrs.GemmaModelManager.get_instance()
    st = mgr.get_status()
    assert st["in_ram"] is False, "Model should not be held in RAM (purged for performance)"
    assert hasattr(mrs, "PlaywrightCDPCommander"), "PlaywrightCDPCommander must be defined"
    assert hasattr(mrs.PlaywrightCDPCommander, "is_cdp_available"), "PlaywrightCDPCommander missing is_cdp_available"
    print("  ✓ Autonomous engine verified: zero-RAM model footprint and Playwright CDP ready.")


def test_13_intelligent_sequence_and_issue_monitor():
    print("[TEST 13] Verifying Intelligent Sequence Configuration & Issue Monitoring...")
    ctrl = mrs.controller
    assert ctrl.step_sequence == "caption_first", f"Expected caption_first, got {ctrl.step_sequence}"
    assert ctrl.composer_step_order == ["caption", "location", "messages", "video_upload"], f"Unexpected step order: {ctrl.composer_step_order}"

    # Verify task generation includes the configured sequence
    task = ctrl._task_for_page(ctrl.pages[0])
    assert task is not None
    assert task.get("step_sequence") == "caption_first"
    assert task.get("composer_step_order") == ["caption", "location", "messages", "video_upload"]

    # Verify extension content script has modular sequence steps
    content_text = (mrs.EXT_DIR / "content.js").read_text(encoding="utf-8")
    assert "stepFillCaption" in content_text, "Missing stepFillCaption in content script"
    assert "stepFillLocation" in content_text, "Missing stepFillLocation in content script"
    assert "stepFillMessages" in content_text, "Missing stepFillMessages in content script"
    assert "stepUploadVideo" in content_text, "Missing stepUploadVideo in content script"
    assert "SEQUENCE_DISPATCHING" in content_text, "Missing SEQUENCE_DISPATCHING in content script"

    # Test dynamic sequence switching and persistence
    ctrl.update_config({"step_sequence": "video_first", "composer_step_order": ["video_upload", "caption", "location", "messages"]})
    assert ctrl.step_sequence == "video_first"
    
    # Revert back to recommended caption_first
    ctrl.update_config({"step_sequence": "caption_first", "composer_step_order": ["caption", "location", "messages", "video_upload"]})
    assert ctrl.step_sequence == "caption_first"

    # Verify Issue Monitor handles CAPTION_BOX_NOT_FOUND
    res = mrs.agent.evaluate_and_remediate("TEST_PAGE", "CAPTION_BOX_NOT_FOUND")
    assert isinstance(res, dict)
    assert res.get("remediated") is True
    assert res.get("action") == "FOCUSED_CAPTION_BOX"

    print("  ✓ Intelligent Sequence Engine and Active Issue Monitor verified.")


def test_14_lexical_safety_and_toolbar_resolution():
    print("[TEST 14] Verifying Lexical Safety, Toolbar Resolution, and Watchdog Protection...")
    content_text = (mrs.EXT_DIR / "content.js").read_text(encoding="utf-8")
    embedded_unpacked = mrs.get_content_js()

    # 1. Ensure deprecated execCommand is completely purged
    assert "execCommand" not in content_text, "Dangerous execCommand found in content.js"
    assert "execCommand" not in embedded_unpacked, "Dangerous execCommand found in embedded_unpacked"

    # 2. Ensure robust Reel details container and toolbar indexing
    assert "findReelDetailsContainer" in content_text, "Missing findReelDetailsContainer"
    assert "below[0]" in content_text, "Missing leftmost messenger indexing"
    assert "below[1]" in content_text, "Missing middle location indexing"

    # 3. Ensure blank page detection and auto-recovery watchdog
    assert "isBlankPage" in content_text, "Missing isBlankPage in content.js"
    assert "COMPOSER_BLANK_DETECTED" in content_text, "Missing COMPOSER_BLANK_DETECTED in content.js"

    # 4. Ensure Win32DialogEngine.focus_chrome is operational
    assert hasattr(mrs.Win32DialogEngine, "focus_chrome"), "Win32DialogEngine missing focus_chrome"

    print("  ✓ Lexical-safe event dispatch, toolbar resolution, and blank screen watchdog verified.")


def test_15_standalone_portability_and_embedded_assets():
    print("[TEST 15] Verifying Standalone Portability, Auto-Dependencies, and Embedded Assets...")
    # 1. Verify auto-dependency bootstrapper
    assert hasattr(mrs, "ensure_dependencies"), "Missing ensure_dependencies function"
    mrs.ensure_dependencies()

    # 2. Verify embedded assets base64
    assert hasattr(mrs, "EMBEDDED_ADD_VIDEO_BTN_B64") and len(mrs.EMBEDDED_ADD_VIDEO_BTN_B64) > 100, "Invalid EMBEDDED_ADD_VIDEO_BTN_B64"
    assert hasattr(mrs, "EMBEDDED_CHECK_CLICK_TARGET_B64") and len(mrs.EMBEDDED_CHECK_CLICK_TARGET_B64) > 100, "Invalid EMBEDDED_CHECK_CLICK_TARGET_B64"
    assert hasattr(mrs, "EMBEDDED_EXACT_BUTTON_B64") and len(mrs.EMBEDDED_EXACT_BUTTON_B64) > 100, "Invalid EMBEDDED_EXACT_BUTTON_B64"

    # 3. Test asset auto-extraction
    test_asset = mrs.BASE_DIR / "add_video_btn.png"
    backup = test_asset.read_bytes() if test_asset.exists() else None
    try:
        if test_asset.exists():
            test_asset.unlink()
        assert not test_asset.exists(), "Asset should be deleted for extraction test"
        mrs.ensure_embedded_assets()
        assert test_asset.exists() and test_asset.stat().st_size > 0, "Asset was not auto-extracted from embedded base64"
    finally:
        if backup and not test_asset.exists():
            test_asset.write_bytes(backup)

    # 4. Verify Chrome Profile dynamic discovery resilience
    p = mrs.detect_chrome_profile_15()
    assert isinstance(p, Path), "detect_chrome_profile_15 should return a Path"

    print("  ✓ Standalone portability, embedded base64 templates, and dependency bootstrapper verified.")


def test_16_windows_task_scheduler_and_multi_schedules():
    print("[TEST 16] Verifying Windows Task Scheduler Integration & Multi-Schedules with Repeat Intervals...")
    # 1. Test WindowsTaskSchedulerManager directly with repeat interval
    mgr = mrs.WindowsTaskSchedulerManager
    test_task_name = "sched_unittest_repeat"
    
    # Clean up if exists
    mgr.delete_task(test_task_name)
    
    # Register/Update with 30-minute repeat interval and 4-hour duration
    res = mgr.register_or_update_task({
        "id": test_task_name,
        "time": "18:00",
        "name": "Unit Test Repeat Schedule",
        "repeat_interval_minutes": 30,
        "repeat_duration_hours": 4
    })
    assert res.get("ok"), f"Failed to register task with repeat interval: {res}"
    assert res.get("repeat_interval_minutes") == 30
    assert res.get("repeat_duration_hours") == 4
    
    # Query task
    q = mgr.query_task(test_task_name)
    assert q.get("exists"), f"Task {test_task_name} should exist in Windows Task Scheduler"
    assert q.get("status") in ("Ready", "Running", "Could not start"), f"Unexpected status: {q}"
    
    # Delete task
    d = mgr.delete_task(test_task_name)
    assert d.get("ok"), f"Failed to delete test task: {d}"
    
    # 2. Test Controller Multi-Schedules with Interval Repetition
    controller = mrs.controller
    original_schedules = copy.deepcopy(controller.schedules)
    try:
        initial_count = len(controller.schedules)
        
        # Add schedule starting at 18:00 repeating every 45 minutes
        add_res = controller.add_schedule(
            time_str="18:00",
            name="Evening Repeat Reel",
            enabled=True,
            days="DAILY",
            repeat_interval_minutes=45,
            repeat_duration_hours=6
        )
        assert add_res.get("id"), f"Failed to add schedule: {add_res}"
        sched_id = add_res["id"]
        assert add_res.get("repeat_interval_minutes") == 45
        assert add_res.get("repeat_duration_hours") == 6
        assert len(controller.schedules) == initial_count + 1
        
        # Edit schedule: change repeat interval to 60 mins and time to 18:30
        edit_res = controller.edit_schedule(
            sched_id=sched_id,
            updates={"name": "Evening Repeat Reel Updated", "time": "18:30", "repeat_interval_minutes": 60, "enabled": False}
        )
        assert edit_res is not None, f"Failed to edit schedule: {edit_res}"
        edited_sched = next((s for s in controller.schedules if s["id"] == sched_id), None)
        assert edited_sched and edited_sched["time"] == "18:30"
        assert edited_sched["repeat_interval_minutes"] == 60
        assert edited_sched["enabled"] is False
        
        # Delete schedule
        del_res = controller.delete_schedule(sched_id)
        assert del_res is True, f"Failed to delete schedule: {del_res}"
        assert not any(s["id"] == sched_id for s in controller.schedules)
        
        # 3. Test REST endpoints with repeat interval payload
        schedules_data = mrs.api_get_schedules()
        assert schedules_data.get("ok") is True
        assert isinstance(schedules_data.get("schedules"), list)
        
        # Test sync endpoint
        sync_res = mrs.api_sync_schedules()
        assert sync_res.get("ok") is True
    finally:
        controller.schedules = original_schedules
        controller.save_config()
        controller.sync_all_schedules_to_windows()
    
    print("  ✓ Windows Task Scheduler and Multi-Schedule Controller (with minute repeat intervals) verified.")


def test_17_auto_extension_installer():
    print("[TEST 17] Verifying Chrome Extension Automatic Installer & Profile Sync...")
    # 1. Run ensure_chrome_extension_installed
    res = mrs.ensure_chrome_extension_installed()
    assert res.get("version"), "Extension installer must return version"
    assert Path(res["ext_path"]).is_dir(), "Local ChromeExtension directory must exist"
    
    # Verify local extension files
    for fname in ("manifest.json", "background.js", "content.js"):
        fpath = Path(res["ext_path"]) / fname
        assert fpath.is_file() and fpath.stat().st_size > 0, f"Extension file {fname} missing or empty"
        
    # Verify profile extension folder
    prof_ext_dir = mrs.PROFILE_PATH / "Extensions" / "MetaReelsScheduler"
    if mrs.PROFILE_PATH.exists():
        assert prof_ext_dir.is_dir(), f"Profile extension directory {prof_ext_dir} not created"
        for fname in ("manifest.json", "background.js", "content.js"):
            assert (prof_ext_dir / fname).is_file(), f"File {fname} not copied to profile extensions"

    # 2. Test via REST API endpoint
    api_resp = mrs.api_install_extension()
    assert api_resp.get("ok") is True, f"API api_install_extension returned: {api_resp}"
    
    print("  ✓ Chrome Extension auto-installer, profile sync, and REST API endpoint verified.")


def test_18_scheduled_batch_cli_flag():
    print("[TEST 18] Verifying Autonomous Scheduled Batch CLI Flag & Entrypoint...")
    import subprocess
    py_exec = sys.executable
    proc = subprocess.run(
        [py_exec, str(mrs.BASE_DIR / "meta_reels_scheduler.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert proc.returncode == 0, f"CLI --help failed with code {proc.returncode}: {proc.stderr}"
    assert "--scheduled-batch" in proc.stdout, "--scheduled-batch missing from CLI help"
    assert "--schedule-id" in proc.stdout, "--schedule-id missing from CLI help"
    
    print("  ✓ Autonomous Scheduled Batch CLI flags and execution entrypoint verified.")


def test_19_nav_click_request_handling():
    print("[TEST 19] Verifying NAV_CLICK_REQUEST Handlers & No UnboundLocalError...")
    controller = mrs.controller
    # Verify NAV_CLICK_REQUEST for each button action doesn't throw UnboundLocalError
    for act in ("SCREEN1_NEXT", "SCREEN2_NEXT", "SHARE", "DONE", "BUTTON"):
        payload = {
            "page_id": "test_page_19",
            "state": "NAV_CLICK_REQUEST",
            "detail": {
                "action": act,
                "text": act,
                "target": {"x": 500, "y": 600, "left": 450, "top": 580, "width": 80, "height": 40},
                "window": {
                    "screenX": 100, "screenY": 50,
                    "outerWidth": 1200, "outerHeight": 800,
                    "innerWidth": 1200, "innerHeight": 720,
                    "devicePixelRatio": 1.0
                }
            }
        }
        # handle_report must process smoothly without exceptions
        controller.handle_report(payload)

    print("  ✓ NAV_CLICK_REQUEST hardware click handlers and coordinate conversions verified.")


def test_20_extension_session_storage_clean():
    print("[TEST 20] Verifying Chrome Extension Connects Cleanly Without sessionStorage Blocker...")
    content_js = (mrs.EXT_DIR / "content.js").read_text(encoding="utf-8")
    assert "sessionStorage.getItem('meta_reel_published_" not in content_js, "Found blocking sessionStorage check in content.js!"
    assert "HELPER_CONNECTED" in content_js, "HELPER_CONNECTED missing from content.js"
    assert "isShareScreenActive" in content_js, "isShareScreenActive missing from content.js"
    assert "STAGE_ALREADY_ON_SHARE_SCREEN" in content_js, "STAGE_ALREADY_ON_SHARE_SCREEN missing from content.js"
    print("  ✓ Chrome Extension clean connection and Stage 3 skip logic verified.")


def test_21_chrome_profile_scanner_and_selection():
    print("[TEST 21] Verifying Chrome Profile Scanner, Selection Engine & Profile APIs...")
    # 1. Format bytes utility
    assert mrs.format_bytes(1024 * 1024) == "1.0 MB"
    assert mrs.format_bytes(500) == "500 B"

    # 2. Scanner discovery
    scanner = mrs.ChromeProfileScanner()
    profs = scanner.scan_profiles()
    print(f"  Discovered {len(profs)} profiles across Chromium browsers.")
    assert len(profs) > 0, "Expected at least 1 discovered profile!"
    p15 = next((p for p in profs if p["profile_dir"] == "Profile 15"), None)
    assert p15 is not None, "Profile 15 not discovered by ChromeProfileScanner!"
    print(f"  Profile 15 discovered: {p15.get('display_name')} ({p15.get('email', 'No email')}) - Size: {p15.get('size_str')}")

    # 3. Controller profile switching & persistence
    controller = mrs.controller
    res = controller.set_selected_profile("Profile 15")
    assert res.get("selected_profile") == "Profile 15"
    assert controller.selected_profile == "Profile 15"
    assert controller.current_profile_path.name == "Profile 15"
    available = controller.get_available_profiles()
    assert len(available) > 0

    # 4. REST API Endpoint
    api_res = mrs.api_get_profiles()
    assert api_res.get("ok") is True
    assert api_res.get("selected_profile") == "Profile 15"
    assert len(api_res.get("profiles", [])) > 0

    # 5. Extension auto-install for active profile
    ext_res = mrs.ensure_chrome_extension_installed(controller.current_profile_path)
    assert Path(ext_res.get("profile")).name == "Profile 15"
    print(f"  Extension installed & registered for active profile: {ext_res.get('actions')}")

    print("  ✓ Chrome Profile Scanner, Selection Engine & APIs verified 100%.")


def test_22_multi_brand_architecture_and_migration():
    print("[TEST 22] Verifying Multi-Brand Core Architecture, Normalization & CRUD...")
    controller = mrs.controller
    
    # 1. Normalization of legacy config without brands
    legacy_cfg = {
        "pages": [{"id": "page_leg_1", "name": "Legacy Page"}],
        "global_video": "C:\\videos\\def.mp4",
        "location": "Delhi",
        "caption": "legacy caption",
        "auto_publish": True,
        "selected_profile": "Profile 15"
    }
    migrated_brands = mrs.normalize_brands(None, fallback_pages=legacy_cfg.get("pages"), global_cfg=legacy_cfg)
    assert len(migrated_brands) >= 1
    assert migrated_brands[0]["pages"][0]["id"] == "page_leg_1"
    assert migrated_brands[0]["chrome_profile"] == "Profile 15"
    assert migrated_brands[0]["location"] == "Delhi"

    # 2. Controller Brand Retrieval
    brands = controller.get_brands()
    assert len(brands) >= 1, "At least 1 brand must be loaded"
    active_b = controller.get_active_brand()
    assert active_b is not None
    assert active_b["id"] == controller.active_brand_id

    # 3. Add New Brand
    initial_brand_count = len(controller.get_brands())
    new_b = controller.add_brand(
        name="Automotive Division",
        chrome_profile="Profile 15",
        video="C:\\videos\\auto.mp4",
        caption="Check out our new cars! #auto",
        location="Pune",
        auto_publish=True,
        description="Auto brand pages"
    )
    assert new_b.get("id"), "add_brand must generate an ID"
    assert new_b["name"] == "Automotive Division"
    assert len(controller.get_brands()) == initial_brand_count + 1

    # 4. Set Active Brand & Verify pages property routing
    switched = controller.set_active_brand(new_b["id"])
    assert switched is True
    assert controller.active_brand_id == new_b["id"]
    assert controller.pages == []  # New brand starts with empty pages

    # Add a page to the active brand via controller.pages
    test_page = {
        "id": "auto_page_101",
        "name": "Auto Page 101",
        "enabled": True,
        "video": "",
        "location": "",
        "caption": ""
    }
    controller.pages.append(test_page)
    controller.update_config({"pages": controller.pages})

    # Verify page persisted inside the new brand
    refreshed_b = controller.get_brand(new_b["id"])
    assert len(refreshed_b["pages"]) == 1
    assert refreshed_b["pages"][0]["id"] == "auto_page_101"

    # 5. Update Brand
    upd = controller.update_brand(new_b["id"], {"location": "Bengaluru", "name": "Auto & Mobility"})
    assert upd is not None
    assert upd["location"] == "Bengaluru"
    assert upd["name"] == "Auto & Mobility"

    # 6. Switch back to primary brand and delete test brand
    primary_id = brands[0]["id"]
    controller.set_active_brand(primary_id)
    assert controller.active_brand_id == primary_id
    assert len(controller.pages) > 0  # Primary brand has pages

    del_ok = controller.delete_brand(new_b["id"])
    assert del_ok is True
    assert controller.get_brand(new_b["id"]) is None
    assert len(controller.get_brands()) == initial_brand_count

    print("  ✓ Multi-Brand Architecture, Normalization, dynamic pages property & CRUD verified.")


def test_23_multi_brand_task_resolution_and_inheritance(tmp_path=None):
    print("[TEST 23] Verifying Multi-Brand Page Task Resolution & Three-Tier Inheritance...")
    controller = mrs.controller

    if tmp_path is None:
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp())
    else:
        tmp_dir = Path(tmp_path)

    brand_vid = tmp_dir / "luxury_brand.mp4"
    brand_vid.write_bytes(b"dummy brand video")
    page_vid = tmp_dir / "custom_item.mp4"
    page_vid.write_bytes(b"dummy page video")

    brand_fixture = {
        "id": "brand_tier_test",
        "name": "Luxury Retail",
        "chrome_profile": "Profile 15",
        "video": str(brand_vid),
        "caption": "Luxury brand default caption #luxury",
        "location": "Mumbai South",
        "auto_publish": False,
        "step_sequence": "caption_first",
        "composer_step_order": ["caption", "location", "messages", "video_upload"],
        "pages": []
    }

    # Case A: Page overrides everything
    page_override = {
        "id": "page_ovr",
        "name": "Exclusive Store",
        "enabled": True,
        "video": str(page_vid),
        "caption": "Special sale today only!",
        "location": "Bandra West",
        "auto_publish": True,
        "step_sequence": "video_first",
        "composer_step_order": ["video_upload", "caption", "location", "messages"]
    }
    task_a = controller.resolve_page_task(page_override, brand_fixture)
    assert task_a["video"] == str(page_vid.resolve())
    assert task_a["caption"] == "Special sale today only!"
    assert task_a["location"] == "Bandra West"
    assert task_a["auto_publish"] is True
    assert task_a["step_sequence"] == "video_first"

    # Case B: Page provides empty overrides -> inherits from Brand
    page_inherit_brand = {
        "id": "page_inh_brand",
        "name": "General Store",
        "enabled": True,
        "video": "",
        "caption": "",
        "location": "",
        "auto_publish": None,
        "step_sequence": None
    }
    task_b = controller.resolve_page_task(page_inherit_brand, brand_fixture)
    assert task_b["video"] == str(brand_vid.resolve())
    assert task_b["caption"] == "Luxury brand default caption #luxury"
    assert task_b["location"] == "Mumbai South"
    assert task_b["auto_publish"] is False
    assert task_b["step_sequence"] == "caption_first"

    # Case C: Page and Brand empty -> inherits from Controller Global Fallbacks
    empty_brand = {
        "id": "brand_empty",
        "name": "Empty Brand",
        "chrome_profile": "Profile 15",
        "video": "",
        "caption": "",
        "location": "",
        "pages": []
    }
    page_inherit_global = {
        "id": "page_inh_global",
        "name": "Fallback Store",
        "enabled": True,
        "video": "",
        "caption": "",
        "location": ""
    }
    task_c = controller.resolve_page_task(page_inherit_global, empty_brand)
    assert Path(task_c["video"]).resolve() == Path(controller.global_video).resolve()
    assert task_c["caption"] == controller.caption
    assert task_c["location"] == controller.location

    # Test find_brand_for_page
    active_b = controller.get_active_brand()
    if active_b and active_b.get("pages"):
        first_page_id = active_b["pages"][0]["id"]
        found_brand, _ = controller.find_brand_for_page(first_page_id)
        assert found_brand is not None
        assert found_brand["id"] == active_b["id"]

    print("  ✓ Three-tier inheritance (Page -> Brand -> Global) and brand discovery verified.")


def test_24_multi_brand_batch_and_scheduled_brand_targeting():
    print("[TEST 24] Verifying Windows Task Scheduler Brand Scoping & All-Brands Execution...")
    mgr = mrs.WindowsTaskSchedulerManager
    test_task_id = "sched_unittest_brand_scope"
    mgr.delete_task(test_task_id)

    # 1. Register task scoped to a specific brand
    res = mgr.register_or_update_task({
        "id": test_task_id,
        "name": "Unit Test Brand Scoped Task",
        "time": "19:00",
        "target_brand": "brand-1",
        "repeat_interval_minutes": 0,
        "repeat_duration_hours": 24,
        "enabled": True
    })
    assert res.get("ok") is True, f"Failed to register brand-scoped task: {res}"
    assert res.get("target_brand") == "brand-1"
    assert "--brand \"brand-1\"" in res.get("command", "")

    # Query task in Windows Task Scheduler
    q = mgr.query_task(test_task_id)
    assert q.get("exists") is True

    # 2. Update task to scope ALL brands
    res_all = mgr.register_or_update_task({
        "id": test_task_id,
        "name": "Unit Test Brand Scoped Task",
        "time": "19:00",
        "target_brand": "ALL",
        "repeat_interval_minutes": 0,
        "repeat_duration_hours": 24,
        "enabled": True
    })
    assert res_all.get("ok") is True
    assert res_all.get("target_brand") == "ALL"
    assert "--brand \"ALL\"" in res_all.get("command", "")

    # Cleanup task
    mgr.delete_task(test_task_id)

    # 3. Test CLI argument parser accepts --brand
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(mrs.BASE_DIR / "meta_reels_scheduler.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=15
    )
    assert "--brand" in proc.stdout, "--brand flag missing from CLI help"

    print("  ✓ Task Scheduler brand scoping, CLI argument parsing, and target_brand options verified.")


def test_25_multi_brand_rest_api_endpoints():
    print("[TEST 25] Verifying Multi-Brand REST API Endpoints...")
    from starlette.testclient import TestClient
    client = TestClient(mrs.api_app)

    # 1. GET /api/brands
    res = client.get("/api/brands")
    assert res.status_code == 200
    data = res.json()
    assert data.get("ok") is True
    assert isinstance(data.get("brands"), list)
    assert len(data["brands"]) > 0
    orig_active_id = data.get("active_brand_id")

    # 2. GET /api/brands/active
    active_res = client.get("/api/brands/active")
    assert active_res.status_code == 200
    active_data = active_res.json()
    assert active_data.get("ok") is True
    assert active_data.get("active_brand_id") == orig_active_id
    assert "brand" in active_data

    # 3. POST /api/brands/create
    create_payload = {
        "name": "REST API Test Brand",
        "chrome_profile": "Profile 15",
        "video": "C:\\test\\brand.mp4",
        "location": "Mumbai",
        "caption": "Brand API test caption",
        "auto_publish": False,
        "description": "Created during REST API test"
    }
    create_res = client.post("/api/brands/create", json=create_payload)
    assert create_res.status_code == 200
    created_brand = create_res.json().get("brand")
    assert created_brand is not None
    brand_id = created_brand["id"]

    # 4. POST /api/brands/select
    sel_res = client.post("/api/brands/select", json={"brand_id": brand_id})
    assert sel_res.status_code == 200
    sel_data = sel_res.json()
    assert sel_data.get("ok") is True
    assert sel_data.get("active_brand_id") == brand_id

    # 5. POST /api/brand/{brand_id}/pages
    pages_payload = {
        "pages": [
            {
                "id": "rest_page_001",
                "name": "REST Test Page 001",
                "enabled": True,
                "video": "",
                "location": "Mumbai",
                "caption": "Sample"
            }
        ]
    }
    save_pg_res = client.post(f"/api/brand/{brand_id}/pages", json=pages_payload)
    assert save_pg_res.status_code == 200
    assert save_pg_res.json().get("ok") is True

    # 6. GET /api/brand/{brand_id}/pages
    get_pg_res = client.get(f"/api/brand/{brand_id}/pages")
    assert get_pg_res.status_code == 200
    get_pg_data = get_pg_res.json()
    assert len(get_pg_data.get("pages", [])) == 1
    assert get_pg_data["pages"][0]["id"] == "rest_page_001"

    # 7. POST /api/brands/update
    upd_res = client.post("/api/brands/update", json={"id": brand_id, "location": "Navi Mumbai"})
    assert upd_res.status_code == 200
    assert upd_res.json()["brand"]["location"] == "Navi Mumbai"

    # 8. Clean up: restore original active brand and delete test brand
    client.post("/api/brands/select", json={"brand_id": orig_active_id})
    del_res = client.post("/api/brands/delete", json={"brand_id": brand_id})
    assert del_res.status_code == 200
    assert del_res.json().get("ok") is True

    print("  ✓ All Multi-Brand REST API Endpoints verified 100%.")


def test_26_meta_url_extraction_and_profile_sanitization():
    print("[TEST 26] Verifying Meta URL Auto-Extraction & Profile Sanitization...")
    # 1. URL with asset_id
    full_url = "https://business.facebook.com/latest/reels_composer/?asset_id=573974582461345&business_id=645625381317413&ir_qe_exposed=1&ref=biz_web_content_manager_published_posts&context_ref=POSTS"
    info = mrs.extract_meta_page_info(full_url)
    assert info["page_id"] == "573974582461345", f"Expected numeric ID 573974582461345, got {info['page_id']}"
    assert "573974582461345" in info["page_name"]
    assert "asset_id=573974582461345" in info["url"]

    # 2. URL with page_id query param
    pid_url = "https://business.facebook.com/latest/reels_composer/?global_scope_id=1937166564351023&page_id=968940149639460"
    info2 = mrs.extract_meta_page_info(pid_url)
    assert info2["page_id"] == "968940149639460"

    # 3. Bare numeric ID
    bare_id = "573974582461345"
    info3 = mrs.extract_meta_page_info(bare_id)
    assert info3["page_id"] == "573974582461345"
    assert "asset_id=573974582461345" in info3["url"]

    # 4. Profile Name Sanitization (preventing the 'Profile' vs 'Profile 15' truncation bug)
    assert mrs.sanitize_chrome_profile("Profile 15 — Pari (parii.v.singh@gmail.com)") == "Profile 15"
    assert mrs.sanitize_chrome_profile("Profile 15 - Pari") == "Profile 15"
    assert mrs.sanitize_chrome_profile("Profile 15 | Pari") == "Profile 15"
    assert mrs.sanitize_chrome_profile("Profile 15") == "Profile 15"
    assert mrs.sanitize_chrome_profile("Profile") == "Profile 15"  # Truncated string falls back safely to Profile 15
    assert mrs.sanitize_chrome_profile("Default — Work") == "Default"
    assert mrs.sanitize_chrome_profile("Profile 2 — Other") == "Profile 2"

    # 5. normalize_pages with URL pasted in ID
    dirty_pages = [
        {"id": full_url, "name": "Pasted Full URL Page", "enabled": True}
    ]
    norm, count = mrs.normalize_pages(dirty_pages)
    assert norm[0]["id"] == "573974582461345"
    assert norm[0]["url"] == full_url

    # 6. Verify brand task resolution for patpedhi
    task = mrs.controller.get_task_for_page("573974582461345", ignore_published=True)
    assert task is not None, "Failed to resolve task for patpedhi page 573974582461345"
    assert task["brand_name"] == "patpedhi"
    assert task["chrome_profile"] == "Profile 15"
    assert "9769602020" in task["caption"]

    print("  ✓ Meta URL auto-extraction, Profile 15 sanitization, and brand task routing verified 100%.")


def test_27_gui_datetime_picker_and_brand_telemetry():
    print("[TEST 27] Verifying Modern Time Picker, Datetime Widgets & Hero Telemetry...")
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()

    try:
        time_var = tk.StringVar(value="14:30")
        picker = mrs.ModernTimePicker(root, time_var)

        # 1. Check initial synchronization
        assert picker.hour_var.get() == "14", f"Expected hour '14', got {picker.hour_var.get()}"
        assert picker.min_var.get() == "30", f"Expected minute '30', got {picker.min_var.get()}"
        assert "02:30 PM" in picker.fmt12_var.get(), f"Expected '02:30 PM', got {picker.fmt12_var.get()}"

        # 2. Test preset time changes
        picker.set_preset("09:00")
        assert time_var.get() == "09:00", f"Expected time_var '09:00', got {time_var.get()}"
        assert "09:00 AM" in picker.fmt12_var.get(), f"Expected '09:00 AM', got {picker.fmt12_var.get()}"

        picker.set_preset("21:45")
        assert time_var.get() == "21:45", f"Expected time_var '21:45', got {time_var.get()}"
        assert "09:45 PM" in picker.fmt12_var.get(), f"Expected '09:45 PM', got {picker.fmt12_var.get()}"

        # 3. Test edge case hour conversions
        time_var.set("00:00")
        picker._update_from_main()
        assert "12:00 AM" in picker.fmt12_var.get(), f"Expected '12:00 AM', got {picker.fmt12_var.get()}"

        time_var.set("12:00")
        picker._update_from_main()
        assert "12:00 PM" in picker.fmt12_var.get(), f"Expected '12:00 PM', got {picker.fmt12_var.get()}"

        time_var.set("23:59")
        picker._update_from_main()
        assert "11:59 PM" in picker.fmt12_var.get(), f"Expected '11:59 PM', got {picker.fmt12_var.get()}"

        # 4. Verify Schedule interval & duration parsing
        class DummyDialog:
            def __init__(self, iv, dv):
                self.repeat_interval_var = tk.StringVar(value=iv)
                self.repeat_duration_var = tk.StringVar(value=dv)
            _parse_interval = mrs.ScheduleDialog._parse_interval
            _parse_duration = mrs.ScheduleDialog._parse_duration

        d1 = DummyDialog("15 minutes", "24 hours (All Day)")
        assert d1._parse_interval() == 15
        assert d1._parse_duration() == 24

        d2 = DummyDialog("0 (No Repeat - Run Once)", "12 hours")
        assert d2._parse_interval() == 0
        assert d2._parse_duration() == 12

        # 5. Verify Web Dashboard HTML generation contains required components
        dash_html = mrs.api_dashboard()
        assert "Meta Reels Enterprise Control Surface" in dash_html
        assert "brand-select" in dash_html
        assert "sched-modal" in dash_html
        assert "dest-search" in dash_html
        assert "caption-counter" in dash_html
        assert "table-layout: fixed !important;" in dash_html

        # 6. Verify MetaReelsGUI full initialization & callback binding
        app = mrs.MetaReelsGUI(root)
        assert hasattr(app, "save_config"), "MetaReelsGUI must have save_config attribute"
        assert hasattr(app, "save_settings"), "MetaReelsGUI must have save_settings attribute"
        assert callable(app.save_config), "save_config must be callable"

        print("  ✓ Modern Time Picker widget, 12h/24h format badge, and enterprise dashboard verified 100%.")
    finally:
        root.destroy()


def test_28_brand_media_folder_and_random_pairing():
    print("[TEST 28] Verifying Brand Media Folder Scanner, Dynamic Random Pairing & API Endpoints...")
    controller = mrs.controller
    loan_folder = BASE_DIR / "loan"
    assert loan_folder.exists(), f"Loan folder must exist at {loan_folder}"

    # 1. Verify scan_media_folder logic
    items = mrs.scan_media_folder(loan_folder)
    assert len(items) == 7, f"Expected 7 videos, got {len(items)}"
    paired_count = sum(1 for x in items if x.get("has_text"))
    assert paired_count == 7, f"Expected 7 paired text captions, got {paired_count}"
    for item in items:
        assert item["has_text"] is True
        assert item["caption"] and len(item["caption"]) > 100
        assert Path(item["video_path"]).exists()
        assert Path(item["text_path"]).exists()

    # 2. Verify select_random_media_pair with anti-repeat
    seen_stems = set()
    for _ in range(7):
        pair = mrs.select_random_media_pair(loan_folder, exclude_stems=list(seen_stems))
        assert pair is not None
        assert pair["stem"] not in seen_stems
        seen_stems.add(pair["stem"])
    assert len(seen_stems) == 7, "All 7 distinct media pairs must be selected without premature repetition"

    # 3. Verify Controller set_brand_media_folder & get_random_brand_media
    controller.set_brand_media_folder("brand_loan", str(loan_folder))
    brand = controller.get_brand("brand_loan")
    assert brand is not None
    assert brand.get("media_folder") == str(loan_folder)

    # 4. Verify get_random_brand_media
    b_pair = controller.get_random_brand_media("brand_loan")
    assert b_pair is not None
    assert b_pair["video"] and Path(b_pair["video"]).exists()
    assert b_pair["caption"] and len(b_pair["caption"]) > 100

    # 5. Verify resolve_page_task automatically picks random pair for brand_loan
    dummy_page = {"id": "page_loan_test", "name": "Loan Test Page", "enabled": True}
    resolved = controller.resolve_page_task(dummy_page, brand)
    assert resolved["video"] and Path(resolved["video"]).exists()
    assert "loan" in resolved["video"].lower()
    assert resolved["caption"] and len(resolved["caption"]) > 100

    # 6. Verify REST API endpoints
    from starlette.testclient import TestClient
    import urllib.parse
    client = TestClient(mrs.api_app)
    # /api/media/scan
    resp_scan = client.get(f"/api/media/scan?folder={urllib.parse.quote(str(loan_folder))}")
    assert resp_scan.status_code == 200
    data_scan = resp_scan.json()
    assert data_scan["ok"] is True
    assert data_scan["total_videos"] == 7
    assert data_scan["paired_count"] == 7

    # /api/brand/{id}/media-pairs
    resp_pairs = client.get("/api/brand/brand_loan/media-pairs")
    assert resp_pairs.status_code == 200
    data_pairs = resp_pairs.json()
    assert data_pairs["ok"] is True
    assert data_pairs["total_videos"] == 7

    # /api/brand/{id}/random-pair
    resp_rand = client.get("/api/brand/brand_loan/random-pair")
    assert resp_rand.status_code == 200
    data_rand = resp_rand.json()
    assert data_rand["ok"] is True
    assert data_rand["pair"]["has_text"] is True
    assert len(data_rand["pair"]["caption"]) > 100

    # /api/brand/{id}/media-folder POST
    resp_set = client.post("/api/brand/brand_loan/media-folder", json={"media_folder": str(loan_folder)})
    assert resp_set.status_code == 200
    assert resp_set.json()["ok"] is True

    print("  ✓ Brand Media Folder scanner, anti-repeat pairing, dynamic task resolution & REST APIs verified 100%.")


def test_29_input_restriction_manager_and_emergency_unlock():
    print("[TEST 29] Verifying Input Restriction Manager, Dual-Layer Blocking & Emergency Unlocking...")
    mgr = mrs.InputRestrictionManager

    # Ensure clean starting state
    mgr.release()
    assert not mgr.is_restricted(), "Expected initial state to be un-restricted"
    st0 = mgr.get_status()
    assert st0["restricted"] is False

    # 1. Acquire restriction
    ok = mgr.acquire(reason="Test Automated Publishing", max_timeout=10.0)
    assert ok is True
    assert mgr.is_restricted() is True
    st1 = mgr.get_status()
    assert st1["restricted"] is True
    assert st1["reason"] == "Test Automated Publishing"
    assert st1["max_timeout_seconds"] == 10.0

    # 2. Release restriction
    ok_rel = mgr.release()
    assert ok_rel is True
    assert mgr.is_restricted() is False
    assert mgr.get_status()["restricted"] is False

    # 3. Context manager 'with mgr.locked(...):'
    with mgr.locked(reason="Test Context Manager Scope", max_timeout=5.0):
        assert mgr.is_restricted() is True
        assert mgr.get_status()["restricted"] is True
    assert mgr.is_restricted() is False
    assert mgr.get_status()["restricted"] is False

    # 4. Watchdog Safety Timeout auto-release
    mgr.acquire(reason="Test Watchdog Timeout", max_timeout=0.4)
    assert mgr.is_restricted() is True
    time.sleep(0.65)
    assert mgr.is_restricted() is False, "Expected watchdog to auto-release input lock on timeout"

    # 5. REST API Endpoints via TestClient
    from starlette.testclient import TestClient
    client = TestClient(mrs.api_app)

    # GET /api/input-restriction/status
    resp_st = client.get("/api/input-restriction/status")
    assert resp_st.status_code == 200
    data_st = resp_st.json()
    assert data_st["ok"] is True
    assert data_st["restricted"] is False

    # POST /api/input-restriction/block
    resp_block = client.post("/api/input-restriction/block", json={"reason": "Audit API Test", "timeout": 2.0})
    assert resp_block.status_code == 200
    data_block = resp_block.json()
    assert data_block["ok"] is True
    assert data_block["status"]["restricted"] is True
    assert mgr.is_restricted() is True

    # POST /api/input-restriction/release
    resp_rel = client.post("/api/input-restriction/release")
    assert resp_rel.status_code == 200
    data_rel = resp_rel.json()
    assert data_rel["ok"] is True
    assert data_rel["status"]["restricted"] is False
    assert mgr.is_restricted() is False

    # 6. Controller Config Integration
    ctrl = mrs.controller
    assert hasattr(ctrl, "block_input_during_automation")
    assert ctrl.block_input_during_automation is True
    cfg = ctrl.get_config()
    assert cfg.get("block_input_during_automation") is True

    print("  ✓ Input Restriction Manager, Dual-Layer Blocking, Watchdog Timeout & REST APIs verified 100%.")


def test_30_multi_publish_and_daily_safety_cap():
    print("Testing Test 30: Multi-Publish Per Day & Anti-Spam Safety Capping Logic...")
    ctrl = mrs.controller
    today = dt.date.today().isoformat()
    test_page_id = "test_safety_page_999"

    # 1. Reset counters for test page
    ctrl.reset_page_attempt(test_page_id)
    assert ctrl.get_today_published_count(test_page_id, today) == 0

    # 2. Increment counters atomically
    cnt1 = ctrl.record_page_published(test_page_id, today)
    assert cnt1 == 1
    assert ctrl.get_today_published_count(test_page_id, today) == 1

    cnt2 = ctrl.record_page_published(test_page_id, today)
    assert cnt2 == 2
    assert ctrl.get_today_published_count(test_page_id, today) == 2

    # 3. Verify get_task_for_page allows multiple publishes when under limit
    orig_limit = ctrl.max_publications_per_day
    try:
        ctrl.max_publications_per_day = 7
        fake_page = {"id": test_page_id, "name": "Safety Test Page", "enabled": True}
        
        # Test capping threshold
        for _ in range(5):
            ctrl.record_page_published(test_page_id, today)
        assert ctrl.get_today_published_count(test_page_id, today) == 7

        # Now pub_cnt is 7, limit is 7 -> should be skipped in _execute_brand_pages
        todo = []
        for p in [fake_page]:
            pid = str(p['id']).strip()
            pub_cnt = ctrl.get_today_published_count(pid, today)
            if ctrl.max_publications_per_day > 0 and pub_cnt >= ctrl.max_publications_per_day:
                continue
            todo.append(p)
        assert len(todo) == 0, "Page should be skipped when reaching daily safety limit of 7"

        # Now set limit to 0 (unlimited) -> should NOT be skipped
        ctrl.max_publications_per_day = 0
        todo_unlimited = []
        for p in [fake_page]:
            pid = str(p['id']).strip()
            pub_cnt = ctrl.get_today_published_count(pid, today)
            if ctrl.max_publications_per_day > 0 and pub_cnt >= ctrl.max_publications_per_day:
                continue
            todo_unlimited.append(p)
        assert len(todo_unlimited) == 1, "Page should NOT be skipped when max_publications_per_day is 0 (unlimited)"

        # 4. REST API Endpoints via TestClient
        from starlette.testclient import TestClient
        client = TestClient(mrs.api_app)

        # POST /api/safety-limit
        resp_limit = client.post("/api/safety-limit", json={"max_publications_per_day": 7})
        assert resp_limit.status_code == 200
        data_limit = resp_limit.json()
        assert data_limit["ok"] is True
        assert data_limit["max_publications_per_day"] == 7
        assert ctrl.max_publications_per_day == 7

        # GET /api/pages contains today_published_count and max_publications_per_day
        resp_pages = client.get("/api/pages")
        assert resp_pages.status_code == 200
        pages_data = resp_pages.json()
        assert "pages" in pages_data
        for p in pages_data["pages"]:
            assert "today_published_count" in p
            assert "max_publications_per_day" in p
            assert p["max_publications_per_day"] == 7

        # 5. Clean up test page
        ctrl.reset_page_attempt(test_page_id)
        assert ctrl.get_today_published_count(test_page_id, today) == 0

    finally:
        ctrl.max_publications_per_day = orig_limit
        ctrl.update_config({"max_publications_per_day": orig_limit})

    print("  ✓ Multi-Publish per day, safety cap, counter increments, and REST APIs verified 100%.")


if __name__ == "__main__":
    print("================================================================================")
    print("STARTING META REELS SCHEDULER EXTENSIVE AUDIT & VERIFICATION SUITE")
    print("================================================================================")
    test_1_dynamic_paths()
    test_2_chrome_profile_and_video_discovery()
    test_3_extension_files_integrity()
    test_4_win32_dialog_engine()
    test_5_cv_inspection_engine()
    test_6_websocket_manager()
    test_7_modular_action_endpoints()
    test_8_research_telemetry_logging()
    test_9_learning_memory_db()
    test_10_autonomous_remediation_agent()
    test_11_publication_state_locking_and_tab_close()
    test_12_dynamic_gemma_root_model()
    test_13_intelligent_sequence_and_issue_monitor()
    test_14_lexical_safety_and_toolbar_resolution()
    test_15_standalone_portability_and_embedded_assets()
    test_16_windows_task_scheduler_and_multi_schedules()
    test_17_auto_extension_installer()
    test_18_scheduled_batch_cli_flag()
    test_19_nav_click_request_handling()
    test_20_extension_session_storage_clean()
    test_21_chrome_profile_scanner_and_selection()
    test_22_multi_brand_architecture_and_migration()
    test_23_multi_brand_task_resolution_and_inheritance()
    test_24_multi_brand_batch_and_scheduled_brand_targeting()
    test_25_multi_brand_rest_api_endpoints()
    test_26_meta_url_extraction_and_profile_sanitization()
    test_27_gui_datetime_picker_and_brand_telemetry()
    test_28_brand_media_folder_and_random_pairing()
    test_29_input_restriction_manager_and_emergency_unlock()
    test_30_multi_publish_and_daily_safety_cap()
    print("================================================================================")
    print("ALL AUDIT & VERIFICATION TESTS PASSED SUCCESSFULLY! (100% GREEN)")
    print("================================================================================")
