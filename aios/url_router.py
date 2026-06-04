"""
URL Router — Pure code-based intent-to-URL mapping.
NO LLM calls. Instant pattern matching for all browser/search/media intents.
Runs BEFORE the LLM parser — catches known patterns immediately.
"""
import re
from urllib.parse import quote_plus as qp
from typing import Optional, Tuple

# ── URL templates ────────────────────────────────────────────────────────────

def _yt(q):    return f"https://www.youtube.com/results?search_query={qp(q)}"
def _g(q):     return f"https://www.google.com/search?q={qp(q)}"
def _gh(q):    return f"https://github.com/search?q={qp(q)}" if q else "https://github.com"
def _so(q):    return f"https://stackoverflow.com/search?q={qp(q)}"
def _amz(q):   return f"https://www.amazon.in/s?k={qp(q)}"
def _flip(q):  return f"https://www.flipkart.com/search?q={qp(q)}"
def _news(q):  return f"https://news.google.com/search?q={qp(q)}" if q else "https://news.google.com"
def _wiki(q):  return f"https://en.wikipedia.org/wiki/Special:Search?search={qp(q)}"
def _maps(q):  return f"https://www.google.com/maps/search/{qp(q)}" if q else "https://maps.google.com"
def _pypi(q):  return f"https://pypi.org/search/?q={qp(q)}"
def _npm(q):   return f"https://www.npmjs.com/search?q={qp(q)}"
def _mdn(q):   return f"https://developer.mozilla.org/en-US/search?q={qp(q)}"
def _tw(q):    return f"https://twitter.com/search?q={qp(q)}" if q else "https://twitter.com"
def _reddit(q):return f"https://www.reddit.com/search/?q={qp(q)}" if q else "https://reddit.com"
def _li(q):    return f"https://www.linkedin.com/search/results/all/?keywords={qp(q)}" if q else "https://linkedin.com"
def _bing(q):  return f"https://www.bing.com/search?q={qp(q)}"
def _ddg(q):   return f"https://duckduckgo.com/?q={qp(q)}"
def _chatgpt(): return "https://chat.openai.com"
def _hf(q):    return f"https://huggingface.co/models?search={qp(q)}" if q else "https://huggingface.co"


# ── Site keyword → direct URL ────────────────────────────────────────────────

DIRECT_SITES = {
    "youtube":      "https://www.youtube.com",
    "yt":           "https://www.youtube.com",
    "google":       "https://www.google.com",
    "github":       "https://github.com",
    "stackoverflow":"https://stackoverflow.com",
    "stack overflow":"https://stackoverflow.com",
    "amazon":       "https://www.amazon.in",
    "flipkart":     "https://www.flipkart.com",
    "wikipedia":    "https://en.wikipedia.org",
    "wiki":         "https://en.wikipedia.org",
    "maps":         "https://maps.google.com",
    "gmail":        "https://mail.google.com",
    "google maps":  "https://maps.google.com",
    "twitter":      "https://twitter.com",
    "x.com":        "https://x.com",
    "reddit":       "https://reddit.com",
    "linkedin":     "https://linkedin.com",
    "instagram":    "https://instagram.com",
    "facebook":     "https://facebook.com",
    "whatsapp web": "https://web.whatsapp.com",
    "whatsapp":     "https://web.whatsapp.com",
    "chatgpt":      "https://chat.openai.com",
    "chat gpt":     "https://chat.openai.com",
    "bard":         "https://bard.google.com",
    "gemini":       "https://gemini.google.com",
    "huggingface":  "https://huggingface.co",
    "pypi":         "https://pypi.org",
    "npm":          "https://npmjs.com",
    "mdn":          "https://developer.mozilla.org",
    "notion":       "https://notion.so",
    "figma":        "https://figma.com",
    "canva":        "https://canva.com",
    "vercel":       "https://vercel.com",
    "netlify":      "https://netlify.com",
    "heroku":       "https://heroku.com",
    "colab":        "https://colab.research.google.com",
    "google colab": "https://colab.research.google.com",
    "kaggle":       "https://kaggle.com",
    "arxiv":        "https://arxiv.org",
    "leetcode":     "https://leetcode.com",
    "hackerrank":   "https://hackerrank.com",
    "codepen":      "https://codepen.io",
    "replit":       "https://replit.com",
    "drive":        "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "docs":         "https://docs.google.com",
    "sheets":       "https://sheets.google.com",
    "slides":       "https://slides.google.com",
    "meet":         "https://meet.google.com",
    "google meet":  "https://meet.google.com",
    "zoom":         "https://zoom.us",
    "news":         "https://news.google.com",
    "google news":  "https://news.google.com",
    "netflix":      "https://www.netflix.com",
    "prime video":  "https://www.primevideo.com",
    "hotstar":      "https://www.hotstar.com",
    "disney+":      "https://www.disneyplus.com",
    "spotify":      "https://open.spotify.com",
    "twitch":       "https://www.twitch.tv",
    "discord":      "https://discord.com",
    "slack":        "https://slack.com",
    "trello":       "https://trello.com",
    "jira":         "https://www.atlassian.com/software/jira",
}


# ── Regex pattern rules ──────────────────────────────────────────────────────
# Each rule: (compiled_regex, handler_fn)
# handler_fn(match) -> (url, browser, description)

_RULES: list[Tuple] = []

def _rule(pattern: str):
    """Decorator to register a URL routing rule."""
    def decorator(fn):
        _RULES.append((re.compile(pattern, re.IGNORECASE), fn))
        return fn
    return decorator


# ── Media / Play ─────────────────────────────────────────────────────────────

@_rule(r"^(?:play|listen(?:\s+to)?|hear)\s+(.+?)(?:\s+(?:on|in|via|using)\s+(?:youtube|yt|chrome|browser))?$")
def _play(m):
    return _yt(m.group(1).strip()), "chrome", f"Playing '{m.group(1).strip()}' on YouTube"

@_rule(r"^(?:watch|see)\s+(.+?)(?:\s+(?:on|in|via)\s+(?:youtube|yt|chrome|browser))?$")
def _watch(m):
    return _yt(m.group(1).strip()), "chrome", f"Opening '{m.group(1).strip()}' on YouTube"

@_rule(r"^(?:open|search|find|show)\s+(.+?)\s+(?:on|in)\s+(?:youtube|yt)$")
def _search_yt(m):
    return _yt(m.group(1).strip()), "chrome", f"YouTube: {m.group(1).strip()}"

@_rule(r"^youtube\s+(.+)$")
def _yt_direct(m):
    return _yt(m.group(1).strip()), "chrome", f"YouTube: {m.group(1).strip()}"


# ── Web Search ────────────────────────────────────────────────────────────────

@_rule(r"^(?:google|search(?:\s+for)?|find|look\s+up|lookup)\s+"
        r"(?!(?:(?:the|my|a|this|that|for)\s+)?files?\b)"   # not a local file search
        r"(.+?)(?:\s+(?:on|in|via|using)\s+(?:google|chrome|browser))?$")
def _google_search(m):
    q = m.group(1).strip()
    # Don't route to Google if the query targets the local machine
    _local = {"my computer", "my pc", "my laptop", "my machine", "my drive",
               "my folder", "my documents", "my desktop", "on my", "locally", "local"}
    if any(kw in q.lower() for kw in _local):
        return None, None, None   # fall through to LLM / file-op detection
    return _g(q), "chrome", f"Google: {q}"

@_rule(r"^(?:search|find|look\s+up)\s+(.+?)\s+on\s+google$")
def _google_explicit(m):
    return _g(m.group(1).strip()), "chrome", f"Google: {m.group(1).strip()}"

@_rule(r"^bing\s+(.+)$")
def _bing_search(m):
    return _bing(m.group(1).strip()), "chrome", f"Bing: {m.group(1).strip()}"

@_rule(r"^(?:ddg|duckduckgo)\s+(.+)$")
def _ddg_search(m):
    return _ddg(m.group(1).strip()), "chrome", f"DuckDuckGo: {m.group(1).strip()}"


# ── Shopping ─────────────────────────────────────────────────────────────────

@_rule(r"^(?:search|find|buy|shop(?:\s+for)?|get)\s+(.+?)\s+(?:on|in|at)\s+amazon$")
def _amazon(m):
    return _amz(m.group(1).strip()), "chrome", f"Amazon: {m.group(1).strip()}"

@_rule(r"^amazon\s+(.+)$")
def _amazon_direct(m):
    return _amz(m.group(1).strip()), "chrome", f"Amazon: {m.group(1).strip()}"

@_rule(r"^(?:search|find|buy|shop(?:\s+for)?)\s+(.+?)\s+(?:on|in|at)\s+flipkart$")
def _flipkart(m):
    return _flip(m.group(1).strip()), "chrome", f"Flipkart: {m.group(1).strip()}"

@_rule(r"^flipkart\s+(.+)$")
def _flipkart_direct(m):
    return _flip(m.group(1).strip()), "chrome", f"Flipkart: {m.group(1).strip()}"


# ── Developer ─────────────────────────────────────────────────────────────────

@_rule(r"^(?:search|find|open)\s+(.+?)\s+(?:on|in)\s+github$")
def _github_search(m):
    return _gh(m.group(1).strip()), "chrome", f"GitHub: {m.group(1).strip()}"

@_rule(r"^github\s+(.+)$")
def _github_direct(m):
    return _gh(m.group(1).strip()), "chrome", f"GitHub: {m.group(1).strip()}"

@_rule(r"^(?:stackoverflow|stack\s+overflow)\s+(.+)$")
def _so_direct(m):
    return _so(m.group(1).strip()), "chrome", f"StackOverflow: {m.group(1).strip()}"

@_rule(r"^(?:search|find|look\s+up)\s+(.+?)\s+(?:on|in)\s+(?:stackoverflow|stack\s+overflow)$")
def _so_search(m):
    return _so(m.group(1).strip()), "chrome", f"StackOverflow: {m.group(1).strip()}"

@_rule(r"^pypi\s+(.+)$")
def _pypi_s(m):
    return _pypi(m.group(1).strip()), "chrome", f"PyPI: {m.group(1).strip()}"

@_rule(r"^npm\s+(.+)$")
def _npm_s(m):
    return _npm(m.group(1).strip()), "chrome", f"npm: {m.group(1).strip()}"

@_rule(r"^mdn\s+(.+)$")
def _mdn_s(m):
    return _mdn(m.group(1).strip()), "chrome", f"MDN: {m.group(1).strip()}"


# ── Knowledge / Info ─────────────────────────────────────────────────────────

@_rule(r"^(?:wikipedia|wiki)\s+(.+)$")
def _wiki_direct(m):
    return _wiki(m.group(1).strip()), "chrome", f"Wikipedia: {m.group(1).strip()}"

@_rule(r"^(?:search|find|look\s+up)\s+(.+?)\s+(?:on|in)\s+(?:wikipedia|wiki)$")
def _wiki_search(m):
    return _wiki(m.group(1).strip()), "chrome", f"Wikipedia: {m.group(1).strip()}"

@_rule(r"^(?:directions?|navigate|maps?)\s+(?:to\s+)?(.+)$")
def _maps_search(m):
    return _maps(m.group(1).strip()), "chrome", f"Maps: {m.group(1).strip()}"

@_rule(r"^(?:news\s+about|search\s+news\s+for|news\s+on)\s+(.+)$")
def _news_search(m):
    return _news(m.group(1).strip()), "chrome", f"News: {m.group(1).strip()}"

@_rule(r"^reddit\s+(.+)$")
def _reddit_s(m):
    return _reddit(m.group(1).strip()), "chrome", f"Reddit: {m.group(1).strip()}"

@_rule(r"^(?:search|find)\s+(.+?)\s+(?:on|in)\s+reddit$")
def _reddit_search(m):
    return _reddit(m.group(1).strip()), "chrome", f"Reddit: {m.group(1).strip()}"

@_rule(r"^(?:huggingface|hf)\s+(.+)$")
def _hf_s(m):
    return _hf(m.group(1).strip()), "chrome", f"HuggingFace: {m.group(1).strip()}"

@_rule(r"^arxiv\s+(.+)$")
def _arxiv_s(m):
    return f"https://arxiv.org/search/?query={qp(m.group(1).strip())}&searchtype=all", "chrome", f"arXiv: {m.group(1).strip()}"


# ── Direct site open ──────────────────────────────────────────────────────────

@_rule(r"^open\s+(.+?)\s+(?:in|on|with)\s+(?:chrome|browser)$")
def _open_in_chrome(m):
    q = m.group(1).strip().lower()
    if q in DIRECT_SITES:
        return DIRECT_SITES[q], "chrome", f"Opening {q}"
    # Treat as URL if looks like domain
    if "." in q and " " not in q:
        url = q if q.startswith("http") else f"https://{q}"
        return url, "chrome", f"Opening {q}"
    # Fallback: Google search
    return _g(q), "chrome", f"Google: {q}"

@_rule(r"^open\s+(https?://\S+)$")
def _open_url(m):
    return m.group(1), "chrome", f"Opening {m.group(1)}"

@_rule(r"^(?:go\s+to|visit|open)\s+(\w[\w\s]*?)(?:\.(?:com|in|org|net|io|dev|ai|co))\s*$")
def _open_domain(m):
    raw = m.group(0)
    domain_match = re.search(r'(\w[\w.-]+\.(?:com|in|org|net|io|dev|ai|co))', raw, re.IGNORECASE)
    if domain_match:
        domain = domain_match.group(1).lower()
        return f"https://{domain}", "chrome", f"Opening {domain}"
    return None, None, None


# ── Main router entry point ───────────────────────────────────────────────────

class RouterResult:
    __slots__ = (
        "url", "browser", "description", "apps", "matched",
        "file_action", "filename", "content_desc", "new_filename",
        # Utility / assistant actions
        "assistant_action",    # "greet" | "time" | "date" | "datetime" | "joke"
        "note_content",        # text of note to save
        "screenshot_filename", # filename for screenshot (may be None → auto)
        "wiki_query",          # Wikipedia/person search query
        "urls",                # list of URLs to open (multi-tab)
        # Local file search (bypasses LLM)
        "file_search_query",   # semantic query for smart_search()
    )

    def __init__(self, url=None, browser=None, description=None, apps=None, matched=False,
                 file_action=None, filename=None, content_desc=None, new_filename=None,
                 assistant_action=None, note_content=None,
                 screenshot_filename=None, wiki_query=None, urls=None,
                 file_search_query=None):
        self.url = url
        self.browser = browser
        self.description = description
        self.apps = apps or []
        self.matched = matched
        self.file_action = file_action
        self.filename = filename
        self.content_desc = content_desc
        self.new_filename = new_filename
        self.assistant_action = assistant_action
        self.note_content = note_content
        self.screenshot_filename = screenshot_filename
        self.wiki_query = wiki_query
        self.urls = urls or []
        self.file_search_query = file_search_query


# ── Utility / assistant rules (return RouterResult directly) ─────────────────

_UTIL_RULES: list = []

def _util(pattern: str):
    def decorator(fn):
        _UTIL_RULES.append((re.compile(pattern, re.IGNORECASE), fn))
        return fn
    return decorator

# Greet
@_util(r"^(?:hi|hello|hey|howdy|hiya|yo)(?:\s+(?:aios|there|buddy))?[!.]*$")
def _u_greet(m):
    return RouterResult(matched=True, assistant_action="greet", description="Greeting")

# Good morning / afternoon / evening
@_util(r"^good\s+(?:morning|afternoon|evening|night)[!.,]*(?:\s+aios)?$")
def _u_greet2(m):
    return RouterResult(matched=True, assistant_action="greet", description="Greeting")

# Time
@_util(r"^(?:what(?:'s|\s+is)\s+(?:the\s+)?(?:current\s+)?time|"
         r"tell\s+me\s+the\s+time|what\s+time\s+is\s+it|current\s+time|"
         r"time\s+now)[?!.]*$")
def _u_time(m):
    return RouterResult(matched=True, assistant_action="time", description="Current time")

# Date
@_util(r"^(?:what(?:'s|\s+is)\s+(?:today'?s?\s+)?(?:the\s+)?date|"
         r"what\s+day\s+is\s+(?:it\s+)?today|what\s+day\s+is\s+it|"
         r"today'?s?\s+date|current\s+date|what'?s?\s+today)[?!.]*$")
def _u_date(m):
    return RouterResult(matched=True, assistant_action="date", description="Current date")

# Date + Time together
@_util(r"^(?:date\s+and\s+time|time\s+and\s+date|"
         r"what(?:'s|\s+is)\s+(?:the\s+)?(?:date\s+and\s+time|time\s+and\s+date))[?!.]*$")
def _u_datetime(m):
    return RouterResult(matched=True, assistant_action="datetime", description="Date and time")

# Joke
@_util(r"^(?:tell\s+(?:me\s+)?(?:a\s+)?joke|"
         r"say\s+something\s+funny|make\s+me\s+laugh|"
         r"joke(?:\s+please)?|got\s+(?:a\s+)?joke)[?!.]*$")
def _u_joke(m):
    return RouterResult(matched=True, assistant_action="joke", description="Tell a joke")

# Screenshot — "take a screenshot", "take a screenshoot" (typo), "capture screen"
# screensho+t handles both 'screenshot' and 'screenshoot' typos
@_util(r"^(?:take\s+(?:a\s+)?screensho+t|capture\s+(?:screen|screensho+t)|screensho+t)"
         r"(?:\s+(?:as|named?|called|with\s+name|save\s+as)\s+([\w\-. ]+))?[?!.]*$")
def _u_screenshot(m):
    fname = m.group(1).strip() if m.lastindex and m.group(1) else None
    return RouterResult(
        matched=True, assistant_action="screenshot",
        screenshot_filename=fname,
        description=f"Screenshot{f' → {fname}' if fname else ''}",
    )

# Explicit "screenshot as filename"
@_util(r"^screensho+t\s+(?:as|named?|called|save\s+as)\s+([\w\-. ]+)$")
def _u_screenshot2(m):
    fname = m.group(1).strip()
    return RouterResult(
        matched=True, assistant_action="screenshot",
        screenshot_filename=fname,
        description=f"Screenshot → {fname}",
    )

# Process / RAM / CPU queries — instant, no LLM
@_util(r"^(?:what(?:'s|\s+is)\s+(?:eating|using|consuming|hogging)\s+(?:my\s+)?(?:ram|memory|cpu|processor)|" 
         r"show\s+(?:processes?|tasks?|running\s+apps?)|" 
         r"what\s+processes?\s+(?:is|are)\s+running|" 
         r"(?:top|list)\s+processes?|" 
         r"how\s+much\s+(?:ram|memory|cpu)\s+(?:is\s+)?(?:being\s+)?used)[?!.]*$")
def _u_process(m):
    return RouterResult(matched=True, assistant_action="process", description="Process list")

# Note taking — "take a note: X" / "note: X" / "remember X" / "save note X"
@_util(r"^(?:take\s+(?:a\s+)?note|add\s+(?:a\s+)?note|save\s+(?:a\s+)?note|"
         r"note\s+(?:down|this)?|jot\s+(?:down)?|write\s+(?:a\s+)?note)[:\s]+(.+)$")
def _u_note(m):
    content = m.group(1).strip()
    return RouterResult(
        matched=True, assistant_action="note",
        note_content=content,
        description=f"Note: {content[:50]}",
    )

@_util(r"^(?:remember|remind\s+me\s+(?:to|that)?|note)[:\s]+(.+)$")
def _u_note2(m):
    content = m.group(1).strip()
    return RouterResult(
        matched=True, assistant_action="note",
        note_content=content,
        description=f"Note: {content[:50]}",
    )

# List notes
@_util(r"^(?:show|list|view|display)\s+(?:my\s+)?notes?[?!.]*$")
def _u_notes_list(m):
    return RouterResult(matched=True, assistant_action="notes_list", description="List notes")

# ── File search (local filesystem — no LLM, no browser) ─────────────────────
# Catches: "show/find/list/search (me/my) files (related to/about/named/for) X"
#           "what files are about X", "search for files related to X"
#           "/files X"  (slash command from dashboard chat)

@_util(
    r"^(?:"
    r"(?:show|find|list|search(?:\s+for)?|give\s+me|get)\s+"
    r"(?:me\s+)?(?:the\s+)?(?:my\s+)?(?:all\s+)?"
    r"files?(?:\s+(?:related\s+to|about|for|named|called|containing|with|that\s+(?:are\s+)?(?:about|related\s+to)))?\s+"
    r"|what\s+files?\s+(?:are\s+)?(?:related\s+to|about|contain|have)\s+"
    r"|/files?\s+"
    r")(.+)$"
)
def _u_file_search(m):
    query = m.group(1).strip().lstrip("/")
    return RouterResult(
        matched=True,
        file_search_query=query,
        description=f"File search: {query}",
    )

# Bare "/files" or "recent files" → recent files
@_util(r"^(?:/files?|recent\s+files?|show\s+recent\s+files?)$")
def _u_file_search_recent(m):
    return RouterResult(
        matched=True,
        file_search_query="",       # empty = list recent files
        description="Recent files",
    )

# ── Natural-language local file search (no "file" keyword required) ──────────
# "find my resume"  /  "where is my document"  /  "locate the report"
# These MUST come after all web-search rules so "find X on google" etc. already matched.
@_util(
    r"^(?:"
    r"(?:find|locate|search\s+for|look\s+for)\s+my\s+(.+?)"          # find my X
    r"|where\s+(?:is|are)\s+(?:my\s+|the\s+)?(.+?)"                  # where is my X
    r"|(?:find|locate|search\s+for|look\s+for)\s+(?:the\s+)?(.+?)"   # find the X (needs file word below)
    r"\s+(?:file|document|doc|pdf|image|photo|folder|dir|report|spreadsheet|sheet|presentation|ppt|txt|log|code)"
    r")[?!.]*$"
)
def _u_file_search_nlp(m):
    # Pick whichever capture group matched
    query = next((g.strip() for g in m.groups() if g), "")
    if not query:
        return RouterResult(matched=False)
    return RouterResult(
        matched=True,
        file_search_query=query,
        description=f"File search: {query}",
    )

# ── Extended process-manager shortcuts ───────────────────────────────────────
# ps / processes / system status / what's running (no LLM needed)
@_util(
    r"^(?:"
    r"ps"
    r"|processes?"
    r"|running\s+(?:processes?|programs?|apps?|tasks?)"
    r"|show\s+(?:running|all)\s+(?:processes?|programs?|apps?|tasks?)"
    r"|(?:system|resource)\s+(?:status|stats?|monitor|usage|info)"
    r"|what(?:'s|\s+is|\s+are)\s+running"
    r"|monitor\s+(?:system|cpu|ram|memory|resources?)"
    r"|task\s+(?:manager|list)"
    r"|/ps"
    r")[?!.]*$"
)
def _u_process_ext(m):
    return RouterResult(matched=True, assistant_action="process", description="Process list")

# Wikipedia / person info
@_util(r"^(?:who\s+(?:is|was)|tell\s+me\s+about|"
         r"info(?:rmation)?\s+(?:about|on)|"
         r"wikipedia(?:\s+(?:about|for))?|"
         r"search\s+wikipedia(?:\s+for)?|"
         r"about)\s+(.+?)[?!.]*$")
def _u_wiki(m):
    query = m.group(1).strip()
    return RouterResult(
        matched=True, assistant_action="wiki",
        wiki_query=query,
        description=f"Wikipedia: {query}",
    )


def route(user_input: str) -> RouterResult:
    """
    Try to match user input against all registered patterns.
    Returns RouterResult with matched=True if a rule fired, False if LLM needed.
    """
    text = user_input.strip()
    text_lower = text.lower()

    # 0. Utility / assistant rules (greet, time, date, joke, note, screenshot, wiki)
    for regex, handler in _UTIL_RULES:
        m = regex.match(text_lower)
        if m:
            result = handler(m)
            if result and result.matched:
                return result

    # 1. Check direct site open: "open youtube", "open github", etc.
    for site, url in DIRECT_SITES.items():
        patterns_to_check = [
            f"open {site}",
            f"go to {site}",
            f"visit {site}",
            f"launch {site}",
            f"show {site}",
        ]
        if text_lower in patterns_to_check or text_lower == site:
            return RouterResult(url=url, browser="chrome", description=f"Opening {site}", apps=["chrome"], matched=True)

    # 2. Check regex rules
    for regex, handler in _RULES:
        m = regex.match(text_lower)
        if m:
            try:
                url, browser, description = handler(m)
                if url:
                    apps = [browser] if browser else []
                    return RouterResult(url=url, browser=browser, description=description, apps=apps, matched=True)
            except Exception:
                continue

    # 3. Multi-app launch patterns (no URL needed)
    multi_match = _detect_multi_app(text_lower)
    if multi_match:
        return multi_match  # Already a RouterResult

    # 4. File operation patterns
    file_result = _detect_file_op(text)
    if file_result:
        return file_result

    # 5. No match — needs LLM
    return RouterResult(matched=False)


# ── Known app names for multi-app detection ──────────────────────────────────

_APP_NAMES = {
    "chrome", "vscode", "vs code", "visual studio code", "code",
    "spotify", "notepad", "terminal", "explorer", "task manager",
    "calculator", "calc", "word", "excel", "powerpoint", "vlc",
    "discord", "slack", "telegram", "obs", "steam", "paint",
    "whatsapp", "zoom", "python", "ollama", "cmd", "notepad++",
    "task_manager", "file_explorer", "gimp", "firefox",
    "libreoffice", "inkscape", "blender", "brave",
    # Windows system apps (resolved via app_normalizer → ms-settings: / .msc)
    "settings", "setting",
    "control panel", "device manager", "task manager",
    "file explorer", "file manager",
    "event viewer", "services", "registry editor",
    "disk management", "system properties",
}

_OPEN_VERBS = r"(?:open|launch|start|run|load|fire\s+up)"

# Aliases to normalize before app/site lookup
_APP_ALIASES = {
    "vs code":            "vscode",
    "visual studio code": "vscode",
    "calc":               "calculator",
    "task manager":       "task_manager",
    "file explorer":      "file_explorer",
    "file manager":       "file_explorer",
    "command prompt":     "cmd",
    "brave browser":      "brave",
    "google chrome":      "chrome",
    "setting":            "settings",
    "control panel":      "control_panel",
    "device manager":     "device_manager",
    "event viewer":       "event_viewer",
    "disk management":    "disk_management",
    "registry editor":    "regedit",
    "system properties":  "system_properties",
}

# Filler words to strip from individual parts after splitting
_PART_FILLER = re.compile(
    r"^(?:a|an|the|my|new|another)\s+|\s+(?:app|browser|window)$",
    re.IGNORECASE,
)
# "new tab in X" / "new tab on X" → keep X
_NEW_TAB = re.compile(r"\bnew\s+tab\s+(?:in|on|for|with|at)?\s*", re.IGNORECASE)
# standalone "new tab" with no site after it
_BARE_NEW_TAB = re.compile(r"\bnew\s+tab\b", re.IGNORECASE)


def _detect_multi_app(text: str) -> Optional[RouterResult]:
    """
    Detect 'open X and Y' patterns — handles mixed apps + websites.
    Recognises DIRECT_SITES keys alongside _APP_NAMES.
    Strips 'new tab in X' → treats as site/app X.
    Returns RouterResult or None.
    """
    if not re.match(_OPEN_VERBS, text, re.IGNORECASE):
        return None

    # Remove the leading verb
    body = re.sub(rf"^{_OPEN_VERBS}\s+", "", text, flags=re.IGNORECASE)

    # "new tab in X" → X  (keep the target)
    body = _NEW_TAB.sub("", body)
    # Remove any remaining standalone "new tab"
    body = _BARE_NEW_TAB.sub("", body)

    # Split on separators (but NOT 'with' — keep it as part of app name candidates)
    parts = re.split(r"\s*(?:,|\band\b|&|\+)\s*", body)

    apps: list[str] = []
    urls: list[str] = []

    for raw in parts:
        part = _PART_FILLER.sub("", raw.strip()).strip().lower()
        # Strip trailing 'with'
        part = re.sub(r"\s+with\s*$", "", part).strip()
        if not part:
            continue

        # Normalize via alias table
        part = _APP_ALIASES.get(part, part)

        if part in _APP_NAMES:
            if part not in apps:
                apps.append(part)
        elif part in DIRECT_SITES:
            url_val = DIRECT_SITES[part]
            if url_val not in urls:
                urls.append(url_val)
        # No match — ignore unknown token

    if not apps and not urls:
        return None

    # Ensure chrome is in the launch list when URLs are present
    if urls and "chrome" not in apps:
        apps.insert(0, "chrome")

    site_names = [k for k, v in DIRECT_SITES.items() if v in urls]
    desc_parts = ([f"apps: {', '.join(apps)}"] if apps else []) + \
                 ([f"sites: {', '.join(site_names)}"] if site_names else [])
    desc = "Opening " + "  ·  ".join(desc_parts)

    return RouterResult(
        matched=True,
        apps=apps,
        url=urls[0] if urls else None,
        urls=urls,
        description=desc,
    )


# ── File operation detection ──────────────────────────────────────────────────

# Matches a filename with a known extension (no spaces)
_FNAME = r'([\w\-.]+\.(?:py|js|ts|html|css|txt|md|json|yaml|yml|csv|xml|java|cpp|c|sh|bat|sql|r|go|rs|jsx|tsx|env|cfg|ini|toml|log))'

# Bare filename — word chars only, no extension required; used with name-indicator phrases
_BARE = r'([\w\-.]+)'

# Name-indicator phrases: "named", "called", "name called", "with name", "name as"
_NAME_IND = r'(?:name\s+called|name\s+as|named?\s+as|named?|called|with\s+name)'

# Trailing filler that can follow a bare filename in description context
_TAIL_FILLER = r'(?:\s+in\s+(?:that\s+)?(?:file|it))?'


def _infer_extension(description: str) -> str:
    """Infer a file extension from a natural-language description."""
    d = description.lower()
    # Check JS/TS FIRST to avoid "script" inside "javascript" matching Python
    if any(w in d for w in ("javascript", " js ", "node", "express", "react", "vue", "angular", "jquery")):
        return ".js"
    if any(w in d for w in ("typescript", " tsx", " ts ")):
        return ".ts"
    if any(w in d for w in ("html", "webpage", "web page", "<div", "template", "css")):
        return ".html"
    if any(w in d for w in ("json", "config ", "configuration")):
        return ".json"
    if any(w in d for w in ("sql", "query", "database", "select ", "insert ")):
        return ".sql"
    if any(w in d for w in ("shell", "bash", " sh ", "shell script")):
        return ".sh"
    if any(w in d for w in ("java ", "public static", "system.out")):
        return ".java"
    if any(w in d for w in ("c++", "cpp", "iostream", "#include")):
        return ".cpp"
    if any(w in d for w in ("markdown", " md ")):
        return ".md"
    # Python — check after JS so "javascript" doesn't match "script"
    if any(w in d for w in ("python", " py ", "function", "class", "def ", "import ", "print(")):
        return ".py"
    # Generic code/math keywords → default to Python
    if any(w in d for w in ("code", "program", "adding", "subtract", "multiply", "calculat", "sort", "search", "algorithm")):
        return ".py"
    return ".txt"


# All patterns: (regex, action_key)
_FILE_PATTERNS = [
    # CREATE BARE — "create a file name called hello and write adding two numbers..."
    #               "create a file called test with python code"
    (re.compile(
        rf'(?:create|make|new)\s+(?:a\s+)?(?:new\s+)?file\s+{_NAME_IND}\s+{_BARE}'
        rf'(?:\s+(?:and\s+)?(?:write|with|to\s+write|and\s+write|containing|having|add)\s+(.+?))?{_TAIL_FILLER}$',
        re.IGNORECASE), "create_bare"),

    # CREATE — "create a file named hello.py" / "create hello.py with python code..."
    (re.compile(
        rf'(?:create|make|new|write)\s+(?:a\s+)?(?:new\s+)?(?:file\s+)?(?:{_NAME_IND}\s+)?\s*{_FNAME}'
        rf'(?:\s+(?:with|and|write|that|which|containing|having)\s+(.+))?',
        re.IGNORECASE), "create"),

    # CREATE — "create a python file hello.py ..."
    (re.compile(
        rf'(?:create|make|new)\s+(?:a\s+)?(?:\w+\s+)?file\s+(?:{_NAME_IND}\s+)?\s*{_FNAME}'
        rf'(?:\s+(?:with|and|write|that|which|containing|having)\s+(.+))?',
        re.IGNORECASE), "create"),

    # WRITE — "write python code for X in hello.py" / "write hello.py with..."
    (re.compile(
        rf'write\s+(.+?)\s+(?:in(?:to)?|to)\s+(?:file\s+)?{_FNAME}',
        re.IGNORECASE), "create_desc_first"),

    # READ — "read hello.py" / "show me hello.py" / "display hello.py"
    (re.compile(
        rf'(?:read|show(?:\s+me)?|display|print|cat|view|open|summary|summarize|explain|describe)\s+(?:file\s+)?{_FNAME}',
        re.IGNORECASE), "read"),

    # READ — "summary what in hello.py" / "what's in hello.py" / "what is in hello.py"
    (re.compile(
        rf'(?:summary\s+(?:what\s+(?:is\s+)?(?:in\s+)?)?|summarize\s+(?:what\s+(?:is\s+)?(?:in\s+)?)?|what(?:\'s|\s+is|\s+are)\s+(?:in|inside)\s+(?:file\s+)?){_FNAME}',
        re.IGNORECASE), "read"),

    # READ — "what does hello.py do" / "what does hello.py contain"
    (re.compile(
        rf'what\s+does\s+{_FNAME}\s+(?:do|contain|have|say|include)[?!.]*',
        re.IGNORECASE), "read"),

    # UPDATE — "update hello.py add a print statement"
    (re.compile(
        rf'(?:update|modify|edit|change|fix|improve)\s+(?:file\s+)?{_FNAME}\s+(.+)',
        re.IGNORECASE), "update"),

    # UPDATE — "add X to hello.py" / "add a function to hello.py"
    (re.compile(
        rf'(?:add|append|insert)\s+(.+?)\s+(?:to|in(?:to)?)\s+(?:file\s+)?{_FNAME}',
        re.IGNORECASE), "append_desc_first"),

    # DELETE — "delete hello.py" / "remove file hello.py"
    (re.compile(
        rf'(?:delete|remove|erase|trash)\s+(?:file\s+)?{_FNAME}',
        re.IGNORECASE), "delete"),

    # RENAME — "rename hello.py to world.py"
    (re.compile(
        rf'rename\s+(?:file\s+)?{_FNAME}\s+(?:to|as)\s+{_FNAME}',
        re.IGNORECASE), "rename"),

    # LIST — "list files" / "list python files" / "show files in src"
    (re.compile(
        r'(?:list|show|ls)\s+(?:all\s+)?(?:(?:\w+)\s+)?files?(?:\s+in\s+(.+))?',
        re.IGNORECASE), "list"),
]


_FILLER_RE = re.compile(r'\s+in\s+(?:that\s+)?(?:file|it)\s*$', re.IGNORECASE)


def _clean_desc(desc: str) -> str:
    """Strip trailing filler phrases like 'in that file', 'in it'."""
    return _FILLER_RE.sub("", desc).strip() if desc else desc


def _detect_file_op(text: str) -> Optional[RouterResult]:
    """Try to detect a file operation in the input text."""
    for pattern, action_key in _FILE_PATTERNS:
        m = pattern.match(text.strip())
        if not m:
            continue

        groups = m.groups()

        if action_key == "create_bare":
            # groups[0] = bare filename (no extension), groups[1] = description
            bare = groups[0].strip() if groups[0] else None
            description = _clean_desc(groups[1].strip() if len(groups) > 1 and groups[1] else "")
            if bare:
                # Infer extension if not already present
                if "." not in bare:
                    ext = _infer_extension(description)
                    filename = bare + ext
                else:
                    filename = bare
                return RouterResult(
                    matched=True,
                    file_action="create",
                    filename=filename,
                    content_desc=description,
                    description=f"Create {filename}" + (f": {description[:50]}" if description else ""),
                )

        elif action_key == "create":
            filename = groups[0].strip() if groups[0] else None
            description = _clean_desc(groups[1].strip() if len(groups) > 1 and groups[1] else "")
            if filename:
                return RouterResult(
                    matched=True,
                    file_action="create",
                    filename=filename,
                    content_desc=description,
                    description=f"Create {filename}" + (f": {description[:50]}" if description else ""),
                )

        elif action_key == "create_desc_first":
            description = _clean_desc(groups[0].strip() if groups[0] else "")
            filename = groups[1].strip() if len(groups) > 1 and groups[1] else None
            if filename:
                return RouterResult(
                    matched=True,
                    file_action="create",
                    filename=filename,
                    content_desc=description,
                    description=f"Create {filename}: {description[:50]}",
                )

        elif action_key == "read":
            filename = groups[0].strip() if groups[0] else None
            if filename:
                return RouterResult(
                    matched=True,
                    file_action="read",
                    filename=filename,
                    description=f"Read {filename}",
                )

        elif action_key == "update":
            filename = groups[0].strip() if groups[0] else None
            instruction = groups[1].strip() if len(groups) > 1 and groups[1] else ""
            if filename:
                return RouterResult(
                    matched=True,
                    file_action="update",
                    filename=filename,
                    content_desc=instruction,
                    description=f"Update {filename}: {instruction[:50]}",
                )

        elif action_key == "append_desc_first":
            description = groups[0].strip() if groups[0] else ""
            filename = groups[1].strip() if len(groups) > 1 and groups[1] else None
            if filename:
                return RouterResult(
                    matched=True,
                    file_action="append",
                    filename=filename,
                    content_desc=description,
                    description=f"Append to {filename}: {description[:50]}",
                )

        elif action_key == "delete":
            filename = groups[0].strip() if groups[0] else None
            if filename:
                return RouterResult(
                    matched=True,
                    file_action="delete",
                    filename=filename,
                    description=f"Delete {filename}",
                )

        elif action_key == "rename":
            old_name = groups[0].strip() if groups[0] else None
            new_name = groups[1].strip() if len(groups) > 1 and groups[1] else None
            if old_name and new_name:
                return RouterResult(
                    matched=True,
                    file_action="rename",
                    filename=old_name,
                    new_filename=new_name,
                    description=f"Rename {old_name} → {new_name}",
                )

        elif action_key == "list":
            path = groups[0].strip() if groups[0] else "."
            return RouterResult(
                matched=True,
                file_action="list",
                filename=path,
                description=f"List files in {path}",
            )

    return None
