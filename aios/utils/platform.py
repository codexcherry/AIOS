"""
Cross-platform OS utilities.
Supports: Windows 10/11, Linux (Ubuntu, Arch, Debian, Fedora, etc.)
NOT supported: macOS
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

# ── Platform detection ───────────────────────────────────────────────────────

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform.startswith("linux")

if not IS_WINDOWS and not IS_LINUX:
    raise RuntimeError(
        "AIOS supports Windows and Linux only. macOS is not supported."
    )


def home() -> Path:
    return Path.home()


def username() -> str:
    """Return the current user's login name."""
    return (
        os.environ.get("USER")
        or os.environ.get("USERNAME")
        or os.environ.get("LOGNAME")
        or "user"
    )


# ── Browser / URL ────────────────────────────────────────────────────────────

def _find_linux_browser() -> str | None:
    """Return the first available browser binary on Linux."""
    for b in (
        "google-chrome", "google-chrome-stable",
        "chromium", "chromium-browser",
        "firefox", "firefox-esr",
        "brave-browser", "brave",
        "vivaldi", "opera",
        "xdg-open",
    ):
        found = shutil.which(b)
        if found:
            return found
    return None


def open_url(url: str) -> bool:
    """Open a URL in the system's default browser. Cross-platform."""
    try:
        if IS_WINDOWS:
            import webbrowser
            webbrowser.open(url)
            return True
        else:
            browser = _find_linux_browser()
            if browser and browser != shutil.which("xdg-open"):
                subprocess.Popen(
                    [browser, url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            return True
    except Exception:
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception:
            return False


def open_file(path: str) -> bool:
    """Open a file with the system default application. Cross-platform."""
    try:
        if IS_WINDOWS:
            os.startfile(str(path))
        else:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True
    except Exception:
        return False


def open_uri(uri: str) -> bool:
    """
    Open a URI (e.g. ms-settings: on Windows, or a file:// on Linux).
    Windows: os.startfile handles ms-settings:, ms-todo:, etc.
    Linux:   xdg-open handles file:// and similar.
    """
    try:
        if IS_WINDOWS:
            os.startfile(uri)
        else:
            subprocess.Popen(
                ["xdg-open", uri],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True
    except Exception:
        return False


# ── Filesystem ───────────────────────────────────────────────────────────────

def root_disk() -> str:
    """Return the primary disk root path for disk usage queries."""
    if IS_WINDOWS:
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def pictures_dir() -> Path:
    """Return a writable pictures/screenshots directory."""
    if IS_WINDOWS:
        pics = home() / "Pictures"
    else:
        pics = home() / "Pictures"
    pics.mkdir(parents=True, exist_ok=True)
    return pics


def documents_dir() -> Path:
    return home() / "Documents"


def desktop_dir() -> Path:
    return home() / "Desktop"


def downloads_dir() -> Path:
    return home() / "Downloads"


# ── Shell helpers ────────────────────────────────────────────────────────────

def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run_detached(cmd: list, shell: bool = False) -> subprocess.Popen:
    """Launch a process detached from the current terminal."""
    kwargs = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=shell,
    )
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)
