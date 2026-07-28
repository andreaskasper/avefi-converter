# Import from PBCore 2.1

This module converts [PBCore 2.1][pbcore] description documents into
the AVefi schema. PBCore is a format, not an institution, so this
converter is generic: it reads any well formed
`pbcoreDescriptionDocument`, whether it is the root of a file or one of
many inside a `pbcoreCollection`, and it takes everything institution
specific from a `PbcoreProfile`.

The mapping table and the assumptions behind it are in
[MAPPING.md](MAPPING.md), which is generated from `MAPPING_RULES` in
`mapping.py`. Do not edit it by hand.

## Usage

```console
$ efi-conv from -f pbcore --profile provider.json -o records.json export.xml
```

The profile names the holding institution; without one the command
refuses to convert, because the shipped issuer is a placeholder. Pass
`--accept-placeholder-issuer` instead while trying a mapping out, and
do not register identifiers for what that produces.

Or, while developing a mapping:

```console
$ python -m efi_conv.pbcore export.xml [records.json]
```

## The issuer has to be configured

The shipped profile carries a placeholder issuer:

```python
{
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}
```

PBCore names no data provider in a form that could be turned into an
ISIL. `pbcoreIdentifier/@source` and `instantiationLocation` name an
organisation in free text, and `pbcoreCollection/@collectionSource` is
optional and equally unconstrained. Deriving an ISIL from any of them
would attach a provenance to the records that the source data does not
support, so the converter does not try. It reports once per input
file that the placeholder is in use. Records carrying it must not have
identifiers registered for them; replace the issuer with the ISIL and
the name of the holding institution first, by constructing a
`PbcoreProfile` of your own.

## How well PBCore actually fits AVefi

Not particularly well, and the reason is structural rather than a
matter of missing vocabulary.

PBCore has two levels. The asset holds the intellectual content, and
every instantiation holds one concrete manifestation of it. AVefi has
three: a WorkVariant for the version of the film, a Manifestation for
the published or produced form of that version, and an Item for the
single copy an archive holds. PBCore's instantiation is both of the
latter two at once — the documentation calls it "any discreet and
tangible unit", which covers a preservation master, a distribution
format and a shelf copy without distinguishing them. There is no
element saying that two instantiations are copies of the same version,
and none saying that one is a copy of the other in any way AVefi could
use.

This converter therefore makes the asset the WorkVariant, makes every
instantiation an Item, and reconstructs the missing middle level by
grouping instantiations that agree on the characteristics AVefi puts at
the manifestation level: colour type, format and languages. That is a
guess made from the data rather than a statement in it. It gets the
common case right — a 35mm print and an MP4 access copy are two
manifestations, two prints of the same reduction are one — and it gets
harder cases wrong, for instance where one provider records the colour
of a print and another leaves it blank. Anyone comparing the output
against the source should expect the manifestation level to need
review; the work and item levels are sound.

A description document that names no instantiation states no holding
at all. Such a record — a series or a screening description, most
often — yields the WorkVariant and nothing else, because an AVefi Item
asserts that the institution holds a physical or digital copy, and
this one says that it does not. The record is reported at warning
level, and the work it produces is what a `pbcoreRelation` of another
record resolves to.

The second structural mismatch is smaller but sharper. AVefi names the
holding institution through `described_by`, one issuer per record.
PBCore names it inside the instantiation, in
`instantiationLocation`, and a single PBCore file can therefore mix
holdings of several institutions. The converter keeps the value as a
note on the item and reports it, but it cannot turn it into an issuer,
which is the other half of the reason the issuer has to come from the
profile.

Beyond that, the following has no AVefi equivalent at all and is
reported with its value rather than forced somewhere it does not
belong:

- `pbcoreDescription`, which is mandatory in PBCore and holds the
  synopsis. AVefi has no description field at any level.
- `pbcoreAudienceLevel` and `pbcoreAudienceRating`.
- The temporal half of `pbcoreCoverage`, which describes the period the
  content is set in rather than the production.
- Most of `instantiationEssenceTrack` and the technical instantiation
  elements — encoding, data rate, sampling rate, bit depth, frame size,
  aspect ratio, channel configuration. AVefi records what an archivist
  needs to identify a copy, not what a transcoder needs to read it.
- `pbcorePart`, which would need a nested record model.

Conversely, AVefi asks for things PBCore rarely carries. Roles are free
text in PBCore, so only the roles the profile recognises as directing
become an activity and the rest are reported; a PBCore file that credits
a cinematographer, an editor and a composer will lose all three unless
the profile is extended. There is no equivalent of AVefi's
`element_type` other than the loosely used `instantiationGenerations`,
and no reliable statement about sound: an audio essence track proves a
copy has sound, but its absence proves nothing, so `has_sound_type`
stays unset rather than claiming the film is silent.

## Generated parser

The input parser was generated from the [PBCore 2.1 schema][schema] by
the [xsData project][xsdata] and must not be edited:

```console
$ uv run xsdata generate --include-header --unnest-classes \
    --relative-imports --docstring-style NumPy \
    --package generated.pbcore_2_1 pbcore-2.1.xsd
```

[pbcore]: https://pbcore.org/
[schema]: https://raw.githubusercontent.com/WGBH-MLA/PBCore_2.1/master/pbcore-2.1.xsd
[xsdata]: https://xsdata.readthedocs.io/
