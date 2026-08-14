"""LIDO importer for museum-digital.

The mapping itself is generic and lives in :mod:`efi_conv.lido`. This
module only carries the profile: issuer information, the house
vocabularies and the language assumed for untagged titles. No line of
mapping code is needed to add this provider, which is what the LIDO
package claims and what this module is meant to demonstrate.

museum-digital (https://www.museum-digital.de) is a publication
platform, not a holding institution. It serves LIDO per instance,
through the OAI-PMH endpoint of that instance and through the ``lido``
output of its object API. The issuer configured here is therefore
museum-digital itself, which is a stand-in: a real conversion replaces
it with the ISIL of the museum whose holdings are being converted, see
the README next to this module. The converter reports that once per
input file, together with the institutions the records name in
``lido:recordSource``, which the mapping does not read.

The vocabularies below were compiled from the terminology museum-digital
uses in its German interface and from the LIDO structures its export is
built on. They could not be verified against a live export while this
module was written, so they are deliberately short and are to be
confirmed against real data before a conversion is run in earnest. An
unknown term is reported by the generic mapping rather than guessed, so
an incomplete vocabulary costs a report entry, not a wrong value.

Can be used through the common command line interface::

    efi-conv from -f mdigital.lido -o records.json export.xml

or directly, which is convenient while developing a mapping::

    python -m efi_conv.mdigital.lido export.xml [records.json]

"""

import sys

from avefi_schema import model_pydantic_v2 as efi

from ..core.report import for_file, report_issue
from ..lido import LidoProfile, MappingContext, parse_lido
from ..lido import efi_import as lido_import
from ..lido import finish_context as lido_finish_context
from ..lido import new_context as lido_new_context

DESCRIPTION = "museum-digital, LIDO export of one instance"
INPUT_FORMAT = "XML (LIDO 1.1)"
#: Stand-in issuer. museum-digital publishes on behalf of the museums,
#: it does not hold the material, so this has to be replaced with the
#: ISIL of the museum before identifiers are registered.
ISSUER_INFO = {
    "has_issuer_id": "https://www.museum-digital.de",
    "has_issuer_name": "museum-digital",
}

#: Object types (``lido:objectWorkType``) denoting film. museum-digital
#: holds mostly non-film material, so this filter carries the weight of
#: keeping photographs, posters and projectors out of the conversion.
FILM_WORK_TYPE_TERMS = frozenset(
    {
        "film",
        "filmrolle",
        "schmalfilm",
        "amateurfilm",
        "dokumentarfilm",
        "spielfilm",
        "werbefilm",
        "kinofilm",
        "video",
        "videokassette",
        "bewegtbild",
    }
)

#: Event types museum-digital uses. "Herstellung" is the one that
#: matters; the platform models an object's making rather than a film
#: production, which is the same event for a film print.
PRODUCTION_EVENT_TERMS = frozenset({"herstellung", "produktion", "entstehung"})
PUBLICATION_EVENT_TERMS = frozenset(
    {"veröffentlichung", "publikation", "erstaufführung"}
)

#: Actor roles. Only the directing role has an AVefi counterpart; every
#: other role is reported as unmapped by the generic mapping.
DIRECTOR_ROLE_TERMS = frozenset({"regie", "regisseur", "regisseurin"})

#: Measurement types denoting a running time. "Länge" is deliberately
#: absent: in museum-digital it is the physical length of the reel.
DURATION_MEASUREMENT_TERMS = frozenset({"laufzeit", "dauer", "spieldauer"})

COLOUR_TYPE_MAP = {
    "farbe": "Colour",
    "farbig": "Colour",
    "schwarz-weiß": "BlackAndWhite",
    "schwarzweiß": "BlackAndWhite",
    "s/w": "BlackAndWhite",
    "sw": "BlackAndWhite",
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
    "35 mm": "35mmFilm",
    "35mm": "35mmFilm",
    "super 8": "Super8mmFilm",
    "super8": "Super8mmFilm",
}
#: Empty on purpose. museum-digital records whether an object is on
#: display, not whether a film copy is an archive, viewing or
#: distribution print, and AVefi's access status must not be guessed
#: from the absence of a statement.
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


def report_stand_in_issuer(input_file, profile: LidoProfile):
    """Say that the issuer is a stand-in, and name what the file says.

    museum-digital publishes on behalf of the museums that hold the
    material. AVefi identifiers are registered by and for the holding
    institution, so records carrying this issuer must not be
    registered, and the run says so rather than leaving it to be
    noticed later.

    The export names the institution it came from in
    ``lido:recordSource``. The generic mapping does not read that
    element — the issuer comes from the profile, so that it is
    unambiguous for the whole conversion — so the values found are
    reported here. Nothing read here reaches an AVefi record.

    Parameters
    ----------
    input_file
        Path of the LIDO document.
    profile : LidoProfile
        The profile the conversion runs with. A profile carrying a
        real ISIL is not reported.

    """
    if profile.issuer_info != ISSUER_INFO:
        return
    report_issue(
        "warning",
        "The issuer shipped with this converter is a stand-in."
        " Replace it with the ISIL of the museum that holds"
        " the material before identifiers are registered",
        source_field="profile issuer_info",
        target_field="described_by.has_issuer_id",
        raw_value=ISSUER_INFO["has_issuer_id"],
    )
    for source in record_sources(input_file):
        report_issue(
            "warning",
            "The record names this institution as its source. The"
            " mapping does not transfer it: AVefi takes the issuer"
            " from the profile, so that one conversion has one"
            " issuer",
            source_field="lido:recordSource",
            target_field="—",
            raw_value=source,
        )


def record_sources(input_file) -> list[dict]:
    """Return the legal bodies the records of a file name, once each.

    A LIDO record states where it came from in
    ``lido:recordSource``, by identifier in ``lido:legalBodyID`` and
    by name in ``lido:legalBodyName``. An aggregated export carries
    the holdings of several institutions, and this is the only place
    saying which.

    """
    found = []
    for record in parse_lido(input_file):
        for administrative in record.administrative_metadata or []:
            wrap = administrative.record_wrap
            for source in (wrap.record_source if wrap else None) or []:
                entry = {
                    "legalBodyID": first_text(source.legal_body_id),
                    "legalBodyName": first_appellation(source.legal_body_name),
                }
                if any(entry.values()) and entry not in found:
                    found.append(entry)
    return found


def first_text(elements) -> str | None:
    """Return the text of the first of ``elements``, if there is one."""
    for element in elements or []:
        value = (getattr(element, "value", None) or "").strip()
        if value:
            return value
    return None


def first_appellation(elements) -> str | None:
    """Return the first appellation value of a LIDO legal body."""
    for element in elements or []:
        value = first_text(element.appellation_value)
        if value:
            return value
    return None


def efi_import(
    input_file,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a museum-digital LIDO export into AVefi records."""
    with for_file(input_file):
        report_stand_in_issuer(input_file, PROFILE)
        return lido_import(input_file, PROFILE, continue_on_error, context)


def convert(
    input_file,
    profile: LidoProfile,
    continue_on_error: bool = False,
    context: MappingContext | None = None,
) -> list[efi.MovingImageRecord]:
    """Convert a museum-digital export using ``profile``.

    Takes the place of the profile this module ships.

    Used by ``efi-conv from --profile``, which binds a converter to a
    profile loaded from a file.

    """
    with for_file(input_file):
        report_stand_in_issuer(input_file, profile)
        return lido_import(input_file, profile, continue_on_error, context)


def finish_context(context: MappingContext, records) -> None:
    """Check the conversion once every input file has been read.

    ``efi-conv from`` calls this after the last file, which is when a
    question about the conversion as a whole — did every identifier
    the input states reach the output — can be answered.

    """
    lido_finish_context(context, records)


def new_context(profile: LidoProfile | None = None) -> MappingContext:
    """Return the grouping context for one conversion.

    ``efi-conv from`` builds one context per invocation and passes it
    to every input file, so that copies of one film described in
    different files share their work instead of being minted twice
    under the same identifier.

    """
    return lido_new_context(profile or PROFILE)


def main(argv=None):
    """Convert INPUT and write the records to OUTPUT or stdout.

    A file that cannot be read is reported as an error naming the file
    rather than as a traceback; pass -v for the traceback.

    """
    from ..core.cli import run_converter_main

    return run_converter_main(
        argv,
        "Usage: python -m efi_conv.mdigital.lido INPUT"
        " [OUTPUT.json]\n"
        "\n"
        "Convert a LIDO export of a museum-digital instance into"
        " AVefi records.\n"
        "Equivalent to: efi-conv from -f mdigital.lido -o OUTPUT"
        " INPUT",
        efi_import,
    )


if __name__ == "__main__":
    from ..main import cli_main  # noqa: F401  (configures logging)

    sys.exit(main())
