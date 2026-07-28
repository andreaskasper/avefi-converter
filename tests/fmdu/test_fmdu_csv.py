import json

from click.testing import CliRunner

from efi_conv.core import avefi, check, from_
from efi_conv.core.report import ConversionReport, collecting
from efi_conv.fmdu import csv as fmdu_csv

# Importing efi_conv.main is what registers the subcommands.
from efi_conv.main import cli_main


def test_map_to_efi(input_path, expected_output):
    efi_records = from_.import_file(fmdu_csv, input_path("sample_data.csv"))
    result_serialized = json.loads(avefi.dumps(efi_records))

    assert result_serialized == expected_output


def test_schema_compliance(input_path):
    schema_validator = check.get_schema_validator()
    efi_records = from_.import_file(fmdu_csv, input_path("sample_data.csv"))
    assert check.pass_checks(efi_records, schema_validator), (
        "Mapped data did not validate"
    )


class TestNothingRecognised:
    """An export without data rows is not a delivery of no films.

    Exiting zero without writing anything tells a pipeline that the
    export held nothing, which is a different statement from being
    unable to read it.

    """

    def header(self, input_path):
        """Return the header line of the sample export."""
        return input_path("sample_data.csv").read_bytes().split(b"\n")[0]

    def test_a_file_without_data_rows_is_reported(self, input_path, tmp_path):
        source = tmp_path / "header_only.csv"
        source.write_bytes(self.header(input_path) + b"\n")
        report = ConversionReport()
        with collecting(report):
            assert fmdu_csv.efi_import(source) == []
        assert report.files_unrecognised == 1
        assert str(source) in report.entries[-1].message

    def test_an_empty_file_is_reported(self, tmp_path):
        source = tmp_path / "empty.csv"
        source.write_bytes(b"")
        report = ConversionReport()
        with collecting(report):
            assert fmdu_csv.efi_import(source) == []
        assert report.files_unrecognised == 1

    def test_the_command_exits_non_zero(self, input_path, tmp_path):
        source = tmp_path / "header_only.csv"
        source.write_bytes(self.header(input_path) + b"\n")
        result = CliRunner().invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu",
                "-o",
                str(tmp_path / "out.json"),
                str(source),
            ],
        )
        assert result.exit_code != 0, result.output

    def test_a_file_with_rows_reports_nothing(self, input_path):
        report = ConversionReport()
        with collecting(report):
            fmdu_csv.efi_import(input_path("sample_data.csv"))
        assert report.files_unrecognised == 0
