"""
AI-Powered Shell — Translates natural language to shell commands and executes them.
Intent-driven terminal. User describes what they want, AI figures out the commands.
Cross-platform: Windows and Linux.
"""
import re
import subprocess
import os
import sys
import time
from pathlib import Path
from typing import Optional
from aios.llm_engine import translate_to_shell
from aios.context_memory import memory
from aios.utils.platform import IS_WINDOWS, IS_LINUX
from aios.logger import log

# ── File-write detection helpers ─────────────────────────────────────────────
_FILENAME_RE = re.compile(r'\b([\w][\w\-]*\.[a-zA-Z]{1,6})\b')
_CODE_EXTS = {
    '.py', '.js', '.ts', '.html', '.css', '.sh', '.bat', '.rb', '.go',
    '.java', '.c', '.cpp', '.rs', '.json', '.yaml', '.yml', '.toml', '.md', '.txt',
}
_WRITE_TRIGGERS = ('create', 'make', 'write', 'generate')

def _detect_file_write(natural_input: str) -> Optional[str]:
    """Return filename if the input looks like 'create/write a file with content'."""
    nl = natural_input.lower()
    if not any(t in nl for t in _WRITE_TRIGGERS):
        return None
    m = _FILENAME_RE.search(natural_input)
    if m:
        fname = m.group(1)
        if Path(fname).suffix.lower() in _CODE_EXTS:
            return fname
    return None

# ── Platform-aware direct command map ────────────────────────────────────────
# Each value is (windows_cmd, linux_cmd)
_CMD_TABLE: dict[str, tuple[str, str]] = {
    "pwd":              ("cd",                                         "pwd"),
    "where am i":       ("cd",                                         "pwd"),
    "current directory":("cd",                                         "pwd"),
    "list files":       ("dir",                                        "ls -la"),
    "show files":       ("dir",                                        "ls -la"),
    "list all files":   ("dir /a",                                     "ls -la"),
    "clear":            ("cls",                                        "clear"),
    "disk space":       ("wmic logicaldisk get size,freespace,caption","df -h"),
    "ip address":       ("ipconfig",                                   "ip addr show || ifconfig"),
    "running processes":("tasklist",                                   "ps aux"),
    "system info":      ('systeminfo | findstr /B /C:"OS" /C:"Total Physical Memory"',
                         "uname -a && free -h"),
    "cpu usage":        ("wmic cpu get loadpercentage",                "top -bn1 | grep 'Cpu(s)'"),
    "memory usage":     ("wmic OS get TotalVisibleMemorySize,FreePhysicalMemory",
                         "free -h"),
    "environment":      ("set",                                        "env"),
    "whoami":           ("whoami",                                     "whoami"),
    "date":             ("date /t",                                    "date"),
    "uptime":           ("net stats workstation | findstr Statistics", "uptime"),
    "network":          ("ipconfig /all",                              "ip addr && ip route"),
    "open ports":       ("netstat -an",                                "ss -tulnp || netstat -tulnp"),
    "installed python": ("python --version",                          "python3 --version"),
}

def _dc(key: str) -> str:
    """Return the platform-appropriate command for a DIRECT_COMMANDS key."""
    win, lin = _CMD_TABLE[key]
    return win if IS_WINDOWS else lin

# Build the DIRECT_COMMANDS dict for this platform
DIRECT_COMMANDS: dict[str, str] = {k: _dc(k) for k in _CMD_TABLE}

# ── Dangerous patterns — covers both platforms ────────────────────────────────
DANGEROUS_PATTERNS = [
    # Windows destructive
    "format ", "del /f", "rmdir /s", "rd /s",
    "reg delete", "cipher /w", "bcdedit",
    # Linux destructive
    "rm -rf", "rm -fr", "dd if=", "mkfs.", "fdisk",
    ":(){ :|:& };:",   # fork bomb
    # Cross-platform
    "drop table", "drop database",
    "shutdown", "reboot", "poweroff", "halt",
]


class AIShell:
    """
    Cognitive shell that understands intent and translates to commands.
    Maintains working directory state across commands.
    Cross-platform: Windows + Linux.
    """

    def __init__(self, progress_callback=None):
        self.cwd = str(Path.home())
        self.history = []
        self.progress = progress_callback or print
        self.env = os.environ.copy()
        self._os_type = "windows" if IS_WINDOWS else "linux"

    def run(self, natural_input: str, dry_run: bool = False) -> dict:
        """
        Process natural language input, translate to shell commands, execute.
        Returns: dict with commands, outputs, errors
        """
        nl = natural_input.strip().lower()

        # Check for "create file with content" — bypass shell echo commands
        target_file = _detect_file_write(natural_input)
        if target_file:
            return self._handle_file_write(natural_input, target_file)

        # Check for direct mappings first (no LLM needed)
        if nl in DIRECT_COMMANDS:
            commands = [DIRECT_COMMANDS[nl]]
        elif nl.startswith("cd ") or nl.startswith("go to "):
            target = nl.replace("cd ", "").replace("go to ", "").strip()
            commands = [f"cd /d {target}" if IS_WINDOWS else f"cd '{target}'"]
        else:
            self.progress(f"  [Shell] Translating: '{natural_input}'...")
            commands = translate_to_shell(natural_input, os_type=self._os_type)

        # Safety check
        for cmd in commands:
            for pattern in DANGEROUS_PATTERNS:
                if pattern in cmd.lower():
                    log.warning("Shell: blocked dangerous pattern '%s' in: %s", pattern, cmd)
                    return {
                        "commands": commands,
                        "blocked": True,
                        "reason": f"Dangerous pattern detected: '{pattern}'. Confirm manually.",
                        "outputs": [],
                        "errors": []
                    }

        if dry_run:
            return {"commands": commands, "dry_run": True, "outputs": [], "errors": []}

        results = []
        for cmd in commands:
            result = self._execute_command(cmd)
            results.append(result)
            memory.log_command(cmd, result.get("stdout", ""))
            if result.get("new_cwd"):
                self.cwd = result["new_cwd"]

        self.history.append({"input": natural_input, "commands": commands, "results": results})
        return {"commands": commands, "results": results, "cwd": self.cwd, "blocked": False}

    def _execute_command(self, command: str) -> dict:
        """Execute a single shell command, cross-platform."""
        t_start = time.time()
        cmd_stripped = command.strip()

        # Handle 'cd' to track working directory
        cd_prefix = ("cd /d " if IS_WINDOWS else "cd ") if IS_WINDOWS else "cd "
        if cmd_stripped.lower().startswith("cd "):
            parts   = cmd_stripped.split(None, 2 if IS_WINDOWS else 1)
            target  = parts[-1].strip().strip("'\"")
            if not os.path.isabs(target):
                target = os.path.join(self.cwd, target)
            target = os.path.normpath(target)
            if os.path.isdir(target):
                self.cwd = target
                return {"cmd": command, "stdout": f"Changed to: {self.cwd}",
                        "stderr": "", "returncode": 0, "new_cwd": self.cwd, "time_ms": 0}
            return {"cmd": command, "stdout": "", "stderr": f"Directory not found: {target}",
                    "returncode": 1, "new_cwd": None, "time_ms": 0}

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=30,
                env=self.env,
            )
            elapsed = round((time.time() - t_start) * 1000)
            log.debug("Shell: [%dms rc=%d] %s", elapsed, proc.returncode, command[:80])
            return {
                "cmd":        command,
                "stdout":     proc.stdout.strip(),
                "stderr":     proc.stderr.strip(),
                "returncode": proc.returncode,
                "new_cwd":    None,
                "time_ms":    elapsed,
            }
        except subprocess.TimeoutExpired:
            return {"cmd": command, "stdout": "", "stderr": "Timed out after 30s",
                    "returncode": -1, "new_cwd": None, "time_ms": 30000}
        except Exception as e:
            log.error("Shell: error executing '%s': %s", command[:60], e)
            return {"cmd": command, "stdout": "", "stderr": str(e),
                    "returncode": -1, "new_cwd": None, "time_ms": 0}

    def _handle_file_write(self, natural_input: str, filename: str) -> dict:
        """Create a file by generating content via LLM and writing it with Python I/O."""
        from aios.llm_engine import generate_file_content
        filepath = os.path.join(self.cwd, filename)
        self.progress(f"  [Shell] Generating content for '{filename}'...")
        content = generate_file_content(natural_input, filename)
        if content.startswith("ERROR:"):
            return {
                "commands": [f"# create {filename}"],
                "results": [{"cmd": f"create {filename}", "stdout": "",
                             "stderr": content, "returncode": 1,
                             "new_cwd": None, "time_ms": 0}],
                "cwd": self.cwd, "blocked": False,
            }
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(content)
            log.info("Shell: created '%s' (%d bytes)", filepath, len(content))
            preview = content[:500] + ("\n...[truncated]" if len(content) > 500 else "")
            return {
                "commands": [f"# write {filename}"],
                "results": [{"cmd": f"create {filename}",
                             "stdout": f"Created '{filename}' ({len(content)} bytes)\n\n{preview}",
                             "stderr": "", "returncode": 0,
                             "new_cwd": None, "time_ms": 0}],
                "cwd": self.cwd, "blocked": False,
            }
        except OSError as e:
            log.error("Shell: failed to write '%s': %s", filepath, e)
            return {
                "commands": [f"# write {filename}"],
                "results": [{"cmd": f"create {filename}", "stdout": "",
                             "stderr": str(e), "returncode": 1,
                             "new_cwd": None, "time_ms": 0}],
                "cwd": self.cwd, "blocked": False,
            }

    def interactive_session(self):
        """Run an interactive AI shell session."""
        print("\n" + "="*60)
        print("  AIOS AI Shell — Type natural language or commands")
        print("  Type 'exit' to return to main AIOS")
        print("="*60)
        print(f"  cwd: {self.cwd}\n")

        while True:
            try:
                user_input = input(f"aios-shell [{self.cwd.split(os.sep)[-1]}]> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[Shell] Exiting AI Shell...")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "back"):
                print("[Shell] Returning to AIOS...")
                break

            result = self.run(user_input)

            # Display translated commands
            if result.get("commands"):
                print(f"\n  Commands: {' && '.join(result['commands'])}")

            if result.get("blocked"):
                print(f"\n  ⚠ BLOCKED: {result['reason']}")
                continue

            if result.get("dry_run"):
                print("  (dry run — not executed)")
                continue

            # Display results
            for r in result.get("results", []):
                if r.get("stdout"):
                    print(f"\n{r['stdout']}")
                if r.get("stderr"):
                    print(f"\n  Error: {r['stderr']}")
            
            print(f"\n  cwd: {result.get('cwd', self.cwd)}")
