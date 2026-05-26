"""
AIOS Background Daemons — autonomous OS management workers.

All daemons are daemon=True threads: they start with AIOS and die
automatically when AIOS exits. No system services, no admin rights needed.

Usage (called once from main.py):
    from aios.daemons import start_all
    start_all(notify=cprint)
"""
from __future__ import annotations
from typing import Callable, Optional


def start_all(notify: Optional[Callable[[str], None]] = None) -> dict:
    """
    Start all background daemons.
    Returns a dict of {name: thread} for the started daemons.

    Args:
        notify: callable that accepts a Rich-markup string, e.g. cprint from main.py.
                Falls back to plain print if not provided.
    """
    _notify = notify or print
    started: dict = {}

    try:
        from aios.daemons.memory_guardian import MemoryGuardian
        mg = MemoryGuardian(notify=_notify)
        mg.start()
        started["memory_guardian"] = mg
    except Exception as e:
        _notify(f"[yellow]⚠  MemoryGuardian failed to start: {e}[/yellow]")

    try:
        from aios.daemons.process_watcher import ProcessWatcher
        pw = ProcessWatcher(notify=_notify)
        pw.start()
        started["process_watcher"] = pw
    except Exception as e:
        _notify(f"[yellow]⚠  ProcessWatcher failed to start: {e}[/yellow]")

    try:
        from aios.daemons.file_organizer import FileOrganizer
        fo = FileOrganizer(notify=_notify)
        fo.start()
        started["file_organizer"] = fo
    except Exception as e:
        _notify(f"[yellow]⚠  FileOrganizer failed to start: {e}[/yellow]")

    try:
        from aios.daemons.device_monitor import DeviceMonitor
        dm = DeviceMonitor(notify=_notify)
        dm.start()
        started["device_monitor"] = dm
    except Exception as e:
        _notify(f"[yellow]⚠  DeviceMonitor failed to start: {e}[/yellow]")

    return started
