"""
AIOS Reinforcement Learning Memory — User pattern adaptation engine.

How it works (in-context learning, no GPU training needed):
  1. Every successful interaction is logged → builds a frequency map.
  2. When the user corrects AIOS (/correct), the (wrong → right) pair is stored.
  3. Before each parse_intent() call, similar past corrections are retrieved
     via word-overlap similarity and injected as few-shot examples.
  4. After every `profile_rebuild_every` interactions the LLM summarises the
     user's habits into a compact profile string (also injected into prompts).

Effect: LLM parse accuracy improves for THIS user's vocabulary over time.
"""
import json
import threading
import time
from pathlib import Path
from typing import Optional

from aios.logger import log
from aios import config as cfg

_RL_DIR           = Path.home() / ".aios" / "rl"
_RL_DIR.mkdir(parents=True, exist_ok=True)

_CORRECTIONS_FILE = _RL_DIR / "corrections.json"
_FREQ_FILE        = _RL_DIR / "frequency.json"
_PROFILE_FILE     = _RL_DIR / "user_profile.json"

_rl_write_lock = threading.Lock()


# ── Persistence helpers ───────────────────────────────────────────────────────

def _load(path: Path, default):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("RL: could not load %s: %s", path.name, e)
    return default


def _save(path: Path, data) -> None:
    """Atomic write — write to .tmp then rename. Thread-safe via module lock."""
    tmp = path.with_suffix(".tmp")
    with _rl_write_lock:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp.replace(path)
        except Exception as e:
            log.error("RL: could not save %s: %s", path.name, e)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


# ── Similarity (bag-of-words, zero dependencies) ──────────────────────────────

def _sim(a: str, b: str) -> float:
    """Word-overlap Jaccard similarity in [0, 1]."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


# ── RLMemory class ────────────────────────────────────────────────────────────

class RLMemory:
    """
    User preference and pattern memory for in-context LLM adaptation.
    Loaded once at import — all methods are lightweight dict ops + JSON writes.
    """

    def __init__(self):
        self._max_corrections = cfg.get("rl", "max_corrections", 100)
        self._max_examples    = cfg.get("rl", "max_examples_in_prompt", 5)
        self._rebuild_every   = cfg.get("rl", "profile_rebuild_every", 50)
        self._corrections: list = _load(_CORRECTIONS_FILE, [])
        self._freq: dict        = _load(_FREQ_FILE, {})
        self._profile: dict     = _load(_PROFILE_FILE, {})
        self._interaction_count = sum(self._freq.values())
        self._profile_lock      = threading.Lock()

    # ── Recording ─────────────────────────────────────────────────────────

    def record_interaction(self, user_input: str, intent_type: str, action_taken: str) -> None:
        """
        Call on every successful routed interaction.
        Builds the frequency map and triggers profile rebuild when threshold is hit.
        """
        if not cfg.get("rl", "enabled", True):
            return
        key = f"{intent_type}:{action_taken}"
        self._freq[key] = self._freq.get(key, 0) + 1
        self._interaction_count += 1
        _save(_FREQ_FILE, self._freq)

        # Trigger async profile rebuild periodically
        if self._interaction_count % self._rebuild_every == 0:
            self._rebuild_profile_async()

        log.debug("RL: interaction recorded (%s), total=%d", key, self._interaction_count)

    def record_correction(
        self,
        original_input: str,
        wrong_intent: str,
        correct_intent: str,
        correct_action: str = "",
    ) -> None:
        """
        User issued /correct — store the (wrong → right) mapping.
        This is the most powerful learning signal.
        """
        if not cfg.get("rl", "enabled", True):
            return
        entry = {
            "input":          original_input,
            "wrong_intent":   wrong_intent,
            "correct_intent": correct_intent,
            "correct_action": correct_action,
            "ts":             time.time(),
            "used_count":     0,
        }
        self._corrections.append(entry)
        # Keep only the most recent N corrections
        if len(self._corrections) > self._max_corrections:
            self._corrections = self._corrections[-self._max_corrections:]
        _save(_CORRECTIONS_FILE, self._corrections)
        log.info("RL: correction stored for '%s' → %s", original_input[:60], correct_intent)

    # ── Retrieval for prompt injection ────────────────────────────────────

    def get_relevant_examples(self, user_input: str) -> str:
        """
        Retrieve past corrections similar to `user_input`.
        Returns a formatted string ready to prepend to the LLM system prompt.
        Returns "" if no relevant examples exist.
        """
        if not self._corrections or not cfg.get("rl", "enabled", True):
            return ""

        # Score + filter (threshold 0.3)
        scored = sorted(
            self._corrections,
            key=lambda c: _sim(user_input, c["input"]),
            reverse=True,
        )
        top = [c for c in scored if _sim(user_input, c["input"]) >= 0.3][:self._max_examples]

        if not top:
            return ""

        lines = ["[User corrections — apply these patterns]"]
        for c in top:
            c["used_count"] = c.get("used_count", 0) + 1
            lines.append(
                f'  "{c["input"]}"'
                f' → correct intent={c["correct_intent"]}'
                + (f', action={c["correct_action"]}' if c.get("correct_action") else "")
            )
        _save(_CORRECTIONS_FILE, self._corrections)
        return "\n".join(lines)

    def get_top_intents(self, n: int = 5) -> str:
        """Return the user's most-used intents as a compact hint string."""
        if not self._freq or not cfg.get("rl", "enabled", True):
            return ""
        top = sorted(self._freq.items(), key=lambda x: x[1], reverse=True)[:n]
        parts = [f"{k.split(':')[0]}({v}x)" for k, v in top]
        return "User's frequent actions: " + ", ".join(parts)

    def get_profile(self) -> str:
        """Return the cached user profile summary (for prompt enrichment)."""
        with self._profile_lock:
            return self._profile.get("summary", "")

    def build_prompt_context(self, user_input: str) -> str:
        """
        Combine relevant corrections + top intents + profile into one string
        to prepend to the LLM system prompt.
        Returns "" when nothing useful is available.
        """
        parts = []
        examples = self.get_relevant_examples(user_input)
        if examples:
            parts.append(examples)
        top = self.get_top_intents()
        if top:
            parts.append(top)
        profile = self.get_profile()
        if profile:
            parts.append(f"[User profile] {profile}")
        return "\n".join(parts)

    # ── Profile rebuild ───────────────────────────────────────────────────

    def _rebuild_profile_async(self) -> None:
        """Kick off an LLM profile summary in a background thread."""
        import threading
        threading.Thread(target=self._rebuild_profile, daemon=True, name="aios-rl-profile").start()

    def _rebuild_profile(self) -> None:
        """Ask the LLM to summarise this user's habits into a compact profile."""
        try:
            from aios.llm_engine import _call_ollama   # late import to avoid circular
            top_intents = sorted(self._freq.items(), key=lambda x: x[1], reverse=True)[:15]
            summary_input = json.dumps({"top_actions": top_intents}, indent=2)
            system = (
                "You are summarising a user's AIOS usage habits. "
                "In 2-3 sentences describe what this user mainly uses AIOS for, "
                "and any notable patterns. Be concise and factual."
            )
            summary = _call_ollama(summary_input, system=system, temperature=0.3)
            if summary and not summary.startswith("ERROR"):
                new_profile = {"summary": summary, "updated_ts": time.time()}
                with self._profile_lock:
                    self._profile = new_profile
                _save(_PROFILE_FILE, new_profile)
                log.info("RL: user profile rebuilt (%d chars)", len(summary))
        except Exception as e:
            log.warning("RL: profile rebuild failed: %s", e)

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        return {
            "corrections":        len(self._corrections),
            "unique_intents":     len(self._freq),
            "total_interactions": self._interaction_count,
            "has_profile":        bool(self._profile.get("summary")),
            "enabled":            cfg.get("rl", "enabled", True),
        }

    def last_input(self) -> Optional[str]:
        """Return the most recent user input (used by /correct command)."""
        return getattr(self, "_last_input", None)

    def set_last_input(self, user_input: str, intent_type: str) -> None:
        self._last_input       = user_input
        self._last_intent_type = intent_type

    def get_last_intent(self) -> Optional[str]:
        return getattr(self, "_last_intent_type", None)


# Module-level singleton
rl = RLMemory()
