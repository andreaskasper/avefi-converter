# 4 · Den Bericht lesen

```console
$ uv run efi-conv from -f fmdu.lido -o ergebnis.json --report bericht.json export.xml
```

Der Bericht ist die Antwort auf die Frage „Was ist aus meinen Daten
geworden?" Ohne ihn wissen Sie nur, dass eine Datei entstanden ist.

## Aufbau

```json
{
  "report_format_version": "1.0",
  "generated_at": "2026-08-11T13:54:08+00:00",
  "efi_conv_version": "0.1.0",
  "avefi_schema_version": "…",
  "summary": { "info": 10718, "warning": 395, "error": 0,
               "records_skipped": 0, "files_unrecognised": 0 },
  "entries": [ … ]
}
```

Jeder Eintrag nennt Schweregrad, Meldung, Datei, Datensatz-ID, Quellfeld,
Zielfeld und den Rohwert. Damit lässt sich jeder Eintrag im Ausgangssystem
wiederfinden.

## Die drei Schweregrade

**`info`** — etwas ist entschieden worden, und Sie sollen es wissen. Ein
Artikel wurde für die Sortierform nach hinten gestellt. Ein Exemplar brachte
seine PID mit. Eine Sprache ohne Verwendungsangabe wurde als gesprochene
Sprache gelesen. Nichts davon ist ein Problem, aber alles davon ist eine
Annahme, die Sie sehen sollen.

**`warning`** — ein Wert konnte nicht abgebildet werden und ist nicht in den
Daten gelandet. Der Datensatz steht trotzdem. **Das ist die Liste, die Sie
durchgehen sollten.** Meist steht dahinter eine Frage, die nur Ihr Haus
beantworten kann: Gibt es für „Festplatte" ein Format im Schema? Ist ein
„Negativ" das Bild- oder das Tonnegativ?

**`error`** — der Datensatz ist gescheitert. Ohne einen Titel gibt es nichts,
worüber der Datensatz handeln könnte.

## Die eine Warnung, die keine Frage ans Haus ist

> `The input states an AVefi identifier that no record of the output carries`

Alle anderen Warnungen sagen: „Ihr Haus hat einen Wert, für den das Schema
keinen Platz hat." Diese hier sagt: „Die Konvertierung hat etwas übersehen."
Die Eingabe nennt ein Handle, und kein einziger Datensatz der Ausgabe trägt
es — die nächste Lieferung würde also eine zweite Identität für etwas
anfordern, das längst eine hat, und ein Handle lässt sich nicht zurücknehmen.

Die Meldung nennt die Beziehung, unter der das Handle stand. Fast immer fehlt
der entsprechende Begriff im Profil (`related_work_rel_terms`,
`manifestation_rel_terms`). Diese Warnung gehört zu Andreas, nicht zu Ihnen.

Sie wird erst am **Ende** des Laufs gestellt, und das ist keine Kleinigkeit:
Kopien eines Films verweisen im Düsseldorfer Export aufeinander, ein Handle
also, das dieser Datensatz nicht trägt, trägt sehr oft der nächste. Beim
ersten Anlauf wurde die Frage pro Datensatz gestellt und meldete 172 Handles
als verloren, die alle vorhanden waren. Eine Prüfung, die grundlos anschlägt,
liest nach kurzer Zeit niemand mehr — und dann ist sie für den Fall, für den
sie gebaut wurde, auch nicht mehr da.

## Was ein guter Bericht aussieht

Viele `info`, überschaubar viele `warning`, keine `error`. Ein Bericht ohne
jede Meldung ist eher verdächtig als beruhigend — er hieße, dass die Quelle
in jedem Feld genau das enthält, was das Schema erwartet, und das kommt bei
gewachsenen Beständen nicht vor.

## Ein Beispiel aus der Praxis

Ein Export mit 5562 Datensätzen ergab:

| | |
| --- | --- |
| `info` | 10718 |
| `warning` | 395 |
| `error` | 0 |

Von den 395 Warnungen entfielen 112 auf „Behandelte Person" — eine Rolle, die
das Haus für den *Gegenstand* des Films vergibt und nicht für einen Mitwirkenden.
91 auf „Festplatte", für die es im Schema kein Format gibt. 57 auf „Negativ",
das Bild- oder Tonnegativ heißen kann. Drei Fragen also, nicht 395 Fehler.

## Auswerten

```console
$ python3 -c "
import json, collections
r = json.load(open('bericht.json'))
w = collections.Counter(e['raw_value'] for e in r['entries']
                        if e['severity'] == 'warning')
for wert, anzahl in w.most_common(20):
    print(f'{anzahl:5d}  {wert}')
"
```
