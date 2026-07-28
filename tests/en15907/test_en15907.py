import dataclasses
import json
import pathlib

import pytest

from efi_conv import en15907
from efi_conv.core import avefi, check, from_
from efi_conv.core.normalise import NormalisationError
from efi_conv.core.records import local_identifier
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.en15907 import mapping
from efi_conv.en15907.profile import EfgProfile

SINGLE_ENTITY = """<?xml version="1.0" encoding="UTF-8"?>
<efgEntity xmlns="http://www.europeanfilmgateway.eu/efg">
  <avcreation>
    <identifier scheme="local">SOLO-1</identifier>
    <title lang="en"><text>A Single Entity</text></title>
    <productionYear>1971</productionYear>
    <avManifestation>
      <identifier scheme="local">SOLO-1-M</identifier>
      <item>
        <identifier scheme="local">SOLO-1-I</identifier>
        <isShownAt>https://example.org/solo</isShownAt>
      </item>
    </avManifestation>
  </avcreation>
</efgEntity>
"""


def records_for(input_path):
    return from_.import_file(en15907, input_path("sample_data.xml"))


def report_for(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(en15907, input_path("sample_data.xml"))
    return report


def test_map_to_efi(input_path, expected_output):
    efi_records = records_for(input_path)
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
    efi_records = records_for(input_path)
    assert check.pass_checks(
        efi_records, schema_validator, accept_placeholder_issuer=True
    ), "Mapped data did not validate"


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(avefi.sort_records(records_for(input_path)), indent=2)
    second = avefi.dumps(avefi.sort_records(records_for(input_path)), indent=2)
    assert first == second


def test_entities_describing_one_film_share_a_work(input_path):
    """A provider may split one film over several entities.

    Minting a work per entity would defeat the purpose of the AVefi
    identifiers, so entities agreeing on the avcreation identifier
    contribute to one WorkVariant.

    """
    efi_records = records_for(input_path)
    categories = [record.category for record in efi_records]
    # Three avcreation entities, two of them for the same film, with
    # four manifestations and five copies between them.
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 4
    assert categories.count("avefi:Item") == 5

    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    shared = next(
        w for w in works if w.has_primary_title.has_name == "Die Brücke"
    )
    assert shared.described_by[0].has_source_key == ["FILM-001"]
    manifestations = [
        r.described_by.has_source_key[0]
        for r in efi_records
        if r.category == "avefi:Manifestation"
        and r.is_manifestation_of[0].id == shared.has_identifier[0].id
    ]
    assert sorted(manifestations) == ["MAN-001", "MAN-002", "MAN-003"]


def test_alternative_titles_of_both_entities_reach_the_work(input_path):
    efi_records = records_for(input_path)
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "Die Brücke"
    )
    titles = {t.has_name: t.type for t in work.has_alternative_title}
    assert titles["The Bridge"] == "TranslatedTitle"
    assert titles["Le pont"] == "TranslatedTitle"
    assert titles["Die sieben Jungen"] == "WorkingTitle"
    # A relation the profile does not know still keeps the title.
    assert titles["Die Brücke bei Cham"] == "AlternativeTitle"


def test_a_keyword_identifier_becomes_an_authority_link(input_path):
    """efi.Subject.same_as exists, so a GND number is not a loss."""
    efi_records = from_.import_file(en15907, input_path("sample_data.xml"))
    subjects = [
        subject
        for record in efi_records
        if record.category == "avefi:WorkVariant"
        for subject in record.has_subject
    ]
    linked = next(s for s in subjects if s.has_name == "Second World War")
    assert [resource.id for resource in linked.same_as or []] == [
        "gnd/4079143-9"
    ]
    assert linked.same_as[0].category == "avefi:GNDResource"


def test_the_country_of_reference_is_not_asserted_as_a_name(input_path):
    """A GeographicName holds a name, and "DE" is a code."""
    efi_records = from_.import_file(en15907, input_path("sample_data.xml"))
    places = [
        place.has_name
        for record in efi_records
        if record.category == "avefi:WorkVariant"
        for event in record.has_event
        for place in event.located_in
    ]
    assert "DE" not in places
    assert "Germany" in places


def test_an_unknown_country_code_is_reported(input_path, tmp_path):
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    changed = tmp_path / "country.xml"
    changed.write_text(source.replace(">DE<", ">ZZ<"), encoding="utf-8")
    report = ConversionReport()
    with collecting(report):
        records = en15907.efi_import(changed)
    places = [
        place.has_name
        for record in records
        if record.category == "avefi:WorkVariant"
        for event in record.has_event
        for place in event.located_in
    ]
    assert "ZZ" not in places
    assert [
        entry
        for entry in report.entries
        if entry.source_field == "avcreation/countryOfReference"
        and entry.raw_value == "ZZ"
        and entry.severity == "warning"
    ]


def test_manifestation_without_items_yields_one(input_path):
    """AVefi keeps the technical description on the item.

    An avManifestation without item elements would otherwise lose its
    carrier and running time, and a manifestation without items does
    not pass the AVefi checks either.

    """
    efi_records = records_for(input_path)
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == local_identifier("MAN-002#item")
    )
    assert item.has_format[0].type == "16mmFilm"
    assert item.has_duration.has_value == "PT01H37M00S"


def test_manifestation_level_description_reaches_every_item(input_path):
    efi_records = records_for(input_path)
    item = next(r for r in efi_records if r.has_identifier[0].id == "ITEM-001")
    assert item.has_duration.has_value == "PT01H43M00S"
    assert item.has_frame_rate == "24fps"
    assert item.has_colour_type == "BlackAndWhite"
    assert item.has_sound_type == "Sound"
    assert item.has_extent.has_unit == "Metre"
    assert [f.type for f in item.has_format] == ["35mmFilm", "MP4"]
    assert [(la.code, list(la.usage)) for la in item.in_language] == [
        ("ger", ["SpokenLanguage"]),
        ("eng", ["Subtitles"]),
    ]
    assert item.has_webresource == [
        "https://example.org/objects/item-001",
        "https://example.org/stream/item-001.mp4",
    ]


def test_digital_carrier_becomes_the_matching_format_classes(input_path):
    efi_records = records_for(input_path)
    item = next(r for r in efi_records if r.has_identifier[0].id == "ITEM-003")
    assert [(f.category, f.type) for f in item.has_format] == [
        ("avefi:Optical", "DVD"),
        ("avefi:DigitalFile", "MP4"),
        ("avefi:DigitalFileEncoding", "MPEG4"),
    ]


def test_referenced_events_are_resolved(input_path):
    """The referenced entities follow the creation in the document."""
    efi_records = records_for(input_path)
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "Die Brücke"
    )
    shooting = next(
        e for e in work.has_event if e.type == "OutdoorShootingEvent"
    )
    assert shooting.has_date == "1959-04"
    assert shooting.located_in[0].has_name == "Cham"

    manifestation = next(
        r
        for r in efi_records
        if r.category == "avefi:Manifestation"
        and r.described_by.has_source_key == ["MAN-001"]
    )
    publication = manifestation.has_event[0]
    assert publication.type == "ReleaseEvent"
    assert publication.has_date == "1959-10-22"
    assert publication.has_activity[0].type == "Publisher"


def test_a_repeated_production_year_does_not_duplicate_the_event(
    input_path,
):
    efi_records = records_for(input_path)
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "Die Brücke"
    )
    assert [e.has_date for e in work.has_event] == ["1959", "1959-04"]


def test_entity_without_an_identifier_falls_back_to_title_and_year(
    input_path,
):
    efi_records = records_for(input_path)
    work = next(
        r
        for r in efi_records
        if r.category == "avefi:WorkVariant"
        and r.has_primary_title.has_name == "Sanitätshunde"
    )
    assert work.has_identifier[0].id == (
        f"{local_identifier('Sanitätshunde__1916')}_work"
    )
    assert work.described_by[0].has_source_key == ["Sanitätshunde__1916"]


def test_a_single_entity_document_is_accepted(tmp_path):
    """A document may carry one efgEntity as its root element."""
    source = tmp_path / "single.xml"
    source.write_text(SINGLE_ENTITY, encoding="utf-8")
    efi_records = en15907.efi_import(source)
    assert [r.category for r in efi_records] == [
        "avefi:WorkVariant",
        "avefi:Manifestation",
        "avefi:Item",
    ]


class TestReporting:
    def test_the_placeholder_issuer_is_reported(self, input_path):
        report = report_for(input_path)
        entries = [
            entry
            for entry in report.entries
            if entry.source_field == "profile issuer_info"
        ]
        assert len(entries) == 1, "Expected exactly one issuer warning"
        assert entries[0].severity == "warning"
        assert "ISIL" in entries[0].message

    def test_an_entity_that_is_not_a_holding_is_reported(self, input_path):
        report = report_for(input_path)
        skipped = [
            entry
            for entry in report.entries
            if entry.source_field == "efgEntity/person"
        ]
        assert skipped, "The person entity must appear in the report"
        assert "skipped" in skipped[0].message

    def test_an_unknown_carrier_is_reported(self, input_path):
        report = report_for(input_path)
        assert any(
            entry.severity == "warning"
            and entry.raw_value == "Nitratfilm"
            and entry.target_field == "has_format"
            for entry in report.entries
        )

    def test_an_unknown_language_tag_is_reported(self, input_path):
        report = report_for(input_path)
        assert any(
            entry.severity == "warning"
            and entry.raw_value == "xx"
            and entry.target_field == "in_language.code"
            for entry in report.entries
        )

    def test_an_agent_in_an_unmapped_role_is_reported(self, input_path):
        report = report_for(input_path)
        roles = {
            entry.raw_value
            for entry in report.entries
            if entry.target_field == "has_event.has_activity"
            and entry.severity == "warning"
        }
        assert {"Cinematographer", "Production company"} <= roles

    def test_an_item_that_is_not_a_moving_image_is_reported(self, input_path):
        report = report_for(input_path)
        assert any(
            entry.record_id == "ITEM-900"
            and entry.source_field == "item/type"
            and entry.severity == "warning"
            for entry in report.entries
        )

    def test_the_work_description_is_reported_not_dropped(self, input_path):
        report = report_for(input_path)
        assert any(
            entry.source_field == "avcreation/description"
            and entry.raw_value.startswith("Sieben Jungen")
            for entry in report.entries
        )


class TestProfile:
    def test_the_work_key_is_configurable(self, input_path):
        profile = dataclasses.replace(
            en15907.PROFILE, work_key_fields=("title", "production_year")
        )
        efi_records = mapping.efi_import(
            input_path("sample_data.xml"), profile
        )
        works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
        assert sorted(w.has_identifier[0].id for w in works) == [
            f"{local_identifier('Brücke, Die__1959')}_work",
            f"{local_identifier('Sanitätshunde__1916')}_work",
        ]

    def test_an_unknown_work_key_field_is_an_error(self, input_path):
        profile = dataclasses.replace(
            en15907.PROFILE, work_key_fields=("nonsense",)
        )
        with pytest.raises(ValueError, match="Unknown work key field"):
            mapping.efi_import(input_path("sample_data.xml"), profile)

    def test_the_description_can_become_a_manifestation_note(self, input_path):
        profile = dataclasses.replace(
            en15907.PROFILE, work_description_target="manifestation_note"
        )
        efi_records = mapping.efi_import(
            input_path("sample_data.xml"), profile
        )
        manifestation = next(
            r
            for r in efi_records
            if r.category == "avefi:Manifestation"
            and r.described_by.has_source_key == ["MAN-001"]
        )
        assert "Sieben Jungen verteidigen eine Brücke." in (
            manifestation.has_note
        )

    def test_an_unknown_description_target_is_an_error(self, input_path):
        profile = dataclasses.replace(
            en15907.PROFILE, work_description_target="nonsense"
        )
        with pytest.raises(
            ValueError, match="Unknown work_description_target"
        ):
            mapping.efi_import(input_path("sample_data.xml"), profile)

    def test_a_real_profile_replaces_the_placeholder_issuer(self, input_path):
        profile = EfgProfile(
            issuer_info={
                "has_issuer_id": "https://w3id.org/isil/XX-EXAMPLE",
                "has_issuer_name": "Example Film Archive",
            }
        )
        report = ConversionReport()
        with collecting(report):
            efi_records = mapping.efi_import(
                input_path("sample_data.xml"), profile
            )
        assert not any(
            entry.source_field == "profile issuer_info"
            for entry in report.entries
        )
        assert (
            efi_records[0].described_by[0].has_issuer_id
            == "https://w3id.org/isil/XX-EXAMPLE"
        )


def broken_copy(input_path, tmp_path, old, new, name="broken.xml"):
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    assert old in source
    target = tmp_path / name
    target.write_text(source.replace(old, new, 1), encoding="utf-8")
    return target


def test_decades_are_reported_as_unconvertible(tmp_path, input_path):
    """The contract reserves the decade mapping for after agreement."""
    broken = broken_copy(
        input_path,
        tmp_path,
        "<productionYear>1916</productionYear>",
        "<productionYear>50er Jahre</productionYear>",
        "decade.xml",
    )
    report = ConversionReport()
    with collecting(report), pytest.raises(NormalisationError):
        en15907.efi_import(broken)
    assert any(
        entry.severity == "error" and "Decade" in entry.message
        for entry in report.entries
    )


def test_unmappable_date_raises(tmp_path, input_path):
    """A date that cannot be mapped must not be silently dropped."""
    broken = broken_copy(
        input_path,
        tmp_path,
        "<productionYear>1959</productionYear>",
        "<productionYear>irgendwann</productionYear>",
    )
    with pytest.raises(NormalisationError):
        en15907.efi_import(broken)


def test_one_bad_entity_does_not_cost_the_whole_file(tmp_path, input_path):
    """File level containment would lose every record of an export."""
    broken = broken_copy(
        input_path,
        tmp_path,
        "<productionYear>1959</productionYear>",
        "<productionYear>irgendwann</productionYear>",
        "partly_broken.xml",
    )
    report = ConversionReport()
    with collecting(report):
        records = en15907.efi_import(broken, continue_on_error=True)
    assert records, "The remaining entities must survive"
    assert any(
        entry.severity == "error" and entry.record_id == "FILM-001"
        for entry in report.entries
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
        for assumption in mapping.ASSUMPTIONS:
            assert assumption in markdown


class TestModuleEntryPoint:
    """`python -m efi_conv.en15907 INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            en15907.main([str(input_path("sample_data.xml")), str(target)])
            == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert en15907.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        en15907.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(records_for(input_path)), indent=2
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert en15907.main(["--help"]) == 0
        assert "efi-conv from -f en15907" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert en15907.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            en15907.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )


def test_module_interface_is_complete():
    """`efi-conv from --list-formats` reads these from the module."""
    assert en15907.DESCRIPTION
    assert en15907.INPUT_FORMAT
    assert set(en15907.ISSUER_INFO) == {
        "has_issuer_id",
        "has_issuer_name",
    }


def test_mapping_documentation_is_up_to_date():
    """MAPPING.md is generated; it must not be edited by hand."""
    generated = mapping.render_mapping_markdown()
    committed = (
        pathlib.Path(mapping.__file__).parent / "MAPPING.md"
    ).read_text(encoding="utf-8")
    assert committed == generated, "Regenerate MAPPING.md from MAPPING_RULES"
