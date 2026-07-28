"""LIDO importer for the Deutsche Digitale Bibliothek.

The mapping itself is generic and lives in :mod:`efi_conv.lido`. This
module only carries the profile: issuer information, the house
vocabularies and the language assumed for untagged titles. No line of
mapping code is needed to add this provider, which is what the LIDO
package claims and what this module is meant to demonstrate.

The Deutsche Digitale Bibliothek
(https://www.deutsche-digitale-bibliothek.de) is an aggregator, not a
holding institution. It ingests LIDO from museums and archives against
its own LIDO profile and republishes it. The issuer configured here is
therefore the DDB itself, which is a stand-in: a real conversion
replaces it with the ISIL of the institution whose holdings are being
converted, see the README next to this module. This matters more here
than anywhere else in this package, because a single DDB export can
carry the holdings of many institutions, and AVefi identifiers are
registered per institution.

The vocabularies below were compiled from the German terminology the
DDB uses in its object pages and from the LIDO structures its ingest
profile is built on. They could not be verified against a live export
while this module was written, so they are deliberately short and are
to be confirmed against real data before a conversion is run in
earnest. An unknown term is reported by the generic mapping rather
than guessed, so an incomplete vocabulary costs a report entry, not a
wrong value.

Can be used through the common command line interface::

    efi-conv from -f ddb.lido -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.ddb.lido export.xml [records.json]

"""

import sys

from avefi_schema import model_pydantic_v2 as efi

from ..lido import LidoProfile, MappingContext
from ..lido import efi_import as lido_import
from ..lido import new_context as lido_new_context

DESCRIPTION = "Deutsche Digitale Bibliothek, LIDO export"
INPUT_FORMAT = "XML (LIDO 1.1)"
#: Stand-in issuer. The DDB aggregates on behalf of the contributing
#: institutions, so this has to be replaced with the ISIL of the
#: institution before identifiers are registered.
ISSUER_INFO = {
    "has_issuer_id": "https://www.deutsche-digitale-bibliothek.de",
    "has_issuer_name": "Deutsche Digitale Bibliothek",
}

#: Object types (``lido:objectWorkType``) denoting film. The DDB holds
#: every kind of cultural object, so this filter carries the weight of
#: keeping the rest out of the conversion.
FILM_WORK_TYPE_TERMS = frozenset(
    {
        "film",
        "filmwerk",
        "stummfilm",
        "tonfilm",
        "kurzfilm",
        "dokumentarfilm",
        "spielfilm",
        "amateurfilm",
        "werbefilm",
        "video",
        "videokassette",
        "bewegtbild",
        "bewegte bilder",
    }
)

#: Event types of the DDB LIDO profile.
PRODUCTION_EVENT_TERMS = frozenset(
    {"herstellung", "produktion", "entstehung", "dreharbeiten"}
)
PUBLICATION_EVENT_TERMS = frozenset(
    {
        "veröffentlichung",
        "publikation",
        "erstaufführung",
        "uraufführung",
    }
)

#: Actor roles. Only the directing role has an AVefi counterpart; every
#: other role is reported as unmapped by the generic mapping.
DIRECTOR_ROLE_TERMS = frozenset(
    {"regie", "regisseur", "regisseurin", "regieführung"}
)

#: Measurement types denoting a running time. "Länge" is deliberately
#: absent: in a museum record it is the physical length of the reel.
DURATION_MEASUREMENT_TERMS = frozenset(
    {"laufzeit", "dauer", "spieldauer", "abspieldauer"}
)

COLOUR_TYPE_MAP = {
    "farbe": "Colour",
    "farbig": "Colour",
    "schwarz-weiß": "BlackAndWhite",
    "schwarzweiß": "BlackAndWhite",
    "s/w": "BlackAndWhite",
    "sw": "BlackAndWhite",
    "farbe und schwarz-weiß": "ColourBlackAndWhite",
    "sepia": "Sepia",
    "viragiert": "Tinted",
}
FORMAT_MAP = {
    "8 mm": "8mmFilm",
    "8mm": "8mmFilm",
    "9,5 mm": "9.5mmFilm",
    "9,5mm": "9.5mmFilm",
    "16 mm": "16mmFilm",
    "16mm": "16mmFilm",
    "17,5 mm": "17.5mmFilm",
    "35 mm": "35mmFilm",
    "35mm": "35mmFilm",
    "70 mm": "70mmFilm",
    "super 8": "Super8mmFilm",
    "super8": "Super8mmFilm",
    "super 16": "Super16mmFilm",
}
#: Empty on purpose. The DDB records whether an object is viewable
#: online, not whether a film copy is an archive, viewing or
#: distribution print, and AVefi's access status must not be guessed
#: from a rights statement.
ACCESS_STATUS_MAP = {}

#: Profile class a profile file is read into.
PROFILE_CLASS = LidoProfile

PROFILE = LidoProfile(
    issuer_info=ISSUER_INFO,
    description=DESCRIPTION,
    default_language="ger",
    film_work_type_terms=FILM_WORK_TYPE_TERMS,
    production_event_terms=PRODUCTION_EVENT_TERMS,
    publication_event_terms=PUBLICATION_EVENT_TERMS,
    director_role_terms=DIRECTOR_ROLE_TERMS,
    duration_measurement_terms=DURATION_MEASUREMENT_TERMS,
    colour_type_map=COLOUR_TYPE_MAP,
    access_status_map=ACCESS_STATUS_MAP,
    format_map=FORMAT_MAP,
)


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a DDB LIDO export into AVefi records."""
    return lido_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: LidoProfile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a DDB LIDO export using ``profile`` instead of the default.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    return lido_import(input_file, profile, continue_on_error, context)


def new_context(profile: LidoProfile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one context per invocation and passes it
    to every input file, so that copies of one film described in
    different files share their work instead of being minted twice
    under the same identifier.

    """
    return lido_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout."""
    from ..core import avefi

    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: python -m efi_conv.ddb.lido INPUT [OUTPUT.json]\n"
            "\n"
            "Convert a LIDO export of the Deutsche Digitale Bibliothek"
            " into AVefi records.\n"
            "Equivalent to: efi-conv from -f ddb.lido -o OUTPUT INPUT",
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
