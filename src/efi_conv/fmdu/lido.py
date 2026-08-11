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

#: The lido:objectWorkType values that denote holdings in scope.
#:
#: The generic default lists work types — "film", "spielfilm",
#: "dokumentarfilm". This provider does not put a work type there. It
#: puts the carrier: "Filmrolle", "Festplatte", "VHS". The two lists
#: overlap in exactly one value, "Video", so the default accepted 67
#: of 5562 records of a real export and skipped the other 5495,
#: including all 5074 film reels, as accompanying material.
#:
#: The list below is not invented. It is every value occurring in the
#: records of the CSV export agreed with the provider, which is the
#: definition of what counts as holdings for this institution. Six
#: records carry a title fragment instead of a carrier — "Teil 1",
#: "Teil 2: Das Bündnis der Viererbande" — and are deliberately not
#: listed: they are a data entry error at the provider, and accepting
#: them here would hide it.
FILM_WORK_TYPE_TERMS = frozenset(
    {
        "analog video",
        "arbeitskopie",
        "bild-negativ",
        "bluray",
        "datei",
        "dcp",
        "disc",
        "dvd",
        "festplatte",
        "filmrolle",
        # A misspelling of "Filmrolle" in a single record. Listed
        # because the copy it describes is a film reel whatever the
        # cataloguer typed, and reported to the provider separately.
        "fimrolle",
        "laserdisc",
        "lto",
        "lto-band",
        "negativ",
        "optisch",
        "raid",
        "ton-negativ",
        "tonband",
        "vhs",
        "video",
    }
)

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
}
FORMAT_MAP = {
    "8mm": "8mmFilm",
    "16mm": "16mmFilm",
    "17,5mm": "17.5mmFilm",
    "35mm": "35mmFilm",
    "super8": "Super8mmFilm",
    "super 8": "Super8mmFilm",
}

#: Profile class a profile file is read into.
PROFILE_CLASS = LidoProfile

PROFILE = LidoProfile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    default_language="ger",
    film_work_type_terms=FILM_WORK_TYPE_TERMS,
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
