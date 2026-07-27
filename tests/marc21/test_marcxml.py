"""Unit tests for the MARCXML reader and the fixed field parsing.

The fixed fields are where a MARC mapping goes wrong quietly: a
character position is off by one, or a position of field 007 is read
with the meaning it has for the other category of carrier. They are
therefore exercised here on hand built records rather than only through
the sample export.

"""

import pytest

from efi_conv.core.report import ConversionReport, collecting
from efi_conv.marc21 import mapping, marcxml
from efi_conv.marc21.marcxml import DataField, MarcRecord, Subfield
from efi_conv.marc21.profile import Marc21Profile

PROFILE = Marc21Profile(
    issuer_info={"has_issuer_id": "x", "has_issuer_name": "x"}
)

SINGLE_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<record xmlns="http://www.loc.gov/MARC21/slim">
  <leader>01234ngm a2200349 a 4500</leader>
  <controlfield tag="001">12345</controlfield>
  <controlfield tag="007">mr baaafa arc</controlfield>
  <controlfield tag="007">vf cbaaou</controlfield>
  <datafield tag="245" ind1="1" ind2="4">
    <subfield code="a">Die Br&#252;cke /</subfield>
    <subfield code="c">Bernhard Wicki.</subfield>
  </datafield>
</record>
"""

COLLECTION = """<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
  <record><leader>a</leader>
    <controlfield tag="001">one</controlfield></record>
  <record><leader>b</leader>
    <controlfield tag="001">two</controlfield></record>
</collection>
"""

WITHOUT_NAMESPACE = """<?xml version="1.0" encoding="UTF-8"?>
<collection>
  <record><leader>a</leader>
    <controlfield tag="001">plain</controlfield></record>
</collection>
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestFixedPosition:
    def test_returns_the_requested_characters(self):
        assert marcxml.fixed_position("abcdef", 2, 3) == "cde"

    def test_returns_empty_beyond_the_end(self):
        assert marcxml.fixed_position("abc", 7) == ""

    def test_returns_empty_for_a_truncated_range(self):
        assert marcxml.fixed_position("abc", 2, 3) == ""

    def test_returns_empty_without_a_field(self):
        assert marcxml.fixed_position(None, 0) == ""

    @pytest.mark.parametrize("code", ["", " ", "|", "#", None])
    def test_fill_characters_carry_no_value(self, code):
        assert marcxml.is_fill(code)

    def test_a_real_code_is_not_a_fill(self):
        assert not marcxml.is_fill("m")


class TestReader:
    def test_reads_a_document_whose_root_is_a_record(self, tmp_path):
        path = write(tmp_path, "one.xml", SINGLE_RECORD)
        records = list(marcxml.iter_records(path))
        assert len(records) == 1
        assert records[0].control_field("001") == "12345"

    def test_reads_a_collection(self, tmp_path):
        path = write(tmp_path, "many.xml", COLLECTION)
        records = list(marcxml.iter_records(path))
        assert [r.control_field("001") for r in records] == ["one", "two"]

    def test_reads_a_document_without_a_namespace(self, tmp_path):
        path = write(tmp_path, "plain.xml", WITHOUT_NAMESPACE)
        records = list(marcxml.iter_records(path))
        assert [r.control_field("001") for r in records] == ["plain"]

    def test_keeps_the_leader_verbatim(self, tmp_path):
        path = write(tmp_path, "one.xml", SINGLE_RECORD)
        record = next(iter(marcxml.iter_records(path)))
        assert len(record.leader) == 24
        assert marcxml.fixed_position(record.leader, 6) == "g"

    def test_007_is_repeatable(self, tmp_path):
        path = write(tmp_path, "one.xml", SINGLE_RECORD)
        record = next(iter(marcxml.iter_records(path)))
        assert len(record.control_field_values("007")) == 2
        assert record.control_field("007").startswith("m")

    def test_exposes_indicators_and_subfields(self, tmp_path):
        path = write(tmp_path, "one.xml", SINGLE_RECORD)
        record = next(iter(marcxml.iter_records(path)))
        field = record.fields("245")[0]
        assert (field.ind1, field.ind2) == ("1", "4")
        assert field.subfield("a") == "Die Brücke /"
        assert record.subfield("245", "c") == "Bernhard Wicki."
        assert record.subfields("245", "a") == ["Die Brücke /"]
        assert field.codes() == ["a", "c"]

    def test_missing_fields_yield_none(self, tmp_path):
        path = write(tmp_path, "one.xml", SINGLE_RECORD)
        record = next(iter(marcxml.iter_records(path)))
        assert record.control_field("008") is None
        assert record.subfield("245", "z") is None
        assert record.fields("500") == []


def record_with(leader="01234ngm a2200349 a 4500", **control):
    """Return a MarcRecord carrying the given control fields."""
    return MarcRecord(
        leader=leader,
        control_fields=tuple(
            (tag.removeprefix("f"), value) for tag, value in control.items()
        ),
    )


class TestDates008:
    """Position 06 decides how positions 07-10 and 11-14 are read."""

    def dates(self, value):
        return mapping.dates_from_008(record_with(f008=value), PROFILE, "test")

    def field(self, date_type, date1, date2="    "):
        return f"590101{date_type}{date1}{date2}gw 103" + " " * 19

    def test_single_date_is_a_production_date(self):
        dates = self.dates(self.field("s", "1959"))
        assert dates.production == "1959"
        assert dates.publication is None

    def test_detailed_date_yields_month_and_day(self):
        dates = self.dates(self.field("e", "1959", "1025"))
        assert dates.production == "1959-10-25"

    def test_detailed_date_without_a_day_yields_a_month(self):
        dates = self.dates(self.field("e", "1959", "1000"))
        assert dates.production == "1959-10"

    def test_multiple_dates_become_an_interval(self):
        dates = self.dates(self.field("m", "1962", "1965"))
        assert dates.production == "1962/1965"

    def test_questionable_dates_are_qualified(self):
        dates = self.dates(self.field("q", "1962", "1965"))
        assert dates.production == "1962?/1965?"

    def test_distribution_date_comes_first_and_production_second(self):
        dates = self.dates(self.field("p", "1998", "1959"))
        assert dates.publication == "1998"
        assert dates.production == "1959"

    def test_reissue_date_comes_first_and_original_second(self):
        dates = self.dates(self.field("r", "1998", "1959"))
        assert (dates.publication, dates.production) == ("1998", "1959")

    def test_copyright_date_is_reported_rather_than_mapped(self):
        report = ConversionReport()
        with collecting(report):
            dates = self.dates(self.field("t", "1959", "1960"))
        assert dates.publication == "1959"
        assert dates.production is None
        assert any("Copyright" in e.message for e in report.entries)

    def test_no_dates_given_yields_nothing(self):
        assert self.dates(self.field("b", "    ")).production is None

    def test_open_ended_range_yields_no_end_date(self):
        dates = self.dates(self.field("c", "1962", "9999"))
        assert dates.production == "1962"

    def test_partially_unknown_date_is_reported_and_left_unset(self):
        report = ConversionReport()
        with collecting(report):
            dates = self.dates(self.field("s", "196u"))
        assert dates.production is None
        assert any(
            e.severity == "warning" and "Partially unknown" in e.message
            for e in report.entries
        )

    def test_wholly_unknown_date_is_reported_as_information(self):
        report = ConversionReport()
        with collecting(report):
            dates = self.dates(self.field("s", "uuuu"))
        assert dates.production is None
        assert any(e.severity == "info" for e in report.entries)

    def test_unknown_date_type_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            dates = self.dates(self.field("x", "1959", "1960"))
        assert dates.production == "1959"
        assert any(
            e.severity == "warning" and "date type" in e.message
            for e in report.entries
        )

    def test_reversed_interval_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            dates = self.dates(self.field("m", "1965", "1962"))
        assert dates.production == "1965"
        assert any("ends before" in e.message for e in report.entries)

    def test_a_record_without_008_has_no_dates(self):
        dates = mapping.dates_from_008(record_with(), PROFILE, "test")
        assert (dates.production, dates.publication) == (None, None)


class TestCarrier007:
    """The meaning of a position of 007 depends on position 00."""

    def carrier(self, *values):
        record = MarcRecord(
            control_fields=tuple(("007", value) for value in values)
        )
        return mapping.carrier_from_007(record, PROFILE, "test")

    def test_motion_picture_gauge_comes_from_position_07(self):
        # 03 b, 04 a, 05 a, 07 f, 11 r
        carrier = self.carrier("mr baaafa arc")
        assert carrier.formats == [("Film", "35mmFilm")]
        assert carrier.colour == "BlackAndWhite"
        assert carrier.sound == "Sound"
        assert carrier.access_status == "Viewing"

    def test_videorecording_format_comes_from_position_04(self):
        # 03 b, 04 b VHS, 05 a, 07 o half inch tape
        carrier = self.carrier("vf bbaaou")
        assert carrier.formats == [("Video", "VHS")]
        assert carrier.colour == "BlackAndWhite"
        assert carrier.sound == "Sound"

    def test_video_position_07_is_not_read_as_a_film_gauge(self):
        """Position 07 of a videorecording is the tape width."""
        # A film gauge of "a" would be 8 mm; here 07 is a tape width.
        carrier = self.carrier("vf bbaaau")
        assert carrier.formats == [("Video", "VHS")]
        assert all(kind != "Film" for kind, _ in carrier.formats)

    def test_film_position_04_is_not_read_as_a_video_format(self):
        """Position 04 of a motion picture is the aperture."""
        # 04 is "b", which would be VHS for a videorecording.
        carrier = self.carrier("mr bbaafa arc")
        assert carrier.formats == [("Film", "35mmFilm")]

    def test_blank_sound_position_means_silent(self):
        carrier = self.carrier("mr ba afa arc")
        assert carrier.sound == "Silent"

    def test_generation_is_read_for_motion_pictures_only(self):
        carrier = self.carrier("vf bbaaou")
        assert carrier.access_status is None

    def test_unmapped_gauge_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            carrier = self.carrier("mr caaaea a c")
        assert carrier.formats == []
        assert any(
            e.severity == "warning" and e.source_field == "007/07"
            for e in report.entries
        )

    def test_unknown_code_is_reported_as_information(self):
        report = ConversionReport()
        with collecting(report):
            carrier = self.carrier("mr uaaafa arc")
        assert carrier.colour is None
        assert any(
            e.severity == "info" and e.source_field == "007/03"
            for e in report.entries
        )

    def test_another_material_category_is_reported_and_skipped(self):
        report = ConversionReport()
        with collecting(report):
            carrier = self.carrier("gs c")
        assert carrier.formats == []
        assert any(e.source_field == "007/00" for e in report.entries)

    def test_the_first_007_wins_when_several_disagree(self):
        carrier = self.carrier("mr baaafa arc", "mr caaada arc")
        assert carrier.colour == "BlackAndWhite"
        assert carrier.formats == [
            ("Film", "35mmFilm"),
            ("Film", "16mmFilm"),
        ]


class TestRunningTime008:
    def duration(self, minutes):
        value = f"590101s1959    gw {minutes}" + " " * 19
        return mapping.duration_from_008(record_with(f008=value), "test")

    def test_minutes_become_a_duration(self):
        assert self.duration("103") == "PT01H43M00S"

    def test_not_applicable_yields_nothing(self):
        assert self.duration("nnn") is None

    def test_blank_yields_nothing(self):
        assert self.duration("   ") is None

    def test_overlong_running_time_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            assert self.duration("000") is None
        assert any("exceeds three digits" in e.message for e in report.entries)

    def test_unknown_running_time_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            assert self.duration("---") is None
        assert report.entries

    def test_a_non_numeric_running_time_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            assert self.duration("1x3") is None
        assert any(e.severity == "warning" for e in report.entries)


class TestLanguageCodes:
    def codes(self, raw):
        return list(mapping.language_codes(raw, "test", "041$a"))

    def test_a_single_code(self):
        assert self.codes("ger") == ["ger"]

    def test_concatenated_codes_are_split(self):
        assert self.codes("gerengfre") == ["ger", "eng", "fre"]

    def test_no_linguistic_content_is_a_code_of_its_own(self):
        assert self.codes("zxx") == ["zxx"]

    def test_a_fill_yields_nothing(self):
        assert self.codes("   ") == []
        assert self.codes(None) == []

    def test_an_unknown_code_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            assert self.codes("xyz") == []
        assert any(e.severity == "warning" for e in report.entries)


class TestTextHelpers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Die Brücke /", "Die Brücke"),
            ("München :", "München"),
            ("Fono-Film,", "Fono-Film"),
            ("Titel ;", "Titel"),
            ("Titel", "Titel"),
        ],
    )
    def test_isbd_punctuation_is_removed(self, value, expected):
        assert mapping.strip_isbd(value) == expected

    def test_a_terminating_full_stop_is_removed(self):
        assert mapping.strip_trailing_period("Wicki, Bernhard.") == (
            "Wicki, Bernhard"
        )

    def test_an_abbreviation_keeps_its_full_stop(self):
        assert mapping.strip_trailing_period("Meyer, H.") == "Meyer, H."

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1959.", "1959"),
            ("[1965]", "1965"),
            ("c1959", "1959"),
            ("©1965", "1965"),
            ("1959,", "1959"),
        ],
    )
    def test_publication_dates_lose_their_markup(self, value, expected):
        assert mapping.publication_date_text(value) == expected


class TestTitleFromField:
    def field(self, ind2, *subfields):
        return DataField(
            tag="245",
            ind1="1",
            ind2=ind2,
            subfields=tuple(
                Subfield(code, value) for code, value in subfields
            ),
        )

    def title(self, data_field):
        return mapping.title_from_field(
            data_field,
            "ger",
            nonfiling=mapping.nonfiling_count(data_field.ind2),
            record_id="test",
            source_field="245",
            target_field="has_primary_title.has_ordering_name",
        )

    def test_nonfiling_indicator_gives_the_ordering_name(self):
        title = self.title(self.field("4", ("a", "Die Brücke.")))
        assert (title.display, title.ordering) == (
            "Die Brücke",
            "Brücke, Die",
        )

    def test_indicator_zero_falls_back_to_the_article_list(self):
        title = self.title(self.field("0", ("a", "Die Brücke.")))
        assert title.ordering == "Brücke, Die"

    def test_subtitle_is_joined_with_a_colon(self):
        title = self.title(
            self.field("0", ("a", "Werbefilm :"), ("b", "Kurzfassung."))
        )
        assert title.display == "Werbefilm : Kurzfassung"

    def test_part_number_and_name_are_joined_with_a_full_stop(self):
        title = self.title(
            self.field(
                "0", ("a", "Serie."), ("n", "Teil 2,"), ("p", "Die Reise.")
            )
        )
        assert title.display == "Serie. Teil 2. Die Reise"

    def test_a_bracketed_title_is_devised(self):
        title = self.title(self.field("5", ("a", "[Die Brücke]")))
        assert title.supplied
        assert (title.display, title.ordering) == (
            "Die Brücke",
            "Brücke, Die",
        )

    def test_an_excessive_indicator_is_reported(self):
        report = ConversionReport()
        with collecting(report):
            title = self.title(self.field("9", ("a", "Brücke")))
        assert title.display == "Brücke"
        assert any(e.severity == "warning" for e in report.entries)

    def test_a_field_without_title_subfields_yields_nothing(self):
        assert self.title(self.field("0", ("c", "Bernhard Wicki."))) is None
