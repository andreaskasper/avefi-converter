# 5 · Prüfen und vergleichen

## `efi-conv check`

```console
$ uv run efi-conv check ergebnis.json
```

Prüft gegen das AVefi-Schema und gegen ein paar Regeln, die über die Form
hinausgehen. Ein Beispiel, das man sonst erst spät bemerkt:

```
ERROR  Do not expect has_access_status=Removed for an item without a PID
```

`Removed` sagt, dass ein **registriertes** Exemplar nicht mehr da ist. Über
ein Exemplar ohne PID sagt es nichts. Solche Regeln kennt `check` und Sie
sollten es deshalb nach jedem Lauf ausführen, nicht nur einmal am Ende.

> [!CAUTION]
> `--remove-invalid` schreibt die Datei ohne die beanstandeten Datensätze
> neu. Erst verstehen, warum sie beanstandet werden — sonst verschwindet
> genau die Frage aus der Lieferung, die zu klären gewesen wäre.

Der Aufruf holt das Schema aus dem Netz. Der Bericht hält fest, welche
Fassung benutzt wurde.

## `efi-conv diff`

```console
$ uv run efi-conv diff referenz.json neu.json
```

Vergleicht zwei Ergebnisdateien und schreibt die Abweichungen als Markdown
oder JSON. Die Reihenfolge der Dateien spielt keine Rolle. Der Befehl endet
mit einem Fehlercode, wenn etwas aus der Referenz im Kandidaten fehlt.

**Wie zugeordnet wird:** zuerst über eine gemeinsame registrierte PID, dann
über einen gemeinsamen lokalen Identifikator. Diese Reihenfolge ist der
Grund, warum sich zwei Exportwege überhaupt vergleichen lassen — lokale
Identifikatoren werden aus den Daten abgeleitet, fallen also je Quellformat
anders aus. Bei einem Museumsbestand stimmte auf Werksebene **kein einziger**
lokaler Identifikator überein und 2217 von 2218 PIDs. Über die lokale ID
zugeordnet galt jeder Datensatz gleichzeitig als fehlend und als zusätzlich.

Wofür das gut ist:

**Zwei Wege auf dieselben Ursprungsdaten.** Wenn Ihr Haus denselben Bestand
als CSV und als LIDO exportiert, zeigt der Vergleich, welcher Weg welche
Felder mitbringt. Das ist der belastbarste Qualitätsnachweis für ein Mapping,
den man ohne Zusatzaufwand bekommen kann.

**Zwei Lieferungen desselben Bestands.** Was ist seit dem letzten Mal
dazugekommen, was hat sich geändert?

**Vor und nach einer Änderung am Mapping.** Hat die Verbesserung an einer
Stelle woanders etwas kaputtgemacht?

```console
$ uv run efi-conv diff --ignore has_identifier alt.json neu.json
```

`--ignore` blendet ein Feld der obersten Ebene aus. Nützlich, wenn sich die
lokalen Identifikatoren geändert haben und Sie den Inhalt vergleichen wollen.

---

← [4 · Den Bericht lesen](04-bericht-lesen.md) · [Übersicht](README.md) · [6 · Daten ernten](06-ernten.md) →
