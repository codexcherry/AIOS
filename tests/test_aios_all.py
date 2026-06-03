"""
AIOS Comprehensive Test Suite
==============================
Single file — tests every major subsystem.
Run:  python -m pytest tests/test_aios_all.py -v
  or: python tests/test_aios_all.py          (standalone, no pytest needed)

Each section maps to one module/component.
Tests are self-contained — they do NOT require Ollama to be running
(LLM calls are mocked where needed).
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Add project root to sys.path so 'aios' is importable ────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ── Minimal test runner (no pytest dependency) ────────────────────────────────

_PASS  = []
_FAIL  = []
_ERROR = []

def _run(name: str, fn):
    try:
        fn()
        _PASS.append(name)
        print(f"  [PASS] {name}")
    except AssertionError as e:
        _FAIL.append((name, str(e)))
        print(f"  [FAIL] {name}  →  {e}")
    except Exception as e:
        _ERROR.append((name, traceback.format_exc()))
        print(f"  [ERR ] {name}  →  {type(e).__name__}: {e}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

section("1. CONFIG")

from aios import config as cfg

def t_config_get_defaults():
    assert cfg.get("llm", "model") == "llama3.2:3b"
    assert cfg.get("llm", "timeout") == 60
    assert cfg.get("rl", "max_corrections") == 100

def t_config_missing_key_returns_default():
    assert cfg.get("nonexistent", "key", "fallback") == "fallback"

def t_config_section_returns_dict():
    s = cfg.section("llm")
    assert isinstance(s, dict)
    assert "model" in s

def t_config_all_config_deep_copy():
    a = cfg.all_config()
    b = cfg.all_config()
    a["llm"]["model"] = "mutated"
    assert cfg.get("llm", "model") == "llama3.2:3b"   # original unchanged

def t_config_save_and_restore():
    original = cfg.get("rl", "max_corrections")
    cfg.save_user_config({"rl": {"max_corrections": 42}})
    assert cfg.get("rl", "max_corrections") == 42
    cfg.save_user_config({"rl": {"max_corrections": original}})

_run("config: defaults readable",       t_config_get_defaults)
_run("config: missing key → default",   t_config_missing_key_returns_default)
_run("config: section() returns dict",  t_config_section_returns_dict)
_run("config: all_config() deep copies",t_config_all_config_deep_copy)
_run("config: save_user_config round-trip", t_config_save_and_restore)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LOGGER
# ═══════════════════════════════════════════════════════════════════════════════

section("2. LOGGER")

from aios.logger import log

def t_logger_has_standard_methods():
    for method in ("debug", "info", "warning", "error", "critical"):
        assert hasattr(log, method), f"log.{method} missing"

def t_logger_does_not_raise():
    log.debug("test debug")
    log.info("test info")
    log.warning("test warning")

_run("logger: standard methods exist",  t_logger_has_standard_methods)
_run("logger: calls do not raise",      t_logger_does_not_raise)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CONTEXT MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

section("3. CONTEXT MEMORY")

from aios.context_memory import ContextMemory

def _fresh_memory(tmp: Path) -> ContextMemory:
    """Create a ContextMemory instance backed by a temp directory."""
    import aios.context_memory as cm_mod
    orig_dir = cm_mod.MEMORY_DIR
    # Monkey-patch paths to temp dir
    cm_mod.MEMORY_DIR      = tmp
    cm_mod.SESSION_FILE    = tmp / "sessions.json"
    cm_mod.WORKFLOWS_FILE  = tmp / "workflows.json"
    cm_mod.FILE_INDEX_FILE = tmp / "file_index.json"
    cm_mod.CONTEXT_FILE    = tmp / "context.json"
    tmp.mkdir(parents=True, exist_ok=True)
    m = ContextMemory()
    cm_mod.MEMORY_DIR = orig_dir
    return m

def t_memory_start_session():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        sess = m.start_session("test-session")
        assert sess["name"] == "test-session"
        assert "id" in sess

def t_memory_end_session():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        m.start_session()
        m.end_session()

def t_memory_save_and_get_workflow():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        wf = {"workflow_name": "myflow", "steps": [{"action": "open_app", "target": "chrome"}]}
        m.save_workflow("myflow", wf)
        retrieved = m.get_workflow("myflow")
        assert retrieved is not None
        assert retrieved["workflow_name"] == "myflow"

def t_memory_log_command():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        m.log_command("ls -la", "output")  # should not raise

def t_memory_increment_interaction():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        m.increment_interaction()
        ctx = m.get_context_summary()
        assert ctx["interaction_count"] >= 1

def t_memory_index_file():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        # Create a real file to index
        fp = Path(d) / "sample.txt"
        fp.write_text("hello world")
        m.index_file(str(fp), description="test file")
        results = m.search_files("hello")
        # Should return the indexed file (or at least not crash)
        assert isinstance(results, list)

def t_memory_corrupt_json_handled():
    """A corrupt JSON file should log a warning and return default, not crash."""
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "sessions.json"
        bad.write_text("{corrupt json!!!")
        m = _fresh_memory(Path(d))
        # Should not raise
        assert isinstance(m._sessions, dict)

def t_memory_concurrent_writes():
    """Multiple threads writing to memory should not corrupt data."""
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_memory(Path(d))
        errors = []
        def writer(i):
            try:
                m.log_command(f"cmd_{i}", f"output_{i}")
            except Exception as e:
                errors.append(str(e))
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == [], f"Thread errors: {errors}"

_run("memory: start_session",          t_memory_start_session)
_run("memory: end_session",            t_memory_end_session)
_run("memory: save/get workflow",      t_memory_save_and_get_workflow)
_run("memory: log_command",            t_memory_log_command)
_run("memory: increment_interaction",  t_memory_increment_interaction)
_run("memory: index_file + search",    t_memory_index_file)
_run("memory: corrupt JSON handled",   t_memory_corrupt_json_handled)
_run("memory: concurrent writes safe", t_memory_concurrent_writes)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RL MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

section("4. RL MEMORY")

from aios.rl_memory import RLMemory, _sim

def _fresh_rl(tmp: Path) -> RLMemory:
    import aios.rl_memory as rl_mod
    rl_mod._RL_DIR           = tmp
    rl_mod._CORRECTIONS_FILE = tmp / "corrections.json"
    rl_mod._FREQ_FILE        = tmp / "frequency.json"
    rl_mod._PROFILE_FILE     = tmp / "user_profile.json"
    tmp.mkdir(parents=True, exist_ok=True)
    return RLMemory()

def t_rl_similarity_identical():
    assert _sim("open chrome", "open chrome") == 1.0

def t_rl_similarity_zero():
    assert _sim("open chrome", "delete file") == 0.0

def t_rl_similarity_partial():
    s = _sim("open chrome browser", "open firefox browser")
    assert 0 < s < 1

def t_rl_record_interaction():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        rl.record_interaction("open chrome", "launch_apps", "chrome")
        assert rl._interaction_count == 1

def t_rl_record_correction():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        rl.record_correction("open chrome", "conversation", "launch_apps", "chrome")
        assert len(rl._corrections) == 1

def t_rl_get_relevant_examples_empty():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        result = rl.get_relevant_examples("open chrome")
        assert result == ""

def t_rl_get_relevant_examples_with_match():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        rl.record_correction("open chrome browser", "conversation", "launch_apps", "chrome")
        result = rl.get_relevant_examples("open chrome")
        assert "launch_apps" in result

def t_rl_build_prompt_context():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        rl.record_interaction("open chrome", "launch_apps", "chrome")
        rl.record_correction("open chrome", "conversation", "launch_apps", "chrome")
        ctx = rl.build_prompt_context("open chrome")
        assert isinstance(ctx, str)

def t_rl_max_corrections_cap():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        rl._max_corrections = 5
        for i in range(10):
            rl.record_correction(f"input_{i}", "wrong", "right")
        assert len(rl._corrections) <= 5

def t_rl_concurrent_saves():
    with tempfile.TemporaryDirectory() as d:
        rl = _fresh_rl(Path(d))
        errors = []
        def writer(i):
            try:
                rl.record_interaction(f"input_{i}", "launch_apps", f"app_{i}")
            except Exception as e:
                errors.append(str(e))
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert errors == [], f"Thread errors: {errors}"

_run("rl: similarity identical = 1.0",      t_rl_similarity_identical)
_run("rl: similarity zero on no overlap",    t_rl_similarity_zero)
_run("rl: similarity partial",               t_rl_similarity_partial)
_run("rl: record_interaction",               t_rl_record_interaction)
_run("rl: record_correction",               t_rl_record_correction)
_run("rl: get_relevant_examples empty",      t_rl_get_relevant_examples_empty)
_run("rl: get_relevant_examples with match", t_rl_get_relevant_examples_with_match)
_run("rl: build_prompt_context",             t_rl_build_prompt_context)
_run("rl: max_corrections cap enforced",     t_rl_max_corrections_cap)
_run("rl: concurrent saves thread-safe",     t_rl_concurrent_saves)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. FILE OPS
# ═══════════════════════════════════════════════════════════════════════════════

section("5. FILE OPS")

from aios.file_ops import (
    create_file, read_file, update_file, append_file,
    delete_file, rename_file, list_directory, _resolve_path,
    _resolve_path_from_args, _TRASH_DIR,
)

def t_fileops_resolve_path_absolute():
    p = _resolve_path(str(Path.home()))
    assert p == Path.home()

def t_fileops_resolve_path_traversal_blocked():
    try:
        _resolve_path("../../etc/passwd")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "traversal" in str(e).lower()

def t_fileops_resolve_path_from_args_with_cwd():
    with tempfile.TemporaryDirectory() as d:
        p = _resolve_path_from_args("test.txt", d)
        assert p == Path(d) / "test.txt"

def t_fileops_create_with_content():
    with tempfile.TemporaryDirectory() as d:
        result = create_file("hello.txt", content="hello world", cwd=d)
        assert result["success"]
        assert Path(d, "hello.txt").read_text() == "hello world"

def t_fileops_create_existing_no_overwrite():
    with tempfile.TemporaryDirectory() as d:
        create_file("f.txt", content="original", cwd=d)
        result = create_file("f.txt", content="new", cwd=d, overwrite=False)
        assert not result["success"]
        assert result.get("exists")

def t_fileops_create_overwrite():
    with tempfile.TemporaryDirectory() as d:
        create_file("f.txt", content="old", cwd=d)
        result = create_file("f.txt", content="new content", cwd=d, overwrite=True)
        assert result["success"]
        assert Path(d, "f.txt").read_text() == "new content"

def t_fileops_create_nested_dirs():
    with tempfile.TemporaryDirectory() as d:
        result = create_file("sub/dir/file.txt", content="x", cwd=d)
        assert result["success"]
        assert Path(d, "sub", "dir", "file.txt").exists()

def t_fileops_read_existing():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "r.txt").write_text("read me")
        result = read_file("r.txt", cwd=d)
        assert result["success"]
        assert result["content"] == "read me"

def t_fileops_read_missing():
    with tempfile.TemporaryDirectory() as d:
        result = read_file("nope.txt", cwd=d)
        assert not result["success"]
        assert "error" in result

def t_fileops_delete_soft():
    with tempfile.TemporaryDirectory() as d:
        create_file("del.txt", content="bye", cwd=d)
        result = delete_file("del.txt", confirmed=True, cwd=d)
        assert result["success"]
        assert not Path(d, "del.txt").exists()
        assert "trash_path" in result
        # Verify moved to trash
        assert Path(result["trash_path"]).exists()
        Path(result["trash_path"]).unlink()  # cleanup

def t_fileops_delete_needs_confirmation():
    with tempfile.TemporaryDirectory() as d:
        create_file("conf.txt", content="x", cwd=d)
        result = delete_file("conf.txt", confirmed=False, cwd=d)
        assert result.get("needs_confirmation")
        assert Path(d, "conf.txt").exists()  # not deleted yet

def t_fileops_delete_missing():
    with tempfile.TemporaryDirectory() as d:
        result = delete_file("ghost.txt", confirmed=True, cwd=d)
        assert not result["success"]

def t_fileops_rename():
    with tempfile.TemporaryDirectory() as d:
        create_file("old.txt", content="data", cwd=d)
        result = rename_file("old.txt", "new.txt", cwd=d)
        assert result["success"]
        assert Path(d, "new.txt").exists()
        assert not Path(d, "old.txt").exists()

def t_fileops_list_directory():
    with tempfile.TemporaryDirectory() as d:
        for name in ("a.txt", "b.txt", "c.py"):
            Path(d, name).write_text("x")
        result = list_directory(d)
        assert result["success"]
        names = [f["name"] for f in result["files"]]
        assert "a.txt" in names and "b.txt" in names and "c.py" in names

def t_fileops_update_llm_error_blocked():
    """LLM returning 'ERROR:...' must NOT overwrite the file."""
    with tempfile.TemporaryDirectory() as d:
        create_file("safe.txt", content="precious data", cwd=d)
        with patch("aios.file_ops.generate_file_content", return_value="ERROR: ollama is down"):
            result = update_file("safe.txt", "add something", cwd=d)
        assert not result["success"]
        assert Path(d, "safe.txt").read_text() == "precious data"

def t_fileops_append_llm_error_blocked():
    """LLM returning 'ERROR:...' must NOT append garbage to the file."""
    with tempfile.TemporaryDirectory() as d:
        create_file("log.txt", content="line1", cwd=d)
        with patch("aios.file_ops.generate_file_content", return_value="ERROR: timeout"):
            result = append_file("log.txt", "add more", cwd=d)
        assert not result["success"]
        assert Path(d, "log.txt").read_text() == "line1"

_run("file_ops: resolve absolute path",            t_fileops_resolve_path_absolute)
_run("file_ops: traversal attack blocked",         t_fileops_resolve_path_traversal_blocked)
_run("file_ops: resolve_path_from_args with cwd",  t_fileops_resolve_path_from_args_with_cwd)
_run("file_ops: create with content",              t_fileops_create_with_content)
_run("file_ops: create existing no overwrite",     t_fileops_create_existing_no_overwrite)
_run("file_ops: create overwrite=True",            t_fileops_create_overwrite)
_run("file_ops: create nested dirs auto-created",  t_fileops_create_nested_dirs)
_run("file_ops: read existing file",               t_fileops_read_existing)
_run("file_ops: read missing → error dict",        t_fileops_read_missing)
_run("file_ops: delete → soft trash",              t_fileops_delete_soft)
_run("file_ops: delete needs confirmation",        t_fileops_delete_needs_confirmation)
_run("file_ops: delete missing → error",           t_fileops_delete_missing)
_run("file_ops: rename",                           t_fileops_rename)
_run("file_ops: list_directory",                   t_fileops_list_directory)
_run("file_ops: update blocks LLM error string",   t_fileops_update_llm_error_blocked)
_run("file_ops: append blocks LLM error string",   t_fileops_append_llm_error_blocked)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FILE MANAGER (smart_search)
# ═══════════════════════════════════════════════════════════════════════════════

section("6. FILE MANAGER")

from aios.file_manager import (
    _detect_type_filter, _keyword_filter, _scan_directory, smart_search,
    recent_files, SKIP_DIRS,
)

def t_fm_detect_type_pdf():
    exts = _detect_type_filter("find my pdf reports")
    assert exts is not None
    assert ".pdf" in exts

def t_fm_detect_type_python():
    exts = _detect_type_filter("show me all python scripts")
    assert ".py" in exts

def t_fm_detect_type_none():
    exts = _detect_type_filter("find the document about health")
    # health doesn't trigger a type filter
    assert exts is None or isinstance(exts, set)

def t_fm_keyword_filter_scores():
    files = [
        {"name": "internship_report.pdf", "stem": "internship_report", "path": "/home/user/internship_report.pdf"},
        {"name": "grocery_list.txt",       "stem": "grocery_list",       "path": "/home/user/grocery_list.txt"},
        {"name": "random.py",              "stem": "random",              "path": "/home/user/random.py"},
    ]
    results = _keyword_filter(files, ["internship", "report"])
    assert results[0]["name"] == "internship_report.pdf"

def t_fm_keyword_filter_empty_keywords_returns_recent():
    files = [
        {"name": "a.txt", "stem": "a", "path": "/a.txt", "modified": "2024-01-01"},
        {"name": "b.txt", "stem": "b", "path": "/b.txt", "modified": "2025-06-01"},
    ]
    results = _keyword_filter(files, [])
    assert len(results) > 0

def t_fm_scan_directory_basic():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "doc.txt").write_text("hello")
        Path(d, "code.py").write_text("print(1)")
        subdir = Path(d, "sub")
        subdir.mkdir()
        Path(subdir, "readme.md").write_text("# readme")
        files = _scan_directory(Path(d))
        names = [f["name"] for f in files]
        assert "doc.txt" in names
        assert "code.py" in names
        assert "readme.md" in names

def t_fm_scan_skips_noise_dirs():
    with tempfile.TemporaryDirectory() as d:
        for skip in ("node_modules", ".git", "__pycache__"):
            skip_dir = Path(d, skip)
            skip_dir.mkdir()
            Path(skip_dir, "hidden.py").write_text("x")
        Path(d, "visible.py").write_text("y")
        files = _scan_directory(Path(d))
        names = [f["name"] for f in files]
        assert "hidden.py" not in names
        assert "visible.py" in names

def t_fm_scan_respects_max_files():
    with tempfile.TemporaryDirectory() as d:
        for i in range(20):
            Path(d, f"file_{i}.txt").write_text("x")
        files = _scan_directory(Path(d), max_files=5)
        assert len(files) <= 5

def t_fm_scan_file_has_required_keys():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "test.txt").write_text("x")
        files = _scan_directory(Path(d))
        assert files
        for key in ("path", "name", "stem", "suffix", "size", "modified", "parent"):
            assert key in files[0], f"Missing key: {key}"

def t_fm_smart_search_returns_list():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "internship_offer.pdf").write_text("internship details here")
        Path(d, "grocery.txt").write_text("milk eggs bread")
        with patch("aios.file_manager.extract_search_keywords", return_value=["internship"]), \
             patch("aios.file_manager.semantic_file_match", return_value=[0]):
            results = smart_search("internship", roots=[d])
        assert isinstance(results, list)

def t_fm_smart_search_no_crash_on_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        with patch("aios.file_manager.extract_search_keywords", return_value=[]), \
             patch("aios.file_manager.semantic_file_match", return_value=[]), \
             patch("aios.file_manager.memory.search_files", return_value=[]):
            results = smart_search("anything", roots=[d])
        assert results == []

def t_fm_smart_search_results_have_parent_key():
    """Regression: KeyError 'parent' must not happen."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "note.txt").write_text("some note")
        with patch("aios.file_manager.extract_search_keywords", return_value=["note"]), \
             patch("aios.file_manager.semantic_file_match", return_value=[0]):
            results = smart_search("note", roots=[d])
        for r in results:
            assert "parent" in r, "Missing 'parent' key in result"

def t_fm_recent_files_returns_list():
    result = recent_files(n=5)
    assert isinstance(result, list)

_run("file_manager: detect type filter pdf",          t_fm_detect_type_pdf)
_run("file_manager: detect type filter python",       t_fm_detect_type_python)
_run("file_manager: detect type filter none",         t_fm_detect_type_none)
_run("file_manager: keyword filter scores correctly", t_fm_keyword_filter_scores)
_run("file_manager: keyword filter empty → recent",   t_fm_keyword_filter_empty_keywords_returns_recent)
_run("file_manager: scan_directory basic",            t_fm_scan_directory_basic)
_run("file_manager: scan skips noise dirs",           t_fm_scan_skips_noise_dirs)
_run("file_manager: scan respects max_files",         t_fm_scan_respects_max_files)
_run("file_manager: scan results have required keys", t_fm_scan_file_has_required_keys)
_run("file_manager: smart_search returns list",       t_fm_smart_search_returns_list)
_run("file_manager: smart_search empty dir no crash", t_fm_smart_search_no_crash_on_empty_dir)
_run("file_manager: smart_search parent key present", t_fm_smart_search_results_have_parent_key)
_run("file_manager: recent_files returns list",       t_fm_recent_files_returns_list)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. URL ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

section("7. URL ROUTER")

from aios.url_router import route as url_route

def t_url_play_youtube():
    r = url_route("play Tum Hi Ho on youtube")
    assert r.matched
    assert "youtube.com" in (r.url or "")

def t_url_google_search():
    r = url_route("search python decorators on google")
    assert r.matched
    assert "google.com" in (r.url or "") or r.apps

def t_url_open_chrome():
    r = url_route("open chrome")
    assert r.matched
    assert "chrome" in [a.lower() for a in (r.apps or [])]

def t_url_open_vscode():
    r = url_route("open vscode")
    assert r.matched

def t_url_greet_hi():
    r = url_route("hi")
    assert r.matched
    assert r.assistant_action == "greet"

def t_url_greet_hello():
    r = url_route("hello")
    assert r.matched
    assert r.assistant_action == "greet"

def t_url_time_query():
    r = url_route("what time is it")
    assert r.matched
    assert r.assistant_action == "time"

def t_url_date_query():
    r = url_route("what is today's date")
    assert r.matched
    assert r.assistant_action == "date"

def t_url_joke():
    r = url_route("tell me a joke")
    assert r.matched
    assert r.assistant_action == "joke"

def t_url_take_screenshot():
    r = url_route("take a screenshot")
    assert r.matched
    assert r.assistant_action == "screenshot"

def t_url_note():
    r = url_route("note: remember to fix the login bug")
    assert r.matched
    assert r.assistant_action == "note"
    assert "login" in (r.note_content or "").lower()

def t_url_file_search():
    r = url_route("find files named resume")
    assert r.matched
    assert r.file_search_query is not None

def t_url_wikipedia():
    r = url_route("who is Nikola Tesla")
    assert r.matched
    assert r.assistant_action == "wiki" or ("wikipedia" in (r.url or "").lower())

def t_url_no_match_returns_unmatched():
    r = url_route("xyzzy frobulate the quantum thingy please")
    assert not r.matched

def t_url_create_file():
    r = url_route("create a file called hello.py")
    assert r.matched
    assert r.file_action == "create"
    assert "hello.py" in (r.filename or "")

def t_url_open_multiple_apps():
    r = url_route("open chrome and vscode")
    assert r.matched
    apps_lower = [a.lower() for a in (r.apps or [])]
    assert "chrome" in apps_lower or "vscode" in apps_lower

_run("url_router: play youtube",              t_url_play_youtube)
_run("url_router: google search",             t_url_google_search)
_run("url_router: open chrome",               t_url_open_chrome)
_run("url_router: open vscode",               t_url_open_vscode)
_run("url_router: greet hi",                  t_url_greet_hi)
_run("url_router: greet hello",               t_url_greet_hello)
_run("url_router: time query",                t_url_time_query)
_run("url_router: date query",                t_url_date_query)
_run("url_router: joke",                      t_url_joke)
_run("url_router: take screenshot",           t_url_take_screenshot)
_run("url_router: note command",              t_url_note)
_run("url_router: file search query",         t_url_file_search)
_run("url_router: wikipedia lookup",          t_url_wikipedia)
_run("url_router: no match returns unmatched",t_url_no_match_returns_unmatched)
_run("url_router: create file intent",        t_url_create_file)
_run("url_router: open multiple apps",        t_url_open_multiple_apps)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. APP NORMALIZER
# ═══════════════════════════════════════════════════════════════════════════════

section("8. APP NORMALIZER")

from aios.app_normalizer import normalize as normalize_app_name, APP_TARGETS, ALIASES as APP_ALIASES

def t_normalizer_chrome_aliases():
    for alias in ("google chrome", "chrome browser", "chromium"):
        result = normalize_app_name(alias)
        assert result is not None, f"alias '{alias}' not resolved"

def t_normalizer_vscode_aliases():
    for alias in ("vscode", "vs code", "visual studio code", "code editor"):
        result = normalize_app_name(alias)
        assert result is not None

def t_normalizer_notepad():
    result = normalize_app_name("notepad")
    assert result is not None

def t_normalizer_unknown_returns_none_or_fuzzy():
    # Should not crash for unknown input
    result = normalize_app_name("xyzzyabcdef_unknown_app_1234")
    # Either None or some fuzzy guess — must not raise
    assert result is None or isinstance(result, tuple)

def t_normalizer_targets_have_required_keys():
    for name, target in list(APP_TARGETS.items())[:20]:
        assert "type" in target, f"{name} missing 'type'"
        assert "target" in target, f"{name} missing 'target'"
        assert target["type"] in ("uri", "exe", "msc", "cpl", "app", "shell", "url")

def t_normalizer_all_aliases_map_to_known_target():
    for alias, canonical in list(APP_ALIASES.items())[:50]:
        assert canonical in APP_TARGETS, f"alias '{alias}' → '{canonical}' not in APP_TARGETS"

_run("app_normalizer: chrome aliases resolve",         t_normalizer_chrome_aliases)
_run("app_normalizer: vscode aliases resolve",         t_normalizer_vscode_aliases)
_run("app_normalizer: notepad resolves",               t_normalizer_notepad)
_run("app_normalizer: unknown → None (no crash)",      t_normalizer_unknown_returns_none_or_fuzzy)
_run("app_normalizer: targets have required keys",     t_normalizer_targets_have_required_keys)
_run("app_normalizer: all aliases map to valid target",t_normalizer_all_aliases_map_to_known_target)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. PROCESS MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

section("9. PROCESS MANAGER")

from aios.process_manager import (
    get_process_list, get_system_stats, find_process, kill_process,
    PROTECTED_PROCESSES,
)

def t_pm_get_system_stats_keys():
    stats = get_system_stats()
    for key in ("cpu_percent", "ram_total_gb", "ram_used_gb", "disk_free_gb"):
        assert key in stats, f"Missing key: {key}"

def t_pm_get_system_stats_sane_values():
    stats = get_system_stats()
    assert 0 <= stats["cpu_percent"] <= 100
    assert stats["ram_total_gb"] > 0
    assert stats["disk_free_gb"] >= 0

def t_pm_get_process_list_returns_list():
    procs = get_process_list(top_n=5)
    assert isinstance(procs, list)
    assert len(procs) <= 5

def t_pm_process_list_has_required_keys():
    procs = get_process_list(top_n=3)
    if procs:
        for key in ("pid", "name", "cpu_percent", "memory_mb", "status"):
            assert key in procs[0], f"Missing key: {key}"

def t_pm_find_process_returns_list():
    # 'python' is almost certainly running (we're running Python right now)
    matches = find_process("python")
    assert isinstance(matches, list)

def t_pm_kill_protected_process_refused():
    result = kill_process(0, name="system")
    assert not result["success"]
    assert "protected" in result.get("reason", "").lower()

def t_pm_kill_nonexistent_pid():
    result = kill_process(999999999)
    assert not result["success"]

def t_pm_protected_set_not_empty():
    assert len(PROTECTED_PROCESSES) > 0
    assert "system" in PROTECTED_PROCESSES

_run("process_manager: get_system_stats has keys",        t_pm_get_system_stats_keys)
_run("process_manager: get_system_stats sane values",     t_pm_get_system_stats_sane_values)
_run("process_manager: get_process_list returns list",    t_pm_get_process_list_returns_list)
_run("process_manager: process list has required keys",   t_pm_process_list_has_required_keys)
_run("process_manager: find_process returns list",        t_pm_find_process_returns_list)
_run("process_manager: kill protected → refused",         t_pm_kill_protected_process_refused)
_run("process_manager: kill nonexistent pid → error",     t_pm_kill_nonexistent_pid)
_run("process_manager: protected set not empty",          t_pm_protected_set_not_empty)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. AI SHELL
# ═══════════════════════════════════════════════════════════════════════════════

section("10. AI SHELL")

from aios.ai_shell import AIShell, DANGEROUS_PATTERNS, DIRECT_COMMANDS

def t_shell_direct_command_pwd():
    shell = AIShell()
    result = shell.run("pwd")
    # Should not crash; may succeed or return output
    assert "commands" in result

def t_shell_direct_command_list_files():
    shell = AIShell()
    result = shell.run("list files")
    assert "commands" in result
    assert not result.get("blocked")

def t_shell_cd_with_spaces_in_path():
    """Regression: cd to a path with spaces must use shlex, not .split()."""
    shell = AIShell()
    with tempfile.TemporaryDirectory(prefix="my dir ") as d:
        result = shell._execute_command(f'cd "{d}"' if sys.platform == "win32" else f"cd '{d}'")
        assert result["returncode"] == 0
        assert result["new_cwd"] is not None

def t_shell_dangerous_pattern_blocked():
    shell = AIShell()
    result = shell.run("rm -rf /")
    assert result.get("blocked")
    assert "reason" in result

def t_shell_dangerous_format_blocked():
    shell = AIShell()
    result = shell.run("format c:")
    assert result.get("blocked")

def t_shell_dry_run():
    shell = AIShell()
    with patch("aios.ai_shell.translate_to_shell", return_value=["echo hello"]):
        result = shell.run("say hello", dry_run=True)
    assert result.get("dry_run")
    assert result["commands"] == ["echo hello"]

def t_shell_direct_commands_not_empty():
    assert len(DIRECT_COMMANDS) > 0

def t_shell_dangerous_patterns_not_empty():
    assert len(DANGEROUS_PATTERNS) > 0
    assert "rm -rf" in DANGEROUS_PATTERNS

def t_shell_translate_failure_returns_empty():
    """translate_to_shell returning [] must not crash the shell."""
    shell = AIShell()
    with patch("aios.ai_shell.translate_to_shell", return_value=[]):
        result = shell.run("do something impossible")
    assert isinstance(result, dict)

_run("ai_shell: direct command pwd",               t_shell_direct_command_pwd)
_run("ai_shell: direct command list files",        t_shell_direct_command_list_files)
_run("ai_shell: cd with spaces in path",           t_shell_cd_with_spaces_in_path)
_run("ai_shell: dangerous rm -rf blocked",         t_shell_dangerous_pattern_blocked)
_run("ai_shell: dangerous format blocked",         t_shell_dangerous_format_blocked)
_run("ai_shell: dry_run returns commands only",    t_shell_dry_run)
_run("ai_shell: DIRECT_COMMANDS not empty",        t_shell_direct_commands_not_empty)
_run("ai_shell: DANGEROUS_PATTERNS not empty",     t_shell_dangerous_patterns_not_empty)
_run("ai_shell: translate [] no crash",            t_shell_translate_failure_returns_empty)


# ═══════════════════════════════════════════════════════════════════════════════
# 11. TASK EXECUTOR
# ═══════════════════════════════════════════════════════════════════════════════

section("11. TASK EXECUTOR")

from aios.task_executor import WorkflowExecutor, _execute_step, _EXECUTOR

def t_executor_shared_pool_exists():
    assert _EXECUTOR is not None
    assert _EXECUTOR._max_workers == 8

def t_executor_step_notify():
    step = {"step_id": 1, "action": "notify", "target": "hello", "description": "test"}
    result = _execute_step(step)
    assert result.status == "success"
    assert result.output == "hello"

def t_executor_step_wait():
    step = {"step_id": 2, "action": "wait", "target": "0.01", "description": "tiny wait"}
    result = _execute_step(step)
    assert result.status == "success"

def t_executor_step_unknown_action():
    step = {"step_id": 3, "action": "teleport", "target": "mars", "description": "sci-fi"}
    result = _execute_step(step)
    assert result.status == "skipped"

def t_executor_empty_workflow():
    ex = WorkflowExecutor()
    result = ex.execute({"workflow_name": "empty", "steps": []})
    assert result["total_steps"] == 0
    assert "error" in result

def t_executor_sequential_workflow():
    wf = {
        "workflow_name": "seq_test",
        "steps": [
            {"step_id": 1, "action": "notify", "target": "step1", "parallel_group": 0},
            {"step_id": 2, "action": "notify", "target": "step2", "parallel_group": 0},
        ]
    }
    result = WorkflowExecutor().execute(wf)
    assert result["success_count"] == 2

def t_executor_parallel_workflow():
    wf = {
        "workflow_name": "par_test",
        "steps": [
            {"step_id": 1, "action": "notify", "target": "a", "parallel_group": 1},
            {"step_id": 2, "action": "notify", "target": "b", "parallel_group": 1},
            {"step_id": 3, "action": "notify", "target": "c", "parallel_group": 1},
        ]
    }
    result = WorkflowExecutor().execute(wf)
    assert result["success_count"] == 3

def t_executor_result_keys():
    wf = {
        "workflow_name": "key_test",
        "steps": [{"step_id": 1, "action": "notify", "target": "x", "parallel_group": 0}]
    }
    result = WorkflowExecutor().execute(wf)
    for key in ("workflow_name", "total_steps", "success_count", "fail_count", "total_time_ms", "results"):
        assert key in result, f"Missing key: {key}"

_run("task_executor: shared pool exists",       t_executor_shared_pool_exists)
_run("task_executor: notify step succeeds",     t_executor_step_notify)
_run("task_executor: wait step succeeds",       t_executor_step_wait)
_run("task_executor: unknown action → skipped", t_executor_step_unknown_action)
_run("task_executor: empty workflow",           t_executor_empty_workflow)
_run("task_executor: sequential workflow",      t_executor_sequential_workflow)
_run("task_executor: parallel workflow",        t_executor_parallel_workflow)
_run("task_executor: result has all keys",      t_executor_result_keys)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. WORKFLOW ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

section("12. WORKFLOW ENGINE")

from aios.workflow_engine import WorkflowEngine, PRESET_WORKFLOWS

def t_wfengine_presets_not_empty():
    assert len(PRESET_WORKFLOWS) > 0

def t_wfengine_presets_have_steps():
    for name, wf in PRESET_WORKFLOWS.items():
        assert "steps" in wf, f"{name} missing steps"
        assert len(wf["steps"]) > 0

def t_wfengine_run_by_name_preset():
    msgs = []
    engine = WorkflowEngine(progress_callback=msgs.append)
    result = engine.run_by_name("focus_mode")
    assert result is not None
    assert "total_steps" in result

def t_wfengine_run_by_name_missing():
    engine = WorkflowEngine(progress_callback=lambda x: None)
    result = engine.run_by_name("nonexistent_workflow_xyz")
    assert result is None

def t_wfengine_list_available():
    engine = WorkflowEngine(progress_callback=lambda x: None)
    workflows = engine.list_available()
    assert isinstance(workflows, list)
    names = [w["name"] for w in workflows]
    assert "dev_mode" in names

def t_wfengine_save_custom():
    engine = WorkflowEngine(progress_callback=lambda x: None)
    engine.save_custom("test_custom", apps=["notepad"], description="test workflow")
    # Should not raise

def t_wfengine_run_from_goal_invalid_plan():
    """If LLM returns empty plan, engine should return error dict, not crash."""
    engine = WorkflowEngine(progress_callback=lambda x: None)
    with patch("aios.workflow_engine.generate_workflow_plan",
               return_value={"workflow_name": "bad", "steps": [], "_raw": "gibberish"}):
        result = engine.run_from_goal("do something")
    assert "error" in result

def t_wfengine_run_from_goal_malformed_steps():
    """Steps missing 'action' or 'target' should be filtered out."""
    engine = WorkflowEngine(progress_callback=lambda x: None)
    with patch("aios.workflow_engine.generate_workflow_plan",
               return_value={"workflow_name": "bad",
                             "steps": [{"step_id": 1}]}):  # missing action + target
        result = engine.run_from_goal("do something")
    assert "error" in result

_run("workflow_engine: presets not empty",                t_wfengine_presets_not_empty)
_run("workflow_engine: presets have steps",               t_wfengine_presets_have_steps)
_run("workflow_engine: run preset by name",               t_wfengine_run_by_name_preset)
_run("workflow_engine: run missing → None",               t_wfengine_run_by_name_missing)
_run("workflow_engine: list_available",                   t_wfengine_list_available)
_run("workflow_engine: save_custom no crash",             t_wfengine_save_custom)
_run("workflow_engine: empty plan → error dict",          t_wfengine_run_from_goal_invalid_plan)
_run("workflow_engine: malformed steps filtered",         t_wfengine_run_from_goal_malformed_steps)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. LLM ENGINE (mocked — no Ollama required)
# ═══════════════════════════════════════════════════════════════════════════════

section("13. LLM ENGINE (mocked)")

from aios.llm_engine import (
    parse_intent, translate_to_shell, generate_file_content,
    generate_workflow_plan, chat_response, semantic_file_match,
    extract_search_keywords, check_ollama_health, build_url_from_intent,
)

_VALID_INTENT = json.dumps({
    "intent_type": "launch_apps",
    "apps": ["chrome"],
    "commands": [],
    "workflow_name": None,
    "file_query": None,
    "file_action": None,
    "filename": None,
    "content_desc": None,
    "new_filename": None,
    "process_action": None,
    "raw_goal": "open chrome",
    "url": None,
    "search_query": None,
    "parallel": True,
})

def t_llm_parse_intent_valid_json():
    with patch("aios.llm_engine._call_ollama", return_value=_VALID_INTENT):
        result = parse_intent("open chrome")
    assert result["intent_type"] == "launch_apps"
    assert "chrome" in result["apps"]

def t_llm_parse_intent_fallback_on_bad_json():
    with patch("aios.llm_engine._call_ollama", return_value="not json at all!"):
        result = parse_intent("something weird")
    assert result["intent_type"] == "conversation"

def t_llm_parse_intent_with_rl_context():
    with patch("aios.llm_engine._call_ollama", return_value=_VALID_INTENT) as mock:
        parse_intent("open chrome", rl_context="[corrections] open chrome → launch_apps")
        prompt_args = mock.call_args
        # rl_context must be in the system prompt
        assert "corrections" in str(prompt_args)

def t_llm_translate_to_shell_valid():
    with patch("aios.llm_engine._call_ollama", return_value='["echo hello", "ls -la"]'):
        result = translate_to_shell("show files and say hello")
    assert result == ["echo hello", "ls -la"]

def t_llm_translate_to_shell_error():
    with patch("aios.llm_engine._call_ollama", return_value="ERROR: connection refused"):
        result = translate_to_shell("anything")
    assert result == []

def t_llm_generate_file_content_no_error_string():
    with patch("aios.llm_engine._call_ollama", return_value="print('hello world')"):
        content = generate_file_content("hello world script", "hello.py")
    assert content == "print('hello world')"
    assert not content.startswith("ERROR:")

def t_llm_generate_file_content_strips_fences():
    with patch("aios.llm_engine._call_ollama", return_value="```python\nprint(1)\n```"):
        content = generate_file_content("print 1", "t.py")
    assert "```" not in content

def t_llm_generate_workflow_plan_valid():
    mock_plan = json.dumps({
        "workflow_name": "test",
        "description": "test plan",
        "steps": [{"step_id": 1, "action": "open_app", "target": "chrome",
                   "description": "open browser", "parallel_group": 1}]
    })
    with patch("aios.llm_engine._call_ollama", return_value=mock_plan):
        plan = generate_workflow_plan("open browser")
    assert plan["workflow_name"] == "test"
    assert len(plan["steps"]) == 1

def t_llm_generate_workflow_plan_bad_json():
    with patch("aios.llm_engine._call_ollama", return_value="garbage"):
        plan = generate_workflow_plan("do something")
    assert plan["steps"] == []

def t_llm_chat_response_returns_string():
    with patch("aios.llm_engine._call_ollama", return_value="I am AIOS."):
        result = chat_response("who are you?")
    assert isinstance(result, str)
    assert len(result) > 0

def t_llm_extract_keywords_cached():
    """Same query should hit cache, not call Ollama twice."""
    # Clear cache first
    extract_search_keywords.cache_clear()
    call_count = 0
    def fake_ollama(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        return '["internship", "offer"]'
    with patch("aios.llm_engine._call_ollama", side_effect=fake_ollama):
        r1 = extract_search_keywords("find my internship offer")
        r2 = extract_search_keywords("find my internship offer")
    assert call_count == 1, "Cache not working — Ollama called twice for identical query"
    assert r1 == r2

def t_llm_build_url_from_intent_uses_existing():
    intent = {"url": "https://github.com", "search_query": None}
    url = build_url_from_intent(intent, "open github")
    assert url == "https://github.com"

def t_llm_build_url_from_intent_play():
    intent = {"url": None, "search_query": None}
    url = build_url_from_intent(intent, "play Bohemian Rhapsody")
    assert url is not None
    assert "youtube.com" in url

def t_llm_ollama_health_returns_bool():
    result = check_ollama_health(silent=True)
    assert isinstance(result, bool)

_run("llm_engine: parse_intent valid JSON",              t_llm_parse_intent_valid_json)
_run("llm_engine: parse_intent fallback bad JSON",       t_llm_parse_intent_fallback_on_bad_json)
_run("llm_engine: parse_intent injects rl_context",     t_llm_parse_intent_with_rl_context)
_run("llm_engine: translate_to_shell valid",             t_llm_translate_to_shell_valid)
_run("llm_engine: translate_to_shell error → []",        t_llm_translate_to_shell_error)
_run("llm_engine: generate_file_content clean",         t_llm_generate_file_content_no_error_string)
_run("llm_engine: generate_file_content strips fences", t_llm_generate_file_content_strips_fences)
_run("llm_engine: generate_workflow_plan valid",        t_llm_generate_workflow_plan_valid)
_run("llm_engine: generate_workflow_plan bad → empty",  t_llm_generate_workflow_plan_bad_json)
_run("llm_engine: chat_response returns string",        t_llm_chat_response_returns_string)
_run("llm_engine: extract_keywords cached",             t_llm_extract_keywords_cached)
_run("llm_engine: build_url uses existing url",         t_llm_build_url_from_intent_uses_existing)
_run("llm_engine: build_url play → youtube",            t_llm_build_url_from_intent_play)
_run("llm_engine: check_ollama_health returns bool",    t_llm_ollama_health_returns_bool)


# ═══════════════════════════════════════════════════════════════════════════════
# 14. FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

section("14. FEATURES (assistant, notes, screenshot)")

from aios.features.assistant import greet_user, tell_time, tell_date, tell_datetime
from aios.features.notes import add_note, list_notes

def t_feat_greet_returns_string():
    msg = greet_user()
    assert isinstance(msg, str) and len(msg) > 0

def t_feat_tell_time_returns_string():
    msg = tell_time()
    assert isinstance(msg, str)
    assert any(c.isdigit() for c in msg)

def t_feat_tell_date_returns_string():
    msg = tell_date()
    assert isinstance(msg, str)
    assert any(c.isdigit() for c in msg)

def t_feat_tell_datetime_returns_string():
    msg = tell_datetime()
    assert isinstance(msg, str) and len(msg) > 0

def t_feat_add_note():
    result = add_note("Remember to test everything")
    assert result["success"]
    note = result["note"]
    assert "content" in note
    assert "Remember" in note["content"]

def t_feat_add_note_assigns_id():
    r1 = add_note("first note")
    r2 = add_note("second note")
    assert r1["note"]["id"] != r2["note"]["id"]

def t_feat_list_notes_returns_list():
    add_note("test note for listing")
    notes = list_notes(n=5)
    assert isinstance(notes, list)
    assert len(notes) > 0

def t_feat_list_notes_order_descending():
    notes = list_notes(n=20)
    if len(notes) >= 2:
        assert notes[0]["id"] >= notes[-1]["id"]

_run("features: greet_user returns string",        t_feat_greet_returns_string)
_run("features: tell_time returns string",         t_feat_tell_time_returns_string)
_run("features: tell_date returns string",         t_feat_tell_date_returns_string)
_run("features: tell_datetime returns string",     t_feat_tell_datetime_returns_string)
_run("features: add_note succeeds",                t_feat_add_note)
_run("features: add_note assigns unique id",       t_feat_add_note_assigns_id)
_run("features: list_notes returns list",          t_feat_list_notes_returns_list)
_run("features: list_notes newest first",          t_feat_list_notes_order_descending)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. DAEMONS (start/stop — no actual system changes)
# ═══════════════════════════════════════════════════════════════════════════════

section("15. DAEMONS")

from aios.daemons import start_all as daemon_start_all

def t_daemons_start_all_returns_dict():
    messages = []
    result = daemon_start_all(notify=messages.append)
    assert isinstance(result, dict)

def t_daemons_started_are_alive():
    result = daemon_start_all(notify=lambda x: None)
    for name, d in result.items():
        assert d.is_alive(), f"Daemon '{name}' is not alive"

def t_daemons_are_daemon_threads():
    result = daemon_start_all(notify=lambda x: None)
    for name, d in result.items():
        assert d.daemon, f"Daemon '{name}' is not a daemon thread"

_run("daemons: start_all returns dict",          t_daemons_start_all_returns_dict)
_run("daemons: started daemons are alive",       t_daemons_started_are_alive)
_run("daemons: all are daemon=True threads",     t_daemons_are_daemon_threads)


# ═══════════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════════════════

total = len(_PASS) + len(_FAIL) + len(_ERROR)
print(f"\n{'='*60}")
print(f"  RESULTS: {len(_PASS)} passed  |  {len(_FAIL)} failed  |  {len(_ERROR)} errors  |  {total} total")
print(f"{'='*60}")

if _FAIL:
    print("\nFAILURES:")
    for name, msg in _FAIL:
        print(f"  [FAIL] {name}")
        print(f"         {msg}")

if _ERROR:
    print("\nERRORS:")
    for name, tb in _ERROR:
        print(f"  [ERR ] {name}")
        for line in tb.strip().splitlines()[-4:]:
            print(f"         {line}")

print()
sys.exit(0 if not _FAIL and not _ERROR else 1)
