<div align="center">

<img src="https://gwdg.de/img/logos/avefi-logo.png" alt="AVefi" width="200">

# Handbuch

</div>

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

## Über das Projekt

AVefi — „Automatisiertes Verbundsystem für audiovisuelle Bestände über
einheitliche Film-Identifikatoren" — baut ein zentrales, PID-basiertes
Verbundsystem für audiovisuelle Bestände auf. Filmhaltende Häuser und
Infrastrukturanbieter arbeiten darin zusammen, damit ein Film über
Sammlungsgrenzen hinweg eindeutig benannt werden kann.

**Projektpartner**

- Leibniz-Informationszentrum Technik und Naturwissenschaften (TIB), Hannover
- Stiftung Deutsche Kinemathek — Museum für Film und Fernsehen (SDK), Berlin
- Gesellschaft für wissenschaftliche Datenverarbeitung mbH Göttingen (GWDG)
- Filmmuseum der Landeshauptstadt Düsseldorf (FMDU)

Die GWDG ist an allen Arbeitspaketen beteiligt und verantwortet Aufbau und
Betrieb der technischen Infrastruktur sowie die Middle-Layer-Software.

**Beauftragt war einer, geworden sind es mehr**

Beauftragt war ein Importer: LIDO für das Filmmuseum der Landeshauptstadt
Düsseldorf — das ist `efi_conv.lido` mit dem Profil `efi_conv.fmdu`.

Alles Weitere ist daraus entstanden und mit dabei. Die Abbildung musste
generisch geschrieben werden, um etwas zu taugen, und bedient damit auch
museum-digital und die Deutsche Digitale Bibliothek. Die Formatkonverter
für EN 15907, MARC21, PBCore, EBUCore und Dublin Core haben dieselbe
Form, und `slub.marc21` zeigt, wie das Profil einer Bibliothek darauf
aussieht. `harvest` holt die Daten, `check` und `diff` machen aus einer
Konvertierung etwas Nachprüfbares — ein Konverter taugt wenig, solange
niemand belegen kann, was er mit den Daten gemacht hat.

**Förderung**

Gefördert von der Deutschen Forschungsgemeinschaft (DFG),
Fördernummer **517778207**.

**Weiterführend**

- Projektseite der GWDG: <https://gwdg.de/projects/avefi/>
- Projektseite der TIB: <https://projects.tib.eu/av-efi/>
- Quellcode und Schema: <https://github.com/AV-EFI>
- Kontakt: <contact@av-efi.net>
