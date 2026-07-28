"""Mapping profiles loaded from a file.

A profile is everything that differs between data providers: the
issuer, the house vocabularies, the terms marking an event or a role.
Each converter already carries one as a dataclass, so that a new
provider needs a profile rather than a converter. What this module
adds is the ability to supply that profile as a file at run time.

That matters for two reasons. A conversion agreed once with a provider
has to be repeatable, unattended, for every later delivery, without
anybody opening a tool and clicking through it again. And the generic
format converters ship with a placeholder issuer on purpose, because
inventing an ISIL for somebody else's collection is not a decision a
converter gets to take; a profile is where the real one comes from.

The document is JSON or TOML::

    {
        "profile_format_version": "1.0",
        "format": "lido",
        "description": "Filmarchiv Musterstadt, delivery 2026-07",
        "issuer": {
            "has_issuer_id": "https://w3id.org/isil/DE-MUS-000000",
            "has_issuer_name": "Filmarchiv Musterstadt",
        },
        "settings": {
            "default_language": "ger",
            "colour_type_map": {"sw": "BlackAndWhite"},
        },
    }

Anything under ``settings`` names a field of that converter's profile
class. An unknown name is an error rather than something to ignore: a
misspelt vocabulary would otherwise look like a working profile and
quietly lose every value it was meant to map. So is a value of the
wrong type, for the same reason: a vocabulary written as an array
rather than as a table maps nothing, and the conversion only finds out
about it somewhere in the middle of a file.

"""

from dataclasses import dataclass, fields
import json
import logging
import pathlib
import tomllib
import types
import typing
import urllib.parse

log = logging.getLogger(__name__)

#: Version of the profile document format understood here.
PROFILE_FORMAT_VERSION = "1.0"

#: Suffixes and the loader for each.
LOADERS = {
    ".json": "json",
    ".toml": "toml",
}

ENCODING = "utf-8"

#: Issuer the generic format converters ship with. A converter cannot
#: know whose collection it is being pointed at, and inventing an ISIL
#: for somebody else's holdings is not its decision to take, so it says
#: so instead of guessing. A profile supplies the real one.
PLACEHOLDER_ISSUER_ID = "https://w3id.org/avefi/issuer/unspecified"


def needs_a_profile(module) -> bool:
    """Return True if the converter ships without a usable issuer."""
    issuer = getattr(module, "ISSUER_INFO", None) or {}
    return issuer.get("has_issuer_id") == PLACEHOLDER_ISSUER_ID


class ProfileError(ValueError):
    """Raised when a profile document cannot be used as given."""


def load_profile_document(path) -> dict:
    """Return the profile document at ``path``.

    Parameters
    ----------
    path
        File with a suffix of ``.json`` or ``.toml``.

    Raises
    ------
    ProfileError
        The suffix is unknown, the file does not parse, or it does not
        contain a mapping at the top level.

    """
    source = pathlib.Path(path)
    kind = LOADERS.get(source.suffix.lower())
    if kind is None:
        raise ProfileError(
            f"Cannot tell the format of {source} from its suffix,"
            f" expected one of {', '.join(sorted(LOADERS))}"
        )
    try:
        if kind == "toml":
            with source.open("rb") as f:
                document = tomllib.load(f)
        else:
            with source.open(encoding=ENCODING) as f:
                document = json.load(f)
    except (OSError, ValueError) as e:
        raise ProfileError(f"Cannot read profile {source}: {e}") from e
    if not isinstance(document, dict):
        raise ProfileError(
            f"Profile {source} does not contain a mapping at the top level"
        )
    version = document.get("profile_format_version")
    if version is not None and str(version) != PROFILE_FORMAT_VERSION:
        raise ProfileError(
            f"Profile {source} declares format version {version},"
            f" this version of efi-conv understands"
            f" {PROFILE_FORMAT_VERSION}"
        )
    return document


#: What a declared profile field accepts in a profile document, and
#: how to name it in a message. Neither JSON nor TOML has a set or a
#: tuple, so every collection arrives as an array whatever the
#: dataclass declares.
TYPE_EXPECTATIONS = {
    "dict": ((dict,), "a table"),
    "frozenset": ((list, tuple, set, frozenset), "an array"),
    "set": ((list, tuple, set, frozenset), "an array"),
    "tuple": ((list, tuple), "an array"),
    "list": ((list, tuple), "an array"),
    "str": ((str,), "a string"),
    "bool": ((bool,), "true or false"),
    "int": ((int,), "an integer"),
    "float": ((int, float), "a number"),
    "NoneType": ((type(None),), "null"),
}

#: How to name what a profile document actually supplied.
VALUE_NAMES = {
    "dict": "a table",
    "list": "an array",
    "tuple": "an array",
    "set": "an array",
    "str": "a string",
    "bool": "true or false",
    "int": "an integer",
    "float": "a number",
    "NoneType": "null",
}

#: Longest value shown in an error message. A vocabulary of several
#: hundred terms says nothing useful once it is on the screen.
MAX_SHOWN_VALUE = 120

#: What a profile has to state about the issuer.
REQUIRED_ISSUER_KEYS = ("has_issuer_id", "has_issuer_name")


def describe_value(value) -> str:
    """Return how to name ``value`` in a message."""
    name = type(value).__name__
    return VALUE_NAMES.get(name, f"a {name}")


def show_value(value) -> str:
    """Return ``value`` rendered short enough to read in a message."""
    shown = repr(value)
    if len(shown) > MAX_SHOWN_VALUE:
        shown = f"{shown[: MAX_SHOWN_VALUE - 3]}..."
    return shown


def type_expectation(field_type):
    """Return what a field declared as ``field_type`` accepts.

    Parameters
    ----------
    field_type
        The annotation the profile dataclass declares the field with.

    Returns
    -------
    tuple or None
        The acceptable Python types and how to name them, or None for
        an annotation this module has no rule for. An unusual
        annotation is passed through rather than refused, because
        refusing a value the converter would have accepted is worse
        than not checking it.

    """
    origin = typing.get_origin(field_type)
    if origin in (typing.Union, types.UnionType):
        accepted = ()
        names = []
        for argument in typing.get_args(field_type):
            expectation = type_expectation(argument)
            if expectation is None:
                return None
            accepted += expectation[0]
            names.append(expectation[1])
        return accepted, " or ".join(dict.fromkeys(names))
    if origin is not None:
        field_type = origin
    if isinstance(field_type, str):
        # Annotations are objects here, but a converter written with
        # `from __future__ import annotations` would deliver strings.
        parts = [part.strip() for part in field_type.split("|")]
        expectations = [TYPE_EXPECTATIONS.get(part) for part in parts]
        if any(expectation is None for expectation in expectations):
            return None
        accepted = ()
        for expectation in expectations:
            accepted += expectation[0]
        return accepted, " or ".join(
            dict.fromkeys(expectation[1] for expectation in expectations)
        )
    return TYPE_EXPECTATIONS.get(getattr(field_type, "__name__", ""))


def check_setting_type(name: str, value, field_type, profile_class):
    """Refuse a setting whose value is not of the declared type.

    Raises
    ------
    ProfileError
        The value cannot be turned into what the field is declared
        with. The message names the setting, what was given and what
        was expected, because that is what has to be corrected in the
        document.

    """
    expectation = type_expectation(field_type)
    if expectation is None:
        return
    accepted, expected = expectation
    acceptable = isinstance(value, accepted)
    if isinstance(value, bool) and bool not in accepted:
        # bool is a subclass of int, and true is not a number here.
        acceptable = False
    if acceptable:
        return
    raise ProfileError(
        f"Profile setting '{name}' of {profile_class.__name__} expects"
        f" {expected}, got {describe_value(value)}: {show_value(value)}"
    )


def check_issuer(issuer):
    """Refuse an issuer a conversion cannot be run with.

    Both keys are checked, not just the one that happens to be looked
    at first: ``described_by`` needs the name as much as the id, and a
    profile missing it fails in the middle of a conversion, as a
    pydantic error about a record rather than about the profile that
    caused it.

    Raises
    ------
    ProfileError
        The issuer is not a table, does not state both keys, or states
        an id that is not a URI.

    """
    if not isinstance(issuer, dict):
        raise ProfileError(
            f"Profile must supply an issuer with"
            f" {' and '.join(REQUIRED_ISSUER_KEYS)}, got"
            f" {describe_value(issuer)}: {show_value(issuer)}"
        )
    for key in REQUIRED_ISSUER_KEYS:
        value = issuer.get(key)
        if value is None:
            raise ProfileError(
                f"Profile issuer does not state {key};"
                f" {' and '.join(REQUIRED_ISSUER_KEYS)} are both"
                f" required"
            )
        if not isinstance(value, str):
            raise ProfileError(
                f"Profile issuer {key} must be a string, got"
                f" {describe_value(value)}: {show_value(value)}"
            )
        if not value.strip():
            raise ProfileError(f"Profile issuer {key} is empty")
    issuer_id = issuer["has_issuer_id"].strip()
    parsed = urllib.parse.urlsplit(issuer_id)
    if not parsed.scheme or not (parsed.netloc or parsed.path):
        raise ProfileError(
            f"Profile issuer has_issuer_id must be a URI, for instance"
            f" https://w3id.org/isil/DE-MUS-000000, got"
            f" {show_value(issuer_id)}"
        )


def coerce(value, field_type):
    """Return ``value`` as the type the profile field is declared with.

    JSON has no set and no tuple, so a vocabulary written as a list has
    to become the frozenset or tuple the dataclass expects, or two
    profiles that say the same thing would not behave the same way.

    """
    name = getattr(field_type, "__name__", str(field_type))
    if name == "frozenset" and isinstance(value, (list, tuple, set)):
        return frozenset(value)
    if name == "tuple" and isinstance(value, (list, tuple)):
        return tuple(value)
    if name == "set" and isinstance(value, (list, tuple, set)):
        return set(value)
    return value


def build_profile(document: dict, profile_class):
    """Return an instance of ``profile_class`` from a profile document.

    Values not named in the document keep the default the converter
    ships, so a profile only has to state what differs.

    Raises
    ------
    ProfileError
        The document names a setting the profile class does not have,
        gives one a value of the wrong type, or does not supply a
        usable issuer.

    """
    known = {field.name: field for field in fields(profile_class)}
    settings = dict(document.get("settings") or {})

    issuer = document.get("issuer")
    if issuer is not None:
        settings["issuer_info"] = issuer
    if "description" in document and "description" in known:
        settings.setdefault("description", document["description"])

    unknown = sorted(set(settings) - set(known))
    if unknown:
        raise ProfileError(
            f"Profile names {'settings' if len(unknown) > 1 else 'a setting'}"
            f" {profile_class.__name__} does not have:"
            f" {', '.join(unknown)}."
            f" Known settings: {', '.join(sorted(known))}"
        )
    if "issuer_info" not in settings:
        raise ProfileError(
            f"Profile must supply an issuer with"
            f" {' and '.join(REQUIRED_ISSUER_KEYS)}"
        )
    check_issuer(settings["issuer_info"])
    for name, value in settings.items():
        if name == "issuer_info":
            continue
        check_setting_type(name, value, known[name].type, profile_class)
    values = {
        name: coerce(value, known[name].type)
        for name, value in settings.items()
    }
    return profile_class(**values)


@dataclass(frozen=True)
class ConfiguredImporter:
    """A converter bound to a profile that was loaded from a file.

    Stands in for the converter module wherever one is expected. The
    module keeps its shipped defaults: configuring a conversion must
    not change what the next one does.

    """

    module: types.ModuleType
    profile: object
    source: str

    @property
    def DESCRIPTION(self) -> str:  # noqa: N802 - mirrors the module
        """Return the description of the configured conversion."""
        return getattr(self.profile, "description", None) or getattr(
            self.module, "DESCRIPTION", ""
        )

    @property
    def INPUT_FORMAT(self) -> str:  # noqa: N802 - mirrors the module
        """Return the input format of the underlying converter."""
        return getattr(self.module, "INPUT_FORMAT", "")

    @property
    def ISSUER_INFO(self) -> dict:  # noqa: N802 - mirrors the module
        """Return the issuer the profile names."""
        return dict(self.profile.issuer_info)

    def efi_import(
        self, input_file, continue_on_error: bool = False, context=None
    ):
        """Convert ``input_file`` using the configured profile."""
        return self.module.convert(
            input_file, self.profile, continue_on_error, context
        )

    def new_context(self):
        """Return a grouping context bound to the configured profile.

        A configured conversion groups the records of its input files
        exactly as an unconfigured one does; a profile decides what a
        source term means, not whether two files describing one film
        yield one work or two.

        """
        factory = getattr(self.module, "new_context", None)
        if factory is None:
            return None
        return factory(self.profile)


def configure(
    module: types.ModuleType,
    path,
    allow_format_mismatch: bool = False,
) -> ConfiguredImporter:
    """Return ``module`` bound to the profile stored at ``path``.

    Parameters
    ----------
    module
        The converter to configure.
    path
        Profile document, JSON or TOML.
    allow_format_mismatch : bool
        Use a profile written for another converter anyway. There is
        no good reason to, but somebody keeping two nearly identical
        deliveries in one file should be able to say so deliberately
        rather than be stopped.

    Raises
    ------
    ProfileError
        The converter does not take a profile, the document names the
        wrong converter, or it cannot be turned into one.

    """
    profile_class = getattr(module, "PROFILE_CLASS", None)
    if profile_class is None or not hasattr(module, "convert"):
        raise ProfileError(
            f"Converter {module.__name__} does not take a profile"
        )
    document = load_profile_document(path)
    declared = document.get("format")
    expected = module.__name__.removeprefix("efi_conv.")
    if declared is not None and declared != expected:
        message = (
            f"Profile {path} was written for the '{declared}' converter"
            f" but is being used with '{expected}'. The vocabularies of"
            f" a profile are the terms of one source schema and mean"
            f" nothing in another, so the issuer would be stamped on"
            f" records mapped by rules this profile was never checked"
            f" against. Convert with -f {declared}, correct the"
            f" 'format' key of the profile, or pass"
            f" --allow-profile-format-mismatch if you mean it."
        )
        if not allow_format_mismatch:
            raise ProfileError(message)
        log.warning(message)
    profile = build_profile(document, profile_class)
    log.info(
        f"Configured {expected} from {path}"
        f" for issuer {profile.issuer_info.get('has_issuer_id')}"
    )
    return ConfiguredImporter(module, profile, str(path))
