# EN 15907 (EFG) to AVefi mapping

Generated from `MAPPING_RULES` in `efi_conv.en15907.mapping`;
do not edit by hand.

| Rule | Level | EFG source | AVefi target | Normalisation | Notes |
| --- | --- | --- | --- | --- | --- |
| `entity_scope` | Record | `efgEntity/avcreation` | `—` | — | Only entities carrying an avcreation become moving image records. productionEvent and publicationEvent entities are kept as referenced events, all other entity types are reported and skipped |
| `work_grouping` | Work | `avcreation/identifier, else title and productionYear` | `has_identifier (work)` | Profile work_key_fields | Several efgEntity elements describing one film share one WorkVariant, which providers splitting a work over several entities depend on |
| `manifestation_grouping` | Manifestation | `avManifestation/identifier, else entity key and position` | `has_identifier (manifestation)` | — | Manifestations agreeing on their EFG identifier are shared between entities in the same way as works |
| `work_identifier` | Work | `avcreation/identifier` | `described_by.has_source_key` | Profile preferred_identifier_schemes | Also used to derive the local work identifier |
| `work_title` | Work | `avcreation/title[relation in preferred relations]/text` | `has_primary_title.has_name, has_primary_title.has_ordering_name` | Article handling in both directions | A title without a relation counts as preferred; the first title is used when no relation marks one; a title in square brackets becomes SuppliedDevisedTitle |
| `work_alternative_title` | Work | `avcreation/title (remaining)` | `has_alternative_title` | Profile title_relation_map | An unknown relation is reported and the title kept as AlternativeTitle |
| `title_detail` | Work, Manifestation | `title/partDesignation, title/temporalScope, title/geographicScope` | `—` | — | Reported as unmapped rather than dropped silently |
| `genre` | Work | `avcreation/keywords[type in genre types]/term` | `has_genre.has_name` | Profile genre_keyword_types | — |
| `subject` | Work | `avcreation/keywords[type in subject types]/term` | `has_subject.has_name` | Profile subject_keyword_types | — |
| `production_year` | Work | `avcreation/productionYear` | `has_event.has_date (ProductionEvent)` | ISODate | Further production years are reported; AVefi holds one date per event |
| `country_of_reference` | Work | `avcreation/countryOfReference` | `has_event.located_in.has_name (ProductionEvent)` | — | The reference attribute names the code list the value comes from and is reported |
| `director` | Work | `avcreation/relPerson, avcreation/relCorporate [type in directing roles]` | `has_event.has_activity (DirectingActivity)` | Profile directing_role_map | relPerson becomes an agent of type Person, relCorporate one of type CorporateBody; placeholder names are skipped and reported |
| `other_agent` | Work | `avcreation/relPerson, avcreation/relCorporate (remaining roles)` | `—` | — | Reported as unmapped rather than dropped silently |
| `related_production_event` | Work | `avcreation/relProductionEvent → efgEntity/productionEvent` | `has_event (ProductionEvent)` | Profile production_event_type_map | Resolved against the productionEvent entities of the same document; an unresolvable reference is reported |
| `work_language` | Work | `avcreation/language` | `—` | — | AVefi carries language on the item, so the value is reported unless the manifestation repeats it |
| `work_description` | Work | `avcreation/description, avcreation/note` | `has_note (Manifestation) or —` | Profile work_description_target | The AVefi work record has no field for free text, so the default is to report the value |
| `work_type` | Work | `—` | `type` | — | Always Monographic; EFG does not state the level of a creation |
| `manifestation_title` | Manifestation | `avManifestation/title` | `has_primary_title (TitleProper), has_alternative_title` | Article handling in both directions | The work title is used when the manifestation carries none |
| `manifestation_note` | Manifestation | `avManifestation/note, avManifestation/provenance` | `has_note` | — | — |
| `thumbnail` | Manifestation | `avManifestation/thumbnail` | `has_webresource` | — | — |
| `publication_event` | Manifestation | `avManifestation/relPublicationEvent → efgEntity/publicationEvent` | `has_event (PublicationEvent)` | Profile publication_event_type_map | A type outside the vocabulary becomes UnknownEvent, which AVefi requires, and is reported |
| `publication_detail` | Manifestation | `publicationEvent/date, publicationEvent/place, publicationEvent/publisher` | `has_event.has_date, has_event.located_in, has_event.has_activity (ManifestationActivity)` | ISODate | — |
| `rights` | Manifestation | `avManifestation/rightsHolder, avManifestation/rightsStatus, avManifestation/coverage` | `—` | — | Reported as unmapped rather than dropped silently |
| `item_record` | Item | `avManifestation/item` | `has_identifier, described_by.has_source_key` | — | One item per item element; an avManifestation without item elements yields one item standing for the copy it describes |
| `duration` | Item | `avManifestation/duration` | `has_duration.has_value` | ISODurationInHours | AVefi holds the running time on the item, so it is applied to every item of the manifestation |
| `frame_rate` | Item | `avManifestation/duration/@frameRate` | `has_frame_rate` | Profile frame_rate_map | — |
| `language` | Item | `avManifestation/language` | `in_language.code, in_language.usage` | ISO 639-2/B, profile language_usage_map | — |
| `carrier` | Item | `avManifestation/format/carrier, avManifestation/format/gauge` | `has_format (Film, Video, Optical)` | Profile film_format_map, video_format_map, optical_format_map | — |
| `colour` | Item | `avManifestation/format/colour` | `has_colour_type` | Profile colour_type_map | The hasColor attribute is used when the element carries no term |
| `sound` | Item | `avManifestation/format/sound` | `has_sound_type` | Profile sound_type_map | The hasSound attribute is used when the element carries no term |
| `digital_format` | Item | `avManifestation/format/digital/container, avManifestation/format/digital/coding` | `has_format (DigitalFile, DigitalFileEncoding)` | Profile digital_file_format_map, digital_encoding_map | — |
| `aspect_ratio` | Item | `avManifestation/format/aspectRatio` | `—` | — | Reported as unmapped; AVefi has no field for it |
| `dimension` | Item | `avManifestation/dimension` | `has_extent.has_value, has_extent.has_unit` | Profile extent_unit_map | — |
| `webresource` | Item | `item/isShownAt, item/isShownBy, item/uri` | `has_webresource` | — | — |
| `file_format` | Item | `item/fileFormat` | `has_format (DigitalFile)` | Profile digital_file_format_map | — |
| `item_type` | Item | `item/type` | `—` | Profile moving_image_item_types | Reported when it does not denote a moving image; the item is converted either way |
| `item_provider` | Item | `item/provider, item/aggregator, item/country` | `—` | — | Reported; the issuer is taken from the profile so that it is unambiguous |
| `item_note` | Item | `item/note` | `has_note` | — | — |
| `unmapped_elements` | Work, Manifestation, Item | `avcreation/identifyingTitle, avcreation/userTag, avcreation/relCollection and further relations` | `—` | — | Elements without an AVefi counterpart are reported once per record, see UNMAPPED_ELEMENTS in the mapping module |
| `issuer` | Work, Manifestation, Item | `profile issuer_info` | `described_by.has_issuer_id, described_by.has_issuer_name` | — | An EFG document names the data provider in free text only, so the issuer comes from the profile; use of the shipped placeholder is reported once per input file |

## Assumptions

Decisions the mapping takes that EN 15907 and the EFG schema do not determine, and that need confirming against the reference data:

- `WorkVariant.type` is always `Monographic`. EFG states no level for a creation, so serial, analytic and collection works are not derived from it.
- Only `efgEntity` elements carrying an `avcreation` describe moving image holdings. `nonavcreation`, `person`, `corporate`, `group`, `collection`, `award`, `decisionEvent` and `iprEvent` entities are reported and skipped.
- EFG carries running time, language, colour, sound, carrier and dimension on the manifestation, AVefi on the item. Those values are therefore applied to every item of the manifestation.
- An `avManifestation` without `item` elements yields one item standing for the copy it describes. AVefi has no home for the technical description above item level, and a manifestation without items does not pass the AVefi checks.
- Works are shared between entities by the `avcreation` identifier and, when there is none, by title and production year. The key is configurable through `work_key_fields`.
- A `title` element without a `relation` is read as the preferred title, and a title in square brackets as supplied by the cataloguer, which makes it a `SuppliedDevisedTitle`.
- A language code that `core.normalise` does not know is passed through when it is a valid ISO 639-2/B code, and reported otherwise. EFG does not fix the code list.
- A `publicationEvent` whose type is missing or outside the profile vocabulary becomes `UnknownEvent`, because AVefi requires the field. The source value is reported.
- `avcreation/description` and `avcreation/note` have no counterpart in the AVefi work record. They are reported by default and only written to the manifestation notes when `work_description_target` asks for it.
- `item/provider` names the data provider in free text, not by ISIL, so it cannot become the AVefi issuer. It is reported, and the issuer comes from the profile.
- A `keywords` element whose type is in neither vocabulary has its terms kept as subjects rather than as genres, a subject being the weaker of the two claims.
- `format/colour/@hasColor` and `format/sound/@hasSound` are only read when the element carries no term that maps: true becomes `Colour` or `Sound`, false `BlackAndWhite` or `Silent`.
- An event that a further entity states again is only added to a known work or manifestation when it says something the events already there do not.
- A carrier or gauge outside the profile vocabularies is reported rather than passed through as a free text `Format`, so that an unreviewed term cannot enter the data.
- Decade expressions such as `50er Jahre` are reported as unconvertible unless `map_decades` is enabled in the profile.
- The shipped issuer is a documented placeholder. It has to be replaced with the ISIL of the data provider before the records are used.
