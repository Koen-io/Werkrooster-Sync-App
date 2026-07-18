"""Offscreen smoke test: the UI must build and load a roster without errors."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

SAMPLE = Path(__file__).parent / "sample_rooster.ics"


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_main_window_loads_roster(app, tmp_path, monkeypatch):
    import werkrooster_sync.core.settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings_path", lambda: tmp_path / "settings.json")

    from werkrooster_sync.ui.main_window import MainWindow

    window = MainWindow()
    window.load_file(str(SAMPLE))
    assert len(window.shifts) == 5
    assert window.sync_btn.isEnabled()
    assert window.preview.count() == 5
    assert "5 items geladen" in window.status.text()


def test_branding_assets_present_and_loadable(app):
    from werkrooster_sync.app import _app_icon, _make_splash
    from werkrooster_sync.resources import asset_path

    for name in ("splash.png", "logo.png", "icon.ico", "icon.icns",
                 "icons/app-icon-512.png"):
        assert asset_path(name).exists(), f"assets/{name} ontbreekt"

    icon = _app_icon()
    assert not icon.isNull()

    splash = _make_splash(app)
    assert splash is not None
    assert not splash.pixmap().isNull()


def test_settings_dialog_builds_and_saves(app, tmp_path, monkeypatch):
    import werkrooster_sync.core.settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings_path", lambda: tmp_path / "settings.json")

    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui.settings_dialog import SettingsDialog

    s = Settings()
    dialog = SettingsDialog(s)
    # On Linux the only backend is .ics export, so the warning must show
    # and the maintenance actions must refuse with the same warning.
    assert not dialog._selected_backend().can_inspect_calendar
    assert dialog.export_warn.isVisibleTo(dialog)
    dialog._check_duplicates()
    assert "export-modus" in dialog.dup_result.text()
    dialog._remove_old_roster()
    assert "export-modus" in dialog.old_result.text()

    dialog.name_edits["ochtend"].setText("Vroeg")
    dialog.include_vrij_check.setChecked(False)
    dialog.include_afspraken_check.setChecked(False)
    idx = dialog.display_combos["nacht"].findData("all_day")
    dialog.display_combos["nacht"].setCurrentIndex(idx)
    dialog.min_shift_spin.setValue(6)
    dialog._save()

    saved = Settings.load(tmp_path / "settings.json")
    assert saved.names["ochtend"] == "Vroeg"
    assert saved.include_vrij is False
    assert saved.include_afspraken is False
    assert saved.display["nacht"] == "all_day"
    assert saved.rules["min_shift_hours"] == 6
