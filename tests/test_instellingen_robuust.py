"""Een kapot of vreemd instellingenbestand mag de app niet laten vastlopen."""
import pytest

from werkrooster_sync.core.settings import Settings


@pytest.mark.parametrize("inhoud", [
    {"names": {"ochtend": 5}}, {"reminders": {"ochtend": "x"}},
    {"reminders": {"ochtend": {"enabled": True, "minutes": "abc"}}},
    {"dienstsoorten": [1]}, {"dienstsoorten": [{"id": "x", "van": 5, "tot": 6}]},
    {"display": {"vrij": 3}}, {"rules": {"keywords": {"vrij": "tekst"}}}, {"include_vrij": "ja"},
    [1, 2], "tekst",
])
def test_vreemd_instellingenbestand_laat_de_app_niet_vastlopen(inhoud):
    from werkrooster_sync.core.classifier import apply_classification
    from werkrooster_sync.core.models import Shift
    from werkrooster_sync.core.settings import controleer_dienstsoorten
    from datetime import datetime
    s = Settings.from_dict(inhoud)
    controleer_dienstsoorten(s.dienstsoorten, s.names)
    x = Shift(start=datetime(2026, 11, 23), end=datetime(2026, 11, 24),
              original_summary="DIENST 07:00-16:30", all_day=True)
    assert apply_classification([x], s)[0].display_name


def test_heel_diep_genest_bestand_valt_terug_op_de_reserve(tmp_path):
    pad = tmp_path / "settings.json"
    Settings(calendar_name="Reserve").save(pad)
    Settings(calendar_name="Reserve").save(pad)  # tweede keer: nu is er een .bak
    pad.write_text("[" * 100000)
    assert Settings.load(pad).calendar_name == "Reserve"


def test_logboek_lekt_geen_namen_of_thuismap():
    from werkrooster_sync.core.logbook import schoon
    r = schoon('Agenda-fout: Can\'t get calendar "Rooster Piet Jansen" in '
               r'C:\Users\PIETJA~1\AppData en /Users/piet/x en C:/Users/Piet/y')
    assert "Piet" not in r and "PIETJA" not in r and "piet" not in r
    assert '"…"' in r
    r = schoon("ValueError: agenda 'Piet Werk' niet gevonden, ‘Jansen’; can't")
    assert "Piet" not in r and "Jansen" not in r and "can't" in r
