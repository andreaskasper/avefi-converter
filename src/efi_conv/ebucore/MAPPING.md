# EBUCore to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.ebucore.mapping`;
do not edit by hand.

| Rule | Level | EBUCore source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Taken from the profile, not from ebuCoreMain/metadataProvider. The shipped default is a placeholder and is reported once per input file |
| `record_id` | Item | `ebucore:identifier[@typeLabel in profile terms]/dc:identifier, else the first identifier, else ebuCoreMain/@documentId` | `has_identifier, described_by.has_source_key` | Profile record_identifier_type_labels | has_identifier is a list, so the further identifiers of the record are kept on the item as well; the scheme each of them belongs to is reported, AVefi having a resource class for only a few of them |
| `work_grouping` | Work | `primary title, director, production date` | `has_identifier (work)` | Profile work_key_fields | Several EBUCore records describing the same programme share one WorkVariant; set work_key_fields to () for one work per record |
| `manifestation_grouping` | Manifestation | `work key plus colour type, carrier format and languages` | `has_identifier (manifestation)` | — | Records agreeing on the carrier characteristics share a manifestation |
| `primary_title` | Work, Manifestation, Item | `ebucore:title[@typeLabel in profile terms]/dc:title` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | The first title is used when none carries a recognised typeLabel; bracketed titles become SuppliedDevisedTitle |
| `alternative_title` | Work | `ebucore:title (remaining), ebucore:alternativeTitle/dc:title` | `has_alternative_title` | Article handling in both directions | A typeLabel outside the profile vocabulary is reported and the title is still kept as an AVefi AlternativeTitle |
| `genre` | Work | `ebucore:type/ebucore:genre/@typeLabel, ebucore:type/ebucore:contentFormat/@typeLabel` | `has_form, has_genre.has_name` | Profile work_form_map | The term is kept verbatim as a genre, the element it comes from being the provider's genre statement; a term the profile knows additionally yields a WorkFormEnum value, as in the PBCore mapping |
| `subject` | Work | `ebucore:subject/dc:subject` | `has_subject.has_name` | — | EBUCore subject is Dublin Core subject, so has_subject is the matching AVefi field rather than has_genre |
| `part_of` | Work | `ebucore:isPartOf/dc:relation` | `is_part_of (LocalResource)` | — | Rewritten to the identifier of the work the related record yields, where the run converts that record; otherwise reported and not transferred, AVefi rejecting a local reference that resolves to no record of the same set |
| `production_date` | Work | `ebucore:date/ebucore:produced, ebucore:date/ebucore:created, ebucore:date[@typeLabel in profile terms]` | `has_event.has_date (ProductionEvent)` | ISODate; @startYear and @endYear become an interval | @date takes precedence over @year, which takes precedence over the dc:date text |
| `production_place` | Work | `ebucore:coverage/ebucore:spatial/ebucore:location/ebucore:name` | `has_event.located_in.has_name (ProductionEvent)` | — | ebucore:coverage/ebucore:temporal and a bare dc:coverage describe the subject of the content, not its production, and are reported instead |
| `director` | Work | `ebucore:creator, ebucore:contributor [ebucore:role/@typeLabel in profile terms]` | `has_event.has_activity (DirectingActivity)` | Profile director_role_labels | Placeholder names such as 'unknown' are skipped and reported |
| `other_agent` | Work | `ebucore:creator, ebucore:contributor (remaining roles)` | `—` | — | Reported as unmapped rather than dropped silently |
| `publication_event` | Manifestation | `ebucore:publicationHistory/ebucore:publicationEvent` | `has_event (PublicationEvent)` | ISODate; profile publication_medium_event_type_map | The default event type is BroadcastEvent, not ReleaseEvent, because EBUCore describes broadcast publication |
| `release_date` | Manifestation | `ebucore:date/ebucore:released, ebucore:date/ebucore:issued` | `has_event (PublicationEvent, ReleaseEvent)` | ISODate | — |
| `duration` | Item | `ebucore:format/ebucore:duration (normalPlayTime, timecode, editUnitNumber or duration)` | `has_duration.has_value` | ISODurationInHours | A timecode contributes hours, minutes and seconds; the frame count is reported because ISODurationInHours cannot hold it. An editUnitNumber without an editRate is unconvertible |
| `medium` | Item | `ebucore:format/ebucore:medium/@typeLabel` | `has_format (Film, Video, Optical, Audio)` | Profile medium_format_map | — |
| `container_format` | Item | `ebucore:format/ebucore:containerFormat (@containerFormatName or ebucore:containerEncoding/@typeLabel)` | `has_format (DigitalFile)` | Profile container_format_map | — |
| `colour_type` | Item | `ebucore:format//ebucore:technicalAttributeString[@typeLabel in profile terms]` | `has_colour_type` | Profile colour_type_map | EBUCore has no colour element; the technical attribute is the place providers use for it |
| `sound_type` | Item | `ebucore:format//ebucore:technicalAttributeString[@typeLabel in profile terms], else ebucore:audioFormat` | `has_sound_type` | Profile sound_type_map | The mere presence of an audioFormat yields Sound |
| `frame_rate` | Item | `ebucore:format/ebucore:videoFormat/ebucore:frameRate` | `has_frame_rate` | Profile frame_rate_map | — |
| `language` | Item | `ebucore:language/dc:language with @typeLabel` | `in_language.code, in_language.usage` | ISO 639-2/B; profile language_usage_map | A code the AVefi schema does not know is reported and the language is not transferred |
| `extent` | Item | `ebucore:format/ebucore:fileSize` | `has_extent.has_value, has_extent.has_unit` | Profile extent_unit_map | A size in bytes is scaled to the largest byte based unit AVefi knows that it fills, the schema having no unit for the byte itself |
| `description` | — | `ebucore:description/dc:description` | `—` | — | A synopsis describes the film, not the copy, and AVefi has no description field at any level; reported per value, as in the PBCore, Dublin Core and EN 15907 mappings |
| `rights` | — | `ebucore:rights` | `—` | — | AVefi records no rights statement; reported in full |
| `part` | — | `ebucore:part` | `—` | — | AVefi has no record type for an editorial segment; reported with the number of parts |
| `technical_detail` | — | `ebucore:format (remaining), ebucore:videoFormat and ebucore:audioFormat (remaining)` | `—` | — | Codecs, bit rates, raster and sampling parameters have no AVefi equivalent; reported per record |
| `out_of_scope` | — | `ebucore:coreMetadata (remaining elements)` | `—` | — | Relations, versions, planning, ratings, artefacts, emotions and the other broadcast production elements are reported per record |

## Assumptions

Decisions the mapping takes that EBUCore does not determine, and that need confirming against the reference data:

- EBUCore describes one editorial object plus the formats it exists in. AVefi wants a work, a manifestation and an item. The bridge is: the editorial content of coreMetadata (titles, creators, subjects, genre, production date and place) becomes the WorkVariant, the publication history becomes the Manifestation, and the carrier described by ebucore:format becomes the Item. One EBUCore record therefore always yields exactly one item.
- Large parts of EBUCore are out of scope. Everything about transmission, essence technicalities, rights, planning, audience ratings, artefacts, animals, props, costumes, food, emotions, actions and text lines has no AVefi equivalent. Such elements are reported per record rather than mapped, and the conversion report is the honest account of what the AVefi records do not carry.
- The issuer is the holding institution and does not follow from the format. The shipped profile carries a documented placeholder, and the converter reports once per input file that it has to be replaced with the ISIL of the institution before the records are used.
- Works and manifestations are shared between records according to the profile key, so several EBUCore records describing the same programme on different carriers do not produce several works.
- WorkVariant.type is always Monographic. EBUCore states series and episode membership through relation elements, and isPartOf becomes is_part_of, but neither says at which level the related record sits, so the type of the work is not derived from it.
- EBUCore has no element for the colour or the sound system. Both are read from a technicalAttributeString whose typeLabel the profile names, which is where providers put them.
- A publication event without a recognised medium is typed as BroadcastEvent. EBUCore is a broadcast schema, so broadcast is the likelier reading than a theatrical release.
- ebucore:subject is mapped to has_subject rather than to has_genre. It is the Dublin Core subject element, and AVefi has a matching field for it.
- A genre term is kept verbatim in has_genre, and additionally yields a has_form value where the profile knows it as an AVefi work form. The element states what the provider calls the genre of the film, and the mapping onto the AVefi work forms is a reading of that term rather than a replacement for it. The PBCore mapping answers the same question the same way.
- An ebucore:description is a synopsis of the content. AVefi has no description field at any level, and an item note describes the copy rather than the film, so the value is reported instead of being written to a note.
- A record commonly carries several identifiers, an ISAN or a house number beside the one it is known by. AVefi has a resource class for a few identifier schemes only, none of which EBUCore names, so the further identifiers are kept as local identifiers of the item and the scheme of each is reported.
- An ebucore:isPartOf identifier names a record in the source system. It becomes is_part_of where the run converts that record too, and is reported rather than transferred where it does not: AVefi rejects a local reference that resolves to no record of the same set, and a converter emitting one would have the whole work discarded by the checks.
- EBUCore states the size of a file, AVefi an extent with a unit from a fixed list that has no byte in it. A size in bytes is therefore scaled to the largest of KiloByte, MegaByte, GigaByte and TeraByte that it fills, using decimal factors.
- A timecode duration contributes hours, minutes and seconds. The frame count is reported, because ISODurationInHours cannot express it.
- Decade expressions are reported as unconvertible unless map_decades is enabled, as in the other converters.
- The vocabularies in the profile follow the EBU classification schemes plus the English and German spellings met in practice. They are provisional and are to be confirmed against the reference data of each provider.
- A work key that would be no more than the title does not group: the record keeps a work of its own, and the decision is reported. Two undated films of the same name are two films, and one AVefi identifier registered for both cannot be corrected afterwards, whereas two works minted for one film can be merged.
- A running time that cannot be read leaves `has_duration` unset and is reported. Discarding the record over it would cost the work, every manifestation and every item derived from it.
