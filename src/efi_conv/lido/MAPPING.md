# LIDO to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.lido.mapping`;
do not edit by hand.

| Rule | Level | LIDO source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `record_id` | Item | `lido:lidoRecID, else lido:administrativeMetadata/lido:recordWrap/lido:recordID` | `has_identifier, described_by.has_source_key` | — | Local identifier; also used to derive the work and manifestation ids |
| `primary_title` | Work, Manifestation, Item | `lido:titleWrap/lido:titleSet[@lido:type='preferred']/lido:appellationValue` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | First title set is used when none is marked preferred; bracketed titles become SuppliedDevisedTitle |
| `alternative_title` | Work | `lido:titleWrap/lido:titleSet (remaining sets)` | `has_alternative_title` | Article handling in both directions | — |
| `genre` | Work | `lido:objectClassificationWrap/lido:classificationWrap/lido:classification` | `has_genre.has_name` | — | Classifications typed as colour, format or access status are consumed by those rules instead |
| `production_date` | Work | `lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventDate` | `has_event.has_date` | ISODate; abbreviated intervals expanded | lido:earliestDate and lido:latestDate take precedence over lido:displayDate |
| `production_place` | Work | `lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventPlace` | `has_event.located_in.has_name` | — | — |
| `director` | Work | `lido:event[production]/lido:eventActor/lido:actorInRole[role in director terms]` | `has_event.has_activity (DirectingActivity)` | — | Placeholder names such as 'unbekannt' are skipped and reported |
| `other_agent` | Work | `lido:event[production]/lido:eventActor/lido:actorInRole (remaining roles)` | `—` | — | Reported as unmapped rather than dropped silently |
| `duration` | Item | `lido:objectMeasurementsWrap//lido:measurementsSet[running time]` | `has_duration.has_value` | ISODurationInHours | — |
| `colour_type` | Item | `lido:classification[@lido:type='colour'], profile vocabulary` | `has_colour_type` | Profile vocabulary | — |
| `format` | Item | `lido:classification[@lido:type='format'], profile vocabulary` | `has_format (Film)` | Profile vocabulary | — |
| `access_status` | Item | `lido:classification[@lido:type='access'], profile vocabulary` | `has_access_status` | Profile vocabulary | — |
| `webresource` | Item | `lido:administrativeMetadata/lido:resourceWrap//lido:linkResource` | `has_webresource` | — | — |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Taken from the profile, not from lido:recordSource, so that the issuer is unambiguous |
