import codecs
import csv
import logging
import pathlib
import re

from avefi_schema import model_pydantic_v2 as efi

from ..core.utils import described_by_issuer

log = logging.getLogger(__name__)
FILE_ENCODING = "iso8859-1"
DELIMITER = ";"
# Key under which csv.DictReader collects unexpected extra columns
EXTRA_COLUMNS = "_unexpected_columns"
FIELD_NAMES = (
    "source_key",
    "_object_number",
    "work_title",
    "director",
    "production_year",
    "country",
    "provider",
    "manifestation_title",
    "SpokenLanguage",
    "Subtitles",
    "Intertitles",
    "colour_type",
    "item_title",
    "access_status",
    "format",
)
DESCRIPTION = "Filmmuseum der Landeshauptstadt Düsseldorf, holdings export"
INPUT_FORMAT = "CSV (semicolon separated, ISO 8859-1)"
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/isil/DE-MUS-432511",
    "has_issuer_name": "Filmmuseum der Landeshauptstadt Düsseldorf",
}


def efi_import(input_file) -> list[efi.MovingImageRecord]:
    parsed_input = read_input(input_file)
    return map_to_efi(parsed_input)


def read_input(input_file, encoding=FILE_ENCODING) -> list[dict]:
    """Read the export and return its data rows.

    Column names are taken from the positional ``FIELD_NAMES`` tuple,
    so the header line of the input is validated rather than silently
    discarded: a changed column count would otherwise shift every value
    into the wrong AVefi field without any error.

    """
    with pathlib.Path(input_file).open(encoding=encoding) as f:
        parsed_input = list(
            csv.DictReader(
                f,
                delimiter=DELIMITER,
                fieldnames=FIELD_NAMES,
                restkey=EXTRA_COLUMNS,
            )
        )

    if not parsed_input:
        log.warning(f"No rows found in {input_file}")
        return []

    header = parsed_input[0]
    check_header(header, input_file)
    warn_about_encoding(header, encoding, input_file)

    # Drop the header line
    return parsed_input[1:]


def check_header(header: dict, input_file):
    """Fail loudly when the input does not have the expected columns."""
    if header.get(EXTRA_COLUMNS):
        raise ValueError(
            f"{input_file} has more columns than expected"
            f" ({len(FIELD_NAMES)}); unexpected values:"
            f" {header[EXTRA_COLUMNS]}"
        )
    missing = [name for name in FIELD_NAMES if header.get(name) is None]
    if missing:
        raise ValueError(
            f"{input_file} is missing expected column(s): {', '.join(missing)}"
        )
    log.debug(
        f"Header of {input_file} mapped positionally to {FIELD_NAMES}:"
        f" {[header[name] for name in FIELD_NAMES]}"
    )


def warn_about_encoding(header: dict, encoding: str, input_file):
    """Warn when the input looks like UTF-8 read as an 8 bit encoding.

    Single byte encodings decode any byte sequence, so a UTF-8 export
    is not rejected but silently turned into mojibake. Spotting the
    typical sequences is the only chance to notice.

    """
    if codecs.lookup(encoding).name.startswith("utf"):
        return
    suspicious = ("Ã¤", "Ã¶", "Ã¼", "ÃŸ", "Ã©", "Ã\x9f", "â€")
    sample = "".join(str(value) for value in header.values())
    if any(marker in sample for marker in suspicious):
        log.warning(
            f"{input_file} looks like UTF-8 but is being read as"
            f" {encoding}; non-ASCII characters will be mangled"
        )


def lookup(mapping: dict, value, field: str, source_key: str):
    """Return ``mapping[value]`` or raise a message naming the row."""
    try:
        return mapping[value]
    except KeyError:
        raise ValueError(
            f"No mapping specified for {field} value '{value}'"
            f" in record {source_key}; known values:"
            f" {', '.join(sorted(str(k) for k in mapping))}"
        ) from None


def map_to_efi(
    parsed_input: list[dict],
) -> list[efi.MovingImageRecord]:
    efi_records = []
    work_man_lookup = {}
    for row in parsed_input:
        source_key = row["source_key"]
        work_key = re.sub(
            r"\W\+",
            "",
            f"{row['work_title']}__{row['director']}"
            f"__{row['production_year']}",
        )
        work_fields = dict(
            (key, row[key])
            for key in ("work_title", "director", "production_year", "country")
        )
        if work_key not in work_man_lookup:
            work_title = make_title(row["work_title"], "PreferredTitle")
            work = efi.WorkVariant(
                type=efi.WorkVariantTypeEnum("Monographic"),
                has_primary_title=work_title,
            )
            work_man_lookup[work_key] = {
                "work_fields": work_fields,
                "work": work,
                "manifestations": {},
            }
            year = row["production_year"]
            if not year:
                raise ValueError(f"No production year for {work_key}")
            locations = [
                efi.GeographicName(has_name=country.strip())
                for country in row["country"].split(",")
            ]
            director_names = [d.strip() for d in row["director"].split(",")]
            directors = []
            for name in director_names:
                name_lower = name.lower()
                if (
                    not name_lower
                    or name_lower == "unbekannt"
                    or name_lower == "verschiedene"
                ):
                    continue
                components = name.rsplit(maxsplit=1)
                normalised = ", ".join(reversed(components))
                name_count = len(name.split())
                if name_count > 2:
                    log.warning(
                        f"Replaced name for director '{name}' by"
                        f" '{normalised}'"
                    )
                elif name_count == 1:
                    log.warning(f"Unusual name for director: {name}")
                directors.append(
                    efi.Agent(
                        type=efi.AgentTypeEnum("Person"), has_name=normalised
                    )
                )
            if not any([year, locations, directors]):
                log.warning(f"No production event for {work_key}")
            else:
                event = efi.ProductionEvent()
                year = sanitise_year_of_reference(year, source_key)
                if year:
                    event.has_date = year
                event.located_in.extend(locations)
                if directors:
                    event.has_activity.append(
                        efi.DirectingActivity(
                            type=efi.DirectingActivityTypeEnum("Director"),
                            has_agent=directors,
                        )
                    )
                work.has_event.append(event)
            work_id = efi.LocalResource(id=f"{work_key}_work")
            work.has_identifier.append(work_id)
            efi_records.append(work)
        else:
            if work_man_lookup[work_key]["work_fields"] != work_fields:
                raise ValueError(
                    f"Contradiction in metadata supposedly describing"
                    f" the same work: {work_key}"
                )
            work = work_man_lookup[work_key]["work"]

        # manifestation
        man_fields = tuple(
            row[key]
            for key in (
                "manifestation_title",
                "SpokenLanguage",
                "Subtitles",
                "Intertitles",
                "colour_type",
                "format",
            )
        )
        manifestation = work_man_lookup[work_key]["manifestations"].get(
            man_fields
        )
        if manifestation is None:
            manifestation_title = make_title(
                row["manifestation_title"], "TitleProper"
            )
            manifestation = efi.Manifestation(
                is_manifestation_of=[work.has_identifier[0]],
                has_primary_title=manifestation_title,
            )
            work_man_lookup[work_key]["manifestations"][man_fields] = (
                manifestation
            )
            manifestation_id = efi.LocalResource(
                id=f"{row['manifestation_title']}_{row['production_year']}"
                f"_{row['SpokenLanguage']}_{row['Subtitles']}"
                f"_{row['Intertitles']}_{row['colour_type']}_{row['format']}"
            )
            manifestation.has_identifier.append(manifestation_id)
            efi_records.append(manifestation)

        # item
        item_title = make_title(row["item_title"], "TitleProper")
        item = efi.Item(
            is_item_of=manifestation.has_identifier[0],
            has_primary_title=item_title,
        )
        access_status = lookup(
            access_status_map,
            row["access_status"],
            "access_status",
            source_key,
        )
        if access_status:
            item.has_access_status = efi.ItemAccessStatusEnum(access_status)
        item_format = lookup(format_map, row["format"], "format", source_key)
        if item_format:
            item.has_format.append(efi.Film(type=item_format))
        spoken_lang = row["SpokenLanguage"]
        if spoken_lang == "Ohne Sprache":
            item.in_language.append(
                efi.Language(usage=[efi.LanguageUsageEnum("NoDialogue")])
            )
        elif spoken_lang == "Verschiedene":
            pass
        else:
            item.in_language.extend(
                [
                    efi.Language(
                        code=lookup(
                            language_map, row[usage], usage, source_key
                        ),
                        usage=[efi.LanguageUsageEnum(usage)],
                    )
                    for usage in ("SpokenLanguage", "Subtitles", "Intertitles")
                    if row[usage]
                ]
            )
        colour_type = lookup(
            colour_type_map,
            row["colour_type"],
            "colour_type",
            source_key,
        )
        if colour_type:
            item.has_colour_type = efi.ColourTypeEnum(colour_type)
        item_id = efi.LocalResource(id=source_key)
        item.has_identifier.append(item_id)
        efi_records.append(item)
        for record in (item, manifestation, work):
            described_by = described_by_issuer(record, ISSUER_INFO)
            if described_by.has_source_key is None:
                described_by.has_source_key = []
            if source_key not in described_by.has_source_key:
                described_by.has_source_key.append(source_key)
    return efi_records


_title_cache = {}


def make_title(input_title: str, type_hint: str) -> efi.Title:
    input_title = (input_title or "").strip()
    if not input_title:
        raise ValueError("Cannot build a title from an empty value")
    if input_title[0] == "[" and input_title[-1] == "]":
        title_type = efi.TitleTypeEnum("SuppliedDevisedTitle")
        title_string = input_title[1:-1]
    else:
        title_type = efi.TitleTypeEnum(type_hint)
        title_string = input_title
    if title_string in _title_cache:
        result = efi.Title(type=title_type, **_title_cache[title_string])
    else:
        try:
            main, last = title_string.rsplit(maxsplit=1)
        except ValueError:
            main = None
        if main and main[-1] == "," and last.lower() in articles:
            _title_cache[title_string] = {
                "has_name": " ".join([last, main[:-1]]),
                "has_ordering_name": title_string,
            }
            result = efi.Title(type=title_type, **_title_cache[title_string])
            log.warning(
                f"Reconstructed display title, pushing article to front:"
                f" {result.has_name}"
            )
        else:
            result = efi.Title(type=title_type, has_name=title_string)
    return result


articles = [
    "das",
    "der",
    "die",
    "ein",
    "eine",
    "a",
    "an",
    "the",
    "la",
    "le",
    "les",
    "un",
    "una",
]


def sanitise_year_of_reference(date_string, source_key):
    if not date_string or date_string.lower() == "ohne datum":
        return None
    parts = date_string.split()
    if len(parts) == 2 and parts[0] in month_map:
        result = f"{parts[1]}-{month_map[parts[0]]}"
    else:
        result = re.sub(r" +", "", date_string)
        # Unfortunately, we have to deal with occurrences of 1972-73,
        # which can be misleading, cs we convert to ISO notation. Just
        # consider 2003-04, for instance
        match = re.search(r"^((\d\d)\d\d\D?)[-/](\d\d\D*)$", result)
        if match:
            mgrp = match.groups()
            result = f"{mgrp[0]}/{mgrp[1]}{mgrp[2]}"
            match = None
        else:
            result = re.sub(
                r"^(\d\d)\.-(\d\d)\.(\d\d)\.(\d{4,4})$",
                "\\4-\\3-\\1/\\4-\\3-\\2",
                result,
            )
            result = re.sub(r"^(\d{4,4}\D?)-(\d{4,4}\D?)$", "\\1/\\2", result)
    if not re.search(
        r"^-?([1-9][0-9]{3,}|0[0-9]{3})(-(0[1-9]|1[0-2])"
        r"(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?"
        r"(/-?([1-9][0-9]{3,}|0[0-9]{3})"
        r"(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?)?$",
        result,
    ):
        raise ValueError(f"Invalid date string: {date_string}")
    return result


month_map = {
    "Jan": "01",
    "Feb": "02",
    "Mrz": "03",
    "Mär": "03",
    "Apr": "04",
    "Mai": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Okt": "10",
    "Nov": "11",
    "Dez": "12",
}
language_map = {
    "Arabisch": "ara",
    "Deutsch": "ger",
    "Englisch": "eng",
    "Französisch": "fre",
    "Irakisch": "ara",  # presumably an arabic dialect
    "Italienisch": "ita",
    "Japanisch": "jpn",
    "Jugoslawisch": None,
    "Litauisch": "lit",
    "Niederländisch": "dut",
    "Spanisch": "spa",
    "Portugiesisch": "por",
}
colour_type_map = {
    "": None,
    "(not assigned)": None,
    "Coloriert": "Colourized",
    "Farbe": "Colour",
    "Farbe, SW": "ColourBlackAndWhite",
    "Schwarz-Weiß": "BlackAndWhite",
    "SW, Viragiert": "BlackAndWhiteTinted",
    "Viragiert": "Tinted",
}
access_status_map = {
    "": None,
    "(not assigned)": None,
    "Archivkopie": "Archive",
    "Verleihkopie": "Distribution",
}
format_map = {
    "": None,
    "(not assigned)": None,
    "8mm": efi.FormatFilmTypeEnum("8mmFilm"),
    "16mm": efi.FormatFilmTypeEnum("16mmFilm"),
    "17,5mm": efi.FormatFilmTypeEnum("17.5mmFilm"),
    "35mm": efi.FormatFilmTypeEnum("35mmFilm"),
    "Super8": efi.FormatFilmTypeEnum("Super8mmFilm"),
}
