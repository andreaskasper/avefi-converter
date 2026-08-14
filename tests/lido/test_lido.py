import json

import pytest

from efi_conv.core import avefi, check, from_
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.fmdu import lido as fmdu_lido
from efi_conv.lido import mapping


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
    # Four film records, two of them prints of the same film, plus one
    # poster that is not a film holding at all.
    assert categories.count("avefi:Item") == 4
    assert categories.count("avefi:WorkVariant") == 3
    assert categories.count("avefi:Manifestation") == 4

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
    assert len(parents) == 3, "Manifestations must hang off their work"


def test_accompanying_material_is_not_imported_as_film(input_path):
    """Only the records this conversion is about are in scope.

    This provider states what each record describes, so the poster is
    excluded by what it says it is rather than by an inference from
    the object it holds.

    """
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
    assert "not a record type" in skipped[0].message


def with_date(tmp_path, input_path, expression, name="dated.xml"):
    """Return the sample with one production date replaced."""
    source = input_path("sample_data.xml").read_text(encoding="utf-8")
    target = tmp_path / name
    target.write_text(
        source.replace(
            "<lido:displayDate>1962-65", f"<lido:displayDate>{expression}"
        ),
        encoding="utf-8",
    )
    return target


def test_decades_are_reported_as_unconvertible(tmp_path, input_path):
    """The contract reserves the decade mapping for after agreement."""
    report = ConversionReport()
    with collecting(report):
        records = fmdu_lido.efi_import(
            with_date(tmp_path, input_path, "50er Jahre")
        )
    assert records, "The record survives a date it cannot state"
    assert any(
        "Decade" in entry.message and "map_decades" in entry.message
        for entry in report.entries
    )


class TestAnUnreadableDate:
    """A date nobody can read costs the field, not the record.

    Everything else the source says about the copy — its title, its
    carrier, its identifiers, the handle it was registered under — is
    still there and still true. Discarding the record over one field
    would cost the work, every manifestation and every item derived
    from it, and `has_date` is optional in the schema, so what remains
    is a valid record rather than a broken one.

    """

    def test_the_record_survives(self, tmp_path, input_path):
        records = fmdu_lido.efi_import(
            with_date(tmp_path, input_path, "irgendwann")
        )
        assert [r for r in records if r.category == "avefi:WorkVariant"]

    def test_the_date_is_left_unset_and_reported(self, tmp_path, input_path):
        report = ConversionReport()
        with collecting(report):
            records = fmdu_lido.efi_import(
                with_date(tmp_path, input_path, "irgendwann")
            )
        work = next(
            r
            for r in records
            if r.category == "avefi:WorkVariant"
            and r.has_primary_title.has_name == "Ohne Titel, Werbefilm"
        )
        assert not [event for event in work.has_event if event.has_date], (
            "the work keeps its identity, only the date is gone"
        )
        assert [
            entry
            for entry in report.entries
            if entry.target_field == "has_event.has_date"
            and entry.severity == "warning"
            and "irgendwann" in str(entry.raw_value)
        ]

    def test_a_run_of_question_marks_states_that_no_date_is_known(
        self, tmp_path, input_path
    ):
        """A placeholder repeated is the same placeholder.

        Cataloguing systems fill a fixed width field with question
        marks; the reference data holds one of fifty six. A single one
        already means "no date given", so a run of them does too, and
        it is not a failure to report.

        """
        report = ConversionReport()
        with collecting(report):
            records = fmdu_lido.efi_import(
                with_date(tmp_path, input_path, "?" * 56)
            )
        assert records
        assert not [
            entry
            for entry in report.entries
            if entry.target_field == "has_event.has_date"
            and entry.severity in ("warning", "error")
        ], "a placeholder is not a conversion failure"
        assert [
            entry
            for entry in report.entries
            if entry.message == "Source states that no date is known"
        ], "but it is worth noting that the source said nothing"


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


class TestClassificationTypes:
    """LIDO leaves the lido:type of a classification to the provider.

    A provider labelling its classifications in German must be able to
    say so in the profile, rather than needing a converter of its own.

    """

    GERMAN_LABELS = """<?xml version="1.0" encoding="UTF-8"?>
<lido:lido xmlns:lido="http://www.lido-schema.org">
  <lido:lidoRecID lido:type="local">DE-0001</lido:lidoRecID>
  <lido:descriptiveMetadata xml:lang="de">
    <lido:objectClassificationWrap>
      <lido:objectWorkTypeWrap>
        <lido:objectWorkType>
          <lido:term xml:lang="de">Film</lido:term>
        </lido:objectWorkType>
      </lido:objectWorkTypeWrap>
      <lido:classificationWrap>
        <lido:classification lido:type="Farbe">
          <lido:term xml:lang="de">sw</lido:term>
        </lido:classification>
        <lido:classification lido:type="Traegerformat">
          <lido:term xml:lang="de">16mm</lido:term>
        </lido:classification>
        <lido:classification lido:type="Gattung">
          <lido:term xml:lang="de">Dokumentarfilm</lido:term>
        </lido:classification>
      </lido:classificationWrap>
    </lido:objectClassificationWrap>
    <lido:objectIdentificationWrap>
      <lido:titleWrap>
        <lido:titleSet lido:type="preferred">
          <lido:appellationValue xml:lang="de">Ein Test</lido:appellationValue>
        </lido:titleSet>
      </lido:titleWrap>
    </lido:objectIdentificationWrap>
  </lido:descriptiveMetadata>
</lido:lido>
"""

    def profile(self, **overrides):
        from efi_conv.lido import LidoProfile

        settings = {
            "issuer_info": {
                "has_issuer_id": "https://example.org/test",
                "has_issuer_name": "Test",
            },
            "colour_type_map": {"sw": "BlackAndWhite"},
            "format_map": {"16mm": "16mmFilm"},
        }
        settings.update(overrides)
        return LidoProfile(**settings)

    def convert(self, tmp_path, profile):
        source = tmp_path / "german.xml"
        source.write_text(self.GERMAN_LABELS, encoding="utf-8")
        return mapping.efi_import(source, profile)

    def test_german_labels_are_understood_by_default(self, tmp_path):
        records = self.convert(tmp_path, self.profile())
        item = next(r for r in records if r.category == "avefi:Item")
        assert str(item.has_colour_type) == "BlackAndWhite"
        assert [str(f.type) for f in item.has_format] == ["16mmFilm"]

    def test_a_consumed_classification_is_not_also_a_genre(self, tmp_path):
        records = self.convert(tmp_path, self.profile())
        work = next(r for r in records if r.category == "avefi:WorkVariant")
        assert [genre.has_name for genre in work.has_genre] == [
            "Dokumentarfilm"
        ]

    def test_a_provider_can_name_its_own_types(self, tmp_path):
        """Narrowing the profile must narrow what is consumed."""
        profile = self.profile(
            classification_types={"colour": ("farbe",), "format": ()}
        )
        records = self.convert(tmp_path, profile)
        item = next(r for r in records if r.category == "avefi:Item")
        work = next(r for r in records if r.category == "avefi:WorkVariant")
        assert str(item.has_colour_type) == "BlackAndWhite"
        assert item.has_format == []
        # The format classification is no longer consumed, so it stays
        # available as a genre instead of being lost.
        assert "16mm" in [genre.has_name for genre in work.has_genre]

    def test_an_unconfigured_term_is_reported(self, tmp_path):
        report = ConversionReport()
        with collecting(report):
            self.convert(tmp_path, self.profile(colour_type_map={"x": "y"}))
        assert any(
            entry.target_field == "colour" and entry.raw_value == "sw"
            for entry in report.entries
        )


class TestDocumentShapes:
    """A record must be found whatever wraps it."""

    RECORD = """<lido:lido xmlns:lido="http://www.lido-schema.org">
  <lido:lidoRecID lido:type="local">SHAPE-1</lido:lidoRecID>
  <lido:descriptiveMetadata xml:lang="de">
    <lido:objectClassificationWrap>
      <lido:objectWorkTypeWrap>
        <lido:objectWorkType>
          <lido:term xml:lang="de">Film</lido:term>
        </lido:objectWorkType>
      </lido:objectWorkTypeWrap>
    </lido:objectClassificationWrap>
    <lido:objectIdentificationWrap>
      <lido:titleWrap>
        <lido:titleSet lido:type="preferred">
          <lido:appellationValue xml:lang="de">Ein Film</lido:appellationValue>
        </lido:titleSet>
      </lido:titleWrap>
    </lido:objectIdentificationWrap>
  </lido:descriptiveMetadata>
</lido:lido>"""

    HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'
    WRAPPED = (
        HEADER
        + '<lido:lidoWrap xmlns:lido="http://www.lido-schema.org">\n'
        + RECORD
        + "\n</lido:lidoWrap>\n"
    )
    BARE = HEADER + RECORD + "\n"
    FOREIGN_WRAPPER = (
        HEADER + "<harvest>\n" + RECORD + "\n" + RECORD + "\n</harvest>\n"
    )

    @pytest.mark.parametrize(
        ("document", "expected"),
        [("WRAPPED", 1), ("BARE", 1), ("FOREIGN_WRAPPER", 2)],
    )
    def test_records_are_found(self, tmp_path, document, expected):
        source = tmp_path / "shape.xml"
        source.write_text(getattr(self, document), encoding="utf-8")
        assert len(mapping.parse_lido(source)) == expected

    def test_a_document_without_records_yields_none(self, tmp_path):
        source = tmp_path / "empty.xml"
        source.write_text(self.HEADER + "<somethingElse/>\n", encoding="utf-8")
        assert mapping.parse_lido(source) == []


class TestUnreadableDuration:
    """A running time nobody can read costs a field, not a record.

    Discarding the record would cost the work, the manifestation and
    the item derived from it, and with them everything the source said
    about the film.

    """

    def test_the_record_survives(self, lido_page, lido_record):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", duration="ungefähr eine Stunde"),
        )
        records = fmdu_lido.efi_import(source)
        assert [record.category for record in records] == [
            "avefi:WorkVariant",
            "avefi:Manifestation",
            "avefi:Item",
        ]

    def test_the_duration_is_left_unset_and_reported(
        self, lido_page, lido_record
    ):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", duration="ungefähr eine Stunde"),
        )
        report = ConversionReport()
        with collecting(report):
            records = fmdu_lido.efi_import(source)
        item = next(r for r in records if r.category == "avefi:Item")
        assert item.has_duration is None
        assert [
            entry
            for entry in report.entries
            if entry.target_field == "has_duration.has_value"
            and entry.severity == "warning"
        ]

    def test_an_iso_duration_is_read(self, lido_page, lido_record):
        source = lido_page(
            "export.xml", lido_record("FMDU-0001", duration="PT01H43M00S")
        )
        records = fmdu_lido.efi_import(source)
        item = next(r for r in records if r.category == "avefi:Item")
        assert item.has_duration.has_value == "PT01H43M00S"


#: A work registered in AVefi, as the Düsseldorf export carries it
#: back: the handle is written as a resolvable URL, and the identifier
#: is the part after the resolver.
WORK_HANDLE_URL = (
    "https://hdl.handle.net/21.11155/8C5A0C79-7A6C-44EC-8920-01C8A158BFBC"
)
WORK_HANDLE = "21.11155/8C5A0C79-7A6C-44EC-8920-01C8A158BFBC"
MANIFESTATION_HANDLE_URL = (
    "https://hdl.handle.net/21.11155/73F965CE-E4C5-4E82-AC4D-30E51DBA6B74"
)
MANIFESTATION_HANDLE = "21.11155/73F965CE-E4C5-4E82-AC4D-30E51DBA6B74"
FILMPORTAL_URL = (
    "https://www.filmportal.de/film/4029730364e64a1a9bc0d3f5fd3534f4"
)
FILMPORTAL_ID = "4029730364e64a1a9bc0d3f5fd3534f4"


def one(records, category):
    """Return the single record of ``category``."""
    matching = [r for r in records if r.category == category]
    assert len(matching) == 1, [r.category for r in records]
    return matching[0]


class TestIdentifiersARecordAlreadyCarries:
    """A registered holding brings its identifiers back with it.

    A provider whose collection has been registered gets the handles
    into its own system and exports them again. Ignoring them means
    the next conversion mints a second identifier for something that
    has one, and a handle cannot be withdrawn once it is out.

    They were read for the copy only, on the assumption that a LIDO
    record states no others. It states them for the work and for the
    manifestation as well, in the relations the record has to them.

    """

    def records(self, lido_page, lido_record, **kwargs):
        source = lido_page(
            "export.xml",
            lido_record(
                "DE-MUS-042628:DE-MUS-432511:955613",
                related=[
                    (
                        "DE-MUS-042628:DE-MUS-432511:955613",
                        "IM DORF DER WEISSEN STÖRCHE",
                        (
                            ("www.filmportal.de", FILMPORTAL_URL),
                            ("www.av-efi.net", WORK_HANDLE_URL),
                        ),
                    )
                ],
                manifestation_handle=MANIFESTATION_HANDLE_URL,
                **kwargs,
            ),
        )
        return fmdu_lido.efi_import(source)

    def test_the_work_keeps_the_pid_the_provider_states(
        self, lido_page, lido_record
    ):
        work = one(self.records(lido_page, lido_record), "avefi:WorkVariant")
        assert [(i.category, i.id) for i in work.has_identifier] == [
            ("avefi:LocalResource", "955613_work"),
            ("avefi:AVefiResource", WORK_HANDLE),
        ]

    def test_the_manifestation_does_too(self, lido_page, lido_record):
        manifestation = one(
            self.records(lido_page, lido_record), "avefi:Manifestation"
        )
        assert [i.category for i in manifestation.has_identifier] == [
            "avefi:LocalResource",
            "avefi:AVefiResource",
        ]
        assert manifestation.has_identifier[1].id == MANIFESTATION_HANDLE

    def test_the_local_identifier_stays_and_stays_first(
        self, lido_page, lido_record
    ):
        """Everything in the delivery refers to it.

        ``is_item_of`` and ``is_manifestation_of`` name a record by
        its first identifier, so a PID appended in front of the local
        one would leave the references pointing at nothing.

        """
        records = self.records(lido_page, lido_record)
        item = one(records, "avefi:Item")
        manifestation = one(records, "avefi:Manifestation")
        work = one(records, "avefi:WorkVariant")
        assert item.is_item_of.category == "avefi:LocalResource"
        assert item.is_item_of.id == manifestation.has_identifier[0].id
        assert manifestation.is_manifestation_of[0].id == (
            work.has_identifier[0].id
        )

    def test_the_filmportal_entry_becomes_an_authority_link(
        self, lido_page, lido_record
    ):
        """And the bare identifier, not the URL it was written as."""
        work = one(self.records(lido_page, lido_record), "avefi:WorkVariant")
        assert [(link.category, link.id) for link in work.same_as] == [
            ("avefi:FilmportalResource", FILMPORTAL_ID)
        ]

    def test_the_provider_namespaces_are_stripped_from_the_local_one(
        self, lido_page, lido_record
    ):
        """The related work is identified as the record itself is.

        Both are written with the archive and the museum in front of
        the number, and the rest of the institution's data uses the
        number alone.

        """
        work = one(self.records(lido_page, lido_record), "avefi:WorkVariant")
        assert work.has_identifier[0].id == "955613_work"

    def test_a_second_conversion_does_not_add_them_twice(
        self, lido_page, lido_record
    ):
        records = self.records(lido_page, lido_record)
        work = one(records, "avefi:WorkVariant")
        assert len(work.has_identifier) == 2
        assert len(work.same_as) == 1

    def test_the_order_of_the_identifiers_does_not_matter(
        self, lido_page, lido_record
    ):
        """Which identifier is which follows from the value.

        LIDO does not order them, and taking the first one worked
        only as long as the provider wrote its own first.

        """
        source = lido_page(
            "export.xml",
            lido_record(
                "955613",
                related=[
                    (
                        "955613",
                        "IM DORF DER WEISSEN STÖRCHE",
                        (("www.av-efi.net", WORK_HANDLE_URL),),
                    )
                ],
            ),
        )
        work = one(fmdu_lido.efi_import(source), "avefi:WorkVariant")
        assert work.has_identifier[0].id == "955613_work"
        assert work.has_identifier[1].id == WORK_HANDLE


class TestATitleTheCataloguerSupplied:
    """Square brackets mean the same thing wherever they are written.

    The rule was applied to the titles of the copy and not to the one
    the related work carries, so a work kept its brackets while the
    copies of it did not.

    """

    def work_with(self, lido_page, lido_record, title):
        source = lido_page(
            "export.xml",
            lido_record("955613", related=[("955613", title)]),
        )
        return one(fmdu_lido.efi_import(source), "avefi:WorkVariant")

    def test_a_bracketed_work_title_is_supplied_and_devised(
        self, lido_page, lido_record
    ):
        work = self.work_with(lido_page, lido_record, "[Storchennest]")
        assert work.has_primary_title.type == "SuppliedDevisedTitle"
        assert work.has_primary_title.has_name == "Storchennest"

    def test_an_ordinary_work_title_is_the_preferred_one(
        self, lido_page, lido_record
    ):
        work = self.work_with(lido_page, lido_record, "Storchennest")
        assert work.has_primary_title.type == "PreferredTitle"

    def test_the_ordering_name_is_derived_here_as_well(
        self, lido_page, lido_record
    ):
        work = self.work_with(lido_page, lido_record, "[Die Störche]")
        assert work.has_primary_title.has_ordering_name == "Störche, Die"


class TestAnAgentThatIsAnOrganisation:
    """The source says so; the vocabulary has to know the word.

    "corporation" is what the Düsseldorf export writes, and it was in
    neither of the two lists, so every production company arrived
    without a type.

    """

    def agent(self, lido_page, lido_record, actor_type):
        source = lido_page(
            "export.xml",
            lido_record(
                "955613",
                director="DEFA-Studio für Dokumentarfilme",
                role="Produktionsfirma",
                actor_type=actor_type,
            ),
        )
        work = one(fmdu_lido.efi_import(source), "avefi:WorkVariant")
        activity = work.has_event[0].has_activity[0]
        return activity.has_agent[0]

    def test_a_corporation_is_a_corporate_body(self, lido_page, lido_record):
        assert (
            self.agent(lido_page, lido_record, "corporation").type
            == "CorporateBody"
        )

    def test_a_person_still_is_one(self, lido_page, lido_record):
        assert self.agent(lido_page, lido_record, "person").type == "Person"

    def test_an_unstated_type_stays_unstated(self, lido_page, lido_record):
        """Deriving it from the name is a documented non-goal."""
        assert self.agent(lido_page, lido_record, "").type is None


class TestWhatALanguageIsFor:
    """The label on the term says it, and nothing else does.

    Every language of a copy is written as a term reading "Deutsch" or
    "Englisch". Read without the label they are all the spoken
    language, which turns an English subtitle track into an English
    soundtrack.

    """

    def item_with(self, lido_page, lido_record, keywords):
        source = lido_page(
            "export.xml", lido_record("955613", keywords=keywords)
        )
        return one(fmdu_lido.efi_import(source), "avefi:Item")

    def test_a_subtitle_is_a_subtitle(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, (("Englisch", "Untertitel"),)
        )
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            ("eng", ["Subtitles"])
        ]

    def test_an_intertitle_is_an_intertitle(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, (("Deutsch", "Zwischentitel"),)
        )
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            ("ger", ["Intertitles"])
        ]

    def test_no_dialogue_under_a_dialogue_label_is_a_usage(
        self, lido_page, lido_record
    ):
        item = self.item_with(
            lido_page, lido_record, (("Ohne Sprache", "Dialogton"),)
        )
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            (None, ["NoDialogue"])
        ]

    def test_all_three_are_kept_apart(self, lido_page, lido_record):
        item = self.item_with(
            lido_page,
            lido_record,
            (
                ("Ohne Sprache", "Dialogton"),
                ("Englisch", "Untertitel"),
                ("Deutsch", "Zwischentitel"),
            ),
        )
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            (None, ["NoDialogue"]),
            ("eng", ["Subtitles"]),
            ("ger", ["Intertitles"]),
        ]

    def test_one_language_used_twice_is_one_entry(
        self, lido_page, lido_record
    ):
        item = self.item_with(
            lido_page,
            lido_record,
            (("Deutsch", "Dialogton"), ("Deutsch", "Zwischentitel")),
        )
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            ("ger", ["SpokenLanguage", "Intertitles"])
        ]

    def test_a_labelled_language_is_not_also_a_genre(
        self, lido_page, lido_record
    ):
        source = lido_page(
            "export.xml",
            lido_record("955613", keywords=(("Englisch", "Untertitel"),)),
        )
        work = one(fmdu_lido.efi_import(source), "avefi:WorkVariant")
        assert "Englisch" not in [g.has_name for g in work.has_genre]

    def test_an_unlabelled_language_is_read_as_before(
        self, lido_page, lido_record
    ):
        """Which is the spoken one, reported as the assumption it is."""
        item = self.item_with(lido_page, lido_record, ("Deutsch",))
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            ("ger", ["SpokenLanguage"])
        ]

    def test_an_unknown_label_is_reported(self, lido_page, lido_record):
        report = ConversionReport()
        with collecting(report):
            self.item_with(
                lido_page, lido_record, (("Englisch", "Gesangssprache"),)
            )
        assert any(
            "language usage" in entry.message.lower()
            for entry in report.entries
        )


class TestWhereAnObjectIsPublished:
    """A published identifier that is a URL is a link to the object.

    ``objectPublishedID`` holds both the AVefi handle and the address
    of the object's page in the provider's own system. The value tells
    them apart; ``lido:type`` does not, this provider typing the page
    address as a local identifier.

    """

    PAGE = "http://www.duesseldorf.de/dkult/DE-MUS-432511/994335"

    def item_with(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("955613", **kwargs))
        return one(fmdu_lido.efi_import(source), "avefi:Item")

    def test_the_page_of_an_object_becomes_a_web_resource(
        self, lido_page, lido_record
    ):
        item = self.item_with(
            lido_page, lido_record, published_urls=(self.PAGE,)
        )
        assert item.has_webresource == [self.PAGE]

    def test_the_handle_does_not(self, lido_page, lido_record):
        """It is the identifier of the copy, and it already is one."""
        item = self.item_with(
            lido_page,
            lido_record,
            handle=WORK_HANDLE_URL,
            published_urls=(self.PAGE,),
        )
        assert item.has_webresource == [self.PAGE]
        assert [i.category for i in item.has_identifier] == [
            "avefi:AVefiResource",
            "avefi:LocalResource",
        ]

    def test_the_same_address_is_not_listed_twice(
        self, lido_page, lido_record
    ):
        item = self.item_with(
            lido_page, lido_record, published_urls=(self.PAGE, self.PAGE)
        )
        assert item.has_webresource == [self.PAGE]


class TestAHandleThatReachesNothing:
    """The conversion compares its own input and output.

    A handle in the record and in none of the records derived from it
    is a silent failure: the run succeeds and the output validates.
    The next delivery then asks for a second identifier for something
    that has one, and a handle cannot be withdrawn.

    """

    def report_for(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("955613", **kwargs))
        report = ConversionReport()
        with collecting(report):
            fmdu_lido.efi_import(source)
        return report

    def lost(self, report):
        return [
            entry
            for entry in report.entries
            if "no output record carries" in entry.message
        ]

    def test_a_handle_under_an_unknown_relation_is_reported(
        self, lido_page, lido_record
    ):
        """Which is what a missing profile term looks like from here."""
        report = self.report_for(
            lido_page,
            lido_record,
            related=[
                (
                    "955613",
                    "Im Dorf der weissen Störche",
                    (("www.av-efi.net", WORK_HANDLE_URL),),
                )
            ],
            related_rel="ist Teil von",
        )
        lost = self.lost(report)
        assert [entry.raw_value for entry in lost] == [WORK_HANDLE]
        assert "ist teil von" in lost[0].source_field

    def test_a_handle_that_is_transferred_is_not(self, lido_page, lido_record):
        report = self.report_for(
            lido_page,
            lido_record,
            related=[
                (
                    "955613",
                    "Im Dorf der weissen Störche",
                    (("www.av-efi.net", WORK_HANDLE_URL),),
                )
            ],
            manifestation_handle=MANIFESTATION_HANDLE_URL,
            handle=(
                "https://hdl.handle.net/21.11155/"
                "11111111-2222-3333-4444-555555555555"
            ),
        )
        assert self.lost(report) == []

    def test_a_record_without_handles_says_nothing(
        self, lido_page, lido_record
    ):
        assert self.lost(self.report_for(lido_page, lido_record)) == []
