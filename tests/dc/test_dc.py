import dataclasses
import json
import pathlib

import pytest

from efi_conv.core import avefi, check, from_
from efi_conv.core.normalise import NormalisationError
from efi_conv.core.records import local_identifier
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.dc import mapping
from efi_conv.dc.profile import DcProfile


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(mapping, input_path("sample_data.xml"))
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
    efi_records = from_.import_file(mapping, input_path("sample_data.xml"))
    assert check.pass_checks(
        efi_records, schema_validator, accept_placeholder_issuer=True
    ), "Mapped data did not validate"


def test_conversion_is_idempotent(input_path):
    """Converting the same input twice must give identical output."""
    first = avefi.dumps(
        avefi.sort_records(
            from_.import_file(mapping, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    second = avefi.dumps(
        avefi.sort_records(
            from_.import_file(mapping, input_path("sample_data.xml"))
        ),
        indent=2,
    )
    assert first == second


def test_every_record_yields_all_three_levels(input_path):
    """Dublin Core cannot group, so nothing is shared between records."""
    efi_records = from_.import_file(mapping, input_path("sample_data.xml"))
    categories = [record.category for record in efi_records]
    assert categories.count("avefi:WorkVariant") == 2
    assert categories.count("avefi:Manifestation") == 2
    assert categories.count("avefi:Item") == 2


def test_the_three_levels_are_reported_as_asserted(input_path):
    """The weakest part of the mapping has to be the loudest."""
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mapping, input_path("sample_data.xml"))
    asserted = [
        entry
        for entry in report.entries
        if entry.severity == "warning"
        and "does not distinguish work" in entry.message
    ]
    assert len(asserted) == 2, (
        "Every converted record must say that its levels are asserted"
    )


def test_placeholder_issuer_is_reported_once_per_run(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mapping, input_path("sample_data.xml"))
    placeholder = [
        entry
        for entry in report.entries
        if entry.raw_value == mapping.PLACEHOLDER_ISSUER_ID
    ]
    assert len(placeholder) == 1
    assert placeholder[0].severity == "warning"
    assert "ISIL" in placeholder[0].message


def test_a_record_of_another_type_is_skipped_and_reported(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mapping, input_path("sample_data.xml"))
    skipped = [
        entry for entry in report.entries if entry.record_id == "OAI-0003"
    ]
    assert skipped, "The photograph must appear in the report"
    assert "not a film" in skipped[0].message


def test_a_record_without_a_type_is_skipped_with_a_warning(input_path):
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mapping, input_path("sample_data.xml"))
    skipped = [
        entry for entry in report.entries if entry.record_id == "OAI-0004"
    ]
    assert skipped and skipped[0].severity == "warning"
    assert "no dc:type" in skipped[0].message


@pytest.mark.parametrize(
    "source_field",
    ["dc:description", "dc:coverage", "dc:rights", "dc:contributor"],
)
def test_every_dropped_element_is_reported(input_path, source_field):
    """Nothing may disappear in silence, least of all here."""
    report = ConversionReport()
    with collecting(report):
        from_.import_file(mapping, input_path("sample_data.xml"))
    assert [
        entry
        for entry in report.entries
        if entry.source_field == source_field and entry.severity == "warning"
    ]


def test_creator_is_reported_rather_than_read_as_the_director(input_path):
    report = ConversionReport()
    with collecting(report):
        records = from_.import_file(mapping, input_path("sample_data.xml"))
    activities = [
        activity
        for record in records
        for event in record.has_event
        for activity in event.has_activity
        if activity.category == "avefi:DirectingActivity"
    ]
    assert not activities, (
        "Dublin Core does not say that a creator directed the film"
    )
    assert [
        entry
        for entry in report.entries
        if entry.source_field == "dc:creator"
        and entry.raw_value == "Wicki, Bernhard"
    ]


def test_creator_becomes_the_director_when_the_profile_says_so(input_path):
    profile = dataclasses.replace(mapping.PROFILE, creator_is_director=True)
    records = mapping.convert(input_path("sample_data.xml"), profile)
    agents = [
        agent.has_name
        for record in records
        for event in record.has_event
        for activity in event.has_activity
        if activity.category == "avefi:DirectingActivity"
        for agent in activity.has_agent
    ]
    assert agents == ["Wicki, Bernhard"]


def test_a_uri_identifier_is_preferred_as_the_source_key(input_path):
    records = from_.import_file(mapping, input_path("sample_data.xml"))
    items = [r for r in records if r.category == "avefi:Item"]
    keys = {
        key
        for item in items
        for key in (item.described_by.has_source_key or [])
    }
    assert "https://example.org/oai/film/0001" in keys
    assert "OAI-0001" not in keys, (
        "A bare local number must lose against a URI"
    )
    with_uri = next(
        item
        for item in items
        if "https://example.org/oai/film/0001"
        in item.described_by.has_source_key
    )
    assert [i.id for i in with_uri.has_identifier] == [
        local_identifier("https://example.org/oai/film/0001"),
        local_identifier("OAI-0001"),
    ]


def test_relation_and_source_become_webresources_only_when_uris(
    input_path,
):
    report = ConversionReport()
    with collecting(report):
        records = from_.import_file(mapping, input_path("sample_data.xml"))
    links = sorted(
        link
        for record in records
        for link in getattr(record, "has_webresource", []) or []
    )
    assert links == [
        "https://example.org/collection/0001",
        "https://example.org/related/0001",
    ]
    assert [
        entry
        for entry in report.entries
        if entry.source_field == "dc:relation"
        and entry.raw_value == "Teil der Sammlung Werbefilm"
    ]


def test_the_format_vocabulary_is_applied_and_the_rest_reported(
    input_path,
):
    report = ConversionReport()
    with collecting(report):
        records = from_.import_file(mapping, input_path("sample_data.xml"))
    formats = [
        entry.type
        for record in records
        for entry in getattr(record, "has_format", []) or []
    ]
    assert formats == ["35mmFilm"]
    assert [
        entry
        for entry in report.entries
        if entry.source_field == "dc:format" and entry.raw_value == "video/mp4"
    ]


def test_subject_terms_become_subjects_rather_than_genres(input_path):
    """dc:subject is the topic of the resource, not its genre."""
    records = from_.import_file(mapping, input_path("sample_data.xml"))
    works = [r for r in records if r.category == "avefi:WorkVariant"]
    subjects = [
        subject.has_name for work in works for subject in work.has_subject
    ]
    genres = [genre.has_name for work in works for genre in work.has_genre]
    assert subjects == ["Dokumentarfilm", "Nachkriegszeit"]
    assert "Nachkriegszeit" not in genres, (
        "A post-war period is a topic, not a genre"
    )


def test_a_type_term_beside_the_film_filter_is_still_a_genre(input_path):
    """dc:type says what kind of resource it is, which is a genre."""
    records = from_.import_file(mapping, input_path("sample_data.xml"))
    genres = [
        genre.has_name
        for record in records
        if record.category == "avefi:WorkVariant"
        for genre in record.has_genre
    ]
    assert genres == ["Werbefilm"], (
        "MovingImage identified the record as film and is consumed"
    )


def test_language_is_mapped_with_the_usage_from_the_profile(input_path):
    records = from_.import_file(mapping, input_path("sample_data.xml"))
    languages = [
        (language.code, tuple(language.usage))
        for record in records
        for language in getattr(record, "in_language", []) or []
    ]
    assert languages == [
        ("ger", ("SpokenLanguage",)),
        ("ger", ("SpokenLanguage",)),
    ]


def test_a_bare_oai_dc_root_is_read(tmp_path):
    """One record per file is as common as a harvested wrapper."""
    single = tmp_path / "single.xml"
    single.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<oai_dc:dc"
        ' xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "  <dc:title>Einzelsatz</dc:title>\n"
        "  <dc:type>MovingImage</dc:type>\n"
        "  <dc:identifier>OAI-9001</dc:identifier>\n"
        "</oai_dc:dc>\n",
        encoding="utf-8",
    )
    records = mapping.efi_import(single)
    assert [record.category for record in records] == [
        "avefi:WorkVariant",
        "avefi:Manifestation",
        "avefi:Item",
    ]


def test_a_record_without_an_identifier_is_an_error(tmp_path):
    source = tmp_path / "no_id.xml"
    source.write_text(
        "<oai_dc:dc"
        ' xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Namenlos</dc:title>"
        "<dc:type>MovingImage</dc:type>"
        "</oai_dc:dc>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="without dc:identifier"):
        mapping.efi_import(source)


def test_a_record_without_a_title_is_an_error(tmp_path):
    source = tmp_path / "no_title.xml"
    source.write_text(
        "<oai_dc:dc"
        ' xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:identifier>OAI-9002</dc:identifier>"
        "<dc:type>MovingImage</dc:type>"
        "</oai_dc:dc>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no dc:title"):
        mapping.efi_import(source)


def test_unmappable_date_raises(tmp_path, input_path):
    """A date that cannot be mapped must not be silently dropped."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "broken.xml"
    broken.write_text(
        source.replace("<dc:date>1959", "<dc:date>irgendwann"),
        encoding="utf-8",
    )
    with pytest.raises(NormalisationError):
        mapping.efi_import(broken)


def test_one_bad_record_does_not_cost_the_whole_file(tmp_path, input_path):
    """File level containment would lose every record of an export."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "partly_broken.xml"
    broken.write_text(
        source.replace("<dc:date>1959", "<dc:date>irgendwann"),
        encoding="utf-8",
    )
    report = ConversionReport()
    with collecting(report):
        records = mapping.efi_import(broken, continue_on_error=True)
    assert records, "The remaining records must survive"
    assert any(
        entry.severity == "error"
        and entry.record_id == "https://example.org/oai/film/0001"
        for entry in report.entries
    )


def test_decades_are_reported_as_unconvertible(tmp_path, input_path):
    """The contract reserves the decade mapping for after agreement."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    broken = tmp_path / "decade.xml"
    broken.write_text(
        source.replace("<dc:date>1959", "<dc:date>50er Jahre"),
        encoding="utf-8",
    )
    report = ConversionReport()
    with collecting(report), pytest.raises(NormalisationError):
        mapping.efi_import(broken)
    assert any(
        entry.severity == "error" and "Decade" in entry.message
        for entry in report.entries
    )


def test_the_film_filter_can_be_switched_off(input_path):
    """An export of nothing but film needs no filter."""
    profile = dataclasses.replace(mapping.PROFILE, film_type_terms=frozenset())
    records = mapping.convert(input_path("sample_data.xml"), profile)
    keys = {
        key
        for record in records
        for described in (
            record.described_by
            if isinstance(record.described_by, list)
            else [record.described_by]
        )
        for key in (described.has_source_key or [])
    }
    assert {"OAI-0003", "OAI-0004"} <= keys


def test_the_profile_default_is_deliberately_cautious():
    """Guessing a role or an issuer is worse than reporting a gap."""
    profile = DcProfile(issuer_info=mapping.ISSUER_INFO)
    assert profile.creator_is_director is False
    assert profile.map_decades is False
    assert profile.format_map == {}


class TestMappingDocumentation:
    def test_rule_ids_are_unique(self):
        ids = [rule.id for rule in mapping.MAPPING_RULES]
        assert len(ids) == len(set(ids))

    def test_every_rule_is_rendered(self):
        markdown = mapping.render_mapping_markdown()
        for rule in mapping.MAPPING_RULES:
            assert f"`{rule.id}`" in markdown
            assert rule.source_path.split(",")[0] in markdown

    def test_table_has_a_header(self):
        markdown = mapping.render_mapping_markdown()
        assert markdown.splitlines()[0].startswith("# ")
        assert "| Rule |" in markdown

    def test_the_limits_are_stated_rather_than_glossed_over(self):
        markdown = mapping.render_mapping_markdown()
        assert "cannot express the distinction" in markdown
        assert "placeholder" in markdown


class TestModuleEntryPoint:
    """`python -m efi_conv.dc.mapping INPUT [OUTPUT]`."""

    def test_writes_to_a_file(self, tmp_path, input_path):
        target = tmp_path / "out.json"
        assert (
            mapping.main([str(input_path("sample_data.xml")), str(target)])
            == 0
        )
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_writes_to_stdout(self, capsys, input_path):
        assert mapping.main([str(input_path("sample_data.xml"))]) == 0
        assert json.loads(capsys.readouterr().out)

    def test_output_matches_the_command_line_interface(
        self, tmp_path, input_path
    ):
        target = tmp_path / "out.json"
        mapping.main([str(input_path("sample_data.xml")), str(target)])
        expected = avefi.dumps(
            avefi.sort_records(
                from_.import_file(mapping, input_path("sample_data.xml"))
            ),
            indent=2,
        )
        assert target.read_text(encoding="utf-8") == expected

    def test_help_is_available(self, capsys):
        assert mapping.main(["--help"]) == 0
        assert "efi-conv from -f dc" in capsys.readouterr().out

    def test_no_arguments_is_an_error(self):
        assert mapping.main([]) == 2

    def test_too_many_arguments_is_an_error(self, input_path):
        assert (
            mapping.main(
                [str(input_path("sample_data.xml")), "a.json", "b.json"]
            )
            == 2
        )


def test_mapping_documentation_is_up_to_date():
    """MAPPING.md is generated; it must not be edited by hand."""
    generated = mapping.render_mapping_markdown()
    committed = (
        pathlib.Path(mapping.__file__).parent / "MAPPING.md"
    ).read_text(encoding="utf-8")
    assert committed == generated, "Regenerate MAPPING.md from MAPPING_RULES"
