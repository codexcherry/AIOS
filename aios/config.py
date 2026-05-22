"""
AIOS Configuration — Single source of truth for all settings.

Load order (each layer overrides the previous):
  1. Built-in defaults
  2. ~/.aios/config.json  (user persistent config)
  3. .env file in project root
  4. Environment variables  AIOS__SECTION__KEY=value
                            e.g. AIOS__LLM__MODEL=llama3.1:8b
"""
import copy
import json
import os
from pathlib import Path
from typing import Any

_CONFIG_DIR  = Path.home() / ".aios"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
# .env lives next to the project (two levels up from this file = repo root)
_ENV_FILE    = Path(__file__).parent.parent / ".env"

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULTS: dict = {
    "llm": {
        "model":        "llama3.2:3b",
        "url":          "http://localhost:11434/api/generate",
        "health_url":   "http://localhost:11434/api/tags",
        "timeout":      60,
        "max_retries":  3,
        "retry_delay":  1.5,      # seconds between retries (exponential × attempt)
    },
    "search": {
        "max_files": 2000,
    },
    "screenshots": {
        "save_dir": str(Path.home() / "Pictures" / "AIOS"),
    },
    "voice": {
        # Set enabled=true or start AIOS with /voice to enable
        "enabled":               False,
        # Free pvporcupine built-ins: jarvis, computer, terminator, porcupine,
        # blueberry, bumblebee, grapefruit, grasshopper, americano, alexa
        "wake_word":             "jarvis",
        "tts_enabled":           True,
        "tts_rate":              175,
        "tts_volume":            0.9,
        # Get a free key at https://console.picovoice.ai/
        # Leave blank to use the SpeechRecognition phrase-match fallback
        "picovoice_access_key":  "",
    },
    "logging": {
        "level":        "DEBUG",
        "max_bytes":    5_242_880,    # 5 MB
        "backup_count": 5,
    },
    "rl": {
        "enabled":                True,
        "max_corrections":        100,
        "max_examples_in_prompt": 5,
        # Rebuild user profile summary after this many interactions
        "profile_rebuild_every":  50,
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_dotenv(path: Path) -> None:
    """Parse a .env file and push values into os.environ (setdefault — won't overwrite)."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip("\"'")
            os.environ.setdefault(key.strip(), val)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (base is mutated, then returned)."""
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _cast(value: str, target) -> Any:
    """Cast a string env var to the type of *target*."""
    try:
        if isinstance(target, bool):
            return value.lower() in ("1", "true", "yes", "on")
        if isinstance(target, int):
            return int(value)
        if isinstance(target, float):
            return float(value)
    except (ValueError, TypeError):
        pass
    return value


def _load() -> dict:
    cfg = copy.deepcopy(_DEFAULTS)

    # 1. User config file
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                _deep_merge(cfg, json.load(f))
        except Exception:
            pass   # logger not yet available; silently skip

    # 2. .env file
    _load_dotenv(_ENV_FILE)

    # 3. Env vars  AIOS__SECTION__KEY=value
    for env_key, env_val in os.environ.items():
        if not env_key.startswith("AIOS__"):
            continue
        parts = env_key.split("__")[1:]        # ["LLM", "MODEL"]
        if len(parts) == 2:
            section, key = parts[0].lower(), parts[1].lower()
            if section in cfg and key in cfg[section]:
                cfg[section][key] = _cast(env_val, cfg[section][key])

    # 4. Convenience: pull well-known env vars
    if os.environ.get("PICOVOICE_ACCESS_KEY"):
        cfg["voice"]["picovoice_access_key"] = os.environ["PICOVOICE_ACCESS_KEY"]
    if os.environ.get("OLLAMA_MODEL"):
        cfg["llm"]["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_URL"):
        cfg["llm"]["url"] = os.environ["OLLAMA_URL"]

    return cfg


# ── Module-level config dict (populated once at import) ──────────────────────
_cfg: dict = _load()


# ── Public API ────────────────────────────────────────────────────────────────

def get(section: str, key: str, default: Any = None) -> Any:
    """cfg.get('llm', 'model') → 'llama3.2:3b'"""
    return _cfg.get(section, {}).get(key, default)


def section(name: str) -> dict:
    """Return an entire config section as a dict copy."""
    return dict(_cfg.get(name, {}))


def all_config() -> dict:
    """Return a deep copy of the full config."""
    return copy.deepcopy(_cfg)


def save_user_config(updates: dict) -> None:
    """
    Persist a partial config update to ~/.aios/config.json and apply live.
    Example: save_user_config({"voice": {"enabled": True}})
    """
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    _deep_merge(existing, updates)
    tmp = _CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    tmp.replace(_CONFIG_FILE)
    # Apply live
    _deep_merge(_cfg, updates)
