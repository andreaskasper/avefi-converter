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


#: One LIDO record describing a copy of a film, with the vocabulary
#: the Filmmuseum Düsseldorf profile knows. Small enough to read in a
#: test, complete enough to convert.
LIDO_RECORD = """\
  <lido:lido>
    <lido:lidoRecID lido:type="local">{record_id}</lido:lidoRecID>
{published}\
    <lido:descriptiveMetadata xml:lang="de">
      <lido:objectClassificationWrap>
        <lido:objectWorkTypeWrap>
          <lido:objectWorkType>
            <lido:term xml:lang="de">{work_type}</lido:term>
          </lido:objectWorkType>
        </lido:objectWorkTypeWrap>
        <lido:classificationWrap>
          <lido:classification lido:type="colour">
            <lido:term xml:lang="de">{colour}</lido:term>
          </lido:classification>
{genre}\
{keywords}\
        </lido:classificationWrap>
      </lido:objectClassificationWrap>
      <lido:objectIdentificationWrap>
        <lido:titleWrap>
          <lido:titleSet lido:type="preferred">
            <lido:appellationValue xml:lang="de" lido:pref="preferred"
              >{title}</lido:appellationValue>
          </lido:titleSet>
        </lido:titleWrap>
        <lido:objectMeasurementsWrap>
          <lido:objectMeasurementsSet>
            <lido:objectMeasurements>
              <lido:measurementsSet>
                <lido:measurementType
                  xml:lang="de">{measurement}</lido:measurementType>
                <lido:measurementValue>{duration}</lido:measurementValue>
              </lido:measurementsSet>
            </lido:objectMeasurements>
          </lido:objectMeasurementsSet>
        </lido:objectMeasurementsWrap>
      </lido:objectIdentificationWrap>
      <lido:eventWrap>
        <lido:eventSet>
          <lido:event>
            <lido:eventType>
              <lido:term xml:lang="de">Produktion</lido:term>
            </lido:eventType>
{actor}\
            <lido:eventDate>
              <lido:displayDate>{date}</lido:displayDate>
            </lido:eventDate>
{places}\
{materials}\
          </lido:event>
        </lido:eventSet>
      </lido:eventWrap>
    </lido:descriptiveMetadata>
    <lido:administrativeMetadata xml:lang="de">
      <lido:recordWrap>
        <lido:recordID lido:type="local">{record_id}</lido:recordID>
        <lido:recordType>
          <lido:term xml:lang="de">{record_type}</lido:term>
        </lido:recordType>
      </lido:recordWrap>
    </lido:administrativeMetadata>
  </lido:lido>
"""

LIDO_PUBLISHED_ID = """\
    <lido:objectPublishedID lido:type="http://terminology.lido-schema.org/lido00099"
      lido:source="www.av-efi.net">{handle}</lido:objectPublishedID>
"""

LIDO_PLACE = """\
            <lido:eventPlace lido:type="Produktionsland">
              <lido:place>
{place_id}\
                <lido:namePlaceSet>
                  <lido:appellationValue>{name}</lido:appellationValue>
                </lido:namePlaceSet>
              </lido:place>
            </lido:eventPlace>
"""

LIDO_PLACE_ID = """\
                <lido:placeID lido:type="http://terminology.lido-schema.org/lido00100"
                  lido:source="TGN">{tgn}</lido:placeID>
"""

LIDO_GENRE = """\
          <lido:classification lido:type="genre">
            <lido:term xml:lang="de">{genre}</lido:term>
          </lido:classification>
"""

#: A classification collecting language, access status and working
#: notes under one heading, as this provider keeps them.
LIDO_KEYWORDS = """\
          <lido:classification lido:type="Schlagwort">
{terms}\
          </lido:classification>
"""

LIDO_ACTOR = """\
            <lido:eventActor>
              <lido:actorInRole>
                <lido:actor{actor_type}>
{authority}\
                  <lido:nameActorSet>
                    <lido:appellationValue>{director}</lido:appellationValue>
                  </lido:nameActorSet>
                </lido:actor>
                <lido:roleActor>
                  <lido:term xml:lang="de">{role}</lido:term>
                </lido:roleActor>
              </lido:actorInRole>
            </lido:eventActor>
"""

#: The technical description of a copy, where this provider records
#: colour, format, element type and sound.
LIDO_MATERIALS_TECH = """\
            <lido:eventMaterialsTech>
              <lido:materialsTech>
{terms}\
              </lido:materialsTech>
            </lido:eventMaterialsTech>
"""

LIDO_MATERIALS_TERM = """\
                <lido:termMaterialsTech lido:type="http://terminology.lido-schema.org/lido00131">
{concept}\
                  <lido:term>{term}</lido:term>
                </lido:termMaterialsTech>
"""

LIDO_MATERIALS_CONCEPT = """\
                  <lido:conceptID lido:type="http://terminology.lido-schema.org/lido00099"
                    lido:source="www.av-efi.net">https://www.av-efi.net/av-efi-schema/{concept}</lido:conceptID>
"""

LIDO_ACTOR_ID = """\
                  <lido:actorID lido:type="http://terminology.lido-schema.org/lido00099"
                    lido:source="{source}">{value}</lido:actorID>
"""

#: An event that records the people rather than the making of a copy.
#: Providers that model it this way put director, composer and writer
#: here, which is where they were previously not looked for.
LIDO_CREATION_EVENT = """\
        <lido:eventSet>
          <lido:event>
            <lido:eventType>
              <lido:term xml:lang="de">Geistige Schöpfung</lido:term>
            </lido:eventType>
{actors}\
          </lido:event>
        </lido:eventSet>
"""

LIDO_DOCUMENT = """\
<?xml version="1.0" encoding="UTF-8"?>
{doctype}<lido:lidoWrap xmlns:lido="http://www.lido-schema.org">
{records}</lido:lidoWrap>
"""


def make_lido_record(
    record_id,
    title="Die Brücke",
    director="Wicki, Bernhard",
    date="1959",
    colour="sw",
    duration="103",
    genre="",
    work_type="Filmrolle",
    handle="",
    role="Regie",
    actor_type="",
    gnd="",
    gnd_source="GND",
    materials=(),
    keywords=(),
    places=(),
    measurement="Laufzeit",
    record_type="Item",
):
    """Return the LIDO serialisation of one film holding."""
    return LIDO_RECORD.format(
        record_id=record_id,
        work_type=work_type,
        measurement=measurement,
        record_type=record_type,
        published=(LIDO_PUBLISHED_ID.format(handle=handle) if handle else ""),
        title=title,
        colour=colour,
        date=date,
        duration=duration,
        genre=LIDO_GENRE.format(genre=genre) if genre else "",
        places="".join(
            LIDO_PLACE.format(
                name=name,
                place_id=(LIDO_PLACE_ID.format(tgn=tgn) if tgn else ""),
            )
            for name, tgn in places
        ),
        keywords=(
            LIDO_KEYWORDS.format(
                terms="".join(
                    f'            <lido:term xml:lang="de">{term}'
                    f"</lido:term>\n"
                    for term in keywords
                )
            )
            if keywords
            else ""
        ),
        materials=(
            LIDO_MATERIALS_TECH.format(
                terms="".join(
                    LIDO_MATERIALS_TERM.format(
                        term=term,
                        concept=(
                            LIDO_MATERIALS_CONCEPT.format(concept=concept)
                            if concept
                            else ""
                        ),
                    )
                    for term, concept in materials
                )
            )
            if materials
            else ""
        ),
        actor=(
            LIDO_ACTOR.format(
                director=director,
                role=role,
                actor_type=(
                    f' lido:type="{actor_type}"' if actor_type else ""
                ),
                authority=(
                    LIDO_ACTOR_ID.format(source=gnd_source, value=gnd)
                    if gnd
                    else ""
                ),
            )
            if director
            else ""
        ),
    )


@pytest.fixture
def lido_record():
    """Return a factory for one LIDO record describing a film copy."""
    return make_lido_record


@pytest.fixture
def lido_page(tmp_path):
    """Return a factory writing LIDO records to a document."""

    def write(name, *records, doctype=""):
        target = tmp_path / name
        target.write_text(
            LIDO_DOCUMENT.format(doctype=doctype, records="".join(records)),
            encoding="utf-8",
        )
        return target

    return write
