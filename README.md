# AIOS — Cognitive Workflow Orchestration System

> **Intent → Understanding → Parallel Execution → Contextual Computing**

A local-first, AI-native operating layer that lets you control your entire computer using natural language. Powered by **Ollama (llama3.2:3b)** running entirely on your machine — no subscriptions, no mandatory cloud APIs.

---

## What Is AIOS?

AIOS is not a voice assistant or a macro runner.  
It is a **Cognitive Operating Layer** — a system where:

- You think in **goals**, not applications
- The AI understands **intent**, not just keywords
- Tasks execute **in parallel**, not one by one
- The system **learns and remembers** your patterns across sessions

```
Traditional OS:  You → open app → use app → open another app → ...
AIOS:            You → state goal → AI orchestrates everything at once
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         AIOS CLI / Voice                         │
│                    main.py  ·  voice.py                          │
└────────────────────────────┬─────────────────────────────────────┘
                             │  user input (text or speech)
              ┌──────────────▼──────────────┐
              │   Stage 1: URL Router        │  ← zero LLM, ~0 ms
              │      url_router.py           │    45+ regex rules
              │   + App Normalizer           │    70+ direct sites
              └──────────────┬──────────────┘
                             │  no match
              ┌──────────────▼──────────────┐
              │   Stage 2: LLM Engine        │  ← Ollama llama3.2:3b
              │      llm_engine.py           │    intent JSON + RL context
              │   + RL Memory (context)      │    exponential-backoff retry
              └──┬───────┬────────┬──────┬───┘
                 │       │        │      │
    ┌────────────▼─┐ ┌───▼───┐ ┌─▼───┐ ┌▼──────────┐ ┌───────────┐
    │ App Launcher │ │AI     │ │File │ │ Workflow  │ │ Features  │
    │ + Normalizer │ │Shell  │ │ Ops │ │ Engine    │ │ assistant │
    │ app_launcher │ │       │ │     │ │           │ │ notes     │
    │ app_normalizer│ │ai_shell│ │file_│ │workflow_  │ │ screenshot│
    └──────┬───────┘ └───────┘ │ops  │ │engine +   │ └───────────┘
           │                   │file_│ │task_execu-│
           │                   │mgr  │ │tor        │
           └──────────────┬────┴─────┘ └─────┬─────┘
                          │                  │
              ┌───────────▼──────────────────▼────────┐
              │         Parallel Executor              │
              │       ThreadPoolExecutor               │
              └───────────────────┬────────────────────┘
                                  │
              ┌───────────────────▼────────────────────┐
              │           Context Memory               │
              │    ~/.aios/memory/*.json               │
              ├────────────────────────────────────────┤
              │           RL Memory                    │
              │    ~/.aios/rl/*.json                   │
              └────────────────────────────────────────┘
```

---

## Features

### 1. Natural Language Command Engine

Every input is understood as **intent**, not a raw command. A two-stage pipeline handles routing:

| You Type | AIOS Does |
|---|---|
| `open chrome and vscode` | Launches both in parallel |
| `open settings` | Opens Windows Settings |
| `start dev mode` | Runs the `dev_mode` workflow |
| `what's eating my RAM?` | AI process analysis |
| `hi` / `hello` | Time-aware greeting |
| `what time is it` | Current time |
| `tell me a joke` | Programmer joke |
| `who is Nikola Tesla` | Wikipedia summary |
| `take a screenshot` | Full-screen capture |
| `note: fix the login bug` | Saves a quick note |

**Pipeline:**  
Input → URL Router (instant) → LLM Parser (if no match) → Route to handler

---

### 2. Parallel Multi-App Execution

Apps launch **simultaneously** using `ThreadPoolExecutor`.

```
AIOS: open chrome, vscode, spotify and terminal

⚡ Launching 4 apps in parallel: chrome, vscode, spotify, terminal
  ✓ chrome      (21ms)
  ✓ vscode      (34ms)
  ✓ spotify     (28ms)
  ✓ terminal    (19ms)

✓ 4 launched  ✗ 0 failed  (38ms total)
```

Sequential time ≈ 400 ms. Parallel time: **38 ms**.

**App resolution — zero hardcoded paths:**
- Windows Registry lookup (`winreg`)
- `shutil.which` (PATH search)
- `glob` patterns for versioned installs (e.g. `C:\Program Files\Google\Chrome\*\chrome.exe`)
- Environment variable fallbacks
- `ms-settings:` URIs for Windows system pages

**Supported apps include:**  
`chrome`, `vscode`, `spotify`, `discord`, `slack`, `telegram`, `zoom`, `vlc`, `obs`, `steam`, `word`, `excel`, `powerpoint`, `notepad`, `terminal`, `cmd`, `calculator`, `paint`, `task_manager`, `settings`, `control_panel`, `device_manager`, `file_explorer`, `regedit`, `services`, `event_viewer`, `startup_apps`, and 80+ more.

---

### 3. URL Router (Instant — No LLM)

Pure Python regex routing fires **before** the LLM. Zero latency, zero tokens.

| You Type | Opens |
|---|---|
| `play Tum Hi Ho` | YouTube search |
| `search python tutorials` | Google search |
| `google machine learning` | Google search |
| `bing AI news` | Bing search |
| `duckduckgo privacy` | DuckDuckGo search |
| `amazon wireless headphones` | Amazon.in search |
| `flipkart laptop` | Flipkart search |
| `github fastapi` | GitHub search |
| `stackoverflow python error` | StackOverflow search |
| `wikipedia quantum computing` | Wikipedia search |
| `maps to Chennai` | Google Maps |
| `news about AI` | Google News |
| `pypi requests` | PyPI package page |
| `npm express` | npm package page |
| `mdn flexbox` | MDN Web Docs |
| `huggingface bert` | Hugging Face model search |
| `reddit python` | Reddit search |
| `arxiv transformers` | arXiv search |
| `linkedin data science` | LinkedIn search |
| `open youtube` | youtube.com |
| `open chatgpt` | chat.openai.com |
| `open colab` | colab.research.google.com |
| `open whatsapp` | web.whatsapp.com |
| `open notion` / `figma` / `vercel` / `kaggle` / `leetcode` | Direct site |

**70+ direct site mappings. 45+ regex rules. Fires in ~0 ms.**

---

### 4. App Normalizer

Understands any alias, partial name, description, or typo.

| You Say | Resolves To | Opens |
|---|---|---|
| `browser` / `web browser` | `chrome` | Chrome |
| `code editor` / `ide` | `vscode` | VS Code |
| `music` / `music player` | `spotify` | Spotify |
| `files` / `file manager` | `file_explorer` | Explorer |
| `presentation` / `slides` | `powerpoint` | PowerPoint |
| `spreadsheet` / `sheets` | `excel` | Excel |
| `command prompt` / `console` | `cmd` | CMD |
| `wallpaper` / `theme` | `personalization` | ms-settings:personalization |
| `startup programs` | `startup_apps` | ms-settings:startupapps |
| `screen recorder` | `obs` | OBS Studio |
| `task manager` | `task_manager` | taskmgr.exe |
| `device manager` | `device_manager` | devmgmt.msc |
| `uninstall` / `programs` | `programs` | appwiz.cpl |

Final fallback: **`difflib` fuzzy matching** — even misspellings resolve correctly.

---

### 5. Context Memory

AIOS remembers everything across sessions.

**Stored at:** `~/.aios/memory/`

| File | Stores |
|---|---|
| `sessions.json` | Full session history (apps, commands, timestamps) |
| `workflows.json` | Saved named workflows + run counts |
| `file_index.json` | Manually indexed files for faster search |
| `context.json` | Active session context (last 20 apps, last 50 commands) |

```
AIOS: /memory      → Summary of all sessions and workflows
AIOS: /context     → Current session state as JSON
```

Memory is injected as context into every LLM call — AIOS always knows your recent history.

---

### 6. Reinforcement Learning Memory

AIOS **adapts to your vocabulary** over time without retraining.

**How it works:**
1. Every successful interaction is logged → builds a frequency map
2. `/correct <wrong> → <right>` stores correction pairs
3. Before each intent parse, similar past corrections are retrieved via Jaccard similarity and injected as few-shot examples
4. After every 50 interactions, the LLM summarizes your usage habits into a compact profile string (also injected into prompts)

**Stored at:** `~/.aios/rl/`

| File | Stores |
|---|---|
| `corrections.json` | User correction pairs (up to 100) |
| `frequency.json` | Interaction frequency map |
| `user_profile.json` | LLM-generated user profile summary |

**Effect:** Intent parsing accuracy improves for your specific vocabulary and habits over time.

---

### 7. Autonomous Workflow Execution

Give AIOS a high-level goal — it generates and executes a multi-step plan.

```
AIOS: prepare hackathon submission

[Workflow] Planning: 'prepare hackathon submission'...

  ⚡ Parallel group 1 — 3 steps simultaneously:
    ✓ [1] Open VS Code        (34ms)
    ✓ [2] Open Chrome browser (21ms)
    ✓ [3] Open Terminal       (19ms)
  → [4] Run project zip command (210ms)
  → [5] Open GitHub             (28ms)

[AIOS] Workflow complete: 5/5 steps in 312ms
```

**Built-in preset workflows:**

| Name | What it does |
|---|---|
| `ai_research` | VS Code + Chrome + Terminal + starts Ollama |
| `dev_mode` | VS Code + Terminal + Chrome in parallel |
| `presentation_mode` | PowerPoint + Chrome + notification |
| `focus_mode` | VS Code + Notepad + focus reminder |
| `morning_setup` | Chrome + VS Code + Terminal + morning greeting |

```
AIOS: /run dev_mode           ← by name
AIOS: start ai research mode  ← natural language also works
AIOS: /workflows              ← list all available workflows
```

**Supported step actions:** `open_app`, `run_command`, `file_search`, `wait`, `notify`

---

### 8. AI-Powered Shell

A natural language terminal — translate intent to shell commands.

```
aios-shell [home]> create a python backend project with fastapi

  Commands: mkdir fastapi-project && cd fastapi-project &&
            python -m venv venv && pip install fastapi uvicorn

  cwd: C:\Users\YourName\fastapi-project
```

**Enter:** `AIOS: /shell`

**Capabilities:**
- Natural language → Windows/Linux shell command translation
- Working directory tracking (fully `cd`-aware across commands)
- Dangerous pattern blocking: `rm -rf`, `format`, `del /f /s /q`, `mkfs`, `dd` require explicit confirmation
- File creation with LLM-generated content (e.g. "create a FastAPI main.py")
- Command history saved to context memory

---

### 9. Smart File Manager

Semantic file search — find files by meaning, not exact filename.

```
AIOS: /files find my last healthcare presentation

🔍 Searching: 'find my last healthcare presentation'...

┌──────────────────────────────────────────────────────┐
│ File                   │ Path        │ Modified       │
│ healthcare_v2.pptx     │ Documents/  │ 2026-05-18     │
│ hospital_AI_demo.pptx  │ Desktop/    │ 2026-05-10     │
│ patient_data.xlsx      │ Projects/   │ 2026-05-15     │
└──────────────────────────────────────────────────────┘

Open a file? Enter number (or Enter to skip):
```

**Search pipeline:**
1. Scans `Documents/`, `Desktop/`, `Downloads/`, `Projects/`, current dir
2. Fast keyword pre-filter (no LLM)
3. LLM semantic ranking via `semantic_file_match()`
4. Returns top 8 results with open-by-number prompt

**Search roots are fully dynamic** — resolved from `Path.home()` and `os.environ`.

```
AIOS: /recent          → Last N modified files
```

---

### 10. File Operations (LLM-Powered CRUD)

Create, read, modify, and delete files using natural language.

| You Type | AIOS Does |
|---|---|
| `create a file called hello.py` | Creates file, LLM generates boilerplate |
| `create a README for my project` | LLM writes README content |
| `read config.json` | Displays file contents |
| `append a docstring to main.py` | LLM modifies file content |
| `delete old_backup.txt` | Asks confirmation, then deletes |
| `rename foo.py to bar.py` | Renames file |
| `list files in src/` | Directory listing |

**Supported operations:** `create`, `read`, `write`, `update`, `append`, `delete`, `rename`, `list`

---

### 11. AI Process Manager

Real-time process monitoring with AI-powered optimization advice.

```
AIOS: /ps

System: CPU 12%  RAM 9.2/15.7 GB (58%)  Disk 234 GB free

┌──────────────────────────────────────────────────────────────┐
│ PID    │ Name              │ CPU%  │ RAM MB │ Status         │
│ 4821   │ chrome.exe        │  4.2  │   892  │ running        │
│ 12044  │ Code.exe          │  2.1  │   512  │ running        │
│ 9203   │ Discord.exe       │  0.3  │   280  │ running        │
└──────────────────────────────────────────────────────────────┘

AIOS: /optimize

AI: Chrome is using 892 MB — consider closing unused tabs.
    Discord is idle at 280 MB — closing it frees ~1.2 GB total.
```

| Command | Action |
|---|---|
| `/ps` | Top 15 processes sorted by RAM |
| `/optimize` | AI analysis + recommendations |
| `/kill <pid>` | Kill process by PID |
| `/kill chrome` | Find all chrome processes, pick which to kill |

Protected system processes cannot be killed accidentally.

---

### 12. Voice I/O (Optional)

Three-tier voice system with automatic graceful degradation.

| Tier | Requires | Wake Word | Transcription |
|---|---|---|---|
| **Tier 1** (best) | `pvporcupine` + `SpeechRecognition` + `pyaudio` + Picovoice key | Hardware-level (jarvis, computer, alexa, …) | Google Web Speech |
| **Tier 2** | `SpeechRecognition` + `pyaudio` | Phrase-match ("hey aios", "aios") | Google Web Speech |
| **Tier 3** | Nothing | N/A | Text CLI only |

**TTS:** `pyttsx3` (offline, cross-platform)

**Built-in free Porcupine wake words:**  
`jarvis`, `computer`, `terminator`, `porcupine`, `blueberry`, `bumblebee`, `grapefruit`, `grasshopper`, `americano`, `alexa`

```
AIOS: /voice       → Toggle voice mode on/off
```

Configure in `~/.aios/config.json` or `.env`:
```env
AIOS__VOICE__ENABLED=true
AIOS__VOICE__WAKE_WORD=jarvis
AIOS__VOICE__PICOVOICE_ACCESS_KEY=your_free_key_here
```

---

### 13. Quick Features

| Command | What it does |
|---|---|
| `/screenshot` | Full-screen capture → `~/Pictures/AIOS/screenshot_YYYYMMDD_HHMMSS.png` |
| `/screenshot my_cap` | Screenshot with custom filename |
| `/note <text>` | Save a tagged note → `~/.aios/notes.json` |
| `/notes` | List 10 most recent notes |
| `/time` | Current time (12h + 24h) |
| `/date` | Today's date |
| `/joke` | Programmer joke |
| `who is <person>` | Wikipedia summary |
| `tell me about <topic>` | Wikipedia summary |

**Screenshot backends (auto-selected):**  
Pillow `ImageGrab` → Linux tools (scrot, gnome-screenshot, spectacle, flameshot) → PowerShell fallback

---

## Installation

### Requirements

- **OS:** Windows 10/11 or Linux (macOS not supported)
- **Python:** 3.11+
- **Ollama:** with `llama3.2:3b` pulled

### Setup

```bash
# 1. Clone or download the project
cd C:\PC\AIOS

# 2. Install core dependencies
pip install requests psutil rich

# 3. Optional: screenshot support
pip install Pillow

# 4. Optional: voice support
pip install SpeechRecognition pyaudio pyttsx3
pip install pvporcupine        # Tier 1 wake word (needs free API key)

# 5. Start Ollama (in a separate terminal)
ollama serve
ollama pull llama3.2:3b

# 6. Run AIOS
python -m aios
```

### Install as a Package (editable)

```bash
pip install -e .
aios          # now available as a global command
```

---

## Configuration

AIOS uses a layered config system. Each layer overrides the previous:

1. **Built-in defaults** (hardcoded in `config.py`)
2. **`~/.aios/config.json`** (user persistent config — auto-created)
3. **`.env` file** (in project root)
4. **Environment variables** `AIOS__SECTION__KEY=value`

**Example `.env`:**
```env
AIOS__LLM__MODEL=llama3.1:8b
AIOS__LLM__TIMEOUT=90
AIOS__VOICE__ENABLED=true
AIOS__VOICE__WAKE_WORD=computer
AIOS__VOICE__PICOVOICE_ACCESS_KEY=your_key_here
AIOS__SCREENSHOTS__SAVE_DIR=D:\Screenshots
```

**Key config options:**

| Section | Key | Default | Description |
|---|---|---|---|
| `llm` | `model` | `llama3.2:3b` | Ollama model name |
| `llm` | `url` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `llm` | `timeout` | `60` | Request timeout (seconds) |
| `llm` | `max_retries` | `3` | Retry attempts with backoff |
| `voice` | `enabled` | `false` | Enable voice mode at startup |
| `voice` | `wake_word` | `jarvis` | Porcupine wake word |
| `voice` | `tts_rate` | `175` | TTS speech rate (WPM) |
| `screenshots` | `save_dir` | `~/Pictures/AIOS` | Screenshot save directory |
| `rl` | `enabled` | `true` | Enable RL memory adaptation |
| `rl` | `profile_rebuild_every` | `50` | Rebuild user profile every N interactions |

---

## Usage

### Starting AIOS

```bash
python -m aios
# or, if installed as package:
aios
```

### All Commands

#### Natural Language (just type it)

```
open chrome and vscode
open settings
open device manager
play Tum Hi Ho
search python tutorials
google latest AI news
amazon wireless headphones
find my last project report
start dev mode
what's using the most RAM?
create a file called utils.py
who is Alan Turing
tell me a joke
take a screenshot
note: remember to push changes
```

#### Slash Commands

```
/shell              Enter AI-powered natural language shell
/workflows          List all available workflows
/run <name>         Execute a named workflow
/ps                 Process manager table (top 15 by RAM)
/optimize           AI system optimization analysis
/files <query>      Semantic file search
/recent             Recently modified files
/notes              List saved notes
/note <text>        Save a quick note
/screenshot         Take a screenshot (auto-named)
/screenshot <name>  Take a screenshot with custom filename
/time               Show current time
/date               Show today's date
/joke               Tell a programmer joke
/voice              Toggle voice mode on/off
/memory             View context memory summary
/context            View session context as JSON
/kill <pid>         Kill a process by PID
/kill <name>        Find and kill a process by name
/correct <w> → <r>  Teach AIOS a correction (RL memory)
/help               Show help screen
/clear              Clear screen
/exit               Exit AIOS
```

#### AI Shell (enter with `/shell`)

```
aios-shell [home]> create a python backend project with fastapi
aios-shell [home]> list all python files recursively
aios-shell [home]> show disk usage
aios-shell [home]> git status
aios-shell [home]> install flask and sqlalchemy
aios-shell [home]> cd projects/myapp
aios-shell [myapp]> run tests
aios-shell [myapp]> exit
```

---

## Project Structure

```
AIOS/
├── aios/
│   ├── __init__.py          Version info (v1.1.0)
│   ├── __main__.py          Entry point (python -m aios)
│   ├── main.py              CLI REPL — intent router + all slash-command handlers
│   ├── config.py            Multi-layer config (defaults → JSON → .env → env vars)
│   ├── logger.py            Rotating file logger (5 MB × 5 backups)
│   ├── llm_engine.py        Ollama API — intent parsing, translation, generation
│   ├── url_router.py        Pure-code URL/browser routing (no LLM, 45+ rules)
│   ├── app_normalizer.py    App alias table + difflib fuzzy matching (200+ aliases)
│   ├── app_launcher.py      Dynamic path resolution + ThreadPoolExecutor launcher
│   ├── context_memory.py    Session/workflow/file persistent memory (JSON)
│   ├── rl_memory.py         User pattern adaptation — corrections + frequency + profile
│   ├── task_executor.py     Parallel workflow step executor
│   ├── ai_shell.py          NL → shell command translator + interactive REPL
│   ├── file_manager.py      Semantic file search + LLM ranking
│   ├── file_ops.py          NL file CRUD (create/read/write/delete/rename/list)
│   ├── process_manager.py   psutil process monitor + AI optimization advice
│   ├── workflow_engine.py   Preset + LLM-generated workflow orchestration
│   ├── voice.py             3-tier voice I/O (Porcupine / SR / text-only)
│   ├── features/
│   │   ├── assistant.py     Greeting, time/date, jokes, Wikipedia summaries
│   │   ├── notes.py         Quick note save/list (JSON, tagged)
│   │   └── screenshot.py    Full-screen capture (Pillow → Linux tools → PowerShell)
│   └── utils/
│       ├── __init__.py
│       └── platform.py      OS detection, username, browser opener, path helpers
├── hello.py
├── pyproject.toml           Package metadata + pip entry point
├── requirements.txt
└── README.md
```

---

## Module Reference

### `llm_engine.py`

| Function | Purpose |
|---|---|
| `check_ollama_health()` | Ping Ollama, set global health flag |
| `parse_intent(text, context)` | NL input → structured intent JSON |
| `translate_to_shell(text, cwd)` | NL → Windows/Linux shell commands |
| `generate_workflow_plan(goal, context)` | Goal → multi-step execution plan dict |
| `chat_response(text, context)` | General conversational AI response |
| `analyze_process_list(procs)` | AI process optimization advice |
| `semantic_file_match(query, files)` | LLM file relevance ranking |
| `generate_file_content(filename, description)` | LLM-generated file content |

### `url_router.py`

| Function | Purpose |
|---|---|
| `route(user_input)` | Match input → `RouterResult` (url, apps, description) |

### `app_normalizer.py`

| Function | Purpose |
|---|---|
| `normalize(app_name)` | Any name → `(canonical, target_info)` |
| `normalize_app_list(names)` | Normalize a list of app names |

### `app_launcher.py`

| Function | Purpose |
|---|---|
| `launch_apps_parallel(apps, callback)` | Launch multiple apps simultaneously |
| `open_url_in_chrome(url)` | Open URL in Chrome (webbrowser fallback) |
| `is_app_running(app_name)` | Check if app process is currently running |
| `_resolve_app_path(name)` | Dynamic path resolution (registry/glob/PATH) |

### `context_memory.py`

| Method | Purpose |
|---|---|
| `memory.start_session()` | Begin a new session |
| `memory.log_app_opened(name)` | Record app launch |
| `memory.log_command(cmd)` | Record shell command |
| `memory.save_workflow(name, wf)` | Persist a workflow |
| `memory.get_workflow(name)` | Retrieve a saved workflow |
| `memory.get_context_summary()` | Dict summary for LLM context injection |

### `rl_memory.py`

| Method | Purpose |
|---|---|
| `rl.log_interaction(input, intent)` | Record successful interaction |
| `rl.add_correction(wrong, right)` | Store a user correction pair |
| `rl.get_context_injection(input)` | Retrieve relevant examples for prompt |
| `rl.rebuild_profile(llm_fn)` | Summarize user habits via LLM |

### `task_executor.py`

| Class / Method | Purpose |
|---|---|
| `WorkflowExecutor(callback)` | Create executor with progress callback |
| `.execute(workflow_dict)` | Run a full workflow plan dict |

### `ai_shell.py`

| Method | Purpose |
|---|---|
| `AIShell.run(text)` | Translate NL → execute → return result |
| `AIShell.interactive_session()` | Start interactive shell REPL |

### `file_manager.py`

| Function | Purpose |
|---|---|
| `smart_search(query)` | Semantic file search, returns ranked list |
| `recent_files(n)` | Get n most recently modified files |
| `open_file(path)` | Open file with system default app |

### `file_ops.py`

| Function | Purpose |
|---|---|
| `dispatch(text, cwd)` | Route NL file command to correct operation |
| `create_file(filename, description)` | Create file (LLM content generation) |
| `read_file(filename)` | Read and return file contents |
| `update_file(filename, instruction)` | LLM-guided file modification |
| `delete_file(filename)` | Delete file with confirmation |
| `rename_file(old, new)` | Rename a file |
| `list_dir(path)` | List directory contents |

### `process_manager.py`

| Function | Purpose |
|---|---|
| `get_process_list(top_n)` | Top N processes by RAM/CPU |
| `get_system_stats()` | CPU, RAM, disk stats |
| `kill_process(pid)` | Safely terminate a process |
| `ai_optimize()` | AI-generated optimization recommendations |
| `find_process(name)` | Find all processes matching a name |

### `workflow_engine.py`

| Method | Purpose |
|---|---|
| `WorkflowEngine.run_by_name(name)` | Run a preset or saved workflow |
| `WorkflowEngine.run_from_goal(goal)` | LLM-plan + execute from NL goal |
| `WorkflowEngine.list_available()` | List all workflows (preset + saved) |
| `WorkflowEngine.save_custom(name, apps, commands)` | Save a custom workflow |

### `voice.py`

| Method | Purpose |
|---|---|
| `voice.start_wake_listener(callback)` | Start background wake-word listener |
| `voice.stop_wake_listener()` | Stop the listener thread |
| `voice.listen_once()` | Listen for one utterance, return text |
| `voice.speak(text)` | Speak text via TTS |

### `features/assistant.py`

| Function | Purpose |
|---|---|
| `greet_user()` | Time-aware greeting (morning/afternoon/evening) |
| `tell_time()` | Current time (12h + 24h) |
| `tell_date()` | Today's date |
| `tell_joke()` | Random programmer joke |
| `wikipedia_summary(query)` | Fetch Wikipedia intro paragraph |

### `features/notes.py`

| Function | Purpose |
|---|---|
| `add_note(content, tag)` | Save a tagged note |
| `list_notes(n, tag)` | Return n most recent notes (filterable by tag) |

### `features/screenshot.py`

| Function | Purpose |
|---|---|
| `take_screenshot(filename)` | Capture full screen, save to disk |

---

## How Intent Routing Works

```
User Input
    │
    ▼
┌────────────────────────────────────────────┐
│  Stage 1: url_router.route(input)          │
│  • 45+ regex rules (play, search, maps…)   │
│  • 70+ direct site mappings                │
│  • Multi-app "open X and Y" detection      │
│  • App Normalizer for "open X" calls       │
│  • ~0 ms, zero LLM calls                   │
└──────────────────┬─────────────────────────┘
                   │ match → execute directly
                   │ no match ↓
┌──────────────────▼─────────────────────────┐
│  Stage 2: llm_engine.parse_intent()        │
│  • RL context injected (corrections +      │
│    frequency examples + user profile)      │
│  • Calls Ollama llama3.2:3b                │
│  • Exponential-backoff retry (3×)          │
│  • Returns structured JSON intent          │
│    {intent_type, apps, commands,           │
│     workflow_name, file_query,             │
│     process_action, raw_goal}              │
└──────────────────┬─────────────────────────┘
                   │
    ┌──────────────▼──────────────────────────────────┐
    │ Route by intent_type:                            │
    │  launch_apps    → handle_launch_apps()           │
    │  workflow       → WorkflowEngine.run_by_name()   │
    │  file_search    → handle_file_search()           │
    │  file_ops       → file_ops.dispatch()            │
    │  process_mgmt   → handle_process_manager()       │
    │  shell_command  → AIShell.run()                  │
    │  conversation   → chat_response()                │
    └──────────────────────────────────────────────────┘
```

---

## Memory & Data Storage

All data lives under `~/.aios/` (your home directory — portable across machines):

```
~/.aios/
├── config.json              ← User configuration overrides
├── memory/
│   ├── sessions.json        ← All session history
│   ├── workflows.json       ← Saved workflows + run counts
│   ├── file_index.json      ← Indexed files for faster search
│   └── context.json         ← Active session state
├── rl/
│   ├── corrections.json     ← User correction pairs
│   ├── frequency.json       ← Interaction frequency map
│   └── user_profile.json    ← LLM-generated user profile
└── notes.json               ← Quick notes (tagged, timestamped)
```

**Reset memory:**
```bash
# Windows
rmdir /s /q %USERPROFILE%\.aios\memory

# Linux
rm -rf ~/.aios/memory
```

**Reset everything:**
```bash
# Windows
rmdir /s /q %USERPROFILE%\.aios

# Linux
rm -rf ~/.aios
```

---

## Technical Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| LLM | Ollama — llama3.2:3b (local, configurable) |
| Parallelism | `concurrent.futures.ThreadPoolExecutor` |
| Terminal UI | `rich` — tables, panels, colors, spinners |
| System monitoring | `psutil` |
| App resolution | `winreg`, `shutil.which`, `glob`, env vars |
| Memory | JSON files in `~/.aios/` |
| URL routing | Pure Python `re` + `urllib.parse` |
| Fuzzy matching | `difflib.get_close_matches` |
| Voice recognition | `SpeechRecognition` + Google Web Speech (optional) |
| Wake word | `pvporcupine` (optional, free key) |
| TTS | `pyttsx3` (offline, optional) |
| Screenshots | `Pillow` / Linux tools / PowerShell (tiered) |
| Logging | `logging.handlers.RotatingFileHandler` (5 MB × 5) |

---

## Key Design Principles

1. **Local-first** — Ollama runs on your machine. Core features work offline.
2. **Code-first routing** — URL/app patterns resolved in code; LLM used only when needed.
3. **Zero hardcoded paths** — All app paths resolved dynamically (registry, glob, PATH).
4. **Portable** — Works on any Windows or Linux machine, any username, any install path.
5. **Memory-aware** — Every action is logged and available as LLM context.
6. **Parallel by default** — Multi-app launches always use thread pools.
7. **Adaptive** — RL memory improves intent accuracy for your specific vocabulary over time.
8. **Graceful degradation** — Missing optional dependencies (voice, Pillow) never crash the system.

---

## Demo Flow

```
AIOS: start my AI research workspace

[Workflow] Planning: 'start my AI research workspace'...

  ⚡ Parallel group 1 — 3 steps simultaneously:
    ✓ Open VS Code          (34ms)
    ✓ Open Chrome browser   (21ms)
    ✓ Open Windows Terminal (19ms)
  → Start Ollama server     (180ms)
  → Notify: AI workspace ready!

[AIOS] Workflow complete: 5/5 steps in 254ms
```

> *"The user doesn't open applications. The user states a goal.  
> AIOS understands intent, builds an execution plan, and orchestrates everything in parallel —  
> this is not automation, this is Cognitive Workflow Orchestration."*
