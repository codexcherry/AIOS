"""
LLM Engine — Ollama-powered brain for AIOS.
All intent parsing, command translation, and reasoning goes through here.
"""
import json
import time
import requests
from typing import Optional

from aios.logger import log
from aios import config as cfg

# Read from config (with env-override support)
OLLAMA_URL  = cfg.get("llm", "url",         "http://localhost:11434/api/generate")
HEALTH_URL  = cfg.get("llm", "health_url",  "http://localhost:11434/api/tags")
MODEL       = cfg.get("llm", "model",        "llama3.2:3b")
_TIMEOUT    = cfg.get("llm", "timeout",      60)
_MAX_RETRY  = cfg.get("llm", "max_retries",  3)
_RETRY_DELAY = cfg.get("llm", "retry_delay", 1.5)

# Global health flag — set on startup, checked before LLM calls
OLLAMA_AVAILABLE: bool = True


def check_ollama_health(silent: bool = False) -> bool:
    """
    Ping the Ollama API to verify it is running.
    Sets the global OLLAMA_AVAILABLE flag.
    Returns True if healthy, False otherwise.
    """
    global OLLAMA_AVAILABLE
    try:
        r = requests.get(HEALTH_URL, timeout=3)
        OLLAMA_AVAILABLE = r.status_code == 200
    except Exception:
        OLLAMA_AVAILABLE = False

    if not OLLAMA_AVAILABLE and not silent:
        log.warning("Ollama is not running. AI features will be disabled until it starts.")
    else:
        log.debug("Ollama health check: %s", "OK" if OLLAMA_AVAILABLE else "FAIL")
    return OLLAMA_AVAILABLE


def _call_ollama(prompt: str, system: str = "", temperature: float = 0.2) -> str:
    """
    Call Ollama with automatic retry + exponential backoff.
    Returns the model response string, or an ERROR: ... string on failure.
    """
    global OLLAMA_AVAILABLE
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    payload = {
        "model": MODEL,
        "prompt": full_prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": 512},
    }
    last_error = ""
    for attempt in range(_MAX_RETRY):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            OLLAMA_AVAILABLE = True
            return resp.json().get("response", "").strip()
        except requests.exceptions.ConnectionError:
            last_error = "Ollama is not running. Start it with: ollama serve"
            OLLAMA_AVAILABLE = False
            break   # no point retrying if server is down
        except requests.exceptions.Timeout:
            last_error = f"Ollama timed out (attempt {attempt + 1}/{_MAX_RETRY})"
            log.warning("LLM: timeout on attempt %d", attempt + 1)
        except requests.exceptions.HTTPError as e:
            last_error = f"Ollama HTTP error: {e}"
            log.warning("LLM: HTTP error on attempt %d: %s", attempt + 1, e)
        except Exception as e:
            last_error = str(e)
            log.error("LLM: unexpected error on attempt %d: %s", attempt + 1, e)

        # Exponential backoff before retry
        if attempt < _MAX_RETRY - 1:
            delay = _RETRY_DELAY * (2 ** attempt)
            log.info("LLM: retrying in %.1fs ...", delay)
            time.sleep(delay)

    log.error("LLM: all %d attempts failed — %s", _MAX_RETRY, last_error)
    return f"ERROR: {last_error}"


def parse_intent(user_input: str, context: dict = None) -> dict:
    """
    Parse user natural language input into a structured intent object.
    Injects RL user-adaptation context (past corrections + profile) into the prompt.
    Returns dict with: intent_type, apps, commands, workflow, raw_goal
    """
    # ── RL context injection ──────────────────────────────────────────────
    rl_context = ""
    try:
        from aios.rl_memory import rl   # late import to avoid circular
        rl_context = rl.build_prompt_context(user_input)
    except Exception:
        pass

    ctx_str = json.dumps(context, indent=2) if context else "{}"
    base_system = """You are the intent parser for AIOS, an AI-native operating environment.
Analyze user input and return ONLY valid JSON (no markdown, no explanation).

JSON schema:
{
  "intent_type": "<one of: launch_apps|run_command|file_search|file_op|workflow|process_management|shell_command|conversation>",
  "apps": ["list of app names to open, e.g. chrome, vscode, spotify, notepad"],
  "commands": ["list of shell commands to execute"],
  "workflow_name": "<named workflow if mentioned, else null>",
  "file_query": "<semantic file search query if applicable, else null>",
  "file_action": "<one of: create|read|update|append|delete|rename|list — only for file_op intents, else null>",
  "filename": "<target filename including extension — only for file_op intents, else null>",
  "content_desc": "<description of content to write/modify — only for file_op intents, else null>",
  "new_filename": "<new filename for rename — only for file_op rename intents, else null>",
  "process_action": "<one of: status|optimize|kill|null>",
  "raw_goal": "<one sentence summary of what the user wants>",
  "url": "<full URL to open if user wants to visit a site or play media, else null. For music/video use YouTube search URL: https://www.youtube.com/results?search_query=QUERY. For web searches: https://www.google.com/search?q=QUERY>",
  "search_query": "<the raw search/media query string if user wants to search or play something, else null>",
  "parallel": true
}

Rules:
- If user says 'play X', 'search X in chrome', 'open X on youtube' → set url to YouTube search URL and add chrome to apps.
- If user says 'google X' or 'search X' → set url to Google search URL and add chrome to apps.
- URL-encode spaces as + in the url field.
- If user wants to create/read/edit/update/modify/change/delete/rename a file → set intent_type to file_op, set file_action and filename accordingly, do NOT add apps.

App name mappings (use these exact keys): chrome, vscode, spotify, notepad, terminal, explorer, task_manager, calculator, word, excel, powerpoint, vlc, discord, slack, telegram, whatsapp, obs, steam"""

    system = f"{base_system}\n\n{rl_context}" if rl_context else base_system

    prompt = f"User context:\n{ctx_str}\n\nUser input: {user_input}"
    raw = _call_ollama(prompt, system=system, temperature=0.1)

    # Extract JSON from response
    try:
        # Try direct parse
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON block
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    # Fallback
    return {
        "intent_type": "conversation",
        "apps": [],
        "commands": [],
        "workflow_name": None,
        "file_query": None,
        "process_action": None,
        "url": None,
        "search_query": None,
        "raw_goal": user_input,
        "parallel": False,
        "_raw_response": raw
    }


def translate_to_shell(natural_command: str, os_type: str = "windows") -> list[str]:
    """Translate natural language to shell commands."""
    system = f"""You are an expert {os_type} system administrator.
Convert the user's natural language request into exact shell commands.
Return ONLY a JSON array of command strings. No explanation. No markdown.
Example: ["mkdir myproject", "cd myproject", "python -m venv venv"]"""
    raw = _call_ollama(natural_command, system=system, temperature=0.1)
    try:
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
    except Exception:
        return [raw]


def generate_file_content(description: str, filename: str) -> str:
    """
    Generate source code or text content for a new file based on a natural-language description.
    Returns the raw file content string (no markdown fences, no explanation).
    """
    from pathlib import Path as _Path
    ext = _Path(filename).suffix.lower()
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".html": "HTML", ".css": "CSS", ".sh": "Bash shell script",
        ".bat": "Windows batch script", ".rb": "Ruby", ".go": "Go",
        ".java": "Java", ".c": "C", ".cpp": "C++", ".rs": "Rust",
        ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
        ".toml": "TOML", ".md": "Markdown", ".txt": "plain text",
    }
    lang = lang_map.get(ext, "code")
    system = (
        f"You are a code generator. Write clean, working {lang} code based on the user's description.\n"
        "Rules:\n"
        "- Return ONLY the raw file content. No markdown fences (no ```). No extra explanation.\n"
        "- Include proper imports, a __main__ guard if applicable, and working code.\n"
        "- Add brief inline comments for clarity."
    )
    prompt = f"Create a {lang} file named '{filename}': {description}"
    return _call_ollama(prompt, system=system, temperature=0.2)


def generate_workflow_plan(goal: str, context: dict = None) -> dict:
    """Generate a multi-step autonomous workflow plan."""
    ctx_str = json.dumps(context, indent=2) if context else "{}"
    system = """You are an autonomous AI agent workflow planner for AIOS.
Given a high-level goal, create an execution plan.
Return ONLY valid JSON:
{
  "workflow_name": "<name>",
  "description": "<what this workflow does>",
  "steps": [
    {
      "step_id": 1,
      "action": "<one of: open_app|run_command|file_search|wait|notify>",
      "target": "<app name or command or search query>",
      "description": "<human readable step description>",
      "parallel_group": <integer, steps with same group run in parallel, 0 = sequential>
    }
  ]
}"""
    prompt = f"Context:\n{ctx_str}\n\nGoal: {goal}"
    raw = _call_ollama(prompt, system=system, temperature=0.2)
    try:
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return json.loads(raw)
    except Exception:
        return {"workflow_name": "custom", "description": goal, "steps": [], "_raw": raw}


def chat_response(user_input: str, context: dict = None) -> str:
    """General conversational response with system context awareness."""
    ctx_summary = ""
    if context:
        ctx_summary = f"Current session context: {json.dumps(context, indent=2)}\n\n"
    system = """You are AIOS, a Cognitive Operating Layer — an AI-native operating environment assistant.
You help users orchestrate applications, manage workflows, and interact with their computer using natural language.
Be concise, helpful, and action-oriented. You run on local Ollama — no cloud."""
    return _call_ollama(f"{ctx_summary}User: {user_input}", system=system, temperature=0.7)


def analyze_process_list(processes: list) -> str:
    """AI analysis of running processes for optimization suggestions."""
    system = """You are a system performance analyst AI.
Analyze the process list and provide brief, actionable optimization recommendations.
Focus on: high memory/CPU consumers, redundant processes, optimization opportunities.
Keep response under 200 words."""
    prompt = f"Running processes (name, cpu%, memory_mb):\n{json.dumps(processes, indent=2)}"
    return _call_ollama(prompt, system=system, temperature=0.3)


def semantic_file_match(query: str, file_list: list) -> list:
    """Use LLM to semantically rank file relevance to a query."""
    system = """You are a semantic file search engine.
Given a search query and file list, return the indices (0-based) of the most relevant files.
Return ONLY a JSON array of integers. Max 10 results. Example: [2, 5, 0, 8]"""
    prompt = f"Query: {query}\n\nFiles:\n" + "\n".join(f"{i}: {f}" for i, f in enumerate(file_list))
    raw = _call_ollama(prompt, system=system, temperature=0.1)
    try:
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return list(range(min(5, len(file_list))))


def extract_search_keywords(query: str) -> list:
    """
    Use LLM to extract semantic keywords from a file search query.
    Returns a list of keyword strings (lowercase).
    Falls back to splitting the query on spaces if LLM unavailable.
    Example: "find my health related pdfs" → ["health", "medical", "clinical", "patient"]
    """
    system = """Extract the most useful search keywords from a file search query.
Return ONLY a JSON array of lowercase strings. 3-8 keywords max.
Focus on nouns and adjectives; skip filler words like 'find', 'my', 'related', 'files'.
Example: "find my health related pdfs" → ["health", "medical", "clinical", "patient", "report"]
Example: "last project presentation" → ["project", "presentation", "slides", "deck"]"""
    raw = _call_ollama(query, system=system, temperature=0.1)
    try:
        import re
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
            if isinstance(result, list) and all(isinstance(k, str) for k in result):
                return [k.lower() for k in result if k.strip()]
    except Exception:
        pass
    # Fallback: simple word split, skip common filler words
    _SKIP = {"find", "my", "related", "files", "file", "the", "a", "an", "some",
              "show", "search", "get", "all", "any", "last", "recent", "latest"}
    return [w for w in query.lower().split() if w not in _SKIP and len(w) > 2]


# ── URL builder (fallback when LLM doesn't populate url field) ──────────────

import re as _re
from urllib.parse import quote_plus as _qp

# Keywords that indicate a YouTube/media intent
_PLAY_WORDS = {"play", "song", "music", "video", "watch", "listen", "youtube", "yt"}
_SEARCH_WORDS = {"search", "google", "find", "look up", "lookup", "show me"}

def build_url_from_intent(intent: dict, raw_input: str) -> Optional[str]:
    """
    If the LLM already set a url, return it.
    Otherwise infer from raw_input keywords whether to build a YouTube or Google URL.
    """
    # LLM already provided a URL
    url = intent.get("url")
    if url and url.startswith("http"):
        return url

    words = set(raw_input.lower().split())

    # Detect media/play intent → YouTube
    if words & _PLAY_WORDS:
        query = _strip_intent_words(raw_input, _PLAY_WORDS | {"in", "the", "on", "chrome", "browser", "open"})
        if query:
            return f"https://www.youtube.com/results?search_query={_qp(query)}"

    # Detect search intent → Google
    if words & _SEARCH_WORDS:
        query = _strip_intent_words(raw_input, _SEARCH_WORDS | {"in", "the", "on", "chrome", "browser", "open", "for"})
        if query:
            return f"https://www.google.com/search?q={_qp(query)}"

    # LLM gave a search_query field
    sq = intent.get("search_query")
    if sq:
        return f"https://www.google.com/search?q={_qp(sq)}"

    return None


def _strip_intent_words(text: str, stop_words: set) -> str:
    """Remove intent/stop words and return the meaningful query remainder."""
    tokens = _re.sub(r'[^\w\s]', '', text.lower()).split()
    remaining = [t for t in tokens if t not in stop_words]
    return " ".join(remaining).strip()


# ── File content generation ──────────────────────────────────────────────────

# Language system prompts per file extension
_LANG_PROMPTS = {
    ".py":   "You are a Python developer. Write clean, working Python code.",
    ".js":   "You are a JavaScript developer. Write clean, working JS code.",
    ".ts":   "You are a TypeScript developer. Write clean, working TypeScript code.",
    ".html": "You are a web developer. Write valid, clean HTML.",
    ".css":  "You are a CSS developer. Write clean, valid CSS.",
    ".java": "You are a Java developer. Write clean, working Java code.",
    ".cpp":  "You are a C++ developer. Write clean, working C++ code.",
    ".c":    "You are a C developer. Write clean, working C code.",
    ".sh":   "You are a bash/shell scripting expert. Write a working shell script.",
    ".bat":  "You are a Windows batch scripting expert. Write a working .bat script.",
    ".sql":  "You are a SQL expert. Write clean, valid SQL.",
    ".json": "You are a data engineer. Write valid, well-structured JSON.",
    ".yaml": "You are a DevOps engineer. Write valid YAML configuration.",
    ".yml":  "You are a DevOps engineer. Write valid YAML configuration.",
    ".md":   "You are a technical writer. Write clean, well-structured Markdown.",
    ".txt":  "You are a helpful assistant. Write clear, well-organized text.",
    ".csv":  "You are a data engineer. Write valid CSV with headers.",
    ".xml":  "You are a developer. Write valid, well-structured XML.",
    ".rs":   "You are a Rust developer. Write clean, working Rust code.",
    ".go":   "You are a Go developer. Write clean, working Go code.",
    ".r":    "You are a data scientist using R. Write working R code.",
}

def generate_file_content(description: str, filename: str, existing_content: str = None) -> str:
    """
    Generate file content using LLM based on description and file type.
    If existing_content is provided, it modifies/updates it.
    Returns raw content string (no markdown fences, no explanation).
    """
    ext = _re.search(r'\.\w+$', filename)
    ext = ext.group(0).lower() if ext else ".txt"
    lang_hint = _LANG_PROMPTS.get(ext, "Write the requested content.")

    if existing_content:
        system = f"""{lang_hint}
You are updating an existing file.
Return ONLY the complete updated file content.
Do NOT include markdown code fences (```), explanations, or any text other than the file content itself."""
        prompt = f"""Filename: {filename}

Existing content:
{existing_content}

Modification instruction: {description}

Return the complete updated file content:"""
    else:
        system = f"""{lang_hint}
Return ONLY the file content.
Do NOT include markdown code fences (```), explanations, or any intro/outro text.
The output will be written directly to a file — return only what should be in the file."""
        prompt = f"""Filename: {filename}
Task: {description}

Write the complete file content:"""

    raw = _call_ollama(prompt, system=system, temperature=0.3,)

    # Strip markdown code fences if LLM added them anyway
    raw = _re.sub(r'^```[\w]*\n?', '', raw.strip())
    raw = _re.sub(r'\n?```$', '', raw.strip())
    return raw.strip()


def extract_file_intent(user_input: str) -> Optional[dict]:
    """
    Use LLM to extract file operation intent when regex didn't catch it.
    Returns dict or None.
    """
    system = """You are a file operation intent extractor.
Given a user request, extract the file operation details.
Return ONLY valid JSON (no markdown):
{
  "action": "<one of: create|read|update|append|delete|rename>",
  "filename": "<the target filename with extension, or null>",
  "description": "<what content to write/add, or what modification to make, or null>",
  "new_filename": "<for rename action, the new filename, else null>"
}
Return null if this is NOT a file operation request."""
    raw = _call_ollama(user_input, system=system, temperature=0.1)
    try:
        result = json.loads(raw)
        if isinstance(result, dict) and result.get("action"):
            return result
    except Exception:
        match = _re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, dict) and result.get("action"):
                    return result
            except Exception:
                pass
    return None
