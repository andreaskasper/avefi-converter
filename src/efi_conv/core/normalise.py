"""Normalisation routines shared by all converters.

The rules implemented here are the ones agreed for the conversion of
holdings metadata to the AVefi schema. They are deliberately kept free
of any parsing of a particular source schema, so that every converter
produces the same AVefi value for the same source expression and so
that the rules can be unit tested in isolation.

"""

import re

from .report import report_issue

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

#: Pattern for an ISO 8601 duration, which is what this module emits
#: and therefore what a source that has already been converted once
#: hands back. Years and months are refused: they say nothing about a
#: running time. A fractional value is accepted and rounded, as
#: everywhere else here.
ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?!$)(?:(?P<days>\d+(?:[.,]\d+)?)D)?"
    r"(?:T(?!$)(?:(?P<hours>\d+(?:[.,]\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:[.,]\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:[.,]\d+)?)S)?)?$",
    re.IGNORECASE,
)

#: Longest span an abbreviated interval such as ``1962-65`` may
#: denote. Beyond it the second number is far more likely to be a
#: mistyped month than the end of a production period: ``1959-13``
#: would otherwise be read as 1959 to 2013 and asserted as fact. An
#: interval that really is longer is written with four digit years,
#: which is read as given.
MAX_ABBREVIATED_INTERVAL_YEARS = 20

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

#: Mapping of the language tags found in the source schemas to
#: ISO 639-2/B, which is what the AVefi schema expects.
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


#: Expressions naming a decade, e.g. "50er Jahre" or "1950er".
DECADE_PATTERN = re.compile(r"^(\d{2}|\d{4})\s*er(\s+Jahre)?$", re.I)

#: A span from a year to the end of a decade, e.g. "1940-1950er Jahre".
DECADE_SPAN_PATTERN = re.compile(
    r"^(\d{4})\s*[-/]\s*(\d{2}|\d{4})\s*er(\s+Jahre)?$", re.I
)

#: A circa marker in front of a date. Providers write these in German,
#: in English, and in both at once: "ca./ c. 1982" occurs forty times
#: in one export, and used to be unconvertible because the check was
#: for a single prefix followed by a space.
CIRCA_PATTERN = re.compile(
    # "c." only with its full stop: a bare "c" would swallow the
    # first letter of anything.
    r"^(?:ca\.?|c\.|circa|um|about|approx\.?|etwa)"
    r"(?:\s*[/,]\s*(?:c\.?|ca\.?|circa|about|etwa))?"
    r"[\s.]+",
    re.I,
)

#: A question mark in brackets behind a date, "1960 (?)". The bare
#: trailing question mark was already read as the uncertainty
#: qualifier; this is the same statement with different punctuation,
#: and the more common one in the reference data.
BRACKETED_QUERY_PATTERN = re.compile(r"\s*\(\s*\?\s*\)$")

#: Month names as cataloguers write them, mapped to their number.
#: German and English, full and abbreviated, because a holdings
#: database collects both over the decades.
MONTH_NAMES = {
    "januar": 1,
    "jan": 1,
    "january": 1,
    "februar": 2,
    "feb": 2,
    "february": 2,
    "maerz": 3,
    "märz": 3,
    "mrz": 3,
    "mar": 3,
    "march": 3,
    "april": 4,
    "apr": 4,
    "mai": 5,
    "may": 5,
    "juni": 6,
    "jun": 6,
    "june": 6,
    "juli": 7,
    "jul": 7,
    "july": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "oktober": 10,
    "okt": 10,
    "oct": 10,
    "october": 10,
    "november": 11,
    "nov": 11,
    "dezember": 12,
    "dez": 12,
    "dec": 12,
    "december": 12,
}


def decade_to_period(text: str) -> str | None:
    """Return the closed interval a decade expression denotes.

    Not applied by default. The contract requires decade expressions to
    be reported as unconvertible first and to be mapped only once the
    client has agreed on a representation, so this is opt in through
    ``map_decades`` in the converter profile.

    """
    text = text.strip()
    span = DECADE_SPAN_PATTERN.match(text)
    if span:
        # "1940-1950er Jahre": from a stated year to the end of a
        # stated decade. Reading the second half as a plain year would
        # end the interval nine years too early.
        start = int(span.group(1))
        end = _decade_start(span.group(2)) + 9
        if end < start:
            return None
        return f"{start:04d}/{end:04d}"
    match = DECADE_PATTERN.match(text)
    if not match:
        return None
    start = _decade_start(match.group(1))
    return f"{start:04d}/{start + 9:04d}"


def _decade_start(digits: str) -> int:
    """Return the first year of a decade written with two or four digits.

    Two digit decades are read as twentieth century, which is an
    assumption that needs confirming against the reference data.

    """
    return int(digits) if len(digits) == 4 else 1900 + int(digits)


def normalise_date(
    value: str | None,
    *,
    record_id: str | None = None,
    source_field: str = "eventDate",
    target_field: str = "has_event.has_date",
    map_decades: bool = False,
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
    if text and set(text) <= {"?", " "}:
        # A single question mark already stands for "no date given".
        # Cataloguing systems produce runs of them, up to fifty six in
        # one field of the reference data, where a fixed width column
        # was filled with the same placeholder. That is the same
        # statement typed repeatedly, not a different one.
        text = "?"
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

    if text.startswith("[") and text.endswith("]"):
        # Square brackets mark a date the cataloguer supplied rather
        # than read off the object. That says where the date came
        # from, not how sure anybody is of it, so the brackets are
        # dropped and the date is taken as stated.
        text = text[1:-1].strip()
        report_issue(
            "info",
            "Date was supplied by the cataloguer; brackets dropped",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )

    stripped = CIRCA_PATTERN.sub("", text, count=1)
    approximate = stripped != text
    text = stripped.strip()

    text_without_query = BRACKETED_QUERY_PATTERN.sub("", text)
    if text_without_query != text:
        text = text_without_query.strip()
        suffix = "?"
    elif text.endswith("?"):
        text = text[:-1].strip()
        suffix = "?"
    else:
        suffix = "~" if approximate else ""

    result = _map_date_expression(text, record_id=record_id)
    if result is None and (
        DECADE_PATTERN.match(text) or DECADE_SPAN_PATTERN.match(text)
    ):
        if not map_decades:
            # Reported by the caller, which knows whether the value is
            # being dropped or the whole record; saying it twice with
            # two severities would only make the report harder to read.
            raise NormalisationError(
                f"Decade expression needs an agreed representation:"
                f" {value!r}. Enable map_decades in the profile to read"
                f" it as a closed interval"
            )
        result = decade_to_period(text)
        report_issue(
            "info",
            "Decade expression mapped to a closed interval as agreed",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )
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


#: Words that join the two ends of an interval, "1970 bis 1977" or
#: "zwischen 1940 und 1945". Wording, not interpretation: the value is
#: the same interval a hyphen would have written.
INTERVAL_WORDS_PATTERN = re.compile(r"(?<=\d)\s+(?:bis|und|to)\s+(?=\d)", re.I)
INTERVAL_OPENER_PATTERN = re.compile(
    r"^(?:zwischen|between|von|from)\s+(?=\d)", re.I
)


def _map_date_expression(
    text: str, record_id: str | None = None
) -> str | None:
    """Return the ISODate body for ``text`` without any qualifier."""
    text = INTERVAL_OPENER_PATTERN.sub("", text)
    text = INTERVAL_WORDS_PATTERN.sub("/", text)
    # Already an ISO date or period
    if ISO_DATE_PATTERN.match(text):
        if AMBIGUOUS_PATTERN.match(text):
            report_issue(
                "info",
                "Ambiguous date read as ISO year and month, not as an"
                " abbreviated interval; note that fmdu/csv.py reads the"
                " same notation as an interval",
                record_id=record_id,
                source_field="eventDate",
                target_field="has_event.has_date",
                raw_value=text,
            )
        return text

    # Abbreviated interval: "1962-65", "1962/65"
    match = re.match(r"^(\d{2})(\d{2})\s*[-/]\s*(\d{2})$", text)
    if match:
        century, start, end = match.groups()
        start_year = int(f"{century}{start}")
        end_year = int(f"{century}{end}")
        if end_year < start_year:
            end_year += 100
        if end_year - start_year > MAX_ABBREVIATED_INTERVAL_YEARS:
            raise NormalisationError(
                f"Refusing to read {text!r} as the interval"
                f" {start_year}/{end_year}: a span of"
                f" {end_year - start_year} years is far more likely to"
                f" be a mistyped month. Write the interval with four"
                f" digit years if it is meant as given."
            )
        return f"{start_year:04d}/{end_year:04d}"

    # Full interval: "1962-1965", "1962/1965"
    match = re.match(r"^(\d{4})\s*[-/]\s*(\d{4})$", text)
    if match:
        start, end = match.groups()
        if int(end) < int(start):
            return None
        return f"{start}/{end}"

    # Month by name: "Juni 1980", "Jan 1979", "1980 Juni"
    match = re.match(r"^([^\W\d_]+)\.?\s+(\d{4})$", text, re.UNICODE)
    if match:
        month = MONTH_NAMES.get(match.group(1).lower())
        if month:
            return f"{match.group(2)}-{month:02d}"
    match = re.match(r"^(\d{4})\s+([^\W\d_]+)\.?$", text, re.UNICODE)
    if match:
        month = MONTH_NAMES.get(match.group(2).lower())
        if month:
            return f"{match.group(1)}-{month:02d}"

    # Month and year with a slash: "8/1988". The slash is the interval
    # separator in ISODate, so this is only read as a month where the
    # left hand side cannot be a year and the right hand side is one.
    match = re.match(r"^(0?[1-9]|1[0-2])\s*/\s*(\d{4})$", text)
    if match:
        return f"{match.group(2)}-{int(match.group(1)):02d}"

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
    if round(seconds) == 0:
        # A running time of zero is not a running time. Recording it
        # as PT00H00M00S would state that the copy runs no length,
        # where the source states that nobody measured it.
        report_issue(
            "info",
            "Running time is zero; read as not recorded",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )
        return None
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
    # ISO 8601, the form this module emits itself. EFG duration and
    # PBCore instantiationDuration are free text, so a value that has
    # been through a conversion once turns up here again.
    match = ISO_8601_DURATION_PATTERN.match(text)
    if match and any(match.groups()):
        return (
            _number(match.group("days")) * 86400
            + _number(match.group("hours")) * 3600
            + _number(match.group("minutes")) * 60
            + _number(match.group("seconds"))
        )

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
    # The exponent is not decoration: a cataloguing system writing
    # "0E-10" into a measurement column means the field is empty, and
    # 1084 records of one export say it that way.
    match = re.match(
        r"^(\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)\s*([a-zA-Zäöü.']*)$", text
    )
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


def _number(value: str | None) -> float:
    """Return a duration component as a number, 0 when absent."""
    if not value:
        return 0.0
    return float(value.replace(",", "."))


def mapped_duration(
    value: str | None,
    unit: str | None = None,
    *,
    record_id: str | None = None,
    source_field: str = "measurementsSet",
    target_field: str = "has_duration.has_value",
) -> str | None:
    """Return the duration of a copy, or None if it cannot be read.

    Every converter reads a running time from free text, and every one
    of them has to decide what an unreadable value costs. Discarding
    the record would cost the work, every manifestation and every item
    derived from it, and with them everything the source says about
    the film; leaving ``has_duration`` unset costs one field. The
    field is therefore dropped and reported, and the record is kept.

    """
    try:
        return normalise_duration(
            value,
            unit,
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
        )
    except NormalisationError as e:
        report_issue(
            "warning",
            f"{e}; the running time is not transferred",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )
        return None


def mapped_date(
    value: str | None,
    *,
    record_id: str | None = None,
    source_field: str = "eventDate",
    target_field: str = "has_event.has_date",
    map_decades: bool = False,
) -> str | None:
    """Return the date of an event, or None if it cannot be read.

    The counterpart of :func:`mapped_duration`, and for the same
    reason. A date expression nobody can read is a fact about one
    field, not about the record it sits in: the title, the carrier,
    the identifiers and the copy itself are all still there and all
    still true. Discarding the record over it would cost the work,
    every manifestation and every item derived from it.

    ``has_date`` is optional in the AVefi schema, so a film without a
    production date is a valid record rather than a broken one. The
    value is therefore dropped and reported, and the record is kept.
    What must not happen is that it disappears quietly, which is why
    this reports before returning.

    """
    try:
        return normalise_date(
            value,
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            map_decades=map_decades,
        )
    except NormalisationError as e:
        report_issue(
            "warning",
            f"{e}; the date is not transferred",
            record_id=record_id,
            source_field=source_field,
            target_field=target_field,
            raw_value=value,
        )
        return None


def normalise_title(
    value: str,
    language: str | None = None,
    *,
    articles: dict[str, tuple[str, ...]] | None = None,
    record_id: str | None = None,
    target_field: str = "has_ordering_name",
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
                record_id=record_id,
                source_field="appellationValue/@xml:lang",
                target_field=target_field,
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
