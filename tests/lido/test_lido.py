import json

import pytest

from efi_conv.core import avefi, check, from_
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


def test_every_record_yields_work_manifestation_and_item(input_path):
    efi_records = from_.import_file(fmdu_lido, input_path("sample_data.xml"))
    categories = [record.category for record in efi_records]
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 2
    assert categories.count("avefi:Item") == 2


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
