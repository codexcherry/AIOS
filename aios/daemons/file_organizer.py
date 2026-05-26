"""
File Organizer — automatic Downloads folder sorter + new-file indexer.

Two jobs:
  1. ORGANIZER   — every hour, moves files in the Downloads folder into
                   typed sub-folders (Images/, Docs/, Code/, Videos/, etc.)
  2. FILE WATCHER — uses watchdog (if installed) to detect newly created
                   files and register them in AIOS context_memory so they
                   surface in semantic file searches immediately.
                   Falls back to a simple polling scan if watchdog is missing.

Extension → folder map is hard-coded but can be extended via config.
Configurable:
    AIOS__DAEMONS__FO_DOWNLOADS_DIR   path to watch (default ~/Downloads)
    AIOS__DAEMONS__FO_INTERVAL        sort interval in seconds (default 3600)
    AIOS__DAEMONS__FO_DRY_RUN         if true, log moves but don't actually move
    AIOS__DAEMONS__FO_WATCH_DIRS      extra dirs to index, comma-separated
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from aios.logger import log
from aios import config as cfg
from aios import context_memory as memory


# ── Extension-to-folder mapping ───────────────────────────────────────────────

EXT_MAP: Dict[str, str] = {
    # Images
    ".jpg": "Images", ".jpeg": "Images", ".png": "Images",
    ".gif": "Images", ".webp": "Images", ".bmp": "Images",
    ".svg": "Images", ".ico": "Images",
    # Documents
    ".pdf": "Docs",  ".docx": "Docs",  ".doc": "Docs",
    ".xlsx": "Docs", ".xls": "Docs",   ".pptx": "Docs", ".ppt": "Docs",
    ".odt": "Docs",  ".ods": "Docs",   ".txt": "Docs",  ".rtf": "Docs",
    # Code & archives
    ".py": "Code",  ".js": "Code",  ".ts": "Code",  ".html": "Code",
    ".css": "Code", ".json": "Code", ".xml": "Code", ".yaml": "Code",
    ".yml": "Code", ".sh": "Code",   ".bat": "Code",
    ".zip": "Archives", ".tar": "Archives", ".gz": "Archives",
    ".rar": "Archives", ".7z": "Archives",
    # Videos
    ".mp4": "Videos", ".mkv": "Videos", ".avi": "Videos",
    ".mov": "Videos", ".wmv": "Videos", ".flv": "Videos",
    # Audio
    ".mp3": "Audio", ".wav": "Audio", ".flac": "Audio",
    ".aac": "Audio", ".ogg": "Audio",
}


class FileOrganizer(threading.Thread):
    """Background daemon that sorts Downloads and indexes new files."""

    def __init__(self, notify: Optional[Callable[[str], None]] = None):
        super().__init__(daemon=True, name="FileOrganizer")
        self._notify   = notify or print
        raw_dir        = cfg.get("daemons", "fo_downloads_dir", None)
        self._dl_dir   = Path(raw_dir).expanduser() if raw_dir else Path.home() / "Downloads"
        self._interval = int(cfg.get("daemons", "fo_interval",  3600))
        self._dry_run  = bool(cfg.get("daemons", "fo_dry_run",  False))
        raw_watch      = cfg.get("daemons", "fo_watch_dirs",    None)
        extra: List[Path] = []
        if raw_watch:
            extra = [Path(d.strip()).expanduser() for d in raw_watch.split(",") if d.strip()]
        self._watch_dirs: List[Path] = [self._dl_dir] + extra
        self._watcher_thread: Optional[threading.Thread] = None

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        log.info("FileOrganizer started  dl_dir=%s  interval=%ds  dry_run=%s",
                 self._dl_dir, self._interval, self._dry_run)
        self._start_file_watcher()
        while True:
            try:
                self._organize()
            except Exception as exc:
                log.error("FileOrganizer organize error: %s", exc)
            time.sleep(self._interval)

    # ── Organizer ─────────────────────────────────────────────────────────────

    def _organize(self) -> None:
        if not self._dl_dir.exists():
            log.debug("FileOrganizer: Downloads dir not found: %s", self._dl_dir)
            return

        moved = 0
        skipped = 0
        for item in self._dl_dir.iterdir():
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            folder = EXT_MAP.get(ext, "Others")
            target_dir = self._dl_dir / folder
            target_file = target_dir / item.name
            if target_file.exists():
                skipped += 1
                continue
            try:
                if not self._dry_run:
                    target_dir.mkdir(exist_ok=True)
                    item.rename(target_file)
                else:
                    log.debug("DRY-RUN: would move %s → %s/%s", item.name, folder, item.name)
                moved += 1
            except Exception as exc:
                log.warning("FileOrganizer: could not move %s: %s", item.name, exc)

        if moved:
            label = "Would move" if self._dry_run else "Moved"
            self._notify(
                f"\n[green]📁 FileOrganizer:[/green] {label} {moved} file(s) "
                f"in [dim]{self._dl_dir}[/dim]\n"
                f"[dim]  {skipped} skipped (already in sub-folder).[/dim]"
            )
            log.info("FileOrganizer: %s %d file(s), %d skipped", label.lower(), moved, skipped)

    # ── File watcher (watchdog or fallback) ───────────────────────────────────

    def _start_file_watcher(self) -> None:
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            organizer_ref = self

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if event.is_directory:
                        return
                    path = Path(event.src_path)
                    try:
                                memory.index_file(str(path))
                    except Exception:
                        pass
                    log.debug("FileOrganizer: indexed new file %s", path.name)

            obs = Observer()
            for d in self._watch_dirs:
                if d.exists():
                    obs.schedule(_Handler(), str(d), recursive=False)
            obs.daemon = True
            obs.start()
            log.info("FileOrganizer: watchdog active on %s", self._watch_dirs)
        except ImportError:
            log.info("FileOrganizer: watchdog not installed — using polling scan")
            self._watcher_thread = threading.Thread(
                target=self._polling_watcher, daemon=True, name="FileOrganizerPoller"
            )
            self._watcher_thread.start()

    def _polling_watcher(self) -> None:
        """Poll every 60 s to index new files when watchdog is unavailable."""
        seen: Set[str] = set()
        while True:
            try:
                for d in self._watch_dirs:
                    if not d.exists():
                        continue
                    for f in d.iterdir():
                        if f.is_file() and str(f) not in seen:
                            seen.add(str(f))
                            try:
                                memory.index_file(str(f))
                            except Exception:
                                pass
            except Exception as exc:
                log.debug("FileOrganizer poll error: %s", exc)
            time.sleep(60)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running":     self.is_alive(),
            "dl_dir":      str(self._dl_dir),
            "interval_s":  self._interval,
            "dry_run":     self._dry_run,
            "watch_dirs":  [str(d) for d in self._watch_dirs],
        }
