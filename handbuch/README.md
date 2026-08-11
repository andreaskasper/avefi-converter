# Handbuch

Anleitung für alle, die Bestandsdaten nach AVefi konvertieren — geschrieben
für die Menschen in den Archiven und Museen, nicht für Entwicklerinnen und
Entwickler. Die technische Referenz steht in der [README](../README.md) im
Wurzelverzeichnis, der Code und die Mapping-Tabellen sind auf Englisch.

| Kapitel | Worum es geht |
| --- | --- |
| [1 · Einstieg](01-einstieg.md) | Installation und die erste Konvertierung |
| [2 · Konvertieren](02-konvertieren.md) | Der Befehl `efi-conv from` im Alltag |
| [3 · Profile](03-profile.md) | Das eigene Haus-Vokabular in einer Datei |
| [4 · Den Bericht lesen](04-bericht-lesen.md) | Was `--report` sagt und was nicht |
| [5 · Prüfen und vergleichen](05-pruefen-und-vergleichen.md) | `check` und `diff` |
| [6 · Daten ernten](06-ernten.md) | OAI-PMH und SRU |
| [7 · Filmmuseum Düsseldorf](07-filmmuseum-duesseldorf.md) | Besonderheiten dieses Bestands |
| [8 · Wenn etwas schiefgeht](08-fehlerbehebung.md) | Häufige Meldungen und ihre Ursache |

## Die drei Sätze, die den Rest erklären

**Nichts verschwindet stillschweigend.** Was nicht abgebildet werden kann,
steht im Bericht. Das ist die wichtigste Zusage dieses Werkzeugs, und sie ist
der Grund, warum ein Lauf mit vielen Meldungen kein schlechter Lauf ist.

**Ein Wert entscheidet über ein Feld, nicht über einen Datensatz.** Ein
Datum, das niemand lesen kann, kostet das Datum. Titel, Träger und
Identifikator des Exemplars bleiben.

**Geraten wird nicht.** Wo die Quelle schweigt, bleibt das Feld leer. Ein
plausibler Wert, den niemand angegeben hat, ist im Verbund schlimmer als eine
Lücke, die man sieht.
