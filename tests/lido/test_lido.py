import json

import pytest

from efi_conv.core import avefi, check, from_
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.fmdu import lido as fmdu_lido
from efi_conv.lido import mapping
from efi_conv.lido.normalise import NormalisationError


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    result_serialized = json.loads(avefi.dumps(efi_records))

    assert result_serialized == expected_output


def test_schema_compliance(input_path):
    schema_validator = check.get_schema_validator()
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    assert check.pass_checks(efi_records, schema_validator), (
        "Mapped data did not validate"
    )


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(
        avefi.sort_records(
            from_.import_file(fmdu_lido, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    second = avefi.dumps(
        avefi.sort_records(
            from_.import_file(fmdu_lido, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    assert first == second


def test_copies_of_one_film_share_a_work(input_path):
    """Two prints of the same film are one work, not two.

    Minting a work per record would defeat the purpose of the AVefi
    identifiers; the CSV importer for the same institution groups by
    title, director and year, and so does this one.

    """
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    categories = [record.category for record in efi_records]
    # Three film records, two of them prints of the same film, plus one
    # poster that is not a film holding at all.
    assert categories.count("avefi:Item") == 3
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 3

    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    shared = next(
        w for w in works if w.has_primary_title.has_name == "Die Brücke"
    )
    assert sorted(shared.described_by[0].has_source_key) == [
        "FMDU-0001",
        "FMDU-0003",
    ]


def test_copies_differing_in_carrier_get_their_own_manifestation(
    input_path,
):
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    manifestations = [
        r for r in efi_records if r.category == "avefi:Manifestation"
    ]
    parents = {m.is_manifestation_of[0].id for m in manifestations}
    assert len(parents) == 2, "Manifestations must hang off their work"


def test_accompanying_material_is_not_imported_as_film(input_path):
    """Only holdings metadata about film is in scope."""
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
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
    assert "FMDU-0004" not in source_keys, (
        "The poster record must not become a film work"
    )


def test_bracketed_title_becomes_supplied_devised(input_path):
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    supplied = [
        record
        for record in efi_records
        if record.has_primary_title.type == "SuppliedDevisedTitle"
    ]
    assert supplied, "Expected the bracketed title to be marked as supplied"
    assert all(
        not title.has_name.startswith("[")
        for title in (record.has_primary_title for record in supplied)
    )


def test_abbreviated_interval_is_expanded(input_path):
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    dates = [
        event.has_date
        for record in efi_records
        for event in record.has_event
        if event.has_date
    ]
    assert "1962/1965" in dates


def test_house_vocabularies_are_applied(input_path):
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    items = [r for r in efi_records if r.category == "avefi:Item"]
    described = [item for item in items if item.has_colour_type]
    assert described, "Expected at least one item with a colour type"
    assert described[0].has_colour_type == "BlackAndWhite"
    assert described[0].has_access_status == "Archive"
    assert described[0].has_format[0].type == "35mmFilm"


def test_a_skipped_record_is_reported(input_path):
    """Skipping must be visible in the protocol, not silent."""
    report = ConversionReport()
    with collecting(report):
        from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    skipped = [
        entry for entry in report.entries if entry.record_id == "FMDU-0004"
    ]
    assert skipped, "The skipped poster must appear in the report"
    assert "not a film" in skipped[0].message


def test_decades_are_reported_as_unconvertible(tmp_path, input_path):
    """The contract reserves the decade mapping for after agreement."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "decade.xml"
    broken.write_text(
        source.replace(
            "<lido:displayDate>1962-65", "<lido:displayDate>50er Jahre"
        ),
        encoding="utf-8",
    )
    report = ConversionReport()
    with collecting(report), pytest.raises(NormalisationError):
        fmdu_lido.efi_import(broken)
    assert any(
        entry.severity == "error" and "Decade" in entry.message
        for entry in report.entries
    )


def test_one_bad_record_does_not_cost_the_whole_file(tmp_path, input_path):
    """File level containment would lose every record of an export."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "partly_broken.xml"
    broken.write_text(
        source.replace(
            "<lido:displayDate>1962-65", "<lido:displayDate>irgendwann"
        ),
        encoding="utf-8",
    )
    report = ConversionReport()
    with collecting(report):
        records = fmdu_lido.efi_import(broken, continue_on_error=True)
    assert records, "The remaining records must survive"
    assert any(
        entry.severity == "error" and entry.record_id == "FMDU-0002"
        for entry in report.entries
    )


def test_unmappable_date_raises(tmp_path, input_path):
    """A date that cannot be mapped must not be silently dropped."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "broken.xml"
    broken.write_text(
        source.replace(
            "<lido:displayDate>1962-65", "<lido:displayDate>irgendwann"
        ),
        encoding="utf-8",
    )
    with pytest.raises(NormalisationError):
        fmdu_lido.efi_import(broken)


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


class TestModuleEntryPoint:
    """`python -m efi_conv.fmdu.lido INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            fmdu_lido.main([str(input_path("sample_data.xml")), str(target)])
            == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert fmdu_lido.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        fmdu_lido.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(
                from_.import_file(fmdu_lido, input_path("sample_data.xml"))
            ),
            indent=2,
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert fmdu_lido.main(["--help"]) == 0
        assert "efi-conv from -f fmdu.lido" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert fmdu_lido.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            fmdu_lido.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )


def test_mapping_documentation_is_up_to_date():
    """MAPPING.md is generated; it must not be edited by hand."""
    import pathlib

    generated = mapping.render_mapping_markdown()
    committed = (
        pathlib.Path(mapping.__file__).parent / "MAPPING.md"
    ).read_text(encoding="utf-8")
    assert committed == generated, "Regenerate MAPPING.md from MAPPING_RULES"
