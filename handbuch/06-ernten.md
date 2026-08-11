# 6 · Daten ernten

Wenn Ihr System eine OAI-PMH- oder SRU-Schnittstelle hat, muss niemand
Dateien von Hand exportieren.

```console
$ uv run efi-conv harvest \
    --protocol oai-pmh \
    --endpoint https://beispiel.de/oai \
    --metadata-prefix oai_dc \
    -o ernte/
$ uv run efi-conv from -f dc --profile mein-archiv.toml -o ergebnis.json ernte/*.xml
```

Geerntet wird in ein Verzeichnis, konvertiert wird daraus. Zwei Schritte,
weil man den Rohbestand behalten will: Was einmal geholt wurde, lässt sich
erneut konvertieren, wenn das Mapping besser geworden ist, ohne die
Schnittstelle noch einmal zu belasten.

## Nur einen Ausschnitt

```console
$ uv run efi-conv harvest --protocol oai-pmh \
    --endpoint https://beispiel.de/oai \
    --metadata-prefix oai_dc \
    --set film \
    --from 2026-01-01 \
    -o ernte/
```

## Was Sie beachten sollten

Der Ernter hält sich an die Wiederaufnahme-Marken des Protokolls und macht
Pausen zwischen den Anfragen. Er ist absichtlich langsam — eine
OAI-Schnittstelle gehört meist zu einem Haus, das damit auch noch anderes zu
tun hat.

`oai_dc` ist der einzige Präfix, den jede OAI-Schnittstelle anbieten muss,
aber Dublin Core ist das schwächste der unterstützten Formate. Wenn Ihr
Endpunkt auch LIDO, EN 15907 oder MARC21 ausliefert, nehmen Sie das.
