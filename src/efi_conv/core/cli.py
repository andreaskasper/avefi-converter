# To be imported in each subcommand module

import logging

import click

from .. import __version__

IMPORTERS = ["avportal", "fmdu"]
log = logging.getLogger(__name__)


def set_log_level(verbose: int, quiet: int):
    """Adjust the log level of the package logger.

    The level configured through the EFI_CONV_LOGLEVEL environment
    variable stays in effect unless one of the options is given.

    """
    if not (verbose or quiet):
        return
    package_logger = logging.getLogger(__package__.split(".")[0])
    level = logging.DEBUG if verbose else logging.ERROR
    package_logger.setLevel(level)
    for handler in package_logger.handlers:
        handler.setLevel(level)


@click.group()
@click.version_option(version=__version__, prog_name="efi-conv")
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Show debug output (overrides EFI_CONV_LOGLEVEL).",
)
@click.option(
    "-q",
    "--quiet",
    count=True,
    help="Show errors only (overrides EFI_CONV_LOGLEVEL).",
)
def cli_main(verbose, quiet):
    """Convert collection metadata to the AVefi schema and check it.

    Each converter reads the export format of one institution and
    produces records complying with the AVefi schema, ready to have
    persistent identifiers registered for them. Run

        efi-conv from --list-formats

    for the converters available in this installation, and

        efi-conv check FILE

    to validate generated records against the schema.

    """
    set_log_level(verbose, quiet)
