"""Tests for the ICS parser, classifier and sync engine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from werkrooster_sync.calendars.base import CalendarBackend
from werkrooster_sync.calendars.ics_export import IcsExportBackend
from werkrooster_sync.core.classifier import apply_classification, classify
from werkrooster_sync.core.ics_parser import IcsParseError, parse_ics
from werkrooster_sync.core.models import (
    Shift,
    ShiftType,
    extract_sync_ids,
    marker_for,
)
from werkrooster_sync.core.settings import Settings
from werkrooster_sync.core.sync import (
    find_duplicates,
    mark_already_imported,
    prepare_shifts,
    sync_shifts,
)

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
    backend = FakeBackend()
    report = sync_shifts(shifts, backend, s)
    assert report.ok
    synced_titles = {x.display_name for x in report.added}
    assert not any("Rust" in t or "Verjaardag" in t for t in synced_titles)
    assert {x.shift_type for x in report.skipped_by_settings} == {ShiftType.NEGEREN}


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
# Sync engine
# ----------------------------------------------------------------------
class FakeBackend(CalendarBackend):
    id = "fake"
    label = "Fake"

    def __init__(self, existing=None, existing_ids=None, events=None):
        self.added: list[Shift] = []
        self.removed_ids: set[str] = set()
        self._existing = existing or []
        self._existing_ids = set(existing_ids or [])
        self._events = list(events or [])

    def is_available(self):
        return True

    def list_calendars(self):
        return ["Werk"]

    def add_shift(self, calendar_name, shift):
        self.added.append(shift)

    def existing_keys_list(self, calendar_name, start, end):
        return list(self._existing)

    def existing_sync_ids(self, calendar_name, start, end):
        return set(self._existing_ids)

    def scan_events(self, calendar_name, start, end):
        return super().scan_events(calendar_name, start, end) + list(self._events)

    def remove_by_sync_ids(self, calendar_name, start, end, sync_ids):
        self.removed_ids |= set(sync_ids)
        return len(sync_ids)


def test_prepare_shifts_respects_vrij_and_afspraak_settings():
    s = Settings()
    shifts = apply_classification(parse_ics(SAMPLE), s)

    s.include_vrij = True
    to_sync, skipped = prepare_shifts(shifts, s)
    assert len(to_sync) == 5 and not skipped

    s.include_vrij = False
    to_sync, skipped = prepare_shifts(shifts, s)
    assert len(to_sync) == 4
    assert skipped[0].shift_type == ShiftType.VRIJ

    s.include_afspraken = False
    to_sync, skipped = prepare_shifts(shifts, s)
    assert len(to_sync) == 3
    assert {x.shift_type for x in skipped} == {ShiftType.VRIJ, ShiftType.AFSPRAAK}


def test_sync_skips_duplicates():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(parse_ics(SAMPLE), s)
    existing = [shifts[0].dedupe_key]

    backend = FakeBackend(existing=existing)
    report = sync_shifts(shifts, backend, s)
    assert report.ok
    assert len(report.added) == 4
    assert len(report.skipped_existing) == 1


def test_sync_never_adds_same_shift_twice_in_one_run():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(parse_ics(SAMPLE), s)
    doubled = shifts + [
        make_shift(sh.start, sh.end, sh.original_summary, sh.all_day) for sh in shifts
    ]
    doubled = apply_classification(doubled, s)

    backend = FakeBackend()
    report = sync_shifts(doubled, backend, s)
    assert len(report.added) == 5
    assert len(report.skipped_existing) == 5


def test_sync_skips_renamed_item_via_sync_id():
    """A user renamed the calendar item (added a note to the title): the
    sync-ID marker must still recognise it, so it is skipped and the user's
    edit survives a re-import."""
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(parse_ics(SAMPLE), s)
    renamed = shifts[0]

    # In the calendar the item now has a different title, so the legacy
    # (title, start) key does NOT match — only the marker does.
    backend = FakeBackend(
        existing=[("ochtend - tandarts 14u!", renamed.dedupe_key[1])],
        existing_ids={renamed.sync_id},
    )
    report = sync_shifts(shifts, backend, s)
    assert report.ok
    assert renamed not in report.added
    assert renamed in report.skipped_existing
    assert len(report.added) == 4


def test_mark_already_imported_flags_shifts():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(parse_ics(SAMPLE), s)
    backend = FakeBackend(existing_ids={shifts[1].sync_id, shifts[2].sync_id})
    count = mark_already_imported(shifts, backend, s)
    assert count == 2
    assert [x.already_imported for x in shifts] == [False, True, True, False, False]


def test_sync_adds_marker_to_description():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(parse_ics(SAMPLE), s)
    backend = FakeBackend()
    sync_shifts(shifts, backend, s)
    for shift in backend.added:
        assert marker_for(shift.sync_id) in shift.description
        assert extract_sync_ids(shift.description) == [shift.sync_id]


def _dienst_shift(day: int, summary: str) -> Shift:
    return make_shift(
        datetime(2026, 8, day), datetime(2026, 8, day + 1), summary, all_day=True
    )


def _concept_event(day: int, sync_id: str):
    from werkrooster_sync.calendars.base import ExistingEvent

    return ExistingEvent(
        "laat (concept)", f"202608{day:02d}1400", sync_id, concept=True
    )


def test_definitive_shift_replaces_concept_item():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(
        [_dienst_shift(5, "[R] 12345678 DIENST 07:00 - 16:00")], s
    )
    backend = FakeBackend(events=[_concept_event(5, "oldconcept01")])
    report = sync_shifts(shifts, backend, s)
    assert report.ok
    assert backend.removed_ids == {"oldconcept01"}
    assert report.concept_removed == 1
    assert len(report.added) == 1
    assert report.replaced == [shifts[0]]


def test_updated_concept_replaces_older_concept():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(
        [_dienst_shift(5, "[C1] 12345678 DIENST 15:00 - 23:30")], s
    )
    backend = FakeBackend(events=[_concept_event(5, "oldconcept01")])
    report = sync_shifts(shifts, backend, s)
    assert backend.removed_ids == {"oldconcept01"}
    assert len(report.added) == 1
    # The new concept item carries the concept tag for the next round.
    from werkrooster_sync.core.models import CONCEPT_TAG

    assert CONCEPT_TAG in backend.added[0].description


def test_unchanged_concept_import_deletes_nothing():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(
        [_dienst_shift(5, "[C1] 12345678 DIENST 15:00 - 23:30")], s
    )
    backend = FakeBackend(events=[_concept_event(5, shifts[0].sync_id)])
    report = sync_shifts(shifts, backend, s)
    assert backend.removed_ids == set()
    assert not report.added
    assert len(report.skipped_existing) == 1


def test_afspraak_never_triggers_replacement():
    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(
        [make_shift(datetime(2026, 8, 5, 12, 30), datetime(2026, 8, 5, 13, 0), "Briefing")], s
    )
    backend = FakeBackend(events=[_concept_event(5, "oldconcept01")])
    report = sync_shifts(shifts, backend, s)
    assert backend.removed_ids == set()
    assert len(report.added) == 1
    assert report.concept_removed == 0


def test_replacement_can_be_disabled():
    s = Settings()
    s.calendar_name = "Werk"
    s.replace_concept = False
    shifts = apply_classification(
        [_dienst_shift(5, "[R] 12345678 DIENST 07:00 - 16:00")], s
    )
    backend = FakeBackend(events=[_concept_event(5, "oldconcept01")])
    report = sync_shifts(shifts, backend, s)
    assert backend.removed_ids == set()
    assert len(report.added) == 1


def test_definitive_items_are_never_deleted():
    from werkrooster_sync.calendars.base import ExistingEvent

    s = Settings()
    s.calendar_name = "Werk"
    shifts = apply_classification(
        [_dienst_shift(5, "[R] 12345678 DIENST 07:00 - 16:00")], s
    )
    definitive = ExistingEvent("ochtend", "202608050700", "definitief01", concept=False)
    backend = FakeBackend(events=[definitive])
    report = sync_shifts(shifts, backend, s)
    assert backend.removed_ids == set()
    assert report.concept_removed == 0


def test_find_duplicates():
    s = Settings()
    s.calendar_name = "Werk"
    key = ("ochtend", "202607200700")
    backend = FakeBackend(existing=[key, key, ("laat", "202607211500")])
    dups = find_duplicates(backend, s)
    assert dups == {key: 2}


def test_export_backend_cannot_inspect_calendar():
    from werkrooster_sync.calendars.base import CalendarError

    backend = IcsExportBackend(open_after=False)
    assert backend.can_inspect_calendar is False
    with pytest.raises(CalendarError):
        backend.count_synced("x", datetime(2026, 1, 1), datetime(2026, 12, 31))
    with pytest.raises(CalendarError):
        backend.remove_synced("x", datetime(2026, 1, 1), datetime(2026, 12, 31))


# ----------------------------------------------------------------------
# ICS export backend
# ----------------------------------------------------------------------
def test_ics_export_roundtrip(tmp_path):
    s = Settings()
    s.calendar_name = "whatever"
    shifts = apply_classification(parse_ics(SAMPLE), s)

    backend = IcsExportBackend(output_dir=tmp_path, open_after=False)
    report = sync_shifts(shifts, backend, s)
    assert report.ok
    assert backend.last_output is not None and backend.last_output.exists()

    # The exported file parses again and keeps the renamed shifts + reminders
    reparsed = parse_ics(backend.last_output)
    assert len(reparsed) == 5
    summaries = {x.original_summary for x in reparsed}
    assert {"Ochtend", "Laat", "Nacht", "Vrij", "Overleg team"} <= summaries
    content = backend.last_output.read_text(encoding="utf-8")
    assert "BEGIN:VALARM" in content
    assert "TRIGGER:-PT60M" in content  # dienst default reminder: 1 uur ervoor
    # The sync-ID marker travels along in the description
    assert "[WerkroosterSync:" in content
