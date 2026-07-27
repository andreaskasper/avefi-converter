# Import from the Deutsche Digitale Bibliothek

The [Deutsche Digitale
Bibliothek](https://www.deutsche-digitale-bibliothek.de) aggregates the
holdings of German libraries, archives, museums and media institutions.
Museum data reaches it as LIDO, ingested against the DDB LIDO profile,
and comes back out as LIDO through its interfaces.

This package is a `LidoProfile`, not a converter. The mapping lives in
[`efi_conv.lido`](../lido/README.md) and is not touched by adding a
provider here; `lido.py` contains the house vocabularies and nothing
else. That is the whole point of the module, and a test asserts it.

## The DDB is not the holding institution

The issuer shipped here is

```python
ISSUER_INFO = {
    "has_issuer_id": "https://www.deutsche-digitale-bibliothek.de",
    "has_issuer_name": "Deutsche Digitale Bibliothek",
}
```

which is a stand-in and has to be replaced before anything is
registered. The DDB holds nothing; it republishes what its partners
deliver. AVefi identifiers are registered by and for the institution
that holds the material, so a real conversion replaces the issuer with
the ISIL of that institution, which is in
`lido:recordSource/lido:legalBodyID` of each record.

This matters more here than for a single museum: a DDB export routinely
carries the holdings of many institutions in one file, and one AVefi
conversion has exactly one issuer. Split the export per contributing
institution before converting it.

## The vocabularies are extrapolated

The terms in `lido.py` were compiled from the German terminology the
DDB uses on its object pages and from the LIDO structures its ingest
profile is built on. They could not be checked against a live export
while the module was written, so they are short by design and are to
be confirmed against real data. Nothing is guessed at conversion time:
a term the profile does not know is reported by the generic mapping,
not mapped to something plausible.

`ACCESS_STATUS_MAP` is empty on purpose. The DDB records whether an
object is viewable online and under which licence, not whether a film
copy is an archive, viewing or distribution print, and the AVefi access
status must not be inferred from a rights statement.

Because the DDB normalises what it ingests only in part, the terms
actually found in an export vary by contributing institution. Expect to
extend the vocabularies per delivery rather than once and for all, and
read the conversion report after every run.

## Classification types

`efi_conv.lido.mapping` reads the colour type, the carrier format and
the access status from `lido:classification` elements, and LIDO does
not prescribe the `lido:type` value marking each of them. The profile
therefore names them, through `classification_types`, and the defaults
in `efi_conv.lido.profile` accept the English and the German labels.
A classification of any other type becomes a genre.

An instance labelling its classifications differently only needs its
own `classification_types` in the profile here. The sample under
`tests/ddb/` uses the default values.
