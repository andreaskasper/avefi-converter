"""MARC21-XML importer.

MARC21 is a standard, so this is a format converter rather than a
converter for one institution: the mapping lives in
:mod:`efi_conv.marc21.mapping` and everything a particular library or
archive does differently is configured in a
:class:`~efi_conv.marc21.profile.Marc21Profile`.

The profile shipped here carries a documented placeholder issuer. Every
run using it reports a warning, because records naming an unspecified
issuer must not have persistent identifiers registered for them. A data
provider supplies its own profile with the ISIL of the holding
institution, in the same way as :mod:`efi_conv.fmdu.lido` does for the
generic LIDO mapping.

Can be used through the common command line interface::

    efi-conv from -f marc21 -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.marc21 export.xml [records.json]

"""

from avefi_schema import model_pydantic_v2 as efi

from .mapping import (
    ASSUMPTIONS,
    MAPPING_RULES,
    MappingContext,
    MappingRule,
    map_record,
    render_mapping_markdown,
)
from .mapping import efi_import as marc21_import
from .mapping import new_context as marc21_new_context
from .marcxml import MarcRecord, iter_records
from .profile import Marc21Profile

DESCRIPTION = "Generic MARC21 bibliographic records, issuer unspecified"
INPUT_FORMAT = "XML (MARC21 slim, bibliographic)"

#: Documented placeholder. MARC says who catalogued a record but not
#: who holds the copy it describes, and an ISIL must not be guessed, so
#: the holding institution is configured in a profile of its own.
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}

#: Profile class a profile file is read into.
PROFILE_CLASS = Marc21Profile

PROFILE = Marc21Profile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
)

__all__ = (
    "ASSUMPTIONS",
    "DESCRIPTION",
    "INPUT_FORMAT",
    "ISSUER_INFO",
    "MAPPING_RULES",
    "PROFILE",
    "PROFILE_CLASS",
    "Marc21Profile",
    "MarcRecord",
    "MappingContext",
    "MappingRule",
    "convert",
    "efi_import",
    "iter_records",
    "main",
    "map_record",
    "new_context",
    "render_mapping_markdown",
)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a MARCXML export into AVefi records."""
    return marc21_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: Marc21Profile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a MARCXML export using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return marc21_import(input_file, profile, continue_on_error, context)


def new_context(profile: Marc21Profile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one per invocation and passes it to every
    input file, so that records describing one film in different files
    share their work instead of being minted twice under the same
    identifier.

    """
    return marc21_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.marc21 INPUT [OUTPUT.json]\n"
        "\n"
        "Convert a MARCXML export into AVefi records.\n"
        "Equivalent to: efi-conv from -f marc21 -o OUTPUT INPUT",
        efi_import,
    )
