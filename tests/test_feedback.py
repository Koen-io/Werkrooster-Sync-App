"""Tests for the feedback sender and dialog (network mocked)."""
from __future__ import annotations

import json
import os

import pytest

from werkrooster_sync.core import feedback
from werkrooster_sync.core.feedback import FeedbackError, _payload, send_feedback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_requires_name_and_message():
    # Validation happens before any network call.
    with pytest.raises(FeedbackError):
        send_feedback("", "hallo")
    with pytest.raises(FeedbackError):
        send_feedback("Koen", "   ")


def test_payload_has_access_key_not_email():
    p = _payload("Koen", "Top app!", "koen@voorbeeld.nl", "1.4.1")
    # Routing is by access key; the developer's address is never sent.
    assert p["access_key"] == "e8774a01-016e-498a-ad03-0075a0b631f6"
    assert p["name"] == "Koen"
    assert p["message"] == "Top app!"
    assert p["email"] == "koen@voorbeeld.nl"
    assert p["replyto"] == "koen@voorbeeld.nl"
    assert p["app_version"] == "1.4.1"
    assert "hotmail" not in json.dumps(p)


def test_payload_omits_empty_email():
    p = _payload("Anon", "Zonder mail", "", "1.0")
    assert "email" not in p
    assert "replyto" not in p


def test_send_success(monkeypatch):
    sent = {}
    monkeypatch.setattr(feedback, "_post", lambda payload: sent.update(payload) or {"success": True})
    send_feedback("Koen", "Werkt goed!", email="koen@x.nl", app_version="1.4.1")
    assert sent["name"] == "Koen"
    assert sent["access_key"] == "e8774a01-016e-498a-ad03-0075a0b631f6"


def test_send_raises_on_api_failure(monkeypatch):
    monkeypatch.setattr(feedback, "_post", lambda payload: {"success": False, "message": "nope"})
    with pytest.raises(FeedbackError, match="nope"):
        send_feedback("Koen", "test")


def test_urllib_fallback_posts_json(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"success": True}).encode()

    def fake_urlopen(req, timeout=0, context=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["ua"] = req.headers.get("User-agent")
        return _Resp()

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)
    result = feedback._post_urllib(_payload("Koen", "hoi", "", "1.0"))
    assert result == {"success": True}
    assert captured["url"] == "https://api.web3forms.com/submit"
    assert captured["body"]["message"] == "hoi"
    assert "Mozilla" in captured["ua"] or "WerkroosterSync" in captured["ua"]


def test_feedback_dialog_smoke():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication([])
    from werkrooster_sync.ui.feedback_dialog import FeedbackDialog

    dialog = FeedbackDialog()
    dialog.name_edit.setText("Koen")
    dialog.message_edit.setPlainText("Werkt goed!")
    dialog._show_success()
    labels = " ".join(l.text() for l in dialog.findChildren(QLabel))
    assert "Bedankt" in labels
    dialog.close()
