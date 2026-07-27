"""Building blocks shared by every converter.

The AVefi schema, not the source schema, decides how records are
identified, how a work is shared between the copies describing it and
how titles are represented. Those decisions therefore belong here
rather than in the individual converters, so that two converters
cannot quietly arrive at different answers.

"""

from dataclasses import dataclass, field
import hashlib
import re

from avefi_schema import model_pydantic_v2 as efi

from .utils import described_by_issuer

#: Identifiers longer than this are shortened and given a digest, so
#: that they stay usable while remaining unique and reproducible.
MAX_SLUG_LENGTH = 120

#: Separator between the parts of a grouping key. Chosen so that it
#: cannot occur inside a normalised title or date.
KEY_SEPARATOR = "__"


def slug(value: str) -> str:
    """Return a compact, stable identifier fragment for ``value``."""
    cleaned = re.sub(r"\s+", "_", value.strip())
    cleaned = re.sub(r"[^\w.:/-]", "", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip("_")
    if len(cleaned) <= MAX_SLUG_LENGTH:
        return cleaned or "record"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{cleaned[:100]}_{digest}"


def make_key(*parts) -> str:
    """Return a grouping key from ``parts``."""
    return KEY_SEPARATOR.join(
        "" if part is None else str(part) for part in parts
    )


@dataclass(frozen=True)
class SourceTitle:
    """A title as found in the source document.

    Attributes
    ----------
    display : str
        The title as it is to be shown.
    ordering : str or None
        The title with a leading article moved to the end, if the
        language is known and the title carries one.
    supplied : bool
        The title was supplied by the cataloguer rather than taken from
        the film itself, which the source data marks with brackets.

    """

    display: str
    ordering: str | None = None
    supplied: bool = False


def as_title(title: SourceTitle, type_hint: str) -> efi.Title:
    """Return an AVefi title for a parsed source title."""
    title_type = "SuppliedDevisedTitle" if title.supplied else type_hint
    result = efi.Title(
        type=efi.TitleTypeEnum(title_type), has_name=title.display
    )
    if title.ordering:
        result.has_ordering_name = title.ordering
    return result


def merge_alternative_titles(work, alternatives):
    """Add the titles a further record contributes to a known work."""
    known = {title.has_name for title in work.has_alternative_title}
    for title in alternatives:
        if title.display not in known:
            work.has_alternative_title.append(
                as_title(title, "AlternativeTitle")
            )
            known.add(title.display)


@dataclass
class GroupingContext:
    """Works and manifestations shared across the records of a run.

    Several source records commonly describe several copies of the
    same film. Minting a separate work for each of them would defeat
    the purpose of the AVefi identifiers, so a converter looks a work
    or manifestation up by its key and only creates one when it has
    not seen that key before.

    """

    works: dict = field(default_factory=dict)
    manifestations: dict = field(default_factory=dict)

    def work_for(self, key: str, factory):
        """Return the work for ``key``, creating it if it is new.

        Returns
        -------
        tuple
            The work and whether it was created by this call.

        """
        work = self.works.get(key)
        if work is not None:
            return work, False
        work = factory()
        work.has_identifier.append(efi.LocalResource(id=f"{slug(key)}_work"))
        self.works[key] = work
        return work, True

    def manifestation_for(self, key: str, factory):
        """Return the manifestation for ``key``, creating it if new.

        Returns
        -------
        tuple
            The manifestation and whether it was created by this call.

        """
        manifestation = self.manifestations.get(key)
        if manifestation is not None:
            return manifestation, False
        manifestation = factory()
        manifestation.has_identifier.append(
            efi.LocalResource(id=f"{slug(key)}_manifestation")
        )
        self.manifestations[key] = manifestation
        return manifestation, True


def attach_source_key(records, issuer_info: dict, source_key: str):
    """Record which source record a set of AVefi records came from.

    Called for every source record, including the ones that only
    contribute a further copy to a known work, so that the provenance
    of a shared work lists all of them.

    """
    for record in records:
        described_by = described_by_issuer(record, issuer_info)
        if described_by.has_source_key is None:
            described_by.has_source_key = []
        if source_key not in described_by.has_source_key:
            described_by.has_source_key.append(source_key)
