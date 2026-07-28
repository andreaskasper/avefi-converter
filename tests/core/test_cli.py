"""Tests for the command line interface.

The CLI was previously untested: exit codes, output routing and the
error paths were only ever exercised by hand.

"""

import json

from click.testing import CliRunner
import pytest

# Importing efi_conv.main is what registers the subcommands.
from efi_conv.main import cli_main

SAMPLE_CSV = "tests/fmdu/sample_data.csv"
SAMPLE_LIDO = "tests/lido/sample_data.xml"


@pytest.fixture
def runner():
    return CliRunner()


class TestTopLevel:
    def test_help_describes_the_tool(self, runner):
        result = runner.invoke(cli_main, ["--help"])
        assert result.exit_code == 0
        assert "AVefi" in result.output
        assert "--list-formats" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli_main, ["--version"])
        assert result.exit_code == 0
        assert "efi-conv" in result.output


class TestListFormats:
    def test_lists_every_registered_importer(self, runner):
        result = runner.invoke(cli_main, ["from", "--list-formats"])
        assert result.exit_code == 0
        for expected in ("avportal", "fmdu", "fmdu.lido"):
            assert expected in result.output

    def test_shows_input_format_and_issuer(self, runner):
        result = runner.invoke(cli_main, ["from", "--list-formats"])
        assert "LIDO" in result.output
        assert "isil" in result.output

    def test_works_without_the_required_format_option(self, runner):
        """The eager flag must not trip over -f being required."""
        result = runner.invoke(cli_main, ["from", "--list-formats"])
        assert result.exit_code == 0
        assert "Missing option" not in result.output


class TestFrom:
    def test_writes_records_to_a_file(self, runner, tmp_path):
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            ["from", "-f", "fmdu.lido", "-o", str(target), SAMPLE_LIDO],
        )
        assert result.exit_code == 0, result.output
        records = json.loads(target.read_text(encoding="utf-8"))
        assert len(records) == 8

    def test_writes_to_stdout_without_output_option(self, runner):
        result = runner.invoke(
            cli_main, ["from", "-f", "fmdu.lido", SAMPLE_LIDO]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)

    def test_output_is_deterministic(self, runner, tmp_path):
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        for target in (first, second):
            runner.invoke(
                cli_main,
                [
                    "from",
                    "-f",
                    "fmdu.lido",
                    "-o",
                    str(target),
                    SAMPLE_LIDO,
                ],
            )
        assert first.read_bytes() == second.read_bytes()

    def test_unknown_format_is_rejected(self, runner):
        result = runner.invoke(
            cli_main, ["from", "-f", "nonsense", SAMPLE_CSV]
        )
        assert result.exit_code != 0
        assert "nonsense" in result.output

    def test_missing_input_file_is_rejected(self, runner):
        result = runner.invoke(
            cli_main, ["from", "-f", "fmdu", "does-not-exist.csv"]
        )
        assert result.exit_code != 0

    def test_a_broken_file_aborts_by_default(self, runner, tmp_path):
        broken = tmp_path / "broken.csv"
        broken.write_text("only;three;columns\n", encoding="utf-8")
        result = runner.invoke(cli_main, ["from", "-f", "fmdu", str(broken)])
        assert result.exit_code != 0

    def test_continue_on_error_skips_and_exits_non_zero(
        self, runner, tmp_path
    ):
        broken = tmp_path / "broken.csv"
        broken.write_text("only;three;columns\n", encoding="utf-8")
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "--continue-on-error",
                "-o",
                str(target),
                str(broken),
                SAMPLE_LIDO,
            ],
        )
        assert result.exit_code == 1
        assert json.loads(target.read_text(encoding="utf-8"))


class TestReport:
    def test_report_is_written_and_well_formed(self, runner, tmp_path):
        report = tmp_path / "report.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "-o",
                str(tmp_path / "out.json"),
                "--report",
                str(report),
                SAMPLE_LIDO,
            ],
        )
        assert result.exit_code == 0, result.output
        content = json.loads(report.read_text(encoding="utf-8"))
        assert content["report_format_version"]
        assert set(content["summary"]) == {
            "info",
            "warning",
            "error",
            "records_skipped",
        }
        assert content["entries"]

    def test_unmapped_role_appears_in_the_report(self, runner, tmp_path):
        report = tmp_path / "report.json"
        runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "-o",
                str(tmp_path / "out.json"),
                "--report",
                str(report),
                SAMPLE_LIDO,
            ],
        )
        content = json.loads(report.read_text(encoding="utf-8"))
        values = [entry["raw_value"] for entry in content["entries"]]
        assert "Kamera" in values, (
            "An agent that cannot be mapped must be reported, not dropped"
        )

    def test_report_records_the_schema_in_use(self, runner, tmp_path):
        report = tmp_path / "report.json"
        runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "-o",
                str(tmp_path / "out.json"),
                "--report",
                str(report),
                SAMPLE_LIDO,
            ],
        )
        content = json.loads(report.read_text(encoding="utf-8"))
        fingerprint = content["avefi_schema_version"]
        assert fingerprint is None or "sha256" in fingerprint


class TestCheck:
    def test_valid_file_passes(self, runner, tmp_path):
        target = tmp_path / "out.json"
        runner.invoke(
            cli_main,
            ["from", "-f", "fmdu.lido", "-o", str(target), SAMPLE_LIDO],
        )
        result = runner.invoke(cli_main, ["check", str(target)])
        assert result.exit_code == 0, result.output

    def test_missing_file_is_rejected(self, runner):
        result = runner.invoke(cli_main, ["check", "does-not-exist.json"])
        assert result.exit_code != 0


class TestDiff:
    def test_identical_files_report_no_deviation(self, runner, tmp_path):
        target = tmp_path / "out.json"
        runner.invoke(
            cli_main,
            ["from", "-f", "fmdu.lido", "-o", str(target), SAMPLE_LIDO],
        )
        result = runner.invoke(cli_main, ["diff", str(target), str(target)])
        assert result.exit_code == 0
        assert "No deviations found" in result.output

    def test_missing_records_exit_non_zero(self, runner, tmp_path):
        full = tmp_path / "full.json"
        partial = tmp_path / "partial.json"
        runner.invoke(
            cli_main,
            ["from", "-f", "fmdu.lido", "-o", str(full), SAMPLE_LIDO],
        )
        records = json.loads(full.read_text(encoding="utf-8"))
        partial.write_text(json.dumps(records[:3]), encoding="utf-8")
        result = runner.invoke(cli_main, ["diff", str(full), str(partial)])
        assert result.exit_code == 1
        assert "Missing from candidate" in result.output

    def test_json_output_is_machine_readable(self, runner, tmp_path):
        target = tmp_path / "out.json"
        runner.invoke(
            cli_main,
            ["from", "-f", "fmdu.lido", "-o", str(target), SAMPLE_LIDO],
        )
        result = runner.invoke(
            cli_main,
            ["diff", "--format", "json", str(target), str(target)],
        )
        assert result.exit_code == 0
        assert json.loads(result.output)["summary"]["missing"] == 0
