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

## Der Datensatz sagt selbst, was er ist

`lido:recordType` steht bei allen 5562 Datensätzen auf `Item` — das ist
das vereinbarte Kriterium für ein Exemplar, und das Profil nennt es in
`record_type_terms`.

Vorher wurde über `lido:objectWorkType` gefiltert. Das Feld ist im
Standard für die Werkart gedacht; dieses Haus trägt dort den Träger ein
(`Filmrolle`, `Festplatte`, `VHS`). Die allgemeine Voreinstellung kennt
Werkarten, beide Listen überschnitten sich in genau einem Wert, und aus
5562 Datensätzen wurden 67. Die Träger einzusammeln hat die Zahl
repariert, war aber weiterhin eine Schlussfolgerung auf eine Frage, die
der Datensatz direkt beantwortet — und sie verwarf sechs Exemplare, bei
denen in `objectWorkType` ein Titelbestandteil steht.

## Der Identifier ist das letzte Segment von `lidoRecID`

`DE-MUS-042628:DE-MUS-432511:1059195` — die ersten beiden Segmente
nennen Archiv und Museum. Der Identifier ist `1059195`, und genau das
steht im CSV-Export in der ersten Spalte. Nähme man die ganze
Zeichenkette, hätte dasselbe Exemplar je nach Importer zwei
verschiedene Schlüssel und nichts ließe sich zuordnen.

## Das Haus sagt, zu welchen Werken ein Exemplar gehört

Jeder Datensatz trägt `relatedWorkSet`-Einträge mit `relType` `Film`,
jeder mit einer eigenen Werk-ID und einem Werktitel. Das ergibt 3717
Werke — und es drückt einen Fall aus, den ein abgeleiteter Schlüssel
nicht ausdrücken kann: Sechs Exemplare enthalten mehr als einen Film,
und eine Rolle mit zwei Kurzfilmen ist **zwei Werke und eine
Manifestation**. Drei solche Fälle mussten im revidierten CSV-Ergebnis
von Hand aufgetrennt werden; alle drei kommen jetzt ohne Handarbeit so
aus der Konvertierung.

Enthält ein Exemplar mehrere Filme, werden Produktionsereignis, Genres
und Alternativtitel des Datensatzes **keinem** davon zugeordnet und das
wird gemeldet. Ein Datum, das auf einer Kompilationsrolle steht, ist
das Datum der Rolle.

## Die PID kommt zurück

Sind für den Bestand schon Handles vergeben worden, stehen sie im Export
wieder drin:

```xml
<lido:objectPublishedID lido:source="www.av-efi.net"
  >https://hdl.handle.net/21.11155/F68FEFE5-…</lido:objectPublishedID>
```

Im Referenzexport tragen 3712 von 5562 Datensätzen einen — genau die 3712
Exemplare der früheren CSV-Lieferung. Der Konverter übernimmt sie als
`avefi:AVefiResource` am **Exemplar**.

Werk und Manifestation tragen ihre PID ebenfalls, aber nicht hier: ein
LIDO-Datensatz beschreibt die Kopie, also ist `objectPublishedID` die PID
der Kopie. Werk und Manifestation stehen in den **Beziehungen** des
Datensatzes, und dort steht auch ihr Handle:

```xml
<lido:relatedWorkSet>
  <lido:relatedWork><lido:object>
    <lido:objectID lido:source="www.av-efi.net"
      >https://hdl.handle.net/21.11155/73F965CE-…</lido:objectID>
  </lido:object></lido:relatedWork>
  <lido:relatedWorkRelType>
    <lido:conceptID>https://www.av-efi.net/av-efi-schema/is_item_of</lido:conceptID>
    <lido:term xml:lang="en">is item of</lido:term>
  </lido:relatedWorkRelType>
</lido:relatedWorkSet>
```

`relType` `Film` liefert die Werk-PID, `is_item_of` die der Manifestation.
Beide werden **neben** den lokalen Identifier gestellt, nicht an seine
Stelle: `is_item_of` und `is_manifestation_of` verweisen über den lokalen
Identifier, und der bleibt deshalb der erste.

Warum das wichtig ist: Ohne diese Übernahme fordert jede Nachlieferung eine
zweite Identität für Werke, Fassungen und Kopien, die längst eine haben. Ein
Handle lässt sich nicht zurücknehmen.

## Der Filmportal-Eintrag steht beim Werk

Im selben `relatedWorkSet` steht neben der lokalen ID und dem Handle oft
noch der Filmportal-Identifier des Werks:

```xml
<lido:objectID lido:source="www.filmportal.de"
  >https://www.filmportal.de/film/4029730364e64a1a9bc0d3f5fd3534f4</lido:objectID>
```

Er wird zu `same_as` am Werk, als `avefi:FilmportalResource` mit der bloßen
ID — nicht mit der URL, in der sie geschrieben steht. Erkannt wird er an
der Form des Werts und nicht an `lido:source`: wie ein Haus die Normdatei
benennt, ist seine Sache, die URI der Normdatei ist es nicht.

## Die Objektseite ist eine Webressource

`objectPublishedID` enthält zweierlei: das AVefi-Handle und die Adresse der
Objektseite im hauseigenen System.

```xml
<lido:objectPublishedID lido:type="…/lido00100"
  >http://www.duesseldorf.de/dkult/DE-MUS-432511/994335</lido:objectPublishedID>
```

Der Wert entscheidet, welches von beidem vorliegt, nicht `lido:type` — das
Haus typisiert die Adresse als „Local identifier", eine URL ist sie
trotzdem. Was eine URL ist und kein Handle, wird zu `has_webresource` am
Exemplar.

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

## Form, Genre und Sachschlagwort

Der `classificationWrap` beantwortet zwei Fragen in einer Liste — was
für ein Ding der Film ist und wie er ist —, das Schema fragt sie
getrennt. Dokumentarfilm, Spielfilm, Amateurfilm, Kurzfilm, Werbefilm,
Lehrfilm und Wochenschau werden zu `has_form` und **nicht zusätzlich**
zum Genre.

Einen `subjectWrap` gibt es in diesem Export nicht. Wovon ein Film
handelt, steht als Person mit der Rolle „Behandelte Person" — also dort,
wo auch die Mitwirkenden stehen. Nur die Rolle unterscheidet die
beiden; ohne sie wurden 130 Sachschlagworte als nicht abbildbare
Mitwirkende gemeldet.

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

Drei Feinheiten:

- Trägt der Begriff ein `lido:label`, sagt das Label, **wofür** die Sprache
  da ist, und nur das Label sagt es: die Begriffe selbst heißen alle
  „Deutsch" oder „Englisch".

  ```xml
  <lido:term lido:label="Untertitel" lido:pref="alternate">Englisch</lido:term>
  ```

  wird zu `{"code": "eng", "usage": ["Subtitles"]}`. Bekannt sind
  „Dialogton" (`SpokenLanguage`), „Untertitel" (`Subtitles`) und
  „Zwischentitel" (`Intertitles`); weitere Label kommen ins Profil unter
  `language_usage_labels`. Ein unbekanntes Label wird gemeldet, statt die
  Sprache als gesprochene zu lesen — eine englische Untertitelspur ist
  keine englische Tonspur.

  „Ohne Sprache" unter „Dialogton" wird zu `{"usage": ["NoDialogue"]}`,
  ohne Sprachcode: Der Satz sagt etwas über die Kopie aus und nicht über
  eine Sprache, und `zxx` wäre die Antwort auf eine Frage, die niemand
  gestellt hat.
- Die Sprache **ohne Label** steht ohne Verwendungsangabe da. Sie wird als
  gesprochene Sprache gelesen — der Normalfall, und das, was der
  CSV-Importer desselben Hauses schreibt. Die Annahme steht im Bericht.
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

## Die Länge wird übernommen — und gegengerechnet

`measurementType = "Länge"` mit Einheit „m" ist **innerhalb derselben
Datei uneinheitlich**: Von 1947 vergleichbaren 35-mm-Datensätzen stehen
1334 in Zentimetern und 613 in Metern. Der Wert wird trotzdem
übernommen, so wie er dasteht — etwas wegzulassen, das das Haus erfasst
hat, hilft niemandem.

Neu ist, dass die Konvertierung merkt, wenn er nicht stimmen kann. Bei
bekanntem Format sagen Länge und Laufzeit einander voraus; wo beide um
mehr als eine Größenordnung auseinanderliegen, steht das im Bericht —
bei 2347 Datensätzen, durchweg mit dem Faktor 100. Korrigiert wird
nichts: Welcher der beiden Werte die falsche Einheit trägt, geht aus
dem Datensatz nicht hervor.

## Offene Fragen an das Haus

| Was | Wie oft |
| --- | --- |
| „Festplatte" hat kein Format im Schema | 91 |
| „Negativ" — Bild- oder Tonnegativ? | 57 |
| „Behandelte Person"/„Institution": Gegenstand des Films, nicht Mitwirkende | 130 |
| „Coloriert" hat kein Gegenstück in `ColourTypeEnum` | 2 |
| „Amateurfilm", „bewegtes Bild-Werk" unter einer ungültigen `conceptID` | 27 |
| Sechs Datensätze mit Titelbestandteilen in `objectWorkType` | 6 |
| Lokale ID des Werks lautet `<ID>_work`, nicht `<ID>` — so gewollt? | — |
| Uneindeutige Datumsangaben, überwiegend Jahrzehnte | 85 |
| Einheit der Längenangabe — Länge und Laufzeit widersprechen sich | 2347 |
