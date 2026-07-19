"""Tests for the feedback sender and dialog (network mocked)."""
from __future__ import annotations

import io
import json
import os

import pytest

from werkrooster_sync.core import feedback
from werkrooster_sync.core.feedback import FeedbackError, send_feedback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_requires_name_and_message():
    with pytest.raises(FeedbackError):
        send_feedback("", "hallo")
    with pytest.raises(FeedbackError):
        send_feedback("Koen", "   ")


def test_send_posts_access_key_not_email(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0, context=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(json.dumps({"success": True}).encode("utf-8"))

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)
    send_feedback("Koen", "Top app!", email="koen@voorbeeld.nl", app_version="1.3.3")

    assert captured["url"] == "https://api.web3forms.com/submit"
    body = captured["body"]
    # The routing is by access key; the developer's address is never sent.
    assert body["access_key"] == "e8774a01-016e-498a-ad03-0075a0b631f6"
    assert body["name"] == "Koen"
    assert body["message"] == "Top app!"
    assert body["email"] == "koen@voorbeeld.nl"
    assert body["app_version"] == "1.3.3"
    assert "hotmail" not in json.dumps(body)


def test_send_optional_email_omitted(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0, context=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(json.dumps({"success": True}).encode("utf-8"))

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)
    send_feedback("Anon", "Zonder mail")
    assert "email" not in captured["body"]


def test_send_raises_on_api_failure(monkeypatch):
    def fake_urlopen(req, timeout=0, context=None):
        return _FakeResp(json.dumps({"success": False, "message": "nope"}).encode())

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(FeedbackError, match="nope"):
        send_feedback("Koen", "test")


def test_feedback_dialog_smoke(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from werkrooster_sync.ui.feedback_dialog import FeedbackDialog

    from PySide6.QtWidgets import QLabel

    dialog = FeedbackDialog()
    dialog.name_edit.setText("Koen")
    dialog.message_edit.setPlainText("Werkt goed!")
    # Success view swaps the form out for the thank-you confirmation.
    dialog._show_success()
    labels = " ".join(l.text() for l in dialog.findChildren(QLabel))
    assert "Bedankt" in labels
    dialog.close()
