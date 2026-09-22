"""Finding the consensus flow object and elementary flow for a source row.

Matching is deliberately conservative. A candidate is rejected when the evidence
is ambiguous -- several flow objects reachable by different identifiers, or a
label match against an object that carries CAS numbers the source row does not.
An unmatched row is reported for review; a wrong match is silent.
"""

from __future__ import annotations

import sqlite3

from collections.abc import Collection, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import coerce_alt_labels, flow_label_value
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.filesystem import PUBCHEM_DATA_FILEPATH
from brightway_flows.integrations.chebi import load_chebi_index
from brightway_flows.domain.context_registry import context_display_parts
from brightway_flows.merge.contexts import (
    ContextExpectations,
    _context_taxonomy_distance,
    _normalize_text,
    _same_taxonomy_root,
    context_contradicts,
)
from brightway_flows.merge.prepared import _is_deprecated_elementary
from brightway_flows.merge.prepared_context_decisions import (
    PreparedContextRuling,
)
from brightway_flows.merge.historical_names import load_historical_names
from brightway_flows.merge.report import UnmatchedReason, UnmatchedRow
from brightway_flows.merge.species import load_canonical_identities, rule_governs, parse_species, species_object_label
from brightway_flows.merge.state import (
    CandidateResolution,
    MergeAccumulator,
    MergeIndexes,
    SourceRow,
)
from brightway_flows.pipeline.sqlite import (
    elementary_flow_record,
    merge_object_payload,
)
from brightway_flows.domain.flow_object import (
    FlowObject,
    stable_flow_object_id as _stable_flow_object_id,
)
from brightway_flows.domain.land_flow_classes import land_class_for_source_flow
from brightway_flows.flow_layers.land_hierarchy import land_object_id
from brightway_flows.domain.materials import (
    flow_object_basis_for,
    material_for_source_flow,
)
from brightway_flows.domain.particulate_size import (
    SizeClass,
    UnreadParticleRowError,
    names_a_particle_by_size,
    size_class_for_source_flow,
)
from brightway_flows.qualifiers import detect_origin_qualifier
from brightway_flows.simapro_names import (
    simapro_name_aliases,
    systematic_name_aliases,
)
from brightway_flows.sources import SourceList

logger = structlog.get_logger(__name__)

#: One candidate elementary flow with its score: ``(score, unit_exact,
#: context_overlap, context_penalty, context_iri_exact, row)``.  Sorted on the
#: score alone; the four components after it are carried so the report can say
#: what the score was made of.
ScoredCandidate = tuple[int, bool, int, int, bool, ElementaryFlow]

def _classification_values(obj: FlowObject, predicate: str) -> list[str]:
    """The registry numbers *obj* carries under *predicate*.

    `classifications` is a declared field, so it is read by attribute.  Its
    *value* stays a dict guard: a classification block is an open map keyed by
    predicate IRI, and what sits under one is a payload rather than a record.
    """
    classifications = obj.classifications
    if not isinstance(classifications, dict):
        return []
    row = classifications.get(predicate)
    if not isinstance(row, dict):
        return []
    values = row.get("@value")
    if not isinstance(values, list):
        return []
    return [str(x).strip() for x in values if isinstance(x, str) and str(x).strip()]

def _load_working_set(db_path: Path) -> tuple[list[FlowObject], list[ElementaryFlow]]:
    """The flow objects and elementary flows the merge works against.

    Read from the database the build just wrote, rather than from
    `flow-objects.json` and `elementary-flows.json`. Those files existed only to
    carry data from one stage of a single run to the next, which is what a
    single command with one database does instead.

    The flow objects are `FlowObject` records, built here at the read boundary
    rather than left as the payload they were stored as.  `flow_object_json` is
    written by the transform as `FlowObject.to_dict()`, so `from_dict` is its
    exact inverse: checked against all 8,021 objects of the 2026-08-14 build,
    every one round-trips with the same keys, the same values and the same key
    order.

    The elementary flows are `ElementaryFlow` records, built here for the same
    reason and checked the same way (#93).  Over all 95,190 rows of the
    2026-08-14 build, `ElementaryFlow.from_dict(projected).to_dict()` returns
    the same keys with the same values -- but **not** in the same order, on
    93,993 of them.  That is the record putting the projection's output in its
    own declaration order: `elementary_flow_record` appends
    `elementary_flow_id`, `general_comment` and `cas_match_labels` at the end
    when the stored flow does not carry them, which is what makes nine distinct
    key orders out of one set of keys.  The record makes four, and it is the
    order the merge's own created flows already came out in, because those went
    through `ElementaryFlow` before being stored.

    No published byte moves with it.  The working list is never serialised in
    this order: a created flow reaches `flow_json` through
    `_as_harmonised`, which rebuilds it as a `Flow` and so imposes `Flow`'s
    order, and the selector traces in `merge_outcomes.detail_json` are built
    key by key from the fields they name.  See #93 for the run that shows it.

    What the record is built from is projected from `flow_json` by
    `elementary_flow_record`, rather than read from a second stored payload:
    `elementary_flow_json` said nothing `flow_json` did not -- every key the two
    shared was byte identical in all 94,433 rows -- for 221.3 MiB (#255).

    The projection is fed the *rehydrated* flow, because `flow_json` no longer
    carries the substance body; `flow_object_payloads` holds it once per object
    (#253).

    Deprecated flows are included: the merge decides for itself what to skip,
    and needs the deprecated ones to follow a replacement chain.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"No consensus database at {db_path}. Run `brightway-flows build` first."
        )
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        flow_objects = [
            FlowObject.from_dict(orjson.loads(row[0]))
            for row in connection.execute(
                "SELECT flow_object_json FROM flow_objects "
                "WHERE flow_object_json IS NOT NULL ORDER BY rowid"
            )
        ]
        elementary = [
            ElementaryFlow.from_dict(
                elementary_flow_record(
                    merge_object_payload(orjson.loads(row[0]), row[1])
                )
            )
            for row in connection.execute(
                "SELECT ef.flow_json, p.payload_json FROM elementary_flows ef "
                "LEFT JOIN flow_object_payloads p "
                "ON p.flow_object_id = ef.flow_object_id "
                "WHERE ef.flow_json IS NOT NULL ORDER BY ef.rowid"
            )
        ]
    finally:
        connection.close()
    return flow_objects, elementary

def _build_indexes(
    flow_objects: list[FlowObject],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    cas_to_object_ids: dict[str, set[str]] = {}
    ec_to_object_ids: dict[str, set[str]] = {}
    label_to_object_ids: dict[str, set[str]] = {}
    pref_label_to_object_ids: dict[str, set[str]] = {}

    for obj in flow_objects:
        object_id = obj.flow_object_id
        if not object_id:
            continue

        for cas in _classification_values(obj, CHEMINF_CAS_REGISTRY_NUMBER):
            cas_to_object_ids.setdefault(cas, set()).add(object_id)

        for ec in _classification_values(obj, CHEMINF_EC_NUMBER):
            ec_to_object_ids.setdefault(ec, set()).add(object_id)

        pref = flow_label_value(obj)
        if isinstance(pref, str) and pref.strip():
            norm = _normalize_text(pref)
            label_to_object_ids.setdefault(norm, set()).add(object_id)
            pref_label_to_object_ids.setdefault(norm, set()).add(object_id)

        for item in coerce_alt_labels(obj.altLabel):
            if isinstance(item.value, str) and item.value.strip():
                label_to_object_ids.setdefault(_normalize_text(item.value), set()).add(object_id)

    return cas_to_object_ids, ec_to_object_ids, label_to_object_ids, pref_label_to_object_ids

def _source_labels(flow: Flow) -> list[str]:
    """Every name this source row is known by, best first, deduplicated.

    Matching used to look up one name and its synonyms.  That is one label's
    worth of evidence dressed up as several, and it breaks the moment the label
    changes: enrichment renamed `MCPA` to `(4-Chloro-2-methylphenoxy)acetic
    acid`, and the row stopped hitting the label index under either name.

    A row is known by all of them at once -- the label enrichment settled on,
    the name the source list shipped, its synonyms, and the alternative labels
    enrichment found -- so all of them are looked up.  Order is preference, and
    is what `basis_value` reports when a match is traced back.
    """
    ordered = [
        flow_label_value(flow),
        *flow.provided.labels(),
        *(item.value for item in coerce_alt_labels(flow.altLabel)),
    ]
    seen: set[str] = set()
    labels: list[str] = []
    for value in ordered:
        if not isinstance(value, str) or not value.strip():
            continue
        key = _normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        labels.append(value.strip())
    return labels

def build_merge_indexes(
    flow_objects: list[FlowObject],
    *,
    context_expectations: ContextExpectations,
    consensus_context_strings: dict[str, list[str]],
    prepared_context_decisions: Mapping[tuple[str, str], PreparedContextRuling],
    mapping_file: str | None,
    source: SourceList,
) -> MergeIndexes:
    """Every lookup the row logic reads, assembled from *flow_objects*.

    `_build_indexes` above derives the identifier and label indexes; the
    qualifier index, the two by-id views and the CAS-carrying subset are derived
    here beside it.  The remaining arguments are lookups the merge loaded
    elsewhere -- contexts, prepared decisions, the list being merged -- which
    this only carries onto the frozen record.
    """
    cas_index, ec_index, label_index, pref_label_index = _build_indexes(flow_objects)
    # Pre-compute the set of flow object IDs that carry at least one CAS number.
    # Used to restrict no-source-CAS label matches to genuinely CAS-less flow
    # objects, preventing trade-name false positives (e.g. "Granite" matching
    # Penoxsulam) while still allowing unspecified radioactive groups, etc.
    flow_objects_with_cas: set[str] = set().union(*cas_index.values()) if cas_index else set()
    # Index of origin_qualifier → set of flow object IDs.  Used to narrow CAS
    # candidates when multiple flow objects share a CAS (e.g. all water variants
    # share 7732-18-5).  Qualifier matching is tried before label matching.
    qualifier_index: dict[str, set[str]] = {}
    for _fo in flow_objects:
        if _fo.origin_qualifier and _fo.flow_object_id:
            qualifier_index.setdefault(_fo.origin_qualifier, set()).add(
                _fo.flow_object_id
            )
    # `_load_working_set` builds these as records, so an object with no
    # identifier is the only case to skip -- the three isinstance guards that
    # used to be here were asking whether a payload had the shape of a record,
    # which is a question the record type now answers.
    flow_object_label_by_id: dict[str, str] = {
        obj.flow_object_id: flow_label_value(obj)
        for obj in flow_objects
        if obj.flow_object_id
    }
    flow_objects_by_id: dict[str, FlowObject] = {
        obj.flow_object_id: obj
        for obj in flow_objects
        if obj.flow_object_id
    }
    return MergeIndexes(
        flow_objects_by_id=flow_objects_by_id,
        flow_object_label_by_id=flow_object_label_by_id,
        cas_index=cas_index,
        ec_index=ec_index,
        label_index=label_index,
        pref_label_index=pref_label_index,
        qualifier_index=qualifier_index,
        flow_objects_with_cas=flow_objects_with_cas,
        context_expectations=context_expectations,
        consensus_context_strings=consensus_context_strings,
        prepared_context_decisions=prepared_context_decisions,
        mapping_file=mapping_file,
        source=source,
        # Loaded only where the element/ion rule governs -- ecoinvent with no
        # prepared table -- so every list merged today carries an empty mapping
        # and the rule's machinery is inert until the table is retired.
        canonical_identities=(
            load_canonical_identities() if rule_governs(source) else {}
        ),
        # Loaded for every list: each entry is a string the vendor itself
        # shipped for a known flow, and the branch that reads it is reached
        # only once everything the row shipped has failed.
        historical_names=load_historical_names(),
    )

def build_merge_accumulator(elementary: list[ElementaryFlow]) -> MergeAccumulator:
    """The collections the merge writes to, seeded with the flows it loaded.

    `merged_elementary` is a deep copy, and `elementary_by_object` deliberately
    indexes the rows that were passed in rather than the copies: matching reads
    its candidates from the index and writes to the copies, so a candidate list
    does not grow the source refs of the flow that is being matched against it
    while the match is still being decided.

    Deprecated flows are left out of `elementary_by_object` and `by_elem_id` --
    they are neither candidates nor match targets -- but stay in
    `all_by_elem_id`, which is how a prepared decision follows a replacement
    chain to the flow that supersedes its target.

    `preexisting_flow_ids` is taken here because here is the only place that
    knows it: *elementary* is the database as it stood before this pass, and
    once the pass starts adding to `merged_elementary` the two are no longer
    distinguishable by inspection.
    """
    elementary_by_object: dict[str, list[ElementaryFlow]] = {}
    for row in elementary:
        if _is_deprecated_elementary(row):
            continue
        if row.flow_object_id:
            elementary_by_object.setdefault(row.flow_object_id, []).append(row)

    merged_elementary = deepcopy(elementary)
    return MergeAccumulator(
        merged_elementary=merged_elementary,
        all_by_elem_id={
            row.elementary_flow_id: row for row in merged_elementary
        },
        by_elem_id={
            row.elementary_flow_id: row
            for row in merged_elementary
            if not _is_deprecated_elementary(row)
        },
        elementary_by_object=elementary_by_object,
        preexisting_flow_ids=frozenset(
            row.elementary_flow_id
            for row in elementary
            if row.elementary_flow_id
        ),
    )

def _probe_flow_object_matches(
    *,
    source_labels: list[str],
    source_cas: str,
    source_ec: str,
    cas_index: dict[str, set[str]],
    ec_index: dict[str, set[str]],
    label_index: dict[str, set[str]],
    flow_object_label_by_id: dict[str, str],
) -> dict[str, Any]:
    candidates: dict[str, set[str]] = {"cas": set(), "ec": set(), "label": set()}
    if source_cas:
        candidates["cas"] = set(cas_index.get(source_cas, set()))
    if source_ec:
        candidates["ec"] = set(ec_index.get(source_ec, set()))
    labels_used: list[str] = []
    for label in source_labels:
        label_norm = _normalize_text(label)
        if not label_norm:
            continue
        hits = label_index.get(label_norm, set())
        if hits:
            labels_used.append(label)
            candidates["label"].update(hits)

    union = set().union(candidates["cas"], candidates["ec"], candidates["label"])
    if candidates["cas"]:
        preferred_basis = "cas"
    elif candidates["ec"]:
        preferred_basis = "ec"
    elif candidates["label"]:
        preferred_basis = "label"
    else:
        preferred_basis = ""

    return {
        "has_flow_object_candidates": bool(union),
        "preferred_basis": preferred_basis,
        "candidate_flow_object_ids": sorted(union),
        "candidate_flow_objects": [
            {
                "flow_object_id": object_id,
                "name": flow_object_label_by_id.get(object_id, ""),
                "basis_hits": sorted(
                    basis
                    for basis in ("cas", "ec", "label")
                    if object_id in candidates[basis]
                ),
            }
            for object_id in sorted(union)
        ],
        "basis_counts": {
            "cas": len(candidates["cas"]),
            "ec": len(candidates["ec"]),
            "label": len(candidates["label"]),
        },
        "labels_used": sorted(set(labels_used)),
    }

def _load_external_names_by_cas() -> dict[str, dict[str, Any]]:
    """Build CAS -> names index from ChEBI and PubChem caches."""
    by_cas: dict[str, dict[str, Any]] = {}

    def _add(cas: str, *, name: str, source: str) -> None:
        cas_clean = str(cas or "").strip()
        name_clean = str(name or "").strip()
        if not cas_clean or not name_clean:
            return
        row = by_cas.setdefault(cas_clean, {"normalized_names": set(), "name_rows": []})
        nname = _normalize_text(name_clean)
        if not nname:
            return
        row["normalized_names"].add(nname)
        row["name_rows"].append({"name": name_clean, "source": source})

    try:
        chebi = load_chebi_index()
        records = chebi.get("records", {}) if isinstance(chebi, dict) else {}
        by_cas_index = chebi.get("by_cas", {}) if isinstance(chebi, dict) else {}
        if isinstance(records, dict) and isinstance(by_cas_index, dict):
            for cas, chebi_ids in by_cas_index.items():
                if not isinstance(cas, str) or not isinstance(chebi_ids, list):
                    continue
                for chebi_id in chebi_ids:
                    rec = records.get(chebi_id, {})
                    if not isinstance(rec, dict):
                        continue
                    label = rec.get("label")
                    if isinstance(label, str):
                        _add(cas, name=label, source="chebi")
                    synonyms = rec.get("synonyms")
                    if isinstance(synonyms, list):
                        for syn in synonyms:
                            if isinstance(syn, str):
                                _add(cas, name=syn, source="chebi")
    except Exception:
        pass

    if PUBCHEM_DATA_FILEPATH.exists():
        try:
            payload = orjson.loads(PUBCHEM_DATA_FILEPATH.read_bytes())
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            cid_to_names: dict[int, set[str]] = {}
            by_name = payload.get("by_name", {})
            if isinstance(by_name, dict):
                for raw_name, compounds in by_name.items():
                    if not isinstance(raw_name, str) or not isinstance(compounds, list):
                        continue
                    for compound in compounds:
                        if not isinstance(compound, dict):
                            continue
                        cid = compound.get("cid")
                        if isinstance(cid, int):
                            cid_to_names.setdefault(cid, set()).add(raw_name)
            identifiers = payload.get("identifiers", {})
            if isinstance(identifiers, dict):
                for cid_str, ident in identifiers.items():
                    if not isinstance(ident, dict):
                        continue
                    try:
                        cid = int(str(cid_str).strip())
                    except Exception:
                        continue
                    title_rows = ident.get("RecordTitle")
                    if isinstance(title_rows, list):
                        for item in title_rows:
                            if not isinstance(item, dict):
                                continue
                            value = item.get("value")
                            if isinstance(value, str) and value.strip():
                                cid_to_names.setdefault(cid, set()).add(value.strip())

            by_cas_rows = payload.get("by_cas", {})
            if isinstance(by_cas_rows, dict):
                for cas, compounds in by_cas_rows.items():
                    if not isinstance(cas, str) or not isinstance(compounds, list):
                        continue
                    for compound in compounds:
                        if not isinstance(compound, dict):
                            continue
                        cid = compound.get("cid")
                        if isinstance(cid, int):
                            for name in cid_to_names.get(cid, set()):
                                _add(cas, name=name, source="pubchem")

    for cas, row in by_cas.items():
        name_rows = row.get("name_rows", [])
        if isinstance(name_rows, list):
            dedup: dict[tuple[str, str], dict[str, str]] = {}
            for item in name_rows:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                source = str(item.get("source") or "").strip()
                if not name or not source:
                    continue
                dedup[(name, source)] = {"name": name, "source": source}
            row["name_rows"] = sorted(
                dedup.values(),
                # The raw name is part of the key, not just its normalised form.
                # Case variants of one name ("HFC-134a" / "hfc-134a") normalise
                # identically, so a case-insensitive key leaves them tied, and a
                # stable sort then preserves insertion order -- which comes from
                # iterating a set, and so varies between processes.  That made
                # the merge report differ run to run for identical inputs.
                key=lambda x: (
                    str(x.get("source") or ""),
                    _normalize_text(str(x.get("name") or "")),
                    str(x.get("name") or ""),
                ),
            )
        normalized_names = row.get("normalized_names")
        if isinstance(normalized_names, set):
            row["normalized_names"] = sorted(normalized_names)
    return by_cas

def _harmonised_context_details_for_unmatched_row(
    *,
    row: dict[str, Any],
    context_expectations: ContextExpectations,
    consensus_context_strings: dict[str, list[str]],
    elementary_by_object: dict[str, list[ElementaryFlow]],
    flow_object_label_by_id: dict[str, str],
) -> dict[str, Any]:
    source_context = row.get("source_context")
    if not isinstance(source_context, list):
        source_context = []
    expected_iri = context_expectations.resolve(
        row.get("source_uuid"), source_context, row.get("source_name")
    )
    expected_context = consensus_context_strings.get(expected_iri, []) if expected_iri else []

    candidate_object_ids = row.get("candidate_flow_object_ids")
    if not isinstance(candidate_object_ids, list):
        candidate_object_ids = []
    candidate_object_ids = [str(x) for x in candidate_object_ids if isinstance(x, str) and x.strip()]

    candidate_elementary: list[ElementaryFlow] = []
    for object_id in candidate_object_ids:
        candidate_elementary.extend(elementary_by_object.get(object_id, []))

    exact_count = 0
    for elem in candidate_elementary:
        if expected_iri and elem.context_iri.strip() == expected_iri:
            exact_count += 1

    closest_suggestions: list[dict[str, Any]] = []
    if expected_iri and exact_count == 0 and candidate_elementary:
        scored: list[tuple[int, ElementaryFlow]] = []
        for elem in candidate_elementary:
            elem_iri = elem.context_iri.strip()
            elem_context = consensus_context_strings.get(elem_iri) or context_display_parts(elem.context)
            if not _same_taxonomy_root(expected_context, elem_context):
                continue
            distance = _context_taxonomy_distance(expected_context, elem_context)
            scored.append((distance, elem))
        scored.sort(
            key=lambda x: (
                int(x[0]),
                x[1].flow_object_id.lower(),
                x[1].elementary_flow_id.lower(),
            )
        )
        for distance, elem in scored[:8]:
            foid = elem.flow_object_id
            elem_iri = elem.context_iri.strip()
            elem_context = consensus_context_strings.get(elem_iri) or context_display_parts(elem.context)
            closest_suggestions.append({
                "distance": int(distance),
                "elementary_flow_id": elem.elementary_flow_id,
                "flow_object_id": foid,
                "flow_object_name": flow_object_label_by_id.get(foid, ""),
                "context_iri": elem_iri,
                "context": elem_context,
                "unit": elem.unit or "",
            })

    return {
        "harmonised_source_context_iri": expected_iri or "",
        "harmonised_source_context": expected_context,
        "exact_context_elementary_flow_count": exact_count,
        "closest_context_candidates": closest_suggestions,
    }

def _select_elementary_flow(
    candidates: list[ElementaryFlow],
    *,
    source_context: list[str],
    source_unit: str,
    source_context_iri: str = "",
) -> tuple[ElementaryFlow | None, str, dict[str, Any]]:
    """Pick the elementary flow a source row belongs to, from *candidates*.

    Nothing here is specific to any list: the two arguments were spelled
    `ecoinvent_context` and `ecoinvent_unit` until #242, while the call site
    already passed values it called `selector_source_context` and `source_unit`.
    """
    source_dim = _normalize_text(source_context[0]) if len(source_context) >= 1 else ""
    source_media = _normalize_text(source_context[1]) if len(source_context) >= 2 else ""

    eligible_candidates: list[ElementaryFlow] = []
    filtered_out_context_mismatch = 0
    for row in candidates:
        target_ctx = context_display_parts(row.context)
        target_dim = _normalize_text(target_ctx[0]) if len(target_ctx) >= 1 else ""
        target_media = _normalize_text(target_ctx[1]) if len(target_ctx) >= 2 else ""
        # Algorithmic matching must never cross dimension or media boundaries.
        if source_dim and source_dim != target_dim:
            filtered_out_context_mismatch += 1
            continue
        if source_media and source_media != target_media:
            filtered_out_context_mismatch += 1
            continue
        eligible_candidates.append(row)

    details: dict[str, Any] = {
        "flow_object_candidate_count": 1,
        "elementary_candidate_count": len(candidates),
        "eligible_candidate_count": len(eligible_candidates),
        "filtered_out_context_mismatch_count": filtered_out_context_mismatch,
        "required_dimension": source_context[0] if len(source_context) >= 1 else "",
        "required_media": source_context[1] if len(source_context) >= 2 else "",
        "selector_model": "exact-iri-shortcircuit;up-tree-filter;score=(2*unit_exact)+context_overlap-context_penalty+context_iri_exact;contradiction-veto",
        "top_candidates": [],
        "scored_candidates": [],
        "winning_score": None,
        "tie_on_top_score": False,
    }
    if not candidates:
        return None, UnmatchedReason.NO_ELEMENTARY_CANDIDATES, details
    if not eligible_candidates:
        return None, UnmatchedReason.NO_CANDIDATES_SAME_DIMENSION_MEDIA, details

    # Short-circuit: exact context IRI match takes priority over scoring.
    if source_context_iri:
        exact_iri = [
            c for c in eligible_candidates
            if c.context_iri.strip() == source_context_iri
        ]
        if len(exact_iri) == 1:
            only = exact_iri[0]
            details["top_candidates"] = [{
                "elementary_flow_id": only.elementary_flow_id,
                "score": 0,
                "unit_exact": False,
                "context_overlap": 0,
                "context_penalty": 0,
                "context_iri_exact": True,
                "unit": only.unit or "",
                "context": context_display_parts(only.context),
                "context_iri": only.context_iri,
            }]
            details["scored_candidates"] = list(details["top_candidates"])
            return only, "exact-context-iri-match", details

    unit_norm = _normalize_text(source_unit) if source_unit else ""
    source_ctx = {_normalize_text(x) for x in source_context if x.strip()}

    def score_all(rows: list[ElementaryFlow]) -> list[ScoredCandidate]:
        out: list[ScoredCandidate] = []
        for row in rows:
            score = 0
            target_unit = row.unit
            unit_exact = (
                bool(unit_norm)
                and isinstance(target_unit, str)
                and _normalize_text(target_unit) == unit_norm
            )
            if unit_exact:
                score += 2
            target_ctx = {_normalize_text(x) for x in context_display_parts(row.context)}
            overlap = 0
            penalty = 0
            if source_ctx and target_ctx:
                overlap = len(source_ctx & target_ctx)
                penalty = len(target_ctx - source_ctx)
                score += overlap - penalty
            # The two counts above compare words, and count how deep two
            # compartments agree rather than whether they are the same one.  A
            # flow in air with the height left unstated -- which is the
            # compartment a row in air, unspecified names -- is written
            # `Environmental / Air / Unknown` while the row arrives as
            # `Environmental / Air`, so it shares two words with the row and
            # differs by one, exactly like `Air / Long-term` and `Air /
            # Aircraft cruise height`, which are other places (#90).  The IRI
            # is the identity those words describe, so this is the term that
            # asks whether the candidate *is* the compartment the row named.
            #
            # Worth one point, and deliberately less than the unit's two: EF
            # holds water vapour in air, unspecified twice, once in kilograms
            # and once in cubic metres, and it is the unit that has to tell a
            # row in kilograms which of the two it means (§8 of
            # `water-taxonomy-overview.md`).  A row whose compartment the list
            # does not hold gives this term to nobody, so it leaves the nearest
            # neighbour to be found as before.
            context_iri_exact = bool(source_context_iri) and (
                row.context_iri.strip() == source_context_iri
            )
            if context_iri_exact:
                score += 1
            out.append((score, unit_exact, overlap, penalty, context_iri_exact, row))
        out.sort(key=lambda x: x[0], reverse=True)
        return out

    def pick(scored: list[ScoredCandidate]) -> tuple[ElementaryFlow | None, str]:
        """The winner of a scored list, or why there is none."""
        if not scored:
            return None, UnmatchedReason.UNABLE_TO_SCORE_CANDIDATES
        if scored[0][0] <= 0:
            return None, UnmatchedReason.NO_CONTEXT_OR_UNIT_SIGNAL
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None, UnmatchedReason.TIED_ELEMENTARY_CANDIDATES
        return scored[0][5], "best-score"

    # Only score candidates that are not more specific than the source context
    # (go "up" the tree only — no extra tokens beyond what the source specifies).
    up_tree = [
        row for row in eligible_candidates
        if not ({_normalize_text(x) for x in context_display_parts(row.context)} - source_ctx)
    ]
    scoring_candidates = up_tree if up_tree else eligible_candidates

    scored = score_all(scoring_candidates)
    selected, reason = pick(scored)

    # A row is never published in a place that contradicts the place it named
    # (#85).  Coarsening is fine and is most of what this function does: a
    # release to a lake published as a release to water, unspecified, loses
    # detail and says nothing false, which is the only thing to do when the
    # base list has no lake.  Landing it on groundwater is a different act.
    # Groundwater is not a vaguer way of saying lake, and the score cannot tell
    # the two apart, because all it counts is how many words two contexts
    # share: for BAFU's lead-210 the groundwater flow scored above every honest
    # alternative on the strength of "an environmental release to water" plus a
    # matching unit.
    #
    # So the choice is re-made among the candidates that do not contradict the
    # row.  Re-made rather than pre-filtered: dropping them before scoring would
    # also break the ties that today send a row to a flow of its own, which is
    # the right outcome and not this issue's to change -- 113 rows on the
    # 2026-08-13 build, most of them ecoinvent's forestry soil.
    if selected is not None and context_contradicts(
        source_context_iri, selected.context_iri.strip()
    ):
        details["rejected_contradicting_context_iri"] = selected.context_iri.strip()
        honest = [
            row
            for row in scoring_candidates
            if not context_contradicts(source_context_iri, row.context_iri.strip())
        ]
        details["non_contradicting_candidate_count"] = len(honest)
        scored = score_all(honest)
        selected, reason = pick(scored)
        if selected is None:
            # Not "nothing scored" or "two tied": everything that fit this row
            # disagreed with it.  Its own reason, and a creatable one -- the row
            # gets a flow in the context it named rather than the nearest flow
            # that denies it.
            reason = UnmatchedReason.CONTEXT_CONTRADICTION

    # The row named a compartment this list holds, and no flow of its substance
    # is in it.  Coarsening onto the nearest one that exists says nothing false
    # -- a release to a lake published as a release to water, unspecified, only
    # loses detail -- and #85 left it as the right answer for exactly that
    # reason.  What it also does is make the answer depend on *when* the row was
    # asked, because the set of flows to be nearest to grows as the merge runs.
    #
    # ecoinvent's `Aerosols, radioactive, unspecified` is the demonstration.  The
    # identical row, in `air / urban air close to ground` in both releases, was
    # matched onto `Air → Unknown` during the 3.12 pass, where that flow won 3 to
    # 2; by the 3.8 pass a third flow of the substance existed, two candidates
    # tied at 3, and the tie minted a flow in the row's own compartment.  One
    # intervention, two consensus flows, and the difference is the order.
    #
    # So the row gets its own compartment whenever that compartment is one this
    # list knows -- which makes the answer a property of the row.  Every one of
    # the twelve rows this reached on the 2026-08-18 build was being coarsened
    # onto a compartment that says the compartment is unknown, and two of them,
    # Thifensulfuron on farm soil and on forest soil, were being coarsened onto
    # the same flow as each other (#112).
    #
    # Guarded on there being no candidate in the row's own compartment rather
    # than on the winner not being in it: where two flows share that compartment
    # the exact-IRI short-circuit above declines to choose, and this must not
    # turn that row into an unmatched one.  A row whose compartment the list does
    # not hold is left alone, because there is no compartment to create it in.
    if (
        selected is not None
        and reason == "best-score"
        and source_context_iri
        and not any(
            row.context_iri.strip() == source_context_iri
            for row in eligible_candidates
        )
    ):
        details["rejected_coarser_context_iri"] = selected.context_iri.strip()
        selected = None
        reason = UnmatchedReason.NO_CANDIDATE_IN_STATED_CONTEXT

    # Built from the list the decision was actually made on, so a report of a
    # vetoed row shows what it chose between and not what it first considered.
    def as_detail(item: ScoredCandidate) -> dict[str, Any]:
        return {
            "elementary_flow_id": item[5].elementary_flow_id,
            "score": int(item[0]),
            "unit_exact": bool(item[1]),
            "context_overlap": int(item[2]),
            "context_penalty": int(item[3]),
            "context_iri_exact": bool(item[4]),
            "unit": item[5].unit or "",
            "context": context_display_parts(item[5].context),
            "context_iri": item[5].context_iri,
        }

    details["top_candidates"] = [as_detail(item) for item in scored[:5]]
    details["scored_candidates"] = [as_detail(item) for item in scored]
    if scored:
        details["winning_score"] = int(scored[0][0])
    details["tie_on_top_score"] = reason == UnmatchedReason.TIED_ELEMENTARY_CANDIDATES
    if selected is None:
        return None, reason, details
    return selected, reason, details


def _record_unmatched_row(
    *, row: SourceRow, accumulator: MergeAccumulator, reason: UnmatchedReason,
    **extra: Any,
) -> None:
    """Report a source row that produced no usable match."""
    accumulator.unmatched.append(UnmatchedRow(
        source_uuid=row.uuid,
        source_name=row.name,
        source_shipped_name=row.shipped_name or None,
        source_context=row.context,
        source_unit=row.unit,
        source_cas=row.cas,
        source_ec=row.ec,
        reason=reason,
        matching_method="algorithm",
        **extra,
    ))


def resolve_flow_object(
    *,
    row: SourceRow,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> CandidateResolution | None:
    """Find the one flow object a source row belongs to.

    Evidence is tried in order of reliability -- CAS, then EC, then labels -- and
    narrowed when a single key reaches several objects. Returns None when no
    candidate is found or when more than one survives; in both cases the row has
    been recorded as unmatched, because a wrong match is silent whereas an
    unmatched row is reviewable.
    """
    candidate_ids: set[str] = set()
    basis = ""
    basis_value = ""
    labels_used: list[str] = []

    land_use = land_class_for_source_flow(indexes.source.source_label, row.uuid)
    if land_use:
        # Exclusive, and before the material for the same reason it is before it
        # in the layering: a curated row says which land class this is, and a
        # land flow has no registry number for a later branch to disagree with.
        #
        # This is what makes a BAFU land flow reach the EF flow it is the same
        # as.  `Occupation, annual crop, non-irrigated, intensive` and EF's
        # `arable, non-irrigated, intensive` decompose to one class, mint one
        # id, and meet -- where before, BAFU's 123 land rows matched nothing at
        # all and every one of them minted a duplicate of a flow EF already
        # published (#66 §1.3).
        target = land_object_id(land_use)
        if target in indexes.flow_objects_by_id:
            return CandidateResolution(
                flow_object_id=target,
                basis="land_class",
                basis_value=land_use.key,
            )
        # Known and not yet built, which is `create it` rather than `choose`.
        # Recorded for the reason the material branch records it: a row that
        # returns without being recorded leaves the merge silent about it.
        _record_unmatched_row(
            row=row, accumulator=accumulator,
            reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
        )
        return None

    material = material_for_source_flow(indexes.source.source_label, row.uuid)
    if material:
        # Exclusive, exactly as in layering, and for the reason the CAS branch
        # below already anticipates: every water variant shares 7732-18-5, so
        # once the materials have their own objects a CAS lookup returns ten
        # candidates and narrows to none.  It cost ecoinvent's `Water, green`
        # its match -- reported `multiple-flow-object-candidates`, matched
        # nothing, and the flow left the list -- because it carries neither an
        # origin qualifier nor a label any object answers to.
        #
        # Not intersected with the CAS candidates: brine carries no CAS at all,
        # so an intersection would drop the one row that needs this most.
        target = _material_flow_object(material)
        if target in indexes.flow_objects_by_id:
            return CandidateResolution(
                flow_object_id=target,
                basis="material",
                basis_value=material,
                material=material,
            )
        # The material is known and its object does not exist yet, which is
        # `create it`, not `choose between ten`.  Falling through to the CAS
        # branch would return every water object, narrow to none, and report
        # `multiple-flow-object-candidates` -- a reason creation deliberately
        # excludes, because it means the row matched too much rather than too
        # little.  The row would then be dropped instead of minting the object
        # the taxonomy already names.  Reported as having no candidate, which is
        # both true and creatable -- and recorded, because a row that returns
        # without being recorded leaves the merge silent about it.
        _record_unmatched_row(
            row=row, accumulator=accumulator,
            reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
        )
        return None

    size_class = size_class_for_source_flow(indexes.source.source_label, row.uuid)
    if size_class is None and names_a_particle_by_size(row.name):
        # A particle row the table has not read stops the merge, the way a
        # land row in a compartment told apart by name that matches no rule
        # does (#52).  Before this it fell through to the label branch,
        # matched nothing, and minted a substance with no window and no
        # factor -- `Particulates, SPM` and Stepwise's `Particulates, < 10
        # um` on the build of 2 September 2026 -- and nobody was told.  The
        # reading is a curator's, written once in
        # `tools/build_particulate_flow_classes.py`; the merge does not guess
        # it, and does not finish without it (#196).
        raise UnreadParticleRowError(
            source=indexes.source.source_label,
            source_uuid=row.uuid,
            name=row.name,
            context=row.context,
        )
    if size_class:
        # Exclusive, exactly as in layering, and the exclusivity is the fix
        # rather than a precaution.  These rows carry no registry number -- not
        # one of the 200 in `particulate-flow-classes.json` does -- so before
        # this branch existed they fell through to the label, and the label is
        # not theirs to trust.  `Particles (PM10)` carries both of ecoinvent's
        # coarse-fraction spellings as alternative labels, left there by the
        # member-name pass after #37's override put those rows in its merge
        # group; BAFU spells its coarse fraction the same way, so four of its
        # rows matched PM10 on the label with `basis_value` reading
        # `Particulates, > 2.5 Um, And < 10um` and nothing recorded anywhere
        # that a decision had been taken.  Meanwhile BAFU's actual PM10 rows
        # matched nothing and minted substances with no factors at all (#153).
        #
        # Looked up by the window, both stop being possible: a row reaches the
        # flow its window names, or it reaches nothing and is reported.
        target = _size_class_flow_object(size_class)
        if target in indexes.flow_objects_by_id:
            return CandidateResolution(
                flow_object_id=target,
                basis="particulate_size_class",
                basis_value=size_class.id,
            )
        # Known and not yet built, which is `create it` rather than `choose`.
        # Recorded for the reason the material branch records it: a row that
        # returns without being recorded leaves the merge silent about it.
        _record_unmatched_row(
            row=row, accumulator=accumulator,
            reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
        )
        return None

    if row.cas:
        candidate_ids = set(indexes.cas_index.get(row.cas, set()))
        basis, basis_value = "cas", row.cas
        # Several flow objects can share a CAS -- every water variant shares
        # 7732-18-5 -- so narrow by origin qualifier, then by label.
        if len(candidate_ids) > 1:
            # Every label, not just the published one: "Water, well, in ground"
            # carries the qualifier and the label enrichment settled on may not.
            qualifier = next(
                (q for q in map(detect_origin_qualifier, row.labels) if q), ""
            )
            if qualifier:
                carriers = indexes.qualifier_index.get(qualifier, set())
                narrowed = candidate_ids & carriers
                if narrowed:
                    candidate_ids = narrowed
                    basis = "cas+qualifier"
                elif not carriers:
                    # The qualifier is one this vocabulary detects and *no flow
                    # object in the list carries*.  Every candidate the CAS
                    # found has been ruled out by the row's own name, so there
                    # is nothing here to choose between -- the same shape as the
                    # material branch above, and reported the same way.
                    #
                    # Falling through would publish the row as a substance its
                    # name says it is not.  That is how `Carbon dioxide,
                    # non-fossil, resource correction` reaches unqualified
                    # `Carbon Dioxide` (#133): the qualifier is detected, no
                    # object carries it, and the label branch then matches the
                    # substance the qualifier exists to distinguish it from.
                    #
                    # `no-flow-object-candidate` is the one reason
                    # `merge.creations` mints a substance for, and minting is
                    # right by that module's own test: several candidates mean
                    # the row matched *too much*, but a qualifier none of them
                    # carries means it matched too little.
                    #
                    # Deliberately narrow: it fires only where the qualifier is
                    # carried by nothing at all -- three qualifiers today,
                    # `biogenic_resource_correction`, `grey_water` and
                    # `blue_water` -- and not where it is carried by objects
                    # that happen not to share this CAS, which is a different
                    # population nobody has counted.
                    _record_unmatched_row(
                        row=row,
                        accumulator=accumulator,
                        reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
                        basis="cas+qualifier-unmatched",
                    )
                    return None
        if len(candidate_ids) > 1:
            narrowed = set()
            for label in row.labels:
                narrowed.update(
                    indexes.label_index.get(_normalize_text(label), set()) & candidate_ids
                )
            if narrowed:
                candidate_ids = narrowed
                basis = "cas+label"
        if len(candidate_ids) > 1 and indexes.source.simapro_origin:
            # The name's last comma-segment, read against the candidates the
            # registry number already found.  ecoinvent 2 named twelve
            # fluorinated ethers as structural prose with the industry
            # designation appended -- `Ether, 1,1,2,2-Tetrafluoroethyl
            # 2,2,2-trifluoroethyl-, HFE-347mcc3` -- and gave every member of a
            # family one CAS, which EF 3.1 also carries; SimaPro-era method
            # files still ship those rows.  The full name is nobody's published
            # label, so the narrowing above reads nothing, and the one segment
            # that names a single substance is the designation at the end.
            #
            # A name rule, so it owes the reason the curated alternative was
            # not used: it was tried.  Synonyms written onto the EF rows in
            # `ef-3.1-manual-fixes.json` are read at matching and purged before
            # publication, so the lookup -- which rebuilds its label index from
            # published labels -- never sees them, measured on the 2026-08-24
            # build of `890459c`.  What keeps this narrower than a name rule
            # usually is: the segment is only read against the row's *own* CAS
            # candidates' published labels, so it can choose among substances
            # the registry number already reached and can never introduce one.
            # Gated to the SimaPro lineage like every other habit of that
            # naming, and behind the full-label narrowing above, so a row whose
            # own name is a candidate's label never reaches it.
            narrowed = set()
            used = []
            for label in row.labels:
                head, sep, tail = label.rpartition(",")
                if not sep or not head.strip() or not tail.strip():
                    continue
                hits = (
                    indexes.label_index.get(_normalize_text(tail.strip()), set())
                    & candidate_ids
                )
                if hits:
                    used.append(tail.strip())
                    narrowed.update(hits)
            if narrowed:
                candidate_ids = narrowed
                basis = "cas+designation"

    if not candidate_ids and row.ec:
        candidate_ids = set(indexes.ec_index.get(row.ec, set()))
        basis, basis_value = "ec", row.ec

    if not candidate_ids:
        for label in row.labels:
            hits = indexes.label_index.get(_normalize_text(label), set())
            if hits:
                labels_used.append(label)
            candidate_ids.update(hits)
        if candidate_ids:
            candidate_ids, labels_used = _narrow_label_candidates(
                row=row,
                candidate_ids=candidate_ids,
                labels_used=labels_used,
                indexes=indexes,
            )
        if candidate_ids:
            basis = "label"
            basis_value = "; ".join(sorted(set(labels_used))[:3])

    # Last, and only for a list SimaPro shaped: the row's names rewritten out of
    # the habits that lineage carries -- `Benzene, Chloro-` for chlorobenzene
    # (#285).
    #
    # A fallback rather than an enrichment step, which is the whole point.  A
    # derived spelling is a weaker claim than anything above it, so it is only
    # reached once every real identifier and every shipped name has failed, and
    # a row that matches by CAS or by its own label never sees one.  Written as
    # an alternative label before matching instead, it would have joined
    # `row.labels` for *every* such row -- including the ones already matching
    # -- where the CAS branch narrows on labels and a wrong spelling can move a
    # match that was right.  Two of BAFU's, `2-Butene, 2-methyl-` and
    # `Dioxin, 2,3,7,8 Tetrachlorodibenzo-p-`, are exactly that row.
    if not candidate_ids and indexes.source.simapro_origin:
        systematic: set[str] = set()
        for label in row.labels:
            nomenclature = set(systematic_name_aliases(label))
            for alias in simapro_name_aliases(label):
                hits = indexes.label_index.get(_normalize_text(alias), set())
                if hits:
                    labels_used.append(alias)
                    if alias in nomenclature:
                        systematic.add(alias)
                candidate_ids.update(hits)
        if candidate_ids:
            candidate_ids, labels_used = _narrow_label_candidates(
                row=row,
                candidate_ids=candidate_ids,
                labels_used=labels_used,
                indexes=indexes,
                systematic_labels=systematic,
            )
        if candidate_ids:
            # Its own basis, so a curator reading `merge_outcomes` can tell a
            # row that matched on a name the vendor shipped from one that
            # matched on a name this project derived.
            basis = "simapro-name-pattern"
            basis_value = "; ".join(sorted(set(labels_used))[:3])

    # Last of all: a name ecoinvent retired.  2.2 said `Laterite, in ground`
    # and `Sulfate, ion`; every release since says `Laterite` and `Sulfate`,
    # and `data/ecoinvent-historical-names.json` -- derived from the vendor's
    # own 2.2 -> 3.12 correspondence -- records exactly those pairs
    # (`merge/historical_names.py`).  The row's names are rewritten through it
    # and looked up like any other label.
    #
    # A fallback for the same reason the SimaPro rewriting above is one: a row
    # that matches on its registry number or its own name never sees an alias,
    # so an entry that is wrong can only touch a row that was going to be
    # reported unmatched -- or minted as a duplicate of a flow this list
    # already publishes, which is how ecoinvent 3.8's `Sulfate, ion` came to
    # sit beside `Sulfate`.  Unlike that rewriting it is not gated to a
    # lineage: every entry is a string the vendor itself shipped for a known
    # flow, a dictionary rather than a pattern, so there is no derived guess
    # to confine.
    if not candidate_ids and indexes.historical_names:
        for label in row.labels:
            ruling = indexes.historical_names.get(_normalize_text(label))
            if ruling is None:
                continue
            hits = indexes.label_index.get(
                _normalize_text(ruling.canonical_name), set()
            )
            if hits:
                labels_used.append(ruling.canonical_name)
            candidate_ids.update(hits)
        if candidate_ids:
            candidate_ids, labels_used = _narrow_label_candidates(
                row=row,
                candidate_ids=candidate_ids,
                labels_used=labels_used,
                indexes=indexes,
            )
        if candidate_ids:
            # Its own basis, so a curator can tell a match made by the vendor's
            # crosswalk from one made by a name the row itself carried.
            basis = "historical-name"
            basis_value = "; ".join(sorted(set(labels_used))[:3])

    if not candidate_ids:
        # Say so when the only thing any name found was the bare element of
        # the row's own ion name (#198): the row was refused, not missed.
        label_hits: set[str] = set().union(*(
            indexes.label_index.get(_normalize_text(label), set()) for label in row.labels
        ))
        refused = _bare_element_hits(row=row, candidate_ids=label_hits, indexes=indexes)
        _record_unmatched_row(
            row=row, accumulator=accumulator,
            reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
            **({"basis": ION_ELEMENT_REFUSED_BASIS} if refused and refused == label_hits else {}),
        )
        return None

    if len(candidate_ids) > 1:
        narrowed, name_used = _narrow_to_preferred_name(
            row=row, candidate_ids=candidate_ids, indexes=indexes
        )
        if narrowed:
            candidate_ids = narrowed
            basis = f"{basis}+preferred-name" if basis else "preferred-name"
            basis_value = f"{basis_value}; {name_used}" if basis_value else name_used

    if len(candidate_ids) > 1:
        _record_unmatched_row(
            row=row,
            accumulator=accumulator,
            reason=UnmatchedReason.MULTIPLE_FLOW_OBJECT_CANDIDATES,
            candidate_flow_object_ids=sorted(candidate_ids),
            basis=basis,
        )
        return None

    return CandidateResolution(
        flow_object_id=next(iter(candidate_ids)),
        basis=basis,
        basis_value=basis_value,
    )


def _narrow_to_preferred_name(
    *,
    row: SourceRow,
    candidate_ids: set[str],
    indexes: MergeIndexes,
) -> tuple[set[str], str]:
    """The candidates whose *own* name is the row's, and the name that said so.

    The last thing tried, and only on a row about to be reported as matching
    too much.  A tie means every rule above it found the same evidence for
    several substances; this asks the one question none of them asks, which is
    **which of them is actually called that**.

    A label hit does not say which kind of label it hit.  BAFU's row named
    simply `Water` carries 7732-18-5, and twelve substances in this list carry
    it too -- every kind of water is H2O.  Eleven of the twelve also answer to
    "water" among their alternative names, correctly, because they are all
    water.  So the row hits twelve on the number and eleven on a name, and the
    twelve-way tie stands.  One of the twelve is *called* `Water`.  That is a
    different and better answer than eleven substances that merely also go by
    it, and nothing before this notices the difference (#86).

    Two things keep it from collapsing the distinctions the list works to hold:

    **The row's own name, not any of its names.**  A row is looked up under
    every name it is known by -- the shipped name, its synonyms, the labels
    enrichment found -- and for water that is 23 names shared by every water
    row BAFU ships, `Water, river` included.  Matching on any of them would
    send `Water, river` to plain `Water`, which is exactly the collapse the
    material axis exists to stop.  Only :attr:`SourceRow.name` is asked, so a
    row whose name no candidate is called stays unmatched.

    **Equality, not similarity.**  `Water, river` finds nothing here on its own
    and is reached, if at all, through the spellings a SimaPro-shaped list's
    habits imply -- `river water` is one of them (#288), and the list holds a
    substance called exactly that.  Those are gated on ``simapro_origin`` like
    everything else derived from a name, and they are consulted here for the
    same reason the fallback below consults them: the row was going to be
    reported unmatched, so a rule that is wrong costs a review rather than a
    silent mismatch.

    **The species vocabulary's spelling counts as the row's name.**  A vendor
    row saying `Copper Ion` and a substance called `Copper, Ion` are one name
    in the spelling this list already matches the family under
    (`merge/species.py`); the tie this rule broke by preferred label stopped
    breaking the day the minted ions were renamed onto the house spelling
    (#141's harmonisation), because the vendor's comma-less spelling became an
    alternative label -- and an alternative label is exactly what this rule
    refuses to count.  Folding the *row's own name* through the species
    vocabulary keeps the refusal and the match: only the one name is asked,
    just in both spellings.

    Returns ``(set(), "")`` when no candidate is called what the row is, which
    leaves the tie exactly as it was.
    """
    names = [row.name]
    species = parse_species(row.name)
    if species:
        names.append(species_object_label(species))
    if indexes.source.simapro_origin:
        names += simapro_name_aliases(row.name)
    for name in names:
        key = _normalize_text(name)
        if not key:
            continue
        narrowed = indexes.pref_label_index.get(key, set()) & candidate_ids
        if narrowed:
            return narrowed, name
    return set(), ""


def _size_class_flow_object(size_class: SizeClass) -> str:
    """The flow object id *size_class* mints.

    From the scheme's stated basis rather than composed here, so the merge and
    the layering cannot drift into minting two ids for one window.  Every class
    in the scheme mints one, unlike the material taxonomy, so there is no empty
    case to return.
    """
    return _stable_flow_object_id("fo", size_class.flow_object_basis)


def _material_flow_object(material: str) -> str:
    """The flow object id *material* mints, or "" for a concept that mints none.

    From the taxonomy's stated basis rather than composed here, so the merge and
    the layering cannot drift into minting two ids for one concept.
    """
    basis = flow_object_basis_for(material)
    return _stable_flow_object_id("fo", basis) if basis else ""


def _narrow_label_candidates(
    *,
    row: SourceRow,
    candidate_ids: set[str],
    labels_used: list[str],
    indexes: MergeIndexes,
    systematic_labels: Collection[str] = (),
) -> tuple[set[str], list[str]]:
    """Reduce label-only candidates to those the evidence actually supports.

    Reached only once the CAS and EC lookups have found nothing, so a source CAS
    -- when there is one -- is a number this index does not know.  A label hit on
    a flow object that *does* carry a CAS is then a positive disagreement rather
    than missing evidence: that object's identity is pinned to a different
    number.  This used to try intersecting the candidates with the source CAS
    first and keep them all when that came back empty, which it always did,
    given where this is called from.

    So the same rule applies whether or not the source has a CAS of its own.
    Two kinds of label evidence are safe:

      - a prefLabel hit on a CAS-bearing object: the label is that substance's
        primary name rather than one of the many things it is also called.  A
        salt form numbered differently from its parent acid lands here.
      - any hit on a CAS-less object: neither side has a CAS to disagree with.

    An altLabel hit on a CAS-bearing object is rejected, which is what stops a
    trade name or a product code matching the wrong substance: "Granite" ->
    Penoxsulam, and "Propylene Carbonate" -> Talc on a shared "K 3".

    The question is asked of ``labels_used`` -- the names that actually found
    the candidates -- not of the row's own labels (#103).  For a shipped name
    the two are the same set, because a name that hits the prefLabel index hits
    the label index too.  For a name the SimaPro rewriting derived they are
    not: `Ethane, chloro-` rewrites to `chloroethane`, which is the published
    name of exactly one substance, and a rule reading the shipped names finds
    nothing to accept and throws that match away.  A prefLabel hit is a claim
    about the name that made it, so it is judged on that name.

    ``systematic_labels`` is a third kind of safe evidence, and the narrowest:
    an **altLabel** hit made by a systematic chemical name.  The refusal above
    exists because this code cannot tell a trade name from a real one, and a
    name from :func:`~brightway_flows.simapro_names.systematic_name_aliases`
    settles that question by construction -- it was built out of a parent
    compound and what is attached to it, by a rule that fires only on the
    syntax of one, so it cannot be `Granite` or `K 3`.  Nine BAFU rows across
    five names land here: `Ethene, 1,1-dichloro-` rewrites to
    `1,1-dichloroethene`, which the list holds as a synonym of
    1,1-dichloroethylene, and `Benzo(a)anthracene` retypes to
    `benzo[a]anthracene`, which is that substance's published name (#103).

    The caller passes only names it derived.  A name the vendor shipped is
    never systematic however chemical it looks, which is what keeps this from
    becoming the wider relaxation the refusal is there to prevent.

    **A name that states a charge never reaches the bare element** (#198).
    ecoinvent 3.12's `Rhodium III` carries the ion's number, 16065-89-7, and
    EF 3.1 holds no rhodium ion, so the number found nothing and the label
    branch read the vendor's own synonym `Rhodium` -- a preferred-label hit on
    a numbered object, which the rule above accepts.  Seven rows were published
    as the metal.  The row said which substance it was twice over, in the name
    and in the number, and the candidate was the one substance the charge
    exists to distinguish it from, so it is refused here whatever label found
    it: :func:`_bare_element_hits` names the candidates that are the bare
    element of the row's own ion name, and they are dropped.  With nothing
    left the row mints, as AGRIBALYSE's `Rhodium (III)` already did.  Only
    label evidence is judged: a row whose *number* is the element's -- ecoinvent's
    `Strontium II` under 7440-24-6 -- matches on the number above and never
    reaches here, and what that number means is a ruling, not a rule.
    """
    pref_hits: set[str] = set().union(*(
        indexes.pref_label_index.get(_normalize_text(label), set())
        for label in labels_used
    )) & candidate_ids & indexes.flow_objects_with_cas
    systematic_hits: set[str] = set().union(*(
        indexes.label_index.get(_normalize_text(label), set())
        for label in systematic_labels
    )) & candidate_ids & indexes.flow_objects_with_cas
    no_cas_hits = candidate_ids - indexes.flow_objects_with_cas
    narrowed = pref_hits | systematic_hits | no_cas_hits
    narrowed -= _bare_element_hits(row=row, candidate_ids=narrowed, indexes=indexes)
    return narrowed, (labels_used if narrowed else [])


#: What the unmatched record says when every label hit was the bare element of
#: the row's own ion name (#198), so a curator can tell the refusal from a row
#: no name reached at all.
ION_ELEMENT_REFUSED_BASIS = "label+ion-element-refused"


def _bare_element_hits(
    *, row: SourceRow, candidate_ids: set[str], indexes: MergeIndexes
) -> set[str]:
    """The candidates that are the bare element of *row*'s own ion name.

    Empty unless the row's name parses as an ion of the element/ion family
    (`merge/species.py`) with a stated charge or the generic marker: `Rhodium
    III`, `Palladium (II)`, `Copper ion`.  A candidate is the bare element when
    its preferred label parses as the bare member of the same element --
    `Rhodium`, not `Rhodium(3+)` and not `Rhodium, Ion`.  Read off the label
    rather than the typing because the label is what the row's name was
    compared with, and because a minted ion is typed only after it exists.
    """
    species = parse_species(row.name)
    if species is None or species.kind == "bare":
        return set()
    hits: set[str] = set()
    for candidate in candidate_ids:
        target = parse_species(indexes.flow_object_label_by_id.get(candidate, ""))
        if target is not None and target.kind == "bare" and target.element == species.element:
            hits.add(candidate)
    return hits
