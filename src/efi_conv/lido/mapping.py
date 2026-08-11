"""Generic mapping from LIDO to the AVefi schema.

LIDO is a standard, so the traversal of the document is the same for
every data provider. Everything that differs between institutions —
issuer information, the vocabularies used inside the LIDO terms — is
supplied through a :class:`~efi_conv.lido.profile.LidoProfile`.

Every LIDO record yields a work, a manifestation and an item, mirroring
the structure the CSV importer produces for the same institution.

"""

from dataclasses import dataclass
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
from .profile import LidoProfile

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
        "film_filter",
        "Record",
        "lido:objectClassificationWrap/lido:objectWorkTypeWrap"
        "/lido:objectWorkType",
        "—",
        "Profile vocabulary",
        "Only holdings metadata about film is in scope. Records of"
        " another work type are skipped and reported; a record without"
        " a work type is skipped with a warning",
    ),
    MappingRule(
        "work_grouping",
        "Work",
        "primary title, director, production date",
        "has_identifier (work)",
        "Profile work_key_fields",
        "Several copies of one film share one WorkVariant, as in"
        " fmdu/csv.py; set work_key_fields to () for one work per"
        " record",
    ),
    MappingRule(
        "manifestation_grouping",
        "Manifestation",
        "work key plus colour type, format and languages of the copy",
        "has_identifier (manifestation)",
        notes="Copies agreeing on the carrier characteristics share a"
        " manifestation",
    ),
    MappingRule(
        "record_id",
        "Item",
        "lido:lidoRecID, else lido:administrativeMetadata"
        "/lido:recordWrap/lido:recordID",
        "has_identifier, described_by.has_source_key",
        notes="Local identifier; also used to derive the work and"
        " manifestation ids",
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
        "genre",
        "Work",
        "lido:objectClassificationWrap/lido:classificationWrap"
        "/lido:classification",
        "has_genre.has_name",
        notes="Classifications whose lido:type is named in the"
        " profile as carrying colour, format or access status are"
        " consumed by those rules instead",
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
        "ISODurationInHours",
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
        "lido:objectPublishedID carrying the AVefi handle prefix",
        "has_identifier (AVefiResource)",
        "Profile avefi_handle_prefix",
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
        "webresource",
        "Item",
        "lido:administrativeMetadata/lido:resourceWrap//lido:linkResource",
        "has_webresource",
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
    "Every record yields one item. Works and manifestations are shared"
    " between records according to the profile key, so several copies"
    " of one film do not produce several works.",
    "`WorkVariant.type` is always `Monographic`; serial and analytic"
    " works are not derived from LIDO.",
    "Actors are read from the production event and from an event of"
    " creation, because a provider may record the people separately"
    " from the making of the copy. The activities are production"
    " activities either way and are attached to the production event.",
    "Whether an agent is a `Person` or a `CorporateBody` is taken from"
    " `lido:type` and left unset where the source does not say."
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
                    e, record_id=safe_record_identifier(lido_record)
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


def new_context(profile: LidoProfile) -> MappingContext:
    """Return a grouping context for one conversion.

    Handed to :func:`efi_import` once per run rather than once per
    file, so that the works of a conversion are shared between the
    input files.

    """
    return MappingContext(profile=profile)


def map_record(
    lido_record: Lido,
    profile: LidoProfile,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one LIDO record."""
    if context is None:
        context = MappingContext(profile=profile)
    source_key = record_identifier(lido_record)
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

    if not is_film_record(descriptive, profile, source_key):
        return []

    titles = collect_titles(descriptive, profile, source_key)
    if not titles:
        raise ValueError(f"LIDO record {source_key} has no usable title")
    primary, alternatives = titles[0], titles[1:]

    production = build_production_event(descriptive, profile, source_key)
    publication = build_publication_event(descriptive, profile, source_key)

    new_records = []
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
    work_id = work.has_identifier[0]

    item = build_item(lido_record, descriptive, primary, profile, source_key)
    manifestation_key = make_manifestation_key(work_key, item)

    def new_manifestation():
        manifestation = efi.Manifestation(
            is_manifestation_of=[work_id],
            has_primary_title=as_title(primary, "TitleProper"),
        )
        if publication is not None:
            manifestation.has_event.append(publication)
        return manifestation

    manifestation, is_new = context.manifestation_for(
        manifestation_key, new_manifestation
    )
    if is_new:
        new_records.append(manifestation)
    item.is_item_of = manifestation.has_identifier[0]
    item.has_identifier.append(
        efi.LocalResource(id=local_identifier(source_key))
    )
    new_records.append(item)

    attach_source_key(
        (work, manifestation, item), profile.issuer_info, source_key
    )
    return new_records


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
                f"{language.code}:{','.join(sorted(language.usage or []))}"
                for language in item.in_language or []
            )
        ),
    ]
    return make_key(*parts)


def safe_record_identifier(lido_record) -> str | None:
    """Return the record identifier, or None if there is none."""
    try:
        return record_identifier(lido_record)
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
        work.has_genre.append(efi.Genre(has_name=term))
    return work


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
            agent = build_agent(in_role, name)
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


def build_agent(in_role, name: str):
    """Return the Agent for an actorInRole element.

    Whether the actor is a person or an organisation is read off
    ``lido:type`` rather than guessed from the name. Guessing is a
    documented non-goal, and it is also unnecessary here: the source
    states it.

    """
    actor = getattr(in_role, "actor", None)
    agent = efi.Agent(has_name=name)
    agent_type = agent_type_of(actor)
    if agent_type:
        agent.type = efi.AgentTypeEnum(agent_type)
    for authority in authority_resources(actor):
        agent.same_as.append(authority)
    return agent


def agent_type_of(actor) -> str | None:
    """Return Person or CorporateBody as stated by lido:type."""
    stated = str(getattr(actor, "type_value", "") or "").strip().lower()
    if stated in ("person", "personal"):
        return "Person"
    if stated in (
        "corporatebody",
        "corporate body",
        "koerperschaft",
        "körperschaft",
        "organisation",
        "organization",
        "group",
    ):
        return "CorporateBody"
    return None


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
    apply_technical_description(item, descriptive, profile, source_key)
    # Before the keywords, because one of them can only be stated
    # about a copy that carries an identifier.
    for identifier in avefi_identifiers(lido_record, profile, source_key):
        item.has_identifier.append(identifier)
    apply_keyword_classifications(item, descriptive, profile, source_key)
    for link in web_resources(lido_record):
        item.has_webresource.append(link)
    return item


def avefi_identifiers(lido_record, profile, source_key):
    """Yield the AVefi identifiers a record already carries.

    A provider whose holdings have been registered gets the handles
    back into its own system, and exports them again the next time.
    Ignoring them means the next conversion mints a second identifier
    for a copy that has one, and a handle cannot be withdrawn once it
    is out. Reading them turns a re-import into an update.

    They are only ever found on the copy. Work and manifestation
    identifiers exist too, but no LIDO record states them: a record
    describes one object, and the object is the copy.

    """
    prefix = profile.avefi_handle_prefix
    if not prefix:
        return
    pattern = re.compile(rf"\b({re.escape(prefix)}/[^\s\"'<>]+)")
    seen = set()
    for published in lido_record.object_published_id or []:
        text = text_of(published)
        if not text:
            continue
        match = pattern.search(text)
        if not match:
            continue
        handle = match.group(1)
        if handle in seen:
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


def record_identifier(lido_record: Lido) -> str:
    """Return the local identifier of a LIDO record."""
    for candidate in lido_record.lido_rec_id or []:
        text = text_of(candidate)
        if text:
            return text
    for administrative in lido_record.administrative_metadata or []:
        record_wrap = administrative.record_wrap
        if record_wrap is None:
            continue
        for candidate in record_wrap.record_id or []:
            text = text_of(candidate)
            if text:
                return text
    raise ValueError("LIDO record without lidoRecID or recordID")


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
    for classification in classifications(descriptive):
        type_value = str(
            getattr(classification, "type_value", "") or ""
        ).lower()
        if type_value in consumed:
            continue
        text = term_text(classification)
        if text:
            yield text


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
    for classification in classifications(descriptive):
        type_value = str(
            getattr(classification, "type_value", "") or ""
        ).lower()
        if type_value not in wanted:
            continue
        for term in classification.term or []:
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
        add_language(item, "zxx", "NoDialogue")
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


def add_language(item, code: str, usage: str) -> None:
    """Add a language to a copy, without repeating one it has."""
    for existing in item.in_language:
        if existing.code == code:
            if usage not in (existing.usage or []):
                existing.usage.append(efi.LanguageUsageEnum(usage))
            return
    item.in_language.append(
        efi.Language(
            code=efi.LanguageCodeEnum(code),
            usage=[efi.LanguageUsageEnum(usage)],
        )
    )


def duration_measurement(descriptive, profile):
    """Return value and unit of the running time measurement."""
    wrap = getattr(
        descriptive.object_identification_wrap,
        "object_measurements_wrap",
        None,
    )
    if wrap is None:
        return None, None
    for measurements_set in wrap.object_measurements_set or []:
        measurements = measurements_set.object_measurements
        if measurements is None:
            continue
        for entry in measurements.measurements_set or []:
            kind = text_of(first(entry.measurement_type))
            if not kind or kind.lower() not in (
                profile.duration_measurement_terms
            ):
                continue
            value = text_of(first(entry.measurement_value))
            unit = text_of(first(entry.measurement_unit))
            override = profile.duration_units.get(kind.lower())
            if value:
                return value, override or unit
    return None, None


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
