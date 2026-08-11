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
