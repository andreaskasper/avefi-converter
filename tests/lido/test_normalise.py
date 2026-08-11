import pytest

from efi_conv.lido import normalise
from efi_conv.lido.normalise import (
    ISO_DATE_PATTERN,
    ISO_DURATION_PATTERN,
    NormalisationError,
    normalise_date,
    normalise_duration,
    normalise_title,
)


class TestNormaliseDate:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            # The rule named explicitly in the commission
            ("1962-65", "1962/1965"),
            ("1972-73", "1972/1973"),
            # Century roll over
            ("1998-02", "1998-02"),
            ("1962-1965", "1962/1965"),
            ("1962/1965", "1962/1965"),
            ("1962", "1962"),
            ("  1962  ", "1962"),
            # Approximation and uncertainty
            ("ca. 1962", "1962~"),
            ("um 1962", "1962~"),
            ("1962?", "1962?"),
            # German day and month notation
            ("15.03.1962", "1962-03-15"),
            ("3.1962", "1962-03"),
            # Already ISO
            ("1962-03-15", "1962-03-15"),
        ],
    )
    def test_maps_known_expressions(self, source, expected):
        assert normalise_date(source) == expected

    @pytest.mark.parametrize(
        "source",
        ["", "ohne Datum", "o. D.", "unbekannt", "n.d.", None],
    )
    def test_reports_absence_as_none(self, source):
        assert normalise_date(source) is None

    @pytest.mark.parametrize(
        "source",
        ["irgendwann", "1962-1961", "19. Jahrhundert", "1962--1965", "abc"],
    )
    def test_rejects_ambiguous_values(self, source):
        with pytest.raises(NormalisationError):
            normalise_date(source)

    @pytest.mark.parametrize(
        "source", ["50er Jahre", "1950er", "1950er Jahre"]
    )
    def test_decades_need_an_agreed_representation(self, source):
        """The contract reserves this mapping for after agreement."""
        with pytest.raises(NormalisationError):
            normalise_date(source)

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("50er Jahre", "1950/1959"),
            ("1950er", "1950/1959"),
            ("1950er Jahre", "1950/1959"),
            ("1920er", "1920/1929"),
        ],
    )
    def test_decades_map_once_enabled(self, source, expected):
        assert normalise_date(source, map_decades=True) == expected

    @pytest.mark.parametrize(
        "source", ["1959-13", "1959-00", "1959-99", "1900-25"]
    )
    def test_refuses_an_implausible_abbreviated_interval(self, source):
        """A mistyped month must not become a decades long interval."""
        with pytest.raises(NormalisationError) as excinfo:
            normalise_date(source)
        assert "interval" in str(excinfo.value).lower()

    @pytest.mark.parametrize(
        ("source", "expected"),
        [("1959-60", "1959/1960"), ("1962-65", "1962/1965")],
    )
    def test_keeps_the_abbreviated_intervals_that_make_sense(
        self, source, expected
    ):
        assert normalise_date(source) == expected

    def test_result_always_complies_with_iso_date(self):
        for source in ("1962-65", "ca. 1962", "15.03.1962"):
            assert ISO_DATE_PATTERN.match(normalise_date(source))


class TestNotationsRatherThanGuesses:
    """The same date, written the way a cataloguer wrote it.

    Everything here is a different spelling of a date the source
    already states, not a heuristic reading of one it does not. The
    result is the value the provider gave, punctuation removed.

    """

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            # A question mark in brackets is the commoner form of the
            # trailing one in this data, a hundred occurrences to two.
            ("1960 (?)", "1960?"),
            ("1960(?)", "1960?"),
            ("1950-1970 ?", "1950?/1970?"),
            # A circa marker written in two languages at once. Forty
            # occurrences in one export, none of them convertible
            # while the check was for a prefix and a space.
            ("ca./ c. 1982", "1982~"),
            ("ca. / c. 1982", "1982~"),
            ("c. 1982", "1982~"),
            # Month by name, German and English, full and short
            ("Juni 1980", "1980-06"),
            ("Jan 1979", "1979-01"),
            ("Oktober 1981", "1981-10"),
            ("March 1962", "1962-03"),
            ("1980 Juni", "1980-06"),
            # Month and year separated by the interval character
            ("8/1988", "1988-08"),
            ("08/1988", "1988-08"),
            # Brackets mark a date the cataloguer supplied
            ("[1965 - 1975]", "1965/1975"),
            ("[1965]", "1965"),
            # An interval spelled out in words
            ("zwischen 1940 und 1945", "1940/1945"),
            ("1970 bis 1977", "1970/1977"),
            ("ca. 1970 bis 1977", "1970~/1977~"),
        ],
    )
    def test_reads_the_notation(self, source, expected):
        assert normalise_date(source) == expected

    @pytest.mark.parametrize("source", ["?", "??", "?" * 56, "?? ??"])
    def test_a_run_of_question_marks_is_no_date_at_all(self, source):
        """A single one already means that. Repeating it changes nothing."""
        assert normalise_date(source) is None

    @pytest.mark.parametrize("source", ["nach 1989", "vor 1950", "seit 1970"])
    def test_open_intervals_stay_unconvertible(self, source):
        """EDTF level 0 has no open end, and the schema allows no more.

        Reading "nach 1989" as 1989 would state a production year the
        source explicitly refuses to give.

        """
        with pytest.raises(NormalisationError):
            normalise_date(source)

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("1980er?", "1980?/1989?"),
            ("ca. 1970er Jahre", "1970~/1979~"),
            ("1940-1950er Jahre", "1940/1959"),
            ("ca. 1940-1950er Jahre", "1940~/1959~"),
        ],
    )
    def test_qualified_decades_once_enabled(self, source, expected):
        """A decade is an interval; the qualifier applies to both ends.

        EDTF level 0 has no decade syntax — 197X would be level 2 —
        so the closed interval is the only form the schema allows.

        """
        assert normalise_date(source, map_decades=True) == expected

    @pytest.mark.parametrize(
        "source", ["1940-1950er Jahre", "1980er?", "ca. 1960er"]
    )
    def test_decade_spans_still_need_the_agreement(self, source):
        with pytest.raises(NormalisationError) as excinfo:
            normalise_date(source)
        assert "map_decades" in str(excinfo.value)


class TestNormaliseDuration:
    @pytest.mark.parametrize(
        ("value", "unit"),
        [("0", "min"), ("0", "h"), ("0.0", "min"), ("0E-10", "h")],
    )
    def test_zero_is_no_running_time(self, value, unit):
        """A copy that runs no length is not what the source means.

        Cataloguing systems write an empty measurement as a zero, and
        one of them writes it as 0E-10; 1084 records of the reference
        export do. Recording PT00H00M00S would state a fact about the
        copy where the source states that nobody measured it.

        """
        assert normalise_duration(value, unit) is None

    @pytest.mark.parametrize(
        ("value", "unit", "expected"),
        [
            ("103", "min", "PT01H43M00S"),
            ("103", None, "PT01H43M00S"),
            ("01:43:00", None, "PT01H43M00S"),
            ("1:43", None, "PT00H01M43S"),
            ("1 h 43 min", None, "PT01H43M00S"),
            ("6180", "s", "PT01H43M00S"),
            ("1,5", "h", "PT01H30M00S"),
            ("90", "Minuten", "PT01H30M00S"),
        ],
    )
    def test_maps_known_notations(self, value, unit, expected):
        assert normalise_duration(value, unit) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("PT01H43M00S", "PT01H43M00S"),
            ("PT1H43M", "PT01H43M00S"),
            ("pt01h43m00s", "PT01H43M00S"),
            ("PT103M", "PT01H43M00S"),
            ("P0DT01H43M00S", "PT01H43M00S"),
            ("PT6180S", "PT01H43M00S"),
            ("PT1H43M0.4S", "PT01H43M00S"),
        ],
    )
    def test_reads_the_iso_form_it_writes_itself(self, value, expected):
        """EFG and PBCore state a duration in free text, ISO included."""
        assert normalise_duration(value) == expected

    @pytest.mark.parametrize("value", ["P", "PT", "P2Y", "PT1X"])
    def test_rejects_an_iso_duration_without_a_running_time(self, value):
        with pytest.raises(NormalisationError):
            normalise_duration(value)

    @pytest.mark.parametrize("value", ["", None])
    def test_absent_duration_is_none(self, value):
        assert normalise_duration(value) is None

    @pytest.mark.parametrize(
        ("value", "unit"),
        [("lang", None), ("103", "Meter"), ("abc:def", None)],
    )
    def test_rejects_unknown_notations(self, value, unit):
        with pytest.raises(NormalisationError):
            normalise_duration(value, unit)

    def test_result_always_complies_with_the_schema_pattern(self):
        for minutes in (1, 59, 60, 61, 599, 600):
            result = normalise_duration(str(minutes), "min")
            assert ISO_DURATION_PATTERN.match(result), result


class TestNormaliseTitle:
    @pytest.mark.parametrize(
        ("value", "language", "expected"),
        [
            # Leading article yields an ordering name
            ("Die Brücke", "ger", ("Die Brücke", "Brücke, Die")),
            ("The Bridge", "eng", ("The Bridge", "Bridge, The")),
            # Trailing article yields a display name
            ("Brücke, Die", "ger", ("Die Brücke", "Brücke, Die")),
            ("Bridge, The", "eng", ("The Bridge", "Bridge, The")),
            # Elided article, no space after the apostrophe
            ("L'Atalante", "fre", ("L'Atalante", "Atalante, L'")),
            ("Atalante, L'", "fre", ("L'Atalante", "Atalante, L'")),
            # Nothing to do
            ("Nosferatu", "ger", ("Nosferatu", None)),
            ("Metropolis", None, ("Metropolis", None)),
            # Whitespace is normalised
            ("  Die   Brücke ", "ger", ("Die Brücke", "Brücke, Die")),
        ],
    )
    def test_moves_articles_in_both_directions(
        self, value, language, expected
    ):
        assert normalise_title(value, language) == expected

    def test_round_trip_is_stable(self):
        display, ordering = normalise_title("Die Brücke", "ger")
        assert normalise_title(ordering, "ger") == (display, ordering)

    def test_language_without_articles_leaves_title_alone(self):
        assert normalise_title("Der Film", "jpn") == ("Der Film", None)

    def test_empty_title_is_rejected(self):
        with pytest.raises(NormalisationError):
            normalise_title("   ")


class TestLanguageCode:
    @pytest.mark.parametrize(
        ("tag", "expected"),
        [
            ("de", "ger"),
            ("de-DE", "ger"),
            ("DEU", "ger"),
            ("en", "eng"),
            ("fr", "fre"),
            ("xx", None),
            (None, None),
        ],
    )
    def test_maps_xml_lang_to_iso_639_2b(self, tag, expected):
        assert normalise.language_code(tag) == expected
