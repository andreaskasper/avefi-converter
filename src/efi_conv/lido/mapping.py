"""Generic mapping from LIDO to the AVefi schema.

LIDO is a standard, so the traversal of the document is the same for
every data provider. Everything that differs between institutions —
issuer information, the vocabularies used inside the LIDO terms — is
supplied through a :class:`~efi_conv.lido.profile.LidoProfile`.

Every LIDO record yields a work, a manifestation and an item, mirroring
the structure the CSV importer produces for the same institution.

"""

from dataclasses import dataclass, field
import logging
import re

from avefi_schema import model_pydantic_v2 as efi

from ..core.normalise import (
    language_code,
    mapped_date,
    mapped_duration,
    normalise_title,
)
from ..core.records import (
    GroupingContext,
    SourceTitle,
    as_title,
    attach_source_key,
    local_identifier,
    make_key,
    merge_alternative_titles,
    work_key,
)
from ..core.report import for_file, report_issue, report_record_skipped
from ..core.xmlrecords import first, parse_records, text_of
from .generated.lido_1_1 import Lido
from .profile import DEFAULT_AGENT_TYPES, LidoProfile

log = logging.getLogger(__name__)

#: Namespace and element name of a LIDO record.
LIDO_NAMESPACE = "http://www.lido-schema.org"
LIDO_RECORD_ELEMENT = "lido"


@dataclass(frozen=True)
class MappingRule:
    """One documented mapping from a LIDO path to an AVefi field."""

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
        "scope",
        "Record",
        "lido:administrativeMetadata/lido:recordWrap/lido:recordType,"
        " else lido:objectWorkType",
        "—",
        "Profile record_type_terms, else film_work_type_terms",
        "Where a provider states what a record describes, that decides"
        " and the work type is not consulted. Records out of scope are"
        " skipped and reported; a record stating neither is skipped"
        " with a warning",
    ),
    MappingRule(
        "work_identity",
        "Work",
        "lido:objectRelationWrap/lido:relatedWorksWrap"
        "/lido:relatedWorkSet[relType in profile terms]",
        "has_identifier (work), has_primary_title, is_manifestation_of",
        "Profile related_work_rel_terms",
        "Where the provider states which films a copy is of, that"
        " decides: the work keeps its own identifier and title, and a"
        " copy naming several belongs to several works",
    ),
    MappingRule(
        "work_pid",
        "Work",
        "lido:relatedWorkSet[relType in profile terms]/lido:relatedWork"
        "/lido:object/lido:objectID whose lido:source names AVefi",
        "has_identifier (AVefiResource)",
        "Profile avefi_sources",
        "The local identifier stays and stays first; the handle is"
        " added beside it, so that a re-import of registered holdings"
        " updates the work instead of minting a second one for it",
    ),
    MappingRule(
        "work_authority",
        "Work",
        "lido:relatedWorkSet[relType in profile terms]/lido:relatedWork"
        "/lido:object/lido:objectID whose lido:source names an"
        " authority AVefi knows",
        "same_as",
        "Profile related_authority_sources",
        "The identifier is the last segment of the value: an authority"
        " writes one identifier under more than one path, and"
        " filmportal.de/film/<id> and filmportal.de/<id> resolve to"
        " the same work. Filmportal is the one authority a LIDO export"
        " has been seen to carry here",
    ),
    MappingRule(
        "manifestation_pid",
        "Manifestation",
        "lido:relatedWorkSet[relType in profile"
        " manifestation_rel_terms]/lido:relatedWork/lido:object"
        "/lido:objectID whose lido:source names AVefi",
        "has_identifier (AVefiResource), manifestation grouping",
        "Profile manifestation_rel_terms, avefi_sources",
        "The only place a record states the identifier of its"
        " manifestation: the record describes the copy, so"
        " objectPublishedID is the copy's. It also decides which"
        " copies share a manifestation, the derived key being the"
        " fallback for a copy that states none",
    ),
    MappingRule(
        "work_grouping",
        "Work",
        "primary title, director, production date",
        "has_identifier (work)",
        "Profile work_key_fields",
        "Fallback where no related work is stated. Several copies of"
        " one film share one WorkVariant, as in fmdu/csv.py; set"
        " work_key_fields to () for one work per record",
    ),
    MappingRule(
        "manifestation_grouping",
        "Manifestation",
        "the manifestation's own identifier where the record states"
        " one, else the work key plus colour type, format and"
        " languages of the copy",
        "has_identifier (manifestation)",
        notes="Where the provider names the manifestation, that"
        " decides which copies share one — two copies described"
        " differently are still one manifestation. Otherwise copies"
        " agreeing on the carrier characteristics share one",
    ),
    MappingRule(
        "record_id",
        "Item",
        "lido:lidoRecID, else lido:administrativeMetadata"
        "/lido:recordWrap/lido:recordID",
        "has_identifier, described_by.has_source_key",
        "Profile source_key_pattern",
        notes="Local identifier; also used to derive the work and"
        " manifestation ids. The pattern selects the identifier out of"
        " the namespaces a provider prefixes it with, so that the key"
        " matches the one the rest of its data uses",
    ),
    MappingRule(
        "primary_title",
        "Work, Manifestation, Item",
        "lido:titleWrap/lido:titleSet[@lido:type='preferred']"
        "/lido:appellationValue",
        "has_primary_title.has_name, has_primary_title.has_ordering_name",
        "Article handling in both directions",
        "First title set is used when none is marked preferred;"
        " bracketed titles become SuppliedDevisedTitle",
    ),
    MappingRule(
        "alternative_title",
        "Work",
        "lido:titleWrap/lido:titleSet (remaining sets)",
        "has_alternative_title",
        "Article handling in both directions",
    ),
    MappingRule(
        "form_and_genre",
        "Work",
        "lido:objectClassificationWrap/lido:classificationWrap"
        "/lido:classification",
        "has_form, has_genre.has_name",
        "Profile work_form_map",
        "A term naming the kind of thing a film is becomes a form and"
        " not also a genre; the rest become genres. Classifications"
        " whose lido:type is named in the profile as carrying colour,"
        " format, access status or keywords are consumed by those"
        " rules instead",
    ),
    MappingRule(
        "subject",
        "Work",
        "lido:eventActor/lido:actorInRole[role in subject terms]",
        "has_subject.has_name, has_subject.same_as",
        "Profile subject_role_terms",
        "What the film is about, which this provider files where the"
        " credits are; only the role tells the two apart",
    ),
    MappingRule(
        "production_date",
        "Work",
        "lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventDate",
        "has_event.has_date",
        "ISODate; abbreviated intervals expanded",
        "lido:earliestDate and lido:latestDate take precedence"
        " over lido:displayDate",
    ),
    MappingRule(
        "production_place",
        "Work",
        "lido:eventWrap/lido:eventSet/lido:event[production]/lido:eventPlace",
        "has_event.located_in.has_name, located_in.same_as",
        notes="Name as the source gives it, plus the authority"
        " identifier where the record carries one; a place stated"
        " twice is recorded once",
    ),
    MappingRule(
        "activity",
        "Work",
        "lido:event[production or creation]/lido:eventActor/lido:actorInRole",
        "has_event.has_activity",
        "Profile role_activity_map and director_role_terms",
        "The role decides the activity class, since no value is"
        " shared between the sixteen activity vocabularies. Agents of"
        " one role share one activity. Placeholder names such as"
        " 'unbekannt' are skipped and reported",
    ),
    MappingRule(
        "agent_type",
        "Work",
        "lido:actor/@lido:type",
        "has_event.has_activity.has_agent.type",
        notes="Person or CorporateBody as the source states it; it is"
        " not derived from the name",
    ),
    MappingRule(
        "agent_authority",
        "Work",
        "lido:actor/lido:actorID[@lido:source in GND, VIAF, Wikidata]",
        "has_event.has_activity.has_agent.same_as",
        notes="Transferred where the source carries it; nothing is"
        " looked up and nothing is added",
    ),
    MappingRule(
        "other_agent",
        "Work",
        "lido:eventActor/lido:actorInRole (roles with no activity)",
        "—",
        notes="Reported as unmapped rather than dropped silently",
    ),
    MappingRule(
        "publication_date",
        "Manifestation",
        "lido:event[publication]/lido:eventDate and lido:eventPlace",
        "has_event (PublicationEvent, ReleaseEvent)",
        "ISODate",
    ),
    MappingRule(
        "duration",
        "Item",
        "lido:objectMeasurementsWrap//lido:measurementsSet[running time]",
        "has_duration.has_value",
        "ISODurationInHours; profile duration_units may state the unit",
    ),
    MappingRule(
        "extent",
        "Item",
        "lido:objectMeasurementsWrap//lido:measurementsSet[length]",
        "has_extent.has_value, has_extent.has_unit",
        "Profile extent_unit_map",
        "Transferred as the record states it. Where the length and the"
        " running time cannot both be right for the format, that is"
        " reported and neither is changed",
    ),
    MappingRule(
        "colour_type",
        "Item",
        "lido:classification[@lido:type in profile"
        " classification_types['colour']]",
        "has_colour_type",
        "Profile vocabulary",
    ),
    MappingRule(
        "format",
        "Item",
        "lido:classification[@lido:type in profile"
        " classification_types['format']]",
        "has_format (Film)",
        "Profile vocabulary",
    ),
    MappingRule(
        "access_status",
        "Item",
        "lido:classification[@lido:type in profile"
        " classification_types['access']]",
        "has_access_status",
        "Profile vocabulary",
    ),
    MappingRule(
        "avefi_identifier",
        "Item",
        "lido:objectPublishedID whose lido:source names AVefi",
        "has_identifier (AVefiResource)",
        "Profile avefi_sources, avefi_handle_prefix as a fallback",
        "A copy registered in AVefi carries its handle back into the"
        " provider's export; transferring it makes a re-import an"
        " update instead of a second identifier for one copy",
    ),
    MappingRule(
        "materials_tech",
        "Item",
        "lido:event/lido:eventMaterialsTech/lido:materialsTech"
        "/lido:termMaterialsTech",
        "has_colour_type, has_format, element_type, has_sound_type",
        "Profile materials_tech_map, then the value itself",
        "The colour, sound, element type and format vocabularies of"
        " the schema share no value, so the value determines the"
        " field. lido:conceptID is read as a cross check and a"
        " disagreement is reported; publication and preservation"
        " event types found here are recognised but not acted on",
    ),
    MappingRule(
        "keyword_classification",
        "Item",
        "lido:classification[@lido:type in profile"
        " keyword_classification_types]",
        "in_language, has_access_status",
        "Profile language_name_map and access_status_map",
        "Routed by the term rather than by the type, because a"
        " provider may file language, access status and working notes"
        " under one heading; a term matching neither is reported",
    ),
    MappingRule(
        "language_usage",
        "Item",
        "lido:classification/lido:term[@lido:label]",
        "in_language.code, in_language.usage",
        "Profile language_usage_labels and language_name_map",
        "The label states what a language is for — Dialogton,"
        " Untertitel, Zwischentitel — and is the only thing telling"
        " the terms apart; a term whose label is not configured is"
        " reported rather than read as the spoken language",
    ),
    MappingRule(
        "webresource",
        "Item",
        "lido:administrativeMetadata/lido:resourceWrap//lido:linkResource,"
        " lido:objectPublishedID holding a URL",
        "has_webresource",
        notes="A published identifier that is a URL and not an AVefi"
        " handle is the object's page in the provider's system. The"
        " value decides, not lido:type, which this provider gives as"
        " a local identifier for a URL",
    ),
    MappingRule(
        "handle_check",
        "Record",
        "lido:objectPublishedID, lido:relatedWorkSet//lido:objectID"
        " whose lido:source names AVefi",
        "—",
        "Profile avefi_handle_prefix",
        "Not a mapping but its own check: a handle stated in the"
        " record and carried by none of the records derived from it"
        " is reported with the relation it stood under. A handle"
        " cannot be withdrawn, so losing one is expensive and silent",
    ),
    MappingRule(
        "issuer",
        "Work, Manifestation, Item",
        "profile issuer_info",
        "described_by.has_issuer_id, described_by.has_issuer_name",
        notes="Taken from the profile, not from lido:recordSource,"
        " so that the issuer is unambiguous",
    ),
)

MAPPING_RULES_BY_ID = {rule.id: rule for rule in MAPPING_RULES}


#: Decisions the mapping takes that are not derivable from LIDO alone.
#: They are listed in the generated documentation so that a reviewer
#: sees them without reading the code.
ASSUMPTIONS = (
    "A record without a recognised `lido:objectWorkType` is skipped"
    " rather than imported as a film.",
    "Where a copy states several films, the record's production"
    " event, genres and alternative titles are not attributed to any"
    " of them. A date read off a compilation reel is the date of the"
    " reel; its genres belong to no one film on it. The works are"
    " created with the identifiers and titles the provider gives them"
    " and the rest is reported.",
    "Every record yields one item. Works and manifestations are shared"
    " between records according to the profile key, so several copies"
    " of one film do not produce several works.",
    "`WorkVariant.type` is always `Monographic`; serial and analytic"
    " works are not derived from LIDO.",
    "Actors are read from the production event and from an event of"
    " creation, because a provider may record the people separately"
    " from the making of the copy. The activities are production"
    " activities either way and are attached to the production event.",
    "A title in square brackets is one the cataloguer supplied, on"
    " the work as on the copy. It becomes `SuppliedDevisedTitle` with"
    " the brackets removed, including where the title arrives through"
    " `lido:displayObject` of a related work.",
    "Who issued an identifier is read from `lido:source` and not from"
    " the shape of the value. AVefi will register under more than one"
    " handle prefix, and a record naming the issuer has answered the"
    " question the prefix was standing in for. The prefix is used only"
    " where a record states no source at all.",
    "Whether an agent is a `Person` or a `CorporateBody` is taken from"
    " `lido:type`, against the profile's vocabulary, and left unset"
    " where the source does not say."
    " Deriving it from the name is out of scope, and the earlier"
    " default of `Person` for every director was that derivation in"
    " all but name.",
    "Decade expressions such as `50er Jahre` are reported as"
    " unconvertible. Enabling `map_decades` maps them to a closed ten"
    " year interval and reads two digit decades as twentieth century."
    " EDTF conformance level 0, which is what ISODate allows, has no"
    " decade syntax, so the interval is the only available form.",
    "`ca.`, `c.`, `um` and the combined `ca./ c.` become the ISODate"
    " approximation qualifier `~`; a trailing question mark and one in"
    " brackets, `1960 (?)`, become the uncertainty qualifier `?`. On"
    " an interval the qualifier is written on both ends, because"
    " ISODate carries it per date rather than per interval.",
    "Square brackets around a date mark one the cataloguer supplied"
    " rather than read off the object. That states where the date came"
    " from, not how certain it is, so the brackets are dropped, the"
    " date is taken as given, and the fact is reported.",
    "Words joining an interval — `zwischen 1940 und 1945`, `1970 bis"
    " 1977` — are read as the interval they spell out. An open one,"
    " `nach 1989`, is reported instead: level 0 cannot express it, and"
    " reading it as 1989 would state a year the source refuses to give.",
    "Month names are read in German and English, full and abbreviated."
    " `8/1988` is read as a month and year rather than an interval,"
    " because the left hand side cannot be a year.",
    "A running time given as a bare number without a unit is read as"
    " minutes, unless the profile states the unit of that measurement."
    " A provider labelling a column once and filling it in another"
    " unit is a fact about that export, so it is corrected in its"
    " profile rather than guessed at in the mapping.",
    "A length and a running time that contradict each other are both"
    " transferred as stated and the contradiction is reported. Which"
    " of the two is in the wrong unit is not decidable from the"
    " record, and the provider is the one who knows.",
    "A running time of zero is read as none given. Cataloguing"
    " systems write an empty measurement as a zero, and recording"
    " `PT00H00M00S` would state that the copy runs no length.",
    "Production places keep the name the source gives, including"
    " historical states such as `DDR` or `Deutsches Reich`. That is"
    " the country the film was made in at the time, which is the part"
    " worth having; where the record carries an authority identifier"
    " it is transferred, and that is what resolves the spelling.",
    "Clock notation with two components, such as `1:43`, is read as"
    " minutes and seconds, not as hours and minutes.",
    "A date such as `2003-04` is read as an ISO year and month. Note"
    " that `fmdu/csv.py` reads the same notation as the interval"
    " 2003 to 2004; the divergence is reported per occurrence.",
    "Only the first `lido:descriptiveMetadata` block of a record is"
    " mapped; further blocks are reported.",
    "The article lists are provisional and are to be confirmed against"
    " the reference data.",
    "A term of the technical description that is already an AVefi"
    " value is taken as it stands. The values are a closed set, so a"
    " term that is one of them means itself, and a provider adding a"
    " carrier does not need a change to the converter.",
    "Where `lido:conceptID` names a vocabulary the value does not"
    " belong to, the value decides and the disagreement is reported."
    " The reference data files `DCP` under the digital file"
    " vocabulary although it is an element type, and a hard disk"
    " under the optical one.",
    "Publication and preservation event types occurring in the"
    " technical description are reported rather than turned into"
    " events. A note about the material of a copy does not state that"
    " the film was distributed or restored.",
    "A language recorded without a usage is read as the spoken"
    " language, which is the common case and what the CSV importer"
    " for the same institution records. The assumption is reported"
    " per occurrence rather than left implied.",
    "`Removed` is set only for a copy that carries an AVefi"
    " identifier. It states that something registered is gone, which"
    " says nothing about a copy that was never registered; such a"
    " record is kept without an access status and reported, because"
    " whether it belongs in a delivery is the provider's decision.",
    "LIDO does not prescribe the `lido:type` values marking a colour,"
    " format or access status classification. The profile names them,"
    " and a classification of any other type becomes a genre.",
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
        "# LIDO to AVefi mapping",
        "",
        "Generated from `MAPPING_RULES` in `efi_conv.lido.mapping`;",
        "do not edit by hand.",
        "",
        "| Rule | Level | LIDO source | AVefi target |"
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
        "Decisions the mapping takes that LIDO does not determine, and"
        " that need confirming against the reference data:",
        "",
    ]
    lines += [f"- {assumption}" for assumption in ASSUMPTIONS]
    return "\n".join(lines) + "\n"


#: AVefi activity type value to the class that carries it. The sixteen
#: activity vocabularies of the schema share no value between them, so
#: a profile can name the role and leave the class to be looked up.
ACTIVITY_CLASS_BY_TYPE = {
    member.value: getattr(efi, name[: -len("TypeEnum")])
    for name in dir(efi)
    if name.endswith("ActivityTypeEnum")
    for member in getattr(efi, name)
}


def parse_lido(input_file) -> list[Lido]:
    """Parse a LIDO document and return its records.

    Whatever wraps the records is ignored. Providers ship a
    lido:lidoWrap, a single lido:lido element as the root, or a
    wrapper of their own devising, and all three have to work: parsing
    a document of the second kind as a wrap used to yield an empty
    result rather than an error, and lost every record in it.

    """
    return list(
        parse_records(input_file, Lido, LIDO_NAMESPACE, LIDO_RECORD_ELEMENT)
    )


def efi_import(
    input_file,
    profile: LidoProfile,
    continue_on_error: bool = False,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Convert a LIDO file into AVefi records using ``profile``.

    Parameters
    ----------
    input_file
        Path of the LIDO document.
    profile : LidoProfile
        Institution specific configuration.
    continue_on_error : bool
        Report a record that cannot be converted and carry on with the
        remaining ones, instead of aborting the whole file. A single
        unmappable date in a large export would otherwise cost every
        record in it.
    context : MappingContext, optional
        Grouping context to add the records of this file to. One
        conversion of several files passes the same context to each of
        them, so that copies of one film described in different files
        share their work rather than being minted twice with the same
        identifier. Without it the file is converted on its own.

    """
    records = []
    if context is None:
        context = new_context(profile)
    with for_file(input_file):
        for lido_record in parse_lido(input_file):
            try:
                with context.attempt():
                    records.extend(map_record(lido_record, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_record_skipped(
                    e, record_id=safe_record_identifier(lido_record, profile)
                )
    return records


@dataclass
class MappingContext(GroupingContext):
    """State shared by all records of one conversion.

    Several LIDO records commonly describe several copies of the same
    film. Minting a separate work for each of them would defeat the
    purpose of the AVefi identifiers, so works and manifestations are
    reused across records, mirroring what the CSV importer for the same
    institution does.

    """

    profile: LidoProfile | None = None
    #: Keys a manifestation has already built its local identifier
    #: from. A dict rather than a set so that it is rolled back with
    #: everything else a failed record registered.
    manifestation_local_keys: dict = field(default_factory=dict)


def new_context(profile: LidoProfile) -> MappingContext:
    """Return a grouping context for one conversion.

    Handed to :func:`efi_import` once per run rather than once per
    file, so that the works of a conversion are shared between the
    input files.

    """
    return MappingContext(profile=profile)


#: The AVefi resource class for each authority a related record may
#: be linked to. The profile says which ``lido:source`` means which of
#: them, so a provider naming Filmportal differently needs a profile
#: entry and not a code change.
RELATED_WORK_RESOURCES = {
    "filmportal": efi.FilmportalResource,
    "gnd": efi.GNDResource,
    "viaf": efi.VIAFResource,
    "wikidata": efi.WikidataResource,
    "eidr": efi.EIDRResource,
}

#: Resolvers an identifier may be written through. A handle is the
#: same handle whether it is written bare or as a URL that resolves
#: it, and providers write both.
HANDLE_RESOLVERS = (
    "https://hdl.handle.net/",
    "http://hdl.handle.net/",
    "https://doi.org/",
    "hdl:",
)


@dataclass(frozen=True)
class RelatedRecord:
    """What a ``lido:relatedWorkSet`` says about the record it names.

    Attributes
    ----------
    local : str or None
        The provider's own identifier for the related record.
    title : str
        Its title, as ``lido:displayObject`` states it.
    avefi : str or None
        Its AVefi handle, where the provider carries one. A work and
        a manifestation are named nowhere else in a LIDO record: the
        record describes the copy, and ``objectPublishedID`` is
        therefore the copy's own identifier. Reading the handle here
        is what turns a re-import of registered holdings into an
        update of the work rather than a second work for one film.
    same_as : tuple
        Authority links stated for it, such as its Filmportal entry.

    """

    local: str | None
    title: str = ""
    avefi: str | None = None
    same_as: tuple = ()


def rel_type_names(related_set) -> tuple:
    """Return the ways a relatedWorkSet names its relation.

    Both the human readable ``lido:term`` and the ``lido:conceptID``
    identifying the relation, the latter reduced to its last path
    segment: ``https://www.av-efi.net/av-efi-schema/is_item_of`` is
    the same statement as the term "is item of", and a provider is
    free to give either or both.

    """
    rel = getattr(related_set, "related_work_rel_type", None)
    if rel is None:
        return ()
    names = []
    text = term_text(rel)
    if text:
        names.append(text.strip().lower())
    for concept in getattr(rel, "concept_id", None) or []:
        value = (text_of(concept) or "").strip()
        if not value:
            continue
        names.append(value.lower())
        names.append(value.rstrip("/").rsplit("/", 1)[-1].lower())
    return tuple(names)


def related_sets(descriptive, terms):
    """Yield the relatedWorkSets whose relation is one of ``terms``."""
    if not terms:
        return
    wrap = getattr(
        descriptive.object_relation_wrap, "related_works_wrap", None
    )
    if wrap is None:
        return
    wanted = {str(term).lower() for term in terms}
    for related_set in wrap.related_work_set or []:
        if wanted.intersection(rel_type_names(related_set)):
            yield related_set


def issued_by_avefi(candidate, text, profile) -> bool:
    """Return True if AVefi issued this identifier.

    The record says so: ``lido:source`` names the authority. The handle
    prefix is not the criterion, because AVefi will register under more
    than one and an identifier that named its issuer has already
    answered the question the prefix was standing in for. Where a
    record states no source, the prefix is what is left to go on.

    """
    source = str(getattr(candidate, "source", "") or "").strip().lower()
    if source:
        return source in profile.avefi_sources
    prefix = profile.avefi_handle_prefix
    return bool(prefix) and f"{prefix}/" in text


def avefi_handle(text: str) -> str | None:
    """Return the handle in ``text``, without the resolver it is under."""
    value = (text or "").strip()
    for resolver in HANDLE_RESOLVERS:
        if value.lower().startswith(resolver):
            value = value[len(resolver) :]
            break
    value = value.strip().strip("/")
    return value or None


def authority_resource_for(candidate, profile):
    """Return the resource class for an identifier's ``lido:source``."""
    source = str(getattr(candidate, "source", "") or "").strip().lower()
    if not source:
        return None
    authority = profile.related_authority_sources.get(source)
    return RELATED_WORK_RESOURCES.get(authority) if authority else None


def authority_identifier(text: str) -> str | None:
    """Return the identifier in ``text``, without the URL around it.

    An authority writes the same identifier under more than one path —
    ``filmportal.de/film/<id>`` and ``filmportal.de/<id>`` resolve to
    one work — so the last segment is the identifier and the rest is
    how one gets to it.

    """
    value = (text or "").strip().rstrip("/")
    return value.rsplit("/", 1)[-1].strip() or None


def object_identifiers(obj, profile):
    """Return local identifier, AVefi handle and authority links.

    A related record states several identifiers of itself and LIDO
    does not order them, so which one is which follows from what the
    record says about them rather than from their position: the one
    whose ``lido:source`` names AVefi is the AVefi identifier, one
    naming another authority is a link to it, and what remains is the
    provider's own key. Taking the first one, as this did, worked only
    as long as the provider happened to write its own first.

    """
    local = None
    avefi = None
    same_as = []
    for candidate in getattr(obj, "object_id", None) or []:
        text = (text_of(candidate) or "").strip()
        if not text:
            continue
        if issued_by_avefi(candidate, text, profile):
            avefi = avefi or avefi_handle(text)
            continue
        resource = authority_resource_for(candidate, profile)
        if resource is not None:
            identifier = authority_identifier(text)
            if identifier:
                link = resource(id=identifier)
                if link not in same_as:
                    same_as.append(link)
            continue
        if local is None and not is_absolute_url(text):
            local = local_source_key(text, profile)
    return local, avefi, tuple(same_as)


def is_absolute_url(text: str) -> bool:
    """Return True if ``text`` is an http or https URL."""
    return text.lower().startswith(("http://", "https://"))


def apply_stated_identifiers(record, related, source_key, level: str) -> None:
    """Add the PID and authority links a provider states for a record.

    Only ever added, never replaced: the local identifier stays where
    it is and stays first, because everything in the delivery refers
    to a work and a manifestation by it.

    """
    if related.avefi:
        others = [
            identifier.id
            for identifier in record.has_identifier
            if identifier.category == "avefi:AVefiResource"
            and identifier.id != related.avefi
        ]
        if others:
            report_issue(
                "warning",
                f"{level} is given a second AVefi identifier by this"
                " record; both are kept, because a handle cannot be"
                " withdrawn and which of them is right is for the"
                " data provider to say",
                record_id=source_key,
                source_field="relatedWorkSet/relatedWork/object/objectID",
                target_field="has_identifier",
                raw_value=[*others, related.avefi],
            )
    if related.avefi and not any(
        identifier.category == "avefi:AVefiResource"
        and identifier.id == related.avefi
        for identifier in record.has_identifier
    ):
        record.has_identifier.append(efi.AVefiResource(id=related.avefi))
        report_issue(
            "info",
            f"{level} already carries an AVefi identifier; transferred"
            " rather than minted again",
            record_id=source_key,
            source_field="relatedWorkSet/relatedWork/object/objectID",
            target_field="has_identifier",
            raw_value=related.avefi,
        )
    known = {(link.category, link.id) for link in record.same_as or []}
    for link in related.same_as:
        if (link.category, link.id) in known:
            continue
        record.same_as.append(link)
        known.add((link.category, link.id))


def manifestation_relations(descriptive, profile, source_key):
    """Return what the record says about its own manifestation.

    A copy is related to the manifestation it is one of, and that
    relation carries the manifestation's AVefi identifier. It is the
    only place a LIDO record states one: the record describes the
    copy, so ``objectPublishedID`` is the copy's.

    """
    for related_set in related_sets(
        descriptive, profile.manifestation_rel_terms
    ):
        related = getattr(related_set, "related_work", None)
        if related is None:
            continue
        obj = getattr(related, "object_value", None) or getattr(
            related, "object", None
        )
        if obj is None:
            continue
        local, avefi, same_as = object_identifiers(obj, profile)
        if avefi or same_as:
            return RelatedRecord(local, "", avefi, same_as)
    return None


def related_works(lido_record, descriptive, profile, source_key):
    """Yield the works a copy belongs to, as the provider states them.

    A related work carries an identifier of its own and a title, which
    is a better basis for a work than a key derived from the copy: the
    provider decides what is one film and what is two, and says so.
    In the reference export that identifies 3717 works, including the
    six copies that hold more than one film — a reel of two shorts is
    two works and one manifestation, and reconstructing that from a
    concatenated title is what the manual revision of the CSV output
    had to do by hand.

    """
    seen = set()
    for related_set in related_sets(
        descriptive, profile.related_work_rel_terms
    ):
        related = getattr(related_set, "related_work", None)
        if related is None:
            continue
        obj = getattr(related, "object_value", None) or getattr(
            related, "object", None
        )
        identifier, avefi, same_as = (
            object_identifiers(obj, profile)
            if obj is not None
            else (None, None, ())
        )
        title = text_of(first(getattr(related, "display_object", None)))
        if not identifier:
            report_issue(
                "warning",
                "Related work states no identifier, so the copy cannot"
                " be attached to it",
                record_id=source_key,
                source_field="relatedWorkSet/relatedWork",
                target_field="is_manifestation_of",
                raw_value=title,
            )
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        yield RelatedRecord(identifier, (title or "").strip(), avefi, same_as)


def map_record(
    lido_record: Lido,
    profile: LidoProfile,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one LIDO record."""
    if context is None:
        context = MappingContext(profile=profile)
    source_key = record_identifier(lido_record, profile)
    descriptive = first(lido_record.descriptive_metadata)
    if descriptive is None:
        raise ValueError(
            f"LIDO record {source_key} has no descriptiveMetadata"
        )
    if len(lido_record.descriptive_metadata or []) > 1:
        report_issue(
            "warning",
            "Only the first descriptiveMetadata block is mapped",
            record_id=source_key,
            source_field="descriptiveMetadata",
            raw_value=len(lido_record.descriptive_metadata),
        )

    if not in_scope(lido_record, descriptive, profile, source_key):
        return []

    titles = collect_titles(descriptive, profile, source_key)
    if not titles:
        raise ValueError(f"LIDO record {source_key} has no usable title")
    primary, alternatives = titles[0], titles[1:]

    production = build_production_event(descriptive, profile, source_key)
    publication = build_publication_event(descriptive, profile, source_key)

    new_records = []
    stated = list(related_works(lido_record, descriptive, profile, source_key))
    if stated:
        works, work_key = works_as_stated(
            stated,
            descriptive,
            primary,
            alternatives,
            production,
            profile,
            source_key,
            context,
            new_records,
        )
    else:
        works, work_key = work_from_the_copy(
            descriptive,
            primary,
            alternatives,
            production,
            profile,
            source_key,
            context,
            new_records,
        )
    work_ids = [work.has_identifier[0] for work in works]

    item = build_item(lido_record, descriptive, primary, profile, source_key)
    manifestation_key = make_manifestation_key(work_key, item)

    def new_manifestation():
        manifestation = efi.Manifestation(
            is_manifestation_of=list(work_ids),
            has_primary_title=as_title(primary, "TitleProper"),
        )
        if publication is not None:
            manifestation.has_event.append(publication)
        return manifestation

    stated_manifestation = manifestation_relations(
        descriptive, profile, source_key
    )
    manifestation, is_new = manifestation_for(
        context,
        manifestation_key,
        stated_manifestation,
        new_manifestation,
        work_ids,
        source_key,
    )
    if is_new:
        new_records.append(manifestation)
    if stated_manifestation is not None:
        apply_stated_identifiers(
            manifestation, stated_manifestation, source_key, "Manifestation"
        )
    item.is_item_of = manifestation.has_identifier[0]
    item.has_identifier.append(
        efi.LocalResource(id=local_identifier(source_key))
    )
    new_records.append(item)

    attach_source_key(
        (*works, manifestation, item), profile.issuer_info, source_key
    )
    report_handles_not_transferred(
        lido_record,
        descriptive,
        (*works, manifestation, item),
        profile,
        source_key,
    )
    return new_records


def manifestation_for(context, key, stated, factory, work_ids, source_key):
    """Return the manifestation this copy belongs to.

    Several copies commonly belong to one manifestation, and until now
    the converter decided which by deriving a key from the copy —
    colour, format, languages. Where the provider states the
    manifestation's own identifier, that is the better answer and the
    only one that cannot contradict itself: two copies described
    differently were becoming two manifestations, and both were given
    the one identifier the provider stated, which ``efi-conv check``
    rightly rejects as not unique.

    The identifier is therefore the key where there is one, and the
    derived key is registered alongside it so that a copy of the same
    manifestation that carries no identifier still finds it. What the
    local identifier is built from does not change: it is what a
    reader recognises, and a handle repeated inside it would say the
    same thing twice.

    """
    pid = stated.avefi if stated is not None else None
    if not pid:
        return context.manifestation_for(key, factory)
    manifestation, is_new = context.manifestation_for(
        f"avefi:{pid}", factory, local_id=unique_manifestation_id(context, key)
    )
    context.manifestations.setdefault(key, manifestation)
    if not is_new:
        report_manifestation_disagreement(
            manifestation, work_ids, pid, source_key
        )
    return manifestation, is_new


def unique_manifestation_id(context, key: str) -> str:
    """Return a key no other manifestation has built its id from.

    Two manifestations the provider keeps apart can look the same to
    the derived key — it knows colour, format and language and the
    provider may be separating them on something else. They would then
    be given one local identifier between them, which is the same
    duplicate the persistent identifiers were producing.

    """
    taken = context.manifestation_local_keys
    if key not in taken:
        taken[key] = True
        return key
    suffix = 2
    while make_key(key, str(suffix)) in taken:
        suffix += 1
    unique = make_key(key, str(suffix))
    taken[unique] = True
    return unique


def report_manifestation_disagreement(
    manifestation, work_ids, pid, source_key
) -> None:
    """Report a manifestation two records attach to different works."""
    known = {identifier.id for identifier in manifestation.is_manifestation_of}
    stated = {identifier.id for identifier in work_ids}
    if known == stated:
        return
    report_issue(
        "warning",
        "Copies of one manifestation are attached to different works;"
        " the manifestation keeps the works of the record that"
        " introduced it",
        record_id=source_key,
        source_field="relatedWorkSet",
        target_field="is_manifestation_of",
        raw_value=sorted(known ^ stated),
    )


def report_handles_not_transferred(
    lido_record, descriptive, records, profile, source_key
) -> None:
    """Report an AVefi handle in the record that reached no output.

    A handle in the source and not in the output means the next
    delivery asks for a second identifier for something that already
    has one, and a handle cannot be withdrawn. It is also a silent
    failure: the conversion succeeds, the records validate, and only
    a comparison of input and output shows it — which is how the
    handles of works and manifestations went unread for weeks.

    So the conversion compares them itself. Every handle the record
    writes into an identifier is looked for in the records derived
    from it, and one that is not there is reported together with the
    relation it was stated under, which is usually what is missing
    from the profile.

    """
    transferred = {
        identifier.id
        for record in records
        for identifier in record.has_identifier
        if identifier.category == "avefi:AVefiResource"
    }
    for handle, relation in stated_handles(lido_record, descriptive, profile):
        if handle in transferred:
            continue
        report_issue(
            "warning",
            "Record states an AVefi identifier that no output record"
            " carries; the next delivery would ask for a second one."
            " A relation named here that the profile does not know is"
            " the usual cause",
            record_id=source_key,
            source_field=relation,
            target_field="has_identifier",
            raw_value=handle,
        )


def stated_handles(lido_record, descriptive, profile):
    """Yield every AVefi handle the record writes into an identifier.

    Identifiers only — ``objectPublishedID`` and the ``objectID`` of
    any related record, whatever the relation. A handle quoted in a
    note or a description is somebody talking about a film and not the
    record claiming an identity.

    """
    seen = set()

    def handles(candidate, relation):
        text = (text_of(candidate) or "").strip()
        if not text or not issued_by_avefi(candidate, text, profile):
            return
        handle = avefi_handle(text)
        if handle and handle not in seen:
            seen.add(handle)
            yield handle, relation

    for published in lido_record.object_published_id or []:
        yield from handles(published, "objectPublishedID")
    wrap = getattr(
        descriptive.object_relation_wrap, "related_works_wrap", None
    )
    if wrap is None:
        return
    for related_set in wrap.related_work_set or []:
        names = rel_type_names(related_set) or ("—",)
        relation = f"relatedWorkSet[relType={names[0]}]/objectID"
        related = getattr(related_set, "related_work", None)
        obj = (
            getattr(related, "object_value", None)
            or getattr(related, "object", None)
            if related is not None
            else None
        )
        for candidate in getattr(obj, "object_id", None) or []:
            yield from handles(candidate, relation)


def work_from_the_copy(
    descriptive,
    primary,
    alternatives,
    production,
    profile,
    source_key,
    context,
    new_records,
):
    """Return the single work derived from the copy's own data."""
    work_key = make_work_key(profile, source_key, primary, production)

    def new_work():
        work = build_work(
            descriptive, primary, alternatives, profile, source_key
        )
        if production is not None:
            work.has_event.append(production)
        return work

    work, is_new = context.work_for(work_key, new_work)
    if is_new:
        new_records.append(work)
    else:
        merge_alternative_titles(work, alternatives)
    return [work], work_key


def works_as_stated(
    stated,
    descriptive,
    primary,
    alternatives,
    production,
    profile,
    source_key,
    context,
    new_records,
):
    """Return the works the provider states this copy belongs to.

    Where a copy holds one film, everything the record says about it
    describes that film, and the record's own titles and production
    event go to the work as before.

    Where it holds several, they do not. A production date read off a
    compilation reel is the date of the reel, not of each film on it,
    and its genres and alternative titles belong to no one film in
    particular. Attaching them to all of them would state something
    about each film that the source does not, so the works are created
    with the titles and identifiers the provider gives them, and the
    rest is reported as not attributable.

    """
    single = len(stated) == 1
    if not single:
        report_issue(
            "info",
            f"Copy belongs to {len(stated)} works, so what the record"
            " says about production, genre and alternative titles"
            " cannot be attributed to one of them and is not"
            " transferred",
            record_id=source_key,
            source_field="relatedWorkSet",
            target_field="has_event, has_genre, has_alternative_title",
            raw_value=[related.local for related in stated],
        )
    works = []
    for related in stated:
        # The title of the work as the provider writes it, which is
        # not the same string as the copy's: it carries the bracket
        # notation for a title somebody supplied just as any other
        # title does, and reading it as a plain string was why a work
        # kept its brackets while its copies did not.
        stated_title = source_title(
            related.title,
            profile,
            source_key,
            "has_primary_title.has_ordering_name",
        )

        def new_work(stated_title=stated_title, related=related):
            if single:
                work = build_work(
                    descriptive, primary, alternatives, profile, source_key
                )
                if production is not None:
                    work.has_event.append(production)
                if stated_title and stated_title.display != primary.display:
                    # The record's own title is the carrier's; the
                    # related work is what the film is called.
                    work.has_primary_title = as_title(
                        stated_title, "PreferredTitle"
                    )
                return work
            return efi.WorkVariant(
                type=efi.WorkVariantTypeEnum("Monographic"),
                has_primary_title=as_title(
                    stated_title or SourceTitle(related.local, None, False),
                    "PreferredTitle",
                ),
            )

        work, is_new = context.work_for(related.local, new_work)
        if is_new:
            new_records.append(work)
        elif single:
            merge_alternative_titles(work, alternatives)
        apply_stated_identifiers(work, related, source_key, "Work")
        works.append(work)
    return works, make_key(*(related.local for related in stated))


def in_scope(lido_record, descriptive, profile, source_key) -> bool:
    """Return True if the record is one the conversion is about.

    Two ways of deciding, and the first is the better one. Where a
    provider states what each record describes — ``lido:recordType`` —
    that is an answer rather than an inference, and a profile naming
    the terms gets exactly the records the provider means.

    Only where it does not is the work type consulted, which infers
    the same thing from the object and can be wrong about it.

    """
    if profile.record_type_terms:
        return has_record_type(lido_record, profile, source_key)
    return is_film_record(descriptive, profile, source_key)


def record_types(lido_record):
    """Yield the recordType terms a record states."""
    for administrative in lido_record.administrative_metadata or []:
        record_wrap = administrative.record_wrap
        if record_wrap is None:
            continue
        text = term_text(getattr(record_wrap, "record_type", None))
        if text:
            yield text


def has_record_type(lido_record, profile, source_key) -> bool:
    """Return True if the record states a type the profile wants."""
    terms = list(record_types(lido_record))
    if not terms:
        report_issue(
            "warning",
            "Record states no recordType, so it cannot be told from a"
            " record of another kind; record skipped",
            record_id=source_key,
            source_field="recordType",
            target_field="—",
        )
        return False
    if any(term.lower() in profile.record_type_terms for term in terms):
        return True
    report_issue(
        "info",
        "Record skipped: not a record type this conversion is about",
        record_id=source_key,
        source_field="recordType",
        target_field="—",
        raw_value=terms,
    )
    return False


def is_film_record(descriptive, profile, source_key) -> bool:
    """Return True if the record describes film rather than an extra.

    Only holdings metadata about film is in scope; accompanying
    material such as posters, scripts or photographs occurs in the same
    museum export and must not become a film work.

    """
    if not profile.film_work_type_terms:
        return True
    wrap = getattr(
        descriptive.object_classification_wrap, "object_work_type_wrap", None
    )
    terms = []
    for work_type in getattr(wrap, "object_work_type", None) or []:
        text = term_text(work_type)
        if text:
            terms.append(text)
    if not terms:
        report_issue(
            "warning",
            "Record has no objectWorkType, cannot tell film from"
            " accompanying material; record skipped",
            record_id=source_key,
            source_field="objectWorkType",
            target_field="—",
        )
        return False
    if any(term.lower() in profile.film_work_type_terms for term in terms):
        return True
    report_issue(
        "info",
        "Record skipped: not a film holding",
        record_id=source_key,
        source_field="objectWorkType",
        target_field="—",
        raw_value=terms,
    )
    return False


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

    Copies that agree on the characteristics carried by the Fassung
    level belong to the same manifestation.

    """
    parts = [
        work_key,
        str(item.has_colour_type or ""),
        ",".join(sorted(str(fmt.type) for fmt in item.has_format or [])),
        ",".join(
            sorted(
                f"{language.code or ''}"
                f":{','.join(sorted(language.usage or []))}"
                for language in item.in_language or []
            )
        ),
    ]
    return make_key(*parts)


def safe_record_identifier(lido_record, profile=None) -> str | None:
    """Return the record identifier, or None if there is none."""
    try:
        return record_identifier(lido_record, profile)
    except ValueError:
        return None


def build_work(descriptive, primary, alternatives, profile, source_key):
    """Return the WorkVariant for one LIDO record."""
    work = efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=as_title(primary, "PreferredTitle"),
    )
    for title in alternatives:
        work.has_alternative_title.append(as_title(title, "AlternativeTitle"))
    for term in classification_terms(descriptive, profile):
        form = profile.work_form_map.get(term.lower())
        if form:
            if form not in (work.has_form or []):
                work.has_form.append(efi.WorkFormEnum(form))
            continue
        work.has_genre.append(efi.Genre(has_name=term))
    for subject in collect_subjects(descriptive, profile, source_key):
        work.has_subject.append(subject)
    return work


def collect_subjects(descriptive, profile, source_key):
    """Yield what a record says the film is about.

    Providers record the subject of a film as an actor with a role of
    its own — "Behandelte Person" — which puts a person the film is
    about in the same place as the people who made it. Reading the
    role is what tells the two apart; without it the subject either
    becomes a director or is reported as an unmappable credit, and
    130 of them were.

    """
    if not profile.subject_role_terms:
        return
    seen = set()
    for lido_event in actor_events(descriptive, profile):
        for actor_wrap in lido_event.event_actor or []:
            in_role = actor_wrap.actor_in_role
            if in_role is None:
                continue
            role = term_text(first(in_role.role_actor))
            if not role or role.strip().lower() not in (
                profile.subject_role_terms
            ):
                continue
            name = actor_name(in_role)
            if not name or name in seen:
                continue
            seen.add(name)
            subject = efi.Subject(has_name=name)
            for authority in authority_resources(
                getattr(in_role, "actor", None)
            ):
                subject.same_as.append(authority)
            yield subject


def build_production_event(descriptive, profile, source_key):
    """Return the ProductionEvent described by the LIDO events."""
    lido_event = find_event(descriptive, profile.production_event_terms)
    if lido_event is None:
        return None
    event = efi.ProductionEvent()

    date_value = event_date_value(lido_event)
    has_date = mapped_date(
        date_value,
        record_id=source_key,
        map_decades=profile.map_decades,
    )
    if has_date:
        event.has_date = has_date

    add_places(event, lido_event)

    for activity in collect_activities(descriptive, profile, source_key):
        event.has_activity.append(activity)
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def role_activity_type(role: str | None, profile) -> str | None:
    """Return the AVefi activity type a source role denotes."""
    if not role:
        return None
    key = role.strip().lower()
    if key in profile.director_role_terms:
        return "Director"
    return profile.role_activity_map.get(key)


def actor_events(descriptive, profile):
    """Yield the events whose actors take part in the production.

    The people who made a film are not always recorded on the event
    that made the copy. A provider may model the intellectual creation
    as an event of its own and put director, composer and writer
    there, which is a statement about how the source is organised
    rather than about the film: the activities are production
    activities either way, and land on the production event.

    """
    wrap = descriptive.event_wrap
    if wrap is None:
        return
    terms = set(profile.production_event_terms) | set(
        profile.creation_event_terms
    )
    for event_set in wrap.event_set or []:
        event = event_set.event
        if event is None:
            continue
        text = term_text(event.event_type)
        if text and text.lower() in terms:
            yield event


def collect_activities(descriptive, profile, source_key):
    """Yield the activities of one record, one per role.

    Agents sharing a role share an activity, mirroring the shape the
    CSV importer produces, and the order of both follows the source.

    """
    by_role = {}
    for lido_event in actor_events(descriptive, profile):
        for actor_wrap in lido_event.event_actor or []:
            in_role = actor_wrap.actor_in_role
            if in_role is None:
                continue
            name = actor_name(in_role)
            if not name:
                continue
            role = term_text(first(in_role.role_actor))
            if name.lower() in profile.unknown_agent_names:
                report_issue(
                    "info",
                    "Placeholder actor name skipped",
                    record_id=source_key,
                    source_field="eventActor",
                    target_field="has_event.has_activity",
                    raw_value=name,
                )
                continue
            if role and role.strip().lower() in profile.subject_role_terms:
                # Not a credit at all; build_work reads these.
                continue
            activity_type = role_activity_type(role, profile)
            activity_class = ACTIVITY_CLASS_BY_TYPE.get(activity_type)
            if activity_class is None:
                report_issue(
                    "warning",
                    "No AVefi activity mapped for this role, agent not"
                    " transferred",
                    record_id=source_key,
                    source_field="eventActor/roleActor",
                    target_field="has_event.has_activity",
                    raw_value=role or name,
                )
                continue
            agent = build_agent(in_role, name, profile)
            activity = by_role.get(activity_type)
            if activity is None:
                # has_agent is required, so the activity cannot exist
                # before the first agent that justifies it.
                by_role[activity_type] = activity_class(
                    type=activity_type, has_agent=[agent]
                )
            elif not any(
                existing.has_name == agent.has_name
                for existing in activity.has_agent
            ):
                activity.has_agent.append(agent)
    yield from by_role.values()


def build_agent(in_role, name: str, profile=None):
    """Return the Agent for an actorInRole element.

    Whether the actor is a person or an organisation is read off
    ``lido:type`` rather than guessed from the name. Guessing is a
    documented non-goal, and it is also unnecessary here: the source
    states it.

    """
    actor = getattr(in_role, "actor", None)
    agent = efi.Agent(has_name=name)
    agent_type = agent_type_of(actor, profile)
    if agent_type:
        agent.type = efi.AgentTypeEnum(agent_type)
    for authority in authority_resources(actor):
        agent.same_as.append(authority)
    return agent


def agent_type_of(actor, profile=None) -> str | None:
    """Return the kind of agent ``lido:type`` states, if it states one.

    LIDO leaves the value to the provider, so the vocabulary is
    configuration: ``DEFAULT_AGENT_TYPES`` collects the spellings seen
    so far and a profile adds its own. Left unset where the source
    says nothing — deriving the kind from the name is out of scope,
    and the earlier default of Person for every actor was that
    derivation in all but name.

    """
    stated = str(getattr(actor, "type_value", "") or "").strip().lower()
    if not stated:
        return None
    known = dict(DEFAULT_AGENT_TYPES)
    known.update(
        {
            str(key).lower(): value
            for key, value in (
                getattr(profile, "agent_type_map", None) or {}
            ).items()
        }
    )
    return known.get(stated)


#: Authority file to the AVefi resource class carrying its identifiers,
#: keyed by the lido:source a provider names it with.
AUTHORITY_RESOURCES = {
    "gnd": efi.GNDResource,
    "viaf": efi.VIAFResource,
    "wikidata": efi.WikidataResource,
    "tgn": efi.TGNResource,
    "aat": efi.AATResource,
}

#: An authority identifier is written either bare or as the URI that
#: resolves it. Only the identifier goes into the record.
AUTHORITY_ID_PATTERN = re.compile(r"([^/#\s]+)\s*$")


def authority_resources(actor):
    """Yield the authority file identifiers stated for an entity.

    Used for actors and for places, which state theirs the same way
    and differ only in the name of the element.

    Reading an identifier the source already carries is mapping, not
    the authority file enrichment the commission puts out of scope:
    nothing is looked up and nothing is added that the provider did
    not write down.

    """
    seen = set()
    candidates = (
        getattr(actor, "actor_id", None)
        or getattr(actor, "place_id", None)
        or []
    )
    for candidate in candidates:
        source = str(getattr(candidate, "source", "") or "").strip().lower()
        resource = AUTHORITY_RESOURCES.get(source)
        text = text_of(candidate)
        if resource is None or not text:
            continue
        match = AUTHORITY_ID_PATTERN.search(text.strip())
        if not match:
            continue
        identifier = match.group(1)
        if (source, identifier) in seen:
            continue
        seen.add((source, identifier))
        yield resource(id=identifier)


def build_publication_event(descriptive, profile, source_key):
    """Return the PublicationEvent described by the LIDO events."""
    lido_event = find_event(descriptive, profile.publication_event_terms)
    if lido_event is None:
        return None
    event = efi.PublicationEvent(
        type=efi.PublicationEventTypeEnum("ReleaseEvent")
    )
    date_value = event_date_value(lido_event)
    has_date = mapped_date(
        date_value,
        record_id=source_key,
        source_field="event[publication]/eventDate",
        target_field="has_event.has_date",
        map_decades=profile.map_decades,
    )
    if has_date:
        event.has_date = has_date
    add_places(event, lido_event)
    if not (event.has_date or event.located_in):
        return None
    return event


#: Where a value of the technical description belongs. The colour, the
#: sound, the element type and the six format vocabularies share no
#: value between them, so the value itself says which field it is
#: destined for and a provider does not have to keep the two in step.
TECHNICAL_TARGETS = {}
for _enum_name in dir(efi):
    if _enum_name == "ColourTypeEnum":
        _target, _wrapper = "has_colour_type", None
    elif _enum_name == "ItemElementTypeEnum":
        _target, _wrapper = "element_type", None
    elif _enum_name == "SoundTypeEnum":
        _target, _wrapper = "has_sound_type", None
    elif _enum_name.startswith("Format") and _enum_name.endswith("TypeEnum"):
        _target = "has_format"
        _wrapper = getattr(
            efi, _enum_name[len("Format") : -len("TypeEnum")], None
        )
        if _wrapper is None:
            continue
    else:
        continue
    for _member in getattr(efi, _enum_name):
        TECHNICAL_TARGETS.setdefault(_member.value, []).append(
            (_enum_name, _target, _wrapper)
        )
del _enum_name, _target, _wrapper, _member

#: Vocabularies this provider writes into the same field, which the
#: mapping recognises but does not act on. Deriving a publication or a
#: preservation event from a note about the material would be a
#: statement about the film that the note does not make, so the value
#: is reported and the decision left to the data provider.
TECHNICAL_OUT_OF_SCOPE = {
    member.value: name
    for name in ("PublicationEventTypeEnum", "PreservationEventTypeEnum")
    for member in getattr(efi, name)
}


def technical_terms(descriptive):
    """Yield the terms of the technical description with their concept.

    The concept identifier is what the provider says the term means.
    It is read as a cross check rather than as the answer, because a
    provider can name one vocabulary and write a value from another,
    and the reference data does exactly that.

    """
    wrap = descriptive.event_wrap
    if wrap is None:
        return
    for event_set in wrap.event_set or []:
        event = event_set.event
        if event is None:
            continue
        for materials_wrap in event.event_materials_tech or []:
            for materials in materials_wrap.materials_tech or []:
                for entry in materials.term_materials_tech or []:
                    term = text_of(first(entry.term))
                    if not term:
                        continue
                    concept = text_of(first(entry.concept_id)) or ""
                    yield term.strip(), concept.rsplit("/", 1)[-1]


def apply_technical_description(item, descriptive, profile, source_key):
    """Fill colour, format and element type from the material notes.

    A house term is translated first, and a term that is already an
    AVefi value is taken as it stands. That second step is what keeps
    the mapping from needing a commit every time the provider adds a
    carrier: the values are a closed set, so a term that is one of
    them means itself.

    """
    for term, concept in technical_terms(descriptive):
        if term.lower() in profile.empty_terms:
            continue
        value = profile.materials_tech_map.get(term.lower(), term)
        candidates = TECHNICAL_TARGETS.get(value)
        if not candidates:
            if value in TECHNICAL_OUT_OF_SCOPE:
                report_issue(
                    "info",
                    "Recognised as"
                    f" {TECHNICAL_OUT_OF_SCOPE[value]}, which this"
                    " mapping does not derive from a material note",
                    record_id=source_key,
                    source_field="termMaterialsTech",
                    target_field="—",
                    raw_value=term,
                )
                continue
            report_issue(
                "warning",
                "No AVefi value for this term of the technical description",
                record_id=source_key,
                source_field="termMaterialsTech",
                target_field=concept or "—",
                raw_value=term,
            )
            continue
        chosen = candidates[0]
        if len(candidates) > 1:
            named = [c for c in candidates if c[0] == concept]
            if not named:
                report_issue(
                    "warning",
                    "Term belongs to more than one vocabulary and the"
                    " record does not say which; not transferred",
                    record_id=source_key,
                    source_field="termMaterialsTech",
                    target_field="—",
                    raw_value=term,
                )
                continue
            chosen = named[0]
        enum_name, target, wrapper = chosen
        if concept and concept != enum_name:
            report_issue(
                "info",
                f"Record files this term under {concept}; it is a"
                f" {enum_name} value and is mapped as one",
                record_id=source_key,
                source_field="termMaterialsTech/conceptID",
                target_field=target,
                raw_value=term,
            )
        if target == "has_format":
            if not any(existing.type == value for existing in item.has_format):
                item.has_format.append(wrapper(type=value))
        elif getattr(item, target) is None:
            setattr(item, target, value)


def build_item(lido_record, descriptive, primary, profile, source_key):
    """Return the Item for one LIDO record.

    ``is_item_of`` is filled in by the caller, once the manifestation
    this copy belongs to is known.

    """
    item = efi.Item(
        is_item_of=efi.LocalResource(id="__pending__"),
        has_primary_title=as_title(primary, "TitleProper"),
    )

    duration_value, duration_unit = duration_measurement(descriptive, profile)
    if duration_value:
        has_value = mapped_duration(
            duration_value, duration_unit, record_id=source_key
        )
        if has_value:
            item.has_duration = efi.Duration(has_value=has_value)

    colour = mapped_classification(
        descriptive, profile, "colour", profile.colour_type_map, source_key
    )
    if colour:
        item.has_colour_type = efi.ColourTypeEnum(colour)
    access = mapped_classification(
        descriptive,
        profile,
        "access",
        profile.access_status_map,
        source_key,
    )
    if access:
        item.has_access_status = efi.ItemAccessStatusEnum(access)
    film_format = mapped_classification(
        descriptive, profile, "format", profile.format_map, source_key
    )
    if film_format:
        item.has_format.append(
            efi.Film(type=efi.FormatFilmTypeEnum(film_format))
        )
    # After the technical description: the plausibility check needs
    # the format to know how fast the film runs.
    apply_technical_description(item, descriptive, profile, source_key)
    apply_extent(item, descriptive, profile, source_key)
    # Before the keywords, because one of them can only be stated
    # about a copy that carries an identifier.
    for identifier in avefi_identifiers(lido_record, profile, source_key):
        item.has_identifier.append(identifier)
    # Before the keyword routing, so that a language the record has
    # already placed by its label is not placed a second time as the
    # spoken one.
    apply_language_usages(item, descriptive, profile, source_key)
    apply_keyword_classifications(item, descriptive, profile, source_key)
    for link in (
        *web_resources(lido_record),
        *published_web_resources(lido_record, profile),
    ):
        if link not in item.has_webresource:
            item.has_webresource.append(link)
    return item


def published_web_resources(lido_record, profile):
    """Yield the published addresses of the object itself.

    ``lido:objectPublishedID`` holds whatever the provider publishes
    the object under, which is a mixture: the AVefi handle, read as
    the copy's identifier, and the address of the object's page in the
    provider's own system, which is a link to it and nothing else.
    The value tells them apart. Its ``lido:type`` does not — this
    provider types the page address as a local identifier, and it is
    a URL whatever the type says.

    """
    for published in lido_record.object_published_id or []:
        text = (text_of(published) or "").strip()
        if not text or not is_absolute_url(text):
            continue
        if issued_by_avefi(published, text, profile):
            continue
        yield text


def avefi_identifiers(lido_record, profile, source_key):
    """Yield the AVefi identifiers a record already carries.

    A provider whose holdings have been registered gets the handles
    back into its own system, and exports them again the next time.
    Ignoring them means the next conversion mints a second identifier
    for a copy that has one, and a handle cannot be withdrawn once it
    is out. Reading them turns a re-import into an update.

    Here they are only ever the copy's: a record describes one object,
    and the object is the copy, so ``objectPublishedID`` is the copy's
    identifier. The work and the manifestation carry one as well, and
    a record states them in the relations it has to them; see
    :func:`related_works` and :func:`manifestation_relations`.

    """
    seen = set()
    for published in lido_record.object_published_id or []:
        text = (text_of(published) or "").strip()
        if not text or not issued_by_avefi(published, text, profile):
            continue
        handle = avefi_handle(text)
        if not handle or handle in seen:
            continue
        seen.add(handle)
        report_issue(
            "info",
            "Copy already carries an AVefi identifier; transferred"
            " rather than minted again",
            record_id=source_key,
            source_field="objectPublishedID",
            target_field="has_identifier",
            raw_value=handle,
        )
        yield efi.AVefiResource(id=handle)


# --- LIDO traversal helpers -------------------------------------------


def term_text(term) -> str | None:
    """Return the text of a lido:term style element."""
    if term is None:
        return None
    inner = getattr(term, "term", None)
    if inner:
        return text_of(first(inner))
    return text_of(term)


def record_identifier(lido_record: Lido, profile=None) -> str:
    """Return the local identifier of a LIDO record.

    A provider commonly prefixes the identifier with namespaces of its
    own — ``DE-MUS-042628:DE-MUS-432511:1059195`` — while the rest of
    its data, and the export the other importer for the same
    institution reads, uses the bare ``1059195``. The two have to
    agree, or the same copy carries two different source keys
    depending on which importer ran, and nothing can be matched
    between them. ``source_key_pattern`` in the profile says which
    part is the identifier.

    """
    for candidate in lido_record.lido_rec_id or []:
        text = text_of(candidate)
        if text:
            return local_source_key(text, profile)
    for administrative in lido_record.administrative_metadata or []:
        record_wrap = administrative.record_wrap
        if record_wrap is None:
            continue
        for candidate in record_wrap.record_id or []:
            text = text_of(candidate)
            if text:
                return local_source_key(text, profile)
    raise ValueError("LIDO record without lidoRecID or recordID")


def local_source_key(text: str, profile=None) -> str:
    """Return the part of a record identifier that identifies it."""
    pattern = getattr(profile, "source_key_pattern", None)
    if not pattern:
        return text
    match = re.search(pattern, text)
    if not match:
        return text
    return match.group(1) if match.groups() else match.group(0)


def source_title(raw, profile, source_key, target_field) -> SourceTitle | None:
    """Return a title as the source states it, or None if it is empty.

    One reading of one string, so that a title arriving through the
    related work is understood the same way as one in the titleWrap.
    Square brackets mark a title the cataloguer supplied rather than
    read off the film, here as everywhere, and an article is moved for
    the ordering name here as everywhere.

    """
    value = (raw or "").strip()
    supplied = value.startswith("[") and value.endswith("]")
    if supplied:
        value = value[1:-1].strip()
    if not value:
        return None
    display, ordering = normalise_title(
        value,
        profile.default_language,
        record_id=source_key,
        target_field=target_field,
    )
    return SourceTitle(display, ordering, supplied)


def collect_titles(descriptive, profile, source_key) -> list[SourceTitle]:
    """Return the titles of a record, preferred one first."""
    wrap = getattr(descriptive.object_identification_wrap, "title_wrap", None)
    if wrap is None:
        return []
    preferred, others = [], []
    for title_set in wrap.title_set or []:
        for appellation in title_set.appellation_value or []:
            raw = text_of(appellation)
            if not raw:
                continue
            supplied = raw.startswith("[") and raw.endswith("]")
            value = raw[1:-1].strip() if supplied else raw
            if not value:
                continue
            language = (
                language_code(getattr(appellation, "lang", None))
                or profile.default_language
            )
            is_preferred = (
                str(getattr(title_set, "type_value", "") or "").lower()
                == "preferred"
                or str(getattr(appellation, "pref", "") or "").lower()
                == "preferred"
            )
            target_field = (
                "has_primary_title.has_ordering_name"
                if is_preferred
                else "has_alternative_title.has_ordering_name"
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
                    source_field="titleSet/appellationValue",
                    target_field=target_field,
                    raw_value=raw,
                )
            title = SourceTitle(display, ordering, supplied)
            (preferred if is_preferred else others).append(title)
    return preferred + others


def classifications(descriptive):
    """Yield the classification elements of a record."""
    wrap = getattr(
        descriptive.object_classification_wrap, "classification_wrap", None
    )
    if wrap is None:
        return
    yield from wrap.classification or []


def classification_type_values(profile, target: str) -> tuple:
    """Return the lido:type values marking a classification.

    LIDO leaves the value of ``lido:type`` to the provider, so the
    labels for colour, format and access status are configuration, not
    part of the standard.

    """
    values = profile.classification_types.get(target, (target,))
    return tuple(str(value).lower() for value in values)


def consumed_classification_types(profile) -> set:
    """Return the lido:type values a vocabulary rule consumes."""
    return {
        value
        for target in profile.classification_types
        for value in classification_type_values(profile, target)
    } | {str(value).lower() for value in profile.keyword_classification_types}


def classification_terms(descriptive, profile):
    """Yield classification terms not consumed by a vocabulary rule."""
    consumed = consumed_classification_types(profile)
    labelled = labelled_language_terms(profile)
    for classification in classifications(descriptive):
        type_value = str(
            getattr(classification, "type_value", "") or ""
        ).lower()
        if type_value in consumed:
            continue
        for term in classification.term or []:
            if term_label(term) in labelled:
                # A language of the copy, not a genre of the film.
                continue
            text = text_of(term)
            if text:
                yield text
            break


def mapped_classification(
    descriptive, profile, target, vocabulary, source_key
):
    """Return the AVefi value for a typed classification, if mappable."""
    if not vocabulary:
        return None
    wanted = classification_type_values(profile, target)
    for classification in classifications(descriptive):
        type_value = str(
            getattr(classification, "type_value", "") or ""
        ).lower()
        if type_value not in wanted:
            continue
        text = term_text(classification)
        if not text:
            continue
        mapped = vocabulary.get(text.lower())
        if mapped is None:
            report_issue(
                "warning",
                f"No AVefi value configured for {target} term",
                record_id=source_key,
                source_field=f"classification[@type='{type_value}']",
                target_field=target,
                raw_value=text,
            )
            return None
        return mapped
    return None


def term_label(term) -> str:
    """Return the lido:label of a term, lower case."""
    return str(getattr(term, "label", "") or "").strip().lower()


def language_usage_terms(descriptive, profile):
    """Yield the language terms whose lido:label states their usage.

    A provider records the languages of a copy as terms and writes on
    the term what each one is for — "Dialogton", "Untertitel",
    "Zwischentitel". The label is the only thing that tells them
    apart: the terms themselves all say "Englisch" or "Deutsch", and
    without reading it an English subtitle track arrives as an English
    soundtrack.

    Every classification is looked at, whatever it is called. Which
    heading a provider files its languages under is its own business
    and says nothing about them; the label does.

    """
    if not profile.language_usage_labels:
        return
    labels = {
        str(key).lower(): value
        for key, value in profile.language_usage_labels.items()
    }
    for classification in classifications(descriptive):
        for term in classification.term or []:
            label = term_label(term)
            if not label:
                continue
            text = (text_of(term) or "").strip()
            if not text:
                continue
            yield label, labels.get(label), text


def labelled_language_terms(profile) -> set:
    """Return the labels a language usage is configured for."""
    return {str(key).lower() for key in profile.language_usage_labels}


def apply_language_usages(item, descriptive, profile, source_key):
    """Record the languages of a copy with the usage stated for them."""
    for label, usage, text in language_usage_terms(descriptive, profile):
        key = text.lower()
        if usage is None:
            if key in profile.language_name_map or key in (
                profile.no_dialogue_terms
            ):
                report_issue(
                    "warning",
                    "No AVefi language usage configured for this label,"
                    " so the language is not transferred",
                    record_id=source_key,
                    source_field="classification/term[@lido:label]",
                    target_field="in_language.usage",
                    raw_value=f"{label}: {text}",
                )
            continue
        if key in profile.no_dialogue_terms:
            # "Ohne Sprache" under a dialogue label is a statement
            # about the copy, not a language of it.
            add_language(item, None, "NoDialogue")
            continue
        code = profile.language_name_map.get(key)
        if code is None:
            report_issue(
                "warning",
                "No ISO 639-2/B code configured for this language name",
                record_id=source_key,
                source_field="classification/term[@lido:label]",
                target_field="in_language.code",
                raw_value=f"{label}: {text}",
            )
            continue
        add_language(item, code, usage)


def apply_keyword_classifications(item, descriptive, profile, source_key):
    """Route the terms of a keyword classification by what they say.

    A provider may file the language of a copy, its access status and
    its working notes under one heading. The heading then says nothing
    about where a term belongs and the term has to say it: this
    provider writes "Deutsch", "Archivkopie" and "angedacht" into the
    same classification, and the first of them was arriving as a genre
    of the film.

    The language is recorded without stating how it is used. It is
    read as the spoken language, which is the common case and what
    the CSV importer for the same institution records, and the
    assumption is reported so that it is visible rather than implied.

    """
    wanted = {
        str(value).lower() for value in profile.keyword_classification_types
    }
    if not wanted:
        return
    labelled = labelled_language_terms(profile)
    for classification in classifications(descriptive):
        type_value = str(
            getattr(classification, "type_value", "") or ""
        ).lower()
        if type_value not in wanted:
            continue
        for term in classification.term or []:
            if term_label(term) in labelled:
                # The label already said what this language is for.
                continue
            text = text_of(term)
            if not text:
                continue
            text = text.strip()
            if text.lower() in profile.empty_terms:
                continue
            if apply_keyword_term(item, text, profile, source_key):
                continue
            report_issue(
                "warning",
                "No AVefi field for this keyword",
                record_id=source_key,
                source_field=f"classification[@type='{type_value}']",
                target_field="—",
                raw_value=text,
            )


def apply_keyword_term(item, text: str, profile, source_key) -> bool:
    """Place one keyword, returning True if it found a field."""
    key = text.lower()
    if key in profile.no_dialogue_terms:
        add_language(item, None, "NoDialogue")
        return True
    code = profile.language_name_map.get(key)
    if code:
        report_issue(
            "info",
            "Language recorded without a usage; read as the spoken language",
            record_id=source_key,
            source_field="classification/term",
            target_field="in_language.usage",
            raw_value=text,
        )
        add_language(item, code, "SpokenLanguage")
        return True
    access = profile.access_status_map.get(key)
    if access:
        if access == "Removed" and not has_avefi_identifier(item):
            # Removed says that something registered is gone. About a
            # copy that was never registered it says nothing, and
            # efi-conv check rejects the combination. Whether such a
            # copy belongs in a delivery at all is the provider's
            # decision, so the record is kept and the fact reported.
            report_issue(
                "warning",
                "Copy is marked as deaccessioned but carries no AVefi"
                " identifier, so no access status is set; whether it"
                " belongs in the delivery is for the data provider to"
                " decide",
                record_id=source_key,
                source_field="classification/term",
                target_field="has_access_status",
                raw_value=text,
            )
            return True
        if item.has_access_status is None:
            item.has_access_status = efi.ItemAccessStatusEnum(access)
        return True
    return False


def has_avefi_identifier(item) -> bool:
    """Return True if the copy carries a registered AVefi identifier."""
    return any(
        identifier.category == "avefi:AVefiResource"
        for identifier in item.has_identifier
    )


def add_language(item, code: str | None, usage: str) -> None:
    """Add a language to a copy, without repeating one it has.

    ``code`` may be None. "No dialogue" is a statement about the copy
    and not about a language, and the schema lets the code stand
    empty; putting zxx there, as this did, answers a question the
    source did not ask.

    """
    for existing in item.in_language:
        if existing.code == code:
            if usage not in (existing.usage or []):
                existing.usage.append(efi.LanguageUsageEnum(usage))
            return
    language = efi.Language(usage=[efi.LanguageUsageEnum(usage)])
    if code:
        language.code = efi.LanguageCodeEnum(code)
    item.in_language.append(language)


def measurements(descriptive):
    """Yield the measurements of a record as type, value and unit."""
    wrap = getattr(
        descriptive.object_identification_wrap,
        "object_measurements_wrap",
        None,
    )
    if wrap is None:
        return
    for measurements_set in wrap.object_measurements_set or []:
        entries = measurements_set.object_measurements
        if entries is None:
            continue
        for entry in entries.measurements_set or []:
            kind = text_of(first(entry.measurement_type))
            value = text_of(first(entry.measurement_value))
            if not kind or not value:
                continue
            yield kind, value, text_of(first(entry.measurement_unit))


def duration_measurement(descriptive, profile):
    """Return value and unit of the running time measurement."""
    for kind, value, unit in measurements(descriptive):
        if kind.lower() in profile.duration_measurement_terms:
            override = profile.duration_units.get(kind.lower())
            return value, override or unit
    return None, None


#: Metres of film per minute at 24 frames a second, by format. Used
#: only to notice that a stated length and a stated running time
#: cannot both be right, never to change either of them.
METRES_PER_MINUTE = {
    "35mmFilm": 27.36,
    "16mmFilm": 10.97,
    "8mmFilm": 4.01,
    "Super8mmFilm": 4.88,
}

#: How far the two may disagree before it is worth reporting. Generous
#: on purpose: prints run at other speeds, leaders and trailers are
#: counted or not, and a factor of three is still an ordinary record.
EXTENT_DISAGREEMENT_FACTOR = 10


def extent_measurement(descriptive, profile):
    """Return value and unit of the length measurement."""
    for kind, value, unit in measurements(descriptive):
        if kind.lower() in profile.extent_measurement_terms:
            return value, unit
    return None, None


def apply_extent(item, descriptive, profile, source_key):
    """Record the length of a copy, and check it against its duration."""
    value, unit = extent_measurement(descriptive, profile)
    if not value:
        return
    try:
        amount = float(str(value).replace(",", "."))
    except ValueError:
        report_issue(
            "warning",
            "Length is not a number",
            record_id=source_key,
            source_field="measurementsSet[length]",
            target_field="has_extent",
            raw_value=value,
        )
        return
    if round(amount) == 0:
        return
    mapped = profile.extent_unit_map.get(str(unit or "").strip().lower())
    if mapped is None:
        report_issue(
            "warning",
            "No AVefi unit configured for this measurement unit",
            record_id=source_key,
            source_field="measurementsSet[length]",
            target_field="has_extent.has_unit",
            raw_value=unit,
        )
        return
    item.has_extent = efi.Extent(
        has_value=amount, has_unit=efi.UnitEnum(mapped)
    )
    check_extent_against_duration(item, source_key, value, unit)


def check_extent_against_duration(item, source_key, value, unit) -> None:
    """Report a length and a running time that contradict each other.

    Both are transferred as the record states them. This only says
    that they cannot both be right, which is worth knowing before
    anybody computes with either: in the reference export the length
    column is labelled in metres and holds centimetres for two records
    in three.

    """
    if item.has_extent is None or item.has_duration is None:
        return
    speeds = [
        METRES_PER_MINUTE[str(fmt.type)]
        for fmt in item.has_format or []
        if str(fmt.type) in METRES_PER_MINUTE
    ]
    if len(speeds) != 1 or item.has_extent.has_unit != "Metre":
        return
    minutes = iso_duration_minutes(item.has_duration.has_value)
    if not minutes:
        return
    expected = minutes * speeds[0]
    # has_value is a Decimal in the schema; the comparison is about
    # orders of magnitude, so float is the right precision for it.
    ratio = float(item.has_extent.has_value) / expected
    if 1 / EXTENT_DISAGREEMENT_FACTOR <= ratio <= EXTENT_DISAGREEMENT_FACTOR:
        return
    report_issue(
        "info",
        f"Length and running time disagree by a factor of"
        f" {ratio:.0f}; both are transferred as stated, but the unit"
        f" of one of them is not what the record says it is",
        record_id=source_key,
        source_field="measurementsSet[length]",
        target_field="has_extent.has_value",
        raw_value=f"{value} {unit or ''}".strip(),
    )


def iso_duration_minutes(value: str | None) -> float | None:
    """Return an ISODurationInHours as a number of minutes."""
    if not value:
        return None
    match = re.match(r"^PT(\d+)H(\d\d)M(\d\d)S$", value)
    if not match:
        return None
    hours, minutes, seconds = (int(part) for part in match.groups())
    total = hours * 60 + minutes + seconds / 60
    return total or None


def find_event(descriptive, terms):
    """Return the first event whose type matches ``terms``."""
    wrap = descriptive.event_wrap
    if wrap is None:
        return None
    for event_set in wrap.event_set or []:
        event = event_set.event
        if event is None:
            continue
        text = term_text(event.event_type)
        if text and text.lower() in terms:
            return event
    return None


def event_date_value(lido_event) -> str | None:
    """Return the most specific date expression of an event."""
    date_set = lido_event.event_date
    if date_set is None:
        return None
    date = getattr(date_set, "date", None)
    if date is not None:
        earliest = text_of(getattr(date, "earliest_date", None))
        latest = text_of(getattr(date, "latest_date", None))
        if earliest and latest and earliest != latest:
            return f"{earliest}/{latest}"
        if earliest or latest:
            return earliest or latest
    return text_of(first(getattr(date_set, "display_date", None)))


def place_name(place_wrap) -> str | None:
    """Return the name of an eventPlace element."""
    place = getattr(place_wrap, "place", None) or place_wrap
    for name_set in getattr(place, "name_place_set", None) or []:
        for appellation in name_set.appellation_value or []:
            text = text_of(appellation)
            if text:
                return text
    return None


def build_place(place_wrap, name: str):
    """Return the GeographicName for an eventPlace element.

    The name is taken as the source gives it. A holdings record saying
    "Deutsches Reich" or "DDR" is stating the country a film was made
    in at the time it was made, which is not the same country that
    stands there today, and normalising it away would be losing the
    part that is worth having. Where the record carries an authority
    identifier, that is what resolves the spelling.

    """
    place = efi.GeographicName(has_name=name)
    for authority in authority_resources(
        getattr(place_wrap, "place", None) or place_wrap
    ):
        place.same_as.append(authority)
    return place


def add_places(event, lido_event) -> None:
    """Add the places of a LIDO event, without repeating one."""
    for place_wrap in lido_event.event_place or []:
        name = place_name(place_wrap)
        if not name:
            continue
        place = build_place(place_wrap, name)
        identifiers = {(a.category, a.id) for a in place.same_as}
        if any(
            existing.has_name == name
            and {(a.category, a.id) for a in existing.same_as} == identifiers
            for existing in event.located_in
        ):
            continue
        event.located_in.append(place)


def actor_name(in_role) -> str | None:
    """Return the name of an actorInRole element."""
    actor = getattr(in_role, "actor", None)
    if actor is None:
        return None
    for name_set in actor.name_actor_set or []:
        for appellation in name_set.appellation_value or []:
            text = text_of(appellation)
            if text:
                return text
    return None


def web_resources(lido_record: Lido):
    """Yield the link resources of a record."""
    for administrative in lido_record.administrative_metadata or []:
        wrap = administrative.resource_wrap
        if wrap is None:
            continue
        for resource_set in wrap.resource_set or []:
            for representation in resource_set.resource_representation or []:
                link = text_of(
                    getattr(representation, "link_resource", None)
                    or first(getattr(representation, "link_resource", None))
                )
                if link:
                    yield link
