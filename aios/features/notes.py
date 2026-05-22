"""
Notes module — take, list, and manage quick notes.
Notes are stored as JSON in ~/.aios/notes.json.
Cross-platform.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def _notes_file() -> Path:
    path = Path.home() / ".aios" / "notes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> list:
    path = _notes_file()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(notes: list) -> None:
    _notes_file().write_text(
        json.dumps(notes, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Public API ───────────────────────────────────────────────────────────────

def add_note(content: str, tag: str = "general") -> dict:
    """
    Save a note.
    Returns the saved note dict.
    """
    notes = _load()
    note = {
        "id": (notes[-1]["id"] + 1) if notes else 1,
        "content": content.strip(),
        "tag": tag.lower().strip(),
        "timestamp": datetime.now().isoformat(),
    }
    notes.append(note)
    _save(notes)
    return {"success": True, "note": note, "total": len(notes)}


def list_notes(n: int = 10, tag: Optional[str] = None) -> list:
    """Return the n most recent notes (optionally filtered by tag)."""
    notes = _load()
    if tag:
        notes = [x for x in notes if x.get("tag") == tag.lower()]
    return list(reversed(notes[-n:]))  # most recent first


def delete_note(note_id: int) -> bool:
    notes = _load()
    new = [x for x in notes if x.get("id") != note_id]
    if len(new) == len(notes):
        return False  # not found
    _save(new)
    return True


def clear_notes() -> int:
    notes = _load()
    _save([])
    return len(notes)


def notes_file_path() -> str:
    """Return the absolute path to the notes JSON file."""
    return str(_notes_file())
