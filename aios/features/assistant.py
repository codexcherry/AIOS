"""
Assistant module — greet, time/date, jokes, Wikipedia person lookups.
Cross-platform (Windows + Linux). No macOS.
"""
import re
from datetime import datetime
from aios.utils.platform import username


# ── Greet ────────────────────────────────────────────────────────────────────

def greet_user() -> str:
    """Return a time-aware greeting addressed to the current user."""
    hour = datetime.now().hour
    name = username().split(".")[0].capitalize()

    if 5 <= hour < 12:
        return f"Good morning, {name}! How can I help you today?"
    elif 12 <= hour < 17:
        return f"Good afternoon, {name}! What can I do for you?"
    elif 17 <= hour < 21:
        return f"Good evening, {name}! How can I assist?"
    else:
        return f"Hey {name}! Working late? I'm here to help."


# ── Time & Date ──────────────────────────────────────────────────────────────

def tell_time() -> str:
    now = datetime.now()
    return f"Current time: {now.strftime('%I:%M %p')}  ({now.strftime('%H:%M:%S')})"


def tell_date() -> str:
    now = datetime.now()
    return f"Today is {now.strftime('%A, %B %d, %Y')}"


def tell_datetime() -> str:
    now = datetime.now()
    return (
        f"{now.strftime('%A, %B %d, %Y')}  |  "
        f"{now.strftime('%I:%M %p')} ({now.strftime('%H:%M')})"
    )


# ── Jokes ────────────────────────────────────────────────────────────────────

_FALLBACK_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs!",
    "A SQL query walks into a bar, walks up to two tables and asks... 'Can I join you?'",
    "Why did the developer go broke? Because he used up all his cache.",
    "What's a computer's favourite snack? Microchips.",
    "Why do Java developers wear glasses? Because they don't C#.",
    "How many programmers does it take to change a light bulb? None — that's a hardware problem.",
    "There are 10 types of people: those who understand binary and those who don't.",
    "Why was the function sad? Because it had too many arguments.",
    "A byte walks into a bar and orders a pint. Bartender asks: 'Why so glum?' The byte replies: 'I've had a bit of a bad day.'",
    "I asked an AI to tell me a joke. It said: 'I would, but my training data isn't funny enough.'",
]

_joke_index = 0


def tell_joke() -> str:
    """Return a joke — tries the local LLM first, falls back to built-ins."""
    global _joke_index
    try:
        from aios.llm_engine import _call_ollama
        joke = _call_ollama(
            prompt="Tell me one short, clean, funny programmer or tech joke. Just the joke, no intro or outro.",
            system="You are a witty comedian. Reply with a single short joke only.",
            temperature=0.9,
        )
        if joke and len(joke.strip()) > 10:
            return joke.strip()
    except Exception:
        pass

    # Rotate through fallback jokes
    joke = _FALLBACK_JOKES[_joke_index % len(_FALLBACK_JOKES)]
    _joke_index += 1
    return joke


# ── Wikipedia ────────────────────────────────────────────────────────────────

def wikipedia_summary(query: str, sentences: int = 3) -> dict:
    """
    Fetch a Wikipedia summary for a person or topic.
    Uses the Wikipedia REST API — no API key required.
    Returns: {"success": bool, "title": str, "summary": str, "url": str}
    """
    try:
        import requests

        # Step 1: search for the article
        search_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 1,
            },
            timeout=8,
        )
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])

        if not results:
            return {
                "success": False,
                "summary": f"No Wikipedia article found for '{query}'.",
            }

        title = results[0]["title"]

        # Step 2: get the summary
        from urllib.parse import quote as urlquote
        summary_resp = requests.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{urlquote(title)}",
            timeout=8,
        )
        summary_resp.raise_for_status()
        data = summary_resp.json()

        extract = data.get("extract", "")
        # Trim to requested sentence count
        sents = re.split(r"(?<=[.!?])\s+", extract.strip())
        summary = " ".join(sents[:sentences])

        return {
            "success": True,
            "title": data.get("title", title),
            "summary": summary,
            "url": (
                data.get("content_urls", {})
                    .get("desktop", {})
                    .get("page", f"https://en.wikipedia.org/wiki/{urlquote(title)}")
            ),
            "thumbnail": data.get("thumbnail", {}).get("source", ""),
        }

    except Exception as exc:
        return {
            "success": False,
            "summary": f"Could not fetch Wikipedia info: {exc}",
        }
