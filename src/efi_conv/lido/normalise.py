"""Normalisation routines, re-exported for the LIDO converter.

The routines moved to :mod:`efi_conv.core.normalise` when converters
for further source schemas were added: date, duration and title
normalisation is not a LIDO concern, and every converter has to arrive
at the same AVefi value for the same source expression.

This module stays as the import path the LIDO converter and its tests
have always used.

"""

from ..core.normalise import (
    ARTICLES,
    CIRCA_PREFIXES,
    DECADE_PATTERN,
    EMPTY_DATE_VALUES,
    ISO_DATE_PATTERN,
    ISO_DURATION_PATTERN,
    LANGUAGE_TAGS,
    NormalisationError,
    decade_to_period,
    language_code,
    normalise_date,
    normalise_duration,
    normalise_title,
)

__all__ = (
    "ARTICLES",
    "CIRCA_PREFIXES",
    "DECADE_PATTERN",
    "EMPTY_DATE_VALUES",
    "ISO_DATE_PATTERN",
    "ISO_DURATION_PATTERN",
    "LANGUAGE_TAGS",
    "NormalisationError",
    "decade_to_period",
    "language_code",
    "normalise_date",
    "normalise_duration",
    "normalise_title",
)
