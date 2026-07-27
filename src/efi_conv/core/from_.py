from collections import Counter
import importlib
import inspect
import logging
import types

from avefi_schema import model_pydantic_v2 as efi
import click

from . import avefi
from .check import schema_fingerprint
from .cli import IMPORTERS, cli_main
from .report import ConversionReport, collecting, for_file
from .utils import described_by_issuer

log = logging.getLogger(__name__)


def import_module_for(format_: str) -> types.ModuleType:
    """Return the converter module registered as ``format_``."""
    return importlib.import_module(f"..{format_}", __package__)


def print_formats(ctx, param, value):
    """Print the available converters and exit (eager option)."""
    if not value or ctx.resilient_parsing:
        return
    for format_ in IMPORTERS:
        try:
            mod = import_module_for(format_)
        except ImportError as e:  # pragma: no cover - defensive
            click.echo(f"{format_}\n    unavailable: {e}")
            continue
        description = getattr(mod, "DESCRIPTION", "")
        input_format = getattr(mod, "INPUT_FORMAT", "")
        issuer = getattr(mod, "ISSUER_INFO", {})
        click.echo(format_)
        if description:
            click.echo(f"    {description}")
        if input_format:
            click.echo(f"    Input:  {input_format}")
        if issuer:
            click.echo(
                f"    Issuer: {issuer.get('has_issuer_name', '')}"
                f" <{issuer.get('has_issuer_id', '')}>"
            )
    ctx.exit()


@cli_main.command("from")
@click.option(
    "--list-formats",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=print_formats,
    help="List available converters with their input format and exit.",
)
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
@click.option(
    "--report",
    "report_file",
    type=click.Path(dir_okay=False, writable=True),
    help="Write a structured JSON report of unconvertible values.",
)
@click.option(
    "--continue-on-error",
    is_flag=True,
    default=False,
    help="Skip input files that fail to convert instead of aborting.",
)
@click.argument("input_files", nargs=-1, type=click.Path(exists=True))
def efi_from(
    input_files,
    output=None,
    report_file=None,
    continue_on_error=False,
    **kwargs,
):
    """Convert files from some schema into a JSON file with AVefi records."""
    mod = import_module_for(kwargs["format"])
    generated_records = []
    failed_files = []
    report = ConversionReport(avefi_schema_version=schema_fingerprint())
    with collecting(report):
        for input_file in input_files:
            try:
                with for_file(input_file):
                    generated_records.extend(
                        import_file(
                            mod,
                            input_file,
                            continue_on_error=continue_on_error,
                        )
                    )
            except Exception as e:
                report.add(
                    "error",
                    f"Failed to convert file: {e}",
                    source_file=str(input_file),
                )
                if not continue_on_error:
                    if report_file:
                        report.write(report_file)
                    raise RuntimeError(
                        f"Failed to convert {input_file}"
                    ) from e
                failed_files.append(input_file)
    if generated_records:
        generated_records = avefi.sort_records(generated_records)
        if output and output != "-":
            avefi.dump(generated_records, output)
        else:
            print(avefi.dumps(generated_records, indent=2))
    else:
        log.warning(
            f"No records generated from {len(input_files)} input file(s),"
            f" nothing written"
        )
    log_summary(input_files, generated_records, failed_files, report)
    if report_file:
        report.write(report_file)
        log.info(f"Wrote conversion report to {report_file}")
    if failed_files:
        raise SystemExit(1)


def accepts_continue_on_error(importer: types.ModuleType) -> bool:
    """Return True if the converter can skip individual records."""
    try:
        signature = inspect.signature(importer.efi_import)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False
    return "continue_on_error" in signature.parameters


def log_summary(input_files, generated_records, failed_files, report=None):
    """Report what the run produced, per record category."""
    counts = Counter(record.category for record in generated_records)
    breakdown = ", ".join(
        f"{count} {category.removeprefix('avefi:')}"
        for category, count in sorted(counts.items())
    )
    log.info(
        f"Processed {len(input_files) - len(failed_files)} of"
        f" {len(input_files)} input file(s),"
        f" produced {len(generated_records)} record(s)"
        f"{f' ({breakdown})' if breakdown else ''}"
    )
    if failed_files:
        log.error(
            f"Skipped {len(failed_files)} file(s): {', '.join(failed_files)}"
        )


def import_file(
    importer: types.ModuleType,
    input_file: str,
    continue_on_error: bool = False,
) -> list[efi.MovingImageRecord]:
    """Convert one input file and complete the issuer information.

    Converters that can contain an error to the individual record
    declare a ``continue_on_error`` parameter on ``efi_import``; for
    the others the flag stays a file level decision, as before.

    """
    if continue_on_error and accepts_continue_on_error(importer):
        result = importer.efi_import(
            input_file, continue_on_error=continue_on_error
        )
    else:
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
