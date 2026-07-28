"""Entity declarations in third party input.

An XML entity is ordinary markup, and a record is serialised away from
the document type declaration that gave its entities a meaning. What
the record then says is not what the provider wrote, so a document
relying on entity declarations is refused rather than converted into
something quietly shorter.

"""

import json

from click.testing import CliRunner
from lxml import etree
import pytest

from efi_conv.core.xmlrecords import (
    EntityDeclarationError,
    iter_record_elements,
)

# Importing efi_conv.main is what registers the subcommands.
from efi_conv.main import cli_main

PLAIN = """\
<?xml version="1.0" encoding="UTF-8"?>
{doctype}<collection>
  <record><title>{title}</title></record>
</collection>
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def document(tmp_path):
    """Return a factory for a small document with a given doctype."""

    def write(name, doctype="", title="Die Brücke"):
        target = tmp_path / name
        target.write_text(
            PLAIN.format(doctype=doctype, title=title), encoding="utf-8"
        )
        return target

    return write


class TestInternalEntities:
    def test_a_declared_entity_is_refused(self, document):
        source = document(
            "internal.xml",
            doctype='<!DOCTYPE collection [ <!ENTITY archiv "Filmmuseum'
            ' D&#252;sseldorf"> ]>\n',
            title="Die Brücke (&archiv;)",
        )
        with pytest.raises(EntityDeclarationError) as excinfo:
            list(iter_record_elements(source, None, "record"))
        assert "archiv" in str(excinfo.value)

    def test_the_message_says_what_to_do(self, document):
        source = document(
            "internal.xml",
            doctype='<!DOCTYPE collection [ <!ENTITY archiv "x"> ]>\n',
            title="Die Brücke (&archiv;)",
        )
        with pytest.raises(EntityDeclarationError) as excinfo:
            list(iter_record_elements(source, None, "record"))
        assert "xmllint" in str(excinfo.value)

    def test_a_document_without_entities_is_read(self, document):
        source = document("plain.xml")
        found = list(iter_record_elements(source, None, "record"))
        assert len(found) == 1
        assert "Die Brücke".encode() in found[0]

    def test_predefined_entities_are_not_entity_declarations(self, document):
        """&amp; and character references are ordinary text."""
        source = document("amp.xml", title="Bild &amp; Ton &#252;")
        found = list(iter_record_elements(source, None, "record"))
        assert etree.fromstring(found[0]).findtext("title") == "Bild & Ton ü"


class TestExternalEntities:
    def test_an_external_entity_is_never_resolved(self, tmp_path, document):
        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRET\n", encoding="utf-8")
        source = document(
            "external.xml",
            doctype="<!DOCTYPE collection [ <!ENTITY xxe SYSTEM"
            f' "file://{secret}"> ]>\n',
            title="Die Brücke (&xxe;)",
        )
        with pytest.raises(EntityDeclarationError) as excinfo:
            list(iter_record_elements(source, None, "record"))
        assert "TOPSECRET" not in str(excinfo.value)


class TestEveryConverterBehavesTheSame:
    """The defect was not that it failed, but that it differed."""

    @pytest.fixture
    def lido_with_entity(self, lido_page, lido_record):
        return lido_page(
            "entity.xml",
            lido_record("FMDU-0001", title="Die Brücke (&archiv;)"),
            doctype='<!DOCTYPE lido:lidoWrap [ <!ENTITY archiv "Filmmuseum'
            ' D&#252;sseldorf"> ]>\n',
        )

    def test_lido_refuses_instead_of_losing_text(
        self, runner, tmp_path, lido_with_entity
    ):
        target = tmp_path / "out.json"
        result = runner.invoke(
            cli_main,
            [
                "from",
                "-f",
                "fmdu.lido",
                "-o",
                str(target),
                str(lido_with_entity),
            ],
        )
        assert result.exit_code != 0
        assert not target.exists()

    def test_the_refusal_reaches_the_report(
        self, runner, tmp_path, lido_with_entity
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
                str(lido_with_entity),
            ],
        )
        content = json.loads(report.read_text(encoding="utf-8"))
        assert any(
            "entit" in entry["message"].lower() for entry in content["entries"]
        ), content["entries"]

    def test_xxe_never_leaks_into_the_output(
        self, runner, tmp_path, lido_page, lido_record
    ):
        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRET\n", encoding="utf-8")
        source = lido_page(
            "xxe.xml",
            lido_record("FMDU-0001", title="Die Brücke (&xxe;)"),
            doctype="<!DOCTYPE lido:lidoWrap [ <!ENTITY xxe SYSTEM"
            f' "file://{secret}"> ]>\n',
        )
        result = runner.invoke(
            cli_main, ["from", "-f", "fmdu.lido", str(source)]
        )
        assert result.exit_code != 0
        assert "TOPSECRET" not in result.output

    def test_dublin_core_refuses_with_the_same_error(self, tmp_path):
        source = tmp_path / "dc.xml"
        source.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE records [ <!ENTITY archiv "Filmmuseum"> ]>\n'
            "<records"
            ' xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            "  <oai_dc:dc><dc:title>Die Brücke (&archiv;)</dc:title>"
            "<dc:identifier>DC-1</dc:identifier></oai_dc:dc>\n"
            "</records>\n",
            encoding="utf-8",
        )
        from efi_conv import dc

        with pytest.raises(EntityDeclarationError):
            dc.efi_import(source)
