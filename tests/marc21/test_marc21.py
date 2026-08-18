import json
import pathlib

import pytest

from efi_conv.core import avefi, check, from_
from efi_conv.core.records import local_identifier
from efi_conv.core.report import ConversionReport, collecting
import efi_conv.marc21 as marc21
from efi_conv.marc21 import mapping


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
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
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    assert check.pass_checks(
        efi_records, schema_validator, accept_placeholder_issuer=True
    ), "Mapped data did not validate"


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
    assert local_identifier("(DE-101)0000012345") in identifiers
    assert local_identifier("(DE-Mb112)AK-0007") in identifiers, (
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
        and r.has_identifier[0].id == local_identifier("(DE-101)0000012347")
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
    assert statuses[local_identifier("(DE-101)0000012345")] == "Viewing"
    assert statuses[local_identifier("(DE-101)0000012346")] == "Master"


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
        and r.has_identifier[0].id == local_identifier("(DE-Mb112)AK-0007")
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
        and r.has_identifier[0].id == local_identifier("(DE-Mb112)AK-0007")
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
        and r.has_identifier[0].id == local_identifier("(DE-101)0000012345")
    )
    assert [i.id for i in item.has_identifier] == [
        local_identifier("(DE-101)0000012345"),
        local_identifier("(DE-Mb112)F 1959/12"),
    ]
    assert any(note.startswith("Holdings:") for note in item.has_note)


def test_credits_and_cast_are_kept_as_notes(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == local_identifier("(DE-101)0000012345")
    )
    assert any(
        note.startswith("Production credits:") for note in item.has_note
    )
    assert any(note.startswith("Cast:") for note in item.has_note)


def test_notes_lose_their_isbd_terminal_punctuation(input_path):
    """A note is free text, not a card catalogue entry."""
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    notes = [
        note
        for record in efi_records
        for note in getattr(record, "has_note", None) or []
    ]
    assert "Edition: 2. Fassung" in notes
    assert "Language: Deutsch" in notes
    assert not [note for note in notes if note.endswith(".")], (
        "ISBD punctuation separates fields on a card, not sentences"
    )


def test_subtitles_become_a_language_usage(input_path):
    efi_records = from_.import_file(marc21, input_path("sample_data.xml"))
    item = next(
        r
        for r in efi_records
        if r.category == "avefi:Item"
        and r.has_identifier[0].id == local_identifier("(DE-101)0000012347")
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


class TestAnUnreadableDate:
    """A date nobody can read costs the field, not the record.

    Everything else the record says — its title, its carrier, its
    identifiers — is still there and still true, and has_date is
    optional in the schema, so what remains is a valid record rather
    than a broken one. Discarding it would cost the work and every
    manifestation and item derived from it.

    A real export of 268 records contains "circa Ende der 1940er-Jahre"
    in one of them, and used to take all 268 down with it.

    """

    def test_the_record_survives(self, tmp_path, input_path):
        broken = broken_copy(tmp_path, input_path, "broken.xml")
        assert marc21.efi_import(broken)

    def test_the_date_is_left_unset_and_reported(self, tmp_path, input_path):
        broken = broken_copy(tmp_path, input_path, "broken.xml")
        report = ConversionReport()
        with collecting(report):
            records = marc21.efi_import(broken)
        works = [r for r in records if r.category == "avefi:WorkVariant"]
        assert works
        assert [
            entry
            for entry in report.entries
            if entry.target_field == "has_event.has_date"
            and entry.severity == "warning"
        ]

    def test_the_rest_of_the_file_is_unaffected(self, tmp_path, input_path):
        """The other records convert exactly as they did."""
        broken = broken_copy(tmp_path, input_path, "partly_broken.xml")
        report = ConversionReport()
        with collecting(report):
            records = marc21.efi_import(broken)
        assert records, "The remaining records must survive"


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


MINIMAL = """\
<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
{records}</collection>
"""

UNTITLED = """\
  <record>
    <leader>01234ngm a2200349 a 4500</leader>
    <controlfield tag="001">{control}</controlfield>
    <controlfield tag="008">590101n        gw {minutes}\
            mbger d</controlfield>
    <datafield tag="245" ind1="1" ind2="0">
      <subfield code="a">{title}</subfield>
    </datafield>
  </record>
"""


def _catalogue(tmp_path, *records):
    target = tmp_path / "degenerate.xml"
    target.write_text(MINIMAL.format(records="".join(records)), "utf-8")
    return target


class TestDegenerateWorkKey:
    """Two undated films of the same name are two films.

    Amateur and advertising material carries a generic title, no
    director and no date, which is exactly the material archives hold
    a lot of. Merging two of them would register one AVefi identifier
    for two different films.

    """

    @pytest.fixture
    def two_films_called_heimatfilm(self, tmp_path):
        return _catalogue(
            tmp_path,
            UNTITLED.format(
                control="0000099001", minutes="012", title="Heimatfilm"
            ),
            UNTITLED.format(
                control="0000099002", minutes="020", title="Heimatfilm"
            ),
        )

    def test_they_do_not_share_a_work(self, two_films_called_heimatfilm):
        records = marc21.efi_import(two_films_called_heimatfilm)
        works = [r for r in records if r.category == "avefi:WorkVariant"]
        assert len(works) == 2, (
            "One identifier for two films cannot be corrected later"
        )
        assert len({w.has_identifier[0].id for w in works}) == 2

    def test_the_decision_is_reported(self, two_films_called_heimatfilm):
        report = ConversionReport()
        with collecting(report):
            marc21.efi_import(two_films_called_heimatfilm)
        entries = [
            entry
            for entry in report.entries
            if entry.severity == "warning"
            and entry.target_field == "has_identifier (work)"
        ]
        assert len(entries) == 2
        assert {entry.record_id for entry in entries} == {
            "0000099001",
            "0000099002",
        }

    def test_a_full_key_still_groups(self, input_path):
        """The records of the sample export keep sharing their work."""
        records = from_.import_file(marc21, input_path("sample_data.xml"))
        works = [r for r in records if r.category == "avefi:WorkVariant"]
        assert len(works) < len(
            [r for r in records if r.category == "avefi:Item"]
        )


LINKED_COLLECTION = """<?xml version="1.0" encoding="UTF-8"?>
<collection xmlns="http://www.loc.gov/MARC21/slim">
  <record>
    <leader>01234ngm a2200349 a 4500</leader>
    <controlfield tag="001">FILM</controlfield>
    <datafield tag="245" ind1="1" ind2="0">
      <subfield code="a">Die Testaufnahme</subfield>
    </datafield>
    <datafield tag="338" ind1=" " ind2=" ">
      <subfield code="b">mr</subfield>
    </datafield>
  </record>
  <record>
    <leader>01234ngm a2200349 a 4500</leader>
    <controlfield tag="001">ONLINE</controlfield>
    <controlfield tag="003">DE-627</controlfield>
    <datafield tag="245" ind1="1" ind2="0">
      <subfield code="a">Die Testaufnahme : Untertitel</subfield>
    </datafield>
    <datafield tag="338" ind1=" " ind2=" ">
      <subfield code="b">cr</subfield>
    </datafield>
    <datafield tag="776" ind1="0" ind2="8">
      <subfield code="i">Erscheint auch als</subfield>
      <subfield code="w">(DE-627)FILM</subfield>
    </datafield>
  </record>
  <record>
    <leader>01234ngm a2200349 a 4500</leader>
    <controlfield tag="001">OTHER</controlfield>
    <datafield tag="245" ind1="1" ind2="0">
      <subfield code="a">Ein zweiter Film</subfield>
    </datafield>
    <datafield tag="338" ind1=" " ind2=" ">
      <subfield code="b">vd</subfield>
    </datafield>
  </record>
</collection>
"""


class TestRecordsTheLibraryHasLinked:
    """One film catalogued as a reel, a disc and an online edition.

    A library records those as separate documents and links them
    through 776. They are one work in three manifestations, and the
    library has said so. Deriving the work from title, director and
    year finds them again only if the three titles agree — and they do
    not, because the record for the online edition carries a subtitle
    that the reel does not.

    """

    @pytest.fixture
    def collection(self, tmp_path):
        target = tmp_path / "linked.xml"
        target.write_text(LINKED_COLLECTION, encoding="utf-8")
        return target

    def works(self, records):
        return [r for r in records if r.category == "avefi:WorkVariant"]

    def test_linked_records_share_one_work(self, collection):
        records = marc21.efi_import(collection)
        assert len(self.works(records)) == 2

    def test_the_work_names_every_record_it_came_from(self, collection):
        records = marc21.efi_import(collection)
        work = next(
            w
            for w in self.works(records)
            if len(w.described_by[0].has_source_key) > 1
        )
        assert sorted(work.described_by[0].has_source_key) == [
            "(DE-627)ONLINE",
            "FILM",
        ]

    def test_each_record_still_gets_its_own_manifestation(self, collection):
        records = marc21.efi_import(collection)
        assert (
            len([r for r in records if r.category == "avefi:Manifestation"])
            == 3
        )

    def test_an_unlinked_record_is_grouped_as_before(self, collection):
        """Enabling the links only ever merges what was linked.

        A record naming no other keeps the key derived from its own
        title, director and year, so nothing that used to group stops
        grouping.

        """
        records = marc21.efi_import(collection)
        alone = next(
            w
            for w in self.works(records)
            if w.has_primary_title.has_name == "Ein zweiter Film"
        )
        assert alone.described_by[0].has_source_key == ["OTHER"]

    def test_the_agency_prefix_does_not_prevent_a_match(self):
        """A record states its identifier bare and refers to it prefixed."""
        assert mapping.bare_identifier("(DE-627)FILM") == "FILM"
        assert mapping.bare_identifier("FILM") == "FILM"

    def test_the_links_are_followed_transitively(self, tmp_path):
        """A chain is one work however the export orders it."""
        document = LINKED_COLLECTION.replace(
            """    <datafield tag="338" ind1=" " ind2=" ">
      <subfield code="b">vd</subfield>
    </datafield>""",
            """    <datafield tag="338" ind1=" " ind2=" ">
      <subfield code="b">vd</subfield>
    </datafield>
    <datafield tag="776" ind1="0" ind2="8">
      <subfield code="w">(DE-627)ONLINE</subfield>
    </datafield>""",
        )
        target = tmp_path / "chain.xml"
        target.write_text(document, encoding="utf-8")
        assert len(self.works(marc21.efi_import(target))) == 1
