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
