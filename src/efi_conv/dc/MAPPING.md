# Dublin Core (oai_dc) to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.dc.mapping`;
do not edit by hand.

| Rule | Level | Dublin Core source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `film_filter` | Record | `dc:type` | `—` | Profile film_type_terms | Only holdings metadata about film is in scope. Records of another type are skipped and reported; a record without a dc:type is skipped with a warning |
| `record_id` | Item | `dc:identifier` | `has_identifier, described_by.has_source_key` | A URI is preferred over a bare local number | Further dc:identifier values become additional LocalResource identifiers of the item |
| `levels` | Work, Manifestation, Item | `—` | `WorkVariant, Manifestation, Item` | One of each per record | Dublin Core cannot express the distinction, so the three levels are asserted; reported per record at warning |
| `primary_title` | Work, Manifestation, Item | `dc:title (first)` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | The order of the elements in the record is the only clue available for picking the primary title |
| `alternative_title` | Work | `dc:title (remaining)` | `has_alternative_title` | Article handling in both directions | — |
| `genre` | Work | `dc:subject, dc:type` | `has_genre.has_name` | — | dc:type terms that identified the record as film are consumed by the film filter instead |
| `production_date` | Work | `dc:date (first)` | `has_event.has_date (ProductionEvent)` | ISODate; abbreviated intervals expanded | Dublin Core does not say what happened on the date; it is read as the production date. Further dc:date values are reported |
| `director` | Work | `dc:creator` | `has_event.has_activity (DirectingActivity)` | Profile creator_is_director | Only when the provider has confirmed that dc:creator holds the director; otherwise creators are reported as unmapped |
| `contributor` | Work | `dc:contributor` | `—` | — | Dublin Core does not say in what capacity a contributor contributed, so no activity can be derived |
| `publisher` | Manifestation | `dc:publisher` | `has_event.has_activity (ManifestationActivity, Publisher)` | — | PublicationEvent type is UnknownEvent, because Dublin Core does not say what kind of publication it was |
| `language` | Item | `dc:language` | `in_language.code, in_language.usage` | ISO 639-2/B; profile language_usage | Dublin Core does not say whether the language is spoken, written as an intertitle or used for subtitles |
| `format` | Item | `dc:format` | `has_format (Film)` | Profile format_map | dc:format is also used for MIME types and file sizes, which are reported rather than mapped |
| `webresource` | Item | `dc:relation, dc:source` | `has_webresource` | Only values that are http(s) URIs | Non-URI relations are reported; Dublin Core does not say what the relation is |
| `dropped` | — | `dc:description, dc:coverage, dc:rights` | `—` | — | No AVefi target; reported per value so that the loss is visible in the conversion report |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Dublin Core does not name the holding institution. The shipped value is a placeholder and is reported once per run |

## Assumptions

Decisions the mapping takes that Dublin Core does not determine, and that need confirming with the data provider:

- Unqualified Dublin Core cannot express the distinction between a work, a manifestation and a copy. The converter asserts one of each per record and reports that it has done so. If an export actually describes several copies of one film, this converter will register identifiers for copies rather than for films.
- `dc:date` is read as the production date. Dublin Core does not say what happened on the date, so this is a convention, not a reading of the data.
- The first `dc:title` is the primary title. Element order is the only clue an oai_dc record offers.
- `dc:creator` is not read as the director unless the provider has confirmed that convention through `creator_is_director`. `dc:contributor` is never read as a role, because Dublin Core does not record one.
- `dc:language` is recorded with the usage configured in the profile, `SpokenLanguage` by default. Dublin Core does not say whether a language is spoken, written as an intertitle or used for subtitles.
- A `dc:publisher` becomes a PublicationEvent of type `UnknownEvent`, because Dublin Core does not say what kind of publication took place.
- `WorkVariant.type` is always `Monographic`; serial and analytic works are not derivable from Dublin Core.
- A record without a recognised `dc:type` is skipped rather than imported as a film, as in the LIDO converter.
- The shipped issuer is the documented placeholder `https://w3id.org/avefi/issuer/unspecified`. It has to be replaced with the ISIL of the data provider before identifiers are registered; the converter reports this once per run.
- Decade expressions such as `50er Jahre` are reported as unconvertible unless `map_decades` is enabled, as in the LIDO converter.
- `dc:description`, `dc:coverage` and `dc:rights` have no AVefi target and are reported per value.
