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
actually sent on the day the records were made.

"""

from dataclasses import dataclass, field
import logging
import pathlib
import time
from urllib.parse import urlencode

import click
from lxml import etree
import requests

from .cli import cli_main

log = logging.getLogger(__name__)

OAI_NAMESPACE = "http://www.openarchives.org/OAI/2.0/"
#: SRU changed its namespace between the versions still in the field.
SRU_NAMESPACES = (
    "http://www.loc.gov/zing/srw/",
    "http://docs.oasis-open.org/ns/search-ws/sruResponse",
)
#: Namespace of the element wrapping a harvested page.
HARVEST_NAMESPACE = "https://av-efi.net/efi-conv/harvest"

#: Requests that fail with one of these are worth repeating.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

DEFAULT_TIMEOUT = 60
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF = 5
#: Servers vary in what they will hand over in one response.
DEFAULT_SRU_PAGE_SIZE = 50
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


def fetch(
    url,
    params,
    session=None,
    timeout=DEFAULT_TIMEOUT,
    retries=DEFAULT_RETRIES,
    backoff=DEFAULT_BACKOFF,
    sleep=None,
):
    """Return the body of one request, repeating a failure worth repeating.

    An OAI-PMH server under load answers 503 with a Retry-After header
    rather than an error, and expects the harvester to wait and come
    back. Ignoring that is how a harvester gets blocked.

    """
    get = (session or requests).get
    sleep = time.sleep if sleep is None else sleep
    attempt = 0
    while True:
        attempt += 1
        try:
            response = get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            if attempt > retries:
                raise HarvestError(f"{url}: {e}") from e
            wait = backoff * attempt
            log.warning(f"{url}: {e}, retrying in {wait} s")
            sleep(wait)
            continue
        if response.status_code in RETRY_STATUS and attempt <= retries:
            wait = retry_after(response, backoff * attempt)
            log.warning(
                f"{url}: HTTP {response.status_code},"
                f" retrying in {wait} s"
            )
            sleep(wait)
            continue
        if response.status_code != 200:
            raise HarvestError(
                f"{url} answered HTTP {response.status_code}"
            )
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
        Stop after this many records. For trying an endpoint out
        without pulling the whole repository.

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
    while True:
        page += 1
        body = fetch(url, params, session=session, **fetch_options)
        result.requests += 1
        root = parse_response(body, url)
        error = oai_error(root)
        if error:
            if error.startswith("noRecordsMatch") and page == 1:
                log.warning(f"{url} has no records matching the request")
                return result
            raise HarvestError(f"{url} reported {error}")
        payloads, deleted = oai_payloads(root)
        result.deleted += deleted
        if payloads:
            result.files.append(write_page(directory, page, payloads))
            result.records += len(payloads)
        log.info(
            f"Harvested page {page}: {len(payloads)} record(s),"
            f" {result.records} so far"
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


def oai_payloads(root):
    """Return the metadata payloads of one OAI response.

    Returns
    -------
    tuple
        The payload elements and the number of deleted records seen.

    """
    payloads = []
    deleted = 0
    list_records = root.find(f"{{{OAI_NAMESPACE}}}ListRecords")
    if list_records is None:
        return payloads, deleted
    for record in list_records.findall(f"{{{OAI_NAMESPACE}}}record"):
        header = record.find(f"{{{OAI_NAMESPACE}}}header")
        if header is not None and header.get("status") == "deleted":
            deleted += 1
            continue
        metadata = record.find(f"{{{OAI_NAMESPACE}}}metadata")
        if metadata is None or len(metadata) == 0:
            log.warning("Record without metadata skipped")
            continue
        payloads.append(metadata[0])
    return payloads, deleted


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
    session=None,
    **fetch_options,
) -> HarvestResult:
    """Harvest an SRU endpoint with searchRetrieve.

    SRU is how library systems are queried, so this is the way to a
    catalogue's film holdings without asking anybody for an export.

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

    """
    directory = prepare_directory(output_directory)
    result = HarvestResult()
    start = 1
    page = 0
    total = None
    while True:
        page += 1
        params = {
            "version": version,
            "operation": "searchRetrieve",
            "query": query,
            "startRecord": start,
            "maximumRecords": page_size,
        }
        if record_schema:
            params["recordSchema"] = record_schema
        body = fetch(url, params, session=session, **fetch_options)
        result.requests += 1
        root = parse_response(body, url)
        diagnostic = sru_diagnostic(root)
        if diagnostic:
            raise HarvestError(f"{url} reported {diagnostic}")
        if total is None:
            total = sru_number_of_records(root)
            log.info(f"{url} reports {total} matching record(s)")
        payloads = sru_payloads(root)
        if payloads:
            result.files.append(write_page(directory, page, payloads))
            result.records += len(payloads)
        log.info(
            f"Harvested page {page}: {len(payloads)} record(s),"
            f" {result.records} so far"
        )
        if not payloads:
            break
        if limit is not None and result.records >= limit:
            log.info(f"Stopping after {result.records} record(s) as asked")
            break
        if total is not None and result.records >= total:
            break
        start += len(payloads)
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


def write_page(directory: pathlib.Path, page: int, payloads) -> str:
    """Write one page of payloads and return the file name.

    Each page becomes one document with the payloads under a wrapper of
    ours. The readers in this package find their records by element
    name whatever wraps them, so the wrapper costs nothing and keeps
    the payloads exactly as the provider sent them.

    """
    root = etree.Element(f"{{{HARVEST_NAMESPACE}}}harvest")
    for payload in payloads:
        root.append(payload)
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
    """Return the request as a URL, for the log and for the report."""
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
@click.option("-q", "--query", help="SRU query, in CQL.")
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
    help="Stop after this many records, for trying an endpoint out.",
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

    """
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
            limit=limit,
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
            limit=limit,
        )
    log.info(
        f"Harvested {result.records} record(s) into {len(result.files)}"
        f" file(s) in {result.requests} request(s)"
    )
    if result.deleted:
        log.info(f"{result.deleted} deleted record(s) skipped")
    if not result.records:
        raise SystemExit(1)
