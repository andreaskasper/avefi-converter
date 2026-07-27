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
            # Decades
            ("50er Jahre", "1950/1959"),
            ("1950er", "1950/1959"),
            ("1950er Jahre", "1950/1959"),
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

    def test_result_always_complies_with_iso_date(self):
        for source in ("1962-65", "ca. 1962", "50er Jahre", "15.03.1962"):
            assert ISO_DATE_PATTERN.match(normalise_date(source))


class TestNormaliseDuration:
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
            ("0", "min", "PT00H00M00S"),
        ],
    )
    def test_maps_known_notations(self, value, unit, expected):
        assert normalise_duration(value, unit) == expected

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
