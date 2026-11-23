"""Schermafbeeldingen van de nieuwe schermen, offscreen, tegen een NepAgenda.
Raakt geen echte agenda en geen echte instellingen."""
import os
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_SCALE_FACTOR", "2")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
UIT = Path(sys.argv[1] if len(sys.argv) > 1 else "ui")
UIT.mkdir(parents=True, exist_ok=True)

from werkrooster_sync.core import settings as settings_mod  # noqa: E402

basis = Path(tempfile.mkdtemp())
settings_mod._user_config_dir = lambda: basis / "persoonlijk"
settings_mod._portable_dir = lambda: basis / "naast"

from werkrooster_sync.calendars import macos_calendar, outlook_windows, ics_export  # noqa: E402
from werkrooster_sync import resources  # noqa: E402


def geblokkeerd(*a, **k):
    raise AssertionError("echte agenda")


macos_calendar._run = geblokkeerd
outlook_windows._com = geblokkeerd
ics_export.IcsExportBackend._open = staticmethod(geblokkeerd)
resources.open_path = geblokkeerd

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from tests.nep_agenda import NepAgenda  # noqa: E402
from werkrooster_sync.calendars.macos_calendar import MacCalendarBackend  # noqa: E402
from werkrooster_sync.core import bijwerken as bw  # noqa: E402
from werkrooster_sync.core.classifier import apply_classification  # noqa: E402
from werkrooster_sync.core.models import Shift  # noqa: E402
from werkrooster_sync.core.pdf_parser import read_roster  # noqa: E402
from werkrooster_sync.core.settings import Settings  # noqa: E402
from werkrooster_sync.ui import main_window as mw  # noqa: E402
from werkrooster_sync.ui import theme  # noqa: E402

DEF = PROJECT / "tests/rooster_blokken_definitief.pdf"
agenda = NepAgenda()


class NepApple(NepAgenda):
    id = "apple_calendar"
    label = "Apple Agenda"

    def calendars(self):
        return [("Werk", "agenda-1"), ("Thuis", "agenda-2")]


agenda = NepApple()
mw.get_backend = lambda _id: agenda
mw.all_backends = lambda: [agenda, ics_export.IcsExportBackend(open_after=False)]


def wacht(w):
    for _ in range(50):
        app.processEvents()
        bezig = [t for t in w.findChildren(QThread) if t.isRunning()]
        if not bezig:
            app.processEvents()
            if not [t for t in w.findChildren(QThread) if t.isRunning()]:
                return
        for t in bezig:
            t.wait()


def foto(w, naam):
    app.processEvents()
    w.grab().save(str(UIT / naam))
    print("opgeslagen", UIT / naam)


def instellingen():
    s = Settings(backend_id="apple_calendar", calendar_name="Werk", calendar_key="agenda-1")
    s.save()
    return s


def oud_rooster_in_agenda(s):
    """Een ouder rooster staat al in de agenda: definitief (10 nov) voor
    20-26 nov en een conceptrooster (15 nov) voor 27-29 nov."""
    nieuw = read_roster(DEF, s)
    raw = {x.roster_date: x for x in nieuw.shifts}

    def dienst(d, soort, info=""):
        st = datetime(d.year, d.month, d.day)
        x = Shift(start=st, end=st + timedelta(days=1), original_summary=soort, all_day=True,
                  info=info)
        x.roster_date = d
        return x

    d = lambda n: (datetime(2026, 11, n) + timedelta(weeks=23)).date()  # noqa: E731  testroosters 23 weken opgeschoven
    oud1 = bw.Roster(per_kolom=True, volledig=True, is_concept=False,
                     gegenereerd=datetime(2026, 11, 10, 9, 0), personeelsnummer="12345678",
                     periode=(d(20), d(26)))
    oud1.shifts = [dienst(d(20), "DIENST 07:00-16:30", "Bureaudienst Despatcher"),
                   dienst(d(21), "Vrij"), dienst(d(22), "Vrij"),
                   dienst(d(23), "DIENST 07:00-16:30", "Bureaudienst Despatcher"),
                   dienst(d(23), "Cursus 13:00-15:00"),
                   dienst(d(26), "DIENST 07:00-16:30", "Teamdag")]
    oud2 = bw.Roster(per_kolom=True, volledig=True, is_concept=True,
                     gegenereerd=datetime(2026, 11, 15, 9, 0), personeelsnummer="12345678",
                     periode=(d(27), d(29)))
    oud2.shifts = [dienst(d(27), "DIENST 07:00-16:30", "Bureaudienst Despatcher"),
                   dienst(d(28), "Vrij"), dienst(d(29), "Vrij")]
    for x in oud2.shifts:
        x.is_concept = True
    for r in (oud1, oud2):
        r.shifts = apply_classification(r.shifts, s)
        beheer = bw.Beheer.laad()
        plan = bw.maak_plan(r, r.shifts, agenda, s, beheer, bw.Keuzes(verwijderen_bevestigd=True))
        bw.voer_uit(plan, agenda, beheer, bw.Keuzes(verwijderen_bevestigd=True))
    # Het journaal van deze voorbereiding telt niet als "laatste bijwerking".
    bw.journaal_pad().unlink(missing_ok=True)
    return raw


s = instellingen()
oud_rooster_in_agenda(s)

w = mw.MainWindow()
w.resize(1120, 780)
w.show()
foto(w, "1-rooster-kiezen.png")

w.load_files([str(DEF)])
wacht(w)
foto(w, "2-controleren.png")

# Keuzevraag: een item met de hand aangepast.
w.reset_file()
for i in agenda.items.values():
    if i.start.day in (30, 2) and i.start.month in (4, 5):
        agenda.items[i.native_id] = replace(i, title="Ochtend - ruil met collega")
w.load_files([str(DEF)])
wacht(w)
foto(w, "2b-controleren-keuzevraag.png")

# Uitvoeren met bevestigd verwijderen, dan klaar.
w._laat([datetime(2026, 11, 20).date()])
w.verwijder_check.setChecked(True)
w.start_bijwerken()
wacht(w)
foto(w, "3-klaar.png")

# Instelhulp, drie stappen, met het eigen rooster als voorbeeld.
w.open_instelhulp()
wacht(w)
hulp = w._extra
foto(w, "4-instelhulp-agenda.png")
hulp._volgende()
foto(w, "5-instelhulp-diensten.png")
hulp._volgende()
foto(w, "6-instelhulp-voorkeuren.png")
w._sluit_extra()

# Onbekende code.
from werkrooster_sync.ui.main_window import OnbekendeCode  # noqa: E402

x = Shift(start=datetime(2027, 5, 18), end=datetime(2027, 5, 19), original_summary="TVT",
          all_day=True)
x.roster_date = x.start.date()
w._toon_extra(OnbekendeCode("TVT", [x], s, lambda *a: None))
foto(w, "7-onbekende-code.png")
w._sluit_extra()

# Feedback met voorbeeldrooster.
from werkrooster_sync.ui.feedback_dialog import FeedbackDialog  # noqa: E402

fb = FeedbackDialog(w, rooster=str(DEF))
fb._bevestig_voorbeeld = lambda tekst: True
fb.name_edit.setText("Koen")
fb.message_edit.setPlainText("Mijn rooster wordt niet goed gelezen.")
fb._kies_voorbeeld()
fb.show()
app.processEvents()
foto(fb, "8-feedback.png")

# De tekst die meegaat, zoals de gebruiker hem te zien krijgt.
from PySide6.QtWidgets import QDialog  # noqa: E402

orig_exec = QDialog.exec


def toon(self):
    self.show()
    app.processEvents()
    foto(self, "8b-feedback-voorbeeld-tekst.png")
    return QDialog.DialogCode.Rejected


QDialog.exec = toon
fb._voorbeeld = ""
del fb._bevestig_voorbeeld
fb._kies_voorbeeld()
QDialog.exec = orig_exec
fb.close()

# Stap 2 voor "een andere agenda" (bestand).
ics = ics_export.IcsExportBackend(output_dir=basis, open_after=False)
mw.get_backend = lambda _id: ics
w.settings.backend_id = "ics_export"
w.reset_file()
w._ververs_agendabalk()
w.load_files([str(DEF)])
foto(w, "9-controleren-bestand.png")
from werkrooster_sync.ui.settings_dialog import SettingsPanel  # noqa: E402
w.open_settings()
dlg = w.findChildren(SettingsPanel)[-1]
for i in range(dlg.tabs.count()):
    dlg.tabs.setCurrentIndex(i)
    foto(w, f"10-instellingen-{i+1}.png")
print("klaar")
