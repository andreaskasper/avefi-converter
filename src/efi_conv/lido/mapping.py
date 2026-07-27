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
import pathlib

from avefi_schema import model_pydantic_v2 as efi

from ..core.normalise import (
    NormalisationError,
    language_code,
    normalise_date,
    normalise_duration,
    normalise_title,
)
from ..core.records import (
    GroupingContext,
    SourceTitle,
    as_title,
    attach_source_key,
    make_key,
    merge_alternative_titles,
)
from ..core.report import for_file, report_issue
from ..core.xmlrecords import first, text_of, xml_parser
from .generated.lido_1_1 import Lido, LidoWrap
from .profile import LidoProfile

log = logging.getLogger(__name__)


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
        notes="Classifications typed as colour, format or access"
        " status are consumed by those rules instead",
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
        "has_event.located_in.has_name",
    ),
    MappingRule(
        "director",
        "Work",
        "lido:event[production]/lido:eventActor/lido:actorInRole"
        "[role in director terms]",
        "has_event.has_activity (DirectingActivity)",
        notes="Placeholder names such as 'unbekannt' are skipped and reported",
    ),
    MappingRule(
        "other_agent",
        "Work",
        "lido:event[production]/lido:eventActor/lido:actorInRole"
        " (remaining roles)",
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
        "lido:classification[@lido:type='colour'], profile vocabulary",
        "has_colour_type",
        "Profile vocabulary",
    ),
    MappingRule(
        "format",
        "Item",
        "lido:classification[@lido:type='format'], profile vocabulary",
        "has_format (Film)",
        "Profile vocabulary",
    ),
    MappingRule(
        "access_status",
        "Item",
        "lido:classification[@lido:type='access'], profile vocabulary",
        "has_access_status",
        "Profile vocabulary",
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
    "Decade expressions such as `50er Jahre` are reported as"
    " unconvertible. Enabling `map_decades` maps them to a closed ten"
    " year interval and reads two digit decades as twentieth century.",
    "`ca.` and `um` become the ISODate approximation qualifier `~`, a"
    " trailing question mark becomes `?`.",
    "A running time given as a bare number without a unit is read as minutes.",
    "Clock notation with two components, such as `1:43`, is read as"
    " minutes and seconds, not as hours and minutes.",
    "A date such as `2003-04` is read as an ISO year and month. Note"
    " that `fmdu/csv.py` reads the same notation as the interval"
    " 2003 to 2004; the divergence is reported per occurrence.",
    "Only the first `lido:descriptiveMetadata` block of a record is"
    " mapped; further blocks are reported.",
    "The article lists are provisional and are to be confirmed against"
    " the reference data.",
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


def parse_lido(input_file) -> list[Lido]:
    """Parse a LIDO document and return its records."""
    parser = xml_parser()
    path = pathlib.Path(input_file)
    try:
        wrap = parser.parse(str(path), LidoWrap)
    except Exception:
        # A document may carry a single lido:lido element as its root.
        return [parser.parse(str(path), Lido)]
    return list(wrap.lido)


def efi_import(
    input_file, profile: LidoProfile, continue_on_error: bool = False
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

    """
    records = []
    context = MappingContext(profile=profile)
    with for_file(input_file):
        for lido_record in parse_lido(input_file):
            try:
                records.extend(map_record(lido_record, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_issue(
                    "error",
                    f"Record skipped: {e}",
                    record_id=safe_record_identifier(lido_record),
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
        work = build_work(descriptive, primary, alternatives, source_key)
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
    item.has_identifier.append(efi.LocalResource(id=source_key))
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
    parts = []
    for name in profile.work_key_fields:
        if name == "primary_title":
            parts.append(primary.ordering or primary.display)
        elif name == "director":
            parts.append(director_names(production))
        elif name == "date":
            parts.append(
                production.has_date
                if production is not None and production.has_date
                else ""
            )
        else:
            raise ValueError(f"Unknown work key field: {name}")
    return make_key(*parts)


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


def build_work(descriptive, primary, alternatives, source_key):
    """Return the WorkVariant for one LIDO record."""
    work = efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=as_title(primary, "PreferredTitle"),
    )
    for title in alternatives:
        work.has_alternative_title.append(as_title(title, "AlternativeTitle"))
    for term in classification_terms(descriptive, source_key):
        work.has_genre.append(efi.Genre(has_name=term))
    return work


def build_production_event(descriptive, profile, source_key):
    """Return the ProductionEvent described by the LIDO events."""
    lido_event = find_event(descriptive, profile.production_event_terms)
    if lido_event is None:
        return None
    event = efi.ProductionEvent()

    date_value = event_date_value(lido_event)
    try:
        has_date = normalise_date(
            date_value,
            record_id=source_key,
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=source_key,
            source_field="eventDate",
            target_field="has_event.has_date",
            raw_value=date_value,
        )
        raise
    if has_date:
        event.has_date = has_date

    for place in lido_event.event_place or []:
        name = place_name(place)
        if name:
            event.located_in.append(efi.GeographicName(has_name=name))

    directors = []
    for actor_wrap in lido_event.event_actor or []:
        in_role = actor_wrap.actor_in_role
        if in_role is None:
            continue
        name = actor_name(in_role)
        role = term_text(first(in_role.role_actor))
        if not name:
            continue
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
        if role and role.lower() in profile.director_role_terms:
            directors.append(
                efi.Agent(type=efi.AgentTypeEnum("Person"), has_name=name)
            )
        else:
            report_issue(
                "warning",
                "No AVefi activity mapped for this role, agent not"
                " transferred",
                record_id=source_key,
                source_field="eventActor/roleActor",
                target_field="has_event.has_activity",
                raw_value=role or name,
            )
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


def build_publication_event(descriptive, profile, source_key):
    """Return the PublicationEvent described by the LIDO events."""
    lido_event = find_event(descriptive, profile.publication_event_terms)
    if lido_event is None:
        return None
    event = efi.PublicationEvent(
        type=efi.PublicationEventTypeEnum("ReleaseEvent")
    )
    date_value = event_date_value(lido_event)
    try:
        has_date = normalise_date(
            date_value,
            record_id=source_key,
            source_field="event[publication]/eventDate",
            target_field="has_event.has_date",
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=source_key,
            source_field="event[publication]/eventDate",
            target_field="has_event.has_date",
            raw_value=date_value,
        )
        raise
    if has_date:
        event.has_date = has_date
    for place in lido_event.event_place or []:
        name = place_name(place)
        if name:
            event.located_in.append(efi.GeographicName(has_name=name))
    if not (event.has_date or event.located_in):
        return None
    return event


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
        try:
            has_value = normalise_duration(
                duration_value, duration_unit, record_id=source_key
            )
        except NormalisationError as e:
            report_issue(
                "error",
                str(e),
                record_id=source_key,
                source_field="measurementsSet",
                target_field="has_duration.has_value",
                raw_value=duration_value,
            )
            raise
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
    for link in web_resources(lido_record):
        item.has_webresource.append(link)
    return item


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


def classification_terms(descriptive, profile, kind="genre"):
    """Yield classification terms not consumed by a vocabulary rule."""
    consumed = {"colour", "format", "access"}
    for classification in classifications(descriptive):
        type_value = str(
            getattr(classification, "type_value", "") or ""
        ).lower()
        if kind == "genre" and type_value in consumed:
            continue
        text = term_text(classification)
        if text:
            yield text


def mapped_classification(
    descriptive, profile, type_value, vocabulary, source_key
):
    """Return the AVefi value for a typed classification, if mappable."""
    if not vocabulary:
        return None
    for classification in classifications(descriptive):
        if (
            str(getattr(classification, "type_value", "") or "").lower()
            != type_value
        ):
            continue
        text = term_text(classification)
        if not text:
            continue
        mapped = vocabulary.get(text.lower())
        if mapped is None:
            report_issue(
                "warning",
                f"No AVefi value configured for {type_value} term",
                record_id=source_key,
                source_field=f"classification[@type='{type_value}']",
                target_field=type_value,
                raw_value=text,
            )
            return None
        return mapped
    return None


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
            if value:
                return value, unit
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
