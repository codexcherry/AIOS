"""
Context Memory — AIOS persistent session and workflow memory.
Stores: session history, named workflows, file access patterns, app usage.
Uses JSON for simplicity (no external DB needed for POC).
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from aios.logger import log

MEMORY_DIR = Path.home() / ".aios" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = MEMORY_DIR / "sessions.json"
WORKFLOWS_FILE = MEMORY_DIR / "workflows.json"
FILE_INDEX_FILE = MEMORY_DIR / "file_index.json"
CONTEXT_FILE = MEMORY_DIR / "context.json"


_write_lock = threading.Lock()


def _load_json(path: Path, default=None):
    if default is None:
        default = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            log.warning("context_memory: corrupt JSON in %s (%s) — starting fresh", path.name, exc)
            return default
        except Exception as exc:
            log.warning("context_memory: could not load %s: %s", path.name, exc)
            return default
    return default


def _save_json(path: Path, data) -> None:
    """Atomic write: write to .tmp then rename — prevents partial-write corruption."""
    tmp = path.with_suffix(".tmp")
    with _write_lock:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            tmp.replace(path)
        except Exception as exc:
            log.error("context_memory: failed to save %s: %s", path.name, exc)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


class ContextMemory:
    """
    AIOS Context Memory Engine.
    Maintains session state, named workflows, and interaction history.
    """

    def __init__(self):
        self._sessions = _load_json(SESSION_FILE, {"sessions": [], "current": {}})
        self._workflows = _load_json(WORKFLOWS_FILE, {"workflows": {}})
        self._file_index = _load_json(FILE_INDEX_FILE, {"files": []})
        self._context = _load_json(CONTEXT_FILE, {
            "active_workflow": None,
            "last_apps": [],
            "last_commands": [],
            "session_start": datetime.now().isoformat(),
            "interaction_count": 0,
        })

    # ── Session Management ──────────────────────────────────────────────────

    def start_session(self, name: str = None):
        """Record new session start."""
        session = {
            "id": f"sess_{int(time.time())}",
            "name": name or f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "started": datetime.now().isoformat(),
            "ended": None,
            "apps_opened": [],
            "commands_run": [],
            "workflows_used": [],
        }
        self._sessions["current"] = session
        self._sessions["sessions"].append(session)
        _save_json(SESSION_FILE, self._sessions)
        return session

    def end_session(self):
        """Mark current session as ended."""
        if self._sessions.get("current"):
            self._sessions["current"]["ended"] = datetime.now().isoformat()
            # Update in list
            for i, s in enumerate(self._sessions["sessions"]):
                if s["id"] == self._sessions["current"]["id"]:
                    self._sessions["sessions"][i] = self._sessions["current"]
                    break
            _save_json(SESSION_FILE, self._sessions)

    def log_app_opened(self, app_name: str):
        """Record app was opened."""
        ts = datetime.now().isoformat()
        # Update context
        apps = self._context.get("last_apps", [])
        apps = [a for a in apps if a["name"] != app_name]  # deduplicate
        apps.insert(0, {"name": app_name, "time": ts})
        self._context["last_apps"] = apps[:20]  # keep last 20

        # Update session
        if self._sessions.get("current"):
            self._sessions["current"].setdefault("apps_opened", []).append(
                {"name": app_name, "time": ts}
            )
        self._save_context()

    def log_command(self, command: str, result: str = ""):
        """Record a command was executed."""
        ts = datetime.now().isoformat()
        cmds = self._context.get("last_commands", [])
        cmds.insert(0, {"cmd": command, "time": ts, "result": result[:100]})
        self._context["last_commands"] = cmds[:50]
        if self._sessions.get("current"):
            self._sessions["current"].setdefault("commands_run", []).append(
                {"cmd": command, "time": ts}
            )
        self._save_context()

    def increment_interaction(self):
        self._context["interaction_count"] = self._context.get("interaction_count", 0) + 1
        self._save_context()

    # ── Workflow Memory ─────────────────────────────────────────────────────

    def save_workflow(self, name: str, workflow: dict):
        """Persist a named workflow."""
        self._workflows["workflows"][name.lower()] = {
            **workflow,
            "saved": datetime.now().isoformat(),
            "run_count": self._workflows["workflows"].get(name.lower(), {}).get("run_count", 0)
        }
        _save_json(WORKFLOWS_FILE, self._workflows)

    def get_workflow(self, name: str) -> Optional[dict]:
        """Retrieve a saved workflow by name."""
        return self._workflows["workflows"].get(name.lower())

    def increment_workflow_run(self, name: str):
        wf = self._workflows["workflows"].get(name.lower())
        if wf:
            wf["run_count"] = wf.get("run_count", 0) + 1
            wf["last_run"] = datetime.now().isoformat()
            _save_json(WORKFLOWS_FILE, self._workflows)

    def list_workflows(self) -> list:
        """List all saved workflows."""
        return [
            {"name": k, **{kk: vv for kk, vv in v.items() if kk != "steps"}}
            for k, v in self._workflows["workflows"].items()
        ]

    def set_active_workflow(self, name: Optional[str]):
        self._context["active_workflow"] = name
        self._save_context()

    # ── File Index ──────────────────────────────────────────────────────────

    def index_file(self, path: str, tags: list = None, description: str = ""):
        """Add a file to the semantic index."""
        files = self._file_index.get("files", [])
        # Remove existing entry for same path
        files = [f for f in files if f["path"] != path]
        files.insert(0, {
            "path": path,
            "name": os.path.basename(path),
            "tags": tags or [],
            "description": description,
            "indexed": datetime.now().isoformat(),
            "size": os.path.getsize(path) if os.path.exists(path) else 0,
            "modified": datetime.fromtimestamp(
                os.path.getmtime(path)
            ).isoformat() if os.path.exists(path) else "",
        })
        self._file_index["files"] = files[:500]  # limit
        _save_json(FILE_INDEX_FILE, self._file_index)

    def search_files(self, query: str) -> list:
        """Return all indexed files for semantic ranking."""
        return self._file_index.get("files", [])

    # ── Context Summary ─────────────────────────────────────────────────────

    def get_context_summary(self) -> dict:
        """Return a summary of current context for LLM consumption."""
        return {
            "session_start": self._context.get("session_start"),
            "interaction_count": self._context.get("interaction_count", 0),
            "active_workflow": self._context.get("active_workflow"),
            "recent_apps": [a["name"] for a in self._context.get("last_apps", [])[:5]],
            "recent_commands": [c["cmd"] for c in self._context.get("last_commands", [])[:5]],
            "saved_workflows": list(self._workflows["workflows"].keys()),
        }

    def get_full_context(self) -> dict:
        return self._context

    def _save_context(self):
        _save_json(CONTEXT_FILE, self._context)

    def clear_session_context(self):
        """Reset transient context."""
        self._context["last_apps"] = []
        self._context["last_commands"] = []
        self._context["active_workflow"] = None
        self._context["interaction_count"] = 0
        self._save_context()


# Singleton instance
memory = ContextMemory()
