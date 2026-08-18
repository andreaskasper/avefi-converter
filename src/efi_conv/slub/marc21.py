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
    "prn": ("ProducingActivity", "ProductionCompany"),
    "pat": ("ProducingActivity", "Sponsor"),
    # Reported by the provider as a low confidence reading: ctb is the
    # generic "contributor" and says nothing about what was
    # contributed. Left in because dropping the agent says less, but
    # it is the first entry to revisit.
    "ctb": ("ProducingActivity", "Cooperation"),
}

#: Authorities the subject and genre headings cite.
GENRE_SOURCE_VOCABULARIES = frozenset({"gnd", "lcgft", "rvk"})

#: Profile class a profile file is read into.
PROFILE_CLASS = Marc21Profile

PROFILE = Marc21Profile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    default_language="ger",
    relator_activities=RELATOR_ACTIVITIES_SLUB,
    genre_source_vocabularies=GENRE_SOURCE_VOCABULARIES,
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
