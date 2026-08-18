"""The Filmmuseum Düsseldorf profile for LIDO.

What is tested here is the profile, not the mapping: the terms this
one provider uses, and the consequences of getting them wrong. The
generic traversal has its own tests under ``tests/lido``.

"""

from efi_conv.fmdu import lido as fmdu_lido


class TestScope:
    """What counts as a record this conversion is about.

    The provider says so itself: every record carries a recordType,
    and all 5562 of the reference export say "Item". Taking that
    answer is better than inferring one from the object, which is what
    the earlier filter on lido:objectWorkType did — and it got six
    copies wrong, because their objectWorkType holds a title fragment
    rather than a carrier.

    """

    def test_the_record_type_decides(self):
        assert fmdu_lido.PROFILE.record_type_terms == frozenset({"item"})

    def test_the_work_type_filter_is_not_used(self):
        """Two criteria for one question is one too many.

        objectWorkType names the carrier in this export, not the type
        of work, so it answers a different question than the one the
        filter asks.

        """
        assert not fmdu_lido.PROFILE.film_work_type_terms

    def test_an_item_converts(self, lido_page, lido_record):
        source = lido_page(
            "export.xml", lido_record("FMDU-0001", record_type="Item")
        )
        assert fmdu_lido.efi_import(source)

    def test_another_kind_of_record_does_not(self, lido_page, lido_record):
        source = lido_page(
            "export.xml", lido_record("FMDU-0002", record_type="Sonstiges")
        )
        assert fmdu_lido.efi_import(source) == []

    def test_a_carrier_the_old_filter_rejected_now_converts(
        self, lido_page, lido_record
    ):
        """Six copies carry a title where the carrier belongs.

        They are copies whatever the cataloguer typed, and the record
        says so.

        """
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0003", work_type="Teil 2: Das Bündnis"),
        )
        assert fmdu_lido.efi_import(source)

    def test_a_record_without_a_type_is_reported(self, lido_page, lido_record):
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            records = fmdu_lido.efi_import(
                lido_page(
                    "export.xml", lido_record("FMDU-0004", record_type="")
                )
            )
        assert records == []
        assert [
            entry
            for entry in report.entries
            if entry.severity == "warning"
            and entry.source_field == "recordType"
        ]


class TestAnIdentifierAlreadyRegistered:
    """A handle the provider carries back is not minted a second time.

    Once holdings have been registered, the identifiers go back into
    the provider's own system and come out again with the next export.
    A handle cannot be withdrawn, so a conversion that ignores the one
    in front of it turns every later delivery into a second identity
    for a copy that already has one. In the reference export 3712 of
    5562 records carry theirs.

    """

    HANDLE = "21.11155/F68FEFE5-205A-4090-8A31-60C6F87875BB"

    def item(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("FMDU-0001", **kwargs))
        records = fmdu_lido.efi_import(source)
        return next(r for r in records if r.category == "avefi:Item")

    def test_the_handle_becomes_an_avefi_identifier(
        self, lido_page, lido_record
    ):
        item = self.item(lido_page, lido_record, handle=self.HANDLE)
        assert self.HANDLE in [
            i.id
            for i in item.has_identifier
            if i.category == "avefi:AVefiResource"
        ]

    def test_it_is_read_out_of_a_resolver_url(self, lido_page, lido_record):
        item = self.item(
            lido_page,
            lido_record,
            handle=f"https://hdl.handle.net/{self.HANDLE}",
        )
        assert [
            i.id
            for i in item.has_identifier
            if i.category == "avefi:AVefiResource"
        ] == [self.HANDLE]

    def test_the_local_identifier_stays(self, lido_page, lido_record):
        """Both are needed: one identifies, the other groups."""
        item = self.item(lido_page, lido_record, handle=self.HANDLE)
        assert [i.category for i in item.has_identifier].count(
            "avefi:LocalResource"
        ) == 1

    def test_a_record_without_one_gets_none(self, lido_page, lido_record):
        item = self.item(lido_page, lido_record)
        assert not [
            i
            for i in item.has_identifier
            if i.category == "avefi:AVefiResource"
        ]

    def test_only_the_copy_carries_it(self, lido_page, lido_record):
        """No LIDO record states a work or manifestation identifier.

        A record describes one object and the object is the copy, so
        putting the handle anywhere else would be an assertion the
        source never made.

        """
        source = lido_page(
            "export.xml", lido_record("FMDU-0001", handle=self.HANDLE)
        )
        for record in fmdu_lido.efi_import(source):
            if record.category == "avefi:Item":
                continue
            assert not [
                i
                for i in record.has_identifier
                if i.category == "avefi:AVefiResource"
            ]


class TestPeopleAndTheirRoles:
    """The credits sit in an event of their own in this export.

    Director, composer and writer are recorded under "Geistige
    Schöpfung" rather than on the event that produced the copy, and
    the mapping only ever looked at the latter. 1228 records name a
    director; none of them arrived.

    """

    def work_of(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("FMDU-0001", **kwargs))
        records = fmdu_lido.efi_import(source)
        return next(r for r in records if r.category == "avefi:WorkVariant")

    def activities(self, work):
        return [a for event in work.has_event for a in event.has_activity]

    def test_the_director_arrives(self, lido_page, lido_record):
        work = self.work_of(lido_page, lido_record, role="Regie")
        activity = self.activities(work)[0]
        assert activity.category == "avefi:DirectingActivity"
        assert activity.type == "Director"

    def test_a_composer_becomes_a_music_activity(self, lido_page, lido_record):
        """The role decides the class, and the schema decides the role.

        No value is shared between the sixteen activity vocabularies,
        so a profile names the role and the class follows.

        """
        work = self.work_of(lido_page, lido_record, role="Musik")
        activity = self.activities(work)[0]
        assert activity.category == "avefi:MusicActivity"
        assert activity.type == "Composer"

    def test_a_writer_becomes_a_writing_activity(self, lido_page, lido_record):
        work = self.work_of(lido_page, lido_record, role="Drehbuch")
        assert self.activities(work)[0].category == "avefi:WritingActivity"

    def test_a_role_with_no_activity_transfers_nobody(
        self, lido_page, lido_record
    ):
        """Absender*in records provenance, not a credit."""
        work = self.work_of(lido_page, lido_record, role="Absender*in")
        assert self.activities(work) == []


class TestAgentIdentity:
    def agent_of(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("FMDU-0001", **kwargs))
        work = next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:WorkVariant"
        )
        return work.has_event[0].has_activity[0].has_agent[0]

    def test_the_person_type_comes_from_the_source(
        self, lido_page, lido_record
    ):
        agent = self.agent_of(lido_page, lido_record, actor_type="person")
        assert agent.type == "Person"

    def test_so_does_the_corporate_body(self, lido_page, lido_record):
        agent = self.agent_of(
            lido_page,
            lido_record,
            director="Gruppe 5 Filmproduktion GmbH",
            actor_type="corporateBody",
        )
        assert agent.type == "CorporateBody"

    def test_an_unstated_type_stays_unstated(self, lido_page, lido_record):
        """Deriving it from the name is out of scope, and it was wrong.

        Every director used to be typed Person outright. The reference
        data holds a production company that was typed that way and
        had to be corrected by hand afterwards.

        """
        agent = self.agent_of(lido_page, lido_record, actor_type="")
        assert agent.type is None

    def test_a_gnd_identifier_is_transferred(self, lido_page, lido_record):
        agent = self.agent_of(
            lido_page, lido_record, gnd="http://d-nb.info/gnd/123867967"
        )
        assert [(a.category, a.id) for a in agent.same_as] == [
            ("avefi:GNDResource", "123867967")
        ]

    def test_a_bare_identifier_works_too(self, lido_page, lido_record):
        agent = self.agent_of(lido_page, lido_record, gnd="123867967")
        assert agent.same_as[0].id == "123867967"

    def test_an_unknown_authority_is_not_invented(
        self, lido_page, lido_record
    ):
        agent = self.agent_of(
            lido_page, lido_record, gnd="4711", gnd_source="Hauskartei"
        )
        assert agent.same_as == []


class TestTechnicalDescription:
    """Colour, format, element type and sound sit in one field here.

    The mapping looked for them in typed classifications, which this
    provider does not use for the purpose, so every copy of a 5562
    record export arrived without a format, without a colour and
    without an element type.

    """

    def item_with(self, lido_page, lido_record, *materials):
        # colour="" keeps the typed classification of the shared
        # fixture out of the way: this provider records the colour in
        # the technical description, and that is what is under test.
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", colour="", materials=materials),
        )
        records = fmdu_lido.efi_import(source)
        return next(r for r in records if r.category == "avefi:Item")

    def test_a_value_that_is_already_avefi_is_taken_as_it_stands(
        self, lido_page, lido_record
    ):
        """The provider writes schema values into its own field.

        They are a closed set, so a term that is one of them means
        itself, and adding a carrier costs the provider nothing.

        """
        item = self.item_with(
            lido_page, lido_record, ("35mmFilm", "FormatFilmTypeEnum")
        )
        assert [(f.category, f.type) for f in item.has_format] == [
            ("avefi:Film", "35mmFilm")
        ]

    def test_a_house_spelling_is_translated(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, ("17,5mmFilm", "FormatFilmTypeEnum")
        )
        assert item.has_format[0].type == "17.5mmFilm"

    def test_colour_and_element_and_sound_reach_their_own_fields(
        self, lido_page, lido_record
    ):
        item = self.item_with(
            lido_page,
            lido_record,
            ("Colour, SW", "ColourTypeEnum"),
            ("Positive", "ItemElementTypeEnum"),
            ("Stummfilm", ""),
        )
        assert item.has_colour_type == "ColourBlackAndWhite"
        assert item.element_type == "Positive"
        assert item.has_sound_type == "Silent"

    def test_the_value_decides_where_the_concept_disagrees(
        self, lido_page, lido_record
    ):
        """The provider files DCP under the digital file vocabulary.

        It is an element type. Following the label rather than the
        value would put a value into a field the schema does not
        allow it in, so the value wins and the disagreement is noted.

        """
        item = self.item_with(
            lido_page, lido_record, ("DCP", "FormatDigitalFileTypeEnum")
        )
        assert item.element_type == "DCP"
        assert not item.has_format

    def test_not_assigned_is_not_a_value(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, ("(not assigned)", "ColourTypeEnum")
        )
        assert item.has_colour_type is None

    def test_a_publication_event_type_is_reported_not_acted_on(
        self, lido_page, lido_record
    ):
        """A note on the material does not state a distribution.

        Deriving an event from it would put something in the record
        that the source does not say, so it is left to the provider.

        """
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            item = self.item_with(
                lido_page,
                lido_record,
                ("TheatricalDistributionEvent", "PublicationEventTypeEnum"),
            )
        assert not item.has_format
        assert [
            entry
            for entry in report.entries
            if entry.raw_value == "TheatricalDistributionEvent"
            and entry.severity == "info"
        ]

    def test_an_unknown_term_is_reported(self, lido_page, lido_record):
        """A hard disk has no format in the schema, so say so.

        Ninety one copies are stored on one. Silently dropping the
        fact would leave the copy looking as if nothing were known
        about its carrier.

        """
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            self.item_with(
                lido_page, lido_record, ("Festplatte", "FormatOpticalTypeEnum")
            )
        assert [
            entry
            for entry in report.entries
            if entry.raw_value == "Festplatte" and entry.severity == "warning"
        ]


class TestKeywordsCarryMoreThanKeywords:
    """One classification holds language, access status and notes.

    The heading says "Schlagwort" and says nothing more, so the term
    has to say where it belongs. Until it did, the language of a copy
    was arriving as a genre of the film: "Deutsch" 1922 times.

    """

    def records_with(self, lido_page, lido_record, *keywords, handle=""):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", keywords=keywords, handle=handle),
        )
        return fmdu_lido.efi_import(source)

    def item_with(self, lido_page, lido_record, *keywords, handle=""):
        records = self.records_with(
            lido_page, lido_record, *keywords, handle=handle
        )
        return next(r for r in records if r.category == "avefi:Item")

    def test_a_language_becomes_a_language(self, lido_page, lido_record):
        item = self.item_with(lido_page, lido_record, "Deutsch")
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            ("ger", ["SpokenLanguage"])
        ]

    def test_it_is_no_longer_a_genre(self, lido_page, lido_record):
        records = self.records_with(lido_page, lido_record, "Deutsch")
        work = next(r for r in records if r.category == "avefi:WorkVariant")
        assert "Deutsch" not in [genre.has_name for genre in work.has_genre]

    def test_no_dialogue_is_a_usage_not_a_language(
        self, lido_page, lido_record
    ):
        """And it is not a language code either.

        zxx says "no linguistic content", which is an answer to a
        question the record does not ask: it states that the copy
        carries no dialogue, not which language it does not carry.
        The schema lets the code stand empty, so it stands empty.

        """
        item = self.item_with(lido_page, lido_record, "Ohne Sprache")
        assert [(lang.code, lang.usage) for lang in item.in_language] == [
            (None, ["NoDialogue"])
        ]

    def test_an_access_status_becomes_one(self, lido_page, lido_record):
        item = self.item_with(lido_page, lido_record, "Archivkopie")
        assert item.has_access_status == "Archive"

    def test_a_working_note_is_reported(self, lido_page, lido_record):
        """A working note is about the cataloguing, not the film."""
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            self.item_with(lido_page, lido_record, "angedacht")
        assert [
            entry
            for entry in report.entries
            if entry.raw_value == "angedacht" and entry.severity == "warning"
        ]


class TestDeaccession:
    """Removed says a registered copy is gone.

    About a copy that was never registered it says nothing, and
    efi-conv check refuses the combination — a rule of the target
    system that is easy to miss and expensive to find out late.

    """

    HANDLE = "21.11155/F68FEFE5-205A-4090-8A31-60C6F87875BB"

    def item_with(self, lido_page, lido_record, handle):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", keywords=("Deakzession",), handle=handle),
        )
        return next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:Item"
        )

    def test_a_registered_copy_is_marked_removed(self, lido_page, lido_record):
        item = self.item_with(lido_page, lido_record, self.HANDLE)
        assert item.has_access_status == "Removed"

    def test_an_unregistered_one_is_not(self, lido_page, lido_record):
        item = self.item_with(lido_page, lido_record, "")
        assert item.has_access_status is None

    def test_and_the_record_survives_with_a_warning(
        self, lido_page, lido_record
    ):
        """Dropping it is the provider's call, not the converter's."""
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            item = self.item_with(lido_page, lido_record, "")
        assert item is not None
        assert [
            entry
            for entry in report.entries
            if entry.target_field == "has_access_status"
            and entry.severity == "warning"
        ]


class TestPlaces:
    def work_with(self, lido_page, lido_record, *places):
        source = lido_page(
            "export.xml", lido_record("FMDU-0001", places=places)
        )
        return next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:WorkVariant"
        )

    def test_the_name_is_left_as_the_source_gives_it(
        self, lido_page, lido_record
    ):
        """A film made in the DDR was made in the DDR.

        Normalising it to Germany would drop the part that carries
        information, and it is a heuristic the commission puts out of
        scope besides.

        """
        work = self.work_with(lido_page, lido_record, ("DDR", "7017366"))
        assert [p.has_name for p in work.has_event[0].located_in] == ["DDR"]

    def test_the_authority_identifier_comes_along(
        self, lido_page, lido_record
    ):
        """It is what resolves BRD and Deutschland to one country.

        Every place in the reference export carries one, so the
        spelling does not have to be argued about.

        """
        work = self.work_with(lido_page, lido_record, ("BRD", "7003656"))
        place = work.has_event[0].located_in[0]
        assert [(a.category, a.id) for a in place.same_as] == [
            ("avefi:TGNResource", "7003656")
        ]

    def test_a_place_stated_twice_is_recorded_once(
        self, lido_page, lido_record
    ):
        """The reference data repeats one, three times in a record."""
        work = self.work_with(
            lido_page,
            lido_record,
            ("Dänemark", "7006429"),
            ("Dänemark", "7006429"),
            ("BRD", "7003656"),
        )
        assert [p.has_name for p in work.has_event[0].located_in] == [
            "Dänemark",
            "BRD",
        ]


class TestRunningTime:
    """The column says minutes and holds hours.

    A 35mm print of 2523 metres runs 92 minutes at 24 frames a second,
    and its record says 1.5207. Read as minutes the median running
    time of the export would be fourteen seconds.

    """

    def item_with(self, lido_page, lido_record, duration):
        source = lido_page(
            "export.xml", lido_record("FMDU-0001", duration=duration)
        )
        return next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:Item"
        )

    def test_the_profile_states_the_unit_the_values_are_in(self):
        assert fmdu_lido.PROFILE.duration_units["zeit"] == "h"

    def test_zeit_counts_as_a_running_time(self):
        """The generic list has laufzeit and dauer, not this one."""
        assert "zeit" in fmdu_lido.PROFILE.duration_measurement_terms

    def test_a_zero_is_not_a_running_time(self, lido_page, lido_record):
        """1084 records of the export write an empty column as 0E-10."""
        assert (
            self.item_with(lido_page, lido_record, "0E-10").has_duration
            is None
        )

    def test_the_value_is_read_as_hours(self, lido_page, lido_record):
        """1.5207 in the "Zeit" column is 91 minutes, not 91 seconds."""
        source = lido_page(
            "export.xml",
            lido_record(
                "FMDU-0001", measurement="Zeit", duration="1.5206666667"
            ),
        )
        item = next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:Item"
        )
        assert item.has_duration.has_value == "PT01H31M14S"


class TestSourceKey:
    """The two importers of one collection must agree on a key.

    The LIDO export prefixes the identifier with the archive and the
    museum; the CSV export of the same holdings carries the bare
    number, and so does the rest of the institution's data. Taking the
    whole string would give one copy two source keys depending on
    which importer ran, and nothing could be matched between them —
    not the two exports against each other, and not a delivery against
    what AVefi already holds.

    """

    def key_of(self, lido_page, lido_record, record_id):
        source = lido_page("export.xml", lido_record(record_id))
        item = next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:Item"
        )
        return item.described_by.has_source_key

    def test_the_namespaces_are_dropped(self, lido_page, lido_record):
        assert self.key_of(
            lido_page, lido_record, "DE-MUS-042628:DE-MUS-432511:1059195"
        ) == ["1059195"]

    def test_a_bare_identifier_is_left_alone(self, lido_page, lido_record):
        assert self.key_of(lido_page, lido_record, "1059195") == ["1059195"]

    def test_the_report_names_the_record_the_provider_would(
        self, lido_page, lido_record
    ):
        """A report entry has to be findable in the source system."""
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            fmdu_lido.efi_import(
                lido_page(
                    "export.xml",
                    lido_record(
                        "DE-MUS-042628:DE-MUS-432511:1059195",
                        role="Absender*in",
                    ),
                )
            )
        assert {entry.record_id for entry in report.entries} == {"1059195"}


class TestWorksAsTheProviderStatesThem:
    """The provider decides what is one film and what is two.

    Each relatedWorkSet carries the work's own identifier and title,
    which is a better basis than a key derived from the copy: it does
    not depend on a title being spelled the same way twice, and it
    handles the case a derived key cannot express at all — a reel
    holding two films is two works and one manifestation. Three such
    copies had to be taken apart by hand in the revised CSV output.

    """

    def records_for(self, lido_page, lido_record, *related, **kwargs):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", related=related, **kwargs),
        )
        return fmdu_lido.efi_import(source)

    def works_of(self, records):
        return [r for r in records if r.category == "avefi:WorkVariant"]

    def test_one_related_work_is_one_work(self, lido_page, lido_record):
        records = self.records_for(
            lido_page, lido_record, ("W-1", "Die Brücke")
        )
        assert len(self.works_of(records)) == 1

    def test_the_work_is_identified_by_what_the_provider_says(
        self, lido_page, lido_record
    ):
        records = self.records_for(
            lido_page, lido_record, ("W-1", "Die Brücke")
        )
        assert self.works_of(records)[0].has_identifier[0].id == "W-1_work"

    def test_two_related_works_are_two_works_and_one_manifestation(
        self, lido_page, lido_record
    ):
        records = self.records_for(
            lido_page,
            lido_record,
            ("W-1", "Sammeltage: Teil 1"),
            ("W-2", "Sammeltage: Teil 2"),
        )
        assert len(self.works_of(records)) == 2
        manifestations = [
            r for r in records if r.category == "avefi:Manifestation"
        ]
        assert len(manifestations) == 1
        assert len(manifestations[0].is_manifestation_of) == 2

    def test_each_gets_the_title_the_provider_gives_it(
        self, lido_page, lido_record
    ):
        records = self.records_for(
            lido_page,
            lido_record,
            ("W-1", "Sammeltage: Teil 1"),
            ("W-2", "Sammeltage: Teil 2"),
        )
        assert sorted(
            w.has_primary_title.has_name for w in self.works_of(records)
        ) == ["Sammeltage: Teil 1", "Sammeltage: Teil 2"]

    def test_what_belongs_to_no_one_film_is_not_attributed(
        self, lido_page, lido_record
    ):
        """A date read off a compilation reel is the reel's date.

        Attaching the record's production event to each film on it
        would state a production year for films that never had it.

        """
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            records = self.records_for(
                lido_page,
                lido_record,
                ("W-1", "Teil 1"),
                ("W-2", "Teil 2"),
            )
        assert all(not w.has_event for w in self.works_of(records))
        assert [
            entry
            for entry in report.entries
            if entry.source_field == "relatedWorkSet"
        ]

    def test_a_single_work_keeps_everything_the_record_says(
        self, lido_page, lido_record
    ):
        """With one film, the record is about that film."""
        records = self.records_for(
            lido_page, lido_record, ("W-1", "Die Brücke")
        )
        work = self.works_of(records)[0]
        assert work.has_event and work.has_event[0].has_date == "1959"

    def test_copies_of_one_film_still_share_it(self, lido_page, lido_record):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", related=(("W-1", "Die Brücke"),)),
            lido_record(
                "FMDU-0002", related=(("W-1", "Die Brücke"),), colour="farbe"
            ),
        )
        records = fmdu_lido.efi_import(source)
        assert len(self.works_of(records)) == 1

    def test_another_relation_is_not_a_work(self, lido_page, lido_record):
        """Only the relation the profile names denotes the film."""
        records = self.records_for(
            lido_page,
            lido_record,
            ("W-1", "Ein Plakat dazu"),
            related_rel="Plakat",
        )
        works = self.works_of(records)
        assert len(works) == 1
        assert works[0].has_identifier[0].id != "W-1_work"


class TestFormGenreAndSubject:
    """Three questions the provider answers in two places.

    What kind of thing a film is, what it is like, and what it is
    about. The first two share one classification list and the third
    is filed as if it were a credit.

    """

    def work_with(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("FMDU-0001", **kwargs))
        return next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:WorkVariant"
        )

    def test_a_form_becomes_a_form(self, lido_page, lido_record):
        work = self.work_with(lido_page, lido_record, genre="Dokumentarfilm")
        assert work.has_form == ["Documentary"]

    def test_and_not_also_a_genre(self, lido_page, lido_record):
        """It is one statement, not two."""
        work = self.work_with(lido_page, lido_record, genre="Dokumentarfilm")
        assert work.has_genre == []

    def test_a_genre_stays_a_genre(self, lido_page, lido_record):
        work = self.work_with(lido_page, lido_record, genre="Filmkomödie")
        assert [g.has_name for g in work.has_genre] == ["Filmkomödie"]
        assert not work.has_form

    def test_a_subject_is_not_a_credit(self, lido_page, lido_record):
        """A subject role names who the film is about.

        It sits where the credits sit, so only the role tells them
        apart; without that the person is either taken for a director
        or reported as an unmappable credit.

        """
        work = self.work_with(
            lido_page,
            lido_record,
            director="Kratz, Max",
            role="Behandelte Person",
        )
        assert [s.has_name for s in work.has_subject] == ["Kratz, Max"]
        assert not [a for event in work.has_event for a in event.has_activity]

    def test_a_subject_keeps_its_authority_identifier(
        self, lido_page, lido_record
    ):
        work = self.work_with(
            lido_page,
            lido_record,
            director="Kratz, Max",
            role="Behandelte Person",
            gnd="118715585",
        )
        assert [(a.category, a.id) for a in work.has_subject[0].same_as] == [
            ("avefi:GNDResource", "118715585")
        ]


class TestExtent:
    """The length of a copy, and a unit that is not to be trusted.

    Of 1947 comparable 35 mm records, 1334 hold centimetres and 613
    metres, all of them labelled "m". The conversion transfers what
    the record says and reports where the length and the running time
    cannot both be right. Correcting one of them would be guessing
    which, and the provider is the one who knows.

    """

    def item_with(self, lido_page, lido_record, **kwargs):
        source = lido_page("export.xml", lido_record("FMDU-0001", **kwargs))
        return next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:Item"
        )

    def test_the_length_is_transferred(self, lido_page, lido_record):
        item = self.item_with(lido_page, lido_record, extent="2523")
        assert float(item.has_extent.has_value) == 2523
        assert item.has_extent.has_unit == "Metre"

    def test_a_zero_length_is_not_a_length(self, lido_page, lido_record):
        item = self.item_with(lido_page, lido_record, extent="0E-10")
        assert item.has_extent is None

    def test_an_unknown_unit_is_reported(self, lido_page, lido_record):
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            item = self.item_with(
                lido_page, lido_record, extent="2523", extent_unit="Ellen"
            )
        assert item.has_extent is None
        assert [
            entry
            for entry in report.entries
            if entry.target_field == "has_extent.has_unit"
        ]

    def test_a_plausible_pair_says_nothing(self, lido_page, lido_record):
        """2523 m of 35 mm is 92 minutes at 24 frames a second."""
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            self.item_with(
                lido_page,
                lido_record,
                extent="2523",
                measurement="Zeit",
                duration="1.5206666667",
                materials=(("35mmFilm", "FormatFilmTypeEnum"),),
            )
        assert not [
            entry for entry in report.entries if "disagree" in entry.message
        ]

    def test_a_length_in_the_wrong_unit_is_reported(
        self, lido_page, lido_record
    ):
        """The same copy with the length in centimetres.

        Both values are still transferred as stated; the report says
        that the two contradict each other, which is what anybody
        computing with either needs to know first.

        """
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            item = self.item_with(
                lido_page,
                lido_record,
                extent="252300",
                measurement="Zeit",
                duration="1.5206666667",
                materials=(("35mmFilm", "FormatFilmTypeEnum"),),
            )
        assert float(item.has_extent.has_value) == 252300
        assert [
            entry
            for entry in report.entries
            if "disagree" in entry.message
            and entry.target_field == "has_extent.has_value"
        ]


class TestOneAccessStatusOutOfSeveral:
    """A copy can be filed under more than one usage note.

    has_access_status is not repeatable, so one of them decides, and
    which one has to be said rather than left to the order the
    cataloguer happened to type in. A copy given up is that before it
    is anything else, and it does not stop being true because a
    lending note was written down first.

    """

    HANDLE = "21.11155/F68FEFE5-205A-4090-8A31-60C6F87875BB"

    def item_with(self, lido_page, lido_record, *keywords, handle=HANDLE):
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001", keywords=keywords, handle=handle),
        )
        return next(
            r
            for r in fmdu_lido.efi_import(source)
            if r.category == "avefi:Item"
        )

    def test_deaccession_wins_when_stated_second(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, "Verleihkopie", "Deakzession"
        )
        assert item.has_access_status == "Removed"

    def test_and_when_stated_first(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, "Deakzession", "Verleihkopie"
        )
        assert item.has_access_status == "Removed"

    def test_otherwise_the_first_one_decides(self, lido_page, lido_record):
        item = self.item_with(
            lido_page, lido_record, "Verleihkopie", "Archivkopie"
        )
        assert item.has_access_status == "Distribution"

    def test_the_precedence_is_reported(self, lido_page, lido_record):
        """Silently preferring one over another is a decision hidden."""
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            self.item_with(
                lido_page, lido_record, "Verleihkopie", "Deakzession"
            )
        assert [
            entry
            for entry in report.entries
            if entry.target_field == "has_access_status"
            and "precedence" in entry.message
        ]

    def test_a_single_status_says_nothing(self, lido_page, lido_record):
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            item = self.item_with(lido_page, lido_record, "Archivkopie")
        assert item.has_access_status == "Archive"
        assert not [
            entry for entry in report.entries if "precedence" in entry.message
        ]

    def test_without_a_pid_the_other_status_is_used(
        self, lido_page, lido_record
    ):
        """Removed says a registered copy is gone; this one is not.

        The lending note is still true about it, so the record keeps
        that rather than nothing at all, and the deaccession is
        reported.

        """
        from efi_conv.core.report import ConversionReport, collecting

        report = ConversionReport()
        with collecting(report):
            item = self.item_with(
                lido_page,
                lido_record,
                "Verleihkopie",
                "Deakzession",
                handle="",
            )
        assert item.has_access_status == "Distribution"
        assert [
            entry
            for entry in report.entries
            if entry.severity == "warning"
            and entry.target_field == "has_access_status"
        ]
