import inspect
import json
import pathlib

from efi_conv import lido as generic_lido
from efi_conv.core import avefi, check, from_
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.mdigital import lido as mdigital_lido


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(
        mdigital_lido, input_path("sample_data.xml")
    )
    result_serialized = json.loads(avefi.dumps(efi_records))

    assert result_serialized == expected_output


def test_schema_compliance(input_path):
    schema_validator = check.get_schema_validator()
    efi_records = from_.import_file(
        mdigital_lido, input_path("sample_data.xml")
    )
    assert check.pass_checks(efi_records, schema_validator), (
        "Mapped data did not validate"
    )


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(
        avefi.sort_records(
            from_.import_file(mdigital_lido, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    second = avefi.dumps(
        avefi.sort_records(
            from_.import_file(mdigital_lido, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    assert first == second


def test_the_provider_was_added_without_touching_the_generic_mapping():
    """The point of the exercise: a profile, not a converter.

    `efi_conv.lido` claims that a new data provider needs a profile.
    This asserts the claim from both sides: the generic package knows
    nothing about museum-digital, and this module contains no mapping
    code of its own.

    """
    generic_package = pathlib.Path(generic_lido.__file__).parent
    for path in sorted(generic_package.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        assert "museum-digital" not in source, path
        assert "mdigital" not in source, path

    own_functions = {
        name
        for name, obj in vars(mdigital_lido).items()
        if inspect.isfunction(obj) and obj.__module__ == mdigital_lido.__name__
    }
    assert own_functions == {
        "convert",
        "efi_import",
        "first_appellation",
        "first_text",
        "main",
        "new_context",
        "record_sources",
        "report_stand_in_issuer",
    }, "A profile module must not grow mapping code"


def test_the_module_maps_nothing_of_its_own(input_path):
    """Whatever the module adds, it may not touch the mapping.

    `report_stand_in_issuer` reads the export to say which institution
    the records name as their source. Nothing it reads reaches an
    AVefi record, and this is what says so: the module produces
    exactly what the generic mapping produces from its profile.

    """
    own = mdigital_lido.efi_import(input_path("sample_data.xml"))
    generic = generic_lido.efi_import(
        input_path("sample_data.xml"), mdigital_lido.PROFILE
    )
    assert avefi.dumps(own) == avefi.dumps(generic)


def test_the_stand_in_issuer_is_reported_once_per_input_file(input_path):
    """Every other converter says so; these two have to as well."""
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mdigital_lido, input_path("sample_data.xml"))
    entries = [
        entry
        for entry in report.entries
        if entry.target_field == "described_by.has_issuer_id"
    ]
    assert len(entries) == 1
    assert entries[0].severity == "warning"
    assert entries[0].raw_value == "https://www.museum-digital.de"
    assert "ISIL" in entries[0].message


def test_the_institution_the_record_names_is_reported(input_path):
    """lido:recordSource names the holder, and the mapping drops it."""
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mdigital_lido, input_path("sample_data.xml"))
    entries = [
        entry
        for entry in report.entries
        if entry.source_field == "lido:recordSource"
    ]
    assert entries and entries[0].severity == "warning"
    assert entries[0].raw_value == {
        "legalBodyID": None,
        "legalBodyName": "Stadtmuseum Halle",
    }


def test_copies_of_one_film_share_a_work(input_path):
    """Two prints of one film are one work with two manifestations."""
    efi_records = from_.import_file(
        mdigital_lido, input_path("sample_data.xml")
    )
    categories = [record.category for record in efi_records]
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 3
    assert categories.count("avefi:Item") == 3

    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    shared = next(
        w
        for w in works
        if w.has_primary_title.has_name == "Die Saale bei Halle"
    )
    assert sorted(shared.described_by[0].has_source_key) == [
        "https://nat.museum-digital.de/object/70001",
        "https://nat.museum-digital.de/object/70002",
    ]


def test_a_title_set_without_a_preferred_marker_still_works(input_path):
    """museum-digital does not mark a title set as preferred."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    assert 'lido:type="preferred"' not in source
    efi_records = from_.import_file(
        mdigital_lido, input_path("sample_data.xml")
    )
    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    assert all(
        work.has_primary_title.type == "PreferredTitle" for work in works
    )


def test_house_vocabularies_are_applied(input_path):
    efi_records = from_.import_file(
        mdigital_lido, input_path("sample_data.xml")
    )
    items = {
        item.described_by.has_source_key[0]: item
        for item in efi_records
        if item.category == "avefi:Item"
    }
    first = items["https://nat.museum-digital.de/object/70001"]
    assert first.has_colour_type == "BlackAndWhite"
    assert first.has_format[0].type == "16mmFilm"
    assert first.has_duration.has_value == "PT00H22M00S"
    assert first.has_webresource == [
        "https://nat.museum-digital.de/object/70001"
    ]
    colour = items["https://nat.museum-digital.de/object/70003"]
    assert colour.has_colour_type == "Colour"
    assert colour.has_format[0].type == "8mmFilm"


def test_an_approximate_date_keeps_its_qualifier(input_path):
    efi_records = from_.import_file(
        mdigital_lido, input_path("sample_data.xml")
    )
    dates = [
        event.has_date
        for record in efi_records
        for event in record.has_event
        if event.has_date
    ]
    assert "1962~" in dates


def test_a_record_that_is_not_film_is_skipped_and_reported(input_path):
    """A museum export is mostly not film; only film is in scope."""
    report = ConversionReport()
    with collecting(report):
        efi_records = from_.import_file(
            mdigital_lido, input_path("sample_data.xml")
        )
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
    photograph = "https://nat.museum-digital.de/object/70004"
    assert photograph not in source_keys
    skipped = [
        entry for entry in report.entries if entry.record_id == photograph
    ]
    assert skipped and "not a film" in skipped[0].message


def test_a_role_without_an_avefi_counterpart_is_reported(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mdigital_lido, input_path("sample_data.xml"))
    assert [
        entry
        for entry in report.entries
        if entry.severity == "warning" and entry.raw_value == "Kamera"
    ], "An unmapped role must not disappear in silence"


def test_the_issuer_is_declared_as_a_stand_in():
    """museum-digital publishes, it does not hold the material."""
    assert (
        mdigital_lido.ISSUER_INFO["has_issuer_id"]
        == "https://www.museum-digital.de"
    )
    assert mdigital_lido.ISSUER_INFO["has_issuer_name"] == "museum-digital"
    readme = (
        pathlib.Path(mdigital_lido.__file__).parent / "README.md"
    ).read_text(encoding="utf-8")
    assert "ISIL" in readme
    assert "publication platform" in readme


def test_the_access_status_vocabulary_is_empty_on_purpose():
    """An access status must not be inferred from silence."""
    assert mdigital_lido.ACCESS_STATUS_MAP == {}
    assert all(
        item.has_access_status is None
        for item in from_.import_file(
            mdigital_lido,
            pathlib.Path(__file__).parent / "sample_data.xml",
        )
        if item.category == "avefi:Item"
    )


class TestModuleEntryPoint:
    """`python -m efi_conv.mdigital.lido INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            mdigital_lido.main(
                [str(input_path("sample_data.xml")), str(target)]
            )
            == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert mdigital_lido.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        mdigital_lido.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(
                from_.import_file(mdigital_lido, input_path("sample_data.xml"))
            ),
            indent=2,
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert mdigital_lido.main(["--help"]) == 0
        assert "efi-conv from -f mdigital.lido" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert mdigital_lido.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            mdigital_lido.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )
