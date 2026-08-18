"""MARC21 importer for the SLUB Dresden.

The mapping itself is generic and lives in :mod:`efi_conv.marc21`.
This module only carries the profile: issuer information, the relator
codes the house uses and the authority its subject headings cite. No
line of mapping code is needed to add this provider, which is what the
MARC21 package claims and what this module is meant to demonstrate.

Two things about this export are not house practice and are therefore
handled in the generic mapping rather than here. The records are
catalogued to RDA and state the carrier in 338 while leaving 007 and
008/33 empty, and the editions of one film are separate records linked
through 776. Both are standard MARC and both are read by
:mod:`efi_conv.marc21` for every provider.

Can be used through the common command line interface::

    efi-conv from -f slub.marc21 -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.slub.marc21 export.xml [records.json]

"""

import sys

from avefi_schema import model_pydantic_v2 as efi

from ..marc21 import Marc21Profile
from ..marc21.mapping import efi_import as marc21_import
from ..marc21.mapping import new_context as marc21_new_context
from ..marc21.profile import RELATOR_ACTIVITIES

DESCRIPTION = "SLUB Dresden, MARC21-XML export"
INPUT_FORMAT = "XML (MARC21 slim, bibliographic)"
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/isil/DE-14",
    "has_issuer_name": (
        "Sächsische Landesbibliothek – Staats- und"
        " Universitätsbibliothek Dresden (SLUB)"
    ),
}

#: Relator codes this house uses beyond the ones every MARC21 export
#: does. Compiled from the mapping the data provider documented for
#: its own conversion; the readings marked below are its own and are
#: still to be confirmed before identifiers are registered.
RELATOR_ACTIVITIES_SLUB = {
    **RELATOR_ACTIVITIES,
    "adp": ("WritingActivity", "Adaptation"),
    "aue": ("WritingActivity", "Writer"),
    "fmd": ("DirectingActivity", "Director"),
    "pro": ("ProducingActivity", "Producer"),
    "prf": ("CastActivity", "CastMember"),
    "prn": ("ProducingActivity", "ProductionCompany"),
    "pat": ("ProducingActivity", "Sponsor"),
    # Reported by the provider as a low confidence reading: ctb is the
    # generic "contributor" and says nothing about what was
    # contributed. Left in because dropping the agent says less, but
    # it is the first entry to revisit.
    "ctb": ("ProducingActivity", "Cooperation"),
}

#: The part of the record identifier this house uses.
#:
#: MARC builds "(DE-627)1919666257" out of 003 and 001, and the number
#: alone is the PPN the library's own systems know. Keeping the whole
#: string would give one record two different source keys depending on
#: which converter ran — exactly the problem it took a while to find in
#: the Düsseldorf delivery.
SOURCE_KEY_PATTERN = r"([^)]+)$"

#: The vocabulary the genre headings cite. This house names the GND
#: subset rather than the file, and the two subsets say different
#: things: gnd-content is what the film is, gnd-carrier what it is on.
#: Only the first is a genre — "DVD-Video" is a carrier and belongs in
#: the format, which is read from the fixed fields anyway.
GENRE_SOURCE_VOCABULARIES = frozenset({"gnd", "gnd-content", "lcgft", "rvk"})

#: 007/00 codes accepted as a moving image on top of the usual m and v.
#:
#: This house catalogues the online edition of a film as an electronic
#: resource, 007/00 = c, which the generic default does not accept —
#: rightly, because on its own it says nothing about film. Here it is
#: reached only after the leader has called the record a projected
#: medium, and 165 of the 268 records in a real export are exactly
#: that: films published online. Without this they are all skipped.
MOVING_IMAGE_CATEGORIES = frozenset({"m", "v", "c"})

#: What 300 $b says about a copy, in words.
#:
#: This house catalogues to RDA and describes the copy here rather
#: than in the fixed field positions that used to carry it. The values
#: are German and free text, and only the ones that state something
#: the schema has a field for are listed — the codec, the container,
#: the frame rate and the film base are recorded too and have no
#: counterpart.
PHYSICAL_DESCRIPTION_MAP = {
    "schwarz-weiß": "BlackAndWhite",
    "schwarz-weiss": "BlackAndWhite",
    "s/w": "BlackAndWhite",
    "sw": "BlackAndWhite",
    "farbig": "Colour",
    "farb.": "Colour",
    "farbe": "Colour",
    "stumm": "Silent",
    "ton": "Sound",
    "positiv": "Positive",
    "negativ": "ImageNegative",
    "umkehr-positiv": "OriginalPositiveReversalFilm",
    "umkehrfilm": "OriginalPositiveReversalFilm",
}

#: The access status an action note states. This house records that a
#: copy is kept for the long term in 583 rather than as a status.
ACTION_NOTE_ACCESS_MAP = {
    "archivierung/langzeitarchivierung gewährleistet": "Archive",
    "archivierung/langzeitarchivierung gewaehrleistet": "Archive",
}

#: Profile class a profile file is read into.
PROFILE_CLASS = Marc21Profile

PROFILE = Marc21Profile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    default_language="ger",
    relator_activities=RELATOR_ACTIVITIES_SLUB,
    genre_source_vocabularies=GENRE_SOURCE_VOCABULARIES,
    moving_image_categories=MOVING_IMAGE_CATEGORIES,
    source_key_pattern=SOURCE_KEY_PATTERN,
    physical_description_map=PHYSICAL_DESCRIPTION_MAP,
    action_note_access_map=ACTION_NOTE_ACCESS_MAP,
)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context=None,
) -> list[efi.MovingImageRecord]:
    """Convert a SLUB MARC21-XML export into AVefi records."""
    return marc21_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: Marc21Profile,
    continue_on_error: bool = False,
    context=None,
) -> list[efi.MovingImageRecord]:
    """Convert using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return marc21_import(input_file, profile, continue_on_error, context)


def new_context(profile: Marc21Profile | None = None):
    """Return the grouping context for one conversion."""
    return marc21_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.slub.marc21 INPUT [OUTPUT.json]\n"
        "\n"
        "Convert a MARC21-XML export of the SLUB Dresden into AVefi"
        " records.\n"
        "Equivalent to: efi-conv from -f slub.marc21 -o OUTPUT INPUT",
        efi_import,
    )


if __name__ == "__main__":
    from ..main import cli_main  # noqa: F401  (configures logging)

    sys.exit(main())
