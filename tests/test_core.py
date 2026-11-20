"""Tests for the ICS parser, classifier and sync engine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from werkrooster_sync.calendars.ics_export import IcsExportBackend
from werkrooster_sync.core.classifier import apply_classification, classify
from werkrooster_sync.core.ics_parser import IcsParseError, parse_ics
from werkrooster_sync.core.models import Shift, ShiftType
from werkrooster_sync.core.settings import Settings

SAMPLE = Path(__file__).parent / "sample_rooster.ics"


def make_shift(start: datetime, end: datetime, summary: str, all_day=False) -> Shift:
    return Shift(start=start, end=end, original_summary=summary, all_day=all_day)


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------
def test_parse_sample_roster():
    shifts = parse_ics(SAMPLE)
    assert len(shifts) == 5
    assert shifts[0].start == datetime(2026, 7, 20, 7, 0)
    assert shifts[0].end == datetime(2026, 7, 20, 15, 30)
    assert shifts[3].all_day is True
    # Sorted by start time
    starts = [s.start for s in shifts]
    assert starts == sorted(starts)


def test_parse_missing_file(tmp_path):
    with pytest.raises(IcsParseError):
        parse_ics(tmp_path / "nope.ics")


def test_parse_invalid_file(tmp_path):
    bad = tmp_path / "bad.ics"
    bad.write_text("this is not an ics file")
    with pytest.raises(IcsParseError):
        parse_ics(bad)


# ----------------------------------------------------------------------
# Classifier
# ----------------------------------------------------------------------
def test_classify_by_time_windows():
    s = Settings()
    assert classify(make_shift(datetime(2026, 7, 20, 7, 0), datetime(2026, 7, 20, 15, 0), "Dienst"), s) == ShiftType.OCHTEND
    assert classify(make_shift(datetime(2026, 7, 20, 15, 0), datetime(2026, 7, 20, 23, 0), "Dienst"), s) == ShiftType.LAAT
    assert classify(make_shift(datetime(2026, 7, 20, 23, 0), datetime(2026, 7, 21, 7, 0), "Dienst"), s) == ShiftType.NACHT
    assert classify(make_shift(datetime(2026, 7, 20, 2, 0), datetime(2026, 7, 20, 8, 0), "Dienst"), s) == ShiftType.NACHT


def test_default_display_and_reminders():
    """The out-of-the-box configuration: only Vrij is a whole-day item, every
    dienst is a block at its exact times; all dienst types remind 1 hour
    ahead."""
    s = Settings()
    assert s.display_for(ShiftType.VRIJ) == "all_day"
    for t in (ShiftType.OCHTEND, ShiftType.LAAT, ShiftType.NACHT,
              ShiftType.DIENST, ShiftType.AFSPRAAK):
        assert s.display_for(t) == "timed", t
    for t in (ShiftType.OCHTEND, ShiftType.LAAT, ShiftType.NACHT, ShiftType.DIENST):
        assert s.reminder_for(t) == 60, t
    assert s.reminder_for(ShiftType.VRIJ) is None
    assert s.reminder_for(ShiftType.AFSPRAAK) == 30


def test_classify_short_item_is_afspraak():
    s = Settings()
    # 4 hours without a shift keyword: not a whole shift -> afspraak
    meeting = make_shift(datetime(2026, 7, 20, 13, 0), datetime(2026, 7, 20, 17, 0), "Overleg team")
    assert classify(meeting, s) == ShiftType.AFSPRAAK
    # Same duration WITH a shift keyword still counts as that shift
    short_late = make_shift(datetime(2026, 7, 20, 13, 0), datetime(2026, 7, 20, 17, 0), "Late dienst kort")
    assert classify(short_late, s) == ShiftType.LAAT


def test_afspraak_keeps_original_title_and_exact_times():
    s = Settings()
    shifts = [make_shift(datetime(2026, 7, 20, 13, 0), datetime(2026, 7, 20, 17, 0), "Overleg team")]
    result = apply_classification(shifts, s)
    assert result[0].shift_type == ShiftType.AFSPRAAK
    assert result[0].display_name == "Overleg team"
    assert result[0].all_day is False


def test_display_mode_all_day():
    s = Settings()
    s.display[ShiftType.NACHT.value] = "all_day"
    shifts = [make_shift(datetime(2026, 7, 20, 23, 0), datetime(2026, 7, 21, 7, 30), "Nachtdienst")]
    result = apply_classification(shifts, s)
    assert result[0].shift_type == ShiftType.NACHT
    assert result[0].all_day is True
    # The real times survive in the notes when shown as a whole-day item.
    assert "Diensttijden: 23:00–07:30" in result[0].description


def test_classify_by_keyword_beats_time():
    s = Settings()
    # Summary says nacht, but starts at 09:00 -> keyword wins
    shift = make_shift(datetime(2026, 7, 20, 9, 0), datetime(2026, 7, 20, 17, 0), "Nachtdienst")
    assert classify(shift, s) == ShiftType.NACHT


def test_classify_vrij_keyword_and_all_day():
    s = Settings()
    assert classify(make_shift(datetime(2026, 7, 20, 9, 0), datetime(2026, 7, 20, 10, 0), "Vrij"), s) == ShiftType.VRIJ
    # An all-day item without any keyword (e.g. a birthday from another
    # calendar riding along in the export) is an appointment, not a free day.
    assert classify(make_shift(datetime(2026, 7, 20), datetime(2026, 7, 21), "Teamdag", all_day=True), s) == ShiftType.AFSPRAAK


def test_apply_classification_sets_names_and_reminders():
    s = Settings()
    s.names[ShiftType.OCHTEND.value] = "Vroege dienst 🌅"
    s.reminders[ShiftType.OCHTEND.value] = {"enabled": True, "minutes": 45}
    shifts = [make_shift(datetime(2026, 7, 20, 7, 0), datetime(2026, 7, 20, 15, 0), "Dienst")]
    result = apply_classification(shifts, s)
    assert result[0].display_name == "Vroege dienst 🌅"
    assert result[0].reminder_minutes == 45


def test_sample_roster_classification():
    s = Settings()
    shifts = apply_classification(parse_ics(SAMPLE), s)
    types = [x.shift_type for x in shifts]
    assert types == [
        ShiftType.OCHTEND,   # 07:00, 8.5 h
        ShiftType.LAAT,      # 15:00, 8.5 h
        ShiftType.NACHT,     # keyword "nacht"
        ShiftType.VRIJ,      # keyword "vrij", all-day
        ShiftType.AFSPRAAK,  # 13:00, 4 h, no keyword -> not a whole shift
    ]
    assert all(x.sync_id for x in shifts)
    # Re-importing the same file yields identical sync-IDs.
    again = apply_classification(parse_ics(SAMPLE), s)
    assert [x.sync_id for x in shifts] == [x.sync_id for x in again]


def test_bvcm_leave_codes_classify_as_vrij():
    s = Settings()
    for code in ["GEB_VERL", "ZORG", "RVER", "CALA", "ONB_VERL", "ZWAV",
                 "STUDIE", "BVER", "BV_SPORTD", "CAOCOMP", "UITDETA",
                 "BLOK_OPNLL", "VERLOF", "LFU"]:
        shift = make_shift(
            datetime(2026, 8, 3), datetime(2026, 8, 4),
            f"{code} 10:00-17:36", all_day=True,
        )
        result = apply_classification([shift], s)[0]
        assert result.shift_type == ShiftType.VRIJ, f"{code} -> {result.shift_type}"


def test_bvcm_quarantaine_is_dienst_despite_bver_prefix():
    s = Settings()
    shift = make_shift(
        datetime(2026, 8, 3), datetime(2026, 8, 4),
        "BVER_QUARA 22:00-07:00", all_day=True,
    )
    result = apply_classification([shift], s)[0]
    # Longest keyword wins: "bver_quara" (dienst) beats "bver" (vrij).
    assert result.shift_type == ShiftType.DIENST


def test_bvcm_pauze_is_noise_and_consig_keeps_title():
    s = Settings()
    pauze, pauze_bet, consig = apply_classification([
        make_shift(datetime(2026, 8, 3, 12, 0), datetime(2026, 8, 3, 12, 30), "Pauze"),
        make_shift(datetime(2026, 8, 3, 15, 0), datetime(2026, 8, 3, 15, 30), "Pauze_bet"),
        make_shift(datetime(2026, 8, 4), datetime(2026, 8, 5), "CONSIG 18:00-08:00", all_day=True),
    ], s)
    assert pauze.shift_type == ShiftType.NEGEREN
    assert pauze_bet.shift_type == ShiftType.NEGEREN
    assert consig.shift_type == ShiftType.AFSPRAAK
    assert consig.display_name == "CONSIG"
    assert consig.start == datetime(2026, 8, 4, 18, 0)
    assert consig.end == datetime(2026, 8, 5, 8, 0)


def test_bvcm_dienst_codes_keep_time_based_names():
    s = Settings()
    long_shift, short_activity = apply_classification([
        make_shift(datetime(2026, 8, 3), datetime(2026, 8, 4),
                   "A5.05 Motorbegeleiding uitvoeren 07:00-16:00", all_day=True),
        make_shift(datetime(2026, 8, 3), datetime(2026, 8, 4),
                   "A6.02 Adviseren 13:00-15:00", all_day=True),
    ], s)
    # Long dienst-code items are named by their start time, not "Dienst".
    assert long_shift.shift_type == ShiftType.OCHTEND
    assert long_shift.display_name == "Ochtend"
    # Short activities keep their informative code+description title.
    assert short_activity.shift_type == ShiftType.AFSPRAAK
    assert short_activity.display_name == "A6.02 Adviseren"


def _rust_day(day: int, times: str, tag: str = "[C1]") -> Shift:
    return make_shift(
        datetime(2026, 8, day), datetime(2026, 8, day + 1),
        f"{tag} 12345678 [Rust] {times}", all_day=True,
    )


def test_rust_only_days_become_vrij():
    """A day with only [Rust] — full-day OR partial — and no shift is Vrij."""
    s = Settings()
    shifts = apply_classification(
        [
            _rust_day(2, "00:00 - 24:00"),          # rust hele dag
            _rust_day(3, "07:00 - 00:00"),          # partial rust, geen dienst
            _rust_day(4, "00:00 - 07:00"),          # partial rust, geen dienst
        ],
        s,
    )
    vrij = [x for x in shifts if x.shift_type == ShiftType.VRIJ]
    assert [x.start.day for x in vrij] == [2, 3, 4]
    assert all(x.all_day for x in vrij)
    assert all(x.sync_id for x in vrij)
    # Concept rust -> concept Vrij, so auto-replacement keeps working.
    assert all(x.is_concept for x in vrij)
    assert vrij[0].display_name == "Vrij (concept)"


def test_rust_plus_vrij_gives_single_vrij():
    """26-07 scenario: explicit Vrij + [Rust] on the same day -> one Vrij."""
    s = Settings()
    shifts = apply_classification(
        [
            make_shift(datetime(2026, 8, 2), datetime(2026, 8, 3),
                       "[R] 12345678 [Vr.zondag] 00:00 - 24:00", all_day=True),
            _rust_day(2, "00:00 - 24:00", tag="[R]"),
        ],
        s,
    )
    vrij = [x for x in shifts if x.shift_type == ShiftType.VRIJ]
    assert len(vrij) == 1


def test_rust_plus_shift_gives_no_extra_vrij():
    s = Settings()
    shifts = apply_classification(
        [
            make_shift(datetime(2026, 8, 2), datetime(2026, 8, 3),
                       "[R] 12345678 DIENST 07:00 - 16:00", all_day=True),
            _rust_day(2, "00:00 - 07:00", tag="[R]"),
        ],
        s,
    )
    assert not [x for x in shifts if x.shift_type == ShiftType.VRIJ]


def test_rust_vrij_synthesis_can_be_disabled():
    s = Settings()
    s.rules["empty_day_is_vrij"] = False
    shifts = apply_classification([_rust_day(2, "00:00 - 24:00")], s)
    assert not [x for x in shifts if x.shift_type == ShiftType.VRIJ]


def test_double_vrij_registration_gives_single_vrij():
    """VERLOF + [Vakantie] on the same day (2-9 scenario) -> one Vrij."""
    s = Settings()
    shifts = apply_classification(
        [
            make_shift(datetime(2026, 9, 2), datetime(2026, 9, 3),
                       "[C2] 12345678 VERLOF 10:00 - 17:36", all_day=True),
            make_shift(datetime(2026, 9, 2), datetime(2026, 9, 3),
                       "[C2] 12345678 [Vakantie] 00:00 - 24:00", all_day=True),
        ],
        s,
    )
    vrij = [x for x in shifts if x.shift_type == ShiftType.VRIJ]
    assert len(vrij) == 1
    assert vrij[0].all_day


def test_birthday_only_day_is_not_vrij():
    """Negeren items that are not [Rust] never make a day Vrij."""
    s = Settings()
    shifts = apply_classification(
        [make_shift(datetime(2026, 8, 2), datetime(2026, 8, 3),
                    "Verjaardag van Piet", all_day=True)],
        s,
    )
    assert not [x for x in shifts if x.shift_type == ShiftType.VRIJ]


# ----------------------------------------------------------------------
# Informatie/Notitie field in the title
# ----------------------------------------------------------------------
INFO = Path(__file__).parent / "sample_info.ics"


def test_info_field_appended_to_title():
    s = Settings()
    shifts = apply_classification(parse_ics(INFO), s)
    by_uid = {x.uid: x for x in shifts}
    # From the HTML X-ALT-DESC ("Informatie: QRA")
    assert by_uid["info-1@test"].info == "QRA"
    assert by_uid["info-1@test"].display_name == "Ochtend - QRA"
    # From a plain DESCRIPTION ("Notitie: Kustwacht")
    assert by_uid["info-2@test"].info == "Kustwacht"
    assert by_uid["info-2@test"].display_name == "Laat - Kustwacht"
    # Empty Informatie: no suffix
    assert by_uid["info-3@test"].info == ""
    assert by_uid["info-3@test"].display_name == "Ochtend"


def test_info_in_title_can_be_disabled():
    s = Settings()
    s.info_in_title = False
    shifts = apply_classification(parse_ics(INFO), s)
    assert all(" - " not in x.display_name for x in shifts)


# ----------------------------------------------------------------------
# BVCM/Outlook-style roster (all-day events, times in the title)
# ----------------------------------------------------------------------
BVCM = Path(__file__).parent / "sample_bvcm.ics"


def test_bvcm_roster_classification():
    s = Settings()
    shifts = apply_classification(parse_ics(BVCM), s)
    by_uid = {x.uid: x for x in shifts}

    # Times extracted from the title; all-day becomes a real timed shift.
    ochtend = by_uid["bvcm-1@test"]
    assert ochtend.shift_type == ShiftType.OCHTEND
    assert not ochtend.all_day
    assert ochtend.start == datetime(2026, 7, 20, 7, 0)
    assert ochtend.end == datetime(2026, 7, 20, 16, 0)
    assert ochtend.display_name == "Ochtend"  # [R] = definitief, geen suffix

    laat = by_uid["bvcm-2@test"]
    assert laat.shift_type == ShiftType.LAAT
    assert laat.display_name == "Laat (concept)"  # [C1]

    # Night shift wraps past midnight.
    nacht = by_uid["bvcm-3@test"]
    assert nacht.shift_type == ShiftType.NACHT
    assert nacht.start == datetime(2026, 7, 22, 23, 0)
    assert nacht.end == datetime(2026, 7, 23, 7, 30)

    # [Rust] blocks and birthdays are roster noise.
    assert by_uid["bvcm-4@test"].shift_type == ShiftType.NEGEREN
    assert by_uid["bvcm-8@test"].shift_type == ShiftType.NEGEREN

    # "00:00 - 24:00" stays a whole day; VRIJ/Vakantie/LFU are all vrij.
    vrij = by_uid["bvcm-5@test"]
    assert vrij.shift_type == ShiftType.VRIJ
    assert vrij.all_day
    assert by_uid["bvcm-6@test"].shift_type == ShiftType.VRIJ
    assert by_uid["bvcm-7@test"].shift_type == ShiftType.VRIJ

    # A short timed meeting stays an appointment with its own title.
    briefing = by_uid["bvcm-9@test"]
    assert briefing.shift_type == ShiftType.AFSPRAAK
    assert briefing.display_name == "Briefing PALV"


def test_negeren_never_syncs():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(parse_ics(BVCM), s)
    from werkrooster_sync.core.bijwerken import _zichtbaar

    zichtbaar = _zichtbaar(shifts, s)
    synced_titles = {x.display_name for x in zichtbaar}
    assert not any("Rust" in t or "Verjaardag" in t for t in synced_titles)
    assert {x.shift_type for x in shifts if x not in zichtbaar} == {ShiftType.NEGEREN}


def test_time_extraction_can_be_disabled():
    s = Settings()
    s.rules["parse_times_from_title"] = False
    shifts = apply_classification(parse_ics(BVCM), s)
    dienst = next(x for x in shifts if x.uid == "bvcm-1@test")
    assert dienst.all_day  # untouched


def test_sync_id_stable_across_time_extraction_setting():
    s1, s2 = Settings(), Settings()
    s2.rules["parse_times_from_title"] = False
    ids1 = [x.sync_id for x in apply_classification(parse_ics(BVCM), s1)]
    ids2 = [x.sync_id for x in apply_classification(parse_ics(BVCM), s2)]
    assert ids1 == ids2


# ----------------------------------------------------------------------
# ICS export backend ("een andere agenda": alleen een bestand maken)
# ----------------------------------------------------------------------
def test_export_backend_cannot_inspect_calendar():
    from werkrooster_sync.calendars.base import CalendarError

    backend = IcsExportBackend(open_after=False)
    assert backend.can_inspect_calendar is False
    with pytest.raises(CalendarError):
        backend.read_items("x", "", datetime(2026, 1, 1), datetime(2026, 12, 31))


def test_ics_export_roundtrip(tmp_path):
    from werkrooster_sync.core.bijwerken import vaste_uids

    s = Settings()
    shifts = apply_classification(parse_ics(SAMPLE), s)
    vaste_uids(shifts, "12345678")

    backend = IcsExportBackend(output_dir=tmp_path, open_after=False)
    backend.begin("")
    for x in shifts:
        backend.add_shift("", x)
    backend.finalize()
    assert backend.last_output is not None and backend.last_output.exists()
    assert b"\r\r\n" not in backend.last_output.read_bytes()  # Windows: geen dubbele regeleinden

    # The exported file parses again and keeps the renamed shifts + reminders
    reparsed = parse_ics(backend.last_output)
    assert len(reparsed) == 5
    summaries = {x.original_summary for x in reparsed}
    assert {"Ochtend", "Laat", "Nacht", "Vrij", "Overleg team"} <= summaries
    content = backend.last_output.read_text(encoding="utf-8")
    assert "BEGIN:VALARM" in content
    assert "TRIGGER:-PT60M" in content  # dienst default reminder: 1 uur ervoor
    # Vaste UIDs: een nieuwere versie van het rooster werkt het item bij.
    assert {x.uid for x in reparsed} == {f"{x.uid}@werkroostersync" for x in shifts}


# ----------------------------------------------------------------------
# Instellingen 2.0: verhuizen, veilig opslaan, nieuwe trefwoorden
# ----------------------------------------------------------------------
def _mappen():
    import werkrooster_sync.core.settings as m
    return m, m._portable_dir(), m._user_config_dir()


def test_instellingen_verhuizen_van_naast_de_app_en_dat_bestand_wint():
    m, naast, eigen = _mappen()
    naast.mkdir(parents=True)
    eigen.mkdir(parents=True)
    (naast / "settings.json").write_text('{"calendar_name": "Actief"}', encoding="utf-8")
    (eigen / "settings.json").write_text('{"calendar_name": "Verouderd"}', encoding="utf-8")

    assert m.Settings.load().calendar_name == "Actief"
    assert "Verouderd" in (eigen / "settings.verouderd.json").read_text(encoding="utf-8")
    assert (naast / "settings.json").exists()  # oude versie blijft bruikbaar

    # De verhuizing loopt maar één keer: een latere wijziging naast de app
    # overschrijft de persoonlijke instellingen niet meer.
    (naast / "settings.json").write_text('{"calendar_name": "Later"}', encoding="utf-8")
    assert m.Settings.load().calendar_name == "Actief"


def test_bestaande_persoonlijke_instellingen_blijven_zonder_bestand_naast_de_app():
    m, naast, eigen = _mappen()
    eigen.mkdir(parents=True)
    (eigen / "settings.json").write_text('{"calendar_name": "Windows"}', encoding="utf-8")
    assert m.Settings.load().calendar_name == "Windows"
    assert not (eigen / "settings.verouderd.json").exists()


def test_opslaan_bewaart_reservekopie_en_herstelt_bij_beschadiging():
    m, naast, eigen = _mappen()
    s = m.Settings(calendar_name="Eerste")
    pad = s.save()
    s.calendar_name = "Tweede"
    s.save()
    assert m.Settings.load().calendar_name == "Tweede"
    pad.write_text("{half geschre", encoding="utf-8")
    assert m.Settings.load().calendar_name == "Eerste"
    pad.write_text("[1, 2]", encoding="utf-8")  # geldige json, verkeerde vorm
    assert m.Settings.load().calendar_name == "Eerste"


def test_nieuw_standaardtrefwoord_komt_aan_zonder_eigen_keuzes_te_overschrijven(monkeypatch):
    import copy
    m, naast, eigen = _mappen()
    # Een bestand van versie 1: "cala" zelf weggehaald, "mijnverlof" toegevoegd.
    oud = m.Settings().to_dict()
    del oud["known_keywords"]
    oud["rules"]["keywords"]["vrij"].remove("cala")
    oud["rules"]["keywords"]["vrij"].append("mijnverlof")

    nieuw = copy.deepcopy(m.DEFAULT_RULES)
    nieuw["keywords"]["vrij"].append("nieuwverlof")
    monkeypatch.setattr(m, "DEFAULT_RULES", nieuw)

    s = m.Settings.from_dict(copy.deepcopy(oud))
    vrij = s.rules["keywords"]["vrij"]
    assert "nieuwverlof" in vrij      # nieuw uit de update
    assert "mijnverlof" in vrij       # eigen toevoeging blijft
    assert "cala" not in vrij         # zelf weggehaald blijft weg

    # Daarna zelf weghalen blijft ook weg bij de volgende start.
    opgeslagen = s.to_dict()
    opgeslagen["rules"]["keywords"]["vrij"].remove("nieuwverlof")
    assert "nieuwverlof" not in m.Settings.from_dict(opgeslagen).rules["keywords"]["vrij"]


def test_logboek_schrijft_en_verbergt_de_thuismap(monkeypatch):
    import logging
    import sys
    import threading
    from pathlib import Path

    from werkrooster_sync.core import logbook

    root = logging.getLogger()
    voor = list(root.handlers), sys.excepthook, threading.excepthook, root.level
    gemeld = []
    try:
        logbook.setup(on_crash=gemeld.append)
        logbook.log.info("Bestand in %s", Path.home() / "Documents")
        sys.excepthook(ValueError, ValueError("kapot"), None)
        for h in root.handlers:
            h.flush()
        staart = logbook.tail()
        assert "Bestand in ~" in staart and str(Path.home()) not in staart
        assert "Onverwachte fout" in staart and "kapot" in staart
        assert gemeld == ["ValueError: kapot"]
    finally:
        for h in root.handlers[:]:
            if h not in voor[0]:
                root.removeHandler(h)
                h.close()
        sys.excepthook, threading.excepthook = voor[1], voor[2]
        root.setLevel(voor[3])

