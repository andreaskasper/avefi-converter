"""`python -m efi_conv.<converter>` has to work for every converter.

Running a converter directly is what one does while developing a
mapping, before it is worth going through the command line interface.
An entry point that is never exercised is one that breaks unnoticed.

"""

import subprocess
import sys

import pytest

CONVERTERS = [
    "efi_conv.dc",
    "efi_conv.ddb.lido",
    "efi_conv.ebucore",
    "efi_conv.en15907",
    "efi_conv.fmdu.lido",
    "efi_conv.marc21",
    "efi_conv.mdigital.lido",
    "efi_conv.pbcore",
]


def run(module, *arguments):
    """Run a converter as a module and return the completed process."""
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("module", CONVERTERS)
def test_help_is_available(module):
    result = run(module, "--help")
    assert result.returncode == 0, result.stderr
    assert "efi-conv from -f" in result.stdout


@pytest.mark.parametrize("module", CONVERTERS)
def test_no_arguments_is_an_error(module):
    assert run(module).returncode == 2


@pytest.mark.parametrize("module", CONVERTERS)
def test_too_many_arguments_is_an_error(module):
    assert run(module, "a.xml", "b.json", "c.json").returncode == 2


#: The packages a profile-capable converter is reached through. Every
#: one of them has to re-export the same names, so that
#: ``efi_conv.<package>`` can be used wherever the module can.
PROFILE_CAPABLE_PACKAGES = [
    "efi_conv.dc",
    "efi_conv.ddb",
    "efi_conv.ebucore",
    "efi_conv.en15907",
    "efi_conv.marc21",
    "efi_conv.mdigital",
    "efi_conv.pbcore",
]


class TestBadInput:
    """A converter run directly has to fail the way the CLI does.

    Every package README documents ``python -m efi_conv.<name>`` as
    the way to run a converter while developing a mapping, so it is
    the first thing a new data provider tries, with whatever file they
    have to hand.

    """

    @pytest.mark.parametrize("module", CONVERTERS)
    def test_a_missing_file_is_an_error(self, module):
        result = run(module, "does-not-exist.xml")
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "No such file" in result.stderr

    @pytest.mark.parametrize("module", CONVERTERS)
    def test_a_directory_is_an_error(self, module, tmp_path):
        result = run(module, str(tmp_path))
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "directory" in result.stderr

    @pytest.mark.parametrize("module", CONVERTERS)
    def test_a_file_that_is_not_xml_is_an_error(self, module, tmp_path):
        broken = tmp_path / "broken.xml"
        broken.write_text("not xml at all\n", encoding="utf-8")
        result = run(module, str(broken))
        assert result.returncode == 1
        assert "Traceback" not in result.stderr
        assert "broken.xml" in result.stderr

    def test_the_traceback_is_available_under_verbose(self):
        result = run("efi_conv.dc", "-v", "does-not-exist.xml")
        assert result.returncode == 1
        assert "Traceback (most recent call last)" in result.stderr

    def test_main_returns_rather_than_raising(self):
        """main(argv) is called directly while developing a mapping."""
        from efi_conv.dc import main

        assert main(["does-not-exist.xml"]) == 1


class TestPackagesExportTheSameNames:
    """A converter package stands in for its module or it does not."""

    @pytest.mark.parametrize("package", PROFILE_CAPABLE_PACKAGES)
    @pytest.mark.parametrize(
        "name",
        [
            "DESCRIPTION",
            "INPUT_FORMAT",
            "ISSUER_INFO",
            "PROFILE",
            "PROFILE_CLASS",
            "convert",
            "efi_import",
            "main",
            "new_context",
        ],
    )
    def test_the_name_is_exported(self, package, name):
        import importlib

        module = importlib.import_module(package)
        assert hasattr(module, name), f"{package} does not export {name}"
        assert name in module.__all__, f"{package}.__all__ omits {name}"
