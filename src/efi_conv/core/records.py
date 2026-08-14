"""Building blocks shared by every converter.

The AVefi schema, not the source schema, decides how records are
identified, how a work is shared between the copies describing it and
how titles are represented. Those decisions therefore belong here
rather than in the individual converters, so that two converters
cannot quietly arrive at different answers.

"""

from contextlib import contextmanager
from dataclasses import dataclass, field, fields
import hashlib
import re

from avefi_schema import model_pydantic_v2 as efi

from .report import report_issue
from .utils import described_by_issuer

#: Identifiers longer than this are shortened and given a digest, so
#: that they stay usable while remaining unique and reproducible.
MAX_IDENTIFIER_LENGTH = 120

#: How much of an over-long value is kept in front of its digest.
KEPT_BEFORE_DIGEST = 100

#: Separator between the parts of a grouping key. Chosen so that it
#: cannot occur inside a normalised title or date.
KEY_SEPARATOR = "__"

#: The characters a minted identifier is allowed to consist of:
#: Unicode letters and digits, ``-``, ``.``, ``_`` and the ``~`` that
#: introduces a digest.
IDENTIFIER_PATTERN = re.compile(r"[\w.~-]+")

#: A run of characters no identifier may contain, replaced as a whole
#: by a single ``_``. That is everything but Unicode letters, digits,
#: ``-``, ``.`` and ``_``: the space and the URI syntax, from ``/``,
#: ``:``, ``#``, ``?``, ``&``, ``%``, ``=``, ``@``, ``+``, ``;``,
#: ``,`` by way of the quotes and brackets to the control characters,
#: and ``~``, which is reserved as the marker below.
REPLACED = re.compile(r"[^\w.-]+")

#: Separates the readable part of an identifier from the digest that
#: makes it unique, and doubled it separates a shortened value from
#: its digest. No value keeps it, so an identifier carrying no digest
#: cannot contain it and cannot be mistaken for one that does.
DIGEST_MARKER = "~"

#: How much of the digest of a substituted value is kept. Enough that
#: two values whose readable forms coincide do not.
DIGEST_LENGTH = 8

#: How much of the digest of an over-long value is kept.
LONG_DIGEST_LENGTH = 12

#: Identifier of a value that is empty once surrounding whitespace is
#: removed. Carries the marker without a digest behind it, which the
#: rules below cannot produce, so a record without a key cannot
#: borrow the identifier of a record that has one.
EMPTY_IDENTIFIER = f"{DIGEST_MARKER}record"


def _digest(value: str, length: int) -> str:
    """Return the leading ``length`` hexadecimal digits of a digest."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def local_identifier(value: str) -> str:
    """Return the identifier this tool mints for ``value``.

    An AVefi local identifier is not only a key inside the output
    file: a handle is registered for it, URIs are built from that
    handle, and people read it. An archivist reviewing a conversion, a
    developer debugging a mapping and the data provider checking what
    was registered for their collection all look at these strings, and
    German titles are the normal case here rather than an edge case.
    An identifier a German archivist cannot read is worse than one
    that needs encoding somewhere on the way out.

    Unicode letters and digits are therefore kept as they are: ``ü``,
    ``ä``, ``ß`` and ``é`` stay themselves. They are legal in a Handle
    System suffix and in an IRI. They are not legal in a URI, so
    whoever builds one percent-encodes them at that point, as a
    browser does when it displays an IRI; the same applies to a value
    put into an HTTP header or into a filename on a system that
    cannot spell them. Nothing downstream has to guess, because the
    identifier is a plain Unicode string.

    What a URI parser would read is replaced rather than kept: the
    space and ``/``, ``:``, ``#``, ``?``, ``&``, ``%``, ``=``, ``@``,
    ``+``, ``;``, ``,``, ``<``, ``>``, the quotes, the backslash,
    ``|``, ``^``, the brackets and braces, and the control
    characters. A run of them becomes a single ``_``, and ``~`` is
    replaced too, because it marks the digest below. What is left is
    stated by :data:`IDENTIFIER_PATTERN`.

    Replacing loses information, and losing information lets two
    different source keys arrive at one identifier. One identifier
    registered for two films cannot be undone by a later correction,
    whereas two identifiers minted for one film can be merged once the
    duplicate is noticed. Whenever the readable form is therefore not
    a faithful rendering of the value — whenever anything was replaced
    at all — a short digest of the whole value is appended behind
    ``~``. A value that needs no substitution gets no digest and is
    returned exactly as it came in, which is the common case for a
    provider's own record identifiers.

    Distinct values therefore keep distinct identifiers. An identifier
    without ``~`` is the value itself; one with ``~`` names both the
    readable form and the value it was made from; and only a digest
    collision could bring two values together. Surrounding whitespace
    is removed first, so a value differing from another only in that
    respect is the same value. A value too long to be workable keeps
    its first :data:`KEPT_BEFORE_DIGEST` characters and is completed
    by a digest of the whole of it, the two separated by ``~~``, which
    no shorter identifier can contain, so a shortened identifier can
    never look like a complete one.

    Parameters
    ----------
    value : str
        The source key, grouping key or other value to identify a
        record by.

    Returns
    -------
    str
        An identifier matching :data:`IDENTIFIER_PATTERN`.

    """
    stripped = str(value).strip()
    if not stripped:
        return EMPTY_IDENTIFIER
    readable = REPLACED.sub("_", stripped)
    if readable == stripped:
        identifier = readable
    else:
        # An underscore standing where the value began or ended says
        # nothing; the digest is what keeps the value apart.
        readable = readable.strip("_")
        identifier = (
            f"{readable}{DIGEST_MARKER}{_digest(stripped, DIGEST_LENGTH)}"
        )
    if len(identifier) <= MAX_IDENTIFIER_LENGTH:
        return identifier
    kept = readable[:KEPT_BEFORE_DIGEST]
    digest = _digest(stripped, LONG_DIGEST_LENGTH)
    return f"{kept}{DIGEST_MARKER}{DIGEST_MARKER}{digest}"


#: Key fields that identify a work on their own. A local identifier
#: does, because the data provider assigned it to one film. A title
#: does not, however distinctive it looks.
SELF_SUFFICIENT_KEY_FIELDS = frozenset({"identifier"})


def make_key(*parts) -> str:
    """Return a grouping key from ``parts``."""
    return KEY_SEPARATOR.join(
        "" if part is None else str(part) for part in parts
    )


def work_key(
    parts: dict,
    source_key: str,
    *,
    record_id: str | None = None,
    source_field: str = "profile work_key_fields",
) -> str:
    """Return the key deciding which records describe one work.

    A key has to identify a film. When everything but the title is
    missing — untitled, undated amateur and advertising material, of
    which archives hold a great deal — the title alone is left, and
    two unrelated films of the same name would become one WorkVariant
    with one identifier. That is the worst outcome this converter can
    produce: an identifier registered for two films cannot be undone
    by a later correction, whereas two works minted for one film can
    be merged once the duplicate is noticed.

    A degenerate key therefore does not group. The record keeps a work
    of its own, and the decision is reported so that it can be
    reviewed against the source data.

    Parameters
    ----------
    parts : dict
        Key field names and their values, in key order. A field named
        in :data:`SELF_SUFFICIENT_KEY_FIELDS` identifies a work on its
        own; of the others at least two have to be filled.
    source_key : str
        Identifier of the source record, appended to a degenerate key
        so that it groups with nothing but itself.
    record_id : str or None
        Identifier used when reporting, ``source_key`` by default.

    Returns
    -------
    str
        The grouping key.

    """
    filled = [
        name for name, value in parts.items() if str(value or "").strip()
    ]
    if len(filled) > 1 or set(filled) & SELF_SUFFICIENT_KEY_FIELDS:
        return make_key(*parts.values())
    key = make_key(*parts.values())
    report_issue(
        "warning",
        f"Work key holds no more than {', '.join(filled) or 'nothing'};"
        f" this record is kept as a work of its own rather than"
        f" grouped with any other record carrying the same key",
        record_id=record_id or source_key,
        source_field=source_field,
        target_field="has_identifier (work)",
        raw_value=key,
    )
    return make_key(*parts.values(), source_key)


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

    @contextmanager
    def attempt(self):
        """Register what a source record contributes, or nothing.

        A converter looks a work up before it has finished mapping the
        record, so a record failing halfway would leave its work in
        the context but not in the output: the next record with the
        same key would find the work known, emit nothing, and refer to
        a work nobody wrote. Everything the failed record registered
        is therefore discarded again.

        What an earlier record registered is kept, including the
        values this record contributed to it before failing; a work is
        built from several records by design.

        """
        registered = {
            entry.name: set(getattr(self, entry.name))
            for entry in fields(self)
            if isinstance(getattr(self, entry.name), dict)
        }
        try:
            yield self
        except BaseException:
            for name, known in registered.items():
                shared = getattr(self, name)
                for key in list(shared):
                    if key not in known:
                        del shared[key]
            raise

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
        work.has_identifier.append(
            efi.LocalResource(id=f"{local_identifier(key)}_work")
        )
        self.works[key] = work
        return work, True

    def manifestation_for(self, key: str, factory, local_id: str = ""):
        """Return the manifestation for ``key``, creating it if new.

        Parameters
        ----------
        key : str
            What identifies one manifestation for the converter. Where
            a provider states a persistent identifier for it, that is
            the better key: two copies of one manifestation are one
            manifestation whatever else the records say about them.
        factory : callable
            Builds the manifestation when the key is new.
        local_id : str, optional
            Basis of the local identifier, where it is not the key.
            The key may be a persistent identifier the provider
            issued, and a local identifier derived from it would say
            the same thing twice while reading worse.

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
            efi.LocalResource(
                id=f"{local_identifier(local_id or key)}_manifestation"
            )
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
