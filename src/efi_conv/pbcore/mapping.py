"""Generic mapping from PBCore 2.1 to the AVefi schema.

PBCore is a standard, so the traversal of a description document is
the same for every data provider. Everything that differs — issuer
information and the vocabularies used inside the elements — is
supplied through a :class:`~efi_conv.pbcore.profile.PbcoreProfile`.

PBCore knows two levels, the asset and its instantiations, where AVefi
knows three. The asset becomes the WorkVariant, and every
instantiation becomes both a Manifestation and an Item, because a
PBCore instantiation conflates the version of a film with the single
copy of it that the archive holds. Instantiations agreeing on the
characteristics AVefi puts at the Manifestation level therefore share
one Manifestation, which is the only place where the missing middle
level can be recovered from the data.

"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
    merge_alternative_titles,
    slug,
    work_key,
)
from ..core.report import for_file, report_issue, report_record_skipped
from ..core.xmlrecords import first, parse_records, text_of
from .generated.pbcore_2_1 import PbcoreDescriptionDocument
from .generated.pbcore_2_1.pbcore_2_1 import __NAMESPACE__ as PBCORE_NAMESPACE
from .profile import PLACEHOLDER_ISSUER_ID, PbcoreProfile

log = logging.getLogger(__name__)

#: Local name of the element holding one PBCore record. A document may
#: carry one as its root or many inside pbcoreCollection.
RECORD_ELEMENT = "pbcoreDescriptionDocument"

#: AVefi format classes by the name used in the profile vocabularies.
FORMAT_CLASSES = {
    "Audio": efi.Audio,
    "DigitalFile": efi.DigitalFile,
    "Film": efi.Film,
    "Optical": efi.Optical,
    "Video": efi.Video,
}

#: Instantiation elements carrying technical detail for which the
#: AVefi schema has no field. They are reported rather than dropped.
UNMAPPED_INSTANTIATION_FIELDS = (
    ("instantiation_standard", "instantiationStandard"),
    ("instantiation_tracks", "instantiationTracks"),
    (
        "instantiation_channel_configuration",
        "instantiationChannelConfiguration",
    ),
    ("instantiation_alternative_modes", "instantiationAlternativeModes"),
    ("instantiation_time_start", "instantiationTimeStart"),
    ("instantiation_data_rate", "instantiationDataRate"),
    ("instantiation_relation", "instantiationRelation"),
    ("instantiation_part", "instantiationPart"),
    ("instantiation_extension", "instantiationExtension"),
)

#: Essence track elements without an AVefi equivalent.
UNMAPPED_TRACK_FIELDS = (
    ("essence_track_identifier", "essenceTrackIdentifier"),
    ("essence_track_standard", "essenceTrackStandard"),
    ("essence_track_encoding", "essenceTrackEncoding"),
    ("essence_track_data_rate", "essenceTrackDataRate"),
    ("essence_track_playback_speed", "essenceTrackPlaybackSpeed"),
    ("essence_track_sampling_rate", "essenceTrackSamplingRate"),
    ("essence_track_bit_depth", "essenceTrackBitDepth"),
    ("essence_track_frame_size", "essenceTrackFrameSize"),
    ("essence_track_aspect_ratio", "essenceTrackAspectRatio"),
    ("essence_track_time_start", "essenceTrackTimeStart"),
    ("essence_track_extension", "essenceTrackExtension"),
)

#: Asset elements without an AVefi equivalent.
UNMAPPED_ASSET_FIELDS = (
    ("pbcore_description", "pbcoreDescription"),
    ("pbcore_audience_level", "pbcoreAudienceLevel"),
    ("pbcore_audience_rating", "pbcoreAudienceRating"),
    ("pbcore_part", "pbcorePart"),
    ("pbcore_extension", "pbcoreExtension"),
)


@dataclass(frozen=True)
class MappingRule:
    """One documented mapping from a PBCore path to an AVefi field."""

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
        "level_bridge",
        "Work, Manifestation, Item",
        "pbcoreDescriptionDocument and pbcoreInstantiation",
        "WorkVariant, Manifestation, Item",
        notes="PBCore has two levels where AVefi has three. The asset"
        " becomes the work, every instantiation becomes an item, and"
        " instantiations agreeing on colour, format and language share"
        " a manifestation",
    ),
    MappingRule(
        "media_type_filter",
        "Record",
        "pbcoreInstantiation/instantiationMediaType",
        "—",
        "Profile vocabulary",
        "PBCore describes audio and text as well. An instantiation of"
        " another media type is skipped and reported; a record left"
        " without any instantiation by the filter is skipped as a"
        " whole",
    ),
    MappingRule(
        "work_grouping",
        "Work",
        "primary title, director, production date",
        "has_identifier (work)",
        "Profile work_key_fields",
        "Two assets describing the same film share one WorkVariant;"
        " set work_key_fields to () for one work per record",
    ),
    MappingRule(
        "manifestation_grouping",
        "Manifestation",
        "work key plus colour type, format and languages of the copy",
        "has_identifier (manifestation)",
        notes="The only reconstruction of the level PBCore lacks that"
        " the data supports",
    ),
    MappingRule(
        "record_id",
        "Item",
        "pbcoreIdentifier[@source in profile]",
        "has_identifier, described_by.has_source_key",
        "Profile authoritative_identifier_sources",
        "The first identifier whose source the profile names as"
        " authoritative, else the first identifier of the record",
    ),
    MappingRule(
        "other_identifier",
        "Item",
        "pbcoreIdentifier (remaining), instantiationIdentifier",
        "has_identifier (LocalResource), has_webresource",
        notes="An identifier that is a URL becomes a web resource;"
        " AVefi has no place for the @source qualifier, which is"
        " reported per identifier",
    ),
    MappingRule(
        "primary_title",
        "Work, Manifestation, Item",
        "pbcoreTitle[@titleType in profile primary_title_types]",
        "has_primary_title.has_name, has_primary_title.has_ordering_name",
        "Article handling in both directions",
        "The first title of the record is used when no titleType is"
        " eligible; bracketed titles become SuppliedDevisedTitle. On a"
        " work AVefi only allows a PreferredTitle, so a deviating"
        " titleType is reported",
    ),
    MappingRule(
        "alternative_title",
        "Work",
        "pbcoreTitle (remaining), @titleType",
        "has_alternative_title, has_alternative_title.type",
        "Profile title_type_map",
        "An unknown titleType is reported and the title kept as an"
        " AlternativeTitle rather than dropped",
    ),
    MappingRule(
        "asset_type",
        "Work",
        "pbcoreAssetType",
        "type (WorkVariantTypeEnum)",
        "Profile asset_type_map",
        "Collection and Series become Collection and Serial, Episode"
        " and Segment become Analytic",
    ),
    MappingRule(
        "production_date",
        "Work",
        "pbcoreAssetDate[@dateType in profile production_date_types]",
        "has_event.has_date (ProductionEvent)",
        "ISODate",
        "A date of another type is reported rather than forced into an"
        " event it does not describe",
    ),
    MappingRule(
        "production_place",
        "Work",
        "pbcoreCoverage[coverageType='Spatial']/coverage",
        "has_event.located_in.has_name",
        notes="Temporal coverage describes the content, not the"
        " production, and is reported as unmapped",
    ),
    MappingRule(
        "genre",
        "Work",
        "pbcoreGenre, pbcoreSubject[@subjectType in profile"
        " genre_subject_types]",
        "has_genre.has_name, has_form",
        "Profile work_form_map",
        "The term is kept verbatim as a genre; a term the profile"
        " knows additionally yields a WorkFormEnum value",
    ),
    MappingRule(
        "subject",
        "Work",
        "pbcoreSubject (remaining)",
        "has_subject.has_name (Subject)",
        notes="AVefi separates topical subject from genre, so a"
        " PBCore subject only becomes a genre when its subjectType"
        " says it is one",
    ),
    MappingRule(
        "director",
        "Work",
        "pbcoreCreator/creatorRole, pbcoreContributor/contributorRole"
        " [role in profile directing_role_map]",
        "has_event.has_activity (DirectingActivity)",
        "Profile directing_role_map",
        "A creator without a role becomes the profile's"
        " default_creator_activity with the agent type left unset;"
        " placeholder names are skipped and reported",
    ),
    MappingRule(
        "other_agent",
        "Work",
        "pbcoreCreator, pbcoreContributor (remaining roles)",
        "—",
        notes="Reported as unmapped rather than dropped silently;"
        " AVefi has activity classes for them, but PBCore role terms"
        " are free text and must not be guessed at",
    ),
    MappingRule(
        "relation",
        "Work",
        "pbcoreRelation[pbcoreRelationType in profile part_of_relation_types]",
        "is_part_of (LocalResource)",
        notes="Other relation types are reported",
    ),
    MappingRule(
        "publication",
        "Manifestation",
        "pbcoreAssetDate[@dateType in profile publication_date_types],"
        " pbcorePublisher/publisherRole",
        "has_event (PublicationEvent, ManifestationActivity)",
        "ISODate, profile publisher_role_map",
    ),
    MappingRule(
        "asset_rights",
        "Manifestation",
        "pbcoreRightsSummary, pbcoreAnnotation",
        "has_note, has_webresource",
        notes="rightsEmbedded has no AVefi equivalent and is reported",
    ),
    MappingRule(
        "instantiation_date",
        "Item",
        "instantiationDate[@dateType in profile manufacture_date_types]",
        "has_event.has_date (ManufactureEvent)",
        "ISODate",
        "The date the copy was made, not the date of the film",
    ),
    MappingRule(
        "duration",
        "Item",
        "instantiationDuration, else essenceTrackDuration",
        "has_duration.has_value",
        "ISODurationInHours",
    ),
    MappingRule(
        "format",
        "Item",
        "instantiationPhysical, instantiationDigital",
        "has_format (Film, Video, Optical, Audio, DigitalFile)",
        "Profile physical_format_map, digital_format_map",
    ),
    MappingRule(
        "colour_type",
        "Item",
        "instantiationColors",
        "has_colour_type",
        "Profile colour_type_map",
    ),
    MappingRule(
        "language",
        "Item",
        "instantiationLanguage, essenceTrackLanguage",
        "in_language.code, in_language.usage",
        "ISO 639-2/B; profile track_language_usage_map",
        "PBCore does not say how a language is used, so"
        " instantiationLanguage takes the profile default",
    ),
    MappingRule(
        "generations",
        "Item",
        "instantiationGenerations",
        "element_type, has_access_status",
        "Profile element_type_map, access_status_map",
    ),
    MappingRule(
        "instantiation_rights",
        "Item",
        "instantiationRights/rightsSummary, rightsLink",
        "has_access_status, has_note, has_webresource",
        "Profile access_status_map",
        "A rights statement the profile does not know becomes a note",
    ),
    MappingRule(
        "location",
        "Item",
        "instantiationLocation",
        "has_note",
        notes="AVefi names the holding institution through"
        " described_by, which the profile supplies, so the value is"
        " kept as a note and reported",
    ),
    MappingRule(
        "extent",
        "Item",
        "instantiationDimensions, else instantiationFileSize",
        "has_extent.has_value, has_extent.has_unit",
        "Profile extent_unit_map",
        "has_extent holds one value, so the second measurement is reported",
    ),
    MappingRule(
        "essence_track",
        "Item",
        "instantiationEssenceTrack/essenceTrackType,"
        " essenceTrackFrameRate, essenceTrackLanguage",
        "has_sound_type, has_frame_rate, in_language",
        "Profile audio_track_types, frame_rate_map",
        "The remaining track elements are technical detail AVefi does"
        " not carry and are reported per track",
    ),
    MappingRule(
        "annotation",
        "Item",
        "instantiationAnnotation, essenceTrackAnnotation",
        "has_note",
        notes="The @annotationType is kept as a prefix of the note",
    ),
    MappingRule(
        "issuer",
        "Work, Manifestation, Item",
        "profile issuer_info",
        "described_by.has_issuer_id, described_by.has_issuer_name",
        notes="PBCore names no issuer that could be turned into an"
        " ISIL, so the profile supplies one; the shipped default is a"
        " placeholder and is reported once per run",
    ),
)

MAPPING_RULES_BY_ID = {rule.id: rule for rule in MAPPING_RULES}


#: Decisions the mapping takes that are not derivable from PBCore
#: alone. They are listed in the generated documentation so that a
#: reviewer sees them without reading the code.
ASSUMPTIONS = (
    "PBCore describes an asset and its instantiations, which is two"
    " levels where AVefi has three. The asset becomes the WorkVariant,"
    " and every instantiation becomes both a Manifestation and an"
    " Item. Nothing in PBCore states which copies are copies of the"
    " same version, so instantiations are grouped into a manifestation"
    " by the characteristics AVefi puts at that level: colour type,"
    " format and languages. Where a provider records two prints of one"
    " version with different colour statements, they will come out as"
    " two manifestations.",
    "An asset with several instantiations therefore yields several"
    " items. Only the first of them can carry the record identifier"
    " unchanged; the further ones are identified by the record"
    " identifier plus their instantiationIdentifier, or plus their"
    " position when the instantiation has none. This is reported once"
    " per affected record.",
    "An asset without any instantiation still yields a manifestation"
    " and an item, because the AVefi identifier of a holding hangs off"
    " the item. Such an item carries no carrier information, and the"
    " record is reported.",
    "An asset whose instantiations are all of another media type is"
    " skipped, in the same way that the LIDO mapping skips holdings"
    " that are not film. PBCore is widely used for radio, and audio"
    " only material is out of scope for AVefi.",
    "PBCore has no language attribute on pbcoreTitle, so the language"
    " for the article handling of every title of a record comes from"
    " the profile. Where a provider mixes languages in one record, the"
    " ordering names of the foreign titles will be wrong and the"
    " profile should leave default_language unset.",
    "instantiationLanguage does not say how the language is used. It"
    " is recorded with the profile's default_language_usage, which is"
    " SpokenLanguage. Languages taken from an essence track use the"
    " usage the profile associates with the track type.",
    "A pbcoreRelation identifier is transferred unchanged. It names"
    " the related record in the source system and does not resolve to"
    " the AVefi local identifier the converter mints for that record.",
    "Whether an agent is a person or an organisation only follows from"
    " the role, so the agent type stays unset for a creator without a"
    " creatorRole rather than defaulting to Person.",
    "An audio essence track makes an item a sound copy. The absence of"
    " one does not make it silent, so has_sound_type stays unset.",
    "instantiationLocation names the holding institution, which AVefi"
    " expresses through described_by rather than on the item. The"
    " value is kept as a note and reported, and the issuer still has"
    " to be configured in the profile.",
    "pbcoreDescription is mandatory in PBCore and is a synopsis. AVefi"
    " has no field for it at any level, so it is reported with its"
    " value rather than pressed into a note.",
    "A title contributed to an already known work by a further record"
    " is added as an AlternativeTitle. The more specific titleType is"
    " only kept for the record that creates the work.",
    "Decade expressions are reported as unconvertible. Enabling"
    " map_decades maps them to a closed ten year interval.",
    "A running time given as a bare number without a unit is read as"
    " minutes, and clock notation with two components as minutes and"
    " seconds, following the shared normalisation rules.",
    "The shipped profile carries a placeholder issuer. PBCore does not"
    " identify the data provider in a form that could become an ISIL,"
    " and the records are not usable until the holding institution is"
    " configured.",
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
        "# PBCore 2.1 to AVefi mapping",
        "",
        "Generated from `MAPPING_RULES` in `efi_conv.pbcore.mapping`;",
        "do not edit by hand.",
        "",
        "| Rule | Level | PBCore source | AVefi target |"
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
        "Decisions the mapping takes that PBCore does not determine,"
        " and that need confirming against the reference data:",
        "",
    ]
    lines += [f"- {assumption}" for assumption in ASSUMPTIONS]
    return "\n".join(lines) + "\n"


def parse_pbcore(input_file):
    """Yield the description documents of a PBCore file.

    Both a document with pbcoreDescriptionDocument as its root and a
    pbcoreCollection holding many of them are handled, and the file is
    streamed rather than read as a whole.

    """
    return parse_records(
        input_file,
        PbcoreDescriptionDocument,
        PBCORE_NAMESPACE,
        RECORD_ELEMENT,
    )


def efi_import(
    input_file,
    profile: PbcoreProfile,
    continue_on_error: bool = False,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Convert a PBCore file into AVefi records using ``profile``.

    Parameters
    ----------
    input_file
        Path of the PBCore document.
    profile : PbcoreProfile
        Vocabularies and issuer information of the data provider.
    continue_on_error : bool
        Report a record that cannot be converted and carry on with the
        remaining ones, instead of aborting the whole file. A single
        unmappable date in a large export would otherwise cost every
        record in it.
    context : MappingContext, optional
        Grouping context to add the records of this file to. One
        conversion of several files passes the same context to each of
        them, so that assets describing one film in different files
        share their work. Without it the file is converted on its own.

    """
    records = []
    if context is None:
        context = new_context(profile)
    with for_file(input_file):
        report_placeholder_issuer(profile)
        for document in parse_pbcore(input_file):
            try:
                with context.attempt():
                    records.extend(map_record(document, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_record_skipped(
                    e, record_id=safe_record_identifier(document)
                )
    return records


def report_placeholder_issuer(profile: PbcoreProfile):
    """Warn once per run when the issuer is still the placeholder.

    PBCore is a format, not an institution. Records carrying the
    placeholder issuer must not be registered, so the run says so
    rather than leaving it to be noticed later.

    """
    if profile.issuer_info.get("has_issuer_id") != PLACEHOLDER_ISSUER_ID:
        return
    report_issue(
        "warning",
        "Converting with the placeholder issuer of the PBCore profile."
        " Replace it with the ISIL of the holding institution before"
        " using these records",
        source_field="profile issuer_info",
        target_field="described_by.has_issuer_id",
        raw_value=profile.issuer_info.get("has_issuer_id"),
    )


@dataclass
class MappingContext(GroupingContext):
    """State shared by all records of one conversion.

    Several PBCore assets commonly describe the same film, and one
    asset commonly describes several copies of it. Works and
    manifestations are therefore reused across records and across the
    instantiations of a record.

    """

    profile: PbcoreProfile | None = None


def new_context(profile: PbcoreProfile) -> MappingContext:
    """Return a grouping context for one conversion.

    Handed to :func:`efi_import` once per run rather than once per
    file, so that the works of a conversion are shared between the
    input files.

    """
    return MappingContext(profile=profile)


def map_record(
    document: PbcoreDescriptionDocument,
    profile: PbcoreProfile,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one PBCore record."""
    if context is None:
        context = MappingContext(profile=profile)
    source_key, other_identifiers = collect_identifiers(document, profile)

    titles = collect_titles(document, profile, source_key)
    if not titles:
        raise ValueError(f"PBCore record {source_key} has no usable title")
    primary, alternatives = titles[0], titles[1:]

    production_date, publication_date, publication_kind = asset_dates(
        document, profile, source_key
    )
    production = build_production_event(
        document, profile, source_key, production_date
    )
    publication = build_publication_event(
        document, profile, source_key, publication_date, publication_kind
    )
    notes, links = manifestation_notes(document, profile, source_key)
    report_unmapped_asset_elements(document, source_key)

    instantiations = usable_instantiations(document, profile, source_key)
    if document.pbcore_instantiation and not instantiations:
        report_issue(
            "info",
            "Record skipped: no instantiation of a moving image",
            record_id=source_key,
            source_field="instantiationMediaType",
            target_field="—",
        )
        return []
    if not instantiations:
        report_issue(
            "info",
            "Record has no instantiation; the manifestation and item"
            " carry no information about a carrier",
            record_id=source_key,
            source_field="pbcoreInstantiation",
            target_field="Manifestation, Item",
        )

    new_records = []
    work_key = make_work_key(profile, source_key, primary[0], production)

    def new_work():
        work = build_work(document, primary, alternatives, profile, source_key)
        if production is not None:
            work.has_event.append(production)
        return work

    work, is_new = context.work_for(work_key, new_work)
    if is_new:
        new_records.append(work)
    else:
        merge_alternative_titles(work, [title for title, _ in alternatives])
    work_id = work.has_identifier[0]

    for index, instantiation in enumerate(instantiations or [None]):
        item = build_item(instantiation, primary, profile, source_key)
        manifestation_key = make_manifestation_key(work_key, item)

        def new_manifestation(work_id=work_id):
            manifestation = efi.Manifestation(
                is_manifestation_of=[work_id],
                has_primary_title=as_title(primary[0], "TitleProper"),
            )
            if publication is not None:
                manifestation.has_event.append(
                    publication.model_copy(deep=True)
                )
            return manifestation

        manifestation, is_new = context.manifestation_for(
            manifestation_key, new_manifestation
        )
        if is_new:
            new_records.append(manifestation)
        merge_strings(manifestation.has_note, notes)
        merge_strings(manifestation.has_webresource, links)

        item.is_item_of = manifestation.has_identifier[0]
        item.has_identifier.append(
            efi.LocalResource(
                id=item_identifier(
                    source_key, instantiation, index, instantiations
                )
            )
        )
        add_other_identifiers(item, other_identifiers, source_key)
        new_records.append(item)
        attach_source_key(
            (work, manifestation, item), profile.issuer_info, source_key
        )
    return new_records


# --- identifiers ------------------------------------------------------


def collect_identifiers(
    document: PbcoreDescriptionDocument, profile: PbcoreProfile
) -> tuple[str, list[tuple[str, str]]]:
    """Return the source key and the remaining pbcoreIdentifiers."""
    entries = []
    for identifier in document.pbcore_identifier or []:
        value = text_of(identifier)
        if value:
            entries.append((str(identifier.source or "").strip(), value))
    if not entries:
        raise ValueError("PBCore record without a usable pbcoreIdentifier")
    chosen = 0
    wanted = [
        source.lower() for source in profile.authoritative_identifier_sources
    ]
    for source in wanted:
        matching = [
            index
            for index, entry in enumerate(entries)
            if entry[0].lower() == source
        ]
        if matching:
            chosen = matching[0]
            break
    others = [entry for index, entry in enumerate(entries) if index != chosen]
    return entries[chosen][1], others


def add_other_identifiers(item, identifiers, source_key):
    """Add the identifiers not used as the source key to an item."""
    known = {resource.id for resource in item.has_identifier}
    for source, value in identifiers:
        report_issue(
            "info",
            "AVefi has no place for the source of a local identifier,"
            " only for its value",
            record_id=source_key,
            source_field="pbcoreIdentifier/@source",
            target_field="has_identifier",
            raw_value=source or None,
        )
        if value.lower().startswith(("http://", "https://")):
            merge_strings(item.has_webresource, [value])
            continue
        if value not in known:
            item.has_identifier.append(efi.LocalResource(id=value))
            known.add(value)


def item_identifier(
    source_key: str, instantiation, index: int, instantiations
) -> str:
    """Return the local identifier of the item for one instantiation.

    A record describing a single copy yields an item identified by the
    record identifier. A record describing several has to distinguish
    them, which PBCore only supports through instantiationIdentifier.

    """
    if len(instantiations) <= 1:
        return source_key
    local = None
    for identifier in (
        getattr(instantiation, "instantiation_identifier", None) or []
    ):
        local = text_of(identifier)
        if local:
            break
    suffix = slug(local) if local else f"{index + 1}"
    report_issue(
        "info",
        "Record describes several instantiations; the item identifier"
        " is derived from the record identifier",
        record_id=source_key,
        source_field="instantiationIdentifier",
        target_field="has_identifier",
        raw_value=local,
    )
    return f"{source_key}_{suffix}"


def safe_record_identifier(document) -> str | None:
    """Return the record identifier, or None if there is none."""
    for identifier in getattr(document, "pbcore_identifier", None) or []:
        value = text_of(identifier)
        if value:
            return value
    return None


# --- titles -----------------------------------------------------------


def collect_titles(
    document: PbcoreDescriptionDocument, profile: PbcoreProfile, source_key
) -> list[tuple[SourceTitle, str]]:
    """Return the titles of a record, the primary one first."""
    preferred, others = [], []
    for element in document.pbcore_title or []:
        raw = text_of(element)
        if not raw:
            continue
        type_value = str(element.title_type or "").strip().lower()
        mapped = profile.title_type_map.get(type_value)
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi title type configured for this titleType,"
                " title kept as an alternative title",
                record_id=source_key,
                source_field="pbcoreTitle/@titleType",
                target_field="has_alternative_title.type",
                raw_value=element.title_type,
            )
            mapped = "AlternativeTitle"
        supplied = raw.startswith("[") and raw.endswith("]")
        value = raw[1:-1].strip() if supplied else raw
        if not value:
            continue
        is_preferred = (
            type_value in profile.primary_title_types and not preferred
        )
        target_field = (
            "has_primary_title.has_ordering_name"
            if is_preferred
            else "has_alternative_title.has_ordering_name"
        )
        display, ordering = normalise_title(
            value,
            profile.default_language,
            record_id=source_key,
            target_field=target_field,
        )
        if ordering and ordering != display:
            report_issue(
                "info",
                "Derived ordering name from article position",
                record_id=source_key,
                source_field="pbcoreTitle",
                target_field=target_field,
                raw_value=raw,
            )
        entry = (SourceTitle(display, ordering, supplied), mapped)
        (preferred if is_preferred else others).append(entry)
    return preferred + others


# --- work -------------------------------------------------------------


def build_work(document, primary, alternatives, profile, source_key):
    """Return the WorkVariant for one PBCore record."""
    if primary[1] not in ("PreferredTitle", "SuppliedDevisedTitle"):
        report_issue(
            "info",
            "AVefi requires a preferred title on a work; the title"
            " type of the record is kept for the alternative titles"
            " only",
            record_id=source_key,
            source_field="pbcoreTitle/@titleType",
            target_field="has_primary_title.type",
            raw_value=primary[1],
        )
    work = efi.WorkVariant(
        type=efi.WorkVariantTypeEnum(work_type(document, profile, source_key)),
        has_primary_title=as_title(primary[0], "PreferredTitle"),
    )
    for title, title_type in alternatives:
        work.has_alternative_title.append(as_title(title, title_type))
    genres, subjects = genre_and_subject_terms(document, profile)
    for term in genres:
        work.has_genre.append(efi.Genre(has_name=term))
        form = profile.work_form_map.get(term.lower())
        if form and efi.WorkFormEnum(form) not in work.has_form:
            work.has_form.append(efi.WorkFormEnum(form))
    for term in subjects:
        work.has_subject.append(efi.Subject(has_name=term))
    for resource in part_of_resources(document, profile, source_key):
        work.is_part_of.append(resource)
    return work


def work_type(document, profile, source_key) -> str:
    """Return the WorkVariantTypeEnum value for an asset."""
    terms = [
        term
        for term in (
            text_of(element) for element in document.pbcore_asset_type or []
        )
        if term
    ]
    if len(terms) > 1:
        report_issue(
            "warning",
            "AVefi allows one work type; only the first asset type is mapped",
            record_id=source_key,
            source_field="pbcoreAssetType",
            target_field="type",
            raw_value=terms[1:],
        )
    if not terms:
        return profile.default_work_type
    mapped = profile.asset_type_map.get(terms[0].strip().lower())
    if mapped is None:
        report_issue(
            "warning",
            "No AVefi work type configured for this asset type,"
            " falling back to the profile default",
            record_id=source_key,
            source_field="pbcoreAssetType",
            target_field="type",
            raw_value=terms[0],
        )
        return profile.default_work_type
    return mapped


def genre_and_subject_terms(document, profile):
    """Return the terms going to has_genre and to has_subject."""
    genres, subjects = [], []
    for element in document.pbcore_genre or []:
        term = text_of(element)
        if term and term not in genres:
            genres.append(term)
    for element in document.pbcore_subject or []:
        term = text_of(element)
        if not term:
            continue
        kind = str(element.subject_type or "").strip().lower()
        target = genres if kind in profile.genre_subject_types else subjects
        if term not in target:
            target.append(term)
    return genres, subjects


def part_of_resources(document, profile, source_key):
    """Yield the works this record says it is a part of."""
    for relation in document.pbcore_relation or []:
        kind = (text_of(relation.pbcore_relation_type) or "").strip().lower()
        identifier = text_of(relation.pbcore_relation_identifier)
        if not identifier:
            continue
        if kind in profile.part_of_relation_types:
            yield efi.LocalResource(id=identifier)
        else:
            report_issue(
                "warning",
                "No AVefi relation configured for this relation type,"
                " relation not transferred",
                record_id=source_key,
                source_field="pbcoreRelation/pbcoreRelationType",
                target_field="is_part_of",
                raw_value=f"{kind}: {identifier}",
            )


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
    """Return the agents of an event as a stable string."""
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

    PBCore has no level between the asset and the single copy, so the
    manifestation can only be reconstructed from the characteristics
    AVefi puts at that level.

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


# --- events -----------------------------------------------------------


def asset_dates(document, profile, source_key):
    """Return production date, publication date and its date type."""
    production = publication = None
    publication_kind = ""
    for element in document.pbcore_asset_date or []:
        value = text_of(element)
        if not value:
            continue
        kind = str(element.date_type or "").strip().lower()
        if kind in profile.production_date_types and production is None:
            target = "production"
        elif kind in profile.publication_date_types and publication is None:
            target = "publication"
        else:
            report_issue(
                "warning",
                "No AVefi event configured for this asset date type,"
                " date not transferred",
                record_id=source_key,
                source_field="pbcoreAssetDate/@dateType",
                target_field="has_event.has_date",
                raw_value=f"{element.date_type or ''}: {value}",
            )
            continue
        source_field = f"pbcoreAssetDate[@dateType='{kind}']"
        mapped = mapped_date(value, profile, source_key, source_field)
        if target == "production":
            production = mapped
        else:
            publication = mapped
            publication_kind = kind
    return production, publication, publication_kind


def mapped_date(value, profile, source_key, source_field):
    """Return an ISODate for ``value``, reporting what cannot be."""
    try:
        return normalise_date(
            value,
            record_id=source_key,
            source_field=source_field,
            target_field="has_event.has_date",
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=source_key,
            source_field=source_field,
            target_field="has_event.has_date",
            raw_value=value,
        )
        raise


def build_production_event(document, profile, source_key, production_date):
    """Return the ProductionEvent described by the asset."""
    event = efi.ProductionEvent()
    if production_date:
        event.has_date = production_date
    for name in spatial_coverage(document, source_key):
        event.located_in.append(efi.GeographicName(has_name=name))
    for activity in directing_activities(document, profile, source_key):
        event.has_activity.append(activity)
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def spatial_coverage(document, source_key):
    """Yield the place names of the spatial coverage of an asset."""
    for entry in document.pbcore_coverage or []:
        value = text_of(entry.coverage)
        if not value:
            continue
        kind = (
            entry.coverage_type.value
            if entry.coverage_type is not None
            else ""
        )
        if kind == "Spatial":
            yield value
        elif kind == "Temporal":
            report_issue(
                "warning",
                "Temporal coverage describes the content of the film,"
                " for which AVefi has no field; value not transferred",
                record_id=source_key,
                source_field="pbcoreCoverage[coverageType='Temporal']",
                target_field="—",
                raw_value=value,
            )
        else:
            report_issue(
                "warning",
                "Coverage without a coverageType cannot be told apart"
                " from a temporal one; value not transferred",
                record_id=source_key,
                source_field="pbcoreCoverage",
                target_field="has_event.located_in",
                raw_value=value,
            )


def directing_activities(document, profile, source_key):
    """Return the DirectingActivity entries of an asset."""
    by_type: dict[str, list] = {}
    for entry in document.pbcore_creator or []:
        collect_agent(
            by_type,
            entry.creator,
            [text_of(role) for role in entry.creator_role or []],
            profile,
            source_key,
            "pbcoreCreator",
            profile.default_creator_activity,
        )
    for entry in document.pbcore_contributor or []:
        collect_agent(
            by_type,
            entry.contributor,
            [text_of(role) for role in entry.contributor_role or []],
            profile,
            source_key,
            "pbcoreContributor",
            None,
        )
    return [
        efi.DirectingActivity(
            type=efi.DirectingActivityTypeEnum(activity_type),
            has_agent=agents,
        )
        for activity_type, agents in sorted(by_type.items())
    ]


def collect_agent(
    by_type, element, roles, profile, source_key, source_field, default
):
    """Add the agent of one creator or contributor to ``by_type``."""
    name = text_of(element)
    if not name:
        return
    if name.lower() in profile.unknown_agent_names:
        report_issue(
            "info",
            "Placeholder agent name skipped",
            record_id=source_key,
            source_field=source_field,
            target_field="has_event.has_activity",
            raw_value=name,
        )
        return
    affiliation = getattr(element, "affiliation", None)
    if affiliation:
        report_issue(
            "info",
            "AVefi has no field for the affiliation of an agent",
            record_id=source_key,
            source_field=f"{source_field}/@affiliation",
            target_field="has_event.has_activity.has_agent",
            raw_value=affiliation,
        )
    for role in [role for role in roles if role] or [None]:
        key = role.strip().lower() if role else ""
        mapped = profile.directing_role_map.get(key) if role else default
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi activity mapped for this role, agent not"
                " transferred",
                record_id=source_key,
                source_field=f"{source_field}/role",
                target_field="has_event.has_activity",
                raw_value=role or name,
            )
            continue
        agents = by_type.setdefault(mapped, [])
        if all(agent.has_name != name for agent in agents):
            agents.append(
                build_agent(name, role, profile, source_key, source_field)
            )


def build_agent(name, role, profile, source_key, source_field):
    """Return the AVefi agent for a PBCore creator or contributor.

    PBCore states a name and, at best, a role. Whether the name is a
    person or an organisation only follows from the role, so the agent
    type stays unset where the role does not say.

    """
    agent = efi.Agent(has_name=name)
    kind = agent_type(role, profile)
    if kind is None:
        report_issue(
            "info",
            "PBCore does not say whether this agent is a person or a"
            " corporate body; agent type left unset",
            record_id=source_key,
            source_field=source_field,
            target_field="has_agent.type",
            raw_value=name,
        )
    else:
        agent.type = efi.AgentTypeEnum(kind)
    return agent


def agent_type(role, profile) -> str | None:
    """Return the AgentTypeEnum value for an agent in ``role``."""
    if not role:
        return None
    if role.strip().lower() in profile.corporate_agent_role_terms:
        return "CorporateBody"
    if role.strip().lower() in profile.directing_role_map:
        return "Person"
    return None


def build_publication_event(
    document, profile, source_key, publication_date, publication_kind
):
    """Return the PublicationEvent described by the asset."""
    activities = publisher_activities(document, profile, source_key)
    if not (publication_date or activities):
        return None
    event_type = profile.publication_event_type_map.get(
        publication_kind, profile.default_publication_event_type
    )
    event = efi.PublicationEvent(type=efi.PublicationEventTypeEnum(event_type))
    if publication_date:
        event.has_date = publication_date
    for activity in activities:
        event.has_activity.append(activity)
    return event


def publisher_activities(document, profile, source_key):
    """Return the ManifestationActivity entries of an asset."""
    by_type: dict[str, list] = {}
    for entry in document.pbcore_publisher or []:
        name = text_of(entry.publisher)
        if not name:
            continue
        if name.lower() in profile.unknown_agent_names:
            report_issue(
                "info",
                "Placeholder publisher name skipped",
                record_id=source_key,
                source_field="pbcorePublisher",
                target_field="has_event.has_activity",
                raw_value=name,
            )
            continue
        roles = [text_of(role) for role in entry.publisher_role or []]
        for role in [role for role in roles if role] or [None]:
            key = role.strip().lower() if role else ""
            mapped = profile.publisher_role_map.get(key)
            if mapped is None:
                report_issue(
                    "warning",
                    "No AVefi activity mapped for this publisher role,"
                    " agent not transferred",
                    record_id=source_key,
                    source_field="pbcorePublisher/publisherRole",
                    target_field="has_event.has_activity",
                    raw_value=role or name,
                )
                continue
            agents = by_type.setdefault(mapped, [])
            if all(agent.has_name != name for agent in agents):
                agents.append(
                    efi.Agent(
                        type=efi.AgentTypeEnum("CorporateBody"),
                        has_name=name,
                    )
                )
    return [
        efi.ManifestationActivity(
            type=efi.ManifestationActivityTypeEnum(activity_type),
            has_agent=agents,
        )
        for activity_type, agents in sorted(by_type.items())
    ]


# --- manifestation level notes ----------------------------------------


def manifestation_notes(document, profile, source_key):
    """Return the notes and links the asset contributes."""
    notes, links = [], []
    for rights in document.pbcore_rights_summary or []:
        summary = text_of(rights.rights_summary)
        if summary:
            notes.append(f"Rights: {summary}")
        link = text_of(rights.rights_link)
        if link:
            links.append(link)
        if rights.rights_embedded is not None:
            report_issue(
                "warning",
                "Embedded rights metadata has no AVefi equivalent",
                record_id=source_key,
                source_field="pbcoreRightsSummary/rightsEmbedded",
                target_field="has_note",
            )
    for element in document.pbcore_annotation or []:
        note = annotation_note(element)
        if note:
            notes.append(note)
    return notes, links


def annotation_note(element) -> str | None:
    """Return an annotation as a note, keeping its type as a prefix."""
    text = text_of(element)
    if not text:
        return None
    label = str(getattr(element, "annotation_type", "") or "").strip()
    return f"{label}: {text}" if label else text


def merge_strings(target: list, values):
    """Add the values not present yet to a list of strings."""
    for value in values:
        if value not in target:
            target.append(value)


def report_unmapped_asset_elements(document, source_key):
    """Report the asset elements AVefi has no field for."""
    for attribute, name in UNMAPPED_ASSET_FIELDS:
        for element in getattr(document, attribute, None) or []:
            report_issue(
                "info",
                f"AVefi has no field for {name}; value not transferred",
                record_id=source_key,
                source_field=name,
                target_field="—",
                raw_value=text_of(element) or name,
            )


# --- instantiations ---------------------------------------------------


def usable_instantiations(document, profile, source_key) -> list:
    """Return the instantiations describing a moving image."""
    result = []
    for instantiation in document.pbcore_instantiation or []:
        media_type = (
            (text_of(instantiation.instantiation_media_type) or "")
            .strip()
            .lower()
        )
        if (
            profile.moving_image_media_types
            and media_type not in profile.moving_image_media_types
        ):
            report_issue(
                "info",
                "Instantiation skipped: not a moving image",
                record_id=source_key,
                source_field="instantiationMediaType",
                target_field="—",
                raw_value=media_type,
            )
            continue
        result.append(instantiation)
    return result


def build_item(instantiation, primary, profile, source_key):
    """Return the Item for one instantiation.

    ``is_item_of`` and ``has_identifier`` are filled in by the caller,
    once the manifestation this copy belongs to is known.

    """
    item = efi.Item(
        is_item_of=efi.LocalResource(id="__pending__"),
        has_primary_title=as_title(primary[0], "TitleProper"),
    )
    if instantiation is None:
        return item
    add_duration(item, instantiation, profile, source_key)
    add_formats(item, instantiation, profile, source_key)
    add_colour_type(item, instantiation, profile, source_key)
    add_languages(item, instantiation, profile, source_key)
    add_generations(item, instantiation, profile, source_key)
    add_instantiation_rights(item, instantiation, profile, source_key)
    add_extent(item, instantiation, profile, source_key)
    add_location(item, instantiation, source_key)
    add_instantiation_dates(item, instantiation, profile, source_key)
    add_essence_tracks(item, instantiation, profile, source_key)
    for element in instantiation.instantiation_annotation or []:
        note = annotation_note(element)
        if note:
            merge_strings(item.has_note, [note])
    report_unmapped_instantiation_elements(instantiation, source_key)
    return item


def add_duration(item, instantiation, profile, source_key):
    """Set the running time of a copy from instantiationDuration."""
    value = text_of(instantiation.instantiation_duration)
    if not value:
        return
    # PBCore states a duration in free text, so an unreadable one is
    # to be expected; it costs the field, not the record.
    has_value = mapped_duration(
        value, record_id=source_key, source_field="instantiationDuration"
    )
    if has_value:
        item.has_duration = efi.Duration(has_value=has_value)


def add_formats(item, instantiation, profile, source_key):
    """Add the carrier formats of a copy."""
    for element, vocabulary, name in (
        (
            instantiation.instantiation_physical,
            profile.physical_format_map,
            "instantiationPhysical",
        ),
        (
            instantiation.instantiation_digital,
            profile.digital_format_map,
            "instantiationDigital",
        ),
    ):
        term = text_of(element)
        if not term:
            continue
        mapped = vocabulary.get(term.strip().lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi format configured for this carrier term,"
                " format not transferred",
                record_id=source_key,
                source_field=name,
                target_field="has_format",
                raw_value=term,
            )
            continue
        kind, type_value = mapped
        item.has_format.append(FORMAT_CLASSES[kind](type=type_value))


def add_colour_type(item, instantiation, profile, source_key):
    """Set the colour type of a copy from instantiationColors."""
    term = text_of(instantiation.instantiation_colors)
    if not term:
        return
    mapped = profile.colour_type_map.get(term.strip().lower())
    if mapped is None:
        report_issue(
            "warning",
            "No AVefi colour type configured for this term, colour not"
            " transferred",
            record_id=source_key,
            source_field="instantiationColors",
            target_field="has_colour_type",
            raw_value=term,
        )
        return
    item.has_colour_type = efi.ColourTypeEnum(mapped)


def add_languages(item, instantiation, profile, source_key):
    """Add the languages stated for the instantiation as a whole."""
    for element in instantiation.instantiation_language or []:
        code = mapped_language(
            text_of(element), source_key, "instantiationLanguage"
        )
        if code:
            add_language(item, code, profile.default_language_usage)


def mapped_language(tag, source_key, source_field) -> str | None:
    """Return the AVefi language code for a PBCore language tag."""
    if not tag:
        return None
    mapped = language_code(tag)
    if mapped:
        return mapped
    try:
        return efi.LanguageCodeEnum(tag.strip().lower()).value
    except ValueError:
        report_issue(
            "warning",
            "Language tag is not an ISO 639-2/B code AVefi accepts,"
            " language not transferred",
            record_id=source_key,
            source_field=source_field,
            target_field="in_language.code",
            raw_value=tag,
        )
        return None


def add_language(item, code, usage):
    """Add a language to an item, keeping the list free of duplicates."""
    for language in item.in_language:
        if language.code == code:
            if usage not in language.usage:
                language.usage.append(efi.LanguageUsageEnum(usage))
            return
    item.in_language.append(
        efi.Language(
            code=efi.LanguageCodeEnum(code),
            usage=[efi.LanguageUsageEnum(usage)],
        )
    )


def add_generations(item, instantiation, profile, source_key):
    """Map instantiationGenerations to element type and access status."""
    for element in instantiation.instantiation_generations or []:
        term = text_of(element)
        if not term:
            continue
        key = term.strip().lower()
        element_type = profile.element_type_map.get(key)
        access_status = profile.access_status_map.get(key)
        if element_type and item.element_type is None:
            item.element_type = efi.ItemElementTypeEnum(element_type)
        if access_status and item.has_access_status is None:
            item.has_access_status = efi.ItemAccessStatusEnum(access_status)
        if not (element_type or access_status):
            report_issue(
                "warning",
                "No AVefi element type or access status configured for"
                " this generation, value not transferred",
                record_id=source_key,
                source_field="instantiationGenerations",
                target_field="element_type, has_access_status",
                raw_value=term,
            )


def add_instantiation_rights(item, instantiation, profile, source_key):
    """Map the rights of a copy to access status, notes and links."""
    for rights in instantiation.instantiation_rights or []:
        summary = text_of(rights.rights_summary)
        if summary:
            mapped = profile.access_status_map.get(summary.strip().lower())
            if mapped and item.has_access_status is None:
                item.has_access_status = efi.ItemAccessStatusEnum(mapped)
            else:
                merge_strings(item.has_note, [f"Rights: {summary}"])
        link = text_of(rights.rights_link)
        if link:
            merge_strings(item.has_webresource, [link])
        if rights.rights_embedded is not None:
            report_issue(
                "warning",
                "Embedded rights metadata has no AVefi equivalent",
                record_id=source_key,
                source_field="instantiationRights/rightsEmbedded",
                target_field="has_note",
            )


def add_extent(item, instantiation, profile, source_key):
    """Set the extent of a copy, preferring the physical measurement."""
    candidates = [
        (element, "instantiationDimensions")
        for element in instantiation.instantiation_dimensions or []
    ]
    if instantiation.instantiation_file_size is not None:
        candidates.append(
            (instantiation.instantiation_file_size, "instantiationFileSize")
        )
    for element, name in candidates:
        extent = build_extent(element, profile, source_key, name)
        if extent is None:
            continue
        if item.has_extent is None:
            item.has_extent = extent
        else:
            report_issue(
                "info",
                "AVefi holds one extent per item; further measurement"
                " not transferred",
                record_id=source_key,
                source_field=name,
                target_field="has_extent",
                raw_value=text_of(element),
            )


def build_extent(element, profile, source_key, name):
    """Return the AVefi extent for a PBCore measurement, if mappable."""
    value = text_of(element)
    if not value:
        return None
    unit = str(getattr(element, "units_of_measure", "") or "").strip().lower()
    mapped = profile.extent_unit_map.get(unit)
    number = re.sub(r"[\s,]", "", value).replace(",", ".")
    try:
        amount = Decimal(number)
    except InvalidOperation:
        amount = None
    if mapped is None or amount is None:
        report_issue(
            "warning",
            "Measurement cannot be expressed as an AVefi extent, value"
            " not transferred",
            record_id=source_key,
            source_field=name,
            target_field="has_extent",
            raw_value=f"{value} {unit}".strip(),
        )
        return None
    return efi.Extent(has_unit=efi.UnitEnum(mapped), has_value=amount)


def add_location(item, instantiation, source_key):
    """Keep the holding institution as a note and report it."""
    location = text_of(instantiation.instantiation_location)
    if not location:
        return
    merge_strings(item.has_note, [f"Holding institution: {location}"])
    report_issue(
        "info",
        "AVefi names the holding institution through described_by,"
        " which the profile supplies; instantiationLocation kept as a"
        " note",
        record_id=source_key,
        source_field="instantiationLocation",
        target_field="described_by.has_issuer_name",
        raw_value=location,
    )


def add_instantiation_dates(item, instantiation, profile, source_key):
    """Add the date a copy was made as a ManufactureEvent."""
    for element in instantiation.instantiation_date or []:
        value = text_of(element)
        if not value:
            continue
        kind = str(element.date_type or "").strip().lower()
        if kind not in profile.manufacture_date_types:
            report_issue(
                "warning",
                "No AVefi event configured for this instantiation date"
                " type, date not transferred",
                record_id=source_key,
                source_field="instantiationDate/@dateType",
                target_field="has_event.has_date",
                raw_value=f"{element.date_type or ''}: {value}",
            )
            continue
        mapped = mapped_date(value, profile, source_key, "instantiationDate")
        if mapped:
            item.has_event.append(efi.ManufactureEvent(has_date=mapped))


def add_essence_tracks(item, instantiation, profile, source_key):
    """Map the essence tracks of a copy as far as AVefi allows."""
    for track in instantiation.instantiation_essence_track or []:
        kind = (text_of(track.essence_track_type) or "").strip().lower()
        if kind in profile.audio_track_types and item.has_sound_type is None:
            item.has_sound_type = efi.SoundTypeEnum(profile.sound_type)
        add_frame_rate(item, track, profile, source_key)
        usage = profile.track_language_usage_map.get(
            kind, profile.default_language_usage
        )
        for element in track.essence_track_language or []:
            code = mapped_language(
                text_of(element), source_key, "essenceTrackLanguage"
            )
            if code:
                add_language(item, code, usage)
        duration = text_of(track.essence_track_duration)
        if duration and item.has_duration is None:
            has_value = mapped_duration(
                duration,
                record_id=source_key,
                source_field="essenceTrackDuration",
            )
            if has_value:
                item.has_duration = efi.Duration(has_value=has_value)
        for element in track.essence_track_annotation or []:
            note = annotation_note(element)
            if note:
                merge_strings(item.has_note, [note])
        report_unmapped_track_elements(track, source_key)


def add_frame_rate(item, track, profile, source_key):
    """Set the frame rate of a copy from an essence track."""
    value = text_of(track.essence_track_frame_rate)
    if not value or item.has_frame_rate is not None:
        return
    key = value.strip().lower().removesuffix("fps").strip()
    mapped = profile.frame_rate_map.get(key)
    if mapped is None:
        report_issue(
            "warning",
            "No AVefi frame rate configured for this value, frame rate"
            " not transferred",
            record_id=source_key,
            source_field="essenceTrackFrameRate",
            target_field="has_frame_rate",
            raw_value=value,
        )
        return
    item.has_frame_rate = efi.FrameRateEnum(mapped)


def report_unmapped_track_elements(track, source_key):
    """Report the essence track detail AVefi has no field for."""
    present = {}
    for attribute, name in UNMAPPED_TRACK_FIELDS:
        element = getattr(track, attribute, None)
        value = (
            text_of(first(element))
            if isinstance(element, list)
            else text_of(element)
        )
        if value:
            present[name] = value
    if present:
        report_issue(
            "info",
            "AVefi has no field for this technical detail of an"
            " essence track; values not transferred",
            record_id=source_key,
            source_field="instantiationEssenceTrack",
            target_field="—",
            raw_value=present,
        )


def report_unmapped_instantiation_elements(instantiation, source_key):
    """Report the instantiation detail AVefi has no field for."""
    present = {}
    for attribute, name in UNMAPPED_INSTANTIATION_FIELDS:
        element = getattr(instantiation, attribute, None)
        if isinstance(element, list):
            if element:
                present[name] = text_of(first(element)) or len(element)
        elif element is not None:
            present[name] = text_of(element) or name
    if present:
        report_issue(
            "info",
            "AVefi has no field for this detail of an instantiation;"
            " values not transferred",
            record_id=source_key,
            source_field="pbcoreInstantiation",
            target_field="—",
            raw_value=present,
        )
