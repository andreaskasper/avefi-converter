"""Generic mapping from MARC21-XML to the AVefi schema.

MARC21 is a standard, so the traversal of a record is the same for
every data provider. Everything that differs between them — issuer
information, relator vocabularies, genre vocabularies, the fields the
local identifier lives in — is supplied through a
:class:`~efi_conv.marc21.profile.Marc21Profile`.

Every MARC record in scope yields an item. Works and manifestations are
shared between records according to the profile key, because several
records commonly describe several copies of one film and minting a work
per copy would defeat the purpose of the AVefi identifiers.

"""

from dataclasses import dataclass, field
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
    work_key,
)
from ..core.report import for_file, report_issue, report_record_skipped
from .marcxml import fixed_position, is_fill, iter_records
from .profile import Marc21Profile

log = logging.getLogger(__name__)

#: Issuer identifier of the shipped placeholder profile. A converted
#: record naming it is not ready for use: the holding institution has
#: to be identified before persistent identifiers are registered.
PLACEHOLDER_ISSUER_ID = "https://w3id.org/avefi/issuer/unspecified"

#: Placeholder used for is_item_of until the manifestation is known.
PENDING_REFERENCE = "__pending__"

#: Fixed field codes stating that no value is available rather than
#: carrying one: unknown, not applicable and other.
UNKNOWN_FIXED_FIELD_CODES = frozenset({"n", "u", "z"})

#: Activity classes that belong to a publication rather than to a
#: production event, as the AVefi schema allows them there only.
PUBLICATION_ACTIVITY_CLASSES = frozenset(
    {
        "CopyrightAndDistributionActivity",
        "LaboratoryActivity",
        "ManifestationActivity",
    }
)

#: Labels prefixed to the notes derived from a MARC field, so that a
#: note stays intelligible once it is separated from its field.
NOTE_LABELS = {
    "300": "Physical description",
    "508": "Production credits",
    "511": "Cast",
    "546": "Language",
    "852": "Holdings",
    "250": "Edition",
}

#: Subfields of 245 that make up the title. Everything else in the
#: field, such as the medium designator in $h, is reported.
TITLE_SUBFIELDS = ("a", "b", "n", "p")

#: Trailing ISBD punctuation, which is display markup rather than part
#: of the value it terminates.
ISBD_TRAILING = re.compile(r"\s*[/:;,=]+\s*$")

#: A full stop that terminates a value rather than an abbreviation.
#: "Wicki, Bernhard." loses it, "Meyer, H." keeps it.
TRAILING_PERIOD = re.compile(r"(?<![A-Z])\.\s*$")

#: A length in feet or metres inside a MARC 300 $a extent statement.
EXTENT_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ft\.|ft\b|feet\b|m\.|m\b|met(?:er|re)s?\b)",
    re.IGNORECASE,
)

#: A running time in parentheses inside a MARC 300 $a extent statement.
PARENTHESISED_DURATION = re.compile(
    r"\((?:[^()]*?\b)?(\d+)\s*(min\.?|minutes?|minuten|sec\.?|s)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MappingRule:
    """One documented mapping from a MARC21 field to an AVefi field."""

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
        "moving_image_filter",
        "Record",
        "leader/06, 006/00, 007/00, 008/33",
        "—",
        "Profile vocabulary",
        "Only projected medium and videorecording records are in"
        " scope. A record describing a filmstrip, a slide set or a"
        " book is skipped and reported, and so is a projected medium"
        " record that says nothing about which medium it is",
    ),
    MappingRule(
        "record_id",
        "Item",
        "001, prefixed with the assigning agency in 003, else 035$a",
        "has_identifier, described_by.has_source_key",
        notes="Written as (agency)number, the form MARC itself uses in"
        " 035$a. A record without any identifier is skipped and"
        " reported, because its records could not be referred to",
    ),
    MappingRule(
        "work_type",
        "Work",
        "leader/07",
        "type",
        "Profile bibliographic_level_map",
        "Bibliographic level; an unmapped level falls back to"
        " Monographic and is reported",
    ),
    MappingRule(
        "work_grouping",
        "Work",
        "primary title, director, production date",
        "has_identifier (work)",
        "Profile work_key_fields",
        "Several copies of one film share one WorkVariant; set"
        " work_key_fields to () for one work per record",
    ),
    MappingRule(
        "manifestation_grouping",
        "Manifestation",
        "work key plus colour, sound, format and languages of the copy",
        "has_identifier (manifestation)",
        notes="Copies agreeing on the carrier characteristics share a"
        " manifestation",
    ),
    MappingRule(
        "primary_title",
        "Work, Manifestation, Item",
        "245$a$b$n$p with the nonfiling character count in ind2",
        "has_primary_title.has_name, has_primary_title.has_ordering_name",
        "Nonfiling indicator, else article handling",
        "ind2 states how many leading characters are not to be sorted"
        " on, which is better evidence than an article list; a fully"
        " bracketed title becomes SuppliedDevisedTitle",
    ),
    MappingRule(
        "alternative_title",
        "Work",
        "246$a$b$n$p, 247$a$b",
        "has_alternative_title",
        "Article handling in both directions",
        "The distinction MARC draws in 246 ind2 and the former title"
        " semantics of 247 have no AVefi counterpart and are reported",
    ),
    MappingRule(
        "production_date",
        "Work",
        "008/06 date type with 008/07-10 and 008/11-14, else 264 ind2=0 $c",
        "has_event.has_date",
        "ISODate",
        "The date type decides how the two dates are read; p and r put"
        " the release date first and the production date second",
    ),
    MappingRule(
        "production_place",
        "Work",
        "257$a, 264 ind2=0 $a",
        "has_event.located_in.has_name",
    ),
    MappingRule(
        "production_credits",
        "Work",
        "100, 110, 700, 710 with a relator code in $4 or a relator term in $e",
        "has_event.has_activity",
        "Profile relator_activities",
        "An agent without a relator, or with a relator that has no"
        " AVefi activity, is reported rather than filed under a"
        " guessed activity",
    ),
    MappingRule(
        "publication_statement",
        "Manifestation",
        "260$a$b$c, 264 ind2=1 and ind2=2 $a$b$c, 008 release date",
        "has_event (PublicationEvent)",
        "ISODate",
        "ind2=2 becomes a DistributionEvent, everything else a"
        " ReleaseEvent; manufacture and copyright statements are"
        " reported instead, see the assumptions",
    ),
    MappingRule(
        "edition",
        "Manifestation",
        "250$a$b",
        "has_note",
        notes="AVefi has no edition field, so the statement is kept as a note",
    ),
    MappingRule(
        "duration",
        "Item",
        "306$a, else 008/18-20, else the running time in 300$a",
        "has_duration.has_value",
        "ISODurationInHours",
        "008/18-20 holds the running time in minutes; sources that"
        " disagree are reported and the most precise one wins",
    ),
    MappingRule(
        "extent",
        "Item",
        "300$a length in feet or metres",
        "has_extent",
        notes="Only feet and metres have an AVefi unit; a reel count"
        " has none and stays in the note",
    ),
    MappingRule(
        "language",
        "Item",
        "008/35-37, 041$a, 041$j",
        "in_language",
        "ISO 639-2/B",
        "041$a is read as spoken language and 041$j as subtitles;"
        " 041$b and 041$h are reported",
    ),
    MappingRule(
        "colour_type",
        "Item",
        "007/03",
        "has_colour_type",
        "Profile colour_type_map",
    ),
    MappingRule(
        "sound_type",
        "Item",
        "007/05",
        "has_sound_type",
        "Profile sound_type_map",
        "A blank at this position means silent rather than uncoded",
    ),
    MappingRule(
        "format",
        "Item",
        "007/07 for a motion picture, 007/04 for a videorecording",
        "has_format (Film, Video)",
        "Profile film_gauge_map, video_format_map",
        "The positions differ between the two categories of 007, so"
        " 007/00 has to be read before either of them",
    ),
    MappingRule(
        "dimensions",
        "Item",
        "300$c",
        "has_format (Film, Video)",
        "Profile dimension_format_map",
        "Consulted only when 007 yielded no format",
    ),
    MappingRule(
        "access_status",
        "Item",
        "007/11 generation, motion pictures only",
        "has_access_status",
        "Profile generation_access_map",
    ),
    MappingRule(
        "genre",
        "Work",
        "655$a",
        "has_genre.has_name",
        "Profile genre_source_vocabularies",
        "Subdivisions in $v$x$y$z are reported, as AVefi has no place"
        " for them",
    ),
    MappingRule(
        "notes",
        "Item",
        "300, 500, 508, 511, 546",
        "has_note",
        notes="Credits and cast are kept verbatim, because free text"
        " cannot be split into agents and activities reliably",
    ),
    MappingRule(
        "holdings",
        "Item",
        "852$a$b$c$h$j$p",
        "has_note, has_identifier",
        notes="The shelving control number in $j becomes a second"
        " local identifier, qualified with the institution in $a; the"
        " field as a whole becomes a note",
    ),
    MappingRule(
        "technique",
        "Work",
        "008/34",
        "—",
        notes="Animation and live action have no AVefi counterpart and"
        " are reported",
    ),
    MappingRule(
        "issuer",
        "Work, Manifestation, Item",
        "profile issuer_info",
        "described_by.has_issuer_id, described_by.has_issuer_name",
        notes="Taken from the profile, not from 003 or 852$a, so that"
        " the issuer is unambiguous; the shipped default is a"
        " placeholder and using it is reported once per run",
    ),
)

MAPPING_RULES_BY_ID = {rule.id: rule for rule in MAPPING_RULES}


#: Decisions the mapping takes that MARC alone does not determine. They
#: are listed in the generated documentation so that a reviewer sees
#: them without reading the code.
ASSUMPTIONS = (
    "This is a format converter, not an institution converter. The"
    " shipped profile carries a placeholder issuer, and every run"
    " using it reports a warning: the ISIL of the holding institution"
    " has to be configured before the records are used. No ISIL is"
    " ever derived from 003 or 852$a, because an agency code"
    " identifies the cataloguing agency rather than the holder.",
    "Only records whose leader position 06 is `g`, projected medium,"
    " are considered, and of those only the ones that 007/00 or 008/33"
    " identify as a motion picture or a videorecording. A projected"
    " medium record saying nothing about which medium it is, which"
    " would equally be a filmstrip or a slide set, is skipped with a"
    " warning rather than imported as a film.",
    "`245 ind2` gives the number of leading characters not to be"
    " sorted on. It is used for `has_ordering_name` in preference to"
    " the article list of `core.normalise.normalise_title`, because"
    " the cataloguer stated the article rather than a list guessing"
    " it. The article list is used only where the indicator is 0,"
    " which is also what a record without an article carries, so a"
    " title with an article and an indicator of 0 is treated as if it"
    " had no article.",
    "A title enclosed in brackets as a whole is a devised title and"
    " becomes `SuppliedDevisedTitle` with the brackets removed. The"
    " nonfiling count is reduced by one accordingly.",
    "Trailing ISBD punctuation (` / : ; , =`) is display markup and is"
    " removed, from a title as well as from a name. A trailing full"
    " stop is removed only where the preceding character is not a"
    " capital letter, so that an abbreviated forename keeps its stop."
    " Without this, `Die Brücke` and `Die Brücke.` would be two works"
    " rather than one.",
    "The 008 date type in position 06 decides how positions 07-10 and"
    " 11-14 are read. `s` is a production date, `e` a detailed"
    " production date, `m`, `i`, `k`, `c`, `d` and `u` an interval,"
    " `q` an interval qualified as questionable, and `p` and `r` put"
    " the release date in the first and the production date in the"
    " second position. A date type that is not one of these is"
    " reported and only the first date is used.",
    "A date containing `u`, such as `196u`, states a decade in a"
    " notation ISODate cannot express. It is reported and left unset"
    " rather than widened to an interval, which would assert a"
    " precision the record does not have. `9999` in the second date"
    " marks an open ended range and yields no end date.",
    "Copyright statements, that is `264 ind2=4` and the second date of"
    " date type `t`, are reported and not mapped:"
    " RightsCopyrightRegistrationEvent requires a copyright activity"
    " with an agent, and MARC does not reliably supply one. Manufacture"
    " statements in `264 ind2=3` are reported for the same reason,"
    " ManufactureEvent having no generic type value.",
    "008 positions 18-20 hold the running time of a moving image in"
    " minutes. `000` means that it exceeds three digits and `nnn` that"
    " it does not apply; both yield no duration. Where 306$a and the"
    " fixed field disagree, 306$a wins because it is precise to the"
    " second, and the divergence is reported.",
    "A blank in 007 position 05 means silent, not uncoded, so the"
    " profile vocabulary is consulted before a position is dismissed"
    " as a fill character. Everywhere else a blank, a vertical bar or"
    " a hash means that nothing was coded and is passed over silently.",
    "The character positions of 007 depend on 007/00. For a motion"
    " picture position 04 is the presentation format and 07 the film"
    " gauge; for a videorecording 04 is the videorecording format and"
    " 07 the tape width. Only the gauge and the videorecording format"
    " are mapped.",
    "Of 007 only the positions named in the mapping table are"
    " consulted. The remaining positions, such as the base of the film"
    " or the configuration of playback channels, have no AVefi"
    " counterpart and are out of scope rather than reported per"
    " record.",
    "Free text notes are kept verbatim and prefixed with a label"
    " naming the field they came from, because a note detached from"
    " its field is not intelligible. Production credits in 508 and"
    " cast in 511 are kept as notes rather than parsed into agents:"
    " splitting a credit line into names and functions cannot be done"
    " reliably, and a wrong activity is worse than a visible note.",
    "The physical description in 300 is kept as a note in full, in"
    " addition to the duration, extent and format derived from it, so"
    " that nothing of it is lost to the partial parsing.",
    "Life dates in $d of an agent field are reported, AVefi Agent"
    " having no field for them.",
    "Every record in scope yields one item. Works and manifestations"
    " are shared between records according to the profile key.",
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
        "# MARC21 to AVefi mapping",
        "",
        "Generated from `MAPPING_RULES` in `efi_conv.marc21.mapping`;",
        "do not edit by hand.",
        "",
        "| Rule | Level | MARC21 source | AVefi target |"
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
        "Decisions the mapping takes that MARC21 does not determine,"
        " and that need confirming against the reference data:",
        "",
    ]
    lines += [f"- {assumption}" for assumption in ASSUMPTIONS]
    return "\n".join(lines) + "\n"


@dataclass
class MappingContext(GroupingContext):
    """State shared by all records of one conversion."""

    profile: Marc21Profile | None = None


def efi_import(
    input_file,
    profile: Marc21Profile,
    continue_on_error: bool = False,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Convert a MARCXML file into AVefi records using ``profile``.

    Parameters
    ----------
    input_file
        Path of the MARCXML document.
    profile : Marc21Profile
        Institution specific configuration.
    continue_on_error : bool
        Report a record that cannot be converted and carry on with the
        remaining ones, instead of aborting the whole file.
    context : MappingContext, optional
        Grouping context to add the records of this file to. One
        conversion of several files passes the same context to each of
        them, so that records describing one film in different files
        share their work. Without it the file is converted on its own.

    Returns
    -------
    list
        The AVefi records derived from the document.

    """
    records: list[efi.MovingImageRecord] = []
    if context is None:
        context = new_context(profile)
    with for_file(input_file):
        report_placeholder_issuer(profile)
        for marc_record in iter_records(input_file):
            try:
                with context.attempt():
                    records.extend(map_record(marc_record, profile, context))
            except Exception as e:
                if not continue_on_error:
                    raise
                report_record_skipped(
                    e, record_id=record_identifier(marc_record, profile)
                )
    return records


def new_context(profile: Marc21Profile) -> MappingContext:
    """Return a grouping context for one conversion.

    Handed to :func:`efi_import` once per run rather than once per
    file, so that the works of a conversion are shared between the
    input files.

    """
    return MappingContext(profile=profile)


def report_placeholder_issuer(profile: Marc21Profile):
    """Warn once per run when the placeholder issuer is still in use."""
    if profile.issuer_info.get("has_issuer_id") != PLACEHOLDER_ISSUER_ID:
        return
    report_issue(
        "warning",
        "Placeholder issuer in use: replace it with the ISIL of the"
        " holding institution before these records are used",
        source_field="profile issuer_info",
        target_field="described_by.has_issuer_id",
        raw_value=PLACEHOLDER_ISSUER_ID,
    )


def map_record(
    marc_record,
    profile: Marc21Profile,
    context: "MappingContext | None" = None,
) -> list[efi.MovingImageRecord]:
    """Return the AVefi records derived from one MARC record."""
    if context is None:
        context = MappingContext(profile=profile)
    source_key = record_identifier(marc_record, profile)
    if source_key is None:
        report_issue(
            "warning",
            "Record skipped: no identifier in any of the configured"
            " fields, so its records could not be referred to",
            source_field=", ".join(profile.identifier_fields),
            target_field="has_identifier",
            raw_value=marc_record.leader,
        )
        return []
    if not is_moving_image_record(marc_record, profile, source_key):
        return []

    titles = collect_titles(marc_record, profile, source_key)
    if not titles:
        raise ValueError(f"MARC record {source_key} has no usable 245 title")
    primary, alternatives = titles[0], titles[1:]

    dates = dates_from_008(marc_record, profile, source_key)
    production_activities, publication_activities = collect_activities(
        marc_record, profile, source_key
    )
    production = build_production_event(
        marc_record, profile, source_key, dates, production_activities
    )
    publications = build_publication_events(
        marc_record, profile, source_key, dates, publication_activities
    )

    new_records = []
    work_key = make_work_key(profile, source_key, primary, production)

    def new_work():
        work = build_work(
            marc_record, primary, alternatives, profile, source_key
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

    carrier = carrier_from_007(marc_record, profile, source_key)
    item = build_item(marc_record, primary, profile, source_key, carrier)
    manifestation_key = make_manifestation_key(work_key, item)

    def new_manifestation():
        manifestation = efi.Manifestation(
            is_manifestation_of=[work_id],
            has_primary_title=as_title(primary, "TitleProper"),
        )
        for event in publications:
            manifestation.has_event.append(event)
        for note in manifestation_notes(marc_record, source_key):
            manifestation.has_note.append(note)
        return manifestation

    manifestation, is_new = context.manifestation_for(
        manifestation_key, new_manifestation
    )
    if is_new:
        new_records.append(manifestation)
    item.is_item_of = manifestation.has_identifier[0]
    item.has_identifier.append(efi.LocalResource(id=source_key))
    for shelf_mark in shelf_marks(marc_record):
        if shelf_mark != source_key:
            item.has_identifier.append(efi.LocalResource(id=shelf_mark))
    new_records.append(item)

    attach_source_key(
        (work, manifestation, item), profile.issuer_info, source_key
    )
    return new_records


# --- record scope and identity ----------------------------------------


def record_identifier(marc_record, profile: Marc21Profile) -> str | None:
    """Return the local identifier of a MARC record, if it has one."""
    for tag in profile.identifier_fields:
        if tag == "001":
            control = (marc_record.control_field("001") or "").strip()
            if control:
                agency = (marc_record.control_field("003") or "").strip()
                return f"({agency}){control}" if agency else control
            continue
        value = marc_record.subfield(tag, "a")
        if value:
            return value.strip()
    return None


def is_moving_image_record(marc_record, profile, source_key) -> bool:
    """Return True if the record describes a moving image.

    Only projected medium and videorecording records are in scope. A
    library catalogue holds books, scores and slide sets in the same
    file, and none of them may become a film work.

    """
    leader_type = fixed_position(marc_record.leader, 6)
    forms = [
        fixed_position(value, 0)
        for value in marc_record.control_field_values("006")
    ]
    projected = leader_type in profile.moving_image_leader_types or any(
        form in profile.moving_image_leader_types for form in forms
    )
    if not projected:
        report_issue(
            "info",
            "Record skipped: not a projected medium",
            record_id=source_key,
            source_field="leader/06",
            target_field="—",
            raw_value=leader_type,
        )
        return False

    categories = [
        fixed_position(value, 0)
        for value in marc_record.control_field_values("007")
    ]
    categories = [code for code in categories if not is_fill(code)]
    if categories:
        if any(code in profile.moving_image_categories for code in categories):
            return True
        report_issue(
            "info",
            "Record skipped: 007 describes a projected medium that is"
            " neither a motion picture nor a videorecording",
            record_id=source_key,
            source_field="007/00",
            target_field="—",
            raw_value=categories,
        )
        return False

    material = fixed_position(marc_record.control_field("008"), 33)
    if material in profile.moving_image_material_types:
        return True
    if is_fill(material):
        report_issue(
            "warning",
            "Record skipped: neither 007 nor 008/33 says whether this"
            " projected medium is a moving image",
            record_id=source_key,
            source_field="007/00, 008/33",
            target_field="—",
            raw_value=leader_type,
        )
        return False
    report_issue(
        "info",
        "Record skipped: 008/33 describes another type of visual material",
        record_id=source_key,
        source_field="008/33",
        target_field="—",
        raw_value=material,
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
    """Return the directing agents of an event as a stable string."""
    if production is None:
        return ""
    names = sorted(
        agent.has_name
        for activity in production.has_activity
        if isinstance(activity, efi.DirectingActivity)
        for agent in activity.has_agent
    )
    return ", ".join(names)


def make_manifestation_key(work_key: str, item) -> str:
    """Return the key identifying the manifestation of an item."""
    parts = [
        work_key,
        str(item.has_colour_type or ""),
        str(item.has_sound_type or ""),
        ",".join(sorted(str(fmt.type) for fmt in item.has_format or [])),
        ",".join(
            sorted(
                f"{language.code}:{','.join(sorted(language.usage or []))}"
                for language in item.in_language or []
            )
        ),
    ]
    return make_key(*parts)


# --- titles -----------------------------------------------------------


def collect_titles(marc_record, profile, source_key) -> list[SourceTitle]:
    """Return the titles of a record, the primary one first."""
    language = record_language(marc_record, profile)
    primary = []
    for data_field in marc_record.fields("245"):
        if primary:
            report_issue(
                "warning",
                "Further 245 field ignored, a record has one title proper",
                record_id=source_key,
                source_field="245",
                target_field="has_primary_title",
                raw_value=field_text(data_field),
            )
            continue
        report_unmapped_title_subfields(data_field, source_key)
        title = title_from_field(
            data_field,
            language,
            nonfiling=nonfiling_count(data_field.ind2),
            record_id=source_key,
            source_field="245",
            target_field="has_primary_title.has_ordering_name",
        )
        if title:
            primary.append(title)

    alternatives = []
    for tag in ("246", "247"):
        for data_field in marc_record.fields(tag):
            title = title_from_field(
                data_field,
                language,
                nonfiling=0,
                record_id=source_key,
                source_field=tag,
                target_field="has_alternative_title.has_ordering_name",
            )
            if title is None:
                continue
            if tag == "247":
                report_issue(
                    "info",
                    "Former title mapped as an alternative title, AVefi"
                    " having no former title type",
                    record_id=source_key,
                    source_field="247",
                    target_field="has_alternative_title",
                    raw_value=title.display,
                )
            alternatives.append(title)
    return primary + alternatives


def nonfiling_count(indicator: str) -> int:
    """Return the number of nonfiling characters an indicator states."""
    return int(indicator) if indicator.isdigit() else 0


def report_unmapped_title_subfields(data_field, source_key):
    """Report the 245 subfields that carry no title text."""
    for subfield in data_field.subfields:
        if subfield.code in TITLE_SUBFIELDS or not subfield.value:
            continue
        report_issue(
            "info",
            f"Subfield 245 ${subfield.code} is not part of the title"
            f" and has no AVefi counterpart",
            record_id=source_key,
            source_field=f"245${subfield.code}",
            target_field="—",
            raw_value=subfield.value,
        )


def title_from_field(
    data_field,
    language,
    *,
    nonfiling,
    record_id,
    source_field,
    target_field,
) -> SourceTitle | None:
    """Return the title a 245, 246 or 247 field carries."""
    text = ""
    for subfield in data_field.subfields:
        if subfield.code not in TITLE_SUBFIELDS:
            continue
        value = strip_trailing_period(strip_isbd(subfield.value))
        if not value:
            continue
        if not text:
            text = value
        elif subfield.code == "b":
            text = f"{text} : {value}"
        else:
            text = f"{text}. {value}"
    text = strip_trailing_period(text)
    if not text:
        return None

    supplied = text.startswith("[") and text.endswith("]")
    if supplied:
        text = text[1:-1].strip()
        nonfiling = max(0, nonfiling - 1)
    if not text:
        return None

    if nonfiling >= len(text):
        report_issue(
            "warning",
            "Nonfiling character count exceeds the title, falling back"
            " to the article list",
            record_id=record_id,
            source_field=f"{source_field} ind2",
            target_field=target_field,
            raw_value=nonfiling,
        )
        nonfiling = 0
    if nonfiling > 0:
        article = text[:nonfiling].strip()
        rest = text[nonfiling:].strip()
        if article and rest:
            report_issue(
                "info",
                "Derived ordering name from the nonfiling indicator",
                record_id=record_id,
                source_field=f"{source_field} ind2",
                target_field=target_field,
                raw_value=text,
            )
            return SourceTitle(text, f"{rest}, {article}", supplied)
    display, ordering = normalise_title(
        text,
        language,
        record_id=record_id,
        target_field=target_field,
    )
    return SourceTitle(display, ordering, supplied)


def record_language(marc_record, profile) -> str | None:
    """Return the ISO 639-2/B language of a record, if it states one."""
    code = fixed_position(marc_record.control_field("008"), 35, 3)
    return language_code(code) or profile.default_language


# --- fixed field dates ------------------------------------------------


@dataclass(frozen=True)
class FixedFieldDates:
    """The production and release dates 008 states, as ISODate."""

    production: str | None = None
    publication: str | None = None


def dates_from_008(marc_record, profile, source_key) -> FixedFieldDates:
    """Return the dates 008 states, read according to its date type."""
    value = marc_record.control_field("008")
    if not value:
        return FixedFieldDates()
    date_type = fixed_position(value, 6)
    raw_first = fixed_position(value, 7, 4)
    raw_second = fixed_position(value, 11, 4)
    first = fixed_field_date(raw_first, source_key, "008/07-10")
    second = fixed_field_date(raw_second, source_key, "008/11-14")

    production = publication = None
    if date_type in ("b", "n"):
        if first or second:
            report_issue(
                "info",
                "008 date type states that no date is given, the date"
                " positions are not read",
                record_id=source_key,
                source_field="008/06",
                target_field="has_event.has_date",
                raw_value=f"{date_type}{raw_first}{raw_second}",
            )
    elif date_type == "e":
        production = detailed_date(first, raw_second)
    elif date_type in ("m", "i", "k", "q", "c", "d", "u"):
        production = interval_expression(
            first, second, date_type == "q", source_key
        )
    elif date_type in ("p", "r"):
        publication, production = first, second
    elif date_type == "t":
        publication = first
        if second:
            report_issue(
                "info",
                "Copyright date not mapped, see the assumptions",
                record_id=source_key,
                source_field="008/11-14",
                target_field="—",
                raw_value=second,
            )
    elif date_type == "s":
        production = first
        if second:
            report_issue(
                "info",
                "Second date not read, date type s states a single date",
                record_id=source_key,
                source_field="008/11-14",
                target_field="has_event.has_date",
                raw_value=second,
            )
    else:
        report_issue(
            "warning",
            "Unknown 008 date type, only the first date is used",
            record_id=source_key,
            source_field="008/06",
            target_field="has_event.has_date",
            raw_value=date_type,
        )
        production = first
    return FixedFieldDates(
        production=iso_date(production, profile, source_key, "008/07-14"),
        publication=iso_date(publication, profile, source_key, "008/07-14"),
    )


def fixed_field_date(raw: str, record_id, source_field) -> str | None:
    """Return the digits of a fixed field date, or None."""
    text = (raw or "").strip()
    if not text or is_fill(text[0]) and set(text) <= {" ", "|", "#"}:
        return None
    if text == "9999":
        return None
    if text.isdigit():
        return text
    if set(text.lower()) <= {"u"}:
        report_issue(
            "info",
            "Source states that the date is unknown",
            record_id=record_id,
            source_field=source_field,
            target_field="has_event.has_date",
            raw_value=raw,
        )
        return None
    report_issue(
        "warning",
        "Partially unknown date cannot be expressed as an ISODate and"
        " is left unset",
        record_id=record_id,
        source_field=source_field,
        target_field="has_event.has_date",
        raw_value=raw,
    )
    return None


def detailed_date(year: str | None, raw_second: str) -> str | None:
    """Return year, month and day of 008 date type e."""
    if not year:
        return None
    month, day = raw_second[:2], raw_second[2:4]
    if not (month.isdigit() and month != "00"):
        return year
    text = f"{year}-{month}"
    if day.isdigit() and day != "00":
        text = f"{text}-{day}"
    return text


def interval_expression(
    first: str | None, second: str | None, questionable: bool, record_id
) -> str | None:
    """Return the interval two fixed field dates describe."""
    if first and second:
        if first > second:
            report_issue(
                "warning",
                "008 interval ends before it starts, only the first"
                " date is used",
                record_id=record_id,
                source_field="008/07-14",
                target_field="has_event.has_date",
                raw_value=f"{first}/{second}",
            )
            text = first
        else:
            text = f"{first}/{second}"
    else:
        text = first or second
    if text and questionable:
        text = f"{text}?"
    return text


def iso_date(text, profile, record_id, source_field) -> str | None:
    """Return ``text`` as an ISODate, reporting what cannot be mapped."""
    if not text:
        return None
    try:
        return normalise_date(
            text,
            record_id=record_id,
            source_field=source_field,
            target_field="has_event.has_date",
            map_decades=profile.map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "error",
            str(e),
            record_id=record_id,
            source_field=source_field,
            target_field="has_event.has_date",
            raw_value=text,
        )
        raise


# --- fixed field carrier data -----------------------------------------


@dataclass
class Carrier:
    """The carrier characteristics field 007 describes."""

    colour: str | None = None
    sound: str | None = None
    access_status: str | None = None
    formats: list = field(default_factory=list)


def carrier_from_007(marc_record, profile, source_key) -> Carrier:
    """Return the carrier characteristics of the copy described.

    The meaning of a position of 007 depends on 007/00: position 04 is
    the presentation format of a motion picture but the recording
    format of a videorecording, and position 07 the film gauge of the
    one but the tape width of the other. Reading the category first is
    therefore not optional.

    """
    carrier = Carrier()
    for value in marc_record.control_field_values("007"):
        category = fixed_position(value, 0)
        if category not in profile.moving_image_categories:
            if not is_fill(category):
                report_issue(
                    "info",
                    "Field 007 describes another material category and"
                    " is not read",
                    record_id=source_key,
                    source_field="007/00",
                    target_field="—",
                    raw_value=category,
                )
            continue
        colour = mapped_code(
            fixed_position(value, 3),
            profile.colour_type_map,
            record_id=source_key,
            source_field="007/03",
            target_field="has_colour_type",
        )
        if colour and carrier.colour is None:
            carrier.colour = colour
        sound = mapped_code(
            fixed_position(value, 5),
            profile.sound_type_map,
            record_id=source_key,
            source_field="007/05",
            target_field="has_sound_type",
        )
        if sound and carrier.sound is None:
            carrier.sound = sound
        if category == "m":
            gauge = mapped_code(
                fixed_position(value, 7),
                profile.film_gauge_map,
                record_id=source_key,
                source_field="007/07",
                target_field="has_format",
            )
            if gauge:
                carrier.formats.append(("Film", gauge))
            access = mapped_code(
                fixed_position(value, 11),
                profile.generation_access_map,
                record_id=source_key,
                source_field="007/11",
                target_field="has_access_status",
            )
            if access and carrier.access_status is None:
                carrier.access_status = access
        else:
            video_format = mapped_code(
                fixed_position(value, 4),
                profile.video_format_map,
                record_id=source_key,
                source_field="007/04",
                target_field="has_format",
            )
            if video_format:
                carrier.formats.append(("Video", video_format))
    return carrier


def mapped_code(
    code, vocabulary, *, record_id, source_field, target_field
) -> str | None:
    """Return the AVefi value for a fixed field code, if mappable.

    The vocabulary is consulted before the code is dismissed as a fill
    character, because 007 position 05 defines the blank as "silent"
    rather than as "not coded".

    """
    if not code:
        return None
    mapped = vocabulary.get(code)
    if mapped is not None:
        return mapped
    if is_fill(code):
        return None
    if code in UNKNOWN_FIXED_FIELD_CODES:
        report_issue(
            "info",
            "Fixed field states that the value is unknown, other or"
            " not applicable",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=code,
        )
        return None
    report_issue(
        "warning",
        "No AVefi value configured for this fixed field code",
        record_id=record_id,
        source_field=source_field,
        target_field=target_field,
        raw_value=code,
    )
    return None


# --- events -----------------------------------------------------------


def build_work(marc_record, primary, alternatives, profile, source_key):
    """Return the WorkVariant for one MARC record."""
    work = efi.WorkVariant(
        type=work_variant_type(marc_record, profile, source_key),
        has_primary_title=as_title(primary, "PreferredTitle"),
    )
    for title in alternatives:
        work.has_alternative_title.append(as_title(title, "AlternativeTitle"))
    for name in genre_names(marc_record, profile, source_key):
        work.has_genre.append(efi.Genre(has_name=name))
    report_technique(marc_record, source_key)
    return work


def work_variant_type(marc_record, profile, source_key):
    """Return the AVefi work type the bibliographic level states."""
    level = fixed_position(marc_record.leader, 7)
    mapped = profile.bibliographic_level_map.get(level)
    if mapped:
        return efi.WorkVariantTypeEnum(mapped)
    if not is_fill(level):
        report_issue(
            "info",
            "No AVefi work type configured for this bibliographic"
            " level, falling back to Monographic",
            record_id=source_key,
            source_field="leader/07",
            target_field="type",
            raw_value=level,
        )
    return efi.WorkVariantTypeEnum("Monographic")


def genre_names(marc_record, profile, source_key):
    """Yield the genre terms of a record, reporting what is dropped."""
    for data_field in marc_record.fields("655"):
        source = data_field.subfield("2")
        if (
            profile.genre_source_vocabularies
            and (source or "").lower() not in profile.genre_source_vocabularies
        ):
            report_issue(
                "info",
                "Genre term from a vocabulary the profile does not"
                " accept, not transferred",
                record_id=source_key,
                source_field="655$2",
                target_field="has_genre",
                raw_value=f"{field_text(data_field, ('a',))} ({source})",
            )
            continue
        subdivisions = [
            value
            for code in ("v", "x", "y", "z")
            for value in data_field.subfield_values(code)
        ]
        if subdivisions:
            report_issue(
                "info",
                "Genre subdivisions have no AVefi counterpart and are"
                " not transferred",
                record_id=source_key,
                source_field="655$v$x$y$z",
                target_field="has_genre",
                raw_value=subdivisions,
            )
        for value in data_field.subfield_values("a"):
            name = strip_trailing_period(strip_isbd(value))
            if name:
                yield name


def report_technique(marc_record, source_key):
    """Report the technique 008/34 states, which AVefi cannot hold."""
    technique = fixed_position(marc_record.control_field("008"), 34)
    if is_fill(technique) or technique in UNKNOWN_FIXED_FIELD_CODES:
        return
    report_issue(
        "info",
        "Technique has no AVefi counterpart and is not transferred",
        record_id=source_key,
        source_field="008/34",
        target_field="—",
        raw_value=technique,
    )


def build_production_event(
    marc_record, profile, source_key, dates, activities
):
    """Return the ProductionEvent a record describes."""
    event = efi.ProductionEvent()
    has_date = dates.production
    if has_date is None:
        has_date = production_date_from_264(marc_record, profile, source_key)
    if has_date:
        event.has_date = has_date
    for name in production_places(marc_record):
        event.located_in.append(efi.GeographicName(has_name=name))
    for activity in activities:
        event.has_activity.append(activity)
    if not (event.has_date or event.located_in or event.has_activity):
        return None
    return event


def production_date_from_264(marc_record, profile, source_key) -> str | None:
    """Return the date of a 264 production statement, if there is one."""
    for data_field in marc_record.fields("264"):
        if data_field.ind2 != "0":
            continue
        value = data_field.subfield("c")
        if value:
            return iso_date(
                publication_date_text(value), profile, source_key, "264$c"
            )
    return None


def production_places(marc_record) -> list[str]:
    """Return the places of production a record states."""
    names = [strip_isbd(value) for value in marc_record.subfields("257", "a")]
    for data_field in marc_record.fields("264"):
        if data_field.ind2 == "0":
            names.extend(
                strip_isbd(value) for value in data_field.subfield_values("a")
            )
    return [strip_trailing_period(name) for name in names if name]


def build_publication_events(
    marc_record, profile, source_key, dates, activities
):
    """Return the PublicationEvents a record describes."""
    events = []
    for data_field in marc_record.fields("260", "264"):
        if data_field.tag == "264":
            if data_field.ind2 == "0":
                continue
            if data_field.ind2 in ("3", "4"):
                report_issue(
                    "info",
                    "Manufacture or copyright statement not mapped, see"
                    " the assumptions",
                    record_id=source_key,
                    source_field=f"264 ind2={data_field.ind2}",
                    target_field="—",
                    raw_value=field_text(data_field),
                )
                continue
        distribution = data_field.tag == "264" and data_field.ind2 == "2"
        event = efi.PublicationEvent(
            type=efi.PublicationEventTypeEnum(
                "DistributionEvent" if distribution else "ReleaseEvent"
            )
        )
        value = data_field.subfield("c")
        if value:
            event.has_date = iso_date(
                publication_date_text(value),
                profile,
                source_key,
                f"{data_field.tag}$c",
            )
        for place in data_field.subfield_values("a"):
            name = strip_trailing_period(strip_isbd(place))
            if name:
                event.located_in.append(efi.GeographicName(has_name=name))
        for name in data_field.subfield_values("b"):
            agent_name = strip_trailing_period(strip_isbd(name))
            if not agent_name:
                continue
            class_name, type_value = (
                ("CopyrightAndDistributionActivity", "Distributor")
                if distribution
                else ("ManifestationActivity", "Publisher")
            )
            event.has_activity.append(
                build_activity(
                    class_name,
                    type_value,
                    [
                        efi.Agent(
                            type=efi.AgentTypeEnum("CorporateBody"),
                            has_name=agent_name,
                        )
                    ],
                )
            )
        if event.has_date or event.located_in or event.has_activity:
            events.append(event)

    if dates.publication:
        if not events:
            events.append(
                efi.PublicationEvent(
                    type=efi.PublicationEventTypeEnum("ReleaseEvent"),
                    has_date=dates.publication,
                )
            )
        elif not events[0].has_date:
            events[0].has_date = dates.publication
        elif events[0].has_date != dates.publication:
            report_issue(
                "info",
                "008 and the publication statement give different"
                " release dates, the statement is used",
                record_id=source_key,
                source_field="008/07-10",
                target_field="has_event.has_date",
                raw_value=dates.publication,
            )
    if activities:
        if not events:
            events.append(
                efi.PublicationEvent(
                    type=efi.PublicationEventTypeEnum("UnknownEvent")
                )
            )
        events[0].has_activity.extend(activities)
    return events


def publication_date_text(value: str) -> str:
    """Return the date of a publication statement without its markup."""
    text = value.strip().rstrip(".,;:").strip()
    text = text.strip("[]()").strip()
    if text[:1].lower() in ("c", "p", "©") and text[1:2].isdigit():
        text = text[1:]
    return text.strip()


def collect_activities(marc_record, profile, source_key):
    """Return the production and publication activities of a record."""
    grouped: dict[tuple[str, str], dict[str, efi.Agent]] = {}
    for data_field in marc_record.fields(*profile.agent_fields):
        name = agent_name(data_field)
        if not name:
            continue
        if name.lower() in profile.unknown_agent_names:
            report_issue(
                "info",
                "Placeholder agent name skipped",
                record_id=source_key,
                source_field=f"{data_field.tag}$a",
                target_field="has_event.has_activity",
                raw_value=name,
            )
            continue
        report_agent_dates(data_field, source_key)
        relators = data_field.subfield_values(
            "4"
        ) + data_field.subfield_values("e")
        if not relators:
            report_issue(
                "warning",
                "No relator code or term, agent not transferred",
                record_id=source_key,
                source_field=f"{data_field.tag}$4, ${data_field.tag}$e",
                target_field="has_event.has_activity",
                raw_value=name,
            )
            continue
        for relator in relators:
            key = relator_key(relator)
            mapped = profile.relator_activities.get(key)
            if mapped is None:
                report_issue(
                    "warning",
                    "No AVefi activity mapped for this relator, agent"
                    " not transferred",
                    record_id=source_key,
                    source_field=f"{data_field.tag}$4/$e",
                    target_field="has_event.has_activity",
                    raw_value=relator,
                )
                continue
            grouped.setdefault(mapped, {}).setdefault(
                name, agent_for(data_field, name)
            )

    production, publication = [], []
    for (class_name, type_value), agents in grouped.items():
        activity = build_activity(
            class_name, type_value, list(agents.values())
        )
        if class_name in PUBLICATION_ACTIVITY_CLASSES:
            publication.append(activity)
        else:
            production.append(activity)
    return production, publication


def build_activity(class_name: str, type_value: str, agents):
    """Return an AVefi activity of ``class_name`` with ``agents``."""
    activity_class = getattr(efi, class_name)
    type_enum = getattr(efi, f"{class_name}TypeEnum")
    return activity_class(type=type_enum(type_value), has_agent=agents)


def agent_name(data_field) -> str | None:
    """Return the name of an agent field, without its punctuation."""
    value = data_field.subfield("a")
    if not value:
        return None
    return strip_trailing_period(strip_isbd(value)) or None


def agent_for(data_field, name) -> efi.Agent:
    """Return the AVefi agent a 1XX or 7XX field describes."""
    if data_field.tag in ("110", "710"):
        agent_type = "CorporateBody"
    elif data_field.ind1 == "3":
        agent_type = "Family"
    else:
        agent_type = "Person"
    return efi.Agent(type=efi.AgentTypeEnum(agent_type), has_name=name)


def report_agent_dates(data_field, source_key):
    """Report the life dates of an agent, which AVefi cannot hold."""
    for value in data_field.subfield_values("d"):
        report_issue(
            "info",
            "Agent dates have no AVefi counterpart and are not transferred",
            record_id=source_key,
            source_field=f"{data_field.tag}$d",
            target_field="has_agent",
            raw_value=value,
        )


def relator_key(value: str) -> str:
    """Return a relator code or term in its lookup form."""
    return value.strip().rstrip(".,;:").strip().lower()


# --- item -------------------------------------------------------------


def build_item(marc_record, primary, profile, source_key, carrier):
    """Return the Item for one MARC record.

    ``is_item_of`` is filled in by the caller, once the manifestation
    this copy belongs to is known.

    """
    item = efi.Item(
        is_item_of=efi.LocalResource(id=PENDING_REFERENCE),
        has_primary_title=as_title(primary, "TitleProper"),
    )
    duration = item_duration(marc_record, source_key)
    if duration:
        item.has_duration = efi.Duration(has_value=duration)
    if carrier.colour:
        item.has_colour_type = efi.ColourTypeEnum(carrier.colour)
    if carrier.sound:
        item.has_sound_type = efi.SoundTypeEnum(carrier.sound)
    if carrier.access_status:
        item.has_access_status = efi.ItemAccessStatusEnum(
            carrier.access_status
        )
    formats = carrier.formats or dimension_formats(
        marc_record, profile, source_key
    )
    for class_name, type_value in formats:
        item.has_format.append(format_for(class_name, type_value))
    extent = item_extent(marc_record, source_key)
    if extent is not None:
        item.has_extent = extent
    for language in item_languages(marc_record, source_key):
        item.in_language.append(language)
    for note in item_notes(marc_record, source_key):
        item.has_note.append(note)
    return item


def format_for(class_name: str, type_value: str):
    """Return the AVefi format record for a carrier type."""
    format_class = getattr(efi, class_name)
    type_enum = getattr(efi, f"Format{class_name}TypeEnum")
    return format_class(type=type_enum(type_value))


def dimension_formats(marc_record, profile, source_key):
    """Return the formats stated in 300 $c, if 007 gave none."""
    formats = []
    for value in marc_record.subfields("300", "c"):
        key = normalised_dimension(value)
        mapped = profile.dimension_format_map.get(key)
        if mapped is None:
            report_issue(
                "info",
                "No AVefi format configured for these dimensions",
                record_id=source_key,
                source_field="300$c",
                target_field="has_format",
                raw_value=value,
            )
            continue
        formats.append(mapped)
    return formats


def normalised_dimension(value: str) -> str:
    """Return a 300 $c dimension statement in its lookup form."""
    text = strip_trailing_period(strip_isbd(value)).lower()
    text = re.sub(r"\s+", " ", text.replace(",", "."))
    return text.strip()


def item_duration(marc_record, source_key) -> str | None:
    """Return the running time of a copy, from the most precise source.

    306$a is stated to the second, 008/18-20 only in minutes and the
    parenthesis in 300$a is free text. Where they disagree, the more
    precise one wins and the divergence is reported.

    """
    candidates = []
    for value in marc_record.subfields("306", "a"):
        duration = duration_from_306(value, source_key)
        if duration:
            candidates.append(("306$a", duration))
    fixed = duration_from_008(marc_record, source_key)
    if fixed:
        candidates.append(("008/18-20", fixed))
    for value in marc_record.subfields("300", "a"):
        duration = duration_from_extent(value, source_key)
        if duration:
            candidates.append(("300$a", duration))
    if not candidates:
        return None
    chosen_field, chosen = candidates[0]
    for source_field, duration in candidates[1:]:
        if duration != chosen:
            report_issue(
                "info",
                f"Running time differs from {chosen_field}, the more"
                f" precise source is used",
                record_id=source_key,
                source_field=source_field,
                target_field="has_duration.has_value",
                raw_value=duration,
            )
    return chosen


def duration_from_306(value: str, source_key) -> str | None:
    """Return the duration a 306 $a field states as hhmmss."""
    text = value.strip()
    if len(text) != 6 or not text.isdigit():
        report_issue(
            "warning",
            "306$a is expected to hold six digits as hhmmss",
            record_id=source_key,
            source_field="306$a",
            target_field="has_duration.has_value",
            raw_value=value,
        )
        return None
    clock = f"{text[0:2]}:{text[2:4]}:{text[4:6]}"
    return mapped_duration(clock, record_id=source_key, source_field="306$a")


def duration_from_008(marc_record, source_key) -> str | None:
    """Return the running time 008 states, in minutes."""
    raw = fixed_position(marc_record.control_field("008"), 18, 3)
    if not raw or set(raw) <= {" ", "|", "#"}:
        return None
    if raw == "nnn":
        return None
    if raw in ("000", "---"):
        report_issue(
            "info",
            "008 states that the running time is unknown or exceeds"
            " three digits",
            record_id=source_key,
            source_field="008/18-20",
            target_field="has_duration.has_value",
            raw_value=raw,
        )
        return None
    if not raw.isdigit():
        report_issue(
            "warning",
            "008 running time is not a number of minutes",
            record_id=source_key,
            source_field="008/18-20",
            target_field="has_duration.has_value",
            raw_value=raw,
        )
        return None
    return mapped_duration(
        raw, "min", record_id=source_key, source_field="008/18-20"
    )


def duration_from_extent(value: str, source_key) -> str | None:
    """Return the running time stated in a 300 $a extent statement."""
    match = PARENTHESISED_DURATION.search(value)
    if not match:
        return None
    unit = "sec" if match.group(2).lower().startswith("s") else "min"
    return mapped_duration(
        match.group(1),
        unit,
        record_id=source_key,
        source_field="300$a",
    )


def item_extent(marc_record, source_key):
    """Return the length of a copy in feet or metres, if stated."""
    for value in marc_record.subfields("300", "a"):
        match = EXTENT_PATTERN.search(value)
        if not match:
            continue
        unit = "Feet" if match.group(2).lower().startswith("f") else "Metre"
        amount = match.group(1).replace(",", ".")
        report_issue(
            "info",
            "Length taken from the extent statement",
            record_id=source_key,
            source_field="300$a",
            target_field="has_extent",
            raw_value=value,
        )
        return efi.Extent(has_unit=efi.UnitEnum(unit), has_value=amount)
    return None


def item_languages(marc_record, source_key):
    """Return the languages of a copy, from 008 and 041."""
    usages: dict[str, list[str]] = {}

    def add(code, usage):
        if code not in usages:
            usages[code] = []
        if usage not in usages[code]:
            usages[code].append(usage)

    fixed = fixed_position(marc_record.control_field("008"), 35, 3)
    for code in language_codes(fixed, source_key, "008/35-37"):
        add(code, "NoDialogue" if code == "zxx" else "SpokenLanguage")
    for data_field in marc_record.fields("041"):
        for value in data_field.subfield_values("a"):
            for code in language_codes(value, source_key, "041$a"):
                add(code, "NoDialogue" if code == "zxx" else "SpokenLanguage")
        for value in data_field.subfield_values("j"):
            for code in language_codes(value, source_key, "041$j"):
                add(code, "Subtitles")
        for code in ("b", "h"):
            for value in data_field.subfield_values(code):
                report_issue(
                    "info",
                    "Language of summary or of the original has no"
                    " AVefi usage and is not transferred",
                    record_id=source_key,
                    source_field=f"041${code}",
                    target_field="in_language",
                    raw_value=value,
                )
    return [
        efi.Language(
            code=efi.LanguageCodeEnum(code),
            usage=[efi.LanguageUsageEnum(usage) for usage in usage_values],
        )
        for code, usage_values in usages.items()
    ]


def language_codes(raw: str | None, source_key, source_field):
    """Yield the ISO 639-2/B codes a MARC language field carries.

    A MARC language field may hold several three character codes in a
    row, which is why the value is split before it is validated.

    """
    text = (raw or "").strip().lower()
    if not text or is_fill(text[0]):
        return
    chunks = (
        [text[i : i + 3] for i in range(0, len(text), 3)]
        if len(text) > 3 and len(text) % 3 == 0
        else [text]
    )
    for chunk in chunks:
        try:
            yield efi.LanguageCodeEnum(chunk).value
        except ValueError:
            report_issue(
                "warning",
                "Not an ISO 639-2/B language code known to AVefi",
                record_id=source_key,
                source_field=source_field,
                target_field="in_language",
                raw_value=chunk,
            )


def item_notes(marc_record, source_key):
    """Yield the notes a copy carries, in a stable order."""
    for tag in ("300", "500", "508", "511", "546", "852"):
        for data_field in marc_record.fields(tag):
            text = field_text(data_field, note_subfields(tag))
            if not text:
                continue
            if tag in ("508", "511"):
                report_issue(
                    "info",
                    "Credits kept as a note, free text cannot be split"
                    " into agents and activities reliably",
                    record_id=source_key,
                    source_field=tag,
                    target_field="has_note",
                    raw_value=text,
                )
            label = NOTE_LABELS.get(tag)
            yield f"{label}: {text}" if label else text


def note_subfields(tag: str):
    """Return the subfields of a note field that carry text."""
    if tag == "852":
        return ("a", "b", "c", "h", "j", "p")
    if tag == "300":
        return ("a", "b", "c", "e")
    return None


def manifestation_notes(marc_record, source_key):
    """Yield the notes that belong to the manifestation."""
    for data_field in marc_record.fields("250"):
        text = field_text(data_field, ("a", "b"))
        if not text:
            continue
        report_issue(
            "info",
            "Edition statement kept as a note, AVefi having no edition field",
            record_id=source_key,
            source_field="250",
            target_field="has_note",
            raw_value=text,
        )
        yield f"{NOTE_LABELS['250']}: {text}"


def shelf_marks(marc_record) -> list[str]:
    """Return the shelving control numbers a record states.

    A shelf mark is unique within the holding institution only, so it
    is qualified with the institution code of 852 $a where the record
    supplies one, in the same notation as the record identifier.

    """
    marks = []
    for data_field in marc_record.fields("852"):
        institution = (data_field.subfield("a") or "").strip()
        for value in data_field.subfield_values("j"):
            mark = value.strip()
            if not mark:
                continue
            marks.append(f"({institution}){mark}" if institution else mark)
    return marks


# --- text helpers -----------------------------------------------------


def field_text(data_field, codes=None) -> str:
    """Return the text of a data field, subfields joined by a space."""
    return " ".join(
        subfield.value
        for subfield in data_field.subfields
        if subfield.value and (codes is None or subfield.code in codes)
    ).strip()


def strip_isbd(value: str) -> str:
    """Return a subfield value without its trailing ISBD markup."""
    return ISBD_TRAILING.sub("", value or "").strip()


def strip_trailing_period(value: str) -> str:
    """Return a value without a terminating full stop."""
    return TRAILING_PERIOD.sub("", value or "").strip()
