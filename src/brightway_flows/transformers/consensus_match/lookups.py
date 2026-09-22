"""Every network call consensus matching makes, and the caches behind them.

Three services are reached: Common Chemistry for CAS detail and name search,
Wikidata and Wikipedia as the fallback evidence when local sources cannot
settle a relationship.  All three are cached on disk between runs, all three
are throttled, and all three are skipped entirely when a probe at startup says
the service is unreachable -- a run without network produces the same artifacts
as one with it, minus whatever was not already cached.

Nothing here decides anything about a substance.  The callers do that; this
module only answers what a source says, or says nothing.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import orjson
import structlog
from tqdm import tqdm

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.filesystem import (
    COMMONCHEMISTRY_CACHE_FILEPATH,
    WEB_LOOKUP_CACHE_FILEPATH,
    WIKIDATA_CACHE_FILEPATH,
)
from brightway_flows.pipeline import normalize
from brightway_flows.settings import get_settings

logger = structlog.get_logger(__name__)

HTTP_HEADERS = {"User-Agent": "brightway-flows/1.0.0 (https://github.com/brightway-labs)"}
COMMONCHEMISTRY_BASE_URL = "https://commonchemistry.cas.org/api"
WIKIPEDIA_SUMMARY_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"

_CONNECTIVITY_PROBE_TIMEOUT = 5.0
_CONNECTIVITY_PROBE_URLS: dict[str, str] = {
    "wikidata": "https://www.wikidata.org/w/api.php",
    "wikipedia": "https://en.wikipedia.org/api/rest_v1/page/summary/Water",
    "commonchemistry": "https://commonchemistry.cas.org/",
}

LOOKUP_MAX_RETRIES = 3
COMMONCHEM_BACKOFF_BASE_S = 0.5
COMMONCHEM_BACKOFF_MAX_S = 8.0
_COMMONCHEM_PARALLEL_WORKERS = 10


def probe_url(url: str, timeout: float = _CONNECTIVITY_PROBE_TIMEOUT) -> bool:
    """Return True if ``url`` responds within ``timeout`` seconds, False otherwise."""
    try:
        with httpx.Client(timeout=timeout, headers=HTTP_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
        return True
    except Exception:
        return False


def load_json_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return orjson.loads(path.read_bytes())


def save_json_cache(path: Path, payload: dict[str, Any]) -> None:
    data = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass
class LookupClient:
    """Cached, throttled access to Common Chemistry, Wikidata and Wikipedia."""

    #: Raw payloads, keyed as the services are queried, persisted between runs.
    commonchem_cache: dict[str, Any] = field(
        default_factory=lambda: {"search_by_query": {}, "detail_by_cas": {}}
    )
    wikidata_cache: dict[str, Any] = field(default_factory=dict)
    web_cache: dict[str, Any] = field(default_factory=dict)

    #: Common Chemistry names indexed both ways, derived from the payloads above
    #: as they are read.  In memory only: they are a view of the cache, not a
    #: second copy of it.
    commonchem_names_by_cas: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    commonchem_cas_by_name: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )

    api_key: str = ""
    #: False for a service whose probe failed at startup; every lookup against
    #: it then answers from cache alone rather than paying a timeout each time.
    service_available: dict[str, bool] = field(default_factory=dict)
    web_lookups_this_run: int = 0

    _service_last_request_ts: dict[str, float] = field(default_factory=dict)
    _service_min_interval_s: dict[str, float] = field(
        default_factory=lambda: {
            "wikidata": 0.2,
            "wikipedia": 0.2,
            "commonchemistry": 0.4,
        }
    )
    _throttle_lock: threading.Lock = field(default_factory=threading.Lock)
    _http_client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # lifecycle

    def load(self) -> None:
        """Read the caches, take the API key, and probe each service."""
        self.wikidata_cache = load_json_cache(WIKIDATA_CACHE_FILEPATH)
        self.web_cache = load_json_cache(WEB_LOOKUP_CACHE_FILEPATH)
        self.commonchem_cache = load_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH)
        if not isinstance(self.commonchem_cache.get("search_by_query"), dict):
            self.commonchem_cache["search_by_query"] = {}
        if not isinstance(self.commonchem_cache.get("detail_by_cas"), dict):
            self.commonchem_cache["detail_by_cas"] = {}
        token = get_settings().commonchemistry_api_key
        self.api_key = token.get_secret_value().strip() if token is not None else ""

        for service, url in _CONNECTIVITY_PROBE_URLS.items():
            available = probe_url(url)
            self.service_available[service] = available
            if not available:
                logger.warning(
                    "web_service_unavailable",
                    service=service,
                    url=url,
                    detail="Service unreachable; will use cached data only for this run.",
                )
            else:
                logger.info("web_service_available", service=service)

    def reload_commonchem_cache(self) -> None:
        """Refresh Common Chemistry cache after earlier transformers may have updated it."""
        payload = load_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH)
        if not isinstance(payload, dict):
            return
        search_payload = payload.get("search_by_query")
        detail_payload = payload.get("detail_by_cas")
        if not isinstance(search_payload, dict) or not isinstance(detail_payload, dict):
            return
        self.commonchem_cache = payload
        logger.info(
            "consensus_match_commonchem_cache_reloaded",
            search_entries=len(search_payload),
            detail_entries=len(detail_payload),
        )

    def save_caches(self) -> None:
        save_json_cache(WIKIDATA_CACHE_FILEPATH, self.wikidata_cache)
        save_json_cache(WEB_LOOKUP_CACHE_FILEPATH, self.web_cache)
        save_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH, self.commonchem_cache)

    def close(self) -> None:
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def _client(self) -> httpx.Client:
        """The HTTP client, created on demand rather than in ``setup()``.

        ``transform()`` closes it when it finishes, which was safe while it ran
        once per build.  It now also runs once per source list (#213), and
        ``setup()`` is deliberately not called again -- so the second call found
        a client that had been closed and set to None, and every lookup raised
        ``'NoneType' object has no attribute 'get'`` into a broad ``except``
        that logged it as a warning.  Each failure still paid its rate-limit
        delay first, so the pass spent minutes making calls that could not
        succeed.

        Creating on demand makes the close a release rather than a teardown, and
        keeps the lifecycle correct however many times ``transform()`` runs.
        """
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=20.0, headers=HTTP_HEADERS)
        return self._http_client

    # ------------------------------------------------------------------
    # Common Chemistry

    def names_for_cas(self, cas: str) -> set[str]:
        """The primary name and synonyms Common Chemistry holds for *cas*."""
        cas_clean = str(cas or "").strip()
        if not cas_clean:
            return set()
        cached = self.commonchem_names_by_cas.get(cas_clean)
        if cached:
            return set(cached)
        detail = self.commonchem_detail(cas_clean)
        out: set[str] = set()
        name = detail.get("name")
        if isinstance(name, str) and name.strip():
            out.add(name.strip())
        for syn in detail.get("synonyms", []):
            if isinstance(syn, str) and syn.strip():
                out.add(syn.strip())
        if out:
            self.commonchem_names_by_cas[cas_clean].update(out)
            for text in out:
                self.commonchem_cas_by_name[normalize(text)].add(cas_clean)
        return out

    def cas_from_name(self, flow_name: str) -> set[str]:
        """The CAS numbers Common Chemistry returns under exactly this name."""
        query = flow_name.strip()
        if not query:
            return set()
        cached = self.commonchem_cas_by_name.get(normalize(query))
        if cached:
            return set(cached)
        payload = self.commonchem_search(query)
        out: set[str] = set()
        for row in payload.get("results", []):
            if not isinstance(row, dict):
                continue
            candidate_name = str(row.get("name") or "").strip()
            cas = str(row.get("rn") or "").strip()
            if not cas:
                continue
            if normalize(candidate_name) == normalize(query):
                out.add(cas)
        if out:
            key = normalize(query)
            self.commonchem_cas_by_name[key].update(out)
        return out

    def commonchem_search(self, query: str) -> dict[str, Any]:
        q = query.strip()
        if not q:
            return {"results": []}
        cache = self.commonchem_cache.setdefault("search_by_query", {})
        key = q.lower()
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached
        if not self.api_key:
            return {"results": []}
        if not self.service_available.get("commonchemistry", True):
            return {"results": []}

        self.web_lookups_this_run += 1
        result: dict[str, Any] = {"results": []}
        try:
            payload: dict[str, Any] | None = None
            attempt = 0
            while True:
                try:
                    self._throttle("commonchemistry")
                    resp = self._client().get(
                        f"{COMMONCHEMISTRY_BASE_URL}/search",
                        params={"q": q, "size": 25},
                        headers={"X-API-KEY": self.api_key},
                    )
                    resp.raise_for_status()
                    parsed = resp.json()
                    if isinstance(parsed, dict):
                        payload = parsed
                        break
                except Exception as exc:
                    is_429 = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
                    if is_429:
                        logger.warning("commonchemistry_rate_limited_search", query=q, attempt=attempt)
                    if is_429 or (attempt < LOOKUP_MAX_RETRIES - 1 and self._should_retry(exc)):
                        time.sleep(self._backoff_delay(exc, attempt))
                        attempt += 1
                        continue
                    raise
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            if isinstance(rows, list):
                result["results"] = [
                    {
                        "rn": str(item.get("rn") or "").strip(),
                        "name": str(item.get("name") or "").strip(),
                    }
                    for item in rows
                    if isinstance(item, dict)
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("commonchemistry_search_failed", query=q, error=str(exc))

        cache[key] = result
        return result

    def commonchem_detail(self, cas: str) -> dict[str, Any]:
        cas_clean = cas.strip()
        if not cas_clean:
            return {}
        cache = self.commonchem_cache.setdefault("detail_by_cas", {})
        cached = cache.get(cas_clean)
        if isinstance(cached, dict):
            return cached
        if not self.api_key:
            return {}
        if not self.service_available.get("commonchemistry", True):
            return {}

        self.web_lookups_this_run += 1
        result: dict[str, Any] = {}
        try:
            payload: dict[str, Any] | None = None
            attempt = 0
            while True:
                try:
                    self._throttle("commonchemistry")
                    resp = self._client().get(
                        f"{COMMONCHEMISTRY_BASE_URL}/detail",
                        params={"cas_rn": cas_clean},
                        headers={"X-API-KEY": self.api_key},
                    )
                    resp.raise_for_status()
                    parsed = resp.json()
                    if isinstance(parsed, dict):
                        payload = parsed
                        break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        # Treat missing CAS as a valid "no data" response and cache it.
                        payload = {}
                        break
                    is_429 = exc.response.status_code == 429
                    if is_429:
                        logger.warning("commonchemistry_rate_limited_detail", cas=cas_clean, attempt=attempt)
                    if is_429 or (attempt < LOOKUP_MAX_RETRIES - 1 and self._should_retry(exc)):
                        time.sleep(self._backoff_delay(exc, attempt))
                        attempt += 1
                        continue
                    raise
                except Exception as exc:
                    if attempt < LOOKUP_MAX_RETRIES - 1 and self._should_retry(exc):
                        time.sleep(self._backoff_delay(exc, attempt))
                        attempt += 1
                        continue
                    raise
            if isinstance(payload, dict):
                if payload:
                    result = {
                        "rn": str(payload.get("rn") or "").strip(),
                        "name": str(payload.get("name") or "").strip(),
                        "synonyms": [
                            str(x).strip()
                            for x in payload.get("synonyms", [])
                            if isinstance(x, str) and str(x).strip()
                        ],
                        "molecularFormula": str(payload.get("molecularFormula") or "").strip(),
                        "inchi": str(payload.get("inchi") or "").strip(),
                        "inchiKey": str(payload.get("inchiKey") or "").strip(),
                        "url": f"https://commonchemistry.cas.org/detail?cas_rn={cas_clean}",
                    }
                else:
                    result = {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("commonchemistry_detail_failed", cas=cas_clean, error=str(exc))

        cache[cas_clean] = result
        return result

    def prefetch_commonchem(self, flows: list[Flow]) -> None:
        """Warm the cache by fetching all uncached CAS and name keys in parallel."""
        if not self.api_key or not self.service_available.get("commonchemistry", True):
            return

        search_cache = self.commonchem_cache.setdefault("search_by_query", {})
        detail_cache = self.commonchem_cache.setdefault("detail_by_cas", {})

        seen_names: set[str] = set()
        seen_cas: set[str] = set()
        uncached_names: list[str] = []
        uncached_cas: list[str] = []

        for flow in flows:
            flow_name = flow_label_value(flow).strip()
            if flow_name:
                key = flow_name.lower()
                if key not in search_cache and key not in seen_names:
                    uncached_names.append(flow_name)
                    seen_names.add(key)
            for cas in flow.cas_numbers:
                cas_clean = str(cas).strip()
                if cas_clean and cas_clean not in detail_cache and cas_clean not in seen_cas:
                    uncached_cas.append(cas_clean)
                    seen_cas.add(cas_clean)

        total = len(uncached_names) + len(uncached_cas)
        if not total:
            logger.info("commonchem_prefetch_skipped", reason="all keys already cached")
            return

        logger.info(
            "commonchem_prefetch_start",
            uncached_names=len(uncached_names),
            uncached_cas=len(uncached_cas),
            workers=_COMMONCHEM_PARALLEL_WORKERS,
        )

        completed = 0
        with ThreadPoolExecutor(max_workers=_COMMONCHEM_PARALLEL_WORKERS) as pool:
            futures = (
                [pool.submit(self.commonchem_search, n) for n in uncached_names]
                + [pool.submit(self.commonchem_detail, c) for c in uncached_cas]
            )
            for _ in tqdm(as_completed(futures), total=len(futures), desc="CommonChem prefetch", unit="req"):
                completed += 1
                if completed % 500 == 0:
                    save_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH, self.commonchem_cache)
                    logger.info("commonchem_prefetch_checkpoint", completed=completed, total=total)

        logger.info("commonchem_prefetch_complete", fetched=total)

    # ------------------------------------------------------------------
    # fallback evidence

    def wikidata(self, cas: str, name: str) -> dict[str, Any]:
        key = f"{cas}|{name}".lower()
        if key in self.wikidata_cache:
            return self.wikidata_cache[key]
        if not self.service_available.get("wikidata", True):
            return {}

        self.web_lookups_this_run += 1
        result: dict[str, Any] = {}
        query = cas or name
        try:
            payload: dict[str, Any] | None = None
            for attempt in range(LOOKUP_MAX_RETRIES):
                try:
                    self._throttle("wikidata")
                    with httpx.Client(timeout=20.0, headers=HTTP_HEADERS) as client:
                        resp = client.get(
                            "https://www.wikidata.org/w/api.php",
                            params={
                                "action": "wbsearchentities",
                                "format": "json",
                                "language": "en",
                                "search": query,
                                "limit": 1,
                            },
                        )
                        resp.raise_for_status()
                        parsed = resp.json()
                        if isinstance(parsed, dict):
                            payload = parsed
                            break
                except Exception:
                    if attempt + 1 < LOOKUP_MAX_RETRIES:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise
            if isinstance(payload, dict):
                items = payload.get("search", [])
                if isinstance(items, list) and items:
                    item = items[0]
                    if isinstance(item, dict):
                        result = {
                            "id": item.get("id"),
                            "label": item.get("label"),
                            "description": item.get("description"),
                            "url": item.get("concepturi"),
                        }
        except Exception as exc:  # noqa: BLE001
            logger.warning("wikidata_lookup_failed", cas=cas, name=name, error=str(exc))

        self.wikidata_cache[key] = result
        return result

    def wikipedia(self, cas: str, name: str) -> dict[str, Any]:
        key = f"{cas}|{name}".lower()
        if key in self.web_cache:
            cached = self.web_cache.get(key)
            if isinstance(cached, dict):
                return cached
            return {}
        if not self.service_available.get("wikipedia", True):
            return {}

        self.web_lookups_this_run += 1
        result: dict[str, Any] = {}
        # Wikipedia articles are title-based; use the compound name rather than CAS.
        title = name or cas
        try:
            for attempt in range(LOOKUP_MAX_RETRIES):
                try:
                    self._throttle("wikipedia")
                    resp = self._client().get(
                        f"{WIKIPEDIA_SUMMARY_BASE}/{title}",
                        params={"redirect": "true"},
                    )
                    if resp.status_code == 404:
                        # No Wikipedia article for this name — cache the miss.
                        break
                    resp.raise_for_status()
                    payload = resp.json()
                    if isinstance(payload, dict):
                        page_url = (
                            (payload.get("content_urls") or {})
                            .get("desktop", {})
                            .get("page", "")
                        )
                        result = {
                            "heading": payload.get("title"),
                            "abstract": payload.get("extract"),
                            "url": page_url or payload.get("canonicalurl"),
                        }
                    break
                except Exception as exc:
                    if attempt + 1 < LOOKUP_MAX_RETRIES:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("web_lookup_failed", cas=cas, name=name, error=str(exc))

        self.web_cache[key] = result
        return result

    # ------------------------------------------------------------------
    # rate limiting and retries

    def _throttle(self, service: str) -> None:
        min_interval = self._service_min_interval_s.get(service, 0.0)
        with self._throttle_lock:
            now = time.monotonic()
            next_allowed = self._service_last_request_ts.get(service, 0.0)
            wait = max(0.0, next_allowed - now)
            self._service_last_request_ts[service] = max(now, next_allowed) + min_interval
        if wait > 0.0:
            time.sleep(wait)

    def _should_retry(self, exc: Exception) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status in {429, 500, 502, 503, 504}
        return False

    def _backoff_delay(self, exc: Exception, attempt: int) -> float:
        if isinstance(exc, httpx.HTTPStatusError):
            retry_after = exc.response.headers.get("Retry-After")
            if retry_after:
                try:
                    parsed = float(retry_after)
                    if parsed > 0:
                        return min(parsed, COMMONCHEM_BACKOFF_MAX_S)
                except ValueError:
                    pass
        exponential = COMMONCHEM_BACKOFF_BASE_S * (2 ** attempt)
        return min(exponential, COMMONCHEM_BACKOFF_MAX_S)
