"""Curated rulings about the context a prepared match lands a row in.

A decision is made about a row in *one* flow list.  It used to be stored, and
looked up, under a bare ``source_uuid``: source lists do not agree to keep out
of each other's UUID space, and reusing another list's identifiers is normal in
this domain, so two lists whose UUIDs collided applied each other's rulings --
silently, because a decision that resolves is indistinguishable from one that
was meant for the row (#241).  Every row now names the list it was decided
about, and the index is built for one list at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.sources import SourceList
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

DECISIONS_FILEPATH = (
    PACKAGE_DATA_DIR / "prepared-context-decisions.json"
)


class PreparedContextDecision(StrEnum):
    """What a curator answered about one prepared match's context."""

    #: The context the prepared match lands the row in is the one it should.
    MAPPED = "mapped"
    #: The target does not cover the row's context, and that is expected.
    EXPECTED = "expected"
    #: The prepared match is wrong; match the row like any other.
    REJECT = "reject"


#: The spellings a stored decision may use.  Spelled out as strings rather than
#: as the members, because both readers are checking a value that came off disk
#: or out of a web form and has not been made a decision yet.
VALID_DECISIONS = frozenset(decision.value for decision in PreparedContextDecision)


@dataclass(frozen=True)
class PreparedContextRuling:
    """One curated answer about where a prepared match lands a row.

    ``list_version`` is provenance -- which release the curator was looking at
    -- and not part of the key; see
    :func:`load_prepared_context_decision_index`.
    """

    list_name: str
    source_uuid: str
    prepared_target_elementary_flow_id: str
    decision: PreparedContextDecision
    list_version: str = ""
    expected_context_iri: str = ""
    target_flow_object_id: str = ""
    expected_context_elementary_ids: tuple[str, ...] = ()


#: The on-disk format of *this* ruling file, and nothing else.  Every ruling
#: file versions itself independently, so the name is qualified: the bare
#: ``SCHEMA_VERSION`` is ``domain.schema``'s, the version the project publishes
#: (#98).  Bumped to 2 when every row gained ``list_name``.  The file is
#: package data rather than a published artifact, so that was a rewrite:
#: nothing reads version 1.
DECISIONS_SCHEMA_VERSION = 2


def _read_payload() -> dict[str, Any]:
    if not DECISIONS_FILEPATH.exists():
        return {"schema_version": DECISIONS_SCHEMA_VERSION, "decisions": []}
    payload = orjson.loads(DECISIONS_FILEPATH.read_bytes())
    if not isinstance(payload, dict):
        return {"schema_version": DECISIONS_SCHEMA_VERSION, "decisions": []}
    rows = payload.get("decisions")
    if not isinstance(rows, list):
        payload["decisions"] = []
    return payload


def load_prepared_context_decision_index(
    source: SourceList,
) -> dict[tuple[str, str], PreparedContextRuling]:
    """*source*'s decisions, keyed by ``(source_uuid, prepared_target_id)``.

    Filtering happens here rather than at the lookup so that the merge cannot
    reach a decision belonging to another list even by accident: what it is
    handed contains only this list's.

    ``list_name`` alone selects, not ``(list_name, list_version)``.  Within one
    list a UUID names the same flow across releases -- the one decision in the
    file today is present in ecoinvent 3.8 and 3.12 with identical name and
    context -- so version-scoping would make a curator re-decide the same row
    every release while closing nothing: the defect is *cross-list* collision.
    The release the ruling was made under is recorded as ``list_version``, for
    provenance rather than for matching.

    A row naming no list is skipped.  An unstamped decision belongs to every
    list, which is the defect itself.
    """
    payload = _read_payload()
    index: dict[tuple[str, str], PreparedContextRuling] = {}
    unstamped = 0
    for row in payload.get("decisions", []):
        if not isinstance(row, dict):
            continue
        list_name = str(row.get("list_name") or "").strip()
        source_uuid = str(row.get("source_uuid") or "").strip()
        prepared_target_id = str(row.get("prepared_target_elementary_flow_id") or "").strip()
        decision = str(row.get("decision") or "").strip()
        if not source_uuid or not prepared_target_id or decision not in VALID_DECISIONS:
            continue
        if not list_name:
            unstamped += 1
            continue
        if list_name != source.list_name:
            continue
        index[(source_uuid, prepared_target_id)] = PreparedContextRuling(
            list_name=list_name,
            source_uuid=source_uuid,
            prepared_target_elementary_flow_id=prepared_target_id,
            decision=PreparedContextDecision(decision),
            list_version=str(row.get("list_version") or "").strip(),
            expected_context_iri=str(row.get("expected_context_iri") or "").strip(),
            target_flow_object_id=str(row.get("target_flow_object_id") or "").strip(),
            expected_context_elementary_ids=tuple(
                str(x).strip()
                for x in row.get("expected_context_elementary_ids") or ()
                if str(x).strip()
            ),
        )
    if unstamped:
        logger.warning(
            "prepared_context_decisions_without_list",
            path=str(DECISIONS_FILEPATH),
            skipped=unstamped,
        )
    return index


def save_prepared_context_decision(
    *,
    source: SourceList,
    source_uuid: str,
    prepared_target_elementary_flow_id: str,
    decision: str,
    expected_context_iri: str = "",
    target_flow_object_id: str = "",
    expected_context_elementary_ids: list[str] | None = None,
) -> Path:
    """Record one ruling, about a row in *source*.

    *source* is required rather than defaulted: a decision that does not name
    its list is the defect this parameter exists to prevent (#241).
    """
    source_uuid = str(source_uuid or "").strip()
    prepared_target_elementary_flow_id = str(prepared_target_elementary_flow_id or "").strip()
    decision = str(decision or "").strip()
    if not source_uuid or not prepared_target_elementary_flow_id:
        raise ValueError("source_uuid and prepared_target_elementary_flow_id are required")
    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(VALID_DECISIONS)}")

    payload = _read_payload()
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        decisions = []

    new_row = {
        "list_name": source.list_name,
        # Provenance: which release the curator was looking at.  Not part of
        # the key -- see `load_prepared_context_decision_index`.
        "list_version": source.list_version,
        "source_uuid": source_uuid,
        "prepared_target_elementary_flow_id": prepared_target_elementary_flow_id,
        "decision": decision,
        "expected_context_iri": str(expected_context_iri or "").strip(),
        "target_flow_object_id": str(target_flow_object_id or "").strip(),
        "expected_context_elementary_ids": sorted({
            str(x).strip()
            for x in (expected_context_elementary_ids or [])
            if isinstance(x, str) and str(x).strip()
        }),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    replaced = False
    out_rows: list[dict[str, Any]] = []
    for row in decisions:
        if not isinstance(row, dict):
            continue
        lst = str(row.get("list_name") or "").strip()
        src = str(row.get("source_uuid") or "").strip()
        tgt = str(row.get("prepared_target_elementary_flow_id") or "").strip()
        if (
            lst == source.list_name
            and src == source_uuid
            and tgt == prepared_target_elementary_flow_id
        ):
            out_rows.append(new_row)
            replaced = True
        else:
            out_rows.append(row)
    if not replaced:
        out_rows.append(new_row)

    out_rows.sort(
        key=lambda r: (
            str(r.get("list_name") or ""),
            str(r.get("source_uuid") or ""),
            str(r.get("prepared_target_elementary_flow_id") or ""),
        )
    )
    payload["schema_version"] = DECISIONS_SCHEMA_VERSION
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["decisions"] = out_rows
    DECISIONS_FILEPATH.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    return DECISIONS_FILEPATH
