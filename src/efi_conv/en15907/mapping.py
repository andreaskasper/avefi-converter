"""Generic mapping from EN 15907 (EFG 3.2) to the AVefi schema.

EFG is an implementation of the EN 15907 entity model, whose Work,
Variant, Manifestation and Item levels are close to the ones AVefi
uses. The traversal of a document is therefore the same for every data
provider, and the mapping is markedly more direct than the one for a
schema without those levels. Everything that differs between data
providers — the issuer and the vocabularies used inside the elements
the schema declares as plain strings — is supplied through an
:class:`~efi_conv.en15907.profile.EfgProfile`.

One ``efgEntity`` carrying an ``avcreation`` yields one work, one
manifestation per ``avManifestation`` and one item per ``item``.

"""

from dataclasses import dataclass, field
import decimal
import logging
import re

from avefi_schema import model_pydantic_v2 as efi

from ..core.normalise import (
    NormalisationError,
    language_code,
    mapped_duration,
    normalise_date,
    normalise_title,
)
from ..core.records import (
    GroupingContext,
    SourceTitle,
    as_title,
    attach_source_key,
    make_key,
    slug,
    work_key,
)
from ..core.report import for_file, report_issue, report_record_skipped
from ..core.xmlrecords import first, parse_records, text_of
from .generated.efg_3_2 import EfgEntity
from .profile import EfgProfile

log = logging.getLogger(__name__)

#: Namespace and name of the record element of an EFG document. A
#: document may carry a single efgEntity as its root or many of them
#: under a wrapper element of the data provider's choosing.
NAMESPACE = "http://www.europeanfilmgateway.eu/efg"
RECORD_ELEMENT = "efgEntity"

#: A bare country code rather than the name of a country.
COUNTRY_CODE = re.compile(r"^[A-Za-z]{2,3}$")

#: Authority named by the prefix of a keywords/term/@id, and the AVefi
#: resource class holding an identifier from it. The prefixes follow
#: the AVefi identifier notation, so that the value can be transferred
#: as it stands.
AUTHORITY_RESOURCES = {
    "aat": efi.AATResource,
    "gnd": efi.GNDResource,
    "viaf": efi.VIAFResource,
    "wikidata": efi.WikidataResource,
}


@dataclass(frozen=True)
class MappingRule:
    """One documented mapping from an EFG path to an AVefi field."""

    id: str
    level: str
    source_path: str
    target_field: str
    normalisation: str = ""
    notes: str = ""


#: Single declaration of the mapping. The Markdown documentation is
#: rendered from this list, and a test asserts that code and table do
#: not drift apart.
MAPPING_RULES = (
    MappingRule(
        "entity_scope",
        "Record",
        "efgEntity/avcreation",
        "—",
        notes="Only entities carrying an avcreation become moving"
        " image records. productionEvent and publicationEvent entities"
        " are kept as referenced events, all other entity types are"
        " reported and skipped",
    ),
    MappingRule(
        "work_grouping",
        "Work",
        "avcreation/identifier, else title and productionYear",
        "has_identifier (work)",
        "Profile work_key_fields",
        "Several efgEntity elements describing one film share one"
        " WorkVariant, which providers splitting a work over several"
        " entities depend on",
    ),
    MappingRule(
        "manifestation_grouping",
        "Manifestation",
        "avManifestation/identifier, else entity key and position",
        "has_identifier (manifestation)",
        notes="Manifestations agreeing on their EFG identifier are"
        " shared between entities in the same way as works",
    ),
    MappingRule(
        "work_identifier",
        "Work",
        "avcreation/identifier",
        "described_by.has_source_key",
        "Profile preferred_identifier_schemes",
        "Also used to derive the local work identifier",
    ),
    MappingRule(
        "work_title",
        "Work",
        "avcreation/title[relation in preferred relations]/text",
        "has_primary_title.has_name, has_primary_title.has_ordering_name",
        "Article handling in both directions",
        "A title without a relation counts as preferred; the first"
        " title is used when no relation marks one; a title in square"
        " brackets becomes SuppliedDevisedTitle",
    ),
    MappingRule(
        "work_alternative_title",
        "Work",
        "avcreation/title (remaining)",
        "has_alternative_title",
        "Profile title_relation_map",
        "An unknown relation is reported and the title kept as"
        " AlternativeTitle",
    ),
    MappingRule(
        "title_detail",
        "Work, Manifestation",
        "title/partDesignation, title/temporalScope, title/geographicScope",
        "—",
        notes="Reported as unmapped rather than dropped silently",
    ),
    MappingRule(
        "genre",
        "Work",
        "avcreation/keywords[type in genre types]/term, term/@id",
        "has_genre.has_name, has_genre.same_as",
        "Profile genre_keyword_types",
        "A term identifier is transferred when it names an authority"
        " AVefi has a resource class for; a genre may only link to"
        " the GND, so any other authority is reported",
    ),
    MappingRule(
        "subject",
        "Work",
        "avcreation/keywords[type in subject types]/term, term/@id",
        "has_subject.has_name, has_subject.same_as",
        "Profile subject_keyword_types",
        "A term identifier such as `gnd/4079143-9` becomes an"
        " authority link; an authority AVefi has no resource class"
        " for is reported and the term kept without it",
    ),
    MappingRule(
        "production_year",
        "Work",
        "avcreation/productionYear",
        "has_event.has_date (ProductionEvent)",
        "ISODate",
        "Further production years are reported; AVefi holds one date"
        " per event",
    ),
    MappingRule(
        "country_of_reference",
        "Work",
        "avcreation/countryOfReference",
        "has_event.located_in.has_name,"
        " has_event.located_in.has_alternate_name (ProductionEvent)",
        "Profile country_name_map",
        notes="EFG states a country code and AVefi holds a name, so"
        " the code is expanded and kept as an alternate name; a code"
        " the profile does not know is reported rather than asserted"
        " as a name. The reference attribute names the code list and"
        " is reported",
    ),
    MappingRule(
        "director",
        "Work",
        "avcreation/relPerson, avcreation/relCorporate"
        " [type in directing roles]",
        "has_event.has_activity (DirectingActivity)",
        "Profile directing_role_map",
        "relPerson becomes an agent of type Person, relCorporate one"
        " of type CorporateBody; placeholder names are skipped and"
        " reported",
    ),
    MappingRule(
        "other_agent",
        "Work",
        "avcreation/relPerson, avcreation/relCorporate (remaining roles)",
        "—",
        notes="Reported as unmapped rather than dropped silently",
    ),
    MappingRule(
        "related_production_event",
        "Work",
        "avcreation/relProductionEvent → efgEntity/productionEvent",
        "has_event (ProductionEvent)",
        "Profile production_event_type_map",
        "Resolved against the productionEvent entities of the same"
        " document; an unresolvable reference is reported",
    ),
    MappingRule(
        "work_language",
        "Work",
        "avcreation/language",
        "—",
        notes="AVefi carries language on the item, so the value is"
        " reported unless the manifestation repeats it",
    ),
    MappingRule(
        "work_description",
        "Work",
        "avcreation/description, avcreation/note",
        "has_note (Manifestation) or —",
        "Profile work_description_target",
        "The AVefi work record has no field for free text, so the"
        " default is to report the value",
    ),
    MappingRule(
        "work_type",
        "Work",
        "—",
        "type",
        notes="Always Monographic; EFG does not state the level of a creation",
    ),
    MappingRule(
        "manifestation_title",
        "Manifestation",
        "avManifestation/title",
        "has_primary_title (TitleProper), has_alternative_title",
        "Article handling in both directions",
        "The work title is used when the manifestation carries none",
    ),
    MappingRule(
        "manifestation_note",
        "Manifestation",
        "avManifestation/note, avManifestation/provenance",
        "has_note",
    ),
    MappingRule(
        "thumbnail",
        "Manifestation",
        "avManifestation/thumbnail",
        "has_webresource",
    ),
    MappingRule(
        "publication_event",
        "Manifestation",
        "avManifestation/relPublicationEvent → efgEntity/publicationEvent",
        "has_event (PublicationEvent)",
        "Profile publication_event_type_map",
        "A type outside the vocabulary becomes UnknownEvent, which"
        " AVefi requires, and is reported",
    ),
    MappingRule(
        "publication_detail",
        "Manifestation",
        "publicationEvent/date, publicationEvent/place,"
        " publicationEvent/publisher",
        "has_event.has_date, has_event.located_in,"
        " has_event.has_activity (ManifestationActivity)",
        "ISODate",
    ),
    MappingRule(
        "rights",
        "Manifestation",
        "avManifestation/rightsHolder, avManifestation/rightsStatus,"
        " avManifestation/coverage",
        "—",
        notes="Reported as unmapped rather than dropped silently",
    ),
    MappingRule(
        "item_record",
        "Item",
        "avManifestation/item",
        "has_identifier, described_by.has_source_key",
        notes="One item per item element; an avManifestation without"
        " item elements yields one item standing for the copy it"
        " describes",
    ),
    MappingRule(
        "duration",
        "Item",
        "avManifestation/duration",
        "has_duration.has_value",
        "ISODurationInHours",
        "AVefi holds the running time on the item, so it is applied to"
        " every item of the manifestation",
    ),
    MappingRule(
        "frame_rate",
        "Item",
        "avManifestation/duration/@frameRate",
        "has_frame_rate",
        "Profile frame_rate_map",
    ),
    MappingRule(
        "language",
        "Item",
        "avManifestation/language",
        "in_language.code, in_language.usage",
        "ISO 639-2/B, profile language_usage_map",
    ),
    MappingRule(
        "carrier",
        "Item",
        "avManifestation/format/carrier, avManifestation/format/gauge",
        "has_format (Film, Video, Optical)",
        "Profile film_format_map, video_format_map, optical_format_map",
    ),
    MappingRule(
        "colour",
        "Item",
        "avManifestation/format/colour",
        "has_colour_type",
        "Profile colour_type_map",
        "The hasColor attribute is used when the element carries no term",
    ),
    MappingRule(
        "sound",
        "Item",
        "avManifestation/format/sound",
        "has_sound_type",
        "Profile sound_type_map",
        "The hasSound attribute is used when the element carries no term",
    ),
    MappingRule(
        "digital_format",
        "Item",
        "avManifestation/format/digital/container,"
        " avManifestation/format/digital/coding",
        "has_format (DigitalFile, DigitalFileEncoding)",
        "Profile digital_file_format_map, digital_encoding_map",
    ),
    MappingRule(
        "aspect_ratio",
        "Item",
        "avManifestation/format/aspectRatio",
        "—",
        notes="Reported as unmapped; AVefi has no field for it",
    ),
    MappingRule(
        "dimension",
        "Item",
        "avManifestation/dimension",
        "has_extent.has_value, has_extent.has_unit",
        "Profile extent_unit_map",
    ),
    MappingRule(
        "webresource",
        "Item",
        "item/isShownAt, item/isShownBy, item/uri",
        "has_webresource",
    ),
    MappingRule(
        "file_format",
        "Item",
        "item/fileFormat",
        "has_format (DigitalFile)",
        "Profile digital_file_format_map",
    ),
    MappingRule(
        "item_type",
        "Item",
        "item/type",
        "—",
        "Profile moving_image_item_types",
        "Reported when it does not denote a moving image; the item is"
        " converted either way",
    ),
    MappingRule(
        "item_provider",
        "Item",
        "item/provider, item/aggregator, item/country",
        "—",
        notes="Reported; the issuer is taken from the profile so that"
        " it is unambiguous",
    ),
    MappingRule(
        "item_note",
        "Item",
        "item/note",
        "has_note",
    ),
    MappingRule(
        "unmapped_elements",
        "Work, Manifestation, Item",
        "avcreation/identifyingTitle, avcreation/userTag,"
        " avcreation/relCollection and further relations",
        "—",
        notes="Elements without an AVefi counterpart are reported once"
        " per record, see UNMAPPED_ELEMENTS in the mapping module",
    ),
    MappingRule(
        "issuer",
        "Work, Manifestation, Item",
        "profile issuer_info",
        "described_by.has_issuer_id, described_by.has_issuer_name",
        notes="An EFG document names the data provider in free text"
        " only, so the issuer comes from the profile; use of the"
        " shipped placeholder is reported once per input file",
    ),
)

MAPPING_RULES_BY_ID = {rule.id: rule for rule in MAPPING_RULES}


#: Decisions the mapping takes that are not derivable from EFG alone.
#: They are listed in the generated documentation so that a reviewer
#: sees them without reading the code.
ASSUMPTIONS = (
    "`WorkVariant.type` is always `Monographic`. EFG states no level"
    " for a creation, so serial, analytic and collection works are not"
    " derived from it.",
    "Only `efgEntity` elements carrying an `avcreation` describe"
    " moving image holdings. `nonavcreation`, `person`, `corporate`,"
    " `group`, `collection`, `award`, `decisionEvent` and `iprEvent`"
    " entities are reported and skipped.",
    "EFG carries running time, language, colour, sound, carrier and"
    " dimension on the manifestation, AVefi on the item. Those values"
    " are therefore applied to every item of the manifestation.",
    "An `avManifestation` without `item` elements yields one item"
    " standing for the copy it describes. AVefi has no home for the"
    " technical description above item level, and a manifestation"
    " without items does not pass the AVefi checks.",
    "Works are shared between entities by the `avcreation` identifier"
    " and, when there is none, by title and production year. The key"
    " is configurable through `work_key_fields`.",
    "A `title` element without a `relation` is read as the preferred"
    " title, and a title in square brackets as supplied by the"
    " cataloguer, which makes it a `SuppliedDevisedTitle`.",
    "A language code that `core.normalise` does not know is passed"
    " through when it is a valid ISO 639-2/B code, and reported"
    " otherwise. EFG does not fix the code list.",
    "A `publicationEvent` whose type is missing or outside the profile"
    " vocabulary becomes `UnknownEvent`, because AVefi requires the"
    " field. The source value is reported.",
    "`avcreation/description` and `avcreation/note` have no"
    " counterpart in the AVefi work record. They are reported by"
    " default and only written to the manifestation notes when"
    " `work_description_target` asks for it.",
    "`item/provider` names the data provider in free text, not by"
    " ISIL, so it cannot become the AVefi issuer. It is reported, and"
    " the issuer comes from the profile.",
    "A `keywords` element whose type is in neither vocabulary has"
    " its terms kept as subjects rather than as genres, a subject"
    " being the weaker of the two claims.",
    "A `keywords/term/@id` is read as an identifier in the authority"
    " its prefix names, in the notation AVefi uses for the same"
    " authorities, and becomes `same_as`. AVefi has a resource class"
    " for the GND, VIAF, Wikidata and the AAT only, and allows a"
    " genre to link to the GND alone; anything else is reported and"
    " the term kept without its identifier.",
    "`countryOfReference` is a code, and `GeographicName.has_name` is"
    " a name. The code is expanded through the profile vocabulary and"
    " kept as an alternate name of the place. A code the profile does"
    " not know is reported and no production country asserted,"
    " because a code is not the name of anything.",
    "`format/colour/@hasColor` and `format/sound/@hasSound` are only"
    " read when the element carries no term that maps: true becomes"
    " `Colour` or `Sound`, false `BlackAndWhite` or `Silent`.",
    "An event that a further entity states again is only added to a"
    " known work or manifestation when it says something the events"
    " already there do not.",
    "A carrier or gauge outside the profile vocabularies is reported"
    " rather than passed through as a free text `Format`, so that an"
    " unreviewed term cannot enter the data.",
    "Decade expressions such as `50er Jahre` are reported as"
    " unconvertible unless `map_decades` is enabled in the profile.",
    "The shipped issuer is a documented placeholder. It has to be"
    " replaced with the ISIL of the data provider before the records"
    " are used.",
    "A work key that would be no more than the title does not group:"
    " the record keeps a work of its own, and the decision is reported."
    " Two undated films of the same name are two films, and one AVefi"
    " identifier registered for both cannot be corrected afterwards,"
    " whereas two works minted for one film can be merged.",
    "A running time that cannot be read leaves `has_duration` unset"
    " and is reported. Discarding the record over it would cost the"
    " work, every manifestation and every item derived from it.",
)


#: Elements that have no counterpart in the AVefi schema. They are
#: reported once per record so that a reviewer sees what an export
#: carries beyond what is mapped.
UNMAPPED_ELEMENTS = {
    "avcreation": (
        ("identifying_title", "avcreation/identifyingTitle"),
        ("user_tag", "avcreation/userTag"),
        ("view_filmography", "avcreation/viewFilmography"),
        ("record_source", "avcreation/recordSource"),
        ("rel_group", "avcreation/relGroup"),
        ("rel_av_creation", "avcreation/relAvCreation"),
        ("rel_non_avcreation", "avcreation/relNonAVCreation"),
        ("rel_collection", "avcreation/relCollection"),
        ("rel_ipr_registration", "avcreation/relIprRegistration"),
        ("rel_award", "avcreation/relAward"),
    ),
    "avManifestation": (
        ("record_source", "avManifestation/recordSource"),
        ("coverage", "avManifestation/coverage"),
        ("rights_holder", "avManifestation/rightsHolder"),
        ("rights_status", "avManifestation/rightsStatus"),
        ("av_creation_rel", "avManifestation/avCreationRel"),
        ("rel_decision_event", "avManifestation/relDecisionEvent"),
        ("rel_production_event", "avManifestation/relProductionEvent"),
        ("rel_person", "avManifestation/relPerson"),
        ("rel_corporate", "avManifestation/relCorporate"),
        ("rel_group", "avManifestation/relGroup"),
    ),
    "item": (
        ("aggregator", "item/aggregator"),
        ("rel_person", "item/relPerson"),
        ("rel_corporate", "item/relCorporate"),
        ("rel_group", "item/relGroup"),
    ),
}


def render_mapping_markdown(rules=MAPPING_RULES) -> str:
    """Return the mapping table as a Markdown document."""
    lines = [
        "# EN 15907 (EFG) to AVefi mapping",
        "",
        "Generated from `MAPPING_RULES` in `efi_conv.en15907.mapping`;",
        "do not edit by hand.",
        "",
        "| Rule | Level | EFG source | AVefi target | Normalisation | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for rule in rules:
        lines.append(
            f"| `{rule.id}` | {rule.level} | `{rule.source_path}` |"
            f" `{rule.target_field}` | {rule.normalisation or '—'} |"
            f" {rule.notes or '—'} |"
        )
    lines += [
        "",
        "## Assumptions",
        "",
        "Decisions the mapping takes that EN 15907 and the EFG schema"
        " do not determine, and that need confirming against the"
        " reference data:",
        "",
    ]
    lines += [f"- {assumption}" for assumption in ASSUMPTIONS]
    return "\n".join(lines) + "\n"


def parse_efg(input_file):
    """Yield the efgEntity elements of an EFG document.

    Handles both a document whose root is a single efgEntity and one
    holding many of them under a wrapper element, and streams the file
    so that memory use stays independent of the size of the export.

    """
    return parse_records(input_file, EfgEntity, NAMESPACE, RECORD_ELEMENT)


@dataclass
class MappingContext(GroupingContext):
    """State shared by all entities of one conversion.

    A data provider may split one film over several efgEntity
    elements, and the events a manifestation refers to are entities of
    their own. Works, manifestations and the event registry are
    therefore shared across the entities of a run.

    """

    profile: EfgProfile | None = None
    events: dict = field(default_factory=dict)
    items: dict = field(default_factory=dict)


def efi_import(
    input_file,
    profile: EfgProfile,
    continue_on_error: bool = False,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Convert an EFG file into AVefi records using ``profile``.

    Parameters
    ----------
    input_file
        Path of the EFG document.
    profile : EfgProfile
        Data provider specific configuration.
    continue_on_error : bool
        Report an entity that cannot be converted and carry on with
        the remaining ones, instead of aborting the whole file.
    context : MappingContext, optional
        Grouping context to add the records of this file to. One
        conversion of several files passes the same context to each of
        them, so that a film split over several files yields one work.
        The events of each file are added to the registry the context
        carries. Without a context the file is converted on its own.

    """
    if profile.work_description_target not in (
        "report",
        "manifestation_note",
    ):
        raise ValueError(
            f"Unknown work_description_target:"
            f" {profile.work_description_target!r}"
        )
    records = []
    if context is None:
        context = new_context(profile)
    with for_file(input_file):
        if profile.uses_placeholder_issuer():
            report_issue(
                "warning",
                "Placeholder issuer in use; replace it with the ISIL of"
                " the data provider before the records are used",
                source_field="profile issuer_info",
                target_field="described_by.has_issuer_id",
                raw_value=profile.issuer_info.get("has_issuer_id"),
            )
        # The events of every file of the run are registered
        # together: a manifestation may refer to an event entity
        # published in another file of the same delivery.
        context.events.update(collect_events(input_file, profile))
        for entity in parse_efg(input_file):
            try:
                with context.attempt():
                    records.extend(map_entity(entity, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_record_skipped(
                    e, record_id=safe_entity_identifier(entity, profile)
                )
    return records


def new_context(profile: EfgProfile) -> MappingContext:
    """Return a grouping context for one conversion.

    Handed to :func:`efi_import` once per run rather than once per
    file, so that the works, manifestations and items of a conversion
    are shared between the input files.

    """
    return MappingContext(profile=profile)


def collect_events(input_file, profile: EfgProfile) -> dict:
    """Return the event entities of a document, by identifier.

    A manifestation refers to its publication event, and a creation to
    its production event, by identifier. The referenced entity may
    appear anywhere in the document, so the events are collected in a
    pass of their own before the creations are converted.

    """
    registry = {}
    for entity in parse_efg(input_file):
        for kind, element in (
            ("productionEvent", entity.production_event),
            ("publicationEvent", entity.publication_event),
        ):
            if element is None:
                continue
            keys = identifier_keys(element.identifier)
            if not keys:
                report_issue(
                    "warning",
                    f"{kind} entity without identifier, no manifestation"
                    f" can refer to it",
                    source_field=f"efgEntity/{kind}/identifier",
                    target_field="has_event",
                )
                continue
            for key in keys:
                registry[key] = (kind, element)
    return registry


def map_entity(
    entity: EfgEntity,
    profile: EfgProfile,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one efgEntity."""
    if context is None:
        context = MappingContext(profile=profile)
    avcreation = entity.avcreation
    if avcreation is None:
        report_other_entity(entity, profile)
        return []

    identifier = identifier_value(avcreation.identifier, profile)
    if not avcreation.av_manifestation:
        report_issue(
            "warning",
            "avcreation without avManifestation; a work without"
            " manifestations is not a usable AVefi record, entity"
            " skipped",
            record_id=identifier,
            source_field="avcreation/avManifestation",
            target_field="—",
        )
        return []

    titles = collect_titles(
        avcreation.title, profile, identifier, "avcreation/title"
    )
    if not titles:
        raise ValueError(
            f"EFG entity {identifier or '(without identifier)'} has no"
            f" usable title"
        )
    primary, alternatives = split_titles(
        titles, identifier, "avcreation/title"
    )
    production_year = first_production_year(avcreation, identifier)
    work_key = make_work_key(profile, identifier, primary, production_year)
    source_key = identifier or slug(work_key)
    if identifier is None:
        report_issue(
            "info",
            "avcreation without identifier; source key derived from"
            " title and production year",
            record_id=source_key,
            source_field="avcreation/identifier",
            target_field="described_by.has_source_key",
            raw_value=source_key,
        )

    report_unmapped(avcreation, UNMAPPED_ELEMENTS["avcreation"], source_key)
    report_work_language(avcreation, source_key)
    descriptions = collect_work_descriptions(avcreation, profile, source_key)
    genres, subjects = collect_keyword_terms(avcreation, profile, source_key)
    events = [
        event
        for event in (
            build_production_event(avcreation, profile, source_key),
            *build_related_production_events(
                avcreation, profile, source_key, context
            ),
        )
        if event is not None
    ]

    new_records = []

    def new_work():
        return efi.WorkVariant(
            type=efi.WorkVariantTypeEnum("Monographic"),
            has_primary_title=as_title(primary.title, primary.type),
        )

    work, is_new = context.work_for(work_key, new_work)
    if is_new:
        new_records.append(work)
    merge_alternative_titles(work, alternatives)
    merge_named(work.has_genre, genres, efi.Genre)
    merge_named(work.has_subject, subjects, efi.Subject)
    for event in events:
        add_event(work, event)
    attach_source_key((work,), profile.issuer_info, source_key)

    for position, element in enumerate(avcreation.av_manifestation, start=1):
        new_records.extend(
            map_manifestation(
                element,
                position,
                work,
                source_key,
                primary,
                descriptions,
                profile,
                context,
            )
        )
    return new_records


def map_manifestation(
    element,
    position: int,
    work,
    entity_key: str,
    work_title: "TypedTitle",
    descriptions: tuple,
    profile: EfgProfile,
    context: MappingContext,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one avManifestation."""
    records = []
    identifier = identifier_value(element.identifier, profile)
    manifestation_key = identifier or make_key(entity_key, position)
    source_key = identifier or f"{entity_key}#manifestation{position}"

    titles = collect_titles(
        element.title, profile, source_key, "avManifestation/title"
    )
    if titles:
        primary, alternatives = split_titles(
            titles, source_key, "avManifestation/title"
        )
    else:
        primary, alternatives = work_title, []

    report_unmapped(element, UNMAPPED_ELEMENTS["avManifestation"], source_key)
    publications = build_publication_events(
        element, profile, source_key, context
    )
    copy = describe_copy(element, profile, source_key)

    def new_manifestation():
        return efi.Manifestation(
            is_manifestation_of=[work.has_identifier[0]],
            has_primary_title=as_title(primary.title, "TitleProper"),
        )

    manifestation, is_new = context.manifestation_for(
        manifestation_key, new_manifestation
    )
    if is_new:
        records.append(manifestation)
    merge_alternative_titles(manifestation, alternatives)
    for event in publications:
        add_event(manifestation, event)
    for note in (*descriptions, *manifestation_notes(element)):
        if note not in manifestation.has_note:
            manifestation.has_note.append(note)
    for url in element.thumbnail or []:
        text = text_of(url)
        if text and text not in manifestation.has_webresource:
            manifestation.has_webresource.append(text)
    attach_source_key((manifestation,), profile.issuer_info, source_key)

    for item_position, item_element in enumerate(
        list(element.item or []) or [None], start=1
    ):
        if item_element is None:
            report_issue(
                "info",
                "avManifestation without item elements; one item created"
                " for the copy it describes",
                record_id=source_key,
                source_field="avManifestation/item",
                target_field="Item",
            )
        item = build_item(
            item_element,
            item_position,
            manifestation,
            source_key,
            primary,
            copy,
            profile,
            context,
        )
        if item is not None:
            records.append(item)
    return records


def build_item(
    element,
    position: int,
    manifestation,
    manifestation_key: str,
    primary: "TypedTitle",
    copy: "CopyDescription",
    profile: EfgProfile,
    context: MappingContext,
):
    """Return the Item for one item element, or None if it is a repeat."""
    if element is None:
        source_key = f"{manifestation_key}#item"
    else:
        source_key = (
            identifier_value(element.identifier, profile)
            or f"{manifestation_key}#item{position}"
        )
    if source_key in context.items:
        report_issue(
            "warning",
            "Item identifier occurs more than once in this run; the"
            " repeated occurrence is not converted",
            record_id=source_key,
            source_field="item/identifier",
            target_field="has_identifier",
            raw_value=source_key,
        )
        return None

    item = efi.Item(
        is_item_of=manifestation.has_identifier[0],
        has_primary_title=as_title(primary.title, "TitleProper"),
    )
    item.has_identifier.append(efi.LocalResource(id=source_key))
    copy.apply(item)
    if element is not None:
        map_item_element(item, element, source_key, profile)
    context.items[source_key] = item
    attach_source_key((item,), profile.issuer_info, source_key)
    return item


def map_item_element(item, element, source_key: str, profile: EfgProfile):
    """Fill in everything the item element itself contributes."""
    for attribute in ("is_shown_at", "is_shown_by", "uri"):
        for value in getattr(element, attribute, None) or []:
            text = text_of(value)
            if text and text not in item.has_webresource:
                item.has_webresource.append(text)
    for note in element.note or []:
        text = text_of(note)
        if text and text not in item.has_note:
            item.has_note.append(text)
    for value in element.file_format or []:
        text = text_of(value)
        if not text:
            continue
        mapped = profile.digital_file_format_map.get(text.strip().lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi file format configured for this value",
                record_id=source_key,
                source_field="item/fileFormat",
                target_field="has_format",
                raw_value=text,
            )
            continue
        digital = efi.DigitalFile(type=efi.FormatDigitalFileTypeEnum(mapped))
        if digital not in item.has_format:
            item.has_format.append(digital)
    for value in element.type_value or []:
        text = text_of(value)
        if text and text.strip().lower() not in (
            profile.moving_image_item_types
        ):
            report_issue(
                "warning",
                "Item type does not denote a moving image; the item is"
                " converted all the same",
                record_id=source_key,
                source_field="item/type",
                target_field="—",
                raw_value=text,
            )
    for attribute, source_field, message in (
        (
            "provider",
            "item/provider",
            "The data provider is named in free text only; the issuer"
            " is taken from the profile instead",
        ),
        (
            "country",
            "item/country",
            "AVefi has no field for the country of the digital object",
        ),
    ):
        for value in getattr(element, attribute, None) or []:
            text = text_of(value)
            if text:
                report_issue(
                    "info",
                    message,
                    record_id=source_key,
                    source_field=source_field,
                    target_field="—",
                    raw_value=text,
                )
    if element.high_quality is not None:
        report_issue(
            "info",
            "AVefi has no field for the highQuality flag",
            record_id=source_key,
            source_field="item/@highQuality",
            target_field="—",
            raw_value=element.high_quality,
        )
    report_unmapped(element, UNMAPPED_ELEMENTS["item"], source_key)


# --- titles -----------------------------------------------------------


@dataclass(frozen=True)
class TypedTitle:
    """A title of an EFG element together with its AVefi type."""

    title: SourceTitle
    type: str
    preferred: bool = False


def collect_titles(
    elements, profile: EfgProfile, record_id, source_field: str
) -> list[TypedTitle]:
    """Return the titles of an element, typed by their relation."""
    titles = []
    for element in elements or []:
        relation = (text_of(first(element.relation)) or "").strip().lower()
        report_title_detail(element, record_id, source_field)
        language = (
            language_code(getattr(element, "lang", None))
            or profile.default_language
        )
        for raw in element.text or []:
            value = text_of(raw)
            if not value:
                continue
            supplied = value.startswith("[") and value.endswith("]")
            if supplied:
                value = value[1:-1].strip()
                if not value:
                    continue
            preferred = relation in profile.preferred_title_relations
            if relation in profile.supplied_title_relations:
                supplied = True
                preferred = True
            if preferred:
                title_type = "PreferredTitle"
            elif relation in profile.title_relation_map:
                title_type = profile.title_relation_map[relation]
            else:
                report_issue(
                    "warning",
                    "No AVefi title type configured for this relation;"
                    " the title is kept as an alternative title",
                    record_id=record_id,
                    source_field=f"{source_field}/relation",
                    target_field="has_alternative_title.type",
                    raw_value=relation,
                )
                title_type = "AlternativeTitle"
            target_field = (
                "has_primary_title.has_ordering_name"
                if preferred
                else "has_alternative_title.has_ordering_name"
            )
            display, ordering = normalise_title(
                value,
                language,
                record_id=record_id,
                target_field=target_field,
            )
            if ordering and ordering != display:
                report_issue(
                    "info",
                    "Derived ordering name from article position",
                    record_id=record_id,
                    source_field=f"{source_field}/text",
                    target_field=target_field,
                    raw_value=value,
                )
            titles.append(
                TypedTitle(
                    SourceTitle(display, ordering, supplied),
                    title_type,
                    preferred,
                )
            )
    return titles


def split_titles(
    titles: list[TypedTitle], record_id, source_field: str
) -> tuple[TypedTitle, list[TypedTitle]]:
    """Return the primary title and the remaining ones."""
    for index, candidate in enumerate(titles):
        if candidate.preferred:
            return candidate, titles[:index] + titles[index + 1 :]
    report_issue(
        "info",
        "No title relation denotes a preferred title; the first title"
        " is used as the primary title",
        record_id=record_id,
        source_field=f"{source_field}/relation",
        target_field="has_primary_title",
        raw_value=titles[0].title.display,
    )
    primary = TypedTitle(titles[0].title, "PreferredTitle", True)
    return primary, titles[1:]


def merge_alternative_titles(record, alternatives: list[TypedTitle]):
    """Add alternative titles to a record, keeping their AVefi type.

    ``efi_conv.core.records.merge_alternative_titles`` types every
    title it adds as AlternativeTitle, which is all a source without a
    title relation vocabulary can say. EFG states the relation of a
    title, so the type derived from it has to survive the merge. This
    is the same duplicate check with the derived type kept.

    """
    known = {title.has_name for title in record.has_alternative_title}
    for alternative in alternatives:
        if alternative.title.display in known:
            continue
        record.has_alternative_title.append(
            as_title(alternative.title, alternative.type)
        )
        known.add(alternative.title.display)


def report_title_detail(element, record_id, source_field: str):
    """Report the parts of a title element AVefi cannot hold."""
    for attribute, name in (
        ("part_designation", "partDesignation"),
        ("temporal_scope", "temporalScope"),
        ("geographic_scope", "geographicScope"),
    ):
        value = getattr(element, attribute, None)
        if not value:
            continue
        report_issue(
            "info",
            "AVefi holds a title as a name only; this detail is not"
            " transferred",
            record_id=record_id,
            source_field=f"{source_field}/{name}",
            target_field="—",
            raw_value=describe_value(value),
        )


# --- identifiers and entity level helpers -----------------------------


def identifier_keys(identifiers) -> list[str]:
    """Return the lookup keys an identifier element provides."""
    keys = []
    for identifier in identifiers or []:
        value = text_of(identifier)
        if not value:
            continue
        keys.append(value)
        scheme = getattr(identifier, "scheme", None)
        if scheme:
            keys.append(f"{scheme}|{value}")
    return keys


def identifier_value(identifiers, profile: EfgProfile) -> str | None:
    """Return the identifier of an element, honouring the profile."""
    found = []
    for identifier in identifiers or []:
        value = text_of(identifier)
        if value:
            found.append(((getattr(identifier, "scheme", None) or ""), value))
    if not found:
        return None
    for scheme in profile.preferred_identifier_schemes:
        for candidate_scheme, value in found:
            if candidate_scheme.lower() == scheme.lower():
                return value
    return found[0][1]


#: The payload elements an efgEntity may carry, with the names the
#: schema uses for them.
ENTITY_ELEMENTS = (
    ("nonavcreation", "nonavcreation"),
    ("person", "person"),
    ("corporate", "corporate"),
    ("group", "group"),
    ("collection", "collection"),
    ("decision_event", "decisionEvent"),
    ("publication_event", "publicationEvent"),
    ("production_event", "productionEvent"),
    ("award", "award"),
    ("ipr_event", "iprEvent"),
)


def report_other_entity(entity: EfgEntity, profile: EfgProfile):
    """Report an entity that does not describe a moving image."""
    for attribute, name in ENTITY_ELEMENTS:
        element = getattr(entity, attribute, None)
        if element is None:
            continue
        record_id = identifier_value(
            getattr(element, "identifier", None), profile
        )
        if attribute in ("production_event", "publication_event"):
            report_issue(
                "info",
                f"{name} entity is converted only where a creation or"
                f" manifestation refers to it",
                record_id=record_id,
                source_field=f"efgEntity/{name}",
                target_field="has_event",
            )
        else:
            report_issue(
                "info",
                f"{name} entity does not describe moving image"
                f" holdings; skipped",
                record_id=record_id,
                source_field=f"efgEntity/{name}",
                target_field="—",
            )
        return
    report_issue(
        "warning",
        "efgEntity without a payload element; skipped",
        source_field="efgEntity",
        target_field="—",
    )


def safe_entity_identifier(
    entity: EfgEntity, profile: EfgProfile
) -> str | None:
    """Return the identifier of an entity, or None if there is none."""
    for attribute in ("avcreation", *(name for name, _ in ENTITY_ELEMENTS)):
        element = getattr(entity, attribute, None)
        if element is None:
            continue
        return identifier_value(getattr(element, "identifier", None), profile)
    return None


def first_production_year(avcreation, record_id) -> str | None:
    """Return the production year to map, reporting any further one."""
    years = [
        text
        for text in (text_of(y) for y in avcreation.production_year or [])
        if text
    ]
    if not years:
        return None
    if len(years) > 1:
        report_issue(
            "warning",
            "AVefi holds one date per event; only the first"
            " productionYear is mapped",
            record_id=record_id,
            source_field="avcreation/productionYear",
            target_field="has_event.has_date",
            raw_value=years,
        )
    return years[0]


def make_work_key(
    profile: EfgProfile,
    identifier: str | None,
    primary: TypedTitle,
    production_year: str | None,
) -> str:
    """Return the key identifying the work an entity belongs to."""
    values = {
        "identifier": identifier or "",
        "title": primary.title.ordering or primary.title.display,
        "production_year": production_year or "",
    }

    def parts_for(names):
        parts = []
        for name in names:
            if name not in values:
                raise ValueError(f"Unknown work key field: {name}")
            parts.append(values[name])
        return parts

    names = profile.work_key_fields
    if not any(parts_for(names)):
        names = profile.work_key_fallback_fields
    parts = {name: values[name] for name in names}
    return work_key(
        parts,
        identifier or slug(make_key(*parts.values())),
        record_id=identifier,
    )


def merge_named(target: list, entries, factory):
    """Add ``entries`` to a list of named AVefi objects, once each.

    Parameters
    ----------
    target : list
        The AVefi objects collected so far.
    entries : iterable
        Pairs of name and authority resource, the latter None where
        the source names none.
    factory : type
        The AVefi class to build, Genre or Subject.

    """
    known = {entry.has_name for entry in target}
    for name, link in entries:
        if name in known:
            continue
        entry = factory(has_name=name)
        if link is not None:
            entry.same_as = [link]
        target.append(entry)
        known.add(name)


def describe_value(value):
    """Return a readable rendering of a source value for the report."""
    if isinstance(value, (list, tuple)):
        return [describe_value(entry) for entry in value]
    text = text_of(value)
    if text is not None:
        return text
    for attribute in ("name", "title"):
        inner = text_of(getattr(value, attribute, None))
        if inner:
            return inner
    return str(value)


def report_unmapped(element, entries, record_id):
    """Report the elements of ``element`` that AVefi cannot hold."""
    for attribute, source_field in entries:
        value = getattr(element, attribute, None)
        if not value:
            continue
        report_issue(
            "info",
            "No AVefi counterpart for this element; value not transferred",
            record_id=record_id,
            source_field=source_field,
            target_field="—",
            raw_value=describe_value(value),
        )


def report_work_language(avcreation, record_id):
    """Report the language stated for the creation as a whole."""
    for language in avcreation.language or []:
        report_issue(
            "info",
            "AVefi carries language on the item; the language stated"
            " for the creation is not transferred",
            record_id=record_id,
            source_field="avcreation/language",
            target_field="in_language",
            raw_value=text_of(language),
        )


def collect_work_descriptions(
    avcreation, profile: EfgProfile, record_id
) -> tuple:
    """Return the free text of a creation, as the profile asks."""
    texts = []
    for attribute, source_field in (
        ("description", "avcreation/description"),
        ("note", "avcreation/note"),
    ):
        for element in getattr(avcreation, attribute, None) or []:
            value = text_of(element)
            if not value:
                continue
            if profile.work_description_target == "manifestation_note":
                texts.append(value)
                report_issue(
                    "info",
                    "The AVefi work record has no field for free text;"
                    " kept as a note of the manifestation",
                    record_id=record_id,
                    source_field=source_field,
                    target_field="has_note",
                    raw_value=value,
                )
            else:
                report_issue(
                    "info",
                    "The AVefi work record has no field for free text;"
                    " value not transferred",
                    record_id=record_id,
                    source_field=source_field,
                    target_field="—",
                    raw_value=value,
                )
    return tuple(texts)


def collect_keyword_terms(
    avcreation, profile: EfgProfile, record_id
) -> tuple[list, list]:
    """Return the genre and subject terms of a creation.

    Returns
    -------
    tuple
        Two lists of (term, authority link) pairs, the genres and the
        subjects. The link is None where the term carries no ``@id``
        or where AVefi has no resource class for the authority it
        names.

    """
    genres, subjects = [], []
    for keywords in avcreation.keywords or []:
        kind = str(getattr(keywords, "type_value", "") or "").strip().lower()
        if kind in profile.genre_keyword_types:
            target = genres
        elif kind in profile.subject_keyword_types:
            target = subjects
        else:
            report_issue(
                "warning",
                "Unknown keyword type; the terms are kept as subjects"
                " rather than as genres",
                record_id=record_id,
                source_field="avcreation/keywords/@type",
                target_field="has_subject",
                raw_value=kind,
            )
            target = subjects
        for term in keywords.term or []:
            value = text_of(term)
            if not value:
                continue
            target.append(
                (
                    value,
                    authority_resource(
                        getattr(term, "id", None),
                        efi.GNDResource if target is genres else None,
                        record_id,
                    ),
                )
            )
    return genres, subjects


def authority_resource(identifier, only, record_id):
    """Return the AVefi resource a keyword identifier names.

    EFG qualifies a keyword term with the identifier it carries in the
    authority file the provider uses, written as the authority name, a
    slash and the number. AVefi has a resource class for a few
    authorities, and ``same_as`` on both Genre and Subject to hold
    them; a genre may only link to the GND.

    Parameters
    ----------
    identifier : str or None
        Value of ``keywords/term/@id``.
    only : type or None
        The single resource class the target field accepts, or None
        when it accepts all of them.
    record_id : str
        Identifier used when reporting.

    """
    value = (identifier or "").strip()
    if not value:
        return None
    prefix = value.split("/", 1)[0].lower()
    resource = AUTHORITY_RESOURCES.get(prefix)
    if resource is None or (only is not None and resource is not only):
        report_issue(
            "warning",
            "AVefi has no resource class for this authority at this"
            " level, the term is kept without its identifier",
            record_id=record_id,
            source_field="avcreation/keywords/term/@id",
            target_field="same_as",
            raw_value=value,
        )
        return None
    return resource(id=value)


def manifestation_notes(element):
    """Yield the free text an avManifestation carries."""
    for attribute in ("note", "provenance"):
        for entry in getattr(element, attribute, None) or []:
            value = text_of(entry)
            if value:
                yield value


# --- events -----------------------------------------------------------


def build_production_event(avcreation, profile: EfgProfile, record_id):
    """Return the ProductionEvent the creation itself describes."""
    event = efi.ProductionEvent()
    year = first_production_year(avcreation, record_id)
    if year:
        event.has_date = mapped_date(
            year,
            profile,
            record_id,
            "avcreation/productionYear",
        )
    for country in avcreation.country_of_reference or []:
        name = text_of(country)
        if not name:
            continue
        reference = getattr(country, "reference", None)
        if reference:
            report_issue(
                "info",
                "AVefi has no field for the code list a country refers to",
                record_id=record_id,
                source_field="avcreation/countryOfReference/@reference",
                target_field="—",
                raw_value=reference,
            )
        place = country_name(name, profile, record_id)
        if place is not None:
            event.located_in.append(place)
    event.has_activity.extend(
        collect_directing_activities(
            avcreation, profile, record_id, "avcreation"
        )
    )
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def country_name(value: str, profile: EfgProfile, record_id):
    """Return the place a countryOfReference names, if it names one.

    EFG states the country as an ISO 3166-1 alpha-2 code, and an AVefi
    GeographicName holds a name. A code is therefore expanded through
    the profile vocabulary; a code the profile does not know is
    reported rather than asserted as a name, because "ZZ" is not the
    name of anything.

    """
    if not COUNTRY_CODE.match(value):
        return efi.GeographicName(has_name=value)
    expanded = profile.country_name_map.get(value.upper())
    if expanded is None:
        report_issue(
            "warning",
            "No country name configured for this code, and a code is"
            " not a name; production country not transferred",
            record_id=record_id,
            source_field="avcreation/countryOfReference",
            target_field="has_event.located_in.has_name",
            raw_value=value,
        )
        return None
    return efi.GeographicName(
        has_name=expanded, has_alternate_name=[value.upper()]
    )


def build_related_production_events(
    avcreation, profile: EfgProfile, record_id, context: MappingContext
) -> list:
    """Return the ProductionEvents the creation refers to."""
    events = []
    for related in avcreation.rel_production_event or []:
        element = resolve_related_event(
            related,
            "productionEvent",
            context,
            record_id,
            "avcreation/relProductionEvent",
        )
        if element is None:
            continue
        event = build_production_event_entity(element, profile, record_id)
        if event is not None:
            events.append(event)
    return events


def build_production_event_entity(element, profile: EfgProfile, record_id):
    """Return the ProductionEvent a productionEvent entity describes."""
    event = efi.ProductionEvent()
    kind = text_of(first(element.type_value))
    if kind:
        mapped = profile.production_event_type_map.get(kind.strip().lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi production event type configured for this"
                " value; the event is kept without a type",
                record_id=record_id,
                source_field="productionEvent/type",
                target_field="has_event.type",
                raw_value=kind,
            )
        else:
            event.type = efi.ProductionEventTypeEnum(mapped)
    date = text_of(first(element.date))
    if date:
        event.has_date = mapped_date(
            date, profile, record_id, "productionEvent/date"
        )
    for attribute in ("location", "regional_scope"):
        for value in getattr(element, attribute, None) or []:
            name = text_of(value)
            if name:
                event.located_in.append(efi.GeographicName(has_name=name))
    event.has_activity.extend(
        collect_directing_activities(
            element, profile, record_id, "productionEvent"
        )
    )
    report_unmapped(
        element,
        (
            ("note", "productionEvent/note"),
            ("record_source", "productionEvent/recordSource"),
            ("rel_group", "productionEvent/relGroup"),
            ("rel_av_manifestation", "productionEvent/relAvManifestation"),
            (
                "rel_non_avmanifestation",
                "productionEvent/relNonAVManifestation",
            ),
        ),
        record_id,
    )
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def build_publication_events(
    element, profile: EfgProfile, record_id, context: MappingContext
) -> list:
    """Return the PublicationEvents a manifestation refers to."""
    events = []
    for related in element.rel_publication_event or []:
        event_element = resolve_related_event(
            related,
            "publicationEvent",
            context,
            record_id,
            "avManifestation/relPublicationEvent",
        )
        if event_element is None:
            continue
        event = build_publication_event_entity(
            event_element, profile, record_id
        )
        if event is not None:
            events.append(event)
    return events


def build_publication_event_entity(element, profile: EfgProfile, record_id):
    """Return the PublicationEvent a publicationEvent entity describes."""
    kind = text_of(first(element.type_value))
    mapped = None
    if kind:
        mapped = profile.publication_event_type_map.get(kind.strip().lower())
    if mapped is None:
        report_issue(
            "warning",
            "No AVefi publication event type configured for this value;"
            " AVefi requires the field, so"
            f" {profile.default_publication_event_type} is used",
            record_id=record_id,
            source_field="publicationEvent/type",
            target_field="has_event.type",
            raw_value=kind,
        )
        mapped = profile.default_publication_event_type
    event = efi.PublicationEvent(type=efi.PublicationEventTypeEnum(mapped))
    date = text_of(first(element.date))
    if date:
        event.has_date = mapped_date(
            date, profile, record_id, "publicationEvent/date"
        )
    for attribute in ("place", "regional_scope"):
        for value in getattr(element, attribute, None) or []:
            name = text_of(value)
            if name:
                event.located_in.append(efi.GeographicName(has_name=name))
    publishers = [
        name
        for name in (text_of(value) for value in element.publisher or [])
        if name
    ]
    if publishers:
        event.has_activity.append(
            efi.ManifestationActivity(
                type=efi.ManifestationActivityTypeEnum(
                    profile.publisher_activity_type
                ),
                has_agent=[
                    efi.Agent(
                        type=efi.AgentTypeEnum("CorporateBody"),
                        has_name=name,
                    )
                    for name in publishers
                ],
            )
        )
    report_unmapped(
        element,
        (
            ("name", "publicationEvent/name"),
            ("exhibition_organiser", "publicationEvent/exhibitionOrganiser"),
            ("access_conditions", "publicationEvent/accessConditions"),
            ("note", "publicationEvent/note"),
            ("record_source", "publicationEvent/recordSource"),
            ("rel_person", "publicationEvent/relPerson"),
            ("rel_corporate", "publicationEvent/relCorporate"),
            ("rel_group", "publicationEvent/relGroup"),
        ),
        record_id,
    )
    return event


def resolve_related_event(
    related, expected_kind: str, context: MappingContext, record_id, source
):
    """Return the event entity a relation refers to, if there is one."""
    identifier = getattr(related, "identifier", None)
    value = text_of(identifier)
    scheme = getattr(identifier, "scheme", None) if identifier else None
    found = None
    if value:
        if scheme:
            found = context.events.get(f"{scheme}|{value}")
        if found is None:
            found = context.events.get(value)
    if found is None:
        report_issue(
            "warning",
            "Referenced event is not part of this document; the"
            " relation is not converted",
            record_id=record_id,
            source_field=source,
            target_field="has_event",
            raw_value=value or describe_value(related),
        )
        return None
    kind, element = found
    if kind != expected_kind:
        report_issue(
            "warning",
            f"Reference resolves to a {kind} rather than to a"
            f" {expected_kind}; not converted",
            record_id=record_id,
            source_field=source,
            target_field="has_event",
            raw_value=value,
        )
        return None
    return element


def collect_directing_activities(
    element, profile: EfgProfile, record_id, path: str
) -> list:
    """Return the DirectingActivities the relations of an element state."""
    by_type = {}
    identifiers = []
    for attribute, name, agent_type in (
        ("rel_person", "relPerson", "Person"),
        ("rel_corporate", "relCorporate", "CorporateBody"),
    ):
        for related in getattr(element, attribute, None) or []:
            source_field = f"{path}/{name}"
            agent_name = text_of(getattr(related, "name", None))
            role = text_of(getattr(related, "type_value", None)) or ""
            if not agent_name:
                report_issue(
                    "warning",
                    "Related agent without a name; not transferred",
                    record_id=record_id,
                    source_field=source_field,
                    target_field="has_event.has_activity",
                    raw_value=role or None,
                )
                continue
            if agent_name.lower() in profile.unknown_agent_names:
                report_issue(
                    "info",
                    "Placeholder agent name skipped",
                    record_id=record_id,
                    source_field=source_field,
                    target_field="has_event.has_activity",
                    raw_value=agent_name,
                )
                continue
            activity_type = profile.directing_role_map.get(
                role.strip().lower()
            )
            if activity_type is None:
                report_issue(
                    "warning",
                    "No AVefi activity mapped for this role; the agent"
                    " is not transferred",
                    record_id=record_id,
                    source_field=f"{source_field}/type",
                    target_field="has_event.has_activity",
                    raw_value=role or agent_name,
                )
                continue
            by_type.setdefault(activity_type, []).append(
                efi.Agent(
                    type=efi.AgentTypeEnum(agent_type), has_name=agent_name
                )
            )
            value = text_of(getattr(related, "identifier", None))
            if value:
                identifiers.append(value)
    if identifiers:
        report_issue(
            "info",
            "AVefi holds an agent by name; the identifier the source"
            " gives for it is not transferred",
            record_id=record_id,
            source_field=f"{path}/relPerson/identifier",
            target_field="has_event.has_activity.has_agent",
            raw_value=identifiers,
        )
    return [
        efi.DirectingActivity(
            type=efi.DirectingActivityTypeEnum(activity_type),
            has_agent=agents,
        )
        for activity_type, agents in sorted(by_type.items())
    ]


def mapped_date(
    value: str,
    profile: EfgProfile,
    record_id,
    source_field: str,
    target_field: str = "has_event.has_date",
) -> str | None:
    """Return ``value`` as an ISODate, reporting a failure first."""
    try:
        return normalise_date(
            value,
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )
        raise


# --- the technical description of a copy -------------------------------


@dataclass(frozen=True)
class CopyDescription:
    """What an avManifestation says about the copies it describes.

    EFG states running time, language, colour, sound, carrier and
    dimension on the manifestation, AVefi on the item. The values are
    therefore read once per manifestation, reported once when they
    cannot be mapped, and then applied to every item of it.

    """

    duration: str | None = None
    frame_rate: str | None = None
    colour_type: str | None = None
    sound_type: str | None = None
    formats: tuple = ()
    languages: tuple = ()
    extent: tuple | None = None

    def apply(self, item):
        """Write the description to ``item``."""
        if self.duration:
            item.has_duration = efi.Duration(has_value=self.duration)
        if self.frame_rate:
            item.has_frame_rate = efi.FrameRateEnum(self.frame_rate)
        if self.colour_type:
            item.has_colour_type = efi.ColourTypeEnum(self.colour_type)
        if self.sound_type:
            item.has_sound_type = efi.SoundTypeEnum(self.sound_type)
        for class_name, type_value in self.formats:
            format_class = getattr(efi, class_name)
            item.has_format.append(
                format_class()
                if type_value is None
                else format_class(type=type_value)
            )
        for code, usages in self.languages:
            item.in_language.append(
                efi.Language(
                    code=efi.LanguageCodeEnum(code),
                    usage=[efi.LanguageUsageEnum(usage) for usage in usages],
                )
            )
        if self.extent is not None:
            unit, value = self.extent
            item.has_extent = efi.Extent(
                has_unit=efi.UnitEnum(unit), has_value=value
            )


def describe_copy(element, profile: EfgProfile, record_id) -> CopyDescription:
    """Return what an avManifestation says about its copies."""
    duration_element = first(element.duration)
    duration = None
    frame_rate = None
    if duration_element is not None:
        value = text_of(duration_element)
        if value:
            # EFG states a duration in free text, so one that cannot
            # be read is to be expected. It costs the field, not the
            # work with every manifestation and item under it.
            duration = mapped_duration(
                value,
                record_id=record_id,
                source_field="avManifestation/duration",
                target_field="has_duration.has_value",
            )
        frame_rate = map_frame_rate(
            getattr(duration_element, "frame_rate", None), profile, record_id
        )
    if len(element.duration or []) > 1:
        report_issue(
            "warning",
            "AVefi holds one running time per item; only the first"
            " duration is mapped",
            record_id=record_id,
            source_field="avManifestation/duration",
            target_field="has_duration.has_value",
            raw_value=describe_value(element.duration),
        )

    languages = []
    for language in element.language or []:
        mapped = map_language(language, profile, record_id)
        if mapped is not None and mapped not in languages:
            languages.append(mapped)

    colour_type = None
    sound_type = None
    formats = ()
    format_element = first(element.format)
    if format_element is not None:
        colour_type = map_colour(format_element.colour, profile, record_id)
        sound_type = map_sound(format_element.sound, profile, record_id)
        formats = map_formats(format_element, profile, record_id)
        if format_element.aspect_ratio:
            report_issue(
                "info",
                "AVefi has no field for the aspect ratio",
                record_id=record_id,
                source_field="avManifestation/format/aspectRatio",
                target_field="—",
                raw_value=text_of(format_element.aspect_ratio),
            )
    if len(element.format or []) > 1:
        report_issue(
            "warning",
            "Only the first format element is mapped",
            record_id=record_id,
            source_field="avManifestation/format",
            target_field="has_format",
            raw_value=len(element.format),
        )

    return CopyDescription(
        duration=duration,
        frame_rate=frame_rate,
        colour_type=colour_type,
        sound_type=sound_type,
        formats=formats,
        languages=tuple(languages),
        extent=map_extent(element, profile, record_id),
    )


def map_frame_rate(value, profile: EfgProfile, record_id) -> str | None:
    """Return the AVefi frame rate for a frameRate attribute."""
    text = text_of(value)
    if not text:
        return None
    mapped = profile.frame_rate_map.get(text.strip().lower())
    if mapped is None:
        report_issue(
            "warning",
            "No AVefi frame rate configured for this value",
            record_id=record_id,
            source_field="avManifestation/duration/@frameRate",
            target_field="has_frame_rate",
            raw_value=text,
        )
    return mapped


def map_language(element, profile: EfgProfile, record_id):
    """Return code and usage of a language element, if mappable."""
    value = text_of(element)
    if not value:
        return None
    code = language_code(value)
    if code is None:
        candidate = value.strip().lower()
        if candidate in {member.value for member in efi.LanguageCodeEnum}:
            code = candidate
            report_issue(
                "info",
                "Language tag passed through as an ISO 639-2/B code;"
                " core.normalise does not know this tag",
                record_id=record_id,
                source_field="avManifestation/language",
                target_field="in_language.code",
                raw_value=value,
            )
    if code is None:
        report_issue(
            "warning",
            "Language tag is neither known to core.normalise nor a"
            " valid ISO 639-2/B code; language not transferred",
            record_id=record_id,
            source_field="avManifestation/language",
            target_field="in_language.code",
            raw_value=value,
        )
        return None
    usages = []
    usage = getattr(element, "usage", None)
    if usage:
        mapped = profile.language_usage_map.get(str(usage).strip().lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi language usage configured for this value; the"
                " language is kept without a usage",
                record_id=record_id,
                source_field="avManifestation/language/@usage",
                target_field="in_language.usage",
                raw_value=usage,
            )
        else:
            usages.append(mapped)
    return (code, tuple(usages))


def map_colour(element, profile: EfgProfile, record_id) -> str | None:
    """Return the AVefi colour type of a format/colour element."""
    if element is None:
        return None
    value = text_of(element)
    if value:
        mapped = profile.colour_type_map.get(value.strip().lower())
        if mapped is not None:
            return mapped
        report_issue(
            "warning",
            "No AVefi colour type configured for this term",
            record_id=record_id,
            source_field="avManifestation/format/colour",
            target_field="has_colour_type",
            raw_value=value,
        )
    has_color = getattr(element, "has_color", None)
    if has_color is None:
        return None
    mapped = "Colour" if has_color else "BlackAndWhite"
    report_issue(
        "info",
        "Colour type derived from the hasColor attribute, the element"
        " carrying no term that maps",
        record_id=record_id,
        source_field="avManifestation/format/colour/@hasColor",
        target_field="has_colour_type",
        raw_value=has_color,
    )
    return mapped


def map_sound(element, profile: EfgProfile, record_id) -> str | None:
    """Return the AVefi sound type of a format/sound element."""
    if element is None:
        return None
    if getattr(element, "recording", False):
        report_issue(
            "info",
            "AVefi has no field for the recording flag",
            record_id=record_id,
            source_field="avManifestation/format/sound/@recording",
            target_field="—",
            raw_value=element.recording,
        )
    value = text_of(element)
    if value:
        mapped = profile.sound_type_map.get(value.strip().lower())
        if mapped is not None:
            return mapped
        report_issue(
            "warning",
            "No AVefi sound type configured for this term",
            record_id=record_id,
            source_field="avManifestation/format/sound",
            target_field="has_sound_type",
            raw_value=value,
        )
    has_sound = getattr(element, "has_sound", None)
    if has_sound is None:
        return None
    mapped = "Sound" if has_sound else "Silent"
    report_issue(
        "info",
        "Sound type derived from the hasSound attribute, the element"
        " carrying no term that maps",
        record_id=record_id,
        source_field="avManifestation/format/sound/@hasSound",
        target_field="has_sound_type",
        raw_value=has_sound,
    )
    return mapped


def map_formats(element, profile: EfgProfile, record_id) -> tuple:
    """Return the AVefi formats a format element states."""
    formats = []
    for attribute, name in (("gauge", "gauge"), ("carrier", "carrier")):
        value = text_of(getattr(element, attribute, None))
        if not value:
            continue
        key = value.strip().lower()
        for map_name, class_name in (
            ("film_format_map", "Film"),
            ("video_format_map", "Video"),
            ("optical_format_map", "Optical"),
        ):
            mapped = getattr(profile, map_name).get(key)
            if mapped is not None:
                formats.append((class_name, mapped))
                break
        else:
            class_name = profile.carrier_class_map.get(key)
            if class_name is None:
                report_issue(
                    "warning",
                    "No AVefi format configured for this carrier term",
                    record_id=record_id,
                    source_field=f"avManifestation/format/{name}",
                    target_field="has_format",
                    raw_value=value,
                )
            else:
                formats.append((class_name, None))
    digital = getattr(element, "digital", None)
    if digital is not None:
        formats.extend(map_digital_format(digital, profile, record_id))
    typed = {class_name for class_name, type_value in formats if type_value}
    formats = [
        entry
        for entry in formats
        if entry[1] is not None or entry[0] not in typed
    ]
    return tuple(dict.fromkeys(formats))


def map_digital_format(element, profile: EfgProfile, record_id) -> list:
    """Return the AVefi formats a format/digital element states."""
    formats = []
    for attribute, name, map_name, class_name in (
        (
            "container",
            "container",
            "digital_file_format_map",
            "DigitalFile",
        ),
        (
            "coding",
            "coding",
            "digital_encoding_map",
            "DigitalFileEncoding",
        ),
    ):
        value = text_of(getattr(element, attribute, None))
        if not value:
            continue
        mapped = getattr(profile, map_name).get(value.strip().lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi format configured for this digital format term",
                record_id=record_id,
                source_field=f"avManifestation/format/digital/{name}",
                target_field="has_format",
                raw_value=value,
            )
            continue
        formats.append((class_name, mapped))
    status = text_of(getattr(element, "originalstatus", None))
    if status:
        report_issue(
            "info",
            "AVefi has no field for the original status of a digital file",
            record_id=record_id,
            source_field="avManifestation/format/digital/originalstatus",
            target_field="—",
            raw_value=status,
        )
    return formats


def map_extent(element, profile: EfgProfile, record_id):
    """Return unit and value of the first dimension element."""
    dimension = first(element.dimension)
    if dimension is None:
        return None
    if len(element.dimension or []) > 1:
        report_issue(
            "warning",
            "AVefi holds one extent per item; only the first dimension"
            " is mapped",
            record_id=record_id,
            source_field="avManifestation/dimension",
            target_field="has_extent",
            raw_value=describe_value(element.dimension),
        )
    value = text_of(dimension)
    unit = getattr(dimension, "unit", None)
    reference = getattr(dimension, "reference", None)
    if reference:
        report_issue(
            "info",
            "AVefi has no field for the reference of a dimension",
            record_id=record_id,
            source_field="avManifestation/dimension/@reference",
            target_field="—",
            raw_value=reference,
        )
    if not value:
        return None
    mapped_unit = profile.extent_unit_map.get(str(unit or "").strip().lower())
    if mapped_unit is None:
        report_issue(
            "warning",
            "No AVefi unit configured for this dimension; the extent is"
            " not transferred",
            record_id=record_id,
            source_field="avManifestation/dimension/@unit",
            target_field="has_extent.has_unit",
            raw_value=unit,
        )
        return None
    try:
        number = decimal.Decimal(value.replace(",", ".").strip())
    except decimal.InvalidOperation:
        report_issue(
            "warning",
            "Dimension is not a number; the extent is not transferred",
            record_id=record_id,
            source_field="avManifestation/dimension",
            target_field="has_extent.has_value",
            raw_value=value,
        )
        return None
    return (mapped_unit, number)


def add_event(record, event):
    """Add an event to a record unless it says nothing new.

    A data provider may repeat a film in several entities, each of them
    stating the production year again while only one of them names the
    director. Appending every event would leave the work with a bare
    date event next to the full one, so an event whose statements a
    known event already makes is dropped.

    """
    for known in record.has_event:
        if type(known) is not type(event):
            continue
        if event.has_date and known.has_date != event.has_date:
            continue
        if getattr(event, "type", None) != getattr(known, "type", None):
            continue
        if any(place not in known.located_in for place in event.located_in):
            continue
        if any(
            activity not in known.has_activity
            for activity in event.has_activity
        ):
            continue
        return
    record.has_event.append(event)
