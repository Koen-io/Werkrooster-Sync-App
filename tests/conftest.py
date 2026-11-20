"""Gedeelde testinstellingen.

Tests mogen nooit de echte agenda van degene die ze draait aanraken. Elke
aanroep naar Apple Agenda of Outlook wordt daarom geblokkeerd, net als het
openen van een bestand in een ander programma. Een test die een agenda nodig
heeft, gebruikt een nep-koppeling.
"""
from __future__ import annotations

import pytest

from werkrooster_sync import resources
from werkrooster_sync.calendars import ics_export, macos_calendar, outlook_windows


@pytest.fixture(autouse=True)
def geen_echte_agenda(monkeypatch):
    def geblokkeerd(*args, **kwargs):
        raise AssertionError("Test probeerde de echte agenda te gebruiken")

    monkeypatch.setattr(macos_calendar, "_run", geblokkeerd)
    monkeypatch.setattr(outlook_windows, "_com", geblokkeerd)
    monkeypatch.setattr(ics_export.IcsExportBackend, "_open", staticmethod(geblokkeerd))
    monkeypatch.setattr(resources, "open_path", geblokkeerd)


@pytest.fixture(autouse=True)
def eigen_instellingenmap(monkeypatch, tmp_path_factory):
    """Tests lezen en schrijven nooit de echte instellingen van de gebruiker."""
    from werkrooster_sync.core import settings

    basis = tmp_path_factory.mktemp("instellingen")
    monkeypatch.setattr(settings, "_user_config_dir", lambda: basis / "persoonlijk")
    monkeypatch.setattr(settings, "_portable_dir", lambda: basis / "naast-de-app")
