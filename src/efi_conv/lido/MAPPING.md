# LIDO to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.lido.mapping`;
do not edit by hand.

| Rule | Level | LIDO source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `scope` | Record | `lido:administrativeMetadata/lido:recordWrap/lido:recordType, else lido:objectWorkType` | `—` | Profile record_type_terms, else film_work_type_terms | Where a provider states what a record describes, that decides and the work type is not consulted. Records out of scope are skipped and reported; a record stating neither is skipped with a warning |
| `work_grouping` | Work | `primary title, director, production date` | `has_identifier (work)` | Profile work_key_fields | Several copies of one film share one WorkVariant, as in fmdu/csv.py; set work_key_fields to () for one work per record |
| `manifestation_grouping` | Manifestation | `work key plus colour type, format and languages of the copy` | `has_identifier (manifestation)` | — | Copies agreeing on the carrier characteristics share a manifestation |
| `record_id` | Item | `lido:lidoRecID, else lido:administrativeMetadata/lido:recordWrap/lido:recordID` | `has_identifier, described_by.has_source_key` | Profile source_key_pattern | Local identifier; also used to derive the work and manifestation ids. The pattern selects the identifier out of the namespaces a provider prefixes it with, so that the key matches the one the rest of its data uses |
| `primary_title` | Work, Manifestation, Item | `lido:titleWrap/lido:titleSet[@lido:type='preferred']/lido:appellationValue` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | First title set is used when none is marked preferred; bracketed titles become SuppliedDevisedTitle |
| `alternative_title` | Work | `lido:titleWrap/lido:titleSet (remaining sets)` | `has_alternative_title` | Article handling in both directions | — |
| `genre` | Work | `lido:objectClassificationWrap/lido:classificationWrap/lido:classification` | `has_genre.has_name` | — | Classifications whose lido:type is named in the profile as carrying colour, format or access status are consumed by those rules instead |
| `production_date` | Work | `lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventDate` | `has_event.has_date` | ISODate; abbreviated intervals expanded | lido:earliestDate and lido:latestDate take precedence over lido:displayDate |
| `production_place` | Work | `lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventPlace` | `has_event.located_in.has_name, located_in.same_as` | — | Name as the source gives it, plus the authority identifier where the record carries one; a place stated twice is recorded once |
| `activity` | Work | `lido:event[production or creation]/lido:eventActor/lido:actorInRole` | `has_event.has_activity` | Profile role_activity_map and director_role_terms | The role decides the activity class, since no value is shared between the sixteen activity vocabularies. Agents of one role share one activity. Placeholder names such as 'unbekannt' are skipped and reported |
| `agent_type` | Work | `lido:actor/@lido:type` | `has_event.has_activity.has_agent.type` | — | Person or CorporateBody as the source states it; it is not derived from the name |
| `agent_authority` | Work | `lido:actor/lido:actorID[@lido:source in GND, VIAF, Wikidata]` | `has_event.has_activity.has_agent.same_as` | — | Transferred where the source carries it; nothing is looked up and nothing is added |
| `other_agent` | Work | `lido:eventActor/lido:actorInRole (roles with no activity)` | `—` | — | Reported as unmapped rather than dropped silently |
| `publication_date` | Manifestation | `lido:event[publication]/lido:eventDate and lido:eventPlace` | `has_event (PublicationEvent, ReleaseEvent)` | ISODate | — |
| `duration` | Item | `lido:objectMeasurementsWrap//lido:measurementsSet[running time]` | `has_duration.has_value` | ISODurationInHours | — |
| `colour_type` | Item | `lido:classification[@lido:type in profile classification_types['colour']]` | `has_colour_type` | Profile vocabulary | — |
| `format` | Item | `lido:classification[@lido:type in profile classification_types['format']]` | `has_format (Film)` | Profile vocabulary | — |
| `access_status` | Item | `lido:classification[@lido:type in profile classification_types['access']]` | `has_access_status` | Profile vocabulary | — |
| `avefi_identifier` | Item | `lido:objectPublishedID carrying the AVefi handle prefix` | `has_identifier (AVefiResource)` | Profile avefi_handle_prefix | A copy registered in AVefi carries its handle back into the provider's export; transferring it makes a re-import an update instead of a second identifier for one copy |
| `materials_tech` | Item | `lido:event/lido:eventMaterialsTech/lido:materialsTech/lido:termMaterialsTech` | `has_colour_type, has_format, element_type, has_sound_type` | Profile materials_tech_map, then the value itself | The colour, sound, element type and format vocabularies of the schema share no value, so the value determines the field. lido:conceptID is read as a cross check and a disagreement is reported; publication and preservation event types found here are recognised but not acted on |
| `keyword_classification` | Item | `lido:classification[@lido:type in profile keyword_classification_types]` | `in_language, has_access_status` | Profile language_name_map and access_status_map | Routed by the term rather than by the type, because a provider may file language, access status and working notes under one heading; a term matching neither is reported |
| `webresource` | Item | `lido:administrativeMetadata/lido:resourceWrap//lido:linkResource` | `has_webresource` | — | — |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Taken from the profile, not from lido:recordSource, so that the issuer is unambiguous |

## Assumptions

Decisions the mapping takes that LIDO does not determine, and that need confirming against the reference data:

- A record without a recognised `lido:objectWorkType` is skipped rather than imported as a film.
- Every record yields one item. Works and manifestations are shared between records according to the profile key, so several copies of one film do not produce several works.
- `WorkVariant.type` is always `Monographic`; serial and analytic works are not derived from LIDO.
- Actors are read from the production event and from an event of creation, because a provider may record the people separately from the making of the copy. The activities are production activities either way and are attached to the production event.
- Whether an agent is a `Person` or a `CorporateBody` is taken from `lido:type` and left unset where the source does not say. Deriving it from the name is out of scope, and the earlier default of `Person` for every director was that derivation in all but name.
- Decade expressions such as `50er Jahre` are reported as unconvertible. Enabling `map_decades` maps them to a closed ten year interval and reads two digit decades as twentieth century. EDTF conformance level 0, which is what ISODate allows, has no decade syntax, so the interval is the only available form.
- `ca.`, `c.`, `um` and the combined `ca./ c.` become the ISODate approximation qualifier `~`; a trailing question mark and one in brackets, `1960 (?)`, become the uncertainty qualifier `?`. On an interval the qualifier is written on both ends, because ISODate carries it per date rather than per interval.
- Square brackets around a date mark one the cataloguer supplied rather than read off the object. That states where the date came from, not how certain it is, so the brackets are dropped, the date is taken as given, and the fact is reported.
- Words joining an interval — `zwischen 1940 und 1945`, `1970 bis 1977` — are read as the interval they spell out. An open one, `nach 1989`, is reported instead: level 0 cannot express it, and reading it as 1989 would state a year the source refuses to give.
- Month names are read in German and English, full and abbreviated. `8/1988` is read as a month and year rather than an interval, because the left hand side cannot be a year.
- A running time given as a bare number without a unit is read as minutes, unless the profile states the unit of that measurement. A provider labelling a column once and filling it in another unit is a fact about that export, so it is corrected in its profile rather than guessed at in the mapping.
- A running time of zero is read as none given. Cataloguing systems write an empty measurement as a zero, and recording `PT00H00M00S` would state that the copy runs no length.
- Production places keep the name the source gives, including historical states such as `DDR` or `Deutsches Reich`. That is the country the film was made in at the time, which is the part worth having; where the record carries an authority identifier it is transferred, and that is what resolves the spelling.
- Clock notation with two components, such as `1:43`, is read as minutes and seconds, not as hours and minutes.
- A date such as `2003-04` is read as an ISO year and month. Note that `fmdu/csv.py` reads the same notation as the interval 2003 to 2004; the divergence is reported per occurrence.
- Only the first `lido:descriptiveMetadata` block of a record is mapped; further blocks are reported.
- The article lists are provisional and are to be confirmed against the reference data.
- A term of the technical description that is already an AVefi value is taken as it stands. The values are a closed set, so a term that is one of them means itself, and a provider adding a carrier does not need a change to the converter.
- Where `lido:conceptID` names a vocabulary the value does not belong to, the value decides and the disagreement is reported. The reference data files `DCP` under the digital file vocabulary although it is an element type, and a hard disk under the optical one.
- Publication and preservation event types occurring in the technical description are reported rather than turned into events. A note about the material of a copy does not state that the film was distributed or restored.
- A language recorded without a usage is read as the spoken language, which is the common case and what the CSV importer for the same institution records. The assumption is reported per occurrence rather than left implied.
- `Removed` is set only for a copy that carries an AVefi identifier. It states that something registered is gone, which says nothing about a copy that was never registered; such a record is kept without an access status and reported, because whether it belongs in a delivery is the provider's decision.
- LIDO does not prescribe the `lido:type` values marking a colour, format or access status classification. The profile names them, and a classification of any other type becomes a genre.
- A work key that would be no more than the title does not group: the record keeps a work of its own, and the decision is reported. Two undated films of the same name are two films, and one AVefi identifier registered for both cannot be corrected afterwards, whereas two works minted for one film can be merged.
- A running time that cannot be read leaves `has_duration` unset and is reported. Discarding the record over it would cost the work, every manifestation and every item derived from it.
