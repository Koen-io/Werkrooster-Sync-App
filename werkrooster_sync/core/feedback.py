"""Send user feedback to the developer via Web3Forms.

Web3Forms' API sits behind Cloudflare bot protection that challenges plain
HTTP clients (curl, urllib) at the TLS-fingerprint level — only real browsers
pass. ``curl_cffi`` impersonates Chrome's TLS fingerprint, so the desktop app
submits successfully, exactly like a browser-based form would.

The developer's email address is never present in the app or its traffic —
Web3Forms routes messages server-side using the public access key.
"""
from __future__ import annotations

import json
import urllib.request

from .updater import USER_AGENT, _ssl_context

_ENDPOINT = "https://api.web3forms.com/submit"
_ACCESS_KEY = "e8774a01-016e-498a-ad03-0075a0b631f6"


class FeedbackError(Exception):
    """Raised when the feedback cannot be sent."""


def _payload(name: str, message: str, email: str, app_version: str) -> dict:
    payload = {
        "access_key": _ACCESS_KEY,
        "subject": f"Werkrooster Sync — feedback van {name}",
        "from_name": "Werkrooster Sync",
        "name": name,
        "message": message,
        "app_version": app_version or "onbekend",
    }
    if email:
        payload["email"] = email
        payload["replyto"] = email
    return payload


def send_feedback(name: str, message: str, email: str = "", app_version: str = "") -> None:
    """Send *message* from *name* (optional *email*) to the developer."""
    name = (name or "").strip()
    message = (message or "").strip()
    email = (email or "").strip()
    if not name:
        raise FeedbackError("Vul je naam in.")
    if not message:
        raise FeedbackError("Vul je feedback of vraag in.")

    result = _post(_payload(name, message, email, app_version))
    if not result.get("success"):
        raise FeedbackError(result.get("message") or "Versturen mislukt.")


def _post(payload: dict) -> dict:
    """POST to Web3Forms, impersonating Chrome so Cloudflare lets it through.
    Falls back to urllib only where curl_cffi is unavailable (e.g. tests)."""
    try:
        from curl_cffi import requests as creq
    except ImportError:
        return _post_urllib(payload)
    try:
        resp = creq.post(_ENDPOINT, json=payload, impersonate="chrome", timeout=25)
        return resp.json()
    except Exception as exc:
        raise FeedbackError(
            f"Versturen mislukt — controleer je internetverbinding. ({exc})"
        ) from exc


def _post_urllib(payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise FeedbackError(
            f"Versturen mislukt — controleer je internetverbinding. ({exc})"
        ) from exc
