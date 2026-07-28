"""Profiles loaded from a file.

The point of these is that a conversion agreed once with a data
provider can be run again unattended for every later delivery, and
that the generic format converters get a real issuer instead of the
placeholder they ship with.

"""

import json

import pytest

from efi_conv import fmdu, marc21
from efi_conv.core import from_, profiles
from efi_conv.core.profiles import ProfileError
from efi_conv.dc import DcProfile
from efi_conv.fmdu import lido as fmdu_lido
from efi_conv.lido import LidoProfile

ISSUER = {
    "has_issuer_id": "https://w3id.org/isil/DE-MUS-000000",
    "has_issuer_name": "Filmarchiv Musterstadt",
}


def write(tmp_path, document, name="profile.json"):
    """Write ``document`` as a profile file and return its path."""
    target = tmp_path / name
    target.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    return target


class TestLoading:
    def test_reads_json(self, tmp_path):
        path = write(tmp_path, {"issuer": ISSUER})
        assert profiles.load_profile_document(path)["issuer"] == ISSUER

    def test_reads_toml(self, tmp_path):
        path = tmp_path / "profile.toml"
        path.write_text(
            '[issuer]\nhas_issuer_id = "x"\nhas_issuer_name = "y"\n',
            encoding="utf-8",
        )
        document = profiles.load_profile_document(path)
        assert document["issuer"]["has_issuer_id"] == "x"

    def test_an_unknown_suffix_is_an_error(self, tmp_path):
        path = tmp_path / "profile.yaml"
        path.write_text("issuer: {}\n", encoding="utf-8")
        with pytest.raises(ProfileError, match="suffix"):
            profiles.load_profile_document(path)

    def test_malformed_json_is_an_error(self, tmp_path):
        path = tmp_path / "profile.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ProfileError, match="Cannot read"):
            profiles.load_profile_document(path)

    def test_a_list_at_the_top_level_is_an_error(self, tmp_path):
        path = tmp_path / "profile.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ProfileError, match="mapping at the top level"):
            profiles.load_profile_document(path)

    def test_a_future_format_version_is_refused(self, tmp_path):
        path = write(tmp_path, {"profile_format_version": "2.0"})
        with pytest.raises(ProfileError, match="format version"):
            profiles.load_profile_document(path)


class TestBuilding:
    def test_settings_not_given_keep_the_shipped_default(self):
        profile = profiles.build_profile({"issuer": ISSUER}, LidoProfile)
        assert profile.issuer_info == ISSUER
        assert profile.work_key_fields == LidoProfile.work_key_fields

    def test_a_list_becomes_the_declared_collection_type(self):
        """JSON has neither a set nor a tuple."""
        profile = profiles.build_profile(
            {
                "issuer": ISSUER,
                "settings": {
                    "film_work_type_terms": ["film", "schmalfilm"],
                    "work_key_fields": ["primary_title"],
                },
            },
            LidoProfile,
        )
        assert profile.film_work_type_terms == frozenset(
            {"film", "schmalfilm"}
        )
        assert profile.work_key_fields == ("primary_title",)

    def test_an_unknown_setting_is_an_error(self):
        """A misspelt vocabulary would otherwise lose every value."""
        with pytest.raises(ProfileError, match="colour_typ_map"):
            profiles.build_profile(
                {"issuer": ISSUER, "settings": {"colour_typ_map": {}}},
                LidoProfile,
            )

    def test_the_error_names_the_settings_that_do_exist(self):
        with pytest.raises(ProfileError, match="colour_type_map"):
            profiles.build_profile(
                {"issuer": ISSUER, "settings": {"nonsense": 1}},
                LidoProfile,
            )

    def test_the_issuer_is_required(self):
        with pytest.raises(ProfileError, match="issuer"):
            profiles.build_profile({"settings": {}}, LidoProfile)

    def test_an_issuer_without_an_id_is_refused(self):
        with pytest.raises(ProfileError, match="issuer"):
            profiles.build_profile(
                {"issuer": {"has_issuer_name": "x"}}, LidoProfile
            )

    def test_the_description_carries_over(self):
        profile = profiles.build_profile(
            {"issuer": ISSUER, "description": "Delivery 2026-07"},
            LidoProfile,
        )
        assert profile.description == "Delivery 2026-07"


class TestConfiguring:
    def test_the_configured_importer_stands_in_for_the_module(self, tmp_path):
        path = write(tmp_path, {"issuer": ISSUER})
        importer = profiles.configure(fmdu_lido, path)
        assert importer.ISSUER_INFO == ISSUER
        assert importer.INPUT_FORMAT == fmdu_lido.INPUT_FORMAT
        assert callable(importer.efi_import)

    def test_the_module_keeps_its_own_defaults(self, tmp_path):
        """Configuring one run must not change the next one."""
        path = write(tmp_path, {"issuer": ISSUER})
        profiles.configure(fmdu_lido, path)
        assert fmdu_lido.ISSUER_INFO != ISSUER
        assert fmdu_lido.PROFILE.issuer_info != ISSUER

    def test_a_converter_without_a_profile_is_refused(self, tmp_path):
        path = write(tmp_path, {"issuer": ISSUER})
        with pytest.raises(ProfileError, match="does not take a profile"):
            profiles.configure(fmdu, path)

    def test_a_matching_format_is_accepted(self, tmp_path):
        path = write(tmp_path, {"format": "fmdu.lido", "issuer": ISSUER})
        assert profiles.configure(fmdu_lido, path).ISSUER_INFO == ISSUER

    def test_a_profile_without_a_format_key_is_accepted(self, tmp_path):
        path = write(tmp_path, {"issuer": ISSUER})
        assert profiles.configure(fmdu_lido, path).ISSUER_INFO == ISSUER


class TestPlaceholderIssuer:
    """The generic format converters must not invent an issuer."""

    @pytest.mark.parametrize(
        "name", ["dc", "ebucore", "en15907", "marc21", "pbcore"]
    )
    def test_a_format_converter_says_it_needs_a_profile(self, name):
        import importlib

        module = importlib.import_module(f"efi_conv.{name}")
        assert profiles.needs_a_profile(module)

    def test_an_institution_converter_does_not(self):
        assert not profiles.needs_a_profile(fmdu_lido)

    def test_a_profile_replaces_the_placeholder(self, tmp_path):
        path = write(tmp_path, {"issuer": ISSUER})
        importer = profiles.configure(marc21, path)
        assert importer.ISSUER_INFO == ISSUER
        assert not profiles.needs_a_profile(importer)


class TestShippedExamples:
    """The example profiles have to keep working."""

    @pytest.mark.parametrize(
        ("filename", "module"),
        [
            ("filmarchiv-musterstadt.lido.json", "fmdu.lido"),
            ("filmarchiv-musterstadt.en15907.toml", "en15907"),
            ("filmarchiv-musterstadt.dc.json", "dc"),
        ],
    )
    def test_the_examples_load(self, filename, module):
        import importlib
        import pathlib

        path = (
            pathlib.Path(__file__).parent.parent.parent
            / "examples"
            / "profiles"
            / filename
        )
        importer = profiles.configure(
            importlib.import_module(f"efi_conv.{module}"), path
        )
        assert importer.ISSUER_INFO["has_issuer_id"].startswith("https://")

    def test_the_lido_example_configures_a_conversion(self, tmp_path):
        """Run the example, not just parse it.

        An example that does not convert anything is documentation of
        something that does not work.

        """
        import pathlib

        path = (
            pathlib.Path(__file__).parent.parent.parent
            / "examples"
            / "profiles"
            / "filmarchiv-musterstadt.lido.json"
        )
        importer = profiles.configure(fmdu_lido, path)
        sample = (
            pathlib.Path(__file__).parent.parent / "lido" / ("sample_data.xml")
        )
        records = importer.efi_import(sample)
        assert records
        for record in records:
            described_by = record.described_by
            entries = (
                described_by
                if isinstance(described_by, list)
                else [described_by]
            )
            assert all(
                entry.has_issuer_id == ISSUER["has_issuer_id"]
                for entry in entries
            )


def test_dc_takes_a_profile_too():
    assert profiles.build_profile({"issuer": ISSUER}, DcProfile)


class TestConfiguredImporterGroupsAcrossFiles:
    """A profile must not cost the grouping across input files.

    A configured conversion is the normal case for a data provider, so
    it has to mint identifiers exactly as the unconfigured one does.

    """

    @pytest.fixture
    def profile_file(self, tmp_path):
        return write(
            tmp_path,
            {"format": "fmdu.lido", "issuer": ISSUER},
            name="fmdu.json",
        )

    def test_the_configured_importer_offers_a_context(self, profile_file):
        importer = profiles.configure(fmdu_lido, profile_file)
        context = from_.new_shared_context(importer)
        assert context is not None
        assert context.profile.issuer_info == ISSUER

    def test_one_film_in_two_files_is_one_work(
        self, profile_file, lido_page, lido_record
    ):
        importer = profiles.configure(fmdu_lido, profile_file)
        context = from_.new_shared_context(importer)
        records = [
            record
            for name, colour in (("a.xml", "sw"), ("b.xml", "farbe"))
            for record in from_.import_file(
                importer,
                lido_page(name, lido_record(f"REC-{name}", colour=colour)),
                context=context,
            )
        ]
        works = [r for r in records if r.category == "avefi:WorkVariant"]
        assert len(works) == 1


class TestSettingTypes:
    """A mistyped setting has to be refused when the profile loads.

    The strict check on unknown names exists because a misspelt
    vocabulary would look like a working profile and quietly lose
    every value it was meant to map. A vocabulary of the wrong type is
    no better: it takes the conversion down somewhere in the middle,
    long after the profile that caused it was read.

    """

    def test_a_vocabulary_written_as_an_array_is_refused(self):
        with pytest.raises(ProfileError, match="colour_type_map"):
            profiles.build_profile(
                {
                    "issuer": ISSUER,
                    "settings": {"colour_type_map": ["sw", "farbe"]},
                },
                LidoProfile,
            )

    def test_a_flag_written_as_a_string_is_refused(self):
        with pytest.raises(ProfileError, match="map_decades"):
            profiles.build_profile(
                {"issuer": ISSUER, "settings": {"map_decades": "yes"}},
                LidoProfile,
            )

    def test_a_language_written_as_a_number_is_refused(self):
        with pytest.raises(ProfileError, match="default_language"):
            profiles.build_profile(
                {"issuer": ISSUER, "settings": {"default_language": 42}},
                DcProfile,
            )

    def test_the_message_names_the_value_and_the_expectation(self):
        with pytest.raises(ProfileError) as caught:
            profiles.build_profile(
                {
                    "issuer": ISSUER,
                    "settings": {"colour_type_map": ["sw", "farbe"]},
                },
                LidoProfile,
            )
        message = str(caught.value)
        assert "colour_type_map" in message
        assert "table" in message, "must say what was expected"
        assert "array" in message, "must say what was given"
        assert "sw" in message, "must show the value that was rejected"

    def test_an_array_where_a_collection_is_declared_still_works(self):
        """The conversion JSON needs must not be refused as a type error."""
        profile = profiles.build_profile(
            {
                "issuer": ISSUER,
                "settings": {
                    "film_work_type_terms": ["film"],
                    "work_key_fields": ["primary_title"],
                },
            },
            LidoProfile,
        )
        assert profile.film_work_type_terms == frozenset({"film"})
        assert profile.work_key_fields == ("primary_title",)

    def test_null_is_accepted_where_the_declared_type_allows_it(self):
        profile = profiles.build_profile(
            {"issuer": ISSUER, "settings": {"default_language": None}},
            LidoProfile,
        )
        assert profile.default_language is None

    def test_a_boolean_is_not_a_string(self):
        with pytest.raises(ProfileError, match="description"):
            profiles.build_profile(
                {"issuer": ISSUER, "settings": {"description": True}},
                LidoProfile,
            )

    def test_a_correctly_typed_profile_is_untouched(self):
        profile = profiles.build_profile(
            {
                "issuer": ISSUER,
                "settings": {
                    "map_decades": True,
                    "default_language": "ger",
                    "colour_type_map": {"sw": "BlackAndWhite"},
                },
            },
            LidoProfile,
        )
        assert profile.map_decades is True
        assert profile.default_language == "ger"
        assert profile.colour_type_map == {"sw": "BlackAndWhite"}


class TestIssuerCheck:
    """The issuer promised by the error message is the one checked.

    An issuer that is incomplete or not a URI is refused by the AVefi
    schema anyway, but only once the records exist, which is a
    pydantic error from the middle of a conversion rather than
    something the person who wrote the profile can act on.

    """

    def test_an_issuer_without_a_name_is_refused(self):
        with pytest.raises(ProfileError, match="has_issuer_name"):
            profiles.build_profile(
                {"issuer": {"has_issuer_id": ISSUER["has_issuer_id"]}},
                LidoProfile,
            )

    def test_an_empty_issuer_name_is_refused(self):
        with pytest.raises(ProfileError, match="has_issuer_name"):
            profiles.build_profile(
                {
                    "issuer": {
                        "has_issuer_id": ISSUER["has_issuer_id"],
                        "has_issuer_name": "   ",
                    }
                },
                LidoProfile,
            )

    def test_an_issuer_id_that_is_not_a_uri_is_refused(self):
        with pytest.raises(ProfileError, match="URI"):
            profiles.build_profile(
                {
                    "issuer": {
                        "has_issuer_id": "DE-MUS-000000",
                        "has_issuer_name": "Filmarchiv Musterstadt",
                    }
                },
                LidoProfile,
            )

    def test_an_issuer_that_is_not_a_table_is_refused(self):
        with pytest.raises(ProfileError, match="issuer"):
            profiles.build_profile({"issuer": ["x"]}, LidoProfile)

    def test_an_issuer_id_that_is_not_a_string_is_refused(self):
        with pytest.raises(ProfileError, match="has_issuer_id"):
            profiles.build_profile(
                {
                    "issuer": {
                        "has_issuer_id": 42,
                        "has_issuer_name": "Filmarchiv Musterstadt",
                    }
                },
                LidoProfile,
            )

    def test_a_complete_issuer_is_accepted(self):
        assert (
            profiles.build_profile({"issuer": ISSUER}, LidoProfile).issuer_info
            == ISSUER
        )

    def test_a_profile_that_only_names_the_id_never_reaches_pydantic(
        self, tmp_path
    ):
        """The failure has to happen while the profile is read."""
        path = write(
            tmp_path, {"issuer": {"has_issuer_id": ISSUER["has_issuer_id"]}}
        )
        with pytest.raises(ProfileError):
            profiles.configure(fmdu_lido, path)


class TestFormatMismatch:
    """A profile names the converter it was written for.

    Its vocabularies are the terms of one source schema, and they do
    not mean the same thing in another. Using it with a different
    converter stamps the issuer on records mapped by rules the profile
    was never checked against, which is a mistake rather than a
    preference.

    """

    def test_a_profile_for_another_converter_is_refused(self, tmp_path):
        path = write(tmp_path, {"format": "en15907", "issuer": ISSUER})
        with pytest.raises(ProfileError, match="en15907"):
            profiles.configure(fmdu_lido, path)

    def test_the_message_names_both_converters(self, tmp_path):
        path = write(tmp_path, {"format": "en15907", "issuer": ISSUER})
        with pytest.raises(ProfileError) as caught:
            profiles.configure(fmdu_lido, path)
        message = str(caught.value)
        assert "en15907" in message
        assert "fmdu.lido" in message
        assert "--allow-profile-format-mismatch" in message

    def test_the_mismatch_can_be_allowed_deliberately(self, tmp_path, caplog):
        path = write(tmp_path, {"format": "en15907", "issuer": ISSUER})
        importer = profiles.configure(
            fmdu_lido, path, allow_format_mismatch=True
        )
        assert importer.ISSUER_INFO == ISSUER
        assert "en15907" in caplog.text


class TestDcIsLikeTheOthers:
    """The Dublin Core package has to expose what the others do."""

    def test_the_package_carries_a_profile(self):
        import efi_conv.dc as dc

        assert dc.PROFILE.issuer_info == dc.ISSUER_INFO
        assert "PROFILE" in dc.__all__

    def test_the_package_has_a_docstring(self):
        import efi_conv.dc as dc

        assert dc.__doc__ and "efi-conv from -f dc" in dc.__doc__
