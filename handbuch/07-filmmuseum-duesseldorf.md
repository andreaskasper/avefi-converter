# 7 · Filmmuseum der Landeshauptstadt Düsseldorf

Dieses Kapitel beschreibt, was am LIDO-Export dieses Hauses anders ist als
das, was man bei LIDO erwarten würde. Es steht hier, weil jede dieser
Eigenheiten den Konverter einmal Daten gekostet hat und weil andere Häuser
mit ähnlich gewachsenen Systemen davon lernen können.

Konverter: `fmdu.lido` · Profil: `src/efi_conv/fmdu/lido.py`

```console
$ uv run efi-conv from -f fmdu.lido -o ergebnis.json --report bericht.json export.xml
$ uv run efi-conv check ergebnis.json
```

## `objectWorkType` nennt den Träger, nicht die Werkart

LIDO sieht in `objectWorkType` die Art des Werkes vor — „Film",
„Dokumentarfilm". Dieses Haus trägt dort ein, worauf die Kopie gewickelt ist:
**Filmrolle**, Festplatte, VHS, Raid, Datei.

Die allgemeine Voreinstellung des Konverters kennt Werkarten. Beide Listen
überschneiden sich in genau einem Wert, „Video". Ein Export mit 5562
Datensätzen ergab deshalb 67 Exemplare, und die anderen 5495 — darunter alle
5074 Filmrollen — wurden als Begleitmaterial übersprungen. Mit Erfolgsmeldung.

Die Liste im Profil ist deshalb aus dem abgestimmten CSV-Export abgeleitet:
Jede Objektbezeichnung, die dort vorkommt, gilt als Bestand. Digitale Träger
sind dabei, weil sie im CSV-Export dabei sind.

> **Wenn Sie ein eigenes Profil für diesen Konverter schreiben, übernehmen
> Sie `film_work_type_terms`.** Ein Profil ersetzt die Vokabulare, es ergänzt
> sie nicht. → [Kapitel 3](03-profile.md#die-eine-falle-die-sie-kennen-sollten)

Sechs Datensätze tragen dort einen Titelbestandteil statt eines Trägers
(„Teil 1", „Teil 2: Das Bündnis der Viererbande"). Sie werden nicht
übernommen und gemeldet — ein Erfassungsfehler, der sich beheben lässt.

## Die PID kommt zurück

Sind für den Bestand schon Handles vergeben worden, stehen sie im Export
wieder drin:

```xml
<lido:objectPublishedID lido:source="www.av-efi.net"
  >https://hdl.handle.net/21.11155/F68FEFE5-…</lido:objectPublishedID>
```

Im Referenzexport tragen 3712 von 5562 Datensätzen einen — genau die 3712
Exemplare der früheren CSV-Lieferung. Der Konverter übernimmt sie als
`avefi:AVefiResource` am **Exemplar**. Werk- und Fassungs-PIDs stehen nicht
im Export; ein LIDO-Datensatz beschreibt ein Objekt, und das Objekt ist die
Kopie.

Warum das wichtig ist: Ohne diese Übernahme fordert jede Nachlieferung eine
zweite Identität für Kopien, die längst eine haben. Ein Handle lässt sich
nicht zurücknehmen.

## Die Mitwirkenden stehen in einem eigenen Ereignis

Regie, Musik und Drehbuch hängen nicht am Produktionsereignis, sondern an
einem Ereignis vom Typ **„Geistige Schöpfung"**. Dort wurde nicht gesucht,
also kam niemand an: 1228 Datensätze nennen eine Regie, 337 eine Musik, 261
ein Drehbuch.

Die Personen sind gut erfasst — mit GND-Nummer, mit `lido:type="person"`, mit
Vorzugsnamen. Beides wird übernommen: die GND-Nummer als `same_as`, der Typ
als `Person` beziehungsweise `CorporateBody`. Der Typ wird **nicht** aus dem
Namen erraten; wo die Quelle schweigt, bleibt er leer.

„Absender*in" wird nicht abgebildet. Das ist ein Provenienzvermerk, keine
filmografische Rolle.

## Farbe, Format und Elementtyp stehen in `termMaterialsTech`

Nicht in typisierten Klassifikationen, wo der Konverter sie suchte. Deshalb
kam jede Kopie ohne Format, ohne Farbe und ohne Elementtyp an.

Erfreulich: Das Haus schreibt dort schon AVefi-Vokabular — `35mmFilm`,
`Colour`, `BlackAndWhite`, `Positive`, `ImageNegative`. Nur die
Hausschreibweisen brauchen eine Übersetzung, etwa `Super8` → `Super8mmFilm`
oder das Dezimalkomma in `17,5mmFilm`.

Die `conceptID` nennt das Zielvokabular — ist aber nicht immer richtig: `DCP`
steht dort unter den Dateiformaten, obwohl es ein Elementtyp ist, und eine
Festplatte unter den optischen Formaten. Der Konverter richtet sich deshalb
nach dem **Wert** und meldet die Abweichung.

Veröffentlichungs- und Erhaltungsereignisse tauchen im selben Feld auf
(`TheatricalDistributionEvent`, `DigitisationEvent`). Sie werden erkannt,
aber **nicht** in Ereignisse verwandelt: eine Notiz über das Material sagt
nicht, dass der Film verliehen oder restauriert wurde. Das ist mit dem Haus
zu klären.

## Sprache und Zugangsstatus liegen unter „Schlagwort"

In einer Klassifikation liegen nebeneinander: Sprachen („Deutsch",
„Englisch"), Zugangsstatus („Archivkopie", „Verleihkopie", „Master",
„Deakzession") und Arbeitsnotizen („angedacht", „bewilligt"). Weil die
Überschrift nichts über das Ziel sagt, landete alles davon in der
Genre-Liste — „Deutsch" 1922 Mal als Genre des Films.

Jetzt entscheidet der Begriff. Eine Sprache wird zur Sprache, ein
Zugangsstatus zum Zugangsstatus, alles andere wird gemeldet.

Zwei Feinheiten:

- Die Sprache steht **ohne Verwendungsangabe** da. Sie wird als gesprochene
  Sprache gelesen — der Normalfall, und das, was der CSV-Importer desselben
  Hauses schreibt. Die Annahme steht im Bericht.
- „Deakzession" wird zu `Removed`, **aber nur** bei einem Exemplar mit PID.
  Ohne PID sagt der Status nichts und `efi-conv check` weist ihn zurück. Der
  Datensatz bleibt dann ohne Status und wird gemeldet: ob eine
  deakzessionierte Kopie in eine Lieferung gehört, entscheidet das Haus.

## ⚠️ Die Laufzeit steht in Stunden, obwohl „Min" dransteht

Die wichtigste Eigenheit, weil sie sich nicht von selbst zeigt.

```xml
<lido:measurementType>Zeit</lido:measurementType>
<lido:measurementUnit> Min</lido:measurementUnit>
<lido:measurementValue>1.5206666667</lido:measurementValue>
```

Die Einheit sagt Minuten. Die Werte sind Stunden. Der Beleg: Eine
35-mm-Kopie von 2523 Metern läuft bei 24 Bildern je Sekunde 92 Minuten, und
ihr Datensatz sagt `1.5207` — als Stunden gelesen sind das 91,2 Minuten.

Über den ganzen Export:

| gelesen als | Median | oberes Quartil |
| --- | --- | --- |
| Minuten | 14 Sekunden | 1,4 Minuten |
| **Stunden** | **14,4 Minuten** | **87 Minuten** |

Eine Sammlung mit vielen Kurzfilmen und einigen Langfilmen sieht so aus wie
die zweite Zeile.

Das Profil stellt die Einheit deshalb um:

```python
DURATION_UNITS = {"zeit": "h"}
```

Sollte sich das als falsch erweisen, ist es eine Zeile. Wenn Ihr Haus
denselben Fall hat, setzen Sie `duration_units` in Ihrem Profil.

Ergänzend: 1084 Datensätze schreiben die leere Spalte als `0E-10`. Eine
Laufzeit von null ist keine Laufzeit, also bleibt das Feld leer.

## Die Länge ist nicht verwendbar

`measurementType = "Länge"` mit Einheit „m" ist **innerhalb derselben Datei
uneinheitlich**: Von 1947 vergleichbaren 35-mm-Datensätzen stehen 1334 in
Zentimetern und 613 in Metern. Das Feld wird deshalb nicht übernommen. Es
wäre wertvoll — aus Länge und Bildrate ließe sich die Laufzeit gegenrechnen —
aber erst, wenn die Einheit geklärt ist.

## Offene Fragen an das Haus

| Was | Wie oft |
| --- | --- |
| „Festplatte" hat kein Format im Schema | 91 |
| „Negativ" — Bild- oder Tonnegativ? | 57 |
| „Behandelte Person"/„Institution": Gegenstand des Films, nicht Mitwirkende | 130 |
| „Coloriert" hat kein Gegenstück in `ColourTypeEnum` | 2 |
| „Amateurfilm", „bewegtes Bild-Werk" unter einer ungültigen `conceptID` | 27 |
| Sechs Datensätze mit Titelbestandteilen in `objectWorkType` | 6 |
| Uneindeutige Datumsangaben, überwiegend Jahrzehnte | 85 |
| Einheit der Längenangabe | 1947 |
