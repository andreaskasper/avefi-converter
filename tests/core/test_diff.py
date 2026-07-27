import copy
import json

from efi_conv.core import avefi
from efi_conv.core.diff import compare, diff_values, render_markdown

WORK = {
    "category": "avefi:WorkVariant",
    "type": "Monographic",
    "has_primary_title": {
        "type": "PreferredTitle",
        "has_name": "Die Brücke",
    },
    "has_genre": [{"has_name": "Dokumentarfilm"}],
    "has_identifier": [
        {"category": "avefi:LocalResource", "id": "record_work"}
    ],
}


def records(*dicts):
    return avefi.loads(json.dumps(list(dicts)))


def test_identical_input_has_no_deviations():
    result = compare(records(WORK), records(WORK))
    assert result["summary"]["missing"] == 0
    assert result["summary"]["changed"] == 0


def test_missing_record_is_reported():
    result = compare(records(WORK), records())
    assert result["missing"] == ["record_work"]
    assert result["summary"]["missing"] == 1


def test_additional_record_is_reported():
    result = compare(records(), records(WORK))
    assert result["added"] == ["record_work"]


def test_changed_value_is_reported_field_by_field():
    changed = copy.deepcopy(WORK)
    changed["has_primary_title"]["has_name"] = "Die Bruecke"
    result = compare(records(WORK), records(changed))

    differences = result["changed"][0]["differences"]
    assert differences[0]["field"] == "has_primary_title.has_name"
    assert differences[0]["kind"] == "changed"


def test_lost_value_counts_as_removed():
    reduced = copy.deepcopy(WORK)
    del reduced["has_genre"]
    result = compare(records(WORK), records(reduced))
    assert result["summary"]["removed_values"] >= 1


def test_records_are_matched_regardless_of_order():
    second = copy.deepcopy(WORK)
    second["has_identifier"] = [
        {"category": "avefi:LocalResource", "id": "other_work"}
    ]
    forward = compare(records(WORK, second), records(second, WORK))
    assert forward["summary"]["changed"] == 0


class TestDiffValues:
    def test_nested_lists_are_paired_by_identity(self):
        reference = {"has_event": [{"category": "E", "has_date": "1959"}]}
        candidate = {"has_event": [{"category": "E", "has_date": "1960"}]}
        differences = list(diff_values(reference, candidate))
        assert len(differences) == 1
        assert differences[0]["field"] == "has_event[0].has_date"

    def test_unpairable_entries_are_reported_as_added_and_removed(self):
        differences = list(
            diff_values({"a": [{"has_name": "x"}]}, {"a": [{"has_name": "y"}]})
        )
        kinds = sorted(d["kind"] for d in differences)
        assert kinds == ["added", "removed"]

    def test_equal_scalars_produce_nothing(self):
        assert list(diff_values("a", "a")) == []


class TestRenderMarkdown:
    def test_mentions_both_inputs(self):
        result = compare(records(WORK), records(WORK))
        text = render_markdown(result, "ref.json", "cand.json")
        assert "ref.json" in text and "cand.json" in text

    def test_says_so_when_there_is_nothing_to_report(self):
        result = compare(records(WORK), records(WORK))
        assert "No deviations found" in render_markdown(result, "a", "b")

    def test_escapes_pipes_so_the_table_stays_intact(self):
        changed = copy.deepcopy(WORK)
        changed["has_primary_title"]["has_name"] = "A | B"
        result = compare(records(WORK), records(changed))
        text = render_markdown(result, "a", "b")
        row = next(line for line in text.splitlines() if "has_name" in line)
        # Four cells, so five unescaped delimiters; the pipe inside the
        # value must be escaped and therefore not count as one.
        assert row.count("|") - row.count("\\|") == 5
