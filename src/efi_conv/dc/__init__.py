"""Importer for unqualified Dublin Core (oai_dc).

Dublin Core is a format rather than an institution, and the weakest of
the supported inputs: fifteen flat, repeatable and untyped elements,
and nothing else. This converter therefore ships with a documented
placeholder issuer, and a real conversion supplies the ISIL of the
data provider in a profile, as the other format converters do.

Can be used through the common command line interface::

    efi-conv from -f dc --profile provider.json -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.dc export.xml [records.json]

See ``MAPPING.md`` in this directory for the mapping table and the
assumptions it rests on, and ``README.md`` for what Dublin Core cannot
express.

"""

from .mapping import (
    ASSUMPTIONS,
    DESCRIPTION,
    INPUT_FORMAT,
    ISSUER_INFO,
    MAPPING_RULES,
    PROFILE,
    PROFILE_CLASS,
    MappingRule,
    convert,
    efi_import,
    map_record,
    new_context,
    parse_dc,
    render_mapping_markdown,
)
from .profile import DcProfile


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.dc INPUT [OUTPUT.json]\n"
        "\n"
        "Convert an unqualified Dublin Core (oai_dc) export into"
        " AVefi records.\n"
        "The issuer is a placeholder and has to be replaced with the"
        " ISIL of\n"
        "the data provider, see --profile.\n"
        "Equivalent to: efi-conv from -f dc -o OUTPUT INPUT",
        efi_import,
    )


__all__ = (
    "ASSUMPTIONS",
    "DESCRIPTION",
    "INPUT_FORMAT",
    "ISSUER_INFO",
    "MAPPING_RULES",
    "PROFILE",
    "PROFILE_CLASS",
    "DcProfile",
    "MappingRule",
    "convert",
    "efi_import",
    "main",
    "map_record",
    "new_context",
    "parse_dc",
    "render_mapping_markdown",
)
