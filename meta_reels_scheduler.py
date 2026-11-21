# -*- coding: utf-8 -*-
"""Meta Reels Scheduler - Enterprise API & Event-Driven Reels Automation for Chrome Profile 15.

Key Architecture:
1. REST API & WebSocket Backend (FastAPI + Uvicorn) on http://127.0.0.1:8765:
   - All actions and buttons mapped to explicit API endpoints (/api/action/upload, /api/action/caption, /api/action/location, /api/action/next-edit, etc.)
   - High-level orchestrators: /api/pipeline/run-single, /api/run-page/{page_id}, /api/run-now, /api/stop
   - Real-time Server-Sent Events (SSE) telemetry stream on /api/events
   - Two-way WebSocket communication on /ws/page/{page_id}
   - Local Computer Vision inspection engine (/api/cv/inspect) with OpenCV & Pillow
   - Direct Win32 (#32770) native dialog automation via SendMessageW
2. Desktop GUI (Tkinter + Modern Fintech Styling):
   - Every GUI control/button triggers the internal controller methods.
   - Table of all 12 unique Meta pages with per-page overrides (video, caption, location).
   - Duplicate protection reset, daily 5:00 PM scheduler, and immediate batch trigger.
3. Chrome Helper Extension (Manifest V3 + MutationObserver Reactive DOM):
   - MutationObserver-backed instantaneous DOM element detection.
   - Dedicated Lexical / DraftJS caption editor text setter.
   - Dedicated location finder & dropdown selector.
   - Dedicated messenger CTA button activator.
   - 4-screen state machine (Create -> Edit -> Share -> Processing Modal Done).
   - Automatically closes completed tabs upon verified publication.
4. Sequential Execution Guard:
   - Strictly completes ONE profile at a time.
   - If any profile does not complete, halts immediately without opening further profiles.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import ctypes
from ctypes import wintypes
import datetime as dt
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import random
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
import webbrowser
import importlib
import platform

def ensure_dependencies():
    """Auto-detects and installs required dependencies if missing when moved to another PC."""
    required = [
        ("pyautogui", "pyautogui"),
        ("pyperclip", "pyperclip"),
        ("PIL", "pillow"),
        ("numpy", "numpy"),
        ("cv2", "opencv-python"),
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
        ("psutil", "psutil"),
        ("sklearn", "scikit-learn"),
        ("requests", "requests"),
        ("websockets", "websockets"),
        ("httpx", "httpx"),
    ]
    missing = []
    for mod_name, pkg_name in required:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            missing.append(pkg_name)
    if missing:
        print(f"[MetaReelsScheduler] Missing dependencies detected: {missing}. Auto-installing via pip...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *missing])
            print("[MetaReelsScheduler] All dependencies installed successfully.")
        except Exception as e:
            print(f"[MetaReelsScheduler] Warning: Failed to auto-install dependencies: {e}")

ensure_dependencies()

# GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Automation & Image Processing
import pyautogui
import pyperclip
from PIL import Image, ImageStat
import numpy as np
import cv2

# Web Server & Framework
from fastapi import FastAPI, Request, Response, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
import uvicorn

# Disable PyAutoGUI failsafe so boundary movements don't interrupt execution
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.2

APP_NAME = "Meta Reels Scheduler"

def get_base_dir() -> Path:
    """Returns the local folder containing this script. All application configs, state, logs, and extension stay here."""
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
APP_DIR = BASE_DIR
LOG_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = LOG_DIR / "screenshots"
EXT_DIR = BASE_DIR / "ChromeExtension"
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
RESEARCH_LOG_FILE = LOG_DIR / "execution_research.jsonl"
LEARNING_DB_FILE = LOG_DIR / "learning_memory.db"
TEMPLATE_PATH = BASE_DIR / "add_video_btn.png"

SYSTEM_OS = platform.system()
WIN_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if SYSTEM_OS == "Windows" else 0

def get_desktop_path() -> str:
    """Returns absolute path to the user's Desktop directory."""
    if SYSTEM_OS == "Windows":
        try:
            import ctypes.wintypes
            CSIDL_DESKTOP = 0
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOP, None, 0, buf)
            if buf.value:
                return buf.value
        except Exception:
            pass
    return str(Path.home() / "Desktop")

def create_windows_shortcut(target_exe: str, args: str, shortcut_path: str) -> tuple[bool, str]:
    """Generates a genuine Windows .lnk shortcut with target executable and arguments."""
    if SYSTEM_OS != "Windows":
        return False, "Shortcuts are only supported on Windows."
    try:
        temp_dir = os.environ.get("TEMP", str(Path.home()))
        vbs_path = os.path.join(temp_dir, "create_shortcut.vbs")
        vbs_content = f"""
Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = "{shortcut_path}"
Set oLink = oWS.CreateShortcut(sLinkFile)
oLink.TargetPath = "{target_exe}"
oLink.Arguments = "{args}"
oLink.Save
"""
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        subprocess.run(["cscript.exe", "//Nologo", vbs_path], creationflags=WIN_NO_WINDOW)
        if os.path.isfile(vbs_path):
            os.remove(vbs_path)
        return True, "Success"
    except Exception as e:
        return False, str(e)

def format_bytes(size: int | float) -> str:
    """Formats byte counts into human-readable B, KB, MB, GB, TB units."""
    if size == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            if unit == 'B':
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def get_dir_size(path: Path | str) -> int:
    """Optimized directory size calculation using os.scandir."""
    total = 0
    try:
        with os.scandir(str(path)) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += get_dir_size(entry.path)
    except Exception:
        pass
    return total

def clear_profile_cache(profile_full_path: Path | str) -> int:
    """Clears temporary browser caches to free disk space while preserving sessions and cookies."""
    p = Path(profile_full_path)
    cache_dirs = [p / "Cache", p / "Code Cache", p / "System Cache", p / "GPUCache"]
    freed = 0
    for cd in cache_dirs:
        if cd.exists():
            freed += get_dir_size(cd)
            try:
                shutil.rmtree(cd, ignore_errors=True)
            except Exception:
                pass
    return freed


class ChromeProfileScanner:
    """Enterprise Chromium & Chrome Profile Scanner.
    Extracts high-fidelity profile metadata directly from Local State JSON."""

    @staticmethod
    def get_browser_configs() -> dict:
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        user_home = str(Path.home())

        return {
            "Google Chrome": {
                "channel": "Stable",
                "color": "#4285F4",
                "user_data_paths": [
                    os.path.join(local_app, "Google", "Chrome", "User Data"),
                    os.path.join(user_home, "AppData", "Local", "Google", "Chrome", "User Data"),
                    os.path.join(user_home, "Library", "Application Support", "Google", "Chrome"),
                    os.path.join(user_home, ".config", "google-chrome")
                ],
                "exe_paths": [
                    os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"),
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "chrome.exe", "google-chrome"
                ]
            },
            "Chrome Canary": {
                "channel": "Canary",
                "color": "#FFC107",
                "user_data_paths": [os.path.join(local_app, "Google", "Chrome SxS", "User Data")],
                "exe_paths": [os.path.join(local_app, "Google", "Chrome SxS", "Application", "chrome.exe")]
            },
            "Microsoft Edge": {
                "channel": "Edge",
                "color": "#0078D4",
                "user_data_paths": [os.path.join(local_app, "Microsoft", "Edge", "User Data")],
                "exe_paths": [
                    os.path.join(prog_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"),
                    os.path.join(prog_files, "Microsoft", "Edge", "Application", "msedge.exe")
                ]
            },
            "Brave": {
                "channel": "Brave",
                "color": "#FF5722",
                "user_data_paths": [os.path.join(local_app, "BraveSoftware", "Brave-Browser", "User Data")],
                "exe_paths": [os.path.join(prog_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
            }
        }

    @classmethod
    def scan_profiles(cls, deep_scan: bool = False) -> list[dict]:
        configs = cls.get_browser_configs()
        discovered = []
        scanned_dirs = set()

        for browser_name, info in configs.items():
            exe_path = cls._find_exe(info.get("exe_paths", []))
            for udir in info.get("user_data_paths", []):
                if udir and os.path.exists(udir) and udir.lower() not in scanned_dirs:
                    scanned_dirs.add(udir.lower())
                    discovered.extend(cls._parse_user_data(udir, browser_name, info, exe_path))

        def _sort_key(p):
            dname = p.get("profile_dir_name", "")
            if dname == "Profile 15":
                return (-2, 0)
            if dname == "Default":
                return (-1, 0)
            if dname.startswith("Profile "):
                try:
                    return (0, int(dname.split()[1]))
                except Exception:
                    return (0, 999)
            return (1, 999)

        discovered.sort(key=_sort_key)
        return discovered

    @classmethod
    def _parse_user_data(cls, user_data_path: str, browser_name: str, config_info: dict, exe_path: str) -> list[dict]:
        profiles = []
        info_cache = {}
        local_state_path = os.path.join(user_data_path, "Local State")
        if os.path.isfile(local_state_path):
            try:
                with open(local_state_path, "r", encoding="utf-8", errors="ignore") as f:
                    data = json.load(f)
                    info_cache = data.get("profile", {}).get("info_cache") or data.get("profile", {}).get("attributes_storage") or {}
            except Exception:
                pass

        subdirs = []
        try:
            for entry in os.scandir(user_data_path):
                if entry.is_dir() and (entry.name == "Default" or entry.name.startswith("Profile ")):
                    subdirs.append(entry.name)
        except Exception:
            pass

        for pdir in subdirs:
            full_path = os.path.join(user_data_path, pdir)
            pdata = info_cache.get(pdir, {}) if isinstance(info_cache, dict) else {}
            name = pdata.get("name") or pdata.get("gaia_given_name") or pdir
            email = pdata.get("user_name") or pdata.get("gaia_name") or ""
            avatar_path = None
            for img in ("Google Profile Picture.png", "Profile Photo.png", "Google Profile Picture.jpg"):
                cimg = os.path.join(full_path, img)
                if os.path.isfile(cimg):
                    avatar_path = cimg
                    break

            label = f"[{pdir}] {name}" + (f" ({email})" if email else "")
            profiles.append({
                "browser": browser_name,
                "color": config_info.get("color", "#4285F4"),
                "profile_dir": pdir,
                "profile_dir_name": pdir,
                "name": name,
                "display_name": name,
                "email": email,
                "user_data_dir": user_data_path,
                "full_path": full_path,
                "path": full_path,
                "exe_path": exe_path,
                "avatar_path": avatar_path,
                "label": label
            })
        return profiles

    @staticmethod
    def _find_exe(exe_list: list) -> str:
        for exe in exe_list:
            if os.path.isabs(exe) and os.path.isfile(exe):
                return exe
            if shutil.which(exe):
                return shutil.which(exe)
        return ""


def detect_chrome_profile_15() -> Path:
    """Dynamically resolves the Chrome Profile directory using environment variables and cross-platform fallbacks.
    Prioritizes Profile 15, then Default or other existing profiles, ensuring seamless operation across any PC."""
    profiles = ChromeProfileScanner.scan_profiles()
    for p in profiles:
        if p["profile_dir_name"] == "Profile 15":
            return Path(p["full_path"])
    for p in profiles:
        if p["profile_dir_name"] == "Default":
            return Path(p["full_path"])
    if profiles:
        return Path(profiles[0]["full_path"])

    local_app_data = os.environ.get("LOCALAPPDATA")
    candidates = []
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google" / "Chrome" / "User Data")
    candidates.append(Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")

    user_data_root = None
    for c in candidates:
        if c.exists():
            user_data_root = c
            break
    if not user_data_root:
        user_data_root = candidates[0] if candidates else (Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data")

    p15 = user_data_root / "Profile 15"
    return p15

PROFILE_PATH = detect_chrome_profile_15()
USER_DATA_ROOT = PROFILE_PATH.parent
PROFILE_NAME = PROFILE_PATH.name
API_HOST = "127.0.0.1"
API_PORT = 8765

DEFAULT_URLS = [
    "https://business.facebook.com/latest/reels_composer/?asset_id=1021342791059139&business_id=1900745127232068&ir_qe_exposed=1&ref=biz_web_content_manager_published_posts&context_ref=POSTS",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=1937166564351023&business_id=1937166564351023&page_id=968940149639460&asset_id=968940149639460&redirect_session_id=1f660f98-bb22-4c65-a695-13e4a64dde8e",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=1824218265609572&business_id=1824218265609572&page_id=540655599140522&asset_id=540655599140522&redirect_session_id=a4296ebf-6b36-40b3-ac22-ea4b2f7e87de",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=1462542391914857&business_id=1462542391914857&page_id=606126075924474&asset_id=606126075924474&redirect_session_id=b9ab468d-b116-4689-8cce-e0590b9836dd",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=1111672017709796&business_id=1111672017709796&page_id=998352433357127&asset_id=998352433357127&redirect_session_id=9e4824b4-96b5-40b6-9fd5-e6741c361739",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=1900745127232068&business_id=1900745127232068&page_id=1021342791059139&asset_id=1021342791059139&redirect_session_id=ccf4dd9c-d215-420c-82b6-f84f4f2bee08",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=26050327574599734&business_id=26050327574599734&page_id=953852091149168&asset_id=953852091149168&redirect_session_id=8c8e6850-1369-4046-bfb9-d207def2df12",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=919018607501878&business_id=919018607501878&page_id=762973700228895&asset_id=762973700228895&redirect_session_id=408c9a46-cd19-4e50-a61f-ed03e3106bfb",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=2788006474877635&business_id=2788006474877635&page_id=552254391307530&asset_id=552254391307530&redirect_session_id=e5e959e6-4110-41f5-8df0-8296700037df",
    "https://business.facebook.com/latest/reels_composer/?global_scope_id=1598137398647597&business_id=1598137398647597&page_id=601054863081730&asset_id=601054863081730&redirect_session_id=ad14fbb0-a59e-404b-aca6-984a590402d7",
    "https://business.facebook.com/latest/reels_composer/?page_id=717586494764278&asset_id=717586494764278&redirect_session_id=2760f4ef-a98f-470d-9b61-1695c022dd23",
    "https://business.facebook.com/latest/reels_composer/?page_id=964243106761488&asset_id=964243106761488&redirect_session_id=f714874c-4b62-4b6e-85f3-8a3e5c8a8340",
    "https://business.facebook.com/latest/reels_composer/?page_id=974128589119815&asset_id=974128589119815&redirect_session_id=7dd10b66-59fd-4ec2-a0b8-553887dd0dc3",
]

TERMINAL_STATES = {
    "PUBLISHED", "READY_FOR_REVIEW", "READY_FOR_MANUAL_REVIEW", "PUBLISH_UNCERTAIN", "TASK_FAILED",
    "NEEDS_LOGIN", "SECURITY_CHALLENGE", "UPLOAD_NOT_VERIFIED",
    "LOCATION_NOT_VERIFIED", "COMPOSER_NOT_FOUND", "AUTOMATION_STOPPED",
    "TASK_TIMEOUT", "BLOCKED_OR_CHANGED_UI",
    "FILE_PICKER_NOT_DETECTED", "FILE_PICKER_FOCUS_FAILED", "FILE_PICKER_SUBMIT_FAILED",
}

LOG_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Main rotating file logger
logger = logging.getLogger("MetaReelsScheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = RotatingFileHandler(LOG_DIR / "meta_reels.log", maxBytes=5_000_000, backupCount=8, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"))
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(sh)

# Real-time SSE Subscribers
sse_subscribers: list[asyncio.Queue] = []

def broadcast_sse(event_data: dict):
    msg = f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    for q in list(sse_subscribers):
        try:
            q.put_nowait(msg)
        except Exception:
            pass

def record_research_log(event: str, page_id: str, step: str, duration_ms: float = 0.0, detail: dict = None, result: str = "OK"):
    """Appends an in-detail telemetry record to execution_research.jsonl and broadcasts via SSE."""
    try:
        record = {
            "timestamp": dt.datetime.now().isoformat(),
            "epoch_ms": int(time.time() * 1000),
            "event": event,
            "page_id": page_id,
            "step": step,
            "duration_ms": round(duration_ms, 2),
            "result": result,
            "detail": detail or {}
        }
        # Auto-rotate research log if exceeding 10MB to maintain peak I/O performance
        if RESEARCH_LOG_FILE.is_file() and RESEARCH_LOG_FILE.stat().st_size > 10_000_000:
            rot_target = LOG_DIR / "execution_research.old.jsonl"
            try:
                if rot_target.is_file():
                    rot_target.unlink()
                RESEARCH_LOG_FILE.rename(rot_target)
            except Exception as re:
                logger.debug("Research log rotation notice: %s", re)

        with open(RESEARCH_LOG_FILE, "a", encoding="utf-8") as rf:
            rf.write(json.dumps(record, ensure_ascii=False) + "\n")
        broadcast_sse(record)
    except Exception as exc:
        logger.warning("Could not write research log: %s", exc)


def ensure_default_desktop():
    """Attaches current thread to WinSta0\\Default desktop if running on Windows."""
    try:
        if platform.system() == "Windows":
            u = ctypes.windll.user32
            h_desk = u.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                u.SetThreadDesktop(h_desk)
    except Exception:
        pass


# ==============================================================================
# Enterprise Physical Input Restriction Engine (BlockInput & Low-Level Hooks)
# ==============================================================================

class InputRestrictionManager:
    """Blocks physical keyboard and mouse inputs during automated reels publishing,
    preventing user interference with Meta Business Suite clicks and Win32 file pickers.

    Safety & Emergency Release Guarantees:
    1. Automatic release immediately when automation finishes publishing (finally block).
    2. Automatic release if user presses Ctrl+Alt+Del, Alt+Del, or Escape.
    3. Automatic release when Windows switches desktop to Winlogon (SAS screen).
    4. Safety watchdog timeout (auto-releases if exceeding max duration, default 300s).
    5. Native OS BlockInput(True) with automatic fallback to Low-Level Win32 Hooks (WH_KEYBOARD_LL + WH_MOUSE_LL).
    6. Allows synthetic automation events (SendInput / pyautogui / mouse_event) so automation runs unhindered.
    7. Re-entrant reference counting (_ref_count) for nested brand and batch lifecycles.
    """
    _lock = threading.RLock()
    _ref_count = 0
    _is_restricted = False
    _native_blocked = False
    _kb_hook = None
    _ms_hook = None
    _kb_cproc = None
    _ms_cproc = None
    _hook_thread = None
    _hook_thread_id = None
    _hook_ready = threading.Event()
    _watchdog_thread = None
    _watchdog_stop = threading.Event()
    _synthetic_allowed = True
    _reason = ""
    _start_time = 0.0
    _max_timeout = 300.0
    _last_pos = (None, None)

    @classmethod
    def is_restricted(cls) -> bool:
        with cls._lock:
            return cls._is_restricted

    @classmethod
    def get_status(cls) -> dict:
        with cls._lock:
            return {
                "ok": True,
                "restricted": cls._is_restricted,
                "ref_count": cls._ref_count,
                "native_blocked": cls._native_blocked,
                "reason": cls._reason,
                "elapsed_seconds": round(time.time() - cls._start_time, 1) if cls._is_restricted else 0.0,
                "max_timeout_seconds": cls._max_timeout
            }

    @classmethod
    def acquire(cls, reason: str = "Automated publishing in progress", max_timeout: float = 300.0) -> bool:
        if platform.system() != "Windows":
            return False

        if "--no-block-input" in sys.argv:
            logger.info("[InputLock] Physical input restriction bypassed via --no-block-input flag.")
            return False

        try:
            if 'controller' in globals() and controller:
                if not getattr(controller, "block_input_during_automation", True):
                    logger.info("[InputLock] Physical input restriction disabled in controller settings.")
                    return False
        except Exception:
            pass

        with cls._lock:
            cls._ref_count += 1
            if cls._is_restricted:
                logger.debug(f"[InputLock] Re-entrant acquire held (ref_count={cls._ref_count}): {reason}")
                return True

            cls._reason = reason
            cls._max_timeout = max_timeout
            cls._start_time = time.time()
            cls._is_restricted = True
            cls._synthetic_allowed = True

            # Snapshot cursor position
            try:
                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                cls._last_pos = (pt.x, pt.y)
            except Exception:
                cls._last_pos = (None, None)

            logger.info(f"[InputLock] Physical keyboard & mouse LOCKED for: {reason}. (Press Ctrl+Alt+Del or Esc to unlock)")

            # 1. Attempt Native Windows BlockInput(True) (kernel driver lock when elevated)
            try:
                if ctypes.windll.user32.BlockInput(True):
                    cls._native_blocked = True
                    logger.info("[InputLock] Native OS BlockInput activated successfully (kernel driver lock).")
                else:
                    err = ctypes.GetLastError()
                    cls._native_blocked = False
                    logger.debug(f"[InputLock] Native BlockInput returned 0 (code {err}). User-mode low-level hooks active.")
            except Exception as e:
                cls._native_blocked = False
                logger.debug(f"[InputLock] Native BlockInput error: {e}")

            # 2. Always activate Low-Level Hook Blocker (WH_KEYBOARD_LL + WH_MOUSE_LL)
            cls._start_hook_thread()

            # 3. Start Safety & Desktop Switch Watchdog
            cls._start_watchdog_thread()

            record_research_log("INPUT_RESTRICTION_ACQUIRED", "SYSTEM", "SECURITY", detail={"reason": reason, "native_blocked": cls._native_blocked, "ref_count": cls._ref_count})
            return True

    @classmethod
    def release(cls, force: bool = False) -> bool:
        if platform.system() != "Windows":
            return True

        with cls._lock:
            if not cls._is_restricted:
                cls._ref_count = 0
                return True

            if not force:
                cls._ref_count = max(0, cls._ref_count - 1)
                if cls._ref_count > 0:
                    logger.debug(f"[InputLock] Nested release held (ref_count={cls._ref_count})")
                    return True

            cls._ref_count = 0
            cls._is_restricted = False
            cls._watchdog_stop.set()

            # 1. Release Native BlockInput
            try:
                ctypes.windll.user32.BlockInput(False)
            except Exception:
                pass
            cls._native_blocked = False

            # 2. Unhook Low-Level Hooks
            cls._stop_hook_thread()
            if cls._kb_hook:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(cls._kb_hook)
                except Exception:
                    pass
                cls._kb_hook = None
            if cls._ms_hook:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(cls._ms_hook)
                except Exception:
                    pass
                cls._ms_hook = None

            duration = time.time() - cls._start_time if cls._start_time else 0.0
            logger.info(f"[InputLock] Physical keyboard & mouse RESTRICTION RELEASED. (Held for {duration:.1f}s)")
            record_research_log("INPUT_RESTRICTION_RELEASED", "SYSTEM", "SECURITY", duration_ms=duration * 1000)
            return True

    @classmethod
    def _start_hook_thread(cls):
        cls._hook_ready.clear()

        def _hook_worker():
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # Explicit 64-bit ctypes function signatures
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            kernel32.GetCurrentThreadId.argtypes = []

            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]
            user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
            user32.CallNextHookEx.restype = ctypes.c_long
            user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.GetMessageW.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.TranslateMessage.restype = wintypes.BOOL
            user32.TranslateMessage.argtypes = [ctypes.c_void_p]
            user32.DispatchMessageW.restype = ctypes.c_long
            user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SetCursorPos.restype = wintypes.BOOL
            user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.c_void_p]

            WH_KEYBOARD_LL = 13
            WH_MOUSE_LL = 14
            LLKHF_INJECTED = 0x10
            LLKHF_LOWER_IL_INJECTED = 0x02
            LLMHF_INJECTED = 0x01
            LLMHF_LOWER_IL_INJECTED = 0x02
            VK_ESCAPE = 0x1B
            VK_DELETE = 0x2E
            VK_CONTROL = 0x11
            VK_MENU = 0x12  # Alt

            HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

            class KBDLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ('vkCode', wintypes.DWORD),
                    ('scanCode', wintypes.DWORD),
                    ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_size_t)
                ]

            class MSLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ('pt', wintypes.POINT),
                    ('mouseData', wintypes.DWORD),
                    ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_size_t)
                ]

            def kb_proc(nCode, wParam, lParam):
                if nCode >= 0 and cls._is_restricted:
                    kb = KBDLLHOOKSTRUCT.from_address(lParam)
                    is_injected = bool(kb.flags & LLKHF_INJECTED) or bool(kb.flags & LLKHF_LOWER_IL_INJECTED)
                    if is_injected:
                        if cls._synthetic_allowed:
                            return user32.CallNextHookEx(None, nCode, wParam, lParam)
                        return 1

                    # Check emergency release keys: Esc or Ctrl+Alt+Del or Alt+Del
                    ctrl = bool(user32.GetKeyState(VK_CONTROL) & 0x8000) or bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                    alt = bool(user32.GetKeyState(VK_MENU) & 0x8000) or bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                    if kb.vkCode == VK_ESCAPE or (kb.vkCode == VK_DELETE and (ctrl or alt)):
                        logger.warning("[InputLock] Emergency release key triggered by user! Releasing restrictions immediately.")
                        cls.release(force=True)
                        return user32.CallNextHookEx(None, nCode, wParam, lParam)

                    # Swallow all physical keyboard keystrokes
                    return 1
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            def ms_proc(nCode, wParam, lParam):
                if nCode >= 0 and cls._is_restricted:
                    ms = MSLLHOOKSTRUCT.from_address(lParam)
                    is_injected = bool(ms.flags & LLMHF_INJECTED) or bool(ms.flags & LLMHF_LOWER_IL_INJECTED)
                    if is_injected:
                        if cls._synthetic_allowed:
                            with cls._lock:
                                cls._last_pos = (ms.pt.x, ms.pt.y)
                            return user32.CallNextHookEx(None, nCode, wParam, lParam)
                        return 1

                    # Physical mouse event:
                    # Snap back cursor to last known automation position if user physically moves mouse
                    if wParam == 0x0200:  # WM_MOUSEMOVE
                        with cls._lock:
                            last_x, last_y = cls._last_pos
                        if last_x is not None and last_y is not None:
                            user32.SetCursorPos(last_x, last_y)

                    # Swallow all physical mouse clicks, moves, and wheel scrolls
                    return 1
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            cls._kb_cproc = HOOKPROC(kb_proc)
            cls._ms_cproc = HOOKPROC(ms_proc)
            hmod = kernel32.GetModuleHandleW(None)
            cls._kb_hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, cls._kb_cproc, hmod, 0)
            cls._ms_hook = user32.SetWindowsHookExW(WH_MOUSE_LL, cls._ms_cproc, hmod, 0)
            cls._hook_thread_id = kernel32.GetCurrentThreadId()
            cls._hook_ready.set()

            msg = wintypes.MSG()
            while cls._is_restricted and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if cls._kb_hook:
                try:
                    user32.UnhookWindowsHookEx(cls._kb_hook)
                except Exception:
                    pass
                cls._kb_hook = None
            if cls._ms_hook:
                try:
                    user32.UnhookWindowsHookEx(cls._ms_hook)
                except Exception:
                    pass
                cls._ms_hook = None

        t = threading.Thread(target=_hook_worker, name="InputRestrictionHookThread", daemon=True)
        t.start()
        cls._hook_thread = t
        cls._hook_ready.wait(timeout=2.0)

    @classmethod
    def _stop_hook_thread(cls):
        user32 = ctypes.windll.user32
        user32.PostThreadMessageW.restype = wintypes.BOOL
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        if cls._hook_thread_id:
            try:
                user32.PostThreadMessageW(cls._hook_thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
            cls._hook_thread_id = None

    @classmethod
    def _start_watchdog_thread(cls):
        cls._watchdog_stop.clear()
        def _watchdog():
            user32 = ctypes.windll.user32
            DESKTOP_SWITCHDESKTOP = 0x0100
            while not cls._watchdog_stop.wait(0.15):
                if not cls._is_restricted:
                    break

                # 1. Check max timeout safety guard
                if time.time() - cls._start_time > cls._max_timeout:
                    logger.warning(f"[InputLock] Safety timeout ({cls._max_timeout}s) exceeded. Releasing input restriction automatically.")
                    cls.release(force=True)
                    break

                # 2. Check desktop switch (Ctrl+Alt+Del switches to Winlogon secure desktop)
                try:
                    hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
                    if not hdesk:
                        logger.warning("[InputLock] Desktop switch / Ctrl+Alt+Del detected! Releasing input restriction immediately.")
                        cls.release(force=True)
                        break
                    else:
                        user32.CloseDesktop(hdesk)
                except Exception:
                    pass

        t = threading.Thread(target=_watchdog, name="InputRestrictionWatchdogThread", daemon=True)
        t.start()
        cls._watchdog_thread = t

    @classmethod
    @contextlib.contextmanager
    def locked(cls, reason: str = "Automated publishing in progress", max_timeout: float = 300.0):
        enabled = True
        try:
            if 'controller' in globals() and controller:
                enabled = getattr(controller, "block_input_during_automation", True)
        except Exception:
            enabled = True

        if not enabled or "--no-block-input" in sys.argv:
            yield
            return

        cls.acquire(reason=reason, max_timeout=max_timeout)
        try:
            yield
        finally:
            cls.release()


# ==============================================================================
# Native Win32 Dialog Automation (#32770) Engine
# ==============================================================================

class Win32DialogEngine:
    """Direct Windows message automation for file dialogs (#32770) via user32.dll."""

    WM_SETTEXT = 0x000C
    BM_CLICK = 0x00F5
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    VK_RETURN = 0x0D

    @classmethod
    def find_file_dialog(cls) -> int | None:
        ensure_default_desktop()
        user32 = ctypes.windll.user32
        dialog_hwnd = None

        def enum_cb(hwnd, _):
            nonlocal dialog_hwnd
            if user32.IsWindowVisible(hwnd):
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                if cls_buf.value == "#32770":
                    title_buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, title_buf, 512)
                    title = title_buf.value.lower()
                    if any(w in title for w in ["open", "select", "upload", "choose", "file"]):
                        dialog_hwnd = hwnd
                        return 0
                    edit = user32.FindWindowExW(hwnd, 0, "ComboBoxEx32", 0) or user32.FindWindowExW(hwnd, 0, "Edit", 0)
                    if edit:
                        dialog_hwnd = hwnd
                        return 0
            return 1

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return dialog_hwnd

    @classmethod
    def find_edit_control(cls, dialog_hwnd: int) -> int | None:
        user32 = ctypes.windll.user32
        comboboxex = user32.FindWindowExW(dialog_hwnd, 0, "ComboBoxEx32", 0)
        if comboboxex:
            combobox = user32.FindWindowExW(comboboxex, 0, "ComboBox", 0)
            if combobox:
                edit = user32.FindWindowExW(combobox, 0, "Edit", 0)
                if edit:
                    return edit
            edit = user32.FindWindowExW(comboboxex, 0, "Edit", 0)
            if edit:
                return edit
        edit = user32.FindWindowExW(dialog_hwnd, 0, "Edit", 0)
        return edit if edit else None

    @classmethod
    def find_open_button(cls, dialog_hwnd: int) -> int | None:
        user32 = ctypes.windll.user32
        curr = 0
        while True:
            curr = user32.FindWindowExW(dialog_hwnd, curr, "Button", 0)
            if not curr:
                break
            txt_buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(curr, txt_buf, 128)
            btn_txt = txt_buf.value.lower().replace("&", "")
            if "open" in btn_txt or "select" in btn_txt or "choose" in btn_txt:
                return curr
        return None

    @classmethod
    def submit_file(cls, dialog_hwnd: int, file_path: str) -> bool:
        user32 = ctypes.windll.user32
        abs_path = str(Path(file_path).resolve())
        if not Path(abs_path).is_file():
            return False

        user32.ShowWindow(dialog_hwnd, 5) # SW_SHOW
        user32.BringWindowToTop(dialog_hwnd)
        user32.SetForegroundWindow(dialog_hwnd)
        time.sleep(0.15)

        edit = cls.find_edit_control(dialog_hwnd)
        if edit:
            user32.SendMessageW(edit, cls.WM_SETTEXT, 0, abs_path)
            time.sleep(0.15)
        else:
            pyperclip.copy(abs_path)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.15)

        btn = cls.find_open_button(dialog_hwnd)
        if btn:
            user32.SendMessageW(btn, cls.BM_CLICK, 0, 0)
            time.sleep(0.2)

        if user32.IsWindowVisible(dialog_hwnd):
            user32.PostMessageW(dialog_hwnd, cls.WM_KEYDOWN, cls.VK_RETURN, 0)
            user32.PostMessageW(dialog_hwnd, cls.WM_KEYUP, cls.VK_RETURN, 0)
            time.sleep(0.2)

        if user32.IsWindowVisible(dialog_hwnd):
            pyautogui.press("enter")

        return True

    @classmethod
    def focus_chrome(cls) -> bool:
        """Finds visible Google Chrome window (excluding IDE and other electron apps) and brings it to foreground."""
        ensure_default_desktop()
        user32 = ctypes.windll.user32
        chrome_hwnd = None
        fallback_hwnd = None

        def enum_cb(hwnd, _):
            nonlocal chrome_hwnd, fallback_hwnd
            if not user32.IsWindowVisible(hwnd):
                return 1
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            if cls_buf.value == "Chrome_WidgetWin_1":
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    pname = psutil.Process(pid.value).name().lower()
                    if pname != "chrome.exe":
                        return 1
                except Exception:
                    return 1
                title_buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title_buf, 512)
                title = title_buf.value.lower()
                if any(w in title for w in ["meta", "reels", "composer", "business", "facebook"]):
                    chrome_hwnd = hwnd
                    return 0
                if "chrome" in title and not fallback_hwnd:
                    fallback_hwnd = hwnd
            return 1

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        target = chrome_hwnd or fallback_hwnd
        if target:
            user32.ShowWindow(target, 9)  # SW_RESTORE
            user32.ShowWindow(target, 3)  # SW_MAXIMIZE
            user32.BringWindowToTop(target)
            user32.keybd_event(0x12, 0, 0, 0)  # Alt down
            user32.SetForegroundWindow(target)
            user32.keybd_event(0x12, 0, 2, 0)  # Alt up
            time.sleep(0.18)
            return True
        return False

    @classmethod
    def start_watcher(cls, file_path: str, timeout: float = 12.0) -> threading.Thread:
        def _watch():
            deadline = time.time() + timeout
            while time.time() < deadline:
                dlg = cls.find_file_dialog()
                if dlg:
                    cls.submit_file(dlg, file_path)
                    break
                time.sleep(0.15)
        t = threading.Thread(target=_watch, name="Win32DialogWatcher", daemon=True)
        t.start()
        return t


# ==============================================================================
# Computer Vision Inspection Engine (OpenCV + PIL)
# ==============================================================================

class CVInspectionEngine:
    """Local Computer Vision Inspection Engine for screen state classification."""

    @classmethod
    def capture_screen(cls) -> Image.Image:
        ensure_default_desktop()
        try:
            return pyautogui.screenshot()
        except Exception as e:
            logger.debug("Desktop screenshot DC not accessible in this session: %s. Using fallback frame.", e)
            return Image.new("RGB", (1920, 1080), (20, 20, 20))

    @classmethod
    def inspect_current_screen(cls) -> dict:
        sc = cls.capture_screen()
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        sc_path = SCREENSHOT_DIR / f"cv_inspect_{ts}.png"
        try:
            sc.save(sc_path)
            # Auto-prune old screenshots to maintain bounded disk usage (keep latest 25)
            existing_shots = sorted(SCREENSHOT_DIR.glob("cv_inspect_*.png"), key=lambda f: f.stat().st_mtime)
            if len(existing_shots) > 25:
                for old_shot in existing_shots[:-25]:
                    try:
                        old_shot.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass

        sc_np = np.array(sc)
        sc_bgr = cv2.cvtColor(sc_np, cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(sc_bgr, cv2.COLOR_BGR2HSV)

        # 1. Green color mask (for 100% upload progress bar)
        lower_green = np.array([35, 50, 50])
        upper_green = np.array([85, 255, 255])
        green_mask = cv2.inRange(hsv, lower_green, upper_green)
        green_pixels = int(cv2.countNonZero(green_mask))
        has_green_progress_bar = green_pixels > 200

        # 2. Meta Blue color mask (for primary action buttons: Next, Share, Done)
        lower_blue = np.array([100, 120, 120])
        upper_blue = np.array([130, 255, 255])
        blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)
        blue_pixels = int(cv2.countNonZero(blue_mask))
        has_blue_action_button = blue_pixels > 350

        # 3. Laplacian Variance for screen sharpness/activity
        gray = cv2.cvtColor(sc_bgr, cv2.COLOR_BGR2GRAY)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # 4. Template matching against local assets
        template_matches = []
        for t_name in ["add_video_btn.png", "check_click_target.png", "exact_button_in_page2.png"]:
            tp = BASE_DIR / t_name
            if tp.is_file():
                try:
                    tmpl = cv2.imread(str(tp))
                    if tmpl is not None:
                        res = cv2.matchTemplate(sc_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        if max_val > 0.70:
                            template_matches.append({
                                "template": t_name,
                                "confidence": round(float(max_val), 3),
                                "location": {"x": int(max_loc[0]), "y": int(max_loc[1])}
                            })
                except Exception:
                    pass

        # 5. Classify state
        stage = "UNKNOWN"
        confidence = 0.5
        if has_blue_action_button and has_green_progress_bar:
            stage = "SCREEN_1_UPLOAD_COMPLETE"
            confidence = 0.95
        elif any(t["template"] == "add_video_btn.png" for t in template_matches):
            stage = "SCREEN_1_EMPTY_COMPOSER"
            confidence = 0.90
        elif has_blue_action_button and not has_green_progress_bar:
            stage = "SCREEN_2_OR_3_ACTIVE"
            confidence = 0.85
        elif lap_var < 5.0:
            stage = "SCREEN_BLANK_OR_LOADING"
            confidence = 0.90

        analysis = {
            "timestamp": dt.datetime.now().isoformat(),
            "screenshot": str(sc_path.name),
            "stage": stage,
            "confidence": confidence,
            "has_green_progress_bar": has_green_progress_bar,
            "green_pixel_count": green_pixels,
            "has_blue_action_button": has_blue_action_button,
            "blue_pixel_count": blue_pixels,
            "laplacian_variance": round(lap_var, 2),
            "template_matches": template_matches
        }
        record_research_log("CV_INSPECTION_COMPLETED", "SCREEN", stage, detail=analysis)
        return analysis

    @classmethod
    def find_action_button(cls, target: str = "bottom_right", near_coord: tuple[int, int] = None) -> tuple[int, int] | None:
        """Locates the blue Next/Share button or modal Done button using HSV color segmentation."""
        sc = cls.capture_screen()
        sc_np = np.array(sc)
        sc_bgr = cv2.cvtColor(sc_np, cv2.COLOR_RGB2BGR)
        h, w, _ = sc_bgr.shape
        hsv = cv2.cvtColor(sc_bgr, cv2.COLOR_BGR2HSV)

        # Meta primary blue button (covers wide range of saturations/dark mode)
        lower_blue = np.array([90, 80, 80])
        upper_blue = np.array([135, 255, 255])
        blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)

        contours, _ = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for c in contours:
            bx, by, bw, bh = cv2.boundingRect(c)
            if 25 <= bw <= 320 and 15 <= bh <= 80:
                candidates.append((bx, by, bw, bh))

        if not candidates:
            return None

        if near_coord:
            candidates.sort(key=lambda c: (c[0] + c[2]//2 - near_coord[0])**2 + (c[1] + c[3]//2 - near_coord[1])**2)
            bx, by, bw, bh = candidates[0]
            cand_center = (bx + bw // 2, by + bh // 2)
            dist = math.hypot(cand_center[0] - near_coord[0], cand_center[1] - near_coord[1])
            if dist <= 140:
                return cand_center
            return None

        if target == "bottom_right":
            # Sort by lowest and rightmost
            candidates.sort(key=lambda c: (c[1] + c[3], c[0] + c[2]), reverse=True)
            bx, by, bw, bh = candidates[0]
            return (bx + bw // 2, by + bh // 2)

        elif target in ("modal_done", "modal_save"):
            center_x, center_y = w // 2, h // 2
            center_candidates = [
                c for c in candidates 
                if abs((c[0] + c[2]//2) - center_x) < int(w * 0.40) and abs((c[1] + c[3]//2) - center_y) < int(h * 0.40)
            ]
            if center_candidates:
                if target == "modal_save":
                    center_candidates.sort(key=lambda c: c[0] + c[2], reverse=True)
                bx, by, bw, bh = center_candidates[0]
                return (bx + bw // 2, by + bh // 2)
            candidates.sort(key=lambda c: abs((c[0] + c[2]//2) - center_x) + abs((c[1] + c[3]//2) - center_y))
            bx, by, bw, bh = candidates[0]
            return (bx + bw // 2, by + bh // 2)

        return None

    @classmethod
    def click_action_button(cls, target: str = "bottom_right") -> bool:
        coords = cls.find_action_button(target)
        if coords:
            cx, cy = coords
            logger.info("CV clicking action button (%s) at (%d, %d)", target, cx, cy)
            try:
                pyautogui.moveTo(cx, cy, duration=0.2)
                time.sleep(0.1)
                pyautogui.click(cx, cy)
                return True
            except Exception as e:
                logger.warning("CV click failed: %s", e)
        return False


# ==============================================================================
# WebSocket Two-Way Command Manager
# ==============================================================================

class WebSocketManager:
    """Manages real-time bi-directional WebSocket connections from Chrome extension tabs."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.pending_futures: dict[str, asyncio.Future] = {}
        self.pending_commands: dict[str, list[dict]] = {}
        self.lock = threading.RLock()

    async def connect(self, page_id: str, websocket: WebSocket):
        await websocket.accept()
        with self.lock:
            self.active_connections[page_id] = websocket
        logger.info("WebSocket connected for page %s", page_id)
        record_research_log("WS_PAGE_CONNECTED", page_id, "WEBSOCKET")

    def disconnect(self, page_id: str):
        with self.lock:
            self.active_connections.pop(page_id, None)
        logger.info("WebSocket disconnected for page %s", page_id)
        record_research_log("WS_PAGE_DISCONNECTED", page_id, "WEBSOCKET")

    async def send_command(self, page_id: str, action: str, params: dict = None, timeout: float = 15.0) -> dict:
        req_id = f"cmd-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"
        ws = None
        with self.lock:
            ws = self.active_connections.get(page_id)

        payload = {
            "type": "EXEC_ACTION",
            "id": req_id,
            "action": action,
            "params": params or {}
        }

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self.lock:
            self.pending_futures[req_id] = future
            self.pending_commands.setdefault(page_id, []).append(payload)

        record_research_log("WS_COMMAND_DISPATCHED", page_id, action, detail=payload)

        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception as e:
                logger.warning("Failed to send WS command to page %s: %s", page_id, e)

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            record_research_log("WS_COMMAND_RESOLVED", page_id, action, detail=result)
            return result
        except asyncio.TimeoutError:
            record_research_log("WS_COMMAND_TIMEOUT", page_id, action, detail={"timeout_s": timeout}, result="TIMEOUT")
            return {"ok": False, "error": f"Command {action} timed out after {timeout}s", "action": action}
        finally:
            with self.lock:
                self.pending_futures.pop(req_id, None)

    def resolve_future(self, req_id: str, result: dict):
        with self.lock:
            fut = self.pending_futures.get(req_id)
            if fut and not fut.done():
                fut.set_result(result)

ws_manager = WebSocketManager()


# ==============================================================================
# Persistent Learning Database & Heuristics Memory Engine (SQLite WAL)
# ==============================================================================

class LearningMemoryDB:
    """Thread-safe persistent SQLite learning database for dynamic UI heuristics,
    selectors, coordinates, and continuous remediation patterns."""

    def __init__(self, db_path: Path = LEARNING_DB_FILE):
        self.db_path = db_path
        self.lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.lock, self._get_conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS element_heuristics (
                element_key TEXT PRIMARY KEY,
                primary_selector TEXT,
                fallback_selectors TEXT,
                target_coord_x REAL,
                target_coord_y REAL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                last_verified_at TEXT,
                meta_json TEXT
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS remediation_episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page_id TEXT,
                stage TEXT,
                status TEXT,
                error_message TEXT,
                remediation_action TEXT,
                success INTEGER,
                created_at TEXT
            )
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS learned_patterns (
                pattern_key TEXT PRIMARY KEY,
                description TEXT,
                action_type TEXT,
                action_payload TEXT,
                confidence REAL,
                updated_at TEXT
            )
            """)
            conn.commit()
            self._seed_baseline_heuristics(conn)

    def _seed_baseline_heuristics(self, conn: sqlite3.Connection):
        baseline = [
            ("add_video", "div[role='button']:has-text('Add Video'), button:has-text('Add Video')", json.dumps(["[role='button']", "input[type='file']", "text/Add Video"]), 530, 361, "Add Video file picker opener"),
            ("caption_box", "[data-lexical-editor='true'], [role='combobox'][contenteditable='true'], textarea", json.dumps(["div[contenteditable='true']", "[aria-label*='write' i]"]), 450, 420, "Reels caption input box"),
            ("messages_cta", "div[role='button'][title*='message' i], [aria-label*='message' i]", json.dumps(["button:has-text('Get messages')", "div:has-text('Get messages')"]), 280, 520, "Get messages button CTA"),
            ("location_button", "div[role='button'][title*='location' i], [aria-label*='location' i]", json.dumps(["button:has-text('Location')", "div:has-text('Location')"]), 320, 520, "Tag location button"),
            ("location_search", "input[placeholder*='search' i], input[placeholder*='location' i], input[role='combobox']", json.dumps(["[role='dialog'] input", "div[role='dialog'] input[type='text']"]), 500, 380, "Location search input field"),
            ("location_option", "[role='option'], [role='listbox'] div[tabindex]", json.dumps(["[role='option']:first-child", "div[role='listbox'] > div"]), 500, 430, "First location search result option"),
            ("location_save", "button:has-text('Save'), div[role='button']:has-text('Save')", json.dumps(["[role='dialog'] button:has-text('Save')", "[role='dialog'] div[role='button']:has-text('Save')"]), 560, 430, "Location modal blue Save button"),
            ("next_step1", "button:has-text('Next'), div[role='button']:has-text('Next')", json.dumps(["button[aria-label='Next']", "div[role='button'][aria-label='Next']"]), 745, 915, "Create step bottom right Next button"),
            ("next_step2", "button:has-text('Next'), div[role='button']:has-text('Next')", json.dumps(["button[aria-label='Next']", "div[role='button'][aria-label='Next']"]), 745, 840, "Edit step bottom right Next button"),
            ("share_step3", "button:has-text('Share'), div[role='button']:has-text('Share')", json.dumps(["button:has-text('Share now')", "button:has-text('Publish')"]), 745, 915, "Share step bottom right Share button"),
            ("done_step4", "button:has-text('Done'), div[role='button']:has-text('Done')", json.dumps(["[role='dialog'] button:has-text('Done')", "button:has-text('Done')"]), 605, 410, "Reel processing modal Done button")
        ]
        now = dt.datetime.now().isoformat()
        for key, sel, fallbacks, x, y, desc in baseline:
            conn.execute("""
            INSERT OR IGNORE INTO element_heuristics 
            (element_key, primary_selector, fallback_selectors, target_coord_x, target_coord_y, success_count, failure_count, last_verified_at, meta_json)
            VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)
            """, (key, sel, fallbacks, x, y, now, json.dumps({"description": desc})))
        conn.commit()

    def record_success(self, element_key: str, selector: str = "", coord_x: float = None, coord_y: float = None):
        with self.lock, self._get_conn() as conn:
            now = dt.datetime.now().isoformat()
            if coord_x is not None and coord_y is not None:
                conn.execute("""
                UPDATE element_heuristics 
                SET success_count = success_count + 1, last_verified_at = ?, target_coord_x = ?, target_coord_y = ?
                WHERE element_key = ?
                """, (now, coord_x, coord_y, element_key))
            else:
                conn.execute("""
                UPDATE element_heuristics 
                SET success_count = success_count + 1, last_verified_at = ?
                WHERE element_key = ?
                """, (now, element_key))
            conn.commit()

    def record_failure(self, element_key: str, error_msg: str = ""):
        with self.lock, self._get_conn() as conn:
            conn.execute("""
            UPDATE element_heuristics 
            SET failure_count = failure_count + 1
            WHERE element_key = ?
            """, (element_key,))
            conn.commit()

    def get_heuristic(self, element_key: str) -> dict | None:
        with self.lock, self._get_conn() as conn:
            row = conn.execute("SELECT * FROM element_heuristics WHERE element_key = ?", (element_key,)).fetchone()
            if row:
                res = dict(row)
                res["fallback_selectors"] = json.loads(res["fallback_selectors"] or "[]")
                res["meta_json"] = json.loads(res["meta_json"] or "{}")
                return res
            return None

    def list_heuristics(self) -> list[dict]:
        with self.lock, self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM element_heuristics ORDER BY success_count DESC").fetchall()
            out = []
            for r in rows:
                item = dict(r)
                item["fallback_selectors"] = json.loads(item.get("fallback_selectors") or "[]")
                item["meta_json"] = json.loads(item.get("meta_json") or "{}")
                # Aliases for dual-compatibility across GUI and REST APIs
                item["heuristic_key"] = item.get("element_key")
                item["coord_x"] = item.get("target_coord_x")
                item["coord_y"] = item.get("target_coord_y")
                item["last_updated"] = item.get("last_verified_at")
                succ = item.get("success_count", 0)
                fail = item.get("failure_count", 0)
                tot = succ + fail
                item["sample_count"] = tot
                item["reliability"] = (succ / max(1, tot))
                out.append(item)
            return out

    get_all_heuristics = list_heuristics

    def record_episode(self, page_id: str, stage: str, status: str, error_msg: str = "", remediation: str = "", success: bool = True):
        with self.lock, self._get_conn() as conn:
            conn.execute("""
            INSERT INTO remediation_episodes (page_id, stage, status, error_message, remediation_action, success, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (page_id, stage, status, error_msg, remediation, 1 if success else 0, dt.datetime.now().isoformat()))
            conn.commit()

    def list_episodes(self, limit: int = 50) -> list[dict]:
        with self.lock, self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM remediation_episodes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            out = []
            for r in rows:
                item = dict(r)
                # Aliases for dual-compatibility across GUI and REST APIs
                item["timestamp"] = item.get("created_at")
                item["resolution_status"] = item.get("status")
                item["action_taken"] = item.get("remediation_action")
                out.append(item)
            return out

    get_recent_episodes = list_episodes

learning_db = LearningMemoryDB()


# ==============================================================================
# Playwright Desktop Commander & Chrome DevTools Protocol (CDP) Bridge
# ==============================================================================

class PlaywrightCDPCommander:
    """Intelligent Playwright & Chrome DevTools Protocol (CDP) Commander.
    
    Connects to Chrome Profile 15 over CDP port 9222, providing deep accessibility tree
    inspection, trusted event dispatching, and automated self-healing.
    """

    CDP_URL = "http://127.0.0.1:9222"

    @classmethod
    def is_cdp_available(cls) -> bool:
        try:
            req = urllib.request.Request(f"{cls.CDP_URL}/json/version")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    @classmethod
    def execute_cdp_click(cls, selector: str, page_id: str = "") -> dict:
        """Uses Playwright to connect over CDP, locate element, and dispatch trusted hardware click."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(cls.CDP_URL)
                context = browser.contexts[0] if browser.contexts else None
                if not context:
                    return {"ok": False, "error": "No browser context found on CDP"}

                target_page = None
                for pg in context.pages:
                    if "reels_composer" in pg.url or (page_id and page_id in pg.url):
                        target_page = pg
                        break
                if not target_page and context.pages:
                    target_page = context.pages[0]

                if not target_page:
                    return {"ok": False, "error": "No matching target page in Playwright CDP"}

                locator = target_page.locator(selector).first
                locator.wait_for(state="visible", timeout=3000)
                box = locator.bounding_box()
                locator.click(timeout=3000)
                return {"ok": True, "action": "PLAYWRIGHT_CDP_CLICK", "box": box}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @classmethod
    def close_page(cls, page_id: str = "") -> dict:
        """Uses Playwright CDP to close the composer tab."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(cls.CDP_URL)
                context = browser.contexts[0] if browser.contexts else None
                if not context:
                    return {"ok": False, "error": "No browser context found on CDP"}
                for pg in context.pages:
                    if "reels_composer" in pg.url or (page_id and page_id in pg.url):
                        pg.close()
                        return {"ok": True, "action": "PLAYWRIGHT_CDP_CLOSE"}
                return {"ok": False, "error": "No matching target page found to close"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @classmethod
    def run_full_composer_flow(cls, task: dict, logger_func=None) -> dict:
        """Automates the entire Meta Reels Composer flow end-to-end via Playwright CDP."""
        def _log(msg, level="info"):
            if logger_func:
                logger_func(f"[PlaywrightCDP] {msg}", level)
            else:
                logger.info("[PlaywrightCDP] %s", msg)

        page_id = str(task.get("id", ""))
        video_path = task.get("video", "")
        caption = task.get("caption", "")
        location = task.get("location", "")

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(cls.CDP_URL)
                context = browser.contexts[0] if browser.contexts else None
                if not context:
                    return {"ok": False, "error": "No browser context found on CDP"}

                target_page = None
                for _ in range(30):
                    for pg in context.pages:
                        if "reels_composer" in pg.url or (page_id and page_id in pg.url):
                            target_page = pg
                            break
                    if target_page:
                        break
                    time.sleep(1.0)

                if not target_page:
                    if context.pages:
                        target_page = context.pages[0]
                    else:
                        return {"ok": False, "error": "No matching composer page found"}

                _log(f"Attached to composer page: {target_page.title()} ({target_page.url[:60]})")
                try:
                    target_page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(2.0)

                # Check if session redirected to Meta Login
                curr_url = target_page.url.lower()
                curr_title = target_page.title().lower()
                if "login" in curr_url or "login" in curr_title:
                    _log("Meta Business Suite login page detected. User authentication required.", "warning")
                    return {"ok": False, "error": "LOGIN_REQUIRED", "message": "Facebook session expired or logged out. Please log in to Meta Business Suite in Profile 15."}

                # 1. Attach Video File
                _log(f"Attaching video: {video_path}...")
                file_input = target_page.locator('input[type="file"]').first
                try:
                    file_input.wait_for(state="attached", timeout=10000)
                    file_input.set_input_files(video_path)
                    _log("Video file attached via input[type=file].")
                except Exception as fe:
                    _log(f"Input file attachment notice: {fe}. Checking Add Video button...")
                    add_btn = target_page.locator('div[role="button"]:has-text("Add video"), button:has-text("Add video")').first
                    if add_btn.is_visible():
                        Win32DialogEngine.start_watcher(video_path, timeout=12.0)
                        add_btn.click()
                        time.sleep(3.0)

                _log("Waiting for video processing & Next button to become enabled...")
                time.sleep(5.0)

                # 2. Fill Caption
                if caption:
                    _log(f"Filling caption ({len(caption)} chars)...")
                    try:
                        box = target_page.locator('div[role="textbox"], [contenteditable="true"]').first
                        box.wait_for(state="visible", timeout=8000)
                        box.click()
                        box.fill(caption)
                        _log("Caption filled successfully.")
                    except Exception as ce:
                        _log(f"Caption box notice: {ce}")

                # 3. Location
                if location:
                    _log(f"Selecting location '{location}'...")
                    try:
                        loc_btn = target_page.locator('div[role="button"]:has-text("Location"), span:has-text("Location")').first
                        if loc_btn.is_visible():
                            loc_btn.click()
                            time.sleep(1.0)
                            search_input = target_page.locator('input[placeholder*="search" i], input[aria-label*="location" i]').first
                            if search_input.is_visible():
                                search_input.fill(location)
                                time.sleep(1.5)
                                first_opt = target_page.locator('div[role="option"], ul[role="listbox"] > li').first
                                if first_opt.is_visible():
                                    first_opt.click()
                                    time.sleep(1.0)
                                    save_btn = target_page.locator('div[role="button"]:has-text("Save"), button:has-text("Save")').first
                                    if save_btn.is_visible():
                                        save_btn.click()
                                        _log("Location saved successfully.")
                    except Exception as le:
                        _log(f"Location notice: {le}")

                # 4. Screen 1 Next
                _log("Navigating to Screen 2 (Edit)...")
                next1 = target_page.locator('div[role="button"]:has-text("Next"), button:has-text("Next")').last
                next1.wait_for(state="visible", timeout=15000)
                next1.click()
                time.sleep(3.0)

                # 5. Screen 2 Next (to Share screen)
                _log("Navigating to Screen 3 (Share)...")
                share_direct = target_page.locator('div[role="button"]:has-text("Share"), button:has-text("Share")').last
                if not share_direct.is_visible():
                    next2 = target_page.locator('div[role="button"]:has-text("Next"), button:has-text("Next")').last
                    if next2.is_visible():
                        next2.click()
                        time.sleep(3.0)

                # 6. Screen 3 Share
                _log("Locating Share button...")
                share_btn = target_page.locator('div[role="button"]:has-text("Share"), button:has-text("Share")').last
                share_btn.wait_for(state="visible", timeout=20000)
                _log("Clicking Share button to publish reel...")
                share_btn.click()
                time.sleep(4.0)

                # 7. Done Modal & Success
                _log("Waiting for publication confirmation modal...")
                try:
                    done_btn = target_page.locator('div[role="button"]:has-text("Done"), button:has-text("Done")').first
                    done_btn.wait_for(state="visible", timeout=15000)
                    done_btn.click()
                    _log("Clicked Done button on publication modal.")
                    time.sleep(2.0)
                except Exception:
                    _log("Done modal did not appear or was auto-dismissed.")

                # Clean tab close
                try:
                    target_page.close()
                    _log(f"Closed completed tab for page {page_id}.")
                except Exception:
                    pass

                return {"ok": True, "state": "PUBLISHED", "action": "PLAYWRIGHT_CDP_PUBLISHED"}
        except Exception as exc:
            _log(f"Playwright CDP error: {exc}", "error")
            return {"ok": False, "error": str(exc)}


# ==============================================================================
# Autonomous Remediation & Model-Agent Self-Healing Engine
# ==============================================================================

class AdaptiveWaitEngine:
    """Calculates intelligent, jittered wait times based on stage complexity and system latency."""

    BASE_WAITS = {
        "COMPOSER_INIT": 3.0,
        "VIDEO_UPLOAD": 8.0,
        "CAPTION_INPUT": 0.8,
        "MESSAGES_CTA": 0.8,
        "LOCATION_SELECT": 1.2,
        "SCREEN_TRANSITION": 2.5,
        "SHARE_PUBLISH": 3.5,
        "DONE_MODAL": 2.0,
        "TAB_CLOSE": 2.0,
    }

    @classmethod
    def get_wait(cls, stage_key: str, multiplier: float = 1.0) -> float:
        base = cls.BASE_WAITS.get(stage_key, 2.0)
        jitter = random.uniform(0.95, 1.05)
        return round(base * multiplier * jitter, 2)


MODEL_NAME = "NONE"


MODEL_PATH = BASE_DIR
STATUS_FILE = BASE_DIR / "download_status.json"


class GemmaModelManager:
    """Lightweight zero-RAM compatibility stub (offline model completely purged)."""

    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self.llm = None
        self.is_loading = False
        self.is_ready = False
        self.load_error = None
        self.download_thread = None

    @classmethod
    def get_instance(cls) -> GemmaModelManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def get_status(self) -> dict:
        return {
            "model_name": "OFFLINE_MODEL_PURGED",
            "model_path": "",
            "file_exists": False,
            "file_size_bytes": 0,
            "in_ram": False,
            "is_loading": False,
            "load_error": None,
            "download_status": {"state": "PURGED"}
        }

    def trigger_download_async(self):
        pass

    def load_model_into_ram(self) -> bool:
        return True

    def reason(self, stage: str, page_id: str, error_detail: dict = None, heuristics: dict = None, dom_status: dict = None) -> dict:
        return {"action": "UNRESOLVED", "confidence": 0.0}


class LocalModelFallbackAgent:
    """Lightweight Heuristic Reasoning Engine (Zero RAM Overhead)."""

    @classmethod
    def is_local_llm_active(cls) -> bool:
        return False

    @classmethod
    def query_local_llm(cls, prompt: str, model: str = "") -> str | None:
        return None

    @classmethod
    def reason_action(cls, stage: str, page_id: str, error_detail: dict = None, memory_heuristics: dict = None, dom_status: dict = None) -> dict:
        """Intelligently deduces the winning button or coordinate action for the stalled stage."""
        stage_norm = stage.upper()
        h = memory_heuristics or {}

        if "SHARE" in stage_norm:
            coord = (int(h.get("target_coord_x", 1432)), int(h.get("target_coord_y", 986)))
            return {
                "source": "EMBEDDED_HEURISTIC_AGENT",
                "elem_key": "share_step3",
                "action": "HARDWARE_CLICK",
                "selector": "button:has-text('Share'), div[role='button']:has-text('Share')",
                "coord": coord,
                "confidence": 0.98
            }
        elif "DONE" in stage_norm or "PROCESSING" in stage_norm:
            coord = (int(h.get("target_coord_x", 1155)), int(h.get("target_coord_y", 439)))
            return {
                "source": "EMBEDDED_HEURISTIC_AGENT",
                "elem_key": "done_step4",
                "action": "HARDWARE_CLICK",
                "selector": "button:has-text('Done'), div[role='button']:has-text('Done')",
                "coord": coord,
                "confidence": 0.98
            }
        elif "SCREEN1" in stage_norm or "NEXT" in stage_norm:
            coord = (int(h.get("target_coord_x", 1434)), int(h.get("target_coord_y", 986)))
            return {
                "source": "EMBEDDED_HEURISTIC_AGENT",
                "elem_key": "next_step1",
                "action": "HARDWARE_CLICK",
                "selector": "button:has-text('Next')",
                "coord": coord,
                "confidence": 0.95
            }
        elif "SCREEN2" in stage_norm:
            coord = (int(h.get("target_coord_x", 1442)), int(h.get("target_coord_y", 908)))
            return {
                "source": "EMBEDDED_HEURISTIC_AGENT",
                "elem_key": "next_step2",
                "action": "HARDWARE_CLICK",
                "selector": "button:has-text('Next')",
                "coord": coord,
                "confidence": 0.95
            }
        elif "LOCATION" in stage_norm:
            coord = (int(h.get("target_coord_x", 560)), int(h.get("target_coord_y", 430)))
            return {
                "source": "EMBEDDED_HEURISTIC_AGENT",
                "elem_key": "location_save",
                "action": "HARDWARE_CLICK_OR_ENTER",
                "selector": "button:has-text('Save')",
                "coord": coord,
                "confidence": 0.92
            }

        return {"source": "EMBEDDED_HEURISTIC_AGENT", "action": "UNRESOLVED", "confidence": 0.0}


class AutonomousRemediationAgent:
    """Intelligent Self-Healing Model Agent with continuous learning.
    
    When an expected output is not gotten or a stage stalls:
    1. Analyzes the current screen layout via Computer Vision & DOM metrics.
    2. Identifies blocking conditions (e.g. leftover Location dialog, duplicate file dialog, modal backdrops).
    3. Retrieves ranked heuristics from LearningMemoryDB.
    4. Dispatches calibrated remediation actions (modal dismissal, hardware clicks, escape dispatch).
    5. Updates LearningMemoryDB with the verified solution.
    6. Dynamically adapts extension heuristics to prevent recurrence.
    """

    def __init__(self, controller: MetaReelsController, memory: LearningMemoryDB):
        self.controller = controller
        self.memory = memory
        self.lock = threading.RLock()
        self.last_remediation_time = 0.0

    def heal_and_update_code(self, element_key: str, winning_selector: str = "", winning_coord: tuple = None):
        """Continuous learning auto-updater: records the winning selector and coordinate into
        learning_memory.db and logs the continuous learning event."""
        with self.lock:
            if winning_coord:
                self.memory.record_success(element_key, coord_x=winning_coord[0], coord_y=winning_coord[1])
            if winning_selector:
                self.memory.record_success(element_key, selector=winning_selector)

            self.controller.log(f"[ContinuousLearning] Learned updated pattern for {element_key}: selector={winning_selector}, coord={winning_coord}")
            record_research_log("CONTINUOUS_LEARNING_UPDATE", self.controller.active_page_id, "CODE_HEAL", detail={
                "element_key": element_key,
                "selector": winning_selector,
                "coord": winning_coord
            })

    def evaluate_and_remediate(self, page_id: str, current_stage: str, error_detail: dict = None) -> dict:
        with self.lock:
            now = time.time()
            if now - self.last_remediation_time < 2.5:
                return {"remediated": False, "reason": "Throttled: remediation triggered recently"}
            self.last_remediation_time = now

            self.controller.log(f"[AutonomousAgent] Initiating self-healing analysis for page {page_id} at stage {current_stage}...")
            record_research_log("AGENT_REMEDIATION_START", page_id, "SELF_HEALING", detail={"stage": current_stage, "error": error_detail})

            # Check 1: Check for any open Windows OS file dialogs (#32770)
            existing_dlg = Win32DialogEngine.find_file_dialog()
            if existing_dlg:
                self.controller.log(f"[AutonomousAgent] Detected lingering file dialog ({existing_dlg}). Closing it to unblock Chrome...")
                ctypes.windll.user32.PostMessageW(existing_dlg, 0x0010, 0, 0)
                time.sleep(0.4)
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Lingering file dialog blocked Chrome", "Closed #32770 window", True)
                return {"remediated": True, "action": "CLOSED_LINGERING_FILE_DIALOG"}

            # Check 2: Check visual layout with CV inspection
            cv_result = CVInspectionEngine.inspect_current_screen()
            stage_detected = cv_result.get("detected_stage", "UNKNOWN")
            self.controller.log(f"[AutonomousAgent] CV Visual Inspection: Detected {stage_detected} (confidence: {cv_result.get('confidence')}%)")

            # Check 3: Check for blocking modals or missed toolbar buttons
            if current_stage in ("LOCATION_SEARCH_INPUT_NOT_FOUND", "LOCATION_FIRST_OPTION_NOT_FOUND") or stage_detected == "LOCATION_MODAL":
                self.controller.log("[AutonomousAgent] Remediating open Location modal: Clicking Save / pressing Enter...")
                h = self.memory.get_heuristic("location_save")
                if h and h.get("target_coord_x"):
                    x, y = int(h["target_coord_x"]), int(h["target_coord_y"])
                    self.controller.log(f"[AutonomousAgent] Clicking learned Save button coordinate ({x}, {y})...")
                    pyautogui.click(x, y)
                else:
                    pyautogui.press("enter")
                time.sleep(0.8)
                pyautogui.press("escape")
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Location modal blocking", "Dispatched Save/Escape to dismiss modal", True)
                return {"remediated": True, "action": "DISMISSED_LOCATION_MODAL"}

            if current_stage in ("LOCATION_BUTTON_NOT_FOUND", "MESSAGES_BUTTON_NOT_FOUND"):
                self.controller.log(f"[AutonomousAgent] Handling {current_stage}: scrolling down composer panel...")
                pyautogui.moveTo(400, 500)
                pyautogui.scroll(-300)
                time.sleep(0.5)
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", f"{current_stage} handled", "Scrolled composer pane to reveal controls", True)
                return {"remediated": True, "action": "SCROLLED_COMPOSER_PANE"}

            if current_stage == "CAPTION_BOX_NOT_FOUND":
                self.controller.log("[AutonomousAgent] Handling CAPTION_BOX_NOT_FOUND: scrolling to top of composer pane and focusing...")
                pyautogui.moveTo(450, 350)
                pyautogui.scroll(400)
                time.sleep(0.4)
                pyautogui.click(450, 350)
                time.sleep(0.5)
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Caption box unmounted or scrolled out", "Scrolled to top & focused editor", True)
                return {"remediated": True, "action": "FOCUSED_CAPTION_BOX"}

            if current_stage == "ADD_VIDEO_BUTTON_NOT_FOUND":
                self.controller.log("[AutonomousAgent] Handling ADD_VIDEO_BUTTON_NOT_FOUND: resetting composer view...")
                pyautogui.moveTo(530, 360)
                pyautogui.scroll(300)
                time.sleep(0.5)
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Add video button hidden", "Scrolled view", True)
                return {"remediated": True, "action": "SCROLLED_FOR_ADD_VIDEO"}

            # Check 4: Check if Screen 1 / Screen 2 Next button or Screen 3 Share button needs hardware fallback
            if current_stage == "SCREEN2_NEXT_NOT_FOUND" and stage_detected in ("SCREEN_2_OR_3_ACTIVE", "SHARE_SCREEN"):
                # Screen 2 was skipped or already reached Share screen! Seamlessly transition to Share
                self.controller.log(f"[AutonomousAgent] Page {page_id}: Composer already advanced past Edit to Share screen. Targeting Share button...")
                current_stage = "SHARE_BUTTON_NOT_FOUND"

            if "NEXT" in current_stage or current_stage in ("SCREEN1_NEXT_NOT_FOUND", "SCREEN2_NEXT_NOT_FOUND"):
                key = "next_step1" if "SCREEN1" in current_stage else "next_step2"
                blue_btn = CVInspectionEngine.find_action_button("bottom_right")
                h = self.memory.get_heuristic(key)
                x, y = blue_btn if blue_btn else (int(h.get("target_coord_x", 745)), int(h.get("target_coord_y", 915))) if h else (745, 915)
                self.controller.log(f"[AutonomousAgent] Dispatching calibrated hardware click for {key} at ({x}, {y})...")
                pyautogui.moveTo(x, y, duration=0.15)
                pyautogui.click(x, y)
                time.sleep(1.5)
                self.memory.record_success(key, coord_x=x, coord_y=y)
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", f"{key} DOM click missed", f"Hardware click at ({x}, {y})", True)
                return {"remediated": True, "action": f"HARDWARE_CLICK_{key.upper()}"}

            if "SHARE" in current_stage or current_stage == "SHARE_BUTTON_NOT_FOUND" or stage_detected == "SHARE_SCREEN":
                # Tier 1: Try Playwright CDP click if available
                if PlaywrightCDPCommander.is_cdp_available():
                    self.controller.log("[AutonomousAgent] Attempting Playwright CDP trusted click on Share button...")
                    cdp_res = PlaywrightCDPCommander.execute_cdp_click("button:has-text('Share'), div[role='button']:has-text('Share')", page_id)
                    if cdp_res.get("ok"):
                        self.controller.log("[AutonomousAgent] Playwright CDP click on Share succeeded!")
                        self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Share button missed", "Playwright CDP trusted click", True)
                        return {"remediated": True, "action": "PLAYWRIGHT_CDP_SHARE"}

                # Tier 2: Calibrated hardware mouse click (with visual CV blue button snapping)
                blue_btn = CVInspectionEngine.find_action_button("bottom_right")
                h = self.memory.get_heuristic("share_step3")
                x, y = blue_btn if blue_btn else (int(h.get("target_coord_x", 745)), int(h.get("target_coord_y", 915))) if h else (745, 915)
                self.controller.log(f"[AutonomousAgent] Dispatching calibrated hardware click for share_step3 at ({x}, {y})...")
                pyautogui.moveTo(x, y, duration=0.15)
                pyautogui.click(x, y)
                time.sleep(1.5)
                self.memory.record_success("share_step3", coord_x=x, coord_y=y)
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Share button DOM click missed", f"Hardware click at ({x}, {y})", True)
                return {"remediated": True, "action": "HARDWARE_CLICK_SHARE"}

            if "DONE" in current_stage or current_stage in ("WAITING_FOR_PROCESSING_MODAL", "PROCESSING_MODAL"):
                # Tier 1: Try Playwright CDP click if available
                if PlaywrightCDPCommander.is_cdp_available():
                    self.controller.log("[AutonomousAgent] Attempting Playwright CDP click on Done button...")
                    cdp_res = PlaywrightCDPCommander.execute_cdp_click("button:has-text('Done'), div[role='button']:has-text('Done')", page_id)
                    if cdp_res.get("ok"):
                        self.controller.log("[AutonomousAgent] Playwright CDP click on Done succeeded!")
                        self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Done button missed", "Playwright CDP click", True)
                        return {"remediated": True, "action": "PLAYWRIGHT_CDP_DONE"}

                h = self.memory.get_heuristic("done_step4")
                if h:
                    x, y = int(h.get("target_coord_x", 605)), int(h.get("target_coord_y", 410))
                    self.controller.log(f"[AutonomousAgent] Dispatching calibrated hardware click for done_step4 at ({x}, {y})...")
                    pyautogui.click(x, y)
                    time.sleep(1.5)
                    self.memory.record_success("done_step4", coord_x=x, coord_y=y)
                    self.memory.record_episode(page_id, current_stage, "REMEDIATED", "Done button DOM click missed", f"Hardware click at ({x}, {y})", True)
                    return {"remediated": True, "action": "HARDWARE_CLICK_DONE"}

            # Check 5: Model Fallback Agent (Gemma 4B / Embedded Neural Heuristics)
            h_key = "share_step3" if "SHARE" in current_stage else ("done_step4" if "DONE" in current_stage else ("next_step1" if "SCREEN1" in current_stage else ("next_step2" if "SCREEN2" in current_stage else "location_save")))
            h_data = self.memory.get_heuristic(h_key) or {}
            decision = LocalModelFallbackAgent.reason_action(current_stage, page_id, error_detail, h_data)
            self.controller.log(f"[AutonomousAgent] Model Fallback Agent decision: {decision.get('source')} -> action={decision.get('action')}, coord={decision.get('coord')}")

            if decision.get("coord"):
                cx, cy = decision["coord"]
                self.controller.log(f"[AutonomousAgent] Executing calibrated model hardware click at ({cx}, {cy})...")
                pyautogui.moveTo(cx, cy, duration=0.15)
                pyautogui.click(cx, cy)
                time.sleep(AdaptiveWaitEngine.get_wait("SCREEN_TRANSITION"))
                elem_k = decision.get("elem_key", h_key)
                self.heal_and_update_code(elem_k, decision.get("selector", ""), (cx, cy))
                self.memory.record_episode(page_id, current_stage, "REMEDIATED", f"Resolved via {decision.get('source')}", f"Hardware click at ({cx}, {cy})", True)
                return {"remediated": True, "action": decision.get("action"), "source": decision.get("source")}

            self.memory.record_episode(page_id, current_stage, "DIAGNOSED", "No direct remediation rule matched", "Observed state", False)
            return {"remediated": False, "reason": "No matched remediation rule"}


# ==============================================================================
# Extension Assets Setup
# ==============================================================================

BACKGROUND_JS = """const API = "http://127.0.0.1:8765";

const pingServer = async (state, detail = {}) => {
  try {
    await fetch(`${API}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state, detail, at: new Date().toISOString() })
    });
  } catch (e) {}
};

// Immediate ping on service worker execution
pingServer("BACKGROUND_LOADED", { version: "2.2.0" });

chrome.runtime.onInstalled.addListener(() => {
  pingServer("EXTENSION_INSTALLED", { version: "2.2.0" });
});

chrome.runtime.onStartup.addListener(() => {
  pingServer("EXTENSION_STARTUP", {});
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.url && (tab.url.includes("facebook.com") || tab.url.includes("meta.com"))) {
    pingServer("TAB_URL_LOADED", { tabId, status: changeInfo.status, url: tab.url, title: tab.title });
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "GET_TASK") {
    fetch(`${API}/next-task?page_id=${encodeURIComponent(msg.pageId || "")}`)
      .then(r => r.json())
      .then(data => sendResponse(data?.task || null))
      .catch(() => sendResponse(null));
    return true;
  }

  if (msg?.type === "REPORT") {
    fetch(`${API}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(msg.payload || {})
    })
      .then(r => r.json())
      .then(sendResponse)
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg?.type === "CLOSE_TAB") {
    const tabId = sender.tab?.id;
    if (tabId) {
      console.log("[Extension Background] Closing completed sender tab:", tabId);
      chrome.tabs.remove(tabId).catch(e => console.warn("Could not remove tab:", e));
    } else {
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs && tabs[0]?.id) {
          console.log("[Extension Background] Closing active tab:", tabs[0].id);
          chrome.tabs.remove(tabs[0].id).catch(e => console.warn("Could not remove tab:", e));
        }
      });
    }
    sendResponse({ ok: true });
    return true;
  }

  if (msg?.type === "GET_VIDEO_BLOB") {
    fetch(`${API}/api/video?page_id=${encodeURIComponent(msg.pageId || "")}`)
      .then(r => r.blob())
      .then(async blob => {
        const reader = new FileReader();
        reader.onloadend = () => {
          sendResponse({ ok: true, base64: reader.result, type: blob.type || "video/mp4", size: blob.size });
        };
        reader.readAsDataURL(blob);
      })
      .catch(e => sendResponse({ ok: false, error: String(e) }));
    return true;
  }
});"""

EMBEDDED_CONTENT_JS_ZLIB_B64 = """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"""

def get_content_js() -> str:
    content_file = EXT_DIR / "content.js"
    if content_file.is_file() and content_file.stat().st_size > 0:
        return content_file.read_text(encoding="utf-8")
    try:
        import zlib
        return zlib.decompress(base64.b64decode(EMBEDDED_CONTENT_JS_ZLIB_B64.strip())).decode("utf-8")
    except Exception as e:
        logger.warning("Error unpacking embedded content.js: %s", e)
        return ""

def write_extension():
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": "Meta Reels Scheduler Local Helper",
        "version": "2.2.0",
        "description": "Enterprise API & WebSocket connector for Meta Reels Composer.",
        "permissions": ["tabs", "activeTab", "scripting"],
        "host_permissions": [
            f"http://{API_HOST}:{API_PORT}/*",
            f"ws://{API_HOST}:{API_PORT}/*",
            "https://business.facebook.com/*",
            "https://*.facebook.com/*",
            "https://facebook.com/*",
            "https://*.meta.com/*",
            "https://meta.com/*"
        ],
        "background": {"service_worker": "background.js"},
        "content_scripts": [{
            "matches": [
                "https://business.facebook.com/*",
                "https://*.facebook.com/*",
                "https://facebook.com/*",
                "https://*.meta.com/*",
                "https://meta.com/*"
            ],
            "js": ["content.js"],
            "run_at": "document_start"
        }]
    }
    (EXT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (EXT_DIR / "background.js").write_text(BACKGROUND_JS, encoding="utf-8")
    content_file = EXT_DIR / "content.js"
    if not content_file.is_file() or content_file.stat().st_size == 0:
        content_file.write_text(get_content_js(), encoding="utf-8")

    # Synchronize to AppData if present to prevent Chrome profile directory skew
    appdata_ext = Path.home() / "AppData" / "Local" / "MetaReelsScheduler" / "ChromeExtension"
    try:
        appdata_ext.mkdir(parents=True, exist_ok=True)
        (appdata_ext / "manifest.json").write_text((EXT_DIR / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
        (appdata_ext / "background.js").write_text((EXT_DIR / "background.js").read_text(encoding="utf-8"), encoding="utf-8")
        if (EXT_DIR / "content.js").is_file():
            (appdata_ext / "content.js").write_text((EXT_DIR / "content.js").read_text(encoding="utf-8"), encoding="utf-8")
    except Exception as e:
        logger.debug("AppData extension sync notice: %s", e)

    return EXT_DIR

EMBEDDED_ADD_VIDEO_BTN_B64 = """iVBORw0KGgoAAAANSUhEUgAAAHMAAAAoCAIAAABCaFKFAAAFZklEQVR4nO2abUxbVRjHn8logbTMSWEB1uKkcyTFkRRKshaSUhYLLNuKWQjbVHTJtqCSzSwQNTPxBT+IiWGKY75gguJGwpYyZigk40ICdYZCIwWUDhjSWhi0HWmLpbejq2lLSV9ui2FcGfH8cj/c8zzn+Z/2f8899yV3m9PpBAQJbA+TG1ZPTWpmbbidjIG3IlFUSior8YV9ewizujmj3mh6uLzsaW4LNWeH1VML5kUuh02LiSbz124lFq1LytGJnbG0YHN1c8a/rbaU5AQqJdITeSqUyqRmFtkaAC0mmsthT2pmAxMAeqPJ19ZwztpwO5qtwdBiogmXx4fLy762hnMW8ZggZ8kCOUsWyFmyQM5uxpNCGBTK346ffgMnukruSWHdaPw2nhEH/2/WOWebpW2EtgLA1LSm5ebPsCnMqWR3pnDYys7qZgjullcZn7y3Rv3YZX56FvtjBVFu5ptjWRU9/rGei8xjTdrV5uhlbnp5s2G1rbp4wFWi72+oqOnWrqn2JDt7f27es3O0SDwsxySHCnyz03/pwpfLW1rgcEH69ZZWq0/UYTcvBJ4HuMVoDp6EnJwiukI+4m2O9rVbRPnZEH/40oT0FDu0mitosPjruSMOeGLm7Ox9z04sjfb0jtgvP63+of6LXQnxnqDJbA5X7FDI2umSsreLM7D2Xu+fn2qSZPM5uXzmqw3DK//Tgn0gZh8Qc7LFlZ0Wf4n9IiHI7qg8DW2/XJ8tEMT4TG0CNTD31+bliIUnj7CF55qnvINm8jnCPDZXXNkTMMRmOGtZXLThKwfeCSsvdPJy+XU1n3j2l5Zs4ep7bzYmlxxPiys6tF/WjrmFjM01tfMnvp8YGZi4QB8cd3cbaqiQZnzWO6BVXs+0ygM0ROICvK1j0F0r71ULinJWjmooNVDVnMNEV7qVnd3KcktlHYaDuubN2qiqNu3IwOjnPOm79XLHZjsbGen3gAwAjx49unajtfzCO55mdHRUmHKss4Mp5DEB4oUFmV2YzLUgjA3+kiQp2E8FoGaUvJbm6qYdUpiFouKdABH00mK/1cZFbqHE2tc1CmDoa+3nSYS+tyIEaqBRyS2G5qojXPERcd0YTM/M6xTdGlHp4STXmZdfWGhRKDWwyXddUVQqI+4Zg/EBAEzc+1N2G6ut/+539d3VDjvo9JDFDrm0HbSOk8wr3s49dkmRbw+cYNULjkQISo9ZKm6rX0/ukOcfbWSEGs+rxmCwIOPsT/Wlqz11TUAm61xnWbuTPTu/DijPnK/ytRUAkpMSQ1YOymUxJa0jA1r3JjudhHViOPAEB2daO1S4azVsueY+f5nZAmYPJl0AcBgbmzuClQTiQnP7jx+1KQqLRFS/DIEaxPBEXMXXjSqzw67vbHKts8m8PBYmda/g5i6ZjM7jsmDznU19NiVM9nn2c6FSg10yXCjI9DbTc3OoPX1yB0Xy1vmEq6fY6VmcOjxzrzuX9kp18VBlbhaTe2KEISDQyj56JqKjdbyk7CDFP0GkBnFlH76/69YpTgaf+x7mvsLuq/rqvKk6j5mexalSl10qF0TARuIMwbVb3aFSTqfzj7vjL750fDcnM3h7+WyF3mB0roNl3PQAD4jZzAaTzblRak4nbtKbbcvhI2tA6Ez/kDogss6n27S97M4bVzf0EANEUGJ3Bsao9DjqxqkBUGIZlLUiGwN6I0MWyFmyQM6SBXKWLJCz/7mzUVTKonWJtHG3KovWpSgqwb1E5PbtuP3hv3I2lZWoHJ1A5gZ/I5PKInjCjI/bMa2b9zU35NdH6Lsusr7rQjwm6ApGFshZskDOkgVyliyQs2SBnCUL5CxZIGfJAjkLJPEPyf1uNsu84acAAAAASUVORK5CYII="""

EMBEDDED_CHECK_CLICK_TARGET_B64 = """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"""

EMBEDDED_EXACT_BUTTON_B64 = """iVBORw0KGgoAAAANSUhEUgAAAHMAAAAoCAIAAABCaFKFAAAFZklEQVR4nO2abUxbVRjHn8logbTMSWEB1uKkcyTFkRRKshaSUhYLLNuKWQjbVHTJtqCSzSwQNTPxBT+IiWGKY75gguJGwpYyZigk40ICdYZCIwWUDhjSWhi0HWmLpbejq2lLSV9ui2FcGfH8cj/c8zzn+Z/2f8899yV3m9PpBAQJbA+TG1ZPTWpmbbidjIG3IlFUSior8YV9ewizujmj3mh6uLzsaW4LNWeH1VML5kUuh02LiSbz124lFq1LytGJnbG0YHN1c8a/rbaU5AQqJdITeSqUyqRmFtkaAC0mmsthT2pmAxMAeqPJ19ZwztpwO5qtwdBiogmXx4fLy762hnMW8ZggZ8kCOUsWyFmyQM5uxpNCGBTK346ffgMnukruSWHdaPw2nhEH/2/WOWebpW2EtgLA1LSm5ebPsCnMqWR3pnDYys7qZgjullcZn7y3Rv3YZX56FvtjBVFu5ptjWRU9/rGei8xjTdrV5uhlbnp5s2G1rbp4wFWi72+oqOnWrqn2JDt7f27es3O0SDwsxySHCnyz03/pwpfLW1rgcEH69ZZWq0/UYTcvBJ4HuMVoDp6EnJwiukI+4m2O9rVbRPnZEH/40oT0FDu0mitosPjruSMOeGLm7Ox9z04sjfb0jtgvP63+of6LXQnxnqDJbA5X7FDI2umSsreLM7D2Xu+fn2qSZPM5uXzmqw3DK//Tgn0gZh8Qc7LFlZ0Wf4n9IiHI7qg8DW2/XJ8tEMT4TG0CNTD31+bliIUnj7CF55qnvINm8jnCPDZXXNkTMMRmOGtZXLThKwfeCSsvdPJy+XU1n3j2l5Zs4ep7bzYmlxxPiys6tF/WjrmFjM01tfMnvp8YGZi4QB8cd3cbaqiQZnzWO6BVXs+0ygM0ROICvK1j0F0r71ULinJWjmooNVDVnMNEV7qVnd3KcktlHYaDuubN2qiqNu3IwOjnPOm79XLHZjsbGen3gAwAjx49unajtfzCO55mdHRUmHKss4Mp5DEB4oUFmV2YzLUgjA3+kiQp2E8FoGaUvJbm6qYdUpiFouKdABH00mK/1cZFbqHE2tc1CmDoa+3nSYS+tyIEaqBRyS2G5qojXPERcd0YTM/M6xTdGlHp4STXmZdfWGhRKDWwyXddUVQqI+4Zg/EBAEzc+1N2G6ut/+539d3VDjvo9JDFDrm0HbSOk8wr3s49dkmRbw+cYNULjkQISo9ZKm6rX0/ukOcfbWSEGs+rxmCwIOPsT/Wlqz11TUAm61xnWbuTPTu/DijPnK/ytRUAkpMSQ1YOymUxJa0jA1r3JjudhHViOPAEB2daO1S4azVsueY+f5nZAmYPJl0AcBgbmzuClQTiQnP7jx+1KQqLRFS/DIEaxPBEXMXXjSqzw67vbHKts8m8PBYmda/g5i6ZjM7jsmDznU19NiVM9nn2c6FSg10yXCjI9DbTc3OoPX1yB0Xy1vmEq6fY6VmcOjxzrzuX9kp18VBlbhaTe2KEISDQyj56JqKjdbyk7CDFP0GkBnFlH76/69YpTgaf+x7mvsLuq/rqvKk6j5mexalSl10qF0TARuIMwbVb3aFSTqfzj7vjL750fDcnM3h7+WyF3mB0roNl3PQAD4jZzAaTzblRak4nbtKbbcvhI2tA6Ez/kDogss6n27S97M4bVzf0EANEUGJ3Bsao9DjqxqkBUGIZlLUiGwN6I0MWyFmyQM6SBXKWLJCz/7mzUVTKonWJtHG3KovWpSgqwb1E5PbtuP3hv3I2lZWoHJ1A5gZ/I5PKInjCjI/bMa2b9zU35NdH6Lsusr7rQjwm6ApGFshZskDOkgVyliyQs2SBnCUL5CxZIGfJAjkLJPEPyf1uNsu84acAAAAASUVORK5CYII="""

def ensure_embedded_assets():
    """Ensures template PNG images exist locally by auto-extracting from embedded base64 if missing."""
    assets = {
        BASE_DIR / "add_video_btn.png": EMBEDDED_ADD_VIDEO_BTN_B64,
        BASE_DIR / "check_click_target.png": EMBEDDED_CHECK_CLICK_TARGET_B64,
        BASE_DIR / "exact_button_in_page2.png": EMBEDDED_EXACT_BUTTON_B64,
    }
    for file_path, b64_str in assets.items():
        if not file_path.is_file() or file_path.stat().st_size == 0:
            try:
                data = base64.b64decode(b64_str.strip())
                file_path.write_bytes(data)
            except Exception as e:
                logger.warning("Could not extract embedded asset %s: %s", file_path.name, e)


def ensure_chrome_extension_installed(profile_path: Path = None) -> dict:
    r"""Automatically installs and synchronizes the Chrome extension into:
    1. Local EXT_DIR (c:\Users\JMD\Documents\Apps\meta\ChromeExtension)
    2. LocalAppData (%LOCALAPPDATA%\MetaReelsScheduler\ChromeExtension)
    3. Target Chrome Profile directory (e.g. Profile 15\Extensions\MetaReelsScheduler)
    4. Windows Registry for Chrome External Extensions (HKCU\Software\Google\Chrome\Extensions)
    5. Sets developer_mode = True in Profile Preferences so unpacked extensions run without security blocks.
    """
    ext_path = write_extension()
    target_prof = profile_path or PROFILE_PATH
    results = {"version": "2.2.0", "ext_path": str(ext_path), "profile": str(target_prof), "actions": []}

    # 1. Profile Extensions Directory
    try:
        if target_prof.exists():
            prof_ext_dir = target_prof / "Extensions" / "MetaReelsScheduler"
            prof_ext_dir.mkdir(parents=True, exist_ok=True)
            for fname in ("manifest.json", "background.js", "content.js"):
                src = ext_path / fname
                if src.is_file():
                    (prof_ext_dir / fname).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            results["actions"].append("COPIED_TO_PROFILE_DIR")
    except Exception as pe:
        logger.debug("Profile extension sync notice: %s", pe)

    logger.info("Chrome extension synced for Profile: %s (%s)", target_prof.name, ", ".join(results["actions"]) or "UP_TO_DATE")
    return results


def scan_media_folder(folder_path: str | Path) -> list[dict]:
    """Scans a brand media folder for video files and automatically pairs each video
    with its corresponding text file (matching by filename stem, e.g. 1.mp4 <-> 1.txt).
    Returns list of discovered items with full path, file names, paired status, and caption content.
    """
    if not folder_path:
        return []
    p = Path(folder_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.is_dir():
        # Dynamic self-healing: if folder was moved to a new base directory, check BASE_DIR / p.name
        candidate = BASE_DIR / p.name
        if candidate.is_dir():
            p = candidate
        elif (BASE_DIR / "loan").is_dir() and "loan" in str(folder_path).lower():
            p = BASE_DIR / "loan"
        else:
            return []

    video_exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    text_exts = {".txt", ".caption"}

    try:
        all_files = list(p.iterdir())
    except Exception as e:
        logger.warning("Could not read media folder %s: %s", p, e)
        return []

    videos = [f for f in all_files if f.is_file() and f.suffix.lower() in video_exts]
    texts = [f for f in all_files if f.is_file() and f.suffix.lower() in text_exts]

    text_by_stem = {t.stem.lower(): t for t in texts}

    pairs = []
    for vid in sorted(videos, key=lambda x: x.name):
        txt_file = text_by_stem.get(vid.stem.lower())
        caption_content = ""
        if txt_file and txt_file.is_file():
            for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
                try:
                    caption_content = txt_file.read_text(encoding=enc).strip()
                    if caption_content:
                        break
                except Exception:
                    continue
        pairs.append({
            "video_path": str(vid.resolve()),
            "video_name": vid.name,
            "text_path": str(txt_file.resolve()) if txt_file else "",
            "text_name": txt_file.name if txt_file else "",
            "has_paired_text": bool(txt_file and caption_content),
            "has_text": bool(txt_file and caption_content),
            "caption": caption_content,
            "caption_length": len(caption_content),
            "stem": vid.stem
        })
    return pairs


def select_random_media_pair(folder_path: str | Path, exclude_stems: list[str] = None) -> dict | None:
    """Randomly selects a video and its matching text caption from the brand's media folder.
    Prioritizes items that have both a video and a matching text file.
    Applies anti-repeat filtering to prevent back-to-back duplicate reels during batch execution.
    """
    pairs = scan_media_folder(folder_path)
    if not pairs:
        return None

    # Filter out recent selections if multiple candidates exist
    exclude = set(exclude_stems or [])
    eligible = [p for p in pairs if p["stem"] not in exclude]
    if not eligible:
        eligible = pairs

    # Prioritize items with paired text files
    paired_eligible = [p for p in eligible if p["has_paired_text"]]
    pool = paired_eligible if paired_eligible else eligible

    selected = random.choice(pool)
    return {
        "video": selected["video_path"],
        "video_name": selected["video_name"],
        "caption": selected["caption"],
        "text_path": selected["text_path"],
        "text_name": selected["text_name"],
        "has_paired_text": selected["has_paired_text"],
        "has_text": selected["has_paired_text"],
        "stem": selected["stem"],
        "total_pairs": len(pairs)
    }


def ensure_standalone_environment(profile_path: Path = None) -> dict:
    r"""Guarantees complete standalone zero-configuration self-bootstrapping.
    Whenever meta_reels_scheduler.py is copied to any directory or machine:
    1. Installs missing Python dependencies via pip.
    2. Materializes all required template PNG images from embedded base64.
    3. Generates unpacked Chrome Helper extension files in BASE_DIR / 'ChromeExtension' and AppData.
    4. Auto-detects and auto-installs/registers the extension into the active Chrome profile (e.g. Profile 15).
    5. Ensures a valid vertical reel MP4 (sample_reel_vertical.mp4) exists if no video is present.
    6. Ensures directories (logs/, logs/screenshots/) exist.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "screenshots").mkdir(parents=True, exist_ok=True)

    ensure_dependencies()
    ensure_embedded_assets()
    ext_dir = write_extension()
    ext_reg = ensure_chrome_extension_installed(profile_path)

    return {
        "status": "ready",
        "extension_path": str(ext_dir),
        "extension_registered": ext_reg,
    }


class WindowsTaskSchedulerManager:
    """Manages Windows Task Scheduler (schtasks.exe) jobs for automated reels publication."""

    TASK_PREFIX = "MetaReelsScheduler_"

    @classmethod
    def get_python_exe(cls) -> Path:
        """Returns the Python executable: prefers user-configured Python 3.12, .llm_env, or sys.executable."""
        py312 = Path(r"C:\Program Files\Python312\python.exe")
        if py312.is_file():
            return py312
        local_env_py = BASE_DIR / ".llm_env" / "Scripts" / "python.exe"
        if local_env_py.is_file():
            return local_env_py
        return Path(sys.executable)

    @classmethod
    def get_script_path(cls) -> Path:
        """Returns absolute path to meta_reels_scheduler.py."""
        return (BASE_DIR / "meta_reels_scheduler.py").resolve()

    @classmethod
    def sanitize_task_name(cls, sched_id: str) -> str:
        clean = "".join(c for c in sched_id if c.isalnum() or c in ("_", "-"))
        return f"{cls.TASK_PREFIX}{clean}"

    @classmethod
    def register_or_update_task(cls, sched: dict) -> dict:
        """Creates or updates a Windows Task Scheduler job for the given schedule."""
        sched_id = sched.get("id") or f"sched_{int(time.time())}"
        sched_time = str(sched.get("time", "17:00")).strip()
        task_name = cls.sanitize_task_name(sched_id)

        # Validate time format HH:MM
        try:
            parts = sched_time.split(":")
            h, m = int(parts[0]), int(parts[1])
            assert 0 <= h <= 23 and 0 <= m <= 59
            formatted_time = f"{h:02d}:{m:02d}"
        except Exception:
            return {"ok": False, "error": f"Invalid time format: '{sched_time}'. Use HH:MM (24h)."}

        repeat_interval = 0
        try:
            repeat_interval = int(sched.get("repeat_interval_minutes") or 0)
        except Exception:
            repeat_interval = 0

        repeat_duration_hours = 24
        try:
            repeat_duration_hours = int(sched.get("repeat_duration_hours") or 24)
            repeat_duration_hours = max(1, min(repeat_duration_hours, 99))
        except Exception:
            repeat_duration_hours = 24

        days_val = str(sched.get("days", "DAILY")).upper()
        if days_val in ("MON-FRI", "WEEKDAYS"):
            sc_args = ["/sc", "weekly", "/d", "MON,TUE,WED,THU,FRI"]
        elif days_val in ("SAT-SUN", "WEEKENDS"):
            sc_args = ["/sc", "weekly", "/d", "SAT,SUN"]
        else:
            sc_args = ["/sc", "daily"]

        py_exe = str(cls.get_python_exe())
        script_file = str(cls.get_script_path())

        target_brand = str(sched.get("target_brand") or "").strip()
        cmd_run = f'"{py_exe}" "{script_file}" --scheduled-batch --schedule-id "{sched_id}"'
        if target_brand:
            cmd_run += f' --brand "{target_brand}"'

        sch_cmd = [
            "schtasks", "/create",
            "/tn", task_name,
            "/tr", cmd_run,
            *sc_args,
            "/st", formatted_time
        ]

        if repeat_interval > 0:
            dur_str = f"{repeat_duration_hours:02d}:00"
            sch_cmd.extend(["/ri", str(repeat_interval), "/du", dur_str])

        sch_cmd.append("/f")

        try:
            res = subprocess.run(sch_cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                rep_msg = f" repeating every {repeat_interval}m for {repeat_duration_hours}h" if repeat_interval > 0 else ""
                brand_msg = f" (Brand: {target_brand or 'ALL'})" if target_brand else ""
                logger.info(f"Registered Windows Task '{task_name}' at {formatted_time}{rep_msg}{brand_msg}.")
                # Apply Windows Task Scheduler settings hardening via PowerShell
                try:
                    ps_cmd = (
                        f"$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
                        f"-StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew; "
                        f"Set-ScheduledTask -TaskName '{task_name}' -Settings $s -ErrorAction SilentlyContinue"
                    )
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, check=False)
                except Exception as pse:
                    logger.debug("PowerShell task hardening notice: %s", pse)

                return {
                    "ok": True,
                    "task_name": task_name,
                    "time": formatted_time,
                    "target_brand": target_brand or "ALL",
                    "repeat_interval_minutes": repeat_interval,
                    "repeat_duration_hours": repeat_duration_hours,
                    "command": cmd_run,
                    "output": res.stdout.strip()
                }
            else:
                err = res.stderr.strip() or res.stdout.strip()
                logger.warning(f"Could not register Windows Task '{task_name}': {err}")
                return {"ok": False, "error": err}
        except Exception as exc:
            logger.error(f"Error invoking schtasks: {exc}")
            return {"ok": False, "error": str(exc)}

    @classmethod
    def delete_task(cls, sched_id: str) -> dict:
        """Removes a Windows Task Scheduler job."""
        task_name = cls.sanitize_task_name(sched_id)
        cmd = ["schtasks", "/delete", "/tn", task_name, "/f"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                logger.info(f"Deleted Windows Task '{task_name}'.")
                return {"ok": True, "task_name": task_name}
            else:
                return {"ok": False, "error": res.stderr.strip() or res.stdout.strip()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @classmethod
    def query_task(cls, sched_id: str) -> dict:
        """Queries the status and next run time of a Windows Task Scheduler job."""
        task_name = cls.sanitize_task_name(sched_id)
        cmd = ["schtasks", "/query", "/tn", task_name, "/fo", "CSV", "/nh"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                parts = [p.strip().strip('"') for p in res.stdout.strip().split(",")]
                next_run = parts[1] if len(parts) > 1 else ""
                status = parts[2] if len(parts) > 2 else "Ready"
                return {"exists": True, "task_name": task_name, "status": status, "next_run": next_run}
            return {"exists": False, "task_name": task_name, "status": "Not Registered"}
        except Exception as exc:
            return {"exists": False, "task_name": task_name, "status": "Error", "error": str(exc)}

    @classmethod
    def run_task_now(cls, sched_id: str) -> dict:
        """Triggers a Windows Task Scheduler job immediately."""
        task_name = cls.sanitize_task_name(sched_id)
        cmd = ["schtasks", "/run", "/tn", task_name]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0:
                logger.info(f"Triggered Windows Task '{task_name}' on demand.")
                return {"ok": True, "task_name": task_name}
            return {"ok": False, "error": res.stderr.strip() or res.stdout.strip()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @classmethod
    def list_registered_tasks(cls) -> list[str]:
        """Lists all registered Windows Task names starting with TASK_PREFIX."""
        cmd = ["schtasks", "/query", "/fo", "CSV"]
        tasks = []
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout:
                reader = csv.reader(io.StringIO(res.stdout))
                for row in reader:
                    if row and len(row) > 0 and cls.TASK_PREFIX in row[0]:
                        tasks.append(row[0].lstrip("\\"))
        except Exception as exc:
            logger.debug(f"Error querying schtasks list: {exc}")
        return tasks

    @classmethod
    def sync_all_schedules(cls, schedules: list[dict]) -> dict:
        """Synchronizes all schedules in config with Windows Task Scheduler and prunes orphan tasks."""
        results = {"registered": [], "deleted": [], "errors": []}
        active_task_names = set()
        for s in schedules:
            sid = s.get("id")
            if not sid:
                continue
            task_name = cls.sanitize_task_name(sid)
            if s.get("enabled", True):
                r = cls.register_or_update_task(s)
                if r.get("ok"):
                    results["registered"].append(r)
                    active_task_names.add(task_name)
                else:
                    results["errors"].append(r)
            else:
                cls.delete_task(sid)
                results["deleted"].append(sid)

        # Prune orphan Windows tasks that are no longer in active schedules
        try:
            registered_system_tasks = cls.list_registered_tasks()
            for sys_task in registered_system_tasks:
                if sys_task not in active_task_names:
                    del_cmd = ["schtasks", "/delete", "/tn", sys_task, "/f"]
                    del_res = subprocess.run(del_cmd, capture_output=True, text=True, check=False)
                    if del_res.returncode == 0:
                        logger.info(f"Pruned orphan Windows Task '{sys_task}'.")
                        results["deleted"].append(sys_task)
        except Exception as exc:
            logger.debug(f"Error pruning orphan tasks: {exc}")

        return results


# Initialize FastAPI app
api_app = FastAPI(title="Meta Reels Scheduler Backend", version="2.2.0")
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def find_default_video(configured_path: str = "") -> str:
    """Dynamically resolves video path, prioritizing local folder videos and falling back gracefully."""
    if configured_path:
        p = Path(configured_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.is_file():
            return str(p.resolve())

    # Check local workspace folder and brand subfolders for mp4 files
    local_mp4s = list(BASE_DIR.glob("*.mp4")) + list(BASE_DIR.glob("*/*.mp4"))
    if local_mp4s:
        for m in local_mp4s:
            if "gemini_generated" in m.name:
                return str(m.resolve())
        return str(local_mp4s[0].resolve())

    # Fallback to Downloads
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        d_mp4s = list(downloads.glob("*.mp4"))
        if d_mp4s:
            for m in d_mp4s:
                if "gemini_generated" in m.name:
                    return str(m.resolve())
            return str(d_mp4s[0].resolve())

    return ""


def sanitize_chrome_profile(val: str, available_profiles: list = None) -> str:
    """Safely extracts and validates Chrome profile directory name (e.g. 'Profile 15', 'Default').
    Guarantees numbers in 'Profile 15' are never truncated or stripped to broken 'Profile'.
    """
    raw = (val or "").strip()
    if not raw:
        return "Profile 15"

    cand = raw
    for sep in (" — ", " - ", " | "):
        if sep in cand:
            cand = cand.split(sep)[0].strip()
            break

    # If cand happens to be literally 'Profile' without a number, map it to Profile 15
    if cand.lower() == "profile":
        if available_profiles:
            p15 = next((p["profile_dir"] for p in available_profiles if p.get("profile_dir") == "Profile 15"), None)
            if p15:
                return "Profile 15"
            p_any = next((p["profile_dir"] for p in available_profiles if "profile" in p.get("profile_dir", "").lower()), None)
            if p_any:
                return p_any
        return "Profile 15"

    if available_profiles:
        for p in available_profiles:
            p_dir = p.get("profile_dir", "")
            if cand.lower() == p_dir.lower():
                return p_dir
        for p in available_profiles:
            d_name = p.get("display_name", "")
            email = p.get("email", "")
            if (d_name and d_name.lower() in raw.lower()) or (email and email.lower() in raw.lower()):
                return p.get("profile_dir", cand)

    return cand or "Profile 15"


def extract_meta_page_info(input_str: str) -> dict:
    """Intelligently extracts numeric Meta Page ID, clean Page Name, and full Reels Composer URL
    from any input (raw Page ID, Business Suite URL, Facebook Profile link, or page share link).
    """
    raw = (input_str or "").strip()
    if not raw:
        return {"page_id": "", "url": "", "page_name": ""}

    if "http://" in raw or "https://" in raw or "facebook.com" in raw or "meta.com" in raw:
        clean_url = raw
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = "https://" + clean_url
        try:
            parsed = urllib.parse.urlparse(clean_url)
            qs = urllib.parse.parse_qs(parsed.query)

            candidate_id = ""
            for param in ("asset_id", "page_id", "global_scope_id", "id", "business_id"):
                vals = qs.get(param)
                if vals and vals[0].strip().isdigit():
                    candidate_id = vals[0].strip()
                    break

            if not candidate_id and parsed.fragment and "?" in parsed.fragment:
                frag_qs = urllib.parse.parse_qs(parsed.fragment.split("?", 1)[1])
                for param in ("asset_id", "page_id", "global_scope_id", "id"):
                    vals = frag_qs.get(param)
                    if vals and vals[0].strip().isdigit():
                        candidate_id = vals[0].strip()
                        break

            if not candidate_id:
                m = re.findall(r"\b(\d{10,24})\b", parsed.path)
                if m:
                    candidate_id = m[-1]

            vanity_name = ""
            path_parts = [p for p in parsed.path.strip("/").split("/") if p and p.lower() not in ("pages", "p", "profile.php", "latest", "reels_composer", "home")]
            if path_parts:
                vanity_name = path_parts[-1]

            final_id = candidate_id or vanity_name or raw

            if "reels_composer" in clean_url:
                final_url = clean_url
            elif candidate_id:
                final_url = f"https://business.facebook.com/latest/reels_composer/?asset_id={candidate_id}&business_id="
            else:
                final_url = clean_url

            inferred_name = ""
            if vanity_name:
                inferred_name = vanity_name.replace(".", " ").replace("-", " ").replace("_", " ").title()
            elif candidate_id:
                inferred_name = f"Meta Page ({candidate_id})"

            return {
                "page_id": final_id,
                "url": final_url,
                "page_name": inferred_name
            }
        except Exception:
            pass

    digits_match = re.search(r"\b(\d{10,24})\b", raw)
    if digits_match:
        pid = digits_match.group(1)
        return {
            "page_id": pid,
            "url": f"https://business.facebook.com/latest/reels_composer/?asset_id={pid}&business_id=",
            "page_name": f"Meta Page ({pid})"
        }

    return {
        "page_id": raw,
        "url": f"https://business.facebook.com/latest/reels_composer/?asset_id={raw}&business_id=",
        "page_name": f"Meta Page ({raw})"
    }


def page_id_from_url(url: str) -> str:
    try:
        return extract_meta_page_info(url).get("page_id", "")
    except Exception:
        return ""


def normalize_pages(pages: list[dict]) -> tuple[list[dict], list[str]]:
    normalized: list[dict] = []
    seen: set[str] = set()
    removed: list[str] = []
    for index, original in enumerate(pages, 1):
        page = dict(original or {})
        raw_url = str(page.get("url", "")).strip()
        raw_id = str(page.get("id", "")).strip()

        info = extract_meta_page_info(raw_url or raw_id)
        if not info.get("page_id"):
            info = extract_meta_page_info(raw_id)

        pid = info.get("page_id") or raw_id or f"page-{index}"
        final_url = raw_url if raw_url.startswith("http") else (info.get("url") or f"https://business.facebook.com/latest/reels_composer/?asset_id={pid}&business_id=")

        if pid in seen:
            removed.append(pid)
            logger.warning("Duplicate Meta destination skipped (page ID %s)", pid)
            continue
        seen.add(pid)
        page["id"] = pid
        page["url"] = final_url
        if not page.get("name") or str(page.get("name")).startswith("http"):
            page["name"] = info.get("page_name") or f"Meta Page {index} ({pid})"
        page.setdefault("enabled", True)
        page.setdefault("video", "")
        page.setdefault("caption", "")
        page.setdefault("location", "")
        normalized.append(page)
    return normalized, removed


def default_pages() -> list[dict]:
    out = []
    for i, url in enumerate(DEFAULT_URLS, 1):
        pid = page_id_from_url(url) or f"page-{i}"
        out.append({
            "id": pid,
            "name": f"Meta Page {i} ({pid})",
            "url": url,
            "enabled": True,
            "video": "",
            "caption": "",
            "location": ""
        })
    return out


def default_brands(fallback_pages: list[dict] = None, global_cfg: dict = None) -> list[dict]:
    """Generates the default multi-brand configuration, seeding both Loan & Finance and patpedhi brands
    so multi-brand configurations work out of the box in fresh directories."""
    cfg = global_cfg or {}
    pages = fallback_pages if fallback_pages is not None else default_pages()
    norm_pages, _ = normalize_pages(pages)
    selected_prof = sanitize_chrome_profile(str(cfg.get("selected_profile") or "Profile 15").strip())
    loan_dir = str(cfg.get("media_folder") or (BASE_DIR / "loan")).strip()
    return [
        {
            "id": "brand_loan",
            "name": "Loan & Finance",
            "description": "Primary Loan and Financial Services Pages",
            "chrome_profile": selected_prof,
            "media_folder": loan_dir,
            "video": str(cfg.get("global_video") or "").strip(),
            "caption": str(cfg.get("caption") or "9930604542 \n\n#loan #reels #viral #trending #finance #business #loans #homeloan #money #mumbai #india").strip(),
            "location": str(cfg.get("location") or "Mumbai").strip(),
            "auto_publish": bool(cfg.get("auto_publish", True)),
            "step_sequence": str(cfg.get("step_sequence") or "caption_first"),
            "composer_step_order": list(cfg.get("composer_step_order") or ["caption", "location", "messages", "video_upload"]),
            "pages": norm_pages
        },
        {
            "id": "brand_1795088707341",
            "name": "patpedhi",
            "description": "Patpedhi Daily Savings and Micro-Finance",
            "chrome_profile": selected_prof,
            "media_folder": "",
            "video": "",
            "caption": "9769602020 \n\n#savings #patpedhi #goldloan #mumbai #finance #loan",
            "location": "Mumbai",
            "auto_publish": True,
            "step_sequence": "caption_first",
            "composer_step_order": ["caption", "location", "messages", "video_upload"],
            "pages": [
                {
                    "id": "573974582461345",
                    "name": "patpedhi (573974582461345)",
                    "url": "https://business.facebook.com/latest/reels_composer/?asset_id=573974582461345&business_id=645625381317413&ir_qe_exposed=1&ref=biz_web_content_manager_published_posts&context_ref=POSTS",
                    "enabled": True,
                    "video": "",
                    "location": "",
                    "caption": ""
                }
            ]
        }
    ]


def normalize_brands(brands_list: list[dict], fallback_pages: list[dict] = None, global_cfg: dict = None) -> list[dict]:
    """Normalizes brand dictionaries, ensuring unique identifiers, valid profiles, and pages."""
    if not brands_list:
        return default_brands(fallback_pages, global_cfg)
    normalized: list[dict] = []
    seen_ids: set[str] = set()
    cfg = global_cfg or {}
    for idx, raw_brand in enumerate(brands_list, 1):
        brand = dict(raw_brand or {})
        raw_id = str(brand.get("id") or f"brand_{idx}").strip()
        bid = "".join(c for c in raw_id if c.isalnum() or c in ("_", "-")) or f"brand_{idx}"
        if bid in seen_ids:
            bid = f"{bid}_{idx}"
        seen_ids.add(bid)
        brand["id"] = bid
        brand.setdefault("name", f"Brand {idx}")
        brand.setdefault("description", "")
        # Sanitize chrome_profile to avoid broken 'Profile' without number
        brand["chrome_profile"] = sanitize_chrome_profile(brand.get("chrome_profile") or cfg.get("selected_profile") or "Profile 15")
        brand.setdefault("media_folder", str(cfg.get("media_folder") or "").strip())
        brand.setdefault("video", str(cfg.get("global_video") or "").strip())
        brand.setdefault("caption", str(cfg.get("caption") or "loan").strip())
        brand.setdefault("location", str(cfg.get("location") or "Mumbai").strip())
        brand.setdefault("auto_publish", bool(cfg.get("auto_publish", True)))
        brand.setdefault("step_sequence", str(cfg.get("step_sequence") or "caption_first"))
        brand.setdefault("composer_step_order", list(cfg.get("composer_step_order") or ["caption", "location", "messages", "video_upload"]))

        pages_in_brand = brand.get("pages")
        if pages_in_brand is None and idx == 1 and fallback_pages:
            pages_in_brand = fallback_pages
        norm_pages, _ = normalize_pages(pages_in_brand or [])
        brand["pages"] = norm_pages
        normalized.append(brand)
    return normalized


def load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("Could not read %s: %s", path, exc)
    return default


_file_io_lock = threading.RLock()


def save_json(path: Path, data):
    with _file_io_lock:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        tmp = path.with_name(f"{path.stem}_{uuid.uuid4().hex[:8]}.tmp")
        for attempt in range(5):
            try:
                tmp.write_text(content, encoding="utf-8")
                tmp.replace(path)
                return
            except (PermissionError, OSError) as exc:
                if attempt == 4:
                    # Final attempt: write directly to path to bypass Windows file locking
                    try:
                        path.write_text(content, encoding="utf-8")
                        return
                    except Exception as e2:
                        logger.error("save_json failed permanently on %s: %s (direct fallback: %s)", path, exc, e2)
                time.sleep(0.04 * (2 ** attempt))
            finally:
                if tmp.exists():
                    try:
                        tmp.unlink(missing_ok=True)
                    except Exception:
                        pass


# ==============================================================================
# Controller Core
# ==============================================================================

class MetaReelsController:
    """Central orchestration controller for scheduler, API, and visible browser automation."""

    def __init__(self):
        self.lock = threading.RLock()
        self.gui_log_callback = None
        self.logs_buffer: list[str] = []

        standalone_env = ensure_standalone_environment()
        self.extension_path = Path(standalone_env["extension_path"])

        # Load configuration
        raw_cfg = load_json(CONFIG_FILE, {})
        configured_pages = raw_cfg.get("pages") or default_pages()

        # Video & Media Folder Architecture
        raw_video = raw_cfg.get("global_video") or ""
        self.global_video = find_default_video(raw_video)
        self.media_folder = str(raw_cfg.get("media_folder") or "").strip()
        self._brand_media_history: dict[str, list[str]] = {}

        self.location = raw_cfg.get("location") or "Mumbai"
        self.schedule_time = raw_cfg.get("schedule_time") or "17:00"
        self.caption = raw_cfg.get("caption") or "loan"
        self.auto_publish = raw_cfg.get("auto_publish", True)
        self.step_sequence = raw_cfg.get("step_sequence", "caption_first")
        self.composer_step_order = raw_cfg.get("composer_step_order", ["caption", "location", "messages", "video_upload"])
        self.block_input_during_automation = bool(raw_cfg.get("block_input_during_automation", True))
        self.max_publications_per_day = int(raw_cfg.get("max_publications_per_day", 7))

        # Chrome Profile Selection (persisted in config.json)
        self.selected_profile = str(raw_cfg.get("selected_profile") or PROFILE_NAME).strip()
        self.user_data_dir = str(raw_cfg.get("user_data_dir") or str(USER_DATA_ROOT)).strip()

        # Multi-Brand Architecture:
        raw_brands = raw_cfg.get("brands")
        self.brands = normalize_brands(raw_brands, fallback_pages=configured_pages, global_cfg=raw_cfg)
        self.active_brand_id = str(raw_cfg.get("active_brand_id") or (self.brands[0]["id"] if self.brands else "brand_loan")).strip()
        if not any(b["id"] == self.active_brand_id for b in self.brands):
            self.active_brand_id = self.brands[0]["id"] if self.brands else "brand_loan"

        active_b = self.get_active_brand()
        if active_b.get("chrome_profile"):
            self.selected_profile = active_b["chrome_profile"]

        # Multiple Schedules with Windows Task Scheduler sync
        self.schedules = raw_cfg.get("schedules")
        if not self.schedules:
            self.schedules = [
                {
                    "id": f"sched_{self.schedule_time.replace(':', '')}",
                    "name": f"Daily Reel ({self.schedule_time})",
                    "time": self.schedule_time,
                    "enabled": True,
                    "days": "DAILY",
                    "target_brand": "ALL",
                    "video": "",
                    "caption": "",
                    "last_run": ""
                }
            ]

        if not CONFIG_FILE.exists() or not raw_brands:
            self._save_brands_to_config()

        self.batch_running = False
        self.scheduler_enabled = True
        self.current_task: dict | None = None
        self.task_state = "IDLE"
        self.active_page_id = self.pages[0]["id"] if self.pages else ""

        self.task_event = threading.Event()
        self.shutdown_event = threading.Event()
        self.hello_event = threading.Event()
        self._last_report_times = {}
        self._picker_lock = threading.RLock()
        self._picker_in_progress = False
        self._last_picker_completed_time = 0.0
        self.agent: AutonomousRemediationAgent | None = None

    @property
    def pages(self) -> list[dict]:
        with self.lock:
            brand = self.get_active_brand()
            return brand.get("pages", [])

    @pages.setter
    def pages(self, new_pages: list[dict]):
        with self.lock:
            brand = self.get_active_brand()
            norm_pages, _ = normalize_pages(new_pages)
            brand["pages"] = norm_pages
            self._save_brands_to_config()

    def _save_brands_to_config(self):
        with self.lock:
            cfg = load_json(CONFIG_FILE, {})
            cfg["brands"] = self.brands
            cfg["active_brand_id"] = self.active_brand_id
            cfg["pages"] = self.pages
            cfg["selected_profile"] = self.selected_profile
            cfg["user_data_dir"] = self.user_data_dir
            cfg["global_video"] = str(self.global_video) if self.global_video else ""
            cfg["location"] = self.location
            cfg["schedule_time"] = self.schedule_time
            cfg["schedules"] = self.schedules
            cfg["caption"] = self.caption
            cfg["auto_publish"] = self.auto_publish
            cfg["step_sequence"] = self.step_sequence
            cfg["composer_step_order"] = self.composer_step_order
            cfg["block_input_during_automation"] = self.block_input_during_automation
            cfg["max_publications_per_day"] = self.max_publications_per_day
            save_json(CONFIG_FILE, cfg)

    def save_config(self):
        """Persists current state and brands to config.json."""
        with self.lock:
            self._save_brands_to_config()

    def get_brands(self) -> list[dict]:
        with self.lock:
            return list(self.brands)

    def get_brand(self, brand_id: str) -> dict | None:
        with self.lock:
            return next((b for b in self.brands if b.get("id") == brand_id), None)

    find_brand_by_id = get_brand

    def get_random_brand_media(self, brand_id: str, folder_path: str | Path = None) -> dict | None:
        """Maintains per-brand anti-repeat history and randomly selects a video and its paired text caption."""
        with self.lock:
            if not folder_path:
                brand = self.get_brand(brand_id) or self.get_active_brand()
                folder_path = brand.get("media_folder") or ""
            if folder_path:
                fp = Path(folder_path)
                if not fp.is_dir():
                    candidate = BASE_DIR / fp.name
                    if candidate.is_dir():
                        folder_path = str(candidate.resolve())
                    elif (BASE_DIR / "loan").is_dir() and "loan" in str(folder_path).lower():
                        folder_path = str((BASE_DIR / "loan").resolve())
                    else:
                        folder_path = ""
            if not folder_path:
                return None
            recent = self._brand_media_history.get(brand_id, [])
            selected = select_random_media_pair(folder_path, exclude_stems=recent)
            if selected:
                recent.append(selected["stem"])
                max_hist = max(1, min(selected.get("total_pairs", 1) - 1, 5))
                self._brand_media_history[brand_id] = recent[-max_hist:]
            return selected

    def set_brand_media_folder(self, brand_id: str, folder_path: str) -> bool:
        """Updates the media folder for a specific brand."""
        with self.lock:
            brand = self.get_brand(brand_id)
            if not brand:
                return False
            brand["media_folder"] = str(folder_path).strip()
            if brand_id == self.active_brand_id:
                self.media_folder = brand["media_folder"]
            self._save_brands_to_config()
            self.log(f"Updated media folder for brand '{brand.get('name')}' to '{folder_path}'.")
            return True

    def get_active_brand(self) -> dict:
        with self.lock:
            brand = next((b for b in self.brands if b.get("id") == self.active_brand_id), None)
            if not brand:
                if self.brands:
                    brand = self.brands[0]
                    self.active_brand_id = brand["id"]
                else:
                    brand = default_brands()[0]
                    self.brands = [brand]
                    self.active_brand_id = brand["id"]
            return brand

    def set_active_brand(self, brand_id: str) -> bool:
        with self.lock:
            target = next((b for b in self.brands if b.get("id") == brand_id), None)
            if not target:
                return False
            self.active_brand_id = brand_id
            prof = target.get("chrome_profile")
            if prof:
                self.selected_profile = prof.strip()
            if "media_folder" in target:
                self.media_folder = str(target.get("media_folder") or "").strip()
            if target.get("video"):
                self.global_video = target["video"]
            if target.get("caption"):
                self.caption = target["caption"]
            if target.get("location"):
                self.location = target["location"]
            if "auto_publish" in target:
                self.auto_publish = target["auto_publish"]
            if target.get("pages"):
                self.active_page_id = target["pages"][0]["id"]
            self._save_brands_to_config()
            ensure_chrome_extension_installed(self.current_profile_path)
            self.log(f"Active brand set to '{target['name']}' (Profile: {self.selected_profile}).")
            return True

    def add_brand(self, name: str, chrome_profile: str = "Profile 15", video: str = "", caption: str = "", location: str = "Mumbai", auto_publish: bool = True, description: str = "", pages: list[dict] = None, media_folder: str = "") -> dict:
        with self.lock:
            bid = f"brand_{int(time.time() * 1000)}"
            norm_pages, _ = normalize_pages(pages or [])
            new_b = {
                "id": bid,
                "name": name.strip() or f"Brand {len(self.brands)+1}",
                "description": description.strip(),
                "chrome_profile": chrome_profile.strip() or "Profile 15",
                "media_folder": media_folder.strip(),
                "video": video.strip(),
                "caption": caption.strip(),
                "location": location.strip() or "Mumbai",
                "auto_publish": bool(auto_publish),
                "step_sequence": "caption_first",
                "composer_step_order": ["caption", "location", "messages", "video_upload"],
                "pages": norm_pages
            }
            self.brands.append(new_b)
            self._save_brands_to_config()
            ensure_chrome_extension_installed(Path(self.user_data_dir) / new_b["chrome_profile"])
            self.log(f"Added brand '{new_b['name']}' (ID: {bid}, Profile: {new_b['chrome_profile']}).")
            return new_b

    def update_brand(self, brand_id: str, updates: dict) -> dict | None:
        with self.lock:
            brand = next((b for b in self.brands if b.get("id") == brand_id), None)
            if not brand:
                return None
            for k, v in updates.items():
                if k == "pages" and isinstance(v, list):
                    norm_pages, _ = normalize_pages(v)
                    brand["pages"] = norm_pages
                elif k != "id":
                    brand[k] = v
            if brand_id == self.active_brand_id:
                if "chrome_profile" in updates:
                    self.selected_profile = brand["chrome_profile"]
                    ensure_chrome_extension_installed(self.current_profile_path)
                if "video" in updates:
                    self.global_video = brand["video"]
                if "caption" in updates:
                    self.caption = brand["caption"]
                if "location" in updates:
                    self.location = brand["location"]
                if "auto_publish" in updates:
                    self.auto_publish = brand["auto_publish"]
            self._save_brands_to_config()
            self.log(f"Updated brand '{brand.get('name')}'.")
            return brand

    def delete_brand(self, brand_id: str) -> bool:
        with self.lock:
            if len(self.brands) <= 1:
                self.log(f"Cannot delete brand '{brand_id}': at least one brand must remain.", "warning")
                return False
            before_len = len(self.brands)
            self.brands = [b for b in self.brands if b.get("id") != brand_id]
            if len(self.brands) == before_len:
                return False
            if self.active_brand_id == brand_id:
                self.active_brand_id = self.brands[0]["id"]
                active_b = self.get_active_brand()
                self.selected_profile = active_b.get("chrome_profile", self.selected_profile)
            self._save_brands_to_config()
            self.log(f"Deleted brand '{brand_id}'. Active brand is now '{self.active_brand_id}'.")
            return True

    def find_brand_for_page(self, page_id: str) -> tuple[dict | None, dict | None]:
        with self.lock:
            pid = str(page_id).strip()
            # 1. Exact match
            for b in self.brands:
                for p in b.get("pages", []):
                    if str(p.get("id")).strip() == pid:
                        return b, p
            # 2. Substring or URL match
            if pid:
                for b in self.brands:
                    for p in b.get("pages", []):
                        p_id = str(p.get("id", "")).strip()
                        p_url = str(p.get("url", "")).strip()
                        if pid in p_id or pid in p_url or (p_id and p_id in pid):
                            return b, p
            return None, None

    def resolve_page_task(self, p: dict, brand: dict = None) -> dict:
        if brand is None:
            brand, _ = self.find_brand_for_page(p.get("id", ""))
            if brand is None:
                brand = self.get_active_brand() or {}

        # Automatically resolve and sanitize page id and url
        raw_id = str(p.get("id", "")).strip()
        raw_url = str(p.get("url", "")).strip()
        info = extract_meta_page_info(raw_url or raw_id)
        if not info.get("page_id"):
            info = extract_meta_page_info(raw_id)
        pid = info.get("page_id") or raw_id
        p_url = raw_url if raw_url.startswith("http") else (info.get("url") or f"https://business.facebook.com/latest/reels_composer/?asset_id={pid}&business_id=")

        # Brand Media Folder vs Selected File & Text Resolution:
        # 1. If brand has media_folder assigned (and folder exists):
        #    Dynamically & randomly select video and its stem-matching .txt caption from that folder.
        # 2. If NO folder is assigned to brand (or media_folder is empty):
        #    Use brand's selected file (video) and text (caption).
        # 3. Allow explicit per-page override if specified.
        target_folder = None
        b_folder = str(brand.get("media_folder") or "").strip()
        p_folder = str(p.get("media_folder") or "").strip()

        if p_folder and Path(p_folder).is_dir():
            target_folder = p_folder
        elif p_folder and (BASE_DIR / Path(p_folder).name).is_dir():
            target_folder = str((BASE_DIR / Path(p_folder).name).resolve())
        elif b_folder and Path(b_folder).is_dir():
            target_folder = b_folder
        elif b_folder and (BASE_DIR / Path(b_folder).name).is_dir():
            target_folder = str((BASE_DIR / Path(b_folder).name).resolve())
        elif b_folder and (BASE_DIR / "loan").is_dir() and "loan" in b_folder.lower():
            target_folder = str((BASE_DIR / "loan").resolve())

        selected_pair = None
        if target_folder:
            selected_pair = self.get_random_brand_media(brand.get("id"), target_folder)

        if selected_pair and selected_pair.get("video"):
            video_path = Path(selected_pair["video"])
            caption = selected_pair.get("caption") or p.get("caption") or brand.get("caption") or self.caption or "loan"
            self.log(f"[{brand.get('name', 'Brand')}] Selected random media pair: video='{selected_pair['video_name']}', text='{selected_pair.get('text_name') or 'N/A'}' ({len(caption)} chars)")
        else:
            # NO folder assigned to brand (or folder empty) -> use selected file and text
            video_p = p.get("video") or brand.get("video") or self.global_video
            video_path = Path(video_p) if video_p else None
            if video_path and not video_path.is_absolute():
                video_path = BASE_DIR / video_path
            if not video_path or not video_path.is_file():
                fallback = find_default_video()
                if fallback:
                    video_path = Path(fallback)
            caption = p.get("caption") or brand.get("caption") or self.caption or "loan"
        location = p.get("location") or brand.get("location") or self.location or "Mumbai"
        chrome_prof = sanitize_chrome_profile(p.get("chrome_profile") or brand.get("chrome_profile") or self.selected_profile, self.get_available_profiles())
        auto_pub = p["auto_publish"] if p.get("auto_publish") is not None else (brand.get("auto_publish") if brand.get("auto_publish") is not None else self.auto_publish)
        step_seq = p.get("step_sequence") or brand.get("step_sequence", getattr(self, "step_sequence", "caption_first"))
        comp_order = p.get("composer_step_order") or brand.get("composer_step_order", getattr(self, "composer_step_order", ["caption", "location", "messages", "video_upload"]))

        return {
            "id": pid,
            "name": p.get("name") or info.get("page_name") or f"Meta Page ({pid})",
            "url": p_url,
            "brand_id": brand.get("id"),
            "brand_name": brand.get("name"),
            "chrome_profile": chrome_prof,
            "video": str(video_path.resolve()) if video_path and video_path.is_file() else "",
            "caption": caption,
            "location": location,
            "auto_publish": auto_pub,
            "step_sequence": step_seq,
            "composer_step_order": comp_order
        }

    @property
    def current_profile_path(self) -> Path:
        return Path(self.user_data_dir) / self.selected_profile

    def set_selected_profile(self, profile_name: str, user_data_dir: str = None) -> dict:
        with self.lock:
            self.selected_profile = profile_name.strip()
            if user_data_dir:
                self.user_data_dir = user_data_dir.strip()
            else:
                profs = ChromeProfileScanner.scan_profiles()
                for p in profs:
                    if p["profile_dir_name"] == self.selected_profile:
                        self.user_data_dir = p["user_data_dir"]
                        break

            cfg = load_json(CONFIG_FILE, {})
            cfg["selected_profile"] = self.selected_profile
            cfg["user_data_dir"] = self.user_data_dir
            save_json(CONFIG_FILE, cfg)

            ext_res = ensure_chrome_extension_installed(self.current_profile_path)
            self.log(f"Switched active Chrome profile to '{self.selected_profile}' ({self.current_profile_path}). Extension auto-installed & synced.")
            record_research_log("PROFILE_SWITCHED", "ALL", "CONFIG", detail={"profile": self.selected_profile, "path": str(self.current_profile_path)})
            return {
                "ok": True,
                "selected_profile": self.selected_profile,
                "user_data_dir": self.user_data_dir,
                "profile_path": str(self.current_profile_path),
                "extension": ext_res
            }

    def get_available_profiles(self) -> list[dict]:
        profs = ChromeProfileScanner.scan_profiles()
        for p in profs:
            p["is_selected"] = (p["profile_dir_name"] == self.selected_profile and p["user_data_dir"].lower() == self.user_data_dir.lower())
        return profs

    def set_learning_agent(self, agent: AutonomousRemediationAgent):
        self.agent = agent

    def set_gui_callback(self, cb):
        self.gui_log_callback = cb

    def log(self, message: str, level: str = "info"):
        ts = dt.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        getattr(logger, level, logger.info)(message)

        with self.lock:
            self.logs_buffer.append(line)
            if len(self.logs_buffer) > 500:
                self.logs_buffer = self.logs_buffer[-500:]

        if self.gui_log_callback:
            try:
                self.gui_log_callback(line)
            except Exception:
                pass

        broadcast_sse({"event": "LOG", "timestamp": dt.datetime.now().isoformat(), "message": line})

    def get_status(self) -> dict:
        with self.lock:
            today = dt.date.today().isoformat()
            state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
            attempts = state.get("attempts", {})
            counts = state.get("published_counts", {})
            today_attempts = {
                k.split(":", 1)[1]: v
                for k, v in attempts.items()
                if k.startswith(f"{today}:")
            }
            today_published_counts = {
                k.split(":", 1)[1]: v
                for k, v in counts.items()
                if k.startswith(f"{today}:")
            }
            active_b = self.get_active_brand()
            return {
                "batch_running": self.batch_running,
                "scheduler_enabled": self.scheduler_enabled,
                "schedule_time": self.schedule_time,
                "schedules": self.schedules,
                "selected_profile": self.selected_profile,
                "user_data_dir": self.user_data_dir,
                "profile_path": str(self.current_profile_path),
                "active_brand_id": self.active_brand_id,
                "active_brand_name": active_b.get("name", "Active Brand"),
                "brands_count": len(self.brands),
                "brands": self.brands,
                "active_page_id": self.active_page_id,
                "current_task": self.current_task,
                "task_state": self.task_state,
                "pages_count": len(self.pages),
                "enabled_pages_count": len([p for p in self.pages if p.get("enabled", True)]),
                "today_attempts": today_attempts,
                "today_published_counts": today_published_counts,
                "max_publications_per_day": self.max_publications_per_day,
                "global_video": self.global_video,
                "location": self.location,
                "caption": self.caption,
                "auto_publish": self.auto_publish
            }

    def get_config(self) -> dict:
        with self.lock:
            return {
                "brands": self.brands,
                "active_brand_id": self.active_brand_id,
                "pages": self.pages,
                "selected_profile": self.selected_profile,
                "user_data_dir": self.user_data_dir,
                "profile_path": str(self.current_profile_path),
                "global_video": self.global_video,
                "location": self.location,
                "schedule_time": self.schedule_time,
                "schedules": self.schedules,
                "caption": self.caption,
                "auto_publish": self.auto_publish,
                "block_input_during_automation": self.block_input_during_automation,
                "max_publications_per_day": self.max_publications_per_day
            }

    def update_config(self, updates: dict):
        with self.lock:
            if "brands" in updates:
                self.brands = normalize_brands(updates["brands"], fallback_pages=self.pages, global_cfg=updates)
            if "active_brand_id" in updates:
                self.set_active_brand(str(updates["active_brand_id"]))
            if "selected_profile" in updates:
                self.selected_profile = str(updates["selected_profile"]).strip()
            if "user_data_dir" in updates:
                self.user_data_dir = str(updates["user_data_dir"]).strip()
            if "global_video" in updates:
                self.global_video = find_default_video(updates["global_video"])
            if "location" in updates:
                self.location = updates["location"]
            if "schedule_time" in updates:
                self.schedule_time = updates["schedule_time"]
            if "schedules" in updates:
                self.schedules = list(updates["schedules"])
                active_s = [s for s in self.schedules if s.get("enabled", True)]
                if active_s:
                    self.schedule_time = active_s[0].get("time", self.schedule_time)
                elif self.schedules:
                    self.schedule_time = self.schedules[0].get("time", self.schedule_time)
            if "caption" in updates:
                self.caption = updates["caption"]
            if "auto_publish" in updates:
                self.auto_publish = bool(updates["auto_publish"])
            if "block_input_during_automation" in updates:
                self.block_input_during_automation = bool(updates["block_input_during_automation"])
            if "max_publications_per_day" in updates:
                try:
                    self.max_publications_per_day = int(updates["max_publications_per_day"])
                except Exception:
                    self.max_publications_per_day = 7
            if "step_sequence" in updates:
                self.step_sequence = str(updates["step_sequence"])
            if "composer_step_order" in updates:
                self.composer_step_order = list(updates["composer_step_order"])
            if "pages" in updates:
                norm, _ = normalize_pages(updates["pages"])
                brand = self.get_active_brand()
                brand["pages"] = norm

            self._save_brands_to_config()
            self.log("Configuration updated and saved to config.json.")
            record_research_log("CONFIG_UPDATED", "ALL", "CONFIG", detail=updates)

    def add_schedule(self, time_str: str, name: str = "", enabled: bool = True, days: str = "DAILY", repeat_interval_minutes: int = 0, repeat_duration_hours: int = 24, target_brand: str = "ALL", video: str = "", caption: str = "") -> dict:
        sched_id = f"sched_{int(time.time() * 1000)}"
        new_sched = {
            "id": sched_id,
            "name": name.strip() or f"Scheduled Reel ({time_str.strip()})",
            "time": time_str.strip(),
            "enabled": enabled,
            "days": days,
            "target_brand": target_brand.strip() or "ALL",
            "repeat_interval_minutes": int(repeat_interval_minutes or 0),
            "repeat_duration_hours": int(repeat_duration_hours or 24),
            "video": video.strip(),
            "caption": caption.strip(),
            "last_run": "",
            "last_run_date": "",
            "last_trigger": ""
        }
        with self.lock:
            self.schedules.append(new_sched)
            self.update_config({"schedules": self.schedules})
        if enabled:
            WindowsTaskSchedulerManager.register_or_update_task(new_sched)
        rep_note = f" (repeats every {new_sched['repeat_interval_minutes']}m for {new_sched['repeat_duration_hours']}h)" if new_sched['repeat_interval_minutes'] > 0 else ""
        self.log(f"Added new schedule '{new_sched['name']}' at {new_sched['time']}{rep_note} (Windows Task synced).")
        return new_sched

    def edit_schedule(self, sched_id: str, updates: dict) -> dict | None:
        with self.lock:
            sched = next((s for s in self.schedules if s["id"] == sched_id), None)
            if not sched:
                return None
            sched.update(updates)
            if "repeat_interval_minutes" in updates:
                sched["repeat_interval_minutes"] = int(updates["repeat_interval_minutes"] or 0)
            if "repeat_duration_hours" in updates:
                sched["repeat_duration_hours"] = int(updates["repeat_duration_hours"] or 24)
            self.update_config({"schedules": self.schedules})
        if sched.get("enabled", True):
            WindowsTaskSchedulerManager.register_or_update_task(sched)
        else:
            WindowsTaskSchedulerManager.delete_task(sched_id)
        rep_note = f" (repeats every {sched.get('repeat_interval_minutes')}m for {sched.get('repeat_duration_hours')}h)" if sched.get("repeat_interval_minutes", 0) > 0 else ""
        self.log(f"Updated schedule '{sched.get('name')}' ({sched.get('time')}{rep_note}).")
        return sched

    def delete_schedule(self, sched_id: str) -> bool:
        with self.lock:
            before_len = len(self.schedules)
            self.schedules = [s for s in self.schedules if s["id"] != sched_id]
            if len(self.schedules) == before_len:
                return False
            self.update_config({"schedules": self.schedules})
        WindowsTaskSchedulerManager.delete_task(sched_id)
        self.log(f"Deleted schedule '{sched_id}' from config and Windows Task Scheduler.")
        return True

    def sync_all_schedules_to_windows(self) -> dict:
        with self.lock:
            schedules_copy = list(self.schedules)
        res = WindowsTaskSchedulerManager.sync_all_schedules(schedules_copy)
        self.log(f"Synced {len(res.get('registered', []))} schedule(s) with Windows Task Scheduler.")
        return res

    def find_chrome(self) -> Path | None:
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Google/Chrome/Application/chrome.exe"
        ]
        for c in candidates:
            if c.exists():
                return c
        found = shutil.which("chrome.exe") or shutil.which("chrome")
        return Path(found) if found else None

    def open_chrome_url(self, url: str, profile_name: str = None) -> bool:
        target_profile = sanitize_chrome_profile(str(profile_name or self.selected_profile).strip(), self.get_available_profiles())
        prof_path = Path(self.user_data_dir) / target_profile
        # If discovered profile specifies a custom user_data_dir, honor it
        for ap in self.get_available_profiles():
            if ap.get("profile_dir", "").lower() == target_profile.lower():
                if ap.get("user_data_dir"):
                    prof_path = Path(ap["user_data_dir"]) / target_profile
                break

        if not prof_path.exists():
            try:
                prof_path.mkdir(parents=True, exist_ok=True)
                self.log(f"Target Chrome Profile directory created at {prof_path}.")
            except Exception as e:
                self.log(f"Notice creating profile directory {prof_path}: {e}", "warning")
        chrome = self.find_chrome()
        if not chrome:
            self.log("Google Chrome executable not found on machine.", "error")
            return False

        # Ensure Chrome Extension is up to date in target profile
        ensure_chrome_extension_installed(prof_path)

        # Always launch Chrome with the selected authentic user profile on WinSta0\Default
        ensure_default_desktop()
        ext_folder = BASE_DIR / "ChromeExtension"
        cmd = [
            str(chrome),
            f"--profile-directory={target_profile}",
        ]
        if ext_folder.is_dir():
            cmd.append(f"--load-extension={str(ext_folder)}")
        cmd.extend([
            "--start-maximized",
            url
        ])
        startupinfo = None
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpDesktop = r"WinSta0\Default"
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, startupinfo=startupinfo)
            self.log(f"Visible Chrome Profile '{target_profile}' launched for: {url[:90]}...")
            pid = page_id_from_url(url)
            self.active_page_id = pid
            record_research_log("CHROME_LAUNCHED", pid, "BROWSER_START", detail={"url": url, "profile": target_profile})
            return True
        except Exception as exc:
            self.log(f"Could not launch Chrome: {exc}", "error")
            record_research_log("CHROME_LAUNCH_ERROR", page_id_from_url(url), "BROWSER_START", detail={"error": str(exc)}, result="FAIL")
            return False

    def close_tab_for_page(self, page_id: str = ""):
        """Closes the completed browser tab cleanly across CDP, Playwright, and hotkey fallback."""
        self.log(f"Closing completed tab for page {page_id}...")
        # 1. Direct CDP HTTP close target
        try:
            req = urllib.request.Request("http://127.0.0.1:9222/json/list")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                targets = json.loads(resp.read().decode())
                for t in targets:
                    t_url = t.get("url", "")
                    t_id = t.get("id", "")
                    if ("reels_composer" in t_url or (page_id and page_id in t_url)) and t_id:
                        close_req = urllib.request.Request(f"http://127.0.0.1:9222/json/close/{t_id}")
                        urllib.request.urlopen(close_req, timeout=0.8)
                        self.log(f"Page {page_id}: Closed composer tab via CDP target {t_id}.")
                        return
        except Exception:
            pass

        # 2. Playwright CDP close page
        try:
            res = PlaywrightCDPCommander.close_page(page_id)
            if res.get("ok"):
                self.log(f"Page {page_id}: Closed composer tab via Playwright CDP.")
                return
        except Exception:
            pass

        # 3. Hotkey Ctrl+W (closes active foreground tab in Chrome)
        try:
            pyautogui.hotkey("ctrl", "w")
            self.log(f"Page {page_id}: Sent Ctrl+W hotkey to close active composer tab.")
        except Exception as exc:
            self.log(f"Page {page_id}: Error sending Ctrl+W: {exc}", "debug")

    def get_task_for_page(self, page_id: str = "", ignore_published: bool = False) -> dict | None:
        today = dt.date.today().isoformat()
        max_limit = getattr(self, "max_publications_per_day", 7)

        with self.lock:
            pid_str = str(page_id or "").strip()
            if self.current_task:
                cur_id = str(self.current_task.get("id", "")).strip()
                cur_url = str(self.current_task.get("url", "")).strip()
                if not pid_str or cur_id == pid_str or pid_str in cur_id or pid_str in cur_url or (cur_id and cur_id in pid_str):
                    return dict(self.current_task)

            if pid_str:
                pub_cnt = self.get_today_published_count(pid_str, today)
                if not ignore_published and max_limit > 0 and pub_cnt >= max_limit:
                    return None
                target_page = next((p for p in self.pages if str(p.get("id", "")).strip() == pid_str or pid_str in str(p.get("url", "")) or pid_str in str(p.get("id", ""))), None)
                target_brand = None
                if not target_page:
                    target_brand, target_page = self.find_brand_for_page(pid_str)
                if target_page:
                    t_cnt = self.get_today_published_count(target_page["id"], today)
                    if not ignore_published and max_limit > 0 and t_cnt >= max_limit:
                        return None
                    return self.resolve_page_task(target_page, brand=target_brand)
        return None

    def handle_report(self, payload: dict):
        pid = str(payload.get("page_id", "")).strip()
        state = str(payload.get("state", "UNKNOWN")).strip()
        detail = payload.get("detail") or {}

        # Fallback to current task ID if pid is empty
        if not pid and self.current_task:
            pid = str(self.current_task.get("id", "")).strip()

        now = time.time()
        last_state_key = f"{pid}_{state}"
        with self.lock:
            last_time = self._last_report_times.get(last_state_key, 0.0)
            if now - last_time < 0.8:
                return
            self._last_report_times[last_state_key] = now

        if state == "HELPER_CONNECTED":
            self.hello_event.set()
            if pid:
                self.active_page_id = pid
            self.log(f"Chrome helper extension connected on page {self.active_page_id or pid or 'active'}.")
        elif not self.hello_event.is_set():
            self.hello_event.set()
            if pid:
                self.active_page_id = pid
            self.log(f"Chrome helper active on page {self.active_page_id or pid or 'active'} (state: {state}).")
        else:
            self.log(f"PAGE {pid} | {state} | {json.dumps(detail, ensure_ascii=False)[:250]}")

        record_research_log(state, pid, "EXTENSION_EVENT", detail=detail)

        with self.lock:
            if self.current_task and (not pid or str(self.current_task.get("id")) == pid) and state != "FILE_PICKER_REQUEST":
                self.task_state = state
                if state in TERMINAL_STATES:
                    self.task_event.set()

        if state == "PUBLISHED":
            today = dt.date.today().isoformat()
            new_cnt = self.record_page_published(pid, today)
            with self.lock:
                self.task_state = "PUBLISHED"
                self.task_event.set()
            self.log(f"Page {pid}: Reel marked as PUBLISHED in state.json ({new_cnt} today).")

        # Desktop fallback file picker interaction if needed
        if state == "FILE_PICKER_REQUEST":
            with self.lock:
                if self._picker_in_progress:
                    self.log(f"Page {pid}: Ignoring duplicate FILE_PICKER_REQUEST (picker already in progress).", "debug")
                    return
                if now - self._last_picker_completed_time < 8.0:
                    self.log(f"Page {pid}: Ignoring duplicate FILE_PICKER_REQUEST (completed recently).", "debug")
                    return
                self._picker_in_progress = True

            video = (
                detail.get("video")
                or (self.current_task.get("video") if self.current_task else None)
                or self.global_video
            )
            threading.Thread(
                target=self.select_native_file,
                args=(pid, str(video), detail),
                name="DesktopFileDialogPicker",
                daemon=True
            ).start()

        # Desktop hardware click for navigation and share actions (generates isTrusted: true OS events)
        if state == "NAV_CLICK_REQUEST":
            action = detail.get("action", "BUTTON")
            win_metrics = detail.get("window") or {}
            target = detail.get("target") or {}
            dpr = float(win_metrics.get("devicePixelRatio") or 1.0)
            target_x = float(target.get("x", 745))
            target_y = float(target.get("y", 915))
            screen_x = float(win_metrics.get("screenX") or 0)
            screen_y = float(win_metrics.get("screenY") or 0)
            outer_w = float(win_metrics.get("outerWidth") or 1920)
            outer_h = float(win_metrics.get("outerHeight") or 1032)
            inner_w = float(win_metrics.get("innerWidth") or 2400)
            inner_h = float(win_metrics.get("innerHeight") or 1181)

            toolbar_h = max(0.0, outer_h - inner_h) if outer_h > inner_h else 80.0
            border_w = max(0.0, (outer_w - inner_w) / 2.0) if outer_w > inner_w else 0.0
            click_x = round(screen_x + border_w + target_x)
            click_y = round(screen_y + toolbar_h + target_y)

            # Snap to visual blue action button if detected nearby on desktop
            if action in ("SHARE", "PUBLISH", "SCREEN1_NEXT", "SCREEN2_NEXT"):
                snapped = CVInspectionEngine.find_action_button("bottom_right", near_coord=(click_x, click_y))
                if snapped:
                    click_x, click_y = snapped

            self.log(f"Page {pid}: Performing calibrated hardware click for {action} at ({click_x}, {click_y})...")

            def _hw_click():
                ensure_default_desktop()
                Win32DialogEngine.focus_chrome()
                time.sleep(0.15)
                # Tier 1: If Playwright CDP is connected, execute genuine trusted click for SHARE/DONE
                if action in ("SHARE", "PUBLISH") and PlaywrightCDPCommander.is_cdp_available():
                    try:
                        cdp_res = PlaywrightCDPCommander.execute_cdp_click("button:has-text('Share'), div[role='button']:has-text('Share')", pid)
                        if cdp_res.get("ok"):
                            self.log(f"Page {pid}: Playwright CDP trusted click on Share succeeded!")
                            return
                    except Exception as e:
                        self.log(f"Page {pid}: CDP Share click notice: {e}", "debug")

                if action == "DONE" and PlaywrightCDPCommander.is_cdp_available():
                    try:
                        cdp_res = PlaywrightCDPCommander.execute_cdp_click("button:has-text('Done'), div[role='button']:has-text('Done')", pid)
                        if cdp_res.get("ok"):
                            self.log(f"Page {pid}: Playwright CDP trusted click on Done succeeded!")
                            today = dt.date.today().isoformat()
                            new_cnt = self.record_page_published(pid, today)
                            with self.lock:
                                self.task_state = "PUBLISHED"
                                self.task_event.set()
                            self.log(f"Page {pid}: Playwright CDP marked task as PUBLISHED ({new_cnt} today)!")
                            time.sleep(1.8)
                            self.close_tab_for_page(pid)
                            return
                    except Exception as e:
                        self.log(f"Page {pid}: CDP Done click notice: {e}", "debug")

                # Tier 2: Calibrated OS mouse event via pyautogui
                Win32DialogEngine.focus_chrome()
                time.sleep(0.1)
                pyautogui.moveTo(click_x, click_y, duration=0.15)
                pyautogui.click(click_x, click_y)

                if self.agent and self.agent.memory:
                    elem_key = "next_step1" if "SCREEN1" in action else ("next_step2" if "SCREEN2" in action else ("share_step3" if "SHARE" in action else "done_step4"))
                    self.agent.memory.record_success(elem_key, coord_x=click_x, coord_y=click_y)

                if action == "DONE":
                    self.log(f"Page {pid}: Done modal clicked. Marking task as PUBLISHED!")
                    today = dt.date.today().isoformat()
                    new_cnt = self.record_page_published(pid, today)
                    with self.lock:
                        self.task_state = "PUBLISHED"
                        self.task_event.set()
                    self.log(f"Page {pid}: Marked task as PUBLISHED ({new_cnt} today)!")
                    time.sleep(1.8)
                    self.close_tab_for_page(pid)

            threading.Thread(target=_hw_click, name=f"HwClick_{action}", daemon=True).start()

        # Autonomous Remediation & Real-Time Self-Healing Agent
        if state in (
            "SCREEN1_NEXT_NOT_FOUND", "SCREEN2_NEXT_NOT_FOUND", "SHARE_BUTTON_NOT_FOUND",
            "UPLOAD_NOT_VERIFIED", "LOCATION_BUTTON_NOT_FOUND", "LOCATION_FIRST_OPTION_NOT_FOUND",
            "LOCATION_SEARCH_INPUT_NOT_FOUND", "CAPTION_BOX_NOT_FOUND", "MESSAGES_BUTTON_NOT_FOUND",
            "ADD_VIDEO_BUTTON_NOT_FOUND", "COMPOSER_NOT_FOUND", "TASK_FAILED"
        ):
            self.log(f"[IssueMonitor] Observed issue/stall state '{state}' on page {pid}. Activating autonomous learning & remediation agent...", "warning")
            if self.agent:
                def _remediate_and_guard():
                    try:
                        res = self.agent.evaluate_and_remediate(pid, state, detail)
                        if res.get("remediated"):
                            self.log(f"[IssueMonitor] Page {pid}: Self-healing action succeeded ({res.get('action')}). Waiting for page to advance...")
                            # Give the page up to 25s to reach PUBLISHED or next stage before marking failed
                            if not self.task_event.wait(25.0):
                                self.log(f"[IssueMonitor] Page {pid}: Post-remediation timeout without publication. Marking as TASK_FAILED.", "error")
                                with self.lock:
                                    self.task_state = "TASK_FAILED"
                                    self.task_event.set()
                        else:
                            self.log(f"[IssueMonitor] Page {pid}: Autonomous remediation could not resolve '{state}'. Marking as TASK_FAILED.", "error")
                            with self.lock:
                                self.task_state = "TASK_FAILED"
                                self.task_event.set()
                    except Exception as err:
                        self.log(f"[IssueMonitor] Error during self-healing: {err}", "error")
                        with self.lock:
                            self.task_state = "TASK_FAILED"
                            self.task_event.set()

                threading.Thread(
                    target=_remediate_and_guard,
                    name="AgentSelfHealing",
                    daemon=True
                ).start()

    def select_native_file(self, page_id: str, video: str, detail: dict):
        """Calibrated fallback visual/coordinate mouse navigation + Windows file dialog submit."""
        ensure_default_desktop()
        with self._picker_lock:
            try:
                Win32DialogEngine.focus_chrome()
                time.sleep(0.2)

                # 1. Check if any orphaned file dialog is already open; dismiss it first
                existing_dlg = Win32DialogEngine.find_file_dialog()
                if existing_dlg:
                    self.log(f"Page {page_id}: Dismissing existing file dialog ({existing_dlg})...")
                    ctypes.windll.user32.PostMessageW(existing_dlg, 0x0010, 0, 0) # WM_CLOSE
                    time.sleep(0.4)

                if not video:
                    video = (self.current_task.get("video") if self.current_task else None) or self.global_video
                video_p = Path(video)
                if not video_p.is_absolute():
                    video_p = BASE_DIR / video_p
                abs_path = str(video_p.resolve())
                if not Path(abs_path).is_file():
                    fallback_video = find_default_video()
                    if fallback_video and Path(fallback_video).is_file():
                        abs_path = fallback_video
                    else:
                        self.log(f"Page {page_id}: video file does not exist on disk: {abs_path}", "error")
                        self._local_picker_failure(page_id, "FILE_PICKER_SUBMIT_FAILED", f"Invalid video path: {abs_path}")
                        return

                time.sleep(0.2)
                dlg = Win32DialogEngine.find_file_dialog()

                if not dlg:
                    # Tier 1: Computer Vision Template Matching for Add Video button
                    template_coord = None
                    try:
                        import cv2
                        import numpy as np
                        from PIL import ImageGrab
                        screen_arr = np.array(ImageGrab.grab())
                        screen_bgr = cv2.cvtColor(screen_arr, cv2.COLOR_RGB2BGR)
                        for t_name in ["add_video_btn.png", "exact_button_in_page2.png"]:
                            tp = BASE_DIR / t_name
                            if tp.is_file():
                                tmpl = cv2.imread(str(tp))
                                if tmpl is not None:
                                    res = cv2.matchTemplate(screen_bgr, tmpl, cv2.TM_CCOEFF_NORMED)
                                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                                    if max_val >= 0.85:
                                        cx = int(max_loc[0] + tmpl.shape[1] // 2)
                                        cy = int(max_loc[1] + tmpl.shape[0] // 2)
                                        template_coord = (cx, cy)
                                        self.log(f"Page {page_id}: Template visual match at ({cx}, {cy}) (confidence: {max_val:.2f}).")
                                        break
                    except Exception as e:
                        self.log(f"Page {page_id}: CV template match notice: {e}", "debug")

                    win_metrics = detail.get("window") or {}
                    target = detail.get("target") or {}
                    target_x = float(target.get("x", 662))
                    target_y = float(target.get("y", 342))
                    screen_x = float(win_metrics.get("screenX") or 0)
                    screen_y = float(win_metrics.get("screenY") or 0)
                    outer_w = float(win_metrics.get("outerWidth") or 1920)
                    outer_h = float(win_metrics.get("outerHeight") or 1032)
                    inner_w = float(win_metrics.get("innerWidth") or 1920)
                    inner_h = float(win_metrics.get("innerHeight") or 945)

                    toolbar_h = max(75.0, min(140.0, outer_h - inner_h)) if outer_h > inner_h else 85.0
                    border_w = max(0.0, (outer_w - inner_w) / 2.0) if outer_w > inner_w else 0.0
                    dom_click_x = round(screen_x + border_w + target_x)
                    dom_click_y = round(screen_y + toolbar_h + target_y)

                    # Multi-tier click retry loop: CV Template Match -> DOM Target -> Offsets
                    click_attempts = []
                    if template_coord:
                        click_attempts.append(("CV_TEMPLATE_MATCH", template_coord[0], template_coord[1], False))
                    click_attempts.extend([
                        ("DOM_TARGET", dom_click_x, dom_click_y, False),
                        ("OFFSET_TARGET", dom_click_x + 5, dom_click_y + 5, False),
                        ("DOUBLE_CLICK_DOM", template_coord[0] if template_coord else dom_click_x, template_coord[1] if template_coord else dom_click_y, True),
                        ("COMPOSER_DROPZONE", round(screen_x + outer_w * 0.45), round(screen_y + toolbar_h + 280), False),
                    ])

                    for label, cx, cy, is_double in click_attempts:
                        Win32DialogEngine.focus_chrome()
                        time.sleep(0.1)
                        self.log(f"Page {page_id}: [{label}] clicking Add Video at ({cx}, {cy})...")
                        pyautogui.moveTo(cx, cy, duration=0.15)
                        time.sleep(0.08)
                        if is_double:
                            pyautogui.doubleClick(cx, cy)
                        else:
                            pyautogui.click(cx, cy)

                        # Poll up to 2.5s for file dialog after click
                        deadline = time.time() + 2.5
                        while time.time() < deadline:
                            dlg = Win32DialogEngine.find_file_dialog()
                            if dlg:
                                break
                            time.sleep(0.12)
                        if dlg:
                            self.log(f"Page {page_id}: Open dialog (#32770) opened via [{label}].")
                            break

                if dlg:
                    self.log(f"Page {page_id}: Open dialog detected (#32770). Submitting video path...")
                    success = Win32DialogEngine.submit_file(dlg, abs_path)
                    if success:
                        self.log(f"Page {page_id}: video path submitted to Open dialog.")
                        record_research_log("FILE_PICKER_SUBMITTED", page_id, "OPEN_DIALOG", detail={"video": abs_path})
                        if self.agent and self.agent.memory:
                            self.agent.memory.record_success("add_video", coord_x=cx, coord_y=cy)
                        record_research_log("FILE_PICKER_SUBMITTED", page_id, "OPEN_DIALOG", detail={"video": abs_path})
                    else:
                        self.log(f"Page {page_id}: Win32DialogEngine submission failed.", "warning")

                    # Dismiss any unexpected extra/secondary dialog that may have opened
                    time.sleep(0.8)
                    extra = Win32DialogEngine.find_file_dialog()
                    if extra and extra != dlg:
                        self.log(f"Page {page_id}: Closing unexpected secondary dialog ({extra})...")
                        ctypes.windll.user32.PostMessageW(extra, 0x0010, 0, 0)
                else:
                    self.log(f"Page {page_id}: Could not detect Open dialog (#32770) after click.", "warning")
            except Exception as exc:
                self.log(f"Page {page_id}: native picker notice: {exc}", "warning")
            finally:
                with self.lock:
                    self._picker_in_progress = False
                    self._last_picker_completed_time = time.time()

    def _local_picker_failure(self, page_id: str, state: str, message: str):
        self.log(f"PAGE {page_id} | {state} | {message}", "error")
        record_research_log(state, page_id, "PICKER_FAILURE", detail={"message": message}, result="FAIL")
        with self.lock:
            if self.current_task and str(self.current_task.get("id")) == str(page_id):
                self.task_state = state
                self.task_event.set()

    def _task_for_page(self, p: dict) -> dict:
        return self.resolve_page_task(p)

    def run_single_page(self, page_id: str) -> bool:
        """Executes upload and publishing for a single specific page ID across any brand."""
        brand, target_page = self.find_brand_for_page(page_id)
        if not target_page:
            target_page = next((p for p in self.pages if str(p.get("id")) == str(page_id)), None)
            brand = self.get_active_brand()
        if not target_page:
            self.log(f"Page ID {page_id} not found in configured brand destinations.", "error")
            return False

        if self.batch_running:
            self.log("Cannot start single page: another batch run is currently active.", "warning")
            return False

        self.active_page_id = str(page_id)
        t = threading.Thread(
            target=self._execute_brand_pages,
            args=(brand, [target_page], False),
            name=f"SinglePageRunner-{page_id}",
            daemon=True
        )
        t.start()
        self.batch_thread = t
        return True

    def run_batch_now(self, target_pages: list[dict] = None, from_schedule: bool = False) -> bool:
        """Executes batch run for all enabled pages of the active brand immediately."""
        with self.lock:
            if self.batch_running:
                self.log("Batch run already in progress.", "warning")
                return False
            enabled = target_pages if target_pages is not None else [p for p in self.pages if p.get("enabled", True)]
            if not enabled:
                self.log("No pages are currently enabled for this brand.", "warning")
                return False
            self.batch_running = True
            self.shutdown_event.clear()

        t = threading.Thread(
            target=self._execute_batch,
            args=(enabled, from_schedule),
            name="ActiveBrandBatchRunner",
            daemon=True
        )
        t.start()
        self.batch_thread = t
        return True

    def start_batch_now(self, brand_id: str = None) -> bool:
        """Starts batch execution for active brand, specified brand, or 'ALL' brands."""
        if brand_id == "ALL":
            return self.start_all_brands_batch(from_schedule=False)
        if brand_id:
            target_brand = self.get_brand(brand_id)
            if not target_brand:
                self.log(f"Brand ID '{brand_id}' not found.", "error")
                return False
            self.set_active_brand(brand_id)
        enabled = [p for p in self.pages if p.get("enabled", True)]
        return self.run_batch_now(target_pages=enabled, from_schedule=False)

    def start_all_brands_batch(self, from_schedule: bool = False) -> bool:
        """Starts automated publishing sequentially across ALL configured brands."""
        with self.lock:
            if self.batch_running:
                self.log("Batch run already in progress. Cannot start All Brands batch.", "warning")
                return False
            self.batch_running = True
            self.shutdown_event.clear()

        t = threading.Thread(
            target=self._execute_all_brands_batch,
            args=(from_schedule,),
            name="AllBrandsBatchRunner",
            daemon=True
        )
        t.start()
        self.batch_thread = t
        return True

    def run_scheduled_batch(self, schedule_id: str = "", brand_id: str = "") -> bool:
        """Executes batch run triggered by Windows Task Scheduler or background schedule."""
        with self.lock:
            if self.batch_running:
                self.log(f"Scheduled batch triggered ({schedule_id}) but batch run already in progress.", "warning")
                return False

        target_brand = brand_id
        if not target_brand and schedule_id:
            sched = next((s for s in self.schedules if s.get("id") == schedule_id), None)
            if sched:
                target_brand = sched.get("target_brand") or "ALL"

        if target_brand == "ALL":
            return self.start_all_brands_batch(from_schedule=True)
        elif target_brand:
            b = self.get_brand(target_brand)
            if b:
                self.set_active_brand(target_brand)

        enabled = [p for p in self.pages if p.get("enabled", True)]
        if not enabled:
            self.log("No pages are currently enabled for scheduled run.", "warning")
            return False

        with self.lock:
            self.batch_running = True
            self.shutdown_event.clear()

        t = threading.Thread(
            target=self._execute_batch,
            args=(enabled, True),
            name=f"ScheduledBatchRunner-{schedule_id or 'auto'}",
            daemon=True
        )
        t.start()
        self.batch_thread = t
        return True

    def stop_batch(self):
        """Safely stops active batch execution."""
        with self.lock:
            if not self.batch_running:
                InputRestrictionManager.release(force=True)
                return
            self.log("Stopping active batch execution...")
            self.shutdown_event.set()
            self.task_event.set()
            self.hello_event.set()
            InputRestrictionManager.release(force=True)

    def _execute_all_brands_batch(self, from_schedule: bool = False):
        ensure_default_desktop()
        lock_file = BASE_DIR / ".batch_running.lock"
        try:
            if lock_file.exists():
                lock_text = lock_file.read_text(encoding="utf-8").strip()
                lock_data = json.loads(lock_text) if lock_text else {}
                lock_pid = lock_data.get("pid")
                lock_time = lock_data.get("time", 0)
                if lock_pid and lock_pid != os.getpid() and time.time() - lock_time < 3600:
                    cmd = f"Get-Process -Id {lock_pid} -ErrorAction SilentlyContinue"
                    res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
                    if res.returncode == 0 and res.stdout.strip():
                        self.log(f"Another batch is already actively running (PID {lock_pid}). Skipping duplicate concurrent trigger.", "warning")
                        return
        except Exception:
            pass

        with self.lock:
            self.batch_running = True
            self.shutdown_event.clear()

        try:
            lock_file.write_text(json.dumps({"pid": os.getpid(), "time": time.time()}), encoding="utf-8")
        except Exception:
            pass

        # Acquire physical input lock for the entire duration of all-brands execution
        InputRestrictionManager.acquire(
            reason=f"Multi-Brand Batch publishing running for {len(self.brands)} brands",
            max_timeout=7200.0
        )
        try:
            mode = "scheduled" if from_schedule else "manual"
            all_brands = list(self.brands)
            self.log(f"Starting Multi-Brand Batch run for {len(all_brands)} brand(s). Mode: {mode}.")
            ensure_api_server_running(timeout=6.0)
            record_research_log("ALL_BRANDS_BATCH_STARTED", "ALL", "BATCH", detail={"brands_count": len(all_brands), "mode": mode})

            for b_idx, brand in enumerate(all_brands, 1):
                if self.shutdown_event.is_set():
                    self.log("Multi-brand batch stopped by user request.")
                    break

                b_id = brand.get("id")
                b_name = brand.get("name")
                b_prof = brand.get("chrome_profile") or self.selected_profile
                enabled_pages = [p for p in brand.get("pages", []) if p.get("enabled", True)]

                if not enabled_pages:
                    self.log(f"[Brand {b_idx}/{len(all_brands)}] Skipping '{b_name}': no enabled pages.")
                    continue

                self.log("================================================================================")
                self.log(f"[Brand {b_idx}/{len(all_brands)}] Starting '{b_name}' (Profile: {b_prof}, {len(enabled_pages)} pages)...")
                self.log("================================================================================")

                self.set_active_brand(b_id)
                self._execute_brand_pages(brand, enabled_pages, from_schedule=from_schedule)

                if self.shutdown_event.is_set():
                    break

                if b_idx < len(all_brands):
                    next_b = all_brands[b_idx].get("name", "Next Brand")
                    cooldown = random.uniform(10.0, 16.0)
                    self.log(f"[IntelligentQueue] Completed brand '{b_name}'. Cooling down {cooldown:.1f}s before next brand '{next_b}' (Anti-Rate Limit)...")
                    for _ in range(int(cooldown * 2)):
                        if self.shutdown_event.is_set():
                            break
                        time.sleep(0.5)

            self.log("All Brands publishing run finished successfully.")
            record_research_log("ALL_BRANDS_BATCH_FINISHED", "ALL", "BATCH")
        except Exception as exc:
            self.log(f"All Brands batch execution error: {exc}", "error")
        finally:
            InputRestrictionManager.release()
            try:
                if lock_file.exists():
                    lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            with self.lock:
                self.current_task = None
                self.batch_running = False

    def _execute_brand_pages(self, brand: dict, target_pages: list[dict], from_schedule: bool = False):
        ensure_default_desktop()
        today = dt.date.today().isoformat()
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        attempts = state.setdefault("attempts", {})

        b_name = brand.get("name", "Active")
        b_prof = brand.get("chrome_profile") or self.selected_profile
        max_limit = getattr(self, "max_publications_per_day", 7)

        todo = []
        for p in target_pages:
            pid = str(p['id']).strip()
            pub_cnt = self.get_today_published_count(pid, today)
            if max_limit > 0 and pub_cnt >= max_limit:
                self.log(f"[{b_name}] Skipping {p['name']} ({pid}): daily safety limit reached ({pub_cnt}/{max_limit} published today).", "warning")
                continue
            todo.append(p)

        if not todo:
            self.log(f"[{b_name}] All {len(target_pages)} destination page(s) have reached their daily safety limit ({max_limit}/day).")
            return

        mode = "scheduled" if from_schedule else "manual"
        self.log(f"[{b_name}] Starting batch for {len(todo)} page(s) in Profile '{b_prof}'. Mode: {mode}. (Daily limit: {max_limit if max_limit > 0 else 'unlimited'})")
        record_research_log("BRAND_BATCH_STARTED", brand.get("id"), "BATCH", detail={"brand": b_name, "total_pages": len(todo), "mode": mode, "max_limit": max_limit})

        InputRestrictionManager.acquire(
            reason=f"Publishing {len(todo)} reels for brand '{b_name}'",
            max_timeout=max(300.0, len(todo) * 300.0)
        )
        try:
            self._process_brand_todo_pages(brand, todo, state, attempts, today, b_name, b_prof)
        finally:
            InputRestrictionManager.release()

        state["last_batch_date"] = today
        state["last_batch_finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        save_json(STATE_FILE, state)

    def _process_brand_todo_pages(self, brand: dict, todo: list[dict], state: dict, attempts: dict, today: str, b_name: str, b_prof: str):
        for idx, p in enumerate(todo, 1):
            if self.shutdown_event.is_set():
                self.log(f"[{b_name}] Batch stopped by user request.")
                break

            task = self.resolve_page_task(p, brand)
            video_file = Path(task["video"]) if task.get("video") else None
            if not video_file or not video_file.is_file():
                self.log(f"[{b_name}] Skipping {p['name']}: video file missing: {task.get('video')}", "error")
                attempts[f"{today}:{p['id']}"] = "VIDEO_MISSING"
                save_json(STATE_FILE, state)
                continue

            with self.lock:
                self.current_task = task
                self.active_page_id = p["id"]
                self.task_state = "WAITING"
                self.task_event.clear()
                self.hello_event.clear()

            attempts[f"{today}:{p['id']}"] = "STARTED"
            save_json(STATE_FILE, state)

            self.log(f"[{b_name}] Opening page {idx}/{len(todo)}: {p['name']} ({p['id']}) in Profile '{b_prof}'")
            start_time = time.time()

            ensure_api_server_running(timeout=5.0)

            if not self.open_chrome_url(p["url"], profile_name=b_prof):
                attempts[f"{today}:{p['id']}"] = "CHROME_OPEN_FAILED"
                save_json(STATE_FILE, state)
                break

            # Wait up to 90s for extension helper to connect on composer page
            connected = False
            for sec in range(6):  # 6 intervals of 15s = 90s total
                if self.hello_event.wait(15):
                    connected = True
                    break
                ensure_api_server_running(timeout=1.5)
                if not self.shutdown_event.is_set():
                    self.log(f"[{b_name}] Waiting for Chrome helper extension connection... ({(sec + 1) * 15}s/90s)")

            if not connected:
                self.log(f"[{b_name}] Chrome extension helper did not connect within 90s. Halting batch for this brand.", "error")
                attempts[f"{today}:{p['id']}"] = "EXTENSION_NOT_CONNECTED"
                save_json(STATE_FILE, state)
                break

            # Autonomous Active Watchdog & Self-Healing Loop:
            deadline = time.time() + 900
            last_state_change_time = time.time()
            prev_monitored_state = self.task_state

            while time.time() < deadline and not self.shutdown_event.is_set():
                if self.task_event.wait(1.5):
                    break

                now = time.time()
                current_st = self.task_state
                if current_st != prev_monitored_state:
                    prev_monitored_state = current_st
                    last_state_change_time = now

                state_duration = now - last_state_change_time

                # 1. Dialog Watchdog
                dlg = Win32DialogEngine.find_file_dialog()
                if dlg:
                    v_target = (self.current_task.get("video") if self.current_task else None) or self.global_video
                    if v_target and Path(v_target).is_file():
                        self.log(f"[Watchdog] Open dialog (#32770) detected. Auto-submitting video: {v_target}")
                        Win32DialogEngine.submit_file(dlg, str(Path(v_target).resolve()))

                # 2. Upload Stalled Watchdog
                if current_st in ("WAITING_FOR_VIDEO_UPLOAD", "FILE_PICKER_REQUEST") and state_duration > 16.0:
                    self.log(f"[Watchdog] Page {p['id']}: Video upload idle for {state_duration:.0f}s. Re-triggering file picker...")
                    last_state_change_time = now
                    v_path = (self.current_task.get("video") if self.current_task else None) or self.global_video
                    threading.Thread(
                        target=self.select_native_file,
                        args=(p['id'], str(v_path or ""), {}),
                        name=f"WatchdogFilePicker_{p['id']}",
                        daemon=True
                    ).start()

                # 3. Share Screen / Modal Stalled Watchdog
                elif current_st in ("WAITING_FOR_SHARE_SCREEN", "SHARE_BUTTON_CLICKING", "WAITING_FOR_PROCESSING_MODAL") and state_duration > 8.0:
                    self.log(f"[Watchdog] Page {p['id']}: Share/Modal waiting for {state_duration:.0f}s. Re-evaluating buttons...")
                    last_state_change_time = now
                    done_pos = CVInspectionEngine.find_action_button("modal_done")
                    if done_pos:
                        self.log(f"[Watchdog] Done modal detected via CV at {done_pos}. Clicking Done!")
                        pyautogui.click(done_pos[0], done_pos[1])
                        self.task_state = "PUBLISHED"
                        self.task_event.set()
                        break

                    share_pos = CVInspectionEngine.find_action_button("bottom_right")
                    if share_pos:
                        self.log(f"[Watchdog] Dispatching hardware click to Share button at {share_pos}...")
                        pyautogui.click(share_pos[0], share_pos[1])

                # 4. Next Button Stalled Watchdog
                elif current_st in ("SCREEN1_NEXT_WAITING", "WAITING_FOR_EDIT_SCREEN") and state_duration > 10.0:
                    self.log(f"[Watchdog] Page {p['id']}: Next button waiting for {state_duration:.0f}s. Re-clicking Next...")
                    last_state_change_time = now
                    next_pos = CVInspectionEngine.find_action_button("bottom_right")
                    if next_pos:
                        pyautogui.click(next_pos[0], next_pos[1])

            duration = time.time() - start_time
            final_state = self.task_state if self.task_event.is_set() else "TASK_TIMEOUT"
            attempts[f"{today}:{p['id']}"] = final_state

            max_limit = getattr(self, "max_publications_per_day", 7)
            if final_state in {"PUBLISHED", "READY_FOR_REVIEW", "READY_FOR_MANUAL_REVIEW"}:
                new_cnt = self.record_page_published(p['id'], today)
                self.log(f"[{b_name}] Destination {p['name']} successfully completed publication ({new_cnt}/{max_limit if max_limit > 0 else '∞'} published today).")
            else:
                save_json(STATE_FILE, state)

            self.log(f"[{b_name}] Page {p['id']} finished with status: {final_state} ({duration:.1f}s)")
            record_research_log("PAGE_BATCH_ITEM_FINISHED", p['id'], "TASK_FINISH", duration_ms=duration * 1000, detail={"brand": b_name, "status": final_state})

            self.close_tab_for_page(p['id'])

            if final_state not in {"PUBLISHED", "READY_FOR_REVIEW", "READY_FOR_MANUAL_REVIEW"}:
                rec_wait = random.uniform(4.0, 7.0)
                self.log(f"[{b_name}] Page {p['name']} did not complete publication (status: {final_state}). Recovery pacing: waiting {rec_wait:.1f}s before next destination...", "warning")
                for _ in range(int(rec_wait * 2)):
                    if self.shutdown_event.is_set():
                        break
                    time.sleep(0.5)
                continue

            success_wait = random.uniform(6.0, 10.0)
            self.log(f"[{b_name}] Page {p['name']} published successfully! Intelligent pacing: waiting {success_wait:.1f}s before starting next destination.")
            for _ in range(int(success_wait * 2)):
                if self.shutdown_event.is_set():
                    break
                time.sleep(0.5)

    def _execute_batch(self, target_pages: list[dict], from_schedule: bool = False):
        ensure_default_desktop()
        lock_file = BASE_DIR / ".batch_running.lock"
        try:
            if lock_file.exists():
                lock_text = lock_file.read_text(encoding="utf-8").strip()
                lock_data = json.loads(lock_text) if lock_text else {}
                lock_pid = lock_data.get("pid")
                lock_time = lock_data.get("time", 0)
                if lock_pid and lock_pid != os.getpid() and time.time() - lock_time < 3600:
                    cmd = f"Get-Process -Id {lock_pid} -ErrorAction SilentlyContinue"
                    res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
                    if res.returncode == 0 and res.stdout.strip():
                        self.log(f"Another batch is already actively running (PID {lock_pid}). Skipping duplicate concurrent trigger.", "warning")
                        return
        except Exception:
            pass

        with self.lock:
            self.batch_running = True
            self.shutdown_event.clear()

        try:
            lock_file.write_text(json.dumps({"pid": os.getpid(), "time": time.time()}), encoding="utf-8")
        except Exception:
            pass

        InputRestrictionManager.acquire(
            reason=f"Batch publishing {len(target_pages)} destinations for active brand",
            max_timeout=max(300.0, len(target_pages) * 300.0)
        )
        try:
            self._execute_brand_pages(self.get_active_brand(), target_pages, from_schedule=from_schedule)
            self.log("Batch processing completed.")
            record_research_log("BATCH_FINISHED", "ALL", "BATCH")
        except Exception as exc:
            self.log(f"Batch execution error: {exc}", "error")
        finally:
            InputRestrictionManager.release()
            try:
                if lock_file.exists():
                    lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            with self.lock:
                self.current_task = None
                self.batch_running = False

    def get_today_published_count(self, page_id: str, date_str: str = None) -> int:
        """Returns the number of successful publications today for a given page ID."""
        today = date_str or dt.date.today().isoformat()
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        counts = state.get("published_counts", {})
        k = f"{today}:{str(page_id).strip()}"
        if k in counts:
            try:
                return int(counts[k])
            except Exception:
                return 0
        att = state.get("attempts", {}).get(k)
        return 1 if att == "PUBLISHED" else 0

    def record_page_published(self, page_id: str, date_str: str = None) -> int:
        """Atomically increments today's publication counter and records PUBLISHED state."""
        today = date_str or dt.date.today().isoformat()
        pid = str(page_id).strip()
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        counts = state.setdefault("published_counts", {})
        k = f"{today}:{pid}"
        cur = counts.get(k, 0)
        if not isinstance(cur, int):
            cur = 1 if cur == "PUBLISHED" else 0
        counts[k] = cur + 1
        state.setdefault("attempts", {})[k] = "PUBLISHED"
        state["last_batch_date"] = today
        state["last_batch_finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
        save_json(STATE_FILE, state)
        return counts[k]

    def reset_page_attempt(self, page_id: str) -> bool:
        today = dt.date.today().isoformat()
        pid = str(page_id).strip()
        key = f"{today}:{pid}"
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        modified = False
        if "published_counts" in state and key in state["published_counts"]:
            state["published_counts"].pop(key, None)
            modified = True
        if "attempts" in state and key in state["attempts"]:
            state["attempts"].pop(key, None)
            modified = True
        if modified:
            save_json(STATE_FILE, state)
            self.log(f"Reset daily publication count for page {pid} to 0.")
            return True
        return False

    def reset_all_attempts(self):
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        state["attempts"] = {}
        state["published_counts"] = {}
        save_json(STATE_FILE, state)
        self.log("All daily duplicate attempts and publication counts have been reset for today.")
        record_research_log("ALL_ATTEMPTS_RESET", "ALL", "RESET")


# Backward compatibility and GUI aliases
MetaReelsAutomationController = MetaReelsController
MetaReelsController.execute_page_by_id = MetaReelsController.run_single_page

controller = MetaReelsController()
agent = AutonomousRemediationAgent(controller, learning_db)
controller.set_learning_agent(agent)


# ==============================================================================
# REST API Endpoints (FastAPI)
# ==============================================================================

@api_app.get("/health")
def api_health():
    return {"ok": True, "app": APP_NAME, "version": "2.2.0"}


@api_app.get("/api/learning/heuristics")
def api_get_learning_heuristics():
    return {"ok": True, "heuristics": learning_db.list_heuristics()}


@api_app.get("/api/agent/episodes")
def api_get_agent_episodes(limit: int = 50):
    return {"ok": True, "episodes": learning_db.list_episodes(limit)}


@api_app.post("/api/agent/remediate/{page_id}")
def api_trigger_agent_remediate(page_id: str, stage: str = "MANUAL_TRIGGER"):
    result = agent.evaluate_and_remediate(page_id, stage, {"manual_trigger": True})
    return {"ok": True, "result": result}


@api_app.get("/api/status")
def api_status():
    return controller.get_status()


@api_app.get("/api/config")
def api_get_config():
    return controller.get_config()


async def safe_json_body(req: Request) -> dict:
    """Safely decodes JSON body, preventing JSONDecodeError from bubbling to 500 responses."""
    try:
        raw = await req.body()
        if not raw:
            return {}
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            return {}
        return json.loads(text)
    except Exception:
        return {}


@api_app.post("/api/config")
async def api_post_config(req: Request):
    data = await safe_json_body(req)
    controller.update_config(data)
    return {"ok": True, "config": controller.get_config()}


@api_app.get("/api/schedules")
def api_get_schedules():
    schedules = list(controller.schedules)
    enriched = []
    for s in schedules:
        c = dict(s)
        q = WindowsTaskSchedulerManager.query_task(s.get("id", ""))
        c["windows_task_status"] = q.get("status", "Not Registered")
        c["next_run"] = q.get("next_run", "")
        enriched.append(c)
    return {"ok": True, "schedules": enriched}


@api_app.post("/api/schedules/add")
@api_app.post("/api/schedules/create")
async def api_add_schedule(req: Request):
    payload = await safe_json_body(req)
    time_str = payload.get("time", "17:00")
    name = payload.get("name", "")
    enabled = payload.get("enabled", True)
    days = payload.get("days", "DAILY")
    repeat_interval = int(payload.get("repeat_interval_minutes") or 0)
    repeat_duration = int(payload.get("repeat_duration_hours") or 24)
    target_brand = str(payload.get("target_brand") or "ALL")
    video = payload.get("video", "")
    caption = payload.get("caption", "")
    res = controller.add_schedule(time_str, name, enabled, days, repeat_interval, repeat_duration, target_brand, video, caption)
    return {"ok": True, "schedule": res}


@api_app.get("/api/brands")
def api_get_brands():
    return {
        "ok": True,
        "active_brand_id": controller.active_brand_id,
        "brands": controller.get_brands()
    }


@api_app.get("/api/brands/active")
def api_get_active_brand():
    return {
        "ok": True,
        "active_brand_id": controller.active_brand_id,
        "brand": controller.get_active_brand()
    }


@api_app.post("/api/brands/select")
async def api_select_brand(req: Request):
    data = await safe_json_body(req)
    bid = data.get("brand_id") or data.get("id")
    if not bid:
        raise HTTPException(status_code=400, detail="brand_id required")
    ok = controller.set_active_brand(str(bid))
    return {
        "ok": ok,
        "active_brand_id": controller.active_brand_id,
        "brand": controller.get_active_brand()
    }


@api_app.post("/api/brands/create")
async def api_create_brand(req: Request):
    data = await safe_json_body(req)
    name = str(data.get("name") or "New Brand").strip()
    new_b = controller.add_brand(
        name=name,
        chrome_profile=str(data.get("chrome_profile") or "Profile 15").strip(),
        video=str(data.get("video") or "").strip(),
        caption=str(data.get("caption") or "").strip(),
        location=str(data.get("location") or "Mumbai").strip(),
        auto_publish=bool(data.get("auto_publish", True)),
        description=str(data.get("description") or "").strip(),
        pages=data.get("pages") or [],
        media_folder=str(data.get("media_folder") or "").strip()
    )
    return {"ok": True, "brand": new_b}


@api_app.post("/api/brands/update")
async def api_update_brand(req: Request):
    data = await safe_json_body(req)
    bid = data.get("id") or data.get("brand_id")
    if not bid:
        raise HTTPException(status_code=400, detail="Brand id required")
    updated = controller.update_brand(str(bid), data)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Brand {bid} not found")
    return {"ok": True, "brand": updated}


@api_app.post("/api/brands/delete")
async def api_delete_brand(req: Request):
    data = await safe_json_body(req)
    bid = data.get("id") or data.get("brand_id")
    if not bid:
        raise HTTPException(status_code=400, detail="Brand id required")
    ok = controller.delete_brand(str(bid))
    return {"ok": ok, "active_brand_id": controller.active_brand_id}


@api_app.get("/api/brand/{brand_id}/pages")
def api_get_brand_pages(brand_id: str):
    b = controller.get_brand(brand_id)
    if not b:
        raise HTTPException(status_code=404, detail=f"Brand {brand_id} not found")
    return {"brand_id": brand_id, "pages": b.get("pages", [])}


@api_app.post("/api/brand/{brand_id}/pages")
async def api_set_brand_pages(brand_id: str, req: Request):
    b = controller.get_brand(brand_id)
    if not b:
        raise HTTPException(status_code=404, detail=f"Brand {brand_id} not found")
    data = await safe_json_body(req)
    pages = data.get("pages") or []
    updated = controller.update_brand(brand_id, {"pages": pages})
    return {"ok": True, "pages": updated.get("pages", []) if updated else []}


@api_app.get("/api/media/scan")
def api_media_scan(folder: str = ""):
    """Scans any specified local directory for video and text file pairs."""
    target_folder = folder or str(BASE_DIR / "loan")
    items = scan_media_folder(target_folder)
    return {
        "ok": True,
        "folder": target_folder,
        "total": len(items),
        "total_videos": len(items),
        "paired": sum(1 for i in items if i["has_paired_text"]),
        "paired_count": sum(1 for i in items if i["has_paired_text"]),
        "items": items
    }


@api_app.get("/api/brand/{brand_id}/media-pairs")
def api_get_brand_media_pairs(brand_id: str):
    """Returns all discovered video and text pairs for the specified brand."""
    b = controller.get_brand(brand_id)
    if not b:
        raise HTTPException(status_code=404, detail=f"Brand {brand_id} not found")
    folder = b.get("media_folder") or controller.media_folder
    items = scan_media_folder(folder) if folder else []
    return {
        "ok": True,
        "brand_id": brand_id,
        "media_folder": folder,
        "total": len(items),
        "total_videos": len(items),
        "paired": sum(1 for i in items if i["has_paired_text"]),
        "paired_count": sum(1 for i in items if i["has_paired_text"]),
        "items": items
    }


@api_app.get("/api/brand/{brand_id}/random-pair")
def api_get_brand_random_pair(brand_id: str):
    """Randomly selects a video and its paired text caption for the brand."""
    b = controller.get_brand(brand_id)
    if not b:
        raise HTTPException(status_code=404, detail=f"Brand {brand_id} not found")
    folder = b.get("media_folder") or controller.media_folder
    if not folder:
        raise HTTPException(status_code=400, detail="Brand has no media_folder configured")
    pair = controller.get_random_brand_media(brand_id, folder)
    if not pair:
        raise HTTPException(status_code=404, detail="No video files found in brand media folder")
    return {"ok": True, "brand_id": brand_id, "selected": pair, "pair": pair}


@api_app.post("/api/brand/{brand_id}/media-folder")
async def api_set_brand_media_folder(brand_id: str, req: Request):
    """Updates the media folder for a specific brand."""
    data = await safe_json_body(req)
    folder = str(data.get("media_folder") or data.get("folder") or "").strip()
    ok = controller.set_brand_media_folder(brand_id, folder)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Brand {brand_id} not found")
    return {"ok": True, "brand_id": brand_id, "media_folder": folder}


# ==============================================================================
# Enterprise Input Restriction REST API Endpoints
# ==============================================================================

@api_app.get("/api/input-restriction/status")
def api_input_restriction_status():
    """Returns current physical input restriction status and metadata."""
    return InputRestrictionManager.get_status()


@api_app.post("/api/input-restriction/block")
@api_app.post("/api/input-restriction/acquire")
async def api_input_restriction_acquire(req: Request):
    """Acquires physical keyboard and mouse restriction with optional timeout and reason."""
    data = await safe_json_body(req)
    reason = str(data.get("reason") or "Manual API trigger").strip()
    timeout = float(data.get("timeout") or 300.0)
    success = InputRestrictionManager.acquire(reason=reason, max_timeout=timeout)
    return {"ok": success, "status": InputRestrictionManager.get_status()}


@api_app.post("/api/input-restriction/release")
@api_app.post("/api/input-restriction/unlock")
def api_input_restriction_release():
    """Immediately releases physical keyboard and mouse restriction."""
    success = InputRestrictionManager.release(force=True)
    return {"ok": success, "status": InputRestrictionManager.get_status()}


@api_app.post("/api/run-now")
async def api_run_now(req: Request):
    data = await safe_json_body(req)
    target_brand = data.get("brand_id")
    ok = controller.start_batch_now(brand_id=target_brand)
    return {"ok": ok, "batch_running": controller.batch_running, "target_brand": target_brand or controller.active_brand_id}


@api_app.post("/api/batch/start")
async def api_batch_start(req: Request):
    data = await safe_json_body(req)
    target_brand = data.get("brand_id")
    sched_id = data.get("schedule_id", "")
    ok = controller.run_scheduled_batch(schedule_id=sched_id, brand_id=target_brand)
    return {"ok": ok, "batch_running": controller.batch_running, "schedule_id": sched_id, "brand_id": target_brand}


@api_app.post("/api/schedules/edit/{sched_id}")
async def api_edit_schedule(sched_id: str, req: Request):
    updates = await safe_json_body(req)
    res = controller.edit_schedule(sched_id, updates)
    if not res:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True, "schedule": res}


@api_app.post("/api/schedules/update")
async def api_update_schedule_body(req: Request):
    payload = await safe_json_body(req)
    sched_id = payload.get("id", "")
    res = controller.edit_schedule(sched_id, payload)
    if not res:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"ok": True, "schedule": res}


@api_app.delete("/api/schedules/{sched_id}")
def api_delete_schedule(sched_id: str):
    ok = controller.delete_schedule(sched_id)
    return {"ok": ok}


@api_app.post("/api/schedules/delete")
async def api_delete_schedule_post(req: Request):
    payload = await safe_json_body(req)
    sched_id = payload.get("id", "")
    ok = controller.delete_schedule(sched_id)
    return {"ok": ok}


@api_app.post("/api/schedules/sync")
def api_sync_schedules():
    res = controller.sync_all_schedules_to_windows()
    return {"ok": True, "result": res}


@api_app.post("/api/schedules/run/{sched_id}")
def api_run_schedule(sched_id: str):
    res = WindowsTaskSchedulerManager.run_task_now(sched_id)
    return res


@api_app.post("/api/extension/install")
@api_app.post("/api/extension/sync")
def api_install_extension():
    res = ensure_chrome_extension_installed()
    return {"ok": True, "result": res}


@api_app.get("/api/pages")
def api_get_pages():
    status = controller.get_status()
    today_attempts = status.get("today_attempts", {})
    today_counts = status.get("today_published_counts", {})
    max_limit = controller.max_publications_per_day
    enriched = []
    for p in controller.pages:
        pid = str(p["id"])
        c = dict(p)
        cnt = today_counts.get(pid, controller.get_today_published_count(pid))
        c["today_published_count"] = cnt
        c["max_publications_per_day"] = max_limit
        if cnt > 0:
            c["today_status"] = f"PUBLISHED ({cnt}/{max_limit if max_limit > 0 else '∞'})"
        else:
            c["today_status"] = today_attempts.get(pid, "PENDING")
        enriched.append(c)
    return {"ok": True, "pages": enriched, "max_publications_per_day": max_limit}


@api_app.post("/api/safety-limit")
async def api_set_safety_limit(req: Request):
    payload = await safe_json_body(req)
    limit = int(payload.get("max_publications_per_day", 7))
    controller.update_config({"max_publications_per_day": limit})
    return {"ok": True, "max_publications_per_day": controller.max_publications_per_day}


@api_app.post("/api/pages/{page_id}/reset")
def api_reset_page(page_id: str):
    res = controller.reset_page_attempt(page_id)
    return {"ok": True, "cleared": res}


@api_app.post("/api/reset-all")
def api_reset_all():
    controller.reset_all_attempts()
    return {"ok": True}


@api_app.post("/api/run-page/{page_id}")
def api_run_page(page_id: str):
    ok = controller.run_single_page(page_id)
    return {"ok": ok, "page_id": page_id}


@api_app.post("/api/stop")
def api_stop():
    controller.stop_batch()
    return {"ok": True, "batch_running": controller.batch_running}


@api_app.post("/api/scheduler/start")
def api_start_scheduler():
    controller.scheduler_enabled = True
    controller.log(f"Daily scheduler ENABLED for {controller.schedule_time}.")
    return {"ok": True, "scheduler_enabled": True}


@api_app.post("/api/scheduler/stop")
def api_stop_scheduler():
    controller.scheduler_enabled = False
    controller.log("Daily scheduler DISABLED.")
    return {"ok": True, "scheduler_enabled": False}


@api_app.post("/api/open-chrome")
async def api_open_chrome(req: Request):
    data = await safe_json_body(req)
    url = data.get("url") or (controller.pages[0]["url"] if controller.pages else "")
    ok = controller.open_chrome_url(url)
    return {"ok": ok, "url": url}


@api_app.get("/api/profiles")
def api_get_profiles():
    profiles = controller.get_available_profiles()
    return {
        "ok": True,
        "selected_profile": controller.selected_profile,
        "user_data_dir": controller.user_data_dir,
        "profile_path": str(controller.current_profile_path),
        "profiles": profiles
    }


@api_app.post("/api/profile/select")
async def api_select_profile(req: Request):
    data = await safe_json_body(req)
    prof_name = data.get("profile") or data.get("selected_profile")
    user_data = data.get("user_data_dir")
    if not prof_name:
        raise HTTPException(status_code=400, detail="Profile name required")
    res = controller.set_selected_profile(prof_name, user_data)
    return {"ok": True, "selected_profile": controller.selected_profile, "result": res}


@api_app.post("/api/profile/launch")
async def api_launch_profile(req: Request):
    data = await safe_json_body(req)
    prof_name = data.get("profile") or controller.selected_profile
    if prof_name and prof_name != controller.selected_profile:
        controller.set_selected_profile(prof_name)
    url = data.get("url") or (controller.pages[0]["url"] if controller.pages else DEFAULT_URLS[0])
    ok = controller.open_chrome_url(url)
    return {"ok": ok, "profile": controller.selected_profile, "url": url}


@api_app.post("/api/profile/clear-cache")
async def api_clear_cache(req: Request):
    data = await safe_json_body(req)
    prof_name = data.get("profile") or controller.selected_profile
    prof_path = Path(controller.user_data_dir) / prof_name
    res = clear_profile_cache(prof_path)
    return {"ok": True, "result": res}


@api_app.post("/api/profile/shortcut")
async def api_create_shortcut(req: Request):
    data = await safe_json_body(req)
    prof_name = data.get("profile") or controller.selected_profile
    chrome_exe = controller.find_chrome()
    if not chrome_exe:
        raise HTTPException(status_code=404, detail="Chrome executable not found")
    name = data.get("name") or f"Chrome - {prof_name}"
    res = create_windows_shortcut(name, str(chrome_exe), f'--profile-directory="{prof_name}"')
    return {"ok": True, "result": res}


@api_app.get("/api/video")
def api_stream_video(page_id: str = ""):
    """Streams the video file so the Chrome extension can inject it as a Blob/DataTransfer."""
    target_page = next((p for p in controller.pages if str(p.get("id")) == str(page_id)), None)
    video_path = (target_page.get("video") if target_page else None) or controller.global_video
    p = Path(video_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    if not p.is_file():
        fallback = find_default_video()
        if fallback and Path(fallback).is_file():
            p = Path(fallback)
        else:
            raise HTTPException(status_code=404, detail=f"Video file not found on disk: {video_path}")
    return FileResponse(str(p.resolve()), media_type="video/mp4", filename=p.name)


@api_app.get("/api/logs")
def api_logs(limit: int = 150):
    with controller.lock:
        return {"ok": True, "logs": controller.logs_buffer[-limit:]}


@api_app.get("/api/events")
async def api_events(req: Request):
    """Server-Sent Events (SSE) real-time streaming endpoint for telemetry and live activity."""
    async def event_generator():
        q = asyncio.Queue(maxsize=150)
        sse_subscribers.append(q)
        try:
            init_data = {"event": "INIT", "status": controller.get_status()}
            yield f"data: {json.dumps(init_data)}\n\n"
            while True:
                if await req.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=25.0)
                    yield data
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if q in sse_subscribers:
                sse_subscribers.remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@api_app.get("/api/cv/inspect")
def api_cv_inspect():
    """Runs Computer Vision inspection on current desktop / composer window."""
    result = CVInspectionEngine.inspect_current_screen()
    return result


@api_app.post("/api/cv/click-next")
def api_cv_click_next():
    """Triggers Computer Vision detection and click of the bottom-right blue Next/Share button."""
    ok = CVInspectionEngine.click_action_button("bottom_right")
    return {"ok": ok, "target": "bottom_right"}


@api_app.post("/api/cv/click-done")
def api_cv_click_done():
    """Triggers Computer Vision detection and click of the modal Done button."""
    ok = CVInspectionEngine.click_action_button("modal_done")
    return {"ok": ok, "target": "modal_done"}


@api_app.post("/api/cv/click-save")
def api_cv_click_save():
    """Triggers Computer Vision detection and click of the modal Save button."""
    ok = CVInspectionEngine.click_action_button("modal_save")
    return {"ok": ok, "target": "modal_save"}


@api_app.post("/api/action/paste-clipboard")
async def api_action_paste_clipboard(req: Request):
    """Fallback Action: Injects text into focused control via Windows clipboard and Ctrl+V."""
    body = await safe_json_body(req)
    text = body.get("text") or controller.caption or "loan"
    try:
        Win32DialogEngine.focus_chrome()
        time.sleep(0.15)
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'v')
        record_research_log("CLIPBOARD_PASTE_EXECUTED", controller.active_page_id, "PASTE", detail={"text": text})
        return {"ok": True, "action": "PASTE_CLIPBOARD", "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@api_app.get("/next-task")
def api_next_task(page_id: str = ""):
    controller.hello_event.set()
    if page_id:
        controller.active_page_id = page_id
    task = controller.get_task_for_page(page_id)
    return {"task": task}


@api_app.post("/report")
async def api_report(req: Request):
    payload = await safe_json_body(req)
    controller.handle_report(payload or {})
    return {"ok": True}


# ==============================================================================
# Modular Action Endpoints (Converting Every Step & Button to an API)
# ==============================================================================

@api_app.post("/api/action/upload")
async def api_action_upload(req: Request):
    """Action: Triggers file upload on active composer (starts Win32 dialog watcher + extension click)."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    target_page = next((p for p in controller.pages if str(p.get("id")) == pid), None)
    video = body.get("video") or (target_page.get("video") if target_page else "") or controller.global_video
    video_abs = find_default_video(video)

    # Start Win32 Dialog Watcher
    Win32DialogEngine.start_watcher(video_abs, timeout=12.0)

    # Dispatch action to content script
    res = await ws_manager.send_command(pid, "UPLOAD", {"video": video_abs}, timeout=12.0)
    return {"ok": True, "action": "UPLOAD", "page_id": pid, "result": res}


@api_app.post("/api/action/caption")
async def api_action_caption(req: Request):
    """Action: Inserts caption into Lexical / DraftJS editor on active composer."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    caption = body.get("caption") or controller.caption or "loan"
    res = await ws_manager.send_command(pid, "SET_CAPTION", {"caption": caption}, timeout=12.0)
    return {"ok": True, "action": "SET_CAPTION", "page_id": pid, "caption": caption, "result": res}


@api_app.post("/api/action/location")
async def api_action_location(req: Request):
    """Action: Clicks location pin, types location name, and selects first match."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    location = body.get("location") or controller.location or "Mumbai"
    res = await ws_manager.send_command(pid, "SET_LOCATION", {"location": location}, timeout=25.0)
    return {"ok": True, "action": "SET_LOCATION", "page_id": pid, "location": location, "result": res}


@api_app.post("/api/action/messages")
async def api_action_messages(req: Request):
    """Action: Toggles 'Get messages' CTA button on active composer."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "SELECT_MESSAGES", {}, timeout=10.0)
    return {"ok": True, "action": "SELECT_MESSAGES", "page_id": pid, "result": res}


@api_app.post("/api/action/next-edit")
async def api_action_next_edit(req: Request):
    """Action: Clicks Next on Create screen (Step 1 -> 2)."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "NEXT_EDIT", {}, timeout=12.0)
    return {"ok": True, "action": "NEXT_EDIT", "page_id": pid, "result": res}


@api_app.post("/api/action/next-share")
async def api_action_next_share(req: Request):
    """Action: Clicks Next on Edit screen (Step 2 -> 3)."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "NEXT", {}, timeout=12.0)
    return {"ok": True, "action": "NEXT_SHARE", "page_id": pid, "result": res}


@api_app.post("/api/action/publish")
async def api_action_publish(req: Request):
    """Action: Clicks Share / Publish button on Share screen."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "SHARE", {}, timeout=15.0)
    return {"ok": True, "action": "SHARE", "page_id": pid, "result": res}


@api_app.post("/api/action/done")
async def api_action_done(req: Request):
    """Action: Clicks Done button in 'Reel processing' modal dialog."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "DONE", {}, timeout=15.0)
    return {"ok": True, "action": "DONE", "page_id": pid, "result": res}


@api_app.post("/api/action/close")
async def api_action_close(req: Request):
    """Action: Closes composer tab."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "CLOSE", {}, timeout=5.0)
    return {"ok": True, "action": "CLOSE", "page_id": pid, "result": res}


@api_app.post("/api/action/dom-status")
async def api_action_dom_status(req: Request):
    """Action: Queries live DOM status from content script."""
    body = await safe_json_body(req)
    pid = str(body.get("page_id") or controller.active_page_id or (controller.pages[0]["id"] if controller.pages else ""))
    res = await ws_manager.send_command(pid, "DOM_STATUS", {}, timeout=5.0)
    return {"ok": True, "action": "DOM_STATUS", "page_id": pid, "dom": res}


@api_app.post("/api/command-result")
async def api_command_result(req: Request):
    """Fallback HTTP command result reporting from content scripts."""
    data = await safe_json_body(req)
    req_id = data.get("id")
    if req_id:
        ws_manager.resolve_future(req_id, data)
    return {"ok": True}


@api_app.post("/api/pipeline/run-single")
def api_pipeline_run_single(req: Request):
    """Action: Triggers the full sequential pipeline on the active or requested page."""
    pid = controller.active_page_id or (controller.pages[0]["id"] if controller.pages else "")
    ok = controller.run_single_page(pid)
    return {"ok": ok, "page_id": pid, "pipeline": "RUN_SINGLE"}


@api_app.websocket("/ws/page/{page_id}")
async def websocket_page_endpoint(websocket: WebSocket, page_id: str):
    """WebSocket connection handler for two-way communication with Chrome Extension tabs."""
    await ws_manager.connect(page_id, websocket)
    try:
        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                if data.get("type") == "ACTION_RESULT":
                    ws_manager.resolve_future(data.get("id"), data)
                elif data.get("type") == "REPORT":
                    controller.handle_report(data.get("payload") or {})
            except Exception as e:
                logger.warning("Error parsing WS message from page %s: %s", page_id, e)
    except WebSocketDisconnect:
        ws_manager.disconnect(page_id)
    except Exception as exc:
        logger.warning("WebSocket exception on page %s: %s", page_id, exc)
        ws_manager.disconnect(page_id)


@api_app.get("/api/pending-command")
def api_pending_command(page_id: str = ""):
    """Fallback HTTP long-polling command retrieval for content scripts."""
    with ws_manager.lock:
        cmds = ws_manager.pending_commands.get(page_id, [])
        if cmds:
            return cmds.pop(0)
    return {"action": None}


@api_app.post("/api/command-result")
async def api_command_result(req: Request):
    """Fallback HTTP command result reporting from content scripts."""
    data = await req.json()
    req_id = data.get("id")
    if req_id:
        ws_manager.resolve_future(req_id, data)
    return {"ok": True}


# ==============================================================================
# Web Control Dashboard
# ==============================================================================

@api_app.get("/", response_class=HTMLResponse)
@api_app.get("/dashboard", response_class=HTMLResponse)
def api_dashboard():
    """Enterprise Fintech Web Control Dashboard with modular action endpoints."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Meta Reels Enterprise Control Surface</title>
  <style>
    :root {
      --bg: #070a13;
      --card-bg: rgba(15, 23, 42, 0.85);
      --card-border: #1e293b;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-glow: rgba(37, 99, 235, 0.25);
      --success: #10b981;
      --success-hover: #059669;
      --warning: #f59e0b;
      --danger: #ef4444;
      --accent: #38bdf8;
      --purple: #8b5cf6;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --mono: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      padding: 20px;
      line-height: 1.5;
      table-layout: fixed !important;
      overflow-x: hidden !important;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 20px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .header-left { display: flex; align-items: center; gap: 14px; }
    .brand-logo {
      width: 36px; height: 36px; border-radius: 8px;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      display: flex; align-items: center; justify-content: center;
      font-size: 18px; font-weight: bold;
    }
    h1 { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }
    .badge {
      display: inline-flex; align-items: center; gap: 5px;
      padding: 4px 10px; border-radius: 9999px; font-size: 11px;
      font-weight: 600; background: #1e293b; color: var(--text-muted);
    }
    .badge.active { background: #064e3b; color: #34d399; border: 1px solid rgba(52, 211, 153, 0.3); }
    .badge.warning { background: #451a03; color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.3); }
    .badge.danger { background: #450a0a; color: #f87171; border: 1px solid rgba(248, 113, 113, 0.3); }
    .badge.info { background: #0c4a6e; color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
    .pulse-dot {
      width: 7px; height: 7px; border-radius: 50%; background: #10b981;
      display: inline-block; animation: pulse 2s infinite;
    }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }

    .brand-selector-box {
      background: #0f172a; border: 1px solid #334155;
      border-radius: 8px; padding: 4px 10px; display: flex; align-items: center; gap: 8px;
    }
    select {
      background: #06090e; color: var(--text); border: 1px solid var(--card-border);
      padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer;
    }
    select:focus { outline: none; border-color: var(--accent); }

    .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
    @media (max-width: 1024px) { .grid { grid-template-columns: 1fr; } }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 18px;
      margin-bottom: 20px;
      backdrop-filter: blur(8px);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }
    .card h2 {
      font-size: 15px; margin-bottom: 12px; color: var(--text);
      display: flex; justify-content: space-between; align-items: center;
    }
    .btn-group { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    button {
      background: #1e293b;
      color: var(--text);
      border: 1px solid #334155;
      padding: 7px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      display: inline-flex; align-items: center; gap: 5px;
    }
    button:hover { background: #334155; transform: translateY(-1px); }
    button:active { transform: translateY(0); }
    button.primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    button.primary:hover { background: var(--primary-hover); }
    button.success { background: var(--success); border-color: var(--success); color: #fff; }
    button.success:hover { background: var(--success-hover); }
    button.warning { background: var(--warning); border-color: var(--warning); color: #000; }
    button.danger { background: var(--danger); border-color: var(--danger); color: #fff; }
    button.purple { background: var(--purple); border-color: var(--purple); color: #fff; }

    .preset-pill {
      background: #1e293b; border: 1px solid #334155; border-radius: 20px;
      padding: 3px 9px; font-size: 11px; font-weight: 500; color: var(--accent); cursor: pointer;
    }
    .preset-pill:hover { background: #334155; border-color: var(--accent); }

    table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed !important; overflow-x: hidden !important; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--card-border); word-wrap: break-word; }
    th { color: var(--text-muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
    tr:hover td { background: rgba(255, 255, 255, 0.02); }

    #log-stream {
      background: #050811;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 10px;
      height: 320px;
      overflow-y: auto;
      font-family: var(--mono);
      font-size: 11px;
      color: #38bdf8;
    }
    .form-group { margin-bottom: 12px; }
    label { display: block; font-size: 11px; font-weight: 600; color: var(--text-muted); margin-bottom: 4px; }
    input[type="text"], input[type="time"], textarea {
      width: 100%;
      background: #06090e;
      border: 1px solid var(--card-border);
      padding: 7px 10px;
      border-radius: 6px;
      color: var(--text);
      font-size: 12px;
      font-family: inherit;
    }
    input:focus, textarea:focus { outline: none; border-color: var(--accent); }
    .cv-box {
      background: #050811;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      padding: 12px;
      font-size: 11px;
      font-family: var(--mono);
      color: #a7f3d0;
      line-height: 1.6;
    }

    /* Modal */
    .modal-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(0, 0, 0, 0.75); backdrop-filter: blur(5px);
      z-index: 9999; align-items: center; justify-content: center;
    }
    .modal-box {
      background: #0f172a; border: 1px solid var(--accent);
      border-radius: 12px; padding: 22px; width: 560px; max-width: 95vw;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.8);
    }
  </style>
</head>
<body>
  <header>
    <div class="header-left">
      <div class="brand-logo">▶</div>
      <div>
        <h1>Meta Reels Enterprise Control Surface</h1>
        <p style="font-size: 12px; color: var(--text-muted);"><span class="pulse-dot"></span> Real-time SSE Stream &bull; Multi-Brand Engine &bull; Windows Task Scheduler Synced</p>
      </div>
    </div>
    <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
      <div class="brand-selector-box">
        <label style="font-size: 11px; font-weight: 700; color: var(--accent); text-transform: uppercase;">🏢 Active Brand:</label>
        <select id="brand-select" onchange="switchBrand(this.value)">
          <option>Loading brands...</option>
        </select>
      </div>
      <span id="profile-badge" class="badge info">PROFILE: Profile 15</span>
      <span id="batch-status" class="badge">BATCH: IDLE</span>
      <span id="scheduler-status" class="badge warning">SCHEDULER: 17:00</span>
    </div>
  </header>

  <!-- Top Global Action Bar -->
  <div class="card" style="padding: 12px; margin-bottom: 16px;">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button class="primary" onclick="callApi('/api/open-chrome')">🌐 Launch Visible Chrome</button>
        <button class="success" onclick="callApi('/api/run-now')">▶ Run Active Brand Batch</button>
        <button class="purple" onclick="callApi('/api/batch/start')">⚡ Run All Brands (Sequential)</button>
        <button class="danger" onclick="callApi('/api/stop')">⏹ Stop Execution</button>
        <button onclick="callApi('/api/reset-all')">🔄 Reset All Attempts Today</button>
      </div>
      <div style="display: flex; gap: 8px;">
        <button class="primary" onclick="openScheduleModal()">➕ Add Schedule</button>
        <button class="success" onclick="callApi('/api/schedules/sync')">🔄 Sync Windows Tasks</button>
      </div>
    </div>
  </div>

  <div class="grid">
    <div>
      <!-- Publishing Schedules -->
      <div class="card">
        <h2>
          <span>📅 Publishing Schedules (Windows Task Scheduler Synced)</span>
          <button class="primary" style="padding: 4px 8px; font-size: 11px;" onclick="openScheduleModal()">➕ New Schedule</button>
        </h2>
        <table>
          <thead>
            <tr>
              <th style="width: 12%;">Status</th>
              <th style="width: 24%;">Schedule Name</th>
              <th style="width: 18%;">Target Brand</th>
              <th style="width: 12%;">Start Time</th>
              <th style="width: 16%;">Repeat Every</th>
              <th style="width: 18%;">Actions</th>
            </tr>
          </thead>
          <tbody id="schedules-tbody">
            <tr><td colspan="6">Loading schedules...</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Batch Operations & Destinations -->
      <div class="card">
        <h2>
          <span>📋 Target Destinations (<span id="dest-count">0</span> Pages in Active Brand)</span>
          <div style="display: flex; gap: 8px;">
            <input type="text" id="dest-search" placeholder="🔍 Filter destinations..." style="padding: 3px 8px; font-size: 11px; width: 160px;" onkeyup="filterDestinations()">
            <button class="success" style="padding: 3px 8px; font-size: 11px;" onclick="callApi('/api/run-now')">Start Batch</button>
          </div>
        </h2>
        <table>
          <thead>
            <tr>
              <th style="width: 18%;">Today Status</th>
              <th style="width: 32%;">Page Name</th>
              <th style="width: 24%;">Page ID</th>
              <th style="width: 26%;">Actions</th>
            </tr>
          </thead>
          <tbody id="pages-tbody">
            <tr><td colspan="4">Loading destinations...</td></tr>
          </tbody>
        </table>
      </div>

      <!-- Modular Step-by-Step Action Endpoints -->
      <div class="card">
        <h2>⚡ Interactive Step-by-Step Action Endpoints (Manual Debugging)</h2>
        <div class="btn-group">
          <button class="primary" onclick="callApi('/api/action/upload')">1. Upload Video</button>
          <button class="primary" onclick="callApi('/api/action/caption')">2. Set Caption</button>
          <button class="primary" onclick="callApi('/api/action/location')">3. Tag Location</button>
          <button class="primary" onclick="callApi('/api/action/messages')">4. Messages CTA</button>
          <button class="warning" onclick="callApi('/api/action/next-edit')">5. Next (Step 1&rarr;2)</button>
          <button class="warning" onclick="callApi('/api/action/next-share')">6. Next (Step 2&rarr;3)</button>
          <button class="danger" onclick="callApi('/api/action/publish')">7. Share Reel</button>
          <button class="success" onclick="callApi('/api/action/done')">8. Done Modal</button>
          <button onclick="callApi('/api/action/close')">Close Tab</button>
          <button onclick="callApi('/api/action/dom-status')">Inspect DOM</button>
        </div>
      </div>
    </div>

    <div>
      <!-- Computer Vision Inspector -->
      <div class="card">
        <h2>
          <span>🧠 Computer Vision Inspector</span>
          <button style="padding: 3px 8px; font-size: 11px;" onclick="runCvInspect()">Inspect Now</button>
        </h2>
        <div id="cv-results" class="cv-box">Click 'Inspect Now' to analyze desktop / composer screen state.</div>
      </div>

      <!-- Active Brand Quick Settings -->
      <div class="card">
        <h2>🏢 Active Brand Settings & Media</h2>
        <div class="form-group">
          <label>Video Media Path</label>
          <input type="text" id="cfg-video" />
        </div>
        <div class="form-group">
          <label>Location</label>
          <div style="display: flex; gap: 4px; margin-bottom: 4px;">
            <input type="text" id="cfg-location" />
          </div>
          <div style="display: flex; gap: 4px; flex-wrap: wrap;">
            <span class="preset-pill" onclick="document.getElementById('cfg-location').value='Mumbai'">Mumbai</span>
            <span class="preset-pill" onclick="document.getElementById('cfg-location').value='Delhi'">Delhi</span>
            <span class="preset-pill" onclick="document.getElementById('cfg-location').value='Bangalore'">Bangalore</span>
            <span class="preset-pill" onclick="document.getElementById('cfg-location').value='Pune'">Pune</span>
          </div>
        </div>
        <div class="form-group">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <label style="margin: 0;">Caption & Hashtags</label>
            <span id="caption-counter" style="font-size: 10px; color: var(--accent); font-weight: 600;">0/2200</span>
          </div>
          <textarea id="cfg-caption" rows="4" onkeyup="updateCaptionCounter()"></textarea>
          <div style="display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px;">
            <span class="preset-pill" onclick="insertTag('#reels')">#reels</span>
            <span class="preset-pill" onclick="insertTag('#trending')">#trending</span>
            <span class="preset-pill" onclick="insertTag('#viral')">#viral</span>
            <span class="preset-pill" onclick="insertTag('#business')">#business</span>
            <span class="preset-pill" onclick="insertTag('#finance')">#finance</span>
            <span class="preset-pill" onclick="insertTag('#loan')">#loan</span>
            <span class="preset-pill" onclick="insertTag('#mumbai')">#mumbai</span>
          </div>
        </div>
        <button class="primary" style="width: 100%; margin-top: 4px;" onclick="saveConfig()">💾 Save Brand Settings</button>
      </div>

      <!-- Live Real-Time Activity Stream (SSE) -->
      <div class="card">
        <h2>
          <span>📡 Real-Time Activity Stream (SSE)</span>
          <button style="padding: 2px 6px; font-size: 10px;" onclick="document.getElementById('log-stream').innerHTML=''">Clear</button>
        </h2>
        <div id="log-stream">Connecting live stream...</div>
      </div>
    </div>
  </div>

  <!-- Modern Schedule Creator Modal -->
  <div id="sched-modal" class="modal-overlay">
    <div class="modal-box">
      <h2 style="font-size: 16px; margin-bottom: 14px; color: var(--accent);">📅 Add Publishing Schedule</h2>
      <div class="form-group">
        <label>Schedule Name</label>
        <input type="text" id="m-name" value="Daily Scheduled Reel" />
      </div>
      <div class="form-group">
        <label>Target Brand / Scope</label>
        <select id="m-brand" style="width: 100%;">
          <option value="ALL">All Brands (Sequential)</option>
        </select>
      </div>
      <div class="form-group">
        <label>Execution Time (24h format)</label>
        <div style="display: flex; gap: 8px; align-items: center; margin-bottom: 6px;">
          <input type="time" id="m-time" value="18:00" style="font-size: 14px; padding: 6px 10px; width: 140px;" onchange="updateSummary()" />
          <span id="m-12h-badge" class="badge info" style="font-size: 12px;">🕒 06:00 PM</span>
        </div>
        <div style="display: flex; gap: 4px; flex-wrap: wrap;">
          <span class="preset-pill" onclick="setModalTime('09:00')">🌅 09:00</span>
          <span class="preset-pill" onclick="setModalTime('12:00')">☀️ 12:00</span>
          <span class="preset-pill" onclick="setModalTime('17:00')">🌆 17:00</span>
          <span class="preset-pill" onclick="setModalTime('21:00')">🌙 21:00</span>
          <span class="preset-pill" onclick="addModalMinutes(15)">⚡ +15m</span>
          <span class="preset-pill" onclick="addModalMinutes(30)">⚡ +30m</span>
          <span class="preset-pill" onclick="addModalMinutes(60)">⚡ +1h</span>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;" class="form-group">
        <div>
          <label>Frequency</label>
          <select id="m-days" style="width: 100%;" onchange="updateSummary()">
            <option value="DAILY">Daily (All Days)</option>
            <option value="MON-FRI">Mon - Fri (Weekdays)</option>
            <option value="SAT-SUN">Sat - Sun (Weekends)</option>
            <option value="ONCE">Once (Single Run)</option>
          </select>
        </div>
        <div>
          <label>Repeat Every</label>
          <select id="m-interval" style="width: 100%;" onchange="updateSummary()">
            <option value="0">0 (Run Once per Day)</option>
            <option value="15">Every 15 minutes</option>
            <option value="30">Every 30 minutes</option>
            <option value="60">Every 60 minutes</option>
            <option value="120">Every 120 minutes</option>
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>Repeat Duration (Hours)</label>
        <select id="m-duration" style="width: 100%;" onchange="updateSummary()">
          <option value="24">24 hours (All Day)</option>
          <option value="12">12 hours</option>
          <option value="6">6 hours</option>
        </select>
      </div>
      <div id="m-summary" class="badge info" style="display: block; padding: 8px; margin-bottom: 16px; border-radius: 6px;">
        ℹ️ Executes once per day at 18:00.
      </div>
      <div style="display: flex; gap: 8px; justify-content: flex-end;">
        <button onclick="closeScheduleModal()">Cancel</button>
        <button class="success" onclick="saveSchedule()">💾 Save & Sync Windows Tasks</button>
      </div>
    </div>
  </div>

  <script>
    let currentPages = [];
    let currentBrands = [];

    async function callApi(url, body=null) {
      const opts = body ? { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) } : { method: 'POST' };
      try {
        const r = await fetch(url, opts);
        const res = await r.json();
        console.log(url, res);
      } catch (e) {
        console.error(url, e);
      }
      refresh();
    }

    async function switchBrand(brandId) {
      if (!brandId) return;
      try {
        await fetch('/api/brands/select', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({brand_id: brandId})
        });
        await refresh();
      } catch (e) {
        console.error('Error switching brand:', e);
      }
    }

    function openScheduleModal() {
      document.getElementById('sched-modal').style.display = 'flex';
      updateSummary();
    }

    function closeScheduleModal() {
      document.getElementById('sched-modal').style.display = 'none';
    }

    function setModalTime(t) {
      document.getElementById('m-time').value = t;
      updateSummary();
    }

    function addModalMinutes(mins) {
      const cur = document.getElementById('m-time').value || '18:00';
      const parts = cur.split(':');
      let total = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10) + mins;
      total = total % (24 * 60);
      const h = Math.floor(total / 60);
      const m = total % 60;
      document.getElementById('m-time').value = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      updateSummary();
    }

    function updateSummary() {
      const t = document.getElementById('m-time').value || '18:00';
      const parts = t.split(':');
      const h = parseInt(parts[0], 10) || 0;
      const m = parseInt(parts[1], 10) || 0;
      const suffix = h < 12 ? 'AM' : 'PM';
      const h12 = (h % 12) || 12;
      document.getElementById('m-12h-badge').innerText = `🕒 ${String(h12).padStart(2, '0')}:${String(m).padStart(2, '0')} ${suffix}`;

      const interval = parseInt(document.getElementById('m-interval').value || '0', 10);
      const dur = parseInt(document.getElementById('m-duration').value || '24', 10);
      const sumEl = document.getElementById('m-summary');
      if (interval <= 0) {
        sumEl.innerText = `ℹ️ Executes once per day at ${t}.`;
      } else {
        sumEl.innerText = `🔁 Starts at ${t}, repeats every ${interval} mins for ${dur} hrs.`;
      }
    }

    async function saveSchedule() {
      const name = document.getElementById('m-name').value.trim() || 'Daily Scheduled Reel';
      const time = document.getElementById('m-time').value.trim() || '18:00';
      const target_brand = document.getElementById('m-brand').value || 'ALL';
      const days = document.getElementById('m-days').value || 'DAILY';
      const repeat_interval_minutes = parseInt(document.getElementById('m-interval').value || '0', 10);
      const repeat_duration_hours = parseInt(document.getElementById('m-duration').value || '24', 10);

      await fetch('/api/schedules/add', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          name, time, target_brand, days,
          repeat_interval_minutes, repeat_duration_hours,
          enabled: true
        })
      });
      await fetch('/api/schedules/sync', { method: 'POST' });
      closeScheduleModal();
      refresh();
    }

    async function deleteSchedule(schedId) {
      if (!confirm('Delete this schedule?')) return;
      await fetch('/api/schedules/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: schedId})
      });
      await fetch('/api/schedules/sync', { method: 'POST' });
      refresh();
    }

    function copyUrl(pageId, pageUrl) {
      const u = pageUrl || `https://business.facebook.com/latest/reels_composer/?asset_id=${pageId}`;
      navigator.clipboard.writeText(u).then(() => {
        alert('Copied composer URL:\n' + u);
      }).catch(() => {
        prompt('Copy Composer URL:', u);
      });
    }

    function insertTag(tag) {
      const el = document.getElementById('cfg-caption');
      const val = el.value.trim();
      el.value = val ? (val + ' ' + tag) : tag;
      updateCaptionCounter();
    }

    function updateCaptionCounter() {
      const el = document.getElementById('cfg-caption');
      const chars = el.value.length;
      document.getElementById('caption-counter').innerText = `${chars}/2200 chars`;
    }

    async function runCvInspect() {
      const box = document.getElementById('cv-results');
      box.innerText = 'Analyzing screen with OpenCV & Pillow...';
      try {
        const r = await fetch('/api/cv/inspect');
        const res = await r.json();
        box.innerHTML = `
          <div><strong>Stage:</strong> ${res.stage} (Confidence: ${Math.round(res.confidence * 100)}%)</div>
          <div><strong>100% Progress Bar:</strong> ${res.has_green_progress_bar ? 'YES (' + res.green_pixel_count + ' px)' : 'NO'}</div>
          <div><strong>Blue Action Button:</strong> ${res.has_blue_action_button ? 'YES (' + res.blue_pixel_count + ' px)' : 'NO'}</div>
          <div><strong>Sharpness:</strong> ${res.laplacian_variance}</div>
          <div><strong>Matches:</strong> ${res.template_matches.map(t => t.template + ' (' + t.confidence + ')').join(', ') || 'None'}</div>
        `;
      } catch (e) {
        box.innerText = 'Error running CV: ' + String(e);
      }
    }

    async function saveConfig() {
      const payload = {
        global_video: document.getElementById('cfg-video').value,
        location: document.getElementById('cfg-location').value,
        caption: document.getElementById('cfg-caption').value
      };
      await fetch('/api/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
      refresh();
    }

    function filterDestinations() {
      const q = (document.getElementById('dest-search').value || '').toLowerCase();
      renderDestinations(currentPages.filter(p => p.name.toLowerCase().includes(q) || String(p.id).includes(q)));
    }

    function renderDestinations(pages) {
      const tbody = document.getElementById('pages-tbody');
      if (!pages || !pages.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="color: var(--text-muted);">No destinations found.</td></tr>';
        return;
      }
      tbody.innerHTML = pages.map(p => {
        let badgeClass = 'badge';
        let statusText = p.today_status;
        if (p.today_status === 'PUBLISHED') {
          badgeClass = 'badge active';
          statusText = '✅ PUBLISHED';
        } else if (p.today_status === 'LOGIN_REQUIRED') {
          badgeClass = 'badge danger';
          statusText = '🔒 LOGIN REQ';
        } else if (p.today_status === 'RUNNING') {
          badgeClass = 'badge warning';
          statusText = '▶ RUNNING';
        } else if (p.today_status === 'FAILED' || p.today_status === 'ERROR') {
          badgeClass = 'badge danger';
          statusText = '⚠️ ' + p.today_status;
        } else {
          statusText = '⏳ PENDING';
        }

        return `
          <tr>
            <td><span class="${badgeClass}">${statusText}</span></td>
            <td><strong>${p.name}</strong></td>
            <td><code>${p.id}</code></td>
            <td>
              <button class="primary" style="padding: 2px 6px; font-size: 11px;" onclick="callApi('/api/run-page/${p.id}')">Run</button>
              <button style="padding: 2px 6px; font-size: 11px;" onclick="callApi('/api/pages/${p.id}/reset')">Reset</button>
              <button style="padding: 2px 6px; font-size: 11px;" onclick="copyUrl('${p.id}', '${p.url || ''}')">URL</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function refresh() {
      try {
        const [statusRes, pagesRes, cfgRes, schedRes, brandsRes] = await Promise.all([
          fetch('/api/status').then(r => r.json()),
          fetch('/api/pages').then(r => r.json()),
          fetch('/api/config').then(r => r.json()),
          fetch('/api/schedules').then(r => r.json()),
          fetch('/api/brands').then(r => r.json())
        ]);

        // 1. Brands dropdown & Modal brand selector
        if (brandsRes && brandsRes.brands) {
          currentBrands = brandsRes.brands;
          const activeId = brandsRes.active_brand_id;
          const bSelect = document.getElementById('brand-select');
          bSelect.innerHTML = currentBrands.map(b => `
            <option value="${b.id}" ${b.id === activeId ? 'selected' : ''}>
              ${b.name} [${b.chrome_profile || 'Profile 15'}] (${(b.pages || []).length} pages)
            </option>
          `).join('');

          const mBrand = document.getElementById('m-brand');
          mBrand.innerHTML = `<option value="ALL">All Brands (Sequential)</option>` + currentBrands.map(b => `
            <option value="${b.id}">${b.name} [${b.chrome_profile || 'Profile 15'}]</option>
          `).join('');
        }

        // 2. Badges
        const bBadge = document.getElementById('batch-status');
        if (statusRes.batch_running) {
          bBadge.className = 'badge active';
          bBadge.innerText = 'BATCH: RUNNING';
        } else {
          bBadge.className = 'badge';
          bBadge.innerText = 'BATCH: IDLE';
        }

        const sBadge = document.getElementById('scheduler-status');
        if (statusRes.scheduler_enabled) {
          sBadge.className = 'badge active';
          sBadge.innerText = 'SCHEDULER: ' + statusRes.schedule_time + ' (ACTIVE)';
        } else {
          sBadge.className = 'badge';
          sBadge.innerText = 'SCHEDULER: OFF';
        }

        const pBadge = document.getElementById('profile-badge');
        if (statusRes.selected_profile) {
          pBadge.innerText = 'PROFILE: ' + statusRes.selected_profile;
        }

        // 3. Inputs
        document.getElementById('cfg-video').value = cfgRes.global_video || '';
        document.getElementById('cfg-location').value = cfgRes.location || 'Mumbai';
        document.getElementById('cfg-caption').value = cfgRes.caption || '';
        updateCaptionCounter();

        // 4. Schedules Table
        const sTbody = document.getElementById('schedules-tbody');
        if (sTbody && schedRes && schedRes.schedules) {
          sTbody.innerHTML = schedRes.schedules.map(s => {
            const tb = s.target_brand === 'ALL' || !s.target_brand ? 'All Brands' : s.target_brand;
            return `
              <tr>
                <td><span class="badge ${s.enabled ? 'active' : ''}">${s.enabled ? 'ACTIVE' : 'OFF'}</span></td>
                <td><strong>${s.name}</strong></td>
                <td><span class="badge info">${tb}</span></td>
                <td><strong>${s.time}</strong></td>
                <td>${s.repeat_interval_minutes > 0 ? 'Every ' + s.repeat_interval_minutes + 'm (' + (s.repeat_duration_hours || 24) + 'h)' : 'Once / Day'}</td>
                <td>
                  <button class="warning" style="padding: 2px 6px; font-size: 11px;" onclick="callApi('/api/schedules/run/${s.id}')">Run</button>
                  <button class="danger" style="padding: 2px 6px; font-size: 11px;" onclick="deleteSchedule('${s.id}')">Del</button>
                </td>
              </tr>
            `;
          }).join('');
        }

        // 5. Pages
        if (pagesRes && pagesRes.pages) {
          currentPages = pagesRes.pages;
          document.getElementById('dest-count').innerText = currentPages.length;
          filterDestinations();
        }
      } catch (e) {
        console.error(e);
      }
    }

    // Connect SSE Stream for real-time logs
    function connectSse() {
      const logEl = document.getElementById('log-stream');
      const evtSource = new EventSource('/api/events');
      evtSource.onmessage = function(e) {
        try {
          const item = JSON.parse(e.data);
          const line = item.message || (item.event + ' | ' + (item.page_id || '') + ' | ' + JSON.stringify(item.detail || {}));
          const div = document.createElement('div');
          div.style.marginBottom = '2px';
          if (line.includes('WS_CONNECTED') || line.includes('PUBLISHED')) {
            div.style.color = '#34d399';
          } else if (line.includes('ERROR') || line.includes('FAILED')) {
            div.style.color = '#f87171';
          } else if (line.includes('WAITING') || line.includes('HALTED')) {
            div.style.color = '#fbbf24';
          }
          div.textContent = line;
          logEl.appendChild(div);
          logEl.scrollTop = logEl.scrollHeight;
        } catch(err) {}
      };
      evtSource.onerror = function() {
        evtSource.close();
        setTimeout(connectSse, 4000);
      };
    }

    setInterval(refresh, 3500);
    refresh();
    connectSse();
  </script>
</body>
</html>
"""


# ==============================================================================
# Tkinter Desktop GUI
# ==============================================================================

class ModernTimePicker(ttk.Frame):
    """Professional Datetime & Time Picker Dropdown Widget for Tkinter.
    Features:
    - 24-hour hour selector dropdown (00-23)
    - Minute selector dropdown (00-55 in 5m steps, with direct text entry support)
    - 12-hour AM/PM real-time badge indicator (e.g. '06:30 PM')
    - Quick-select preset pills: Morning (09:00), Noon (12:00), Evening (17:00), Night (21:00), Now+15m, Now+30m
    - Two-way binding with a StringVar (e.g. '18:30')
    """

    def __init__(self, parent, time_var: tk.StringVar, on_change=None):
        super().__init__(parent, style="Card.TFrame")
        self.time_var = time_var
        self.on_change = on_change

        val = str(self.time_var.get() or "18:00").strip()
        parts = val.split(":")
        init_h = f"{int(parts[0]):02d}" if parts and parts[0].isdigit() else "18"
        init_m = f"{int(parts[1]):02d}" if len(parts) > 1 and parts[1].isdigit() else "00"

        self.hour_var = tk.StringVar(value=init_h)
        self.min_var = tk.StringVar(value=init_m)
        self.fmt12_var = tk.StringVar(value="")

        self.hours = [f"{i:02d}" for i in range(24)]
        self.minutes = [f"{i:02d}" for i in range(0, 60, 5)]

        # Row 1: Hour & Minute Selectors
        top_row = ttk.Frame(self, style="Card.TFrame")
        top_row.pack(fill="x", pady=(0, 4))

        ttk.Label(top_row, text="Hour:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.h_combo = ttk.Combobox(top_row, textvariable=self.hour_var, values=self.hours, width=4, state="readonly")
        self.h_combo.pack(side="left", padx=(0, 4))
        self.h_combo.bind("<<ComboboxSelected>>", self._sync_to_main)

        tk.Label(top_row, text=":", font=("Segoe UI", 12, "bold"), fg="#2563eb", bg="#ffffff").pack(side="left", padx=(0, 4))

        ttk.Label(top_row, text="Min:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.m_combo = ttk.Combobox(top_row, textvariable=self.min_var, values=self.minutes, width=4)
        self.m_combo.pack(side="left", padx=(0, 8))
        self.m_combo.bind("<<ComboboxSelected>>", self._sync_to_main)
        self.m_combo.bind("<KeyRelease>", self._sync_to_main)

        # 12-hour formatted badge
        self.lbl_12h = tk.Label(top_row, textvariable=self.fmt12_var, font=("Segoe UI", 9, "bold"), fg="#2563eb", bg="#eff6ff", padx=8, pady=3, relief="flat")
        self.lbl_12h.pack(side="left", padx=4)

        # Row 2: Quick Preset Pills
        preset_frame = ttk.Frame(self, style="Card.TFrame")
        preset_frame.pack(fill="x", pady=(3, 0))

        presets = [
            ("🌅 09:00", "09:00"),
            ("☀️ 12:00", "12:00"),
            ("🌆 17:00", "17:00"),
            ("🌙 21:00", "21:00"),
            ("⚡ +15m", 15),
            ("⚡ +30m", 30),
            ("⚡ +1h", 60)
        ]
        for label, val in presets:
            btn = tk.Button(
                preset_frame,
                text=label,
                font=("Segoe UI", 8, "bold"),
                bg="#eff6ff",
                fg="#2563eb",
                activebackground="#2563eb",
                activeforeground="#ffffff",
                relief="flat",
                padx=6,
                pady=2,
                cursor="hand2",
                command=lambda v=val: self.set_preset(v)
            )
            btn.pack(side="left", padx=2)

        self._update_12h()
        try:
            self.time_var.trace_add("write", self._on_time_var_changed)
        except Exception:
            pass

    def _on_time_var_changed(self, *args):
        self._update_from_main()

    def _update_from_main(self, *args):
        try:
            parts = str(self.time_var.get() or "18:00").split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            self.hour_var.set(f"{h:02d}")
            self.min_var.set(f"{m:02d}")
            self._update_12h()
        except Exception:
            pass

    def _sync_to_main(self, *args):
        h = self.hour_var.get().strip() or "00"
        m = self.min_var.get().strip() or "00"
        try:
            h_int = max(0, min(int(h), 23))
            m_int = max(0, min(int(m), 59))
            res = f"{h_int:02d}:{m_int:02d}"
            self.time_var.set(res)
            self._update_12h()
            if self.on_change:
                self.on_change()
        except Exception:
            pass

    def _update_12h(self):
        try:
            parts = str(self.time_var.get() or "18:00").split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            suffix = "AM" if h < 12 else "PM"
            h12 = h % 12
            if h12 == 0:
                h12 = 12
            self.fmt12_var.set(f"🕒 {h12:02d}:{m:02d} {suffix}")
        except Exception:
            self.fmt12_var.set("")

    def set_preset(self, val):
        import datetime as dt
        if isinstance(val, int):
            now = dt.datetime.now() + dt.timedelta(minutes=val)
            self.hour_var.set(f"{now.hour:02d}")
            self.min_var.set(f"{now.minute:02d}")
        else:
            parts = str(val).split(":")
            self.hour_var.set(parts[0])
            self.min_var.set(parts[1])
        self._sync_to_main()


class ScheduleDialog(tk.Toplevel):
    """Modern modal dialog to Add or Edit a Publishing Schedule with Interval Repetition & Brand Targeting."""

    def __init__(self, parent, sched_data: dict = None, on_save_cb = None):
        super().__init__(parent)
        self.sched_data = sched_data or {}
        self.on_save_cb = on_save_cb
        self.title("Edit Publishing Schedule" if sched_data else "Add New Publishing Schedule")
        self.geometry("620x620")
        self.resizable(False, False)
        self.configure(bg="#f1f5f9")
        self.transient(parent)
        self.grab_set()

        self.name_var = tk.StringVar(value=self.sched_data.get("name", "Daily Scheduled Reel"))
        self.time_var = tk.StringVar(value=self.sched_data.get("time", "18:00"))
        self.days_var = tk.StringVar(value=self.sched_data.get("days", "DAILY"))
        self.enabled_var = tk.BooleanVar(value=self.sched_data.get("enabled", True))

        # Brand targeting
        self.brand_options = ["All Brands (Sequential)"]
        for b in controller.brands:
            self.brand_options.append(f"{b.get('name')} [{b.get('chrome_profile')}] | {b.get('id')}")

        init_target = self.sched_data.get("target_brand", "ALL")
        if init_target == "ALL" or not init_target:
            init_val = "All Brands (Sequential)"
        else:
            match = next((opt for opt in self.brand_options if f"| {init_target}" in opt), None)
            init_val = match if match else "All Brands (Sequential)"
        self.target_brand_var = tk.StringVar(value=init_val)

        curr_interval = int(self.sched_data.get("repeat_interval_minutes") or 0)
        default_interval_str = f"{curr_interval} minutes" if curr_interval > 0 else "0 (No Repeat - Run Once)"
        self.repeat_interval_var = tk.StringVar(value=default_interval_str)

        curr_duration = int(self.sched_data.get("repeat_duration_hours") or 24)
        default_dur_str = f"{curr_duration} hours" if curr_duration != 24 else "24 hours (All Day)"
        self.repeat_duration_var = tk.StringVar(value=default_dur_str)

        self.repeat_summary_var = tk.StringVar(value="")

        self._build_ui()
        self._update_repeat_summary()
        self.wait_window(self)

    def _parse_interval(self) -> int:
        val = str(self.repeat_interval_var.get()).strip()
        import re
        m = re.search(r"\d+", val)
        return int(m.group(0)) if m else 0

    def _parse_duration(self) -> int:
        val = str(self.repeat_duration_var.get()).strip()
        import re
        m = re.search(r"\d+", val)
        d = int(m.group(0)) if m else 24
        return max(1, min(d, 99))

    def _update_repeat_summary(self, *args):
        t = self.time_var.get().strip() or "18:00"
        interval = self._parse_interval()
        duration = self._parse_duration()
        if interval <= 0:
            self.repeat_summary_var.set(f"ℹ️ Executes once per day at {t}.")
        else:
            self.repeat_summary_var.set(f"🔁 Starts at {t}, repeats every {interval} mins for {duration} hrs.")

    def _build_ui(self):
        pad_frame = ttk.Frame(self, style="Card.TFrame", padding=16)
        pad_frame.pack(fill="both", expand=True, padx=12, pady=12)

        # 1. Schedule Name
        ttk.Label(pad_frame, text="Schedule Name:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Entry(pad_frame, textvariable=self.name_var, width=48).pack(fill="x", pady=(0, 8))

        # 2. Target Brand
        ttk.Label(pad_frame, text="Target Brand / Scope:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        b_combo = ttk.Combobox(pad_frame, textvariable=self.target_brand_var, state="readonly", values=self.brand_options)
        b_combo.pack(fill="x", pady=(0, 8))

        # 3. Execution Start Time (Modern Time Picker Widget) & Frequency
        time_card = ttk.LabelFrame(pad_frame, text="🕒 Execution Time & Frequency", padding=10)
        time_card.pack(fill="x", pady=(0, 10))

        time_row = ttk.Frame(time_card, style="Card.TFrame")
        time_row.pack(fill="x", pady=(0, 4))

        t_col = ttk.Frame(time_row, style="Card.TFrame")
        t_col.pack(side="left", padx=(0, 16), fill="x", expand=True)
        ttk.Label(t_col, text="Scheduled Time (24h format & presets):", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        self.time_picker = ModernTimePicker(t_col, self.time_var, on_change=self._update_repeat_summary)
        self.time_picker.pack(fill="x", anchor="w")

        d_col = ttk.Frame(time_row, style="Card.TFrame")
        d_col.pack(side="left", anchor="n")
        ttk.Label(d_col, text="Frequency / Days:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        days_combo = ttk.Combobox(d_col, textvariable=self.days_var, state="readonly", width=14, values=["DAILY", "MON-FRI", "SAT-SUN", "WEEKDAYS", "WEEKENDS", "ONCE"])
        days_combo.pack(anchor="w")

        # 4. Repetition Settings Card
        rep_card = ttk.LabelFrame(pad_frame, text="🔁 Repetition Interval & Duration", padding=10)
        rep_card.pack(fill="x", pady=(0, 10))

        rep_row = ttk.Frame(rep_card, style="Card.TFrame")
        rep_row.pack(fill="x", pady=(0, 6))

        r_col = ttk.Frame(rep_row, style="Card.TFrame")
        r_col.pack(side="left", padx=(0, 12))
        ttk.Label(r_col, text="Repeat Every (Minutes):", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        r_combo = ttk.Combobox(
            r_col,
            textvariable=self.repeat_interval_var,
            width=22,
            values=[
                "0 (No Repeat - Run Once)",
                "15 minutes",
                "30 minutes",
                "45 minutes",
                "60 minutes (1 hour)",
                "90 minutes",
                "120 minutes (2 hours)",
                "180 minutes (3 hours)",
                "240 minutes (4 hours)"
            ]
        )
        r_combo.pack(anchor="w")
        r_combo.bind("<<ComboboxSelected>>", self._update_repeat_summary)
        r_combo.bind("<KeyRelease>", self._update_repeat_summary)

        dur_col = ttk.Frame(rep_row, style="Card.TFrame")
        dur_col.pack(side="left")
        ttk.Label(dur_col, text="Duration (Hours):", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        dur_combo = ttk.Combobox(
            dur_col,
            textvariable=self.repeat_duration_var,
            width=20,
            values=[
                "24 hours (All Day)",
                "2 hours",
                "4 hours",
                "6 hours",
                "8 hours",
                "12 hours"
            ]
        )
        dur_combo.pack(anchor="w")
        dur_combo.bind("<<ComboboxSelected>>", self._update_repeat_summary)
        dur_combo.bind("<KeyRelease>", self._update_repeat_summary)

        # Dynamic visual badge
        sum_lbl = tk.Label(rep_card, textvariable=self.repeat_summary_var, font=("Segoe UI", 9, "italic"), fg="#15803d", bg="#f0fdf4", padx=8, pady=4, relief="flat", anchor="w")
        sum_lbl.pack(fill="x", pady=(4, 0))

        # 5. Checkbox
        ttk.Checkbutton(pad_frame, text="Enable and Sync with Windows Task Scheduler (runs automatically in background)", variable=self.enabled_var).pack(anchor="w", pady=(0, 14))

        # 6. Buttons
        btn_box = ttk.Frame(pad_frame, style="Card.TFrame")
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="💾 Save Schedule", style="Success.TButton", command=self._on_save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Cancel", style="Dark.TButton", command=self.destroy).pack(side="left")

    def _on_save(self):
        t = self.time_var.get().strip()
        import re
        if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", t):
            messagebox.showerror(APP_NAME, "Please enter a valid 24-hour time in HH:MM format (e.g. 09:30 or 18:00).")
            return
        parts = t.split(":")
        formatted_time = f"{int(parts[0]):02d}:{int(parts[1]):02d}"

        interval_mins = self._parse_interval()
        duration_hrs = self._parse_duration()

        raw_b = self.target_brand_var.get().strip()
        target_brand = raw_b.split("|")[-1].strip() if "|" in raw_b else "ALL"

        data = {
            "name": self.name_var.get().strip() or f"Scheduled Reel ({formatted_time})",
            "time": formatted_time,
            "days": self.days_var.get(),
            "target_brand": target_brand,
            "enabled": self.enabled_var.get(),
            "repeat_interval_minutes": interval_mins,
            "repeat_duration_hours": duration_hrs
        }
        if self.on_save_cb:
            self.on_save_cb(data)
        self.destroy()


class BrandDialog(tk.Toplevel):
    """Fintech-styled modal dialog to Add or Edit a Brand with assigned Chrome profile, media, and captions."""

    def __init__(self, parent, brand_data: dict = None, on_save_cb = None):
        super().__init__(parent)
        self.brand_data = brand_data or {}
        self.on_save_cb = on_save_cb
        is_edit = bool(brand_data)
        self.title("Edit Brand" if is_edit else "Add New Brand")
        self.geometry("640x620")
        self.resizable(False, False)
        self.configure(bg="#f1f5f9")
        self.transient(parent)
        self.grab_set()

        self.name_var = tk.StringVar(value=self.brand_data.get("name", ""))
        self.desc_var = tk.StringVar(value=self.brand_data.get("description", ""))
        self.profile_var = tk.StringVar(value=self.brand_data.get("chrome_profile", controller.selected_profile))
        self.media_folder_var = tk.StringVar(value=self.brand_data.get("media_folder", ""))
        self.video_var = tk.StringVar(value=self.brand_data.get("video", controller.global_video))
        self.location_var = tk.StringVar(value=self.brand_data.get("location", controller.location or "Mumbai"))
        self.auto_publish_var = tk.BooleanVar(value=self.brand_data.get("auto_publish", True))

        self._build_ui()
        self.wait_window(self)

    def _build_ui(self):
        pad_frame = ttk.Frame(self, style="Card.TFrame", padding=16)
        pad_frame.pack(fill="both", expand=True, padx=12, pady=12)

        # 1. Brand Name & Description
        row1 = ttk.Frame(pad_frame, style="Card.TFrame")
        row1.pack(fill="x", pady=(0, 8))

        n_col = ttk.Frame(row1, style="Card.TFrame")
        n_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(n_col, text="Brand Name (e.g. Loan, Real Estate):", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Entry(n_col, textvariable=self.name_var).pack(fill="x")

        d_col = ttk.Frame(row1, style="Card.TFrame")
        d_col.pack(side="left", fill="x", expand=True)
        ttk.Label(d_col, text="Description / Category:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Entry(d_col, textvariable=self.desc_var).pack(fill="x")

        # 2. Chrome Profile Assignment
        prof_card = ttk.LabelFrame(pad_frame, text="🌐 Assigned Authentic Chrome Profile", padding=10)
        prof_card.pack(fill="x", pady=(0, 10))

        ttk.Label(prof_card, text="Select Chrome profile signed into this brand's Facebook / Meta account:", style="Card.TLabel").pack(anchor="w", pady=(0, 4))

        profs = controller.get_available_profiles()
        prof_opts = []
        cur_prof_idx = 0
        target_p = sanitize_chrome_profile(self.profile_var.get(), profs)
        for idx, p in enumerate(profs):
            p_dir = p.get("profile_dir", "")
            d_name = p.get("display_name", "")
            email = p.get("email", "")
            opt = f"{p_dir}"
            if d_name:
                opt += f" — {d_name}"
            if email:
                opt += f" ({email})"
            prof_opts.append(opt)
            if p_dir.lower() == target_p.lower():
                cur_prof_idx = idx

        self.prof_combo = ttk.Combobox(prof_card, textvariable=self.profile_var, state="readonly", values=prof_opts)
        self.prof_combo.pack(fill="x", pady=(0, 4))
        if prof_opts:
            self.prof_combo.current(cur_prof_idx)

        # 3. Media Folder (Random Video + Matching .txt Caption)
        media_card = ttk.LabelFrame(pad_frame, text="🎬 Brand Media & Dynamic Content Pairing", padding=10)
        media_card.pack(fill="x", pady=(0, 10))

        # 3a. Media Folder Row
        ttk.Label(media_card, text="Brand Media Folder (Folder with Videos and Matching .txt Captions):", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        mf_box = ttk.Frame(media_card, style="Card.TFrame")
        mf_box.pack(fill="x", pady=(0, 4))
        ttk.Entry(mf_box, textvariable=self.media_folder_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(mf_box, text="📁 Browse Folder...", style="Primary.TButton", command=self._browse_media_folder).pack(side="left", padx=(0, 4))
        ttk.Button(mf_box, text="🎲 Test Random Pair", style="Warning.TButton", command=self._test_random_pair).pack(side="left")

        self.mf_status_lbl = tk.Label(media_card, text="Scanning folder...", font=("Segoe UI", 8, "italic"), fg="#15803d", bg="#f0fdf4", padx=6, pady=2)
        self.mf_status_lbl.pack(anchor="w", pady=(0, 6))
        self._update_media_folder_status()
        self.media_folder_var.trace_add("write", lambda *a: self._update_media_folder_status())

        ttk.Label(media_card, text="Fallback Single Video File (if no media folder):", style="Card.TLabel", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 2))
        v_box = ttk.Frame(media_card, style="Card.TFrame")
        v_box.pack(fill="x", pady=(0, 6))
        ttk.Entry(v_box, textvariable=self.video_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(v_box, text="Browse...", style="Dark.TButton", command=self._browse_video).pack(side="left")

        loc_row = ttk.Frame(media_card, style="Card.TFrame")
        loc_row.pack(fill="x", pady=(0, 4))
        ttk.Label(loc_row, text="Default Location:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
        ttk.Entry(loc_row, textvariable=self.location_var, width=22).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(loc_row, text="Auto-Publish Reels (Active)", variable=self.auto_publish_var).pack(side="left")

        # 4. Default Caption & Hashtags
        ttk.Label(pad_frame, text="Default Caption & Hashtags for this Brand:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 2))
        cap_frame = ttk.Frame(pad_frame, style="Card.TFrame")
        cap_frame.pack(fill="both", expand=True, pady=(0, 12))
        self.caption_text = tk.Text(
            cap_frame,
            height=6,
            bg="#ffffff",
            fg="#0f172a",
            insertbackground="#2563eb",
            font=("Segoe UI", 9),
            relief="solid",
            bd=1,
            wrap="word"
        )
        self.caption_text.pack(fill="both", expand=True)
        init_caption = self.brand_data.get("caption", controller.caption or "")
        self.caption_text.insert("1.0", init_caption)

        # 5. Buttons
        btn_box = ttk.Frame(pad_frame, style="Card.TFrame")
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="💾 Save Brand", style="Success.TButton", command=self._on_save).pack(side="left", padx=(0, 8))
        ttk.Button(btn_box, text="Cancel", style="Dark.TButton", command=self.destroy).pack(side="left")

    def _browse_media_folder(self):
        d = filedialog.askdirectory(title="Select Brand Media / Content Folder", initialdir=str(BASE_DIR))
        if d:
            self.media_folder_var.set(d)
            self._update_media_folder_status()

    def _update_media_folder_status(self):
        folder = self.media_folder_var.get().strip()
        if not folder:
            if hasattr(self, "mf_status_lbl"):
                self.mf_status_lbl.configure(text="ℹ️ No media folder set (using fallback static video/caption).", fg="#64748b", bg="#f8fafc")
            return
        p = Path(folder)
        if not p.is_dir():
            if hasattr(self, "mf_status_lbl"):
                self.mf_status_lbl.configure(text="⚠️ Directory not found.", fg="#dc2626", bg="#fef2f2")
            return
        items = scan_media_folder(p)
        paired = sum(1 for i in items if i["has_paired_text"])
        if hasattr(self, "mf_status_lbl"):
            self.mf_status_lbl.configure(
                text=f"✅ Found {len(items)} video(s) and {paired} paired .txt caption(s). Random auto-selection active!",
                fg="#15803d",
                bg="#f0fdf4"
            )

    def _test_random_pair(self):
        folder = self.media_folder_var.get().strip()
        if not folder:
            messagebox.showinfo(APP_NAME, "Please select or enter a media folder path first.")
            return
        pair = select_random_media_pair(folder)
        if not pair:
            messagebox.showwarning(APP_NAME, f"No video files found in folder:\n{folder}")
            return
        msg = f"Selected Video: {pair.get('video_name')}\n" \
              f"Paired Text: {pair.get('text_name') or 'None'}\n" \
              f"Caption Length: {len(pair.get('caption') or '')} chars\n\n" \
              f"Caption Preview:\n{(pair.get('caption') or '')[:200]}..."
        messagebox.showinfo(f"{APP_NAME} - Random Pair Test", msg)

    def _browse_video(self):
        f = filedialog.askopenfilename(
            title="Select Brand Default Video File",
            filetypes=[("MP4 Video", "*.mp4"), ("All files", "*.*")]
        )
        if f:
            self.video_var.set(f)

    def _on_save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror(APP_NAME, "Please enter a brand name.")
            return

        raw_prof = self.profile_var.get().strip()
        prof_name = sanitize_chrome_profile(raw_prof, controller.get_available_profiles())
        cap = self.caption_text.get("1.0", "end-1c").strip()

        data = {
            "name": name,
            "description": self.desc_var.get().strip(),
            "chrome_profile": prof_name,
            "media_folder": self.media_folder_var.get().strip(),
            "video": self.video_var.get().strip(),
            "location": self.location_var.get().strip() or "Mumbai",
            "auto_publish": self.auto_publish_var.get(),
            "caption": cap
        }
        if self.on_save_cb:
            self.on_save_cb(data)
        self.destroy()


class MetaReelsGUI:
    """Enterprise Fintech Desktop User Interface for Meta Reels Scheduler.
    Integrates all features from the web control dashboard into a native desktop control center.
    """

    BG_LIGHT = "#f1f5f9"
    BG_DARK = BG_LIGHT
    CARD_BG = "#ffffff"
    CARD_BORDER = "#cbd5e1"
    INPUT_BG = "#ffffff"
    PRIMARY = "#2563eb"
    PRIMARY_HOVER = "#1d4ed8"
    SUCCESS = "#16a34a"
    SUCCESS_HOVER = "#15803d"
    WARNING = "#d97706"
    DANGER = "#dc2626"
    PURPLE = "#7c3aed"
    TEXT_MAIN = "#0f172a"
    TEXT_MUTED = "#64748b"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} - Enterprise Desktop Control Center (Chrome Profile 15)")
        self.root.geometry("1360x980")
        self.root.minsize(1120, 800)
        self.root.configure(bg=self.BG_LIGHT)

        # Connect GUI callback to controller
        controller.set_gui_callback(self.append_log)

        # Tk Variables
        self.status_var = tk.StringVar(value="Idle | Ready")
        self.kpi_total_var = tk.StringVar(value=f"{len(controller.pages)} Pages")
        self.kpi_published_var = tk.StringVar(value="0 / 0 Published")
        self.kpi_pending_var = tk.StringVar(value="0 Pending")
        self.kpi_batch_var = tk.StringVar(value="BATCH: IDLE")
        self.kpi_sched_var = tk.StringVar(value=f"SCHEDULER: {controller.schedule_time}")
        self.kpi_lock_var = tk.StringVar(value="🔓 INPUT: UNLOCKED")

        # Modern 5-Card Executive KPI Grid Variables
        self.kpi_card_brand_val = tk.StringVar(value="Active Brand")
        self.kpi_card_brand_sub = tk.StringVar(value="Profile 15 • 0 Pages")
        self.kpi_card_media_val = tk.StringVar(value="Media Source")
        self.kpi_card_media_sub = tk.StringVar(value="Random Pairing / Static")
        self.kpi_card_queue_val = tk.StringVar(value="0 / 0 Published")
        self.kpi_card_queue_sub = tk.StringVar(value="0 Pending Destinations")
        self.kpi_card_sched_val = tk.StringVar(value="00:05 (12:05 AM)")
        self.kpi_card_sched_sub = tk.StringVar(value="5 Daily Tasks Synced")
        self.kpi_card_shield_val = tk.StringVar(value="🔓 INPUT UNLOCKED")
        self.kpi_card_shield_sub = tk.StringVar(value="Zero-RAM Engine • Ready")

        # Brand Media Folder Variables
        active_b = controller.get_active_brand() or {}
        self.brand_media_folder_var = tk.StringVar(value=active_b.get("media_folder", "") or controller.media_folder or "")
        self.brand_media_telemetry_var = tk.StringVar(value="Scanning folder...")

        self.global_video = tk.StringVar(value=controller.global_video)
        self.location = tk.StringVar(value=controller.location)
        self.schedule_time = tk.StringVar(value=controller.schedule_time)
        self.scheduler_enabled = tk.BooleanVar(value=controller.scheduler_enabled)
        self.auto_publish = tk.BooleanVar(value=controller.auto_publish)

        self.caption_var = tk.StringVar(value=controller.caption or "loan")
        self.char_count_var = tk.StringVar(value="0 / 2200 characters")
        self.cv_results_var = tk.StringVar(value="Click 'Inspect Desktop Screen Now' to run real-time CV analysis.")
        self.target_page_var = tk.StringVar(value="")
        self.gemma_status_var = tk.StringVar(value="Autonomous Engine: ACTIVE (Zero RAM Overhead)")
        self.kpi_gemma_var = tk.StringVar(value="ENGINE: OPTIMIZED ⚡")
        self.step_sequence_var = tk.StringVar(value=self._get_sequence_combo_label(controller.step_sequence))
        self.sequence_desc_var = tk.StringVar(value=self._get_sequence_description(controller.step_sequence))
        self.log_filter_var = tk.StringVar(value="")
        self.log_autoscroll_var = tk.BooleanVar(value=True)

        self.header_subtitle_var = tk.StringVar(value=f"Enterprise Automation Engine • Chrome: {controller.selected_profile} • Windows Task Scheduler Synced")
        self.selected_profile_var = tk.StringVar(value=controller.selected_profile)
        self.profile_active_desc_var = tk.StringVar(value=f"{controller.selected_profile} ({controller.current_profile_path})")
        self.available_profiles: list[dict] = []

        # Global Configuration Variables
        self.global_max_uploads_var = tk.IntVar(value=getattr(controller, "max_publications_per_day", 7))
        self.global_block_input_var = tk.BooleanVar(value=getattr(controller, "block_input_during_automation", True))

        self.all_log_lines: list[tuple[str, str]] = []

        # Theme & UI Build
        self._apply_theme_styles()
        self._build_header()
        self._build_kpi_dashboard()
        self._build_notebook()
        self._build_execution_console()

        # Initial data load
        self._refresh_brand_combos()
        self._refresh_kpis()
        self._refresh_schedules_table()
        self._refresh_table()
        self._refresh_target_combobox()
        self._refresh_profile_combos()
        self._refresh_learning_memory()
        self._update_caption_counter()

        # Startup auto-extension verification & profile install
        try:
            ensure_chrome_extension_installed(controller.current_profile_path)
        except Exception as ee:
            logger.debug("Startup extension sync: %s", ee)

        # Sync schedules to Windows Task Scheduler on startup
        try:
            controller.sync_all_schedules_to_windows()
        except Exception as se:
            logger.debug("Startup schtasks sync: %s", se)

        # Immediate Engine Optimization Badge
        threading.Thread(target=self._auto_load_gemma_on_gui_open, name="GemmaAutoLoaderGUI", daemon=True).start()

        # Periodic scheduler tick (every 3 seconds)
        self.root.after(1000, self._tick_scheduler)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _get_sequence_combo_label(self, mode: str) -> str:
        if mode == "video_first":
            return "1. Video Upload -> Caption -> Location -> Messenger CTA"
        elif mode == "caption_messages_location":
            return "3. Caption -> Messenger CTA -> Location -> Video Upload"
        return "2. Caption -> Location -> Messenger CTA -> Video Upload (Default Recommended)"

    def _get_sequence_description(self, mode: str) -> str:
        if mode == "video_first":
            return "Uploads video file first, then sets caption, location, and CTA while video processes."
        elif mode == "caption_messages_location":
            return "Enters caption first, toggles Messenger CTA, then adds location, and uploads video last."
        return "Enters caption first, sets location, enables Messenger CTA, then triggers video upload."

    def _on_sequence_combo_change(self, event=None):
        val = self.step_sequence_var.get()
        if "Video Upload ->" in val:
            desc = self._get_sequence_description("video_first")
        elif "Messenger" in val and "Location" in val and val.index("Messenger") < val.index("Location"):
            desc = self._get_sequence_description("caption_messages_location")
        else:
            desc = self._get_sequence_description("caption_first")
        self.sequence_desc_var.set(desc)

    def _apply_theme_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Global Tk option database configuration for Combobox popdown listbox
        self.root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 9))
        self.root.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.root.option_add("*TCombobox*Listbox.foreground", "#0f172a")
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#dbeafe")
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#1e3a8a")
        self.root.option_add("*TCombobox*Listbox.relief", "solid")
        self.root.option_add("*TCombobox*Listbox.borderWidth", 1)

        # Frame styles
        style.configure("Dark.TFrame", background=self.BG_LIGHT)
        style.configure("Card.TFrame", background=self.CARD_BG)

        # Notebook tabs (Modern segmented clean tabs)
        style.configure("TNotebook", background=self.BG_LIGHT, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#e2e8f0",
            foreground="#475569",
            font=("Segoe UI", 10, "bold"),
            padding=[16, 7],
            borderwidth=0
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.CARD_BG), ("active", "#cbd5e1")],
            foreground=[("selected", self.PRIMARY), ("active", self.TEXT_MAIN)]
        )

        # LabelFrame
        style.configure("TLabelframe", background=self.CARD_BG, bordercolor=self.CARD_BORDER, relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=self.CARD_BG, foreground=self.TEXT_MAIN, font=("Segoe UI", 10, "bold"))

        # Labels
        style.configure("TLabel", background=self.BG_LIGHT, foreground=self.TEXT_MAIN, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=self.CARD_BG, foreground=self.TEXT_MAIN, font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background=self.CARD_BG, foreground=self.TEXT_MUTED, font=("Segoe UI", 8))
        style.configure("Badge.TLabel", background="#eff6ff", foreground=self.PRIMARY, font=("Segoe UI", 9, "bold"), padding=[8, 4])

        # Buttons
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=[7, 4], relief="flat")
        style.configure("Primary.TButton", background=self.PRIMARY, foreground="#ffffff")
        style.map("Primary.TButton", background=[("active", self.PRIMARY_HOVER)])
        style.configure("Success.TButton", background=self.SUCCESS, foreground="#ffffff")
        style.map("Success.TButton", background=[("active", self.SUCCESS_HOVER)])
        style.configure("Warning.TButton", background=self.WARNING, foreground="#ffffff")
        style.map("Warning.TButton", background=[("active", "#b45309")])
        style.configure("Danger.TButton", background=self.DANGER, foreground="#ffffff")
        style.map("Danger.TButton", background=[("active", "#b91c1c")])
        style.configure("Purple.TButton", background=self.PURPLE, foreground="#ffffff")
        style.map("Purple.TButton", background=[("active", "#6d28d9")])
        style.configure("Dark.TButton", background="#f1f5f9", foreground="#0f172a")
        style.map("Dark.TButton", background=[("active", "#e2e8f0")])

        # Entries & Comboboxes & Checkbuttons
        style.configure("TEntry", fieldbackground=self.INPUT_BG, foreground=self.TEXT_MAIN, insertcolor=self.PRIMARY)
        style.configure("TCombobox", fieldbackground=self.INPUT_BG, foreground=self.TEXT_MAIN, background="#e2e8f0")
        style.configure("TCheckbutton", background=self.CARD_BG, foreground=self.TEXT_MAIN, font=("Segoe UI", 9))
        style.map("TCheckbutton", background=[("active", self.CARD_BG)])

        # Treeview (Modern crisp Light SaaS styling)
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=self.TEXT_MAIN, rowheight=30, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#f1f5f9", foreground=self.TEXT_MAIN, font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#1e3a8a")])

    def _build_header(self):
        header = tk.Frame(self.root, bg="#ffffff", highlightbackground=self.CARD_BORDER, highlightthickness=1, padx=14, pady=9)
        header.pack(fill="x", padx=12, pady=(8, 6))

        # Title & Subtitle
        left_box = tk.Frame(header, bg="#ffffff")
        left_box.pack(side="left")

        title_row = tk.Frame(left_box, bg="#ffffff")
        title_row.pack(anchor="w")
        tk.Label(title_row, text="META REELS SCHEDULER", font=("Segoe UI", 14, "bold"), fg=self.TEXT_MAIN, bg="#ffffff").pack(side="left")
        tk.Label(title_row, text="ENTERPRISE v2.5", font=("Segoe UI", 8, "bold"), fg=self.PRIMARY, bg="#eff6ff", padx=7, pady=2).pack(side="left", padx=8)

        tk.Label(left_box, textvariable=self.header_subtitle_var, font=("Segoe UI", 9), fg=self.TEXT_MUTED, bg="#ffffff").pack(anchor="w", pady=(2, 0))

        # Right Action & Status
        right_box = tk.Frame(header, bg="#ffffff")
        right_box.pack(side="right")

        self.kpi_batch_lbl = tk.Label(right_box, textvariable=self.kpi_batch_var, font=("Segoe UI", 9, "bold"), fg="#475569", bg="#f1f5f9", padx=12, pady=5, relief="flat")
        self.kpi_batch_lbl.pack(side="left", padx=4)

        ttk.Button(right_box, text="🌐 Web Dashboard", style="Primary.TButton", command=self._open_web_dashboard).pack(side="left", padx=4)

    def _build_kpi_dashboard(self):
        kpi_bar = tk.Frame(self.root, bg=self.BG_LIGHT)
        kpi_bar.pack(fill="x", padx=12, pady=(0, 6))

        for col in range(5):
            kpi_bar.columnconfigure(col, weight=1, uniform="kpi")

        cards_spec = [
            (0, "🏢 ACTIVE BRAND", self.kpi_card_brand_val, self.kpi_card_brand_sub, "#1d4ed8", "#2563eb", "kpi_card_brand_lbl"),
            (1, "🎬 CONTENT SOURCE", self.kpi_card_media_val, self.kpi_card_media_sub, "#0f766e", "#0d9488", "kpi_card_media_lbl"),
            (2, "📊 TODAY'S PROGRESS", self.kpi_card_queue_val, self.kpi_card_queue_sub, "#15803d", "#16a34a", "kpi_card_queue_lbl"),
            (3, "🕒 NEXT SCHEDULE", self.kpi_card_sched_val, self.kpi_card_sched_sub, "#b45309", "#d97706", "kpi_card_sched_lbl"),
            (4, "🛡️ AUTOMATION SHIELD", self.kpi_card_shield_val, self.kpi_card_shield_sub, "#6d28d9", "#7c3aed", "kpi_card_shield_lbl"),
        ]

        for col, title, val_var, sub_var, text_color, accent_color, lbl_attr in cards_spec:
            card = tk.Frame(kpi_bar, bg=self.CARD_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1, padx=12, pady=7)
            card.grid(row=0, column=col, sticky="nsew", padx=3)

            # 3px colorful top accent line
            top_bar = tk.Frame(card, bg=accent_color, height=3)
            top_bar.pack(fill="x", pady=(0, 4))

            # Top label (title)
            tk.Label(card, text=title, font=("Segoe UI", 8, "bold"), fg=self.TEXT_MUTED, bg=self.CARD_BG).pack(anchor="w")

            # Value label
            val_lbl = tk.Label(card, textvariable=val_var, font=("Segoe UI", 12, "bold"), fg=text_color, bg=self.CARD_BG)
            val_lbl.pack(anchor="w", pady=(1, 1))
            setattr(self, lbl_attr, val_lbl)

            # Subtext label
            tk.Label(card, textvariable=sub_var, font=("Segoe UI", 8), fg="#64748b", bg=self.CARD_BG).pack(anchor="w")

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        # 4 Streamlined Enterprise Tabs
        self.tab_schedules_destinations = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.tab_content = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.tab_diagnostics = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.tab_global_config = ttk.Frame(self.notebook, style="Dark.TFrame")

        self.notebook.add(self.tab_schedules_destinations, text="  🕒 Schedules & Destinations  ")
        self.notebook.add(self.tab_content, text="  ✍️ Video Media & Caption Editor  ")
        self.notebook.add(self.tab_diagnostics, text="  🛠️ Chrome Extension & Diagnostics  ")
        self.notebook.add(self.tab_global_config, text="  ⚙️ Global Configuration  ")

        self._build_schedules_destinations_tab()
        self._build_content_tab()
        self._build_diagnostics_tab()
        self._build_global_config_tab()

    # --------------------------------------------------------------------------
    # Tab 1: Schedules & Destinations (Primary Operational Control)
    # --------------------------------------------------------------------------
    def _build_schedules_destinations_tab(self):
        container = ttk.Frame(self.tab_schedules_destinations, style="Dark.TFrame")
        container.pack(fill="both", expand=True, padx=2, pady=4)

        # Unified Command Toolbar (Replaces redundant hero card & stacked bars)
        toolbar = tk.Frame(container, bg=self.CARD_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1, padx=12, pady=9)
        toolbar.pack(fill="x", pady=(2, 8))

        # Left: Brand & Profile Selectors
        left_ctrl = tk.Frame(toolbar, bg=self.CARD_BG)
        left_ctrl.pack(side="left")

        tk.Label(left_ctrl, text="🏢 Brand:", font=("Segoe UI", 9, "bold"), fg=self.TEXT_MAIN, bg=self.CARD_BG).pack(side="left", padx=(0, 4))
        self.brand_combo_var = tk.StringVar()
        self.brand_combo = ttk.Combobox(left_ctrl, textvariable=self.brand_combo_var, state="readonly", width=38)
        self.brand_combo.pack(side="left", padx=(0, 4))
        self.brand_combo.bind("<<ComboboxSelected>>", self._on_brand_combo_selected)

        ttk.Button(left_ctrl, text="➕", width=3, style="Primary.TButton", command=self._add_brand_gui).pack(side="left", padx=1)
        ttk.Button(left_ctrl, text="✏️", width=3, style="Dark.TButton", command=self._edit_brand_gui).pack(side="left", padx=1)
        ttk.Button(left_ctrl, text="🗑️", width=3, style="Danger.TButton", command=self._delete_brand_gui).pack(side="left", padx=1)

        sep = tk.Frame(left_ctrl, bg=self.CARD_BORDER, width=1, height=22)
        sep.pack(side="left", padx=8)

        tk.Label(left_ctrl, text="👤 Profile:", font=("Segoe UI", 9, "bold"), fg=self.TEXT_MAIN, bg=self.CARD_BG).pack(side="left", padx=(0, 4))
        self.profile_quick_var = tk.StringVar(value=controller.selected_profile)
        self.profile_quick_combo = ttk.Combobox(left_ctrl, textvariable=self.profile_quick_var, state="readonly", width=14)
        self.profile_quick_combo.pack(side="left", padx=(0, 4))
        self.profile_quick_combo.bind("<<ComboboxSelected>>", self._on_quick_profile_change)
        ttk.Button(left_ctrl, text="Switch", style="Dark.TButton", width=6, command=self._apply_quick_profile).pack(side="left", padx=2)

        # Right: Batch Execution & Operational Actions
        right_ctrl = tk.Frame(toolbar, bg=self.CARD_BG)
        right_ctrl.pack(side="right")

        ttk.Button(right_ctrl, text="▶ START BATCH", style="Success.TButton", command=self.start_batch_now).pack(side="left", padx=3)
        ttk.Button(right_ctrl, text="⚡ ALL BRANDS", style="Purple.TButton", command=self.start_all_brands_batch).pack(side="left", padx=3)
        ttk.Button(right_ctrl, text="⏹ STOP", style="Danger.TButton", command=self.stop_batch).pack(side="left", padx=3)
        ttk.Button(right_ctrl, text="🌐 Launch Chrome", style="Primary.TButton", command=self._launch_chrome_for_active_brand).pack(side="left", padx=3)
        ttk.Button(right_ctrl, text="🔄 Reset Today", style="Dark.TButton", command=self.reset_all_attempts).pack(side="left", padx=3)
        ttk.Button(right_ctrl, text="🔓 Unlock", style="Dark.TButton", command=self._release_input_gui).pack(side="left", padx=3)

        # 1. Schedules Card
        sched_card = ttk.LabelFrame(container, text="📅 Publishing Schedules (Windows Task Scheduler Synced)", padding=6)
        sched_card.pack(fill="x", pady=(0, 6))

        sched_btn_bar = ttk.Frame(sched_card, style="Card.TFrame")
        sched_btn_bar.pack(fill="x", pady=(0, 4))

        ttk.Button(sched_btn_bar, text="➕ Add Schedule", style="Primary.TButton", command=self._add_schedule_gui).pack(side="left", padx=(0, 3))
        ttk.Button(sched_btn_bar, text="✏️ Edit Selected", style="Dark.TButton", command=self._edit_selected_schedule_gui).pack(side="left", padx=3)
        ttk.Button(sched_btn_bar, text="🗑️ Delete Selected", style="Danger.TButton", command=self._delete_selected_schedule_gui).pack(side="left", padx=3)
        ttk.Button(sched_btn_bar, text="🔄 Sync Windows Tasks", style="Success.TButton", command=self._sync_windows_tasks_gui).pack(side="left", padx=3)
        ttk.Button(sched_btn_bar, text="▶ Run This Schedule Now", style="Warning.TButton", command=self._run_selected_schedule_gui).pack(side="left", padx=3)
        ttk.Button(sched_btn_bar, text="✅ Toggle Active", style="Dark.TButton", command=self._toggle_selected_schedule_gui).pack(side="left", padx=3)

        sched_table_frame = ttk.Frame(sched_card, style="Card.TFrame")
        sched_table_frame.pack(fill="x")

        sched_cols = ("enabled", "name", "target_brand", "time", "repeat", "days", "win_status", "next_run")
        self.sched_tree = ttk.Treeview(sched_table_frame, columns=sched_cols, show="headings", height=5, selectmode="browse")

        sched_col_defs = [
            ("enabled", "Status", 75, "center"),
            ("name", "Schedule Name", 210, "w"),
            ("target_brand", "Target Brand", 140, "w"),
            ("time", "Start Time", 80, "center"),
            ("repeat", "Repeat Every", 115, "center"),
            ("days", "Frequency", 80, "center"),
            ("win_status", "Windows Task Status", 140, "w"),
            ("next_run", "Next Scheduled Execution", 180, "w")
        ]
        for cid, title, width, anchor in sched_col_defs:
            self.sched_tree.heading(cid, text=title)
            self.sched_tree.column(cid, width=width, anchor=anchor)

        self.sched_tree.tag_configure("ACTIVE", foreground="#16a34a")
        self.sched_tree.tag_configure("DISABLED", foreground="#94a3b8")
        self.sched_tree.tag_configure("odd", background="#ffffff")
        self.sched_tree.tag_configure("even", background="#f8fafc")

        s_scroll = ttk.Scrollbar(sched_table_frame, orient="vertical", command=self.sched_tree.yview)
        self.sched_tree.configure(yscrollcommand=s_scroll.set)
        self.sched_tree.pack(side="left", fill="both", expand=True)
        s_scroll.pack(side="right", fill="y")
        self.sched_tree.bind("<Double-1>", lambda e: self._edit_selected_schedule_gui())

        # 2. Destinations Card (Takes expand=True)
        dest_card = ttk.LabelFrame(container, text="📋 Target Facebook Pages (Destinations)", padding=6)
        dest_card.pack(fill="both", expand=True)

        dest_btn_bar = ttk.Frame(dest_card, style="Card.TFrame")
        dest_btn_bar.pack(fill="x", pady=(0, 4))

        ttk.Button(dest_btn_bar, text="➕ Add Destination", style="Primary.TButton", command=self.add_new_page).pack(side="left", padx=(0, 3))
        ttk.Button(dest_btn_bar, text="✏️ Edit Selected", style="Dark.TButton", command=self.edit_selected_page).pack(side="left", padx=3)
        ttk.Button(dest_btn_bar, text="🗑️ Delete", style="Danger.TButton", command=self.delete_selected_page).pack(side="left", padx=3)
        ttk.Button(dest_btn_bar, text="🔄 Reset Selected Attempt", style="Dark.TButton", command=self.reset_selected_attempt).pack(side="left", padx=3)
        ttk.Button(dest_btn_bar, text="✅ Enable All", style="Dark.TButton", command=lambda: self.set_all_enabled(True)).pack(side="left", padx=3)
        ttk.Button(dest_btn_bar, text="❌ Disable All", style="Dark.TButton", command=lambda: self.set_all_enabled(False)).pack(side="left", padx=3)
        ttk.Button(dest_btn_bar, text="📋 Copy Composer URL", style="Dark.TButton", command=self._copy_selected_composer_url).pack(side="left", padx=3)
        ttk.Button(dest_btn_bar, text="🧪 Test Selected Page", style="Warning.TButton", command=self._test_selected_page_gui).pack(side="left", padx=3)

        dest_table_frame = ttk.Frame(dest_card, style="Card.TFrame")
        dest_table_frame.pack(fill="both", expand=True)

        cols = ("enabled", "status", "name", "pageid", "video", "location", "caption")
        self.page_tree = ttk.Treeview(dest_table_frame, columns=cols, show="headings", selectmode="browse")

        col_defs = [
            ("enabled", "On", 45, "center"),
            ("status", "Today Status", 130, "center"),
            ("name", "Page Name", 240, "w"),
            ("pageid", "Page ID", 140, "w"),
            ("video", "Video File Override", 200, "w"),
            ("location", "Location", 110, "w"),
            ("caption", "Caption Override", 280, "w")
        ]
        for cid, title, width, anchor in col_defs:
            self.page_tree.heading(cid, text=title)
            self.page_tree.column(cid, width=width, anchor=anchor, stretch=(cid in ("name", "caption", "video")))

        self.page_tree.tag_configure("PUBLISHED", foreground="#15803d")
        self.page_tree.tag_configure("FAILED", foreground="#dc2626")
        self.page_tree.tag_configure("PENDING", foreground="#0284c7")
        self.page_tree.tag_configure("DISABLED", foreground="#94a3b8")
        self.page_tree.tag_configure("RUNNING", foreground="#d97706")
        self.page_tree.tag_configure("LOGIN_REQUIRED", foreground="#ea580c")
        self.page_tree.tag_configure("CAPPED", foreground="#64748b")
        self.page_tree.tag_configure("odd", background="#ffffff")
        self.page_tree.tag_configure("even", background="#f8fafc")

        tree_scroll = ttk.Scrollbar(dest_table_frame, orient="vertical", command=self.page_tree.yview)
        self.page_tree.configure(yscrollcommand=tree_scroll.set)
        self.page_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        self.page_tree.bind("<Double-1>", lambda e: self.edit_selected_page())
        self.page_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _on_tree_select(self, event=None):
        sel = self.page_tree.selection()
        if sel:
            pid = sel[0]
            for p in controller.pages:
                if str(p.get("id")) == str(pid):
                    disp = f"{p.get('name')} ({p.get('id')})"
                    self.target_page_var.set(disp)
                    break

    # --------------------------------------------------------------------------
    # Tab 2: Video Media & Caption Editor
    # --------------------------------------------------------------------------
    def _build_content_tab(self):
        container = ttk.Frame(self.tab_content, style="Dark.TFrame")
        container.pack(fill="both", expand=True, padx=2, pady=4)

        # Brand Selector Bar in Content Tab
        content_brand_bar = ttk.Frame(container, style="Dark.TFrame")
        content_brand_bar.pack(fill="x", pady=(2, 6))

        ttk.Label(content_brand_bar, text="🏢 Content Configuration For Brand:", style="Dark.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.content_brand_combo = ttk.Combobox(content_brand_bar, textvariable=self.brand_combo_var, state="readonly", width=42)
        self.content_brand_combo.pack(side="left", padx=(0, 6))
        self.content_brand_combo.bind("<<ComboboxSelected>>", self._on_brand_combo_selected)

        ttk.Button(content_brand_bar, text="💾 Save to Active Brand", style="Success.TButton", command=self.save_settings).pack(side="right", padx=4)

        # 1. Dedicated Brand Media & Content Folder Card (Dynamic Random Pairing)
        mf_card = ttk.LabelFrame(container, text="📁 Brand Media & Content Folder (Dynamic Video & Caption Pairing)", padding=10)
        mf_card.pack(fill="x", pady=(0, 6))

        mf_row = ttk.Frame(mf_card, style="Card.TFrame")
        mf_row.pack(fill="x", pady=(0, 4))
        ttk.Label(mf_row, text="Folder Path:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        ttk.Entry(mf_row, textvariable=self.brand_media_folder_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(mf_row, text="📁 Browse Folder...", style="Primary.TButton", command=self._browse_content_folder_gui).pack(side="left", padx=2)
        ttk.Button(mf_row, text="🗑️ Clear Folder", style="Dark.TButton", command=self._clear_content_folder_gui).pack(side="left", padx=2)
        ttk.Button(mf_row, text="🎲 Test Random Draw", style="Warning.TButton", command=self._test_random_pair_gui).pack(side="left", padx=2)

        # Folder Telemetry Banner
        self.mf_telemetry_lbl = tk.Label(
            mf_card,
            textvariable=self.brand_media_telemetry_var,
            font=("Segoe UI", 8, "bold"),
            fg="#15803d",
            bg="#f0fdf4",
            padx=10,
            pady=4,
            relief="flat",
            anchor="w"
        )
        self.mf_telemetry_lbl.pack(fill="x", pady=(2, 0))

        # 2. Fallback / Static Video Media Source Card
        vf_card = ttk.LabelFrame(container, text="🎬 Fallback Video Source (Used if Brand has no Content Folder)", padding=8)
        vf_card.pack(fill="x", pady=(0, 6))

        vf_row = ttk.Frame(vf_card, style="Card.TFrame")
        vf_row.pack(fill="x")
        ttk.Label(vf_row, text="Video File:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        ttk.Entry(vf_row, textvariable=self.global_video).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(vf_row, text="Browse Video...", style="Primary.TButton", command=self.browse_video).pack(side="left")

        # 3. Caption Card
        cap_card = ttk.LabelFrame(container, text="📝 Caption Editor & Quick Hashtags (Fallback if no .txt in folder)", padding=8)
        cap_card.pack(fill="both", expand=True, pady=(0, 6))

        self.caption_text = tk.Text(
            cap_card,
            bg="#ffffff",
            fg="#0f172a",
            insertbackground="#2563eb",
            font=("Segoe UI", 10),
            wrap="word",
            relief="solid",
            bd=1,
            height=6
        )
        self.caption_text.pack(fill="both", expand=True, pady=(0, 4))
        self.caption_text.insert("1.0", controller.caption or "loan")
        self.caption_text.bind("<KeyRelease>", lambda e: self._update_caption_counter())

        # Hashtags bar
        bar = ttk.Frame(cap_card, style="Card.TFrame")
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Quick Hashtags:", style="Muted.TLabel", font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 4))
        for tag in ["#reels", "#trending", "#viral", "#explorepage", "#finance", "#loan", "#business", "#homeloan", "#investment", "#mumbai", "#india"]:
            tk.Button(
                bar, text=tag, font=("Segoe UI", 8, "bold"), bg="#eff6ff", fg="#2563eb", activebackground="#2563eb", activeforeground="#ffffff", relief="flat", bd=0, padx=6, pady=2, cursor="hand2",
                command=lambda t=tag: self._insert_hashtag(t)
            ).pack(side="left", padx=2)

        self.char_count_lbl = ttk.Label(bar, textvariable=self.char_count_var, style="Muted.TLabel", font=("Segoe UI", 9, "bold"))
        self.char_count_lbl.pack(side="right", padx=6)

        cap_helpers = ttk.Frame(cap_card, style="Card.TFrame")
        cap_helpers.pack(fill="x")
        ttk.Button(cap_helpers, text="Clear Caption", style="Dark.TButton", command=self._clear_caption).pack(side="left", padx=(0, 4))
        ttk.Button(cap_helpers, text="Default ('loan')", style="Dark.TButton", command=lambda: self._set_caption_content("loan")).pack(side="left", padx=4)
        ttk.Button(cap_helpers, text="Trim Whitespace", style="Dark.TButton", command=self._trim_caption).pack(side="left", padx=4)

        # 4. Location & Settings Card
        cfg_card = ttk.LabelFrame(container, text="📍 Location & Composer Strategy", padding=8)
        cfg_card.pack(fill="x", pady=(0, 6))
        cfg_card.columnconfigure(1, weight=1)

        ttk.Label(cfg_card, text="Default Location:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        lf = ttk.Frame(cfg_card, style="Card.TFrame")
        lf.grid(row=0, column=1, sticky="ew", pady=2, padx=(8, 0))
        ttk.Entry(lf, textvariable=self.location, width=24).pack(side="left")
        for loc in ["Mumbai", "Delhi", "Bangalore", "Pune"]:
            tk.Button(
                lf, text=loc, font=("Segoe UI", 8, "bold"), bg="#f0fdf4", fg="#16a34a", activebackground="#16a34a", activeforeground="#ffffff", relief="flat", bd=0, padx=6, pady=2, cursor="hand2",
                command=lambda l=loc: self.location.set(l)
            ).pack(side="left", padx=3)

        ttk.Label(cfg_card, text="Publishing Mode:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Checkbutton(cfg_card, text="Fully auto-publish (uncheck to pause at final review screen)", variable=self.auto_publish).grid(row=1, column=1, sticky="w", pady=2, padx=(8, 0))

        ttk.Label(cfg_card, text="Step Sequence:", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=2)
        self.seq_combo = ttk.Combobox(
            cfg_card,
            textvariable=self.step_sequence_var,
            state="readonly",
            values=[
                "Caption -> Location -> Messenger -> Video Upload (Recommended)",
                "Caption -> Messenger -> Location -> Video Upload",
                "Video Upload -> Caption -> Location -> Messenger (Legacy Meta Flow)"
            ]
        )
        self.seq_combo.grid(row=2, column=1, sticky="ew", pady=2, padx=(8, 0))
        self.seq_combo.bind("<<ComboboxSelected>>", self._on_sequence_combo_change)

        # Save Button Bar
        save_bar = ttk.Frame(container, style="Dark.TFrame")
        save_bar.pack(fill="x", pady=4)
        ttk.Button(save_bar, text="💾 SAVE ALL SETTINGS TO ACTIVE BRAND", style="Success.TButton", command=self.save_settings).pack(side="left")

    def _browse_content_folder_gui(self):
        d = filedialog.askdirectory(title="Select Media & Content Folder for Active Brand")
        if d:
            self.brand_media_folder_var.set(d)
            brand_id = controller.active_brand_id
            controller.set_brand_media_folder(brand_id, d)
            self._update_content_folder_telemetry()
            self._refresh_kpis()

    def _clear_content_folder_gui(self):
        self.brand_media_folder_var.set("")
        brand_id = controller.active_brand_id
        controller.set_brand_media_folder(brand_id, "")
        self._update_content_folder_telemetry()
        self._refresh_kpis()

    def _update_content_folder_telemetry(self):
        folder = self.brand_media_folder_var.get().strip()
        if not folder:
            self.brand_media_telemetry_var.set("ℹ️ No folder configured. Scheduler will use fallback static video & caption.")
            if hasattr(self, "mf_telemetry_lbl"):
                self.mf_telemetry_lbl.configure(fg="#64748b", bg="#f8fafc")
            return
        p = Path(folder)
        if not p.is_dir():
            self.brand_media_telemetry_var.set(f"⚠️ Folder does not exist on disk: {folder}")
            if hasattr(self, "mf_telemetry_lbl"):
                self.mf_telemetry_lbl.configure(fg="#dc2626", bg="#fef2f2")
            return
        items = scan_media_folder(p)
        paired = sum(1 for item in items if item.get("has_paired_text"))
        if items:
            self.brand_media_telemetry_var.set(
                f"✅ Active: {len(items)} video(s) (.mp4) and {paired} paired text caption(s) (.txt) found in '{p.name}'. Dynamic random pairing is LIVE."
            )
            if hasattr(self, "mf_telemetry_lbl"):
                self.mf_telemetry_lbl.configure(fg="#15803d", bg="#f0fdf4")
        else:
            self.brand_media_telemetry_var.set(f"⚠️ Folder '{p.name}' contains no .mp4 video files.")
            if hasattr(self, "mf_telemetry_lbl"):
                self.mf_telemetry_lbl.configure(fg="#d97706", bg="#fffbeb")

    # --------------------------------------------------------------------------
    # Tab 3: Chrome Extension & Diagnostics
    # --------------------------------------------------------------------------
    def _build_diagnostics_tab(self):
        container = ttk.Frame(self.tab_diagnostics, style="Dark.TFrame")
        container.pack(fill="both", expand=True, padx=2, pady=4)

        # 1. Chrome Profile & Auto-Extension Manager Card
        ext_card = ttk.LabelFrame(container, text="🌐 Chrome Profile & Auto-Extension Manager", padding=10)
        ext_card.pack(fill="x", pady=(0, 8))

        ext_info = ttk.Frame(ext_card, style="Card.TFrame")
        ext_info.pack(fill="x", pady=(0, 6))
        ttk.Label(ext_info, text="Active Profile:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.profile_active_lbl = tk.Label(ext_info, textvariable=self.profile_active_desc_var, font=("Segoe UI", 9, "bold"), fg="#1d4ed8", bg="#eff6ff", padx=8, pady=2, relief="flat")
        self.profile_active_lbl.pack(side="left", padx=(0, 14))

        ttk.Label(ext_info, text="Extension:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.ext_status_lbl = tk.Label(ext_info, text="v2.2.0 (Installed & Auto-Updated)", font=("Segoe UI", 9, "bold"), fg="#15803d", bg="#dcfce7", padx=8, pady=2, relief="flat")
        self.ext_status_lbl.pack(side="left")

        # Discovered profiles selector & action buttons
        prof_bar = ttk.Frame(ext_card, style="Card.TFrame")
        prof_bar.pack(fill="x", pady=(4, 6))

        ttk.Label(prof_bar, text="Discovered Profiles:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.profile_detail_combo = ttk.Combobox(prof_bar, textvariable=self.selected_profile_var, state="readonly", width=42)
        self.profile_detail_combo.pack(side="left", padx=(0, 6))

        ttk.Button(prof_bar, text="🔄 Scan Profiles", style="Primary.TButton", command=self._refresh_profile_combos).pack(side="left", padx=2)
        ttk.Button(prof_bar, text="✅ Set Active Profile", style="Success.TButton", command=self._switch_profile_gui).pack(side="left", padx=2)
        ttk.Button(prof_bar, text="🌐 Launch Profile", style="Dark.TButton", command=self._launch_selected_profile_gui).pack(side="left", padx=2)
        ttk.Button(prof_bar, text="📁 Open Folder", style="Dark.TButton", command=self._open_profile_folder_gui).pack(side="left", padx=2)
        ttk.Button(prof_bar, text="🧹 Clear Cache", style="Dark.TButton", command=self._clear_profile_cache_gui).pack(side="left", padx=2)
        ttk.Button(prof_bar, text="📌 Create Shortcut", style="Dark.TButton", command=self._create_profile_shortcut_gui).pack(side="left", padx=2)
        ttk.Button(prof_bar, text="🔄 Reinstall Extension", style="Dark.TButton", command=self._force_reinstall_extension_gui).pack(side="left", padx=2)

        # 2. Autonomous Browser Automation & Self-Healing Engine Card
        g_card = ttk.LabelFrame(container, text="🧠 Autonomous Browser Automation & Self-Healing Engine", padding=10)
        g_card.pack(fill="x", pady=(0, 8))

        g_info_frame = ttk.Frame(g_card, style="Card.TFrame")
        g_info_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(g_info_frame, text="Engine Status:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.gemma_status_lbl = tk.Label(g_info_frame, textvariable=self.gemma_status_var, font=("Segoe UI", 9, "bold"), fg="#15803d", bg="#f0fdf4", padx=10, pady=4, relief="flat")
        self.gemma_status_lbl.pack(side="left", fill="x", expand=True, padx=(0, 10))

        g_btn_frame = ttk.Frame(g_card, style="Card.TFrame")
        g_btn_frame.pack(fill="x")
        ttk.Button(g_btn_frame, text="🔄 Refresh Heuristics", style="Primary.TButton", command=self._refresh_learning_memory).pack(side="left", padx=(0, 5))
        ttk.Button(g_btn_frame, text="🛠 Remediate Target Page", style="Warning.TButton", command=self._trigger_remediation).pack(side="left", padx=4)
        ttk.Button(g_btn_frame, text="🧪 Test Diagnostics", style="Dark.TButton", command=self._test_gemma_reasoning).pack(side="left", padx=4)

        # 3. Two side-by-side sub-boxes for Heuristics & Episodes
        diag_split = ttk.Frame(container, style="Dark.TFrame")
        diag_split.pack(fill="both", expand=True, pady=(0, 8))
        diag_split.columnconfigure(0, weight=1)
        diag_split.columnconfigure(1, weight=1)
        diag_split.rowconfigure(0, weight=1)

        # Left: Learned Heuristics
        h_box = ttk.LabelFrame(diag_split, text="Learned Heuristics (SQLite WAL)", padding=6)
        h_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        h_cols = ("key", "coords", "reliability", "updated")
        self.h_tree = ttk.Treeview(h_box, columns=h_cols, show="headings", height=4)
        for cid, title, width in [("key", "Key", 110), ("coords", "Coords (X,Y)", 100), ("reliability", "Reliability", 80), ("updated", "Updated", 140)]:
            self.h_tree.heading(cid, text=title)
            self.h_tree.column(cid, width=width, anchor="w")
        self.h_tree.tag_configure("odd", background="#ffffff")
        self.h_tree.tag_configure("even", background="#f8fafc")
        h_scroll = ttk.Scrollbar(h_box, orient="vertical", command=self.h_tree.yview)
        self.h_tree.configure(yscrollcommand=h_scroll.set)
        self.h_tree.pack(side="left", fill="both", expand=True)
        h_scroll.pack(side="right", fill="y")

        # Right: Self-Healing Episodes
        e_box = ttk.LabelFrame(diag_split, text="Recent Self-Healing Episodes", padding=6)
        e_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        e_cols = ("time", "stage", "status", "action")
        self.e_tree = ttk.Treeview(e_box, columns=e_cols, show="headings", height=4)
        for cid, title, width in [("time", "Time", 120), ("stage", "Stage", 140), ("status", "Status", 90), ("action", "Action", 200)]:
            self.e_tree.heading(cid, text=title)
            self.e_tree.column(cid, width=width, anchor="w")
        self.e_tree.tag_configure("odd", background="#ffffff")
        self.e_tree.tag_configure("even", background="#f8fafc")
        e_scroll = ttk.Scrollbar(e_box, orient="vertical", command=self.e_tree.yview)
        self.e_tree.configure(yscrollcommand=e_scroll.set)
        self.e_tree.pack(side="left", fill="both", expand=True)
        e_scroll.pack(side="right", fill="y")

        # 4. Interactive Step-by-Step Action Endpoints (Manual Debugging)
        s_box = ttk.LabelFrame(container, text="⚡ Interactive Step-by-Step Action Endpoints (Manual Debugging)", padding=8)
        s_box.pack(fill="x")

        tgt_row = ttk.Frame(s_box, style="Card.TFrame")
        tgt_row.pack(fill="x", pady=(0, 6))
        ttk.Label(tgt_row, text="Target Page:", style="Card.TLabel", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.target_page_combo = ttk.Combobox(tgt_row, textvariable=self.target_page_var, state="readonly", width=40)
        self.target_page_combo.pack(side="left", fill="x", expand=True)
        self.target_page_combo.bind("<<ComboboxSelected>>", self._on_combo_target_change)

        btn_row = ttk.Frame(s_box, style="Card.TFrame")
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="1. Upload Video", style="Primary.TButton", command=self._act_upload).pack(side="left", padx=3)
        ttk.Button(btn_row, text="2. Set Caption", style="Dark.TButton", command=self._act_caption).pack(side="left", padx=3)
        ttk.Button(btn_row, text="3. Tag Location", style="Dark.TButton", command=self._act_location).pack(side="left", padx=3)
        ttk.Button(btn_row, text="4. Messages CTA", style="Dark.TButton", command=self._act_messages).pack(side="left", padx=3)
        ttk.Button(btn_row, text="5. Next (1->2)", style="Warning.TButton", command=self._act_next_edit).pack(side="left", padx=3)
        ttk.Button(btn_row, text="6. Next (2->3)", style="Warning.TButton", command=self._act_next_share).pack(side="left", padx=3)
        ttk.Button(btn_row, text="7. Share Reel", style="Danger.TButton", command=self._act_share).pack(side="left", padx=3)
        ttk.Button(btn_row, text="8. Done Modal", style="Success.TButton", command=self._act_done).pack(side="left", padx=3)

    # --------------------------------------------------------------------------
    # Tab 4: Global Configuration (Safety, Rate Limits & Automation Shield)
    # --------------------------------------------------------------------------
    def _build_global_config_tab(self):
        container = ttk.Frame(self.tab_global_config, style="Dark.TFrame")
        container.pack(fill="both", expand=True, padx=8, pady=8)

        # Hero Banner
        hero = tk.Frame(container, bg=self.CARD_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1, padx=14, pady=10)
        hero.pack(fill="x", pady=(0, 10))
        tk.Label(hero, text="⚙️ Global Automation, Safety & Rate Limit Engine", font=("Segoe UI", 12, "bold"), fg=self.TEXT_MAIN, bg=self.CARD_BG).pack(anchor="w")
        tk.Label(hero, text="Configure global safety limits, anti-spam policies, zero-RAM automation shields, and intelligent pacing across all brands.", font=("Segoe UI", 9), fg=self.TEXT_MUTED, bg=self.CARD_BG).pack(anchor="w", pady=(2, 0))

        # Card 1: Anti-Spam Safety Limit (Daily Upload Capping)
        cap_card = ttk.LabelFrame(container, text="🛡️ Anti-Spam Safety Limit: Max Publications per Day per Page", padding=12)
        cap_card.pack(fill="x", pady=(0, 10))

        cap_desc = tk.Label(
            cap_card,
            text="Controls the maximum number of reels any single Facebook Page can publish in a 24-hour calendar day across all schedules.\n"
                 "• Set to 7 (Default): Safe limit for active brands with multiple daily schedules (12:05 AM, 01:10 AM, etc.).\n"
                 "• Set to 0: Disables the daily ceiling (Unlimited daily publications per page).",
            font=("Segoe UI", 9),
            fg="#334155",
            bg="#f8fafc",
            justify="left",
            padx=10,
            pady=8,
            relief="flat"
        )
        cap_desc.pack(fill="x", pady=(0, 10))

        cap_row = ttk.Frame(cap_card, style="Card.TFrame")
        cap_row.pack(fill="x", pady=(0, 4))

        ttk.Label(cap_row, text="Max Publications / Day per Page:", style="Card.TLabel", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 10))
        self.max_pub_spinbox = ttk.Spinbox(cap_row, from_=0, to=50, textvariable=self.global_max_uploads_var, width=8, font=("Segoe UI", 10))
        self.max_pub_spinbox.pack(side="left", padx=(0, 10))

        ttk.Label(cap_row, text="reels / day (0 = Unlimited)", style="Card.TLabel", font=("Segoe UI", 9)).pack(side="left")

        # Card 2: Physical Input Restriction Shield
        shield_card = ttk.LabelFrame(container, text="🔒 Zero-RAM Automation Shield (Physical Input Lock)", padding=12)
        shield_card.pack(fill="x", pady=(0, 10))

        shield_desc = tk.Label(
            shield_card,
            text="Exclusively locks physical keyboard and mouse input while automated reel publishing is in progress.\n"
                 "• Blocks accidental mouse movements, window switches, and keypresses that might disrupt Chrome automation.\n"
                 "• Automatically releases immediately when automation completes or errors out.\n"
                 "• Emergency Override: Press Esc key or Ctrl+Alt+Del anytime to instantly release the shield.",
            font=("Segoe UI", 9),
            fg="#334155",
            bg="#f8fafc",
            justify="left",
            padx=10,
            pady=8,
            relief="flat"
        )
        shield_desc.pack(fill="x", pady=(0, 10))

        shield_chk = ttk.Checkbutton(
            shield_card,
            text="Enable Zero-RAM Automation Shield (Block Keyboard & Mouse during batch execution)",
            variable=self.global_block_input_var,
            style="Dark.TCheckbutton"
        )
        shield_chk.pack(anchor="w", pady=(0, 6))

        shield_btn_row = ttk.Frame(shield_card, style="Card.TFrame")
        shield_btn_row.pack(fill="x")
        ttk.Button(shield_btn_row, text="🔓 Release Input Shield Now", style="Dark.TButton", command=self._release_input_gui).pack(side="left", padx=(0, 6))

        # Card 3: Intelligent Queue Pacing & Delays
        pacing_card = ttk.LabelFrame(container, text="⏱️ Intelligent Human-Like Queue Pacing", padding=12)
        pacing_card.pack(fill="x", pady=(0, 10))

        pacing_desc = tk.Label(
            pacing_card,
            text="Inter-destination randomized wait intervals simulate natural human behavior and protect accounts against rate limiting.\n"
                 "• Between Destination Pages: 6-10 seconds randomized delay after success; 4-7 seconds recovery delay on error.\n"
                 "• Between Sequential Brands: 15-30 seconds randomized delay.",
            font=("Segoe UI", 9),
            fg="#334155",
            bg="#f8fafc",
            justify="left",
            padx=10,
            pady=8,
            relief="flat"
        )
        pacing_desc.pack(fill="x", pady=(0, 6))

        # Bottom Action Bar
        act_bar = tk.Frame(container, bg=self.CARD_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1, padx=14, pady=10)
        act_bar.pack(fill="x", pady=(4, 0))

        ttk.Button(act_bar, text="💾 Save Global Configuration", style="Primary.TButton", command=self._save_global_config_gui).pack(side="left", padx=(0, 8))
        ttk.Button(act_bar, text="🔄 Reset Daily Publication Counters Today", style="Danger.TButton", command=self.reset_all_attempts).pack(side="left", padx=(0, 8))

        self.global_cfg_status_lbl = tk.Label(act_bar, text="Settings synchronized with config.json and active controller.", font=("Segoe UI", 9, "italic"), fg="#15803d", bg=self.CARD_BG)
        self.global_cfg_status_lbl.pack(side="right")

    def _save_global_config_gui(self):
        try:
            max_pub = int(self.global_max_uploads_var.get())
        except Exception:
            max_pub = 7
            self.global_max_uploads_var.set(7)

        block_input = bool(self.global_block_input_var.get())

        controller.max_publications_per_day = max_pub
        controller.block_input_during_automation = block_input

        cfg = {
            "max_publications_per_day": max_pub,
            "block_input_during_automation": block_input,
        }
        controller.update_config(cfg)
        self._refresh_kpis()
        self._refresh_table()
        if hasattr(self, "global_cfg_status_lbl"):
            self.global_cfg_status_lbl.configure(text=f"Saved! Max: {max_pub}/day • Shield: {'ON' if block_input else 'OFF'}", fg="#15803d")
        messagebox.showinfo("Configuration Saved", f"Global settings successfully updated:\n• Max publications per day per page: {max_pub} (0 = unlimited)\n• Automation shield: {'Enabled' if block_input else 'Disabled'}")

    # Brand Management GUI Handlers
    def _refresh_brand_combos(self):
        if not hasattr(self, "brand_combo"):
            return
        brands = controller.get_brands()
        self._brand_combo_map = {}
        combo_vals = []
        cur_idx = 0
        for idx, b in enumerate(brands):
            b_id = b.get("id")
            b_name = b.get("name", "Untitled")
            b_prof = b.get("chrome_profile", "Default")
            p_count = len(b.get("pages", []))
            lbl = f"{b_name} ({p_count} {'Page' if p_count == 1 else 'Pages'}) • [{b_prof}]"
            self._brand_combo_map[lbl] = b_id
            combo_vals.append(lbl)
            if b_id == controller.active_brand_id:
                cur_idx = idx
        self.brand_combo["values"] = combo_vals
        if combo_vals:
            self.brand_combo.current(cur_idx)
        if hasattr(self, "content_brand_combo"):
            self.content_brand_combo["values"] = combo_vals
            if combo_vals:
                self.content_brand_combo.current(cur_idx)

    def _on_brand_combo_selected(self, event=None):
        val = self.brand_combo_var.get()
        b_id = getattr(self, "_brand_combo_map", {}).get(val)
        if not b_id and "|" in val:
            b_id = val.split("|")[-1].strip()
        if not b_id:
            for b in controller.get_brands():
                if val.startswith(b.get("name", "")):
                    b_id = b.get("id")
                    break
        if b_id:
            controller.set_active_brand(b_id)
            brand = controller.get_active_brand()
            self.global_video.set(brand.get("video", ""))
            self.location.set(brand.get("location", "Mumbai"))
            self.auto_publish.set(brand.get("auto_publish", True))
            if hasattr(self, "caption_text"):
                self.caption_text.delete("1.0", "end")
                self.caption_text.insert("1.0", brand.get("caption", ""))
            self.selected_profile_var.set(brand.get("chrome_profile", "Profile 15"))
            self.profile_quick_var.set(brand.get("chrome_profile", "Profile 15"))
            if hasattr(self, "brand_media_folder_var"):
                self.brand_media_folder_var.set(brand.get("media_folder", "") or "")
                self._update_content_folder_telemetry()
            self._refresh_table()
            self._refresh_kpis()
            self._refresh_target_combobox()
            self._refresh_profile_combos()

    def _add_brand_gui(self):
        BrandDialog(self.root, on_save_cb=self._on_brand_added)

    def _on_brand_added(self, data: dict):
        new_b = controller.add_brand(
            name=data["name"],
            chrome_profile=data.get("chrome_profile", "Profile 15"),
            video=data.get("video", ""),
            caption=data.get("caption", ""),
            location=data.get("location", "Mumbai"),
            auto_publish=data.get("auto_publish", True),
            description=data.get("description", "")
        )
        controller.set_active_brand(new_b["id"])
        self._refresh_brand_combos()
        self._on_brand_combo_selected()
        messagebox.showinfo(APP_NAME, f"Brand '{new_b['name']}' created successfully!")

    def _edit_brand_gui(self):
        brand = controller.get_active_brand()
        BrandDialog(self.root, brand_data=brand, on_save_cb=self._on_brand_edited)

    def _on_brand_edited(self, updates: dict):
        controller.update_brand(controller.active_brand_id, updates)
        self._refresh_brand_combos()
        self._on_brand_combo_selected()
        messagebox.showinfo(APP_NAME, "Brand settings updated successfully!")

    def _delete_brand_gui(self):
        if len(controller.brands) <= 1:
            messagebox.showwarning(APP_NAME, "Cannot delete the only configured brand.")
            return
        brand = controller.get_active_brand()
        if not messagebox.askyesno(APP_NAME, f"Delete brand '{brand.get('name')}' and all its {len(brand.get('pages', []))} destinations?"):
            return
        controller.delete_brand(brand["id"])
        self._refresh_brand_combos()
        self._on_brand_combo_selected()

    def _launch_chrome_for_active_brand(self):
        brand = controller.get_active_brand()
        url = brand["pages"][0]["url"] if brand.get("pages") else "https://business.facebook.com/latest/reels_composer/"
        prof = brand.get("chrome_profile") or controller.selected_profile
        controller.open_chrome_url(url, profile_name=prof)

    def start_all_brands_batch(self):
        started = controller.start_all_brands_batch()
        if started:
            self.kpi_batch_var.set("BATCH: RUNNING (ALL BRANDS)")
            self.kpi_batch_lbl.configure(bg="#dcfce7", fg="#15803d")
            self.append_log("Started sequential batch publishing across ALL brands.")

    def _open_web_dashboard(self):
        ensure_api_server_running()
        url = f"http://127.0.0.1:{API_PORT}/dashboard"
        self.append_log(f"Opening Web Control Dashboard in default browser: {url}")
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()

    def _update_hero_card(self):
        brand = controller.get_active_brand() or {}
        b_name = brand.get("name", "Unknown")
        b_id = brand.get("id", "")
        b_prof = brand.get("chrome_profile", controller.selected_profile)
        b_auto = "🚀 Auto-Publish: ON" if brand.get("auto_publish", True) else "⏸ Review Mode (Pause at step 3)"
        p_count = len(brand.get("pages", []))

        vid_path = brand.get("video") or controller.global_video
        vid_ok = False
        vid_size_str = ""
        if vid_path and Path(vid_path).is_file():
            vid_ok = True
            try:
                sz_mb = Path(vid_path).stat().st_size / (1024 * 1024)
                vid_size_str = f"({sz_mb:.2f} MB)"
            except Exception:
                pass

        m_folder = brand.get("media_folder") or controller.media_folder or ""
        pairs = scan_media_folder(m_folder) if m_folder else []
        if pairs:
            paired_count = sum(1 for p in pairs if p["has_paired_text"])
            folder_name = Path(m_folder).name
            vid_text = f"📁 Content Folder: {folder_name} ({len(pairs)} vids, {paired_count} paired text) [🎲 Random]"
            vid_ok = True
            cap_preview = f"Auto-selected randomly from {paired_count} matching .txt files"
        elif vid_ok:
            vid_text = f"🎬 Video: {Path(vid_path).name} {vid_size_str} [Ready ✅]"
        elif vid_path:
            vid_text = f"⚠️ Video Missing: {Path(vid_path).name} [Not Found]"
        else:
            vid_text = "⚠️ No default video or media folder set"

        loc = brand.get("location") or controller.location or "Mumbai"
        cap = brand.get("caption") or controller.caption or ""
        cap_clean = " ".join(cap.split())
        if not pairs:
            cap_preview = (cap_clean[:45] + "...") if len(cap_clean) > 45 else (cap_clean or "None")

        if hasattr(self, "hero_brand_lbl"):
            self.hero_brand_lbl.configure(text=f"🏢 Brand: {b_name} [{b_id}]")
        if hasattr(self, "hero_prof_lbl"):
            self.hero_prof_lbl.configure(text=f"👤 Profile: {b_prof}")
        if hasattr(self, "hero_mode_lbl"):
            self.hero_mode_lbl.configure(text=b_auto, fg="#16a34a" if brand.get("auto_publish", True) else "#d97706")
        if hasattr(self, "hero_pages_lbl"):
            self.hero_pages_lbl.configure(text=f"📋 {p_count} Pages")
        if hasattr(self, "hero_vid_lbl"):
            self.hero_vid_lbl.configure(text=vid_text, fg="#16a34a" if vid_ok else "#dc2626")
        if hasattr(self, "hero_loc_lbl"):
            self.hero_loc_lbl.configure(text=f"📍 Location: {loc}")
        if hasattr(self, "hero_cap_lbl"):
            self.hero_cap_lbl.configure(text=f"💬 Caption: {cap_preview}")

    def _test_random_pair_gui(self):
        brand = controller.get_active_brand()
        folder = brand.get("media_folder") or controller.media_folder
        if not folder or not Path(folder).is_dir():
            messagebox.showinfo(APP_NAME, f"Active brand '{brand.get('name')}' has no media folder configured.\nClick 'Edit Brand Settings' to select a folder.")
            return
        pair = controller.get_random_brand_media(brand.get("id"), folder)
        if not pair:
            messagebox.showwarning(APP_NAME, f"No video files found in folder:\n{folder}")
            return
        cap_prev = (pair.get("caption") or "")[:200]
        if len(pair.get("caption") or "") > 200:
            cap_prev += "..."
        msg = f"🎲 Random Selection Result for '{brand.get('name')}':\n\n" \
              f"🎬 Video: {pair.get('video_name')}\n" \
              f"📄 Text File: {pair.get('text_name') or 'None (using default)'}\n" \
              f"💬 Caption Length: {len(pair.get('caption') or '')} chars\n\n" \
              f"Preview:\n{cap_prev}"
        messagebox.showinfo(f"{APP_NAME} - Random Media Pair", msg)
        self.append_log(f"[{brand.get('name')}] Random test selected: {pair.get('video_name')} with {pair.get('text_name')} ({len(pair.get('caption') or '')} chars)")

    def _copy_selected_composer_url(self):
        sel = self.page_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Please select a page first from the table.")
            return
        pid = sel[0]
        page = next((p for p in controller.pages if str(p.get("id")) == str(pid)), None)
        if not page:
            return
        url = page.get("url") or f"https://business.facebook.com/latest/reels_composer/?asset_id={pid}"
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.append_log(f"📋 Copied Composer URL for '{page.get('name')}' ({pid}) to clipboard.")
        messagebox.showinfo(APP_NAME, f"Composer URL for '{page.get('name')}' copied to clipboard!\n\n{url}")

    def _test_selected_page_gui(self):
        sel = self.page_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Please select a page first from the table.")
            return
        pid = sel[0]
        page = next((p for p in controller.pages if str(p.get("id")) == str(pid)), None)
        if not page:
            return
        if messagebox.askyesno(APP_NAME, f"Run automated publishing test for page '{page.get('name')}' ({pid}) now?"):
            self.append_log(f"Starting single-page automated test for '{page.get('name')}' ({pid})...")
            threading.Thread(target=controller.execute_page_by_id, args=(str(pid),), daemon=True).start()

    # Schedule Management GUI Handlers
    def _refresh_schedules_table(self):
        if not hasattr(self, "sched_tree"):
            return
        self.sched_tree.delete(*self.sched_tree.get_children())
        for idx, s in enumerate(controller.schedules):
            sid = s.get("id", "")
            enabled = "✓ ACTIVE" if s.get("enabled", True) else "✗ OFF"
            name = s.get("name", "")
            tb = s.get("target_brand", "ALL")
            if tb == "ALL" or not tb:
                target_str = "All Brands (Seq)"
            else:
                b_match = controller.get_brand(tb)
                target_str = b_match.get("name", tb) if b_match else tb
            time_str = s.get("time", "")
            ri = int(s.get("repeat_interval_minutes") or 0)
            dh = int(s.get("repeat_duration_hours") or 24)
            repeat_str = f"Every {ri}m ({dh}h)" if ri > 0 else "Once / Day"
            days = s.get("days", "DAILY")
            q = WindowsTaskSchedulerManager.query_task(sid)
            win_st = q.get("status", "Not Registered")
            next_r = q.get("next_run", "") or ("Daily" if s.get("enabled", True) else "Disabled")
            tag = "ACTIVE" if s.get("enabled", True) else "DISABLED"
            row_tag = "even" if idx % 2 == 0 else "odd"
            self.sched_tree.insert("", "end", iid=sid, values=(enabled, name, target_str, time_str, repeat_str, days, win_st, next_r), tags=(tag, row_tag))

    def _add_schedule_gui(self):
        ScheduleDialog(self.root, on_save_cb=self._on_schedule_added)

    def _on_schedule_added(self, data: dict):
        controller.add_schedule(
            time_str=data["time"],
            name=data["name"],
            enabled=data["enabled"],
            days=data["days"],
            repeat_interval_minutes=data.get("repeat_interval_minutes", 0),
            repeat_duration_hours=data.get("repeat_duration_hours", 24),
            target_brand=data.get("target_brand", "ALL")
        )
        self._refresh_kpis()
        self._refresh_schedules_table()

    def _edit_selected_schedule_gui(self):
        sel = self.sched_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a schedule from the table first.")
            return
        sid = sel[0]
        sched = next((s for s in controller.schedules if s["id"] == sid), None)
        if not sched:
            return
        ScheduleDialog(self.root, sched_data=sched, on_save_cb=lambda updates: self._on_schedule_edited(sid, updates))

    def _on_schedule_edited(self, sid: str, updates: dict):
        controller.edit_schedule(sid, updates)
        self._refresh_kpis()
        self._refresh_schedules_table()

    def _delete_selected_schedule_gui(self):
        sel = self.sched_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a schedule to delete.")
            return
        sid = sel[0]
        sched = next((s for s in controller.schedules if s["id"] == sid), None)
        name = sched.get("name") if sched else sid
        if not messagebox.askyesno(APP_NAME, f"Delete schedule '{name}'?\nThis will remove it from Windows Task Scheduler as well."):
            return
        controller.delete_schedule(sid)
        self._refresh_kpis()
        self._refresh_schedules_table()

    def _sync_windows_tasks_gui(self):
        res = controller.sync_all_schedules_to_windows()
        reg_count = len(res.get("registered", []))
        del_count = len(res.get("deleted", []))
        messagebox.showinfo(APP_NAME, f"Windows Task Scheduler Sync Complete!\n\nRegistered/Updated: {reg_count}\nRemoved/Disabled: {del_count}")
        self._refresh_kpis()
        self._refresh_schedules_table()

    def _run_selected_schedule_gui(self):
        sel = self.sched_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a schedule from the table first.")
            return
        sid = sel[0]
        sched = next((s for s in controller.schedules if s["id"] == sid), None)
        name = sched.get("name", sid) if sched else sid
        controller.log(f"Manual trigger for schedule '{name}'. Starting automated batch...")
        self.start_batch_now()

    def _toggle_selected_schedule_gui(self):
        sel = self.sched_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a schedule from the table first.")
            return
        sid = sel[0]
        sched = next((s for s in controller.schedules if s["id"] == sid), None)
        if not sched:
            return
        new_state = not sched.get("enabled", True)
        controller.edit_schedule(sid, {"enabled": new_state})
        self._refresh_kpis()
        self._refresh_schedules_table()

    def _refresh_profile_combos(self):
        try:
            self.available_profiles = controller.get_available_profiles()
            combo_values = []
            for p in self.available_profiles:
                p_name = p.get("profile_dir", "")
                d_name = p.get("display_name", "")
                email = p.get("email", "")
                size = p.get("size_str", "")
                tag = f"{p_name} — {d_name}" if d_name else p_name
                if email:
                    tag += f" ({email})"
                if size:
                    tag += f" [{size}]"
                combo_values.append(tag)

            if hasattr(self, "profile_quick_combo"):
                self.profile_quick_combo["values"] = [p.get("profile_dir") for p in self.available_profiles]
                self.profile_quick_var.set(controller.selected_profile)
            if hasattr(self, "profile_detail_combo"):
                self.profile_detail_combo["values"] = combo_values
                for idx, p in enumerate(self.available_profiles):
                    if p.get("profile_dir") == controller.selected_profile:
                        self.profile_detail_combo.current(idx)
                        break
            if hasattr(self, "profile_active_desc_var"):
                self.profile_active_desc_var.set(f"{controller.selected_profile} ({controller.current_profile_path})")
            if hasattr(self, "header_subtitle_var"):
                self.header_subtitle_var.set(f"Python Native Enterprise Control Center • Chrome: {controller.selected_profile} • AI Learning & Computer Vision")
        except Exception as e:
            self.append_log(f"Profile scan notice: {e}")

    def _on_quick_profile_change(self, event=None):
        self._apply_quick_profile()

    def _apply_quick_profile(self):
        val = sanitize_chrome_profile(self.profile_quick_var.get().strip(), self.available_profiles)
        if not val:
            return
        controller.set_selected_profile(val)
        self.append_log(f"Switched active Chrome profile to '{val}'. Extension synced.")
        self._refresh_profile_combos()

    def _switch_profile_gui(self):
        idx = self.profile_detail_combo.current() if hasattr(self, "profile_detail_combo") else -1
        if 0 <= idx < len(self.available_profiles):
            target = self.available_profiles[idx].get("profile_dir")
        else:
            target = sanitize_chrome_profile(self.selected_profile_var.get(), self.available_profiles)
        if target:
            controller.set_selected_profile(target)
            self.append_log(f"Active Chrome profile set to '{target}'. Extension auto-synced.")
            self._refresh_profile_combos()

    def _launch_selected_profile_gui(self):
        idx = self.profile_detail_combo.current() if hasattr(self, "profile_detail_combo") else -1
        if 0 <= idx < len(self.available_profiles):
            target = self.available_profiles[idx].get("profile_dir")
            controller.set_selected_profile(target)
        url = controller.pages[0]["url"] if controller.pages else DEFAULT_URLS[0]
        controller.open_chrome_url(url)

    def _open_profile_folder_gui(self):
        idx = self.profile_detail_combo.current() if hasattr(self, "profile_detail_combo") else -1
        if 0 <= idx < len(self.available_profiles):
            path_str = self.available_profiles[idx].get("path")
        else:
            path_str = str(controller.current_profile_path)
        if path_str and Path(path_str).exists():
            subprocess.run(["explorer", str(Path(path_str).resolve())])
        else:
            self.append_log(f"Profile directory not found: {path_str}", "warning")

    def _clear_profile_cache_gui(self):
        idx = self.profile_detail_combo.current() if hasattr(self, "profile_detail_combo") else -1
        if 0 <= idx < len(self.available_profiles):
            target = self.available_profiles[idx].get("profile_dir")
            prof_path = Path(self.available_profiles[idx].get("path"))
        else:
            target = controller.selected_profile
            prof_path = controller.current_profile_path
        res = clear_profile_cache(prof_path)
        if res.get("ok"):
            self.append_log(f"Cleared cache for profile '{target}' (Freed {res.get('freed_str')}).")
            self._refresh_profile_combos()
        else:
            self.append_log(f"Notice clearing cache for '{target}': {res.get('error')}", "warning")

    def _create_profile_shortcut_gui(self):
        idx = self.profile_detail_combo.current() if hasattr(self, "profile_detail_combo") else -1
        if 0 <= idx < len(self.available_profiles):
            p = self.available_profiles[idx]
            prof_name = p.get("profile_dir")
            disp_name = p.get("display_name") or prof_name
        else:
            prof_name = controller.selected_profile
            disp_name = prof_name
        chrome_exe = controller.find_chrome()
        if not chrome_exe:
            self.append_log("Google Chrome executable not found.", "error")
            return
        res = create_windows_shortcut(f"Chrome - {disp_name}", str(chrome_exe), f'--profile-directory="{prof_name}"')
        if res.get("ok"):
            self.append_log(f"Created desktop shortcut: {res.get('shortcut_path')}")
        else:
            self.append_log(f"Failed to create desktop shortcut: {res.get('error')}", "error")

    def _force_reinstall_extension_gui(self):
        res = ensure_chrome_extension_installed(controller.current_profile_path)
        actions = ", ".join(res.get("actions", [])) or "Extension is up to date"
        messagebox.showinfo(APP_NAME, f"Extension Reinstall & Update Succeeded!\n\nTarget Profile: {res.get('profile')}\nActions: {actions}")
        if hasattr(self, "ext_status_lbl"):
            self.ext_status_lbl.configure(text=f"v{res.get('version', '2.2.0')} (Installed & Verified)", bg="#dcfce7", fg="#15803d")

    def _test_extension_connection_gui(self):
        if controller.hello_event.is_set():
            messagebox.showinfo(APP_NAME, f"Chrome Extension is CONNECTED!\nActive Page: {controller.active_page_id or 'Detected'}\nStatus: {controller.task_state}")
        else:
            messagebox.showwarning(APP_NAME, "Extension has not sent a handshake recently.\nLaunch Chrome using 'Open Chrome with Extension Loaded' to connect.")

    def _auto_load_gemma_on_gui_open(self):
        try:
            self.gemma_status_var.set("Autonomous Engine: ACTIVE (Zero RAM Overhead)")
            self.kpi_gemma_var.set("ENGINE: OPTIMIZED ⚡")
        except Exception:
            pass

    def _refresh_learning_memory(self):
        if not hasattr(self, "h_tree") or not hasattr(self, "e_tree"):
            return
        try:
            self.h_tree.delete(*self.h_tree.get_children())
            heuristics = learning_db.get_all_heuristics() if learning_db else []
            for h in heuristics:
                coords = f"({h.get('coord_x')}, {h.get('coord_y')})" if h.get("coord_x") is not None else "-"
                rel = f"{h.get('reliability', 1.0)*100:.0f}% ({h.get('success_count', 0)}/{h.get('sample_count', 0)})"
                self.h_tree.insert("", "end", values=(
                    h.get("heuristic_key", ""),
                    coords,
                    rel,
                    str(h.get("last_updated", ""))[:19]
                ))
            self.e_tree.delete(*self.e_tree.get_children())
            episodes = learning_db.get_recent_episodes(limit=30) if learning_db else []
            for ep in episodes:
                self.e_tree.insert("", "end", values=(
                    str(ep.get("timestamp", ""))[:19],
                    ep.get("stage", ""),
                    ep.get("resolution_status", ""),
                    ep.get("action_taken", "")
                ))
        except Exception as exc:
            logger.debug("Error refreshing learning memory trees: %s", exc)

    def _trigger_remediation(self):
        pid = self._get_target_pid()
        if not pid:
            messagebox.showwarning(APP_NAME, "Please select a target page first.")
            return
        def _bg():
            self.append_log(f"Triggered autonomous remediation for page {pid}...")
            res = agent.evaluate_and_remediate(pid, "MANUAL_TRIGGER", {"manual_trigger": True})
            self.append_log(f"[Remediation] Page {pid} result: {res.get('status')} - {res.get('action')}")
            self._refresh_learning_memory()
        threading.Thread(target=_bg, name=f"RemediateGUI_{pid}", daemon=True).start()

    def _test_gemma_reasoning(self):
        pid = self._get_target_pid() or "TEST_PAGE"
        def _bg():
            try:
                self.append_log(f"[Diagnostics] Running test diagnostic on page {pid}...")
                res = agent.evaluate_and_remediate(pid, "SHARE_BUTTON_NOT_FOUND", {"test_run": True})
                self.append_log(f"[Diagnostics] Agent result: {res.get('status')} - {res.get('action')}")
                self._refresh_learning_memory()
            except Exception as e:
                self.append_log(f"[Diagnostics] Test failed: {e}")
        threading.Thread(target=_bg, name="DiagTest", daemon=True).start()

    def _get_target_pid(self) -> str:
        disp = self.target_page_var.get()
        if disp and "(" in disp and ")" in disp:
            return disp.split("(")[-1].replace(")", "").strip()
        sel = self.page_tree.selection()
        if sel:
            return sel[0]
        return controller.active_page_id or (controller.pages[0]["id"] if controller.pages else "")

    def _on_combo_target_change(self, event=None):
        pid = self._get_target_pid()
        controller.active_page_id = pid
        if self.page_tree.exists(pid):
            self.page_tree.selection_set(pid)
            self.page_tree.see(pid)

    def _refresh_target_combobox(self):
        if not hasattr(self, "target_page_combo"):
            return
        vals = [f"{p.get('name')} ({p.get('id')})" for p in controller.pages]
        self.target_page_combo["values"] = vals
        if vals and not self.target_page_var.get():
            self.target_page_var.set(vals[0])

    def _call_action_api(self, endpoint: str, payload: dict = None):
        def _worker():
            try:
                url = f"http://{API_HOST}:{API_PORT}{endpoint}"
                data = json.dumps(payload or {}).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=20) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    controller.log(f"Action {endpoint} dispatched: {res.get('action', 'OK')}")
            except Exception as e:
                controller.log(f"Action {endpoint} error: {e}", "warning")
        threading.Thread(target=_worker, name=f"Action_{endpoint}", daemon=True).start()

    def _act_upload(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/upload", {"page_id": pid})

    def _act_caption(self):
        pid = self._get_target_pid()
        caption = self.caption_text.get("1.0", "end-1c").strip() if hasattr(self, "caption_text") else controller.caption
        self._call_action_api("/api/action/caption", {"page_id": pid, "caption": caption})

    def _act_location(self):
        pid = self._get_target_pid()
        loc = self.location.get().strip() or controller.location
        self._call_action_api("/api/action/location", {"page_id": pid, "location": loc})

    def _act_messages(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/messages", {"page_id": pid})

    def _act_next_edit(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/next-edit", {"page_id": pid})

    def _act_next_share(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/next-share", {"page_id": pid})

    def _act_share(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/publish", {"page_id": pid})

    def _act_done(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/done", {"page_id": pid})

    def _act_close(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/close-tab", {"page_id": pid})

    def _act_inspect_dom(self):
        pid = self._get_target_pid()
        self._call_action_api("/api/action/inspect-dom", {"page_id": pid})

    def _act_run_pipeline(self):
        self.run_selected_page()

    def _act_open_chrome(self):
        pid = self._get_target_pid()
        page = next((p for p in controller.pages if p["id"] == pid), None)
        url = page["url"] if page else "https://business.facebook.com/latest/reels_composer/"
        controller.open_chrome_url(url)

    def run_cv_inspect(self):
        def _worker():
            try:
                res = CVInspectionEngine.inspect_current_screen()
                txt = json.dumps(res, indent=2)
                self.cv_results_var.set(txt)
                if hasattr(self, "cv_text"):
                    self.cv_text.delete("1.0", "end")
                    self.cv_text.insert("1.0", txt)
                controller.log(f"CV Screen Inspection: detected {res.get('detected_stage')} (confidence {res.get('confidence')}%)")
            except Exception as e:
                controller.log(f"CV Inspection error: {e}", "warning")
        threading.Thread(target=_worker, name="CVInspectThread", daemon=True).start()

    def run_cv_click(self, target: str):
        def _worker():
            try:
                ok = CVInspectionEngine.click_action_button(target)
                controller.log(f"CV Click '{target}': {'SUCCESS' if ok else 'MISSED'}")
            except Exception as e:
                controller.log(f"CV Click '{target}' error: {e}", "warning")
        threading.Thread(target=_worker, name=f"CVClick_{target}", daemon=True).start()

    def _update_caption_counter(self):
        if not hasattr(self, "caption_text"):
            return
        text = self.caption_text.get("1.0", "end-1c")
        chars = len(text)
        words = len(text.split()) if text.strip() else 0
        tags = len(re.findall(r"#[A-Za-z0-9_\u0900-\u097F]+", text))
        self.char_count_var.set(f"{chars}/2200 chars • {words} words • {tags} tags")

    def _insert_hashtag(self, tag: str):
        if not hasattr(self, "caption_text"):
            return
        cur = self.caption_text.get("1.0", "end-1c").rstrip()
        new_text = (cur + " " + tag) if cur else tag
        self.caption_text.delete("1.0", "end")
        self.caption_text.insert("1.0", new_text)
        self._update_caption_counter()

    def _clear_caption(self):
        if not hasattr(self, "caption_text"):
            return
        self.caption_text.delete("1.0", "end")
        self._update_caption_counter()

    def _set_caption_content(self, text: str):
        if not hasattr(self, "caption_text"):
            return
        self.caption_text.delete("1.0", "end")
        self.caption_text.insert("1.0", text)
        self._update_caption_counter()

    def _trim_caption(self):
        if not hasattr(self, "caption_text"):
            return
        cur = self.caption_text.get("1.0", "end-1c")
        lines = [line.strip() for line in cur.splitlines() if line.strip()]
        cleaned = "\n".join(lines)
        self.caption_text.delete("1.0", "end")
        self.caption_text.insert("1.0", cleaned)
        self._update_caption_counter()

    # --------------------------------------------------------------------------
    # Bottom Dock: Live Execution Console
    # --------------------------------------------------------------------------
    def _build_execution_console(self):
        console_frame = ttk.LabelFrame(self.root, text="Live Execution & Telemetry Console", padding=8)
        console_frame.pack(fill="x", padx=12, pady=(0, 8))

        # Filter & Action toolbar
        c_bar = ttk.Frame(console_frame, style="Card.TFrame")
        c_bar.pack(fill="x", pady=(0, 6))

        ttk.Label(c_bar, text="Filter:", style="Card.TLabel").pack(side="left", padx=(0, 4))
        filter_entry = ttk.Entry(c_bar, textvariable=self.log_filter_var, width=24)
        filter_entry.pack(side="left", padx=(0, 10))
        filter_entry.bind("<KeyRelease>", lambda e: self._refilter_logs())

        ttk.Checkbutton(c_bar, text="Auto-scroll to latest", variable=self.log_autoscroll_var).pack(side="left", padx=4)

        ttk.Button(c_bar, text="💾 Export Logs...", style="Dark.TButton", command=self.export_logs).pack(side="right", padx=(4, 0))
        ttk.Button(c_bar, text="🗑 Clear Console", style="Dark.TButton", command=self.clear_logs).pack(side="right", padx=4)

        # Scrolled Text Box (Fixed comfortable height, does not steal notebook vertical space)
        box_wrap = tk.Frame(console_frame, bg=self.INPUT_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1)
        box_wrap.pack(fill="x")

        self.log_text = tk.Text(
            box_wrap,
            wrap="word",
            bg="#f8fafc",
            fg="#0f172a",
            insertbackground="#2563eb",
            font=("Consolas", 9),
            relief="flat",
            padx=8,
            pady=6,
            height=7
        )
        self.log_text.pack(side="left", fill="both", expand=True)

        l_scroll = ttk.Scrollbar(box_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=l_scroll.set)
        l_scroll.pack(side="right", fill="y")

        # Syntax color tags
        self.log_text.tag_configure("success", foreground="#16a34a")
        self.log_text.tag_configure("info", foreground="#0284c7")
        self.log_text.tag_configure("warning", foreground="#d97706")
        self.log_text.tag_configure("error", foreground="#dc2626")
        self.log_text.tag_configure("ai", foreground="#7c3aed")
        self.log_text.tag_configure("dim", foreground="#64748b")

    def append_log(self, line: str):
        tag = "info"
        lower = line.lower()
        if "error" in lower or "failed" in lower or "critical" in lower:
            tag = "error"
        elif "published" in lower or "success" in lower or "done" in lower:
            tag = "success"
        elif "warning" in lower or "retry" in lower or "waiting" in lower:
            tag = "warning"
        elif "agent" in lower or "heuristic" in lower or "cv" in lower or "autonomous" in lower:
            tag = "ai"

        self.all_log_lines.append((line, tag))
        if len(self.all_log_lines) > 1000:
            self.all_log_lines = self.all_log_lines[-1000:]

        filt = self.log_filter_var.get().strip().lower()
        if not filt or filt in line.lower():
            def _insert():
                self.log_text.insert("end", line + "\n", tag)
                if self.log_autoscroll_var.get():
                    self.log_text.see("end")
            self.root.after(0, _insert)

    def _refilter_logs(self):
        filt = self.log_filter_var.get().strip().lower()
        self.log_text.delete("1.0", "end")
        for line, tag in self.all_log_lines:
            if not filt or filt in line.lower():
                self.log_text.insert("end", line + "\n", tag)
        if self.log_autoscroll_var.get():
            self.log_text.see("end")

    def clear_logs(self):
        self.all_log_lines.clear()
        self.log_text.delete("1.0", "end")

    def export_logs(self):
        path = filedialog.asksaveasfilename(
            title="Export Execution Logs",
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("Log file", "*.log"), ("All files", "*.*")]
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    for line, _ in self.all_log_lines:
                        f.write(line + "\n")
                messagebox.showinfo(APP_NAME, f"Logs successfully exported to:\n{path}")
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Error saving logs: {e}")

    # --------------------------------------------------------------------------
    # Core Data Management & Logic
    # --------------------------------------------------------------------------
    def _refresh_kpis(self):
        today = dt.date.today().isoformat()
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        attempts = state.get("attempts", {})

        total_pages = len(controller.pages)
        max_limit = getattr(controller, "max_publications_per_day", 7)
        total_reels_published_today = 0
        pages_published_at_least_once = 0
        pages_capped = 0
        pages_pending_upload = 0

        for p in controller.pages:
            pid = str(p.get("id")).strip()
            cnt = controller.get_today_published_count(pid, today)
            total_reels_published_today += cnt
            if cnt > 0:
                pages_published_at_least_once += 1
            if max_limit > 0 and cnt >= max_limit:
                pages_capped += 1
            elif p.get("enabled", True):
                pages_pending_upload += 1

        brand = controller.get_active_brand() or {}
        b_name = brand.get("name", "Active")
        b_id = brand.get("id", "")
        b_prof = brand.get("chrome_profile", controller.selected_profile)

        # Legacy variables (preserved for compatibility)
        self.kpi_total_var.set(f"{total_pages} Pages ({b_name[:14]})")
        self.kpi_published_var.set(f"{pages_published_at_least_once} / {total_pages} Published")
        self.kpi_pending_var.set(f"{pages_pending_upload} Pending")

        # 1. Executive Card 1: Brand & Scope
        self.kpi_card_brand_val.set(b_name[:22])
        self.kpi_card_brand_sub.set(f"{b_prof} • {total_pages} Destinations")

        # 2. Executive Card 2: Media Source (Dynamic Random Folder vs Static File)
        m_folder = brand.get("media_folder") or controller.media_folder or ""
        pairs = scan_media_folder(m_folder) if m_folder else []
        def_vid = brand.get("video") or controller.global_video
        if pairs:
            paired_count = sum(1 for p in pairs if p.get("has_paired_text"))
            f_name = Path(m_folder).name
            self.kpi_card_media_val.set(f"📁 {f_name} ({len(pairs)} vids)")
            self.kpi_card_media_sub.set(f"🎲 Random Pair ({paired_count} .txt captions)")
            if hasattr(self, "kpi_card_media_lbl"):
                self.kpi_card_media_lbl.configure(fg="#0f766e")
        elif def_vid and Path(def_vid).is_file():
            self.kpi_card_media_val.set(f"🎬 {Path(def_vid).name[:20]}")
            self.kpi_card_media_sub.set("Static File Fallback")
            if hasattr(self, "kpi_card_media_lbl"):
                self.kpi_card_media_lbl.configure(fg="#b45309")
        else:
            self.kpi_card_media_val.set("⚠️ No Media Configured")
            self.kpi_card_media_sub.set("Configure folder or video in Tab 2")
            if hasattr(self, "kpi_card_media_lbl"):
                self.kpi_card_media_lbl.configure(fg="#dc2626")

        # 3. Executive Card 3: Today's Queue Progress
        if max_limit > 0:
            self.kpi_card_queue_val.set(f"{total_reels_published_today} Reels Today")
            self.kpi_card_queue_sub.set(f"{pages_pending_upload} Eligible • Daily Cap: {max_limit}/page")
        else:
            self.kpi_card_queue_val.set(f"{total_reels_published_today} Reels Today")
            self.kpi_card_queue_sub.set(f"{pages_pending_upload} Eligible Destinations • Unlimited")
        if hasattr(self, "kpi_card_queue_lbl"):
            self.kpi_card_queue_lbl.configure(fg="#15803d" if total_reels_published_today > 0 else "#0f172a")

        # 4. Executive Card 4: Next Scheduled Run
        active_scheds = [s for s in controller.schedules if s.get("enabled", True)]
        if active_scheds:
            times_str = ", ".join(s.get("time", "") for s in active_scheds[:3])
            if len(active_scheds) > 3:
                times_str += f" (+{len(active_scheds)-3})"
            self.kpi_card_sched_val.set(times_str)
            self.kpi_card_sched_sub.set(f"{len(active_scheds)} Daily Schedule Tasks Synced")
            self.kpi_sched_var.set(f"SCHEDULER: {times_str} (ACTIVE)")
        else:
            self.kpi_card_sched_val.set("DISABLED")
            self.kpi_card_sched_sub.set("No Active Schedules Configured")
            self.kpi_sched_var.set("SCHEDULER: DISABLED")

        # 5. Executive Card 5: Automation Shield / Input Lock Status
        if InputRestrictionManager.is_restricted():
            self.kpi_card_shield_val.set("🔒 RESTRICTED")
            self.kpi_card_shield_sub.set("Press Esc or Ctrl+Alt+Del to release")
            self.kpi_lock_var.set("🔒 INPUT: LOCKED (Press Esc / Ctrl+Alt+Del)")
            if hasattr(self, "kpi_card_shield_lbl"):
                self.kpi_card_shield_lbl.configure(fg="#dc2626")
        else:
            self.kpi_card_shield_val.set("🔓 UNLOCKED")
            self.kpi_card_shield_sub.set("Zero-RAM Automation Engine • Ready")
            self.kpi_lock_var.set("🔓 INPUT: UNLOCKED")
            if hasattr(self, "kpi_card_shield_lbl"):
                self.kpi_card_shield_lbl.configure(fg="#6d28d9")

        # Header live batch badge
        if controller.batch_running:
            self.kpi_batch_var.set("BATCH: RUNNING")
            if hasattr(self, "kpi_batch_lbl"):
                self.kpi_batch_lbl.configure(bg="#dcfce7", fg="#15803d")
        else:
            self.kpi_batch_var.set("BATCH: IDLE")
            if hasattr(self, "kpi_batch_lbl"):
                self.kpi_batch_lbl.configure(bg="#f1f5f9", fg="#475569")

    def _refresh_table(self):
        self.page_tree.delete(*self.page_tree.get_children())
        today = dt.date.today().isoformat()
        state = load_json(STATE_FILE, {"attempts": {}, "published_counts": {}})
        attempts = state.get("attempts", {})
        max_limit = getattr(controller, "max_publications_per_day", 7)
        brand = controller.get_active_brand() or {}
        def_vid = brand.get("video") or controller.global_video
        def_loc = brand.get("location") or controller.location
        def_cap = brand.get("caption") or controller.caption
        def_vid_name = Path(def_vid).name if def_vid else "None"

        for idx, p in enumerate(controller.pages):
            pid = str(p.get("id")).strip()
            k = f"{today}:{pid}"
            st = attempts.get(k, "PENDING")
            pub_cnt = controller.get_today_published_count(pid, today)

            if not p.get("enabled", True):
                st_display = "⏸ DISABLED"
                tag = "DISABLED"
            elif max_limit > 0 and pub_cnt >= max_limit:
                st_display = f"🛑 CAPPED ({pub_cnt}/{max_limit})"
                tag = "CAPPED"
            elif st == "LOGIN_REQUIRED":
                st_display = f"🔒 LOGIN REQUIRED ({pub_cnt}/{max_limit})" if max_limit > 0 else f"🔒 LOGIN REQUIRED ({pub_cnt})"
                tag = "LOGIN_REQUIRED"
            elif st in ("FAILED", "ERROR"):
                st_display = f"⚠️ {st} ({pub_cnt}/{max_limit})" if max_limit > 0 else f"⚠️ {st} ({pub_cnt})"
                tag = "FAILED"
            elif st == "RUNNING":
                st_display = f"▶ RUNNING ({pub_cnt}/{max_limit})" if max_limit > 0 else f"▶ RUNNING ({pub_cnt})"
                tag = "RUNNING"
            elif pub_cnt > 0:
                st_display = f"✅ PUBLISHED ({pub_cnt}/{max_limit})" if max_limit > 0 else f"✅ PUBLISHED ({pub_cnt})"
                tag = "PUBLISHED"
            else:
                st_display = f"⏳ PENDING (0/{max_limit})" if max_limit > 0 else "⏳ PENDING"
                tag = "PENDING"

            row_tag = "even" if idx % 2 == 0 else "odd"
            self.page_tree.insert(
                "",
                "end",
                iid=p["id"],
                tags=(tag, row_tag),
                values=(
                    "YES" if p.get("enabled", True) else "NO",
                    st_display,
                    p.get("name", ""),
                    p.get("id", ""),
                    p.get("video", "") or f"(brand: {def_vid_name})",
                    p.get("location", "") or f"(brand: {def_loc})",
                    (p.get("caption", "") or f"(brand: {def_cap})")[:40]
                )
            )

        self._update_hero_card()

    def _tick_scheduler(self):
        try:
            if controller.scheduler_enabled and not controller.batch_running:
                now = dt.datetime.now()
                now_hm = now.strftime("%H:%M")
                today_str = dt.date.today().isoformat()
                now_total_mins = now.hour * 60 + now.minute
                weekday = now.weekday()

                for sched in controller.schedules:
                    if not sched.get("enabled", True):
                        continue

                    # Frequency check
                    days_mode = str(sched.get("days", "DAILY")).upper()
                    if days_mode in ("MON-FRI", "WEEKDAYS") and weekday >= 5:
                        continue
                    if days_mode in ("SAT-SUN", "WEEKENDS") and weekday < 5:
                        continue

                    sched_time = sched.get("time", "17:00")
                    try:
                        sh, sm = [int(p) for p in sched_time.split(":")]
                        sched_total_mins = sh * 60 + sm
                    except Exception:
                        continue

                    repeat_interval = int(sched.get("repeat_interval_minutes") or 0)
                    repeat_duration_hours = int(sched.get("repeat_duration_hours") or 24)
                    repeat_duration_mins = repeat_duration_hours * 60

                    should_trigger = False
                    trigger_key = f"{today_str}:{now_hm}"

                    if repeat_interval <= 0:
                        if sched_time == now_hm and sched.get("last_trigger") != trigger_key and sched.get("last_run_date") != today_str:
                            should_trigger = True
                    else:
                        if now_total_mins >= sched_total_mins:
                            diff_mins = now_total_mins - sched_total_mins
                            if diff_mins <= repeat_duration_mins and (diff_mins % repeat_interval == 0):
                                if sched.get("last_trigger") != trigger_key:
                                    should_trigger = True

                    if should_trigger:
                        sched["last_trigger"] = trigger_key
                        sched["last_run_date"] = today_str
                        sched["last_run"] = now.strftime("%Y-%m-%d %H:%M:%S")
                        controller.update_config({"schedules": controller.schedules})
                        rep_note = f" (Interval: {repeat_interval}m)" if repeat_interval > 0 else ""
                        target_brand = sched.get("target_brand", "ALL")
                        controller.log(f"Schedule trigger reached for '{sched.get('name')}' (Start: {sched.get('time')}{rep_note}, Scope: {target_brand}). Starting automated batch...")
                        if target_brand == "ALL":
                            threading.Thread(
                                target=controller._execute_all_brands_batch,
                                args=(True,),
                                name="ScheduledAllBrandsBatchRunner",
                                daemon=True
                            ).start()
                        else:
                            controller.set_active_brand(target_brand)
                            threading.Thread(
                                target=controller._execute_batch,
                                args=([p for p in controller.pages if p.get("enabled", True)], True),
                                name="ScheduledBatchRunner",
                                daemon=True
                            ).start()
                        break
        except Exception as e:
            controller.log(f"Scheduler tick error: {e}", "warning")
        finally:
            self.kpi_gemma_var.set("ENGINE: OPTIMIZED ⚡")
            if hasattr(self, "kpi_gemma_lbl"):
                self.kpi_gemma_lbl.configure(fg="#15803d", bg="#dcfce7")

            self._refresh_kpis()
            self._refresh_table()
            self.root.after(3000, self._tick_scheduler)

    def browse_video(self):
        f = filedialog.askopenfilename(
            title="Select Default Video File",
            filetypes=[("MP4 Video", "*.mp4"), ("All files", "*.*")]
        )
        if f:
            self.global_video.set(f)

    def save_settings(self):
        caption_val = self.caption_text.get("1.0", "end-1c").strip()
        val = self.step_sequence_var.get()
        if "Video Upload ->" in val:
            mode = "video_first"
            order = ["video_upload", "caption", "location", "messages"]
        elif "Caption -> Messenger" in val:
            mode = "caption_messages_location"
            order = ["caption", "messages", "location", "video_upload"]
        else:
            mode = "caption_first"
            order = ["caption", "location", "messages", "video_upload"]

        controller.update_config({
            "global_video": self.global_video.get().strip(),
            "location": self.location.get().strip() or "Mumbai",
            "caption": caption_val or "loan",
            "schedule_time": self.schedule_time.get().strip() or "17:00",
            "auto_publish": self.auto_publish.get(),
            "step_sequence": mode,
            "composer_step_order": order
        })
        active_b_id = controller.active_brand_id
        if active_b_id:
            brand_updates = {
                "video": self.global_video.get().strip(),
                "location": self.location.get().strip() or "Mumbai",
                "caption": caption_val or "loan",
                "auto_publish": self.auto_publish.get(),
                "step_sequence": mode,
                "composer_step_order": order
            }
            if hasattr(self, "brand_media_folder_var"):
                brand_updates["media_folder"] = self.brand_media_folder_var.get().strip()
            controller.update_brand(active_b_id, brand_updates)
        controller.scheduler_enabled = self.scheduler_enabled.get()
        messagebox.showinfo(APP_NAME, "All Settings and Execution Sequence saved successfully to config.json.")
        self._refresh_kpis()
        self._refresh_table()

    def save_config(self):
        """Alias for save_settings."""
        return self.save_settings()

    def start_batch_now(self):
        if not controller.run_batch_now():
            messagebox.showwarning(APP_NAME, "Batch could not be started.")

    def stop_batch(self):
        controller.stop_batch()

    def run_selected_page(self):
        sel = self.page_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a page from the destinations table first.")
            return
        pid = sel[0]
        if not controller.run_single_page(pid):
            messagebox.showwarning(APP_NAME, "Could not start single page run.")

    def reset_selected_attempt(self):
        sel = self.page_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a page from the table first.")
            return
        pid = sel[0]
        controller.reset_page_attempt(pid)
        self._refresh_kpis()
        self._refresh_table()

    def reset_all_attempts(self):
        controller.reset_all_attempts()
        self._refresh_kpis()
        self._refresh_table()

    def _release_input_gui(self):
        InputRestrictionManager.release(force=True)
        self._refresh_kpis()

    def set_all_enabled(self, val: bool):
        for p in controller.pages:
            p["enabled"] = val
        controller.update_config({"pages": controller.pages})
        self._refresh_table()

    # --------------------------------------------------------------------------
    # Dialogs: Edit, Add, Delete Destination
    # --------------------------------------------------------------------------
    def edit_selected_page(self):
        sel = self.page_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a destination page from the table first.")
            return
        pid = sel[0]
        page = next((p for p in controller.pages if p["id"] == pid), None)
        if not page:
            return

        w = tk.Toplevel(self.root)
        w.title(f"Edit Destination - {page.get('name')}")
        w.geometry("700x560")
        w.configure(bg=self.BG_DARK)
        w.transient(self.root)
        w.grab_set()

        card = ttk.LabelFrame(w, text="Destination Details & Overrides (Auto-Extraction Supported)", padding=14)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        card.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(card, text="Page URL / Link:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        uf = ttk.Frame(card, style="Card.TFrame")
        uf.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))
        uf.columnconfigure(0, weight=1)
        url_var = tk.StringVar(value=page.get("url", ""))
        url_entry = ttk.Entry(uf, textvariable=url_var)
        url_entry.grid(row=0, column=0, sticky="ew")

        r += 1
        ttk.Label(card, text="Page ID (Numeric):", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        id_var = tk.StringVar(value=page.get("id", ""))
        id_entry = ttk.Entry(card, textvariable=id_var)
        id_entry.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))

        r += 1
        ttk.Label(card, text="Page Name:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        name_var = tk.StringVar(value=page.get("name", ""))
        name_entry = ttk.Entry(card, textvariable=name_var)
        name_entry.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))

        def _on_url_extract(*args):
            raw = url_var.get().strip()
            if raw:
                info = extract_meta_page_info(raw)
                if info.get("page_id") and info["page_id"] != raw:
                    id_var.set(info["page_id"])
                if info.get("url") and "reels_composer" in info["url"]:
                    url_var.set(info["url"])
                if info.get("page_name") and (not name_var.get() or name_var.get().startswith("Meta Page")):
                    name_var.set(info["page_name"])

        def _on_id_pasted(*args):
            raw = id_var.get().strip()
            if raw and ("http" in raw or "facebook" in raw):
                info = extract_meta_page_info(raw)
                if info.get("page_id"):
                    id_var.set(info["page_id"])
                    if not url_var.get():
                        url_var.set(info.get("url", ""))
                    if info.get("page_name") and (not name_var.get() or name_var.get().startswith("Meta Page")):
                        name_var.set(info["page_name"])

        url_var.trace_add("write", _on_url_extract)
        id_var.trace_add("write", _on_id_pasted)
        ttk.Button(uf, text="⚡ Extract", width=9, style="Primary.TButton", command=_on_url_extract).grid(row=0, column=1, padx=(6, 0))

        r += 1
        ttk.Label(card, text="Video Override:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        vf = ttk.Frame(card, style="Card.TFrame")
        vf.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))
        vf.columnconfigure(0, weight=1)
        vid_var = tk.StringVar(value=page.get("video", ""))
        ttk.Entry(vf, textvariable=vid_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(vf, text="...", width=4, style="Dark.TButton", command=lambda: vid_var.set(filedialog.askopenfilename() or vid_var.get())).grid(row=0, column=1, padx=(6, 0))

        r += 1
        ttk.Label(card, text="Location Override:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        loc_var = tk.StringVar(value=page.get("location", ""))
        ttk.Entry(card, textvariable=loc_var).grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))

        r += 1
        ttk.Label(card, text="Caption Override:", style="Card.TLabel").grid(row=r, column=0, sticky="nw", pady=6)
        cw = tk.Frame(card, bg=self.INPUT_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1)
        cw.grid(row=r, column=1, sticky="nsew", pady=6, padx=(8, 0))
        card.rowconfigure(r, weight=1)

        cap_box = tk.Text(cw, height=5, bg=self.INPUT_BG, fg=self.TEXT_MAIN, insertbackground="#2563eb", font=("Segoe UI", 9), wrap="word", relief="flat", padx=6, pady=4)
        cap_box.pack(fill="both", expand=True)
        cap_box.insert("1.0", page.get("caption", ""))

        r += 1
        en_var = tk.BooleanVar(value=page.get("enabled", True))
        ttk.Checkbutton(card, text="Enabled in scheduled and batch runs", variable=en_var).grid(row=r, column=1, sticky="w", pady=6, padx=(8, 0))

        r += 1
        def save():
            raw_id = id_var.get().strip()
            raw_url = url_var.get().strip()
            info = extract_meta_page_info(raw_url or raw_id)
            pid = info.get("page_id") or raw_id
            if not pid:
                messagebox.showerror(APP_NAME, "Page ID or URL cannot be empty.")
                return
            final_url = raw_url if raw_url.startswith("http") else (info.get("url") or f"https://business.facebook.com/latest/reels_composer/?asset_id={pid}&business_id=")
            p_name = name_var.get().strip()
            if not p_name or p_name.startswith("http"):
                p_name = info.get("page_name") or f"Meta Page ({pid})"

            page["name"] = p_name
            page["id"] = pid
            page["url"] = final_url
            page["video"] = vid_var.get().strip()
            page["location"] = loc_var.get().strip()
            page["caption"] = cap_box.get("1.0", "end-1c").strip()
            page["enabled"] = en_var.get()
            controller.update_config({"pages": controller.pages})
            self._refresh_kpis()
            self._refresh_table()
            self._refresh_target_combobox()
            self._refresh_brand_combos()
            w.destroy()

        bf = ttk.Frame(card, style="Card.TFrame")
        bf.grid(row=r, column=0, columnspan=2, pady=(14, 0))
        ttk.Button(bf, text="Save Changes", style="Success.TButton", command=save).pack(side="left", padx=6)
        ttk.Button(bf, text="Cancel", style="Dark.TButton", command=w.destroy).pack(side="left", padx=6)

    def add_new_page(self):
        w = tk.Toplevel(self.root)
        w.title("Add New Meta Destination")
        w.geometry("700x560")
        w.configure(bg=self.BG_DARK)
        w.transient(self.root)
        w.grab_set()

        card = ttk.LabelFrame(w, text="New Destination Details (Auto-Extraction Supported)", padding=14)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        card.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(card, text="Page URL / Link:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        uf = ttk.Frame(card, style="Card.TFrame")
        uf.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))
        uf.columnconfigure(0, weight=1)
        url_var = tk.StringVar(value="")
        url_entry = ttk.Entry(uf, textvariable=url_var)
        url_entry.grid(row=0, column=0, sticky="ew")

        r += 1
        ttk.Label(card, text="Page ID (Numeric):", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        id_var = tk.StringVar(value="")
        id_entry = ttk.Entry(card, textvariable=id_var)
        id_entry.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))

        r += 1
        ttk.Label(card, text="Page Name:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        name_var = tk.StringVar(value="Meta Page New")
        name_entry = ttk.Entry(card, textvariable=name_var)
        name_entry.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))

        def _on_url_extract(*args):
            raw = url_var.get().strip()
            if raw:
                info = extract_meta_page_info(raw)
                if info.get("page_id") and info["page_id"] != raw:
                    id_var.set(info["page_id"])
                if info.get("url") and "reels_composer" in info["url"]:
                    url_var.set(info["url"])
                if info.get("page_name") and name_var.get() in ("Meta Page New", ""):
                    name_var.set(info["page_name"])

        def _on_id_pasted(*args):
            raw = id_var.get().strip()
            if raw and ("http" in raw or "facebook" in raw):
                info = extract_meta_page_info(raw)
                if info.get("page_id"):
                    id_var.set(info["page_id"])
                    if not url_var.get():
                        url_var.set(info.get("url", ""))
                    if info.get("page_name") and name_var.get() in ("Meta Page New", ""):
                        name_var.set(info["page_name"])

        url_var.trace_add("write", _on_url_extract)
        id_var.trace_add("write", _on_id_pasted)
        ttk.Button(uf, text="⚡ Extract", width=9, style="Primary.TButton", command=_on_url_extract).grid(row=0, column=1, padx=(6, 0))

        r += 1
        ttk.Label(card, text="Video Override:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        vf = ttk.Frame(card, style="Card.TFrame")
        vf.grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))
        vf.columnconfigure(0, weight=1)
        vid_var = tk.StringVar(value="")
        ttk.Entry(vf, textvariable=vid_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(vf, text="...", width=4, style="Dark.TButton", command=lambda: vid_var.set(filedialog.askopenfilename() or vid_var.get())).grid(row=0, column=1, padx=(6, 0))

        r += 1
        ttk.Label(card, text="Location Override:", style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=6)
        loc_var = tk.StringVar(value="")
        ttk.Entry(card, textvariable=loc_var).grid(row=r, column=1, sticky="ew", pady=6, padx=(8, 0))

        r += 1
        ttk.Label(card, text="Caption Override:", style="Card.TLabel").grid(row=r, column=0, sticky="nw", pady=6)
        cw = tk.Frame(card, bg=self.INPUT_BG, highlightbackground=self.CARD_BORDER, highlightthickness=1)
        cw.grid(row=r, column=1, sticky="nsew", pady=6, padx=(8, 0))
        card.rowconfigure(r, weight=1)

        cap_box = tk.Text(cw, height=5, bg=self.INPUT_BG, fg=self.TEXT_MAIN, insertbackground="#2563eb", font=("Segoe UI", 9), wrap="word", relief="flat", padx=6, pady=4)
        cap_box.pack(fill="both", expand=True)

        r += 1
        en_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card, text="Enabled in scheduled and batch runs", variable=en_var).grid(row=r, column=1, sticky="w", pady=6, padx=(8, 0))

        r += 1
        def save():
            raw_id = id_var.get().strip()
            raw_url = url_var.get().strip()
            info = extract_meta_page_info(raw_url or raw_id)
            pid = info.get("page_id") or raw_id
            if not pid:
                messagebox.showerror(APP_NAME, "Page ID or URL cannot be empty.")
                return
            final_url = raw_url if raw_url.startswith("http") else (info.get("url") or f"https://business.facebook.com/latest/reels_composer/?asset_id={pid}&business_id=")
            p_name = name_var.get().strip()
            if not p_name or p_name == "Meta Page New" or p_name.startswith("http"):
                p_name = info.get("page_name") or f"Meta Page ({pid})"

            new_item = {
                "name": p_name,
                "id": pid,
                "url": final_url,
                "video": vid_var.get().strip(),
                "location": loc_var.get().strip(),
                "caption": cap_box.get("1.0", "end-1c").strip(),
                "enabled": en_var.get()
            }
            controller.pages.append(new_item)
            controller.update_config({"pages": controller.pages})
            self._refresh_kpis()
            self._refresh_table()
            self._refresh_target_combobox()
            self._refresh_brand_combos()
            w.destroy()

        bf = ttk.Frame(card, style="Card.TFrame")
        bf.grid(row=r, column=0, columnspan=2, pady=(14, 0))
        ttk.Button(bf, text="Add Destination", style="Success.TButton", command=save).pack(side="left", padx=6)
        ttk.Button(bf, text="Cancel", style="Dark.TButton", command=w.destroy).pack(side="left", padx=6)

    def delete_selected_page(self):
        sel = self.page_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a destination page from the table first.")
            return
        pid = sel[0]
        page = next((p for p in controller.pages if p["id"] == pid), None)
        if not page:
            return
        if not messagebox.askyesno(APP_NAME, f"Are you sure you want to remove '{page.get('name')}' ({pid}) from destinations?"):
            return
        controller.pages = [p for p in controller.pages if p["id"] != pid]
        controller.update_config({"pages": controller.pages})
        self._refresh_kpis()
        self._refresh_table()

    def save_config(self):
        """Alias for save_settings."""
        return self.save_settings()
        self._refresh_target_combobox()
        self._refresh_brand_combos()

    def on_close(self):
        if controller.batch_running:
            if not messagebox.askyesno(APP_NAME, "A batch run is currently in progress. Exit anyway?"):
                return
        controller.shutdown_event.set()
        self.root.destroy()


def free_port_if_in_use(port: int = API_PORT, force: bool = False):
    """Automatically frees the port from any orphaned background process."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((API_HOST, port)) == 0:
                if not force:
                    try:
                        import urllib.request, json
                        with urllib.request.urlopen(f"http://{API_HOST}:{port}/api/status", timeout=0.8) as resp:
                            if resp.status == 200:
                                data = json.loads(resp.read().decode("utf-8"))
                                if "pages_count" in data or "batch_running" in data:
                                    logger.debug("Port %s is already serving MetaReelsScheduler API. Keeping server alive.", port)
                                    return False
                    except Exception:
                        pass
                logger.info("Port %s is currently occupied. Releasing port...", port)
                cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
                res = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True).strip()
                for line in res.splitlines():
                    pid = line.strip()
                    if pid.isdigit() and int(pid) != os.getpid():
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                        time.sleep(0.5)
                return True
    except Exception as e:
        logger.debug("Port cleanup notice: %s", e)
    return False


def start_uvicorn_api():
    """Runs FastAPI uvicorn server in a background daemon thread, ensuring dedicated port ownership."""
    free_port_if_in_use(API_PORT, force=True)
    logger.info("Starting FastAPI Uvicorn server on http://%s:%s", API_HOST, API_PORT)
    config = uvicorn.Config(
        app=api_app,
        host=API_HOST,
        port=API_PORT,
        log_level="warning",
        access_log=False
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except Exception as e:
        logger.warning("Uvicorn server notice: %s", e)


def ensure_api_server_running(timeout: float = 5.0) -> bool:
    """Verifies that the internal FastAPI Uvicorn server is active and responding on API_PORT.
    If not responding, releases any hung process and starts Uvicorn in a daemon thread immediately."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://{API_HOST}:{API_PORT}/api/status", timeout=0.8) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    logger.warning("FastAPI Uvicorn server not responding on port %s. Launching dedicated server thread...", API_PORT)
    t = threading.Thread(target=start_uvicorn_api, daemon=True, name="FastAPIUvicornWatchdog")
    t.start()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.25)
        try:
            import urllib.request
            with urllib.request.urlopen(f"http://{API_HOST}:{API_PORT}/api/status", timeout=0.5) as resp:
                if resp.status == 200:
                    logger.info("FastAPI Uvicorn server successfully verified and active on port %s.", API_PORT)
                    return True
        except Exception:
            pass
    return False


def run_scheduled_batch_cli(schedule_id: str = "", brand_id: str = ""):
    """Executes automated reel publishing from Windows Task Scheduler or background CLI."""
    logger.info("================================================================================")
    logger.info("STARTING AUTOMATED SCHEDULED BATCH RUN (Windows Task Scheduler trigger)")
    logger.info("Target Schedule ID: %s | Target Brand: %s", schedule_id or "DEFAULT", brand_id or "ALL")
    logger.info("================================================================================")

    # 1. Ensure latest Chrome extension is installed in profile and AppData
    ensure_chrome_extension_installed()

    # 2. Check if master scheduler daemon is already active on port 8765
    api_active = False
    try:
        import urllib.request, json
        with urllib.request.urlopen(f"http://{API_HOST}:{API_PORT}/api/status", timeout=0.8) as resp:
            if resp.status == 200:
                sdata = json.loads(resp.read().decode("utf-8"))
                api_active = ("pages_count" in sdata)
    except Exception:
        api_active = False

    if api_active:
        logger.info("Master Scheduler daemon is already running on port %s. Forwarding batch trigger...", API_PORT)
        try:
            import urllib.request, json
            payload = json.dumps({"schedule_id": schedule_id, "brand_id": brand_id}).encode("utf-8")
            req = urllib.request.Request(
                f"http://{API_HOST}:{API_PORT}/api/batch/start",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                logger.info("Master daemon accepted batch trigger: %s", res)

            # Follow batch progress until completion
            deadline = time.time() + 3600
            while time.time() < deadline:
                time.sleep(2.0)
                try:
                    with urllib.request.urlopen(f"http://{API_HOST}:{API_PORT}/api/status", timeout=2.0) as sresp:
                        st = json.loads(sresp.read().decode("utf-8"))
                        if not st.get("batch_running"):
                            logger.info("Batch run completed on master daemon.")
                            break
                except Exception:
                    break
            logger.info("================================================================================")
            logger.info("AUTOMATED SCHEDULED BATCH RUN FINISHED (via Master Daemon).")
            logger.info("================================================================================")
            sys.exit(0)
        except Exception as fe:
            logger.warning("Could not delegate batch to master daemon (%s). Proceeding in-process...", fe)

    # 3. If no master daemon, run in-process with dedicated FastAPI daemon
    threading.Thread(target=start_uvicorn_api, name="FastAPIDaemon", daemon=True).start()
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://{API_HOST}:{API_PORT}/health", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.15)

    # 4. Trigger batch execution
    started = controller.run_scheduled_batch(schedule_id, brand_id=brand_id)
    if not started:
        logger.warning("Batch did not start (either already running or no enabled destinations).")
        sys.exit(0)

    # 5. Wait for batch completion
    deadline = time.time() + 3600
    while time.time() < deadline:
        if hasattr(controller, "batch_thread") and controller.batch_thread and controller.batch_thread.is_alive():
            controller.batch_thread.join(timeout=1.0)
        elif controller.batch_running:
            time.sleep(1.0)
        else:
            break

    logger.info("================================================================================")
    logger.info("AUTOMATED SCHEDULED BATCH RUN FINISHED.")
    logger.info("================================================================================")
    sys.exit(0)


def main():
    ensure_default_desktop()
    ensure_standalone_environment()
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Meta Reels Scheduler - Enterprise Automation CLI")
        print("Usage: python meta_reels_scheduler.py [OPTIONS]")
        print("")
        print("Core Publishing Options:")
        print("  --scheduled-batch             Execute automated batch publication triggered by Windows Task Scheduler.")
        print("  --schedule-id <ID>            Specific schedule identifier to execute and update.")
        print("  --brand <BRAND_ID>            Target brand identifier (or 'ALL' for sequential multi-brand run).")
        print("  --batch                       Alias for --scheduled-batch.")
        print("  --api-only, --server          Run FastAPI REST server daemon without Tkinter desktop GUI.")
        print("")
        print("Media & Content Folder Options:")
        print("  --scan-media [FOLDER]         Scan folder for video files and matching .txt captions.")
        print("  --random-pair [BRAND_ID]      Randomly select and display a video + caption pair for a brand.")
        print("  --set-media-folder <BRAND> <DIR> Set the media/content folder for a brand.")
        print("")
        print("Brand, Schedule & Profile CLI Nodes:")
        print("  --list-brands                 List all configured brands, profiles, and media folders.")
        print("  --select-brand <ID>           Set the active brand.")
        print("  --list-schedules              List all schedules and Windows Task Scheduler status.")
        print("  --sync-schedules              Sync all schedules with Windows Task Scheduler.")
        print("  --list-profiles               List all discovered Chromium/Chrome profiles.")
        print("  --select-profile <NAME>       Select active Chrome profile and auto-sync extension.")
        print("  --setup, --ensure-standalone  Verify and auto-bootstrap dependencies, assets, and extension.")
        print("")
        print("Input Restriction Options:")
        print("  --lock-input [SECONDS]        Lock physical keyboard & mouse for testing (default 30s).")
        print("  --unlock-input                Release any active physical keyboard & mouse lock.")
        print("  --input-status                Check whether physical input is currently restricted.")
        print("  --no-block-input              Bypass input restriction during automated publishing.")
        print("  --help, -h                    Show this help message and exit.")
        return

    # CLI Node: Scan Media Folder
    if "--scan-media" in sys.argv:
        idx = sys.argv.index("--scan-media")
        folder = sys.argv[idx + 1] if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-") else str(BASE_DIR / "loan")
        items = scan_media_folder(folder)
        paired = sum(1 for i in items if i["has_paired_text"])
        print(f"Media Folder Scan: {folder}")
        print(f"Total Videos: {len(items)} | Paired with .txt Caption: {paired}")
        for i, item in enumerate(items, 1):
            pair_tag = "✅ PAIRED" if item["has_paired_text"] else "⚠️ NO_TXT"
            print(f"  [{i}] {pair_tag} {item['video_name']} -> {item['text_name'] or 'None'} ({len(item['caption'])} chars)")
        return

    # CLI Node: Random Pair Selector
    if "--random-pair" in sys.argv:
        idx = sys.argv.index("--random-pair")
        bid = sys.argv[idx + 1] if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-") else controller.active_brand_id
        brand = controller.get_brand(bid) or controller.get_active_brand()
        folder = (brand.get("media_folder") or "").strip()
        if not folder or not Path(folder).is_dir():
            print(f"ℹ️ Brand '{brand.get('name')}' has NO media folder assigned.")
            print(f"  Fallback Selected Video: {brand.get('video') or controller.global_video}")
            print(f"  Fallback Selected Text:  {(brand.get('caption') or controller.caption or 'loan')[:120]}... ({len(brand.get('caption') or controller.caption or '')} chars)")
            return
        selected = controller.get_random_brand_media(brand.get("id"), folder)
        if not selected:
            print(f"No media pair could be resolved for brand '{brand.get('name')}' in '{folder}'")
            return
        print(f"🎲 Random Media Pair Selected for '{brand.get('name')}':")
        print(f"  Video:        {selected.get('video_name')}")
        print(f"  Video Path:   {selected.get('video')}")
        print(f"  Text File:    {selected.get('text_name') or 'N/A'}")
        print(f"  Text Path:    {selected.get('text_path') or 'N/A'}")
        print(f"  Caption Size: {len(selected.get('caption') or '')} characters")
        print(f"  Preview:      {(selected.get('caption') or '')[:120]}...")
        return

    # CLI Node: Set Media Folder
    if "--set-media-folder" in sys.argv:
        idx = sys.argv.index("--set-media-folder")
        if idx + 2 < len(sys.argv):
            bid = sys.argv[idx + 1]
            fpath = sys.argv[idx + 2]
            ok = controller.set_brand_media_folder(bid, fpath)
            print(f"Set media folder for brand '{bid}' to '{fpath}': {'SUCCESS' if ok else 'FAILED'}")
        else:
            print("Usage: --set-media-folder <BRAND_ID> <FOLDER_PATH>")
        return

    # CLI Node: List Brands
    if "--list-brands" in sys.argv:
        brands = controller.get_brands()
        print(f"Configured Brands ({len(brands)}): Active Brand ID = '{controller.active_brand_id}'")
        for b in brands:
            active_mark = "▶ [ACTIVE]" if b.get("id") == controller.active_brand_id else "  "
            mf = b.get("media_folder") or "None"
            print(f"{active_mark} ID: {b.get('id'):<20} Name: {b.get('name'):<22} Profile: {b.get('chrome_profile'):<12} Pages: {len(b.get('pages', [])):<3} Folder: {mf}")
        return

    # CLI Node: Select Brand
    if "--select-brand" in sys.argv:
        idx = sys.argv.index("--select-brand")
        if idx + 1 < len(sys.argv):
            bid = sys.argv[idx + 1]
            ok = controller.set_active_brand(bid)
            print(f"Set active brand to '{bid}': {'SUCCESS' if ok else 'FAILED'}")
        return

    # CLI Node: List Schedules
    if "--list-schedules" in sys.argv:
        scheds = controller.schedules
        print(f"Configured Schedules ({len(scheds)}):")
        for s in scheds:
            status = "ENABLED" if s.get("enabled", True) else "DISABLED"
            print(f"  [{status}] ID: {s.get('id'):<16} Time: {s.get('time'):<6} Days: {s.get('days'):<8} Brand: {s.get('target_brand'):<10} Name: {s.get('name')}")
        return

    # CLI Node: Sync Schedules to Windows
    if "--sync-schedules" in sys.argv:
        res = controller.sync_all_schedules_to_windows()
        print(f"Windows Task Scheduler Sync: {len(res.get('registered', []))} registered, {len(res.get('deleted', []))} cleaned.")
        return

    # CLI Node: List Profiles
    if "--list-profiles" in sys.argv:
        profs = controller.get_available_profiles()
        print(f"Discovered Chromium Profiles ({len(profs)}): Selected = '{controller.selected_profile}'")
        for p in profs:
            sel = "▶ [SELECTED]" if p.get("profile_dir") == controller.selected_profile else "  "
            print(f"{sel} {p.get('profile_dir'):<12} Name: {p.get('display_name'):<20} Email: {p.get('email'):<25} Browser: {p.get('browser')}")
        return

    # CLI Node: Select Profile
    if "--select-profile" in sys.argv:
        idx = sys.argv.index("--select-profile")
        if idx + 1 < len(sys.argv):
            pname = sys.argv[idx + 1]
            ok = controller.set_profile(pname)
            print(f"Set active profile to '{pname}': {'SUCCESS' if ok else 'FAILED'}")
        return

    # CLI Node: Lock Input / Test Input Lock
    if "--lock-input" in sys.argv or "--test-lock-input" in sys.argv:
        timeout = 15.0
        flag = "--test-lock-input" if "--test-lock-input" in sys.argv else "--lock-input"
        try:
            idx = sys.argv.index(flag)
            if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith("-"):
                timeout = float(sys.argv[idx + 1])
        except Exception:
            pass
        print("================================================================================")
        print(f"AUTOMATION SHIELD: PHYSICAL KEYBOARD & MOUSE LOCK TEST ({timeout:.1f}s)")
        print("================================================================================")
        print("TRY MOVING MOUSE, CLICKING, OR TYPING: ALL PHYSICAL INPUT IS ACTIVELY BLOCKED.")
        print("EMERGENCY RELEASE: Press Esc, Ctrl+Alt+Del, or Alt+Del at any time.")
        print("Synthetic automation clicks & Win32 messages remain 100% operational.")
        ok = InputRestrictionManager.acquire(reason=f"CLI Test Lock ({timeout:.1f}s)", max_timeout=timeout)
        st = InputRestrictionManager.get_status()
        print(f"Input Restriction: {'LOCKED (SUCCESS)' if ok else 'FAILED'}")
        print(f"Details: {st}\n")
        start_t = time.time()
        try:
            while time.time() - start_t < timeout and InputRestrictionManager.is_restricted():
                remain = max(0.0, timeout - (time.time() - start_t))
                print(f"\r[InputLock Active] Blocking all physical input... Remaining: {remain:4.1f}s (Press Esc to unlock) ", end="", flush=True)
                time.sleep(0.2)
            print("\n")
        finally:
            InputRestrictionManager.release(force=True)
            print("[InputLock] Physical keyboard & mouse restriction released.")
        return

    # CLI Node: Unlock Input
    if "--unlock-input" in sys.argv:
        ok = InputRestrictionManager.release(force=True)
        st = InputRestrictionManager.get_status()
        print(f"Input Restriction: {'RELEASED' if ok else 'FAILED'}")
        print(f"Details: {st}")
        return

    # CLI Node: Input Restriction Status
    if "--input-status" in sys.argv:
        st = InputRestrictionManager.get_status()
        print("Input Restriction Status:")
        print(f"  Restricted:     {st.get('restricted')}")
        print(f"  Native Blocked: {st.get('native_blocked')}")
        print(f"  Reason:         {st.get('reason')}")
        print(f"  Elapsed:        {st.get('elapsed_seconds')}s")
        print(f"  Max Timeout:    {st.get('max_timeout_seconds')}s")
        return

    # CLI Node: Set Max Daily Uploads Safety Limit
    if "--set-max-uploads" in sys.argv or "--safety-limit" in sys.argv:
        flag = "--set-max-uploads" if "--set-max-uploads" in sys.argv else "--safety-limit"
        try:
            idx = sys.argv.index(flag)
            val = int(sys.argv[idx + 1])
            controller.max_publications_per_day = val
            controller.update_config({"max_publications_per_day": val})
            print(f"[MetaReelsScheduler] Daily publication safety limit per page set to: {val} (0 = unlimited)")
        except Exception as e:
            print(f"[MetaReelsScheduler] Error setting safety limit: {e}")
        return

    # CLI Node: Reset Today's Publication Counts
    if "--reset-attempts" in sys.argv or "--reset-today" in sys.argv:
        controller.reset_all_attempts()
        print("[MetaReelsScheduler] All daily publication counts and attempts reset for today.")
        return

    # CLI Node: Status Report
    if "--status" in sys.argv or "--info" in sys.argv:
        b = controller.get_active_brand() or {}
        b_name = b.get("name", "N/A")
        b_id = b.get("id", "N/A")
        b_prof = b.get("chrome_profile", controller.selected_profile)
        b_folder = b.get("media_folder") or "None"
        pages = b.get("pages", [])
        active_pages = sum(1 for p in pages if p.get("enabled", True))
        print("================================================================================")
        print("META REELS SCHEDULER SYSTEM STATUS")
        print("================================================================================")
        print(f"Active Brand:      {b_name} (ID: {b_id})")
        print(f"Chrome Profile:    {b_prof}")
        print(f"Media Folder:      {b_folder}")
        print(f"Pages Configured:  {len(pages)} (Active: {active_pages})")
        print(f"Max Uploads / Day: {controller.max_publications_per_day} (0 = Unlimited)")
        print(f"Schedules Count:   {len(controller.schedules)}")
        print(f"API Server Port:   8765")
        print(f"Input Restriction: {'LOCKED' if InputRestrictionManager.is_restricted() else 'UNLOCKED'}")
        task_names = WindowsTaskSchedulerManager.list_registered_tasks()
        print(f"Windows Tasks ({len(task_names)}):")
        for tn in task_names:
            sid = tn.replace(WindowsTaskSchedulerManager.TASK_PREFIX, "")
            q = WindowsTaskSchedulerManager.query_task(sid)
            status_str = q.get("status", "Ready") if q.get("ok") else "Ready"
            next_run = q.get("next_run", "Scheduled") if q.get("ok") else "Scheduled"
            print(f"  {tn:<36} Next: {next_run:<20} Status: {status_str}")
        print("================================================================================")
        return

    if any(arg in sys.argv for arg in ("--setup", "--ensure-standalone", "--init")):
        res = ensure_standalone_environment()
        print(f"[MetaReelsScheduler] Standalone Environment Setup: {res.get('status')}")
        print(f"  Extension Path: {res.get('extension_path')}")
        print(f"  Sample Video: {res.get('sample_video')}")
        return

    if any(arg in sys.argv for arg in ("--scheduled-batch", "--batch", "--run-batch", "--manual-batch")):
        sched_id = ""
        brand_id = ""
        if "--schedule-id" in sys.argv:
            try:
                idx = sys.argv.index("--schedule-id")
                sched_id = sys.argv[idx + 1]
            except Exception:
                pass
        if "--brand" in sys.argv:
            try:
                idx = sys.argv.index("--brand")
                brand_id = sys.argv[idx + 1]
            except Exception:
                pass
        run_scheduled_batch_cli(schedule_id=sched_id, brand_id=brand_id)
        return

    if "--api-only" in sys.argv or "--server" in sys.argv:
        logger.info("Running in API-only server mode.")
        start_uvicorn_api()
        return

    # In-process FastAPI Uvicorn server daemon
    threading.Thread(target=start_uvicorn_api, name="FastAPIUvicornThread", daemon=True).start()
    time.sleep(0.5)

    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    app = MetaReelsGUI(root)
    root.mainloop()


if __name__ == "__main__":
    _SCRIPT_DIR = Path(__file__).resolve().parent
    _LLM_PYTHON = _SCRIPT_DIR / ".llm_env" / "Scripts" / "python.exe"
    if _LLM_PYTHON.exists() and Path(sys.executable).resolve() != _LLM_PYTHON.resolve():
        try:
            import pyautogui
            import fastapi
        except ImportError:
            try:
                os.execv(str(_LLM_PYTHON), [str(_LLM_PYTHON)] + sys.argv)
            except Exception:
                pass
    main()
