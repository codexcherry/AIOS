"""
File Operations — Natural language file CRUD.
Handles: create, read, write, update, append, delete, rename, list.
Uses LLM to generate/modify file content intelligently.
"""
import os
import re
from pathlib import Path
from typing import Optional, Tuple

from aios.llm_engine import generate_file_content
from aios.context_memory import memory


def _resolve_path(filename: str) -> Path:
    """
    Resolve filename to absolute path.
    If already absolute, use as-is.
    Otherwise, resolve relative to cwd.
    """
    p = Path(filename)
    if p.is_absolute():
        return p
    return Path.cwd() / p


def _confirm(prompt: str) -> bool:
    """Ask user for yes/no confirmation."""
    try:
        ans = input(f"{prompt} [y/N]: ").strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


# ── CREATE ────────────────────────────────────────────────────────────────────

def create_file(filename: str, description: str = "", content: str = None,
                overwrite: bool = False, cwd: str = None) -> dict:
    """
    Create a new file.
    - If content is provided, write it directly.
    - If description is provided, generate content via LLM.
    - If neither, create empty file.
    """
    if cwd:
        path = Path(cwd) / filename if not Path(filename).is_absolute() else Path(filename)
    else:
        path = _resolve_path(filename)

    # Check existence
    if path.exists() and not overwrite:
        return {
            "success": False,
            "action": "create",
            "path": str(path),
            "error": f"File already exists: {path.name}. Use update to modify it.",
            "exists": True,
        }

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Generate or use provided content
    if content is not None:
        final_content = content
    elif description:
        final_content = generate_file_content(description, filename)
    else:
        final_content = ""

    # Write file
    path.write_text(final_content, encoding="utf-8")
    memory.index_file(str(path), description=description)
    memory.log_command(f"create {filename}", f"{len(final_content)} chars written")

    return {
        "success": True,
        "action": "create",
        "path": str(path),
        "filename": path.name,
        "lines": final_content.count("\n") + 1 if final_content else 0,
        "size": len(final_content),
        "content": final_content,
    }


# ── READ ──────────────────────────────────────────────────────────────────────

def read_file(filename: str, cwd: str = None) -> dict:
    """Read and return file content."""
    if cwd:
        path = Path(cwd) / filename if not Path(filename).is_absolute() else Path(filename)
    else:
        path = _resolve_path(filename)

    # Try cwd and common locations if not found
    if not path.exists():
        for search_root in [Path.cwd(), Path.home() / "Documents", Path.home() / "Desktop"]:
            candidate = search_root / filename
            if candidate.exists():
                path = candidate
                break

    if not path.exists():
        return {"success": False, "action": "read", "path": str(path),
                "error": f"File not found: {filename}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        memory.log_command(f"read {filename}", "ok")
        return {
            "success": True,
            "action": "read",
            "path": str(path),
            "filename": path.name,
            "content": content,
            "lines": content.count("\n") + 1,
            "size": len(content),
        }
    except Exception as e:
        return {"success": False, "action": "read", "path": str(path), "error": str(e)}


# ── UPDATE ────────────────────────────────────────────────────────────────────

def update_file(filename: str, instruction: str, cwd: str = None) -> dict:
    """
    Update existing file content using LLM.
    LLM receives existing content + instruction → generates new content.
    """
    if cwd:
        path = Path(cwd) / filename if not Path(filename).is_absolute() else Path(filename)
    else:
        path = _resolve_path(filename)

    if not path.exists():
        # File doesn't exist — offer to create
        return {
            "success": False,
            "action": "update",
            "path": str(path),
            "error": f"File not found: {filename}. Did you mean to create it?",
            "suggest_create": True,
        }

    existing = path.read_text(encoding="utf-8", errors="replace")
    updated = generate_file_content(instruction, filename, existing_content=existing)

    path.write_text(updated, encoding="utf-8")
    memory.log_command(f"update {filename}", instruction[:60])

    return {
        "success": True,
        "action": "update",
        "path": str(path),
        "filename": path.name,
        "content": updated,
        "lines": updated.count("\n") + 1,
    }


# ── APPEND ────────────────────────────────────────────────────────────────────

def append_file(filename: str, description: str, cwd: str = None) -> dict:
    """Append new content to end of file."""
    if cwd:
        path = Path(cwd) / filename if not Path(filename).is_absolute() else Path(filename)
    else:
        path = _resolve_path(filename)

    if not path.exists():
        return create_file(filename, description, cwd=cwd)

    existing = path.read_text(encoding="utf-8", errors="replace")
    new_content = generate_file_content(f"Generate ONLY the new code/text to append: {description}", filename)

    with path.open("a", encoding="utf-8") as f:
        f.write("\n" + new_content)

    memory.log_command(f"append {filename}", description[:60])

    return {
        "success": True,
        "action": "append",
        "path": str(path),
        "filename": path.name,
        "appended": new_content,
    }


# ── DELETE ────────────────────────────────────────────────────────────────────

def delete_file(filename: str, confirmed: bool = False, cwd: str = None) -> dict:
    """Delete a file. Requires confirmation unless confirmed=True."""
    if cwd:
        path = Path(cwd) / filename if not Path(filename).is_absolute() else Path(filename)
    else:
        path = _resolve_path(filename)

    if not path.exists():
        return {"success": False, "action": "delete", "path": str(path),
                "error": f"File not found: {filename}"}

    if not confirmed:
        return {
            "success": False,
            "action": "delete",
            "path": str(path),
            "needs_confirmation": True,
            "message": f"Confirm delete: {path.name} ({path.stat().st_size} bytes)?",
        }

    path.unlink()
    memory.log_command(f"delete {filename}", "deleted")
    return {"success": True, "action": "delete", "path": str(path), "filename": path.name}


# ── RENAME ────────────────────────────────────────────────────────────────────

def rename_file(filename: str, new_filename: str, cwd: str = None) -> dict:
    """Rename a file."""
    if cwd:
        path = Path(cwd) / filename if not Path(filename).is_absolute() else Path(filename)
    else:
        path = _resolve_path(filename)

    if not path.exists():
        return {"success": False, "action": "rename", "path": str(path),
                "error": f"File not found: {filename}"}

    new_path = path.parent / new_filename
    path.rename(new_path)
    memory.log_command(f"rename {filename} → {new_filename}", "ok")
    return {"success": True, "action": "rename", "old_path": str(path),
            "new_path": str(new_path), "filename": new_filename}


# ── LIST ──────────────────────────────────────────────────────────────────────

def list_directory(path: str = ".", pattern: str = "*") -> dict:
    """List files in a directory."""
    dir_path = Path(path) if path != "." else Path.cwd()
    if not dir_path.exists():
        return {"success": False, "error": f"Directory not found: {path}"}

    files = []
    dirs = []
    for item in sorted(dir_path.iterdir()):
        if item.is_file() and item.match(pattern):
            files.append({
                "name": item.name,
                "size": item.stat().st_size,
                "modified": item.stat().st_mtime,
            })
        elif item.is_dir() and not item.name.startswith("."):
            dirs.append(item.name)

    return {
        "success": True,
        "path": str(dir_path),
        "files": files,
        "dirs": dirs,
        "count": len(files),
    }


# ── DISPATCHER ────────────────────────────────────────────────────────────────

def dispatch(action: str, filename: str = None, description: str = None,
             new_filename: str = None, cwd: str = None) -> dict:
    """
    Single dispatch function for all file operations.
    Called from main.py handler.
    """
    action = action.lower().strip()

    if action == "create":
        return create_file(filename, description or "", cwd=cwd)

    elif action == "read" or action == "show" or action == "display" or action == "open":
        return read_file(filename, cwd=cwd)

    elif action == "update" or action == "modify" or action == "edit" or action == "write":
        if not filename:
            return {"success": False, "error": "No filename specified"}
        # If file doesn't exist, create it
        path = Path(cwd or "") / filename if cwd else _resolve_path(filename)
        if not path.exists() and description:
            return create_file(filename, description, cwd=cwd)
        return update_file(filename, description or "", cwd=cwd)

    elif action == "append" or action == "add":
        return append_file(filename, description or "", cwd=cwd)

    elif action == "delete" or action == "remove" or action == "erase":
        result = delete_file(filename, confirmed=False, cwd=cwd)
        if result.get("needs_confirmation"):
            if _confirm(result["message"]):
                return delete_file(filename, confirmed=True, cwd=cwd)
            return {"success": False, "action": "delete", "message": "Cancelled."}
        return result

    elif action == "rename":
        if not new_filename:
            return {"success": False, "error": "New filename not specified"}
        return rename_file(filename, new_filename, cwd=cwd)

    elif action == "list":
        return list_directory(filename or ".", cwd or ".")

    return {"success": False, "error": f"Unknown action: {action}"}
