# 8 · Wenn etwas schiefgeht

## „Es kommen viel zu wenige Datensätze heraus"

Fast immer das Werkart-Vokabular. Sehen Sie im Bericht nach:

```console
$ python3 -c "
import json, collections
r = json.load(open('bericht.json'))
c = collections.Counter(str(e['raw_value']) for e in r['entries']
                        if 'not a film holding' in e['message'])
print(c.most_common(20))
"
```

Stehen dort die Träger Ihres Hauses, dann kennt `film_work_type_terms` sie
nicht. → [Kapitel 3](03-profile.md#die-eine-falle-die-sie-kennen-sollten)

Wenn Sie ein Profil benutzen: Das Profil **ersetzt** die Liste des
Konverters. Kopieren Sie sie hinein.

## „Der Lauf bricht mit NormalisationError ab"

Ein Datumsausdruck, der sich nicht abbilden lässt, kostet seit Version 0.1
nur noch das Feld. Bricht der Lauf trotzdem ab, liegt es an der Datei selbst:
kaputtes XML, falsches Schema, keine erkennbaren Datensätze.

`--continue-on-error` überspringt dann die betroffene Datei und macht mit der
nächsten weiter. Der Exit-Code bleibt von null verschieden, damit eine
Automatisierung nicht denkt, alles sei gut gegangen.

## „Jahreszahlen fehlen"

Wahrscheinlich Jahrzehnte. „50er Jahre" wird absichtlich nicht abgebildet,
bis die Darstellung mit dem Datengeber vereinbart ist:

```
Decade expression needs an agreed representation: '50er Jahre'.
Enable map_decades in the profile to read it as a closed interval
```

Mit `map_decades = true` wird daraus `1950/1959`, und mit „ca." davor
`1950~/1959~`. Das Schema erlaubt keine Jahrzehnt-Schreibweise: `195X` wäre
EDTF-Stufe 2, zulässig ist nur Stufe 0 mit den Kennzeichen `?` und `~`.

Nicht abbildbar bleiben offene Zeiträume wie „nach 1989". Sie als `1989`
zu lesen würde ein Jahr behaupten, das die Quelle ausdrücklich nicht nennt.

## „`check` beanstandet has_access_status=Removed"

`Removed` sagt, dass ein registriertes Exemplar nicht mehr da ist. Ohne PID
sagt es nichts. → [Kapitel 7](07-filmmuseum-duesseldorf.md#sprache-und-zugangsstatus-liegen-unter-schlagwort)

## „Die Identifikatoren sehen anders aus als beim letzten Mal"

Lokale Identifikatoren werden aus den Daten abgeleitet. Ändern sich Titel,
Regie oder Jahr, ändert sich die ID. Sie sind keine dauerhaften Kennungen —
das sind die AVefi-Handles.

Wenn Sie zwei Lieferungen inhaltlich vergleichen wollen:

```console
$ uv run efi-conv diff --ignore has_identifier alt.json neu.json
```

## „Personen fehlen"

Zwei mögliche Ursachen.

Die Rolle ist nicht abgebildet — dann steht sie als Warnung im Bericht und
gehört in `role_activity_map`.

Oder die Personen hängen an einem Ereignis, in dem nicht gesucht wird.
Ergänzen Sie `creation_event_terms` um die Bezeichnung, die Ihr Haus benutzt.

## „`efi-conv check` will ins Netz"

Das Schema wird von dort geholt. Der Bericht hält die benutzte Fassung fest.
Ohne Netz schlägt die Prüfung fehl; die Konvertierung selbst läuft
offline — externe Dienste werden dabei nicht angefragt, und das ist so
gewollt.

## Wenn nichts davon passt

Machen Sie einen kleinen Ausschnitt Ihres Exports, der das Problem zeigt,
und öffnen Sie ein Issue mit diesem Ausschnitt, dem Aufruf und dem Bericht.
Ohne die Daten ist ein Mapping-Problem selten zu finden.
