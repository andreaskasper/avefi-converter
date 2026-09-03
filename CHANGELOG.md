# Änderungsprotokoll

`avefi-converter` — Arbeitsstand zum **Leistungspaket A** des Werkvertrags mit
der TIB Hannover: ein vollautomatischer LIDO-Importer als Python-Modul für
`efi-conv`.

## Was dieses Protokoll abdeckt — und was nicht

Dieses Repository ist ein **Abkömmling von `AV-EFI/efi-conv`**. Der weitaus
größte Teil seiner Geschichte stammt nicht von uns: 156 Commits von Elias
Oltmanns (GWDG), dazu Abhängigkeits-Aktualisierungen. Der `avportal`-Konverter,
das `check`-Modul und das Grundgerüst sind Vorarbeit anderer.

Hier steht ausschließlich, **was wir beigetragen haben** — 52 Commits, beginnend
am 27.07.2026, dazu ein Dockerfile vom 06.03.2025. Die Historie des
Ursprungsrepositories bleibt dort, wo sie hingehört.

Wie im Protokoll des Importers ist nach **Rückmelderunden** gegliedert und nicht
nach Commits, und jeder Eintrag nennt, **wer** etwas gemeldet hat. Für Paket A
ist das fast durchgängig Elias Oltmanns, der das technische Review führt und die
Abnahme verantwortet.

Zeitzone Europe/Berlin.

> **Offen und vertraglich geschuldet:** Die Leistungsbeschreibung verlangt Paket
> A ausdrücklich als **Pull Request auf `AV-EFI/efi-conv`**, Modulname
> `efi_conv.fmdu.lido`, und nennt ihn unter den Liefergegenständen. Dieser PR
> existiert bis heute nicht. Siehe „Offene Punkte" am Ende.

---

## 2026-09-03 — Elias Oltmanns, Kommentar zu PR #34

Gemeldet im Pull Request: im Wurzelverzeichnis lagen versehentlich mehrere
`*.json`-Dateien und `diff.md`.

Entfernt wurden `a.json`, `b.json`, `arep.json`, `brep.json`, `rep.json`,
`csv.json`, `diff.json`, `lido.json`, `jonas.json`, `slub.json` und `diff.md`,
zusammen rund 97 MB. Es waren Konvertierungsergebnisse aus Testläufen, kein
Liefergegenstand; kein Modul und kein Test greift auf sie zu. Damit sie nicht
wiederkommen, fängt die `.gitignore` jetzt `*.json` und `diff.md` im Wurzel-
verzeichnis ab — Dateien in `src/`, `tests/` und `examples/` bleiben unberührt.

Die Historie wurde nicht umgeschrieben. Elias hatte einen Rebase angeboten,
ihn aber ausdrücklich nicht verlangt. Gepackt wiegen die Dateien im Objekt-
speicher rund 5 MB, ein frischer Klon bleibt damit klein; das rechtfertigt
keinen Force-Push auf einen Branch mit 53 Commits, gegen den gerade getestet
wird.

---

## 2026-08-18 — Elias Oltmanns, zweite Reviewrunde

Commits `c8176f8`, `07c247e`.

Beide Wünsche wurden am Tag der Meldung umgesetzt. **Mitgeteilt wurden sie erst
am 01.09.2026** — dreizehn Tage, in denen gegen einen Stand getestet wurde, der
die Anmerkungen längst enthielt. Das ist der ärgerlichste Fehler dieses Pakets
und keiner im Code.

### Zugangsstatus mit Vorrang (`c8176f8`)

**Gemeldet von Elias Oltmanns.** `has_access_status` ist bei AVefi einwertig,
ein Datensatz kann aber mehrere Angaben tragen. Eine Kopie, die als
„Verleihkopie" und als „Deakzession" geführt war, kam als `Distribution` heraus,
weil der Verleihvermerk zufällig zuerst notiert war — das Ergebnis hing an der
Tippreihenfolge der Katalogisierin. Gewünscht: Vorrang für „deakzession", egal an
welcher Stelle sie steht, sonst weiterhin der erste Eintrag.

Umgesetzt, aber **nicht im Code**: Die Regel steht als `access_status_priority`
im Profil (`lido/profile.py`, Vorgabe `("Removed",)`), und die Werteliste in
`fmdu/lido.py` bildet „deakzession" und „deakzessioniert" darauf ab. Ein anderes
Haus mit anderen Vorrangregeln braucht damit keinen Codeeingriff. Wo der Vorrang
greift und einen anderen Status verdrängt, steht das im Bericht — ein stilles
Vorziehen wäre eine Entscheidung, die niemand sieht.

**Eine eigene Korrektur dabei:** `Removed` verlangt einen AVefi-Identifikator,
und wir hatten zunächst einen Umgehungsweg gebaut, wenn keiner da ist. Das war
falsch. Eine Lieferung mit Exemplaren, die das Haus nicht mehr besitzt, würde
sonst darum bitten, für sie PIDs zu vergeben — und genau das soll `efi-conv
check` sichtbar machen, bevor es passiert. Die Beanstandung ist der Zweck.
`Removed` wird jetzt geschrieben, wo die Quelle es sagt. Wer solche Exemplare
gar nicht liefern will, nimmt `efi-conv from --skip-removed`; das lässt sie weg,
nennt jedes einzelne und entfernt auch Fassungen und Werke, deren letztes
Exemplar dabei wegfällt. Im Referenzexport sind das **17 Exemplare, 9 Fassungen
und 4 Werke**.

### Vergleich über PIDs statt über lokale Identifier (`07c247e`)

**Gemeldet von Elias Oltmanns.** Auf Manifestations- und Werksebene ließen sich
die Ergebnisse nicht gegen den CSV-Export prüfen. Wunsch: Das diff-Modul soll
auch Datensätze mit übereinstimmenden PIDs vergleichen, wenn die lokalen
Identifier auseinandergehen.

Die Vermutung war richtig, und deutlicher als gedacht: Zwei Konverter, die
dieselbe Sammlung aus zwei Quellformaten lesen, erzeugen verschiedene lokale
Identifier. Von **2218 Werken**, die in beiden Lieferungen stehen, stimmte
**kein einziger** lokaler Identifier überein; **2217 PIDs** stimmten. Der
Vergleich meldete deshalb fast jeden Datensatz gleichzeitig als fehlend und als
hinzugekommen: 5140 fehlend, 10083 hinzugekommen, 12562 verändert.

Zwei Änderungen tragen die Lösung: Ein Datensatz wird als Ganzes gepaart statt
einmal je Identifikator, den er trägt, und ein gemeinsamer PID entscheidet vor
einem gemeinsamen lokalen Identifier — ein lokaler Identifier kann neu vergeben
werden, ein Handle nicht. Danach: **8850 von 8851 Referenzdatensätzen gepaart**,
einer fehlt, und was an Unterschieden bleibt, sind Unterschiede in den Daten
statt in der Benennung.

### Am selben Tag, ohne Meldung: MARC21 und die SLUB

Commits `1323322`, `2bf84a2`, `016a42e`, `f5a5331`, `4bdb29d`, `9f2dca3`,
`6dc8076`, `a99c685`.

Aus der Zusammenarbeit mit Jonas Pitz (Deutsche Kinemathek) und dem Vergleich
mit dessen refaktoriertem Konverter:

- **Werkbildung über Feld 776 statt über Heuristik.** Bisher wurden Werke über
  Titel, Regie und Jahr gebildet, wenn keine 776 vorlag — daher 120 statt 157
  Werke im Paderborner Vergleich. Feld 776 enthält echte Verlinkungen
  („bearbeitete digitale Ausgabe", „elektronische Reproduktion von"); daraus
  lassen sich Werk, Fassung und Exemplar direkt ableiten, geraten werden muss
  nichts.
- **Träger aus der RDA-Katalogisierung lesen** statt aus der Sammlung, in der
  ein Datensatz liegt.
- **Was ein Datensatz in Worten sagt**, wird gelesen, nicht nur die festen
  Felder.
- **Profil für den Dresdner MARC21-Export der SLUB**, an den realen Export
  angepasst; als Webressource wird der k10plus-OPAC eingetragen, wie von der
  Bibliothek gewünscht.
- **Dokumentation**, was beauftragt war und was darüber hinaus entstanden ist.

---

## 2026-08-14 — Elias Oltmanns, erste Reviewrunde

Commits `2c6af73` (#1), `0ef246e` (#2), `0e00548` (#3), `4da9dd9` (#4).

Acht Anpassungswünsche, alle am selben Tag umgesetzt, mit Tests und einem
Beispiel-Datensatz aus Elias' LIDO-Schnipsel in `tests/lido/sample_data.xml`
(Datensatz `FMDU-0005`), damit sie dauerhaft abgedeckt bleiben.

1. **`objectPublishedID` mit einer URL wird zu `has_webresource` am Exemplar.**
   Entschieden wird am Wert, nicht am `lido:type` — Düsseldorf typisiert die
   Objektseite als `lido00100` („Local identifier"), eine URL ist sie trotzdem.
2.–4. **Sprachen werden über `lido:label` geroutet:** Dialogton →
   `SpokenLanguage`, Untertitel → `Subtitles`, Zwischentitel → `Intertitles`.
   „Ohne Sprache" unter Dialogton wird zu `{"usage": ["NoDialogue"]}`, ohne
   Sprachcode. Der LIDO-Importer schrieb hier bisher `zxx`; der CSV-Importer
   desselben Hauses schreibt es seit jeher ohne Code, insofern war `zxx` der
   Ausreißer.
5. **Die Klammer-Regel für Archivtitel** (`[Titel]` → `SuppliedDevisedTitle`)
   griff nicht auf Werksebene. Ursache: Kommt das Werk aus einem
   `relatedWorkSet`, holt es seinen Titel aus `lido:displayObject`, und der wurde
   als reine Zeichenkette übernommen. Jetzt geht er durch dieselbe
   Titelverarbeitung wie alle anderen, inklusive Artikelumstellung für
   `has_ordering_name`.
6. **`lido:type="corporation"` ergibt `CorporateBody`.** Die Typ-Liste ist dabei
   aus dem Code ins Profil gewandert, damit das nächste Haus mit einer eigenen
   Schreibweise keinen Code-Patch braucht.
7./8. **Werk- und Fassungs-PIDs kommen an:** `relType "Film"` liefert die des
   Werks, `is_item_of` die der Manifestation (erkannt an der `conceptID`, der
   Term „is item of" wird ebenfalls akzeptiert). Der Filmportal-Identifier wird
   zu `same_as` am Werk, als bloße ID ohne die URL, in der sie steht.

**Wichtig dabei:** Die PID wird *neben* den lokalen Identifier gestellt, nie an
dessen Stelle, weil `is_item_of` und `is_manifestation_of` über den lokalen
Identifier verweisen. Der bleibt der erste Eintrag in `has_identifier`.

**Ein Fehler, den Elias' Beispiel sichtbar gemacht hat:** Aus
`relatedWork/object` wurde bisher schlicht die erste `objectID` als lokale ID
genommen. Das ging nur gut, solange das Haus seine eigene zuerst schreibt. Jetzt
wird nach dem Wert unterschieden.

### Aus derselben Runde, am Abend nachgereicht (`0ef246e`)

- **Handles werden nicht mehr am Präfix `21.11155` erkannt**, sondern an
  `lido:source="www.av-efi.net"` — perspektivisch sind andere Präfixe möglich.
- **Filmportal-IDs entsprechend an `lido:source="www.filmportal.de"`**, wobei
  beide URL-Formen (mit und ohne `/film/`) verarbeitet werden.
- **Mehrere Exemplare können mit derselben Manifestation verknüpft sein.** Liegt
  ein PID mit `relType is_item_of` vor, wird geprüft, ob es die Manifestation
  schon gibt; falls ja, folgt ein Konsistenzcheck, dass sie mit demselben Werk
  verknüpft ist. Vorher wurden mehrere Manifestationen mit demselben PID
  ausgegeben, und `efi-conv check` monierte zu Recht uneindeutige Identifier.

### Aus eigenem Antrieb (`0e00548`)

Nicht gefordert, aber direkt aus der Runde folgend: **Die Konvertierung
vergleicht jetzt ihre eigene Ein- und Ausgabe.** Jedes Handle, das ein Datensatz
in einen Identifikator schreibt, wird in den daraus gebauten Datensätzen gesucht;
fehlt es, gibt es eine Warnung samt der Beziehung, unter der es stand.

Der Anlass: Genau das war vorher nicht zu sehen. Der Lauf war erfolgreich, die
Ausgabe valide — aufgefallen ist der Verlust erst Elias beim Vergleich von Ein-
und Ausgabe von Hand.

---

## 2026-08-11 — Kick-Off, Mapping für das Filmmuseum Düsseldorf

Commits `6ff41b6`, `961764c`, `460cb53`, `1adcad8`, `418332a`, `298019d`,
`46a8c6c`, `c8ca049`, `aab8393`, `ceb20e6`, `4b6466f`, `969d709`, `b457a5c`,
`546e8de`, `7d90ed8`, `d4120f2`.

Am Tag des Kick-Off-Treffens. Der LIDO-Importer wird an den realen Düsseldorfer
Export angepasst. Referenzexport: **5562 Datensätze / 3717 Werke.**

Die Eigenheiten dieses Exports, die dabei zutage traten und die im Profil und
nicht im Code stehen:

- `recordType` sagt selbst, dass es ein Exemplar ist — besser, als es aus
  `objectWorkType` zu erraten, dort steht der Träger (`4b6466f`).
- Der Identifier ist das **letzte** Segment von `lidoRecID`
  (`DE-MUS-042628:DE-MUS-432511:1059195` → `1059195`) (`969d709`).
- Die Laufzeit steht in **Stunden**, obwohl die Spalte „Min" heißt (`aab8393`).
- Sprache, Zugangsstatus und Arbeitsnotizen liegen gemeinsam unter „Schlagwort"
  (`c8ca049`).
- Mitwirkende stehen im Ereignis „Geistige Schöpfung", nicht in „Produktion"
  (`298019d`).

Dazu: Datumsangaben in den Schreibweisen, die Katalogisierende tatsächlich
benutzen (`1adcad8`); ein unlesbares Datum kostet das Feld, nicht den Datensatz
(`460cb53`); der AVefi-Identifikator, den ein Exemplar schon trägt, wird
zurückgetragen (`418332a`); die technische Beschreibung wird dort gelesen, wo
dieses Haus sie schreibt (`46a8c6c`); Trennung dessen, was ein Film *ist*, wie er
*beschaffen* ist und wovon er *handelt* (`546e8de`); Länge eines Exemplars samt
Meldung, wenn sie nicht stimmen kann (`7d90ed8`).

Und: **das Handbuch für die Menschen, die die Konvertierungen fahren**
(`ceb20e6`), später an den Stand der Mappings angeglichen (`d4120f2`).

---

## 2026-07-27 und 28 — Vorarbeit, vor dem Werkvertrag

Commits `e8a78a6` bis `6087e49`.

Entstanden **vor** dem formellen Go am 31.07.2026. Beim Kick-Off war das der
gezeigte Zwischenstand.

- **LIDO-Importer, Konvertierungsbericht und `diff`-Kommando** (`c60440e`), im
  Umfang gehalten, den das Modul haben soll (`92157d9`).
- **Fünf weitere Konverter:** EN 15907 für EFG-Dokumente (`bc0d687`), MARC21-XML
  (`30b6341`), PBCore 2.1 (`c13acaf`), EBUCore (`acb6cb0`) und Dublin Core mit
  ausdrücklich benannten Grenzen (`7a873f5`). Was jeder Konverter braucht, wurde
  vorher aus dem LIDO-Modul herausgehoben (`caea152`).
- **LIDO-Profile für museum-digital und die DDB** (`1768725`); ein LIDO-Anbieter
  darf seine Klassifikationstypen selbst benennen (`fc23017`).
- **Konvertierung aus einer Profildatei konfigurierbar** (`b2c3bc1`).
- **Ernten über OAI-PMH und SRU** (`666f4bd`).
- **Vier Wege, auf denen eine Konvertierung falsche Daten erzeugen konnte, ohne
  es zu sagen** (`c299239`) — das ist der Commit, auf den die spätere Haltung
  zurückgeht, dass eine Beanstandung besser ist als eine stille Korrektur.
- Identifier, die das Einsetzen in eine URI überstehen und lesbar bleiben
  (`6087e49`).

**Zum Umfang:** Dieses Repository ist damit über den beauftragten LIDO-Importer
hinausgewachsen. Beauftragt war Paket A als `efi_conv.fmdu.lido`; entstanden
sind zusätzlich MARC21, das SLUB-Profil, museum-digital und die DDB. Welche
Teile in den geschuldeten Pull Request gehören, ist eine offene Abstimmung mit
Elias Oltmanns.

---

## 2025-03-06 — Dockerfile

Commit `065c7e0`, im Ursprungsrepository von Elias Oltmanns übernommen und dort
als Beitrag von Andreas Kasper vermerkt. Deutlich vor dem Werkvertrag.

---

## Offene Punkte

- **Der Pull Request auf `AV-EFI/efi-conv` fehlt.** Vertraglich geschuldet und
  unter den Liefergegenständen genannt. Die eigentliche Frage ist der Zuschnitt,
  siehe oben. In der Mail vom 01.09.2026 zur Abstimmung gestellt.
- **Uneindeutige Identifier auf Werksebene** im großen Testdatensatz. Kein
  Codeproblem; wird von Elias Oltmanns mit Düsseldorf geklärt. Die Konvertierung
  kann die Dubletten benennen, falls das hilft.
- **Fehlende Regieangaben** in den Düsseldorfer LIDO-Daten. Sie stehen schlicht
  nicht im XML, obwohl derselbe Weg für die DDB-Lieferung genutzt wird. Elias
  Oltmanns klärt das mit dem d:kult-Team. Die Grenze liegt hier bei den
  Ausgangsdaten, nicht beim Importer.

## Bekannte Einschränkungen und getroffene Annahmen

- **Ein unbekanntes Sprachlabel wird gemeldet, die Sprache nicht übernommen.**
  Lieber eine Meldung als eine falsche Tonspur. Bekannt sind „Dialogton",
  „Untertitel", „Zwischentitel" und „Nutzungsvermerk"; nach Auskunft von Elias
  Oltmanns kommt im Düsseldorfer Export nichts weiter vor.
- **Ein Exemplar trägt genau eine `is_item_of`-Beziehung.** Von Elias Oltmanns
  bestätigt.
- **Verweise zwischen Datensätzen einer Lieferung bleiben lokal**, auch wenn die
  Werk-PID bekannt ist — nicht alle Datensätze haben schon einen PID, und
  `efi-conv check` kann die Verweise so innerhalb der Lieferung auflösen.
- **Die Mapping-Tabelle `MAPPING.md` wird aus `MAPPING_RULES` im Code erzeugt.**
  Ein Test hält beide synchron; von Hand geändert gehört sie nicht.
- **Hausspezifisches steht im Profil, nicht im Code.** LIDO ist ein Standard,
  die Vokabulare darin sind es nicht. Die Traversierung ist generisch
  (`lido/mapping.py`), alles Hausspezifische steckt in einem `LidoProfile`.
