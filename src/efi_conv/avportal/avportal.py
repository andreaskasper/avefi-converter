from collections import defaultdict
import copy
import logging
import re

from avefi_schema import model_pydantic_v2 as efi
from xsdata.formats.dataclass.parsers import XmlParser

from ..core.settings import settings
from ..core.utils import described_by_issuer
from .generated.ntm_4_avefi import ntm_4_av_efi as ntm
from .generated.ntm_4_avefi import ntm_4_av_efi_schema as ntm_main

ROOT_CLASS = ntm_main.Resource
log = logging.getLogger(__name__)
parser = XmlParser()
DESCRIPTION = "TIB AV-Portal, records in the in-house NTM schema"
INPUT_FORMAT = "XML (NTM metadata schema 2.5)"
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/isil/DE-89",
    "has_issuer_name": "Technische Informationsbibliothek (TIB)",
}


def efi_import(input_file) -> list[efi.MovingImageRecord]:
    input = read_input(input_file)
    return map_to_efi(input)


def read_input(input_file) -> ROOT_CLASS:
    return parser.parse(input_file, ROOT_CLASS)


def map_to_efi(input: ROOT_CLASS) -> list[efi.MovingImageRecord]:
    efi_records = []
    source_key = str(input.identifier)

    # work
    titles = input.titles.title
    primary_title, alternative_titles = process_titles(titles)
    work = efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=primary_title,
        has_alternative_title=alternative_titles,
    )
    production_year = get_iso_date(
        input.production_year, input.iwf_production_year
    )
    if production_year:
        if (
            input.production_year
            and input.iwf_production_year
            and input.production_year not in input.iwf_production_year
        ):
            log.warning(
                f"Contradicting values:"
                f" productionYear={input.production_year},"
                f" iwfProductionYear={input.iwf_production_year}"
            )
    else:
        log.warning("No production year")
    event = efi.ProductionEvent(has_date=production_year)
    work.has_event.append(event)

    # agents and their roles
    contrib_dict = defaultdict(list)
    for c in input.creators.creator if input.creators else []:
        if not c.creator_name:
            continue

        match_dict = re.match(
            r"^(?P<name>.*?)( *\((?P<role>.*)\))?$",
            c.creator_name,
        ).groupdict()

        agent = agent_from_name(match_dict["name"])
        if agent is None:
            continue

        if c.name_identifier:
            raise RuntimeError(f"Cannot handle name_identifier for {c}")

        # Disregard occurrences of "IWF (Hrsg.)" if duplicated as publisher
        role = match_dict.get("role")
        if role and role.lower() == "hrsg.":
            name_lower = agent.has_name.lower()
            if input.publishers and any(
                name_lower in p.publisher_name.lower()
                for p in input.publishers.publisher
            ):
                continue
            role = "publisher"
        else:
            role = "creator"
        activity_type = resolve_role(role, c.creator_name)
        if activity_type is None:
            continue
        append_if_no_equal(agent, contrib_dict[activity_type])

    for p in input.producers.producer if input.producers else []:
        if not p.producer_name:
            continue

        match_dict = re.match(
            r"^(?P<name>.*?)( *\((?P<location>.*)\))?$",
            p.producer_name,
        ).groupdict()

        if match_dict["location"]:
            event.located_in.append(
                efi.GeographicName(has_name=match_dict["location"])
            )

        agent = agent_from_name(match_dict["name"])
        if agent is None:
            continue

        if p.name_identifier:
            raise RuntimeError(f"Cannot handle name_identifier for {p}")

        append_if_no_equal(agent, contrib_dict[role_mapping["producer"]])

    for contributor in (
        input.contributors.contributor if input.contributors else []
    ):
        if not contributor.contributor_name:
            continue

        for unit in contributor.contributor_name.split(";"):
            match = re.search(r"^([^(]*) \(([^()]*).", unit)
            if match:
                name, roles = match.groups()
            else:
                name = unit
                roles = "unknown"
            agent = agent_from_name(name)
            if agent is None:
                continue
            for match in re.finditer(
                r"([^,/]+)(, +|/|$)",
                re.sub(r" +und ", ", ", roles),
            ):
                role = match.groups()[0].strip()
                activity_type = resolve_role(role, roles)
                if activity_type is None:
                    continue
                append_if_no_equal(agent, contrib_dict[activity_type])

    extract_activities_for_event(event, contrib_dict)

    if input.genre and input.genre.value:
        work.has_genre.append(efi.Genre(has_name=input.genre.value))
    for subject_area in (
        input.subject_areas.subject_area if input.subject_areas else []
    ):
        if subject_area.value == "Arts and Media":
            keywords = ["Arts", "Media"]
        else:
            keywords = subject_area.value.split("/")
        for k in keywords:
            gnd_id = subject_area_to_gnd_mapping.get(k)
            if gnd_id is None:
                log.warning(
                    f"No GND identifier known for subject area '{k}',"
                    f" keeping the subject without an authority link"
                )
                work.has_subject.append(efi.Subject(has_name=k))
                continue
            work.has_subject.append(
                efi.Subject(
                    has_name=k,
                    same_as=[efi.GNDResource(id=gnd_id)],
                )
            )
    for k in input.keywords.keyword if input.keywords else []:
        work.has_subject.append(efi.Subject(has_name=k.value))
    identifiers = input.alternate_identifiers
    if identifiers:
        for id in identifiers.alternate_identifier:
            if not (id.value.startswith("10.5240/")):
                raise RuntimeError(f"Cannot handle identifier_type: {id}")
            work.same_as.append(efi.EIDRResource(id=id.value))
    work_id = efi.LocalResource(id=f"{source_key}_work")
    work.has_identifier.append(work_id)
    described_by = described_by_issuer(work, ISSUER_INFO)
    if source_key not in described_by.has_source_key:
        described_by.has_source_key.append(source_key)
    efi_records.append(work)

    # manifestation
    manifestation_title = copy.deepcopy(work.has_primary_title)
    manifestation_title.type = efi.TitleTypeEnum("TitleProper")
    manifestation = efi.Manifestation(
        is_manifestation_of=[work_id], has_primary_title=manifestation_title
    )
    for description in (
        input.descriptions.description if input.descriptions else []
    ):
        # Recon with <br/> elements accepted by the NTM schema
        note = "\n".join(
            [text for text in description.content if isinstance(text, str)]
        )
        if note:
            manifestation.has_note.append(note)
    publication_year = get_iso_date(
        input.publication_year, input.iwf_publication_year
    )
    if (
        publication_year
        or (input.publishers and input.publishers.publisher)
        or any(contrib_dict.get(role) for role in manifestation_roles)
    ):
        publication = efi.PublicationEvent(
            type=efi.PublicationEventTypeEnum("ReleaseEvent")
        )
        manifestation.has_event.append(publication)

        for p in input.publishers.publisher if input.publishers else []:
            match_dict = re.match(
                r"^(?P<name>.*?)( *\((?P<location>.*)\))?$",
                p.publisher_name,
            ).groupdict()

            if match_dict["location"]:
                location_lower = match_dict["location"].lower()
                if any(
                    expr in location_lower
                    for expr in CORPORATE_BODY_FLAG_WORDS
                ):
                    publisher_name = p.publisher_name
                else:
                    append_if_no_equal(
                        efi.GeographicName(has_name=match_dict["location"]),
                        publication.located_in,
                    )
                    publisher_name = match_dict["name"]
            else:
                publisher_name = p.publisher_name

            agent = agent_from_name(publisher_name)
            if agent is None:
                continue

            if p.name_identifier:
                raise RuntimeError(f"Cannot handle name_identifier for {p}")

            append_if_no_equal(agent, contrib_dict[role_mapping["publisher"]])

        extract_activities_for_event(publication, contrib_dict)
        if publication_year:
            publication.has_date = publication_year
    manifestation_id = efi.LocalResource(id=f"{source_key}_manifestation")
    manifestation.has_identifier.append(manifestation_id)
    described_by = described_by_issuer(manifestation, ISSUER_INFO)
    if source_key not in described_by.has_source_key:
        described_by.has_source_key.append(source_key)
    efi_records.append(manifestation)

    # item
    item = efi.Item(
        is_item_of=manifestation_id,
        has_primary_title=copy.deepcopy(manifestation.has_primary_title),
    )

    if input.language:
        if input.language == "qot":
            item.has_sound_type = efi.SoundTypeEnum("Sound")
            item.in_language.append(
                efi.Language(usage=[efi.LanguageUsageEnum("NoDialogue")])
            )
        elif input.language == "qno":
            item.has_sound_type = efi.SoundTypeEnum("Silent")
        else:
            item.in_language.append(
                efi.Language(
                    code=input.language,
                    usage=[efi.LanguageUsageEnum("SpokenLanguage")],
                )
            )
    # Todo: format
    if input.size:
        match = re.search(r"^([\d,]+) *(\w+)$", input.size)
        if match is None:
            raise RuntimeError(f"No idea how to parse size={input.size}")
        value, unit = match.groups()
        value = value.replace(",", ".")
        item.has_extent = efi.Extent(
            has_value=value, has_unit=size_mapping[unit]
        )
    if input.duration:
        match = re.search(r"^(\d\d):(\d\d):(\d\d):\d\d$", input.duration)
        if match is None:
            raise RuntimeError(
                f"No idea how to parse duration={input.duration}"
            )
        duration_str = ""
        for val, suffix in zip(match.groups(), ("H", "M", "S"), strict=True):
            i = int(val)
            if i or (not duration_str and suffix == "S"):
                duration_str += f"{str(i)}{suffix}"
        duration_str = f"PT{duration_str}"
        item.has_duration = efi.Duration(has_value=duration_str)

    # External identifiers
    if input.doi:
        item.same_as.append(efi.DOIResource(id=input.doi))

    # links
    if input.links:
        for link in input.links.link:
            if link.link_type == ntm.LinkType.AV_PORTAL:
                item.has_webresource.append(link.value)

    item_id = efi.LocalResource(id=f"{source_key}_item")
    item.has_identifier.append(item_id)
    described_by = described_by_issuer(item, ISSUER_INFO)
    described_by.has_source_key.append(source_key)
    efi_records.append(item)
    return efi_records


def get_iso_date(year: str | None, iwf_year: str | None) -> str | None:
    """Extract a year or period in keeping with ISO 8601.

    iwf_production_year and iwf_publication_year in the NTM schema
    seem to provide more extensive information than their counterparts
    without the iwf_ prefix. Try to make sense of that information if
    present and resort to the simpler fields when that does not work
    out.

    Parameters
    ----------
    year : str
        Input from production_year or publication_year.
    iwf_year : str
        Input from iwf_production_year or iwf_publication.

    """
    for iso_date in (iwf_year, year):
        if not iso_date:
            continue
        if not isinstance(iso_date, str):
            iso_date = str(iso_date)
        m = re.match(
            r"^(?P<from_year>(?P<from_cent>\d\d)\d\d)\D.*?"
            r"(?P<to_cent>\d\d)?(?P<to>\d\d)$",
            iso_date,
        )
        if m:
            period = m.groupdict()
            to_cent = period["to_cent"] or period["from_cent"]
            from_year = period["from_year"]
            to_year = f"{to_cent}{period['to']}"
            if from_year > to_year:
                log.warning(
                    f"Ignoring implausible period '{iso_date}', falling"
                    f" back to the simpler field"
                )
                continue
            iso_date = f"{from_year}/{to_year}"
        else:
            m = re.match(r"^ca. (?P<year>\d\d\d\d)([,; ]|$)", iso_date)
            if m:
                iso_date = f"{m.groupdict()['year']}~"
        if is_iso_date(iso_date):
            break
    else:
        year = year or iwf_year
        if year is not None and not isinstance(year, str):
            year = str(year)
        if not year or re.match(r"o\. *a\.", year.lower()):
            return None
        else:
            raise ValueError(
                f"Expected date or interval according to ISO 8601,"
                f" got: {year or iwf_year}"
            )
    return iso_date


def is_iso_date(date_str):
    return bool(
        re.search(
            r"^-?([1-9][0-9]{3,}|0[0-9]{3})(-(0[1-9]|1[0-2])"
            "(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?(/-?([1-9][0-9]{3,}|0[0-9]{3})"
            "(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?)?$",
            date_str,
        )
    )


CORPORATE_BODY_FLAG_WORDS = [
    " ag ",
    " ag, ",
    "amt",
    "anstalt",
    "archiv",
    "atelier",
    "bhwk",
    "bildstelle",
    "cinematogra",
    "expedition",
    "film",
    "foundation",
    "fwu",
    "gesellschaft",
    "gmbh",
    "hochschule",
    "hospital",
    "inc.",
    "informationsdienst",
    "institut",
    "iwf",
    "klinik",
    "krankenhaus",
    "labor",
    "ltd.",
    "media",
    "museum",
    "öwf",
    "production",
    "produktion",
    "rfdu",
    "rundfunk",
    "rwu",
    "seminar",
    "studio",
    " tv ",
    "universit",  # matches university and universität
    "verband",
    "vereinigung",
    "-werke",
    "zkm",
]


def append_if_no_equal(item, some_list: list) -> bool:
    """Append item and return True if no other list element is equal."""
    if any(el == item for el in some_list):
        return False
    else:
        some_list.append(item)
        return True


def agent_from_name(
    name: str,
    type: efi.AgentTypeEnum | None = None,
) -> efi.Agent | None:
    """Return agent compliant with AVefi submission guide lines.

    Return agent as specified by ``name`` and ``type`` as provided. If
    ``type`` is not specified, check name for certain keywords
    indicating that it refers to a corporate body rather than a
    person. If it appears to be a person, after all, try to make sure
    it is in the form "family name, given name".

    Note that ``name`` will be rearranged for persons if it does not
    contain a comma by moving the last word to the front, followed by
    a comma and the rest of the name.

    Parameters
    ----------
    name : str
        Name of the agent.
    type : efi.AgentTypeEnum (optional)
        Type of agent.

    Returns
    -------
    efi.Agent | None
        Agent, with type derived from name if none was specified.

    """
    name = name.strip()
    lower_name = name.lower()
    if lower_name in ("n. n.", "nn"):
        return None
    if type is None and (
        any(expr in lower_name for expr in CORPORATE_BODY_FLAG_WORDS)
        or lower_name.endswith(" ag")
    ):
        agent = efi.Agent(
            has_name=name, type=efi.AgentTypeEnum("CorporateBody")
        )
    elif type is not None and type != efi.AgentTypeEnum("Person"):
        agent = efi.Agent(has_name=name, type=type)
    else:
        orig_name = None
        name_components = name.split(",")
        if len(name_components) == 1:
            if len(name.split()) > 4:
                log.warning(f"Left unusual name unchanged: {name}")
            else:
                name_components = name.rsplit(maxsplit=1)
                if len(name_components) > 1:
                    orig_name = name
                    name = ", ".join(reversed(name_components))
                    log.info(f"Replaced name '{orig_name}' by '{name}'")
        elif len(name_components) != 2:
            raise ValueError(
                f"Name probably not in correct format"
                f" (family_name, given_name): {name}"
            )
        agent = efi.Agent(has_name=name, type=efi.AgentTypeEnum("Person"))
        if orig_name:
            agent.has_alternate_name.append(orig_name)
    return agent


def extract_activities_for_event(
    event: efi.Event, activities_by_type: dict[str, efi.Activity]
):
    """Extract activities according to has_activity range of event."""
    event_activities = event.linkml_meta.get("slot_usage", {}).get(
        "has_activity", {}
    )
    if event_activities.get("any_of"):
        ranges = [
            el.get("range")
            for el in event_activities["any_of"]
            if el.get("range")
        ]
    else:
        slot_range = event_activities.get("range")
        ranges = [slot_range] if slot_range else []

    activity_dict = activities_by_type.copy()
    for activity_type, agents in activity_dict.items():
        # Drop TypeEnum suffix to get the required class name.
        activity_class_name = activity_type.__class__.__name__[:-8]
        if activity_class_name in ranges:
            activity = getattr(efi, activity_class_name)(
                type=activity_type,
                has_agent=agents,
            )
            event.has_activity.append(activity)
            del activities_by_type[activity_type]


def process_titles(
    titles: list[ntm.TitleType],
) -> tuple[efi.Title | list[efi.Title]]:
    """Return primary and a list of alternative titles.

    Identify preferred title, append the subtitle if present, and
    return it as primary title. Also, return a (possibly empty) list
    of alternative titles.

    Parameters
    ----------
    titles : list(ntm.TitleType)
        List of titles according to NTM schema.

    Returns
    -------
    tuple(efi.Title, list(efi.Title))
        Primary and list of alternative titles.

    """
    input_primary_title = input_subtitle = None
    alternative_titles = []
    for title in titles:
        if not (title.value.strip()):
            continue
        if title.title_type is None:
            if input_primary_title:
                raise RuntimeError(f"Cannot determine primary title: {titles}")
            input_primary_title = title
        elif title.title_type == ntm.TitleType.SUBTITLE:
            if input_subtitle:
                raise RuntimeError(
                    f"Cannot associate subtitle to primary title: {titles}"
                )
            input_subtitle = title
        elif title.title_type == ntm.TitleType.ALTERNATIVE_TITLE:
            alternative_titles.append(
                make_title(title, efi.TitleTypeEnum("AlternativeTitle"))
            )
        else:
            raise RuntimeError(f"No mapping specified for title type: {title}")
    if input_primary_title is None:
        raise ValueError(
            f"No untyped title available to serve as primary title: {titles}"
        )
    if input_subtitle and input_subtitle.value.strip() not in [
        t.has_name for t in alternative_titles
    ]:
        if input_subtitle.language != input_primary_title.language:
            raise RuntimeError(
                f"Languages do not match for primary and subtitle: {titles}"
            )
        input_primary_title.value = " - ".join(
            [input_primary_title.value, input_subtitle.value]
        )
    primary_title = make_title(
        input_primary_title, efi.TitleTypeEnum("PreferredTitle")
    )
    return primary_title, alternative_titles


def resolve_role(role: str, context: str):
    """Return the activity type for ``role`` or None if unknown.

    The role strings come from free text supplied by a third party, so
    an unknown value must not abort the conversion of a whole file.

    """
    try:
        return role_mapping[role]
    except KeyError:
        log.warning(
            f"No mapping specified for role '{role}', skipping the"
            f" corresponding agent: {context}"
        )
        return None


def make_title(input_title, title_type: efi.TitleTypeEnum) -> efi.Title:
    display_title = re.sub(r"\s+", " ", input_title.value.strip())
    result = efi.Title(type=title_type, has_name=display_title)
    split_title = display_title.split(maxsplit=1)
    known_articles = articles.get(input_title.language)
    if known_articles is None:
        if input_title.language is not None:
            log.warning(
                f"No article list configured for language"
                f" '{input_title.language}', leaving ordering name unset:"
                f" {display_title}"
            )
        known_articles = ()
    if len(split_title) > 1 and split_title[0].lower() in known_articles:
        first, rest = split_title
        result.has_ordering_name = f"{rest}, {first}"
        log.warning(
            f"Pushing article to back of ordering name for title:"
            f" {result.has_ordering_name}"
        )
    if len(display_title) > settings.line_limit:
        result.has_name = f"{display_title[: settings.line_limit - 3]}..."
        if result.has_ordering_name:
            result.has_ordering_name = result.has_ordering_name[
                : settings.line_limit
            ]
        log.warning(
            f"Shortening title that exceeded line limit of"
            f" {settings.line_limit} characters: {result.has_name}"
        )
    return result


articles = {
    "eng": ["a", "an", "the"],
    "ger": ["das", "der", "die", "ein", "eine"],
}


role_mapping = {
    "3D-Animation": efi.SpecialEffectsActivityTypeEnum("VisualEffects"),
    "Animation": efi.AnimationActivityTypeEnum("Animation"),
    "Anthropologe": efi.ProducingActivityTypeEnum("Advisor"),
    "Assistenz": efi.ProducingActivityTypeEnum("Advisor"),
    "ausführender Produzent": efi.ProducingActivityTypeEnum(
        "ExecutiveProducer"
    ),
    "Bearb.": efi.WritingActivityTypeEnum("Adaptation"),
    "Bearbeitung": efi.WritingActivityTypeEnum("Adaptation"),
    "Berater": efi.ProducingActivityTypeEnum("Advisor"),
    "Beratung": efi.ProducingActivityTypeEnum("Advisor"),
    "Bildmischung": efi.EditingActivityTypeEnum("FilmEditor"),
    "Buch": efi.WritingActivityTypeEnum("Writer"),
    "Bühnenbild": efi.ProductionDesignActivityTypeEnum("SetDesigner"),
    "Chorleitung": efi.MusicActivityTypeEnum("MusicConductor"),
    "Computeranimation": efi.AnimationActivityTypeEnum("ComputerAnimation"),
    "Computergraphik": efi.SpecialEffectsActivityTypeEnum("CGIArtist"),
    "Datenkonvertierung": efi.EditingActivityTypeEnum("FilmEditor"),
    "Design": efi.WritingActivityTypeEnum("Stagedby"),
    "Dramaturgie": efi.ProducingActivityTypeEnum("Advisor"),
    "Dramaturgische Beratung": efi.ProducingActivityTypeEnum("Advisor"),
    "Drehbuch": efi.WritingActivityTypeEnum("Writer"),
    "DVD-Authoring": efi.ProducingActivityTypeEnum("PostProductionSupervisor"),
    "DVD-Redaktion": efi.ProducingActivityTypeEnum("PostProductionSupervisor"),
    "elektronische Aufzeichnung": efi.EditingActivityTypeEnum("FilmEditor"),
    "Ethnologie": efi.ProducingActivityTypeEnum("Advisor"),
    "Ethnographie": efi.ProducingActivityTypeEnum("Advisor"),
    "Fachreferat": efi.ProducingActivityTypeEnum("Advisor"),
    "Filmabtastung": efi.EditingActivityTypeEnum("FilmEditor"),
    "Fotografie": efi.CinematographyActivityTypeEnum("StillPhotographer"),
    "Fotorecherche": efi.WritingActivityTypeEnum("Research"),
    "Gestaltung": efi.CinematographyActivityTypeEnum("Cinematographer"),
    "Grafik": efi.AnimationActivityTypeEnum("Animator"),
    "Graphik": efi.AnimationActivityTypeEnum("Animator"),
    "Inszenierung": efi.WritingActivityTypeEnum("Stagedby"),
    "Interview": efi.CastActivityTypeEnum("Interviewer"),
    "Kamera": efi.CinematographyActivityTypeEnum("Cinematographer"),
    "kamera": efi.CinematographyActivityTypeEnum("Cinematographer"),
    "Kameraassistenz": efi.CinematographyActivityTypeEnum("CameraAssistant"),
    "Kommentar": efi.WritingActivityTypeEnum("NarrationWriter"),
    "Kommentartext": efi.WritingActivityTypeEnum("NarrationWriter"),
    "Komposition": efi.MusicActivityTypeEnum("Composer"),
    "Kostüme": efi.ProductionDesignActivityTypeEnum("CostumeDesigner"),
    "Libretto": efi.WritingActivityTypeEnum("Writer"),
    "Licht": efi.CinematographyActivityTypeEnum("GafferLighting"),
    "Lichtbestimmung": efi.LaboratoryActivityTypeEnum("Colorist"),
    "MAZ-Schnitt": efi.EditingActivityTypeEnum("FilmEditor"),
    "MAZ-Technik": efi.EditingActivityTypeEnum("FilmEditor"),
    "Maz-Technik": efi.EditingActivityTypeEnum("FilmEditor"),
    "Mikrokinematographie": efi.CinematographyActivityTypeEnum(
        "Cinematographer"
    ),
    "Mikrokinematographie-Assistenz": efi.CinematographyActivityTypeEnum(
        "CameraAssistant"
    ),
    "Musik": efi.MusicActivityTypeEnum("MusicPerformer"),
    "musikalische Leitung": efi.MusicActivityTypeEnum("MusicSupervisor"),
    "Orchester": efi.MusicActivityTypeEnum("MusicPerformer"),
    "Postproduktion": efi.ProducingActivityTypeEnum(
        "PostProductionSupervisor"
    ),
    "Präparation": efi.CinematographyActivityTypeEnum("Cinematographer"),
    "Produktion": efi.ProducingActivityTypeEnum("Producer"),
    "Produktionsleitung": efi.ProducingActivityTypeEnum("Producer"),
    "Projektkoordination": efi.ProducingActivityTypeEnum(
        "ProductionCoordinator"
    ),
    "Projektleitung": efi.WritingActivityTypeEnum("Editor"),
    "Psychiater": efi.ProducingActivityTypeEnum("Advisor"),
    "Red.": efi.WritingActivityTypeEnum("Editor"),
    "Redaktion": efi.WritingActivityTypeEnum("Editor"),
    "Redaktionsassistenz": efi.WritingActivityTypeEnum("AssistantEditor"),
    "Regie": efi.DirectingActivityTypeEnum("Director"),
    "Regieassistenz": efi.DirectingActivityTypeEnum("AssistantDirector"),
    "Sachbearbeiter": efi.ProducingActivityTypeEnum("ProductionAccountant"),
    "Schnitt": efi.EditingActivityTypeEnum("FilmEditor"),
    "Sprecher": efi.CastActivityTypeEnum("Narrator"),
    "Sprecherin": efi.CastActivityTypeEnum("Narrator"),
    "technische Assistenz": efi.CinematographyActivityTypeEnum("VideoAssist"),
    "technische Leitung": efi.CinematographyActivityTypeEnum("VideoAssist"),
    "Text": efi.WritingActivityTypeEnum("SourceMaterial"),
    "Ton": efi.SoundActivityTypeEnum("SoundRecorderMixer"),
    "Tonmischung": efi.SoundActivityTypeEnum("SoundRecorderMixer"),
    "Trick": efi.AnimationActivityTypeEnum("Animator"),
    "Typografie": efi.WritingActivityTypeEnum("SourceMaterial"),
    "Übersetzung": efi.WritingActivityTypeEnum("SourceMaterial"),
    "Untertitel": efi.EditingActivityTypeEnum("FilmEditor"),
    "Videobearbeitung": efi.CinematographyActivityTypeEnum("VideoAssist"),
    "Videotechnik": efi.CinematographyActivityTypeEnum("VideoAssist"),
    "wissenschaftl. Betreuung": efi.ProducingActivityTypeEnum("Advisor"),
    "wissenschaftliche Beratung": efi.ProducingActivityTypeEnum("Advisor"),
    "wissenschaftliche Mitarbeit": efi.ProducingActivityTypeEnum("Advisor"),
    # These keys are used internally in this module
    "creator": efi.DirectingActivityTypeEnum("Creator"),
    "producer": efi.ProducingActivityTypeEnum("Producer"),
    "publisher": efi.ManifestationActivityTypeEnum("Publisher"),
    "unknown": efi.ManifestationActivityTypeEnum("UnknownActivity"),
}


manifestation_roles = ["Lichtbestimmung", "Unknown"]


size_mapping = {
    "GB": efi.UnitEnum("GigaByte"),
    "MB": efi.UnitEnum("MegaByte"),
}


subject_area_to_gnd_mapping = {
    "Architecture": "4002851-3",
    "Arts": "4114333-4",
    # Arts und Media sind im NTM-Schema zusammengefasst
    "Media": "4169187-8",
    "Chemistry": "4009816-3",
    "Computer Science": "4026894-9",
    "Earth Sciences": "4020288-4",
    "Economics": "4066399-1",
    # Economics und Social Sciences sind im NTM-Schema zusammengefasst
    "Social Sciences": "4055916-6",
    "Educational Science": "4044302-4",
    "Engineering": "4137304-2",
    "Environmental Sciences": "4137364-9",
    # Environmental Sciences und Ecology sind im NTM-Schema zusammengefasst
    "Ecology": "4043207-5",
    "Ethnology": "4078931-7",
    "History": "4020517-4",
    "Horticulture": "4019294-5",
    "Information Science": "4128313-2",
    "Law": "4048737-4",
    "Life Sciences": "4129772-6",
    "Linguistics": "4074250-7",
    "Literature Studies": "4036034-9",
    "Mathematics": "4037944-9",
    "Medicine": "4038243-6",
    "Philosophy": "4045791-6",
    "Physics": "4045956-1",
    "Psychology": "4047704-6",
    "Sports Science": "4056442-3",
    "Study of Religions": "4049426-3",
}
