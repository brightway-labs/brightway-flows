"""Early CAS reconciliation and ETL audit using Common Chemistry + ChEBI."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import httpx
import orjson
import structlog
from tqdm import tqdm

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.common import Provenance
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.filesystem import COMMONCHEMISTRY_CACHE_FILEPATH
from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.domain.labels import flow_label_value, strip_markup
from brightway_flows.pipeline import Change, Transformer, normalize
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.settings import get_settings

logger = structlog.get_logger(__name__)
HTTP_HEADERS = {"User-Agent": "brightway-flows/1.0.0 (https://github.com/brightway-labs)"}
COMMONCHEMISTRY_BASE_URL = "https://commonchemistry.cas.org/api"
LOOKUP_MAX_RETRIES = 3
COMMONCHEM_BACKOFF_BASE_S = 0.5
COMMONCHEM_BACKOFF_MAX_S = 8.0
_CONNECTIVITY_PROBE_TIMEOUT = 5.0
_COMMONCHEM_PARALLEL_WORKERS = 10


def _probe_url(url: str, timeout: float = _CONNECTIVITY_PROBE_TIMEOUT) -> bool:
    """Return True if ``url`` responds within ``timeout`` seconds, False otherwise."""
    try:
        with httpx.Client(timeout=timeout, headers=HTTP_HEADERS) as client:
            resp = client.get(url)
            resp.raise_for_status()
        return True
    except Exception:
        return False


@dataclass
class CommonchemRecord(SerialisableRecord):
    """One substance as Common Chemistry describes it.

    A projection of the API payload, not the payload: only the three fields the
    review pages show survive the boundary, so a change in what CAS returns
    cannot silently alter what a curator reads.
    """

    name: str
    cas: str
    url: str

    #: `rn` is Common Chemistry's own name for a registry number, kept so the
    #: stored payload reads the same as the API response it came from.
    _ALIASES: ClassVar[dict[str, str]] = {"cas": "rn"}


@dataclass
class ChebiCandidate(SerialisableRecord):
    """One ChEBI record a flow's name resolves to, when several do."""

    chebi_id: str
    label: str
    cas_numbers: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class CommonchemNameMatch(SerialisableRecord):
    """Common Chemistry knows this flow's name, and gives a different CAS.

    The name match is *applied* only when the flow has no CAS of its own.  When
    it has one, the two disagree and the CAS wins: this row is then a report,
    not a change, exactly like its sibling `CommonchemCasNameDifference` -- the
    same disagreement seen from the other side, and it cannot have two answers.

    Common Chemistry is definitive about which registry number a name maps to.
    That is not the same claim as "this flow, which carries number Y and calls
    itself N, is wrong about Y".  Source lists routinely pair a generic common
    name with the specific number that says what is actually meant: EF ships
    `butanol` with `71-36-3` (1-butanol) and `ascorbic acid` with `50-81-7`
    (L-ascorbic acid).  Looking up the generic name returns the *generic*
    registry entry, and treating that as definitive discarded the one field that
    said which substance was meant.  See issue #246 and
    `docs/deciding/identity.md`.

    `applied` records which way it went, so a curator can separate the fill-ins
    from the disagreements.
    """

    uuid: str
    flow_name: str
    source: str
    current_cas_numbers: list[str] = field(default_factory=list)
    commonchem_cas_numbers: list[str] = field(default_factory=list)
    matched_commonchem_records: list[CommonchemRecord] = field(default_factory=list)
    #: True when the flow had no CAS and this one was written to it; False when
    #: the flow's own CAS was kept and this is a disagreement to review.
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["matched_commonchem_records"] = [
            record.to_dict() for record in self.matched_commonchem_records
        ]
        return payload


@dataclass
class CommonchemCasNameDifference(SerialisableRecord):
    """Common Chemistry knows this flow's CAS, and calls it something else.

    Nothing was changed: a name is not evidence of identity the way a CAS is,
    and the flow's own name may be the one its source list needs.  Purely a
    report.
    """

    uuid: str
    flow_name: str
    source: str
    cas: str
    commonchem_name: str
    commonchem_url: str = ""


def cas_ambiguity_item_key(
    source: str, flow_name: str, current_cas_numbers: list[str]
) -> str:
    """The review-queue key for one ambiguous name.

    The name is keyed as it compares, not as it is spelled, because that is how
    the candidates were found: `Dmpa` and `DMPA` in one source list resolve to
    the same ChEBI records and are one question.  The source list is part of the
    key -- two lists using one name are two rows, since either could be right
    about which substance it means.
    """
    return ":".join((source, normalize(flow_name), ",".join(current_cas_numbers)))


@dataclass
class CasAmbiguity(SerialisableRecord):
    """A name that matches several ChEBI records and none of its CAS numbers.

    Recorded only when Common Chemistry had no exact name match, so there is no
    definitive answer to defer to.  The candidates are offered rather than
    applied: picking one is exactly the judgement the pipeline cannot make.

    One record per *name*, not per flow.  The candidates come from the name and
    from nothing else, so every flow one source list publishes under that name
    produces the identical row: EF 3.1 files `2-hydroxypropanoic Acid` in
    thirteen contexts, and the queue asked the same question thirteen times.
    There is one answer -- the number the name should carry -- so there is one
    row, and `flow_count` says how many flows are waiting on it.  `uuid` is one
    of them, so the row still links into the list.

    The names are what a curator needs to answer it.  A registry number reads
    as eight digits either way; `299-85-4` is `Zytron` and `71-58-9` is
    `medroxyprogesterone acetate`, and which of those the flow means is the
    question being asked.
    """

    uuid: str
    flow_name: str
    source: str
    current_cas_numbers: list[str] = field(default_factory=list)
    #: What Common Chemistry calls the flow's own numbers, where that is not
    #: what the flow calls itself.  Empty when the two agree: a name repeated
    #: across two columns says nothing, and the disagreement is the signal.
    current_cas_names: list[str] = field(default_factory=list)
    possible_corrected_cas_values: list[str] = field(default_factory=list)
    #: Each candidate number with the ChEBI labels of the records offering it,
    #: paired in one string rather than split across two columns: a candidate
    #: with no label would slide the two lists out of step.
    possible_corrected_cas_names: list[str] = field(default_factory=list)
    matched_chebi_records: list[ChebiCandidate] = field(default_factory=list)
    #: Every flow this row answers for, and how many.  The first is `uuid`.
    #: The flows this pass was shown, which is the ones the chain can still
    #: write to -- the same set that used to produce one row each.
    flow_uuids: list[str] = field(default_factory=list)
    flow_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["matched_chebi_records"] = [
            record.to_dict() for record in self.matched_chebi_records
        ]
        return payload


class CommonchemCasReviewTransformer(Transformer):
    """Apply Common Chemistry name->CAS reconciliation and export ETL review rows."""

    name = "commonchem_cas_review"
    answers_per_flow = True

    def __init__(self) -> None:
        self._chebi_records: dict[str, dict[str, Any]] = {}
        self._chebi_by_name: dict[str, list[str]] = {}
        self._chebi_by_cas: dict[str, list[str]] = {}
        self._commonchem_cache: dict[str, dict[str, Any]] = {
            "search_by_query": {},
            "detail_by_cas": {},
        }
        self._commonchem_api_key: str = ""
        self._commonchemistry_available: bool = True
        self._service_last_request_ts: dict[str, float] = {}
        self._service_min_interval_s: dict[str, float] = {"commonchemistry": 0.4}
        self._throttle_lock: threading.Lock = threading.Lock()
        self._http_client: httpx.Client | None = None

        self.commonchem_name_matches: list[CommonchemNameMatch] = []
        self.commonchem_cas_name_differences: list[CommonchemCasNameDifference] = []
        self.cas_ambiguous_candidates: list[CasAmbiguity] = []
        self._search_cache_hits = 0
        self._search_cache_misses = 0
        self._detail_cache_hits = 0
        self._detail_cache_misses = 0

    def setup(self) -> None:
        chebi = load_chebi_index()
        self._chebi_records = chebi["records"]
        self._chebi_by_name = chebi["by_name"]
        self._chebi_by_cas = chebi["by_cas"]

        self._commonchem_cache = self._load_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH)
        if not isinstance(self._commonchem_cache.get("search_by_query"), dict):
            self._commonchem_cache["search_by_query"] = {}
        if not isinstance(self._commonchem_cache.get("detail_by_cas"), dict):
            self._commonchem_cache["detail_by_cas"] = {}

        token = get_settings().commonchemistry_api_key
        self._commonchem_api_key = token.get_secret_value().strip() if token is not None else ""

        self._commonchemistry_available = _probe_url("https://commonchemistry.cas.org/")
        if not self._commonchemistry_available:
            logger.warning(
                "web_service_unavailable",
                service="commonchemistry",
                url="https://commonchemistry.cas.org/",
                detail="Service unreachable; will use cached data only for this run.",
            )
        else:
            logger.info("web_service_available", service="commonchemistry")

        logger.info(
            "commonchem_cas_review_setup_complete",
            chebi_records=len(self._chebi_records),
            commonchemistry_configured=bool(self._commonchem_api_key),
            commonchemistry_available=self._commonchemistry_available,
        )

    def transform(self, flows: list[Flow]) -> list[Change]:
        self.commonchem_name_matches = []
        self.commonchem_cas_name_differences = []
        self.cas_ambiguous_candidates = []
        self._search_cache_hits = 0
        self._search_cache_misses = 0
        self._detail_cache_hits = 0
        self._detail_cache_misses = 0
        changes: list[Change] = []
        # Ambiguities gathered by (source, name, CAS), in the order the flows
        # were seen, so a rerun over the same list produces the same rows.
        ambiguities: dict[tuple[str, str, tuple[str, ...]], CasAmbiguity] = {}

        logger.info("commonchem_cas_review_start", flow_count=len(flows))
        self._prefetch_commonchem(flows)

        for flow in tqdm(flows, desc="CommonChem CAS review (API/cache)", unit="flow"):
            uuid = str(flow.uuid or "")
            if not uuid:
                continue
            flow_name = flow_label_value(flow).strip()
            if not flow_name:
                continue
            source = str(flow.source or "")
            current_cas = self._sorted_unique(flow.cas_numbers)

            for cas in current_cas:
                detail = self._lookup_commonchemistry_detail_cached(cas)
                cc_name = str(detail.get("name") or "").strip()
                if not cc_name:
                    continue
                if normalize(cc_name) == normalize(flow_name):
                    continue
                self.commonchem_cas_name_differences.append(CommonchemCasNameDifference(
                    uuid=uuid,
                    flow_name=flow_name,
                    source=source,
                    cas=cas,
                    commonchem_name=cc_name,
                    commonchem_url=(
                        str(detail.get("url") or "")
                        or f"https://commonchemistry.cas.org/detail?cas_rn={cas}"
                    ),
                ))

            commonchem_rows = self._commonchem_exact_name_hits(flow_name)
            commonchem_cas = sorted({row.cas for row in commonchem_rows if row.cas})
            if commonchem_cas:
                if current_cas != commonchem_cas:
                    # A name match fills a gap; it never overrules a number.  The
                    # flow's own CAS is the stronger identifier and is usually
                    # the more specific one -- it is what the source list used to
                    # say which substance a generic name meant.  Where the two
                    # disagree the row is reported and nothing is written.
                    applied = not current_cas
                    self.commonchem_name_matches.append(CommonchemNameMatch(
                        uuid=uuid,
                        flow_name=flow_name,
                        source=source,
                        current_cas_numbers=current_cas,
                        commonchem_cas_numbers=commonchem_cas,
                        matched_commonchem_records=commonchem_rows,
                        applied=applied,
                    ))
                    if applied:
                        changes.append(Change(
                            uuid=uuid,
                            field="cas_numbers",
                            new_value=commonchem_cas,
                            comment=(
                                "Set CAS from Common Chemistry exact name match "
                                f"(flow had none): {', '.join(commonchem_cas)}"
                            ),
                        ))
                        existing_sources = flow.cas_number_sources
                        source_map = (
                            dict(existing_sources) if isinstance(existing_sources, dict) else {}
                        )
                        urls_by_cas = {
                            rec.cas: rec.url for rec in commonchem_rows if rec.cas and rec.url
                        }
                        for cas in commonchem_cas:
                            primary_sources = []
                            if cas in urls_by_cas:
                                primary_sources.append(urls_by_cas[cas])
                            source_map[cas] = Provenance(
                                was_generated_by=self.name,
                                was_attributed_to="brightway-flows",
                                had_primary_source=primary_sources,
                                was_derived_from="Common Chemistry exact-name CAS fill-in",
                            ).to_dict()
                        if source_map != existing_sources:
                            changes.append(Change(
                                uuid=uuid,
                                field="cas_number_sources",
                                new_value=source_map,
                                comment="Attach provenance for Common Chemistry CAS fill-ins",
                            ))
                # An exact name match answers the identity question either way --
                # it was applied, or it was reported and the flow's CAS stands --
                # so there is nothing for the ChEBI ambiguity pass to resolve.
                continue

            chebi_ids = self._chebi_by_name.get(normalize(flow_name), [])
            if len(chebi_ids) > 1:
                matched_records: list[ChebiCandidate] = []
                candidate_cas: set[str] = set()
                for chebi_id in chebi_ids:
                    rec = self._chebi_records.get(chebi_id, {})
                    rec_cas = self._sorted_unique(rec.get("cas_numbers", []))
                    candidate_cas.update(rec_cas)
                    matched_records.append(ChebiCandidate(
                        chebi_id=chebi_id,
                        # ChEBI's own field is `label`.  Read as `name` it was
                        # always absent, so every candidate reached the queue
                        # page as a bare number with nothing said about it.
                        label=str(rec.get("label") or ""),
                        cas_numbers=rec_cas,
                        url=self._chebi_link(chebi_id),
                    ))
                if candidate_cas and not set(current_cas).intersection(candidate_cas):
                    # One row per name and source, not per flow: the candidates
                    # are derived from the name alone, so every flow published
                    # under it asks the identical question and takes the same
                    # answer.
                    key = (source, normalize(flow_name), tuple(current_cas))
                    seen = ambiguities.get(key)
                    if seen is not None:
                        seen.flow_uuids.append(uuid)
                        seen.flow_count = len(seen.flow_uuids)
                    else:
                        ambiguities[key] = CasAmbiguity(
                            uuid=uuid,
                            flow_name=flow_name,
                            source=source,
                            current_cas_numbers=current_cas,
                            current_cas_names=self._named_cas(
                                current_cas, skip=flow_name
                            ),
                            possible_corrected_cas_values=sorted(candidate_cas),
                            possible_corrected_cas_names=self._chebi_named_cas(
                                sorted(candidate_cas), matched_records
                            ),
                            matched_chebi_records=matched_records,
                            flow_uuids=[uuid],
                            flow_count=1,
                        )

        self.cas_ambiguous_candidates = list(ambiguities.values())
        self._save_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH, self._commonchem_cache)
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None
        logger.info(
            "commonchem_cas_review_complete",
            flow_count=len(flows),
            search_cache_hits=self._search_cache_hits,
            search_cache_misses=self._search_cache_misses,
            detail_cache_hits=self._detail_cache_hits,
            detail_cache_misses=self._detail_cache_misses,
            network_calls=self._search_cache_misses + self._detail_cache_misses,
        )
        return changes

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """Three queues from one transformer, in the order a curator reads them.

        They were one JSON file with three parallel lists and three counts.
        Splitting them by `queue_name` is what lets each be paged and filtered
        on its own; the counts are `SELECT count(*) GROUP BY queue_name`.
        """
        items: list[ReviewQueueItem] = [
            ReviewQueueItem(
                queue_name=ReviewQueue.COMMONCHEM_NAME_CAS,
                item_key=match.uuid,
                title=match.flow_name,
                # Either an exact name match supplied a CAS the flow lacked, or
                # it disagreed with the CAS the flow already had and lost.  Both
                # want a curator's eye; `applied` in the payload says which.
                severity=Severity.REVIEW,
                uuid=match.uuid,
                cas=match.commonchem_cas_numbers[0] if match.commonchem_cas_numbers else "",
                payload=match.to_dict(),
            )
            for match in self.commonchem_name_matches
        ]
        items.extend(
            ReviewQueueItem(
                queue_name=ReviewQueue.COMMONCHEM_CAS_NAME_DIFFERENCES,
                item_key=f"{difference.uuid}:{difference.cas}",
                title=difference.flow_name,
                severity=Severity.INFO,
                uuid=difference.uuid,
                cas=difference.cas,
                payload=difference.to_dict(),
            )
            for difference in self.commonchem_cas_name_differences
        )
        items.extend(
            ReviewQueueItem(
                queue_name=ReviewQueue.CAS_AMBIGUOUS,
                # The name and the number it carries, which is what an answer
                # binds -- not the flow, of which there are thirteen for one
                # question.
                item_key=cas_ambiguity_item_key(
                    ambiguity.source,
                    ambiguity.flow_name,
                    ambiguity.current_cas_numbers,
                ),
                title=ambiguity.flow_name,
                # Nothing was applied and nothing can be until someone chooses.
                severity=Severity.BLOCKING,
                uuid=ambiguity.uuid,
                cas=ambiguity.current_cas_numbers[0] if ambiguity.current_cas_numbers else "",
                payload=ambiguity.to_dict(),
            )
            for ambiguity in self.cas_ambiguous_candidates
        )
        return items

    def _named_cas(self, cas_numbers: list[str], *, skip: str = "") -> list[str]:
        """Each number with what the registries call it, `number: name`.

        Common Chemistry first, because a registry number is its name for a
        substance and it names every number it publishes; ChEBI where Common
        Chemistry has none, which is what happens to a hydrate or a mineral.
        A number nobody names is left out rather than printed with an empty
        name -- there is nothing to say about it.

        `skip` is the flow's own name: a number called what the flow is already
        called says nothing a curator has not read in the previous column.
        """
        named: list[str] = []
        for cas in cas_numbers:
            detail = self._lookup_commonchemistry_detail_cached(cas)
            names = [strip_markup(str(detail.get("name") or "")).strip()]
            if not names[0]:
                names = [
                    str(self._chebi_records.get(chebi_id, {}).get("label") or "").strip()
                    for chebi_id in self._chebi_by_cas.get(cas, [])
                ]
            names = [
                name for name in names
                if name and (not skip or normalize(name) != normalize(skip))
            ]
            if names:
                named.append(f"{cas}: {', '.join(dict.fromkeys(names))}")
        return named

    @staticmethod
    def _chebi_named_cas(
        cas_numbers: list[str], candidates: list[ChebiCandidate]
    ) -> list[str]:
        """Each candidate number with the labels of the records offering it.

        Read off the candidates rather than looked up again: these numbers are
        in the queue *because* those records carry them, and the label a curator
        needs is the one on the record that made the suggestion.  Two records
        offering one number is the usual case -- `50-21-5` arrives as both
        `rac-lactic acid` and `2-hydroxypropanoic acid` -- and both are shown.
        """
        labels: dict[str, list[str]] = {}
        for candidate in candidates:
            for cas in candidate.cas_numbers:
                label = candidate.label.strip()
                if label and label not in labels.setdefault(cas, []):
                    labels[cas].append(label)
        return [
            f"{cas}: {', '.join(labels[cas])}" if labels.get(cas) else cas
            for cas in cas_numbers
        ]

    def _commonchem_exact_name_hits(self, flow_name: str) -> list[CommonchemRecord]:
        payload = self._lookup_commonchemistry_search_cached(flow_name)
        out: list[CommonchemRecord] = []
        for row in payload.get("results", []):
            if not isinstance(row, dict):
                continue
            candidate_name = str(row.get("name") or "").strip()
            cas = str(row.get("rn") or "").strip()
            if not cas:
                continue
            if normalize(candidate_name) != normalize(flow_name):
                continue
            out.append(CommonchemRecord(
                name=candidate_name,
                cas=cas,
                url=f"https://commonchemistry.cas.org/detail?cas_rn={cas}",
            ))
        return out

    def _client(self) -> httpx.Client:
        """The HTTP client, created on demand rather than in ``setup()``.

        ``transform()`` closes it when it finishes, which was safe while it ran
        once per build.  It now also runs once per source list (#213), and
        ``setup()`` is deliberately not called again -- so the second call found
        a client that had been closed and set to None, and every lookup raised
        ``'NoneType' object has no attribute 'get'``, caught by the broad
        ``except`` below and logged as a warning.  Each failure still paid the
        0.4 s rate-limit delay first, so an enrichment pass spent minutes making
        calls that could not succeed.

        Creating on demand makes the close a release rather than a teardown, and
        keeps the lifecycle correct however many times ``transform()`` runs.
        """
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=20.0, headers=HTTP_HEADERS)
        return self._http_client

    def _lookup_commonchemistry_search_cached(self, query: str) -> dict[str, Any]:
        q = str(query or "").strip()
        if not q:
            return {}
        cache = self._commonchem_cache.setdefault("search_by_query", {})
        key = q.lower()
        cached = cache.get(key)
        if isinstance(cached, dict):
            self._search_cache_hits += 1
            return cached
        self._search_cache_misses += 1
        if not self._commonchem_api_key:
            return {}
        if not self._commonchemistry_available:
            return {}

        result: dict[str, Any] = {}
        try:
            payload: dict[str, Any] | None = None
            attempt = 0
            while True:
                try:
                    self._throttle_lookup_service("commonchemistry")
                    resp = self._client().get(
                        f"{COMMONCHEMISTRY_BASE_URL}/search",
                        params={"q": q, "size": 10, "offset": 0},
                        headers={"X-API-KEY": self._commonchem_api_key},
                    )
                    resp.raise_for_status()
                    parsed = resp.json()
                    if not isinstance(parsed, dict):
                        raise ValueError(f"unexpected payload type: {type(parsed).__name__}")
                    payload = parsed
                    break
                except Exception as exc:
                    is_429 = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429
                    if is_429:
                        logger.warning("commonchemistry_rate_limited_search", query=q, attempt=attempt)
                    if is_429 or (attempt < LOOKUP_MAX_RETRIES - 1 and self._should_retry_commonchem_error(exc)):
                        time.sleep(self._commonchem_backoff_delay_seconds(exc, attempt))
                        attempt += 1
                        continue
                    raise
            if isinstance(payload, dict):
                items = payload.get("results")
                if isinstance(items, list):
                    normalized_rows = [row for row in items if isinstance(row, dict)]
                else:
                    normalized_rows = []
                result = {"results": normalized_rows}
        except Exception as exc:  # noqa: BLE001
            logger.warning("commonchemistry_search_failed", query=q, error=str(exc))

        cache[key] = result
        return result

    def _lookup_commonchemistry_detail_cached(self, cas: str) -> dict[str, Any]:
        cas_clean = str(cas or "").strip()
        if not cas_clean:
            return {}
        cache = self._commonchem_cache.setdefault("detail_by_cas", {})
        cached = cache.get(cas_clean)
        if isinstance(cached, dict):
            self._detail_cache_hits += 1
            return cached
        self._detail_cache_misses += 1
        if not self._commonchem_api_key:
            return {}
        if not self._commonchemistry_available:
            return {}

        result: dict[str, Any] = {}
        try:
            payload: dict[str, Any] | None = None
            attempt = 0
            while True:
                try:
                    self._throttle_lookup_service("commonchemistry")
                    resp = self._client().get(
                        f"{COMMONCHEMISTRY_BASE_URL}/detail",
                        params={"cas_rn": cas_clean},
                        headers={"X-API-KEY": self._commonchem_api_key},
                    )
                    resp.raise_for_status()
                    parsed = resp.json()
                    if not isinstance(parsed, dict):
                        raise ValueError(f"unexpected payload type: {type(parsed).__name__}")
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
                    if is_429 or (attempt < LOOKUP_MAX_RETRIES - 1 and self._should_retry_commonchem_error(exc)):
                        time.sleep(self._commonchem_backoff_delay_seconds(exc, attempt))
                        attempt += 1
                        continue
                    raise
                except Exception as exc:
                    if attempt < LOOKUP_MAX_RETRIES - 1 and self._should_retry_commonchem_error(exc):
                        time.sleep(self._commonchem_backoff_delay_seconds(exc, attempt))
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("commonchemistry_detail_failed", cas=cas_clean, error=str(exc))

        cache[cas_clean] = result
        return result

    def _load_json_cache(self, path: Path) -> dict[str, dict[str, Any]]:
        if not path.exists():
            return {}
        payload = orjson.loads(path.read_bytes())
        if isinstance(payload, dict):
            return payload
        return {}

    def _save_json_cache(self, path: Path, payload: dict[str, Any]) -> None:
        data = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def _prefetch_commonchem(self, flows: list[dict]) -> None:
        """Warm the cache by fetching all uncached CAS and name keys in parallel."""
        if not self._commonchem_api_key or not self._commonchemistry_available:
            return

        search_cache = self._commonchem_cache.setdefault("search_by_query", {})
        detail_cache = self._commonchem_cache.setdefault("detail_by_cas", {})

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
                [pool.submit(self._lookup_commonchemistry_search_cached, n) for n in uncached_names]
                + [pool.submit(self._lookup_commonchemistry_detail_cached, c) for c in uncached_cas]
            )
            for _ in tqdm(as_completed(futures), total=len(futures), desc="CommonChem prefetch", unit="req"):
                completed += 1
                if completed % 500 == 0:
                    self._save_json_cache(COMMONCHEMISTRY_CACHE_FILEPATH, self._commonchem_cache)
                    logger.info("commonchem_prefetch_checkpoint", completed=completed, total=total)

        logger.info("commonchem_prefetch_complete", fetched=total)

    def _throttle_lookup_service(self, service: str) -> None:
        min_interval = self._service_min_interval_s.get(service, 0.0)
        with self._throttle_lock:
            now = time.monotonic()
            next_allowed = self._service_last_request_ts.get(service, 0.0)
            wait = max(0.0, next_allowed - now)
            self._service_last_request_ts[service] = max(now, next_allowed) + min_interval
        if wait > 0.0:
            time.sleep(wait)

    def _should_retry_commonchem_error(self, exc: Exception) -> bool:
        if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status in {429, 500, 502, 503, 504}
        return False

    def _commonchem_backoff_delay_seconds(self, exc: Exception, attempt: int) -> float:
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

    def _sorted_unique(self, values: list[Any]) -> list[str]:
        return sorted({
            str(v).strip()
            for v in values
            if isinstance(v, str) and str(v).strip()
        })

    def _normalize_chebi_id(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        upper = text.upper()
        if upper.startswith("CHEBI:"):
            return f"CHEBI:{text.split(':', 1)[1].strip()}"
        if "CHEBI_" in upper:
            suffix = text.rsplit("CHEBI_", 1)[-1].strip()
            if suffix:
                return f"CHEBI:{suffix}"
        if "/" in text:
            tail = text.rsplit("/", 1)[-1].strip()
            if tail:
                return self._normalize_chebi_id(tail)
        return text

    def _chebi_link(self, chebi_id: str) -> str:
        normalized = self._normalize_chebi_id(chebi_id)
        return f"https://www.ebi.ac.uk/chebi/{normalized or chebi_id}"
