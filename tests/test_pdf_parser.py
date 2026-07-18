"""Tests for the BVCM PDF roster reader."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from werkrooster_sync.core.classifier import apply_classification
from werkrooster_sync.core.ics_parser import IcsParseError
from werkrooster_sync.core.pdf_parser import PdfParseError, parse_pdf
from werkrooster_sync.core.models import ShiftType
from werkrooster_sync.core.settings import Settings

CONCEPT = Path(__file__).parent / "sample_bvcm_concept.pdf"
DEFINITIEF = Path(__file__).parent / "sample_bvcm_definitief.pdf"


def classified(path, settings=None):
    s = settings or Settings()
    return apply_classification(parse_pdf(path, s), s), s


def by_date(shifts, y, m, d):
    return [x for x in shifts if x.start.date() == datetime(y, m, d).date()]


def test_definitief_pdf_parses_and_classifies():
    shifts, _ = classified(DEFINITIEF)

    # Empty day becomes Vrij
    vrij = by_date(shifts, 2026, 7, 18)
    assert len(vrij) == 1
    assert vrij[0].shift_type == ShiftType.VRIJ
    assert vrij[0].is_concept is False

    # DIENST with times from the entry text: whole-day item (default
    # display) with the extracted times preserved in start/end and notes
    dienst = by_date(shifts, 2026, 7, 20)[0]
    assert dienst.shift_type == ShiftType.OCHTEND
    assert dienst.all_day
    assert dienst.start == datetime(2026, 7, 20, 7, 0)
    assert dienst.end == datetime(2026, 7, 20, 16, 0)
    assert "Diensttijden: 07:00–16:00" in dienst.description
    assert dienst.display_name == "Ochtend"  # no concept suffix

    # ZIEK keeps its own (time-stripped) title
    ziek = by_date(shifts, 2026, 7, 21)[0]
    assert ziek.shift_type == ShiftType.AFSPRAAK
    assert ziek.display_name == "ZIEK"
    assert ziek.start == datetime(2026, 7, 21, 10, 0)

    # Continuation line [Rust] belongs to the same day and is ignored noise
    wo = by_date(shifts, 2026, 7, 22)
    assert {x.shift_type for x in wo} == {ShiftType.LAAT, ShiftType.NEGEREN}

    # Vr.zondag day: vrij + the full-day rust row as noise
    zo = by_date(shifts, 2026, 7, 26)
    assert ShiftType.VRIJ in {x.shift_type for x in zo}

    # Night shift wraps past midnight
    nacht = by_date(shifts, 2026, 7, 27)[0]
    assert nacht.shift_type == ShiftType.NACHT
    assert nacht.end == datetime(2026, 7, 28, 7, 30)
    # Memo is attached as note
    assert "extra briefing" in nacht.description


def test_concept_pdf_flags_everything_as_concept():
    shifts, _ = classified(CONCEPT)
    assert all(x.is_concept for x in shifts)
    dienst = by_date(shifts, 2026, 7, 20)[0]
    assert dienst.display_name == "Ochtend (concept)"

    # Full-day [Rust] on an otherwise empty day counts as Vrij
    vrij = by_date(shifts, 2026, 7, 18)
    assert len(vrij) == 1
    assert vrij[0].shift_type == ShiftType.VRIJ


def test_empty_day_option_can_be_disabled():
    s = Settings()
    s.rules["empty_day_is_vrij"] = False
    shifts, _ = classified(DEFINITIEF, s)
    assert by_date(shifts, 2026, 7, 18) == []


def test_pdf_sync_ids_are_deterministic():
    ids1 = [x.sync_id for x in classified(DEFINITIEF)[0]]
    ids2 = [x.sync_id for x in classified(DEFINITIEF)[0]]
    assert ids1 == ids2
    assert all(ids1)


def test_pdf_parse_error_is_catchable_as_ics_error(tmp_path):
    bad = tmp_path / "geen_rooster.pdf"
    bad.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(IcsParseError):
        parse_pdf(bad, Settings())
    assert issubclass(PdfParseError, IcsParseError)
