"""
AI Process Manager — Monitors, analyzes, and optimizes running processes.
Uses psutil for metrics + LLM for intelligent recommendations.
"""
import os
import psutil
import time
import subprocess
from datetime import datetime
from typing import Optional
from aios.llm_engine import analyze_process_list
from aios.utils.platform import IS_WINDOWS, root_disk


# Processes considered system-critical (never recommend killing).
# Includes both Windows (.exe) and Linux process names.
PROTECTED_PROCESSES = {
    # Windows
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "svchost.exe", "winlogon.exe",
    "explorer.exe", "dwm.exe", "audiodg.exe", "spoolsv.exe",
    # Linux
    "init", "systemd", "kthreadd", "ksoftirqd", "kworker",
    "dbus-daemon", "NetworkManager", "Xorg", "Xwayland",
    "gnome-shell", "plasmashell", "xfce4-session",
    # AIOS itself
    "python.exe", "python", "python3", "ollama", "ollama.exe",
}


def get_process_list(top_n: int = 20, sort_by: str = "memory") -> list:
    """
    Get top N processes sorted by CPU or memory usage.
    Returns list of dicts with process info.
    """
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status', 'create_time']):
        try:
            info = proc.info
            mem_mb = round(info['memory_info'].rss / 1024 / 1024, 1) if info['memory_info'] else 0
            procs.append({
                "pid": info['pid'],
                "name": info['name'] or "unknown",
                "cpu_percent": info['cpu_percent'] or 0.0,
                "memory_mb": mem_mb,
                "status": info['status'],
                "uptime_min": round((time.time() - info['create_time']) / 60) if info['create_time'] else 0,
                "protected": info['name'].lower() in PROTECTED_PROCESSES if info['name'] else False,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Second pass for accurate CPU (psutil needs two samples)
    time.sleep(0.3)
    for p in procs:
        try:
            proc = psutil.Process(p["pid"])
            p["cpu_percent"] = round(proc.cpu_percent(interval=None), 1)
        except Exception:
            pass

    sort_key = "memory_mb" if sort_by == "memory" else "cpu_percent"
    procs.sort(key=lambda x: x[sort_key], reverse=True)
    return procs[:top_n]


def get_system_stats() -> dict:
    """Get overall system resource utilization."""
    mem = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    disk = psutil.disk_usage(root_disk())
    
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "cpu_cores": psutil.cpu_count(),
        "cpu_freq_mhz": round(cpu_freq.current) if cpu_freq else 0,
        "ram_total_gb": round(mem.total / 1024**3, 1),
        "ram_used_gb": round(mem.used / 1024**3, 1),
        "ram_percent": mem.percent,
        "disk_total_gb": round(disk.total / 1024**3, 1),
        "disk_free_gb": round(disk.free / 1024**3, 1),
        "disk_percent": disk.percent,
        "timestamp": datetime.now().isoformat(),
    }


def kill_process(pid: int, name: str = "") -> dict:
    """Terminate a process by PID. Refuses to kill protected processes."""
    if name.lower() in PROTECTED_PROCESSES:
        return {"success": False, "reason": f"Process '{name}' is protected and cannot be killed."}
    
    try:
        proc = psutil.Process(pid)
        proc_name = proc.name()
        if proc_name.lower() in PROTECTED_PROCESSES:
            return {"success": False, "reason": f"Process '{proc_name}' is system-protected."}
        proc.terminate()
        proc.wait(timeout=5)
        return {"success": True, "message": f"Terminated {proc_name} (PID {pid})"}
    except psutil.NoSuchProcess:
        return {"success": False, "reason": "Process not found."}
    except psutil.TimeoutExpired:
        proc.kill()  # Force kill
        return {"success": True, "message": f"Force-killed PID {pid}"}
    except Exception as e:
        return {"success": False, "reason": str(e)}


def find_process(name: str) -> list:
    """Find processes by name (partial match)."""
    matches = []
    name_lower = name.lower()
    for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
        try:
            if name_lower in proc.info['name'].lower():
                mem_mb = round(proc.info['memory_info'].rss / 1024 / 1024, 1) if proc.info['memory_info'] else 0
                matches.append({
                    "pid": proc.info['pid'],
                    "name": proc.info['name'],
                    "memory_mb": mem_mb,
                    "cpu_percent": proc.info['cpu_percent'] or 0.0,
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def ai_optimize() -> str:
    """
    Get AI analysis and optimization recommendations for current process state.
    """
    procs = get_process_list(top_n=15, sort_by="memory")
    stats = get_system_stats()
    
    proc_summary = [
        {"name": p["name"], "cpu%": p["cpu_percent"], "ram_mb": p["memory_mb"]}
        for p in procs
    ]
    
    context = f"""
System Stats:
- CPU: {stats['cpu_percent']}% | Cores: {stats['cpu_cores']}
- RAM: {stats['ram_used_gb']}GB / {stats['ram_total_gb']}GB ({stats['ram_percent']}%)
- Disk C: {stats['disk_free_gb']}GB free ({stats['disk_percent']}% used)

Top Processes:
{proc_summary}
"""
    return analyze_process_list(proc_summary)


def monitor_loop(duration_sec: int = 10, interval_sec: float = 2.0, callback=None) -> list:
    """
    Monitor system for duration seconds, sampling every interval.
    Returns list of snapshots.
    """
    snapshots = []
    end_time = time.time() + duration_sec
    while time.time() < end_time:
        snap = get_system_stats()
        snapshots.append(snap)
        if callback:
            callback(snap)
        time.sleep(interval_sec)
    return snapshots
