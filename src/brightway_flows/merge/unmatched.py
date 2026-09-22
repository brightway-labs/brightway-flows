"""What the report says about a row the merge could not place.

An unmatched row is a question put to a curator, and the answer is only cheap if
the row arrives with the evidence attached: which flow objects its identifiers
and labels do reach, whether PubChem or ChEBI agrees that its CAS names the
substance it is called, and which consensus context its own context maps to.
Deriving that is what this module does, once the merge has finished placing
everything it could.

The rows are partitioned by whether anything at all was reachable.  A row with
candidates matched too much -- several flow objects, no way to choose -- and a
row without them names a substance the list may simply not have; those are
different questions, and the report asks them separately.
"""

from __future__ import annotations

from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.merge.contexts import _normalize_text
from brightway_flows.merge.matching import (
    _harmonised_context_details_for_unmatched_row,
    _probe_flow_object_matches,
    _source_labels,
)
from brightway_flows.merge.report import EnrichedUnmatchedRow, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes


def enrich_unmatched_rows(
    *,
    unmatched: list[UnmatchedRow],
    source_flow_by_uuid: dict[str, Flow],
    external_names_by_cas: dict[str, dict[str, Any]],
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> tuple[list[EnrichedUnmatchedRow], list[EnrichedUnmatchedRow]]:
    """Return the still-unmatched rows, enriched and split by whether they have
    flow object candidates.

    Rows are keyed by source uuid first, so a row reported twice is enriched
    once.  A row with no uuid is dropped: it cannot be looked up again, which is
    what a review needs it for.
    """
    unmatched_by_uuid = {row.source_uuid: row for row in unmatched if row.source_uuid}
    with_flow_object_candidates: list[EnrichedUnmatchedRow] = []
    without_flow_object_candidates: list[EnrichedUnmatchedRow] = []
    for source_uuid, row in unmatched_by_uuid.items():
        source_flow = source_flow_by_uuid.get(source_uuid)
        synonyms = source_flow.provided.synonyms if source_flow else []
        probe = _probe_flow_object_matches(
            # The same labels the match attempt used, so the report explains the
            # attempt rather than describing a different one.
            source_labels=_source_labels(source_flow) if source_flow else [row.source_name],
            source_cas=row.source_cas,
            source_ec=row.source_ec,
            cas_index=indexes.cas_index,
            ec_index=indexes.ec_index,
            label_index=indexes.label_index,
            flow_object_label_by_id=indexes.flow_object_label_by_id,
        )
        enriched = row.to_dict()
        enriched.update(probe)
        source_name = str(enriched.get("source_name") or "")
        source_cas = str(enriched.get("source_cas") or "").strip()
        source_terms_norm = {
            _normalize_text(source_name),
            *(_normalize_text(s) for s in synonyms if isinstance(s, str) and s.strip()),
        }
        source_terms_norm = {x for x in source_terms_norm if x}
        external = external_names_by_cas.get(source_cas, {}) if source_cas else {}
        normalized_external_names = external.get("normalized_names", [])
        if isinstance(normalized_external_names, list) and source_terms_norm:
            cas_name_match = any(
                isinstance(name, str) and name in source_terms_norm
                for name in normalized_external_names
            )
        else:
            cas_name_match = False
        matched_external_rows: list[dict[str, str]] = []
        for item in external.get("name_rows", []) if isinstance(external.get("name_rows"), list) else []:
            if not isinstance(item, dict):
                continue
            ext_name = str(item.get("name") or "").strip()
            ext_source = str(item.get("source") or "").strip()
            if _normalize_text(ext_name) in source_terms_norm and ext_name and ext_source:
                matched_external_rows.append({"name": ext_name, "source": ext_source})
        seen_pairs: set[tuple[str, str]] = set()
        unique_matched: list[dict[str, str]] = []
        for item in matched_external_rows:
            key = (item["name"], item["source"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            unique_matched.append(item)
        enriched["cas_name_agrees_pubchem_or_chebi"] = (
            bool(cas_name_match) if source_cas else None
        )
        enriched["cas_name_agreeing_records"] = unique_matched
        enriched["cas_name_agreeing_sources"] = sorted({item["source"] for item in unique_matched})
        enriched["source_cas_known_flow_object"] = (
            bool(indexes.cas_index.get(source_cas)) if source_cas else None
        )
        enriched.update(
            _harmonised_context_details_for_unmatched_row(
                row=enriched,
                context_expectations=indexes.context_expectations,
                consensus_context_strings=indexes.consensus_context_strings,
                elementary_by_object=accumulator.elementary_by_object,
                flow_object_label_by_id=indexes.flow_object_label_by_id,
            )
        )
        if probe["has_flow_object_candidates"]:
            with_flow_object_candidates.append(EnrichedUnmatchedRow.from_dict(enriched))
        else:
            without_flow_object_candidates.append(EnrichedUnmatchedRow.from_dict(enriched))

    with_flow_object_candidates.sort(key=lambda x: (x.source_name.lower(), x.source_uuid))
    without_flow_object_candidates.sort(key=lambda x: (x.source_name.lower(), x.source_uuid))
    return with_flow_object_candidates, without_flow_object_candidates
