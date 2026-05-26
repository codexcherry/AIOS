"""
AIOS — Cognitive Workflow Orchestration System
Main CLI Entry Point

Intent → Understanding → Parallel Execution → Contextual Computing
"""
import re
import sys
import os
import time
from pathlib import Path

# ── Rich terminal UI ─────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.prompt import Prompt
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import print as rprint
    RICH = True
except ImportError:
    RICH = False

from aios.logger import log
from aios import config as cfg
from aios.llm_engine import parse_intent, chat_response, check_ollama_health
from aios.app_launcher import launch_apps_parallel, open_url_in_chrome, _resolve_app_path
from aios.context_memory import memory
from aios.task_executor import WorkflowExecutor
from aios.ai_shell import AIShell
from aios.file_manager import smart_search, recent_files, open_file
from aios.process_manager import get_process_list, get_system_stats, kill_process, ai_optimize, find_process
from aios.workflow_engine import WorkflowEngine, PRESET_WORKFLOWS
from aios.url_router import route as url_route
from aios.file_ops import dispatch as file_dispatch
from aios.features.assistant import greet_user, tell_time, tell_date, tell_datetime, tell_joke, wikipedia_summary
from aios.features.screenshot import take_screenshot
from aios.features.notes import add_note, list_notes
from aios.rl_memory import rl
from aios.voice import voice
from aios.daemons import start_all as _start_all_daemons

console = Console() if RICH else None

# ── Global mutable state ──────────────────────────────────────────────────────
_VOICE_MODE: bool = cfg.get("voice", "enabled", False)
_daemons: dict = {}


# ── Display helpers ──────────────────────────────────────────────────────────

def cprint(msg: str, style: str = ""):
    if RICH:
        console.print(msg, style=style)
    else:
        print(msg)


def _tts_speak(text: str) -> None:
    """Speak `text` via TTS only when voice mode is active."""
    global _VOICE_MODE
    if _VOICE_MODE and voice.tts_available:
        clean = re.sub(r'\[/?[^\]]+\]', '', text).strip()  # strip Rich markup
        if clean:
            voice.speak(clean)

def print_banner():
    banner = r"""
    ╔═══════════════════════════════════════════════════════════╗
    ║          AIOS — Cognitive Workflow Orchestration          ║
    ║     Intent → Understanding → Parallel Execution           ║
    ║              Powered by llama3.2:3b (Ollama)              ║
    ╚═══════════════════════════════════════════════════════════╝
    """
    if RICH:
        console.print(Panel(banner.strip(), style="bold cyan"))
    else:
        print(banner)

def print_help():
    help_text = """
[bold cyan]AIOS Commands:[/bold cyan]

  [green]Natural Language[/green]   → Just type what you want
    "open chrome and vscode"
    "find my last project report"
    "start dev mode"
    "what's eating my RAM?"

  [yellow]Special Commands:[/yellow]
    /shell          → Enter AI-powered shell
    /workflows      → List available workflows
    /run <name>     → Run a named workflow
    /ps             → Show process manager
    /optimize       → AI process optimization
    /files <query>  → Smart file search
    /recent         → Recently modified files
    /notes          → List saved notes
    /note <text>    → Save a quick note
    /screenshot     → Take a screenshot (auto-named)
    /screenshot <n> → Take a screenshot with custom filename
    /time           → Show current time
    /date           → Show today's date
    /joke           → Tell a joke
    /memory         → Show context memory
    /context        → Show session context
    /kill <pid>     → Kill a process by PID
    /help           → This help screen
    /clear          → Clear screen
    /exit           → Exit AIOS

  [green]Natural Language Examples:[/green]
    "hi" / "hello"                     → Greeting
    "what time is it"                  → Current time
    "what's today's date"              → Current date
    "tell me a joke"                   → AI joke
    "take a screenshot"                → Screenshot (auto-named)
    "screenshot as my_capture"         → Screenshot with name
    "note: fix the login bug"          → Save note
    "who is Nikola Tesla"              → Wikipedia info
    "tell me about Python"             → Wikipedia info
    "play Tum Hi Ho"                   → YouTube search
    "open chrome and vscode"           → Parallel launch
    "create a file called hello"       → Create file
    """
    if RICH:
        console.print(Panel(help_text, title="Help", border_style="yellow"))
    else:
        print(help_text.replace("[bold cyan]", "").replace("[/bold cyan]", "")
              .replace("[green]", "").replace("[/green]", "")
              .replace("[yellow]", "").replace("[/yellow]", ""))


# ── Command handlers ─────────────────────────────────────────────────────────

def _handle_multi_url(apps: list, urls: list):
    """Open multiple URLs in Chrome (as tabs) and launch any non-browser apps."""
    non_chrome = [a for a in apps if a.lower() != "chrome"]
    total = len(urls) + len(non_chrome)
    cprint(f"\n[cyan]⚡ Opening {len(urls)} site(s) + {len(non_chrome)} app(s) in parallel:[/cyan]")

    import time as _time
    results = []

    for url in urls:
        t0 = _time.time()
        res = open_url_in_chrome(url)
        ms = round((_time.time() - t0) * 1000)
        site_label = url.split("//")[-1].split("/")[0]
        cprint(f"  [green]✓ {site_label}[/green] ({ms}ms)")
        results.append(res)
        memory.log_app_opened("chrome")

    def _on_app(app, result):
        icon  = "✓" if "launched" in result["status"] else "✗"
        color = "green" if "launched" in result["status"] else "red"
        cprint(f"  [{color}]{icon} {app}[/{color}] ({result['time_ms']}ms)")
        memory.log_app_opened(app)

    if non_chrome:
        launch_apps_parallel(non_chrome, progress_callback=_on_app)

    cprint(f"\n[green]✓ {total} opened[/green]  [dim](parallel)[/dim]")


def handle_launch_apps(apps: list, url: str = None):
    """
    Parallel app launch with live progress.
    If url is provided and chrome is in the list, opens Chrome at that URL.
    """
    if not apps:
        cprint("[red]No apps identified.[/red]")
        return

    # Separate chrome (needs URL handling) from other apps
    has_chrome = "chrome" in [a.lower() for a in apps]
    other_apps = [a for a in apps if a.lower() != "chrome"]

    if url:
        cprint(f"\n[cyan]⚡ Launching {len(apps)} app(s) in parallel:[/cyan] {', '.join(apps)}")
        cprint(f"  [dim]URL → {url}[/dim]")
    else:
        cprint(f"\n[cyan]⚡ Launching {len(apps)} app(s) in parallel:[/cyan] {', '.join(apps)}")

    launched = []
    failed = []

    def on_progress(app, result):
        icon = "✓" if "launched" in result["status"] else "✗"
        color = "green" if "launched" in result["status"] else "red"
        cprint(f"  [{color}]{icon} {app}[/{color}] ({result['time_ms']}ms)")
        if "launched" in result["status"]:
            launched.append(app)
        else:
            failed.append(app)
        memory.log_app_opened(app)

    # Launch chrome with URL if provided
    if has_chrome and url:
        result_chrome = open_url_in_chrome(url)
        on_progress("chrome", result_chrome)
    elif has_chrome:
        # No URL — just open chrome normally
        other_apps.append("chrome")

    # Launch remaining apps in parallel
    result = launch_apps_parallel(other_apps, progress_callback=on_progress) if other_apps else {"success_count": 0, "fail_count": 0, "total_time_ms": 0}

    total_success = len(launched)
    total_fail = len(failed)
    cprint(
        f"\n[green]✓ {total_success} launched[/green]  "
        f"[red]✗ {total_fail} failed[/red]  "
        f"[dim]({result['total_time_ms']}ms total)[/dim]"
    )


def handle_file_op(file_action: str, filename: str, content_desc: str = "",
                   new_filename: str = None):
    """Handle all file CRUD operations with rich output."""
    import os
    cwd = os.getcwd()

    if file_action == "read" or file_action == "show":
        cprint(f"\n[cyan]Reading:[/cyan] {filename}")
        result = file_dispatch("read", filename=filename, cwd=cwd)
        if result["success"]:
            lines = result["content"].splitlines()
            cprint(f"[dim]── {result['path']} ({result['lines']} lines) ──[/dim]")
            # Syntax-aware display with line numbers
            for i, line in enumerate(lines, 1):
                cprint(f"[dim]{i:4}[/dim]  {line}")
        else:
            cprint(f"[red]✗ {result['error']}[/red]")
        return

    if file_action == "create":
        desc_display = f": {content_desc[:60]}..." if content_desc else ""
        cprint(f"\n[cyan]Creating:[/cyan] {filename}{desc_display}")
        if content_desc:
            cprint("[dim]Generating content with AI...[/dim]")
        result = file_dispatch("create", filename=filename, description=content_desc, cwd=cwd)
        if result.get("exists"):
            try:
                ans = input(f"  File exists. Overwrite? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("y", "yes"):
                from aios.file_ops import create_file
                result = create_file(filename, content_desc, overwrite=True, cwd=cwd)
            else:
                cprint("[yellow]Cancelled.[/yellow]")
                return
        if result["success"]:
            cprint(f"[green]✓ Created:[/green] {result['path']}  ({result['lines']} lines, {result['size']} bytes)")
            # Show preview (first 20 lines)
            lines = result["content"].splitlines()
            preview = lines[:20]
            cprint(f"\n[dim]── Preview ──[/dim]")
            for i, line in enumerate(preview, 1):
                cprint(f"[dim]{i:4}[/dim]  {line}")
            if len(lines) > 20:
                cprint(f"[dim]  ... {len(lines) - 20} more lines[/dim]")
        else:
            cprint(f"[red]✗ {result.get('error', 'Unknown error')}[/red]")
        return

    if file_action in ("update", "modify", "edit"):
        cprint(f"\n[cyan]Updating:[/cyan] {filename}")
        cprint(f"[dim]Instruction: {content_desc}[/dim]")
        cprint("[dim]Applying changes with AI...[/dim]")
        result = file_dispatch("update", filename=filename, description=content_desc, cwd=cwd)
        if result.get("suggest_create"):
            try:
                ans = input(f"  File not found. Create it instead? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("y", "yes"):
                result = file_dispatch("create", filename=filename, description=content_desc, cwd=cwd)
        if result["success"]:
            cprint(f"[green]✓ Updated:[/green] {result['path']}  ({result['lines']} lines)")
            lines = result["content"].splitlines()
            cprint(f"\n[dim]── Updated content ──[/dim]")
            for i, line in enumerate(lines[:20], 1):
                cprint(f"[dim]{i:4}[/dim]  {line}")
            if len(lines) > 20:
                cprint(f"[dim]  ... {len(lines) - 20} more lines[/dim]")
        else:
            cprint(f"[red]✗ {result.get('error', 'Unknown error')}[/red]")
        return

    if file_action == "append":
        cprint(f"\n[cyan]Appending to:[/cyan] {filename}")
        cprint("[dim]Generating new content...[/dim]")
        result = file_dispatch("append", filename=filename, description=content_desc, cwd=cwd)
        if result["success"]:
            cprint(f"[green]✓ Appended to:[/green] {result['path']}")
            cprint(f"\n[dim]── Appended ──[/dim]\n{result.get('appended', '')}")
        else:
            cprint(f"[red]✗ {result.get('error', 'Unknown error')}[/red]")
        return

    if file_action == "delete":
        cprint(f"\n[yellow]Delete:[/yellow] {filename}")
        result = file_dispatch("delete", filename=filename, cwd=cwd)
        if result.get("needs_confirmation"):
            try:
                ans = input(f"  {result['message']} [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("y", "yes"):
                from aios.file_ops import delete_file
                result = delete_file(filename, confirmed=True, cwd=cwd)
                cprint(f"[green]✓ Deleted:[/green] {filename}")
            else:
                cprint("[yellow]Cancelled.[/yellow]")
        elif result["success"]:
            cprint(f"[green]✓ Deleted:[/green] {filename}")
        else:
            cprint(f"[red]✗ {result.get('error', 'Unknown error')}[/red]")
        return

    if file_action == "rename":
        cprint(f"\n[cyan]Renaming:[/cyan] {filename} → {new_filename}")
        result = file_dispatch("rename", filename=filename, new_filename=new_filename, cwd=cwd)
        if result["success"]:
            cprint(f"[green]✓ Renamed:[/green] {filename} → {new_filename}")
        else:
            cprint(f"[red]✗ {result.get('error', 'Unknown error')}[/red]")
        return

    if file_action == "list":
        result = file_dispatch("list", filename=filename or ".", cwd=cwd)
        if result["success"]:
            cprint(f"\n[cyan]Files in:[/cyan] {result['path']}")
            if result["dirs"]:
                for d in result["dirs"]:
                    cprint(f"  [blue]📁 {d}/[/blue]")
            for f in result["files"]:
                size = f"{f['size'] // 1024}KB" if f['size'] > 1024 else f"{f['size']}B"
                cprint(f"  [cyan]{f['name']}[/cyan]  [dim]{size}[/dim]")
            cprint(f"\n[dim]{result['count']} files[/dim]")
        else:
            cprint(f"[red]✗ {result.get('error', 'Unknown error')}[/red]")


# ── New feature handlers ────────────────────────────────────────────────────

def handle_assistant(action: str, payload: dict = None):
    """Handle assistant actions: greet, time, date, datetime, joke, screenshot, note, wiki."""
    payload = payload or {}

    if action == "greet":
        msg = greet_user()
        cprint(f"\n[bold cyan]AIOS:[/bold cyan] {msg}\n")
        _tts_speak(msg)

    elif action == "time":
        msg = tell_time()
        cprint(f"\n[bold cyan]AIOS:[/bold cyan] {msg}\n")
        _tts_speak(msg)

    elif action == "date":
        msg = tell_date()
        cprint(f"\n[bold cyan]AIOS:[/bold cyan] {msg}\n")
        _tts_speak(msg)

    elif action == "datetime":
        msg = tell_datetime()
        cprint(f"\n[bold cyan]AIOS:[/bold cyan] {msg}\n")
        _tts_speak(msg)

    elif action == "joke":
        cprint("[dim]Thinking of a joke...[/dim]")
        joke = tell_joke()
        cprint(f"\n[bold cyan]AIOS:[/bold cyan] {joke}\n")
        _tts_speak(joke)

    elif action == "screenshot":
        fname = payload.get("filename")
        cprint(f"[dim]Taking screenshot{f' → {fname}' if fname else ''}...[/dim]")
        result = take_screenshot(fname)
        if result["success"]:
            cprint(f"[green]✓ Screenshot saved:[/green] {result['path']}\n")
        else:
            cprint(f"[red]✗ {result['message']}[/red]\n")

    elif action == "note":
        content = payload.get("content", "")
        if not content:
            cprint("[red]No note content provided.[/red]")
            return
        result = add_note(content)
        note = result["note"]
        cprint(
            f"\n[green]✓ Note saved[/green] [dim](#{note['id']} · {note['timestamp'][:16]})[/dim]\n"
            f"  {note['content']}\n"
        )

    elif action == "notes_list":
        notes = list_notes(n=10)
        if not notes:
            cprint("[yellow]No notes saved yet. Try: 'note: remember to fix the bug'[/yellow]")
            return
        if RICH:
            from rich.table import Table
            tbl = Table(title="Your Notes", show_lines=True)
            tbl.add_column("#",    style="dim",  width=4)
            tbl.add_column("Note", style="white")
            tbl.add_column("Tag",  style="cyan",  width=12)
            tbl.add_column("Saved", style="dim",  width=17)
            for n in notes:
                tbl.add_row(
                    str(n["id"]),
                    n["content"],
                    n.get("tag", ""),
                    n["timestamp"][:16],
                )
            console.print(tbl)
        else:
            for n in notes:
                print(f"  [{n['id']}] {n['content']}  ({n['timestamp'][:16]})")

    elif action == "process":
        handle_process_manager()

    elif action == "wiki":
        query = payload.get("query", "")
        if not query:
            return
        cprint(f"[dim]Looking up '{query}' on Wikipedia...[/dim]")
        result = wikipedia_summary(query)
        if result["success"]:
            if RICH:
                from rich.panel import Panel
                console.print(Panel(
                    f"[bold]{result['title']}[/bold]\n\n{result['summary']}\n\n"
                    f"[dim cyan]{result['url']}[/dim cyan]",
                    title="Wikipedia",
                    border_style="cyan",
                ))
            else:
                print(f"\n{result['title']}\n{result['summary']}\n{result['url']}\n")
        else:
            cprint(f"[red]✗ {result['summary']}[/red]\n")


def handle_file_search(query: str):
    """Semantic file search."""
    cprint(f"\n[cyan]🔍 Searching: '{query}'...[/cyan]")
    results = smart_search(query, max_results=8)

    if not results:
        cprint("[yellow]No files found.[/yellow]")
        return

    if RICH:
        table = Table(title=f"Results for '{query}'", show_lines=True)
        table.add_column("File", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Modified", style="green")
        table.add_column("Size")
        for f in results:
            size_str = f"{f['size'] // 1024}KB" if f.get('size', 0) > 1024 else f"{f.get('size', 0)}B"
            table.add_row(
                f["name"],
                f["parent"],
                f.get("modified", "")[:10],
                size_str
            )
        console.print(table)
    else:
        for i, f in enumerate(results, 1):
            print(f"  {i}. {f['name']}")
            print(f"     {f['path']}")

    # Ask to open
    try:
        choice = input("\nOpen a file? Enter number (or Enter to skip): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                open_file(results[idx]["path"])
                cprint(f"[green]Opened: {results[idx]['name']}[/green]")
    except (EOFError, KeyboardInterrupt):
        pass


def handle_process_manager():
    """Display process table."""
    stats = get_system_stats()
    procs = get_process_list(top_n=15)

    cprint(
        f"\n[cyan]System:[/cyan] CPU {stats['cpu_percent']}%  "
        f"RAM {stats['ram_used_gb']}/{stats['ram_total_gb']}GB ({stats['ram_percent']}%)  "
        f"Disk {stats['disk_free_gb']}GB free"
    )

    if RICH:
        table = Table(title="Top Processes", show_lines=False)
        table.add_column("PID", style="dim", width=8)
        table.add_column("Name", style="cyan", width=25)
        table.add_column("CPU%", justify="right", width=8)
        table.add_column("RAM MB", justify="right", width=10)
        table.add_column("Status", width=12)
        for p in procs:
            cpu_color = "red" if p["cpu_percent"] > 20 else "yellow" if p["cpu_percent"] > 5 else "green"
            ram_color = "red" if p["memory_mb"] > 500 else "yellow" if p["memory_mb"] > 200 else "white"
            table.add_row(
                str(p["pid"]),
                p["name"],
                f"[{cpu_color}]{p['cpu_percent']}[/{cpu_color}]",
                f"[{ram_color}]{p['memory_mb']}[/{ram_color}]",
                p["status"],
            )
        console.print(table)
    else:
        print(f"\n{'PID':>8}  {'NAME':<25}  {'CPU%':>6}  {'RAM MB':>8}  STATUS")
        for p in procs:
            print(f"{p['pid']:>8}  {p['name']:<25}  {p['cpu_percent']:>6}  {p['memory_mb']:>8}  {p['status']}")


def handle_workflows():
    """List available workflows."""
    engine = WorkflowEngine(progress_callback=cprint)
    workflows = engine.list_available()

    if RICH:
        table = Table(title="Available Workflows")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Steps", justify="center")
        table.add_column("Source", style="dim")
        for wf in workflows:
            table.add_row(wf["name"], wf.get("description", ""), str(wf["steps"]), wf["source"])
        console.print(table)
    else:
        for wf in workflows:
            print(f"  {wf['name']:<20} {wf.get('description', '')}")


def handle_memory_view():
    """Show context memory summary."""
    ctx = memory.get_context_summary()
    workflows = memory.list_workflows()

    if RICH:
        table = Table(title="AIOS Context Memory")
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        table.add_row("Session Start", ctx.get("session_start", "N/A")[:19])
        table.add_row("Interactions", str(ctx.get("interaction_count", 0)))
        table.add_row("Active Workflow", ctx.get("active_workflow") or "None")
        table.add_row("Recent Apps", ", ".join(ctx.get("recent_apps", [])) or "None")
        table.add_row("Recent Commands", "\n".join(ctx.get("recent_commands", [])[:3]) or "None")
        table.add_row("Saved Workflows", ", ".join(ctx.get("saved_workflows", [])) or "None")
        console.print(table)
    else:
        for k, v in ctx.items():
            print(f"  {k}: {v}")


# ── Intent router ────────────────────────────────────────────────────────────

def route_intent(user_input: str):
    """
    Parse user intent and route to the correct handler.
    Order:
      1. Code-based URL router (instant, no LLM) — handles play/search/open/etc.
      2. LLM parser — handles complex/ambiguous intents
    Records every interaction in RL memory for user-pattern adaptation.
    """
    ctx = memory.get_context_summary()
    memory.increment_interaction()
    rl.set_last_input(user_input, "unknown")   # will be updated with real intent below

    # ── Stage 1: Code-first URL router ───────────────────────────────────────
    router_result = url_route(user_input)
    if router_result.matched:
        cprint(f"[dim]Matched: {router_result.description}[/dim]\n")
        # Utility / assistant actions
        if router_result.assistant_action:
            action = router_result.assistant_action
            handle_assistant(action, {
                "filename": router_result.screenshot_filename,
                "content":  router_result.note_content,
                "query":    router_result.wiki_query,
            })
            rl.record_interaction(user_input, "assistant", action)
            rl.set_last_input(user_input, "assistant")
            return
        # File search (router caught it without LLM)
        if router_result.file_search_query is not None:
            q = router_result.file_search_query
            if q:
                handle_file_search(q)
            else:
                # empty query → show recent files
                files = recent_files(n=10)
                cprint("\n[cyan]Recent Files:[/cyan]")
                for i, f in enumerate(files, 1):
                    cprint(f"  {i:2}. [cyan]{f['name']}[/cyan]  [dim]{f['parent']}[/dim]  {f.get('modified','')[:10]}")
            rl.record_interaction(user_input, "file_search", q or "recent")
            rl.set_last_input(user_input, "file_search")
            return
        # File operation
        if router_result.file_action:
            handle_file_op(
                router_result.file_action,
                router_result.filename,
                router_result.content_desc or "",
                router_result.new_filename,
            )
            rl.record_interaction(user_input, "file_op", router_result.file_action)
            rl.set_last_input(user_input, "file_op")
            return
        # URL / app launch
        if router_result.urls and len(router_result.urls) > 1:
            _handle_multi_url(router_result.apps, router_result.urls)
        elif router_result.url:
            handle_launch_apps(router_result.apps or ["chrome"], url=router_result.url)
        elif router_result.apps:
            handle_launch_apps(router_result.apps)
        rl.record_interaction(user_input, "launch_apps", ",".join(router_result.apps or ["url"]))
        rl.set_last_input(user_input, "launch_apps")
        return

    # ── Pre-LLM: process-query keyword shortcut (no LLM needed) ────────────────
    _PROC_KEYWORDS = (
        "ram", "memory", "cpu", "process", "processes", "eating",
        "using", "hogging", "consuming", "running apps", "task",
        "what's using", "whats using", "what is using",
        "slow", "performance", "resource",
    )
    _lower_input = user_input.lower()
    if any(kw in _lower_input for kw in _PROC_KEYWORDS) and any(
        w in _lower_input for w in ("ram", "memory", "cpu", "process", "eating", "hogging", "consuming")
    ):
        cprint("[dim]Matched: process query (instant)[/dim]\n")
        handle_process_manager()
        rl.record_interaction(user_input, "process_management", "status")
        rl.set_last_input(user_input, "process_management")
        return

    # ── Stage 2: LLM intent parser ────────────────────────────────────────────
    cprint("[dim]Parsing intent...[/dim]")
    intent = parse_intent(user_input, context=ctx)

    intent_type = intent.get("intent_type", "conversation")
    apps = intent.get("apps", [])
    commands = intent.get("commands", [])
    workflow_name = intent.get("workflow_name")
    file_query = intent.get("file_query")
    process_action = intent.get("process_action")
    goal = intent.get("raw_goal", user_input)

    cprint(f"[dim]Intent: {intent_type} | Goal: {goal}[/dim]\n")
    rl.set_last_input(user_input, intent_type)

    # ── Route ────────────────────────────────────────────────────────────────
    # NOTE: specific intent types must be checked BEFORE the generic
    # `apps` catch-all so that file_search / file_op / shell intents are
    # never hijacked by a Chrome app hint from the LLM.

    if intent_type == "file_op":
        # Infer read vs update from query words when LLM doesn't specify
        _read_words = ("what", "show", "read", "view", "display", "print",
                       "see", "contents", "inside", "in the file")
        default_action = (
            "read" if any(w in user_input.lower() for w in _read_words)
            else "update"
        )
        file_action = intent.get("file_action") or default_action
        filename = intent.get("filename") or ""
        content_desc = intent.get("content_desc") or goal
        new_filename = intent.get("new_filename")
        if not filename:
            cprint("[red]✗ Could not determine filename from your request.[/red]")
        else:
            handle_file_op(file_action, filename, content_desc, new_filename)
        rl.record_interaction(user_input, "file_op", file_action)

    elif intent_type == "file_search" or file_query:
        handle_file_search(file_query or goal)
        rl.record_interaction(user_input, "file_search", file_query or goal)

    elif intent_type == "process_management" or process_action or (
        intent_type == "shell_command" and process_action in ("status", "optimize", "kill")
    ):
        if process_action in ("status", None):
            handle_process_manager()
        elif process_action == "optimize":
            cprint("\n[cyan]AI Process Analysis...[/cyan]")
            analysis = ai_optimize()
            cprint(f"\n{analysis}")
        rl.record_interaction(user_input, "process_management", process_action or "status")
        return  # skip duplicate block below

    elif intent_type == "shell_command" or commands:
        if commands:
            _run_commands(commands)
        else:
            shell = AIShell(progress_callback=cprint)
            result = shell.run(user_input)
            _display_shell_result(result)
        rl.record_interaction(user_input, "shell_command", goal[:40])

    elif intent_type == "workflow" or workflow_name:
        engine = WorkflowEngine(progress_callback=cprint)
        result = engine.run_by_name(workflow_name or goal)
        if not result:
            result = engine.run_from_goal(goal, context=ctx)
        rl.record_interaction(user_input, "workflow", workflow_name or goal)

    elif intent_type == "launch_apps" or apps:
        handle_launch_apps(apps)
        if commands:
            _run_commands(commands)
        rl.record_interaction(user_input, intent_type, ",".join(apps))

    else:
        cprint("[dim]Thinking...[/dim]")
        response = chat_response(user_input, context=ctx)
        cprint(f"\n[bold]AIOS:[/bold] {response}\n")
        _tts_speak(response)
        rl.record_interaction(user_input, "conversation", "chat")


def _run_commands(commands: list):
    """Execute a list of shell commands and display output."""
    import subprocess
    for cmd in commands:
        cprint(f"\n[cyan]$ {cmd}[/cyan]")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            if result.stdout:
                cprint(result.stdout.strip())
            if result.stderr:
                cprint(f"[red]{result.stderr.strip()}[/red]")
            memory.log_command(cmd, result.stdout[:100])
        except Exception as e:
            cprint(f"[red]Error: {e}[/red]")


def _display_shell_result(result: dict):
    if result.get("blocked"):
        cprint(f"\n[red]⚠ BLOCKED:[/red] {result['reason']}")
        return
    for r in result.get("results", []):
        if r.get("stdout"):
            cprint(r["stdout"])
        if r.get("stderr"):
            cprint(f"[red]{r['stderr']}[/red]")


# ── Main REPL ────────────────────────────────────────────────────────────────

def _start_voice_wake_listener() -> None:
    """Start background wake-word listener and route detected speech through AIOS."""
    if voice.start_wake_listener(callback=route_intent):
        wake = cfg.get("voice", "wake_word", "jarvis").capitalize()
        cprint(f"[green]🎙 Voice wake-word active — say '{wake}' to trigger AIOS[/green]")
        log.info("Wake-word listener started")
    else:
        cprint("[yellow]⚠ Voice wake-word unavailable — microphone or SpeechRecognition missing[/yellow]")


def main():
    global _VOICE_MODE
    print_banner()
    memory.start_session()

    # ── Startup: Ollama health check ─────────────────────────────────────────
    ollama_ok = check_ollama_health(silent=True)
    if ollama_ok:
        model = cfg.get("llm", "model", "llama3.2:3b")
        cprint(f"[green]✓ Ollama connected[/green] [dim]({model})[/dim]")
        log.info("Ollama health check passed")
    else:
        cprint("[yellow]⚠  Ollama not running — AI features disabled until you run:[/yellow] [bold]ollama serve[/bold]")
        log.warning("Ollama not running at startup")

    # ── Startup: voice wake listener ─────────────────────────────────────────
    if _VOICE_MODE:
        _start_voice_wake_listener()

    # ── Startup: background daemons ──────────────────────────────────────────
    global _daemons
    try:
        _daemons = _start_all_daemons(notify=cprint)
        log.info("Background daemons started: %s", list(_daemons.keys()))
    except Exception as _de:
        log.warning("Daemons failed to start: %s", _de)

    cprint("[dim]Type /help for commands, or just speak naturally.[/dim]\n")

    shell = AIShell(progress_callback=cprint)
    workflow_engine = WorkflowEngine(progress_callback=cprint)

    while True:
        try:
            prompt_suffix = " [dim][🎙][/dim]" if _VOICE_MODE else ""
            if RICH:
                user_input = Prompt.ask(f"[bold cyan]AIOS[/bold cyan]{prompt_suffix}").strip()
            else:
                user_input = input("AIOS> ").strip()
        except (EOFError, KeyboardInterrupt):
            cprint("\n[yellow]Exiting AIOS. Goodbye.[/yellow]")
            voice.stop_wake_listener()
            memory.end_session()
            sys.exit(0)

        if not user_input:
            continue

        # ── Special slash commands ───────────────────────────────────────────
        lower = user_input.lower()

        if lower in ("/exit", "/quit", "exit", "quit", "bye"):
            cprint("[yellow]Goodbye![/yellow]")
            _tts_speak("Goodbye!")
            voice.stop_wake_listener()
            memory.end_session()
            break

        elif lower == "/help":
            print_help()

        elif lower == "/voice":
            _VOICE_MODE = not _VOICE_MODE
            cfg.save_user_config({"voice": {"enabled": _VOICE_MODE}})
            if _VOICE_MODE:
                cprint("[green]🎙 Voice mode ON[/green]")
                _start_voice_wake_listener()
            else:
                cprint("[yellow]🔇 Voice mode OFF[/yellow]")
                voice.stop_wake_listener()

        elif lower.startswith("/correct"):
            # RL: user tells AIOS the last command was wrong
            # Usage: /correct <what it should have done>
            correction_text = user_input[8:].strip()
            last_input  = rl.last_input()
            last_intent = rl.get_last_intent() or "unknown"
            if not last_input:
                cprint("[yellow]No previous command to correct.[/yellow]")
            elif not correction_text:
                cprint("[yellow]Usage: /correct <what AIOS should have done>[/yellow]")
                cprint(f"[dim]Last command: '{last_input}'  (was routed as: {last_intent})[/dim]")
            else:
                rl.record_correction(
                    original_input=last_input,
                    wrong_intent=last_intent,
                    correct_intent=correction_text,
                    correct_action=correction_text,
                )
                cprint(f"[green]✓ Correction saved.[/green] AIOS will learn from this.")
                cprint(f"[dim]Next time you say '{last_input}', it will route to: {correction_text}[/dim]")

        elif lower == "/rl":
            stats = rl.stats()
            profile = rl.get_profile()
            if RICH:
                tbl = Table(title="AIOS Learning Memory (RL)", show_lines=True)
                tbl.add_column("Metric", style="cyan")
                tbl.add_column("Value")
                tbl.add_row("Enabled",            str(stats['enabled']))
                tbl.add_row("Total interactions", str(stats['total_interactions']))
                tbl.add_row("Unique intents",     str(stats['unique_intents']))
                tbl.add_row("Stored corrections", str(stats['corrections']))
                tbl.add_row("Has user profile",   "Yes" if stats['has_profile'] else "No")
                console.print(tbl)
                if profile:
                    console.print(Panel(profile, title="User Profile", border_style="dim"))
            else:
                for k, v in stats.items():
                    print(f"  {k}: {v}")
                if profile:
                    print(f"\nUser Profile:\n{profile}")

        elif lower == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            print_banner()

        elif lower == "/shell":
            shell.interactive_session()

        elif lower == "/workflows":
            handle_workflows()

        elif lower.startswith("/run "):
            wf_name = user_input[5:].strip()
            result = workflow_engine.run_by_name(wf_name)
            if not result:
                cprint(f"[red]Workflow '{wf_name}' not found. Try /workflows to list available.[/red]")

        elif lower == "/ps":
            handle_process_manager()

        elif lower == "/optimize":
            cprint("\n[cyan]Running AI Process Analysis...[/cyan]")
            analysis = ai_optimize()
            cprint(f"\n{analysis}\n")

        elif lower.startswith("/files "):
            query = user_input[7:].strip()
            handle_file_search(query)

        elif lower == "/recent":
            files = recent_files(n=10)
            cprint("\n[cyan]Recent Files:[/cyan]")
            for i, f in enumerate(files, 1):
                cprint(f"  {i:2}. [cyan]{f['name']}[/cyan]  [dim]{f['parent']}[/dim]  {f.get('modified','')[:10]}")

        elif lower == "/notes":
            handle_assistant("notes_list")

        elif lower.startswith("/note "):
            handle_assistant("note", {"content": user_input[6:].strip()})

        elif lower == "/screenshot" or lower.startswith("/screenshot "):
            fname = user_input[12:].strip() if len(lower) > 12 else None
            handle_assistant("screenshot", {"filename": fname or None})

        elif lower == "/time":
            cprint(f"\n[bold cyan]AIOS:[/bold cyan] {tell_time()}\n")

        elif lower == "/date":
            cprint(f"\n[bold cyan]AIOS:[/bold cyan] {tell_date()}\n")

        elif lower == "/joke":
            handle_assistant("joke")

        elif lower == "/daemons":
            if not _daemons:
                cprint("[yellow]No daemons running.[/yellow]")
            elif RICH:
                tbl = Table(title="AIOS Background Daemons", show_lines=True)
                tbl.add_column("Daemon", style="cyan")
                tbl.add_column("Status")
                tbl.add_column("Details", style="dim")
                for name, d in _daemons.items():
                    alive = d.is_alive()
                    color = "green" if alive else "red"
                    label = "running" if alive else "stopped"
                    try:
                        info = d.status()
                        detail = "  ".join(f"{k}={v}" for k, v in info.items() if k != "running")
                    except Exception:
                        detail = ""
                    tbl.add_row(name, f"[{color}]{label}[/{color}]", detail)
                console.print(tbl)
            else:
                for name, d in _daemons.items():
                    print(f"  {name}: {'alive' if d.is_alive() else 'stopped'}")

        elif lower == "/memory":
            handle_memory_view()

        elif lower == "/context":
            ctx = memory.get_context_summary()
            import json
            cprint(json.dumps(ctx, indent=2))

        elif lower.startswith("/kill "):
            pid_str = user_input[6:].strip()
            if pid_str.isdigit():
                result = kill_process(int(pid_str))
                color = "green" if result["success"] else "red"
                cprint(f"[{color}]{result.get('message', result.get('reason', ''))}[/{color}]")
            else:
                # Find by name
                procs = find_process(pid_str)
                if not procs:
                    cprint(f"[red]No process found matching '{pid_str}'[/red]")
                else:
                    for p in procs[:5]:
                        cprint(f"  PID {p['pid']}: {p['name']} ({p['memory_mb']}MB)")
                    try:
                        pid_input = input("Enter PID to kill (or Enter to cancel): ").strip()
                        if pid_input.isdigit():
                            result = kill_process(int(pid_input), pid_str)
                            cprint(result.get("message", result.get("reason", "")))
                    except (EOFError, KeyboardInterrupt):
                        pass

        else:
            # Natural language — route through AI intent engine
            try:
                route_intent(user_input)
            except Exception as e:
                cprint(f"[red]Error: {e}[/red]")


if __name__ == "__main__":
    main()
