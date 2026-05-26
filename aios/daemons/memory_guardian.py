"""
Memory Guardian — background RAM monitor.

Watches system memory every 30 seconds.
  • WARN  (≥75%): logs AI optimization advice once per cooldown window
  • CRITICAL (≥90%): auto-kills the top non-protected RAM hog (if auto_kill=True)

No admin rights needed — psutil reads user-accessible memory stats.
Skips AccessDenied processes silently.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import psutil

from aios.logger import log
from aios import config as cfg
from aios.process_manager import PROTECTED_PROCESSES, get_process_list, kill_process


# Cooldown: don't re-notify within this many seconds
_WARN_COOLDOWN     = 5 * 60     # 5 minutes
_CRITICAL_COOLDOWN = 2 * 60     # 2 minutes


class MemoryGuardian(threading.Thread):
    """
    Background daemon that watches RAM and acts when thresholds are crossed.

    Thresholds (configurable via config / env):
        AIOS__DAEMONS__MEMORY_WARN_PCT     default 75
        AIOS__DAEMONS__MEMORY_CRITICAL_PCT default 90
        AIOS__DAEMONS__MEMORY_AUTO_KILL    default false
        AIOS__DAEMONS__MEMORY_INTERVAL     default 30 (seconds)
    """

    def __init__(self, notify: Optional[Callable[[str], None]] = None):
        super().__init__(daemon=True, name="MemoryGuardian")
        self._notify        = notify or print
        self._warn_pct      = int(cfg.get("daemons", "memory_warn_pct",     75))
        self._critical_pct  = int(cfg.get("daemons", "memory_critical_pct", 90))
        self._auto_kill     = bool(cfg.get("daemons", "memory_auto_kill",   False))
        self._interval      = int(cfg.get("daemons", "memory_interval",     30))
        self._last_warn_at  = 0.0
        self._last_crit_at  = 0.0

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        log.info("MemoryGuardian started (warn=%d%% critical=%d%% auto_kill=%s interval=%ds)",
                 self._warn_pct, self._critical_pct, self._auto_kill, self._interval)
        while True:
            try:
                self._check()
            except Exception as exc:
                log.error("MemoryGuardian error: %s", exc)
            time.sleep(self._interval)

    # ── Check ─────────────────────────────────────────────────────────────────

    def _check(self) -> None:
        mem = psutil.virtual_memory()
        pct = mem.percent
        now = time.time()

        if pct >= self._critical_pct:
            if now - self._last_crit_at >= _CRITICAL_COOLDOWN:
                self._last_crit_at = now
                self._handle_critical(pct, mem)
        elif pct >= self._warn_pct:
            if now - self._last_warn_at >= _WARN_COOLDOWN:
                self._last_warn_at = now
                self._handle_warn(pct, mem)

    # ── Warn handler ──────────────────────────────────────────────────────────

    def _handle_warn(self, pct: float, mem) -> None:
        used  = round(mem.used  / 1024**3, 1)
        total = round(mem.total / 1024**3, 1)
        log.warning("RAM warn: %.0f%%  (%s GB / %s GB)", pct, used, total)

    # ── Critical handler ─────────────────────────────────────────────────────

    def _handle_critical(self, pct: float, mem) -> None:
        used  = round(mem.used  / 1024**3, 1)
        total = round(mem.total / 1024**3, 1)

        # Find the top non-protected RAM hog
        top_hog = self._find_top_hog()

        if self._auto_kill and top_hog:
            result = kill_process(top_hog["pid"], top_hog["name"])
            if result["success"]:
                msg = (f"\n[bold red]🔴 RAM CRITICAL[/bold red]  "
                       f"[red]{pct:.0f}% ({used}GB / {total}GB)[/red]\n"
                       f"[red]  Auto-killed:[/red] {top_hog['name']} "
                       f"(PID {top_hog['pid']}, {top_hog['memory_mb']:.0f} MB freed)")
            else:
                msg = (f"\n[bold red]🔴 RAM CRITICAL[/bold red]  {pct:.0f}%  "
                       f"Could not kill {top_hog['name']}: {result['reason']}\n"
                       f"[dim]  Run /kill {top_hog['pid']} manually or /optimize for advice.[/dim]")
        elif top_hog:
            msg = (f"\n[bold red]🔴 RAM CRITICAL[/bold red]  "
                   f"[red]{pct:.0f}% ({used}GB / {total}GB)[/red]\n"
                   f"[red]  Top hog:[/red] {top_hog['name']} "
                   f"({top_hog['memory_mb']:.0f} MB, PID {top_hog['pid']})\n"
                   f"[dim]  Run /kill {top_hog['pid']}  or  /optimize  to free RAM.[/dim]")
        else:
            msg = (f"\n[bold red]🔴 RAM CRITICAL[/bold red]  "
                   f"[red]{pct:.0f}% ({used}GB / {total}GB)[/red]\n"
                   f"[dim]  Run /optimize for AI recommendations.[/dim]")

        log.critical("RAM critical: %.0f%%  (%s GB / %s GB)", pct, used, total)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_top_hog(self) -> Optional[dict]:
        """Return the highest-RAM non-protected process, or None."""
        try:
            procs = get_process_list(top_n=10, sort_by="memory")
            for p in procs:
                if not p.get("protected", False):
                    return p
        except Exception:
            pass
        return None

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        mem = psutil.virtual_memory()
        return {
            "running":      self.is_alive(),
            "ram_pct":      mem.percent,
            "ram_used_gb":  round(mem.used  / 1024**3, 1),
            "ram_total_gb": round(mem.total / 1024**3, 1),
            "warn_pct":     self._warn_pct,
            "critical_pct": self._critical_pct,
            "auto_kill":    self._auto_kill,
            "interval_s":   self._interval,
        }
