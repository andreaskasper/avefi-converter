"""EBUCore importer.

EBUCore (EBU Tech 3293) is a format, not an institution, so this
converter ships a documented placeholder issuer instead of an ISIL.
Replace :data:`ISSUER_INFO` — or pass a profile of your own to
:func:`efi_conv.ebucore.mapping.efi_import` — with the ISIL and name
of the holding institution before the records are used. The converter
reports once per input file that the placeholder is still in
place.

Can be used through the common command line interface::

    efi-conv from -f ebucore -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.ebucore export.xml [records.json]

"""

from avefi_schema import model_pydantic_v2 as efi

from .mapping import (
    ASSUMPTIONS,
    MAPPING_RULES,
    MappingContext,
    MappingRule,
    map_record,
    parse_ebucore,
    render_mapping_markdown,
)
from .mapping import (
    efi_import as ebucore_import,
)
from .mapping import (
    new_context as ebucore_new_context,
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
#: Profile class a profile file is read into.
PROFILE_CLASS = EbucoreProfile

PROFILE = EbucoreProfile(issuer_info=ISSUER_INFO, description=DESCRIPTION)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert an EBUCore export into AVefi records."""
    return ebucore_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: EbucoreProfile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert an EBUCore export using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return ebucore_import(input_file, profile, continue_on_error, context)


def new_context(profile: EbucoreProfile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one per invocation and passes it to every
    input file, so that records describing one programme in different
    files share their work instead of being minted twice under the
    same identifier.

    """
    return ebucore_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.ebucore INPUT [OUTPUT.json]\n"
        "\n"
        "Convert an EBUCore export into AVefi records.\n"
        "The issuer is a placeholder and has to be replaced with"
        " the ISIL of\n"
        "the holding institution.\n"
        "Equivalent to: efi-conv from -f ebucore -o OUTPUT INPUT",
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
    "EbucoreProfile",
    "MappingContext",
    "MappingRule",
    "convert",
    "efi_import",
    "main",
    "map_record",
    "new_context",
    "parse_ebucore",
    "render_mapping_markdown",
)
