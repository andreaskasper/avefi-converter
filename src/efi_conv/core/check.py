from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
import pathlib
import re
import sys
import tempfile

import appdirs
from avefi_schema import model_pydantic_v2 as efi
import click
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for
import requests

from . import avefi
from .cli import cli_main
from .settings import settings

log = logging.getLogger(__name__)
SCHEMA_SOURCE = "https://raw.githubusercontent.com/AV-EFI/av-efi-schema/main/project/jsonschema/avefi_schema/model.schema.json"
CACHE_DIR = pathlib.Path(
    appdirs.user_cache_dir(appname=__name__.split(".")[0])
)
SCHEMA_FILE = CACHE_DIR / "avefi_schema.json"
SCHEMA_TIMEOUT = 30
ENCODING = "utf-8"


@cli_main.command()
@click.option(
    "--preserve-status-removed",
    is_flag=True,
    default=False,
    help="Preserve items with access status Removed even without a PID yet.",
)
@click.option(
    "--remove-invalid/--no-remove-invalid",
    "-r",
    default=False,
    help="Remove invalid records modifying EFI_FILE in place.",
)
@click.option(
    "--update-schema",
    "-u",
    is_flag=True,
    default=False,
    help="Fetch latest version of the AVefi schema from upstream repo.",
)
@click.argument(
    "efi_files", nargs=-1, type=click.Path(dir_okay=False, exists=True)
)
def check(
    efi_files,
    *,
    preserve_status_removed=False,
    remove_invalid=False,
    update_schema=False,
):
    """Sanity check EFI_FILES and optionally remove invalid records."""
    schema_validator = get_schema_validator(update_schema=update_schema)
    for efi_file in efi_files:
        log.info(f"Processing {efi_file}")
        efi_records = avefi.load(efi_file)
        old_count = len(efi_records)
        if not pass_checks(
            efi_records,
            schema_validator,
            remove_invalid=remove_invalid,
            preserve_status_removed=preserve_status_removed,
        ):
            if remove_invalid:
                avefi.dump(efi_records, efi_file)
                log.info(
                    f"Successfully removed {old_count - len(efi_records)}"
                    f" invalid records"
                )
            else:
                log.error(
                    f"Found {old_count - len(efi_records)} invalid records"
                    f" (no action taken)"
                )
                sys.exit(1)
        else:
            log.info(f"All {old_count} records passed the checks successfully")


def get_schema_validator(update_schema=False):
    """Load AVefi JSON schema and initialise validator."""
    if update_schema:
        r = requests.get(SCHEMA_SOURCE, timeout=SCHEMA_TIMEOUT)
        r.raise_for_status()
        schema = r.json()
        CACHE_DIR.mkdir(exist_ok=True, parents=True)
        write_schema_cache(schema)
    else:
        try:
            if (
                datetime.now()
                - datetime.fromtimestamp(SCHEMA_FILE.stat().st_mtime)
            ).days > 30:
                log.warning(
                    f"{SCHEMA_FILE} has not been updated in 30 days, please"
                    f" consider using the --update-schema option"
                )
            with SCHEMA_FILE.open(encoding=ENCODING) as f:
                schema = json.load(f)
        except FileNotFoundError:
            return get_schema_validator(update_schema=True)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            log.warning(f"Discarding unusable schema cache {SCHEMA_FILE}: {e}")
            return get_schema_validator(update_schema=True)

    cls = validator_for(schema)
    cls.check_schema(schema)
    validator = cls(schema)
    return validator


def schema_fingerprint() -> dict | None:
    """Return an identification of the AVefi schema currently in use.

    The schema is fetched from a branch rather than from a release, so
    the only reliable identification is a hash of the cached document.
    Recording it makes a conversion reproducible after the fact.

    """
    try:
        raw = SCHEMA_FILE.read_bytes()
    except OSError:
        return None
    try:
        schema = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return {
        "source": SCHEMA_SOURCE,
        "id": schema.get("$id"),
        "version": schema.get("version"),
        "metamodel_version": schema.get("metamodel_version"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "cached_at": datetime.fromtimestamp(
            SCHEMA_FILE.stat().st_mtime, tz=UTC
        ).isoformat(timespec="seconds"),
    }


def write_schema_cache(schema):
    """Write the schema cache atomically.

    A truncated cache file is what makes a later run fail, so the new
    content is written to a temporary file next to the target and moved
    into place only once it is complete.

    """
    fd, tmp_name = tempfile.mkstemp(
        dir=CACHE_DIR, prefix=".avefi_schema.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=ENCODING) as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, SCHEMA_FILE)
    except BaseException:
        pathlib.Path(tmp_name).unlink(missing_ok=True)
        raise


def discard_record(
    record_list: list[efi.MovingImageRecord],
    record: efi.MovingImageRecord,
):
    """Remove ``record`` from ``record_list`` by identity.

    ``list.remove`` compares by equality, and pydantic models compare
    field by field. Two structurally identical records would therefore
    make the wrong object disappear.

    """
    for index, candidate in enumerate(record_list):
        if candidate is record:
            del record_list[index]
            return


class HashableId:
    def __init__(self, identifier: efi.MovingImageResource):
        self.identifier = identifier
        self.name = f"{self.identifier.category}.{self.identifier.id}"

    def __eq__(self, other) -> bool:
        """Check equality to another object."""
        return other.identifier == self.identifier

    def __hash__(self):
        """Return hash of the name attribute."""
        return hash(self.name)

    def __str__(self):
        """Return name attribute."""
        return self.name


def pass_checks(
    efi_records: list[efi.MovingImageRecord],
    schema_validator,
    remove_invalid=False,
    preserve_status_removed=False,
) -> bool:
    """Check records against schema and additional rules.

    Validate against AVefi schema and check various additional rules
    like field length limits, required identifiers, resolvable
    references, etc.

    Note that this function may have obvious side effects on
    ``efi_records`` if ``remove_invalid`` is set to True.

    Parameters
    ----------
    efi_records : List[efi.MovingImageRecord]
        List of records in the AVefi schema.
    schema_validator
        Validator instance as returned by get_schema_validator().
    remove_invalid : bool
        Remove records from the list if they violate any of the rules.
    preserve_status_removed : bool
        Accept items with access status Removed even when they do not
        carry an AVefi PID yet.

    Returns
    -------
    bool
        True if all checks have passed successfully, False otherwise.

    """
    id_lookup = {}
    dependants_by_ref = defaultdict(list)
    all_was_fine = True
    removed_refs = []

    # Check records and track dependencies
    for rec in efi_records.copy():
        error = best_match(schema_validator.iter_errors(rec.model_dump()))
        if error is not None:
            raise error

        if not rec.has_identifier:
            raise ValueError(f"has_identifier is missing in record: {rec}")
        try:
            if has_invalid_value(
                rec, preserve_status_removed=preserve_status_removed
            ):
                if all_was_fine:
                    all_was_fine = False
                if remove_invalid:
                    removed_refs.extend(
                        [HashableId(id_) for id_ in rec.has_identifier]
                    )
                    discard_record(efi_records, rec)
                    continue
        except Exception as e:
            raise RuntimeError(
                f"Error while checking record {rec.has_identifier[0].id}",
            ) from e

        record_ids = []
        for identifier in rec.has_identifier:
            record_id = HashableId(identifier)
            if record_id in id_lookup:
                if all_was_fine:
                    all_was_fine = False
                err_msg = f"Identifier is not unique: {record_id}"
                if remove_invalid:
                    log.error(err_msg)
                    removed_refs.extend(
                        [HashableId(id_) for id_ in rec.has_identifier]
                    )
                    discard_record(efi_records, rec)
                else:
                    raise ValueError(err_msg)
                for record_id in record_ids:
                    del id_lookup[record_id]
                record_ids = []
                break
            record_ids.append(record_id)
            id_lookup[record_id] = (rec, record_ids)
        if not record_ids:
            continue
        if isinstance(rec, efi.WorkVariant):
            link_attributes = ("is_part_of", "is_variant_of")
        elif isinstance(rec, efi.Manifestation):
            # Ignore has_item here
            link_attributes = ("is_manifestation_of", "same_as")
        elif isinstance(rec, efi.Item):
            link_attributes = ("is_item_of", "is_copy_of", "is_derivative_of")
        else:
            raise ValueError(f"Cannot handle {type(rec)} (record={rec})")
        for attr_name in link_attributes:
            attr = getattr(rec, attr_name)
            if attr is None:
                attr = []
            elif not isinstance(attr, list):
                attr = [attr]
            for identifier in attr:
                ref = HashableId(identifier)
                dependants_by_ref[ref].append(record_id)

    # Check for references (to parent records) that cannot be resolved
    for ref in list(dependants_by_ref.keys()):
        if (
            ref not in id_lookup
            and ref.identifier.category == "avefi:LocalResource"
        ):
            if all_was_fine:
                all_was_fine = False
            if remove_invalid:
                purge_dependant_records(
                    ref,
                    efi_records,
                    id_lookup,
                    dependants_by_ref,
                    removed_refs,
                )
            if ref not in removed_refs:
                log.error(f"Unresolvable reference: {ref.identifier.id}")

    # Check for records that should be associated with items but are not
    for rec in efi_records.copy():
        if (
            dangling_record(
                rec,
                efi_records,
                id_lookup,
                dependants_by_ref,
                removed_refs,
                remove_dangling=remove_invalid,
            )
            and all_was_fine
        ):
            all_was_fine = False
    return all_was_fine


def purge_dependant_records(
    ref: HashableId,
    record_list: list[efi.MovingImageRecord],
    id_lookup: dict[
        HashableId, tuple[efi.MovingImageRecord, list[HashableId]]
    ],
    dependants_by_ref: dict[HashableId, list[HashableId]],
    removed_refs: list[HashableId],
    visited: set[HashableId] | None = None,
):
    """Remove all records identified by or dependant on ``ref``.

    Check whether ``ref`` has an associated record in ``id_lookup``,
    remove it from ``record_list`` and all its identifiers from
    ``id_lookup``. Recursively apply this function to all dependants
    of ``ref`` and all known identifiers of the same record.

    Records may reference each other in a cycle. ``visited`` keeps
    track of the identifiers already handled during one descent so that
    such a cycle terminates instead of exhausting the stack.

    """
    if visited is None:
        visited = set()
    if ref in visited:
        return
    visited.add(ref)
    try:
        rec, ids = id_lookup[ref]
    except KeyError:
        ids = [ref]
    else:
        discard_record(record_list, rec)
        for record_id in ids:
            del id_lookup[record_id]
            removed_refs.append(record_id)
            log.debug(
                f"Reference to removed record: {record_id.identifier.id}"
            )

    for record_id in ids:
        visited.add(record_id)
        for dep_ref in dependants_by_ref[record_id]:
            purge_dependant_records(
                dep_ref,
                record_list,
                id_lookup,
                dependants_by_ref,
                removed_refs,
                visited,
            )
        del dependants_by_ref[record_id]


def dangling_record(
    rec: efi.MovingImageRecord,
    record_list: list[efi.MovingImageRecord],
    id_lookup: dict[HashableId, efi.MovingImageRecord],
    dependants_by_ref: dict[HashableId, list[HashableId]],
    removed_refs: list[HashableId],
    remove_dangling=False,
):
    """Return True if record has neither items nor a PID yet.

    Return False for items and records with a PID. Additionally,
    return False for records that are referenced by some child record.
    Otherwise, return True, except for works of type analytic provided
    that they are linked to a parent with at least one child that is
    not a work.

    Optionally, purge dangling records depending on the
    ``remove_dangling`` keyword argument.

    Raises
    ------
    ValueError
        When a manifestation is linked to a work of type analytic.

    """
    if rec.category == "avefi:Item":
        return False

    ids = [HashableId(id_) for id_ in rec.has_identifier]
    if all(
        id_.identifier.category == "avefi:LocalResource"
        and id_ not in dependants_by_ref
        for id_ in ids
    ):
        is_dangling = False
        if rec.category == "avefi:WorkVariant" and rec.type == "Analytic":
            # No manifestation should link to an analytic work.
            if any(
                id_ in dependants_by_ref
                and id_lookup[id_][0].category == "avefi:Manifestation"
                for id_ in ids
            ):
                raise ValueError(
                    f"Analytic work unexpectedly referenced by"
                    f" manifestation(s): {ids[0].identifier.id}"
                )

            # Analytic works should always be part of another work.
            if not rec.is_part_of:
                log.error(
                    f"Analytic work without is_part_of: "
                    f"{rec.has_identifier[0].id}",
                )
                is_dangling = True
            else:
                # We need to make sure that parents of analytic works
                # actually have other dependants than the analytic
                # works themselves, i.e. a manifestation or
                # supplemental material.
                for identifier in rec.is_part_of:
                    if identifier.category != "avefi:LocalResource":
                        continue
                    ref = HashableId(identifier)
                    try:
                        parent, p_ids = id_lookup[ref]
                    except KeyError:
                        log.error(
                            f"Analytic work is part of an unresolvable"
                            f" record: {rec.has_identifier[0].id}"
                        )
                        is_dangling = True
                        continue
                    # TODO: Uncomment if approved by Metadaten-experts
                    # if parent.type != "Monographic":
                    #     log.error(
                    #         f"Analytic work {record_id} is part of work with"
                    #         f" type other than monographic: {ref}"
                    #     )
                    #     is_dangling = True
                    ref_deps = set()
                    for id_ in p_ids:
                        ref_deps.update(dependants_by_ref[id_])
                    if not ref_deps or all(
                        id_lookup[ref_dep][0].category == "avefi:WorkVariant"
                        for ref_dep in ref_deps
                    ):
                        log.error(
                            f"Analytic work is part of work without items: "
                            f"{rec.has_identifier[0].id}",
                        )
                        is_dangling = True
        else:
            log.error(
                f"No items associated with {rec.category}"
                f" {rec.has_identifier[0].id}"
            )
            is_dangling = True
        if is_dangling and remove_dangling:
            refs = []
            for attr_name in (
                "is_manifestation_of",
                "is_variant_of",
                "is_part_of",
            ):
                ref = getattr(rec, attr_name, None)
                if ref:
                    if isinstance(ref, list):
                        refs.extend(HashableId(r) for r in ref)
                    else:
                        refs.append(HashableId(ref))
            purge_dependant_records(
                ids[0],
                record_list,
                id_lookup,
                dependants_by_ref,
                removed_refs,
            )
            for ref in refs:
                ref_deps = dependants_by_ref[ref]
                for id_ in ids:
                    if id_ in ref_deps:
                        ref_deps.remove(id_)
                if not ref_deps:
                    del dependants_by_ref[ref]
                    try:
                        parent, p_ids = id_lookup[ref]
                    except KeyError:
                        pass
                    else:
                        # Check whether parent is dangling now and
                        # remove, accordingly.
                        dangling_record(
                            parent,
                            record_list,
                            id_lookup,
                            dependants_by_ref,
                            removed_refs=removed_refs,
                            remove_dangling=True,
                        )
        return is_dangling
    return False


def has_invalid_value(efi_record, preserve_status_removed=False):
    def any_empty_has_name(elem_generator):
        if any([not elem.has_name for elem in elem_generator]):
            log.error(f"Empty has_name in {efi_record.has_identifier[0].id}")
            return True
        return False

    if exceeds_field_limit(efi_record):
        return True
    if has_invalid_date(efi_record):
        return True
    for event in efi_record.has_event:
        for activity in event.has_activity:
            if any_empty_has_name(activity.has_agent):
                return True
        if any_empty_has_name(event.located_in):
            return True
    if isinstance(efi_record, efi.WorkVariant):
        if any_empty_has_name(efi_record.has_genre):
            return True
        if any_empty_has_name(efi_record.has_subject):
            return True
        if (
            efi_record.has_primary_title
            and efi_record.has_primary_title.type
            not in (
                "PreferredTitle",
                "SuppliedDevisedTitle",
            )
        ):
            log.error(
                f"Primary title type for work records is supposed to be"
                f" one of ('PreferredTitle', 'SuppliedDevisedTitle'), found:"
                f" {efi_record.has_primary_title.type} in record"
                f" {efi_record.has_identifier[0].id}"
            )
            return True
    else:
        if (
            efi_record.has_primary_title
            and efi_record.has_primary_title.type
            not in (
                "TitleProper",
                "SuppliedDevisedTitle",
            )
        ):
            log.error(
                f"Primary title type for non-work records is supposed to be"
                f" one of ('TitleProper', 'SuppliedDevisedTitle'), found:"
                f" {efi_record.has_primary_title.type} in record"
                f" {efi_record.has_identifier[0].id}"
            )
            return True
        if (
            not preserve_status_removed
            and isinstance(efi_record, efi.Item)
            and efi_record.has_access_status == "Removed"
            and not any(
                ident.category == "avefi:AVefiResource"
                for ident in efi_record.has_identifier
            )
        ):
            log.error(
                f"Do not expect has_access_status=Removed for an item"
                f" without a PID: {efi_record.has_identifier[0].id}"
            )
            return True
    return False


def exceeds_field_limit(efi_record):
    titles = []
    if efi_record.has_primary_title:
        titles.append(efi_record.has_primary_title)
    titles.extend(efi_record.has_alternative_title)
    for title in titles:
        if len(title.has_name) > settings.line_limit:
            log.error(
                f"Record {efi_record.has_identifier[0].id} violates limit of"
                f" {settings.line_limit} characters on title length:"
                f" {title.has_name}"
            )
            return True
    if efi_record.category != "avefi:WorkVariant":
        for note in efi_record.has_note:
            if len(note) >= settings.text_limit:
                log.error(
                    f"Record {efi_record.has_identifier[0].id} violates limit"
                    f" of {settings.text_limit} characters on has_note"
                    f" entries"
                )
                return True
    return False


def has_invalid_date(efi_record):
    for event in efi_record.has_event:
        if event.has_date and not re.search(
            r"^-?([1-9][0-9]{3,}|0[0-9]{3})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?(/-?([1-9][0-9]{3,}|0[0-9]{3})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01]))?)?[?~]?)?$",
            event.has_date,
        ):
            log.error(
                f"Record {efi_record.has_identifier[0].id} has event(s) with"
                f" invalid value in has_date: {event.has_date}"
            )
            return True

        # Check if this is a period expression (contains '/')
        if event.has_date and "/" in event.has_date:
            # Split period and clean each part (keep only digits and hyphens)
            period_parts = event.has_date.split("/")
            if len(period_parts) == 2:
                # Remove all characters except digits and hyphens
                clean_start = re.sub(r"[^0-9-]", "", period_parts[0])
                clean_end = re.sub(r"[^0-9-]", "", period_parts[1])

                # Perform lexicographical comparison
                # Equality is valid, only invalid when start > end
                if clean_start > clean_end:
                    log.error(
                        f"Record {efi_record.has_identifier[0].id} has"
                        f" event with invalid period: {event.has_date}"
                        f" (start {clean_start} must be less than or equal to"
                        f" end {clean_end})"
                    )
                    return True
    return False
