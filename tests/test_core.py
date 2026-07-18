"""Tests for the ICS parser, classifier and sync engine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from werkrooster_sync.calendars.base import CalendarBackend
from werkrooster_sync.calendars.ics_export import IcsExportBackend
from werkrooster_sync.core.classifier import apply_classification, classify
from werkrooster_sync.core.ics_parser import IcsParseError, parse_ics
from werkrooster_sync.core.models import Shift, ShiftType
from werkrooster_sync.core.settings import Settings
from werkrooster_sync.core.sync import find_duplicates, prepare_shifts, sync_shifts

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


def test_classify_by_keyword_beats_time():
    s = Settings()
    # Summary says nacht, but starts at 09:00 -> keyword wins
    shift = make_shift(datetime(2026, 7, 20, 9, 0), datetime(2026, 7, 20, 17, 0), "Nachtdienst")
    assert classify(shift, s) == ShiftType.NACHT


def test_classify_vrij_keyword_and_all_day():
    s = Settings()
    assert classify(make_shift(datetime(2026, 7, 20, 9, 0), datetime(2026, 7, 20, 10, 0), "Vrij"), s) == ShiftType.VRIJ
    assert classify(make_shift(datetime(2026, 7, 20), datetime(2026, 7, 21), "", all_day=True), s) == ShiftType.VRIJ


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
        ShiftType.OCHTEND,  # 07:00
        ShiftType.LAAT,     # 15:00
        ShiftType.NACHT,    # keyword "nacht"
        ShiftType.VRIJ,     # keyword "vrij", all-day
        ShiftType.LAAT,     # 13:00, no keyword
    ]


# ----------------------------------------------------------------------
# Sync engine
# ----------------------------------------------------------------------
class FakeBackend(CalendarBackend):
    id = "fake"
    label = "Fake"

    def __init__(self, existing=None):
        self.added: list[Shift] = []
        self._existing = existing or []

    def is_available(self):
        return True

    def list_calendars(self):
        return ["Werk"]

    def add_shift(self, calendar_name, shift):
        self.added.append(shift)

    def existing_keys_list(self, calendar_name, start, end):
        return list(self._existing)


def test_prepare_shifts_respects_vrij_setting():
    s = Settings()
    shifts = apply_classification(parse_ics(SAMPLE), s)

    s.include_vrij = True
    to_sync, skipped = prepare_shifts(shifts, s)
    assert len(to_sync) == 5 and not skipped

    s.include_vrij = False
    to_sync, skipped = prepare_shifts(shifts, s)
    assert len(to_sync) == 4
    assert len(skipped) == 1
    assert skipped[0].shift_type == ShiftType.VRIJ


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


def test_find_duplicates():
    s = Settings()
    s.calendar_name = "Werk"
    key = ("ochtend", "202607200700")
    backend = FakeBackend(existing=[key, key, ("laat", "202607211500")])
    dups = find_duplicates(backend, s)
    assert dups == {key: 2}


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
    assert {"Ochtend", "Laat", "Nacht", "Vrij"} <= summaries
    content = backend.last_output.read_text(encoding="utf-8")
    assert "BEGIN:VALARM" in content
    assert "TRIGGER:-PT720M" in content  # ochtend default reminder
