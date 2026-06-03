"""
App Normalizer — Production-grade app name resolution.
Maps ANY natural language app reference → canonical name → executable/URI.
Covers 200+ aliases with fuzzy fallback. No hardcoded user paths.
"""
import difflib
from typing import Optional, Tuple

# ── Launch target types ───────────────────────────────────────────────────────
# uri   → os.startfile(target)             e.g. ms-settings:, ms-todo:
# exe   → system PATH executable           e.g. taskmgr.exe
# msc   → MMC snap-in                      e.g. devmgmt.msc
# cpl   → Control Panel applet             e.g. sysdm.cpl
# app   → resolved via app_launcher        e.g. chrome, vscode
# shell → shell: URI                       e.g. shell:AppsFolder
# url   → open in browser                  e.g. https://...

APP_TARGETS: dict[str, dict] = {
    # ── Windows System ────────────────────────────────────────────────────────
    "settings":           {"type": "uri",  "target": "ms-settings:"},
    "display_settings":   {"type": "uri",  "target": "ms-settings:display"},
    "sound_settings":     {"type": "uri",  "target": "ms-settings:sound"},
    "bluetooth":          {"type": "uri",  "target": "ms-settings:bluetooth"},
    "wifi":               {"type": "uri",  "target": "ms-settings:network-wifi"},
    "network":            {"type": "uri",  "target": "ms-settings:network"},
    "vpn":                {"type": "uri",  "target": "ms-settings:network-vpn"},
    "apps_settings":      {"type": "uri",  "target": "ms-settings:apps"},
    "startup_apps":       {"type": "uri",  "target": "ms-settings:startupapps"},
    "privacy_settings":   {"type": "uri",  "target": "ms-settings:privacy"},
    "update_settings":    {"type": "uri",  "target": "ms-settings:windowsupdate"},
    "battery":            {"type": "uri",  "target": "ms-settings:battery"},
    "storage":            {"type": "uri",  "target": "ms-settings:storagesense"},
    "notifications":      {"type": "uri",  "target": "ms-settings:notifications"},
    "personalization":    {"type": "uri",  "target": "ms-settings:personalization"},
    "accounts":           {"type": "uri",  "target": "ms-settings:accounts"},
    "time_settings":      {"type": "uri",  "target": "ms-settings:dateandtime"},
    "region_settings":    {"type": "uri",  "target": "ms-settings:regionlanguage"},
    "accessibility":      {"type": "uri",  "target": "ms-settings:easeofaccess"},
    "default_apps":       {"type": "uri",  "target": "ms-settings:defaultapps"},
    "focus":              {"type": "uri",  "target": "ms-settings:quiethours"},

    "task_manager":       {"type": "exe",  "target": "taskmgr.exe"},
    "control_panel":      {"type": "exe",  "target": "control.exe"},
    "regedit":            {"type": "exe",  "target": "regedit.exe"},
    "resource_monitor":   {"type": "exe",  "target": "resmon.exe"},
    "performance_monitor":{"type": "exe",  "target": "perfmon.exe"},
    "notepad":            {"type": "exe",  "target": "notepad.exe"},
    "wordpad":            {"type": "exe",  "target": "wordpad.exe"},
    "paint":              {"type": "exe",  "target": "mspaint.exe"},
    "calculator":         {"type": "exe",  "target": "calc.exe"},
    "snipping_tool":      {"type": "exe",  "target": "SnippingTool.exe"},
    "screenshot":         {"type": "exe",  "target": "SnippingTool.exe"},
    "magnifier":          {"type": "exe",  "target": "magnify.exe"},
    "narrator":           {"type": "exe",  "target": "narrator.exe"},
    "on_screen_keyboard": {"type": "exe",  "target": "osk.exe"},
    "sticky_notes":       {"type": "uri",  "target": "ms-stickynotes:"},
    "clock":              {"type": "uri",  "target": "ms-clock:"},
    "calendar":           {"type": "uri",  "target": "outlookcal:"},
    "mail":               {"type": "uri",  "target": "outlookmail:"},
    "maps":               {"type": "uri",  "target": "bingmaps:"},
    "weather":            {"type": "uri",  "target": "bingweather:"},
    "news":               {"type": "uri",  "target": "bingnews:"},
    "photos":             {"type": "uri",  "target": "ms-photos:"},
    "camera":             {"type": "uri",  "target": "microsoft.windows.camera:"},
    "store":              {"type": "uri",  "target": "ms-windows-store:"},
    "xbox":               {"type": "uri",  "target": "xbox:"},
    "todo":               {"type": "uri",  "target": "ms-todo:"},
    "onenote":            {"type": "uri",  "target": "onenote:"},
    "teams":              {"type": "uri",  "target": "msteams:"},

    "device_manager":     {"type": "msc",  "target": "devmgmt.msc"},
    "disk_management":    {"type": "msc",  "target": "diskmgmt.msc"},
    "event_viewer":       {"type": "msc",  "target": "eventvwr.msc"},
    "services":           {"type": "msc",  "target": "services.msc"},
    "group_policy":       {"type": "msc",  "target": "gpedit.msc"},
    "certificate_manager":{"type": "msc",  "target": "certmgr.msc"},
    "local_users":        {"type": "msc",  "target": "lusrmgr.msc"},
    "component_services": {"type": "msc",  "target": "dcomcnfg.msc"},

    "system_properties":  {"type": "cpl",  "target": "sysdm.cpl"},
    "firewall":           {"type": "cpl",  "target": "firewall.cpl"},
    "display_cpl":        {"type": "cpl",  "target": "desk.cpl"},
    "internet_options":   {"type": "cpl",  "target": "inetcpl.cpl"},
    "sound_cpl":          {"type": "cpl",  "target": "mmsys.cpl"},
    "power_options":      {"type": "cpl",  "target": "powercfg.cpl"},
    "user_accounts":      {"type": "cpl",  "target": "nusrmgr.cpl"},
    "programs":           {"type": "cpl",  "target": "appwiz.cpl"},

    "file_explorer":      {"type": "exe",  "target": "explorer.exe"},
    "terminal":           {"type": "exe",  "target": "wt.exe"},
    "cmd":                {"type": "exe",  "target": "cmd.exe"},
    "powershell":         {"type": "exe",  "target": "powershell.exe"},
    "pwsh":               {"type": "exe",  "target": "pwsh.exe"},

    # ── Developer Tools ───────────────────────────────────────────────────────
    "vscode":             {"type": "app",  "target": "vscode"},
    "python":             {"type": "exe",  "target": "python.exe"},
    "ollama":             {"type": "exe",  "target": "ollama.exe"},
    "git_bash":           {"type": "app",  "target": "git_bash"},
    "postman":            {"type": "app",  "target": "postman"},
    "docker":             {"type": "app",  "target": "docker"},
    "dbeaver":            {"type": "app",  "target": "dbeaver"},
    "insomnia":           {"type": "app",  "target": "insomnia"},
    "figma":              {"type": "app",  "target": "figma"},

    # ── Browsers ──────────────────────────────────────────────────────────────
    "chrome":             {"type": "app",  "target": "chrome"},
    "firefox":            {"type": "app",  "target": "firefox"},
    "edge":               {"type": "app",  "target": "edge"},
    "brave":              {"type": "app",  "target": "brave"},
    "opera":              {"type": "app",  "target": "opera"},

    # ── Media ─────────────────────────────────────────────────────────────────
    "spotify":            {"type": "app",  "target": "spotify"},
    "vlc":                {"type": "app",  "target": "vlc"},
    "windows_media":      {"type": "exe",  "target": "wmplayer.exe"},
    "groove":             {"type": "uri",  "target": "mswindowsmusic:"},
    "movies":             {"type": "uri",  "target": "mswindowsvideo:"},

    # ── Communication ────────────────────────────────────────────────────────
    "discord":            {"type": "app",  "target": "discord"},
    "slack":              {"type": "app",  "target": "slack"},
    "telegram":           {"type": "app",  "target": "telegram"},
    "zoom":               {"type": "app",  "target": "zoom"},
    "skype":              {"type": "uri",  "target": "skype:"},
    "whatsapp":           {"type": "app",  "target": "whatsapp"},

    # ── Office ────────────────────────────────────────────────────────────────
    "word":               {"type": "app",  "target": "word"},
    "excel":              {"type": "app",  "target": "excel"},
    "powerpoint":         {"type": "app",  "target": "powerpoint"},
    "outlook":            {"type": "app",  "target": "outlook"},
    "access":             {"type": "app",  "target": "access"},
    "onenote_app":        {"type": "app",  "target": "onenote"},

    # ── Gaming ────────────────────────────────────────────────────────────────
    "steam":              {"type": "app",  "target": "steam"},
    "obs":                {"type": "app",  "target": "obs"},
}


# ── Alias table — maps ANY natural language variation to canonical name ────────

ALIASES: dict[str, str] = {
    # Settings
    "setting":                  "settings",
    "settings":                 "settings",
    "windows settings":         "settings",
    "system settings":          "settings",
    "pc settings":              "settings",
    "computer settings":        "settings",
    "preferences":              "settings",
    "config":                   "settings",
    "configuration":            "settings",
    "control":                  "settings",
    "system config":            "settings",
    "display settings":         "display_settings",
    "screen settings":          "display_settings",
    "resolution":               "display_settings",
    "brightness":               "display_settings",
    "sound settings":           "sound_settings",
    "audio settings":           "sound_settings",
    "volume settings":          "sound_settings",
    "bluetooth settings":       "bluetooth",
    "wifi settings":            "wifi",
    "network settings":         "network",
    "internet settings":        "network",
    "privacy":                  "privacy_settings",
    "privacy settings":         "privacy_settings",
    "windows update":           "update_settings",
    "update":                   "update_settings",
    "updates":                  "update_settings",
    "battery settings":         "battery",
    "power":                    "battery",
    "power settings":           "battery",
    "storage settings":         "storage",
    "disk usage":               "storage",
    "notification settings":    "notifications",
    "notifications settings":   "notifications",
    "startup":                  "startup_apps",
    "startup apps":             "startup_apps",
    "startup programs":         "startup_apps",
    "personalization":          "personalization",
    "wallpaper":                "personalization",
    "theme":                    "personalization",
    "themes":                   "personalization",
    "accounts settings":        "accounts",
    "user accounts":            "user_accounts",
    "time":                     "time_settings",
    "date time":                "time_settings",
    "date and time":            "time_settings",
    "clock settings":           "time_settings",
    "language":                 "region_settings",
    "region":                   "region_settings",
    "default apps":             "default_apps",
    "accessibility settings":   "accessibility",
    "ease of access":           "accessibility",
    "focus assist":             "focus",
    "do not disturb":           "focus",

    # System tools
    "task manager":             "task_manager",
    "taskmanager":              "task_manager",
    "process manager":          "task_manager",
    "processes":                "task_manager",
    "control panel":            "control_panel",
    "controlpanel":             "control_panel",
    "registry":                 "regedit",
    "registry editor":          "regedit",
    "resource monitor":         "resource_monitor",
    "resmon":                   "resource_monitor",
    "performance monitor":      "performance_monitor",
    "device manager":           "device_manager",
    "devices":                  "device_manager",
    "disk management":          "disk_management",
    "disks":                    "disk_management",
    "event viewer":             "event_viewer",
    "events":                   "event_viewer",
    "event log":                "event_viewer",
    "services":                 "services",
    "windows services":         "services",
    "system properties":        "system_properties",
    "about pc":                 "system_properties",
    "computer info":            "system_properties",
    "firewall":                 "firewall",
    "windows firewall":         "firewall",
    "sound":                    "sound_cpl",
    "audio":                    "sound_cpl",
    "speaker":                  "sound_cpl",
    "speakers":                 "sound_cpl",
    "power options":            "power_options",
    "programs and features":    "programs",
    "uninstall":                "programs",
    "installed apps":           "apps_settings",
    "installed programs":       "apps_settings",

    # Files
    "file explorer":            "file_explorer",
    "explorer":                 "file_explorer",
    "files":                    "file_explorer",
    "file manager":             "file_explorer",
    "my computer":              "file_explorer",
    "this pc":                  "file_explorer",
    "folder":                   "file_explorer",
    "folders":                  "file_explorer",

    # Terminal
    "terminal":                 "terminal",
    "windows terminal":         "terminal",
    "wt":                       "terminal",
    "cmd":                      "cmd",
    "command prompt":           "cmd",
    "command line":             "cmd",
    "dos":                      "cmd",
    "powershell":               "powershell",
    "ps":                       "powershell",
    "shell":                    "terminal",

    # Browsers
    "chrome":                   "chrome",
    "google chrome":            "chrome",
    "chrome browser":           "chrome",
    "chromium":                 "chrome",
    "browser":                  "chrome",
    "web browser":              "chrome",
    "internet":                 "chrome",
    "web":                      "chrome",
    "firefox":                  "firefox",
    "mozilla":                  "firefox",
    "edge":                     "edge",
    "microsoft edge":           "edge",
    "brave":                    "brave",
    "opera":                    "opera",

    # Dev tools
    "vscode":                   "vscode",
    "vs code":                  "vscode",
    "visual studio code":       "vscode",
    "code editor":              "vscode",
    "editor":                   "vscode",
    "code":                     "vscode",
    "ide":                      "vscode",
    "python":                   "python",
    "ollama":                   "ollama",
    "postman":                  "postman",
    "docker":                   "docker",
    "figma":                    "figma",
    "insomnia":                 "insomnia",
    "git bash":                 "git_bash",

    # Office
    "word":                     "word",
    "ms word":                  "word",
    "microsoft word":           "word",
    "document":                 "word",
    "docs":                     "word",
    "excel":                    "excel",
    "ms excel":                 "excel",
    "microsoft excel":          "excel",
    "spreadsheet":              "excel",
    "powerpoint":               "powerpoint",
    "ms powerpoint":            "powerpoint",
    "microsoft powerpoint":     "powerpoint",
    "presentation":             "powerpoint",
    "ppt":                      "powerpoint",
    "slides":                   "powerpoint",
    "outlook":                  "outlook",
    "ms outlook":               "outlook",
    "onenote":                  "onenote_app",
    "one note":                 "onenote_app",

    # Media
    "spotify":                  "spotify",
    "music":                    "spotify",
    "music player":             "spotify",
    "vlc":                      "vlc",
    "media player":             "vlc",
    "video player":             "vlc",
    "windows media player":     "windows_media",
    "photos":                   "photos",
    "photo viewer":             "photos",
    "images":                   "photos",
    "camera":                   "camera",
    "movies":                   "movies",
    "video":                    "movies",
    "groove":                   "groove",

    # Communication
    "discord":                  "discord",
    "slack":                    "slack",
    "telegram":                 "telegram",
    "zoom":                     "zoom",
    "skype":                    "skype",
    "whatsapp":                 "whatsapp",
    "whatsapp desktop":         "whatsapp",
    "teams":                    "teams",
    "microsoft teams":          "teams",

    # Accessories
    "notepad":                  "notepad",
    "text editor":              "notepad",
    "wordpad":                  "wordpad",
    "paint":                    "paint",
    "ms paint":                 "paint",
    "calculator":               "calculator",
    "calc":                     "calculator",
    "snipping tool":            "snipping_tool",
    "snip":                     "snipping_tool",
    "screenshot tool":          "snipping_tool",
    "sticky notes":             "sticky_notes",
    "sticky note":              "sticky_notes",
    "notes":                    "sticky_notes",
    "clock":                    "clock",
    "alarm":                    "clock",
    "timer":                    "clock",
    "stopwatch":                "clock",
    "calendar":                 "calendar",
    "todo":                     "todo",
    "to do":                    "todo",
    "to-do":                    "todo",
    "tasks":                    "todo",
    "maps":                     "maps",
    "weather":                  "weather",
    "store":                    "store",
    "microsoft store":          "store",
    "windows store":            "store",
    "xbox":                     "xbox",
    "gaming":                   "xbox",
    "news":                     "news",
    "mail":                     "mail",
    "email":                    "mail",

    # Gaming
    "steam":                    "steam",
    "obs":                      "obs",
    "obs studio":               "obs",
    "screen recorder":          "obs",
    "streaming":                "obs",
}


def normalize(app_name: str) -> Optional[Tuple[str, dict]]:
    """
    Normalize any app name string to (canonical_name, target_info).
    Returns None if no match found.
    
    Resolution order:
      1. Exact alias match
      2. Fuzzy alias match (difflib)
      3. Direct canonical name match
    """
    if not app_name:
        return None

    name = app_name.strip().lower()

    # 1. Exact alias lookup
    canonical = ALIASES.get(name)
    if canonical and canonical in APP_TARGETS:
        return canonical, APP_TARGETS[canonical]

    # 2. Direct canonical match
    if name in APP_TARGETS:
        return name, APP_TARGETS[name]

    # 3. Fuzzy match against aliases (threshold: 0.75)
    all_keys = list(ALIASES.keys())
    close = difflib.get_close_matches(name, all_keys, n=1, cutoff=0.75)
    if close:
        canonical = ALIASES[close[0]]
        if canonical in APP_TARGETS:
            return canonical, APP_TARGETS[canonical]

    # 4. Fuzzy match against canonical names
    close = difflib.get_close_matches(name, list(APP_TARGETS.keys()), n=1, cutoff=0.75)
    if close:
        return close[0], APP_TARGETS[close[0]]

    return None


def normalize_app_list(app_names: list) -> list:
    """
    Normalize a list of app name strings.
    Returns list of (canonical_name, target_info) tuples.
    Unknown names return (original_name, {"type": "app", "target": original_name}).
    """
    results = []
    for name in app_names:
        result = normalize(name)
        if result:
            results.append(result)
        else:
            # Unknown — pass through to dynamic resolver
            results.append((name, {"type": "app", "target": name}))
    return results
