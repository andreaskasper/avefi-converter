# EBUCore to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.ebucore.mapping`;
do not edit by hand.

| Rule | Level | EBUCore source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | Taken from the profile, not from ebuCoreMain/metadataProvider. The shipped default is a placeholder and is reported once per run |
| `record_id` | Item | `ebucore:identifier[@typeLabel in profile terms]/dc:identifier, else the first identifier, else ebuCoreMain/@documentId` | `has_identifier, described_by.has_source_key` | Profile record_identifier_type_labels | Further identifiers are reported; AVefi has no slot for the house identifiers a broadcaster keeps alongside |
| `work_grouping` | Work | `primary title, director, production date` | `has_identifier (work)` | Profile work_key_fields | Several EBUCore records describing the same programme share one WorkVariant; set work_key_fields to () for one work per record |
| `manifestation_grouping` | Manifestation | `work key plus colour type, carrier format and languages` | `has_identifier (manifestation)` | — | Records agreeing on the carrier characteristics share a manifestation |
| `primary_title` | Work, Manifestation, Item | `ebucore:title[@typeLabel in profile terms]/dc:title` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | The first title is used when none carries a recognised typeLabel; bracketed titles become SuppliedDevisedTitle |
| `alternative_title` | Work | `ebucore:title (remaining), ebucore:alternativeTitle/dc:title` | `has_alternative_title` | Article handling in both directions | A typeLabel outside the profile vocabulary is reported and the title is still kept as an AVefi AlternativeTitle |
| `genre` | Work | `ebucore:type/ebucore:genre/@typeLabel, ebucore:type/ebucore:contentFormat/@typeLabel` | `has_form, has_genre.has_name` | Profile work_form_map | A term the profile knows as an AVefi work form becomes has_form, every other term a free text genre |
| `subject` | Work | `ebucore:subject/dc:subject` | `has_subject.has_name` | — | EBUCore subject is Dublin Core subject, so has_subject is the matching AVefi field rather than has_genre |
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
| `description` | Item | `ebucore:description/dc:description` | `has_note` | — | AVefi offers free text only below the work level, so a synopsis ends up on the item |
| `rights` | — | `ebucore:rights` | `—` | — | AVefi records no rights statement; reported in full |
| `part` | — | `ebucore:part` | `—` | — | AVefi has no record type for an editorial segment; reported with the number of parts |
| `technical_detail` | — | `ebucore:format (remaining), ebucore:videoFormat and ebucore:audioFormat (remaining)` | `—` | — | Codecs, bit rates, raster and sampling parameters have no AVefi equivalent; reported per record |
| `out_of_scope` | — | `ebucore:coreMetadata (remaining elements)` | `—` | — | Relations, versions, planning, ratings, artefacts, emotions and the other broadcast production elements are reported per record |

## Assumptions

Decisions the mapping takes that EBUCore does not determine, and that need confirming against the reference data:

- EBUCore describes one editorial object plus the formats it exists in. AVefi wants a work, a manifestation and an item. The bridge is: the editorial content of coreMetadata (titles, creators, subjects, genre, production date and place) becomes the WorkVariant, the publication history becomes the Manifestation, and the carrier described by ebucore:format becomes the Item. One EBUCore record therefore always yields exactly one item.
- Large parts of EBUCore are out of scope. Everything about transmission, essence technicalities, rights, planning, audience ratings, artefacts, animals, props, costumes, food, emotions, actions and text lines has no AVefi equivalent. Such elements are reported per record rather than mapped, and the conversion report is the honest account of what the AVefi records do not carry.
- The issuer is the holding institution and does not follow from the format. The shipped profile carries a documented placeholder, and the converter reports once per run that it has to be replaced with the ISIL of the institution before the records are used.
- Works and manifestations are shared between records according to the profile key, so several EBUCore records describing the same programme on different carriers do not produce several works.
- WorkVariant.type is always Monographic. EBUCore states series and episode membership through relation elements, which this mapping does not follow.
- EBUCore has no element for the colour or the sound system. Both are read from a technicalAttributeString whose typeLabel the profile names, which is where providers put them.
- A publication event without a recognised medium is typed as BroadcastEvent. EBUCore is a broadcast schema, so broadcast is the likelier reading than a theatrical release.
- ebucore:subject is mapped to has_subject rather than to has_genre. It is the Dublin Core subject element, and AVefi has a matching field for it.
- A timecode duration contributes hours, minutes and seconds. The frame count is reported, because ISODurationInHours cannot express it.
- Decade expressions are reported as unconvertible unless map_decades is enabled, as in the other converters.
- The vocabularies in the profile follow the EBU classification schemes plus the English and German spellings met in practice. They are provisional and are to be confirmed against the reference data of each provider.
