"""Property based tests for the date and title normalisers.

Example based tests confirm the cases we thought of. These check the
invariants that have to hold for every input, which is where the odd
notations in real holdings data tend to surface.

"""

import re

from hypothesis import assume, given
from hypothesis import strategies as st
import pytest

from efi_conv.core.normalise import MAX_ABBREVIATED_INTERVAL_YEARS
from efi_conv.lido.normalise import (
    ARTICLES,
    ISO_DATE_PATTERN,
    ISO_DURATION_PATTERN,
    NormalisationError,
    normalise_date,
    normalise_duration,
    normalise_title,
)

years = st.integers(min_value=1000, max_value=2999)
# From one, because a running time of zero is read as none given
# rather than as a copy that runs no length.
minutes = st.integers(min_value=1, max_value=6000)
words = st.text(
    alphabet=st.characters(
        min_codepoint=32, max_codepoint=0x24F, blacklist_categories=("Cc",)
    ),
    min_size=1,
    max_size=40,
)


@given(years)
def test_bare_year_is_preserved(year):
    assert normalise_date(str(year)) == f"{year:04d}"


@given(years, st.integers(min_value=13, max_value=99))
def test_abbreviated_interval_stays_within_a_plausible_span(year, end):
    # Two trailing digits below 13 are read as an ISO month instead,
    # which is covered by test_ambiguous_year_month_stays_iso. An
    # interval that would run for decades is refused rather than
    # asserted as a fact about the production.
    try:
        result = normalise_date(f"{year}-{end:02d}")
    except NormalisationError:
        return
    start_text, separator, end_text = result.partition("/")
    assert separator == "/", result
    assert (
        int(start_text)
        <= int(end_text)
        <= int(start_text) + MAX_ABBREVIATED_INTERVAL_YEARS
    )


@given(years, st.integers(min_value=1, max_value=12))
def test_ambiguous_year_month_stays_iso(year, month):
    assert normalise_date(f"{year}-{month:02d}") == f"{year}-{month:02d}"


@given(st.one_of(st.just(""), words))
def test_date_either_maps_or_raises_but_never_returns_junk(value):
    try:
        result = normalise_date(value)
    except NormalisationError:
        return
    if result is not None:
        assert ISO_DATE_PATTERN.match(result), result


@given(minutes)
def test_duration_round_trips_through_minutes(value):
    result = normalise_duration(str(value), "min")
    match = ISO_DURATION_PATTERN.match(result)
    assert match, result
    hours, mins, secs = re.match(r"^PT(\d+)H(\d\d)M(\d\d)S$", result).groups()
    assert int(hours) * 60 + int(mins) == value
    assert secs == "00"


@given(words)
def test_duration_either_maps_or_raises(value):
    try:
        result = normalise_duration(value)
    except NormalisationError:
        return
    if result is not None:
        assert ISO_DURATION_PATTERN.match(result), result


@given(
    st.sampled_from(sorted(ARTICLES)),
    words,
)
def test_reordering_never_introduces_stray_punctuation(language, rest):
    """Moving an article must not produce a name that starts on a comma.

    A title such as "den ," is degenerate input: the normaliser has to
    leave it alone rather than turn it into ", den".

    """
    assume(rest.strip())
    article = ARTICLES[language][0]
    try:
        display, ordering = normalise_title(f"{article} {rest}", language)
    except NormalisationError:
        return
    if ordering is not None:
        assert not ordering.startswith(",")
        assert not ordering.startswith(" ")
        assert any(character.isalnum() for character in ordering)


@given(st.sampled_from(sorted(ARTICLES)), words)
def test_moving_an_article_is_reversible(language, main):
    assume(main.strip())
    assume("," not in main)
    article = ARTICLES[language][0]
    display, ordering = normalise_title(f"{article} {main}", language)
    if ordering is None:
        return
    assert normalise_title(ordering, language) == (display, ordering)


@given(words)
def test_title_is_never_empty(value):
    try:
        display, _ = normalise_title(value)
    except NormalisationError:
        return
    assert display.strip()


def test_normalise_title_rejects_blank_input():
    with pytest.raises(NormalisationError):
        normalise_title("")
