"""Backend discovery: which calendar backends exist on this machine."""
from __future__ import annotations

import sys

from .base import CalendarBackend
from .ics_export import IcsExportBackend
from .macos_calendar import MacCalendarBackend
from .outlook_windows import OutlookBackend


def all_backends() -> list[CalendarBackend]:
    """Backends usable on the current platform, best option first."""
    backends: list[CalendarBackend] = []
    mac = MacCalendarBackend()
    if mac.is_available():
        backends.append(mac)
    win = OutlookBackend()
    if win.is_available():
        backends.append(win)
    backends.append(IcsExportBackend())
    return backends


def get_backend(backend_id: str) -> CalendarBackend:
    """Return the backend for *backend_id*, or the platform default."""
    backends = all_backends()
    for b in backends:
        if b.id == backend_id:
            return b
    return backends[0]


def default_backend_id() -> str:
    if sys.platform == "darwin":
        return MacCalendarBackend.id
    if sys.platform == "win32":
        return OutlookBackend.id
    return IcsExportBackend.id
