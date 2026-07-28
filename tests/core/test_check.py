import copy
import json

from click.testing import CliRunner
import pytest

from efi_conv.core import avefi, check, profiles

# Importing efi_conv.main is what registers the subcommands.
from efi_conv.main import cli_main

WORK = {
    "category": "avefi:WorkVariant",
    "type": "Monographic",
    "has_primary_title": {
        "type": "PreferredTitle",
        "has_name": "Die Brücke",
    },
    "has_identifier": [{"category": "avefi:LocalResource", "id": "w1"}],
}
MANIFESTATION = {
    "category": "avefi:Manifestation",
    "has_primary_title": {"type": "TitleProper", "has_name": "Die Brücke"},
    "is_manifestation_of": [{"category": "avefi:LocalResource", "id": "w1"}],
    "has_identifier": [{"category": "avefi:LocalResource", "id": "m1"}],
}
ITEM = {
    "category": "avefi:Item",
    "has_primary_title": {"type": "TitleProper", "has_name": "Die Brücke"},
    "is_item_of": {"category": "avefi:LocalResource", "id": "m1"},
    "has_identifier": [{"category": "avefi:LocalResource", "id": "i1"}],
}


def records(*dicts):
    return avefi.loads(json.dumps([copy.deepcopy(d) for d in dicts]))


@pytest.fixture
def validator():
    return check.get_schema_validator()


class TestPeriods:
    """The period rules, previously asserted inside `if` blocks."""

    def test_analytic_works_validate(self, input_path, validator):
        sample_file = input_path("data_analytic_works.json")
        efi_records = avefi.load(sample_file)
        assert efi_records, "Fixture must not be empty"
        assert check.pass_checks(efi_records, validator), (
            f"Failed to validate {sample_file}"
        )

    def test_valid_period_passes(self, input_path, validator):
        efi_records = avefi.load(input_path("data_analytic_works.json"))
        assert check.pass_checks(efi_records, validator)

    @pytest.mark.parametrize(
        ("period", "expected"),
        [("1975/1976", True), ("1975/1975", True), ("1976/1975", False)],
    )
    def test_period_order(self, input_path, validator, period, expected):
        efi_records = avefi.load(input_path("data_analytic_works.json"))
        record = copy.deepcopy(efi_records[0])
        assert record.has_event, "Fixture record must carry an event"
        record.has_event[0].has_date = period

        assert (
            check.pass_checks([record], validator, remove_invalid=False)
            is expected
        )


class TestRemoveInvalid:
    """The destructive paths, which had no coverage at all."""

    def test_unresolvable_reference_is_reported(self, validator):
        orphan = records(ITEM)
        assert not check.pass_checks(orphan, validator)

    def test_unresolvable_reference_is_purged_on_request(self, validator):
        orphan = records(ITEM)
        check.pass_checks(orphan, validator, remove_invalid=True)
        assert orphan == []

    def test_complete_hierarchy_survives_a_purge(self, validator):
        complete = records(WORK, MANIFESTATION, ITEM)
        assert check.pass_checks(complete, validator, remove_invalid=True)
        assert len(complete) == 3

    def test_work_without_items_is_dangling(self, validator):
        assert not check.pass_checks(records(WORK), validator)

    def test_dangling_work_is_removed_on_request(self, validator):
        lonely = records(WORK)
        check.pass_checks(lonely, validator, remove_invalid=True)
        assert lonely == []

    def test_duplicate_identifiers_are_rejected(self, validator):
        duplicate = records(WORK, WORK, MANIFESTATION, ITEM)
        with pytest.raises(ValueError, match="not unique"):
            check.pass_checks(duplicate, validator)

    def test_duplicate_identifiers_are_removed_on_request(self, validator):
        duplicate = records(WORK, WORK, MANIFESTATION, ITEM)
        check.pass_checks(duplicate, validator, remove_invalid=True)
        identifiers = [
            identifier.id
            for record in duplicate
            for identifier in record.has_identifier
        ]
        assert len(identifiers) == len(set(identifiers))

    def test_removing_a_parent_removes_its_children(self, validator):
        broken_work = copy.deepcopy(WORK)
        broken_work["has_primary_title"]["has_name"] = "x" * 1000
        hierarchy = records(broken_work, MANIFESTATION, ITEM)
        check.pass_checks(hierarchy, validator, remove_invalid=True)
        assert hierarchy == [], (
            "Children of a removed record must not survive it"
        )

    def test_a_reference_cycle_terminates(self, validator):
        """Mutually referencing records used to exhaust the stack."""
        first = copy.deepcopy(WORK)
        second = copy.deepcopy(WORK)
        second["has_identifier"] = [
            {"category": "avefi:LocalResource", "id": "w2"}
        ]
        first["is_part_of"] = [{"category": "avefi:LocalResource", "id": "w2"}]
        second["is_part_of"] = [
            {"category": "avefi:LocalResource", "id": "w1"}
        ]
        first["type"] = second["type"] = "Analytic"
        cycle = records(first, second)

        # The assertion that matters is that this returns at all: the
        # purge used to recurse until the stack was exhausted.
        assert isinstance(
            check.pass_checks(cycle, validator, remove_invalid=True), bool
        )


class TestFieldLimits:
    def test_overlong_title_is_invalid(self, validator):
        record = copy.deepcopy(WORK)
        record["has_primary_title"]["has_name"] = "x" * 1000
        assert check.has_invalid_value(records(record)[0])

    def test_title_at_the_limit_is_accepted(self, validator):
        from efi_conv.core.settings import settings

        record = copy.deepcopy(WORK)
        record["has_primary_title"]["has_name"] = "x" * settings.line_limit
        assert not check.exceeds_field_limit(records(record)[0])


class TestPreserveStatusRemoved:
    """The option used to be declared but never passed on."""

    def _removed_item(self):
        item = copy.deepcopy(ITEM)
        item["has_access_status"] = "Removed"
        return records(item)[0]

    def test_removed_without_pid_is_invalid_by_default(self):
        assert check.has_invalid_value(self._removed_item())

    def test_removed_without_pid_is_accepted_when_preserved(self):
        assert not check.has_invalid_value(
            self._removed_item(), preserve_status_removed=True
        )


class TestSchemaCache:
    def test_fingerprint_identifies_the_schema(self):
        fingerprint = check.schema_fingerprint()
        assert fingerprint is None or {
            "source",
            "sha256",
        } <= set(fingerprint)

    def test_a_damaged_cache_is_discarded(self, tmp_path, monkeypatch):
        broken = tmp_path / "avefi_schema.json"
        broken.write_text('{"incomplete', encoding="utf-8")
        monkeypatch.setattr(check, "SCHEMA_FILE", broken)
        monkeypatch.setattr(check, "CACHE_DIR", tmp_path)

        calls = []

        def fake_update(update_schema=False):
            calls.append(update_schema)
            return "validator"

        monkeypatch.setattr(check, "write_schema_cache", lambda schema: None)
        monkeypatch.setattr(
            check,
            "requests",
            type(
                "R",
                (),
                {
                    "get": staticmethod(
                        lambda *a, **kw: type(
                            "Response",
                            (),
                            {
                                "raise_for_status": lambda self: None,
                                "json": lambda self: {
                                    "$id": "x",
                                    "type": "object",
                                },
                            },
                        )()
                    )
                },
            ),
        )
        assert check.get_schema_validator() is not None
        assert calls == []


class TestPlaceholderIssuer:
    """A file naming no data provider must not reach registration.

    ``efi-conv from`` refuses to convert with the placeholder issuer
    unless it is told to, but a file produced that way, or produced by
    running a converter as ``python -m efi_conv.NAME``, still reaches
    ``check``. The documented pipeline is from, check, register
    identifiers, so ``check`` is the last step that can notice it.

    """

    def _with_issuer(self, issuer_id):
        work = copy.deepcopy(WORK)
        work["described_by"] = [
            {
                "has_issuer_id": issuer_id,
                "has_issuer_name": "Unspecified data provider",
                "has_source_key": ["k1"],
            }
        ]
        return records(work, MANIFESTATION, ITEM)

    def _placeholder(self):
        return self._with_issuer(profiles.PLACEHOLDER_ISSUER_ID)

    def test_a_named_issuer_passes(self, validator):
        named = self._with_issuer("https://w3id.org/isil/DE-MUS-000000")
        assert check.pass_checks(named, validator)

    def test_the_placeholder_issuer_does_not_pass(self, validator):
        assert not check.pass_checks(self._placeholder(), validator)

    def test_it_can_be_accepted_deliberately(self, validator):
        assert check.pass_checks(
            self._placeholder(), validator, accept_placeholder_issuer=True
        )

    def test_removing_invalid_records_does_not_empty_the_file(self, validator):
        """The issuer is not something a record can be dropped for."""
        placeholder = self._placeholder()
        check.pass_checks(placeholder, validator, remove_invalid=True)
        assert len(placeholder) == 3


class TestCheckCommandRejectsThePlaceholder:
    def _file(self, tmp_path, issuer_id):
        work = copy.deepcopy(WORK)
        work["described_by"] = [
            {
                "has_issuer_id": issuer_id,
                "has_issuer_name": "Unspecified data provider",
                "has_source_key": ["k1"],
            }
        ]
        target = tmp_path / "records.json"
        target.write_text(
            json.dumps([work, MANIFESTATION, ITEM]), encoding="utf-8"
        )
        return target

    def test_the_command_exits_non_zero(self, tmp_path):
        runner = CliRunner()
        target = self._file(tmp_path, profiles.PLACEHOLDER_ISSUER_ID)
        result = runner.invoke(cli_main, ["check", str(target)])
        assert result.exit_code != 0
        assert "placeholder" in result.output.lower()

    def test_the_flag_accepts_it(self, tmp_path):
        runner = CliRunner()
        target = self._file(tmp_path, profiles.PLACEHOLDER_ISSUER_ID)
        result = runner.invoke(
            cli_main,
            ["check", "--accept-placeholder-issuer", str(target)],
        )
        assert result.exit_code == 0, result.output

    def test_removing_invalid_records_does_not_hide_it(self, tmp_path):
        """--remove-invalid must not answer this by emptying the file."""
        runner = CliRunner()
        target = self._file(tmp_path, profiles.PLACEHOLDER_ISSUER_ID)
        before = target.read_text(encoding="utf-8")
        result = runner.invoke(
            cli_main, ["check", "--remove-invalid", str(target)]
        )
        assert result.exit_code != 0
        assert target.read_text(encoding="utf-8") == before
