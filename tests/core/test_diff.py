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


PID = "21.11155/8C5A0C79-7A6C-44EC-8920-01C8A158BFBC"


def with_identifiers(*identifiers):
    """Return the sample work carrying these identifiers instead."""
    work = copy.deepcopy(WORK)
    work["has_identifier"] = list(identifiers)
    return work


def local(value):
    return {"category": "avefi:LocalResource", "id": value}


def persistent(value=PID):
    return {"category": "avefi:AVefiResource", "id": value}


class TestMatchingAcrossTwoExports:
    """Two converters reading one collection out of different formats.

    Local identifiers are derived from the data, so the same work
    comes out under a different one from each. Of 2218 works held in
    both the CSV and the LIDO delivery of one museum, not a single
    local identifier agreed and 2217 registered identifiers did.
    Matching on the local one reported every record as both missing
    and added, which is a comparison nobody can read.

    """

    def test_a_shared_pid_matches_records_with_different_local_ids(self):
        result = compare(
            records(with_identifiers(local("derived_work"), persistent())),
            records(with_identifiers(local("955613_work"), persistent())),
        )
        assert result["summary"]["matched"] == 1
        assert result["summary"]["missing"] == 0
        assert result["summary"]["added"] == 0

    def test_the_local_identifier_still_matches_without_a_pid(self):
        result = compare(
            records(with_identifiers(local("record_work"))),
            records(with_identifiers(local("record_work"))),
        )
        assert result["summary"]["matched"] == 1

    def test_a_pid_beats_a_local_identifier(self):
        """Where the two disagree, the registered one is the answer.

        A local identifier can be reused for something else after the
        data changes; a handle cannot.

        """
        reference = records(
            with_identifiers(local("shared"), persistent()),
        )
        candidate = records(
            with_identifiers(local("shared"), persistent("21.11155/OTHER")),
            with_identifiers(local("elsewhere"), persistent()),
        )
        result = compare(reference, candidate)
        assert result["summary"]["matched"] == 1
        assert result["added"] == ["21.11155/OTHER"]

    def test_a_record_is_counted_once_not_once_per_identifier(self):
        """The summary is about records, which is what a reader counts."""
        result = compare(
            records(with_identifiers(local("a_work"), persistent())),
            records(),
        )
        assert result["summary"]["reference_records"] == 1
        assert result["summary"]["missing"] == 1

    def test_an_unmatched_record_is_named_by_its_pid(self):
        result = compare(
            records(with_identifiers(local("a_work"), persistent())),
            records(),
        )
        assert result["missing"] == [PID]

    def test_one_reference_record_matches_one_candidate(self):
        """Two copies of a work must not both pair with the same one."""
        reference = records(
            with_identifiers(local("a")), with_identifiers(local("b"))
        )
        candidate = records(with_identifiers(local("a")))
        result = compare(reference, candidate)
        assert result["summary"]["matched"] == 1
        assert result["missing"] == ["b"]
