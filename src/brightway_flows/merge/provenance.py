"""Provenance and cross-references recorded when a source flow is merged.

Every merge outcome is recorded structurally rather than as free text, per
AGENTS.md: which source flow, by what basis, under which method.
"""

from __future__ import annotations

from brightway_flows.domain.units import unit_iri_for
from typing import Any

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.vocabulary import (
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    QUDT_HAS_UNIT_CURIE,
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    SKOS_PREF_LABEL_CURIE,
    XKOS_CONCEPT_ASSOCIATION_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.sources import SourceList


def _build_match_provenance(
    *,
    source_uuid: str,
    source_name: str,
    source: SourceList,
    mapping_file: str | None,
    merge_method: str,
    merge_basis: str,
    merge_basis_value: str = "",
    selector_reason: str = "",
    algorithm_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    had_primary_source = [
        f"{source.list_name}:{source.list_version}:{source_uuid}",
        source_name,
        # A list nobody has mapped yet has no correspondence table; the empty
        # string keeps the provenance shape rather than putting null in it.
        mapping_file or "",
    ]
    was_derived_from = f"{merge_method}:{merge_basis}"

    if merge_method == "algorithmic_fallback":
        details = algorithm_details or {}
        flow_object_candidates = int(details.get("flow_object_candidate_count", 0) or 0)
        elementary_candidates = int(details.get("elementary_candidate_count", 0) or 0)
        winning_score = details.get("winning_score")
        tie_top = bool(details.get("tie_on_top_score"))
        # The rule the selector says it applied, not a second copy of it written
        # out here.  The copy had already drifted: it never gained the
        # contradiction veto (#85), so every row's provenance described a
        # selector the run had stopped being, and the exact-compartment term
        # (#90) would have drifted from it in the same way.
        score_rule = str(details.get("selector_model") or "")
        basis_detail = f"{merge_basis}:{merge_basis_value}" if merge_basis_value else merge_basis
        had_primary_source.extend([
            "algorithm.lookup_order=cas>ec>label",
            f"algorithm.basis={basis_detail}",
            f"algorithm.flow_object_candidates={flow_object_candidates}",
            f"algorithm.elementary_candidates={elementary_candidates}",
            f"algorithm.selector_reason={selector_reason}",
            f"algorithm.score_rule={score_rule}",
        ])
        if isinstance(winning_score, int):
            had_primary_source.append(f"algorithm.winning_score={winning_score}")
        if tie_top:
            had_primary_source.append("algorithm.tie_on_top_score=true")
        was_derived_from = (
            f"algorithmic_fallback:"
            f"lookup_order(cas>ec>label);"
            f"basis({basis_detail});"
            f"flow_object_candidates({flow_object_candidates});"
            f"elementary_candidates({elementary_candidates});"
            f"selector({selector_reason});"
            f"{score_rule}"
        )

    return Provenance(
        was_generated_by=source.merge_activity,
        was_attributed_to="brightway-flows",
        had_primary_source=had_primary_source,
        was_derived_from=was_derived_from,
    ).to_dict()

def _append_source_ref(
    target_row: ElementaryFlow,
    *,
    source: SourceList,
    source_uuid: str,
    source_name: str,
    source_context: list[str],
    source_unit: str,
    source_cas: str,
    source_ec: str,
    merge_basis: str,
    merge_method: str,
    selector_reason: str,
    mapping_file: str,
    provenance: dict[str, Any],
    merge_details: dict[str, Any] | None = None,
    conversion_factor: float | None = None,
    source_shipped_name: str = "",
) -> None:
    """Record on *target_row* that *source_uuid* of *source* maps to it.

    ``source_flow_name`` is the name the vendor shipped -- ``source_shipped_name``
    where the caller has it -- and not ``source_name``, which is the enriched
    label the merge matched on.  A consumer holding the vendor's inventory has
    the vendor's string and no other, and the schema page promises it verbatim;
    the merged lists published the enriched one for about 5,300 rows before
    #149.  ``source_name`` stays the fallback for a row built without a record.
    """
    source_metadata: dict[str, Any] = {
        "original_context": source_context,
        "unit": source_unit,
        "cas_number": source_cas,
        "ec_number": source_ec,
        "merge_basis": merge_basis,
        "merge_method": merge_method,
        "selector_reason": selector_reason,
        "mapping_file": mapping_file,
        "provenance": provenance,
        "merge_details": merge_details or {},
    }
    # Published if there is one, without asking again whether it is worth
    # publishing: `UnitConversion.holds_between` is where that is decided.
    # See `merge/conversions.py`.
    if conversion_factor is not None:
        source_metadata[QUDT_CONVERSION_MULTIPLIER_CURIE] = conversion_factor
    new_ref = {
        "list_name": source.list_name,
        "list_version": source.list_version,
        "source_flow_uuid": source_uuid,
        "source_flow_name": source_shipped_name or source_name,
        "source_metadata": source_metadata,
    }
    refs = target_row.source_refs
    if not isinstance(refs, list):
        refs = []
        target_row.source_refs = refs
    key = f"{source.list_name}|{source.list_version}|{source_uuid}"
    existing = {
        f"{str(x.get('list_name') or '')}|{str(x.get('list_version') or '')}|{str(x.get('source_flow_uuid') or '')}"
        for x in refs
        if isinstance(x, dict)
    }
    if key not in existing:
        refs.append(new_ref)

def _append_concept_association(
    target_row: ElementaryFlow,
    *,
    source: SourceList,
    source_uuid: str,
    source_name: str,
    source_context: list[str],
    source_unit: str,
    map_type_curie: str,
    provenance: dict[str, Any],
    conversion_factor: float | None = None,
) -> None:
    """Append a concept association to a flow, deduplicating by source IRI."""
    assocs = target_row.concept_associations
    if not isinstance(assocs, list):
        assocs = []
        target_row.concept_associations = assocs
    src_iri = f"{source.flow_iri_prefix}{source_uuid}"
    seen = {
        str(a.get(XKOS_SOURCE_CONCEPT_CURIE, {}).get("@id") or "")
        for a in assocs
        if isinstance(a, dict)
    }
    if src_iri in seen:
        return
    elem_id = target_row.elementary_flow_id
    context_str = " / ".join(str(x) for x in source_context if x)
    src_node: dict[str, Any] = {"@id": src_iri}
    if source_name:
        src_node[SKOS_PREF_LABEL_CURIE] = source_name
    if context_str:
        src_node["context"] = context_str
    if source_unit:
        if unit_iri := unit_iri_for(source_unit):
            src_node[QUDT_HAS_UNIT_CURIE] = {"@id": unit_iri}
    target_iri = f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{elem_id}"
    src_node[map_type_curie] = {"@id": target_iri}
    assoc: dict[str, Any] = {
        "@type": XKOS_CONCEPT_ASSOCIATION_CURIE,
        XKOS_SOURCE_CONCEPT_CURIE: src_node,
        XKOS_TARGET_CONCEPT_CURIE: {"@id": target_iri},
        "provenance": provenance,
    }
    # Published if there is one, without asking again whether it is worth
    # publishing: `UnitConversion.holds_between` is where that is decided.
    # See `merge/conversions.py`.
    if conversion_factor is not None:
        assoc[QUDT_CONVERSION_MULTIPLIER_CURIE] = conversion_factor
    assocs.append(assoc)
