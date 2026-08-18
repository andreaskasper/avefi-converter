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
        assert "(DE-627)1000000004" not in keys

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
            "(DE-627)1000000001",
            "(DE-627)1000000002",
        ]

    def test_each_edition_keeps_its_own_manifestation(self, input_path):
        manifestations = [
            r
            for r in self.records(input_path)
            if r.category == "avefi:Manifestation"
        ]
        assert len(manifestations) == 3
