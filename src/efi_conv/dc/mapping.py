"""Mapping from unqualified Dublin Core (oai_dc) to the AVefi schema.

Dublin Core is the weakest of the supported inputs. It has fifteen
flat, repeatable and untyped elements, and that is all. It cannot
express the distinction between a work, a manifestation and a copy; it
does not say which ``dc:contributor`` directed the film; and
``dc:date`` does not say what happened on that date. Every record
therefore yields exactly one work, one manifestation and one item, and
the converter reports that those three levels are asserted rather than
found in the data.

The converter exists because oai_dc is the one metadata prefix every
OAI-PMH endpoint has to offer. A provider able to export LIDO, EN
15907 or MARC should export that instead.

Can be used through the common command line interface::

    efi-conv from -f dc -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.dc.mapping export.xml [records.json]

"""

from dataclasses import dataclass
import logging
import re
import sys

from avefi_schema import model_pydantic_v2 as efi
from lxml import etree

from ..core.normalise import (
    NormalisationError,
    language_code,
    normalise_date,
    normalise_title,
)
from ..core.records import (
    GroupingContext,
    SourceTitle,
    as_title,
    attach_source_key,
    make_key,
)
from ..core.report import for_file, report_issue
from ..core.xmlrecords import (
    LXML_SAFETY,
    iter_record_elements,
    qualified_name,
    text_of,
)
from .profile import DcProfile

log = logging.getLogger(__name__)

DESCRIPTION = (
    "Unqualified Dublin Core (oai_dc), any OAI-PMH endpoint;"
    " lossy by construction, see the package README"
)
INPUT_FORMAT = "XML (OAI-PMH oai_dc, unqualified Dublin Core)"

#: Placeholder issuer. Dublin Core says nothing about who holds the
#: material, and an ISIL must not be guessed, so the shipped value is
#: documented as a placeholder and reported once per run.
PLACEHOLDER_ISSUER_ID = "https://w3id.org/avefi/issuer/unspecified"
ISSUER_INFO = {
    "has_issuer_id": PLACEHOLDER_ISSUER_ID,
    "has_issuer_name": "Unspecified data provider",
}

#: Namespace of the oai_dc container and of the elements inside it.
OAI_DC_NAMESPACE = "http://www.openarchives.org/OAI/2.0/oai_dc/"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

#: The fifteen elements of unqualified Dublin Core, in schema order.
DC_ELEMENTS = (
    "title",
    "creator",
    "subject",
    "description",
    "publisher",
    "contributor",
    "date",
    "type",
    "format",
    "identifier",
    "source",
    "language",
    "relation",
    "coverage",
    "rights",
)

#: Elements that carry information AVefi has no place for. They are
#: reported per value rather than dropped in silence.
UNMAPPED_ELEMENTS = ("description", "coverage", "rights")

#: A value carrying a URI scheme, used to pick the source key.
URI_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:\S")
#: A value that can be shown as a link.
WEB_URI_PATTERN = re.compile(r"^https?://\S", re.IGNORECASE)

#: Carrier terms seen in ``dc:format`` of film holdings. Deliberately
#: short: a provider extends it in its own profile once its values are
#: known. Everything not listed is reported, not guessed.
FORMAT_MAP = {
    "8mm": "8mmFilm",
    "9,5mm": "9.5mmFilm",
    "9.5mm": "9.5mmFilm",
    "16mm": "16mmFilm",
    "17,5mm": "17.5mmFilm",
    "17.5mm": "17.5mmFilm",
    "35mm": "35mmFilm",
    "70mm": "70mmFilm",
    "super8": "Super8mmFilm",
    "super 8": "Super8mmFilm",
    "super16": "Super16mmFilm",
    "super 16": "Super16mmFilm",
}

#: Profile used when the converter is called through the common
#: command line interface. A provider copies this module's constants
#: into a profile of its own rather than editing them here.
#: Profile class a profile file is read into.
PROFILE_CLASS = DcProfile

PROFILE = DcProfile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    format_map=FORMAT_MAP,
)


@dataclass(frozen=True)
class MappingRule:
    """One documented mapping from a Dublin Core element to AVefi."""

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
        "dc:type",
        "—",
        "Profile film_type_terms",
        "Only holdings metadata about film is in scope. Records of"
        " another type are skipped and reported; a record without a"
        " dc:type is skipped with a warning",
    ),
    MappingRule(
        "record_id",
        "Item",
        "dc:identifier",
        "has_identifier, described_by.has_source_key",
        "A URI is preferred over a bare local number",
        "Further dc:identifier values become additional"
        " LocalResource identifiers of the item",
    ),
    MappingRule(
        "levels",
        "Work, Manifestation, Item",
        "—",
        "WorkVariant, Manifestation, Item",
        "One of each per record",
        "Dublin Core cannot express the distinction, so the three"
        " levels are asserted; reported per record at warning",
    ),
    MappingRule(
        "primary_title",
        "Work, Manifestation, Item",
        "dc:title (first)",
        "has_primary_title.has_name, has_primary_title.has_ordering_name",
        "Article handling in both directions",
        "The order of the elements in the record is the only clue"
        " available for picking the primary title",
    ),
    MappingRule(
        "alternative_title",
        "Work",
        "dc:title (remaining)",
        "has_alternative_title",
        "Article handling in both directions",
    ),
    MappingRule(
        "genre",
        "Work",
        "dc:subject, dc:type",
        "has_genre.has_name",
        notes="dc:type terms that identified the record as film are"
        " consumed by the film filter instead",
    ),
    MappingRule(
        "production_date",
        "Work",
        "dc:date (first)",
        "has_event.has_date (ProductionEvent)",
        "ISODate; abbreviated intervals expanded",
        "Dublin Core does not say what happened on the date; it is"
        " read as the production date. Further dc:date values are"
        " reported",
    ),
    MappingRule(
        "director",
        "Work",
        "dc:creator",
        "has_event.has_activity (DirectingActivity)",
        "Profile creator_is_director",
        "Only when the provider has confirmed that dc:creator holds"
        " the director; otherwise creators are reported as unmapped",
    ),
    MappingRule(
        "contributor",
        "Work",
        "dc:contributor",
        "—",
        notes="Dublin Core does not say in what capacity a"
        " contributor contributed, so no activity can be derived",
    ),
    MappingRule(
        "publisher",
        "Manifestation",
        "dc:publisher",
        "has_event.has_activity (ManifestationActivity, Publisher)",
        notes="PublicationEvent type is UnknownEvent, because Dublin"
        " Core does not say what kind of publication it was",
    ),
    MappingRule(
        "language",
        "Item",
        "dc:language",
        "in_language.code, in_language.usage",
        "ISO 639-2/B; profile language_usage",
        "Dublin Core does not say whether the language is spoken,"
        " written as an intertitle or used for subtitles",
    ),
    MappingRule(
        "format",
        "Item",
        "dc:format",
        "has_format (Film)",
        "Profile format_map",
        "dc:format is also used for MIME types and file sizes, which"
        " are reported rather than mapped",
    ),
    MappingRule(
        "webresource",
        "Item",
        "dc:relation, dc:source",
        "has_webresource",
        "Only values that are http(s) URIs",
        "Non-URI relations are reported; Dublin Core does not say"
        " what the relation is",
    ),
    MappingRule(
        "dropped",
        "—",
        "dc:description, dc:coverage, dc:rights",
        "—",
        notes="No AVefi target; reported per value so that the loss"
        " is visible in the conversion report",
    ),
    MappingRule(
        "issuer",
        "Work, Manifestation, Item",
        "profile issuer_info",
        "described_by.has_issuer_id, described_by.has_issuer_name",
        notes="Dublin Core does not name the holding institution."
        " The shipped value is a placeholder and is reported once per"
        " run",
    ),
)

MAPPING_RULES_BY_ID = {rule.id: rule for rule in MAPPING_RULES}


#: Decisions the mapping takes that Dublin Core does not determine.
#: They are listed in the generated documentation so that a reviewer
#: sees them without reading the code.
ASSUMPTIONS = (
    "Unqualified Dublin Core cannot express the distinction between a"
    " work, a manifestation and a copy. The converter asserts one of"
    " each per record and reports that it has done so. If an export"
    " actually describes several copies of one film, this converter"
    " will register identifiers for copies rather than for films.",
    "`dc:date` is read as the production date. Dublin Core does not"
    " say what happened on the date, so this is a convention, not a"
    " reading of the data.",
    "The first `dc:title` is the primary title. Element order is the"
    " only clue an oai_dc record offers.",
    "`dc:creator` is not read as the director unless the provider has"
    " confirmed that convention through `creator_is_director`."
    " `dc:contributor` is never read as a role, because Dublin Core"
    " does not record one.",
    "`dc:language` is recorded with the usage configured in the"
    " profile, `SpokenLanguage` by default. Dublin Core does not say"
    " whether a language is spoken, written as an intertitle or used"
    " for subtitles.",
    "A `dc:publisher` becomes a PublicationEvent of type"
    " `UnknownEvent`, because Dublin Core does not say what kind of"
    " publication took place.",
    "`WorkVariant.type` is always `Monographic`; serial and analytic"
    " works are not derivable from Dublin Core.",
    "A record without a recognised `dc:type` is skipped rather than"
    " imported as a film, as in the LIDO converter.",
    "The shipped issuer is the documented placeholder"
    " `https://w3id.org/avefi/issuer/unspecified`. It has to be"
    " replaced with the ISIL of the data provider before identifiers"
    " are registered; the converter reports this once per run.",
    "Decade expressions such as `50er Jahre` are reported as"
    " unconvertible unless `map_decades` is enabled, as in the LIDO"
    " converter.",
    "`dc:description`, `dc:coverage` and `dc:rights` have no AVefi"
    " target and are reported per value.",
)


def render_mapping_markdown(rules=MAPPING_RULES) -> str:
    """Return the mapping table as a Markdown document."""
    lines = [
        "# Dublin Core (oai_dc) to AVefi mapping",
        "",
        "Generated from `MAPPING_RULES` in `efi_conv.dc.mapping`;",
        "do not edit by hand.",
        "",
        "| Rule | Level | Dublin Core source | AVefi target |"
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
        "Decisions the mapping takes that Dublin Core does not"
        " determine, and that need confirming with the data provider:",
        "",
    ]
    lines += [f"- {assumption}" for assumption in ASSUMPTIONS]
    return "\n".join(lines) + "\n"


def parse_dc(input_file):
    """Yield the ``oai_dc:dc`` elements of a document.

    The schema is small enough that generated bindings would cost more
    than they save, so the records are read with lxml on top of the
    shared streaming reader. A document whose root is a single
    ``oai_dc:dc`` element and a document carrying many of them under a
    wrapper are both handled.

    Parameters
    ----------
    input_file
        Path of the oai_dc document.

    Yields
    ------
    lxml.etree._Element
        One ``oai_dc:dc`` element.

    """
    parser = etree.XMLParser(**LXML_SAFETY)
    for serialised in iter_record_elements(input_file, OAI_DC_NAMESPACE, "dc"):
        yield etree.fromstring(serialised, parser)


def efi_import(
    input_file, continue_on_error: bool = False
) -> list[efi.MovingImageRecord]:
    """Convert an oai_dc export into AVefi records."""
    return convert(input_file, PROFILE, continue_on_error)


def convert(
    input_file, profile: DcProfile, continue_on_error: bool = False
) -> list[efi.MovingImageRecord]:
    """Convert an oai_dc file into AVefi records using ``profile``.

    Parameters
    ----------
    input_file
        Path of the oai_dc document.
    profile : DcProfile
        Provider specific configuration.
    continue_on_error : bool
        Report a record that cannot be converted and carry on with the
        remaining ones, instead of aborting the whole file.

    """
    records = []
    context = GroupingContext()
    with for_file(input_file):
        report_placeholder_issuer(profile)
        for element in parse_dc(input_file):
            try:
                records.extend(map_record(element, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_issue(
                    "error",
                    f"Record skipped: {e}",
                    record_id=safe_source_key(element),
                )
    return records


def report_placeholder_issuer(profile: DcProfile):
    """Say once per run that the issuer still has to be supplied."""
    if profile.issuer_info.get("has_issuer_id") != PLACEHOLDER_ISSUER_ID:
        return
    report_issue(
        "warning",
        "The issuer information shipped with the Dublin Core converter"
        " is a documented placeholder. Replace it with the ISIL of the"
        " data provider before identifiers are registered",
        target_field="described_by.has_issuer_id",
        raw_value=PLACEHOLDER_ISSUER_ID,
    )


def map_record(
    element,
    profile: DcProfile,
    context: GroupingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one oai_dc record."""
    if context is None:
        context = GroupingContext()
    values = collect_values(element)
    source_key = source_key_of(values)
    if source_key is None:
        raise ValueError("oai_dc record without dc:identifier")

    if not is_film_record(values, profile, source_key):
        return []

    titles = collect_titles(values, profile, source_key)
    if not titles:
        raise ValueError(f"oai_dc record {source_key} has no dc:title")
    primary, alternatives = titles[0], titles[1:]

    report_issue(
        "warning",
        "Dublin Core does not distinguish work, manifestation and"
        " copy; one of each is asserted for this record",
        record_id=source_key,
        source_field="oai_dc:dc",
        target_field="WorkVariant, Manifestation, Item",
    )
    report_dropped_elements(values, source_key)

    production = build_production_event(values, profile, source_key)
    publication = build_publication_event(values, source_key)

    new_records = []

    def new_work():
        work = efi.WorkVariant(
            type=efi.WorkVariantTypeEnum("Monographic"),
            has_primary_title=as_title(primary, "PreferredTitle"),
        )
        for title in alternatives:
            work.has_alternative_title.append(
                as_title(title, "AlternativeTitle")
            )
        for term in genre_terms(values, profile):
            work.has_genre.append(efi.Genre(has_name=term))
        if production is not None:
            work.has_event.append(production)
        return work

    work, _ = context.work_for(make_key(source_key), new_work)
    new_records.append(work)
    work_id = work.has_identifier[0]

    def new_manifestation():
        manifestation = efi.Manifestation(
            is_manifestation_of=[work_id],
            has_primary_title=as_title(primary, "TitleProper"),
        )
        if publication is not None:
            manifestation.has_event.append(publication)
        return manifestation

    manifestation, _ = context.manifestation_for(
        make_key(source_key), new_manifestation
    )
    new_records.append(manifestation)

    item = build_item(values, profile, primary, source_key)
    item.is_item_of = manifestation.has_identifier[0]
    new_records.append(item)

    attach_source_key(new_records, profile.issuer_info, source_key)
    return new_records


def collect_values(element) -> dict[str, list[tuple[str, str | None]]]:
    """Return the Dublin Core values of a record, per element name.

    Returns
    -------
    dict
        Element name to a list of (value, xml:lang) pairs, in document
        order.

    """
    values = {}
    for name in DC_ELEMENTS:
        found = []
        for child in element.findall(qualified_name(DC_NAMESPACE, name)):
            text = text_of(child.text)
            if text:
                found.append((text, child.get(XML_LANG)))
        values[name] = found
    return values


def texts(values, name) -> list[str]:
    """Return the plain values recorded for one element name."""
    return [text for text, _ in values.get(name, ())]


def source_key_of(values) -> str | None:
    """Return the identifier a record is known by.

    A URI is preferred over a bare local number: it is the only kind
    of Dublin Core identifier that stays unambiguous once the records
    have left the provider.

    """
    identifiers = texts(values, "identifier")
    for identifier in identifiers:
        if URI_PATTERN.match(identifier):
            return identifier
    return identifiers[0] if identifiers else None


def safe_source_key(element) -> str | None:
    """Return the source key of a record, or None if there is none."""
    try:
        return source_key_of(collect_values(element))
    except Exception:  # pragma: no cover - defensive
        return None


def is_film_record(values, profile, source_key) -> bool:
    """Return True if the record describes film.

    Only holdings metadata about film is in scope. An oai_dc export of
    a museum or a repository holds photographs, texts and datasets in
    the same set, and none of them may become a film work.

    """
    if not profile.film_type_terms:
        return True
    terms = texts(values, "type")
    if not terms:
        report_issue(
            "warning",
            "Record has no dc:type, cannot tell film from other"
            " material; record skipped",
            record_id=source_key,
            source_field="dc:type",
            target_field="—",
        )
        return False
    if any(term.lower() in profile.film_type_terms for term in terms):
        return True
    report_issue(
        "info",
        "Record skipped: not a film holding",
        record_id=source_key,
        source_field="dc:type",
        target_field="—",
        raw_value=terms,
    )
    return False


def collect_titles(values, profile, source_key) -> list[SourceTitle]:
    """Return the titles of a record, in document order."""
    titles = []
    for index, (raw, lang) in enumerate(values.get("title", ())):
        target_field = (
            "has_primary_title.has_ordering_name"
            if index == 0
            else "has_alternative_title.has_ordering_name"
        )
        language = language_code(lang) or profile.default_language
        display, ordering = normalise_title(
            raw,
            language,
            record_id=source_key,
            target_field=target_field,
        )
        if ordering and ordering != display:
            report_issue(
                "info",
                "Derived ordering name from article position",
                record_id=source_key,
                source_field="dc:title",
                target_field=target_field,
                raw_value=raw,
            )
        titles.append(SourceTitle(display, ordering))
    return titles


def genre_terms(values, profile):
    """Yield the terms recorded as genre.

    ``dc:subject`` is the closest Dublin Core comes to a genre. The
    ``dc:type`` terms that identified the record as film carry no
    information about the film itself and are left to the film filter.

    """
    for term in texts(values, "subject"):
        yield term
    for term in texts(values, "type"):
        if term.lower() not in profile.film_type_terms:
            yield term


def build_production_event(values, profile, source_key):
    """Return the ProductionEvent a record supports, if any."""
    event = efi.ProductionEvent()
    dates = texts(values, "date")
    if dates:
        report_issue(
            "info",
            "Dublin Core does not say what happened on the date; it is"
            " read as the production date",
            record_id=source_key,
            source_field="dc:date",
            target_field="has_event.has_date",
            raw_value=dates[0],
        )
        try:
            has_date = normalise_date(
                dates[0],
                record_id=source_key,
                source_field="dc:date",
                target_field="has_event.has_date",
                map_decades=profile.map_decades,
            )
        except NormalisationError as e:
            report_issue(
                "error",
                str(e),
                record_id=source_key,
                source_field="dc:date",
                target_field="has_event.has_date",
                raw_value=dates[0],
            )
            raise
        if has_date:
            event.has_date = has_date
    for extra in dates[1:]:
        report_issue(
            "warning",
            "Only the first dc:date is mapped; Dublin Core does not"
            " say what the further dates refer to",
            record_id=source_key,
            source_field="dc:date",
            target_field="has_event.has_date",
            raw_value=extra,
        )

    directors = build_directors(values, profile, source_key)
    if directors:
        event.has_activity.append(
            efi.DirectingActivity(
                type=efi.DirectingActivityTypeEnum("Director"),
                has_agent=directors,
            )
        )
    for contributor in texts(values, "contributor"):
        report_issue(
            "warning",
            "Dublin Core does not say in what capacity a contributor"
            " contributed, no AVefi activity derived",
            record_id=source_key,
            source_field="dc:contributor",
            target_field="has_event.has_activity",
            raw_value=contributor,
        )
    if not (event.has_date or event.has_activity):
        return None
    return event


def build_directors(values, profile, source_key) -> list:
    """Return the agents a record supports as directors.

    Dublin Core does not say in what capacity a creator contributed,
    so this only happens when the provider has confirmed that its
    ``dc:creator`` holds the director.

    """
    creators = texts(values, "creator")
    if not creators:
        return []
    if not profile.creator_is_director:
        for creator in creators:
            report_issue(
                "warning",
                "dc:creator is not read as the director; enable"
                " creator_is_director in the profile once the provider"
                " has confirmed that convention",
                record_id=source_key,
                source_field="dc:creator",
                target_field="has_event.has_activity",
                raw_value=creator,
            )
        return []
    return [
        efi.Agent(type=efi.AgentTypeEnum("Person"), has_name=creator)
        for creator in creators
    ]


def build_publication_event(values, source_key):
    """Return the PublicationEvent a dc:publisher supports."""
    publishers = texts(values, "publisher")
    if not publishers:
        return None
    report_issue(
        "info",
        "Dublin Core does not say what kind of publication took"
        " place; recorded as UnknownEvent",
        record_id=source_key,
        source_field="dc:publisher",
        target_field="has_event.type",
        raw_value=publishers,
    )
    return efi.PublicationEvent(
        type=efi.PublicationEventTypeEnum("UnknownEvent"),
        has_activity=[
            efi.ManifestationActivity(
                type=efi.ManifestationActivityTypeEnum("Publisher"),
                has_agent=[
                    efi.Agent(
                        type=efi.AgentTypeEnum("CorporateBody"),
                        has_name=publisher,
                    )
                    for publisher in publishers
                ],
            )
        ],
    )


def build_item(values, profile, primary, source_key):
    """Return the Item for one oai_dc record.

    ``is_item_of`` is filled in by the caller, once the manifestation
    this copy belongs to is known.

    """
    item = efi.Item(
        is_item_of=efi.LocalResource(id="__pending__"),
        has_primary_title=as_title(primary, "TitleProper"),
    )
    item.has_identifier.append(efi.LocalResource(id=source_key))
    for identifier in texts(values, "identifier"):
        if identifier != source_key:
            item.has_identifier.append(efi.LocalResource(id=identifier))
    for language in build_languages(values, profile, source_key):
        item.in_language.append(language)
    for film_format in build_formats(values, profile, source_key):
        item.has_format.append(film_format)
    for link in build_webresources(values, source_key):
        item.has_webresource.append(link)
    return item


def build_languages(values, profile, source_key):
    """Yield the languages recorded for a record."""
    for tag in texts(values, "language"):
        code = language_code(tag)
        if code is None:
            report_issue(
                "warning",
                "No ISO 639-2/B code known for this language tag",
                record_id=source_key,
                source_field="dc:language",
                target_field="in_language.code",
                raw_value=tag,
            )
            continue
        report_issue(
            "info",
            "Dublin Core does not say how the language is used;"
            f" recorded as {profile.language_usage}",
            record_id=source_key,
            source_field="dc:language",
            target_field="in_language.usage",
            raw_value=tag,
        )
        yield efi.Language(
            code=efi.LanguageCodeEnum(code),
            usage=[efi.LanguageUsageEnum(profile.language_usage)],
        )


def build_formats(values, profile, source_key):
    """Yield the carrier formats recorded for a record."""
    for value in texts(values, "format"):
        mapped = profile.format_map.get(value.strip().lower())
        if mapped is None:
            report_issue(
                "warning",
                "No AVefi value configured for this dc:format term;"
                " note that dc:format is also used for MIME types and"
                " file sizes",
                record_id=source_key,
                source_field="dc:format",
                target_field="has_format",
                raw_value=value,
            )
            continue
        yield efi.Film(type=efi.FormatFilmTypeEnum(mapped))


def build_webresources(values, source_key):
    """Yield the links a record offers, reporting the other values."""
    for name in ("relation", "source"):
        for value in texts(values, name):
            if WEB_URI_PATTERN.match(value):
                yield value
                continue
            report_issue(
                "warning",
                f"dc:{name} is not a web address and Dublin Core does"
                " not say what the relation is, value not transferred",
                record_id=source_key,
                source_field=f"dc:{name}",
                target_field="has_webresource",
                raw_value=value,
            )


def report_dropped_elements(values, source_key):
    """Report the elements for which AVefi has no target."""
    for name in UNMAPPED_ELEMENTS:
        for value in texts(values, name):
            report_issue(
                "warning",
                f"No AVefi target for dc:{name}, value not transferred",
                record_id=source_key,
                source_field=f"dc:{name}",
                target_field="—",
                raw_value=value,
            )


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core import avefi

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m efi_conv.dc.mapping INPUT [OUTPUT.json]\n"
            "\n"
            "Convert an unqualified Dublin Core (oai_dc) export into"
            " AVefi records.\n"
            "Equivalent to: efi-conv from -f dc -o OUTPUT INPUT",
            file=sys.stderr if not argv else sys.stdout,
        )
        return 0 if argv else 2
    if len(argv) > 2:
        print("Expected at most two arguments, see --help", file=sys.stderr)
        return 2

    records = efi_import(argv[0])
    if len(argv) == 2:
        avefi.dump(avefi.sort_records(records), argv[1])
    else:
        print(avefi.dumps(avefi.sort_records(records), indent=2))
    return 0


if __name__ == "__main__":
    from ..main import cli_main  # noqa: F401  (configures logging)

    sys.exit(main())
