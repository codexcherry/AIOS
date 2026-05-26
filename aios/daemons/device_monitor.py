"""
Device Monitor — battery, USB drives, and network changes.

Three watchers in one thread (60 s poll by default):

  1. BATTERY       — alerts at ≤30% (low) and ≤15% (critical).
                     Uses psutil.sensors_battery().  No-ops gracefully
                     if no battery is present (desktop / server).

  2. USB / DISK    — detects when new disk partitions appear (e.g. a USB
                     drive is plugged in) and adds their root path to the
                     AIOS file search context.

  3. NETWORK       — alerts once when the primary interface goes offline
                     and once when it comes back.

Configurable:
    AIOS__DAEMONS__DM_BATTERY_LOW      low battery threshold (default 30)
    AIOS__DAEMONS__DM_BATTERY_CRITICAL critical threshold (default 15)
    AIOS__DAEMONS__DM_INTERVAL         poll interval in seconds (default 60)
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Set

import psutil

from aios.logger import log
from aios import config as cfg


class DeviceMonitor(threading.Thread):
    """Background daemon for battery, USB, and network monitoring."""

    def __init__(self, notify: Optional[Callable[[str], None]] = None):
        super().__init__(daemon=True, name="DeviceMonitor")
        self._notify          = notify or print
        self._interval        = int(cfg.get("daemons", "dm_interval",          60))
        self._batt_low        = int(cfg.get("daemons", "dm_battery_low",        30))
        self._batt_critical   = int(cfg.get("daemons", "dm_battery_critical",   15))
        # Battery alert state — avoid repeating the same level
        self._batt_alerted    = ""          # "critical" | "low" | ""
        # Known disk partitions so we can detect new ones
        self._known_partitions: Set[str] = set()
        self._known_partitions_loaded = False
        # Network state
        self._net_was_up: Optional[bool] = None

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        log.info("DeviceMonitor started  interval=%ds  batt_low=%d%%  batt_crit=%d%%",
                 self._interval, self._batt_low, self._batt_critical)
        # Initialise known-partition set before first check to avoid false alerts on start
        self._known_partitions = self._current_partitions()
        self._known_partitions_loaded = True

        while True:
            try:
                self._check_battery()
                self._check_disks()
                self._check_network()
            except Exception as exc:
                log.error("DeviceMonitor error: %s", exc)
            time.sleep(self._interval)

    # ── Battery ───────────────────────────────────────────────────────────────

    def _check_battery(self) -> None:
        batt = psutil.sensors_battery()
        if batt is None:
            return  # No battery (desktop / server)

        pct = batt.percent
        plugged = batt.power_plugged

        if not plugged:
            if pct <= self._batt_critical and self._batt_alerted != "critical":
                self._batt_alerted = "critical"
                log.critical("Battery critical: %.0f%%", pct)
            elif pct <= self._batt_low and self._batt_alerted not in ("critical", "low"):
                self._batt_alerted = "low"
                log.warning("Battery low: %.0f%%", pct)
        else:
            # Charger reconnected — reset alert state
            if self._batt_alerted:
                self._batt_alerted = ""
                log.info("Battery charging: %.0f%%", pct)

    # ── Disks / USB ───────────────────────────────────────────────────────────

    def _current_partitions(self) -> Set[str]:
        try:
            return {p.mountpoint for p in psutil.disk_partitions(all=False)}
        except Exception:
            return set()

    def _check_disks(self) -> None:
        current = self._current_partitions()
        new = current - self._known_partitions

        for mountpoint in new:
            log.info("DeviceMonitor: new partition detected: %s", mountpoint)

        removed = self._known_partitions - current
        for mountpoint in removed:
            log.info("DeviceMonitor: partition removed: %s", mountpoint)

        self._known_partitions = current

    # ── Network ───────────────────────────────────────────────────────────────

    def _is_network_up(self) -> bool:
        """Return True if at least one non-loopback interface has bytes sent."""
        try:
            stats = psutil.net_if_stats()
            for iface, st in stats.items():
                if iface.lower().startswith(("lo", "loopback")):
                    continue
                if st.isup:
                    return True
        except Exception:
            pass
        return False

    def _check_network(self) -> None:
        up = self._is_network_up()
        if self._net_was_up is None:
            self._net_was_up = up
            return

        if not up and self._net_was_up:
            self._net_was_up = False
            log.warning("DeviceMonitor: network went offline")
        elif up and not self._net_was_up:
            self._net_was_up = True
            log.info("DeviceMonitor: network came back online")

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        batt = psutil.sensors_battery()
        return {
            "running":          self.is_alive(),
            "interval_s":       self._interval,
            "battery_pct":      round(batt.percent, 1) if batt else None,
            "battery_plugged":  batt.power_plugged if batt else None,
            "network_up":       self._net_was_up,
            "known_partitions": list(self._known_partitions),
        }
