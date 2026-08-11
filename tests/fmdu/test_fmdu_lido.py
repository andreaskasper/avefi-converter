"""The Filmmuseum Düsseldorf profile for LIDO.

What is tested here is the profile, not the mapping: the terms this
one provider uses, and the consequences of getting them wrong. The
generic traversal has its own tests under ``tests/lido``.

"""

from efi_conv.fmdu import lido as fmdu_lido
from efi_conv.lido import LidoProfile


class TestWorkTypeVocabulary:
    """objectWorkType names the carrier here, not the work.

    The generic default lists work types. This provider lists what the
    copy is wound on. The two vocabularies meet in exactly one term,
    "Video", so a conversion running on the default accepted 67 of
    5562 records of a real export and dropped every film reel in it.

    """

    def test_a_film_reel_is_a_film_holding(self):
        assert "filmrolle" in fmdu_lido.PROFILE.film_work_type_terms

    def test_the_generic_default_would_not_have_accepted_it(self):
        """Guard the reason this list exists in the first place."""
        assert (
            "filmrolle"
            not in LidoProfile(
                issuer_info=fmdu_lido.ISSUER_INFO
            ).film_work_type_terms
        )

    def test_digital_carriers_count_as_holdings(self):
        """They appear in the CSV export agreed with the provider.

        Whether a hard disk is a film holding is the provider's call,
        and it has already been made: these carriers are in the export
        that defines the scope, so leaving them out here would make
        the two importers disagree about the same collection.

        """
        terms = fmdu_lido.PROFILE.film_work_type_terms
        for carrier in ("festplatte", "raid", "datei", "lto", "optisch"):
            assert carrier in terms

    def test_title_fragments_are_not_carrier_terms(self):
        """Six records carry a title where the carrier belongs.

        Accepting them would import the records and hide a data entry
        error that the provider can still fix.

        """
        terms = fmdu_lido.PROFILE.film_work_type_terms
        for fragment in ("teil 1", "teil 1 und 2", "teil 4: die abrechnung"):
            assert fragment not in terms

    def test_the_terms_are_lower_case(self):
        """The lookup lower cases the source term before comparing."""
        terms = fmdu_lido.PROFILE.film_work_type_terms
        assert all(term == term.lower() for term in terms)


class TestFilteringInPractice:
    def test_a_film_reel_converts(self, lido_page, lido_record):
        source = lido_page(
            "export.xml", lido_record("FMDU-0001", work_type="Filmrolle")
        )
        assert fmdu_lido.efi_import(source)

    def test_a_poster_does_not(self, lido_page, lido_record):
        source = lido_page(
            "export.xml", lido_record("FMDU-0002", work_type="Plakat")
        )
        assert fmdu_lido.efi_import(source) == []

    def test_a_hard_disk_converts(self, lido_page, lido_record):
        source = lido_page(
            "export.xml", lido_record("FMDU-0003", work_type="Festplatte")
        )
        assert fmdu_lido.efi_import(source)


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
