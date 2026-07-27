import json
import pathlib

import pytest

from efi_conv.core import avefi, check, from_
from efi_conv.core.normalise import NormalisationError
from efi_conv.core.report import ConversionReport, collecting
import efi_conv.marc21 as marc21
from efi_conv.marc21 import mapping


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    result_serialized = json.loads(avefi.dumps(efi_records))

    assert result_serialized == expected_output


def test_schema_compliance(input_path):
    schema_validator = check.get_schema_validator()
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    assert check.pass_checks(efi_records, schema_validator), (
        "Mapped data did not validate"
    )


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(
        avefi.sort_records(
            from_.import_file(marc21, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    second = avefi.dumps(
        avefi.sort_records(
            from_.import_file(marc21, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    assert first == second


def test_copies_of_one_film_share_a_work(input_path):
    """Three records describing one film are one work, not three.

    A library catalogue holds one record per copy. Minting a work per
    record would register identifiers for copies rather than for films,
    which is the opposite of what the AVefi project is for.

    """
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    categories = [record.category for record in efi_records]
    # Four records in scope: a 35 mm print, a 16 mm print and a VHS
    # copy of one film, plus an advertising film.
    assert categories.count("avefi:Item") == 4
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 4

    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    shared = next(
        w for w in works if w.has_primary_title.has_name == "Die Brücke"
    )
    assert sorted(shared.described_by[0].has_source_key) == [
        "(DE-101)0000012345",
        "(DE-101)0000012346",
        "(DE-101)0000012347",
    ]


def test_copies_differing_in_carrier_get_their_own_manifestation(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    manifestations = [
        r for r in efi_records if r.category == "avefi:Manifestation"
    ]
    parents = {m.is_manifestation_of[0].id for m in manifestations}
    assert len(parents) == 2, "Manifestations must hang off their work"
    formats = set()
    for item in (r for r in efi_records if r.category == "avefi:Item"):
        formats.update(str(fmt.type) for fmt in item.has_format)
    assert {"35mmFilm", "16mmFilm", "VHS"} <= formats


def test_accompanying_material_is_not_imported_as_film(input_path):
    """A filmstrip is a projected medium but not a moving image."""
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    source_keys = {
        key
        for record in efi_records
        for described in (
            record.described_by
            if isinstance(record.described_by, list)
            else [record.described_by]
        )
        for key in (described.has_source_key or [])
    }
    assert "(DE-101)0000012348" not in source_keys, (
        "The filmstrip record must not become a film work"
    )


def test_a_skipped_record_is_reported(input_path):
    """Skipping must be visible in the protocol, not silent."""
    report = ConversionReport()
    with collecting(report):
        from_.import_file(marc21, input_path("sample_data.xml"))
    skipped = [
        entry
        for entry in report.entries
        if entry.record_id == "(DE-101)0000012348"
    ]
    assert skipped, "The skipped filmstrip must appear in the report"
    assert "Record skipped" in skipped[0].message
    assert skipped[0].source_field == "007/00"


def test_a_record_without_an_identifier_is_skipped_and_reported(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(marc21, input_path("sample_data.xml"))
    assert any(
        entry.severity == "warning" and "no identifier" in entry.message
        for entry in report.entries
    )


def test_the_placeholder_issuer_is_reported_once(input_path):
    """Records naming an unspecified issuer are not ready for use."""
    report = ConversionReport()
    with collecting(report):
        marc21.efi_import(input_path("sample_data.xml"))
    placeholder = [
        entry
        for entry in report.entries
        if entry.source_field == "profile issuer_info"
    ]
    assert len(placeholder) == 1
    assert placeholder[0].severity == "warning"
    assert placeholder[0].raw_value == mapping.PLACEHOLDER_ISSUER_ID


def test_the_identifier_carries_the_assigning_agency(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    items = [r for r in efi_records if r.category == "avefi:Item"]
    identifiers = {item.has_identifier[0].id for item in items}
    assert "(DE-101)0000012345" in identifiers
    assert "(DE-Mb112)AK-0007" in identifiers, (
        "A record without 001 must fall back to 035$a"
    )


def test_the_nonfiling_indicator_gives_the_ordering_name(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "Die Brücke"
    )
    assert work.has_primary_title.has_ordering_name == "Brücke, Die"


def test_a_questionable_date_becomes_a_qualified_interval(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    dates = [
        event.has_date
        for record in efi_records
        for event in record.has_event
        if event.has_date
    ]
    assert "1962?/1965?" in dates


def test_the_release_date_of_a_reissue_goes_to_the_manifestation(input_path):
    """008 date type p states release first and production second."""
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    manifestation = next(
        r
        for r in efi_records
        if r.category == "avefi:Manifestation"
        and "VHS" in r.has_identifier[0].id
    )
    assert manifestation.has_event[0].has_date == "1998"
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "Die Brücke"
    )
    assert work.has_event[0].has_date == "1959"


def test_the_carrier_of_a_videorecording_is_not_read_as_film(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "(DE-101)0000012347"
    )
    assert [str(fmt.type) for fmt in item.has_format] == ["VHS"]
    assert item.has_colour_type == "BlackAndWhite"
    assert item.has_sound_type == "Sound"


def test_generation_becomes_the_access_status(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    statuses = {
        item.has_identifier[0].id: item.has_access_status
        for item in efi_records
        if item.category == "avefi:Item"
    }
    assert statuses["(DE-101)0000012345"] == "Viewing"
    assert statuses["(DE-101)0000012346"] == "Master"


def test_an_unmappable_relator_is_reported(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(marc21, input_path("sample_data.xml"))
    assert any(
        entry.severity == "warning"
        and entry.raw_value == "Sammlerin"
        and "relator" in entry.message
        for entry in report.entries
    ), "An agent that cannot be filed must be reported, not dropped"


def test_an_unmappable_film_gauge_is_reported(input_path):
    """28 mm film has no AVefi format value."""
    report = ConversionReport()
    with collecting(report):
        efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    assert any(
        entry.severity == "warning"
        and entry.source_field == "007/07"
        and entry.raw_value == "e"
        for entry in report.entries
    )
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "(DE-Mb112)AK-0007"
    )
    assert not item.has_format, "No format may be invented for 28 mm"


def test_the_more_precise_running_time_wins_and_the_other_is_reported(
    input_path,
):
    report = ConversionReport()
    with collecting(report):
        efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "(DE-Mb112)AK-0007"
    )
    assert item.has_duration.has_value == "PT00H21M30S"
    assert any(
        entry.source_field == "008/18-20"
        and "Running time differs" in entry.message
        for entry in report.entries
    )


def test_holdings_become_an_identifier_and_a_note(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "(DE-101)0000012345"
    )
    assert [i.id for i in item.has_identifier] == [
        "(DE-101)0000012345",
        "(DE-Mb112)F 1959/12",
    ]
    assert any(note.startswith("Holdings:") for note in item.has_note)


def test_credits_and_cast_are_kept_as_notes(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "(DE-101)0000012345"
    )
    assert any(
        note.startswith("Production credits:") for note in item.has_note
    )
    assert any(note.startswith("Cast:") for note in item.has_note)


def test_subtitles_become_a_language_usage(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "(DE-101)0000012347"
    )
    usages = {
        str(language.code): [str(u) for u in language.usage]
        for language in item.in_language
    }
    assert usages == {"ger": ["SpokenLanguage"], "eng": ["Subtitles"]}


def broken_copy(tmp_path, input_path, name):
    """Return a copy of the sample whose 260 $c cannot be mapped."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / name
    broken.write_text(
        source.replace(
            '<subfield code="c">1959.</subfield>',
            '<subfield code="c">irgendwann</subfield>',
        ),
        encoding="utf-8",
    )
    return broken


def test_unmappable_date_raises(tmp_path, input_path):
    """A date that cannot be mapped must not be silently dropped."""
    broken = broken_copy(tmp_path, input_path, "broken.xml")
    with pytest.raises(NormalisationError):
        marc21.efi_import(broken)


def test_one_bad_record_does_not_cost_the_whole_file(tmp_path, input_path):
    """File level containment would lose every record of an export."""
    broken = broken_copy(tmp_path, input_path, "partly_broken.xml")
    report = ConversionReport()
    with collecting(report):
        records = marc21.efi_import(broken, continue_on_error=True)
    assert records, "The remaining records must survive"
    assert any(
        entry.severity == "error" and entry.record_id == "(DE-101)0000012345"
        for entry in report.entries
    )


def test_a_single_record_document_is_read(tmp_path, input_path):
    """An export may ship one record per file."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    start = source.index("  <record>")
    end = source.index("  </record>") + len("  </record>")
    single = tmp_path / "single.xml"
    single.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + source[start:end].replace(
            "<record>",
            '<record xmlns="http://www.loc.gov/MARC21/slim">',
            1,
        )
        + "\n",
        encoding="utf-8",
    )
    records = marc21.efi_import(single)
    assert len(records) == 3


class TestMappingDocumentation:
    def test_rule_ids_are_unique(self):
        ids = [rule.id for rule in mapping.MAPPING_RULES]
        assert len(ids) == len(set(ids))

    def test_every_rule_is_rendered(self):
        markdown = mapping.render_mapping_markdown()
        for rule in mapping.MAPPING_RULES:
            assert f"`{rule.id}`" in markdown
            assert rule.source_path.split("/")[0] in markdown

    def test_table_has_a_header(self):
        markdown = mapping.render_mapping_markdown()
        assert markdown.splitlines()[0].startswith("# ")
        assert "| Rule |" in markdown

    def test_assumptions_are_rendered(self):
        markdown = mapping.render_mapping_markdown()
        assert "## Assumptions" in markdown
        for assumption in mapping.ASSUMPTIONS:
            assert f"- {assumption}" in markdown


class TestModuleEntryPoint:
    """`python -m efi_conv.marc21 INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            marc21.main([str(input_path("sample_data.xml")), str(target)]) == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert marc21.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        marc21.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(
                from_.import_file(marc21, input_path("sample_data.xml"))
            ),
            indent=2,
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert marc21.main(["--help"]) == 0
        assert "efi-conv from -f marc21" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert marc21.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            marc21.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )


class TestModuleInterface:
    """What `efi-conv from` expects of a converter module."""

    def test_declares_the_issuer(self):
        assert set(marc21.ISSUER_INFO) == {
            "has_issuer_id",
            "has_issuer_name",
        }

    def test_declares_a_description_and_an_input_format(self):
        assert marc21.DESCRIPTION
        assert marc21.INPUT_FORMAT

    def test_efi_import_accepts_continue_on_error(self):
        assert from_.accepts_continue_on_error(marc21)


def test_mapping_documentation_is_up_to_date():
    """MAPPING.md is generated; it must not be edited by hand."""
    generated = mapping.render_mapping_markdown()
    committed = (
        pathlib.Path(mapping.__file__).parent / "MAPPING.md"
    ).read_text(encoding="utf-8")
    assert committed == generated, "Regenerate MAPPING.md from MAPPING_RULES"
