import importlib
import logging
import types

from avefi_schema import model_pydantic_v2 as efi
import click

from . import avefi
from .cli import IMPORTERS, cli_main
from .utils import described_by_issuer

log = logging.getLogger(__name__)


@cli_main.command("from")
@click.option(
    "-f",
    "--format",
    type=click.Choice(IMPORTERS),
    required=True,
    help="Source data format.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    help="Output file (stdout if not specified).",
)
@click.argument("input_files", nargs=-1, type=click.Path(exists=True))
def efi_from(input_files, output=None, **kwargs):
    """Convert files from some schema into a JSON file with AVefi records."""
    mod = importlib.import_module(f"..{kwargs['format']}", __package__)
    generated_records = []
    for input_file in input_files:
        try:
            generated_records.extend(import_file(mod, input_file))
        except Exception as e:
            raise RuntimeError(f"Failed to convert {input_file}") from e
    if generated_records:
        if output and output != "-":
            avefi.dump(generated_records, output)
        else:
            print(avefi.dumps(generated_records, indent=2))
    else:
        log.warning(
            f"No records generated from {len(input_files)} input file(s),"
            f" nothing written"
        )


def import_file(
    importer: types.ModuleType,
    input_file: str,
) -> list[efi.MovingImageRecord]:
    result = importer.efi_import(input_file)
    for record in result:
        if not (record.has_identifier):
            raise ValueError("has_identifier missing for some record(s)")
        described_by = described_by_issuer(record, importer.ISSUER_INFO)
        if not (described_by.has_source_key):
            log.warning(
                f"Records with unspecified source key in {input_file},"
                f" copying identifier to fill the gap"
            )
            described_by.has_source_key = [record.has_identifier[0].id]
        else:
            described_by.has_source_key.sort()
    return result
