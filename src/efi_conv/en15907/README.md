# Import from EN 15907 metadata in the EFG schema

EN 15907 is the European standard for film identification, which
models a film as a Work with one or more Variants, each realised by
Manifestations, each held as Items. The
[European Film Gateway](https://www.europeanfilmgateway.eu/) publishes
an XML schema implementing that model, and film archives across Europe
deliver their holdings metadata in it. Because those levels are close
to the ones the AVefi schema uses, the mapping is markedly more direct
than one from a schema without them: an `avcreation` becomes a
WorkVariant, an `avManifestation` a Manifestation, an `item` an Item.

This module is a format converter, not an institution converter. The
mapping in `mapping.py` applies to every EFG export, and everything a
data provider decides for itself — the issuer and the vocabularies
used inside the elements the schema declares as plain strings — is
carried by an `EfgProfile` in `profile.py`. The rules the mapping
follows are declared once in `MAPPING_RULES` and rendered into
[MAPPING.md](MAPPING.md); the table is generated, so it is not to be
edited by hand.

## Issuer

An EFG document does not name its data provider in a form AVefi can
use: `item/provider` gives a name in free text, not an ISIL. The
profile shipped here therefore carries a documented placeholder,

    https://w3id.org/avefi/issuer/unspecified

and the converter reports its use once per input file. A real
conversion supplies a profile with the ISIL of the data provider,
which is also the place to put the house vocabularies of that
provider:

```python
from efi_conv.en15907 import EfgProfile
from efi_conv.en15907.mapping import efi_import

PROFILE = EfgProfile(
    issuer_info={
        "has_issuer_id": "https://w3id.org/isil/XX-EXAMPLE",
        "has_issuer_name": "Example Film Archive",
    },
    default_language="ger",
)
records = efi_import("export.xml", PROFILE)
```

## Usage

```console
$ efi-conv from -f en15907 -o records.json export.xml
```

or, which is convenient while developing a mapping,

```console
$ python -m efi_conv.en15907 export.xml [records.json]
```

## Input parser

The parser has been generated from the EFG schema version 3.2.07,
downloaded from
<https://www.efgproject.eu/downloads/efg_3.2.07_fixed.xsd>, courtesy
of the [xsData project][xsdata] by running the following command in
this directory:

```console
$ uv run xsdata generate --include-header --unnest-classes \
    --relative-imports --docstring-style NumPy \
    --package generated.efg_3_2 efg_3.2.07.xsd
```

Nothing under `generated/` is edited by hand. A document may carry a
single `efgEntity` as its root or many of them under a wrapper element
of the data provider's choosing, for instance an OAI-PMH envelope;
`core.xmlrecords.parse_records` handles both and streams the file.

## What this converter deliberately does not do

* It does not invent an issuer. See above.
* It does not convert entities other than `avcreation`. A `person`,
  `corporate`, `group`, `collection`, `award`, `decisionEvent`,
  `iprEvent` or `nonavcreation` entity is reported and skipped: AVefi
  describes moving image holdings, and an agent or an accompanying
  object is not one. `productionEvent` and `publicationEvent` entities
  are read, but only where a creation or manifestation refers to them.
* It does not guess vocabularies. A carrier, colour, sound, role,
  title relation, language usage or event type outside the profile is
  reported rather than passed through as free text, so that an
  unreviewed term cannot enter the data.
* It does not derive the level of a work. `WorkVariant.type` is always
  `Monographic`, because EFG states nothing about it.
* It does not resolve references across documents. An event referred
  to by a manifestation has to be part of the same document.
* It does not attach work level free text to a manifestation unless
  the profile asks for it. The AVefi work record has no field for a
  description, and moving one to the manifestation level changes
  what it is a statement about.

[xsdata]: https://xsdata.readthedocs.io/
