"""Fetch records from an OAI-PMH or SRU endpoint.

Most institutions that can deliver metadata at all already serve it
over one of these two protocols, so the usual first step of a
conversion — asking somebody to produce an export and send it — can be
skipped. What is harvested here is the payload as the provider
publishes it: LIDO, EN 15907, MARC21-XML, Dublin Core. Nothing is
converted. The files this writes are the input to ``efi-conv from``,
and every reader in this package locates its records by element name
inside whatever wraps them, so the harvest wrapper is invisible to
them.

Harvesting is deliberately a separate step rather than an option on
the conversion. A harvest is slow, it is rude to repeat against
somebody else's server while a mapping is being developed, and the
result is worth keeping: it is the evidence of what the provider
actually sent on the day the records were made. That is also why the
OAI record header is written next to the payload and why each page
names the request that produced it: without the datestamps and the
request, the pages say what was received but not when or in answer to
what, and an incremental harvest cannot be resumed from them.

Being a guest on somebody else's server is taken seriously here. The
requests identify the tool and, if the operator supplies one, a
contact address; there is a pause between them; and a server that asks
for a delay is obeyed up to a limit rather than indefinitely.

"""

from dataclasses import dataclass, field
import logging
import pathlib
import time
from urllib.parse import urlencode

import click
from lxml import etree
import requests

from .. import __version__
from .cli import cli_main

log = logging.getLogger(__name__)

OAI_NAMESPACE = "http://www.openarchives.org/OAI/2.0/"
#: SRU changed its namespace between the versions still in the field.
SRU_NAMESPACES = (
    "http://www.loc.gov/zing/srw/",
    "http://docs.oasis-open.org/ns/search-ws/sruResponse",
)
#: Namespace of the elements wrapping a harvested page.
HARVEST_NAMESPACE = "https://av-efi.net/efi-conv/harvest"

#: Requests that fail with one of these are worth repeating.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 5
#: Servers vary in what they will hand over in one response.
DEFAULT_SRU_PAGE_SIZE = 50
#: Seconds to wait between two requests to the same endpoint. Nobody
#: harvesting somebody else's repository is in that much of a hurry.
DEFAULT_DELAY = 1.0
#: Longest a Retry-After is obeyed before the harvest gives up. A
#: server may ask for a day; waiting it out is not retrying, it is
#: hanging, and the operator can always come back tomorrow.
DEFAULT_MAX_RETRY_AFTER = 300
#: Empty SRU pages in a row tolerated before a harvest that has not
#: reached the reported total is called incomplete.
MAX_EMPTY_PAGES = 5
#: Named in the User-Agent, so that whoever runs the endpoint can find
#: out what has been asking and complain to the right people.
PROJECT_URL = "https://github.com/AV-EFI/efi-conv"
ENCODING = "utf-8"


class HarvestError(RuntimeError):
    """Raised when an endpoint cannot or will not deliver records."""


@dataclass
class HarvestResult:
    """What one harvest produced.

    Attributes
    ----------
    files : list
        The files written, in the order they were fetched.
    records : int
        Number of records written.
    deleted : int
        Records the endpoint reported as deleted. They carry no
        metadata and are not written, but they matter for an
        incremental harvest, so they are counted and reported.
    requests : int
        Number of requests sent, useful when a run has to be explained
        to whoever runs the server.

    """

    files: list = field(default_factory=list)
    records: int = 0
    deleted: int = 0
    requests: int = 0


def user_agent(contact=None) -> str:
    """Return the User-Agent this harvester introduces itself with.

    An OAI aggregator that sees ``python-requests`` with no way of
    finding out who is behind it blocks it, and is right to.

    Parameters
    ----------
    contact : str, optional
        Address of whoever runs the harvest, added so that the
        provider can get in touch instead of blocking.

    """
    agent = f"efi-conv/{__version__} (+{PROJECT_URL})"
    return f"{agent} ({contact})" if contact else agent


def pause(seconds, sleep=None):
    """Wait between two requests to the same endpoint."""
    if not seconds or seconds <= 0:
        return
    (time.sleep if sleep is None else sleep)(seconds)


def fetch(
    url,
    params,
    session=None,
    timeout=DEFAULT_TIMEOUT,
    retries=DEFAULT_RETRIES,
    backoff=DEFAULT_BACKOFF,
    max_retry_after=DEFAULT_MAX_RETRY_AFTER,
    contact=None,
    sleep=None,
):
    """Return the body of one request, repeating a failure worth repeating.

    An OAI-PMH server under load answers 503 with a Retry-After header
    rather than an error, and expects the harvester to wait and come
    back. Ignoring that is how a harvester gets blocked. Obeying it
    without a limit is how a harvest hangs for a day, so a server
    asking for longer than ``max_retry_after`` is left alone instead.

    """
    get = (session or requests).get
    headers = {"User-Agent": user_agent(contact)}
    sleep = time.sleep if sleep is None else sleep
    attempt = 0
    while True:
        attempt += 1
        try:
            response = get(
                url, params=params, timeout=timeout, headers=headers
            )
        except requests.RequestException as e:
            if attempt > retries:
                raise HarvestError(f"{url}: {e}") from e
            wait = backoff * attempt
            log.warning(f"{url}: {e}, retrying in {wait} s")
            sleep(wait)
            continue
        if response.status_code in RETRY_STATUS and attempt <= retries:
            wait = retry_after(response, backoff * attempt)
            if wait > max_retry_after:
                raise HarvestError(
                    f"{url} answered HTTP {response.status_code} and asked"
                    f" us to wait {wait:g} s, more than the"
                    f" {max_retry_after:g} s this harvest may wait. Come"
                    f" back when the server is ready, or allow the wait"
                    f" with --max-retry-after."
                )
            log.warning(
                f"{url}: HTTP {response.status_code}, retrying in {wait} s"
            )
            sleep(wait)
            continue
        if response.status_code != 200:
            raise HarvestError(f"{url} answered HTTP {response.status_code}")
        return response.content


def retry_after(response, default) -> float:
    """Return the number of seconds the server asked us to wait."""
    value = response.headers.get("Retry-After")
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        # The header may hold an HTTP date. Waiting the default is
        # better than parsing it wrongly and hammering the server.
        return default


def parse_response(body: bytes, url: str):
    """Return the root element of a response body."""
    try:
        return etree.fromstring(
            body,
            parser=etree.XMLParser(
                resolve_entities=False, load_dtd=False, no_network=True
            ),
        )
    except etree.XMLSyntaxError as e:
        raise HarvestError(f"{url} did not answer with XML: {e}") from e


def oai_error(root):
    """Return the OAI error an endpoint reported, if any."""
    for element in root.findall(f"{{{OAI_NAMESPACE}}}error"):
        code = element.get("code", "unknown")
        return f"{code}: {(element.text or '').strip()}"
    return None


def harvest_oai(
    url,
    metadata_prefix,
    output_directory,
    set_spec=None,
    from_date=None,
    until_date=None,
    limit=None,
    delay=DEFAULT_DELAY,
    contact=None,
    session=None,
    **fetch_options,
) -> HarvestResult:
    """Harvest an OAI-PMH endpoint with ListRecords.

    Parameters
    ----------
    url : str
        Base URL of the endpoint.
    metadata_prefix : str
        Metadata prefix to request, for instance ``lido``, ``marc21``
        or ``oai_dc``. Run ListMetadataFormats against the endpoint if
        you do not know what it offers.
    output_directory
        Directory the pages are written to. It is created if needed.
    set_spec : str, optional
        Restrict the harvest to one set.
    from_date, until_date : str, optional
        Selective harvesting, in the granularity the endpoint supports.
    limit : int, optional
        Write at most this many records and then stop. For trying an
        endpoint out without pulling the whole repository. ListRecords
        has no way of asking for fewer records than the server cares to
        send, so the page that reaches the limit is truncated.
    delay : float
        Seconds to wait between two requests.
    contact : str, optional
        Contact address for the User-Agent.

    """
    directory = prepare_directory(output_directory)
    result = HarvestResult()
    params = {"verb": "ListRecords", "metadataPrefix": metadata_prefix}
    if set_spec:
        params["set"] = set_spec
    if from_date:
        params["from"] = from_date
    if until_date:
        params["until"] = until_date
    seen_tokens = set()
    page = 0
    written = 0
    while True:
        page += 1
        if page > 1:
            pause(delay)
        request = describe(url, params)
        body = fetch(
            url, params, session=session, contact=contact, **fetch_options
        )
        result.requests += 1
        root = parse_response(body, url)
        error = oai_error(root)
        if error:
            if error.startswith("noRecordsMatch") and page == 1:
                log.warning(f"{url} has no records matching the request")
                return result
            raise HarvestError(f"{url} reported {error}")
        records, deleted = oai_payloads(root)
        result.deleted += deleted
        records = up_to_the_limit(records, result.records, limit)
        if records:
            written += 1
            result.files.append(
                write_page(directory, written, records, request)
            )
            result.records += len(records)
        log.info(
            f"Harvested page {page}: {len(records)} record(s),"
            f" {result.records} so far, from {request}"
        )
        token = resumption_token(root)
        if limit is not None and result.records >= limit:
            log.info(f"Stopping after {result.records} record(s) as asked")
            break
        if not token:
            break
        if token in seen_tokens:
            raise HarvestError(
                f"{url} returned a resumption token it had already"
                f" returned, which would harvest for ever"
            )
        seen_tokens.add(token)
        # A resumption token replaces every other argument.
        params = {"verb": "ListRecords", "resumptionToken": token}
    return result


def up_to_the_limit(records, harvested, limit):
    """Return no more records than the limit still leaves room for.

    A limit is there to fetch a handful of records for a look, so a
    page arriving with a thousand of them is truncated rather than
    written whole.

    """
    if limit is None:
        return records
    room = max(limit - harvested, 0)
    if len(records) <= room:
        return records
    log.info(
        f"Keeping {room} of the {len(records)} record(s) on this page,"
        f" which is what the limit of {limit} leaves room for"
    )
    return records[:room]


def oai_payloads(root):
    """Return the records of one OAI response.

    Returns
    -------
    tuple
        A list of (header, payload) pairs and the number of deleted
        records seen. The header is kept because it carries the
        identifier, the datestamp and the sets the record belongs to,
        none of which the payload has to repeat.

    """
    records = []
    deleted = 0
    list_records = root.find(f"{{{OAI_NAMESPACE}}}ListRecords")
    if list_records is None:
        return records, deleted
    for record in list_records.findall(f"{{{OAI_NAMESPACE}}}record"):
        header = record.find(f"{{{OAI_NAMESPACE}}}header")
        if header is not None and header.get("status") == "deleted":
            deleted += 1
            continue
        metadata = record.find(f"{{{OAI_NAMESPACE}}}metadata")
        if metadata is None or len(metadata) == 0:
            log.warning(
                f"Record {oai_identifier(header)} carries no metadata, skipped"
            )
            continue
        records.append((header, metadata[0]))
    return records, deleted


def oai_identifier(header) -> str:
    """Return the identifier in an OAI header, or a stand-in for it."""
    if header is None:
        return "without a header"
    element = header.find(f"{{{OAI_NAMESPACE}}}identifier")
    if element is None or not (element.text or "").strip():
        return "without an identifier"
    return element.text.strip()


def resumption_token(root) -> str | None:
    """Return the resumption token of an OAI response, if any."""
    list_records = root.find(f"{{{OAI_NAMESPACE}}}ListRecords")
    if list_records is None:
        return None
    element = list_records.find(f"{{{OAI_NAMESPACE}}}resumptionToken")
    if element is None or not (element.text or "").strip():
        return None
    return element.text.strip()


def harvest_sru(
    url,
    query,
    output_directory,
    record_schema=None,
    page_size=DEFAULT_SRU_PAGE_SIZE,
    version="1.2",
    limit=None,
    delay=DEFAULT_DELAY,
    contact=None,
    session=None,
    **fetch_options,
) -> HarvestResult:
    """Harvest an SRU endpoint with searchRetrieve.

    SRU is how library systems are queried, so this is the way to a
    catalogue's film holdings without asking anybody for an export.

    An empty page is not taken as the end of the data. SRU says how
    many records match, and a server that answers one page with
    nothing while later pages still hold records would otherwise
    truncate the harvest silently. Such a gap is logged, skipped and
    carried on from; only a run of :data:`MAX_EMPTY_PAGES` of them
    ends the harvest, and then as an error rather than as a success.

    Parameters
    ----------
    url : str
        Base URL of the endpoint.
    query : str
        CQL query, for instance ``pica.bkl=24.34``.
    record_schema : str, optional
        Schema to request, for instance ``marcxml``.
    page_size : int
        Records per request. Servers cap this, and the response says
        how many were actually returned.
    limit : int, optional
        Write at most this many records and then stop. No more than
        are still needed are requested.
    delay : float
        Seconds to wait between two requests.
    contact : str, optional
        Contact address for the User-Agent.

    """
    directory = prepare_directory(output_directory)
    result = HarvestResult()
    start = 1
    page = 0
    written = 0
    total = None
    empty_pages = 0
    while True:
        page += 1
        if page > 1:
            pause(delay)
        wanted = page_size
        if limit is not None:
            wanted = min(page_size, limit - result.records)
        params = {
            "version": version,
            "operation": "searchRetrieve",
            "query": query,
            "startRecord": start,
            "maximumRecords": wanted,
        }
        if record_schema:
            params["recordSchema"] = record_schema
        request = describe(url, params)
        body = fetch(
            url, params, session=session, contact=contact, **fetch_options
        )
        result.requests += 1
        root = parse_response(body, url)
        diagnostic = sru_diagnostic(root)
        if diagnostic:
            raise HarvestError(f"{url} reported {diagnostic}")
        if total is None:
            total = sru_number_of_records(root)
            log.info(f"{url} reports {total} matching record(s)")
        records = [(None, payload) for payload in sru_payloads(root)]
        records = up_to_the_limit(records, result.records, limit)
        if records:
            empty_pages = 0
            written += 1
            result.files.append(
                write_page(directory, written, records, request)
            )
            result.records += len(records)
        log.info(
            f"Harvested page {page}: {len(records)} record(s),"
            f" {result.records} so far, from {request}"
        )
        if limit is not None and result.records >= limit:
            log.info(f"Stopping after {result.records} record(s) as asked")
            break
        if total is not None and result.records >= total:
            break
        if not records:
            if total is None:
                log.info(
                    f"{url} returned an empty page and reports no total,"
                    f" so this is the end of the result set"
                )
                break
            empty_pages += 1
            if empty_pages > MAX_EMPTY_PAGES:
                raise HarvestError(
                    f"{url} returned {empty_pages} empty pages in a row"
                    f" while reporting {total} matching record(s), of"
                    f" which {result.records} were delivered. The pages"
                    f" written so far are usable, but the harvest is not"
                    f" complete."
                )
            log.warning(
                f"{url} returned no records for record {start} onwards"
                f" although it reports {total} matching record(s) and"
                f" only {result.records} have been delivered. Skipping"
                f" the gap and carrying on."
            )
            start += wanted
            continue
        start += len(records)
    return result


def sru_find(root, local_name):
    """Return the first element of that name, in either SRU namespace."""
    for namespace in SRU_NAMESPACES:
        found = root.find(f".//{{{namespace}}}{local_name}")
        if found is not None:
            return found
    return None


def sru_findall(root, local_name):
    """Return the elements of that name, in either SRU namespace."""
    for namespace in SRU_NAMESPACES:
        found = root.findall(f".//{{{namespace}}}{local_name}")
        if found:
            return found
    return []


def sru_number_of_records(root) -> int | None:
    """Return how many records the endpoint says match the query."""
    element = sru_find(root, "numberOfRecords")
    if element is None or not (element.text or "").strip():
        return None
    try:
        return int(element.text.strip())
    except ValueError:
        return None


def sru_diagnostic(root) -> str | None:
    """Return the diagnostic an SRU endpoint reported, if any."""
    for element in root.iter():
        tag = etree.QName(element).localname
        if tag != "diagnostic":
            continue
        parts = [
            (child.text or "").strip()
            for child in element
            if (child.text or "").strip()
        ]
        return "; ".join(parts) or "diagnostic without detail"
    return None


def sru_payloads(root):
    """Return the record payloads of one SRU response."""
    payloads = []
    for record_data in sru_findall(root, "recordData"):
        for child in record_data:
            payloads.append(child)
            break
    return payloads


def prepare_directory(output_directory) -> pathlib.Path:
    """Return the output directory, created if it does not exist."""
    directory = pathlib.Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_page(
    directory: pathlib.Path, page: int, records, source=None
) -> str:
    """Write one page of records and return the file name.

    Each page becomes one document. Every record goes into a wrapper
    of ours holding what the provider sent about it: the payload, and
    for OAI-PMH the record header with its identifier, datestamp and
    sets. The readers in this package find their records by element
    name whatever wraps them, so the wrapper costs nothing and keeps
    the payloads exactly as the provider sent them.

    Parameters
    ----------
    directory
        Directory to write into.
    page : int
        Number of the page, counted over the pages written rather than
        over the requests sent, so that the files on disk are numbered
        without gaps.
    records
        Pairs of a header, which may be None, and a payload element.
    source : str, optional
        The request that produced this page, recorded on the page so
        that it can be repeated or accounted for later.

    """
    root = etree.Element(
        f"{{{HARVEST_NAMESPACE}}}harvest", nsmap={"h": HARVEST_NAMESPACE}
    )
    if source:
        root.set("source", source)
    for header, payload in records:
        wrapper = etree.SubElement(root, f"{{{HARVEST_NAMESPACE}}}record")
        if header is not None:
            wrapper.append(header)
        wrapper.append(payload)
    target = directory / f"page-{page:05d}.xml"
    tree = etree.ElementTree(root)
    tree.write(
        str(target),
        encoding=ENCODING,
        xml_declaration=True,
        pretty_print=True,
    )
    return str(target)


def describe(url, params) -> str:
    """Return the request as a URL, for the log and for the page."""
    return f"{url}?{urlencode(params)}"


@cli_main.command("harvest")
@click.option(
    "-p",
    "--protocol",
    type=click.Choice(["oai", "sru"]),
    default="oai",
    show_default=True,
    help="Protocol the endpoint speaks.",
)
@click.option("-u", "--url", required=True, help="Base URL of the endpoint.")
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(file_okay=False, writable=True),
    help="Directory to write the harvested pages to.",
)
@click.option(
    "-m",
    "--metadata-prefix",
    help="OAI-PMH metadata prefix, for instance lido, marc21 or oai_dc.",
)
@click.option("--set", "set_spec", help="OAI-PMH set to restrict to.")
@click.option(
    "--from",
    "from_date",
    help="Harvest records changed on or after this date.",
)
@click.option(
    "--until",
    "until_date",
    help="Harvest records changed on or before this date.",
)
# No -q: that is --quiet on `efi-conv` itself, and a -q here would
# swallow the next argument as a query on an OAI-PMH harvest.
@click.option("--query", help="SRU query, in CQL.")
@click.option(
    "--record-schema", help="SRU record schema, for instance marcxml."
)
@click.option(
    "--page-size",
    type=int,
    default=DEFAULT_SRU_PAGE_SIZE,
    show_default=True,
    help="Records to request per SRU response.",
)
@click.option(
    "--limit",
    type=int,
    help="Write at most this many records, for trying an endpoint out.",
)
@click.option(
    "--contact",
    help="Contact address to add to the User-Agent, so that whoever runs"
    " the endpoint can get in touch rather than block the harvester.",
)
@click.option(
    "--delay",
    type=float,
    default=DEFAULT_DELAY,
    show_default=True,
    help="Seconds to wait between two requests.",
)
@click.option(
    "--max-retry-after",
    type=float,
    default=DEFAULT_MAX_RETRY_AFTER,
    show_default=True,
    help="Give up rather than obey a Retry-After longer than this.",
)
def efi_harvest(
    protocol,
    url,
    output,
    metadata_prefix=None,
    set_spec=None,
    from_date=None,
    until_date=None,
    query=None,
    record_schema=None,
    page_size=DEFAULT_SRU_PAGE_SIZE,
    limit=None,
    contact=None,
    delay=DEFAULT_DELAY,
    max_retry_after=DEFAULT_MAX_RETRY_AFTER,
):
    """Fetch records from an OAI-PMH or SRU endpoint into a directory.

    The payloads are written exactly as the provider publishes them and
    are the input to `efi-conv from`, which reads a whole directory::

        efi-conv harvest -u https://example.org/oai -m lido -o harvest/
        efi-conv from -f mdigital.lido -o records.json harvest/*.xml

    Harvesting is a separate step on purpose: it is slow, it should not
    be repeated against somebody else's server while a mapping is being
    worked out, and the result is the evidence of what the provider
    actually sent.

    Give --contact an address whoever runs the endpoint can write to.
    A harvester that cannot be identified is a harvester that gets
    blocked.

    """
    common = {
        "limit": limit,
        "contact": contact,
        "delay": delay,
        "max_retry_after": max_retry_after,
    }
    try:
        if protocol == "oai":
            if not metadata_prefix:
                raise click.UsageError(
                    "OAI-PMH needs --metadata-prefix. Ask the endpoint for"
                    " verb=ListMetadataFormats if you do not know what it"
                    " offers."
                )
            result = harvest_oai(
                url,
                metadata_prefix,
                output,
                set_spec=set_spec,
                from_date=from_date,
                until_date=until_date,
                **common,
            )
        else:
            if not query:
                raise click.UsageError("SRU needs --query.")
            result = harvest_sru(
                url,
                query,
                output,
                record_schema=record_schema,
                page_size=page_size,
                **common,
            )
    except HarvestError as e:
        # The pages fetched before the failure are on disk and usable,
        # so say what went wrong and exit non-zero without a traceback.
        raise click.ClickException(str(e)) from e
    log.info(
        f"Harvested {result.records} record(s) into {len(result.files)}"
        f" file(s) in {result.requests} request(s)"
    )
    if result.deleted:
        log.info(f"{result.deleted} deleted record(s) skipped")
    if not result.records:
        # Nothing matched is not the same as something went wrong. An
        # incremental harvest whose only changes were deletions is a
        # good run, and so is a query nothing answers.
        if result.deleted:
            log.warning(
                f"No records to write: the only changes the endpoint"
                f" reported were {result.deleted} deletion(s). That is a"
                f" complete run, not a failure."
            )
        else:
            log.warning(
                "The endpoint sent no records to write. Nothing matched"
                " the request, which is not in itself an error."
            )
