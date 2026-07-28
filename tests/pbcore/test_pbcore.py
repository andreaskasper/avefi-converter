import json

import pytest

from efi_conv.core import avefi, check, from_
from efi_conv.core.normalise import NormalisationError
from efi_conv.core.report import ConversionReport, collecting
import efi_conv.pbcore as pbcore
from efi_conv.pbcore import mapping, profile


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    result_serialized = json.loads(avefi.dumps(efi_records))

    assert result_serialized == expected_output


def test_schema_compliance(input_path):
    """The mapping, not the profile, is what is under test here.

    This converter ships with the placeholder issuer, because it reads
    a format rather than one institution's export. That is what
    ``--profile`` is for, and what ``check`` refuses without; here it
    is accepted deliberately, so that the assertion stays about the
    records the mapping produces.

    """
    schema_validator = check.get_schema_validator()
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    assert check.pass_checks(
        efi_records, schema_validator, accept_placeholder_issuer=True
    ), "Mapped data did not validate"


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(
        avefi.sort_records(
            from_.import_file(pbcore, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    second = avefi.dumps(
        avefi.sort_records(
            from_.import_file(pbcore, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    assert first == second


def test_a_single_document_is_read_as_well(tmp_path, input_path):
    """A file may hold one record as its root instead of a collection."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    start = source.index("<pbcoreDescriptionDocument>")
    end = source.index("</pbcoreDescriptionDocument>") + len(
        "</pbcoreDescriptionDocument>"
    )
    single = tmp_path / "single.xml"
    single.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + source[start:end].replace(
            "<pbcoreDescriptionDocument>",
            "<pbcoreDescriptionDocument"
            ' xmlns="http://www.pbcore.org/PBCore/PBCoreNamespace.html">',
            1,
        ),
        encoding="utf-8",
    )
    records = pbcore.efi_import(single)
    assert [record.category for record in records].count("avefi:Item") == 2


def test_copies_of_one_film_share_a_work(input_path):
    """Two assets describing the same film are one work, not two."""
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    categories = [record.category for record in efi_records]
    assert categories.count("avefi:WorkVariant") == 3
    # Four moving image instantiations, and the series description,
    # which names no instantiation, contributes no item.
    assert categories.count("avefi:Item") == 4

    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    shared = next(
        w for w in works if w.has_primary_title.has_name == "The Bridge"
    )
    assert sorted(shared.described_by[0].has_source_key) == [
        "PBCORE-0001",
        "PBCORE-0002",
    ]


def test_instantiations_become_items_and_manifestations(input_path):
    """The two level model is bridged at the instantiation."""
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    items = [r for r in efi_records if r.category == "avefi:Item"]
    from_first_asset = [
        item
        for item in items
        if item.described_by.has_source_key == ["PBCORE-0001"]
    ]
    assert len(from_first_asset) == 2, (
        "Each moving image instantiation must yield its own item"
    )
    assert {item.has_identifier[0].id for item in from_first_asset} == {
        "PBCORE-0001_PBCORE-0001-1",
        "PBCORE-0001_PBCORE-0001-2",
    }
    assert len({item.is_item_of.id for item in from_first_asset}) == 2, (
        "Copies differing in format belong to different manifestations"
    )


def test_manifestations_hang_off_their_work(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    manifestations = [
        r for r in efi_records if r.category == "avefi:Manifestation"
    ]
    works = {
        r.has_identifier[0].id
        for r in efi_records
        if r.category == "avefi:WorkVariant"
    }
    assert len(manifestations) == 4
    assert all(m.is_manifestation_of[0].id in works for m in manifestations)


def test_a_record_without_an_instantiation_yields_a_work_alone(
    input_path,
):
    """An Item asserts a holding; a series description is not one.

    SERIES-42 describes a screening series and names no
    instantiation. Emitting a manifestation and an item for it would
    assert that the institution holds a copy of something that has no
    carrier in the source data at all.

    """
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    from_series = [
        record
        for record in efi_records
        for described in (
            record.described_by
            if isinstance(record.described_by, list)
            else [record.described_by]
        )
        if described.has_source_key == ["SERIES-42"]
    ]
    assert [record.category for record in from_series] == ["avefi:WorkVariant"]


def test_a_record_without_an_instantiation_is_reported(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(pbcore, input_path("sample_data.xml"))
    entries = [
        entry
        for entry in report.entries
        if entry.record_id == "SERIES-42"
        and entry.source_field == "pbcoreInstantiation"
    ]
    assert entries and entries[0].severity == "warning"
    assert "no instantiation" in entries[0].message


def test_a_relation_resolves_to_the_work_of_the_related_record(
    input_path,
):
    """is_part_of must point at a work, not at an item."""
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    works = {
        record.has_identifier[0].id: record
        for record in efi_records
        if record.category == "avefi:WorkVariant"
    }
    series = next(
        work
        for work in works.values()
        if work.has_primary_title.has_name == "Classic Cinema"
    )
    parents = [
        resource.id for work in works.values() for resource in work.is_part_of
    ]
    assert parents == [series.has_identifier[0].id]
    assert "SERIES-42" not in parents, (
        "The source identifier resolves to the item of another record"
    )


def test_an_unresolved_relation_is_reported_and_not_asserted(tmp_path):
    """AVefi rejects a reference resolving to no record in the set."""
    single = tmp_path / "single.xml"
    single.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<pbcoreDescriptionDocument"
        ' xmlns="http://www.pbcore.org/PBCore/PBCoreNamespace.html">'
        '<pbcoreIdentifier source="Example">PB-1'
        "</pbcoreIdentifier>"
        "<pbcoreTitle>Ein Film</pbcoreTitle>"
        "<pbcoreRelation><pbcoreRelationType>Is Part Of"
        "</pbcoreRelationType><pbcoreRelationIdentifier>ELSEWHERE-1"
        "</pbcoreRelationIdentifier></pbcoreRelation>"
        "<pbcoreInstantiation>"
        "<instantiationLocation>Example</instantiationLocation>"
        "<instantiationMediaType>Moving Image</instantiationMediaType>"
        "</pbcoreInstantiation>"
        "</pbcoreDescriptionDocument>",
        encoding="utf-8",
    )
    report = ConversionReport()
    with collecting(report):
        records = pbcore.efi_import(single)
    work = next(r for r in records if r.category == "avefi:WorkVariant")
    assert work.is_part_of == []
    assert [
        entry
        for entry in report.entries
        if entry.target_field == "is_part_of"
        and entry.raw_value == "ELSEWHERE-1"
        and entry.severity == "warning"
    ]


def test_the_instantiation_identifier_reaches_the_item(input_path):
    """The archive tracks the copy by it, so the item must carry it."""
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    identifiers = {
        record.described_by.has_source_key[0]: [
            resource.id for resource in record.has_identifier
        ]
        for record in efi_records
        if record.category == "avefi:Item"
    }
    assert "PBCORE-0002-1" in identifiers["PBCORE-0002"], (
        "A single instantiation must not cost its identifier"
    )
    assert "PBCORE-0003-1" in identifiers["PBCORE-0003"]


def test_audio_only_records_are_not_imported(input_path):
    """PBCore is used for radio; only moving image is in scope."""
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
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
    assert "PBCORE-0004" not in source_keys


def test_asset_type_becomes_the_work_type(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    by_title = {
        r.has_primary_title.has_name: r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
    }
    assert by_title["The Bridge"].type == "Monographic"
    assert by_title["Classic Cinema"].type == "Serial"
    assert by_title["Untitled advertising film"].type == "Analytic"


def test_titles_and_article_handling(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "The Bridge"
    )
    assert work.has_primary_title.has_ordering_name == "Bridge, The"
    assert work.has_primary_title.type == "PreferredTitle"
    types = {t.type for t in work.has_alternative_title}
    assert "SeriesTitle" in types, "The titleType vocabulary must be applied"


def test_bracketed_title_becomes_supplied_devised(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    supplied = [
        record
        for record in efi_records
        if record.has_primary_title.type == "SuppliedDevisedTitle"
    ]
    assert supplied
    assert all(
        not record.has_primary_title.has_name.startswith("[")
        for record in supplied
    )


def test_abbreviated_interval_is_expanded(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    dates = [
        event.has_date
        for record in efi_records
        for event in record.has_event
        if event.has_date
    ]
    assert "1962/1965" in dates


def test_instantiation_vocabularies_are_applied(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "PBCORE-0001_PBCORE-0001-1"
    )
    assert item.has_colour_type == "BlackAndWhite"
    assert item.has_format[0].type == "35mmFilm"
    assert item.has_access_status == "Archive"
    assert item.has_duration.has_value == "PT01H43M00S"
    assert item.has_extent.has_unit == "Feet"
    assert item.has_frame_rate == "24fps"
    assert item.has_sound_type == "Sound"
    assert item.in_language[0].code == "ger"
    assert item.has_event[0].category == "avefi:ManufactureEvent"


def test_digital_instantiation_becomes_a_digital_file(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == "PBCORE-0001_PBCORE-0001-2"
    )
    assert item.has_format[0].category == "avefi:DigitalFile"
    assert item.has_format[0].type == "MP4"
    assert item.has_access_status == "Viewing"


def test_holding_institution_is_kept_as_a_note(input_path):
    """AVefi names the holder through described_by, not on the item."""
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    items = [r for r in efi_records if r.category == "avefi:Item"]
    assert any(
        "Holding institution: Example Film Archive" in (item.has_note or [])
        for item in items
    )


def test_subjects_and_genres_are_kept_apart(input_path):
    efi_records = from_.import_file(pbcore, input_path("sample_data.xml"))
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "The Bridge"
    )
    assert [g.has_name for g in work.has_genre] == ["Feature", "War film"]
    assert [s.has_name for s in work.has_subject] == ["Second World War"]
    assert "Feature" in work.has_form


class TestReporting:
    def _report(self, input_path):
        report = ConversionReport()
        with collecting(report):
            from_.import_file(pbcore, input_path("sample_data.xml"))
        return report

    def test_placeholder_issuer_is_reported_once(self, input_path):
        """Records with the placeholder issuer must not be registered."""
        entries = [
            entry
            for entry in self._report(input_path).entries
            if entry.target_field == "described_by.has_issuer_id"
        ]
        assert len(entries) == 1
        assert entries[0].severity == "warning"
        assert "placeholder issuer" in entries[0].message

    def test_a_skipped_record_is_reported(self, input_path):
        skipped = [
            entry
            for entry in self._report(input_path).entries
            if entry.record_id == "PBCORE-0004"
            and "Record skipped" in entry.message
        ]
        assert skipped, "The audio only record must appear in the report"

    def test_unmappable_vocabulary_is_reported(self, input_path):
        """Nothing may be dropped without a trace."""
        raw_values = {
            str(entry.raw_value)
            for entry in self._report(input_path).entries
            if entry.severity == "warning"
        }
        for value in (
            "Nitrate print",
            "Hand coloured",
            "zzz",
            "Moving image/Dub",
            "18",
            "Cinematographer",
            "Nickname",
        ):
            assert value in raw_values, f"{value} was dropped silently"

    def test_unmapped_elements_are_reported_with_their_value(self, input_path):
        entries = [
            entry
            for entry in self._report(input_path).entries
            if entry.source_field == "pbcoreDescription"
        ]
        assert entries
        assert entries[0].raw_value.startswith("Seven schoolboys")


def test_unmappable_date_raises(tmp_path, input_path):
    """A date that cannot be mapped must not be silently dropped."""
    broken = _broken_copy(tmp_path, input_path, "sometime")
    with pytest.raises(NormalisationError):
        pbcore.efi_import(broken)


def test_decades_are_reported_as_unconvertible(tmp_path, input_path):
    """The contract reserves the decade mapping for after agreement."""
    broken = _broken_copy(tmp_path, input_path, "60er Jahre")
    report = ConversionReport()
    with collecting(report), pytest.raises(NormalisationError):
        pbcore.efi_import(broken)
    assert any(
        entry.severity == "error" and "Decade" in entry.message
        for entry in report.entries
    )


def test_one_bad_record_does_not_cost_the_whole_file(tmp_path, input_path):
    """File level containment would lose every record of an export."""
    broken = _broken_copy(tmp_path, input_path, "sometime")
    report = ConversionReport()
    with collecting(report):
        records = pbcore.efi_import(broken, continue_on_error=True)
    assert records, "The remaining records must survive"
    assert any(
        entry.severity == "error" and entry.record_id == "PBCORE-0003"
        for entry in report.entries
    )


def _broken_copy(tmp_path, input_path, replacement):
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "broken.xml"
    broken.write_text(
        source.replace(
            '<pbcoreAssetDate dateType="created">1962-65',
            f'<pbcoreAssetDate dateType="created">{replacement}',
        ),
        encoding="utf-8",
    )
    return broken


class TestProfile:
    def test_the_shipped_issuer_is_the_documented_placeholder(self):
        assert pbcore.ISSUER_INFO == profile.PLACEHOLDER_ISSUER_INFO
        assert pbcore.PROFILE.issuer_info == pbcore.ISSUER_INFO

    def test_vocabularies_live_in_the_profile(self):
        """The mapping must not hard code a house vocabulary."""
        for name in (
            "colour_type_map",
            "physical_format_map",
            "digital_format_map",
            "directing_role_map",
            "title_type_map",
            "asset_type_map",
        ):
            assert getattr(pbcore.PROFILE, name)

    def test_a_profile_may_override_a_vocabulary(self, input_path):
        custom = profile.PbcoreProfile(
            issuer_info={
                "has_issuer_id": "https://w3id.org/isil/DE-TEST-1",
                "has_issuer_name": "Test archive",
            },
            colour_type_map={"hand coloured": "Tinted"},
        )
        records = mapping.efi_import(
            input_path("sample_data.xml"), custom, continue_on_error=True
        )
        assert any(
            getattr(record, "has_colour_type", None) == "Tinted"
            for record in records
        )

    def test_a_real_issuer_is_not_reported_as_a_placeholder(self, input_path):
        custom = profile.PbcoreProfile(
            issuer_info={
                "has_issuer_id": "https://w3id.org/isil/DE-TEST-1",
                "has_issuer_name": "Test archive",
            }
        )
        report = ConversionReport()
        with collecting(report):
            mapping.efi_import(input_path("sample_data.xml"), custom)
        assert not any(
            "placeholder issuer" in entry.message for entry in report.entries
        )


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
    """`python -m efi_conv.pbcore INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            pbcore.main([str(input_path("sample_data.xml")), str(target)]) == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert pbcore.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        pbcore.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(
                from_.import_file(pbcore, input_path("sample_data.xml"))
            ),
            indent=2,
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert pbcore.main(["--help"]) == 0
        assert "efi-conv from -f pbcore" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert pbcore.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            pbcore.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )

    def test_the_module_declares_the_converter_interface(self):
        assert pbcore.DESCRIPTION
        assert pbcore.INPUT_FORMAT
        assert set(pbcore.ISSUER_INFO) == {
            "has_issuer_id",
            "has_issuer_name",
        }


def test_mapping_documentation_is_up_to_date():
    """MAPPING.md is generated; it must not be edited by hand."""
    import pathlib

    generated = mapping.render_mapping_markdown()
    committed = (
        pathlib.Path(mapping.__file__).parent / "MAPPING.md"
    ).read_text(encoding="utf-8")
    assert committed == generated, "Regenerate MAPPING.md from MAPPING_RULES"


class TestUnreadableDuration:
    """One free text duration must not cost a whole asset.

    instantiationDuration is free text, so an expression nobody can
    parse is to be expected. Discarding the record would lose the
    work, every manifestation and every item derived from it.

    """

    @pytest.fixture
    def broken_duration(self, tmp_path, input_path):
        source = input_path("sample_data.xml").read_text(encoding="utf-8")
        target = tmp_path / "duration.xml"
        target.write_text(
            source.replace(
                "<instantiationDuration>01:43:00",
                "<instantiationDuration>ungefähr eine Stunde",
            ),
            encoding="utf-8",
        )
        return target

    def test_the_other_fields_of_the_record_survive(
        self, broken_duration, input_path
    ):
        intact = pbcore.efi_import(input_path("sample_data.xml"))
        damaged = pbcore.efi_import(broken_duration)
        assert [r.category for r in damaged] == [r.category for r in intact]

    def test_the_duration_is_left_unset_and_reported(self, broken_duration):
        report = ConversionReport()
        with collecting(report):
            records = pbcore.efi_import(broken_duration)
        without = [
            record
            for record in records
            if record.category == "avefi:Item" and record.has_duration is None
        ]
        assert without
        assert [
            entry
            for entry in report.entries
            if entry.severity == "warning"
            and entry.target_field == "has_duration.has_value"
        ]

    def test_an_iso_duration_is_read(self, tmp_path, input_path):
        source = input_path("sample_data.xml").read_text(encoding="utf-8")
        target = tmp_path / "iso.xml"
        target.write_text(
            source.replace(
                "<instantiationDuration>01:43:00",
                "<instantiationDuration>PT01H43M00S",
            ),
            encoding="utf-8",
        )
        durations = {
            record.has_duration.has_value
            for record in pbcore.efi_import(target)
            if record.category == "avefi:Item" and record.has_duration
        }
        assert "PT01H43M00S" in durations
