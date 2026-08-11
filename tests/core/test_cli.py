"""Tests for the command line interface.

The CLI was previously untested: exit codes, output routing and the
error paths were only ever exercised by hand.

"""

import json
import pathlib

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
            "files_unrecognised",
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


SAMPLE_MARC = "tests/marc21/sample_data.xml"
SAMPLE_DC = "tests/dc/sample_data.xml"

#: A LIDO document holding one object that is not a film. It is read
#: without error and yields no records, and the report says why.
NON_FILM_LIDO = """\
<?xml version="1.0" encoding="UTF-8"?>
<lido:lidoWrap xmlns:lido="http://www.lido-schema.org">
  <lido:lido>
    <lido:lidoRecID lido:type="local">FOTO-1</lido:lidoRecID>
    <lido:descriptiveMetadata xml:lang="de">
      <lido:objectClassificationWrap>
        <lido:objectWorkTypeWrap>
          <lido:objectWorkType>
            <lido:term xml:lang="de">Fotografie</lido:term>
          </lido:objectWorkType>
        </lido:objectWorkTypeWrap>
      </lido:objectClassificationWrap>
      <lido:objectIdentificationWrap>
        <lido:titleWrap>
          <lido:titleSet lido:type="preferred">
            <lido:appellationValue xml:lang="de"
              >Ansicht der Brücke</lido:appellationValue>
          </lido:titleSet>
        </lido:titleWrap>
      </lido:objectIdentificationWrap>
    </lido:descriptiveMetadata>
  </lido:lido>
</lido:lidoWrap>
"""

ISSUER = {
    "has_issuer_id": "https://w3id.org/isil/DE-MUS-000000",
    "has_issuer_name": "Filmarchiv Musterstadt",
}


@pytest.fixture
def profile_file(tmp_path):
    """Write a usable profile for the Dublin Core converter."""
    target = tmp_path / "provider.json"
    target.write_text(
        json.dumps({"format": "dc", "issuer": ISSUER}), encoding="utf-8"
    )
    return str(target)


class TestErrorsAreReportedAsErrors:
    """A bad input file is the data provider's problem, not a bug.

    Handing efi-conv something it cannot read has to produce a message
    naming the file and what is wrong with it. A stack trace says
    where the tool noticed, which is of no use to whoever has to fix
    the export.

    """

    @pytest.fixture
    def unreadable(self, tmp_path, request):
        broken = tmp_path / "broken.xml"
        broken.write_bytes(request.param)
        return str(broken)

    @pytest.mark.parametrize(
        "unreadable",
        [
            pytest.param(b"", id="empty"),
            pytest.param(b"not xml at all\n", id="not-xml"),
            pytest.param(
                b'<?xml version="1.0"?>\n<lido:lidoWrap xmlns:lido="h',
                id="truncated",
            ),
        ],
        indirect=True,
    )
    def test_a_file_that_cannot_be_read_is_an_error(self, runner, unreadable):
        result = runner.invoke(
            cli_main, ["from", "-f", "fmdu.lido", unreadable]
        )
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "Error:" in result.output
        assert "broken.xml" in result.output

    def test_the_traceback_is_available_under_verbose(self, runner, tmp_path):
        broken = tmp_path / "broken.xml"
        broken.write_text("not xml at all\n", encoding="utf-8")
        result = runner.invoke(
            cli_main, ["-v", "from", "-f", "fmdu.lido", str(broken)]
        )
        assert result.exit_code == 1
        assert "Traceback (most recent call last)" in result.output

    def test_a_profile_error_is_an_error_not_a_traceback(
        self, runner, tmp_path
    ):
        profile = tmp_path / "profile.json"
        profile.write_text(
            json.dumps({"issuer": {"has_issuer_id": "not-a-uri"}}),
            encoding="utf-8",
        )
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "--profile",
                str(profile),
                SAMPLE_LIDO,
            ],
        )
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "Error:" in result.output

    def test_a_profile_for_another_converter_is_refused(
        self, runner, tmp_path
    ):
        profile = tmp_path / "profile.json"
        profile.write_text(
            json.dumps({"format": "en15907", "issuer": ISSUER}),
            encoding="utf-8",
        )
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "--profile",
                str(profile),
                SAMPLE_LIDO,
            ],
        )
        assert result.exit_code == 1
        assert "en15907" in result.output

    def test_the_mismatch_can_be_allowed_deliberately(self, runner, tmp_path):
        profile = tmp_path / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "format": "en15907",
                    "issuer": ISSUER,
                    # A profile replaces the vocabularies the converter
                    # ships, so a profile that names none accepts none
                    # of this provider's carrier terms.
                    "settings": {"film_work_type_terms": ["filmrolle"]},
                }
            ),
            encoding="utf-8",
        )
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "--profile",
                str(profile),
                "--allow-profile-format-mismatch",
                "-o",
                str(target),
                SAMPLE_LIDO,
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(target.read_text(encoding="utf-8"))


class TestWrongSchema:
    """Well-formed XML of another schema is not a successful run.

    Reading a document the converter recognises nothing in has to be
    reported. Exiting zero without writing anything tells a pipeline
    that the delivery held no films, which is a different statement
    altogether.

    """

    @pytest.mark.parametrize("format_", ["dc", "pbcore", "ebucore"])
    def test_marc_fed_to_another_converter_fails(
        self, runner, tmp_path, format_, caplog
    ):
        profile = tmp_path / f"{format_}.json"
        profile.write_text(
            json.dumps({"format": format_, "issuer": ISSUER}),
            encoding="utf-8",
        )
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                format_,
                "--profile",
                str(profile),
                "-o",
                str(target),
                SAMPLE_MARC,
            ],
        )
        assert result.exit_code != 0, result.output
        assert "sample_data.xml" in caplog.text
        assert format_ in caplog.text
        assert not target.exists()

    def test_the_reason_reaches_the_report(
        self, runner, tmp_path, profile_file
    ):
        report = tmp_path / "report.json"
        runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "dc",
                "--profile",
                profile_file,
                "--report",
                str(report),
                "-o",
                str(tmp_path / "out.json"),
                SAMPLE_MARC,
            ],
        )
        content = json.loads(report.read_text(encoding="utf-8"))
        assert content["summary"]["error"] >= 1
        assert any(
            "sample_data.xml" in (entry["source_file"] or "")
            for entry in content["entries"]
        )

    def test_a_file_whose_records_were_skipped_is_not_an_error(
        self, runner, tmp_path
    ):
        """The report already says why, which is what was asked for."""
        source = tmp_path / "photos.xml"
        source.write_text(NON_FILM_LIDO, encoding="utf-8")
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "-o",
                str(tmp_path / "out.json"),
                str(source),
            ],
        )
        assert result.exit_code == 0, result.output


class TestPlaceholderIssuer:
    """--list-formats says a profile is required, so one is required.

    The pipeline is from, check, register identifiers. A placeholder
    issuer that survives the first two steps is discovered at the one
    that cannot be undone.

    """

    def test_a_format_converter_without_a_profile_is_refused(
        self, runner, tmp_path
    ):
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main, ["from", "-f", "dc", "-o", str(target), SAMPLE_DC]
        )
        assert result.exit_code == 1
        assert "--profile" in result.output
        assert not target.exists()

    def test_a_profile_makes_it_run(self, runner, tmp_path, profile_file):
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "dc",
                "--profile",
                profile_file,
                "-o",
                str(target),
                SAMPLE_DC,
            ],
        )
        assert result.exit_code == 0, result.output
        records = json.loads(target.read_text(encoding="utf-8"))
        assert all(
            entry["has_issuer_id"] == ISSUER["has_issuer_id"]
            for record in records
            for entry in (
                record["described_by"]
                if isinstance(record["described_by"], list)
                else [record["described_by"]]
            )
        )

    def test_the_placeholder_can_be_accepted_deliberately(
        self, runner, tmp_path
    ):
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "dc",
                "--accept-placeholder-issuer",
                "-o",
                str(target),
                SAMPLE_DC,
            ],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_a_profile_that_keeps_the_placeholder_is_refused(
        self, runner, tmp_path
    ):
        profile = tmp_path / "placeholder.json"
        profile.write_text(
            json.dumps(
                {
                    "format": "dc",
                    "issuer": {
                        "has_issuer_id": (
                            "https://w3id.org/avefi/issuer/unspecified"
                        ),
                        "has_issuer_name": "Unspecified data provider",
                    },
                }
            ),
            encoding="utf-8",
        )
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "dc",
                "--profile",
                str(profile),
                "-o",
                str(tmp_path / "out.json"),
                SAMPLE_DC,
            ],
        )
        assert result.exit_code == 1
        assert "placeholder" in result.output

    def test_an_institution_converter_still_runs_without_a_profile(
        self, runner, tmp_path
    ):
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "-o",
                str(tmp_path / "out.json"),
                SAMPLE_LIDO,
            ],
        )
        assert result.exit_code == 0, result.output

    def test_list_formats_agrees_with_the_command(self, runner):
        result = runner.invoke(cli_main, ["from", "--list-formats"])
        assert result.exit_code == 0
        assert "Profile: required" in result.output
        assert "--accept-placeholder-issuer" in result.output


class TestOutputPaths:
    def test_a_character_device_can_be_written_to(self, runner):
        """-o /dev/null is how one runs a conversion for its report."""
        devnull = pathlib.Path("/dev/null")
        if not devnull.exists() or devnull.is_file():
            pytest.skip("no /dev/null on this platform")
        result = runner.invoke(
            cli_main,
            ["from", "-f", "fmdu.lido", "-o", str(devnull), SAMPLE_LIDO],
        )
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output
