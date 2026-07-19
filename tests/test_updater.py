"""Tests for the auto-update logic (no network involved)."""
from __future__ import annotations

import os

import pytest

from werkrooster_sync.core.updater import (
    UpdateInfo,
    is_newer,
    pick_asset,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ASSETS = [
    {"name": "WerkroosterSync-macOS.zip",
     "browser_download_url": "https://example/mac.zip", "size": 41_000_000},
    {"name": "WerkroosterSync.exe",
     "browser_download_url": "https://example/win.exe", "size": 58_000_000},
]


def test_version_comparison():
    assert is_newer("1.3.0", "1.2.0")
    assert is_newer("2.0.0", "1.9.9")
    assert is_newer("1.2.10", "1.2.9")
    assert not is_newer("1.2.0", "1.2.0")
    assert not is_newer("1.1.9", "1.2.0")
    # A dev build or garbage never triggers an update prompt by comparison.
    assert not is_newer("garbage", "1.2.0")
    assert is_newer("1.3.0", "0.0.0-dev") is True


def test_pick_asset_per_platform():
    assert pick_asset(ASSETS, "darwin")["name"] == "WerkroosterSync-macOS.zip"
    assert pick_asset(ASSETS, "win32")["name"] == "WerkroosterSync.exe"
    assert pick_asset([], "darwin") is None
    assert pick_asset(ASSETS, "linux") is None


def test_ssl_context_uses_certifi_bundle():
    import certifi

    from werkrooster_sync.core.updater import _ssl_context

    ctx = _ssl_context()
    # A CA store must actually be loaded (this is what fails in a frozen
    # app without certifi: no local issuer certificates).
    assert ctx.cert_store_stats()["x509_ca"] > 0
    assert certifi.where()


def test_up_to_date_dialog_smoke():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from werkrooster_sync.ui.update_dialog import UpToDateDialog

    dialog = UpToDateDialog("1.3.1")
    assert dialog.windowTitle() == "Up-to-date"
    from PySide6.QtWidgets import QLabel

    texts = " ".join(l.text() for l in dialog.findChildren(QLabel))
    assert "v1.3.1" in texts
    dialog.close()


def test_update_dialog_smoke():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from werkrooster_sync.ui.update_dialog import UpdateDialog

    update = UpdateInfo(
        version="9.9.9",
        notes="## Downloads\n- **macOS**: nieuwe versie\n- Windows: idem",
        asset_name="WerkroosterSync-macOS.zip",
        asset_url="https://example/mac.zip",
        asset_size=41_000_000,
    )
    dialog = UpdateDialog(update, current_version="1.2.0")
    # Progress formatting path
    dialog._on_progress(20_500_000, 41_000_000)
    assert dialog.progress.value() == 50
    assert "MB" in dialog.status.text()
    dialog._on_failed("Download mislukt: test")
    assert dialog.install_btn.isEnabled()
    dialog.close()
