# 3 · Profile

Ein Profil ist alles, was sich von Haus zu Haus unterscheidet: die
Einrichtung, die Hausbegriffe, die Bezeichnungen für Ereignisse und Rollen.
Es steht in einer JSON- oder TOML-Datei.

Zwei Gründe, warum es das gibt. Eine einmal abgestimmte Konvertierung soll
für jede spätere Lieferung unverändert wiederholbar sein, ohne dass jemand
etwas anklickt. Und die Format-Konverter — `en15907`, `marc21`, `pbcore`,
`ebucore`, `dc` — lesen einen Standard, nicht den Export eines bestimmten
Hauses; sie können nicht wissen, wessen Sammlung sie vor sich haben.

```console
$ uv run efi-conv from -f en15907 \
    --profile mein-archiv.toml \
    -o ergebnis.json export.xml
```

## Wie eine Profildatei aussieht

```toml
profile_format_version = "1.0"
format = "fmdu.lido"
description = "Filmarchiv Musterstadt, Lieferung 2026-07"

[issuer]
has_issuer_id = "https://w3id.org/isil/DE-MUS-000000"
has_issuer_name = "Filmarchiv Musterstadt"

[settings]
default_language = "ger"

[settings.colour_type_map]
"s/w" = "BlackAndWhite"
"farbe" = "Colour"
```

Beispiele für beide Formate liegen in
[`examples/profiles/`](../examples/profiles).

## Die eine Falle, die Sie kennen sollten

> **Ein Profil ersetzt die Vokabulare des Konverters, es ergänzt sie nicht.**

Wenn Sie ein Profil schreiben, um nur die Einrichtung zu ändern, und dabei
`film_work_type_terms` weglassen, dann gilt **nicht** die Liste des
Konverters, sondern die allgemeine Voreinstellung. Beim Filmmuseum Düsseldorf
heißt das: statt 5556 Exemplaren kommen 67 heraus, und der Lauf endet
trotzdem mit Erfolgsmeldung.

Nachsehen können Sie das immer:

```console
$ uv run efi-conv from --list-formats
```

Steht dort „Profile: optional, --profile replaces the vocabularies this
converter ships", dann ist genau das gemeint.

Faustregel: Wer ein Profil für einen Haus-Konverter schreibt, kopiert dessen
Vokabulare hinein und ändert dann. Wer nur den `issuer` austauschen will,
sollte prüfen, ob er das Profil überhaupt braucht.

## Was `settings` aufnimmt

Jeder Name unter `settings` ist ein Feld der Profilklasse des Konverters.
Ein Name, den es nicht gibt, ist ein **Fehler** und kein stiller Hinweis —
ein vertipptes Vokabular sähe sonst aus wie ein funktionierendes Profil und
würde jeden Wert verlieren, den es abbilden sollte. Dasselbe gilt für einen
Wert vom falschen Typ.

Die wichtigsten Felder für LIDO:

| Feld | Bedeutung |
| --- | --- |
| `film_work_type_terms` | Welche `objectWorkType`-Werte als Filmbestand gelten |
| `default_language` | Sprache für Titel ohne `xml:lang` |
| `map_decades` | Ob „50er Jahre" als Zeitraum abgebildet wird |
| `role_activity_map` | Hausrolle → AVefi-Tätigkeit, etwa `{"musik" = "Composer"}` |
| `creation_event_terms` | Ereignisse, deren Personen zur Produktion gehören |
| `materials_tech_map` | Hausschreibweise → AVefi-Wert für die technische Beschreibung |
| `keyword_classification_types` | Klassifikationen, die nach Begriff sortiert werden |
| `language_name_map` | Sprachname → ISO-639-2/B-Code |
| `language_usage_labels` | `lido:label` einer Sprache → wofür sie da ist, etwa `{"untertitel" = "Subtitles"}` |
| `agent_type_map` | `lido:type` am Akteur → `Person`, `CorporateBody`, `Family`, `PersonGroup` |
| `related_work_rel_terms` | Beziehungen, die das Werk benennen, zu dem ein Exemplar gehört |
| `manifestation_rel_terms` | Beziehungen, die die Fassung benennen — dort steht deren PID |
| `duration_units` | Einheit einer Messung, wenn die Angabe im Datensatz nicht stimmt |
| `avefi_sources` | `lido:source`-Werte, die AVefi als Aussteller eines Identifikators benennen |
| `related_authority_sources` | `lido:source` → Normdatei (`filmportal`, `gnd`, `viaf`, `wikidata`, `eidr`) |
| `avefi_handle_prefix` | Handle-Präfix — nur noch Rückfallebene für Identifikatoren ohne `lido:source` |

## Zwei Felder, die man leicht übersieht

`language_usage_labels` und `manifestation_rel_terms` haben eine
Voreinstellung, die für die bisher gesehenen Exporte passt. Sie zu ergänzen
kostet nichts, sie zu vergessen dagegen etwas:

- Ohne das passende Label wird jede Sprache als **gesprochene** gelesen. Aus
  einer englischen Untertitelspur wird dann eine englische Tonspur. Ein
  unbekanntes Label wird gemeldet und die Sprache nicht übernommen — die
  Meldung ist der Hinweis, dass hier ein Eintrag fehlt.
- Ohne `manifestation_rel_terms` kommt die PID der Fassung nicht an. Der Lauf
  meldet das inzwischen von selbst: „The input states an AVefi identifier
  that no record of the output carries", zusammen mit dem Namen der
  Beziehung, unter der sie stand. Diese Meldung heißt fast immer, dass ein Begriff im Profil
  fehlt.

## Rollen benennen, nicht Klassen

Bei `role_activity_map` geben Sie die **Rolle** an, nicht die Klasse:

```toml
[settings.role_activity_map]
"regie" = "Director"
"musik" = "Composer"
"drehbuch" = "Writer"
```

Die sechzehn Tätigkeitsvokabulare des Schemas teilen sich keinen einzigen
Wert, deshalb ist `Composer` eindeutig und die Klasse `MusicActivity` ergibt
sich von selbst. Eine Rolle, die Sie nicht eintragen, wird gemeldet und die
Person nicht übernommen — das ist Absicht und besser, als sie einer falschen
Tätigkeit zuzuschlagen.
