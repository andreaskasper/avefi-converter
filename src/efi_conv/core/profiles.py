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
quietly lose every value it was meant to map.

"""

from dataclasses import dataclass, fields
import json
import logging
import pathlib
import tomllib
import types

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
        or it does not supply the issuer.

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
    issuer_info = settings.get("issuer_info")
    if not isinstance(issuer_info, dict) or not issuer_info.get(
        "has_issuer_id"
    ):
        raise ProfileError(
            "Profile must supply an issuer with has_issuer_id and"
            " has_issuer_name"
        )
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

    def efi_import(self, input_file, continue_on_error: bool = False):
        """Convert ``input_file`` using the configured profile."""
        return self.module.convert(input_file, self.profile, continue_on_error)


def configure(module: types.ModuleType, path) -> ConfiguredImporter:
    """Return ``module`` bound to the profile stored at ``path``.

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
        log.warning(
            f"Profile {path} declares format '{declared}' but is being"
            f" used with '{expected}'"
        )
    profile = build_profile(document, profile_class)
    log.info(
        f"Configured {expected} from {path}"
        f" for issuer {profile.issuer_info.get('has_issuer_id')}"
    )
    return ConfiguredImporter(module, profile, str(path))
