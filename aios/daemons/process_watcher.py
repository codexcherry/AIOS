"""
Process Watcher — monitors key processes and CPU spikes.

Two jobs:
  1. CRASH WATCHER  — checks that every process in WATCH_LIST is alive.
                      If one exits, tries to restart it once.
  2. CPU SPIKE ALERT — if any user process sustains >80% CPU for two
                       consecutive checks (at least 15 s apart), alerts
                       the user so they can investigate.

Configurable via .env / config.json:
    AIOS__DAEMONS__PW_WATCH_LIST   comma-separated process names to watch
    AIOS__DAEMONS__PW_CPU_THRESH   CPU% alert threshold (default 80)
    AIOS__DAEMONS__PW_INTERVAL     check interval in seconds (default 15)
"""
from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Set

import psutil

from aios.logger import log
from aios import config as cfg
from aios.process_manager import PROTECTED_PROCESSES
from aios.utils.platform import IS_WINDOWS


# Processes to watch by default — add your own in config
_DEFAULT_WATCH = ["ollama.exe", "ollama"] if IS_WINDOWS else ["ollama"]


class ProcessWatcher(threading.Thread):
    """
    Background daemon for crash detection and CPU spike alerting.

    Attributes set by config:
        watch_list   list of process names to watch for crashes
        cpu_thresh   CPU% that triggers a spike alert (default 80)
        interval     seconds between checks (default 15)
    """

    def __init__(self, notify: Optional[Callable[[str], None]] = None):
        super().__init__(daemon=True, name="ProcessWatcher")
        self._notify       = notify or print
        self._interval     = int(cfg.get("daemons", "pw_interval",   15))
        self._cpu_thresh   = int(cfg.get("daemons", "pw_cpu_thresh",  80))
        raw_watch          = cfg.get("daemons", "pw_watch_list",      None)
        if raw_watch:
            self._watch_list: List[str] = [s.strip() for s in raw_watch.split(",") if s.strip()]
        else:
            self._watch_list = list(_DEFAULT_WATCH)

        # track restart attempts so we don't spam
        self._restart_attempted: Set[str] = set()
        # track previous high-CPU procs for two-consecutive check rule
        self._prev_high_cpu: Set[int] = set()   # PIDs that were high last cycle
        # track last alert time per-PID to rate-limit
        self._spike_alerted_at: Dict[int, float] = {}
        self._spike_cooldown = 10 * 60  # 10 minutes per PID

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        log.info("ProcessWatcher started  watch=%s  cpu_thresh=%d%%  interval=%ds",
                 self._watch_list, self._cpu_thresh, self._interval)
        while True:
            try:
                self._check_crashes()
                self._check_cpu_spikes()
            except Exception as exc:
                log.error("ProcessWatcher error: %s", exc)
            time.sleep(self._interval)

    # ── Crash watching ────────────────────────────────────────────────────────

    def _check_crashes(self) -> None:
        alive_names: Set[str] = set()
        try:
            for p in psutil.process_iter(["name"]):
                alive_names.add((p.info["name"] or "").lower())
        except Exception:
            return

        for name in self._watch_list:
            if name.lower() not in alive_names:
                self._handle_crash(name)
            else:
                # Clear restart flag once the process is alive again
                self._restart_attempted.discard(name.lower())

    def _handle_crash(self, name: str) -> None:
        key = name.lower()
        if key in self._restart_attempted:
            return  # already tried once this down-cycle

        self._restart_attempted.add(key)
        log.warning("ProcessWatcher: '%s' not found in running processes", name)

        restart_cmd = cfg.get("daemons", f"pw_restart_{key}", None)
        if restart_cmd:
            try:
                subprocess.Popen(
                    restart_cmd,
                    shell=IS_WINDOWS,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0,
                )
                msg = (f"\n[yellow]⚡ ProcessWatcher:[/yellow] "
                       f"[bold]{name}[/bold] crashed — restarting automatically.\n"
                       f"[dim]  Command: {restart_cmd}[/dim]")
                log.info("Attempted restart of '%s': %s", name, restart_cmd)
            except Exception as exc:
                msg = (f"\n[yellow]⚡ ProcessWatcher:[/yellow] "
                       f"[bold]{name}[/bold] crashed — restart failed: {exc}")
                log.error("Failed to restart '%s': %s", name, exc)
        else:
            # No restart command configured — log silently, don't interrupt the terminal
            log.info("ProcessWatcher: '%s' is not running (no restart command configured)", name)
            return

        self._notify(msg)

    # ── CPU spike detection ───────────────────────────────────────────────────

    def _check_cpu_spikes(self) -> None:
        high_this_cycle: Set[int] = set()
        now = time.time()

        try:
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "username"]):
                try:
                    pid  = p.info["pid"]
                    name = p.info["name"] or "unknown"
                    cpu  = p.info["cpu_percent"] or 0.0

                    # Skip protected and system processes
                    if name.lower() in PROTECTED_PROCESSES:
                        continue

                    if cpu >= self._cpu_thresh:
                        high_this_cycle.add(pid)
                        # Alert only if it was ALSO high last cycle (sustained spike)
                        if pid in self._prev_high_cpu:
                            last = self._spike_alerted_at.get(pid, 0)
                            if now - last >= self._spike_cooldown:
                                self._spike_alerted_at[pid] = now
                                log.warning("CPU spike: %s (PID %d) at %.0f%%", name, pid, cpu)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as exc:
            log.debug("ProcessWatcher cpu check error: %s", exc)

        self._prev_high_cpu = high_this_cycle

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "running":     self.is_alive(),
            "watch_list":  self._watch_list,
            "cpu_thresh":  self._cpu_thresh,
            "interval_s":  self._interval,
        }
