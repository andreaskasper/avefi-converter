"""Tests for loading and dumping AVefi records.

This module was previously untested although every converter and the
check command depend on it.

"""

import json

from avefi_schema import model_pydantic_v2 as efi
from pydantic import ValidationError
import pytest

from efi_conv.core import avefi

WORK = {
    "category": "avefi:WorkVariant",
    "type": "Monographic",
    "has_primary_title": {
        "type": "PreferredTitle",
        "has_name": "Die Brücke",
    },
    "has_identifier": [
        {"category": "avefi:LocalResource", "id": "record_work"}
    ],
}
ITEM = {
    "category": "avefi:Item",
    "has_primary_title": {"type": "TitleProper", "has_name": "Die Brücke"},
    "is_item_of": {
        "category": "avefi:LocalResource",
        "id": "record_manifestation",
    },
    "has_identifier": [{"category": "avefi:LocalResource", "id": "record"}],
}


def test_loads_a_list_of_records():
    records = avefi.loads(json.dumps([WORK, ITEM]))
    assert len(records) == 2
    assert records[0].category == "avefi:WorkVariant"


def test_loads_a_single_record_without_a_list():
    """The single record fallback in loads() was never exercised."""
    records = avefi.loads(json.dumps(WORK))
    assert len(records) == 1
    assert records[0].has_identifier[0].id == "record_work"


def test_round_trip_preserves_non_ascii(tmp_path):
    """Regression: file access used to depend on the platform encoding."""
    target = tmp_path / "records.json"
    records = avefi.loads(json.dumps([WORK]))
    avefi.dump(records, target)

    assert "Brücke" in target.read_text(encoding="utf-8")
    assert avefi.load(target)[0].has_primary_title.has_name == "Die Brücke"


def test_dump_is_atomic_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "records.json"
    avefi.dump(avefi.loads(json.dumps([WORK])), target)

    assert [p.name for p in tmp_path.iterdir()] == ["records.json"]


def test_a_failing_dump_does_not_destroy_the_previous_file(
    tmp_path, monkeypatch
):
    """The old content must survive a write that goes wrong."""
    target = tmp_path / "records.json"
    avefi.dump(avefi.loads(json.dumps([WORK])), target)
    before = target.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(avefi, "dumps", boom)
    with pytest.raises(OSError):
        avefi.dump(avefi.loads(json.dumps([ITEM])), target)

    assert target.read_text(encoding="utf-8") == before
    assert [p.name for p in tmp_path.iterdir()] == ["records.json"]


def test_invalid_json_still_raises():
    with pytest.raises(ValidationError):
        avefi.loads('{"category": "avefi:Nonsense"}')


class TestSortRecords:
    def test_orders_parents_before_children(self):
        records = avefi.loads(json.dumps([ITEM, WORK]))
        ordered = avefi.sort_records(records)
        assert [r.category for r in ordered] == [
            "avefi:WorkVariant",
            "avefi:Item",
        ]

    def test_is_stable_regardless_of_input_order(self):
        forward = avefi.loads(json.dumps([WORK, ITEM]))
        backward = avefi.loads(json.dumps([ITEM, WORK]))
        assert avefi.dumps(avefi.sort_records(forward)) == avefi.dumps(
            avefi.sort_records(backward)
        )

    def test_sorts_by_identifier_within_a_category(self):
        second = dict(WORK)
        second["has_identifier"] = [
            {"category": "avefi:LocalResource", "id": "a_work"}
        ]
        records = avefi.loads(json.dumps([WORK, second]))
        ordered = avefi.sort_records(records)
        assert [r.has_identifier[0].id for r in ordered] == [
            "a_work",
            "record_work",
        ]

    def test_does_not_lose_records(self):
        records = avefi.loads(json.dumps([ITEM, WORK]))
        assert len(avefi.sort_records(records)) == len(records)

    def test_handles_records_without_identifiers(self):
        record = efi.WorkVariant(
            type=efi.WorkVariantTypeEnum("Monographic"),
            has_primary_title=efi.Title(
                type=efi.TitleTypeEnum("PreferredTitle"), has_name="X"
            ),
        )
        assert avefi.sort_records([record]) == [record]
