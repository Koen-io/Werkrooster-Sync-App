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


def test_settings_dialog_builds_and_saves(app, tmp_path, monkeypatch):
    import werkrooster_sync.core.settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings_path", lambda: tmp_path / "settings.json")

    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui.settings_dialog import SettingsDialog

    s = Settings()
    dialog = SettingsDialog(s)
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
