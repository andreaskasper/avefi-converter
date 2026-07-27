from collections.abc import Callable
import json
from pathlib import Path

import pytest

from efi_conv.core import check

#: Snapshot of the AVefi JSON schema, so that the test suite does not
#: need network access on a cold run. Refresh with
#: `efi-conv check --update-schema` followed by copying the cache file.
SCHEMA_FIXTURE = Path(__file__).parent / "avefi_schema.json"


@pytest.fixture(scope="module")
def input_path(request) -> Callable[[str], Path]:
    def get_path(filename):
        return request.path.parent / filename

    return get_path


@pytest.fixture(scope="module")
def expected_output(input_path):
    with input_path("efi_records.json").open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def offline_schema(monkeypatch):
    """Serve the AVefi schema from the fixture instead of the network."""
    monkeypatch.setattr(check, "SCHEMA_FILE", SCHEMA_FIXTURE)
    monkeypatch.setattr(
        check,
        "get_schema_validator",
        _cached_validator,
    )
    return SCHEMA_FIXTURE


def _cached_validator(update_schema=False):
    """Return a validator built from the fixture, built once."""
    global _VALIDATOR
    if _VALIDATOR is None:
        with SCHEMA_FIXTURE.open(encoding="utf-8") as f:
            schema = json.load(f)
        from jsonschema.validators import validator_for

        cls = validator_for(schema)
        cls.check_schema(schema)
        _VALIDATOR = cls(schema)
    return _VALIDATOR


_VALIDATOR = None
