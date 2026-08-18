"""Compare generated AVefi records against reference data.

The acceptance criteria for a conversion require that information
already present in AVefi is not lost without being documented, and that
deviations from the reference data are written down. Doing that by hand
does not scale and cannot be repeated, so this command produces the
comparison as an artefact.

"""

import json
import logging

import click

from . import avefi
from .cli import cli_main

log = logging.getLogger(__name__)

#: Fields that describe the record itself rather than the object.
IGNORED_FIELDS = frozenset({"category"})


@cli_main.command()
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    help="Write the comparison to FILE (stdout if not specified).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--ignore",
    multiple=True,
    metavar="FIELD",
    help="Ignore this top level field (repeatable).",
)
@click.argument("reference", type=click.Path(dir_okay=False, exists=True))
@click.argument("candidate", type=click.Path(dir_okay=False, exists=True))
def diff(reference, candidate, output, output_format, ignore):
    """Compare CANDIDATE against REFERENCE and report the deviations.

    Records are matched on a shared persistent identifier where both
    sides carry one and on a shared local identifier otherwise, so the
    order of the two files does not matter and two exports of one
    collection can be compared even though their local identifiers
    differ. Exits non-zero when anything present in REFERENCE is
    missing from CANDIDATE.

    """
    result = compare(
        avefi.load(reference),
        avefi.load(candidate),
        ignored=IGNORED_FIELDS | set(ignore),
    )
    if output_format == "json":
        text = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    else:
        text = render_markdown(result, reference, candidate)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        log.info(f"Wrote comparison to {output}")
    else:
        click.echo(text)
    if result["summary"]["missing"] or result["summary"]["removed_values"]:
        raise SystemExit(1)


#: Identifier category holding a registered persistent identifier.
PERSISTENT_CATEGORY = "avefi:AVefiResource"


class Entry:
    """One record, with the identifiers it can be recognised by."""

    __slots__ = ("dump", "persistent", "local", "label")

    def __init__(self, record):
        self.dump = record.model_dump(exclude_none=True)
        self.persistent = {
            identifier.id
            for identifier in record.has_identifier or []
            if identifier.category == PERSISTENT_CATEGORY
        }
        self.local = {
            identifier.id
            for identifier in record.has_identifier or []
            if identifier.category != PERSISTENT_CATEGORY
        }
        self.label = next(
            iter(sorted(self.persistent) or sorted(self.local)), "—"
        )


def match_records(reference_records, candidate_records):
    """Pair the records of two files, and say what is left over.

    A record is matched as a whole rather than once per identifier it
    carries, and a shared persistent identifier settles it before a
    shared local one does.

    That order is what makes a comparison across two exports of one
    collection possible at all. Local identifiers are derived from the
    data, so two converters reading the same holdings out of different
    source formats produce different ones: of 2218 works held in both
    the CSV and the LIDO delivery of one museum, not a single local
    identifier agreed and 2217 registered identifiers did. Matching on
    the local one reported every record as both missing and added.

    Returns
    -------
    tuple
        Pairs of matched entries, then the unmatched reference and
        candidate entries.

    """
    reference = [Entry(record) for record in reference_records]
    candidate = [Entry(record) for record in candidate_records]
    pairs = []
    for attribute in ("persistent", "local"):
        index = {}
        for entry in candidate:
            for identifier in getattr(entry, attribute):
                index.setdefault(identifier, []).append(entry)
        taken = set()
        remaining = []
        for entry in reference:
            partner = next(
                (
                    other
                    for identifier in sorted(getattr(entry, attribute))
                    for other in index.get(identifier, [])
                    if id(other) not in taken
                ),
                None,
            )
            if partner is None:
                remaining.append(entry)
                continue
            taken.add(id(partner))
            pairs.append((entry, partner))
        reference = remaining
        candidate = [entry for entry in candidate if id(entry) not in taken]
    return pairs, reference, candidate


def compare(reference_records, candidate_records, ignored=IGNORED_FIELDS):
    """Return a structured comparison of two sets of records."""
    pairs, unmatched_reference, unmatched_candidate = match_records(
        reference_records, candidate_records
    )
    changed = []
    removed_values = 0
    for reference_entry, candidate_entry in pairs:
        differences = [
            difference
            for difference in diff_values(
                reference_entry.dump, candidate_entry.dump
            )
            if difference["field"].split(".")[0] not in ignored
        ]
        if differences:
            changed.append(
                {"id": reference_entry.label, "differences": differences}
            )
            removed_values += sum(
                1 for d in differences if d["kind"] == "removed"
            )
    changed.sort(key=lambda entry: entry["id"])
    missing = sorted(entry.label for entry in unmatched_reference)
    added = sorted(entry.label for entry in unmatched_candidate)
    return {
        "summary": {
            "reference_records": len(reference_records),
            "candidate_records": len(candidate_records),
            "matched": len(pairs),
            "missing": len(missing),
            "added": len(added),
            "changed": len(changed),
            "removed_values": removed_values,
        },
        "missing": missing,
        "added": added,
        "changed": changed,
    }


def diff_values(reference, candidate, path=""):
    """Yield the differences between two nested structures."""
    if isinstance(reference, dict) and isinstance(candidate, dict):
        for key in sorted(set(reference) | set(candidate)):
            field = f"{path}.{key}" if path else key
            if key not in candidate:
                yield {
                    "field": field,
                    "kind": "removed",
                    "reference": reference[key],
                    "candidate": None,
                }
            elif key not in reference:
                yield {
                    "field": field,
                    "kind": "added",
                    "reference": None,
                    "candidate": candidate[key],
                }
            else:
                yield from diff_values(reference[key], candidate[key], field)
        return
    if isinstance(reference, list) and isinstance(candidate, list):
        reference_only = [x for x in reference if x not in candidate]
        candidate_only = [x for x in candidate if x not in reference]
        # Pair up entries that describe the same thing so that a single
        # changed attribute is not reported as a whole object being
        # replaced.
        paired = pair_by_key(reference_only, candidate_only)
        for index, (left, right) in enumerate(paired):
            reference_only.remove(left)
            candidate_only.remove(right)
            yield from diff_values(left, right, f"{path}[{index}]")
        for value in reference_only:
            yield {
                "field": path,
                "kind": "removed",
                "reference": value,
                "candidate": None,
            }
        for value in candidate_only:
            yield {
                "field": path,
                "kind": "added",
                "reference": None,
                "candidate": value,
            }
        return
    if reference != candidate:
        yield {
            "field": path,
            "kind": "changed",
            "reference": reference,
            "candidate": candidate,
        }


#: Keys used to recognise two list entries as describing the same thing.
PAIRING_KEYS = ("id", "has_name", "type", "category")


def pairing_key(value):
    """Return a key identifying ``value`` among its siblings."""
    if not isinstance(value, dict):
        return None
    for key in PAIRING_KEYS:
        if key in value and isinstance(value[key], (str, int)):
            return (key, value[key])
    return None


def pair_by_key(reference_only, candidate_only):
    """Return pairs of entries that describe the same thing."""
    candidates = {}
    for value in candidate_only:
        key = pairing_key(value)
        if key is not None:
            candidates.setdefault(key, []).append(value)
    pairs = []
    for left in reference_only:
        key = pairing_key(left)
        if key is None:
            continue
        matches = candidates.get(key)
        if matches:
            pairs.append((left, matches.pop(0)))
    return pairs


def render_markdown(result, reference_name, candidate_name) -> str:
    """Return the comparison as a Markdown report."""
    summary = result["summary"]
    lines = [
        "# AVefi record comparison",
        "",
        f"* Reference: `{reference_name}`"
        f" ({summary['reference_records']} records)",
        f"* Candidate: `{candidate_name}`"
        f" ({summary['candidate_records']} records)",
        "",
        "| Outcome | Count |",
        "| --- | ---: |",
        f"| Matched | {summary['matched']} |",
        f"| Missing from candidate | {summary['missing']} |",
        f"| Only in candidate | {summary['added']} |",
        f"| Changed | {summary['changed']} |",
        f"| Values lost | {summary['removed_values']} |",
        "",
    ]
    if result["missing"]:
        lines += ["## Missing from candidate", ""]
        lines += [f"* `{identifier}`" for identifier in result["missing"]]
        lines.append("")
    if result["added"]:
        lines += ["## Only in candidate", ""]
        lines += [f"* `{identifier}`" for identifier in result["added"]]
        lines.append("")
    if result["changed"]:
        lines += ["## Changed records", ""]
        for entry in result["changed"]:
            lines += [f"### `{entry['id']}`", ""]
            lines += [
                "| Field | Change | Reference | Candidate |",
                "| --- | --- | --- | --- |",
            ]
            for difference in entry["differences"]:
                lines.append(
                    f"| `{difference['field']}` | {difference['kind']} |"
                    f" {render_value(difference['reference'])} |"
                    f" {render_value(difference['candidate'])} |"
                )
            lines.append("")
    if not (result["missing"] or result["added"] or result["changed"]):
        lines += ["No deviations found.", ""]
    return "\n".join(lines)


def render_value(value) -> str:
    """Return a compact single line rendering for a table cell."""
    if value is None:
        return "—"
    text = json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("|", "\\|")
    if len(text) > 80:
        text = f"{text[:77]}..."
    return f"`{text}`"
