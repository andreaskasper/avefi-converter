"""Every vocabulary a converter ships maps into the AVefi schema.

A profile that maps a source term to a value the schema does not know
looks like a working mapping until the day the term first occurs in a
delivery. Then it fails as a validation error somewhere in the middle
of a file, long after the mistake was made, and the run is lost. The
values are a closed set, so the mistake is findable here instead.

"""

import importlib

from avefi_schema import model_pydantic_v2 as efi
import pytest

from efi_conv.core.cli import IMPORTERS

#: Profile field holding a vocabulary, and the enum its values live in.
VOCABULARIES = {
    "colour_type_map": efi.ColourTypeEnum,
    "access_status_map": efi.ItemAccessStatusEnum,
    "format_map": efi.FormatFilmTypeEnum,
    "element_type_map": efi.ItemElementTypeEnum,
    "work_form_map": efi.WorkFormEnum,
}


def profiles_of(name):
    """Yield the profiles a converter module carries."""
    module = importlib.import_module(f"efi_conv.{name}")
    profile = getattr(module, "PROFILE", None)
    if profile is not None:
        yield name, profile


@pytest.mark.parametrize("name", IMPORTERS)
def test_vocabularies_map_into_the_schema(name):
    for label, profile in profiles_of(name):
        for field, enum in VOCABULARIES.items():
            vocabulary = getattr(profile, field, None) or {}
            allowed = {member.value for member in enum}
            unknown = {
                term: value
                for term, value in vocabulary.items()
                if value not in allowed
            }
            assert not unknown, (
                f"{label}.{field} maps to values {enum.__name__} does not"
                f" know: {unknown}"
            )


@pytest.mark.parametrize("name", IMPORTERS)
def test_vocabulary_keys_are_lower_case(name):
    """Lookups are done on the lower cased source term.

    A key with an upper case letter can never match, which is the same
    failure as a missing entry but harder to see.

    """
    for label, profile in profiles_of(name):
        for field in VOCABULARIES:
            vocabulary = getattr(profile, field, None) or {}
            wrong = [key for key in vocabulary if key != key.lower()]
            assert not wrong, (
                f"{label}.{field} has non lower case keys: {wrong}"
            )
