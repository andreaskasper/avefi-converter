"""Structured conversion report.

Values that cannot be converted must not disappear silently. Every
converter records them here, in addition to logging, so that the run
can be audited afterwards.

The collector is kept in a :class:`contextvars.ContextVar` so that
mapping code deep inside a converter can report an issue without every
function having to pass a report object around.

"""

from contextlib import contextmanager
import contextvars
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import logging
import os
import pathlib
import tempfile
from typing import Any

log = logging.getLogger(__name__)

REPORT_FORMAT_VERSION = "1.0"
ENCODING = "utf-8"

#: Severity values used in the report, ordered by increasing severity.
SEVERITIES = ("info", "warning", "error")

_current_report = contextvars.ContextVar("current_report", default=None)


@dataclass(frozen=True)
class ReportEntry:
    """One value that could not be converted as intended.

    Attributes
    ----------
    severity : str
        One of :data:`SEVERITIES`.
    message : str
        Human readable explanation.
    source_file : str or None
        Input file the value came from.
    record_id : str or None
        Identifier of the affected record in the source data.
    source_field : str or None
        Field or path in the source schema.
    target_field : str or None
        Field in the AVefi schema that could not be filled.
    raw_value : Any
        The value as found in the source data.

    """

    severity: str
    message: str
    source_file: str | None = None
    record_id: str | None = None
    source_field: str | None = None
    target_field: str | None = None
    raw_value: Any = None

    def __post_init__(self):
        """Reject unknown severities early."""
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"Unknown severity '{self.severity}',"
                f" expected one of {SEVERITIES}"
            )


@dataclass
class ConversionReport:
    """Collection of report entries for one conversion run."""

    entries: list[ReportEntry] = field(default_factory=list)
    source_file: str | None = None
    avefi_schema_version: str | None = None

    def add(self, severity: str, message: str, **kwargs) -> ReportEntry:
        """Record an issue and log it at the matching level."""
        kwargs.setdefault("source_file", self.source_file)
        entry = ReportEntry(severity=severity, message=message, **kwargs)
        self.entries.append(entry)
        log.log(
            {
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
            }[severity],
            format_entry(entry),
        )
        return entry

    def counts(self) -> dict[str, int]:
        """Return the number of entries per severity."""
        return {
            severity: sum(
                1 for entry in self.entries if entry.severity == severity
            )
            for severity in SEVERITIES
        }

    def to_dict(self) -> dict:
        """Return the report as a JSON serialisable dictionary."""
        from .. import __version__

        return {
            "report_format_version": REPORT_FORMAT_VERSION,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "efi_conv_version": __version__,
            "avefi_schema_version": self.avefi_schema_version,
            "summary": self.counts(),
            "entries": [asdict(entry) for entry in self.entries],
        }

    def write(self, to_file):
        """Write the report atomically as JSON."""
        target = pathlib.Path(to_file)
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent or pathlib.Path(),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding=ENCODING) as f:
                json.dump(
                    self.to_dict(),
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
                f.write("\n")
            os.replace(tmp_name, target)
        except BaseException:
            pathlib.Path(tmp_name).unlink(missing_ok=True)
            raise


def format_entry(entry: ReportEntry) -> str:
    """Return a one line rendering of ``entry`` for the log."""
    context = [
        part
        for part in (
            f"record {entry.record_id}" if entry.record_id else None,
            f"source {entry.source_field}" if entry.source_field else None,
            f"target {entry.target_field}" if entry.target_field else None,
            f"value {entry.raw_value!r}"
            if entry.raw_value is not None
            else None,
        )
        if part
    ]
    if context:
        return f"{entry.message} ({', '.join(context)})"
    return entry.message


def current_report() -> ConversionReport | None:
    """Return the report being collected, if any."""
    return _current_report.get()


def report_issue(severity: str, message: str, **kwargs):
    """Record an issue with the active report.

    Falls back to plain logging when no report is being collected, so
    that converters can call this unconditionally.

    """
    report = current_report()
    if report is None:
        entry = ReportEntry(severity=severity, message=message, **kwargs)
        log.log(
            {
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
            }[severity],
            format_entry(entry),
        )
        return entry
    return report.add(severity, message, **kwargs)


@contextmanager
def collecting(report: ConversionReport):
    """Collect reported issues in ``report`` for the duration."""
    token = _current_report.set(report)
    try:
        yield report
    finally:
        _current_report.reset(token)


@contextmanager
def for_file(source_file):
    """Attribute issues reported inside the block to ``source_file``."""
    report = current_report()
    if report is None:
        yield None
        return
    previous = report.source_file
    report.source_file = str(source_file)
    try:
        yield report
    finally:
        report.source_file = previous
