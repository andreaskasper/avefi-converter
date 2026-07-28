"""Generic mapping from EBUCore to the AVefi schema.

EBUCore (EBU Tech 3293) is a standard, so the traversal of a document
is the same for every data provider. Everything that differs between
providers — the issuer information and the controlled vocabularies
behind the ``typeLabel`` attributes — is supplied through an
:class:`~efi_conv.ebucore.profile.EbucoreProfile`.

EBUCore is a broadcast schema. It describes one editorial object plus
the formats it exists in, not the work / manifestation / item
hierarchy AVefi is built on, and a large part of it is concerned with
transmission and essence technicalities that AVefi has no home for.
How the two are bridged is stated in :data:`ASSUMPTIONS` and in the
README, and everything left behind is reported rather than dropped.

"""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from dataclasses import fields as dataclass_fields
from decimal import Decimal, InvalidOperation
import logging

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
    merge_alternative_titles,
    work_key,
)
from ..core.report import for_file, report_issue, report_record_skipped
from ..core.xmlrecords import first, parse_records, text_of
from .generated.ebucore_1_10 import EbuCoreMain
from .profile import EbucoreProfile

log = logging.getLogger(__name__)

#: Namespace and element name of an EBUCore record. A document may
#: hold a single ebuCoreMain element or any number of them under a
#: wrapper element of the provider's choosing.
EBUCORE_NAMESPACE = "urn:ebu:metadata-schema:ebucore"
RECORD_ELEMENT = "ebuCoreMain"

#: AVefi carrier format classes, keyed by the name a profile uses in
#: its medium_format_map.
FORMAT_CLASSES = {
    "Audio": (efi.Audio, efi.FormatAudioTypeEnum),
    "DigitalFile": (efi.DigitalFile, efi.FormatDigitalFileTypeEnum),
    "Film": (efi.Film, efi.FormatFilmTypeEnum),
    "Optical": (efi.Optical, efi.FormatOpticalTypeEnum),
    "Video": (efi.Video, efi.FormatVideoTypeEnum),
}

#: ISO 639-2/B codes the AVefi schema accepts.
LANGUAGE_CODES = frozenset(code.value for code in efi.LanguageCodeEnum)

#: coreMetadata elements the mapping consumes.
MAPPED_CORE_ELEMENTS = frozenset(
    {
        "alternative_title",
        "contributor",
        "coverage",
        "creator",
        "date",
        "description",
        "format",
        "identifier",
        "is_part_of",
        "language",
        "publication_history",
        "subject",
        "title",
        "type_value",
    }
)

#: format elements the mapping consumes.
MAPPED_FORMAT_ELEMENTS = frozenset(
    {
        "audio_format",
        "container_format",
        "duration",
        "file_size",
        "medium",
        "technical_attribute_string",
        "video_format",
    }
)

#: Factors from a size in bytes to the byte based units AVefi knows,
#: largest first. EBUCore states a file size in the unit of its @unit
#: attribute, which is usually the byte; AVefi has no byte unit, so a
#: size in bytes is scaled to the largest unit it fills.
BYTE_UNITS = (
    ("TeraByte", Decimal(10) ** 12),
    ("GigaByte", Decimal(10) ** 9),
    ("MegaByte", Decimal(10) ** 6),
    ("KiloByte", Decimal(10) ** 3),
)

#: videoFormat and audioFormat elements the mapping consumes.
MAPPED_VIDEO_ELEMENTS = frozenset({"frame_rate", "technical_attribute_string"})
MAPPED_AUDIO_ELEMENTS = frozenset({"technical_attribute_string"})


@dataclass(frozen=True)
class MappingRule:
    """One documented mapping from an EBUCore path to an AVefi field."""

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
        "issuer",
        "Work, Manifestation, Item",
        "profile issuer_info",
        "described_by.has_issuer_id, described_by.has_issuer_name",
        notes="Taken from the profile, not from"
        " ebuCoreMain/metadataProvider. The shipped default is a"
        " placeholder and is reported once per input file",
    ),
    MappingRule(
        "record_id",
        "Item",
        "ebucore:identifier[@typeLabel in profile terms]/dc:identifier,"
        " else the first identifier, else ebuCoreMain/@documentId",
        "has_identifier, described_by.has_source_key",
        "Profile record_identifier_type_labels",
        "has_identifier is a list, so the further identifiers of the"
        " record are kept on the item as well; the scheme each of"
        " them belongs to is reported, AVefi having a resource class"
        " for only a few of them",
    ),
    MappingRule(
        "work_grouping",
        "Work",
        "primary title, director, production date",
        "has_identifier (work)",
        "Profile work_key_fields",
        "Several EBUCore records describing the same programme share"
        " one WorkVariant; set work_key_fields to () for one work per"
        " record",
    ),
    MappingRule(
        "manifestation_grouping",
        "Manifestation",
        "work key plus colour type, carrier format and languages",
        "has_identifier (manifestation)",
        notes="Records agreeing on the carrier characteristics share"
        " a manifestation",
    ),
    MappingRule(
        "primary_title",
        "Work, Manifestation, Item",
        "ebucore:title[@typeLabel in profile terms]/dc:title",
        "has_primary_title.has_name, has_primary_title.has_ordering_name",
        "Article handling in both directions",
        "The first title is used when none carries a recognised"
        " typeLabel; bracketed titles become SuppliedDevisedTitle",
    ),
    MappingRule(
        "alternative_title",
        "Work",
        "ebucore:title (remaining), ebucore:alternativeTitle/dc:title",
        "has_alternative_title",
        "Article handling in both directions",
        "A typeLabel outside the profile vocabulary is reported and"
        " the title is still kept as an AVefi AlternativeTitle",
    ),
    MappingRule(
        "genre",
        "Work",
        "ebucore:type/ebucore:genre/@typeLabel,"
        " ebucore:type/ebucore:contentFormat/@typeLabel",
        "has_form, has_genre.has_name",
        "Profile work_form_map",
        "The term is kept verbatim as a genre, the element it comes"
        " from being the provider's genre statement; a term the"
        " profile knows additionally yields a WorkFormEnum value, as"
        " in the PBCore mapping",
    ),
    MappingRule(
        "subject",
        "Work",
        "ebucore:subject/dc:subject",
        "has_subject.has_name",
        notes="EBUCore subject is Dublin Core subject, so has_subject"
        " is the matching AVefi field rather than has_genre",
    ),
    MappingRule(
        "part_of",
        "Work",
        "ebucore:isPartOf/dc:relation",
        "is_part_of (LocalResource)",
        notes="Rewritten to the identifier of the work the related"
        " record yields, where the run converts that record;"
        " otherwise reported and not transferred, AVefi rejecting a"
        " local reference that resolves to no record of the same set",
    ),
    MappingRule(
        "production_date",
        "Work",
        "ebucore:date/ebucore:produced, ebucore:date/ebucore:created,"
        " ebucore:date[@typeLabel in profile terms]",
        "has_event.has_date (ProductionEvent)",
        "ISODate; @startYear and @endYear become an interval",
        "@date takes precedence over @year, which takes precedence"
        " over the dc:date text",
    ),
    MappingRule(
        "production_place",
        "Work",
        "ebucore:coverage/ebucore:spatial/ebucore:location/ebucore:name",
        "has_event.located_in.has_name (ProductionEvent)",
        notes="ebucore:coverage/ebucore:temporal and a bare dc:coverage"
        " describe the subject of the content, not its production,"
        " and are reported instead",
    ),
    MappingRule(
        "director",
        "Work",
        "ebucore:creator, ebucore:contributor"
        " [ebucore:role/@typeLabel in profile terms]",
        "has_event.has_activity (DirectingActivity)",
        "Profile director_role_labels",
        "Placeholder names such as 'unknown' are skipped and reported",
    ),
    MappingRule(
        "other_agent",
        "Work",
        "ebucore:creator, ebucore:contributor (remaining roles)",
        "—",
        notes="Reported as unmapped rather than dropped silently",
    ),
    MappingRule(
        "publication_event",
        "Manifestation",
        "ebucore:publicationHistory/ebucore:publicationEvent",
        "has_event (PublicationEvent)",
        "ISODate; profile publication_medium_event_type_map",
        "The default event type is BroadcastEvent, not ReleaseEvent,"
        " because EBUCore describes broadcast publication",
    ),
    MappingRule(
        "release_date",
        "Manifestation",
        "ebucore:date/ebucore:released, ebucore:date/ebucore:issued",
        "has_event (PublicationEvent, ReleaseEvent)",
        "ISODate",
    ),
    MappingRule(
        "duration",
        "Item",
        "ebucore:format/ebucore:duration"
        " (normalPlayTime, timecode, editUnitNumber or duration)",
        "has_duration.has_value",
        "ISODurationInHours",
        "A timecode contributes hours, minutes and seconds; the frame"
        " count is reported because ISODurationInHours cannot hold"
        " it. An editUnitNumber without an editRate is unconvertible",
    ),
    MappingRule(
        "medium",
        "Item",
        "ebucore:format/ebucore:medium/@typeLabel",
        "has_format (Film, Video, Optical, Audio)",
        "Profile medium_format_map",
    ),
    MappingRule(
        "container_format",
        "Item",
        "ebucore:format/ebucore:containerFormat"
        " (@containerFormatName or ebucore:containerEncoding/@typeLabel)",
        "has_format (DigitalFile)",
        "Profile container_format_map",
    ),
    MappingRule(
        "colour_type",
        "Item",
        "ebucore:format//ebucore:technicalAttributeString"
        "[@typeLabel in profile terms]",
        "has_colour_type",
        "Profile colour_type_map",
        "EBUCore has no colour element; the technical attribute is"
        " the place providers use for it",
    ),
    MappingRule(
        "sound_type",
        "Item",
        "ebucore:format//ebucore:technicalAttributeString"
        "[@typeLabel in profile terms], else ebucore:audioFormat",
        "has_sound_type",
        "Profile sound_type_map",
        "The mere presence of an audioFormat yields Sound",
    ),
    MappingRule(
        "frame_rate",
        "Item",
        "ebucore:format/ebucore:videoFormat/ebucore:frameRate",
        "has_frame_rate",
        "Profile frame_rate_map",
    ),
    MappingRule(
        "language",
        "Item",
        "ebucore:language/dc:language with @typeLabel",
        "in_language.code, in_language.usage",
        "ISO 639-2/B; profile language_usage_map",
        "A code the AVefi schema does not know is reported and the"
        " language is not transferred",
    ),
    MappingRule(
        "extent",
        "Item",
        "ebucore:format/ebucore:fileSize",
        "has_extent.has_value, has_extent.has_unit",
        "Profile extent_unit_map",
        "A size in bytes is scaled to the largest byte based unit"
        " AVefi knows that it fills, the schema having no unit for"
        " the byte itself",
    ),
    MappingRule(
        "description",
        "—",
        "ebucore:description/dc:description",
        "—",
        notes="A synopsis describes the film, not the copy, and AVefi"
        " has no description field at any level; reported per value,"
        " as in the PBCore, Dublin Core and EN 15907 mappings",
    ),
    MappingRule(
        "rights",
        "—",
        "ebucore:rights",
        "—",
        notes="AVefi records no rights statement; reported in full",
    ),
    MappingRule(
        "part",
        "—",
        "ebucore:part",
        "—",
        notes="AVefi has no record type for an editorial segment;"
        " reported with the number of parts",
    ),
    MappingRule(
        "technical_detail",
        "—",
        "ebucore:format (remaining), ebucore:videoFormat and"
        " ebucore:audioFormat (remaining)",
        "—",
        notes="Codecs, bit rates, raster and sampling parameters have"
        " no AVefi equivalent; reported per record",
    ),
    MappingRule(
        "out_of_scope",
        "—",
        "ebucore:coreMetadata (remaining elements)",
        "—",
        notes="Relations, versions, planning, ratings, artefacts,"
        " emotions and the other broadcast production elements are"
        " reported per record",
    ),
)

MAPPING_RULES_BY_ID = {rule.id: rule for rule in MAPPING_RULES}


#: Decisions the mapping takes that EBUCore does not determine. They
#: are listed in the generated documentation so that a reviewer sees
#: them without reading the code.
ASSUMPTIONS = (
    "EBUCore describes one editorial object plus the formats it"
    " exists in. AVefi wants a work, a manifestation and an item. The"
    " bridge is: the editorial content of coreMetadata (titles,"
    " creators, subjects, genre, production date and place) becomes"
    " the WorkVariant, the publication history becomes the"
    " Manifestation, and the carrier described by ebucore:format"
    " becomes the Item. One EBUCore record therefore always yields"
    " exactly one item.",
    "Large parts of EBUCore are out of scope. Everything about"
    " transmission, essence technicalities, rights, planning,"
    " audience ratings, artefacts, animals, props, costumes, food,"
    " emotions, actions and text lines has no AVefi equivalent. Such"
    " elements are reported per record rather than mapped, and the"
    " conversion report is the honest account of what the AVefi"
    " records do not carry.",
    "The issuer is the holding institution and does not follow from"
    " the format. The shipped profile carries a documented"
    " placeholder, and the converter reports once per input file that"
    " it has to be replaced with the ISIL of the institution before"
    " the records are used.",
    "Works and manifestations are shared between records according to"
    " the profile key, so several EBUCore records describing the same"
    " programme on different carriers do not produce several works.",
    "WorkVariant.type is always Monographic. EBUCore states series"
    " and episode membership through relation elements, and isPartOf"
    " becomes is_part_of, but neither says at which level the related"
    " record sits, so the type of the work is not derived from it.",
    "EBUCore has no element for the colour or the sound system. Both"
    " are read from a technicalAttributeString whose typeLabel the"
    " profile names, which is where providers put them.",
    "A publication event without a recognised medium is typed as"
    " BroadcastEvent. EBUCore is a broadcast schema, so broadcast is"
    " the likelier reading than a theatrical release.",
    "ebucore:subject is mapped to has_subject rather than to"
    " has_genre. It is the Dublin Core subject element, and AVefi has"
    " a matching field for it.",
    "A genre term is kept verbatim in has_genre, and additionally"
    " yields a has_form value where the profile knows it as an AVefi"
    " work form. The element states what the provider calls the genre"
    " of the film, and the mapping onto the AVefi work forms is a"
    " reading of that term rather than a replacement for it. The"
    " PBCore mapping answers the same question the same way.",
    "An ebucore:description is a synopsis of the content. AVefi has"
    " no description field at any level, and an item note describes"
    " the copy rather than the film, so the value is reported instead"
    " of being written to a note.",
    "A record commonly carries several identifiers, an ISAN or a"
    " house number beside the one it is known by. AVefi has a"
    " resource class for a few identifier schemes only, none of which"
    " EBUCore names, so the further identifiers are kept as local"
    " identifiers of the item and the scheme of each is reported.",
    "An ebucore:isPartOf identifier names a record in the source"
    " system. It becomes is_part_of where the run converts that"
    " record too, and is reported rather than transferred where it"
    " does not: AVefi rejects a local reference that resolves to no"
    " record of the same set, and a converter emitting one would have"
    " the whole work discarded by the checks.",
    "EBUCore states the size of a file, AVefi an extent with a unit"
    " from a fixed list that has no byte in it. A size in bytes is"
    " therefore scaled to the largest of KiloByte, MegaByte, GigaByte"
    " and TeraByte that it fills, using decimal factors.",
    "A timecode duration contributes hours, minutes and seconds. The"
    " frame count is reported, because ISODurationInHours cannot"
    " express it.",
    "Decade expressions are reported as unconvertible unless"
    " map_decades is enabled, as in the other converters.",
    "The vocabularies in the profile follow the EBU classification"
    " schemes plus the English and German spellings met in practice."
    " They are provisional and are to be confirmed against the"
    " reference data of each provider.",
    "A work key that would be no more than the title does not group:"
    " the record keeps a work of its own, and the decision is reported."
    " Two undated films of the same name are two films, and one AVefi"
    " identifier registered for both cannot be corrected afterwards,"
    " whereas two works minted for one film can be merged.",
    "A running time that cannot be read leaves `has_duration` unset"
    " and is reported. Discarding the record over it would cost the"
    " work, every manifestation and every item derived from it.",
)


def render_mapping_markdown(rules=MAPPING_RULES) -> str:
    """Return the mapping table as a Markdown document."""
    lines = [
        "# EBUCore to AVefi mapping",
        "",
        "Generated from `MAPPING_RULES` in `efi_conv.ebucore.mapping`;",
        "do not edit by hand.",
        "",
        "| Rule | Level | EBUCore source | AVefi target |"
        " Normalisation | Notes |",
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
        "Decisions the mapping takes that EBUCore does not determine,"
        " and that need confirming against the reference data:",
        "",
    ]
    lines += [f"- {assumption}" for assumption in ASSUMPTIONS]
    return "\n".join(lines) + "\n"


def parse_ebucore(input_file):
    """Yield the ebuCoreMain records of a document.

    The document is streamed, so a harvest holding many records under
    a wrapper element costs no more memory than a single record.

    """
    return parse_records(
        input_file, EbuCoreMain, EBUCORE_NAMESPACE, RECORD_ELEMENT
    )


def efi_import(
    input_file,
    profile: EbucoreProfile,
    continue_on_error: bool = False,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Convert an EBUCore file into AVefi records using ``profile``.

    Parameters
    ----------
    input_file
        Path of the EBUCore document.
    profile : EbucoreProfile
        Provider specific configuration.
    continue_on_error : bool
        Report a record that cannot be converted and carry on with the
        remaining ones, instead of aborting the whole file. A single
        unmappable date in a large export would otherwise cost every
        record in it.
    context : MappingContext, optional
        Grouping context to add the records of this file to. One
        conversion of several files passes the same context to each of
        them, so that records describing one programme in different
        files share their work. Without it the file is converted on
        its own.

    """
    records = []
    if context is None:
        context = new_context(profile)
    with for_file(input_file):
        if profile.uses_placeholder_issuer():
            report_issue(
                "warning",
                "Records are issued by the documented placeholder"
                " issuer. Replace issuer_info with the ISIL and name"
                " of the holding institution before using them",
                source_field="profile issuer_info",
                target_field="described_by.has_issuer_id",
                raw_value=profile.issuer_info.get("has_issuer_id"),
            )
        for main in parse_ebucore(input_file):
            try:
                with context.attempt():
                    records.extend(map_record(main, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_record_skipped(
                    e, record_id=safe_record_identifier(main, profile)
                )
        resolve_relations(context)
    return records


def resolve_relations(context: "MappingContext"):
    """Point every is_part_of at the work of the record it names.

    An ebucore:isPartOf identifies a record in the source system, not
    an AVefi record. A reference the run can resolve is rewritten to
    the identifier of the work that record contributed to; one it
    cannot is reported and not asserted, because AVefi rejects a local
    reference resolving to no record of the same set. Unresolved
    references are kept aside, so that a file converted later can
    still supply the record they name.

    Called once per input file, since the records of one conversion
    reach the converter file by file.

    """
    minted = {work.has_identifier[0].id for work in context.works.values()}
    for work in context.works.values():
        work_id = work.has_identifier[0].id
        pending = context.unresolved_relations.pop(work_id, [])
        resolved = []
        for identifier in [
            resource.id for resource in work.is_part_of
        ] + pending:
            if identifier in minted:
                if identifier not in resolved:
                    resolved.append(identifier)
                continue
            target = context.work_ids.get(identifier)
            if target is not None:
                if target not in resolved:
                    resolved.append(target)
                continue
            context.unresolved_relations.setdefault(work_id, []).append(
                identifier
            )
            if identifier in context.reported_relations:
                continue
            context.reported_relations.add(identifier)
            report_issue(
                "warning",
                "The related record is not among the records converted"
                " so far, so the relation cannot name an AVefi work"
                " and is not transferred",
                record_id=(source_keys_of(work) or [None])[0],
                source_field="isPartOf/dc:relation",
                target_field="is_part_of",
                raw_value=identifier,
            )
        work.is_part_of = [
            efi.LocalResource(id=identifier) for identifier in resolved
        ]


def source_keys_of(record) -> list:
    """Return the source keys recorded for an AVefi record."""
    described_by = record.described_by
    if described_by is None:
        return []
    entries = (
        described_by if isinstance(described_by, list) else [described_by]
    )
    return [key for entry in entries for key in (entry.has_source_key or [])]


@dataclass
class MappingContext(GroupingContext):
    """State shared by all records of one conversion.

    Several EBUCore records commonly describe the same programme on
    different carriers. Minting a separate work for each of them would
    defeat the purpose of the AVefi identifiers, so works and
    manifestations are reused across the records of a run.

    Attributes
    ----------
    profile : EbucoreProfile or None
        Vocabularies and issuer information of the data provider.
    work_ids : dict
        Record identifier to the local identifier of the work that
        record contributed to, which is what turns an isPartOf
        relation into a reference to an AVefi work.
    reported_relations : set
        Relations already reported as unresolved, so that converting
        a further file does not report them again.
    unresolved_relations : dict
        Work identifier to the relation identifiers that could not be
        resolved yet, kept so that a file converted later can still
        supply the record they name.

    """

    profile: EbucoreProfile | None = None
    work_ids: dict = dataclass_field(default_factory=dict)
    reported_relations: set = dataclass_field(default_factory=set)
    unresolved_relations: dict = dataclass_field(default_factory=dict)


def new_context(profile: EbucoreProfile) -> MappingContext:
    """Return a grouping context for one conversion.

    Handed to :func:`efi_import` once per run rather than once per
    file, so that the works of a conversion are shared between the
    input files.

    """
    return MappingContext(profile=profile)


def map_record(
    main: EbuCoreMain,
    profile: EbucoreProfile,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one EBUCore record."""
    if context is None:
        context = MappingContext(profile=profile)
    core = main.core_metadata
    if core is None:
        raise ValueError("ebuCoreMain without coreMetadata")
    source_key, other_identifiers = collect_identifiers(main, profile)

    titles = collect_titles(main, profile, source_key)
    if not titles:
        raise ValueError(f"EBUCore record {source_key} has no usable title")
    primary, alternatives = titles[0], titles[1:]

    production = build_production_event(core, profile, source_key)
    publications = build_publication_events(core, profile, source_key)

    new_records = []
    work_key = make_work_key(profile, source_key, primary, production)

    def new_work():
        work = build_work(core, primary, alternatives, profile, source_key)
        if production is not None:
            work.has_event.append(production)
        return work

    work, is_new = context.work_for(work_key, new_work)
    if is_new:
        new_records.append(work)
    else:
        merge_alternative_titles(work, alternatives)
    work_id = work.has_identifier[0]
    context.work_ids.setdefault(source_key, work_id.id)

    item = build_item(core, primary, profile, source_key)
    manifestation_key = make_manifestation_key(work_key, item)

    def new_manifestation():
        manifestation = efi.Manifestation(
            is_manifestation_of=[work_id],
            has_primary_title=as_title(primary, "TitleProper"),
        )
        manifestation.has_event.extend(publications)
        return manifestation

    manifestation, is_new = context.manifestation_for(
        manifestation_key, new_manifestation
    )
    if is_new:
        new_records.append(manifestation)
    item.is_item_of = manifestation.has_identifier[0]
    item.has_identifier.append(efi.LocalResource(id=source_key))
    for value in other_identifiers:
        item.has_identifier.append(efi.LocalResource(id=value))
    new_records.append(item)

    report_descriptions(core, source_key)
    report_out_of_scope(main, core, source_key)
    attach_source_key(
        (work, manifestation, item), profile.issuer_info, source_key
    )
    return new_records


# --- grouping ---------------------------------------------------------


def make_work_key(profile, source_key, primary, production) -> str:
    """Return the key identifying the work a record belongs to."""
    if not profile.work_key_fields:
        return source_key
    parts = {}
    for name in profile.work_key_fields:
        if name == "primary_title":
            parts[name] = primary.ordering or primary.display
        elif name == "director":
            parts[name] = director_names(production)
        elif name == "date":
            parts[name] = (
                production.has_date
                if production is not None and production.has_date
                else ""
            )
        else:
            raise ValueError(f"Unknown work key field: {name}")
    return work_key(parts, source_key, record_id=source_key)


def director_names(production) -> str:
    """Return the directors of an event as a stable string."""
    if production is None:
        return ""
    names = sorted(
        agent.has_name
        for activity in production.has_activity
        for agent in activity.has_agent
    )
    return ", ".join(names)


def make_manifestation_key(work_key: str, item) -> str:
    """Return the key identifying the manifestation of an item.

    Records that agree on the carrier characteristics describe the
    same version of the programme and share a manifestation.

    """
    parts = [
        work_key,
        str(item.has_colour_type or ""),
        ",".join(sorted(str(fmt.type) for fmt in item.has_format or [])),
        ",".join(
            sorted(
                f"{language.code}:{','.join(sorted(language.usage or []))}"
                for language in item.in_language or []
            )
        ),
    ]
    return make_key(*parts)


# --- identifiers ------------------------------------------------------


def record_identifier(main: EbuCoreMain, profile) -> str:
    """Return the local identifier of an EBUCore record."""
    return collect_identifiers(main, profile)[0]


def collect_identifiers(main: EbuCoreMain, profile) -> tuple[str, list[str]]:
    """Return the local identifier of a record and the further ones.

    Returns
    -------
    tuple
        The identifier the record is known by, and the values of the
        remaining identifier elements in document order.

    """
    identifiers = list((main.core_metadata.identifier if main else None) or [])
    chosen = None
    fallback = None
    for entry in identifiers:
        value = text_of(entry.identifier)
        if not value:
            continue
        if fallback is None:
            fallback = value
        label = (entry.type_label or "").strip().lower()
        if chosen is None and label in profile.record_identifier_type_labels:
            chosen = value
    result = chosen or fallback or text_of(main.document_id)
    if not result:
        raise ValueError("EBUCore record without an identifier")
    others = []
    for entry in identifiers:
        value = text_of(entry.identifier)
        if not value or value == result or value in others:
            continue
        others.append(value)
        report_issue(
            "info",
            "AVefi has no resource class for the scheme this"
            " identifier belongs to, so it is kept as a further local"
            " identifier of the item rather than as a typed link",
            record_id=result,
            source_field="identifier",
            target_field="has_identifier",
            raw_value={
                "identifier": value,
                "typeLabel": entry.type_label,
                "formatLabel": entry.format_label,
            },
        )
    return result, others


def safe_record_identifier(main, profile) -> str | None:
    """Return the record identifier, or None if there is none."""
    try:
        return record_identifier(main, profile)
    except (AttributeError, ValueError):
        return None


# --- titles -----------------------------------------------------------


def collect_titles(main, profile, source_key) -> list[SourceTitle]:
    """Return the titles of a record, the main one first."""
    core = main.core_metadata
    document_language = language_code(getattr(main, "lang", None))
    primary, others = [], []
    for entry in core.title or []:
        label = (entry.type_label or "").strip().lower()
        is_primary = not primary and (
            not label or label in profile.primary_title_type_labels
        )
        for parsed in parse_title_elements(
            entry.title, profile, document_language, source_key, is_primary
        ):
            (primary if is_primary else others).append(parsed)
            is_primary = False
    for entry in core.alternative_title or []:
        label = (entry.type_label or "").strip().lower()
        if label and label not in profile.alternative_title_type_labels:
            report_issue(
                "info",
                "Alternative title type is not in the profile"
                " vocabulary, title kept as AlternativeTitle",
                record_id=source_key,
                source_field="alternativeTitle/@typeLabel",
                target_field="has_alternative_title.type",
                raw_value=entry.type_label,
            )
        others.extend(
            parse_title_elements(
                entry.title, profile, document_language, source_key, False
            )
        )
    if not primary and others:
        primary, others = others[:1], others[1:]
    return primary + others


def parse_title_elements(
    elements, profile, document_language, source_key, is_primary
):
    """Yield the parsed titles of one EBUCore title element."""
    target_field = (
        "has_primary_title.has_ordering_name"
        if is_primary
        else "has_alternative_title.has_ordering_name"
    )
    for element in elements or []:
        raw = text_of(element)
        if not raw:
            continue
        supplied = raw.startswith("[") and raw.endswith("]")
        value = raw[1:-1].strip() if supplied else raw
        if not value:
            continue
        language = (
            language_code(getattr(element, "lang", None))
            or document_language
            or profile.default_language
        )
        display, ordering = normalise_title(
            value,
            language,
            record_id=source_key,
            target_field=target_field,
        )
        if ordering and ordering != display:
            report_issue(
                "info",
                "Derived ordering name from article position",
                record_id=source_key,
                source_field="title/dc:title",
                target_field=target_field,
                raw_value=raw,
            )
        yield SourceTitle(display, ordering, supplied)
        is_primary = False


# --- work -------------------------------------------------------------


def build_work(core, primary, alternatives, profile, source_key):
    """Return the WorkVariant for one EBUCore record."""
    work = efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=as_title(primary, "PreferredTitle"),
    )
    for title in alternatives:
        work.has_alternative_title.append(as_title(title, "AlternativeTitle"))
    for term in genre_terms(core):
        work.has_genre.append(efi.Genre(has_name=term))
        mapped = profile.work_form_map.get(term.lower())
        if mapped:
            form = efi.WorkFormEnum(mapped)
            if form not in work.has_form:
                work.has_form.append(form)
    for term in subject_terms(core):
        work.has_subject.append(efi.Subject(has_name=term))
    for resource in part_of_resources(core):
        work.is_part_of.append(resource)
    return work


def part_of_resources(core):
    """Yield the works an EBUCore record says it is a part of.

    The relation identifier names a record in the source system. It is
    transferred as it stands: EBUCore states no level for the record
    it points at, so the converter cannot tell whether that record is
    among the ones it is converting.

    """
    for entry in core.is_part_of or []:
        value = text_of(entry.relation) or text_of(entry.relation_identifier)
        if value:
            yield efi.LocalResource(id=value)


def genre_terms(core):
    """Yield the genre and content format terms of a record."""
    for entry in core.type_value or []:
        genres = list(entry.genre or []) + list(entry.content_format or [])
        for genre in genres:
            label = (genre.type_label or "").strip()
            if label:
                yield label
        for plain in entry.type_value or []:
            text = text_of(plain)
            if text:
                yield text


def subject_terms(core):
    """Yield the subject terms of a record."""
    for entry in core.subject or []:
        for subject in entry.subject or []:
            text = text_of(subject)
            if text:
                yield text


def build_production_event(core, profile, source_key):
    """Return the ProductionEvent described by a record."""
    event = efi.ProductionEvent()
    value = production_date_value(core, profile)
    try:
        has_date = normalise_date(
            value,
            record_id=source_key,
            source_field="date[production]",
            target_field="has_event.has_date",
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=source_key,
            source_field="date[production]",
            target_field="has_event.has_date",
            raw_value=value,
        )
        raise
    if has_date:
        event.has_date = has_date
    for name in production_places(core, source_key):
        event.located_in.append(efi.GeographicName(has_name=name))
    directors = collect_directors(core, profile, source_key)
    if directors:
        event.has_activity.append(
            efi.DirectingActivity(
                type=efi.DirectingActivityTypeEnum("Director"),
                has_agent=directors,
            )
        )
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def production_date_value(core, profile) -> str | None:
    """Return the date expression describing the production."""
    for entry in core.date or []:
        for group in (entry.produced, entry.created):
            value = date_group_value(group)
            if value:
                return value
        label = (entry.type_label or "").strip().lower()
        if label in profile.production_date_type_labels:
            value = date_group_value(entry) or text_of(first(entry.date))
            if value:
                return value
    return None


def date_group_value(group) -> str | None:
    """Return the date expression of an EBUCore date attribute group."""
    if group is None:
        return None
    single = getattr(group, "date", None)
    if single is not None and not isinstance(single, list):
        return str(single)
    year = getattr(group, "year", None)
    if year is not None:
        return str(year)
    start = getattr(group, "start_date", None) or getattr(
        group, "start_year", None
    )
    end = getattr(group, "end_date", None) or getattr(group, "end_year", None)
    if start is not None and end is not None:
        return f"{start}/{end}"
    if start is not None or end is not None:
        return str(start if start is not None else end)
    period = getattr(group, "period", None)
    if period:
        return str(period)
    return None


def production_places(core, source_key):
    """Yield the place names describing where a record was produced."""
    for entry in core.coverage or []:
        spatial = entry.spatial
        for location in getattr(spatial, "location", None) or []:
            for name in location.name or []:
                text = text_of(name)
                if text:
                    yield text
        unmapped = []
        if entry.temporal is not None:
            unmapped.append("temporal")
        if text_of(entry.coverage):
            unmapped.append("dc:coverage")
        if unmapped:
            report_issue(
                "info",
                "Coverage of the content is not the production place"
                " and is not transferred",
                record_id=source_key,
                source_field="coverage",
                target_field="—",
                raw_value=unmapped,
            )


def collect_directors(core, profile, source_key):
    """Return the directing agents of a record."""
    directors = []
    for source_field, entities in (
        ("creator", core.creator or []),
        ("contributor", core.contributor or []),
    ):
        for entity in entities:
            name = entity_name(entity)
            roles = [
                (role.type_label or "").strip()
                for role in entity.role or []
                if (role.type_label or "").strip()
            ]
            if not name:
                report_issue(
                    "warning",
                    "Entity without a usable name, not transferred",
                    record_id=source_key,
                    source_field=source_field,
                    target_field="has_event.has_activity",
                    raw_value=roles or None,
                )
                continue
            if name.lower() in profile.unknown_agent_names:
                report_issue(
                    "info",
                    "Placeholder agent name skipped",
                    record_id=source_key,
                    source_field=source_field,
                    target_field="has_event.has_activity",
                    raw_value=name,
                )
                continue
            if any(
                role.lower() in profile.director_role_labels for role in roles
            ):
                directors.append(
                    efi.Agent(type=agent_type(entity), has_name=name)
                )
            else:
                report_issue(
                    "warning",
                    "No AVefi activity mapped for this role, agent not"
                    " transferred",
                    record_id=source_key,
                    source_field=f"{source_field}/role/@typeLabel",
                    target_field="has_event.has_activity",
                    raw_value=roles or name,
                )
    return directors


def entity_name(entity) -> str | None:
    """Return the name of an EBUCore entity."""
    for contact in entity.contact_details or []:
        for name in contact.name or []:
            text = text_of(name)
            if text:
                return text
        given = text_of(contact.given_name)
        family = text_of(contact.family_name)
        if family:
            return f"{family}, {given}" if given else family
        if given:
            return given
    for organisation in entity.organisation_details or []:
        for name in organisation.organisation_name or []:
            text = text_of(name)
            if text:
                return text
    return None


def agent_type(entity):
    """Return the AVefi agent type of an EBUCore entity."""
    if entity.contact_details:
        return efi.AgentTypeEnum("Person")
    return efi.AgentTypeEnum("CorporateBody")


# --- manifestation ----------------------------------------------------


def build_publication_events(core, profile, source_key):
    """Return the PublicationEvents described by a record."""
    events = []
    for history in core.publication_history or []:
        for entry in history.publication_event or []:
            event = build_publication_event(entry, profile, source_key)
            if event is not None:
                events.append(event)
    release = release_date_value(core)
    if release:
        try:
            has_date = normalise_date(
                release,
                record_id=source_key,
                source_field="date[released]",
                target_field="has_event.has_date",
                map_decades=profile.map_decades,
            )
        except NormalisationError as e:
            report_issue(
                "error",
                str(e),
                record_id=source_key,
                source_field="date[released]",
                target_field="has_event.has_date",
                raw_value=release,
            )
            raise
        if has_date:
            events.append(
                efi.PublicationEvent(
                    type=efi.PublicationEventTypeEnum("ReleaseEvent"),
                    has_date=has_date,
                )
            )
    return events


def release_date_value(core) -> str | None:
    """Return the date expression describing the release."""
    for entry in core.date or []:
        for group in list(entry.released or []) + [entry.issued]:
            value = date_group_value(group)
            if value:
                return value
    return None


def build_publication_event(entry, profile, source_key):
    """Return the AVefi PublicationEvent for one EBUCore event."""
    event = efi.PublicationEvent(
        type=efi.PublicationEventTypeEnum(
            publication_event_type(entry, profile)
        )
    )
    value = (
        str(entry.publication_date)
        if entry.publication_date is not None
        else None
    )
    try:
        has_date = normalise_date(
            value,
            record_id=source_key,
            source_field="publicationEvent/@publicationDate",
            target_field="has_event.has_date",
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=source_key,
            source_field="publicationEvent/@publicationDate",
            target_field="has_event.has_date",
            raw_value=value,
        )
        raise
    if has_date:
        event.has_date = has_date
    if entry.publication_time is not None:
        report_issue(
            "info",
            "AVefi dates have no time component, publication time not"
            " transferred",
            record_id=source_key,
            source_field="publicationEvent/@publicationTime",
            target_field="has_event.has_date",
            raw_value=str(entry.publication_time),
        )
    for region in entry.publication_region or []:
        for name in region_names(region):
            event.located_in.append(efi.GeographicName(has_name=name))
    broadcaster = publication_agent(entry)
    if broadcaster:
        event.has_activity.append(
            efi.ManifestationActivity(
                type=efi.ManifestationActivityTypeEnum("Broadcaster"),
                has_agent=[
                    efi.Agent(
                        type=efi.AgentTypeEnum("CorporateBody"),
                        has_name=broadcaster,
                    )
                ],
            )
        )
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def publication_event_type(entry, profile) -> str:
    """Return the AVefi type of an EBUCore publication event."""
    medium = entry.publication_medium
    for candidate in (
        text_of(medium),
        getattr(medium, "type_label", None),
    ):
        if not candidate:
            continue
        mapped = profile.publication_medium_event_type_map.get(
            candidate.strip().lower()
        )
        if mapped:
            return mapped
    return profile.default_publication_event_type


def region_names(region):
    """Yield the names of an EBUCore region."""
    country = region.country
    text = text_of(country) or getattr(country, "type_label", None)
    if text:
        yield text
    for sub in region.country_region or []:
        text = text_of(sub) or getattr(sub, "type_label", None)
        if text:
            yield text


def publication_agent(entry) -> str | None:
    """Return the broadcaster of an EBUCore publication event."""
    service = entry.publication_service
    if service is not None:
        name = service.publication_service_name
        if name:
            return name.strip()
        source = service.publication_source
        for organisation in getattr(source, "organisation_name", None) or []:
            text = text_of(organisation)
            if text:
                return text
    channel = entry.publication_channel
    text = text_of(channel)
    if text:
        return text
    return None


# --- item -------------------------------------------------------------


def build_item(core, primary, profile, source_key):
    """Return the Item for one EBUCore record.

    ``is_item_of`` is filled in by the caller, once the manifestation
    this carrier belongs to is known.

    """
    item = efi.Item(
        is_item_of=efi.LocalResource(id="__pending__"),
        has_primary_title=as_title(primary, "TitleProper"),
    )
    formats = list(core.format or [])
    has_value = item_duration(formats, profile, source_key)
    if has_value:
        item.has_duration = efi.Duration(has_value=has_value)
    for carrier in carrier_formats(formats, profile, source_key):
        item.has_format.append(carrier)
    colour = technical_value(
        formats,
        profile.colour_attribute_labels,
        profile.colour_type_map,
        "has_colour_type",
        source_key,
    )
    if colour:
        item.has_colour_type = efi.ColourTypeEnum(colour)
    sound = technical_value(
        formats,
        profile.sound_attribute_labels,
        profile.sound_type_map,
        "has_sound_type",
        source_key,
    )
    if sound is None and any(fmt.audio_format for fmt in formats):
        sound = "Sound"
    if sound:
        item.has_sound_type = efi.SoundTypeEnum(sound)
    frame_rate = item_frame_rate(formats, profile, source_key)
    if frame_rate:
        item.has_frame_rate = efi.FrameRateEnum(frame_rate)
    for language in item_languages(core, profile, source_key):
        item.in_language.append(language)
    extent = item_extent(formats, profile, source_key)
    if extent is not None:
        item.has_extent = extent
    return item


def item_extent(formats, profile, source_key):
    """Return the extent of the carrier, if EBUCore states a size.

    EBUCore states the size of a file rather than the length of a
    reel, so this is the digital half of what AVefi calls an extent.
    A size in bytes is scaled to the largest byte based unit AVefi
    knows that it fills, because the schema has no unit for the byte
    itself.

    """
    for fmt in formats:
        for size in fmt.file_size or []:
            value = text_of(size)
            unit = str(getattr(size, "unit", "") or "").strip().lower()
            amount = decimal_or_none(value)
            if amount is None:
                report_issue(
                    "warning",
                    "File size is not a number, no AVefi extent derived",
                    record_id=source_key,
                    source_field="format/fileSize",
                    target_field="has_extent",
                    raw_value=f"{value} {unit}".strip(),
                )
                continue
            mapped = profile.extent_unit_map.get(unit)
            if mapped is not None:
                return efi.Extent(
                    has_unit=efi.UnitEnum(mapped), has_value=amount
                )
            if unit in profile.byte_unit_labels:
                return byte_extent(amount)
            report_issue(
                "warning",
                "No AVefi unit configured for this file size unit,"
                " value not transferred",
                record_id=source_key,
                source_field="format/fileSize/@unit",
                target_field="has_extent.has_unit",
                raw_value=unit or None,
            )
    return None


def byte_extent(amount: Decimal):
    """Return a size in bytes as the largest AVefi unit it fills."""
    for name, factor in BYTE_UNITS:
        if amount >= factor:
            return efi.Extent(
                has_unit=efi.UnitEnum(name),
                has_value=normalised_decimal(amount / factor),
            )
    return efi.Extent(
        has_unit=efi.UnitEnum("KiloByte"),
        has_value=normalised_decimal(amount / Decimal(10) ** 3),
    )


def decimal_or_none(value) -> Decimal | None:
    """Return the number a text carries, or None if it carries none."""
    if not value:
        return None
    try:
        return Decimal(str(value).replace(" ", "").replace(",", ""))
    except InvalidOperation:
        return None


def normalised_decimal(value: Decimal) -> Decimal:
    """Return a decimal without trailing zeros in its fraction."""
    quantised = value.quantize(Decimal("0.001"))
    return quantised.normalize() if quantised == value else value


def item_duration(formats, profile, source_key) -> str | None:
    """Return the running time of the carrier, if EBUCore states one."""
    for fmt in formats:
        for duration in fmt.duration or []:
            value, unit = duration_expression(duration, source_key)
            if value is None:
                continue
            has_value = mapped_duration(
                value,
                unit,
                record_id=source_key,
                source_field="format/duration",
                target_field="has_duration.has_value",
            )
            if has_value:
                return has_value
    return None


def duration_expression(duration, source_key):
    """Return value and unit of an EBUCore duration.

    EBUCore expresses a duration in four alternative ways. A normal
    play time and a free text duration are taken as they are, a
    timecode contributes hours, minutes and seconds, and a number of
    edit units is converted with the edit rate it carries.

    Raises
    ------
    NormalisationError
        When a number of edit units comes without an edit rate, which
        leaves the value without a scale.

    """
    if duration.normal_play_time is not None:
        seconds = xml_duration_seconds(duration.normal_play_time)
        return f"{seconds:.0f}", "s"
    if duration.timecode is not None:
        return timecode_expression(duration.timecode, source_key), None
    if duration.edit_unit_number is not None:
        return edit_unit_expression(duration.edit_unit_number), "s"
    if duration.duration is not None:
        return text_of(duration.duration), duration.duration.format_label
    return None, None


def xml_duration_seconds(value) -> float:
    """Return the number of seconds an xs:duration expresses."""
    if value.years or value.months:
        raise NormalisationError(
            f"Duration with years or months is not a running time: {value}"
        )
    seconds = (
        (value.days or 0) * 86400
        + (value.hours or 0) * 3600
        + (value.minutes or 0) * 60
        + (value.seconds or 0)
    )
    return -seconds if value.negative else seconds


def timecode_expression(timecode, source_key) -> str | None:
    """Return the hours, minutes and seconds of an EBUCore timecode."""
    text = text_of(timecode)
    if not text:
        return None
    parts = text.split(":")
    if len(parts) == 4:
        report_issue(
            "info",
            "ISODurationInHours has no frame component, the frame"
            " count of the timecode is not transferred",
            record_id=source_key,
            source_field="format/duration/timecode",
            target_field="has_duration.has_value",
            raw_value=text,
        )
        return ":".join(parts[:3])
    return text


def edit_unit_expression(edit_unit) -> str:
    """Return the number of seconds a number of edit units expresses."""
    rate = edit_unit.edit_rate
    numerator = edit_unit.factor_numerator or 1
    denominator = edit_unit.factor_denominator or 1
    if not rate or not numerator:
        raise NormalisationError(
            f"Edit unit number without a usable edit rate: {edit_unit.value}"
        )
    seconds = edit_unit.value * denominator / (rate * numerator)
    return f"{seconds:.0f}"


def carrier_formats(formats, profile, source_key):
    """Yield the AVefi carrier formats a record states."""
    seen = set()
    for fmt in formats:
        for medium in fmt.medium or []:
            label = (medium.type_label or "").strip()
            if not label:
                continue
            mapped = profile.medium_format_map.get(label.lower())
            if mapped is None:
                report_issue(
                    "warning",
                    "No AVefi format configured for this medium",
                    record_id=source_key,
                    source_field="format/medium/@typeLabel",
                    target_field="has_format",
                    raw_value=label,
                )
                continue
            class_name, value = mapped
            if (class_name, value) in seen:
                continue
            seen.add((class_name, value))
            format_class, enumeration = FORMAT_CLASSES[class_name]
            yield format_class(type=enumeration(value))
        for container in fmt.container_format or []:
            label = container_label(container)
            if not label:
                continue
            mapped = profile.container_format_map.get(label.lower())
            if mapped is None:
                report_issue(
                    "warning",
                    "No AVefi format configured for this container",
                    record_id=source_key,
                    source_field="format/containerFormat",
                    target_field="has_format",
                    raw_value=label,
                )
                continue
            if ("DigitalFile", mapped) in seen:
                continue
            seen.add(("DigitalFile", mapped))
            yield efi.DigitalFile(type=efi.FormatDigitalFileTypeEnum(mapped))


def container_label(container) -> str | None:
    """Return the name of an EBUCore container format."""
    if container.container_format_name:
        return container.container_format_name.strip()
    for encoding in container.container_encoding or []:
        label = (encoding.type_label or "").strip()
        if label:
            return label
    return None


def technical_attributes(formats):
    """Yield the technical string attributes of the format elements."""
    for fmt in formats:
        yield from fmt.technical_attribute_string or []
        for video in fmt.video_format or []:
            yield from video.technical_attribute_string or []
        for audio in fmt.audio_format or []:
            yield from audio.technical_attribute_string or []


def technical_value(
    formats, labels, vocabulary, target_field, source_key
) -> str | None:
    """Return the AVefi value of a typed technical attribute."""
    for attribute in technical_attributes(formats):
        label = (attribute.type_label or "").strip().lower()
        if label not in labels:
            continue
        text = text_of(attribute)
        if not text:
            continue
        mapped = vocabulary.get(text.lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi value configured for this technical attribute",
                record_id=source_key,
                source_field="format//technicalAttributeString",
                target_field=target_field,
                raw_value=text,
            )
            return None
        return mapped
    return None


def item_frame_rate(formats, profile, source_key) -> str | None:
    """Return the frame rate of the carrier, if EBUCore states one."""
    for fmt in formats:
        for video in fmt.video_format or []:
            value = frame_rate_expression(video.frame_rate)
            if not value:
                continue
            mapped = profile.frame_rate_map.get(value)
            if mapped is None:
                report_issue(
                    "warning",
                    "No AVefi frame rate configured for this value",
                    record_id=source_key,
                    source_field="format/videoFormat/frameRate",
                    target_field="has_frame_rate",
                    raw_value=value,
                )
                continue
            return mapped
    return None


def frame_rate_expression(frame_rate) -> str | None:
    """Return the frame rate an EBUCore rational element expresses.

    EBUCore states a non integer frame rate as a whole number plus a
    correction factor, so 23.98 fps arrives as 24 with the factor
    1000/1001.

    """
    if frame_rate is None:
        return None
    numerator = frame_rate.factor_numerator or 1
    denominator = frame_rate.factor_denominator or 1
    if not denominator:
        return None
    value = frame_rate.value * numerator / denominator
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return f"{value:.2f}"


def item_languages(core, profile, source_key):
    """Yield the languages of a record."""
    seen = set()
    for entry in core.language or []:
        tag = text_of(entry.language)
        if not tag:
            continue
        code = resolve_language(tag, source_key)
        if code is None:
            continue
        label = (entry.type_label or "").strip()
        usage = (
            profile.language_usage_map.get(label.lower()) if label else None
        )
        if usage is None:
            report_issue(
                "info" if not label else "warning",
                "No AVefi language usage configured for this purpose,"
                " falling back to the profile default",
                record_id=source_key,
                source_field="language/@typeLabel",
                target_field="in_language.usage",
                raw_value=label or None,
            )
            usage = profile.default_language_usage
        usages = [efi.LanguageUsageEnum(usage)] if usage else []
        key = (code, tuple(str(value) for value in usages))
        if key in seen:
            continue
        seen.add(key)
        yield efi.Language(code=efi.LanguageCodeEnum(code), usage=usages)


def resolve_language(tag, source_key) -> str | None:
    """Return the ISO 639-2/B code for an EBUCore language tag."""
    code = language_code(tag)
    if code:
        return code
    candidate = tag.strip().lower().split("-")[0]
    if candidate in LANGUAGE_CODES:
        return candidate
    report_issue(
        "warning",
        "Language code is not known to the AVefi schema, language not"
        " transferred",
        record_id=source_key,
        source_field="language/dc:language",
        target_field="in_language.code",
        raw_value=tag,
    )
    return None


def report_descriptions(core, source_key):
    """Report the descriptions AVefi has no field for.

    An ebucore:description is a synopsis of the content. AVefi has no
    description field at any level, and an item note describes the
    copy rather than the film, so the value is reported with the text
    it carries instead of being written somewhere it does not belong.
    The PBCore, Dublin Core and EN 15907 converters answer the same
    question the same way.

    """
    for entry in core.description or []:
        for description in entry.description or []:
            text = text_of(description)
            if not text:
                continue
            report_issue(
                "warning",
                "AVefi has no field for a description at any level,"
                " value not transferred",
                record_id=source_key,
                source_field="description/dc:description",
                target_field="—",
                raw_value=text,
            )


# --- reporting what is out of scope -----------------------------------


def report_out_of_scope(main, core, source_key):
    """Report the parts of a record the mapping does not transfer."""
    if main.metadata_provider is not None:
        report_issue(
            "info",
            "The issuer comes from the profile, metadataProvider is not used",
            record_id=source_key,
            source_field="ebuCoreMain/metadataProvider",
            target_field="described_by.has_issuer_id",
            raw_value=entity_name(main.metadata_provider),
        )
    if core.rights:
        report_issue(
            "warning",
            "AVefi records no rights statement, rights not transferred",
            record_id=source_key,
            source_field="rights",
            target_field="—",
            raw_value=[text_of(first(entry.rights)) for entry in core.rights],
        )
    if core.part:
        report_issue(
            "warning",
            "AVefi has no record type for an editorial segment, part"
            " not transferred",
            record_id=source_key,
            source_field="part",
            target_field="—",
            raw_value=len(core.part),
        )
    report_unmapped_elements(
        core,
        MAPPED_CORE_ELEMENTS | {"rights", "part"},
        source_key,
        "coreMetadata",
        "No AVefi field for this EBUCore element, not transferred",
    )
    for fmt in core.format or []:
        report_unmapped_elements(
            fmt,
            MAPPED_FORMAT_ELEMENTS,
            source_key,
            "format",
            "Technical detail without an AVefi equivalent, not transferred",
        )
        for video in fmt.video_format or []:
            report_unmapped_elements(
                video,
                MAPPED_VIDEO_ELEMENTS,
                source_key,
                "format/videoFormat",
                "Technical detail without an AVefi equivalent, not"
                " transferred",
            )
        for audio in fmt.audio_format or []:
            report_unmapped_elements(
                audio,
                MAPPED_AUDIO_ELEMENTS,
                source_key,
                "format/audioFormat",
                "Technical detail without an AVefi equivalent, not"
                " transferred",
            )


def report_unmapped_elements(obj, consumed, source_key, source_field, message):
    """Report the child elements of ``obj`` the mapping does not use."""
    present = []
    for entry in dataclass_fields(obj):
        if entry.name in consumed:
            continue
        if entry.metadata.get("type") != "Element":
            continue
        if not getattr(obj, entry.name, None):
            continue
        present.append(entry.metadata.get("name", entry.name))
    if present:
        report_issue(
            "info",
            message,
            record_id=source_key,
            source_field=source_field,
            target_field="—",
            raw_value=sorted(present),
        )
