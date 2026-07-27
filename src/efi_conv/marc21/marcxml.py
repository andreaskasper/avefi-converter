"""Reader for MARCXML documents.

MARCXML is a thin envelope around the MARC21 record structure: a
``leader``, a number of ``controlfield`` elements holding fixed field
data at defined character positions, and ``datafield`` elements holding
``subfield`` elements. The schema is small and very loose, so a
generated parser would add a dependency and several thousand lines of
bindings without making the mapping any easier to write. This module
provides the few accessors the mapping needs instead.

Two properties of MARC decide how the elements are read:

* The leader and the control fields are positional. Their whitespace is
  significant, so their text is taken verbatim, unlike subfield values,
  which are trimmed.
* A document may carry a single ``record`` as its root element or many
  of them inside a ``collection``. Both are handled by streaming the
  records with :func:`~efi_conv.core.xmlrecords.iter_record_elements`,
  so memory use stays independent of the size of the export.

"""

from collections.abc import Iterator
from dataclasses import dataclass, field
import logging

from lxml import etree

from ..core.xmlrecords import LXML_SAFETY, iter_record_elements

log = logging.getLogger(__name__)

#: Namespace of the MARC21 slim schema.
MARC_NAMESPACE = "http://www.loc.gov/MARC21/slim"

#: Characters standing for "nothing coded here" in a fixed field. The
#: blank is the MARC fill for an undefined position, the vertical bar
#: means "no attempt to code" and the hash is the way a blank is
#: written in the MARC documentation, which does end up in exports.
FILL_CHARACTERS = frozenset({"", " ", "|", "#"})


def local_name(element) -> str:
    """Return the local name of an element, ignoring its namespace.

    Comments and processing instructions carry a callable rather than a
    string as their tag; they yield an empty name and are skipped by
    the callers.

    """
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def fixed_position(value: str | None, index: int, length: int = 1) -> str:
    """Return the characters of a fixed field at a position.

    Parameters
    ----------
    value : str or None
        Leader or control field, taken verbatim from the document.
    index : int
        Zero based character position, as counted in the MARC
        documentation.
    length : int
        Number of characters to return.

    Returns
    -------
    str
        The requested characters, or an empty string when the field is
        absent or too short. A truncated fixed field is common enough
        in exports that it must not raise.

    """
    if not value:
        return ""
    chunk = value[index : index + length]
    return chunk if len(chunk) == length else ""


def is_fill(code: str | None) -> bool:
    """Return True if a fixed field position carries no value."""
    return code is None or code in FILL_CHARACTERS


@dataclass(frozen=True)
class Subfield:
    """One ``subfield`` element of a MARC data field."""

    code: str
    value: str


@dataclass(frozen=True)
class DataField:
    """One ``datafield`` element, that is a MARC variable data field."""

    tag: str
    ind1: str = " "
    ind2: str = " "
    subfields: tuple[Subfield, ...] = ()

    def subfield(self, code: str) -> str | None:
        """Return the first subfield with ``code``, or None."""
        for subfield in self.subfields:
            if subfield.code == code and subfield.value:
                return subfield.value
        return None

    def subfield_values(self, code: str) -> list[str]:
        """Return the values of every subfield with ``code``."""
        return [
            subfield.value
            for subfield in self.subfields
            if subfield.code == code and subfield.value
        ]

    def codes(self) -> list[str]:
        """Return the subfield codes present, in document order."""
        return [subfield.code for subfield in self.subfields]


@dataclass(frozen=True)
class MarcRecord:
    """One MARC21 record.

    Attributes
    ----------
    leader : str
        The 24 character leader, verbatim.
    control_fields : tuple
        Pairs of tag and verbatim value for fields 001 to 009.
    data_fields : tuple
        The variable data fields, in document order.

    """

    leader: str = ""
    control_fields: tuple[tuple[str, str], ...] = ()
    data_fields: tuple[DataField, ...] = field(default_factory=tuple)

    def control_field(self, tag: str) -> str | None:
        """Return the first control field with ``tag``, or None."""
        for control_tag, value in self.control_fields:
            if control_tag == tag:
                return value
        return None

    def control_field_values(self, tag: str) -> list[str]:
        """Return every control field with ``tag``.

        Fields 006 and 007 are repeatable: a record may describe a
        videorecording and its accompanying motion picture in one go.

        """
        return [
            value
            for control_tag, value in self.control_fields
            if control_tag == tag
        ]

    def fields(self, *tags: str) -> list[DataField]:
        """Return the data fields carrying any of ``tags``."""
        return [
            data_field
            for data_field in self.data_fields
            if data_field.tag in tags
        ]

    def subfield(self, tag: str, code: str) -> str | None:
        """Return the first ``tag $code`` value, or None."""
        for data_field in self.fields(tag):
            value = data_field.subfield(code)
            if value:
                return value
        return None

    def subfields(self, tag: str, code: str) -> list[str]:
        """Return every ``tag $code`` value, in document order."""
        return [
            value
            for data_field in self.fields(tag)
            for value in data_field.subfield_values(code)
        ]


def record_from_element(element) -> MarcRecord:
    """Return the MarcRecord described by a ``record`` element."""
    leader = ""
    control_fields: list[tuple[str, str]] = []
    data_fields: list[DataField] = []
    for child in element:
        name = local_name(child)
        if name == "leader":
            leader = child.text or ""
        elif name == "controlfield":
            control_fields.append((child.get("tag") or "", child.text or ""))
        elif name == "datafield":
            data_fields.append(data_field_from_element(child))
    return MarcRecord(
        leader=leader,
        control_fields=tuple(control_fields),
        data_fields=tuple(data_fields),
    )


def data_field_from_element(element) -> DataField:
    """Return the DataField described by a ``datafield`` element."""
    subfields = tuple(
        Subfield(child.get("code") or "", (child.text or "").strip())
        for child in element
        if local_name(child) == "subfield"
    )
    return DataField(
        tag=element.get("tag") or "",
        ind1=indicator(element.get("ind1")),
        ind2=indicator(element.get("ind2")),
        subfields=subfields,
    )


def indicator(value: str | None) -> str:
    """Return a single character indicator, blank when unset."""
    if not value:
        return " "
    return value[0]


def parse_record(serialised: bytes, parser=None) -> MarcRecord:
    """Return the MarcRecord parsed from a serialised element."""
    if parser is None:
        parser = etree.XMLParser(**LXML_SAFETY)
    return record_from_element(etree.fromstring(serialised, parser))


def iter_records(input_file) -> Iterator[MarcRecord]:
    """Yield the MARC records of a MARCXML document.

    Both a document rooted in ``collection`` and one rooted in a single
    ``record`` are handled, because both occur in the wild. A document
    that declares no namespace at all is read as well: exports produced
    by hand or by a stylesheet regularly omit it, and refusing them
    would send the data provider away for a reason that has nothing to
    do with their metadata.

    """
    parser = etree.XMLParser(**LXML_SAFETY)
    found = False
    for serialised in iter_record_elements(
        input_file, MARC_NAMESPACE, "record"
    ):
        found = True
        yield parse_record(serialised, parser)
    if found:
        return
    log.debug(
        f"No namespaced <record> in {input_file}, retrying without namespace"
    )
    for serialised in iter_record_elements(input_file, None, "record"):
        yield parse_record(serialised, parser)
