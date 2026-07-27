"""Profiles loaded from a file.

The point of these is that a conversion agreed once with a data
provider can be run again unattended for every later delivery, and
that the generic format converters get a real issuer instead of the
placeholder they ship with.

"""

import json

import pytest

from efi_conv import fmdu, marc21
from efi_conv.core import profiles
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
    def test_the_configured_importer_stands_in_for_the_module(
        self, tmp_path
    ):
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

    def test_a_mismatched_format_is_only_a_warning(self, tmp_path, caplog):
        path = write(tmp_path, {"format": "marc21", "issuer": ISSUER})
        importer = profiles.configure(fmdu_lido, path)
        assert importer.ISSUER_INFO == ISSUER
        assert "declares format" in caplog.text


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
        sample = pathlib.Path(__file__).parent.parent / "lido" / (
            "sample_data.xml"
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
