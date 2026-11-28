"""The app's log file ("logboek").

One small rotating text file in the user's settings directory. It records
what the app did and what went wrong, so a problem can be looked into
afterwards. Rule for everything that is logged: counts, dates and error
texts only — never roster contents, titles or calendar names.
"""
from __future__ import annotations

import logging
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import settings

log = logging.getLogger("werkrooster_sync")


def log_path() -> Path:
    return settings._user_config_dir() / "logboek.txt"


def setup(on_crash=None) -> None:
    """Start logging to the file and record every uncaught error.
    ``on_crash(message)`` is called (if given) to tell the user."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=300_000, backupCount=1, encoding="utf-8"
        )
    except OSError:
        return  # no log file is no reason not to start
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    def crashed(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        log.critical("Onverwachte fout", exc_info=(exc_type, exc, tb))
        if on_crash:
            try:
                on_crash(f"{exc_type.__name__}: {exc}")
            except Exception:  # the messenger must never crash the crash handler
                pass

    sys.excepthook = crashed
    threading.excepthook = lambda args: crashed(
        args.exc_type, args.exc_value, args.exc_traceback
    )


def tail(lines: int = 120) -> str:
    """The last *lines* lines of the log, for sending along with feedback.
    The user's home directory is replaced by "~" so the account name on the
    computer does not travel along."""
    try:
        text = log_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(schoon(r) for r in text.splitlines()[-lines:])


def schoon(regel: str) -> str:
    """Haal uit een logregel wat iets over de persoon kan zeggen: de thuismap
    (ook als C:\\Users\\NAAM~1 of met schuine strepen) en tekst tussen
    aanhalingstekens (agendanamen en titels in foutmeldingen van de agenda)."""
    regel = regel.replace(str(Path.home()), "~")
    regel = re.sub(r"(?i)[a-z]:[\\/]+(users|documents and settings)[\\/]+[^\\/\s]+", "~", regel)
    regel = re.sub(r"[\\/]+(Users|home)[\\/]+[^\\/\s]+", "~", regel)
    regel = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’', '"…"', regel)
    regel = re.sub(r"(?<!\w)'[^'\n]*'(?!\w)", '"…"', regel)
    return regel[:500]
