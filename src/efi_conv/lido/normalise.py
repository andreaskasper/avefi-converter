"""Normalisation routines shared by all LIDO based converters.

The rules implemented here are the ones agreed for the conversion of
LIDO holdings metadata to the AVefi schema. They are deliberately kept
free of any LIDO parsing so that they can be unit tested in isolation.

"""

import re

from ..core.report import report_issue

#: Pattern for the ISODate type of the AVefi schema.
ISO_DATE_PATTERN = re.compile(
    r"^-?([1-9][0-9]{3,}|0[0-9]{3})(-(0[1-9]|1[0-2])"
    r"(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?"
    r"(/-?([1-9][0-9]{3,}|0[0-9]{3})"
    r"(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?)?$"
)

#: Pattern for the ISODurationInHours type of the AVefi schema.
ISO_DURATION_PATTERN = re.compile(
    r"^PT[1-9]*[0-9][0-9]H[0-5][0-9]M[0-5][0-9]S$"
)

#: Values that stand for "no date given" rather than for a date.
EMPTY_DATE_VALUES = frozenset(
    {
        "",
        "-",
        "?",
        "o.a.",
        "o. a.",
        "o.d.",
        "o. d.",
        "o.j.",
        "o. j.",
        "ohne datum",
        "ohne jahr",
        "unbekannt",
        "unknown",
        "n.d.",
        "n. d.",
        "no date",
    }
)

#: Prefixes marking an approximate date.
CIRCA_PREFIXES = ("ca.", "ca", "circa", "um", "about", "approx.", "etwa")

#: Leading articles per ISO 639-2/B language code.
ARTICLES = {
    "ger": ("der", "die", "das", "ein", "eine", "einer", "eines", "einem"),
    "eng": ("the", "a", "an"),
    "fre": ("le", "la", "les", "un", "une", "des", "l'"),
    "ita": ("il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "l'"),
    "spa": ("el", "la", "los", "las", "un", "una", "unos", "unas"),
    "dut": ("de", "het", "een"),
    "por": ("o", "a", "os", "as", "um", "uma"),
    "swe": ("den", "det", "en", "ett"),
    "dan": ("den", "det", "en", "et"),
    "nor": ("den", "det", "en", "et"),
}

#: Mapping of the language tags typically found in LIDO to ISO 639-2/B.
LANGUAGE_TAGS = {
    "de": "ger",
    "deu": "ger",
    "ger": "ger",
    "en": "eng",
    "eng": "eng",
    "fr": "fre",
    "fra": "fre",
    "fre": "fre",
    "it": "ita",
    "ita": "ita",
    "es": "spa",
    "spa": "spa",
    "nl": "dut",
    "dut": "dut",
    "nld": "dut",
    "pt": "por",
    "por": "por",
    "sv": "swe",
    "swe": "swe",
    "da": "dan",
    "dan": "dan",
    "no": "nor",
    "nor": "nor",
}


class NormalisationError(ValueError):
    """Raised when a value cannot be mapped to a schema compliant form."""


def language_code(tag: str | None) -> str | None:
    """Return the ISO 639-2/B code for an xml:lang tag, if known."""
    if not tag:
        return None
    return LANGUAGE_TAGS.get(tag.strip().lower().split("-")[0])


def normalise_date(
    value: str | None,
    *,
    record_id: str | None = None,
    source_field: str = "eventDate",
    target_field: str = "has_event.has_date",
) -> str | None:
    """Return ``value`` as an AVefi ISODate, or None if there is none.

    Handles the abbreviated intervals common in film holdings data,
    such as ``1962-65`` for ``1962/1965``, as well as decade and
    approximation expressions. Anything that cannot be mapped
    unambiguously raises :class:`NormalisationError` — it must not be
    guessed, and it must not be dropped silently either.

    Parameters
    ----------
    value : str or None
        Date expression as found in the source data.
    record_id : str or None
        Identifier used when reporting an unconvertible value.
    source_field, target_field : str
        Field names used when reporting an unconvertible value.

    Returns
    -------
    str or None
        A value matching the ISODate pattern, or None when the source
        explicitly states that no date is known.

    Raises
    ------
    NormalisationError
        When the value is neither empty nor unambiguously mappable.

    """
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if text.lower() in EMPTY_DATE_VALUES:
        if text:
            report_issue(
                "info",
                "Source states that no date is known",
                record_id=record_id,
                source_field=source_field,
                target_field=target_field,
                raw_value=value,
            )
        return None

    approximate = False
    lowered = text.lower()
    for prefix in CIRCA_PREFIXES:
        if lowered.startswith(f"{prefix} "):
            approximate = True
            text = text[len(prefix) :].strip()
            break
    if text.endswith("?"):
        text = text[:-1].strip()
        suffix = "?"
    else:
        suffix = "~" if approximate else ""

    result = _map_date_expression(text)
    if result is None:
        raise NormalisationError(
            f"Unable to map date expression to ISODate: {value!r}"
        )
    if suffix:
        result = "/".join(f"{part}{suffix}" for part in result.split("/"))
    if not ISO_DATE_PATTERN.match(result):
        raise NormalisationError(
            f"Mapped date {result!r} does not comply with ISODate"
            f" (source: {value!r})"
        )
    return result


#: Expressions that could be read as an ISO year-month or as an
#: abbreviated interval, e.g. "2003-04" for April 2003 or 2003 to 2004.
AMBIGUOUS_PATTERN = re.compile(r"^(\d{2})\d{2}-(0[1-9]|1[0-2])$")


def _map_date_expression(text: str) -> str | None:
    """Return the ISODate body for ``text`` without any qualifier."""
    # Already an ISO date or period
    if ISO_DATE_PATTERN.match(text):
        if AMBIGUOUS_PATTERN.match(text):
            report_issue(
                "info",
                "Ambiguous date read as ISO year and month, not as an"
                " abbreviated interval",
                source_field="eventDate",
                target_field="has_event.has_date",
                raw_value=text,
            )
        return text

    # Decades: "50er Jahre", "1950er", "1950er Jahre"
    match = re.match(r"^(\d{2}|\d{4})\s*er(\s+Jahre)?$", text, re.IGNORECASE)
    if match:
        digits = match.group(1)
        start = int(digits) if len(digits) == 4 else 1900 + int(digits)
        return f"{start:04d}/{start + 9:04d}"

    # Abbreviated interval: "1962-65", "1962/65"
    match = re.match(r"^(\d{2})(\d{2})\s*[-/]\s*(\d{2})$", text)
    if match:
        century, start, end = match.groups()
        end_year = int(f"{century}{end}")
        if end_year < int(f"{century}{start}"):
            end_year += 100
        return f"{century}{start}/{end_year:04d}"

    # Full interval: "1962-1965", "1962/1965"
    match = re.match(r"^(\d{4})\s*[-/]\s*(\d{4})$", text)
    if match:
        start, end = match.groups()
        if int(end) < int(start):
            return None
        return f"{start}/{end}"

    # German day and month: "15.03.1962", "03.1962"
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    match = re.match(r"^(\d{1,2})\.(\d{4})$", text)
    if match:
        month, year = match.groups()
        return f"{year}-{int(month):02d}"

    # Bare year
    if re.match(r"^\d{4}$", text):
        return text
    return None


def normalise_duration(
    value: str | None,
    unit: str | None = None,
    *,
    record_id: str | None = None,
    source_field: str = "measurementsSet",
    target_field: str = "has_duration.has_value",
) -> str | None:
    """Return ``value`` as an AVefi ISODurationInHours.

    Accepts the notations found in holdings data: a plain number with a
    unit, ``HH:MM:SS`` and ``MM:SS`` clock notation, and expressions
    such as ``103 min`` or ``1 h 43``.

    Returns
    -------
    str or None
        A value of the form ``PT01H43M00S``, or None when no duration
        is given.

    Raises
    ------
    NormalisationError
        When the value cannot be interpreted.

    """
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None

    seconds = _duration_seconds(text, unit)
    if seconds is None:
        raise NormalisationError(
            f"Unable to map duration to ISODurationInHours: {value!r}"
            f"{f' (unit {unit!r})' if unit else ''}"
        )
    if seconds < 0:
        raise NormalisationError(f"Negative duration: {value!r}")
    hours, rest = divmod(int(round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    result = f"PT{hours:02d}H{minutes:02d}M{secs:02d}S"
    if not ISO_DURATION_PATTERN.match(result):
        raise NormalisationError(
            f"Mapped duration {result!r} does not comply with"
            f" ISODurationInHours (source: {value!r})"
        )
    if record_id is not None and hours > 24:
        report_issue(
            "warning",
            "Implausibly long duration",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )
    return result


def _duration_seconds(text: str, unit: str | None) -> float | None:
    """Return the number of seconds expressed by ``text``."""
    # Clock notation
    match = re.match(r"^(\d+):([0-5]?\d)(?::([0-5]?\d))?$", text)
    if match:
        first, second, third = match.groups()
        if third is None:
            # Ambiguous by nature; holdings data uses MM:SS here.
            return int(first) * 60 + int(second)
        return int(first) * 3600 + int(second) * 60 + int(third)

    # "1 h 43 min", "1h43"
    match = re.match(
        r"^(\d+)\s*(?:h|std\.?|stunden?)\s*(\d+)?\s*(?:min\.?|m)?$",
        text,
        re.IGNORECASE,
    )
    if match:
        hours, minutes = match.groups()
        return int(hours) * 3600 + int(minutes or 0) * 60

    # Number with an explicit or supplied unit
    match = re.match(r"^(\d+(?:[.,]\d+)?)\s*([a-zA-Zäöü.']*)$", text)
    if not match:
        return None
    amount = float(match.group(1).replace(",", "."))
    given_unit = (match.group(2) or unit or "").strip().lower().rstrip(".")
    factor = {
        "": 60,  # holdings data states running time in minutes
        "s": 1,
        "sec": 1,
        "secs": 1,
        "sek": 1,
        "sekunde": 1,
        "sekunden": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minuten": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "std": 3600,
        "stunde": 3600,
        "stunden": 3600,
        "hour": 3600,
        "hours": 3600,
    }.get(given_unit)
    if factor is None:
        return None
    return amount * factor


def normalise_title(
    value: str,
    language: str | None = None,
    *,
    articles: dict[str, tuple[str, ...]] | None = None,
) -> tuple[str, str | None]:
    """Return display name and ordering name for a title.

    Two directions are supported, as agreed in the commission:

    * a leading article yields an ordering name with the article moved
      to the back (``Die Brücke`` → ``Brücke, Die``);
    * a title supplied with a trailing article yields a display name
      with the article moved to the front, keeping the original as the
      ordering name (``Brücke, Die`` → ``Die Brücke``).

    Parameters
    ----------
    value : str
        Title as found in the source data.
    language : str or None
        ISO 639-2/B code selecting the article list.
    articles : dict, optional
        Article lists to use instead of :data:`ARTICLES`.

    Returns
    -------
    tuple(str, str or None)
        Display name and ordering name; the latter is None when the
        title needs no reordering.

    """
    articles = ARTICLES if articles is None else articles
    display = re.sub(r"\s+", " ", value).strip()
    if not display:
        raise NormalisationError("Cannot build a title from an empty value")

    if language:
        known = articles.get(language)
        if known is None:
            # Guessing an article list from another language would
            # silently corrupt the title, so leave it alone and say so.
            report_issue(
                "info",
                "No article list configured for this language, ordering"
                " name left unset",
                source_field="appellationValue/@xml:lang",
                target_field="has_ordering_name",
                raw_value=language,
            )
            return display, None
    else:
        known = tuple({a for entry in articles.values() for a in entry})

    # Trailing article: "Brücke, Die"
    match = re.match(r"^(?P<main>.+?),\s*(?P<article>[^\s,]+)$", display)
    if (
        match
        and match.group("article").lower() in known
        and _sortable(match.group("main"))
    ):
        article = match.group("article")
        main = match.group("main")
        separator = "" if article.endswith("'") else " "
        return f"{article}{separator}{main}", display

    # Leading article: "Die Brücke"
    parts = display.split(maxsplit=1)
    if len(parts) == 2:
        first, rest = parts
        if first.lower() in known and _sortable(rest):
            return display, f"{rest}, {first}"
    match = re.match(r"^([A-Za-zÀ-ÿ]+')(\S.*)$", display)
    if match and match.group(1).lower() in known and _sortable(match.group(2)):
        return display, f"{match.group(2)}, {match.group(1)}"

    return display, None


def _sortable(text: str) -> bool:
    """Return True if ``text`` can start an ordering name.

    Moving an article to the back only makes sense when what remains
    begins with something sortable. A title such as "den ,0" must be
    left alone: reordering it would yield ",0, den", which sorts before
    every real title.

    """
    stripped = text.strip()
    return bool(stripped) and stripped[0].isalnum()
