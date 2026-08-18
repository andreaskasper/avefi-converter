# Import from the SLUB Dresden

MARC21-XML export of the Sächsische Landesbibliothek – Staats- und
Universitätsbibliothek Dresden. The mapping is the generic one in
[`efi_conv.marc21`](../marc21/README.md); this package is the profile.

```console
$ uv run efi-conv from -f slub.marc21 -o efi_records.json --report report.json export.xml
$ uv run efi-conv check efi_records.json
```

## What is house practice, and what is not

The profile carries what this library does differently: the issuer, the
relator codes it uses beyond the common ones, and the authorities its
headings cite.

Two other things about the export are **not** house practice, and are
therefore read by the generic MARC21 mapping for every provider:

**The records are catalogued to RDA.** They state the carrier in 338 —
`mr` for a film reel, `vd` for a videodisc, `cr` for an online edition —
and leave 007 and 008/33 empty. A converter reading only the fixed
fields skips the entire export; that is what happened before 338 was
read.

**One film is several records.** The reel, the disc and the online
edition are catalogued separately and linked through 776. They are one
work in three manifestations, and the library says so. Deriving the work
from title, director and year finds them again only when all the titles
agree, and they do not: the record for a digitised version carries that
in its title and the reel does not.

## Still open

The data provider documented a set of readings for its own conversion
that are plausible but not yet ratified, and said so itself. They are
**not** in this profile:

| MARC value | Proposed reading | Why it is held back |
| --- | --- | --- |
| Filmbericht | `Newsreel` + `Documentary` | two forms from one term |
| Fernsehmagazin | `Series` | a magazine is not obviously a series |
| Fernsehmitschnitt | `UneditedFootage` | no form in the schema fits |
| `ctb` | `ProducingActivity/Cooperation` | the generic contributor code says nothing about what was contributed |

`ctb` is the one exception and is included, because dropping the agent
says less than a broad activity does. It is the first entry to revisit.

Genre and form terms are otherwise carried as they stand. Mapping them
to `has_form` needs a vocabulary agreed with the provider, in the way
[`efi_conv.fmdu.lido`](../fmdu/README.md) does for its own house terms.

## Not yet verified against real data

The sample beside these tests is hand written in the shape of the
export, not taken from it. The profile has not been run against a full
delivery, so the vocabularies are to be confirmed rather than trusted.
An unknown term is reported by the generic mapping rather than guessed,
so an incomplete profile costs a report entry and not a wrong value.
