# Ontwerp: de agenda echt bijwerken (versie 2)

Dit is het riskantste deel van de app: hier wordt gewijzigd en verwijderd.
Het ontwerp is daarom zo gemaakt dat de agenda zelf altijd de waarheid is en
dat bij twijfel niets gebeurt.

## Kern

- **Eenheid is de dag.** Per roosterdag vergelijkt de app zijn eigen items in
  de agenda met de diensten uit de pdf. Gelijk: niets doen. Anders: de dag
  wordt gelijkgetrokken. Er wordt nooit geraden welk oud item bij welk nieuw
  item hoort.
- **Een dag gaat helemaal of helemaal niet.** Mislukt één stap, dan wordt de
  dag teruggezet.
- **Plannen en uitvoeren zijn gescheiden.** `maak_plan()` leest alleen en
  levert een `Plan`; de gebruiker ziet dat; `voer_uit()` schrijft.

## Kenmerk in de notitie

```
Uit je werkrooster:
Activiteit: …
07:00-11:30 …
[WerkroosterSync:2:<eigenaar>:<jjjjmmdd>:<inhoud>:<d|c><jjjjmmdduumm>]
```

- `eigenaar`: 10 tekens van sha256 over het personeelsnummer. Niet leesbaar
  als nummer; geen geheim (een 8-cijferig nummer is terug te rekenen), het
  dient alleen om items van twee medewerkers uit elkaar te houden.
- `jjjjmmdd`: de roosterdatum, de dag waaronder de dienst in de pdf staat.
  Een nachtdienst hoort bij de dag waarop hij begint.
- `inhoud`: 10 tekens vingerafdruk van wat de app schreef: titel, begin,
  eind, hele-dag en het eigen blok. Wijkt het item daarvan af, dan heeft de
  gebruiker het aangepast.
- `d`/`c`: definitief of concept, gevolgd door de generatiedatum van het
  rooster (als die bekend is). Zo weet ook een tweede computer zonder
  `beheer.json` welk rooster het laatst gewonnen heeft.
- Alles tussen de regel "Uit je werkrooster:" en het kenmerk is van de app.
  Tekst daarbuiten is van de gebruiker en blijft bij bijwerken staan.
  Herinnering, kleur en locatie zijn ook van de gebruiker. Een item met een
  eigen locatie of eigen tekst wordt niet stil vervangen ("zelf aangepast").
- Staat het kenmerk er twee keer in (gekopieerd), dan telt het item als
  aangepast; bij overschrijven blijft er één kenmerk over.
- Het oude kenmerk `[WerkroosterSync:<12 tekens>]` (versie 1) wordt herkend
  maar bewijst geen eigenaar.

Vergelijken gebeurt op genormaliseerde inhoud (tijden op de minuut, hele dag
als datum + aantal dagen, regeleinden en witruimte gelijkgetrokken), omdat
Outlook en Apple Agenda tekst en tijden net anders teruggeven.

## Wat de agenda-koppeling moet kunnen

`lees(agenda, van, tot)` geeft volledige items (eigen nummer van de agenda,
titel, tijden, notitie, locatie); `voeg_toe`, `werk_bij`, `verwijder` werken
op dat eigen nummer; `agendas()` geeft naam plus een vast nummer per agenda
(Apple: `calendarIdentifier`; Outlook: StoreID + EntryID). Zonder vast
nummer wordt er niet verwijderd of gewijzigd.

## Plan per dag

Voor elke dag in de periode van de pdf:

| Situatie | Uitkomst |
|---|---|
| eigen items gelijk aan pdf | staat er al |
| geen eigen items, wel diensten | nieuw |
| precies één tegenover één, andere inhoud | gewijzigd: bestaand item aanpassen |
| anders | vervangen: oude weg, nieuwe erbij (nooit raden wat bij wat hoort) |
| eigen item was concept, pdf is definitief | vervangt concept |
| eigen items, geen dienst meer | wordt verwijderd |
| een eigen item is met de hand aangepast | zelf aangepast: gebruiker kiest |
| dag heeft een onbegrepen regel | overgeslagen, ook niet toevoegen |
| ouder rooster dan al verwerkt | overgeslagen tot bevestiging |

Verdwijnen er op een dag netto items (meer weg dan erbij), dan vraagt dat
een eigen bevestiging; zonder die bevestiging blijft de hele dag staan.
Vervangen (één weg, één erbij) vraagt dat niet: de dienst blijft bestaan.

Een dienst die niet begint op zijn roosterdag wordt overgeslagen: de app
herkent zijn items aan roosterdag én begindag, anders zou elke ronde een
dubbele geven.

Wijzigen en verwijderen mag alleen als `Roster.mag_aanpassen(dag)` waar is,
het kenmerk dezelfde eigenaar heeft en de agenda een vast nummer heeft dat
gelijk is aan het nummer dat de app voor die agenda beheert. Anders geldt
**alleen toevoegen**: diensten die er nog niet staan komen erbij, verder
niets. Zonder personeelsnummer telt daarbij elk item van de app als
mogelijk eigen item (liever niets toevoegen dan een dubbele).

## Overstap van versie 1

Items met het oude kenmerk tellen pas mee nadat de gebruiker één keer heeft
bevestigd dat in deze agenda alleen zijn eigen diensten staan. Daarna wordt
een oud item overgenomen (krijgt het nieuwe kenmerk) als datum, soort en
tijden precies bij één dienst van die dag passen. Staat er in de notitie
tekst die niet van versie 1 kan zijn, dan "zelf aangepast". Is het niet
eenduidig, dan toont het plan "mogelijk dubbel" en kiest de gebruiker. Ook
zonder bevestiging zet de app geen dienst naast een oud item dat net niet
past.

## Welk rooster wint

Per medewerker, agenda en dag onthoudt `beheer.json` de rang van het laatst
verwerkte rooster: (definitief boven concept, generatiedatum) plus een
vingerafdruk van de dag. Ook lege dagen.

- hogere rang: verwerken;
- zelfde rang en zelfde inhoud: verwerken (herstelt een half uitgevoerde dag);
- zelfde datum met andere inhoud: gebruiker beslist;
- geen generatiedatum terwijl het vorige rooster er wel een had: gebruiker
  beslist (nieuwer valt niet te bewijzen);
- lagere rang: waarschuwen, niets doen tot bevestiging. Na bevestiging wordt
  de inhoud van die dagen teruggezet, maar de onthouden rang blijft de hoge
  (zonder vastgelegde inhoud, zodat het nieuwste rooster daarna weer zonder
  vraag wint).

Meerdere roosters tegelijk worden op rangvolgorde verwerkt: laagste eerst.

Een dag telt pas als verwerkt nadat de agenda is teruggelezen en gelijk is
aan het rooster.

## Uitvoeren, afbreken en herstellen

1. Vlak voor het schrijven wordt de agenda opnieuw gelezen. Een dag waarvan
   de eigen items anders zijn dan in het plan wordt overgeslagen.
2. Per stap: eerst in het journaal ("ga dit doen", met volledige kopie van
   het item), dan uitvoeren, dan de uitkomst noteren.
3. Mislukt een stap, dan worden de al gedane stappen van die dag omgekeerd.
4. Na afloop terugkijken in de agenda; alleen kloppende dagen gaan naar
   `beheer.json`.

Het journaal opent pas bij de eerste echte stap; een ronde zonder werk laat
de vorige bijwerking dus ongedaan te maken. Een stap die halverwege mislukt
(titel wel, notitie niet) wordt ook teruggezet. Teruggezette en ongedaan
gemaakte stappen worden per stap afgevinkt, zodat opnieuw proberen niets
dubbel doet.

Valt de app halverwege uit, dan is er niets te repareren aan het journaal:
bij de volgende keer vergelijkt het plan opnieuw de agenda met het rooster en
voert alleen het verschil uit. Omdat elk item zijn eigen inhoud-vingerafdruk
draagt, levert dat geen dubbelen op. Het journaal van de onderbroken ronde
wordt aangevuld (niet overschreven), zodat ongedaan maken beide rondes
terugdraait. Het journaal onthoudt welke agenda-app gebruikt werd; ongedaan
maken in een andere app wordt geweigerd.

**Ongedaan maken** draait de laatste uitvoering om, stap voor stap in
omgekeerde volgorde, en zet `beheer.json` terug. Een item dat sindsdien met
de hand is aangepast blijft staan en wordt gemeld.

## Breekpunten die getest worden

- afbreken vóór een stap, tussen uitvoeren en noteren, en na de stap; daarna
  opnieuw draaien geeft precies het gewenste eindbeeld zonder dubbelen;
- een stap die mislukt midden op een dag: dag is terug zoals hij was;
- item met de hand aangepast tussen plan en uitvoeren: dag overgeslagen;
- twee medewerkers in dezelfde agenda: elkaars items blijven staan;
- agenda zonder vast nummer, onvolledige pdf, noodstand: alleen toevoegen;
- ouder rooster na nieuwer; concept na definitief; zelfde datum, andere inhoud;
- dienst gesplitst, samengevoegd, vervallen; nachtdienst over middernacht en
  over de periodegrens;
- ongedaan maken, ook nadat één item met de hand is aangepast.

## Bestand voor een andere agenda (.ics)

Die route kan de agenda niet inzien: alleen een bestand maken. Elk item
krijgt een vast `UID` (`bijwerken.vaste_uids`: eigenaar + roosterdatum + volgnummer), zodat
agenda-apps die dat ondersteunen bij opnieuw inlezen bijwerken in plaats van
verdubbelen.
