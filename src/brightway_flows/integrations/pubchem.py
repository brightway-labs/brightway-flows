"""Query PubChem for compound data based on EF 3.1 flow names and CAS numbers."""

import asyncio
from pathlib import Path

import httpx
import orjson
from tqdm import tqdm

from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.sources import base_source_list
from brightway_flows.integrations.fetch_pubchem_identifiers import (
    PUG_VIEW_URL,
    NoOtherIdentifiers,
    extract_other_identifiers,
    filter_cas_hmdb_only,
)

PUBCHEM_NAME_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{value}/json"
)
PUBCHEM_CAS_URL = (
    "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/xref/RN/{value}/json"
)


def _trim_response(data: dict) -> list[dict]:
    """Keep only cid, charge, and props from each compound in a PubChem response."""
    return [
        {
            "cid": compound["id"]["id"]["cid"],
            "charge": compound["charge"],
            "props": compound["props"],
        }
        for compound in data.get("PC_Compounds", [])
    ]


def store_identifiers(cache: dict, cid_str: str, data: dict) -> None:
    """Record one CID's PUG View response in the identifier cache.

    Three outcomes, and the middle one is the reason this is a function rather
    than three lines inline.  A compound whose record has no "Other Identifiers"
    section is cached as `{}`: PubChem was asked and holds no registry
    identifiers for it, which is an answer the curated-CAS gate in
    `enrich_references` acts on.  A malformed response is left uncached so the
    next run retries it, because "we never got an answer" must not look like
    one.

    Both used to be swallowed by the same `except (KeyError, ValueError)`.
    Nothing was written either way, so 4,172 of the CIDs reachable from
    `by_cas` were re-requested on every run, always discarded, and the gate had
    no way to tell a compound that denies a CAS from one nobody asked (#249).
    """
    try:
        identifiers = extract_other_identifiers(data)
    except NoOtherIdentifiers:
        cache["identifiers"][cid_str] = {}
    except KeyError:
        pass
    else:
        cache["identifiers"][cid_str] = filter_cas_hmdb_only(identifiers)


def _load_cache() -> dict[str, dict]:
    """Load the existing PubChem cache file, or return an empty structure."""
    if PUBCHEM_DATA_FILEPATH.exists():
        data = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
        data.setdefault("identifiers", {})
        return data
    return {"by_name": {}, "by_cas": {}, "identifiers": {}}


def _collect_all_cids(cache: dict) -> set[int]:
    """Gather every CID present in the by_name and by_cas compound lists."""
    cids: set[int] = set()
    for compounds in cache.get("by_name", {}).values():
        for compound in compounds:
            cids.add(compound["cid"])
    for compounds in cache.get("by_cas", {}).values():
        for compound in compounds:
            cids.add(compound["cid"])
    return cids


def load_flow_queries(
    limit: int | None = None,
) -> tuple[list[str], list[str]]:
    """Return (names, cas_numbers) to query, skipping cached entries.

    Flows whose first ``context`` element is
    ``"Land use"`` are excluded.  Already-cached keys are also excluded.
    """
    base = base_source_list()
    if not base.flows_path.exists():
        raise FileNotFoundError(
            f"Flows data file not found: {base.flows_path}. "
            f"Run 'brightway-flows {base.fetch_command}' first."
        )

    flows = orjson.loads(base.flows_path.read_bytes())
    cache = _load_cache()

    cached_names: set[str] = set(cache.get("by_name", {}))
    cached_cas: set[str] = set(cache.get("by_cas", {}))

    seen_names: set[str] = set()
    seen_cas: set[str] = set()
    names: list[str] = []
    cas_numbers: list[str] = []

    for flow in flows:
        categories = flow.get("context") or flow.get("elementary_flow_categorization", [])
        if categories and categories[0] == "Land use":
            continue

        name = flow.get("name")
        if name and name not in seen_names:
            seen_names.add(name)
            if name not in cached_names:
                names.append(name)

        for cas in flow.get("cas_numbers", []):
            if cas and cas not in seen_cas:
                seen_cas.add(cas)
                if cas not in cached_cas:
                    cas_numbers.append(cas)

    if limit is not None:
        names = names[:limit]
        cas_numbers = cas_numbers[:limit]

    return names, cas_numbers


class _RateLimiter:
    """Async rate limiter that enforces a minimum interval between dispatches."""

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._last: float = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = self._interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = asyncio.get_event_loop().time()


async def _rate_limited_requests(
    queries: list[tuple[str, str]],
    rate_limiter: _RateLimiter,
    desc: str,
) -> dict[str, dict]:
    """Fire async rate-limited GET requests and return successful JSON responses.

    Parameters
    ----------
    queries
        Each element is ``(key, url)``.
    rate_limiter
        Shared rate limiter instance.
    desc
        Label for the tqdm progress bar.
    """
    results: dict[str, dict] = {}
    progress = tqdm(total=len(queries), desc=desc)

    async def fetch_one(client: httpx.AsyncClient, key: str, url: str) -> None:
        await rate_limiter.wait()
        try:
            response = await client.get(url)
            response.raise_for_status()
            results[key] = orjson.loads(response.content)
        except (httpx.HTTPStatusError, httpx.RequestError):
            pass
        finally:
            progress.update(1)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        tasks = [fetch_one(client, key, url) for key, url in queries]
        await asyncio.gather(*tasks)

    progress.close()
    return results


async def fetch_and_store_pubchem(limit: int | None = None) -> Path:
    """Load flow queries, query PubChem, merge with cache, and persist."""
    names, cas_numbers = load_flow_queries(limit=limit)

    rate_limiter = _RateLimiter(2.5)
    cache = _load_cache()

    for cid_str, identifiers in cache.get("identifiers", {}).items():
        filter_cas_hmdb_only(identifiers)

    # --- Phase 1: compound data by name and CAS ---
    compound_queries: list[tuple[str, str]] = []
    compound_queries.extend((n, PUBCHEM_NAME_URL.format(value=n)) for n in names)
    compound_queries.extend((c, PUBCHEM_CAS_URL.format(value=c)) for c in cas_numbers)

    if compound_queries:
        results = await _rate_limited_requests(
            compound_queries, rate_limiter, "Compounds"
        )

        name_set = set(names)
        cas_set = set(cas_numbers)

        for key, data in results.items():
            trimmed = _trim_response(data)
            if key in name_set:
                cache["by_name"][key] = trimmed
            elif key in cas_set:
                cache["by_cas"][key] = trimmed

    # --- Phase 2: identifiers by CID (one request per unique CID) ---
    all_cids = _collect_all_cids(cache)
    cached_cids = {int(k) for k in cache.get("identifiers", {})}
    new_cids = sorted(all_cids - cached_cids)

    if limit is not None:
        new_cids = new_cids[:limit]

    if new_cids:
        id_queries = [
            (str(cid), PUG_VIEW_URL.format(cid=cid)) for cid in new_cids
        ]
        id_results = await _rate_limited_requests(
            id_queries, rate_limiter, "Identifiers"
        )

        for cid_str, data in id_results.items():
            store_identifiers(cache, cid_str, data)

    PUBCHEM_DATA_FILEPATH.write_bytes(
        orjson.dumps(cache, option=orjson.OPT_INDENT_2)
    )

    return PUBCHEM_DATA_FILEPATH
