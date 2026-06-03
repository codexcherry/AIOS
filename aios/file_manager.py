"""
Smart File Manager — Semantic file search using LLM ranking.
"Find my last healthcare presentation" → returns relevant files.
Combines filesystem indexing with AI semantic matching.
"""
import os
import re
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from aios.context_memory import memory
from aios.llm_engine import semantic_file_match, extract_search_keywords
from aios.logger import log

# Default search roots — only include paths that actually exist
DEFAULT_SEARCH_ROOTS = [
    p for p in [
        Path.home() / "Documents",
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "Projects",
        Path.home(),
        Path(os.environ.get("USERPROFILE", str(Path.home()))),
    ]
    if p.exists()
]

# Add current working directory if not already present
_cwd = Path.cwd()
if _cwd not in DEFAULT_SEARCH_ROOTS:
    DEFAULT_SEARCH_ROOTS.append(_cwd)

# Extensions to include in semantic search
INDEXABLE_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".docx", ".doc", ".xlsx", ".xls",
    ".pptx", ".ppt", ".py", ".js", ".ts", ".html", ".css",
    ".json", ".yaml", ".yml", ".csv", ".ipynb", ".zip",
    ".png", ".jpg", ".jpeg", ".mp4", ".mp3"
}

# Map user-facing type words → file extensions (for type filtering)
_TYPE_MAP: dict[str, set] = {
    "pdf":          {".pdf"},
    "doc":          {".doc", ".docx"},
    "word":         {".doc", ".docx"},
    "excel":        {".xls", ".xlsx"},
    "spreadsheet":  {".xls", ".xlsx", ".csv"},
    "ppt":          {".ppt", ".pptx"},
    "powerpoint":   {".ppt", ".pptx"},
    "presentation": {".ppt", ".pptx"},
    "csv":          {".csv"},
    "image":        {".png", ".jpg", ".jpeg"},
    "photo":        {".png", ".jpg", ".jpeg"},
    "video":        {".mp4"},
    "notebook":     {".ipynb"},
    "python":       {".py"},
    "text":         {".txt", ".md"},
    "markdown":     {".md"},
    "json":         {".json"},
    "zip":          {".zip"},
}

_TYPE_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in _TYPE_MAP) + r')s?\b',
    re.IGNORECASE,
)

# Extensions too noisy to include
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".cache", "AppData", "temp", "tmp", "Temp"
}


def _detect_type_filter(query: str) -> Optional[set]:
    """Extract file-type constraints from natural-language query. Returns set of extensions or None."""
    matches = _TYPE_PATTERN.findall(query)
    if not matches:
        return None
    exts: set = set()
    for m in matches:
        exts |= _TYPE_MAP.get(m.lower(), set())
    return exts or None


def _scan_directory(root: Path, max_files: int = 2000, ext_filter: Optional[set] = None) -> list:
    """Scan directory recursively for indexable files, optionally filtered by extension."""
    allowed = ext_filter if ext_filter else INDEXABLE_EXTENSIONS
    files = []
    try:
        for entry in root.rglob("*"):
            if len(files) >= max_files:
                break
            # Skip noisy dirs
            if any(skip in entry.parts for skip in SKIP_DIRS):
                continue
            if entry.is_file() and entry.suffix.lower() in allowed:
                try:
                    stat = entry.stat()
                    files.append({
                        "path": str(entry),
                        "name": entry.name,
                        "stem": entry.stem,
                        "suffix": entry.suffix.lower(),
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "parent": str(entry.parent),
                    })
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass
    return files


def _keyword_filter(files: list, keywords: list) -> list:
    """Fast keyword pre-filter before LLM ranking. Accepts a list of keyword strings."""
    scored = []
    for f in files:
        name_lower = f.get("name", "").lower().replace("_", " ").replace("-", " ")
        path_lower  = f.get("path", "").lower()
        stem_lower  = f.get("stem", f.get("name", "").rsplit(".", 1)[0]).lower()

        score = 0
        for word in keywords:
            if word in stem_lower:
                score += 5   # Strong: keyword in stem (filename without extension)
            elif word in name_lower:
                score += 3   # Good: keyword in full filename
            if word in path_lower:
                score += 1   # Weak: keyword anywhere in path
        scored.append((score, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [f for _, f in scored if _ > 0]
    if not top:
        # No keyword matches — return recently modified files
        top = sorted(files, key=lambda x: x.get("modified", ""), reverse=True)[:50]
    return top[:100]


def smart_search(query: str, max_results: int = 10, roots: list = None) -> list:
    """
    Semantic file search — 3-stage pipeline:
    1. LLM extracts semantic keywords + detect file-type filter (runs in parallel with scan)
    2. Parallel filesystem scan across all roots (ThreadPoolExecutor)
    3. Keyword pre-filter → LLM semantic ranking
    Returns list of file dicts sorted by relevance.
    """
    search_roots = [Path(r) for r in (roots or DEFAULT_SEARCH_ROOTS)]

    # Detect file-type filter from query (instant, no LLM)
    ext_filter = _detect_type_filter(query)

    # Run LLM keyword extraction + filesystem scans in parallel
    all_files: list = []
    keywords: list = []

    with ThreadPoolExecutor(max_workers=min(len(search_roots) + 1, 8)) as ex:
        # Submit LLM keyword extraction as a task
        kw_future = ex.submit(extract_search_keywords, query)

        # Submit one scan per root directory
        scan_futures = {
            ex.submit(_scan_directory, root, 2000, ext_filter): root
            for root in search_roots if root.exists()
        }

        # Collect scan results as they complete
        for fut in as_completed(scan_futures):
            root = scan_futures[fut]
            try:
                all_files.extend(fut.result())
            except Exception as exc:
                log.warning("file_manager: scan failed for %s: %s", root, exc)

        # Get LLM keywords (may already be done by now)
        try:
            keywords = kw_future.result(timeout=10)
        except Exception as exc:
            log.warning("file_manager: keyword extraction failed: %s", exc)
            keywords = []

    # Include keywords from the raw query as fallback
    _SKIP = {"find", "my", "related", "files", "file", "the", "a", "an", "some",
              "show", "search", "get", "all", "any", "last", "recent", "latest", "pdfs", "docs"}
    raw_keywords = [w for w in query.lower().split() if w not in _SKIP and len(w) > 2]
    combined_keywords = list(dict.fromkeys(keywords + raw_keywords))  # deduplicate, preserve order

    # Also add memory-indexed files.
    # Normalise each entry so they have the same keys as scanned files.
    indexed_raw = memory.search_files(query)
    indexed = []
    for entry in indexed_raw:
        p = Path(entry.get("path", ""))
        indexed.append({
            "path":     entry.get("path", ""),
            "name":     entry.get("name", p.name),
            "stem":     entry.get("stem", p.stem),
            "suffix":   entry.get("suffix", p.suffix.lower()),
            "size":     entry.get("size", 0),
            "modified": entry.get("modified", ""),
            "parent":   entry.get("parent", str(p.parent)),
        })
    all_files = indexed + all_files

    # Deduplicate by path
    seen: set = set()
    unique_files: list = []
    for f in all_files:
        p = f.get("path", "")
        if p not in seen:
            seen.add(p)
            unique_files.append(f)

    if not unique_files:
        return []

    # Keyword pre-filter
    candidates = _keyword_filter(unique_files, combined_keywords)

    if not candidates:
        return []

    # LLM semantic ranking (use file names/paths for ranking)
    file_descriptions = [
        f"{f.get('name', '')} | {f.get('parent', '')} | modified: {f.get('modified', 'unknown')[:10]}"
        for f in candidates
    ]

    if len(candidates) <= 5:
        return candidates[:max_results]

    ranked_indices = semantic_file_match(query, file_descriptions)

    results: list = []
    seen_indices: set = set()
    for idx in ranked_indices:
        if isinstance(idx, int) and 0 <= idx < len(candidates) and idx not in seen_indices:
            results.append(candidates[idx])
            seen_indices.add(idx)

    # Add unranked top keyword matches
    for i, f in enumerate(candidates):
        if i not in seen_indices and len(results) < max_results:
            results.append(f)
    return results[:max_results]


def index_path(path: str):
    """Manually add a path to the memory index."""
    if os.path.exists(path):
        memory.index_file(path)
        return True
    return False


def recent_files(n: int = 10, extension: str = None) -> list:
    """Get recently modified files."""
    all_files = []
    for root in DEFAULT_SEARCH_ROOTS:
        root = Path(root)
        if root.exists():
            all_files.extend(_scan_directory(root, max_files=500))
    
    if extension:
        all_files = [f for f in all_files if f["suffix"] == extension.lower()]
    
    all_files.sort(key=lambda x: x.get("modified", ""), reverse=True)
    return all_files[:n]


def open_file(path: str) -> bool:
    """Open a file with its default application."""
    import subprocess
    try:
        os.startfile(path)
        memory.index_file(path)
        return True
    except Exception:
        try:
            subprocess.Popen(["explorer", path])
            return True
        except Exception:
            return False
