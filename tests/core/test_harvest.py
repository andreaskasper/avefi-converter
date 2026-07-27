"""Harvesting from an OAI-PMH or SRU endpoint.

Every test runs against a fake transport. A test suite that reaches a
real endpoint is a test suite that fails when somebody else's server is
down, and harvesting somebody else's repository to run a unit test is
not a thing to do.

"""

import pathlib

import pytest

from efi_conv.core import harvest
from efi_conv.core.harvest import HarvestError

OAI = "http://www.openarchives.org/OAI/2.0/"
DC_RECORD = """
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
               xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title>Ein Film {number}</dc:title>
      <dc:type>MovingImage</dc:type>
      <dc:date>1959</dc:date>
      <dc:identifier>OAI-{number}</dc:identifier>
    </oai_dc:dc>
"""


def oai_response(numbers, token=None, deleted=0):
    """Return an OAI ListRecords response with these records."""
    records = "".join(
        f"<record><header><identifier>OAI-{number}</identifier></header>"
        f"<metadata>{DC_RECORD.format(number=number)}</metadata></record>"
        for number in numbers
    )
    records += "".join(
        f'<record><header status="deleted">'
        f"<identifier>GONE-{index}</identifier></header></record>"
        for index in range(deleted)
    )
    resumption = f"<resumptionToken>{token}</resumptionToken>" if token else ""
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<OAI-PMH xmlns="{OAI}"><ListRecords>{records}{resumption}'
        f"</ListRecords></OAI-PMH>"
    ).encode()


def oai_error(code, message="no"):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<OAI-PMH xmlns="{OAI}"><error code="{code}">{message}</error>'
        f"</OAI-PMH>"
    ).encode()


def sru_response(numbers, total, namespace="http://www.loc.gov/zing/srw/"):
    records = "".join(
        f"<record><recordData>{DC_RECORD.format(number=number)}"
        f"</recordData></record>"
        for number in numbers
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<searchRetrieveResponse xmlns="{namespace}">'
        f"<numberOfRecords>{total}</numberOfRecords>"
        f"<records>{records}</records></searchRetrieveResponse>"
    ).encode()


class FakeResponse:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}


class FakeSession:
    """Answers requests from a script, and records what was asked."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def no_sleep(monkeypatch):
    """Do not actually wait during a retry test."""
    waited = []
    monkeypatch.setattr(harvest.time, "sleep", waited.append)
    return waited


class TestOai:
    def test_follows_the_resumption_token(self, tmp_path):
        session = FakeSession(
            [
                FakeResponse(oai_response([1, 2], token="next")),
                FakeResponse(oai_response([3])),
            ]
        )
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        assert result.records == 3
        assert result.requests == 2
        assert len(result.files) == 2

    def test_a_token_replaces_the_other_arguments(self, tmp_path):
        """Sending them again alongside a token is a protocol error."""
        session = FakeSession(
            [
                FakeResponse(oai_response([1], token="next")),
                FakeResponse(oai_response([2])),
            ]
        )
        harvest.harvest_oai(
            "http://example.org/oai",
            "oai_dc",
            tmp_path,
            set_spec="film",
            session=session,
        )
        first, second = session.calls
        assert first[1]["metadataPrefix"] == "oai_dc"
        assert first[1]["set"] == "film"
        assert second[1] == {
            "verb": "ListRecords",
            "resumptionToken": "next",
        }

    def test_selective_harvesting_is_passed_on(self, tmp_path):
        session = FakeSession([FakeResponse(oai_response([1]))])
        harvest.harvest_oai(
            "http://example.org/oai",
            "lido",
            tmp_path,
            from_date="2026-01-01",
            until_date="2026-07-01",
            session=session,
        )
        params = session.calls[0][1]
        assert params["from"] == "2026-01-01"
        assert params["until"] == "2026-07-01"

    def test_deleted_records_are_counted_not_written(self, tmp_path):
        session = FakeSession([FakeResponse(oai_response([1], deleted=2))])
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        assert (result.records, result.deleted) == (1, 2)

    def test_no_records_matching_is_not_an_error(self, tmp_path):
        session = FakeSession([FakeResponse(oai_error("noRecordsMatch"))])
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        assert result.records == 0

    def test_another_oai_error_is_an_error(self, tmp_path):
        session = FakeSession(
            [FakeResponse(oai_error("cannotDisseminateFormat"))]
        )
        with pytest.raises(HarvestError, match="cannotDisseminateFormat"):
            harvest.harvest_oai(
                "http://example.org/oai",
                "nonsense",
                tmp_path,
                session=session,
            )

    def test_a_repeated_token_does_not_harvest_for_ever(self, tmp_path):
        session = FakeSession(
            [
                FakeResponse(oai_response([1], token="same")),
                FakeResponse(oai_response([2], token="same")),
            ]
        )
        with pytest.raises(HarvestError, match="for ever"):
            harvest.harvest_oai(
                "http://example.org/oai",
                "oai_dc",
                tmp_path,
                session=session,
            )

    def test_the_limit_stops_the_harvest(self, tmp_path):
        session = FakeSession(
            [FakeResponse(oai_response([1, 2, 3], token="next"))]
        )
        result = harvest.harvest_oai(
            "http://example.org/oai",
            "oai_dc",
            tmp_path,
            limit=2,
            session=session,
        )
        assert result.records == 3
        assert result.requests == 1

    def test_a_malformed_response_is_an_error(self, tmp_path):
        session = FakeSession([FakeResponse(b"<not xml")])
        with pytest.raises(HarvestError, match="did not answer with XML"):
            harvest.harvest_oai(
                "http://example.org/oai",
                "oai_dc",
                tmp_path,
                session=session,
            )


class TestRetrying:
    def test_a_503_is_retried_after_the_time_the_server_asked_for(
        self, tmp_path, no_sleep
    ):
        session = FakeSession(
            [
                FakeResponse(b"", 503, {"Retry-After": "7"}),
                FakeResponse(oai_response([1])),
            ]
        )
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        assert result.records == 1
        assert no_sleep == [7.0]

    def test_a_retry_after_header_that_is_not_a_number_is_survivable(
        self, tmp_path, no_sleep
    ):
        session = FakeSession(
            [
                FakeResponse(b"", 503, {"Retry-After": "Wed, 21 Oct 2026"}),
                FakeResponse(oai_response([1])),
            ]
        )
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        assert result.records == 1
        assert no_sleep and no_sleep[0] > 0

    def test_giving_up_reports_the_status(self, tmp_path, no_sleep):
        session = FakeSession([FakeResponse(b"", 503)] * 5)
        with pytest.raises(HarvestError, match="503"):
            harvest.harvest_oai(
                "http://example.org/oai",
                "oai_dc",
                tmp_path,
                session=session,
            )

    def test_a_status_not_worth_retrying_fails_at_once(self, tmp_path):
        session = FakeSession([FakeResponse(b"", 404)])
        with pytest.raises(HarvestError, match="404"):
            harvest.harvest_oai(
                "http://example.org/oai",
                "oai_dc",
                tmp_path,
                session=session,
            )
        assert len(session.calls) == 1


class TestSru:
    def test_pages_until_the_reported_total_is_reached(self, tmp_path):
        session = FakeSession(
            [
                FakeResponse(sru_response([1, 2], total=3)),
                FakeResponse(sru_response([3], total=3)),
            ]
        )
        result = harvest.harvest_sru(
            "http://example.org/sru",
            "dc.title=film",
            tmp_path,
            page_size=2,
            session=session,
        )
        assert result.records == 3
        assert session.calls[1][1]["startRecord"] == 3

    def test_the_record_schema_is_passed_on(self, tmp_path):
        session = FakeSession([FakeResponse(sru_response([1], total=1))])
        harvest.harvest_sru(
            "http://example.org/sru",
            "pica.all=film",
            tmp_path,
            record_schema="marcxml",
            session=session,
        )
        assert session.calls[0][1]["recordSchema"] == "marcxml"

    def test_the_later_srw_namespace_is_understood(self, tmp_path):
        session = FakeSession(
            [
                FakeResponse(
                    sru_response(
                        [1],
                        total=1,
                        namespace=(
                            "http://docs.oasis-open.org/ns/search-ws/"
                            "sruResponse"
                        ),
                    )
                )
            ]
        )
        result = harvest.harvest_sru(
            "http://example.org/sru", "x", tmp_path, session=session
        )
        assert result.records == 1

    def test_a_diagnostic_is_an_error(self, tmp_path):
        body = (
            b'<?xml version="1.0"?>'
            b'<searchRetrieveResponse xmlns="http://www.loc.gov/zing/srw/">'
            b'<diagnostics><diagnostic xmlns="http://www.loc.gov/zing/srw/'
            b'diagnostic/"><uri>info:srw/diagnostic/1/10</uri>'
            b"<message>Query syntax error</message></diagnostic>"
            b"</diagnostics></searchRetrieveResponse>"
        )
        session = FakeSession([FakeResponse(body)])
        with pytest.raises(HarvestError, match="Query syntax error"):
            harvest.harvest_sru(
                "http://example.org/sru", "bad(", tmp_path, session=session
            )

    def test_an_empty_page_ends_the_harvest(self, tmp_path):
        session = FakeSession(
            [
                FakeResponse(sru_response([1], total=99)),
                FakeResponse(sru_response([], total=99)),
            ]
        )
        result = harvest.harvest_sru(
            "http://example.org/sru",
            "x",
            tmp_path,
            page_size=1,
            session=session,
        )
        assert result.records == 1


class TestWhatIsWritten:
    """The output has to be usable as input, or the step is pointless."""

    def test_a_harvest_converts_without_further_handling(self, tmp_path):
        from efi_conv import dc
        from efi_conv.core import avefi, from_

        session = FakeSession(
            [
                FakeResponse(oai_response([1, 2], token="next")),
                FakeResponse(oai_response([3])),
            ]
        )
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        records = []
        for path in result.files:
            records.extend(from_.import_file(dc, path))
        items = [r for r in records if r.category == "avefi:Item"]
        assert len(items) == 3
        assert avefi.dumps(records)

    def test_the_payload_is_written_as_the_provider_sent_it(self, tmp_path):
        session = FakeSession([FakeResponse(oai_response([1]))])
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        written = pathlib.Path(result.files[0]).read_text(encoding="utf-8")
        assert "Ein Film 1" in written
        assert "oai_dc:dc" in written or "oai_dc/" in written
        # The OAI envelope is not carried over into the payload file.
        assert "ListRecords" not in written

    def test_pages_are_named_in_harvest_order(self, tmp_path):
        session = FakeSession(
            [
                FakeResponse(oai_response([1], token="next")),
                FakeResponse(oai_response([2])),
            ]
        )
        result = harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", tmp_path, session=session
        )
        assert [pathlib.Path(f).name for f in result.files] == [
            "page-00001.xml",
            "page-00002.xml",
        ]

    def test_the_output_directory_is_created(self, tmp_path):
        target = tmp_path / "deep" / "harvest"
        session = FakeSession([FakeResponse(oai_response([1]))])
        harvest.harvest_oai(
            "http://example.org/oai", "oai_dc", target, session=session
        )
        assert target.is_dir()


class TestCommandLine:
    def test_oai_without_a_metadata_prefix_is_refused(self, tmp_path):
        from click.testing import CliRunner

        from efi_conv.core.cli import cli_main

        result = CliRunner().invoke(
            cli_main,
            ["harvest", "-u", "http://example.org/oai", "-o", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "metadata-prefix" in result.output

    def test_sru_without_a_query_is_refused(self, tmp_path):
        from click.testing import CliRunner

        from efi_conv.core.cli import cli_main

        result = CliRunner().invoke(
            cli_main,
            [
                "harvest",
                "-p",
                "sru",
                "-u",
                "http://example.org/sru",
                "-o",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0
        assert "--query" in result.output
