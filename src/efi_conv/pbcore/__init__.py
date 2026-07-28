"""Importer for PBCore 2.1 description documents.

PBCore is a format rather than an institution, so this converter ships
with a placeholder issuer. Before the records it produces can be used,
the profile has to be given the ISIL and the name of the institution
holding the material; the converter reports once per input file that
this has not happened yet.

Can be used through the common command line interface::

    efi-conv from -f pbcore -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.pbcore export.xml [records.json]

See ``MAPPING.md`` in this directory for the mapping table and the
assumptions it rests on, and ``README.md`` for how well PBCore and
AVefi actually fit together.

"""

from avefi_schema import model_pydantic_v2 as efi

from .mapping import (
    MAPPING_RULES,
    MappingContext,
    MappingRule,
    map_record,
    parse_pbcore,
    render_mapping_markdown,
)
from .mapping import (
    efi_import as pbcore_import,
)
from .mapping import (
    new_context as pbcore_new_context,
)
from .profile import PbcoreProfile

DESCRIPTION = "PBCore 2.1 description document, any data provider"
INPUT_FORMAT = "XML (PBCore 2.1)"

#: Placeholder issuer. PBCore names no data provider that could be
#: turned into an ISIL, and inventing one would produce records
#: claiming a provenance they do not have. Replace this with the
#: holding institution before registering identifiers.
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}

#: Profile used by :func:`efi_import`. A data provider with its own
#: vocabularies replaces it with one of their own.
#: Profile class a profile file is read into.
PROFILE_CLASS = PbcoreProfile

PROFILE = PbcoreProfile(issuer_info=ISSUER_INFO, description=DESCRIPTION)

__all__ = (
    "DESCRIPTION",
    "INPUT_FORMAT",
    "ISSUER_INFO",
    "MAPPING_RULES",
    "PROFILE",
    "PROFILE_CLASS",
    "MappingContext",
    "MappingRule",
    "PbcoreProfile",
    "convert",
    "efi_import",
    "main",
    "map_record",
    "new_context",
    "parse_pbcore",
    "render_mapping_markdown",
)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a PBCore 2.1 document into AVefi records."""
    return pbcore_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: PbcoreProfile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a PBCore 2.1 document using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return pbcore_import(input_file, profile, continue_on_error, context)


def new_context(profile: PbcoreProfile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one per invocation and passes it to every
    input file, so that assets describing one film in different files
    share their work instead of being minted twice under the same
    identifier.

    """
    return pbcore_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.pbcore INPUT [OUTPUT.json]\n"
        "\n"
        "Convert a PBCore 2.1 document into AVefi records.\n"
        "Equivalent to: efi-conv from -f pbcore -o OUTPUT INPUT",
        efi_import,
    )
