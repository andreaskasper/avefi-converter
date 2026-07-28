"""The grouping layer every converter shares.

Two decisions are taken here rather than in the converters, because a
converter getting either of them wrong produces an identifier that
says something untrue about the material: which records describe one
work, and what happens to a work whose record then fails.

"""

import pytest

from efi_conv.core.records import (
    IDENTIFIER_PATTERN,
    MAX_IDENTIFIER_LENGTH,
    GroupingContext,
    local_identifier,
    make_key,
    work_key,
)
from efi_conv.core.report import ConversionReport, collecting


def film(title="Die Brücke", director="Wicki, Bernhard", date="1959"):
    """Return the key fields the converters build a work key from."""
    return {"primary_title": title, "director": director, "date": date}


class TestDegenerateWorkKey:
    def test_a_full_key_groups_two_records(self):
        assert work_key(film(), source_key="A") == work_key(
            film(), source_key="B"
        )

    def test_a_title_alone_does_not_group_two_records(self):
        """Untitled, undated amateur material is where archives live.

        Two films called Heimatfilm are two films. Registering one
        identifier for both cannot be undone by a later correction,
        whereas two works for one film can be merged.

        """
        parts = film(title="Heimatfilm", director="", date="")
        assert work_key(parts, source_key="A") != work_key(
            parts, source_key="B"
        )

    def test_two_of_three_parts_are_enough(self):
        parts = film(director="")
        assert work_key(parts, source_key="A") == work_key(
            parts, source_key="B"
        )

    def test_an_identifier_identifies_a_work_on_its_own(self):
        """EFG groups by the identifier of the creation, and may."""
        parts = {"identifier": "EFG-1", "title": "", "production_year": ""}
        assert work_key(parts, source_key="A") == work_key(
            parts, source_key="B"
        )

    def test_the_refusal_to_group_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            work_key(
                film(title="Heimatfilm", director="", date=""),
                source_key="MARC-1",
            )
        entries = [
            entry for entry in report.entries if entry.severity == "warning"
        ]
        assert entries, "A key that cannot group must not do so silently"
        assert entries[0].record_id == "MARC-1"
        assert "Heimatfilm" in str(entries[0].raw_value)

    def test_a_full_key_is_the_plain_join(self):
        """The keys of grouped records must not change shape."""
        assert work_key(film(), source_key="A") == make_key(
            "Die Brücke", "Wicki, Bernhard", "1959"
        )


class TestFailedRecordsLeaveNothingBehind:
    def test_a_work_registered_by_a_failing_record_is_dropped(self):
        context = GroupingContext()
        with pytest.raises(ValueError), context.attempt():
            context.work_for("shared", lambda: _work())
            raise ValueError("no carrier information")
        work, is_new = context.work_for("shared", lambda: _work())
        assert is_new, (
            "The next record describing this film must still emit it"
        )

    def test_a_manifestation_is_dropped_as_well(self):
        context = GroupingContext()
        with pytest.raises(ValueError), context.attempt():
            context.manifestation_for("shared", lambda: _manifestation())
            raise ValueError("boom")
        _, is_new = context.manifestation_for("shared", _manifestation)
        assert is_new

    def test_what_was_there_before_survives(self):
        context = GroupingContext()
        work, _ = context.work_for("kept", _work)
        with pytest.raises(ValueError), context.attempt():
            context.work_for("dropped", _work)
            raise ValueError("boom")
        again, is_new = context.work_for("kept", _work)
        assert again is work
        assert not is_new

    def test_a_successful_record_keeps_its_work(self):
        context = GroupingContext()
        with context.attempt():
            work, _ = context.work_for("shared", _work)
        again, is_new = context.work_for("shared", _work)
        assert again is work
        assert not is_new


def _work():
    from avefi_schema import model_pydantic_v2 as efi

    return efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=efi.Title(
            type=efi.TitleTypeEnum("PreferredTitle"), has_name="Die Brücke"
        ),
    )


def _manifestation():
    from avefi_schema import model_pydantic_v2 as efi

    return efi.Manifestation(
        is_manifestation_of=[efi.LocalResource(id="x_work")],
        has_primary_title=efi.Title(
            type=efi.TitleTypeEnum("TitleProper"), has_name="Die Brücke"
        ),
    )


class TestLocalIdentifier:
    """What a minted identifier may contain, and why it stays unique.

    An identifier minted here ends up in a handle, in an IRI built
    from it and in front of the people reviewing a conversion. Letters
    and digits are therefore kept, whatever script they are written
    in, while every character that means something to a URI parser is
    replaced by ``_``. Replacing loses information, so a value that
    had anything replaced carries a digest of itself: two source keys
    must never arrive at one identifier, because an identifier
    registered for two films cannot be taken back.

    """

    @pytest.mark.parametrize(
        "value",
        [
            "Ohne Titel (Werbefilm)__1962/1965",
            "Brücke, Die__Wicki, Bernhard__1959",
            "https://www.deutsche-digitale-bibliothek.de/item/AAAA0001",
            "(DE-Mb112)F 1959/12",
            "MAN-002#item",
            "STADTARCHIV DÜSSELDORF - BOBBEL SPORTLICH?",
            "ger:SpokenLanguage",
            "x" * 400,
        ],
    )
    def test_the_identifier_holds_nothing_a_uri_parser_reads(self, value):
        assert IDENTIFIER_PATTERN.fullmatch(local_identifier(value))

    @pytest.mark.parametrize(
        "value",
        ["a/b", "a:b", "a b", "a#b", "a?b", "a%b", "a~b", "a+b", "a\tb"],
    )
    def test_no_character_survives_that_a_uri_would_read(self, value):
        assert IDENTIFIER_PATTERN.fullmatch(local_identifier(value))
        assert local_identifier(value) != local_identifier("ab")

    def test_keys_differing_only_in_dropped_characters_stay_apart(self):
        """The old slug deleted them, which merged two films into one."""
        keys = ["a/b", "a:b", "a b", "a#b", "a?b", "a%b", "a~b", "ab"]
        assert len({local_identifier(key) for key in keys}) == len(keys)

    @pytest.mark.parametrize(
        "value",
        [
            "FMDU-0001",
            "Brücke",
            "Sanitätshunde__1916",
            "Bemaßung.v2-3_final",
            "白蛇伝",
        ],
    )
    def test_a_value_needing_no_substitution_is_passed_through(self, value):
        """Readability is the point: an untouched value stays itself."""
        assert local_identifier(value) == value

    def test_a_readable_identifier_still_tells_two_values_apart(self):
        """The readable part is shared, the digest behind it is not."""
        comma = local_identifier("Brücke, Die__1959")
        slash = local_identifier("Brücke/ Die__1959")
        assert comma.startswith("Brücke_Die__1959")
        assert slash.startswith("Brücke_Die__1959")
        assert comma != slash

    def test_a_long_value_is_shortened_but_stays_distinct(self):
        first = "Die Brücke " * 40 + "A"
        second = "Die Brücke " * 40 + "B"
        assert len(local_identifier(first)) <= MAX_IDENTIFIER_LENGTH + 20
        assert local_identifier(first) != local_identifier(second)
        assert IDENTIFIER_PATTERN.fullmatch(local_identifier(first))

    def test_a_shortened_value_cannot_look_like_a_short_one(self):
        """No value keeps the marker, so no value can spell it out."""
        long_form = local_identifier("Die Brücke " * 40)
        assert "~~" in long_form
        assert "~~" not in local_identifier("~~")

    def test_the_same_value_always_yields_the_same_identifier(self):
        assert local_identifier("a b/c") == local_identifier("a b/c")

    def test_surrounding_whitespace_is_not_part_of_the_value(self):
        assert local_identifier("  FMDU-0001\n") == local_identifier(
            "FMDU-0001"
        )

    def test_an_empty_value_does_not_borrow_a_real_one(self):
        assert IDENTIFIER_PATTERN.fullmatch(local_identifier("   "))
        assert local_identifier("   ") != local_identifier("record")


class TestGroupedIdentifiers:
    """The identifiers the shared grouping layer mints."""

    def test_a_work_identifier_is_safe(self):
        context = GroupingContext()
        work, _ = context.work_for(
            make_key("Ohne Titel", "1962/1965"), lambda: _bare_work()
        )
        assert IDENTIFIER_PATTERN.fullmatch(work.has_identifier[0].id)

    def test_a_manifestation_identifier_is_safe(self):
        context = GroupingContext()
        manifestation, _ = context.manifestation_for(
            make_key("Die Brücke", "35mm", "ger:SpokenLanguage"),
            lambda: _bare_manifestation(),
        )
        assert IDENTIFIER_PATTERN.fullmatch(manifestation.has_identifier[0].id)

    def test_two_keys_do_not_share_one_work(self):
        context = GroupingContext()
        first, _ = context.work_for("Heimat/1959", lambda: _bare_work())
        second, _ = context.work_for("Heimat:1959", lambda: _bare_work())
        assert first.has_identifier[0].id != second.has_identifier[0].id


def _bare_work():
    from avefi_schema import model_pydantic_v2 as efi

    return efi.WorkVariant(
        type=efi.WorkVariantTypeEnum("Monographic"),
        has_primary_title=efi.Title(
            type=efi.TitleTypeEnum("PreferredTitle"), has_name="x"
        ),
    )


def _bare_manifestation():
    from avefi_schema import model_pydantic_v2 as efi

    return efi.Manifestation(
        is_manifestation_of=[efi.LocalResource(id="w")],
        has_primary_title=efi.Title(
            type=efi.TitleTypeEnum("TitleProper"), has_name="x"
        ),
    )
