"""Behaviour of ``efi-conv from`` when it is given several files.

One invocation is one conversion. The records of all its input files
are therefore grouped together, which is what the documented harvest
workflow depends on: ``efi-conv harvest`` writes one file per page,
and the pages of a harvest cut through the films rather than around
them.

"""

import json

from click.testing import CliRunner
import pytest

from efi_conv.core import from_
from efi_conv.lido import mapping as lido_mapping

# Importing efi_conv.main is what registers the subcommands.
from efi_conv.main import cli_main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def two_pages(lido_page, lido_record):
    """Two copies of one film, delivered as two harvest pages.

    The two records do not say quite the same thing about the film,
    which is the case in which the order the files are converted in
    could show in the output.

    """
    return (
        lido_page("page1.xml", lido_record("FMDU-0001", genre="Spielfilm")),
        lido_page(
            "page2.xml",
            lido_record("FMDU-0003", colour="farbe", genre="Kriegsfilm"),
        ),
    )


def convert(runner, tmp_path, *arguments):
    """Run the converter over the arguments and return its records."""
    target = tmp_path / "out.json"
    result = runner.invoke(
        cli_main,
        ["from", "-f", "fmdu.lido", "-o", str(target), *arguments],
    )
    assert result.exit_code == 0, result.output
    return json.loads(target.read_text(encoding="utf-8"))


def identifiers(records):
    """Return every identifier the records carry."""
    return [
        identifier["id"]
        for entry in records
        for identifier in entry["has_identifier"]
    ]


class TestOneContextPerInvocation:
    def test_two_files_describing_one_film_share_its_work(
        self, runner, tmp_path, two_pages
    ):
        first, second = two_pages
        records = convert(runner, tmp_path, str(first), str(second))
        works = [
            entry
            for entry in records
            if entry["category"] == "avefi:WorkVariant"
        ]
        assert len(works) == 1, (
            "One film described in two files is one work, not two"
        )
        assert sorted(works[0]["described_by"][0]["has_source_key"]) == [
            "FMDU-0001",
            "FMDU-0003",
        ]

    def test_identifiers_stay_unique_across_files(
        self, runner, tmp_path, two_pages
    ):
        first, second = two_pages
        found = identifiers(convert(runner, tmp_path, str(first), str(second)))
        assert len(found) == len(set(found)), (
            f"Duplicate identifiers minted across files: {found}"
        )

    def test_output_does_not_depend_on_the_order_of_the_files(
        self, runner, tmp_path, two_pages
    ):
        first, second = two_pages
        forwards = convert(runner, tmp_path, str(first), str(second))
        backwards = convert(runner, tmp_path, str(second), str(first))
        assert forwards == backwards

    def test_the_direct_api_still_converts_one_file_on_its_own(
        self, two_pages
    ):
        """efi_import(file) keeps its per file behaviour."""
        from efi_conv.fmdu import lido as fmdu_lido

        works = [
            entry
            for path in two_pages
            for entry in fmdu_lido.efi_import(path)
            if entry.category == "avefi:WorkVariant"
        ]
        assert len(works) == 2

    def test_a_converter_may_stay_out_of_it(self):
        """Only converters that take a context get a shared one."""
        from efi_conv import avportal

        assert from_.new_shared_context(avportal) is None


class TestRecordsLost:
    @pytest.fixture
    def export_with_one_bad_record(self, lido_page, lido_record):
        return lido_page(
            "export.xml",
            lido_record("FMDU-0001"),
            lido_record("FMDU-0002", title="Rheinbrücke", date="50er Jahre"),
        )

    def test_a_skipped_record_makes_the_run_exit_non_zero(
        self, runner, tmp_path, export_with_one_bad_record
    ):
        """A pipeline must not be told that a lossy run succeeded."""
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
                str(export_with_one_bad_record),
            ],
        )
        assert result.exit_code == 1, result.output
        assert json.loads(target.read_text(encoding="utf-8"))

    def test_the_report_counts_the_records_that_were_lost(
        self, runner, tmp_path, export_with_one_bad_record
    ):
        report = tmp_path / "report.json"
        runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "--continue-on-error",
                "-o",
                str(tmp_path / "out.json"),
                "--report",
                str(report),
                str(export_with_one_bad_record),
            ],
        )
        content = json.loads(report.read_text(encoding="utf-8"))
        assert content["summary"]["records_skipped"] == 1

    def test_a_run_that_loses_nothing_still_succeeds(
        self, runner, tmp_path, two_pages
    ):
        assert convert(runner, tmp_path, *(str(p) for p in two_pages))

    def test_a_skipped_record_leaves_no_dangling_work(
        self, runner, tmp_path, monkeypatch, lido_page, lido_record
    ):
        """The work of a failed record must not be half registered.

        The record is skipped after its work has been registered in
        the grouping context, so the next copy of the same film finds
        the work already known, emits nothing, and leaves its
        manifestation pointing at a work that is not in the output.

        """
        original = lido_mapping.build_item
        seen = []

        def failing_build_item(*args, **kwargs):
            seen.append(1)
            if len(seen) == 1:
                raise ValueError("no carrier information")
            return original(*args, **kwargs)

        monkeypatch.setattr(lido_mapping, "build_item", failing_build_item)
        source = lido_page(
            "export.xml",
            lido_record("FMDU-0001"),
            lido_record("FMDU-0003"),
        )
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
                str(source),
            ],
        )
        assert result.exit_code == 1, result.output
        records = json.loads(target.read_text(encoding="utf-8"))
        works = {
            identifier["id"]
            for entry in records
            if entry["category"] == "avefi:WorkVariant"
            for identifier in entry["has_identifier"]
        }
        referenced = {
            parent["id"]
            for entry in records
            if entry["category"] == "avefi:Manifestation"
            for parent in entry["is_manifestation_of"]
        }
        assert referenced <= works, (
            f"Manifestation refers to a work that was never written:"
            f" {referenced - works}"
        )


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


class TestNothingRecognised:
    """A file the converter cannot read is told apart from an empty one.

    Both produce no records. Only the first is a failure, and it is
    the converter that knows which of the two happened: it went
    looking for its record element and did not find it. ``from`` used
    to conclude it instead, from a run that produced no records and
    reported nothing about any record, which is right only for as long
    as every converter reports what it drops.

    """

    def run(self, runner, tmp_path, source):
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
                str(source),
            ],
        )
        return result, json.loads(report.read_text(encoding="utf-8"))

    def test_a_document_of_another_schema_fails(self, runner, tmp_path):
        source = tmp_path / "photos.xml"
        source.write_text(
            '<?xml version="1.0"?>\n<records><record/></records>\n',
            encoding="utf-8",
        )
        result, report = self.run(runner, tmp_path, source)
        assert result.exit_code != 0, result.output
        assert report["summary"]["files_unrecognised"] == 1

    def test_the_report_says_which_file_and_what_was_expected(
        self, runner, tmp_path
    ):
        source = tmp_path / "photos.xml"
        source.write_text(
            '<?xml version="1.0"?>\n<records><record/></records>\n',
            encoding="utf-8",
        )
        _, report = self.run(runner, tmp_path, source)
        unrecognised = [
            entry
            for entry in report["entries"]
            if entry["severity"] == "error"
            and "photos.xml" in entry["message"]
        ]
        assert unrecognised, report["entries"]
        message = unrecognised[0]["message"]
        assert "fmdu.lido" in message, "The converter has to be named"
        assert "lido" in unrecognised[0]["source_field"]

    def test_a_file_whose_records_were_filtered_still_succeeds(
        self, runner, tmp_path
    ):
        """The records were read; that they held no film is reported."""
        source = tmp_path / "photos.xml"
        source.write_text(NON_FILM_LIDO, encoding="utf-8")
        result, report = self.run(runner, tmp_path, source)
        assert result.exit_code == 0, result.output
        assert report["summary"]["files_unrecognised"] == 0
