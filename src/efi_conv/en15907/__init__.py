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

import sys

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
    input_file, continue_on_error: bool = False
) -> list[efi.MovingImageRecord]:
    """Convert an EFG export into AVefi records."""
    return efg_import(input_file, PROFILE, continue_on_error)


def convert(
    input_file, profile: EfgProfile, continue_on_error: bool = False
) -> list[efi.MovingImageRecord]:
    """Convert an EFG export using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return efg_import(input_file, profile, continue_on_error)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core import avefi

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m efi_conv.en15907 INPUT [OUTPUT.json]\n"
            "\n"
            "Convert an EN 15907 export in the EFG schema into AVefi"
            " records.\n"
            "Equivalent to: efi-conv from -f en15907 -o OUTPUT INPUT",
            file=sys.stderr if not argv else sys.stdout,
        )
        return 0 if argv else 2
    if len(argv) > 2:
        print("Expected at most two arguments, see --help", file=sys.stderr)
        return 2

    records = efi_import(argv[0])
    if len(argv) == 2:
        avefi.dump(avefi.sort_records(records), argv[1])
    else:
        print(avefi.dumps(avefi.sort_records(records), indent=2))
    return 0


__all__ = (
    "ASSUMPTIONS",
    "DESCRIPTION",
    "INPUT_FORMAT",
    "ISSUER_INFO",
    "MAPPING_RULES",
    "PLACEHOLDER_ISSUER_INFO",
    "PROFILE",
    "CopyDescription",
    "EfgProfile",
    "MappingContext",
    "MappingRule",
    "efi_import",
    "main",
    "map_entity",
    "parse_efg",
    "render_mapping_markdown",
)
