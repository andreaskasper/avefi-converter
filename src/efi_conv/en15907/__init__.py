"""Importer for EN 15907 metadata in the EFG 3.2 schema.

This is a format converter, not an institution converter: the mapping
in :mod:`efi_conv.en15907.mapping` applies to every EFG export, and
everything a data provider decides for itself is carried by an
:class:`~efi_conv.en15907.profile.EfgProfile`.

An EFG document does not name its data provider in a form the AVefi
schema can use, so the profile shipped here carries a documented
placeholder issuer. A real conversion supplies a profile with the ISIL
of the data provider; the converter reports the use of the placeholder
once per input file.

Can be used through the common command line interface::

    efi-conv from -f en15907 -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.en15907 export.xml [records.json]

"""

from avefi_schema import model_pydantic_v2 as efi

from .mapping import (
    ASSUMPTIONS,
    MAPPING_RULES,
    CopyDescription,
    MappingContext,
    MappingRule,
    map_entity,
    parse_efg,
    render_mapping_markdown,
)
from .mapping import efi_import as efg_import
from .mapping import new_context as efg_new_context
from .profile import PLACEHOLDER_ISSUER_INFO, EfgProfile

DESCRIPTION = "EN 15907 metadata as published by the European Film Gateway"
INPUT_FORMAT = "XML (EFG 3.2.07)"

#: Placeholder, because an EFG export states its data provider in free
#: text only. Replace it with a profile carrying the ISIL of the data
#: provider before the records are used.
ISSUER_INFO = dict(PLACEHOLDER_ISSUER_INFO)

#: Profile class a profile file is read into.
PROFILE_CLASS = EfgProfile

PROFILE = EfgProfile(issuer_info=ISSUER_INFO, description=DESCRIPTION)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert an EFG export into AVefi records."""
    return efg_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: EfgProfile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert an EFG export using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return efg_import(input_file, profile, continue_on_error, context)


def new_context(profile: EfgProfile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one per invocation and passes it to every
    input file, so that entities describing one film in different
    files share their work instead of being minted twice under the
    same identifier.

    """
    return efg_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.en15907 INPUT [OUTPUT.json]\n"
        "\n"
        "Convert an EN 15907 export in the EFG schema into AVefi"
        " records.\n"
        "Equivalent to: efi-conv from -f en15907 -o OUTPUT INPUT",
        efi_import,
    )


__all__ = (
    "ASSUMPTIONS",
    "DESCRIPTION",
    "INPUT_FORMAT",
    "ISSUER_INFO",
    "MAPPING_RULES",
    "PLACEHOLDER_ISSUER_INFO",
    "PROFILE",
    "PROFILE_CLASS",
    "CopyDescription",
    "EfgProfile",
    "MappingContext",
    "MappingRule",
    "convert",
    "efi_import",
    "main",
    "map_entity",
    "new_context",
    "parse_efg",
    "render_mapping_markdown",
)
