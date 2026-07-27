"""LIDO importer for the Filmmuseum der Landeshauptstadt Düsseldorf.

The mapping itself is generic and lives in :mod:`efi_conv.lido`. This
module only carries the profile: issuer information, the house
vocabularies and the language assumed for untagged titles.

Can be used through the common command line interface::

    efi-conv from -f fmdu.lido -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.fmdu.lido export.xml [records.json]

"""

import sys

from avefi_schema import model_pydantic_v2 as efi

from ..lido import LidoProfile
from ..lido import efi_import as lido_import

DESCRIPTION = "Filmmuseum der Landeshauptstadt Düsseldorf, LIDO export"
INPUT_FORMAT = "XML (LIDO 1.1)"
ISSUER_INFO = {
    "has_issuer_id": "https://w3id.org/isil/DE-MUS-432511",
    "has_issuer_name": "Filmmuseum der Landeshauptstadt Düsseldorf",
}

#: House vocabularies, kept in step with the CSV importer for the same
#: institution so that both produce identical AVefi values.
COLOUR_TYPE_MAP = {
    "coloriert": "Colourized",
    "farbe": "Colour",
    "farbe, sw": "ColourBlackAndWhite",
    "schwarz-weiß": "BlackAndWhite",
    "schwarz-weiss": "BlackAndWhite",
    "sw": "BlackAndWhite",
    "sw, viragiert": "BlackAndWhiteTinted",
    "viragiert": "Tinted",
}
ACCESS_STATUS_MAP = {
    "archivkopie": "Archive",
    "verleihkopie": "Distribution",
}
FORMAT_MAP = {
    "8mm": "8mmFilm",
    "16mm": "16mmFilm",
    "17,5mm": "17.5mmFilm",
    "35mm": "35mmFilm",
    "super8": "Super8mmFilm",
    "super 8": "Super8mmFilm",
}

PROFILE = LidoProfile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    default_language="ger",
    colour_type_map=COLOUR_TYPE_MAP,
    access_status_map=ACCESS_STATUS_MAP,
    format_map=FORMAT_MAP,
)


def efi_import(input_file) -> list[efi.MovingImageRecord]:
    """Convert a FMDU LIDO export into AVefi records."""
    return lido_import(input_file, PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core import avefi

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m efi_conv.fmdu.lido INPUT [OUTPUT.json]\n"
            "\n"
            "Convert a LIDO export of the Filmmuseum Düsseldorf into"
            " AVefi records.\n"
            "Equivalent to: efi-conv from -f fmdu.lido -o OUTPUT INPUT",
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


if __name__ == "__main__":
    from ..main import cli_main  # noqa: F401  (configures logging)

    sys.exit(main())
