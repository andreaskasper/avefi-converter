# Filmmuseum der Landeshauptstadt Düsseldorf

Two converters for one collection: `fmdu` reads the CSV export, and
`fmdu.lido` the LIDO one. They describe the same holdings and are
deliberately kept in step, so that a comparison of their output says
something about the mapping rather than about the two exports.

- Issuer: `https://w3id.org/isil/DE-MUS-432511`
- Mapping table for the LIDO side: [`../lido/MAPPING.md`](../lido/MAPPING.md)
- German user guide: [`handbuch/07`](../../../handbuch/07-filmmuseum-duesseldorf.md)

```console
$ uv run efi-conv from -f fmdu.lido -o efi_records.json --report report.json export.xml
$ uv run efi-conv check efi_records.json
```

## What this export does differently

Everything below cost the conversion data at some point. It is written
down because the next provider with a system of this age will have
some of the same, and because a profile that omits any of it silently
produces less than it should.

### `objectWorkType` names the carrier, not the work type

LIDO intends the type of work there. This provider records what the
copy is wound on: `Filmrolle`, `Festplatte`, `VHS`, `Raid`, `Datei`.
The generic default holds work types, so the two vocabularies meet in
exactly one value, `Video`. An export of 5562 records converted to 67.

`FILM_WORK_TYPE_TERMS` in `lido.py` therefore lists the carriers, and
it is derived rather than invented: every value occurring in the
records of the agreed CSV export, which is what defines the holdings of
this institution. Digital carriers are in it because they are in that
export. Six records carry a title fragment instead of a carrier and are
left out, so that the data entry error stays visible.

**A profile written for this converter must repeat that list.** A
profile replaces the vocabularies rather than adding to them.

### The copies carry their AVefi identifiers back

`lido:objectPublishedID` with `lido:source="www.av-efi.net"` holds the
handle registered for the copy. 3712 of 5562 records have one, and that
set is exactly the 3712 copies of the earlier CSV delivery. They are
transferred, which is what makes a re-import an update rather than a
request for a second identity. Only the item ever carries one: a LIDO
record describes one object and the object is the copy.

### The credits sit in an event of their own

Director, composer and writer hang off an event of type `Geistige
Schöpfung`, not off the production event. 1228 records name a director
and none of them used to arrive. The actors are well described — GND
identifier, `lido:type`, preferred name — and all three are read.

### Colour, format, element type and sound share one field

`lido:termMaterialsTech`, not the typed classifications the mapping
looked in. What is written there is largely AVefi vocabulary already,
so only the house spellings are mapped: `Super8`, the decimal comma in
`17,5mmFilm`, `Colour, SW`.

`lido:conceptID` names the intended vocabulary but does not always get
it right — `DCP` is filed under the digital file formats although it is
an element type, a hard disk under the optical ones. The value decides
and the disagreement is reported.

### Language and access status are filed as keywords

One `Schlagwort` classification holds languages, access statuses and
working notes side by side. The type says nothing about the target, so
the term decides; before it did, `Deutsch` was arriving as a genre of
the film 1922 times.

`Deakzession` becomes `Removed`, but only for a copy that carries an
AVefi identifier: the status states that something registered is gone,
and `efi-conv check` refuses the combination otherwise.

### ⚠️ The running time is in hours, and the column says minutes

The one that does not announce itself.

```xml
<lido:measurementType>Zeit</lido:measurementType>
<lido:measurementUnit> Min</lido:measurementUnit>
<lido:measurementValue>1.5206666667</lido:measurementValue>
```

A 35 mm print of 2523 metres runs 92 minutes at 24 frames a second, and
its record says `1.5207`. Across the export:

| read as | median | upper quartile |
| --- | --- | --- |
| minutes | 14 seconds | 1.4 minutes |
| **hours** | **14.4 minutes** | **87 minutes** |

A collection of shorts and features looks like the second row. The
profile therefore states the unit:

```python
DURATION_UNITS = {"zeit": "h"}
```

It is a statement about this export rather than about LIDO, which is
why it lives in the profile: should it turn out to be wrong, it is one
line.

1084 records write the empty column as `0E-10`. A running time of zero
is read as none given.

### `Länge` is not usable

`measurementType = "Länge"` with unit `m` is inconsistent within one
file: of 1947 comparable 35 mm records, 1334 are in centimetres and 613
in metres. The field is not mapped until the provider has settled it.

## Open questions

| | count |
| --- | ---: |
| `Festplatte` has no format in the schema | 91 |
| `Negativ` — image or sound negative? | 57 |
| `Behandelte Person` / `Institution` — the subject of a film, recorded as a credit | 130 |
| `Coloriert` has no counterpart in `ColourTypeEnum` | 2 |
| `Amateurfilm`, `bewegtes Bild-Werk` under an invalid `conceptID` | 27 |
| Title fragments in `objectWorkType` | 6 |
| Decade expressions, pending an agreed representation | 85 |
| The unit of `Länge` | 1947 |
