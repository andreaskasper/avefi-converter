# Import from Dublin Core (oai_dc)

This package maps unqualified Dublin Core records, as served by every
OAI-PMH endpoint under the `oai_dc` metadata prefix, to the AVefi
schema.

## Read this before using it

Dublin Core is the weakest of the inputs supported by `efi-conv`, and
this converter cannot make it stronger. Unqualified Dublin Core has
fifteen elements. All of them are flat, all of them are repeatable,
none of them is typed, and none of them says what it means:

- It cannot express the distinction between a work, a manifestation and
  a copy. The AVefi schema is built on that distinction, so the
  converter asserts one work, one manifestation and one item per
  record and reports, per record, that it has done so. If the export
  actually describes several prints of one film, the identifiers
  registered from it will describe prints rather than films — which is
  the opposite of what the AVefi project is for.
- It does not say who did what. `dc:creator` may be the director, the
  production company or the cataloguer; `dc:contributor` may be anyone
  at all. The converter therefore reads no role from Dublin Core
  unless the data provider has confirmed the convention in writing
  (see `creator_is_director` below).
- It does not say what a date is a date of. `dc:date` is read as the
  production date. That is a convention, not a reading of the data.
- It has no place for colour, sound, running time, access status,
  extent or preservation history.

This converter exists because `oai_dc` is the one metadata prefix an
OAI-PMH endpoint is required to offer, so it is often the only thing
available at the start of a conversation with a data provider. **A
provider who can export LIDO, EN 15907 or MARC should export that
instead.** The `efi_conv.lido` and `efi_conv.en15907` inputs carry the
levels, roles and carrier characteristics that Dublin Core throws
away.

## What is mapped

| Dublin Core | AVefi |
| --- | --- |
| `dc:identifier` | item identifiers and the source key, a URI preferred |
| `dc:title` | primary title, further titles as alternative titles |
| `dc:date` | production date |
| `dc:language` | `in_language`, with the usage set in the profile |
| `dc:subject` | `has_subject`, the topic of the resource |
| `dc:type` | `has_genre`, unless the term marked the record as film |
| `dc:format` | item format, through the profile vocabulary |
| `dc:publisher` | publication event with a `Publisher` activity |
| `dc:creator` | directing activity, only if the profile says so |
| `dc:relation`, `dc:source` | `has_webresource`, if they are http(s) URIs |
| `dc:contributor` | nothing; reported |
| `dc:description`, `dc:coverage`, `dc:rights` | nothing; reported |

Nothing is dropped in silence. Every element the converter cannot use
produces an entry in the conversion report, so run it with `--report`
and read the result:

```console
$ efi-conv from -f dc --profile provider.json --report report.json \
    -o records.json export.xml
```

The profile names the data provider. Without one the command refuses
to convert, the shipped issuer being a placeholder; pass
`--accept-placeholder-issuer` instead while trying a mapping out.

[`MAPPING.md`](MAPPING.md) is rendered from `MAPPING_RULES` in
`mapping.py`, and a test fails when the two drift apart. The
assumptions the mapping takes are listed at the end of it.

## The issuer is a placeholder

Dublin Core does not name the holding institution, and an ISIL must
not be guessed. The converter therefore ships

```python
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}
```

and reports once per input file that this has to be replaced with
the ISIL of the data provider before any identifier is registered.

## The profile

`DcProfile` carries the few things a provider can confirm about its own
export: the issuer information, the `dc:format` vocabulary, the
`dc:type` terms that mark a record as film, the language usage assumed
for `dc:language`, and `creator_is_director`. The last one is off by
default: creators are reported as unmapped until a provider states
that its `dc:creator` really does hold the director.

A provider builds its own module with its own profile, in the way
`efi_conv.fmdu.lido` does for LIDO, rather than editing the constants
in `mapping.py`.

## Reading the input

The records are read with `lxml` on top of
`efi_conv.core.xmlrecords.iter_record_elements`, which streams the
document and applies the same parser hardening as the other XML
converters: no DTD loading, no entity resolution, no network access.
`oai_dc` is small enough that generated bindings would cost more than
they save, so there is no `generated/` directory here.

Both shapes of input work: a document whose root element is a single
`oai_dc:dc`, and a document carrying many of them under a wrapper —
an OAI-PMH `ListRecords` response, for instance.
