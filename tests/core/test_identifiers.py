"""Every identifier this tool mints has to keep its shape.

A local identifier ends up inside a handle and inside the address
built from it, where ``/`` separates path segments, ``#`` starts a
fragment, ``?`` starts a query, ``:`` separates the scheme and a space
is not legal at all. A converter that lets one of those through mints
an identifier that means something different once it is resolved.
Letters and digits are a different matter: they carry no syntax, they
are what makes an identifier readable, and they are kept whatever
script they are written in.

The property is asserted here rather than in the test module of each
converter, so that a converter added later is covered without anybody
having to remember this file. What is checked is the recorded output
of every converter: ``tests/<package>/efi_records.json`` is what the
converter produced from that package's sample data, compared against
it record by record by the package's own ``test_map_to_efi``.

"""

import pathlib

import pytest

from efi_conv.core import avefi
from efi_conv.core.cli import IMPORTERS
from efi_conv.core.records import IDENTIFIER_PATTERN

TESTS = pathlib.Path(__file__).parent.parent

#: The converted sample data of every converter, one file per package.
SNAPSHOTS = sorted(
    path.parent.name for path in TESTS.glob("*/efi_records.json")
)


def snapshot(name):
    """Return the recorded records of one converter."""
    return avefi.load(TESTS / name / "efi_records.json")


@pytest.mark.parametrize("package", SNAPSHOTS)
def test_every_minted_identifier_keeps_its_shape(package):
    minted = [
        identifier.id
        for record in snapshot(package)
        for identifier in record.has_identifier
        # An AVefi PID is issued by the AVefi registry rather than
        # minted here, so its shape is not this tool's to decide.
        if identifier.category == "avefi:LocalResource"
    ]
    assert minted, f"{package} records carry no local identifier"
    offending = [
        value for value in minted if not IDENTIFIER_PATTERN.fullmatch(value)
    ]
    assert not offending, (
        f"{package} mints identifiers of the wrong shape: {offending}"
    )


@pytest.mark.parametrize("package", SNAPSHOTS)
def test_the_references_between_records_keep_it_too(package):
    """A reference names an identifier, so it has the same shape."""
    offending = []
    for record in snapshot(package):
        for attribute in (
            "is_part_of",
            "is_variant_of",
            "is_manifestation_of",
            "is_item_of",
            "is_copy_of",
            "is_derivative_of",
        ):
            value = getattr(record, attribute, None)
            if value is None:
                continue
            for reference in value if isinstance(value, list) else [value]:
                if reference.category != "avefi:LocalResource":
                    continue
                if not IDENTIFIER_PATTERN.fullmatch(reference.id):
                    offending.append(reference.id)
    assert not offending, (
        f"{package} refers to identifiers of the wrong shape: {offending}"
    )


def test_every_converter_has_a_snapshot_to_check():
    """Otherwise a converter added later would go unchecked here."""
    assert len(SNAPSHOTS) >= len(IMPORTERS), (
        f"{len(IMPORTERS)} converters are registered but only"
        f" {len(SNAPSHOTS)} recorded conversions were found:"
        f" {SNAPSHOTS}"
    )
