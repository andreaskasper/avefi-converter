"""EBUCore importer.

EBUCore (EBU Tech 3293) is a format, not an institution, so this
converter ships a documented placeholder issuer instead of an ISIL.
Replace :data:`ISSUER_INFO` — or pass a profile of your own to
:func:`efi_conv.ebucore.mapping.efi_import` — with the ISIL and name
of the holding institution before the records are used. The converter
reports once per run that the placeholder is still in place.

Can be used through the common command line interface::

    efi-conv from -f ebucore -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.ebucore export.xml [records.json]

"""

import sys

from avefi_schema import model_pydantic_v2 as efi

from .mapping import (
    ASSUMPTIONS,
    MAPPING_RULES,
    MappingRule,
    map_record,
    parse_ebucore,
    render_mapping_markdown,
)
from .mapping import (
    efi_import as ebucore_import,
)
from .profile import PLACEHOLDER_ISSUER_INFO, EbucoreProfile

DESCRIPTION = "EBUCore export (issuer to be configured)"
INPUT_FORMAT = "XML (EBUCore 1.10, EBU Tech 3293)"

#: Placeholder issuer. EBUCore says nothing about who holds the
#: material, and inventing an ISIL for a real institution would be
#: worse than saying that it is unknown.
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/avefi/issuer/unspecified",
    "has_issuer_name": "Unspecified data provider",
}

#: Default profile: the standard EBU vocabularies plus the placeholder
#: issuer. A data provider supplies its own profile instead.
PROFILE = EbucoreProfile(issuer_info=ISSUER_INFO, description=DESCRIPTION)


def efi_import(
    input_file, continue_on_error: bool = False
) -> list[efi.MovingImageRecord]:
    """Convert an EBUCore export into AVefi records."""
    return ebucore_import(input_file, PROFILE, continue_on_error)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core import avefi

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m efi_conv.ebucore INPUT [OUTPUT.json]\n"
            "\n"
            "Convert an EBUCore export into AVefi records.\n"
            "The issuer is a placeholder and has to be replaced with"
            " the ISIL of\n"
            "the holding institution.\n"
            "Equivalent to: efi-conv from -f ebucore -o OUTPUT INPUT",
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
    "EbucoreProfile",
    "MappingRule",
    "efi_import",
    "main",
    "map_record",
    "parse_ebucore",
    "render_mapping_markdown",
)
