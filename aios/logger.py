"""
AIOS Logging System — Structured rotating file logger.
All modules import `log` from here.

Logs are written to ~/.aios/logs/aios-YYYY-MM-DD.log
Rotating: 5 MB per file, 5 backups kept.
Console: WARNING+ only (won't pollute the REPL).
"""
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime

_LOG_DIR = Path.home() / ".aios" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("aios")
    if logger.handlers:          # already configured (re-import guard)
        return logger

    logger.setLevel(logging.DEBUG)

    # ── Rotating file handler ─────────────────────────────────────────────
    log_file = _LOG_DIR / f"aios-{datetime.now().strftime('%Y-%m-%d')}.log"
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,   # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(module)s:%(lineno)d — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # ── Console handler — WARNING+ only ──────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("[AIOS %(levelname)s] %(message)s"))
    logger.addHandler(ch)

    return logger


log = _build_logger()
