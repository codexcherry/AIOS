"""
AIOS  --  Cognitive Pipeline Dashboard  v2
==========================================
Deep OS-level animated pipeline.

Pipeline (blank when idle, only used nodes light up):
  USER INPUT
  -> [URL Router  |  LLM Engine]  (only one path illuminates)
  -> INTENT PARSER
  -> SYSCALL PLANNER
  -> KERNEL DISPATCHER
  -> [Process Mgr | File System | Memory Mgr | Network Stack | Registry]
  -> OS RESPONSE BUFFER
  -> ACTION COMPLETE

Right panel:
  AI ALERT CENTER   real-time OS monitoring (CPU/RAM/PROC/DISK/NET)
  AI BRAIN          reasoning log + NL chat

Run:   python dashboard.py
Needs: pip install dearpygui psutil
"""
from __future__ import annotations

import math
import random
import re
import threading
import time
import datetime
from collections import deque

import psutil
import dearpygui.dearpygui as dpg

# ─────────────────────────────────────────────────────────────────────────────
# Window / canvas geometry
# ─────────────────────────────────────────────────────────────────────────────
WIN_W = 1440
WIN_H = 900

PL_W  = 858          # pipeline drawlist width
PL_H  = 755          # pipeline drawlist height  (nodes reach y~733)

PL_PANEL_W   = PL_W + 22          # 880 -- left child_window width
RIGHT_W      = WIN_W - PL_PANEL_W - 22  # 538

CONTENT_H    = 792   # WIN_H - header(36) - footer(54) - gaps(18)
ALERT_H      = 490   # AI alert center panel height
BRAIN_H      = CONTENT_H - ALERT_H - 8  # 294

ALERT_BARS_H = 86    # health-bar drawlist inside alert panel (5 rows)
ALERT_FEED_H = ALERT_H - ALERT_BARS_H - 52   # alert card drawlist height

BRAIN_TEXT_H = BRAIN_H - 54     # leaves room for header + chat bar
CHAT_H       = 32

# ─────────────────────────────────────────────────────────────────────────────
# Colour palette
# ─────────────────────────────────────────────────────────────────────────────
C_BG      = (  6,   7,  17, 255)
C_PANEL   = ( 11,  15,  32, 255)
C_BORDER  = (  0,  85, 100, 255)
C_CYAN    = (  0, 210, 225, 255)
C_GREEN   = ( 25, 210, 115, 255)
C_RED     = (255,  75,  75, 255)
C_ORANGE  = (255, 155,   0, 255)
C_PURPLE  = (155,  70, 250, 255)
C_YELLOW  = (235, 200,   0, 255)
C_BLUE    = ( 45, 125, 255, 255)
C_MAGENTA = (220,  55, 175, 255)
C_TEAL    = (  0, 185, 175, 255)
C_TEXT    = (190, 220, 235, 255)
C_DIM     = ( 70,  85, 110, 255)
C_WHITE   = (225, 235, 250, 255)

def _a(c: tuple, alpha: int) -> list:
    return list(c[:3]) + [max(0, min(255, int(alpha)))]

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline node definitions
# Format: (label, sublabel, cx, y, w, h, colour)
# CX = 429 is the horizontal centre of the main column
# ─────────────────────────────────────────────────────────────────────────────
CX = 429

PIPE: dict[str, tuple] = {
    "input":   ("USER INPUT",         "natural language command",  CX,   12, 240, 50, C_CYAN),
    "router":  ("URL ROUTER",         "45+ rules  --  0 ms",      178,  107, 196, 42, C_GREEN),
    "llm":     ("LLM ENGINE",         "llama3.2:3b  Ollama",      680,  107, 196, 42, C_ORANGE),
    "intent":  ("INTENT PARSER",      "map input to OS action",   CX,   196, 240, 50, C_CYAN),
    "syscall": ("SYSCALL PLANNER",    "select kernel APIs",       CX,   296, 240, 50, C_BLUE),
    "kernel":  ("KERNEL DISPATCHER",  "route to OS subsystem",    CX,   396, 240, 50, C_MAGENTA),
    "proc":    ("PROCESS MGR",        "spawn / kill / list",      86,   496, 130, 38, C_GREEN),
    "filesys": ("FILE SYSTEM",        "read / write / move",      254,  496, 130, 38, C_YELLOW),
    "memgr":   ("MEMORY MGR",         "alloc / GC / swap",        429,  496, 130, 38, C_PURPLE),
    "net":     ("NETWORK STACK",      "socket / HTTP / DNS",      606,  496, 130, 38, C_BLUE),
    "reg":     ("REGISTRY",           "keys / env / config",      778,  496, 130, 38, C_ORANGE),
    "osbuf":   ("OS RESPONSE BUF",    "collect + format output",  CX,   588, 240, 42, C_TEAL),
    "done":    ("ACTION COMPLETE",    "result delivered",         CX,   684, 240, 50, C_GREEN),
}

EDGES: list[tuple[str, str]] = [
    ("input",  "router"),  ("input",  "llm"),
    ("router", "intent"),  ("llm",    "intent"),
    ("intent", "syscall"),
    ("syscall","kernel"),
    ("kernel", "proc"),    ("kernel", "filesys"),
    ("kernel", "memgr"),   ("kernel", "net"),     ("kernel", "reg"),
    ("proc",   "osbuf"),   ("filesys","osbuf"),
    ("memgr",  "osbuf"),   ("net",    "osbuf"),   ("reg",    "osbuf"),
    ("osbuf",  "done"),
]

# Mapping intent type -> which branch nodes to activate
BRANCH_MAP: dict[str, list[str]] = {
    "app":     ["proc"],
    "file":    ["filesys"],
    "memory":  ["memgr"],
    "network": ["net"],
    "config":  ["reg"],
    "shell":   ["proc", "filesys"],
    "default": ["proc"],
    "demo":    ["proc", "filesys", "memgr", "net", "reg"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Alert centre definitions
# ─────────────────────────────────────────────────────────────────────────────
MAX_ALERTS  = 28
_alert_lock = threading.Lock()
_alerts: deque[dict] = deque(maxlen=MAX_ALERTS)

ALERT_LEVEL_COL = {
    "CRIT": C_RED,
    "WARN": C_ORANGE,
    "INFO": C_CYAN,
    "OK":   C_GREEN,
}
ALERT_CAT_COL = {
    "CPU":  C_RED,
    "RAM":  C_PURPLE,
    "PROC": C_GREEN,
    "DISK": C_YELLOW,
    "NET":  C_BLUE,
    "SWAP": C_ORANGE,
    "THRD": C_TEAL,
    "SYS":  C_CYAN,
}

def _push_alert(level: str, cat: str, msg: str):
    with _alert_lock:
        _alerts.append({
            "level": level, "cat": cat, "msg": msg,
            "ts": datetime.datetime.now().strftime("%H:%M:%S"),
        })

# ─────────────────────────────────────────────────────────────────────────────
# Shared live metrics
# ─────────────────────────────────────────────────────────────────────────────
_live: dict = {
    "cpu": 0.0, "ram": 0.0, "ram_used": 0.0, "ram_total": 0.0,
    "disk": 0.0, "disk_free": 0.0,
    "net_rx": 0.0, "net_tx": 0.0,
    "procs": 0, "threads": 0,
    "swap": 0.0,
    "top_proc": ("--", 0.0),
}
_live_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline animation state
# ─────────────────────────────────────────────────────────────────────────────
_pipe_lock    = threading.Lock()
node_pulse:   dict[str, float] = {k: 0.0    for k in PIPE}
node_state:   dict[str, str]   = {k: "idle" for k in PIPE}
node_sub:     dict[str, str]   = {}    # override sublabel
edge_flow:    dict              = {e: 0.0   for e in EDGES}
edge_active:  dict              = {e: False for e in EDGES}
_active_path: set[str]         = set()    # nodes participating in current run
_pipeline_running = False

brain_lines:   list[str] = ["Waiting for trigger...\n"]
_brain_lock    = threading.Lock()
_chat_pending: list[str] = []
demo_running   = False
_last_pipeline_cmd = ""

# ─────────────────────────────────────────────────────────────────────────────
# Metric + alert monitor thread
# ─────────────────────────────────────────────────────────────────────────────
def _monitor_thread():
    # Prime cpu_percent so second call returns a real value
    psutil.cpu_percent(interval=0.1)
    prev_net  = psutil.net_io_counters()
    prev_disk = psutil.disk_io_counters()
    tick = 0

    while True:
        time.sleep(2.5)
        tick += 1
        try:
            cpu  = psutil.cpu_percent(interval=0.1)
            mem  = psutil.virtual_memory()
            swap = psutil.swap_memory()

            # Safe per-process iteration -- some procs deny access
            pcount   = 0
            tcnt     = 0
            top_name = "--"
            top_cpu  = 0.0
            for p in psutil.process_iter(["name", "cpu_percent", "num_threads"]):
                try:
                    pcount += 1
                    pc = p.info.get("cpu_percent") or 0.0
                    nt = p.info.get("num_threads") or 0
                    tcnt += nt
                    if pc > top_cpu:
                        top_cpu  = pc
                        top_name = (p.info.get("name") or "--")[:18]
                except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                    pass

            try:
                disk = psutil.disk_usage("C:\\")
                disk_pct  = disk.percent
                disk_free = disk.free / 1024**3
            except Exception:
                disk_pct  = 0.0
                disk_free = 0.0

            curr_net  = psutil.net_io_counters()
            curr_disk = psutil.disk_io_counters()
            net_rx    = max(0, curr_net.bytes_recv - prev_net.bytes_recv) / 1024
            net_tx    = max(0, curr_net.bytes_sent - prev_net.bytes_sent) / 1024
            prev_net  = curr_net
            prev_disk = curr_disk

            with _live_lock:
                _live.update({
                    "cpu": cpu, "ram": mem.percent,
                    "ram_used":  mem.used  / 1024**3,
                    "ram_total": mem.total / 1024**3,
                    "disk": disk_pct, "disk_free": disk_free,
                    "net_rx": net_rx, "net_tx": net_tx,
                    "procs": pcount, "threads": tcnt,
                    "swap": swap.percent,
                    "top_proc": (top_name, top_cpu),
                })

            # ── Generate alerts ────────────────────────────────────────────
            if cpu > 88:
                _push_alert("CRIT","CPU", f"CPU spike {cpu:.0f}%  --  system stressed")
            elif cpu > 68:
                _push_alert("WARN","CPU", f"CPU elevated {cpu:.0f}%  --  {psutil.cpu_count()} cores")

            if mem.percent > 87:
                _push_alert("CRIT","RAM",
                    f"Memory pressure {mem.percent:.0f}%  "
                    f"--  {mem.available/1024**3:.1f} GB free")
            elif mem.percent > 72:
                _push_alert("WARN","RAM",
                    f"Memory {mem.percent:.0f}%  "
                    f"({mem.used/1024**3:.1f}/{mem.total/1024**3:.1f} GB)")

            if top_cpu > 30:
                _push_alert("WARN","PROC",
                    f"High-CPU process:  {top_name}  @  {top_cpu:.0f}%")
            elif top_cpu > 15:
                _push_alert("INFO","PROC",
                    f"Active process:  {top_name}  @  {top_cpu:.0f}%")

            if disk_pct > 92:
                _push_alert("CRIT","DISK",
                    f"C:\\ {disk_pct:.0f}% full  --  {disk_free:.1f} GB free")
            elif disk_pct > 80:
                _push_alert("WARN","DISK",
                    f"C:\\ {disk_pct:.0f}% used  --  {disk_free:.1f} GB free")

            if swap.percent > 50:
                _push_alert("WARN","SWAP",
                    f"Swap usage {swap.percent:.0f}%  --  RAM spilling to disk")

            rx_mb = net_rx / 1024
            tx_mb = net_tx / 1024
            if rx_mb > 5 or tx_mb > 5:
                _push_alert("INFO","NET",
                    f"Network burst  rx {rx_mb:.1f} MB/s  tx {tx_mb:.1f} MB/s")
            elif rx_mb > 0.5 or tx_mb > 0.5:
                _push_alert("INFO","NET",
                    f"Network active  rx {net_rx:.0f} KB/s  tx {net_tx:.0f} KB/s")

            # Periodic SYS heartbeat every ~30s
            if tick % 12 == 0:
                boot   = datetime.datetime.fromtimestamp(psutil.boot_time())
                uptime = datetime.datetime.now() - boot
                hours  = int(uptime.total_seconds() // 3600)
                mins   = int((uptime.total_seconds() % 3600) // 60)
                _push_alert("OK","SYS",
                    f"Uptime {hours}h {mins}m  --  "
                    f"{pcount} procs  {tcnt} threads  --  nominal")

            if tick % 6 == 0 and cpu < 50 and mem.percent < 60:
                _push_alert("OK","SYS",
                    f"All thresholds clear  --  CPU {cpu:.0f}%  RAM {mem.percent:.0f}%")

        except Exception as e:
            _push_alert("INFO","SYS", f"Monitor tick error: {e}")

threading.Thread(target=_monitor_thread, daemon=True, name="Monitor").start()

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline helpers
# ─────────────────────────────────────────────────────────────────────────────
def _set_node(nid: str, state: str, sub: str = ""):
    node_state[nid] = state
    node_pulse[nid] = (1.0 if state == "active" else
                       0.40 if state == "done"   else 0.0)
    if sub:
        node_sub[nid] = sub
    else:
        node_sub.pop(nid, None)

def _activate_edge(fid: str, tid: str):
    key = (fid, tid)
    if key in edge_flow:
        edge_flow[key]   = 0.0
        edge_active[key] = True

def _reset_pipeline():
    global _pipeline_running
    for k in PIPE:
        node_state[k] = "idle"
        node_pulse[k] = 0.0
    node_sub.clear()
    _active_path.clear()
    for e in EDGES:
        edge_flow[e]   = 0.0
        edge_active[e] = False
    _pipeline_running = False

def _pipeline_run(cmd: str, use_llm: bool, branches: list[str]):
    global _pipeline_running, _last_pipeline_cmd
    _pipeline_running   = True
    _last_pipeline_cmd  = cmd

    # Determine the active path for this run
    path: set[str] = {"input", "intent", "syscall", "kernel", "osbuf", "done"}
    path |= set(branches)
    if use_llm:
        path.add("llm")
    else:
        path.add("router")
    _active_path.clear()
    _active_path.update(path)

    def step(nid: str, dur: float, sub: str = ""):
        _set_node(nid, "active", sub)
        for (f, t) in EDGES:
            if f == nid and t in _active_path:
                _activate_edge(f, t)
        time.sleep(dur)
        _set_node(nid, "done")

    label = f'"{cmd[:18]}..."' if len(cmd) > 18 else f'"{cmd}"'
    step("input", 0.45, label)

    if not use_llm:
        step("router", 0.40, "RULE MATCHED")
        node_state["llm"] = "idle"
    else:
        _set_node("router", "active", "checking rules...")
        time.sleep(0.12)
        step("llm", 0.90, "LLM inferring...")
        _set_node("router", "done")

    step("intent",  0.45, "mapping to OS")
    step("syscall", 0.50, "syscall list ready")
    step("kernel",  0.40, "dispatching...")

    for b in branches:
        _set_node(b, "active")
        _activate_edge("kernel", b)
    time.sleep(0.60)
    for b in branches:
        _set_node(b, "done")
        _activate_edge(b, "osbuf")

    step("osbuf", 0.40, "buffering output")
    step("done",  0.55, "OK")
    time.sleep(2.5)
    _reset_pipeline()

# ─────────────────────────────────────────────────────────────────────────────
# Typewriter brain log
# ─────────────────────────────────────────────────────────────────────────────
def _typewrite(line: str):
    with _brain_lock:
        brain_lines.append("")
        idx = len(brain_lines) - 1
    for ch in line:
        with _brain_lock:
            brain_lines[idx] += ch
        time.sleep(0.020)

# ─────────────────────────────────────────────────────────────────────────────
# Demo sequence
# ─────────────────────────────────────────────────────────────────────────────
AI_DEMO_SCRIPT = [
    "[ AIOS OS Monitor -- scanning system state ]",
    "  CPU:  {cpu:.0f}%   RAM:  {ram:.0f}%  ({ram_used:.1f}/{ram_total:.1f} GB)",
    "  Swap: {swap:.0f}%   Disk C:\\  {disk:.0f}%   Processes: {procs}",
    "",
    "ALERT  RAM at {ram:.0f}% -- threshold breached  -->  MemoryGuardian",
    "  Scanning process table for largest consumer...",
    "  Top consumer:  {top_name}  PID {pid}  --  {top_mem:.0f} MB resident",
    "  Protected list check...  NOT protected  (safe to terminate)",
    "",
    "SYSCALL  sys_kill(PID={pid}, SIGTERM)  -->  KERNEL DISPATCHER",
    "  Process table update... {top_name} removed",
    "  Freed ~{freed:.0f} MB of RAM",
    "",
    "POST-ACTION  RAM now {after_ram:.0f}%  (reclaimed {delta:.1f}%)",
    "  Writing event to AIOS memory journal...",
    "  RL reward +0.82  -->  MemoryGuardian policy updated",
    "",
    "[ System stabilised -- monitoring resumed ]",
]

def _demo_thread():
    global demo_running
    with _live_lock:
        snap = dict(_live)

    pid       = random.randint(2200, 28000)
    top_mem   = random.uniform(380, 980)
    freed     = top_mem * random.uniform(0.85, 1.05)
    after_ram = max(snap["ram"] - freed / snap["ram_total"] / 10.24, 18.0)

    ctx = {
        "cpu":       snap["cpu"],
        "ram":       snap["ram"],
        "ram_used":  snap["ram_used"],
        "ram_total": snap["ram_total"],
        "swap":      snap["swap"],
        "disk":      snap["disk"],
        "procs":     snap["procs"],
        "top_name":  snap["top_proc"][0],
        "pid":       pid,
        "top_mem":   top_mem,
        "freed":     freed,
        "after_ram": after_ram,
        "delta":     snap["ram"] - after_ram,
    }

    threading.Thread(
        target=_pipeline_run,
        args=("kill high-mem process  --  free RAM", False, ["proc", "memgr"]),
        daemon=True, name="PipeAnim"
    ).start()

    _push_alert("CRIT","RAM", f"Demo: RAM {snap['ram']:.0f}% -- MemoryGuardian triggered")
    _push_alert("INFO","PROC", f"Demo: targeting {snap['top_proc'][0]}  PID {pid}")

    for line in AI_DEMO_SCRIPT:
        try:
            _typewrite(line.format(**ctx))
        except Exception:
            _typewrite(line)
        time.sleep(0.38)

    _push_alert("OK","RAM", f"Demo: freed {freed:.0f} MB -- RAM now {after_ram:.0f}%")
    demo_running = False

def trigger_demo(sender=None, app_data=None, user_data=None):
    global demo_running
    if demo_running:
        return
    demo_running = True
    with _brain_lock:
        brain_lines.clear()
    threading.Thread(target=_demo_thread, daemon=True, name="Demo").start()

# ─────────────────────────────────────────────────────────────────────────────
# NL Chat -- wired to AIOS route_intent()
# ─────────────────────────────────────────────────────────────────────────────
_aios_mod = None

def _load_aios():
    global _aios_mod
    if _aios_mod is None:
        try:
            import sys, os as _os
            sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
            import aios.main as _m
            _aios_mod = _m
        except Exception:
            pass
    return _aios_mod

def _nl_worker(text: str):
    mod        = _load_aios()
    use_llm    = True
    branches   = ["proc"]
    captured:  list[str] = []

    if mod is not None:
        try:
            from aios.url_router import route as _rt
            r = _rt(text)
            use_llm = not r.matched
            # Pick pipeline branches from router result
            if getattr(r, "file_search_query", None) is not None:
                branches = ["filesys"]
            elif getattr(r, "file_action", None):
                branches = ["filesys"]
            elif getattr(r, "assistant_action", None) in ("process",):
                branches = ["proc"]
            elif getattr(r, "apps", None):
                branches = ["proc"]
        except Exception:
            pass

        _orig = mod.cprint
        def _cap(msg="", style=""):
            clean = re.sub(r"\[/?[^\]]+\]", "", str(msg)).strip()
            if clean:
                captured.append(clean)
        mod.cprint = _cap
        threading.Thread(
            target=_pipeline_run, args=(text, use_llm, branches),
            daemon=True, name="PipeAnim"
        ).start()
        try:
            mod.route_intent(text)
        except Exception as e:
            captured.append(f"Error: {e}")
        finally:
            mod.cprint = _orig
    else:
        # Offline fallback -- local OS queries
        t = text.lower()
        if any(w in t for w in ("ram","memory","mem")):
            with _live_lock:
                s = dict(_live)
            captured.append(
                f"RAM: {s['ram']:.0f}%  "
                f"({s['ram_used']:.1f}/{s['ram_total']:.1f} GB)  "
                f"Swap {s['swap']:.0f}%"
            )
            branches = ["memgr"]
        elif "cpu" in t:
            with _live_lock:
                s = dict(_live)
            captured.append(
                f"CPU: {s['cpu']:.0f}%   Cores: {psutil.cpu_count()}  "
                f"({psutil.cpu_count(logical=False)} physical)"
            )
            branches = ["proc"]
        elif any(w in t for w in ("disk","storage","drive")):
            with _live_lock:
                s = dict(_live)
            captured.append(
                f"Disk C:\\  {s['disk']:.0f}% used  --  {s['disk_free']:.1f} GB free"
            )
            branches = ["filesys"]
        elif any(w in t for w in ("net","network","ping","ip")):
            conns = len(psutil.net_connections())
            with _live_lock:
                s = dict(_live)
            captured.append(
                f"Network: {conns} connections  "
                f"rx {s['net_rx']:.0f} KB/s  tx {s['net_tx']:.0f} KB/s"
            )
            branches = ["net"]
        elif any(w in t for w in ("proc","process","task","ps")):
            with _live_lock:
                s = dict(_live)
            captured.append(
                f"Processes: {s['procs']}  Threads: {s['threads']}  "
                f"Top: {s['top_proc'][0]} @ {s['top_proc'][1]:.0f}%"
            )
            branches = ["proc"]
        elif any(w in t for w in ("demo","trigger","test")):
            trigger_demo()
            captured.append("Demo triggered.")
            branches = []
        else:
            captured.append(f"Queued: '{text}'  (AIOS offline -- no Ollama)")
        if branches:
            threading.Thread(
                target=_pipeline_run, args=(text, False, branches),
                daemon=True, name="PipeAnim"
            ).start()

    for line in (captured or ["Done."]):
        _typewrite(line)

def nl_send(sender=None, app_data=None, user_data=None):
    text = dpg.get_value("chat_input").strip()
    if not text:
        return
    dpg.set_value("chat_input", "")
    with _brain_lock:
        brain_lines.append(f"  > {text}")
    _chat_pending.append(text)

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline renderer
# ─────────────────────────────────────────────────────────────────────────────
def _node_bottom(nid: str) -> tuple[float, float]:
    _, _, cx, y, _, h, _ = PIPE[nid]
    return float(cx), float(y + h)

def _node_top(nid: str) -> tuple[float, float]:
    _, _, cx, y, _, _, _ = PIPE[nid]
    return float(cx), float(y)

def _draw_pipeline(dl: str, frame: int):
    dpg.delete_item(dl, children_only=True)

    running = _pipeline_running

    # Faint dot grid
    for gx in range(28, PL_W, 46):
        for gy in range(20, PL_H, 46):
            dpg.draw_circle((gx, gy), 1.0,
                            color=_a(C_BORDER, 18),
                            fill=_a(C_BORDER, 18), parent=dl)

    # Edges
    for (fid, tid) in EDGES:
        fp     = edge_flow[(fid, tid)]
        active = edge_active[(fid, tid)]
        _, _, _, _, _, _, bcol = PIPE[tid]
        fx, fy = _node_bottom(fid)
        tx, ty = _node_top(tid)

        on_path = (not running) or (fid in _active_path and tid in _active_path)
        a_line  = (40 + int(fp * 140)) if active else (28 if on_path else 0)
        if a_line == 0:
            continue
        col = _a(bcol, a_line)
        dpg.draw_line((fx, fy), (tx, ty), color=col, thickness=1.4, parent=dl)

        # Arrowhead
        ah = 5.5
        dpg.draw_triangle(
            (tx - ah, ty - 8), (tx + ah, ty - 8), (tx, ty),
            color=col, fill=col, parent=dl,
        )

        # Particle dot
        if active and fp > 0.04:
            dx = fx + (tx - fx) * fp
            dy = fy + (ty - fy) * fp
            r  = 3.5 + fp * 3.0
            dpg.draw_circle((dx, dy), r + 7, color=_a(bcol, 35), fill=_a(bcol, 20), parent=dl)
            dpg.draw_circle((dx, dy), r,     color=_a(bcol, 255), fill=_a(bcol, 210), parent=dl)

    # Nodes
    for nid, (label, sublabel, cx, y, w, h, base) in PIPE.items():
        state    = node_state[nid]
        p        = node_pulse[nid]
        x0, y0   = cx - w / 2, float(y)
        x1, y1   = cx + w / 2, float(y + h)
        disp_sub = node_sub.get(nid, sublabel)

        on_path  = (not running) or (nid in _active_path)

        if not on_path:
            # Off-path while pipeline runs: almost invisible
            dpg.draw_rectangle((x0, y0), (x1, y1),
                               color=_a(base, 5), fill=_a(base, 0),
                               rounding=9, thickness=0.5, parent=dl)
            continue

        if state == "idle":
            fill = _a(base, 0);    border = _a(base, 14)
            t_col = _a(C_DIM, 65); s_col  = _a(C_DIM, 40); thick = 0.8
        elif state == "active":
            fill   = _a(base, int(30 + p * 118))
            border = _a(base, int(120 + p * 135))
            t_col  = _a(C_WHITE, 255)
            s_col  = _a(base, 230)
            thick  = 2.5 + p * 1.6
        elif state == "done":
            fill   = _a(C_GREEN, int(12 + p * 60))
            border = _a(C_GREEN, int(65 + p * 110))
            t_col  = _a(C_GREEN, 215)
            s_col  = _a(C_GREEN, 140)
            thick  = 1.4
        else:
            fill = _a(C_RED, 30);  border = _a(C_RED, 190)
            t_col = _a(C_RED, 255); s_col = _a(C_RED, 180); thick = 2.0

        # Glow halo when active
        if state == "active" and p > 0.06:
            gp = p * 14
            dpg.draw_rectangle(
                (x0 - gp, y0 - gp * 0.60), (x1 + gp, y1 + gp * 0.60),
                color=_a(base, int(p * 38)), fill=_a(base, int(p * 18)),
                rounding=16, thickness=0, parent=dl,
            )

        dpg.draw_rectangle((x0, y0), (x1, y1),
                           color=border, fill=fill,
                           rounding=9, thickness=thick, parent=dl)

        # Status dot
        dot_a = 255 if state != "idle" else 45
        dpg.draw_circle((x0 + 13, y0 + h / 2), 4.5,
                        color=_a(base, dot_a), fill=_a(base, dot_a), parent=dl)

        # Text
        lx = cx - len(label) * 4.55
        dpg.draw_text((lx, y0 + 8),  label,    color=t_col, size=15, parent=dl)
        sx = cx - len(disp_sub) * 3.65
        dpg.draw_text((sx, y0 + 28), disp_sub, color=s_col, size=12, parent=dl)

# ─────────────────────────────────────────────────────────────────────────────
# Alert centre renderer  (health bars + alert cards)
# ─────────────────────────────────────────────────────────────────────────────
def _bar_full(dl, y: float, w: float, bh: float,
              pct: float, col: tuple, label: str, val_str: str):
    """Draw a full-width labelled bar: LABEL [====....] VALUE."""
    LW = 32   # label column width
    VW = 88   # value column width (right side)
    bw = w - LW - VW - 8  # track width
    dpg.draw_text((2, y), label, color=_a(C_DIM, 210), size=11, parent=dl)
    tx = LW
    # Track
    dpg.draw_rectangle((tx, y + 1), (tx + bw, y + bh + 1),
                       color=_a(C_BORDER, 55), fill=_a(C_BORDER, 20),
                       rounding=2, thickness=1, parent=dl)
    # Fill
    fw = max(3, bw * min(pct / 100.0, 1.0))
    fc = C_RED if pct > 85 else (C_ORANGE if pct > 65 else col)
    dpg.draw_rectangle((tx, y + 1), (tx + fw, y + bh + 1),
                       color=_a(fc, 210), fill=_a(fc, 115),
                       rounding=2, thickness=0, parent=dl)
    # Value (right-aligned in VW column)
    dpg.draw_text((tx + bw + 5, y), val_str[:13],
                  color=_a(fc, 225), size=11, parent=dl)


def _draw_health_bars(dl: str, w: int, h: int):
    dpg.delete_item(dl, children_only=True)
    with _live_lock:
        s = dict(_live)

    bh = 11   # bar track height
    ys = [4, 21, 38, 55, 70]   # y positions for 5 rows

    _bar_full(dl, ys[0], w, bh, s["cpu"],  C_CYAN,
              "CPU", f"{s['cpu']:.0f}%")
    _bar_full(dl, ys[1], w, bh, s["ram"],  C_PURPLE,
              "RAM", f"{s['ram']:.0f}% {s['ram_used']:.0f}/{s['ram_total']:.0f}G")
    _bar_full(dl, ys[2], w, bh, s["disk"], C_YELLOW,
              "DSK", f"{s['disk']:.0f}% {s['disk_free']:.0f}G")
    _bar_full(dl, ys[3], w, bh, s["swap"], C_ORANGE,
              "SWP", f"{s['swap']:.0f}%")

    rx = s["net_rx"]; tx_v = s["net_tx"]
    net_str = (f"rx {rx/1024:.1f}M  tx {tx_v/1024:.1f}M"
               if rx > 1024 or tx_v > 1024
               else f"rx {rx:.0f}KB  tx {tx_v:.0f}KB")
    top_n, top_c = s["top_proc"]
    dpg.draw_text((2, ys[4]),
                  f"NET {net_str}   PROC {s['procs']}  TH {s['threads']}"
                  f"   top: {top_n} {top_c:.0f}%",
                  color=_a(C_TEAL, 210), size=11, parent=dl)


CARD_H    = 21    # height of each alert card
CARD_PAD  = 1     # vertical gap between cards

def _draw_alert_feed(dl: str, w: int, h: int):
    dpg.delete_item(dl, children_only=True)
    with _alert_lock:
        recent = list(reversed(list(_alerts)))   # newest first

    visible = max(1, (h - 4) // (CARD_H + CARD_PAD))
    recent  = recent[:visible]

    for i, alert in enumerate(recent):
        y    = 4 + i * (CARD_H + CARD_PAD)
        lv   = alert["level"]
        cat  = alert["cat"]
        ts   = alert["ts"]
        msg  = alert["msg"]
        lv_c = ALERT_LEVEL_COL.get(lv, C_CYAN)
        ct_c = ALERT_CAT_COL.get(cat, C_TEXT)

        # Row background (subtle)
        bg_a = 18 if i % 2 == 0 else 8
        dpg.draw_rectangle((2, y), (w - 2, y + CARD_H),
                           color=_a(lv_c, 12), fill=_a(lv_c, bg_a),
                           rounding=3, thickness=0, parent=dl)

        # Level badge
        dpg.draw_rectangle((4, y + 2), (46, y + CARD_H - 2),
                           color=_a(lv_c, 90), fill=_a(lv_c, 28),
                           rounding=3, thickness=1, parent=dl)
        dpg.draw_text((7, y + 5), lv, color=_a(lv_c, 255), size=10, parent=dl)

        # Cat badge
        dpg.draw_rectangle((50, y + 2), (90, y + CARD_H - 2),
                           color=_a(ct_c, 70), fill=_a(ct_c, 22),
                           rounding=3, thickness=1, parent=dl)
        dpg.draw_text((53, y + 5), cat, color=_a(ct_c, 240), size=10, parent=dl)

        # Timestamp
        dpg.draw_text((95, y + 5), ts, color=_a(C_DIM, 190), size=10, parent=dl)

        # Message (truncate to fit)
        max_chars = max(10, (w - 148) // 6)
        dpg.draw_text((148, y + 5), msg[:max_chars],
                      color=_a(C_TEXT, 220), size=10, parent=dl)

# ─────────────────────────────────────────────────────────────────────────────
# UI construction
# ─────────────────────────────────────────────────────────────────────────────
def build_ui():
    # Theme
    with dpg.theme() as g_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg,       C_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg,        C_PANEL)
            dpg.add_theme_color(dpg.mvThemeCol_Border,         C_BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_Text,           C_TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_Button,         (  0,  75, 95, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,  (  0, 115,135, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,   (  0, 185,200, 255))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg,        ( 10,  18, 40, 255))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, ( 18,  30, 60, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg,    C_BG)
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab,  C_BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,  8)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,   6)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,   4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding,  10, 10)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,     7,  5)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding,    6,  5)
    dpg.bind_theme(g_theme)

    try:
        with dpg.font_registry():
            mono = dpg.add_font("c:/Windows/Fonts/consola.ttf", 14)
        dpg.bind_font(mono)
    except Exception:
        pass

    # ── Alert feed inner dimensions (drawlist width = RIGHT_W - 20 for padding)
    ADLW = RIGHT_W - 22    # 516

    with dpg.window(tag="main", no_title_bar=True, no_move=True,
                    no_resize=True, width=WIN_W, height=WIN_H, pos=(0, 0)):

        # ── Header ─────────────────────────────────────────────────────────
        with dpg.group(horizontal=True):
            dpg.add_text("AIOS", color=C_CYAN)
            dpg.add_text("  Cognitive Pipeline Dashboard", color=C_TEXT)
            dpg.add_text(
                "   OS-Level:  Syscall -> Kernel -> Subsystem -> Response",
                color=C_DIM)
            dpg.add_spacer(width=18)
            dpg.add_text("", tag="clock_lbl", color=C_DIM)
        dpg.add_separator()
        dpg.add_spacer(height=3)

        # ── Main content ────────────────────────────────────────────────────
        with dpg.group(horizontal=True):

            # Left: pipeline canvas
            with dpg.child_window(width=PL_PANEL_W, height=CONTENT_H,
                                  border=True, tag="pipe_panel"):
                with dpg.group(horizontal=True):
                    dpg.add_text("[COGNITIVE PIPELINE]", color=C_CYAN)
                    dpg.add_spacer(width=6)
                    dpg.add_text("Blank until triggered -- only active path illuminates",
                                 color=C_DIM)
                dpg.add_separator()
                dpg.add_spacer(height=3)
                dpg.add_drawlist(width=PL_W, height=PL_H, tag="pipeline_dl")

            dpg.add_spacer(width=5)

            # Right: alert center + brain
            with dpg.group():

                # AI Alert Center
                with dpg.child_window(width=RIGHT_W, height=ALERT_H,
                                      border=True, tag="alert_panel"):
                    with dpg.group(horizontal=True):
                        dpg.add_text("[AI ALERT CENTER]", color=C_RED)
                        dpg.add_spacer(width=6)
                        dpg.add_text("Real-time OS threat monitor", color=C_DIM)
                    dpg.add_separator()
                    dpg.add_spacer(height=3)

                    # Health bars drawlist
                    dpg.add_drawlist(width=ADLW, height=ALERT_BARS_H,
                                     tag="health_dl")
                    dpg.add_separator()
                    dpg.add_spacer(height=3)

                    # Alert feed drawlist (latest on top, no scroll needed)
                    dpg.add_drawlist(width=ADLW, height=ALERT_FEED_H,
                                     tag="alert_dl")

                dpg.add_spacer(height=5)

                # AI Brain + NL chat
                with dpg.child_window(width=RIGHT_W, height=BRAIN_H,
                                      border=True, tag="brain_panel"):
                    with dpg.group(horizontal=True):
                        dpg.add_text("[AI BRAIN]", color=C_CYAN)
                        dpg.add_spacer(width=6)
                        dpg.add_text("Reasoning log", color=C_DIM)
                    dpg.add_separator()
                    dpg.add_spacer(height=3)

                    dpg.add_input_text(
                        tag="brain_txt",
                        multiline=True, readonly=True,
                        width=-1, height=BRAIN_TEXT_H,
                        default_value="Waiting for trigger...\n",
                        tab_input=False,
                    )
                    dpg.add_separator()
                    dpg.add_spacer(height=3)
                    with dpg.group(horizontal=True):
                        dpg.add_input_text(
                            tag="chat_input",
                            hint="Ask AIOS  (ram, cpu, disk, processes, demo...)",
                            width=-96,
                            on_enter=True,
                            callback=nl_send,
                        )
                        dpg.add_button(label=" Send NL ", callback=nl_send,
                                       width=88, height=28, tag="send_btn")

        # ── Footer ──────────────────────────────────────────────────────────
        dpg.add_spacer(height=4)
        dpg.add_separator()
        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            dpg.add_button(label="  [!]  TRIGGER DEMO  ",
                           callback=trigger_demo,
                           tag="demo_btn", height=34, width=215)
            dpg.add_spacer(width=12)
            dpg.add_text("●", tag="status_dot", color=list(C_GREEN))
            dpg.add_spacer(width=4)
            dpg.add_text("Monitoring -- system nominal",
                         tag="status_txt", color=C_TEXT)
            dpg.add_spacer(width=-330)
            dpg.add_text("", tag="live_stats", color=C_DIM)

# ─────────────────────────────────────────────────────────────────────────────
# Per-frame update loop
# ─────────────────────────────────────────────────────────────────────────────
_frame = 0

def on_frame():
    global _frame
    _frame += 1

    # Clock (1 Hz)
    if _frame % 60 == 0:
        dpg.set_value("clock_lbl",
                      datetime.datetime.now().strftime("  %Y-%m-%d  %H:%M:%S"))

    # Advance edge particles
    for e in EDGES:
        if edge_active[e]:
            edge_flow[e] = min(1.0, edge_flow[e] + 0.032)
            if edge_flow[e] >= 1.0:
                edge_flow[e] = 0.0
                edge_active[e] = False

    # Node pulse: breathe when active, decay otherwise
    for k in PIPE:
        if node_state[k] == "active":
            node_pulse[k] = 0.76 + 0.24 * math.sin(_frame * 0.14)
        elif node_pulse[k] > 0.0:
            node_pulse[k] = max(0.0, node_pulse[k] - 0.010)

    # Redraw pipeline
    _draw_pipeline("pipeline_dl", _frame)

    # Health bars + alert feed (every 4 frames = ~15 Hz)
    if _frame % 4 == 0:
        ADLW = RIGHT_W - 22
        _draw_health_bars("health_dl", ADLW, ALERT_BARS_H)
        _draw_alert_feed("alert_dl",  ADLW, ALERT_FEED_H)

    # Drain NL queue
    pending = list(_chat_pending)
    _chat_pending.clear()
    for cmd in pending:
        threading.Thread(target=_nl_worker, args=(cmd,),
                         daemon=True, name="NLWorker").start()

    # AI Brain
    with _brain_lock:
        b_text = "\n".join(brain_lines)
    cursor = "|" if demo_running else ""
    dpg.set_value("brain_txt", b_text + cursor)

    # Status bar
    if demo_running or _pipeline_running:
        blink = (int(time.time() * 2) % 2) == 0
        dpg.set_value("status_dot", "●" if blink else "○")
        dpg.configure_item("status_dot", color=list(C_RED))
        label = ("DEMO RUNNING" if demo_running else
                 f"PIPELINE  --  {_last_pipeline_cmd[:30]}")
        dpg.set_value("status_txt", label + " -- animating...")
        dpg.configure_item("status_txt", color=list(C_ORANGE))
    else:
        dpg.set_value("status_dot", "●")
        dpg.configure_item("status_dot", color=list(C_GREEN))
        dpg.set_value("status_txt", "Monitoring -- system nominal")
        dpg.configure_item("status_txt", color=list(C_TEXT))

    with _live_lock:
        s = dict(_live)
    dpg.set_value(
        "live_stats",
        f"CPU {s['cpu']:.0f}%   "
        f"RAM {s['ram_used']:.1f}/{s['ram_total']:.1f}GB ({s['ram']:.0f}%)   "
        f"DISK {s['disk']:.0f}%   "
        f"PROCS {s['procs']}",
    )

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    dpg.create_context()
    build_ui()
    dpg.set_primary_window("main", True)
    dpg.create_viewport(
        title="AIOS -- Cognitive Pipeline Dashboard",
        width=WIN_W, height=WIN_H, resizable=True,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    while dpg.is_dearpygui_running():
        on_frame()
        dpg.render_dearpygui_frame()
    dpg.destroy_context()


if __name__ == "__main__":
    main()
