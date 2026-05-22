"""
Screenshot module — take and save screenshots.
Cross-platform: Windows + Linux. No macOS.

Priority:
  1. Pillow / ImageGrab  (pip install Pillow)  — works on both platforms
  2. Linux fallbacks:    scrot, gnome-screenshot, spectacle, flameshot, import (ImageMagick)
  3. Windows fallback:   PowerShell + System.Windows.Forms
"""
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from aios.utils.platform import IS_WINDOWS, IS_LINUX, pictures_dir


def _default_filename() -> str:
    return f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"


def _resolve_path(filename: Optional[str]) -> Path:
    """Turn a bare name / relative path into an absolute save path."""
    if filename:
        p = Path(filename)
        # Add .png if no extension
        if not p.suffix:
            p = p.with_suffix(".png")
        # If only a filename (no directory), save to AIOS screenshots folder
        if not p.is_absolute() and p.parent == Path("."):
            p = pictures_dir() / "AIOS" / p
    else:
        p = pictures_dir() / "AIOS" / _default_filename()

    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def take_screenshot(filename: Optional[str] = None) -> dict:
    """
    Take a full-screen screenshot and save to disk.

    Args:
        filename: Optional save name (with or without extension, with or without path).
                  Defaults to a timestamped name in ~/Pictures/AIOS/.

    Returns:
        {"success": bool, "path": str, "message": str}
    """
    save_path = _resolve_path(filename)

    # ── 1. Pillow (cross-platform, best option) ──────────────────────────────
    try:
        from PIL import ImageGrab  # type: ignore
        img = ImageGrab.grab()
        img.save(str(save_path))
        return {
            "success": True,
            "path": str(save_path),
            "message": f"Screenshot saved to {save_path}",
        }
    except ImportError:
        pass  # Pillow not installed — try OS-specific fallbacks
    except Exception:
        pass

    # ── 2. Linux fallbacks ───────────────────────────────────────────────────
    if IS_LINUX:
        candidates = [
            ("scrot",             ["scrot", str(save_path)]),
            ("gnome-screenshot",  ["gnome-screenshot", "--full", "-f", str(save_path)]),
            ("spectacle",         ["spectacle", "-b", "-o", str(save_path)]),
            ("flameshot",         ["flameshot", "full", "-p", str(save_path.parent)]),
            ("import",            ["import", "-window", "root", str(save_path)]),  # ImageMagick
        ]
        for tool, cmd in candidates:
            if shutil.which(tool):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=10, check=False)
                    if save_path.exists():
                        return {
                            "success": True,
                            "path": str(save_path),
                            "message": f"Screenshot saved to {save_path} (via {tool})",
                        }
                except Exception:
                    continue

    # ── 3. Windows PowerShell fallback ───────────────────────────────────────
    if IS_WINDOWS:
        escaped = str(save_path).replace("'", "''")
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bmp.Save('{escaped}')
$g.Dispose()
$bmp.Dispose()
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, timeout=15, check=False,
            )
            if save_path.exists():
                return {
                    "success": True,
                    "path": str(save_path),
                    "message": f"Screenshot saved to {save_path} (via PowerShell)",
                }
        except Exception as exc:
            return {
                "success": False,
                "path": str(save_path),
                "message": f"PowerShell fallback failed: {exc}. Install Pillow: pip install Pillow",
            }

    return {
        "success": False,
        "path": str(save_path),
        "message": (
            "No screenshot tool found. Install Pillow:  pip install Pillow\n"
            + ("On Linux also try: sudo apt install scrot  OR  sudo pacman -S scrot" if IS_LINUX else "")
        ),
    }
