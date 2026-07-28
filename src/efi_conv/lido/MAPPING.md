# LIDO to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.lido.mapping`;
do not edit by hand.

| Rule | Level | LIDO source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `film_filter` | Record | `lido:objectClassificationWrap/lido:objectWorkTypeWrap/lido:objectWorkType` | `—` | Profile vocabulary | Only holdings metadata about film is in scope. Records of another work type are skipped and reported; a record without a work type is skipped with a warning |
| `work_grouping` | Work | `primary title, director, production date` | `has_identifier (work)` | Profile work_key_fields | Several copies of one film share one WorkVariant, as in fmdu/csv.py; set work_key_fields to () for one work per record |
| `manifestation_grouping` | Manifestation | `work key plus colour type, format and languages of the copy` | `has_identifier (manifestation)` | — | Copies agreeing on the carrier characteristics share a manifestation |
| `record_id` | Item | `lido:lidoRecID, else lido:administrativeMetadata/lido:recordWrap/lido:recordID` | `has_identifier, described_by.has_source_key` | — | Local identifier; also used to derive the work and manifestation ids |
| `primary_title` | Work, Manifestation, Item | `lido:titleWrap/lido:titleSet[@lido:type='preferred']/lido:appellationValue` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | First title set is used when none is marked preferred; bracketed titles become SuppliedDevisedTitle |
| `alternative_title` | Work | `lido:titleWrap/lido:titleSet (remaining sets)` | `has_alternative_title` | Article handling in both directions | — |
| `genre` | Work | `lido:objectClassificationWrap/lido:classificationWrap/lido:classification` | `has_genre.has_name` | — | Classifications whose lido:type is named in the profile as carrying colour, format or access status are consumed by those rules instead |
| `production_date` | Work | `lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventDate` | `has_event.has_date` | ISODate; abbreviated intervals expanded | lido:earliestDate and lido:latestDate take precedence over lido:displayDate |
| `production_place` | Work | `lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventPlace` | `has_event.located_in.has_name` | — | — |
| `director` | Work | `lido:event[production]/lido:eventActor/lido:actorInRole[role in director terms]` | `has_event.has_activity (DirectingActivity)` | — | Placeholder names such as 'unbekannt' are skipped and reported |
| `other_agent` | Work | `lido:event[production]/lido:eventActor/lido:actorInRole (remaining roles)` | `—` | — | Reported as unmapped rather than dropped silently |
| `publication_date` | Manifestation | `lido:event[publication]/lido:eventDate and lido:eventPlace` | `has_event (PublicationEvent, ReleaseEvent)` | ISODate | — |
| `duration` | Item | `lido:objectMeasurementsWrap//lido:measurementsSet[running time]` | `has_duration.has_value` | ISODurationInHours | — |
| `colour_type` | Item | `lido:classification[@lido:type in profile classification_types['colour']]` | `has_colour_type` | Profile vocabulary | — |
| `format` | Item | `lido:classification[@lido:type in profile classification_types['format']]` | `has_format (Film)` | Profile vocabulary | — |
| `access_status` | Item | `lido:classification[@lido:type in profile classification_types['access']]` | `has_access_status` | Profile vocabulary | — |
| `webresource` | Item | `lido:administrativeMetadata/lido:resourceWrap//lido:linkResource` | `has_webresource` | — | — |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Taken from the profile, not from lido:recordSource, so that the issuer is unambiguous |

## Assumptions

Decisions the mapping takes that LIDO does not determine, and that need confirming against the reference data:

- A record without a recognised `lido:objectWorkType` is skipped rather than imported as a film.
- Every record yields one item. Works and manifestations are shared between records according to the profile key, so several copies of one film do not produce several works.
- `WorkVariant.type` is always `Monographic`; serial and analytic works are not derived from LIDO.
- Decade expressions such as `50er Jahre` are reported as unconvertible. Enabling `map_decades` maps them to a closed ten year interval and reads two digit decades as twentieth century.
- `ca.` and `um` become the ISODate approximation qualifier `~`, a trailing question mark becomes `?`.
- A running time given as a bare number without a unit is read as minutes.
- Clock notation with two components, such as `1:43`, is read as minutes and seconds, not as hours and minutes.
- A date such as `2003-04` is read as an ISO year and month. Note that `fmdu/csv.py` reads the same notation as the interval 2003 to 2004; the divergence is reported per occurrence.
- Only the first `lido:descriptiveMetadata` block of a record is mapped; further blocks are reported.
- The article lists are provisional and are to be confirmed against the reference data.
- LIDO does not prescribe the `lido:type` values marking a colour, format or access status classification. The profile names them, and a classification of any other type becomes a genre.
- A work key that would be no more than the title does not group: the record keeps a work of its own, and the decision is reported. Two undated films of the same name are two films, and one AVefi identifier registered for both cannot be corrected afterwards, whereas two works minted for one film can be merged.
- A running time that cannot be read leaves `has_duration` unset and is reported. Discarding the record over it would cost the work, every manifestation and every item derived from it.
