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
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig

from ..core.report import for_file, report_issue
from ..core.utils import described_by_issuer
from .generated.lido_1_1 import Lido, LidoWrap
from .normalise import (
    NormalisationError,
    language_code,
    normalise_date,
    normalise_duration,
    normalise_title,
)
from .profile import LidoProfile

log = logging.getLogger(__name__)

# The input comes from third parties, so entity resolution and DTD
# loading are disabled deliberately rather than inherited from whatever
# defaults the installed xsdata and lxml versions happen to have.
PARSER_CONFIG = ParserConfig(
    process_xinclude=False,
    load_dtd=False,
    fail_on_unknown_properties=False,
    fail_on_unknown_attributes=False,
)


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
    return "\n".join(lines) + "\n"


def parse_lido(input_file) -> list[Lido]:
    """Parse a LIDO document and return its records."""
    parser = XmlParser(config=PARSER_CONFIG, context=XmlContext())
    path = pathlib.Path(input_file)
    try:
        wrap = parser.parse(str(path), LidoWrap)
    except Exception:
        # A document may carry a single lido:lido element as its root.
        return [parser.parse(str(path), Lido)]
    return list(wrap.lido)


def efi_import(
    input_file, profile: LidoProfile
) -> list[efi.MovingImageRecord]:
    """Convert a LIDO file into AVefi records using ``profile``."""
    records = []
    with for_file(input_file):
        for lido_record in parse_lido(input_file):
            records.extend(map_record(lido_record, profile))
    return records


def map_record(
    lido_record: Lido, profile: LidoProfile
) -> list[efi.MovingImageRecord]:
    """Return work, manifestation and item for one LIDO record."""
    source_key = record_identifier(lido_record)
    descriptive = first(lido_record.descriptive_metadata)
    if descriptive is None:
        raise ValueError(
            f"LIDO record {source_key} has no descriptiveMetadata"
        )

    titles = collect_titles(descriptive, profile, source_key)
    if not titles:
        raise ValueError(f"LIDO record {source_key} has no usable title")
    primary, alternatives = titles[0], titles[1:]

    work = build_work(descriptive, primary, alternatives, profile, source_key)
    work_id = efi.LocalResource(id=f"{source_key}_work")
    work.has_identifier.append(work_id)

    manifestation = efi.Manifestation(
        is_manifestation_of=[work_id],
        has_primary_title=as_title(primary, "TitleProper"),
    )
    manifestation_id = efi.LocalResource(id=f"{source_key}_manifestation")
    manifestation.has_identifier.append(manifestation_id)

    item = build_item(
        lido_record,
        descriptive,
        primary,
        profile,
        source_key,
        manifestation_id,
    )
    item.has_identifier.append(efi.LocalResource(id=source_key))

    for record in (work, manifestation, item):
        described_by = described_by_issuer(record, profile.issuer_info)
        if described_by.has_source_key is None:
            described_by.has_source_key = []
        if source_key not in described_by.has_source_key:
            described_by.has_source_key.append(source_key)
    return [work, manifestation, item]


def build_work(descriptive, primary, alternatives, profile, source_key):
    """Return the WorkVariant for one LIDO record."""
    work = efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=as_title(primary, "PreferredTitle"),
    )
    for title in alternatives:
        work.has_alternative_title.append(as_title(title, "AlternativeTitle"))
    for term in classification_terms(descriptive, profile, kind="genre"):
        work.has_genre.append(efi.Genre(has_name=term))

    event = build_production_event(descriptive, profile, source_key)
    if event is not None:
        work.has_event.append(event)
    return work


def build_production_event(descriptive, profile, source_key):
    """Return the ProductionEvent described by the LIDO events."""
    lido_event = find_event(descriptive, profile.production_event_terms)
    if lido_event is None:
        return None
    event = efi.ProductionEvent()

    date_value = event_date_value(lido_event)
    try:
        has_date = normalise_date(date_value, record_id=source_key)
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


def build_item(
    lido_record,
    descriptive,
    primary,
    profile,
    source_key,
    manifestation_id,
):
    """Return the Item for one LIDO record."""
    item = efi.Item(
        is_item_of=manifestation_id,
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


def first(sequence):
    """Return the first element of ``sequence`` or None."""
    if not sequence:
        return None
    if isinstance(sequence, (list, tuple)):
        return sequence[0] if sequence else None
    return sequence


def text_of(element) -> str | None:
    """Return the string value of a LIDO element, if any.

    LIDO declares several elements as mixed content, which xsdata maps
    to a ``content`` list rather than to a ``value`` attribute, so both
    have to be considered.

    """
    if element is None:
        return None
    if isinstance(element, str):
        text = element.strip()
        return text or None
    value = getattr(element, "value", None)
    if value is None:
        content = getattr(element, "content", None)
        if content:
            value = " ".join(
                part.strip()
                for part in content
                if isinstance(part, str) and part.strip()
            )
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


@dataclass(frozen=True)
class SourceTitle:
    """A title as found in the LIDO document."""

    display: str
    ordering: str | None
    supplied: bool


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
            display, ordering = normalise_title(value, language)
            if ordering and ordering != display:
                report_issue(
                    "info",
                    "Derived ordering name from article position",
                    record_id=source_key,
                    source_field="titleSet/appellationValue",
                    target_field="has_primary_title.has_ordering_name",
                    raw_value=raw,
                )
            title = SourceTitle(display, ordering, supplied)
            is_preferred = (
                str(getattr(title_set, "type_value", "") or "").lower()
                == "preferred"
                or str(getattr(appellation, "pref", "") or "").lower()
                == "preferred"
            )
            (preferred if is_preferred else others).append(title)
    return preferred + others


def as_title(title: SourceTitle, type_hint: str) -> efi.Title:
    """Return an AVefi title for a parsed source title."""
    title_type = "SuppliedDevisedTitle" if title.supplied else type_hint
    result = efi.Title(
        type=efi.TitleTypeEnum(title_type), has_name=title.display
    )
    if title.ordering:
        result.has_ordering_name = title.ordering
    return result


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
