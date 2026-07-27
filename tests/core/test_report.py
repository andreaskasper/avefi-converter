import json

import pytest

from efi_conv.core import report as report_module
from efi_conv.core.report import (
    ConversionReport,
    ReportEntry,
    collecting,
    for_file,
    report_issue,
)


def test_entry_rejects_an_unknown_severity():
    with pytest.raises(ValueError):
        ReportEntry(severity="fatal", message="boom")


def test_issues_are_collected_while_a_report_is_active():
    report = ConversionReport()
    with collecting(report):
        report_issue("warning", "something odd", record_id="X")
    assert len(report.entries) == 1
    assert report.entries[0].record_id == "X"


def test_issues_outside_a_report_only_log(caplog):
    """Converters call report_issue unconditionally."""
    assert report_module.current_report() is None
    entry = report_issue("info", "no report active")
    assert entry.message == "no report active"


def test_source_file_is_attributed_automatically():
    report = ConversionReport()
    with collecting(report), for_file("export.xml"):
        report_issue("error", "bad value")
    assert report.entries[0].source_file == "export.xml"


def test_nested_files_restore_the_previous_attribution():
    report = ConversionReport()
    with collecting(report), for_file("outer.xml"):
        with for_file("inner.xml"):
            report_issue("info", "inner")
        report_issue("info", "outer")
    assert [entry.source_file for entry in report.entries] == [
        "inner.xml",
        "outer.xml",
    ]


def test_counts_are_grouped_by_severity():
    report = ConversionReport()
    with collecting(report):
        report_issue("info", "a")
        report_issue("warning", "b")
        report_issue("warning", "c")
    assert report.counts() == {"info": 1, "warning": 2, "error": 0}


def test_report_is_written_atomically(tmp_path):
    report = ConversionReport()
    with collecting(report):
        report_issue("error", "unconvertible", raw_value="50er Jahre")
    target = tmp_path / "report.json"
    report.write(target)

    assert [p.name for p in tmp_path.iterdir()] == ["report.json"]
    content = json.loads(target.read_text(encoding="utf-8"))
    assert content["summary"]["error"] == 1
    assert content["entries"][0]["raw_value"] == "50er Jahre"


def test_report_documents_its_own_format_version(tmp_path):
    target = tmp_path / "report.json"
    ConversionReport().write(target)
    content = json.loads(target.read_text(encoding="utf-8"))
    assert content["report_format_version"] == (
        report_module.REPORT_FORMAT_VERSION
    )
    assert "efi_conv_version" in content


def test_non_ascii_values_survive_the_round_trip(tmp_path):
    report = ConversionReport()
    with collecting(report):
        report_issue("info", "Umlaut", raw_value="Düsseldorf")
    target = tmp_path / "report.json"
    report.write(target)
    content = json.loads(target.read_text(encoding="utf-8"))
    assert content["entries"][0]["raw_value"] == "Düsseldorf"


def test_report_validates_against_its_own_schema(tmp_path):
    """The documented format has to describe what we actually write."""
    import pathlib

    from jsonschema.validators import validator_for

    schema_path = (
        pathlib.Path(report_module.__file__).parent / "report_schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)

    report = ConversionReport(
        avefi_schema_version={
            "source": "https://example.invalid/model.schema.json",
            "id": "x",
            "version": None,
            "metamodel_version": "1.7.0",
            "sha256": "0" * 64,
            "cached_at": "2026-07-27T00:00:00+00:00",
        }
    )
    with collecting(report):
        report_issue("info", "a note")
        report_issue("warning", "lost", raw_value=["a", "b"])
        report_issue("error", "unconvertible", record_id="X")
    target = tmp_path / "report.json"
    report.write(target)

    validator_class(schema).validate(
        json.loads(target.read_text(encoding="utf-8"))
    )
