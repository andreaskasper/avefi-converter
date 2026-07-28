"""The grouping layer every converter shares.

Two decisions are taken here rather than in the converters, because a
converter getting either of them wrong produces an identifier that
says something untrue about the material: which records describe one
work, and what happens to a work whose record then fails.

"""

import pytest

from efi_conv.core.records import GroupingContext, make_key, work_key
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
