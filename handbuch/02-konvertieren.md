# 2 · Konvertieren

```console
$ uv run efi-conv from -f FORMAT -o AUSGABE.json EINGABE [EINGABE …]
```

## Die Optionen, die im Alltag zählen

| Option | Wofür |
| --- | --- |
| `-f`, `--format` | Welcher Konverter. `--list-formats` zeigt alle |
| `-o`, `--output` | Zieldatei. Ohne die Option geht alles auf die Standardausgabe |
| `--report DATEI` | Schreibt das Protokoll als JSON |
| `--profile DATEI` | Bindet den Lauf an ein → [Profil](03-profile.md) |
| `--continue-on-error` | Macht mit der nächsten Datei weiter, wenn eine nicht lesbar ist |
| `-v` / `-q` | Mehr beziehungsweise nur Fehler auf dem Bildschirm |

> [!TIP]
> Setzen Sie `--report` bei **jedem** Lauf. Ohne den Bericht wissen Sie
> hinterher nur, dass eine Datei entstanden ist — nicht, was auf dem Weg
> dorthin nicht abgebildet werden konnte.

## Mehrere Dateien auf einmal

```console
$ uv run efi-conv from -f fmdu.lido -o alles.json lieferung/*.xml
```

Das ist nicht dasselbe wie mehrere einzelne Läufe: Kopien desselben Films aus
verschiedenen Dateien teilen sich dann ein Werk, statt zwei zu bekommen. Die
Dateien werden in fester Reihenfolge gelesen, damit dasselbe Ergebnis
herauskommt, egal wie die Shell die Sternchen aufgelöst hat.

## Was reproduzierbar ist

Derselbe Eingang mit demselben Profil ergibt dieselbe Ausgabe — Zeichen für
Zeichen. Darauf können Sie sich verlassen und es für einen Vergleich
zwischen zwei Lieferungen nutzen.

## Lokale Identifikatoren

Jeder Datensatz bekommt eine `avefi:LocalResource`-ID. Sie wird aus den Daten
abgeleitet — Titel, Regie, Jahr — und ist dafür da, innerhalb eines Laufes
zusammenzuhalten, was zusammengehört.

> [!IMPORTANT]
> Diese ID ändert sich, wenn sich die Daten ändern. Sie ist **keine**
> dauerhafte Kennung. Dauerhaft ist die AVefi-PID, und die kommt aus dem
> Handle-System, nicht von hier.

Trägt ein Exemplar in Ihrem Export bereits eine AVefi-PID, wird sie
übernommen (siehe [Kapitel 7](07-filmmuseum-duesseldorf.md#die-pid-kommt-zurück)).
Das ist der Unterschied zwischen einer Nachlieferung und einer zweiten
Registrierung derselben Kopie.

## Ein Lauf mit Meldungen ist kein misslungener Lauf

Ein Export von 5500 Datensätzen erzeugt schnell einige hundert Einträge im
Bericht. Das heißt nicht, dass etwas kaputt ist — es heißt, dass das Werkzeug
Ihnen sagt, worüber noch zu reden ist. → [Kapitel 4](04-bericht-lesen.md)

---

← [1 · Einstieg](01-einstieg.md) · [Übersicht](README.md) · [3 · Profile](03-profile.md) →
