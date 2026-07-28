import json
import pathlib

import pytest

from efi_conv import ebucore
from efi_conv.core import avefi, check, from_
from efi_conv.core.normalise import NormalisationError
from efi_conv.core.records import local_identifier
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.ebucore import mapping, profile


def convert(input_path):
    """Convert the fixture through the common importer interface."""
    return from_.import_file(ebucore, input_path("sample_data.xml"))


def report_for(input_path) -> ConversionReport:
    """Convert the fixture and return the collected report."""
    report = ConversionReport()
    with collecting(report):
        convert(input_path)
    return report


def entries_for(report, record_id=None, source_field=None):
    """Return the report entries matching the given criteria."""
    return [
        entry
        for entry in report.entries
        if (record_id is None or entry.record_id == record_id)
        and (source_field is None or entry.source_field == source_field)
    ]


def test_map_to_efi(input_path, expected_output):
    efi_records = convert(input_path)
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
    efi_records = convert(input_path)
    assert check.pass_checks(
        efi_records, schema_validator, accept_placeholder_issuer=True
    ), "Mapped data did not validate"


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(avefi.sort_records(convert(input_path)), indent=2)
    second = avefi.dumps(avefi.sort_records(convert(input_path)), indent=2)
    assert first == second


def test_records_of_one_programme_share_a_work(input_path):
    """Two carriers of the same programme are one work, not two.

    EBUCore describes an editorial object together with the format it
    exists in, so an archive exporting a film print and its transfer
    ships two records for one film. Minting a work for each of them
    would register identifiers for carriers rather than for films.

    """
    efi_records = convert(input_path)
    categories = [record.category for record in efi_records]
    assert categories.count("avefi:Item") == 3
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 3

    works = [r for r in efi_records if r.category == "avefi:WorkVariant"]
    shared = next(
        w for w in works if w.has_primary_title.has_name == "Die Brücke"
    )
    assert sorted(shared.described_by[0].has_source_key) == [
        "EBU-0001",
        "EBU-0002",
    ]
    assert [title.has_name for title in shared.has_alternative_title] == [
        "The Bridge",
        "Die Bruecke (Fernsehfassung)",
    ]


def test_carriers_differing_get_their_own_manifestation(input_path):
    efi_records = convert(input_path)
    manifestations = [
        r for r in efi_records if r.category == "avefi:Manifestation"
    ]
    parents = {m.is_manifestation_of[0].id for m in manifestations}
    assert len(parents) == 2, "Manifestations must hang off their work"


def test_bracketed_title_becomes_supplied_devised(input_path):
    efi_records = convert(input_path)
    supplied = [
        record
        for record in efi_records
        if record.has_primary_title.type == "SuppliedDevisedTitle"
    ]
    assert supplied, "Expected the bracketed title to be marked as supplied"
    assert all(
        not record.has_primary_title.has_name.startswith("[")
        for record in supplied
    )


def test_start_and_end_year_become_an_interval(input_path):
    efi_records = convert(input_path)
    dates = [
        event.has_date
        for record in efi_records
        for event in record.has_event
        if event.has_date
    ]
    assert "1962/1965" in dates


def test_publication_history_becomes_a_broadcast_event(input_path):
    """EBUCore is a broadcast schema, so broadcast is the default."""
    efi_records = convert(input_path)
    events = [
        event
        for record in efi_records
        for event in record.has_event
        if record.category == "avefi:Manifestation"
    ]
    broadcast = [e for e in events if e.type == "BroadcastEvent"]
    assert len(broadcast) == 1
    assert broadcast[0].has_date == "1959-11-05"
    assert broadcast[0].located_in[0].has_name == "Deutschland"
    assert broadcast[0].has_activity[0].type == "Broadcaster"
    assert broadcast[0].has_activity[0].has_agent[0].has_name == "ARD"
    assert any(e.type == "ReleaseEvent" for e in events)


def test_profile_vocabularies_are_applied(input_path):
    efi_records = convert(input_path)
    items = {
        item.has_identifier[0].id: item
        for item in efi_records
        if item.category == "avefi:Item"
    }
    print_ = items["EBU-0001"]
    assert print_.has_colour_type == "BlackAndWhite"
    assert print_.has_sound_type == "Sound"
    assert print_.has_format[0].type == "35mmFilm"
    assert print_.in_language[0].code == "ger"
    assert print_.in_language[0].usage == ["SpokenLanguage"]

    tape = items["EBU-0002"]
    assert tape.has_format[0].type == "DigitalBetacam"
    assert tape.has_frame_rate == "25fps"
    assert [language.code for language in tape.in_language] == ["ger", "eng"]

    file_ = items["EBU-0003"]
    assert file_.has_format[0].type == "MXF"


def test_genre_terms_are_split_into_form_and_genre(input_path):
    efi_records = convert(input_path)
    work = next(
        record
        for record in efi_records
        if record.category == "avefi:WorkVariant"
        and record.has_primary_title.has_name == "Die Brücke"
    )
    assert list(work.has_form) == ["Feature"]
    assert [genre.has_name for genre in work.has_genre] == [
        "Feature",
        "Kriegsfilm",
    ], "The provider called the term a genre, so it stays one"
    assert [s.has_name for s in work.has_subject] == ["Nachkriegszeit"]


def test_durations_of_every_notation_are_mapped(input_path):
    """EBUCore states a duration in four alternative ways."""
    efi_records = convert(input_path)
    durations = {
        item.has_identifier[0].id: item.has_duration.has_value
        for item in efi_records
        if item.category == "avefi:Item" and item.has_duration
    }
    assert durations == {
        "EBU-0001": "PT01H43M00S",
        "EBU-0002": "PT01H43M12S",
        "EBU-0003": "PT00H12M00S",
    }


def test_placeholder_issuer_is_reported_once(input_path):
    """The shipped issuer is a placeholder and must not pass unnoticed."""
    report = report_for(input_path)
    warnings = [
        entry
        for entry in report.entries
        if entry.source_field == "profile issuer_info"
    ]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert "placeholder" in warnings[0].message
    assert ebucore.ISSUER_INFO == profile.PLACEHOLDER_ISSUER_INFO


def test_unmapped_role_is_reported(input_path):
    report = report_for(input_path)
    roles = entries_for(report, "EBU-0001", "contributor/role/@typeLabel")
    assert roles and roles[0].severity == "warning"
    assert roles[0].raw_value == ["Camera Operator"]


def test_placeholder_agent_name_is_skipped_and_reported(input_path):
    report = report_for(input_path)
    entries = entries_for(report, "EBU-0003", "creator")
    assert entries and entries[0].raw_value == "unbekannt"


def test_unmappable_vocabulary_terms_are_reported(input_path):
    """A term without an AVefi equivalent must not vanish."""
    report = report_for(input_path)
    reported = [
        (entry.source_field, entry.raw_value)
        for entry in report.entries
        if entry.severity == "warning"
    ]
    assert ("format/medium/@typeLabel", "Hard disk") in reported
    assert (
        "format//technicalAttributeString",
        "Kolorierung",
    ) in reported
    assert ("language/dc:language", "qaa") in reported


def test_rights_and_parts_are_reported_as_out_of_scope(input_path):
    """AVefi has no home for either, so both have to be visible."""
    report = report_for(input_path)
    rights = entries_for(report, "EBU-0003", "rights")
    parts = entries_for(report, "EBU-0003", "part")
    assert rights and rights[0].raw_value == ["Rechte ungeklärt."]
    assert parts and parts[0].raw_value == 1


def test_technical_detail_is_reported(input_path):
    """The technical part of EBUCore is out of scope, not forgotten."""
    report = report_for(input_path)
    video = entries_for(report, "EBU-0002", "format/videoFormat")
    assert video and video[0].raw_value == ["height", "width"]
    formats = entries_for(report, "EBU-0003", "format")
    assert formats and formats[0].raw_value == ["fileName"]


def test_unmapped_core_elements_are_reported(input_path):
    report = report_for(input_path)
    core = entries_for(report, "EBU-0003", "coreMetadata")
    assert not core, "Nothing is left unmapped in that record"


RECORD = """\
  <ebuCoreMain xmlns="urn:ebu:metadata-schema:ebucore"
               xmlns:dc="http://purl.org/dc/elements/1.1/"
               version="1.10" xml:lang="de" documentId="{key}">
    <coreMetadata>
      <title><dc:title>{title}</dc:title></title>
      <identifier><dc:identifier>{key}</dc:identifier></identifier>
      <date><produced year="{year}"/></date>
      {relation}
    </coreMetadata>
  </ebuCoreMain>
"""


def two_records(tmp_path, name="related.xml"):
    """Write a document whose second record is part of the first."""
    target = tmp_path / name
    target.write_text(
        "<ebuCoreRecords>"
        + RECORD.format(
            key="EBU-COLLECTION-7",
            title="Werbefilmsammlung",
            year="1960",
            relation="",
        )
        + RECORD.format(
            key="EBU-0009",
            title="Ein Werbefilm",
            year="1962",
            relation="<isPartOf><dc:relation>EBU-COLLECTION-7"
            "</dc:relation></isPartOf>",
        )
        + "</ebuCoreRecords>",
        encoding="utf-8",
    )
    return target


def test_is_part_of_becomes_a_work_relation(tmp_path):
    """WorkVariant.is_part_of exists, so isPartOf is not a loss."""
    records = ebucore.efi_import(two_records(tmp_path))
    works = {
        record.described_by[0].has_source_key[0]: record
        for record in records
        if record.category == "avefi:WorkVariant"
    }
    assert [resource.id for resource in works["EBU-0009"].is_part_of] == [
        works["EBU-COLLECTION-7"].has_identifier[0].id
    ]


def test_an_unresolved_relation_is_reported_and_not_asserted(input_path):
    """AVefi rejects a reference resolving to no record in the set."""
    efi_records = convert(input_path)
    work = next(
        record
        for record in efi_records
        if record.category == "avefi:WorkVariant"
        and record.has_primary_title.has_name == "Ohne Titel, Werbefilm"
    )
    assert work.is_part_of == []
    report = report_for(input_path)
    assert [
        entry
        for entry in report.entries
        if entry.target_field == "is_part_of"
        and entry.raw_value == "EBU-COLLECTION-7"
        and entry.severity == "warning"
    ]


def test_further_identifiers_are_kept_on_the_item(input_path):
    """has_identifier is a list; an ISAN must not be thrown away."""
    efi_records = convert(input_path)
    item = next(
        record
        for record in efi_records
        if record.category == "avefi:Item"
        and record.described_by.has_source_key == ["EBU-0001"]
    )
    assert [resource.id for resource in item.has_identifier] == [
        local_identifier("EBU-0001"),
        local_identifier("ISAN 0000-0000-3A8D-0000-Z-0000-0000-6"),
    ]


def test_the_scheme_of_a_further_identifier_is_reported(input_path):
    report = report_for(input_path)
    entries = entries_for(report, "EBU-0001", "identifier")
    assert entries
    assert entries[0].raw_value["typeLabel"] == "ISAN"
    assert "no resource class" in entries[0].message


def test_a_description_is_reported_rather_than_noted(input_path):
    """The other converters refuse a description; so does this one."""
    efi_records = convert(input_path)
    notes = [
        note
        for record in efi_records
        for note in getattr(record, "has_note", None) or []
    ]
    assert notes == [], "A synopsis is not a note on a print"
    report = report_for(input_path)
    entries = entries_for(report, "EBU-0001", "description/dc:description")
    assert entries and entries[0].severity == "warning"


def test_a_file_size_becomes_an_extent(input_path):
    """Item.has_extent holds a size in bytes as a byte based unit."""
    efi_records = convert(input_path)
    item = next(
        record
        for record in efi_records
        if record.category == "avefi:Item"
        and record.described_by.has_source_key == ["EBU-0003"]
    )
    assert item.has_extent is not None
    assert item.has_extent.has_unit == "GigaByte"
    assert float(item.has_extent.has_value) == 4.5


def test_timecode_frames_are_reported(input_path):
    """ISODurationInHours cannot hold the frame count of a timecode."""
    report = report_for(input_path)
    entries = entries_for(report, "EBU-0002", "format/duration/timecode")
    assert entries and entries[0].raw_value == "01:43:12:10"


def test_metadata_provider_is_not_used_as_the_issuer(input_path):
    report = report_for(input_path)
    entries = entries_for(report, "EBU-0001", "ebuCoreMain/metadataProvider")
    assert entries and entries[0].raw_value == "Beispielarchiv"


def broken_copy(tmp_path, input_path, replacement, name):
    """Return a copy of the fixture with one date made unusable."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / name
    broken.write_text(
        source.replace("<dc:date>1959</dc:date>", replacement),
        encoding="utf-8",
    )
    return broken


def test_decades_are_reported_as_unconvertible(tmp_path, input_path):
    """The contract reserves the decade mapping for after agreement."""
    broken = broken_copy(
        tmp_path,
        input_path,
        "<dc:date>50er Jahre</dc:date>",
        "decade.xml",
    )
    report = ConversionReport()
    with collecting(report), pytest.raises(NormalisationError):
        ebucore.efi_import(broken)
    assert any(
        entry.severity == "error" and "Decade" in entry.message
        for entry in report.entries
    )


def test_unmappable_date_raises(tmp_path, input_path):
    """A date that cannot be mapped must not be silently dropped."""
    broken = broken_copy(
        tmp_path,
        input_path,
        "<dc:date>irgendwann</dc:date>",
        "broken.xml",
    )
    with pytest.raises(NormalisationError):
        ebucore.efi_import(broken)


def test_one_bad_record_does_not_cost_the_whole_file(tmp_path, input_path):
    """File level containment would lose every record of an export."""
    broken = broken_copy(
        tmp_path,
        input_path,
        "<dc:date>irgendwann</dc:date>",
        "partly_broken.xml",
    )
    report = ConversionReport()
    with collecting(report):
        records = ebucore.efi_import(broken, continue_on_error=True)
    assert records, "The remaining records must survive"
    assert any(
        entry.severity == "error" and entry.record_id == "EBU-0002"
        for entry in report.entries
    )


def test_a_single_record_document_is_accepted(tmp_path, input_path):
    """A provider may ship one ebuCoreMain element per file."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    start = source.index("<ebuCoreMain")
    end = source.index("</ebuCoreMain>") + len("</ebuCoreMain>")
    single = tmp_path / "single.xml"
    single.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + source[start:end],
        encoding="utf-8",
    )
    records = ebucore.efi_import(single)
    assert [record.category for record in records] == [
        "avefi:WorkVariant",
        "avefi:Manifestation",
        "avefi:Item",
    ]


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
    """`python -m efi_conv.ebucore INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            ebucore.main([str(input_path("sample_data.xml")), str(target)])
            == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert ebucore.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        ebucore.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(convert(input_path)), indent=2
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert ebucore.main(["--help"]) == 0
        assert "efi-conv from -f ebucore" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert ebucore.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            ebucore.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )


def test_module_interface_is_complete():
    """The common command line interface relies on these names."""
    assert ebucore.DESCRIPTION
    assert ebucore.INPUT_FORMAT
    assert set(ebucore.ISSUER_INFO) == {
        "has_issuer_id",
        "has_issuer_name",
    }
    assert callable(ebucore.efi_import)
    assert callable(ebucore.main)


def test_mapping_documentation_is_up_to_date():
    """MAPPING.md is generated; it must not be edited by hand."""
    generated = mapping.render_mapping_markdown()
    committed = (
        pathlib.Path(mapping.__file__).parent / "MAPPING.md"
    ).read_text(encoding="utf-8")
    assert committed == generated, "Regenerate MAPPING.md from MAPPING_RULES"
