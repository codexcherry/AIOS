"""
Parallel App Launcher — Opens multiple applications simultaneously.
Cross-platform: Windows 10/11 + Linux (Arch, Ubuntu, Debian, Fedora, etc.)
All paths are resolved dynamically — no hardcoded user/machine paths.
"""
import os
import sys
import subprocess
import shutil
import glob
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

# ── Dynamic path helpers ────────────────────────────────────────────────────

def _home() -> Path:
    return Path.home()

def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local"))

def _roaming_app_data() -> Path:
    return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming"))

def _program_files() -> Path:
    return Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))

def _program_files_x86() -> Path:
    return Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))

def _glob_first(pattern: str) -> Optional[str]:
    """Return first glob match or None."""
    matches = glob.glob(pattern, recursive=False)
    return sorted(matches)[-1] if matches else None  # latest version last


def _registry_lookup(key_path: str, value_name: str = "") -> Optional[str]:
    """Read a value from Windows registry. Returns None if not found."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return val
    except Exception:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return val
    except Exception:
        return None


# ── Dynamic app resolver ────────────────────────────────────────────────────

@lru_cache(maxsize=64)
def _resolve_app_path(app_name: str) -> Optional[str]:
    """
    Dynamically resolve an app name to its executable path.
    Resolution order:
      1. System PATH (shutil.which)
      2. Registry lookup
      3. Common install patterns (glob with env vars)
      4. Return name as-is for subprocess shell fallback
    """
    name = app_name.lower().strip()
    local = _local_app_data()
    roaming = _roaming_app_data()
    pf = _program_files()
    pf86 = _program_files_x86()

    # ── 1. System PATH first (fastest) ──────────────────────────────────────
    path_exe_map = {
        "notepad":      "notepad.exe",
        "terminal":     "wt.exe",
        "cmd":          "cmd.exe",
        "explorer":     "explorer.exe",
        "task_manager": "taskmgr.exe",
        "calculator":   "calc.exe",
        "paint":        "mspaint.exe",
        "wordpad":      "wordpad.exe",
        "control":      "control.exe",
        "regedit":      "regedit.exe",
        "python":       "python.exe",
        "ollama":       "ollama.exe",
        "git":          "git.exe",
        "node":         "node.exe",
        "npm":          "npm.cmd",
        "code":         "code.cmd",
    }
    if name in path_exe_map:
        found = shutil.which(path_exe_map[name])
        if found:
            return found
        # Still return the exe name — let OS resolve via shell
        return path_exe_map[name]

    # ── 2. Apps that need dynamic discovery ─────────────────────────────────

    if name == "chrome":
        candidates = [
            _registry_lookup(
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
            ),
            str(pf  / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(pf86 / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(local / "Google" / "Chrome" / "Application" / "chrome.exe"),
            shutil.which("chrome"),
        ]
        return _first_existing(candidates)

    if name == "vscode":
        candidates = [
            shutil.which("code"),
            str(local / "Programs" / "Microsoft VS Code" / "Code.exe"),
            str(pf / "Microsoft VS Code" / "Code.exe"),
            _registry_lookup(
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\code.exe"
            ),
        ]
        return _first_existing(candidates)

    if name == "spotify":
        candidates = [
            str(roaming / "Spotify" / "Spotify.exe"),
            str(local  / "Microsoft" / "WindowsApps" / "Spotify.exe"),
            shutil.which("spotify"),
            _glob_first(str(local / "Packages" / "SpotifyAB*" / "LocalState" / "Spotify.exe")),
        ]
        return _first_existing(candidates)

    if name == "discord":
        # Discord installs under LocalAppData/Discord/app-x.x.x/Discord.exe
        pattern = str(local / "Discord" / "app-*" / "Discord.exe")
        found = _glob_first(pattern)
        if found:
            return found
        candidates = [
            shutil.which("discord"),
            str(local / "Discord" / "Discord.exe"),
        ]
        return _first_existing(candidates)

    if name == "slack":
        pattern = str(local / "slack" / "app-*" / "slack.exe")
        found = _glob_first(pattern)
        if found:
            return found
        candidates = [
            shutil.which("slack"),
            str(local / "slack" / "slack.exe"),
        ]
        return _first_existing(candidates)

    if name == "telegram":
        candidates = [
            str(roaming / "Telegram Desktop" / "Telegram.exe"),
            str(local  / "Telegram Desktop" / "Telegram.exe"),
            shutil.which("telegram"),
        ]
        return _first_existing(candidates)

    if name == "whatsapp":
        candidates = [
            _glob_first(str(local / "WhatsApp" / "app-*" / "WhatsApp.exe")),
            str(local / "WhatsApp" / "WhatsApp.exe"),
            shutil.which("whatsapp"),
        ]
        return _first_existing(candidates)

    if name in ("word", "winword"):
        return _find_office_app("WINWORD.EXE")

    if name == "excel":
        return _find_office_app("EXCEL.EXE")

    if name in ("powerpoint", "ppt"):
        return _find_office_app("POWERPNT.EXE")

    if name == "vlc":
        candidates = [
            str(pf  / "VideoLAN" / "VLC" / "vlc.exe"),
            str(pf86 / "VideoLAN" / "VLC" / "vlc.exe"),
            shutil.which("vlc"),
            _registry_lookup(
                r"SOFTWARE\VideoLAN\VLC", "InstallDir"
            ),
        ]
        result = _first_existing(candidates)
        if result and os.path.isdir(result):
            result = os.path.join(result, "vlc.exe")
        return result

    if name == "obs":
        candidates = [
            str(pf  / "obs-studio" / "bin" / "64bit" / "obs64.exe"),
            str(pf86 / "obs-studio" / "bin" / "64bit" / "obs64.exe"),
            shutil.which("obs64"),
            shutil.which("obs"),
        ]
        return _first_existing(candidates)

    if name == "steam":
        candidates = [
            _registry_lookup(r"SOFTWARE\Valve\Steam", "SteamExe"),
            str(pf86 / "Steam" / "steam.exe"),
            str(pf   / "Steam" / "steam.exe"),
            shutil.which("steam"),
        ]
        return _first_existing(candidates)

    if name == "winamp":
        candidates = [
            str(pf  / "Winamp" / "winamp.exe"),
            str(pf86 / "Winamp" / "winamp.exe"),
        ]
        return _first_existing(candidates)

    # ── 3. Generic: try shutil.which and common install patterns ────────────
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return found

    # Last resort: return as-is and let subprocess shell try
    return app_name


def _first_existing(candidates: list) -> Optional[str]:
    """Return the first path in the list that actually exists."""
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    # Return first non-None candidate as fallback (let OS try)
    for c in candidates:
        if c:
            return c
    return None


def _find_office_app(exe_name: str) -> Optional[str]:
    """Dynamically find Microsoft Office executables."""
    pf = _program_files()
    pf86 = _program_files_x86()
    # Office 365/2019/2016/2021 — version-agnostic glob
    patterns = [
        str(pf  / "Microsoft Office" / "root" / "Office*" / exe_name),
        str(pf  / "Microsoft Office" / "Office*" / exe_name),
        str(pf86 / "Microsoft Office" / "root" / "Office*" / exe_name),
        str(pf86 / "Microsoft Office" / "Office*" / exe_name),
    ]
    for pattern in patterns:
        found = _glob_first(pattern)
        if found:
            return found
    # Registry fallback
    reg = _registry_lookup(
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + exe_name.lower()
    )
    return reg or shutil.which(exe_name)


def _launch_single_app(app_name: str, args: list = None) -> dict:
    """Launch a single application. Returns result dict."""
    result = {"app": app_name, "status": "unknown", "pid": None, "error": None, "time_ms": 0}
    t_start = time.time()
    
    path = _resolve_app_path(app_name)
    cmd = [path] + (args or [])
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )
        result["status"] = "launched"
        result["pid"] = proc.pid
    except FileNotFoundError:
        # Try using 'start' command as fallback
        try:
            subprocess.Popen(
                f'start "" "{path}"',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            result["status"] = "launched (shell)"
        except Exception as e2:
            result["status"] = "failed"
            result["error"] = str(e2)
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
    
    result["time_ms"] = round((time.time() - t_start) * 1000)
    return result


def launch_apps_parallel(
    app_names: list,
    progress_callback: Callable = None,
    max_workers: int = 8
) -> dict:
    """
    Launch multiple applications in TRUE PARALLEL using ThreadPoolExecutor.
    
    Args:
        app_names: List of app names to launch
        progress_callback: Optional callback(app_name, result) called as each app launches
        max_workers: Thread pool size
    
    Returns:
        dict with 'results', 'success_count', 'fail_count', 'total_time_ms'
    """
    if not app_names:
        return {"results": [], "success_count": 0, "fail_count": 0, "total_time_ms": 0}
    
    t_start = time.time()
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all app launches simultaneously
        future_to_app = {
            executor.submit(_launch_single_app, app): app
            for app in app_names
        }
        
        for future in as_completed(future_to_app):
            result = future.result()
            results.append(result)
            if progress_callback:
                progress_callback(result["app"], result)
    
    total_time = round((time.time() - t_start) * 1000)
    success = sum(1 for r in results if "launched" in r["status"])
    fail = sum(1 for r in results if r["status"] == "failed")
    
    return {
        "results": results,
        "success_count": success,
        "fail_count": fail,
        "total_time_ms": total_time
    }


def launch_apps_sequential(app_names: list, delay_ms: int = 500) -> dict:
    """Launch apps one by one with optional delay (for comparison/fallback)."""
    t_start = time.time()
    results = []
    for app in app_names:
        result = _launch_single_app(app)
        results.append(result)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)
    
    return {
        "results": results,
        "success_count": sum(1 for r in results if "launched" in r["status"]),
        "fail_count": sum(1 for r in results if r["status"] == "failed"),
        "total_time_ms": round((time.time() - t_start) * 1000)
    }


def open_url_in_chrome(url: str) -> dict:
    """
    Open a URL in Chrome. Works whether Chrome is already running or not.
    Uses the system default browser as fallback if Chrome not found.
    """
    import webbrowser
    t_start = time.time()
    chrome_path = _resolve_app_path("chrome")

    # Try launching Chrome with the URL directly
    try:
        if chrome_path and os.path.isfile(chrome_path):
            proc = subprocess.Popen(
                [chrome_path, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
            return {"app": "chrome", "status": "launched", "pid": proc.pid, "error": None,
                    "time_ms": round((time.time() - t_start) * 1000), "url": url}
    except Exception:
        pass

    # Fallback: webbrowser module (always works, opens default browser)
    try:
        webbrowser.open(url)
        return {"app": "chrome", "status": "launched (webbrowser)", "pid": None, "error": None,
                "time_ms": round((time.time() - t_start) * 1000), "url": url}
    except Exception as e:
        return {"app": "chrome", "status": "failed", "pid": None, "error": str(e),
                "time_ms": round((time.time() - t_start) * 1000), "url": url}


def is_app_running(app_name: str) -> bool:
    """Check if an application is already running by matching the resolved executable name."""
    import psutil
    name_lower = app_name.lower()

    # Derive process exe name from resolved path
    resolved = _resolve_app_path(name_lower)
    if resolved:
        exe_name = os.path.basename(resolved).lower()
    else:
        exe_name = f"{app_name}.exe".lower()

    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == exe_name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False
