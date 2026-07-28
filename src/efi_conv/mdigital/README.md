# Import from museum-digital

[museum-digital](https://www.museum-digital.de) publishes museum
objects on behalf of the museums that hold them. Every instance —
`nat`, `rlp`, `berlin`, `sachsen` and the rest — serves LIDO, through
its OAI-PMH endpoint and through the `lido` output of its object API.

This package is a `LidoProfile`, not a converter. The mapping lives in
[`efi_conv.lido`](../lido/README.md) and is not touched by adding a
provider here; `lido.py` contains the house vocabularies, and beyond
them only the reporting of the stand-in issuer, which produces no
AVefi value of any kind. That is the whole point of the module, and a
test asserts that the records it yields are exactly the records the
generic mapping yields from its profile.

## museum-digital is not the holding institution

The issuer shipped here is

```python
ISSUER_INFO = {
    "has_issuer_id": "https://www.museum-digital.de",
    "has_issuer_name": "museum-digital",
}
```

which is a stand-in and has to be replaced before anything is
registered. museum-digital is a publication platform: it presents the
holdings of a museum, it does not hold them. AVefi identifiers are
registered by and for the institution that holds the material, so a
real conversion replaces the issuer with the ISIL of that museum.

The converter says so: it reports once per input file, at warning
level, that the shipped issuer is a stand-in.

The export itself names the institution each record came from in
`lido:recordSource`, by name in `lido:legalBodyName` and, where the
instance records one, by identifier in `lido:legalBodyID`. The mapping
does not read those elements — the issuer comes from the profile, so
that one conversion has exactly one issuer, whatever the file happens
to mix. What the file says is reported instead, so that the run tells
you whose holdings you are looking at and which ISIL to configure:

```console
$ efi-conv from -f mdigital.lido --report report.json -o records.json \
    export.xml
```

An export pulled from an aggregating instance such as `nat` carries the
holdings of many museums at once. Such a file has to be split per
museum before conversion, and the reported `lido:recordSource` values
are what tells you that it needs splitting.

## The vocabularies are extrapolated

The terms in `lido.py` were compiled from the German terminology
museum-digital uses in its interface and from the LIDO structures its
export is built on. They could not be checked against a live export
while the module was written, so they are short by design and are to
be confirmed against real data. Nothing is guessed at conversion time:
a term the profile does not know is reported by the generic mapping,
not mapped to something plausible.

`ACCESS_STATUS_MAP` is empty on purpose. museum-digital records whether
an object is on display, not whether a film copy is an archive, viewing
or distribution print, and the AVefi access status must not be inferred
from the absence of a statement.

## Classification types

`efi_conv.lido.mapping` reads the colour type, the carrier format and
the access status from `lido:classification` elements, and LIDO does
not prescribe the `lido:type` value marking each of them. The profile
therefore names them, through `classification_types`, and the defaults
in `efi_conv.lido.profile` accept the English and the German labels.
A classification of any other type becomes a genre.

An instance labelling its classifications differently only needs its
own `classification_types` in the profile here. The sample under
`tests/mdigital/` uses the default values.
