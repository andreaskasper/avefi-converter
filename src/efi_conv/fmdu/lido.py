"""LIDO importer for the Filmmuseum der Landeshauptstadt Düsseldorf.

The mapping itself is generic and lives in :mod:`efi_conv.lido`. This
module only carries the profile: issuer information, the house
vocabularies and the language assumed for untagged titles.

Can be used through the common command line interface::

    efi-conv from -f fmdu.lido -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.fmdu.lido export.xml [records.json]

"""

import sys

from avefi_schema import model_pydantic_v2 as efi

from ..lido import LidoProfile, MappingContext
from ..lido import efi_import as lido_import
from ..lido import new_context as lido_new_context

DESCRIPTION = "Filmmuseum der Landeshauptstadt Düsseldorf, LIDO export"
INPUT_FORMAT = "XML (LIDO 1.1)"
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/isil/DE-MUS-432511",
    "has_issuer_name": "Filmmuseum der Landeshauptstadt Düsseldorf",
}

#: The lido:recordType terms this conversion is about.
#:
#: The provider states what every record describes, so nothing has to
#: be inferred from the object. All 5562 records of the reference
#: export say "Item", which is the agreed criterion for a copy.
#:
#: This replaces an earlier filter on lido:objectWorkType. That field
#: is meant for the type of work and this provider puts the carrier in
#: it — Filmrolle, Festplatte, VHS — so the generic default, which
#: lists work types, let 67 of 5562 records through. Reading the
#: carrier as a work type worked well enough once the terms were
#: collected, but it was answering the question by inference where the
#: record answers it outright, and it wrongly dropped six copies whose
#: objectWorkType holds a title fragment.
RECORD_TYPE_TERMS = frozenset({"item"})

#: The part of lido:lidoRecID that identifies the record.
#:
#: The export writes "DE-MUS-042628:DE-MUS-432511:1059195", where the
#: first two segments name the archive and the museum. The identifier
#: is the last one, and it is what the CSV export of the same holdings
#: carries in its first column. Taking the whole string would give the
#: same copy two different source keys depending on which of the two
#: importers ran, and nothing could be matched between them.
SOURCE_KEY_PATTERN = r"([^:]+)$"

#: The relatedWorkSet relation naming the film a copy is of.
#:
#: Each one carries the work's own identifier and title, so the
#: provider decides what is one film and what is two rather than the
#: converter inferring it from title, director and year. Six copies of
#: the reference export hold more than one film; reconstructing that
#: from a concatenated title is what the manual revision of the CSV
#: output had to do by hand.
RELATED_WORK_REL_TERMS = frozenset({"film"})

#: House vocabularies, kept in step with the CSV importer for the same
#: institution so that both produce identical AVefi values.
COLOUR_TYPE_MAP = {
    # "coloriert" has no AVefi equivalent and is deliberately absent:
    # hand and stencil colouring is neither Colour nor Tinted, and
    # guessing one of them would put a value into the data that the
    # provider never stated. The term is reported as unmapped instead.
    "farbe": "Colour",
    "farbe, sw": "ColourBlackAndWhite",
    "schwarz-weiß": "BlackAndWhite",
    "schwarz-weiss": "BlackAndWhite",
    "sw": "BlackAndWhite",
    "sw, viragiert": "BlackAndWhiteTinted",
    "viragiert": "Tinted",
}
ACCESS_STATUS_MAP = {
    "archivkopie": "Archive",
    "verleihkopie": "Distribution",
    "master": "Master",
    # A deaccessioned copy is not a copy that has to be left out. The
    # schema has a status for it, and a holdings record saying the
    # item is gone is worth more than no record at all.
    "deakzession": "Removed",
    "deakzessioniert": "Removed",
}

#: Languages as this provider names them. It writes them into the
#: same classification as the access status and a few working notes,
#: so the term has to say where it belongs — before this, "Deutsch"
#: was arriving as a genre of the film, 1922 times.
LANGUAGE_NAME_MAP = {
    "deutsch": "ger",
    "englisch": "eng",
    "französisch": "fre",
    "franzoesisch": "fre",
    "spanisch": "spa",
    "italienisch": "ita",
    "japanisch": "jpn",
    "niederländisch": "dut",
    "niederlaendisch": "dut",
    "russisch": "rus",
    "türkisch": "tur",
    "tuerkisch": "tur",
    "persisch": "per",
    "polnisch": "pol",
    "portugiesisch": "por",
    "hindi": "hin",
    "griechisch": "gre",
    "koreanisch": "kor",
    "mandarin": "chi",
    "kantonesisch": "chi",
    # A misspelling in sixteen records, kept so that the copies are
    # not left without a language over a typing slip.
    "kantonesich": "chi",
    "chinesisch": "chi",
    "dänisch": "dan",
    "daenisch": "dan",
    "schwedisch": "swe",
    "norwegisch": "nor",
    "tschechisch": "cze",
    "ungarisch": "hun",
    "arabisch": "ara",
    "hebräisch": "heb",
    "hebraeisch": "heb",
    "latein": "lat",
    "lateinisch": "lat",
    # "Verschiedene" is a statement that there are several and which
    # ones was not recorded; mul says exactly that.
    "verschiedene": "mul",
    "mehrsprachig": "mul",
}
FORMAT_MAP = {
    "8mm": "8mmFilm",
    "16mm": "16mmFilm",
    "17,5mm": "17.5mmFilm",
    "35mm": "35mmFilm",
    "super8": "Super8mmFilm",
    "super 8": "Super8mmFilm",
}

#: The roles this provider records, and the AVefi activity each one
#: denotes. They sit in an event of their own, "Geistige Schöpfung",
#: rather than on the production event, so none of them used to be
#: found: 1796 directing credits, 607 for music and 492 for writing.
#:
#: "Absender*in" is deliberately absent. It is a provenance note about
#: who sent the material in, not a filmographic role, and there is no
#: activity in the schema that would be true of it.
ROLE_ACTIVITY_MAP = {
    "regie": "Director",
    "regieassistenz": "AssistantDirector",
    "musik": "Composer",
    "drehbuch": "Writer",
    "autor*in": "Writer",
    "autor": "Writer",
    "autorin": "Writer",
    "kamera": "Cinematographer",
    "schnitt": "FilmEditor",
    "kostüm": "CostumeDesigner",
    "kostuem": "CostumeDesigner",
    "choreograph*in": "Choreographer",
    "choreographie": "Choreographer",
    "interviewer*in": "Interviewer",
    "produktionsfirma": "ProductionCompany",
    "produktion": "Producer",
    "ton": "SoundEngineer",
    "produzent*in": "Producer",
    "produzent": "Producer",
    "produzentin": "Producer",
    "kamerassistenz": "CameraAssistant",
    "kameraassistenz": "CameraAssistant",
    "aufnahmeleitung": "ProductionManager",
    "bauten": "ProductionDesigner",
    "szenenbild": "ProductionDesigner",
    "maske": "MakeUpArtist",
    "erzähler*in": "Narrator",
    "sprecher*in": "Narrator",
}

#: Classification terms naming the form of a work rather than its
#: genre. The provider keeps both in one list, which is reasonable of
#: it — they are both answers to "what sort of film is this" — but the
#: schema asks them separately: has_form is what kind of thing the
#: film is, has_genre what it is like. A term listed here becomes a
#: form and not also a genre.
WORK_FORM_MAP = {
    "dokumentarfilm": "Documentary",
    "dokumentation": "Documentary",
    "spielfilm": "Fiction",
    "amateurfilm": "AmateurFilm",
    "experimentalfilm": "ExperimentalFilm",
    "kurzfilm": "Short",
    "werbefilm": "Commercial",
    "werbung": "Commercial",
    "lehrfilm": "EducationalFilm",
    "monatsschau": "Newsreel",
    "wochenschau": "Newsreel",
    "kompilationsfilm": "Compilation",
    "filmcollage": "Compilation",
    "essayfilm": "EssayFilm",
    "industriefilm": "IndustrialFilm",
    "videoclip": "MusicVideo",
    "tv-serie": "Series",
    "serienfilm": "Series",
    "fernsehen - filmserie": "Series",
}

#: Roles marking an actor as what the film is about. This provider
#: records the subject of a film in the same place as its credits, so
#: without these terms a person the film is about is either taken for
#: somebody who made it or reported as an unmappable credit — 130 of
#: them were.
SUBJECT_ROLE_TERMS = frozenset(
    {
        "behandelte person",
        "behandelte institution",
        "behandelter ort",
        "dargestellte person",
    }
)

#: House spellings in the technical description, and the AVefi value
#: each one means. Everything else this provider writes there is
#: already an AVefi value and needs no entry.
#:
#: "Coloriert" is absent for the same reason it is absent from the
#: colour map: hand and stencil colouring is neither Colour nor
#: Tinted, and the schema has no third answer.
MATERIALS_TECH_MAP = {
    "super8": "Super8mmFilm",
    "super 8": "Super8mmFilm",
    # A decimal comma where the schema writes a point.
    "17,5mmfilm": "17.5mmFilm",
    "colour, sw": "ColourBlackAndWhite",
    "blackandwhite & colour": "ColourBlackAndWhite",
    "laserdisc (ld)": "LaserDisc",
    "duplicatepositivee": "DuplicatePositive",
    "nicht-theatricaldistributionevent": "NonTheatricalDistributionEvent",
    "heimkino": "HomeVideoPublicationEvent",
    "stummfilm": "Silent",
}

#: The measurement holding the running time, and the unit its values
#: are really in.
#:
#: The records label this column " Min" and the values are hours. It
#: is not a close call: a 35mm print of 2523 metres runs 92 minutes at
#: 24 frames a second, and the record for it says 1.5207. Read as
#: minutes, the median running time of the whole export would be
#: fourteen seconds; read as hours it is 14.4 minutes, with a quartile
#: at 87, which is what a collection of shorts and features looks
#: like. The override is a statement about this one export and lives
#: here rather than in the mapping.
DURATION_MEASUREMENT_TERMS = frozenset(
    {"zeit", "laufzeit", "dauer", "spieldauer", "running time", "duration"}
)
DURATION_UNITS = {"zeit": "h"}

#: Profile class a profile file is read into.
PROFILE_CLASS = LidoProfile

PROFILE = LidoProfile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    default_language="ger",
    source_key_pattern=SOURCE_KEY_PATTERN,
    related_work_rel_terms=RELATED_WORK_REL_TERMS,
    record_type_terms=RECORD_TYPE_TERMS,
    # Switched off rather than left at the default: objectWorkType
    # answers a different question in this export, and two criteria
    # for one decision is one too many.
    film_work_type_terms=frozenset(),
    role_activity_map=ROLE_ACTIVITY_MAP,
    work_form_map=WORK_FORM_MAP,
    subject_role_terms=SUBJECT_ROLE_TERMS,
    duration_measurement_terms=DURATION_MEASUREMENT_TERMS,
    duration_units=DURATION_UNITS,
    keyword_classification_types=frozenset({"schlagwort"}),
    language_name_map=LANGUAGE_NAME_MAP,
    materials_tech_map=MATERIALS_TECH_MAP,
    colour_type_map=COLOUR_TYPE_MAP,
    access_status_map=ACCESS_STATUS_MAP,
    format_map=FORMAT_MAP,
)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a FMDU LIDO export into AVefi records."""
    return lido_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: LidoProfile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a FMDU LIDO export using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return lido_import(input_file, profile, continue_on_error, context)


def new_context(profile: LidoProfile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one context per invocation and passes it
    to every input file, so that copies of one film described in
    different files share their work instead of being minted twice
    under the same identifier.

    """
    return lido_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.fmdu.lido INPUT [OUTPUT.json]\n"
        "\n"
        "Convert a LIDO export of the Filmmuseum Düsseldorf into"
        " AVefi records.\n"
        "Equivalent to: efi-conv from -f fmdu.lido -o OUTPUT INPUT",
        efi_import,
    )


if __name__ == "__main__":
    from ..main import cli_main  # noqa: F401  (configures logging)

    sys.exit(main())
