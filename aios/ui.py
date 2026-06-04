"""
AIOS — Textual TUI
Full-screen split-panel terminal interface.

Layout:
  ┌─ Header ────────────────────────────────────┐
  │ ┌─ Chat (3fr) ──┐  ┌─ Sidebar (1fr) ───┐  │
  │ │  conversation  │  │  CPU / RAM / Disk  │  │
  │ │  output log    │  │  top processes     │  │
  │ └────────────────┘  └───────────────────┘  │
  │ ┌─ Input ──────────────────────── [Send] ─┐ │
  └─ Status bar ────────────────────────────── ┘

Usage:
    python -m aios --ui
    from aios.ui import launch_ui; launch_ui()
"""

from __future__ import annotations

import queue
import threading
import time
from io import StringIO
from typing import Optional

from rich.console import Console as RichConsole

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Input, Button, Static, RichLog, Label,
)
from textual import on, work
from textual.reactive import reactive

# ── Output queue: route_intent() → UI ────────────────────────────────────────
_output_q: queue.SimpleQueue = queue.SimpleQueue()
_processing = threading.Event()   # set while a request is in-flight


class _UICapture:
    """File-like object that forwards Rich-rendered lines to the UI queue."""

    def __init__(self):
        self._buf = ""

    def write(self, text: str):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            # Only forward non-empty lines
            if line.strip():
                _output_q.put(line)

    def flush(self):
        if self._buf.strip():
            _output_q.put(self._buf)
            self._buf = ""


class _UIConsole:
    """
    Drop-in replacement for the Rich Console used in aios.main.
    Markup strings go straight to the queue; Rich renderables (Table, Panel)
    are rendered to plain text first.
    """

    def __init__(self):
        self._width = 90

    def print(self, *args, style=None, **kwargs):
        if not args:
            return
        obj = args[0]
        if isinstance(obj, str):
            # It's already Rich markup — send as-is
            _output_q.put(obj)
        else:
            # Rich renderable (Table, Panel, …) — render to plain text
            buf = StringIO()
            rc = RichConsole(
                file=buf, markup=True, width=self._width,
                highlight=False, force_terminal=False, no_color=True,
            )
            rc.print(obj)
            for line in buf.getvalue().splitlines():
                if line.strip():
                    _output_q.put(line)


def _make_ui_cprint(ui_console: _UIConsole):
    """Return a cprint() replacement that forwards markup to the UI queue."""
    def _ui_cprint(msg: str, style: str = ""):
        ui_console.print(msg, style=style)
    return _ui_cprint


# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
Screen {
    layout: vertical;
    background: $surface;
}

#main-area {
    height: 1fr;
    layout: horizontal;
}

#chat-panel {
    width: 3fr;
    border: solid $accent;
    padding: 0 1;
    margin: 0 1 0 0;
}

#chat-log {
    height: 1fr;
}

#sidebar {
    width: 28;
    border: solid $panel-lighten-1;
    padding: 0 1;
}

#stats-display {
    height: 1fr;
    color: $text;
}

#input-row {
    height: 3;
    layout: horizontal;
    padding: 0 1;
    margin-top: 1;
}

#user-input {
    width: 1fr;
    margin-right: 1;
}

#send-btn {
    width: 10;
}

#status-bar {
    height: 1;
    background: $panel;
    padding: 0 1;
    color: $text-muted;
    dock: bottom;
}

.thinking {
    color: $warning;
}
"""


# ── Main App ──────────────────────────────────────────────────────────────────
class AIOSUI(App):
    """AIOS full-screen terminal interface."""

    CSS = _CSS
    TITLE = "AIOS — AI Operating System"
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear"),
    ]

    _intent_label: reactive[str] = reactive("")
    _ollama_ok: reactive[Optional[bool]] = reactive(None)
    _busy: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-area"):
            with Vertical(id="chat-panel"):
                yield RichLog(id="chat-log", markup=True, wrap=True, highlight=True)
            with Vertical(id="sidebar"):
                yield Static(id="stats-display", markup=True)
        with Horizontal(id="input-row"):
            yield Input(
                placeholder="Ask anything — 'find my resume', 'show processes', 'open chrome'…",
                id="user-input",
            )
            yield Button("Send", id="send-btn", variant="primary")
        yield Static("", id="status-bar", markup=True)

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    def on_mount(self) -> None:
        self._stats_timer = self.set_interval(2.0, self._refresh_stats)
        self._drain_timer = self.set_interval(0.08, self._drain_output)
        self._refresh_stats()
        self._check_ollama()
        chat = self.query_one("#chat-log", RichLog)
        chat.write("[bold cyan]AIOS[/bold cyan] — AI Operating System  [dim](Textual UI)[/dim]")
        chat.write(
            "[dim]Just type in natural language. No slash commands needed.[/dim]\n"
            "[dim]Examples: 'find my resume'  ·  'show processes'  ·  'open spotify'[/dim]\n"
        )
        self.query_one("#user-input", Input).focus()

    # ── Stats sidebar ──────────────────────────────────────────────────────────
    def _refresh_stats(self) -> None:
        try:
            from aios.process_manager import get_system_stats, get_process_list
            s = get_system_stats()
            procs = get_process_list(top_n=6)

            cpu = s["cpu_percent"]
            ram_pct = s["ram_percent"]
            disk_free = s["disk_free_gb"]

            def _bar(pct: float, width: int = 14) -> str:
                filled = round(pct / 100 * width)
                color = "red" if pct > 80 else "yellow" if pct > 55 else "green"
                return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/{color}]"

            cpu_color = "red" if cpu > 80 else "yellow" if cpu > 55 else "green"
            ram_color = "red" if ram_pct > 85 else "yellow" if ram_pct > 65 else "white"

            lines = [
                "[bold]System Stats[/bold]",
                f"CPU  [{cpu_color}]{cpu:5.1f}%[/{cpu_color}]",
                _bar(cpu),
                f"RAM  [{ram_color}]{s['ram_used_gb']}/{s['ram_total_gb']}GB[/{ram_color}]",
                _bar(ram_pct),
                f"Disk  [dim]{disk_free}GB free[/dim]",
                "",
                "[bold]Top Processes[/bold]",
            ]
            for p in procs:
                name = p["name"][:13]
                c = p["cpu_percent"]
                m = p["memory_mb"]
                pc = "red" if c > 20 else "yellow" if c > 5 else "white"
                lines.append(
                    f"[{pc}]{name:<13}[/{pc}] [dim]{c:4.1f}% {m:4}MB[/dim]"
                )

            widget = self.query_one("#stats-display", Static)
            widget.update("\n".join(lines))
        except Exception:
            pass

    # ── Ollama health ──────────────────────────────────────────────────────────
    @work(thread=True)
    def _check_ollama(self) -> None:
        from aios.llm_engine import check_ollama_health
        ok = check_ollama_health()
        self.call_from_thread(self._set_ollama, ok)

    def _set_ollama(self, ok: bool) -> None:
        self._ollama_ok = ok
        self._update_status()

    # ── Status bar ─────────────────────────────────────────────────────────────
    def _update_status(self, intent: str = "") -> None:
        try:
            bar = self.query_one("#status-bar", Static)
            if self._ollama_ok is None:
                ol = "[dim]Ollama: checking…[/dim]"
            elif self._ollama_ok:
                ol = "[green]● Ollama[/green]"
            else:
                ol = "[red]● Ollama offline[/red]  [dim](fast-mode only)[/dim]"
            busy_str = "  [yellow]⠿ thinking…[/yellow]" if self._busy else ""
            intent_str = f"  [dim]Intent: {intent}[/dim]" if intent else ""
            bar.update(f" {ol}{busy_str}{intent_str}")
        except Exception:
            pass

    # ── Output drain ───────────────────────────────────────────────────────────
    def _drain_output(self) -> None:
        try:
            chat = self.query_one("#chat-log", RichLog)
            count = 0
            while count < 30:
                try:
                    line = _output_q.get_nowait()
                    chat.write(line)
                    count += 1
                except queue.Empty:
                    break
            if not _processing.is_set() and self._busy:
                self._busy = False
                self._update_status(self._intent_label)
        except Exception:
            pass

    # ── Input handling ─────────────────────────────────────────────────────────
    @on(Input.Submitted, "#user-input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._dispatch(event.value)

    @on(Button.Pressed, "#send-btn")
    def on_send_pressed(self, event: Button.Pressed) -> None:
        inp = self.query_one("#user-input", Input)
        self._dispatch(inp.value)

    def _dispatch(self, text: str) -> None:
        text = text.strip()
        if not text or self._busy:
            return
        inp = self.query_one("#user-input", Input)
        inp.value = ""
        chat = self.query_one("#chat-log", RichLog)
        chat.write(f"\n[bold green]You:[/bold green] {text}")
        self._busy = True
        _processing.set()
        self._update_status()
        self._run_intent(text)

    # ── Background worker ──────────────────────────────────────────────────────
    @work(thread=True)
    def _run_intent(self, text: str) -> None:
        import aios.main as _main

        ui_console = _UIConsole()
        ui_cprint = _make_ui_cprint(ui_console)

        # Patch output functions
        orig_console = _main.console
        orig_cprint = _main.cprint
        # Also suppress blocking input() calls — auto-respond 'n' (safe default)
        import builtins
        orig_input = builtins.input

        def _safe_input(prompt=""):
            _output_q.put(f"[dim]{prompt}[auto: n][/dim]")
            return "n"

        _main.console = ui_console
        _main.cprint = ui_cprint
        builtins.input = _safe_input

        try:
            _main.route_intent(text)
        except SystemExit:
            _output_q.put("[yellow]Use Ctrl+C or close the window to exit.[/yellow]")
        except Exception as exc:
            _output_q.put(f"[red]Error: {exc}[/red]")
        finally:
            _main.console = orig_console
            _main.cprint = orig_cprint
            builtins.input = orig_input
            _processing.clear()

    # ── Actions ────────────────────────────────────────────────────────────────
    def action_quit(self) -> None:
        self.exit()

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", RichLog).clear()


# ── Entry point ───────────────────────────────────────────────────────────────
def launch_ui() -> None:
    """Start the AIOS Textual UI."""
    app = AIOSUI()
    app.run()
