"""Pieces every command line entry point of efi-conv shares.

Besides the click group the subcommands hang off, this holds the two
things that decide what a failing run looks like: how an unusable
input file is described, and how that description reaches the user.
Both are needed twice, because a converter is run through
``efi-conv from`` and through ``python -m efi_conv.<name>``, and the
package READMEs document the second as the way to run one while
developing a mapping.

"""

import logging
import pathlib
import sys
import traceback

import click
from lxml import etree

from .. import __version__
from . import avefi

#: Converters available in this installation, in the order
#: `efi-conv from --list-formats` prints them. The name is the module
#: path below efi_conv, so that a converter is registered by adding it
#: here and nowhere else.
IMPORTERS = [
    "avportal",
    "dc",
    "ddb.lido",
    "ebucore",
    "en15907",
    "fmdu",
    "fmdu.lido",
    "marc21",
    "mdigital.lido",
    "pbcore",
]
log = logging.getLogger(__name__)

#: Whether a reported error should carry its Python traceback. A data
#: provider needs the message; whoever is debugging the converter
#: needs the traceback, and asks for it with -v.
_traceback_wanted = False


def set_log_level(verbose: int, quiet: int):
    """Adjust the log level of the package logger.

    The level configured through the EFI_CONV_LOGLEVEL environment
    variable stays in effect unless one of the options is given.

    """
    global _traceback_wanted
    _traceback_wanted = bool(verbose)
    if not (verbose or quiet):
        return
    package_logger = logging.getLogger(__package__.split(".")[0])
    level = logging.DEBUG if verbose else logging.ERROR
    package_logger.setLevel(level)
    for handler in package_logger.handlers:
        handler.setLevel(level)


def show_traceback() -> bool:
    """Return True if errors should be shown with their traceback."""
    return _traceback_wanted


def describe_input_error(input_file, error: BaseException) -> str:
    """Return what is wrong with ``input_file``, in one line.

    A data provider handed a stack trace learns where efi-conv noticed
    the problem, which is not the same as what is wrong with the file
    they have to correct.

    Parameters
    ----------
    input_file
        The file that was being read.
    error : BaseException
        What was raised while reading it.

    Returns
    -------
    str
        A message naming the file and what is wrong with it.

    """
    if isinstance(error, click.ClickException):
        return error.format_message()
    if isinstance(error, FileNotFoundError):
        return f"No such file: {input_file}"
    if isinstance(error, IsADirectoryError):
        return (
            f"{input_file} is a directory, not a file. Name the files"
            f" to convert, for instance"
            f" {str(input_file).rstrip('/')}/*.xml"
        )
    if isinstance(error, PermissionError):
        return f"Cannot read {input_file}: permission denied"
    if isinstance(error, UnicodeDecodeError):
        return (
            f"Cannot decode {input_file}: {error}. The file is not in"
            f" the encoding it declares"
        )
    if isinstance(error, etree.XMLSyntaxError):
        return (
            f"{input_file} is not well-formed XML ({error}). Check that"
            f" the export is complete and that it really is the format"
            f" the converter expects"
        )
    return f"Cannot convert {input_file}: {type(error).__name__}: {error}"


def user_error(
    message: str, error: BaseException | None = None
) -> click.ClickException:
    """Return an error to report to whoever ran the command.

    Click prints it as ``Error: <message>`` and exits 1, without the
    traceback. The traceback is appended when -v asked for it, because
    the person debugging a converter needs exactly what the person
    delivering the data does not.

    """
    if error is not None and show_traceback():
        message = "{}\n\n{}".format(
            message,
            "".join(traceback.format_exception(error)).rstrip(),
        )
    return click.ClickException(message)


def write_records(records, output) -> None:
    """Write AVefi ``records`` to ``output``.

    Normally that is the atomic replace of :func:`efi_conv.core.avefi.
    dump`, which writes next to the target and renames. An output that
    is not a regular file cannot be replaced by a rename, and
    ``-o /dev/null`` is how one runs a conversion for its report
    alone, so such a target is written to directly.

    """
    target = pathlib.Path(output)
    try:
        if target.exists() and not target.is_file():
            with target.open("w", encoding=avefi.ENCODING) as f:
                f.write(avefi.dumps(records, indent=2))
        else:
            avefi.dump(records, str(target))
    except OSError as e:
        raise user_error(f"Cannot write {output}: {e}", e) from e


def run_converter_main(argv, usage: str, efi_import) -> int:
    """Run one converter as ``python -m efi_conv.<name>``.

    Shared by the ``main(argv=None)`` entry points of the converters.
    Every package README documents them as the way to run a converter
    while developing a mapping, so they are the first thing a new data
    provider tries, with whatever file they have to hand. They
    therefore report a bad file the way ``efi-conv from`` does.

    Parameters
    ----------
    argv : list or None
        Arguments without the program name, ``sys.argv[1:]`` if None.
    usage : str
        Usage text, printed for ``--help`` and for no arguments.
    efi_import : callable
        The ``efi_import`` of the converter being run.

    Returns
    -------
    int
        0 for success, 1 for a file that could not be converted, 2 for
        a usage error.

    """
    argv = sys.argv[1:] if argv is None else list(argv)
    verbose = 0
    while argv and argv[0] in ("-v", "--verbose"):
        verbose += 1
        argv.pop(0)
    set_log_level(verbose, 0)
    if not argv or argv[0] in ("-h", "--help"):
        print(usage, file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    if len(argv) > 2:
        print("Expected at most two arguments, see --help", file=sys.stderr)
        return 2
    input_file = argv[0]
    try:
        records = avefi.sort_records(efi_import(input_file))
        if len(argv) == 2:
            write_records(records, argv[1])
        else:
            print(avefi.dumps(records, indent=2))
    except Exception as e:
        message = describe_input_error(input_file, e)
        if show_traceback():
            message = "{}\n\n{}".format(
                message,
                "".join(traceback.format_exception(e)).rstrip(),
            )
        print(f"Error: {message}", file=sys.stderr)
        return 1
    return 0


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
