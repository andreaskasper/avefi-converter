"""Shared XML handling for the converters reading an XML schema.

Every XML based converter faces the same three problems, so they are
solved once here rather than in each of them:

* The input comes from third parties, so entity resolution and DTD
  loading have to be switched off deliberately instead of inheriting
  whatever the installed lxml happens to default to. A document that
  relies on entity declarations is refused, because a record is
  converted on its own, away from the declaration that gives its
  entities a meaning.
* A provider may ship one record per file, many records under a
  wrapper element of their own choosing, or a harvest in which the
  records sit inside an envelope. All three have to work.
* An export can be large. Reading it into memory as a whole is not an
  option, so records are streamed one at a time.

"""

from collections.abc import Iterator
import pathlib

from lxml import etree
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig

from .report import report_nothing_recognised

#: Parser configuration used by every converter. External entities and
#: DTDs stay disabled; unknown properties are tolerated because
#: providers do extend the schemas they export.
PARSER_CONFIG = ParserConfig(
    process_xinclude=False,
    load_dtd=False,
    fail_on_unknown_properties=False,
    fail_on_unknown_attributes=False,
)

#: lxml settings matching PARSER_CONFIG, for the streaming reader.
LXML_SAFETY = {
    "resolve_entities": False,
    "load_dtd": False,
    "no_network": True,
    "huge_tree": False,
}


class EntityDeclarationError(ValueError):
    """Raised for a document whose records rely on XML entities."""


#: One shared xsdata context. Building it is expensive, and it caches
#: the class metadata the parser needs.
_CONTEXT = XmlContext()


def xml_parser() -> XmlParser:
    """Return a parser configured for untrusted third party input."""
    return XmlParser(config=PARSER_CONFIG, context=_CONTEXT)


def qualified_name(namespace: str | None, local_name: str) -> str:
    """Return the lxml style qualified name for an element."""
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def iter_record_elements(
    input_file,
    namespace: str | None,
    local_name: str,
    *,
    report_if_empty: bool = True,
) -> Iterator[bytes]:
    """Yield the serialised record elements of a document.

    The document is streamed, and each record is released once it has
    been yielded, so that memory use stays independent of the size of
    the export. A document whose root element is itself a record is
    handled as a document with exactly one record.

    Parameters
    ----------
    input_file
        Path of the XML document.
    namespace : str or None
        Namespace URI of the record element, None for no namespace.
    local_name : str
        Local name of the record element.
    report_if_empty : bool
        Report a document holding no such element as one the converter
        recognises nothing in. Set to False by a caller that will look
        for a different element next, so that only its last attempt
        speaks.

    Yields
    ------
    bytes
        One record element, serialised with the namespace declarations
        it needs to be parsed on its own.

    Raises
    ------
    EntityDeclarationError
        The document declares XML entities. See
        :func:`refuse_entity_declarations`.

    """
    tag = qualified_name(namespace, local_name)
    path = pathlib.Path(input_file)
    context = etree.iterparse(
        str(path), events=("start", "end"), **LXML_SAFETY
    )
    found = False
    checked = False
    for event, element in context:
        if event == "start":
            if not checked:
                checked = True
                refuse_entity_declarations(element, path)
            continue
        if element.tag != tag:
            continue
        refuse_entity_references(element, path)
        found = True
        yield etree.tostring(element, encoding="utf-8")
        # Release the record and everything before it. The parent is
        # kept, because the parser is still writing into it.
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]
    if not found and report_if_empty:
        # This is where the tool knows the document is not what the
        # converter expects, so this is where it is reported.
        report_nothing_recognised(path, f"<{local_name}> element")


def refuse_entity_declarations(root, path):
    """Refuse a document whose document type declares entities.

    Resolving entities from an untrusted export is not an option: an
    external entity would make the converter fetch whatever the
    document points it at. Not resolving them is no better as long as
    the record is then serialised on its own, without the declaration
    that gave the entity a meaning — the reference and the rest of the
    text node disappear, and the run reports success. So the document
    is refused, and the person running the conversion is told how to
    produce one that can be converted.

    Raises
    ------
    EntityDeclarationError
        The internal subset of the document type declaration declares
        at least one entity.

    """
    internal_subset = root.getroottree().docinfo.internalDTD
    if internal_subset is None:
        return
    names = sorted(
        entity.name for entity in internal_subset.iterentities() or []
    )
    if not names:
        return
    raise EntityDeclarationError(
        f"{path} declares the XML"
        f" {'entities' if len(names) > 1 else 'entity'}"
        f" {', '.join(names)}. efi-conv does not resolve entities:"
        f" every record is converted on its own, away from the"
        f" declaration, so the text of the reference would be lost"
        f" without a trace, and an external entity would have this"
        f" tool fetch whatever the document points it at. Resolve the"
        f" entities before converting, for instance with"
        f" `xmllint --noent {path} > resolved.xml`, and check the"
        f" result before using it."
    )


def refuse_entity_references(element, path):
    """Refuse a record holding an entity reference.

    A second line of defence for entities that the internal subset
    does not declare, such as those of an external DTD.

    Raises
    ------
    EntityDeclarationError
        The record refers to an entity.

    """
    names = sorted({entity.name for entity in element.iter(etree.Entity)})
    if not names:
        return
    raise EntityDeclarationError(
        f"{path} refers to the XML"
        f" {'entities' if len(names) > 1 else 'entity'}"
        f" {', '.join(names)}, which efi-conv does not resolve."
        f" Resolve them before converting, for instance with"
        f" `xmllint --noent {path} > resolved.xml`, and check the"
        f" result before using it."
    )


def parse_records(input_file, clazz, namespace: str | None, local_name: str):
    """Yield the records of a document, parsed into ``clazz``.

    Parameters
    ----------
    input_file
        Path of the XML document.
    clazz
        Generated dataclass for the record element.
    namespace : str or None
        Namespace URI of the record element.
    local_name : str
        Local name of the record element.

    """
    parser = xml_parser()
    for serialised in iter_record_elements(input_file, namespace, local_name):
        yield parser.from_bytes(serialised, clazz)


def first(sequence):
    """Return the first element of ``sequence`` or None.

    The generated dataclasses use a list for a repeatable element and a
    plain value for a single one, and which of the two a given element
    is differs between the source schemas. Accepting both keeps the
    mapping code free of that distinction.

    """
    if not sequence:
        return None
    if isinstance(sequence, (list, tuple)):
        return sequence[0]
    return sequence


def text_of(element) -> str | None:
    """Return the string value of a generated element, if any.

    Several schemas declare elements as mixed content, which xsdata
    maps to a ``content`` list rather than to a ``value`` attribute, so
    both have to be considered.

    """
    if element is None:
        return None
    if isinstance(element, str):
        text = element.strip()
        return text or None
    value = getattr(element, "value", None)
    if value is None:
        content = getattr(element, "content", None)
        if content:
            value = " ".join(
                part.strip()
                for part in content
                if isinstance(part, str) and part.strip()
            )
    if value is None:
        return None
    text = str(value).strip()
    return text or None
