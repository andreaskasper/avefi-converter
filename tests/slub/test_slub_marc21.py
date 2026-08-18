"""The SLUB Dresden profile for MARC21.

What is tested here is the profile and the two things about this export
that are not house practice: it is catalogued to RDA, so the carrier is
in 338 and the fixed fields are empty, and the editions of one film are
separate records linked through 776. Both are read by the generic
mapping and have their own tests there; what these check is that the
combination works for this provider.

"""

import json

from efi_conv import slub
from efi_conv.core import avefi, check, from_


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(slub, input_path("sample_data.xml"))
    assert json.loads(avefi.dumps(efi_records)) == expected_output


def test_schema_compliance(input_path):
    schema_validator = check.get_schema_validator()
    efi_records = from_.import_file(slub, input_path("sample_data.xml"))
    assert check.pass_checks(efi_records, schema_validator), (
        "Mapped data did not validate"
    )


class TestTheProfile:
    def test_the_issuer_is_the_holding_library(self):
        assert slub.ISSUER_INFO["has_issuer_id"].endswith("DE-14")

    def test_it_is_not_the_placeholder(self):
        """A record naming nobody must not have identifiers minted."""
        assert "unspecified" not in slub.ISSUER_INFO["has_issuer_id"]

    def test_the_source_key_is_the_number_the_library_uses(self):
        """MARC builds "(DE-627)1919666257"; the PPN is the number.

        Keeping the whole string gives one record two different keys
        depending on which converter read it, and nothing can be
        matched between the two results.

        """
        assert slub.PROFILE.source_key_pattern

    def test_the_house_relator_codes_are_known(self):
        """Codes this house uses beyond the common ones."""
        activities = slub.PROFILE.relator_activities
        assert activities["adp"] == ("WritingActivity", "Adaptation")
        assert activities["prn"] == (
            "ProducingActivity",
            "ProductionCompany",
        )

    def test_the_common_ones_are_still_there(self):
        assert slub.PROFILE.relator_activities["drt"] == (
            "DirectingActivity",
            "Director",
        )


class TestTheExportInPractice:
    def records(self, input_path):
        return from_.import_file(slub, input_path("sample_data.xml"))

    def test_an_rda_record_converts_at_all(self, input_path):
        """No 007, no usable 008/33; the carrier is in 338.

        Read only the fixed fields and this whole export is skipped.

        """
        assert self.records(input_path)

    def test_a_book_is_still_out_of_scope(self, input_path):
        """A library catalogue holds more than films."""
        keys = {
            key
            for record in self.records(input_path)
            for described in (
                record.described_by
                if isinstance(record.described_by, list)
                else [record.described_by]
            )
            for key in (described.has_source_key or [])
        }
        assert "1000000004" not in keys

    def test_the_linked_editions_are_one_work(self, input_path):
        """The reel and the digitised version are one film.

        Their titles differ — one carries "digitalisierte Fassung" —
        so a key derived from the title would not have found them.

        """
        works = [
            r
            for r in self.records(input_path)
            if r.category == "avefi:WorkVariant"
        ]
        assert len(works) == 2
        linked = next(
            w for w in works if len(w.described_by[0].has_source_key) > 1
        )
        assert sorted(linked.described_by[0].has_source_key) == [
            "1000000001",
            "1000000002",
        ]

    def test_each_edition_keeps_its_own_manifestation(self, input_path):
        manifestations = [
            r
            for r in self.records(input_path)
            if r.category == "avefi:Manifestation"
        ]
        assert len(manifestations) == 3


class TestThePhysicalDescription:
    """The copy is described in words here, not in fixed fields.

    "schwarz-weiß, stumm, positiv" in 300 $b instead of a 007 whose
    meaning depends on the category of carrier. Reading only the fixed
    fields leaves colour, sound and element type empty for the whole
    export.

    """

    def test_the_map_covers_the_terms_the_export_uses(self):
        terms = slub.PROFILE.physical_description_map
        for term in ("schwarz-weiß", "farbig", "stumm", "positiv"):
            assert term in terms

    def test_an_action_note_states_the_access_status(self):
        """A library keeps a copy for the long term and says so in 583."""
        assert (
            slub.PROFILE.action_note_access_map[
                "archivierung/langzeitarchivierung gewährleistet"
            ]
            == "Archive"
        )

    def test_the_copy_is_reachable_through_the_union_catalogue(self):
        """Agreed with the library: the catalogue page, not 856.

        The addresses in 856 point at the digitised copy in the
        house's own media library, which is a different thing and not
        what was asked for.

        """
        assert slub.PROFILE.web_resource_fields == ()
        assert "{identifier}" in slub.PROFILE.web_resource_template

    def test_the_address_is_built_from_the_record_identifier(self, input_path):
        records = from_.import_file(slub, input_path("sample_data.xml"))
        item = next(r for r in records if r.category == "avefi:Item")
        assert item.has_webresource == [
            "https://opac.k10plus.de/DB=2.299/PPN?PPN="
            + item.described_by.has_source_key[0]
        ]
