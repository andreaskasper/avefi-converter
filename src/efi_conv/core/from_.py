from collections import Counter
import importlib
import inspect
import logging
import types

from avefi_schema import model_pydantic_v2 as efi
import click

from . import avefi
from .check import schema_fingerprint
from .cli import (
    IMPORTERS,
    cli_main,
    describe_input_error,
    user_error,
    write_records,
)
from .profiles import (
    PLACEHOLDER_ISSUER_ID,
    ProfileError,
    configure,
    needs_a_profile,
)
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
        if needs_a_profile(mod):
            click.echo(
                "    Profile: required, this converter reads a format"
                " rather than one institution's export, so the issuer"
                " has to be supplied with --profile."
                " --accept-placeholder-issuer converts without one,"
                " for trying out a mapping; identifiers must not be"
                " registered for the records that produces"
            )
        elif hasattr(mod, "PROFILE_CLASS"):
            click.echo(
                "    Profile: optional, --profile replaces the"
                " vocabularies this converter ships"
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
    "--profile",
    "profile_file",
    type=click.Path(exists=True, dir_okay=False),
    help="Bind the converter to a mapping profile (JSON or TOML)."
    " Required for the generic format converters, which ship with a"
    " placeholder issuer rather than inventing one.",
)
@click.option(
    "--allow-profile-format-mismatch",
    is_flag=True,
    default=False,
    help="Use a profile written for another converter anyway.",
)
@click.option(
    "--accept-placeholder-issuer",
    is_flag=True,
    default=False,
    help="Convert although the issuer is still the documented"
    " placeholder. For trying out a mapping only: records naming an"
    " unspecified data provider must not have identifiers registered.",
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
    profile_file=None,
    allow_profile_format_mismatch=False,
    accept_placeholder_issuer=False,
    continue_on_error=False,
    **kwargs,
):
    """Convert files from some schema into a JSON file with AVefi records."""
    # The files of one run are converted in a defined order, so that
    # the output depends on which files were named rather than on the
    # order they were named in. Where two records describing one film
    # disagree, the first one seen decides, exactly as two records
    # inside one file do; without this, the same set of files would
    # convert differently depending on how the shell expanded them.
    input_files = sorted(input_files)
    format_ = kwargs["format"]
    mod = import_module_for(format_)
    try:
        importer = (
            configure(
                mod,
                profile_file,
                allow_format_mismatch=allow_profile_format_mismatch,
            )
            if profile_file
            else mod
        )
    except ProfileError as e:
        raise user_error(str(e), e) from e
    if needs_a_profile(importer) and not accept_placeholder_issuer:
        raise user_error(placeholder_issuer_message(format_, profile_file))
    generated_records = []
    failed_files = []
    unreadable_files = []
    report = ConversionReport(avefi_schema_version=schema_fingerprint())
    context = new_shared_context(importer)
    with collecting(report):
        for input_file in input_files:
            records_before = len(generated_records)
            entries_before = len(report.entries)
            skipped_before = report.records_skipped
            try:
                with for_file(input_file):
                    generated_records.extend(
                        import_file(
                            importer,
                            input_file,
                            continue_on_error=continue_on_error,
                            context=context,
                        )
                    )
            except Exception as e:
                message = describe_input_error(input_file, e)
                report.add("error", message, source_file=str(input_file))
                if not continue_on_error:
                    if report_file:
                        report.write(report_file)
                    raise user_error(message, e) from e
                failed_files.append(input_file)
                continue
            if len(generated_records) == records_before and not saw_records(
                report, entries_before, skipped_before
            ):
                unreadable_files.append(input_file)
                report.add(
                    "error",
                    unrecognised_input_message(input_file, format_, importer),
                    source_file=str(input_file),
                )
    if generated_records:
        sort_source_keys(generated_records)
        generated_records = avefi.sort_records(generated_records)
        if output and output != "-":
            write_records(generated_records, output)
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
    if failed_files or unreadable_files or report.records_skipped:
        raise SystemExit(1)


def placeholder_issuer_message(format_: str, profile_file) -> str:
    """Return why a run without a real issuer is refused.

    ``--list-formats`` says a profile is required for the format
    converters, and the documented pipeline is from, check, register
    identifiers. Nothing between the first step and the last notices a
    placeholder issuer, so the run that names an unspecified data
    provider is discovered at the one step that cannot be undone.

    """
    source = (
        f"the profile {profile_file} also names"
        if profile_file
        else f"the {format_} converter ships with"
    )
    return (
        f"Refusing to convert: {source} the placeholder issuer"
        f" {PLACEHOLDER_ISSUER_ID}. A converter cannot know whose"
        f" collection it is pointed at, and an ISIL must not be"
        f" guessed, so the data provider has to be named with"
        f" --profile FILE. Pass --accept-placeholder-issuer to convert"
        f" anyway while trying out a mapping; identifiers must not be"
        f" registered for records produced that way."
    )


def saw_records(report, entries_before: int, skipped_before: int) -> bool:
    """Return True if the converter reported on individual records.

    Used to tell a file this converter cannot read from one whose
    records it read and then left out. Both produce no output, but
    only the second is a documented outcome: a record that is filtered
    or skipped is reported, with the identifier of the record it
    concerns, which is what the README sends the user to the report
    for.

    """
    return report.records_skipped > skipped_before or any(
        entry.record_id for entry in report.entries[entries_before:]
    )


def unrecognised_input_message(input_file, format_: str, importer) -> str:
    """Return why a file that parsed produced nothing at all."""
    input_format = getattr(importer, "INPUT_FORMAT", "")
    expected = f", expected {input_format}" if input_format else ""
    return (
        f"Nothing in {input_file} could be read by the {format_}"
        f" converter{expected}. The file parsed, but it holds no"
        f" record this converter recognises, so it is either another"
        f" schema or another wrapper than the one expected."
    )


def accepts(importer, parameter: str) -> bool:
    """Return True if ``efi_import`` takes the named parameter."""
    try:
        signature = inspect.signature(importer.efi_import)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return False
    return parameter in signature.parameters


def accepts_continue_on_error(importer) -> bool:
    """Return True if the converter can skip individual records."""
    return accepts(importer, "continue_on_error")


def new_shared_context(importer):
    """Return the grouping context for one invocation, if there is one.

    One invocation of ``efi-conv from`` is one conversion, whatever
    the input happens to be split into: ``efi-conv harvest`` writes
    one file per page of a harvest, and the page boundaries have
    nothing to do with which records describe the same film. A
    converter that groups records therefore gets one context for the
    whole run instead of one per file, which is what keeps it from
    minting the same identifier twice.

    A converter opts in by taking a ``context`` parameter on
    ``efi_import`` and offering a ``new_context`` factory; for the
    others nothing changes, and every converter keeps its per file
    behaviour when ``efi_import`` is called directly.

    """
    factory = getattr(importer, "new_context", None)
    if factory is None or not accepts(importer, "context"):
        return None
    return factory()


def sort_source_keys(records):
    """Order the source keys of every record, once the run is over.

    A work is contributed to by every record describing it, and those
    may sit in different input files, so the keys cannot be ordered
    before the last file has been read. Without this the output would
    depend on the order the input files were named in.

    """
    for record in records:
        described_by = record.described_by
        if described_by is None:
            continue
        # described_by is multivalued on a WorkVariant only.
        entries = (
            described_by if isinstance(described_by, list) else [described_by]
        )
        for entry in entries:
            if entry.has_source_key:
                entry.has_source_key.sort()


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
    if report is not None and report.records_skipped:
        log.error(
            f"Skipped {report.records_skipped} record(s) that could not"
            f" be converted; see the conversion report"
        )


def import_file(
    importer: types.ModuleType,
    input_file: str,
    continue_on_error: bool = False,
    context=None,
) -> list[efi.MovingImageRecord]:
    """Convert one input file and complete the issuer information.

    Converters that can contain an error to the individual record
    declare a ``continue_on_error`` parameter on ``efi_import``; for
    the others the flag stays a file level decision, as before. The
    same applies to ``context``: a converter that groups records
    across the files of one run takes one, and a converter that does
    not is called as before.

    """
    arguments = {}
    if continue_on_error and accepts_continue_on_error(importer):
        arguments["continue_on_error"] = continue_on_error
    if context is not None and accepts(importer, "context"):
        arguments["context"] = context
    result = importer.efi_import(input_file, **arguments)
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
