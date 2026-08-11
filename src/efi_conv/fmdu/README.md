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

### The record says what it is; the object does not

`lido:recordType` is `Item` on all 5562 records, which is the agreed
criterion for a copy, and `record_type_terms` in the profile names it.

The filter used to be on `lido:objectWorkType`, which is meant for the
type of work and holds the carrier here — `Filmrolle`, `Festplatte`,
`VHS`. The generic default lists work types, so the two vocabularies
met in exactly one value and an export of 5562 records converted to 67.
Collecting the carrier terms fixed the count, but it was still
inferring an answer the record gives outright, and it dropped six
copies whose `objectWorkType` holds a title fragment. The work type
filter is switched off for this provider rather than left at a default
that would never be reached.

### The identifier is the last segment of `lidoRecID`

`DE-MUS-042628:DE-MUS-432511:1059195` — the first two segments name the
archive and the museum. The identifier is `1059195`, which is what the
CSV export of the same holdings carries in its first column, so
`source_key_pattern` selects it. Taking the whole string gave one copy
two source keys depending on which importer ran, and nothing could be
matched between them.

### The provider states which films a copy is of

Every record carries `relatedWorkSet` entries with `relType` `Film`,
each with the work's own identifier and title. That identifies 3717
works, and it expresses the case a derived key cannot: six copies hold
more than one film, and a reel of two shorts is two works and one
manifestation. Three such copies had to be taken apart by hand in the
revised CSV output; all three now come out of the conversion the same
way with no manual step.

Where a copy names several films, the record's production event,
genres and alternative titles are not attributed to any of them. A date
read off a compilation reel is the date of the reel.

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

### Form, genre and subject

`classificationWrap` answers two questions in one list — what kind of
thing the film is and what it is like — and the schema asks them
separately. `work_form_map` names the terms that are forms;
Dokumentarfilm, Spielfilm, Amateurfilm, Kurzfilm, Werbefilm, Lehrfilm
and Wochenschau become `has_form` and not also a genre.

There is no `subjectWrap` in this export. The subject of a film is
recorded as an actor with a role of its own, `Behandelte Person`, in
the same element as the credits, so `subject_role_terms` is what tells
them apart. Without it, 130 subjects were reported as unmappable
credits.

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

### `Länge` is transferred, and checked against the running time

`measurementType = "Länge"` with unit `m` is inconsistent within one
file: of 1947 comparable 35 mm records, 1334 are in centimetres and 613
in metres. The value is transferred as stated all the same — omitting
what the provider recorded tells nobody anything.

What the conversion adds is the observation that it cannot be right.
With the format known, length and running time predict each other, and
where they disagree by more than an order of magnitude that is
reported: 2347 records of the export do, all by a clean factor of a
hundred. Neither value is corrected, because which of the two carries
the wrong unit is not decidable from the record.

## Open questions

| | count |
| --- | ---: |
| `Festplatte` has no format in the schema | 91 |
| `Negativ` — image or sound negative? | 57 |
| `Coloriert` has no counterpart in `ColourTypeEnum` | 2 |
| `Amateurfilm`, `bewegtes Bild-Werk` under an invalid `conceptID` | 27 |
| Title fragments in `objectWorkType` | 6 |
| Length and running time disagreeing by a factor of a hundred | 2347 |
| Decade expressions, pending an agreed representation | 85 |
| The unit of `Länge` | 1947 |
