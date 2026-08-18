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


class TestWhereATechnicalValueBelongs:
    """The value says which field it is destined for.

    Colour, sound, element type and the format vocabularies share no
    value between them, which is what lets a provider write all four
    into one field and the mapping still tell them apart.

    """

    def test_every_value_has_exactly_one_home(self):
        from efi_conv.core.vocabulary import TECHNICAL_TARGETS

        ambiguous = {
            value: [name for name, _, _ in targets]
            for value, targets in TECHNICAL_TARGETS.items()
            if len(targets) > 1
        }
        # DV is a digital file and a video format both; the schema
        # says so and a caller has to resolve it.
        assert set(ambiguous) <= {"DV"}, ambiguous

    def test_black_and_white_and_colour_combine(self):
        """A copy that is both is not a copy that is one of them.

        Taking whichever was stated first throws away half of what the
        record says, and the schema has a value for the combination.

        """
        from avefi_schema import model_pydantic_v2 as efi

        from efi_conv.core.vocabulary import place_technical_value

        item = efi.Item(
            is_item_of=efi.LocalResource(id="x"),
            has_primary_title=efi.Title(has_name="x", type="TitleProper"),
        )
        place_technical_value(item, "has_colour_type", "BlackAndWhite", None)
        place_technical_value(item, "has_colour_type", "Colour", None)
        assert item.has_colour_type == "ColourBlackAndWhite"

    def test_a_repeated_value_changes_nothing(self):
        from avefi_schema import model_pydantic_v2 as efi

        from efi_conv.core.vocabulary import place_technical_value

        item = efi.Item(
            is_item_of=efi.LocalResource(id="x"),
            has_primary_title=efi.Title(has_name="x", type="TitleProper"),
        )
        place_technical_value(item, "has_colour_type", "Colour", None)
        place_technical_value(item, "has_colour_type", "Colour", None)
        assert item.has_colour_type == "Colour"
