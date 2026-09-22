"""Previously reviewed match decisions.

A prepared decision records a human judgement about where a source flow belongs.
Its target may since have been deprecated and replaced, so the stored identifier
is followed to whichever flow is active now.
"""

from __future__ import annotations

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.vocabulary import DCTERMS_IS_REPLACED_BY_CURIE
from brightway_flows.domain.context_registry import context_display_parts
from brightway_flows.merge.contexts import (
    _normalize_text,
)
from brightway_flows.merge.report import PreparedContextInconsistency
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes


def _is_deprecated_elementary(row: ElementaryFlow) -> bool:
    """Whether *row* is a flow the list has retired.

    The string arm is not dead code left over from the dict days: the field is
    declared ``bool | None`` and a stored payload can still carry ``"true"``,
    which `from_dict` copies through rather than coercing.
    """
    value = row.owl_deprecated
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False

def _strip_urn_uuid(value: str) -> str:
    """Strip a leading 'urn:uuid:' prefix if present."""
    if value.lower().startswith("urn:uuid:"):
        return value[len("urn:uuid:"):]
    return value

def _extract_replacement_elementary_id(row: ElementaryFlow) -> str:
    """Return replacement elementary flow ID from common replacement fields.

    Two of the four are fields the record declares; the other two are spellings
    of the same fact that no writer in this project produces -- `replaced_by_uuid`
    is the SQLite column's name and `dcterms:isReplacedBy` is the CURIE form of
    the IRI-keyed field.  They are read from the passthrough bag, because that
    is where an undeclared key on a stored row lands, and a chain that used to
    follow one of them must keep following it.
    """
    candidates = [
        row.extra.get("replaced_by_uuid"),
        row.is_replaced_by_uuid,
        row.extra.get(DCTERMS_IS_REPLACED_BY_CURIE),
        row.dcterms_is_replaced_by,
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return _strip_urn_uuid(value.strip())
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return _strip_urn_uuid(item.strip())
                if isinstance(item, dict):
                    ident = item.get("@id")
                    if isinstance(ident, str) and ident.strip():
                        return _strip_urn_uuid(ident.strip())
    return ""

def _resolve_active_prepared_target(
    target_uuid: str,
    *,
    all_by_elem_id: dict[str, ElementaryFlow],
    active_by_elem_id: dict[str, ElementaryFlow],
) -> tuple[str, ElementaryFlow | None, list[str], str]:
    """Resolve prepared target to active elementary flow, following replacement chains."""
    start = str(target_uuid or "").strip()
    if not start:
        return "", None, [], "empty-target"
    visited: list[str] = []
    current = start
    while current:
        if current in visited:
            return "", None, visited + [current], "replacement-cycle"
        visited.append(current)
        active_row = active_by_elem_id.get(current)
        if active_row is not None:
            if len(visited) == 1:
                return current, active_row, visited, "direct-active-target"
            return current, active_row, visited, "redirected-from-deprecated-target"
        raw_row = all_by_elem_id.get(current)
        if raw_row is None:
            return "", None, visited, "missing-target-row"
        replacement = _extract_replacement_elementary_id(raw_row)
        if not replacement:
            return "", None, visited, "deprecated-target-without-replacement"
        current = replacement
    return "", None, visited, "unresolved-target"

def _pick_expected_context_target(
    *,
    candidates: list[ElementaryFlow],
    source_unit: str,
) -> tuple[str, ElementaryFlow | None]:
    source_unit_norm = _normalize_text(source_unit) if source_unit else ""
    if not candidates:
        return "", None
    if source_unit_norm:
        for row in candidates:
            unit = row.unit
            if isinstance(unit, str) and _normalize_text(unit) == source_unit_norm:
                elem_id = row.elementary_flow_id.strip()
                if elem_id:
                    return elem_id, row
    candidates_sorted = sorted(
        candidates,
        key=lambda r: (r.elementary_flow_id, r.unit or ""),
    )
    chosen = candidates_sorted[0]
    elem_id = chosen.elementary_flow_id.strip()
    if elem_id:
        return elem_id, chosen
    return "", None

def find_prepared_context_inconsistencies(
    *,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> list[PreparedContextInconsistency]:
    """Prepared matches whose target sits in a context the source row did not expect.

    A prepared decision names a target flow; the source row's own context maps,
    through the context registry, to the consensus context that row belongs in.
    When the two disagree the decision still stands -- it is a human judgement --
    but it is reported, because the pair is exactly what a curator has to look at
    again.

    Rows whose source context maps to no consensus IRI are skipped: there is no
    expectation to contradict.  The report also carries whether the target's flow
    object already has a flow in the expected context, since that is what makes
    the decision cheap to correct.
    """
    inconsistencies: list[PreparedContextInconsistency] = []
    for row in accumulator.prepared_matches:
        source_context = row.source_context if isinstance(row.source_context, list) else []
        expected_iri = indexes.context_expectations.resolve(
            row.source_uuid, source_context, row.source_name
        )

        target_elem_id = row.target_elementary_flow_id or ""
        target_row = (
            accumulator.by_elem_id.get(target_elem_id) if target_elem_id else None
        )
        actual_iri = target_row.context_iri.strip() if target_row is not None else ""
        if expected_iri and actual_iri and expected_iri == actual_iri:
            continue
        if not expected_iri:
            continue

        expected_context = indexes.consensus_context_strings.get(expected_iri, [])
        actual_context = (
            context_display_parts(target_row.context) if target_row is not None else []
        )
        target_flow_object_id = row.target_flow_object_id or ""
        expected_context_elementary_ids: list[str] = []
        if expected_iri and target_flow_object_id:
            for elem in accumulator.elementary_by_object.get(target_flow_object_id, []):
                if elem.context_iri.strip() != expected_iri:
                    continue
                if elem_id := elem.elementary_flow_id.strip():
                    expected_context_elementary_ids.append(elem_id)
        expected_context_elementary_ids = sorted(set(expected_context_elementary_ids))
        inconsistencies.append(PreparedContextInconsistency(
            source_uuid=row.source_uuid,
            source_name=row.source_name,
            source_context=source_context,
            expected_context_iri=expected_iri,
            expected_context=expected_context,
            actual_context_iri=actual_iri,
            actual_context=actual_context,
            target_elementary_flow_id=target_elem_id,
            prepared_target_elementary_flow_id=(
                row.prepared_target_elementary_flow_id or target_elem_id
            ),
            target_flow_object_id=target_flow_object_id,
            target_name=row.target_name,
            prepared_context_decision=row.prepared_context_decision or "mapped",
            expected_context_elementary_present=bool(expected_context_elementary_ids),
            expected_context_elementary_count=len(expected_context_elementary_ids),
            expected_context_elementary_ids=expected_context_elementary_ids,
            provenance=row.provenance,
            reason="expected_context_iri_mismatch",
        ))

    inconsistencies.sort(key=lambda x: (x.source_name.lower(), x.source_uuid))
    return inconsistencies
