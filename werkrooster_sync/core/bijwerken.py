"""De agenda gelijktrekken met het rooster: plannen, uitvoeren, ongedaan maken.

Het ontwerp staat in ``docs/ontwerp-bijwerken.md``. Kort:

* de eenheid is de roosterdag; een dag gaat helemaal of helemaal niet;
* :func:`maak_plan` leest alleen, :func:`voer_uit` schrijft;
* de agenda zelf is de waarheid: elk item draagt in zijn kenmerk een
  vingerafdruk van wat de app schreef, zodat opnieuw draaien na een
  onderbreking alleen het verschil uitvoert en nooit dubbelen maakt;
* bij twijfel gebeurt er niets en wordt het gemeld.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..calendars.base import AgendaItem, CalendarBackend, CalendarError
from . import settings as settings_mod
from .models import CONCEPT_TAG, MARKER_RE, Shift, ShiftType
from .pdf_parser import Roster
from .settings import Settings

log = logging.getLogger(__name__)

KOP = "Uit je werkrooster:"
KENMERK_RE = re.compile(
    r"\[WerkroosterSync:2:([0-9a-f]{10}):(\d{8}):([0-9a-f]{10}):([dc])(\d{12})?\]"
)

# Uitkomsten per dag, in de volgorde waarin het controlescherm ze toont.
NIEUW = "nieuw"
GEWIJZIGD = "gewijzigd"
VERVANGT_CONCEPT = "vervangt concept"
STAAT_ER_AL = "staat er al"
VERWIJDEREN = "wordt verwijderd"
ZELF_AANGEPAST = "zelf aangepast"
MOGELIJK_DUBBEL = "mogelijk dubbel"
OUDER_ROOSTER = "ouder rooster"
ANDERE_INHOUD = "zelfde datum, andere inhoud"
OVERGESLAGEN = "overgeslagen"


# ----------------------------------------------------------------------
# Kenmerk en inhoud
# ----------------------------------------------------------------------
def eigenaar_van(personeelsnummer: str) -> str:
    """Onleesbare vingerafdruk van het personeelsnummer (geen geheim: het
    houdt alleen items van verschillende medewerkers uit elkaar)."""
    raw = f"werkrooster-sync|{personeelsnummer.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def _regels(tekst: str) -> list[str]:
    """Notitietekst als regels, zoals elke agenda-app hem ook teruggeeft."""
    regels = [r.rstrip() for r in (tekst or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while regels and not regels[0]:
        regels.pop(0)
    while regels and not regels[-1]:
        regels.pop()
    return regels


def _tijd_sleutel(start: datetime, end: datetime, all_day: bool) -> str:
    if all_day:
        dagen = max(1, round((end - start).total_seconds() / 86400))
        return f"D{start:%Y%m%d}+{dagen}"
    return f"T{start:%Y%m%d%H%M}-{end:%Y%m%d%H%M}"


def inhoud_van(titel: str, start: datetime, end: datetime, all_day: bool,
               blok: list[str]) -> str:
    """Vingerafdruk van wat van de app is: titel, tijden en het eigen blok."""
    raw = "\x1f".join([titel.strip(), _tijd_sleutel(start, end, all_day), *blok])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


@dataclass
class Gewenst:
    """Eén dienst zoals hij volgens het rooster in de agenda hoort."""

    dag: date
    titel: str
    start: datetime
    end: datetime
    all_day: bool
    blok: list[str]
    concept: bool
    reminder_minutes: int | None = None
    location: str = ""
    #: Wanneer het rooster gemaakt is (jjjjmmdduumm), "" als dat onbekend is.
    gegenereerd: str = ""

    @property
    def inhoud(self) -> str:
        return inhoud_van(self.titel, self.start, self.end, self.all_day, self.blok)

    def kenmerk(self, eigenaar: str) -> str:
        return (f"[WerkroosterSync:2:{eigenaar}:{self.dag:%Y%m%d}:{self.inhoud}:"
                f"{'c' if self.concept else 'd'}{self.gegenereerd}]")

    def notitie(self, eigenaar: str, voor: list[str] = (), na: list[str] = ()) -> str:
        """Het eigen blok met kenmerk, met tekst van de gebruiker eromheen."""
        eigen = ([KOP, *self.blok] if self.blok else []) + [self.kenmerk(eigenaar)]
        delen = [list(voor), eigen, list(na)]
        return "\n\n".join("\n".join(d) for d in delen if d)

    def als_item(self, eigenaar: str, bestaand: "AgendaItem | None" = None) -> AgendaItem:
        voor, na = ([], [])
        if bestaand is not None:
            voor, na = Gelezen.van(bestaand).eigen_tekst
        return AgendaItem(
            native_id=bestaand.native_id if bestaand else "",
            title=self.titel, start=self.start, end=self.end, all_day=self.all_day,
            notes=self.notitie(eigenaar, voor, na),
            location=bestaand.location if bestaand else self.location,
            reminder_minutes=self.reminder_minutes,
        )


def gewenst_uit(shift: Shift, gegenereerd: datetime | None = None) -> Gewenst:
    end = shift.end if shift.end > shift.start else shift.start
    return Gewenst(
        dag=shift.roster_date or shift.start.date(),
        titel=shift.display_name, start=shift.start, end=end, all_day=shift.all_day,
        blok=_regels(shift.description), concept=shift.is_concept,
        reminder_minutes=shift.reminder_minutes, location=shift.location,
        gegenereerd=f"{gegenereerd:%Y%m%d%H%M}" if gegenereerd else "",
    )


@dataclass
class Gelezen:
    """Een agenda-item, ontleed in wat van de app is en wat van de gebruiker."""

    item: AgendaItem
    versie: int = 0            # 0 = geen kenmerk, 1 = oud kenmerk, 2 = nieuw
    eigenaar: str = ""
    dag: date | None = None    # roosterdatum uit het kenmerk
    inhoud: str = ""           # vingerafdruk uit het kenmerk
    concept: bool = False
    gegenereerd: str = ""      # jjjjmmdduumm uit het kenmerk
    eigen_tekst: tuple[list[str], list[str]] = ((), ())  # van de gebruiker: voor, na
    aangepast: bool = False    # wijkt af van wat de app schreef

    @classmethod
    def van(cls, item: AgendaItem) -> "Gelezen":
        regels = _regels(item.notes)
        tekst = "\n".join(regels)
        treffers = KENMERK_RE.findall(tekst)
        if not treffers:
            return cls(item, versie=1 if MARKER_RE.search(tekst) else 0)
        eigenaar, dag_txt, inhoud, soort, gen = treffers[0]
        try:
            dag = datetime.strptime(dag_txt, "%Y%m%d").date()
        except ValueError:
            return cls(item)
        i_kenmerk = next(i for i, r in enumerate(regels) if KENMERK_RE.search(r))
        i_kop = max((i for i in range(i_kenmerk) if regels[i].strip() == KOP), default=None)
        blok = regels[i_kop + 1:i_kenmerk] if i_kop is not None else []
        rest = KENMERK_RE.sub("", regels[i_kenmerk]).strip()
        weg = lambda rr: [KENMERK_RE.sub("", r).rstrip() for r in rr  # noqa: E731
                          if KENMERK_RE.sub("", r).strip() or not KENMERK_RE.search(r)]
        voor = weg(regels[:i_kop if i_kop is not None else i_kenmerk])
        na = ([rest] if rest else []) + weg(regels[i_kenmerk + 1:])
        werkelijk = inhoud_van(item.title, item.start, item.end, item.all_day, blok)
        return cls(
            item, versie=2, eigenaar=eigenaar, dag=dag, inhoud=inhoud,
            concept=soort == "c", gegenereerd=gen, eigen_tekst=(_regels("\n".join(voor)), _regels("\n".join(na))),
            # Twee kenmerken, tekst op de kenmerkregel of een andere inhoud dan
            # de app schreef: dan heeft de gebruiker er iets aan gedaan.
            aangepast=len(treffers) > 1 or bool(rest) or werkelijk != inhoud,
        )

    @property
    def afdruk(self) -> str:
        """Alles wat er nu staat, om te zien of het item intussen veranderd is."""
        i = self.item
        raw = "\x1f".join([i.native_id, i.title.strip(), (i.location or "").strip(),
                           _tijd_sleutel(i.start, i.end, i.all_day), *_regels(i.notes)])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _lees(backend: CalendarBackend, agenda: str, nummer: str,
          van: datetime, tot: datetime) -> list[Gelezen]:
    """Lees de agenda. Regeleinden worden meteen gelijkgetrokken: Outlook geeft
    Windows-regeleinden terug, en wat de app later terugschrijft (bij
    terugzetten) moet daar niet steeds een regel bij krijgen."""
    items = backend.read_items(agenda, nummer, van, tot)
    for i in items:
        i.notes = (i.notes or "").replace("\r\n", "\n").replace("\r", "\n")
    return [Gelezen.van(i) for i in items]


def vaste_uids(shifts: list[Shift], personeelsnummer: str) -> None:
    """Geef elke dienst een vaste UID voor het .ics-bestand: medewerker,
    roosterdag en volgnummer op die dag. Een nieuwere versie van het rooster
    geeft dezelfde dienst dezelfde UID."""
    eigenaar = eigenaar_van(personeelsnummer)
    teller: dict[date, int] = {}
    for x in sorted(shifts, key=lambda x: (x.roster_date or x.start.date(), x.start)):
        d = x.roster_date or x.start.date()
        teller[d] = teller.get(d, 0) + 1
        x.uid = f"ws-{eigenaar}-{d:%Y%m%d}-{teller[d]}"


def op_rangvolgorde(roosters: list[Roster]) -> list[Roster]:
    """Meerdere roosters tegelijk: laagste rang eerst, zodat het nieuwste
    definitieve rooster als laatste wint en niets een "ouder rooster" is."""
    return sorted(roosters, key=lambda r: _rang(not r.is_concept, r.gegenereerd))


def agenda_kiezen(backend: CalendarBackend, naam: str, nummer: str) -> tuple[str, str]:
    """Zoek het vaste nummer bij de gekozen agenda.

    Met een nummer dat nog bestaat wint het nummer (de agenda kan hernoemd
    zijn). Zonder nummer: alleen als precies één agenda zo heet. Anders geen
    nummer; dan voegt de app alleen toe."""
    try:
        lijst = backend.calendars()
    except CalendarError:
        return naam, ""
    if nummer:
        for n, k in lijst:
            if k == nummer:
                return n, k
        return naam, ""
    treffers = [k for n, k in lijst if n == naam and k]
    return naam, treffers[0] if len(treffers) == 1 else ""


# ----------------------------------------------------------------------
# Wat de app beheert ("welk rooster wint")
# ----------------------------------------------------------------------
def beheer_pad() -> Path:
    return settings_mod._user_config_dir() / "beheer.json"


def journaal_pad() -> Path:
    return settings_mod._user_config_dir() / "laatste-bijwerking.jsonl"


class Beheer:
    """Per medewerker, agenda en dag: welk rooster het laatst gewonnen heeft."""

    def __init__(self, data: dict | None = None):
        self.data = data if isinstance(data, dict) else {}
        self.data.setdefault("agendas", {})

    @classmethod
    def laad(cls) -> "Beheer":
        try:
            return cls(json.loads(beheer_pad().read_text(encoding="utf-8")))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError):
            log.exception("beheer.json onleesbaar; begin opnieuw")
            return cls()

    def bewaar(self) -> None:
        pad = beheer_pad()
        pad.parent.mkdir(parents=True, exist_ok=True)
        settings_mod._write_safely(pad, json.dumps(self.data, indent=1).encode("utf-8"))

    def agenda(self, sleutel: str) -> dict:
        a = self.data["agendas"].setdefault(sleutel, {})
        a.setdefault("dagen", {})
        return a


def _rang(definitief: bool, gegenereerd: datetime | None) -> tuple[int, str]:
    return (1 if definitief else 0, f"{gegenereerd:%Y%m%d%H%M}" if gegenereerd else "")


def _hoogste(bekend: dict | None, eigen: list["Gelezen"]) -> dict | None:
    """De hoogste rang die voor een dag bekend is: uit het eigen geheugen en
    uit de kenmerken in de agenda zelf (die reizen mee naar een tweede
    apparaat; het geheugen niet)."""
    kandidaten = [bekend] if bekend else []
    kandidaten += [{"def": 0 if e.concept else 1, "gen": e.gegenereerd, "inhoud": None}
                   for e in eigen]
    return max(kandidaten, key=lambda k: (k.get("def", 0), k.get("gen", "")), default=None)


def _oordeel(bekend: dict | None, definitief: bool, gegenereerd: datetime | None,
             dag_inhoud: str) -> str:
    """'' = verwerken, anders OUDER_ROOSTER of ANDERE_INHOUD."""
    if not bekend:
        return ""
    oud_def, oud_gen = bekend.get("def", 0), bekend.get("gen", "")
    nieuw_def, nieuw_gen = _rang(definitief, gegenereerd)
    if nieuw_def != oud_def:
        return "" if nieuw_def > oud_def else OUDER_ROOSTER
    if nieuw_gen and oud_gen and nieuw_gen != oud_gen:
        return "" if nieuw_gen > oud_gen else OUDER_ROOSTER
    if bekend.get("inhoud") is not None:
        return "" if bekend["inhoud"] == dag_inhoud else ANDERE_INHOUD
    # Rang uit de agenda (of na een bevestigd ouder rooster): de inhoud staat
    # in de agenda zelf. Zonder datum valt "nieuwer" niet te bewijzen.
    return ANDERE_INHOUD if oud_gen and not nieuw_gen else ""


# ----------------------------------------------------------------------
# Plan
# ----------------------------------------------------------------------
@dataclass
class Stap:
    actie: str                      # "voeg_toe" | "werk_bij" | "verwijder"
    voor: AgendaItem | None = None  # het item zoals het nu is
    na: AgendaItem | None = None    # het item zoals het wordt


@dataclass
class DagPlan:
    dag: date
    uitkomst: str
    stappen: list[Stap] = field(default_factory=list)
    reden: str = ""
    #: Afdrukken van de eigen items op het moment van plannen.
    gezien: list[str] = field(default_factory=list)
    gewenst: list[Gewenst] = field(default_factory=list)
    dag_inhoud: str = ""
    #: De gebruiker moet eerst kiezen; zonder keuze gebeurt er niets.
    keuze_nodig: bool = False
    behoud_rang: bool = False

    @property
    def verwijdert(self) -> bool:
        return any(s.actie == "verwijder" for s in self.stappen)

    @property
    def netto_weg(self) -> int:
        """Zoveel items minder staan er na deze dag. Vervangen (één weg, één
        erbij) telt niet: dan blijft de dienst staan, met nieuwe inhoud."""
        weg = sum(s.actie == "verwijder" for s in self.stappen)
        return max(0, weg - sum(s.actie == "voeg_toe" for s in self.stappen))


@dataclass
class Keuzes:
    """Wat de gebruiker op het controlescherm heeft beslist."""

    overschrijf_aangepast: set[date] = field(default_factory=set)
    ouder_toestaan: bool = False
    andere_inhoud_toestaan: bool = False
    #: "In deze agenda staan alleen mijn eigen diensten" (eenmalig, onthouden).
    oude_items_zijn_van_mij: bool = False
    vervang_oude_items: set[date] = field(default_factory=set)
    #: Rooster met een regel die bij geen dag hoort: toch (alleen) toevoegen.
    onbegrepen_bevestigd: bool = False
    verwijderen_bevestigd: bool = False


@dataclass
class Plan:
    dagen: list[DagPlan] = field(default_factory=list)
    alleen_toevoegen: bool = False
    meldingen: list[str] = field(default_factory=list)
    eigenaar: str = ""
    agenda: str = ""            # naam, voor de koppeling
    agenda_nummer: str = ""     # vast nummer van de agenda
    beheer_sleutel: str = ""
    definitief: bool = True
    gegenereerd: datetime | None = None
    bereik: tuple[datetime, datetime] | None = None
    #: Aantal items met het oude kenmerk waarover nog niets bevestigd is.
    oude_items: int = 0

    def met(self, uitkomst: str) -> list[DagPlan]:
        return [d for d in self.dagen if d.uitkomst == uitkomst]

    @property
    def aantal_verwijderingen(self) -> int:
        """Items die netto verdwijnen; daarvoor is een eigen bevestiging nodig."""
        return sum(d.netto_weg for d in self.dagen if not d.keuze_nodig)


def _zichtbaar(shifts: list[Shift], s: Settings) -> list[Shift]:
    uit = []
    for x in shifts:
        if x.shift_type == ShiftType.NEGEREN:
            continue
        if x.shift_type == ShiftType.VRIJ and not s.include_vrij:
            continue
        if x.shift_type == ShiftType.AFSPRAAK and not s.include_afspraken:
            continue
        uit.append(x)
    return uit


def _dag_inhoud(shifts: list[Shift]) -> str:
    """Vingerafdruk van wat het rooster zelf over een dag zegt, los van de
    instellingen (namen, wat je wel en niet wilt zien)."""
    raw = "\x1e".join(sorted(
        f"{x.original_summary}\x1f{x.info}\x1f{x.description}" for x in shifts))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def _basis(titel: str) -> str:
    return titel.split(" - ")[0].strip().casefold()


def _eigen_items(gelezen: list[Gelezen], eigenaar: str, dag: date) -> list[Gelezen]:
    """Items van de app voor deze medewerker op deze roosterdag. Een item dat
    naar een andere dag is gesleept of gekopieerd telt niet meer als eigen."""
    return [g for g in gelezen if g.versie == 2 and g.eigenaar == eigenaar
            and g.dag == dag and g.item.start.date() == dag]


def maak_plan(roster: Roster, shifts: list[Shift], backend: CalendarBackend,
              settings: Settings, beheer: Beheer, keuzes: Keuzes | None = None) -> Plan:
    """Vergelijk het (ingedeelde) rooster met de agenda. Leest alleen."""
    keuzes = keuzes or Keuzes()
    plan = Plan(
        eigenaar=eigenaar_van(roster.personeelsnummer),
        agenda=settings.calendar_name, agenda_nummer=settings.calendar_key,
        definitief=not roster.is_concept, gegenereerd=roster.gegenereerd,
    )
    plan.beheer_sleutel = f"{plan.eigenaar}|{backend.id}|{plan.agenda_nummer}"
    plan.meldingen = list(roster.meldingen)

    redenen = []
    if not roster.per_kolom:
        redenen.append("de kolommen van het rooster zijn niet herkend")
    elif not roster.volledig:
        redenen.append("het rooster is niet compleet gelezen")
    if roster.per_kolom and not roster.personeelsnummer:
        redenen.append("het personeelsnummer staat niet in het rooster")
    if not plan.agenda_nummer:
        redenen.append("deze agenda heeft geen vast nummer")
    plan.alleen_toevoegen = bool(redenen)
    if redenen and roster.per_kolom:
        plan.meldingen.append(
            "De app voegt deze keer alleen toe en past niets aan, omdat "
            + " en ".join(redenen) + ".")

    per_dag: dict[date, list[Shift]] = {}
    for x in shifts:
        per_dag.setdefault(x.roster_date or x.start.date(), []).append(x)
    if not per_dag:
        return plan
    dagen = sorted(per_dag)
    if roster.periode and not plan.alleen_toevoegen:
        eerste, laatste = roster.periode
        dagen = [eerste + timedelta(days=i) for i in range((laatste - eerste).days + 1)]
    # Ruim lezen: een nachtdienst loopt door tot in de volgende dag.
    plan.bereik = (datetime.combine(dagen[0], datetime.min.time()) - timedelta(days=1),
                   datetime.combine(dagen[-1], datetime.min.time()) + timedelta(days=3))
    gelezen = _lees(backend, plan.agenda, plan.agenda_nummer, *plan.bereik)

    half = _half_bijgewerkt()
    for g in gelezen:
        if g.aangepast and g.item.native_id in half:
            g.aangepast = False
    verplaatst = sum(1 for g in gelezen if g.versie == 2 and g.eigenaar == plan.eigenaar
                     and g.dag is not None and g.item.start.date() != g.dag)
    if verplaatst:
        plan.meldingen.append(
            f"{verplaatst} item(s) van de app heb je naar een andere dag gezet. "
            "Die laat de app met rust; ze worden niet meer bijgewerkt.")

    bekend = beheer.agenda(plan.beheer_sleutel)
    oude_bevestigd = keuzes.oude_items_zijn_van_mij or bool(bekend.get("oude_items_van_mij"))
    los_onbegrepen = None in roster.onbegrepen

    for dag in dagen:
        ruw = per_dag.get(dag, [])
        gewenst = sorted((gewenst_uit(x, roster.gegenereerd) for x in _zichtbaar(ruw, settings)),
                         key=lambda g: (g.start, g.titel))
        dp = DagPlan(dag, STAAT_ER_AL, gewenst=gewenst, dag_inhoud=_dag_inhoud(ruw))
        plan.dagen.append(dp)
        op_dag = [g for g in gelezen if g.item.start.date() == dag]
        eigen = _eigen_items(gelezen, plan.eigenaar, dag)
        dp.gezien = sorted(g.afdruk for g in eigen)

        if dag in roster.onbegrepen:
            dp.uitkomst, dp.reden = OVERGESLAGEN, "een regel op deze dag is niet begrepen"
            continue
        if any(g.start.date() != dag for g in gewenst):
            # Zou bij elke ronde een dubbel geven: de app herkent zijn eigen
            # items aan roosterdag én begindag.
            dp.uitkomst, dp.reden = OVERGESLAGEN, "een dienst begint niet op zijn roosterdag"
            continue
        if los_onbegrepen and not keuzes.onbegrepen_bevestigd:
            dp.uitkomst, dp.reden = OVERGESLAGEN, "het rooster bevat een regel die niet begrepen is"
            dp.keuze_nodig = True
            continue

        if plan.alleen_toevoegen or los_onbegrepen:
            _plan_alleen_toevoegen(dp, plan, op_dag, bool(roster.personeelsnummer))
            continue

        # --- beheerde stand: de dag gelijktrekken -------------------------
        over_eigen = list(eigen)
        over_gewenst = []
        for g in gewenst:  # 1. wat al precies klopt blijft onaangeroerd
            treffer = next((e for e in over_eigen
                            if not e.aangepast and e.inhoud == g.inhoud
                            and e.concept == g.concept), None)
            if treffer:
                over_eigen.remove(treffer)
            else:
                over_gewenst.append(g)

        # 2. items met het oude kenmerk (versie 1)
        oud = [g for g in op_dag if g.versie == 1]
        v1_eigen_tekst = False
        if oud and not oude_bevestigd:
            plan.oude_items += len(oud)
            # Zonder bevestiging: niet aankomen, en geen dubbel ernaast zetten.
            past = [o for o in oud if any(_v1_past(o, g) for g in over_gewenst)]
            over_gewenst = [g for g in over_gewenst if not any(_v1_past(o, g) for o in oud)]
            if len(past) < len(oud) and over_gewenst:
                dp.uitkomst, dp.keuze_nodig = MOGELIJK_DUBBEL, True
                dp.reden = ("er staat een ouder item van de app dat niet precies bij "
                            "het rooster past; er een dienst naast zetten kan een dubbele geven")
        elif oud:
            for g in list(over_gewenst):
                passend = [o for o in oud if _basis(o.item.title) == _basis(g.titel)
                           and _tijd_sleutel(o.item.start, o.item.end, o.item.all_day)
                           == _tijd_sleutel(g.start, g.end, g.all_day)]
                zelfde = [h for h in over_gewenst if _basis(h.titel) == _basis(g.titel)
                          and _tijd_sleutel(h.start, h.end, h.all_day)
                          == _tijd_sleutel(g.start, g.end, g.all_day)]
                if len(passend) == 1 and len(zelfde) == 1:  # eenduidig: overnemen
                    v1_eigen_tekst |= bool(_v1_eigen_tekst(passend[0], g))
                    oud.remove(passend[0])
                    over_gewenst.remove(g)
                    dp.stappen.append(Stap("werk_bij", passend[0].item,
                                           _zonder_oud_kenmerk(g, plan.eigenaar, passend[0].item)))
            if oud:
                if dag in keuzes.vervang_oude_items:
                    dp.stappen += [Stap("verwijder", o.item) for o in oud]
                else:
                    dp.uitkomst, dp.keuze_nodig = MOGELIJK_DUBBEL, True
                    dp.reden = f"{len(oud)} ouder item(s) van de app passen niet precies bij het rooster"

        # 3. de rest: aanpassen als het aantal gelijk is, anders vervangen
        gaat_weg = []
        if len(over_eigen) == 1 and len(over_gewenst) == 1:
            # Precies één tegenover één: het bestaande item aanpassen, zodat
            # eigen notities en herinnering blijven staan. Bij meer zou de
            # app moeten raden welk item bij welke dienst hoort.
            e, g = over_eigen[0], over_gewenst[0]
            dp.stappen.append(Stap("werk_bij", e.item, g.als_item(plan.eigenaar, e.item)))
        else:
            gaat_weg = over_eigen
            dp.stappen += [Stap("verwijder", e.item) for e in over_eigen]
            dp.stappen += [Stap("voeg_toe", None, g.als_item(plan.eigenaar)) for g in over_gewenst]

        if not dp.stappen:
            continue
        if dp.uitkomst != MOGELIJK_DUBBEL:
            if not eigen and not dp.verwijdert:
                dp.uitkomst = NIEUW
            elif not gewenst:
                dp.uitkomst = VERWIJDEREN
            elif not roster.is_concept and any(e.concept for e in eigen):
                dp.uitkomst = VERVANGT_CONCEPT
            else:
                dp.uitkomst = GEWIJZIGD
        if dag not in keuzes.overschrijf_aangepast:
            if any(e.aangepast for e in over_eigen):
                dp.uitkomst, dp.keuze_nodig = ZELF_AANGEPAST, True
                dp.reden = "je hebt een item van de app op deze dag zelf aangepast"
            elif any(any(e.eigen_tekst) for e in gaat_weg) or v1_eigen_tekst:
                dp.uitkomst, dp.keuze_nodig = ZELF_AANGEPAST, True
                dp.reden = ("een item dat vervangen wordt bevat een notitie van "
                            "jezelf; die zou verloren gaan")
            elif any((e.item.location or "").strip() not in
                     {"", *((g.location or "").strip() for g in gewenst)} for e in gaat_weg):
                dp.uitkomst, dp.keuze_nodig = ZELF_AANGEPAST, True
                dp.reden = ("een item dat vervangen wordt heeft een locatie van "
                            "jezelf; die zou verloren gaan")
        oordeel = _oordeel(_hoogste(bekend["dagen"].get(f"{dag:%Y%m%d}"), eigen),
                           plan.definitief, plan.gegenereerd, dp.dag_inhoud)
        if oordeel == OUDER_ROOSTER:
            dp.behoud_rang = True
            if not keuzes.ouder_toestaan:
                dp.uitkomst, dp.keuze_nodig = OUDER_ROOSTER, True
                dp.reden = "er is al een nieuwer rooster verwerkt voor deze dag"
        elif oordeel == ANDERE_INHOUD and not keuzes.andere_inhoud_toestaan:
            dp.uitkomst, dp.keuze_nodig = ANDERE_INHOUD, True
            dp.reden = ("er is al een rooster met dezelfde datum maar een andere "
                        "inhoud verwerkt")
    return plan


def _half_bijgewerkt() -> set[str]:
    """Items waarvan een aanpassing door de app begonnen maar niet afgerond is
    (de app viel uit). Een agenda zet titel, tijd en notitie niet in één keer;
    zo'n half item is dus niet door de gebruiker aangepast."""
    bezig: dict[int, str] = {}
    for r in _lees_journaal()[1:]:
        if r.get("fase") == "ga" and r.get("actie") == "werk_bij":
            bezig[r["n"]] = (r.get("na") or {}).get("native_id", "")
        elif r.get("fase") in ("klaar", "mislukt", "teruggezet"):
            bezig.pop(r.get("n"), None)
    return {n for n in bezig.values() if n}


def _v1_past(o: Gelezen, g: Gewenst) -> bool:
    return (_basis(o.item.title) == _basis(g.titel)
            and _tijd_sleutel(o.item.start, o.item.end, o.item.all_day)
            == _tijd_sleutel(g.start, g.end, g.all_day))


def _v1_eigen_tekst(o: Gelezen, g: Gewenst) -> list[str]:
    """Regels in de notitie van een item van versie 1 die niet van de app
    kunnen zijn. Versie 1 schreef de memo's, het kenmerk en het conceptlabel."""
    return [r for r in _regels(o.item.notes) if r.strip()
            and not MARKER_RE.search(r) and r.strip() != CONCEPT_TAG and r not in g.blok]


def _zonder_oud_kenmerk(g: Gewenst, eigenaar: str, bestaand: AgendaItem) -> AgendaItem:
    """Een item van versie 1 overnemen: het oude kenmerk en de oude tekst van
    de app gaan eruit, het nieuwe blok komt erin."""
    item = g.als_item(eigenaar)
    item.native_id, item.location = bestaand.native_id, bestaand.location
    return item


def _plan_alleen_toevoegen(dp: DagPlan, plan: Plan, op_dag: list[Gelezen],
                           eigenaar_bekend: bool) -> None:
    """Noodstand: alleen toevoegen wat er nog niet staat, verder niets.
    Zonder personeelsnummer is niet te zien welke items van wie zijn; dan
    telt elk item van de app mee (liever niets toevoegen dan een dubbele)."""
    van_de_app = [o for o in op_dag if o.versie == 1 or (
        o.versie == 2 and (o.eigenaar == plan.eigenaar or not eigenaar_bekend))]
    past = lambda o, g: (o.inhoud == g.inhoud if o.versie == 2 else (  # noqa: E731
        _basis(o.item.title) == _basis(g.titel)
        and _tijd_sleutel(o.item.start, o.item.end, o.item.all_day)
        == _tijd_sleutel(g.start, g.end, g.all_day)))
    if any(not any(past(o, g) for g in dp.gewenst) for o in van_de_app):
        # Er staat al iets van de app dat niet bij dit rooster past. Er een
        # dienst naast zetten geeft een dubbele; aanpassen mag nu niet.
        dp.uitkomst = OVERGESLAGEN
        dp.reden = ("er staat al een ander item van de app op deze dag; "
                    "dat kan de app nu niet veilig aanpassen")
        return
    for g in dp.gewenst:
        staat_er = any(past(o, g) for o in van_de_app) or any(
            o.item.title.strip().casefold() == g.titel.strip().casefold()
            and _tijd_sleutel(o.item.start, o.item.end, o.item.all_day)
            == _tijd_sleutel(g.start, g.end, g.all_day) for o in op_dag if not o.versie)
        if not staat_er:
            dp.stappen.append(Stap("voeg_toe", None, g.als_item(plan.eigenaar)))
    if dp.stappen:
        dp.uitkomst = NIEUW


# ----------------------------------------------------------------------
# Uitvoeren
# ----------------------------------------------------------------------
@dataclass
class Uitkomst:
    toegevoegd: int = 0
    bijgewerkt: int = 0
    verwijderd: int = 0
    dagen_klaar: list[date] = field(default_factory=list)
    #: dag -> waarom hij niet is bijgewerkt
    niet_bijgewerkt: dict[date, str] = field(default_factory=dict)
    fouten: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.fouten and not self.niet_bijgewerkt


def _item_dict(item: AgendaItem | None) -> dict | None:
    if item is None:
        return None
    d = asdict(item)
    d["start"], d["end"] = item.start.isoformat(), item.end.isoformat()
    return d


def _item_uit(d: dict | None) -> AgendaItem | None:
    if d is None:
        return None
    d = dict(d)
    d["start"], d["end"] = datetime.fromisoformat(d["start"]), datetime.fromisoformat(d["end"])
    return AgendaItem(**d)


class _Journaal:
    """Het logboek van één bijwerking: eerst 'ga', dan uitvoeren, dan 'klaar'.

    Het bestand wordt pas geopend bij de eerste echte stap: een ronde waarin
    niets gebeurt, laat de vorige bijwerking ongedaan te maken. Is de vorige
    bijwerking niet afgemaakt (de app viel uit), dan hoort deze ronde daarbij
    en wordt het journaal aangevuld; ongedaan maken draait dan beide terug.
    """

    def __init__(self, kop: dict):
        self.kop = kop
        self._fh = None
        self.n = 0

    def _open(self) -> None:
        pad = journaal_pad()
        pad.parent.mkdir(parents=True, exist_ok=True)
        oud = _lees_journaal()
        if (oud and not any(r.get("fase") == "einde" for r in oud)
                and oud[0].get("sleutel") == self.kop["sleutel"]
                and oud[0].get("backend") == self.kop["backend"]):
            self.n = max((r.get("n", 0) for r in oud), default=0)
            self._fh = open(pad, "a", encoding="utf-8")
            self.schrijf({"fase": "verder"})
        else:
            self._fh = open(pad, "w", encoding="utf-8")
            self.schrijf({"fase": "begin", **self.kop})

    def volgende(self) -> int:
        """Nummer voor de volgende stap (opent het journaal zo nodig eerst)."""
        if self._fh is None:
            self._open()
        self.n += 1
        return self.n

    def schrijf(self, regel: dict) -> None:
        if self._fh is None:
            self._open()
        self._fh.write(json.dumps(regel, ensure_ascii=False) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def sluit(self) -> None:
        if self._fh is not None:
            if not self._fh.closed:
                self.schrijf({"fase": "einde"})
            self._fh.close()


def _doe(backend: CalendarBackend, plan: Plan, stap: Stap) -> str:
    """Voer één stap uit; geeft het eigen nummer van het item terug."""
    if stap.actie == "voeg_toe":
        return backend.add_item(plan.agenda, plan.agenda_nummer, stap.na)
    if stap.actie == "werk_bij":
        backend.update_item(plan.agenda, plan.agenda_nummer, stap.na)
        return stap.na.native_id
    backend.delete_item(plan.agenda, plan.agenda_nummer, stap.voor.native_id)
    return stap.voor.native_id


def _omgekeerd(stap: Stap, native_id: str) -> Stap:
    if stap.actie == "voeg_toe":
        weg = AgendaItem(**{**asdict(stap.na), "native_id": native_id})
        return Stap("verwijder", weg)
    if stap.actie == "werk_bij":
        return Stap("werk_bij", stap.na, stap.voor)
    return Stap("voeg_toe", None, AgendaItem(**{**asdict(stap.voor), "native_id": ""}))


def _dag_klopt(gelezen: list[Gelezen], plan: Plan, dp: DagPlan) -> bool:
    eigen = _eigen_items(gelezen, plan.eigenaar, dp.dag)
    if plan.alleen_toevoegen:
        staat = [e.inhoud for e in eigen]
        return all(g.inhoud in staat for g in dp.gewenst
                   if any(s.na and Gelezen.van(s.na).inhoud == g.inhoud for s in dp.stappen))
    return (not any(e.aangepast for e in eigen)
            and sorted(e.inhoud for e in eigen) == sorted(g.inhoud for g in dp.gewenst))


def voer_uit(plan: Plan, backend: CalendarBackend, beheer: Beheer,
             keuzes: Keuzes | None = None, voortgang=None) -> Uitkomst:
    """Voer het plan uit. Een dag gaat helemaal of helemaal niet."""
    keuzes = keuzes or Keuzes()
    uit = Uitkomst()
    werk = [d for d in plan.dagen if d.stappen and not d.keuze_nodig]
    for d in [d for d in werk if d.verwijdert and not keuzes.verwijderen_bevestigd
              and not plan.alleen_toevoegen]:
        if d.netto_weg or any(
                s.actie == "verwijder" and Gelezen.van(s.voor).versie == 1 for s in d.stappen):
            uit.niet_bijgewerkt[d.dag] = "verwijderen is niet bevestigd"
            werk.remove(d)
    if not werk:
        return uit

    try:
        # Vlak voor het schrijven: staat alles er nog zoals op het controlescherm?
        nu = _lees(backend, plan.agenda, plan.agenda_nummer, *plan.bereik)
    except CalendarError as exc:
        uit.fouten.append(str(exc))
        return uit
    per_nummer = {g.item.native_id: g for g in nu}

    sleutel = plan.beheer_sleutel
    journaal = _Journaal({
        "agenda": plan.agenda, "agenda_nummer": plan.agenda_nummer, "sleutel": sleutel,
        "backend": backend.id,
        "bereik": [plan.bereik[0].isoformat(), plan.bereik[1].isoformat()],
        "beheer_voor": beheer.data["agendas"].get(sleutel),
    })
    gedaan_dagen: list[DagPlan] = []
    totaal = sum(len(d.stappen) for d in werk)
    teller = 0
    klaar = False
    try:
        for dp in werk:
            eigen_nu = sorted(g.afdruk for g in _eigen_items(nu, plan.eigenaar, dp.dag))
            anders = eigen_nu != dp.gezien or any(
                s.voor is not None and (
                    s.voor.native_id not in per_nummer
                    or per_nummer[s.voor.native_id].afdruk != Gelezen.van(s.voor).afdruk)
                for s in dp.stappen)
            if anders:
                uit.niet_bijgewerkt[dp.dag] = "de agenda is intussen veranderd"
                continue
            gedaan: list[tuple[Stap, str, int]] = []
            try:
                for stap in dp.stappen:
                    teller += 1
                    if voortgang:
                        voortgang(teller, totaal, f"{dp.dag:%d-%m}")
                    journaal.volgende()
                    journaal.schrijf({"fase": "ga", "n": journaal.n, "dag": dp.dag.isoformat(),
                                      "actie": stap.actie, "voor": _item_dict(stap.voor),
                                      "na": _item_dict(stap.na)})
                    nummer = _doe(backend, plan, stap)
                    gedaan.append((stap, nummer, journaal.n))
                    journaal.schrijf({"fase": "klaar", "n": journaal.n, "nummer": nummer})
            except CalendarError as exc:
                log.warning("Dag %s mislukt: %s", dp.dag, exc)
                if stap.actie == "werk_bij":
                    # Een agenda zet titel, tijd en notitie los: de mislukte
                    # stap kan half gelukt zijn. Die dus ook terugzetten.
                    gedaan.append((stap, stap.na.native_id, journaal.n))
                else:
                    journaal.schrijf({"fase": "mislukt", "n": journaal.n})
                terug = _zet_terug(backend, plan, gedaan, journaal)
                uit.niet_bijgewerkt[dp.dag] = (
                    f"een stap mislukte ({exc}); de dag is teruggezet" if terug else
                    f"een stap mislukte ({exc}) en terugzetten lukte niet helemaal")
                if not terug:
                    uit.fouten.append(f"{dp.dag:%d-%m-%Y}: terugzetten is niet helemaal gelukt")
                continue
            gedaan_dagen.append(dp)
            if len(gedaan_dagen) == 1:
                # Eerste dag: geeft de agenda terug wat de app schreef? Zo
                # niet, dan stoppen vóór er meer dagen geraakt worden.
                try:
                    proef = _lees(backend, plan.agenda, plan.agenda_nummer, *plan.bereik)
                except CalendarError as exc:
                    uit.fouten.append(f"Controle na de eerste dag mislukt: {exc}")
                    proef = None
                if proef is None or not _dag_klopt(proef, plan, dp):
                    if proef is not None:
                        uit.fouten.append(
                            "De agenda geeft items anders terug dan de app ze schreef. "
                            "Er is na de eerste dag gestopt. Stuur het logboek mee via Feedback.")
                    for stap, _, _ in gedaan:
                        uit.toegevoegd += stap.actie == "voeg_toe"
                        uit.bijgewerkt += stap.actie == "werk_bij"
                        uit.verwijderd += stap.actie == "verwijder"
                    break
            for stap, _, _ in gedaan:
                uit.toegevoegd += stap.actie == "voeg_toe"
                uit.bijgewerkt += stap.actie == "werk_bij"
                uit.verwijderd += stap.actie == "verwijder"

        # Terugkijken: een dag telt pas als de agenda echt gelijk is aan het rooster.
        try:
            na = _lees(backend, plan.agenda, plan.agenda_nummer, *plan.bereik)
        except CalendarError as exc:
            uit.fouten.append(f"Controle achteraf mislukt: {exc}")
            return uit
        dagen = beheer.agenda(sleutel)["dagen"]
        if keuzes.oude_items_zijn_van_mij:
            beheer.agenda(sleutel)["oude_items_van_mij"] = True
        controle = gedaan_dagen + ([] if plan.alleen_toevoegen else
                                   [d for d in plan.dagen if d.uitkomst == STAAT_ER_AL])
        for dp in controle:
            if not _dag_klopt(na, plan, dp):
                if dp in gedaan_dagen:
                    uit.niet_bijgewerkt[dp.dag] = "na het schrijven klopte de dag niet"
                continue
            if dp in gedaan_dagen:
                uit.dagen_klaar.append(dp.dag)
            if plan.alleen_toevoegen:
                continue
            oud = dagen.get(f"{dp.dag:%Y%m%d}")
            if oud and (dp.behoud_rang or _oordeel(oud, plan.definitief, plan.gegenereerd,
                                                   dp.dag_inhoud) == OUDER_ROOSTER):
                dagen[f"{dp.dag:%Y%m%d}"] = {**oud, "inhoud": None}
            else:
                d, g = _rang(plan.definitief, plan.gegenereerd)
                dagen[f"{dp.dag:%Y%m%d}"] = {"def": d, "gen": g, "inhoud": dp.dag_inhoud}
        beheer.bewaar()
        klaar = True
    finally:
        if klaar:
            journaal.sluit()
        elif journaal._fh is not None:
            journaal._fh.close()  # uitgevallen: geen 'einde', zodat de volgende ronde aanvult
    log.info("Bijgewerkt: +%d ~%d -%d, %d dag(en) niet", uit.toegevoegd, uit.bijgewerkt,
             uit.verwijderd, len(uit.niet_bijgewerkt))
    return uit


def _zet_terug(backend, plan: Plan, gedaan: list[tuple[Stap, str, int]],
               journaal: _Journaal) -> bool:
    gelukt = True
    for stap, nummer, n in reversed(gedaan):
        try:
            _doe(backend, plan, _omgekeerd(stap, nummer))
            journaal.schrijf({"fase": "teruggezet", "n": n})
        except CalendarError:
            log.exception("Terugzetten van een stap mislukt")
            gelukt = False
    return gelukt


# ----------------------------------------------------------------------
# Ongedaan maken
# ----------------------------------------------------------------------
@dataclass
class Ongedaan:
    hersteld: int = 0
    #: Items die sinds de bijwerking met de hand zijn aangepast: blijven staan.
    blijft_staan: list[str] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)


def kan_ongedaan() -> bool:
    return bool(_lees_journaal())


def _lees_journaal() -> list[dict]:
    try:
        # split("\n"), niet splitlines(): die knipt ook op tekens als U+2028
        # die gewoon in een notitie kunnen staan.
        tekst = [r for r in journaal_pad().read_text(encoding="utf-8").split("\n") if r.strip()]
    except OSError:
        return []
    regels = []
    for i, r in enumerate(tekst):
        try:
            regels.append(json.loads(r))
        except ValueError:
            if i < len(tekst) - 1:
                return []  # kapot midden in het journaal: niet op vertrouwen
            # Alleen de laatste regel is half geschreven (stroom uitgevallen).
    return regels if regels and regels[0].get("fase") == "begin" else []


def maak_ongedaan(backend: CalendarBackend, beheer: Beheer) -> Ongedaan:
    """Draai de laatste bijwerking terug, stap voor stap in omgekeerde volgorde."""
    uit = Ongedaan()
    regels = _lees_journaal()
    if not regels:
        uit.fouten.append("Er is geen bijwerking om ongedaan te maken.")
        return uit
    kop = regels[0]
    agenda, nummer = kop["agenda"], kop["agenda_nummer"]
    if kop.get("backend", backend.id) != backend.id:
        uit.fouten.append("De laatste bijwerking was in een andere agenda-app. "
                          "Kies die eerst weer bij Instellingen.")
        return uit
    stappen: dict[int, dict] = {}
    al_terug: set[int] = set()  # teruggezet bij uitvoeren, of al ongedaan gemaakt
    for r in regels[1:]:
        if r["fase"] == "ga":
            stappen[r["n"]] = r
        elif r["fase"] == "klaar" and r["n"] in stappen:
            stappen[r["n"]]["nummer"] = r["nummer"]
        elif r["fase"] == "mislukt":
            stappen.pop(r["n"], None)
        elif r["fase"] in ("teruggezet", "ongedaan"):
            al_terug.add(r["n"])
    try:
        van, tot = (datetime.fromisoformat(x) for x in kop["bereik"])
        nu = {g.item.native_id: g for g in _lees(backend, agenda, nummer, van, tot)}
    except (CalendarError, KeyError, ValueError) as exc:
        uit.fouten.append(f"Kan de agenda niet lezen: {exc}")
        return uit

    def zelfde(g: Gelezen, verwacht: AgendaItem) -> bool:
        v = Gelezen.van(verwacht)
        if (g.item.location or "").strip() != (verwacht.location or "").strip():
            return False
        return (g.item.title.strip() == verwacht.title.strip()
                and _tijd_sleutel(g.item.start, g.item.end, g.item.all_day)
                == _tijd_sleutel(verwacht.start, verwacht.end, verwacht.all_day)
                and _regels(g.item.notes) == _regels(verwacht.notes)) or (
                    g.versie == 2 and not g.aangepast and g.inhoud == v.inhoud
                    and g.eigen_tekst == v.eigen_tekst)

    def gedaan(n: int) -> None:
        # Per stap noteren, zodat opnieuw proberen na een fout niets dubbel doet.
        with open(journaal_pad(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"fase": "ongedaan", "n": n}) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    teruggezet_ids: set[str] = set()
    for n in sorted(stappen, reverse=True):
        if n in al_terug:
            continue
        r = stappen[n]
        voor, na = _item_uit(r["voor"]), _item_uit(r["na"])
        try:
            if r["actie"] == "verwijder":
                # Na uitval en een tweede ronde kan hetzelfde item twee keer
                # als "verwijder" in het journaal staan: maar één keer terugzetten.
                if (("nummer" in r or voor.native_id not in nu)
                        and voor.native_id not in teruggezet_ids):
                    backend.add_item(agenda, nummer, AgendaItem(**{**asdict(voor), "native_id": ""}))
                    teruggezet_ids.add(voor.native_id)
                    uit.hersteld += 1
                for m, rr in stappen.items():  # ook de dubbele vermelding afvinken
                    if rr["actie"] == "verwijder" and (rr["voor"] or {}).get("native_id") == voor.native_id:
                        gedaan(m)
                        al_terug.add(m)
                continue
            # toegevoegd of bijgewerkt: zoek het item zoals de app het achterliet
            staat = nu.get(r.get("nummer") or (na.native_id if r["actie"] == "werk_bij" else ""))
            if staat is None and "nummer" not in r and r["actie"] == "voeg_toe":
                staat = next((g for g in nu.values() if zelfde(g, na)), None)
            if staat is None:
                gedaan(n)  # stap is nooit uitgevoerd, of het item is al weg
                continue
            if not zelfde(staat, na):
                uit.blijft_staan.append(f"{staat.item.start:%d-%m-%Y} {staat.item.title}")
                continue
            if r["actie"] == "voeg_toe":
                backend.delete_item(agenda, nummer, staat.item.native_id)
                nu.pop(staat.item.native_id, None)
            else:
                backend.update_item(agenda, nummer, AgendaItem(
                    **{**asdict(voor), "native_id": staat.item.native_id}))
            uit.hersteld += 1
            gedaan(n)
        except CalendarError as exc:
            uit.fouten.append(str(exc))
    if not uit.fouten:
        if kop.get("beheer_voor") is None:
            beheer.data["agendas"].pop(kop["sleutel"], None)
        else:
            beheer.data["agendas"][kop["sleutel"]] = kop["beheer_voor"]
        beheer.bewaar()
        try:
            os.replace(journaal_pad(), journaal_pad().with_suffix(".ongedaan"))
        except OSError:
            pass
    log.info("Ongedaan gemaakt: %d hersteld, %d blijft staan", uit.hersteld, len(uit.blijft_staan))
    return uit
