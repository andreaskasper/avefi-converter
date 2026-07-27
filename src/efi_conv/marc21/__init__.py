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

import sys

from avefi_schema import model_pydantic_v2 as efi

from .mapping import (
    ASSUMPTIONS,
    MAPPING_RULES,
    MappingRule,
    map_record,
    render_mapping_markdown,
)
from .mapping import efi_import as marc21_import
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
    "Marc21Profile",
    "MarcRecord",
    "MappingRule",
    "efi_import",
    "iter_records",
    "main",
    "map_record",
    "render_mapping_markdown",
)


def efi_import(
    input_file, continue_on_error: bool = False
) -> list[efi.MovingImageRecord]:
    """Convert a MARCXML export into AVefi records."""
    return marc21_import(input_file, PROFILE, continue_on_error)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core import avefi

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m efi_conv.marc21 INPUT [OUTPUT.json]\n"
            "\n"
            "Convert a MARCXML export into AVefi records.\n"
            "Equivalent to: efi-conv from -f marc21 -o OUTPUT INPUT",
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
