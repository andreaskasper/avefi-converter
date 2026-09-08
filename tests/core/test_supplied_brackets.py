r"""Square brackets around a whole value, and the case that used to break.

Every format module used to write ``value.startswith("[") and
value.endswith("]")``. That is true of ``[a] und [b]`` as well — a value
made of two bracketed parts rather than one bracketed whole — and
stripping the outer characters turned it into ``a] und [b``, marked as a
title the cataloguer supplied.

Reported while building the same rule for the web importer, where the
greedy pattern ``^\[.*\]$`` had the identical flaw.
"""

import pytest

from efi_conv.core.normalise import supplied_in_brackets


@pytest.mark.parametrize(
    "raw, value",
    [
        ("[Betriebsausflug 1962]", "Betriebsausflug 1962"),
        ("[ohne Titel]", "ohne Titel"),
        ("  [Aufnahmen Hafen]  ", "Aufnahmen Hafen"),
        ("[ Innenraum ]", "Innenraum"),
        # A bracketed whole may itself contain brackets.
        ("[[doppelt]]", "[doppelt]"),
    ],
)
def test_whole_value_in_brackets_is_supplied(raw, value):
    assert supplied_in_brackets(raw) == (value, True)


@pytest.mark.parametrize(
    "raw",
    [
        "Der blaue Engel",
        # A bracketed addition inside a title, not a bracketed title.
        "Der blaue Engel [Fragment]",
        "[Fragment] Der blaue Engel",
        # Starts with a bracket and ends with one, but is not bracketed
        # as a whole. This is the case the old test got wrong.
        "[a] und [b]",
        "[eins] [zwei]",
        # Unpaired brackets are left alone rather than guessed at.
        "[unvollstaendig",
        "unvollstaendig]",
        "][",
        "",
    ],
)
def test_anything_else_is_left_alone(raw):
    assert supplied_in_brackets(raw) == (raw.strip(), False)


def test_empty_pair_keeps_the_old_behaviour():
    # Callers drop empty values; ``[]`` therefore yields no title, as
    # before. Only the nesting case changes.
    assert supplied_in_brackets("[]") == ("", True)
    assert supplied_in_brackets("[  ]") == ("", True)


def test_none_is_not_an_error():
    assert supplied_in_brackets(None) == ("", False)
