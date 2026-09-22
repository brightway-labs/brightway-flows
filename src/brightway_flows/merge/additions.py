"""Flows added to the consensus list rather than matched into it.

Two kinds: manual additions, where a curator has grouped source flows onto a
chosen flow object, and algorithmic additions, where a confident match exists for
the substance but not for its context.

Either way the flow gets its identifier from
:func:`~brightway_flows.domain.elementary_flow.minted_elementary_flow_id`,
which is a function of the substance and the compartment -- not of the source
row that arrived first, which is what it used to be (#102).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.elementary_flow import (
    ElementaryFlow,
    minted_elementary_flow_id,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.units import unit_iri_for
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    QUDT_HAS_UNIT_CURIE,
    RO_HAS_ROLE_IRI,
    SKOS_BROAD_MATCH_CURIE,
    SKOS_DEFINITION_IRI,
    SKOS_PREF_LABEL_CURIE,
    XKOS_CONCEPT_ASSOCIATION_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.merge.contexts import (
    _context_for_new_flow,
    _normalize_text,
)
from brightway_flows.merge.provenance import _build_match_provenance
from brightway_flows.merge.unit_changes import published_unit_for
from brightway_flows.merge.report import ManualAddition, UnmatchedRow
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.sources import base_source_label
from brightway_flows.transformers.unit_normalization import resolve_unit_notation

logger = structlog.get_logger(__name__)

#: What a manually added flow records as the file that placed it.  A constant
#: because the groupings file states no name for itself, and the two places that
#: write it must not be able to say different things.
MAPPING_FILE_LABEL = "manual-additions"

@dataclass(frozen=True)
class ManualAdditionRule:
    """Which existing flow object a source row the merge could not place goes on.

    ``source_uuids`` is what the rule was written against and ``source_name`` is
    the fallback for a release that added a row the file has not catalogued yet;
    see :func:`_build_manual_additions_indexes` for which one is asked first.
    """

    source_name: str
    flow_object_id: str
    source_uuids: tuple[str, ...] = ()
    flow_object_label: str = ""
    #: What the substance is used for, in the source's own words, and what the
    #: created flow publishes as its general comment.
    notes: str = ""
    pesticide_type: str = ""

    @property
    def extra_fields(self) -> dict[str, Any]:
        """What the created flow's ``source_metadata`` carries beyond the core.

        The merge reads ``source_name``, ``flow_object_id``,
        ``flow_object_label`` and ``notes`` by name and forwards the rest, so a
        reader of the published flow can see which rule placed it and on what.
        Built from the declared fields rather than from whatever keys the file
        happened to hold: this is published, so its shape is a decision rather
        than a consequence of a curator's next column heading.
        """
        extra: dict[str, Any] = {}
        if self.pesticide_type:
            extra["pesticide_type"] = self.pesticide_type
        if self.source_uuids:
            extra["source_uuids"] = list(self.source_uuids)
        return extra


def _load_manual_additions(path: Path | None) -> tuple[ManualAdditionRule, ...]:
    """One source list's manual-additions file, as the rules it states.

    A row naming no target flow object is dropped: it decides nothing, and the
    indexes below were already skipping it.

    *path* is ``None`` for a list that declares no groupings, which is the
    normal state of a list on the day it is added; it merges without them.
    The argument used to default to ecoinvent's pesticide groupings, and the
    caller passed nothing, so every list was given ecoinvent's curated
    decisions (#240).
    """
    if path is None:
        return ()
    if not path.exists():
        logger.warning("manual_additions_file_not_found", path=str(path))
        return ()
    payload = orjson.loads(path.read_bytes())
    rules: list[ManualAdditionRule] = []
    for mapping in payload.get("mappings", []) or ():
        if not isinstance(mapping, dict):
            continue
        flow_object_id = mapping.get("flow_object_id")
        if not isinstance(flow_object_id, str) or not flow_object_id:
            continue
        rules.append(ManualAdditionRule(
            source_name=str(mapping.get("source_name") or "").strip(),
            flow_object_id=flow_object_id,
            source_uuids=tuple(
                uuid.strip()
                for uuid in mapping.get("source_uuids", []) or ()
                if isinstance(uuid, str) and uuid.strip()
            ),
            flow_object_label=str(mapping.get("flow_object_label") or ""),
            notes=str(mapping.get("notes") or ""),
            pesticide_type=str(mapping.get("pesticide_type") or ""),
        ))
    return tuple(rules)

def _build_manual_additions_indexes(
    additions: tuple[ManualAdditionRule, ...],
) -> tuple[dict[str, ManualAdditionRule], dict[str, ManualAdditionRule]]:
    """Return (uuid_index, name_index) over *additions*.

    uuid_index keys on each source UUID the rule lists.  name_index keys on the
    normalised source_name and is used as a fallback when a UUID is not present
    in the file (e.g. a new ecoinvent version adds flows not yet catalogued in
    the groupings file).
    """
    uuid_index: dict[str, ManualAdditionRule] = {}
    name_index: dict[str, ManualAdditionRule] = {}
    for rule in additions:
        for uuid in rule.source_uuids:
            uuid_index[uuid] = rule
        if rule.source_name:
            name_index[_normalize_text(rule.source_name)] = rule
    return uuid_index, name_index

def _inherited_flow_object_fields(flow_object: FlowObject) -> dict[str, Any]:
    """The label, property and reference fields a flow inherits from its substance.

    Mirrors the enrichment that the main pipeline applies to harmonised flows so
    that algorithm- and manual-addition elementary flows carry the same schema as
    flows produced by the full transform run.

    Returned as the bag that becomes `ElementaryFlow.extra`, and keyed by
    serialised name, because that is what these are: `ElementaryFlow` declares
    none of them.  Two shapes of stored record exist -- 93,993 base-list flows
    carry the occurrence keys alone and the 1,197 the merge created carry these
    as well -- and which is right is a question for whoever can answer it, not
    something to settle in passing here (see `_MERGE_RECORD_SUBSTANCE_KEYS`).
    Until then this is an undeclared key on a record that has a bag for them,
    which is where AGENTS.md rule 3 says it goes.

    *flow_object* is read by attribute.  The attribute and serialised names
    differ for `skos_definition` and `roles`, so the pairs are stated once below
    rather than read off `_ALIASES` -- an alias table is a serialisation detail,
    and a field is inherited here because it belongs to the substance, not
    because it happens to be aliased.
    """
    new_flow: dict[str, Any] = {}
    # `RO_HAS_ROLE_IRI` is here because a role is a property of the substance,
    # so a flow the merge creates for that substance bears it as much as the
    # source-list flow that seeded the object does.  Left out, the roles reached
    # only the flows the transform had touched: on a 600-flow run 46 flows
    # published roles and 233 whose object had them published none, and because
    # `_hoist_shared_object_payloads` only hoists a key *every* flow of the
    # object carries, the key was never shared either.
    for attribute, key in (
        ("prefLabel", "prefLabel"),
        ("altLabel", "altLabel"),
        ("properties", "properties"),
        ("references", "references"),
        ("skos_definition", SKOS_DEFINITION_IRI),
        ("roles", RO_HAS_ROLE_IRI),
    ):
        value = getattr(flow_object, attribute)
        if value is not None:
            new_flow[key] = value
    new_flow["name"] = flow_label_value(flow_object) or ""
    classifications = (
        flow_object.classifications
        if isinstance(flow_object.classifications, dict)
        else {}
    )
    cas_entry = classifications.get(CHEMINF_CAS_REGISTRY_NUMBER, {})
    new_flow["cas_numbers"] = cas_entry.get("@value", []) if isinstance(cas_entry, dict) else []
    ec_entry = classifications.get(CHEMINF_EC_NUMBER, {})
    new_flow["ec_numbers"] = ec_entry.get("@value", []) if isinstance(ec_entry, dict) else []
    return new_flow

def apply_manual_additions(
    *,
    unmatched: list[UnmatchedRow],
    source_flow_by_uuid: dict[str, Flow],
    external_names_by_cas: dict[str, dict[str, Any]],
    units_index: Any,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
    consensus_is_partial: bool,
) -> list[ManualAddition]:
    """Place unmatched rows a curator has grouped onto a chosen flow object.

    For an unmatched row whose uuid -- or, as a fallback, whose normalised source
    name -- is listed in *this list's* manual-additions file, a new elementary
    flow is created on the flow object the entry names, in the row's own context,
    and an XKOS broadMatch concept association is minted back to the base list's
    "XXX, unspecified" flow for that object in the same context.  Broad, not
    exact: one grouping gathers several source rows onto one consensus flow.

    UUID lookup is tried first; the name fallback is what catches rows a newer
    release of the same list added that the groupings file has not catalogued
    yet.  That fallback is why the file has to come from the manifest: matched
    across lists, a normalised name collision silently removes a row from the
    unmatched queue (#240).

    The new flows go onto *accumulator*.  The rows that were placed are returned
    as report rows, and the caller drops them from *unmatched* -- the same shape
    as :func:`~brightway_flows.merge.creations.create_flows_for_unmatched_rows`,
    and for the same reason: a row that has been placed is no longer unmatched.

    A grouping names a flow object that already exists; nothing here creates
    one.  When the named object cannot be found the row is *not* placed, and
    what that means depends on *consensus_is_partial*:

    - ``False`` -- the consensus list is the whole base list, so an object that
      is not in it is one the groupings file names and the data does not have.
      That is a stale curated decision, and it raises.
    - ``True`` -- the consensus list is a bounded slice (`build --max-flows`),
      so the object is very likely outside the slice rather than absent.  The
      rows are logged and left unmatched, which is what a smoke run should do
      with them.

    Until #228 the lookup was `if fo:` around the field inheritance alone: the
    elementary flow was written either way, pointing at a flow object that did
    not exist, with no label, no properties and no `@type`.  A bounded 400-flow
    run produced 189 such rows -- a third of the published export.

    :raises ValueError: if a placed row's flow object does not exist and the
        consensus list is complete.
    """
    source = indexes.source
    manual_additions: list[ManualAddition] = []
    manual_additions_uuid_index, manual_additions_name_index = _build_manual_additions_indexes(
        _load_manual_additions(source.manual_additions_path)
    )
    if not manual_additions_uuid_index and not manual_additions_name_index:
        return manual_additions

    #: flow object id -> the source uuids a grouping sent to it, for objects
    #: that do not exist.  Collected rather than raised on the first one, so a
    #: curator sees every stale id at once.
    missing_targets: dict[str, list[str]] = {}

    for unmatched_row in unmatched:
        u_uuid = unmatched_row.source_uuid.strip()
        if not u_uuid:
            continue
        mapping = manual_additions_uuid_index.get(u_uuid)
        if mapping is None:
            mapping = manual_additions_name_index.get(
                _normalize_text(unmatched_row.source_name)
            )
        if mapping is None:
            continue

        manual_fo_id = mapping.flow_object_id
        # Before anything is built from the row: a flow object that does not
        # exist cannot be inherited from, and the flow it would carry would
        # point at nothing.  Leave the row unmatched instead.
        flow_object = indexes.flow_objects_by_id.get(manual_fo_id)
        if flow_object is None:
            missing_targets.setdefault(manual_fo_id, []).append(u_uuid)
            continue

        u_name = unmatched_row.source_name
        u_context = unmatched_row.source_context or []
        u_unit = unmatched_row.source_unit
        # `u_unit` stays the row's own everywhere it describes the row -- the
        # source ref, the concept association, the report.  The *flow* states
        # the unit this list publishes the quantity kind in, where the two
        # differ on one scale -- the same rule as every other mint (#142).
        flow_unit = (
            published_unit_for([u_unit] if u_unit else []) or u_unit
        )
        _u_resolved = resolve_unit_notation(flow_unit, units_index) if flow_unit else None
        flow_unit_iri = _u_resolved[1] or "" if _u_resolved else ""
        u_cas = unmatched_row.source_cas
        u_ec = unmatched_row.source_ec
        u_context_iri = indexes.context_expectations.resolve(
            u_uuid, u_context, u_name
        ) or ""
        new_elem_id = minted_elementary_flow_id(manual_fo_id, u_context_iri)
        u_provenance = _build_match_provenance(
            source_uuid=u_uuid,
            source_name=u_name,
            source=source,
            mapping_file=MAPPING_FILE_LABEL,
            merge_method="manual_addition_lookup",
            merge_basis="manual_addition",
        )

        # Find the base list's elementary flow for the group in the same
        # context, used as the target of the broadMatch concept association.
        ef_flows_for_group = [
            ef for ef in accumulator.elementary_by_object.get(manual_fo_id, [])
            if ef.source == base_source_label()
        ]
        ef_elem_for_ctx = next(
            (ef for ef in ef_flows_for_group
             if u_context_iri and ef.context_iri == u_context_iri),
            None,
        )
        concept_associations: list[dict[str, Any]] = []
        target_ef_elem_id = ""
        if ef_elem_for_ctx is not None:
            target_ef_elem_id = ef_elem_for_ctx.elementary_flow_id
        # When there is no base-list equivalent in this context, fall back to the new
        # consensus flow itself so the source UUID remains traceable.
        target_concept_id = target_ef_elem_id or new_elem_id
        if target_concept_id:
            concept_associations.append({
                "@type": XKOS_CONCEPT_ASSOCIATION_CURIE,
                XKOS_SOURCE_CONCEPT_CURIE: {
                    "@id": f"{source.flow_iri_prefix}{u_uuid}",
                    SKOS_PREF_LABEL_CURIE: u_name,
                    "context": " / ".join(str(x) for x in u_context if x),
                    **(
                        {QUDT_HAS_UNIT_CURIE: {"@id": u_unit_iri}}
                        if (u_unit_iri := unit_iri_for(u_unit))
                        else {}
                    ),
                    # Broad, not exact: a manual addition groups several
                    # source flows onto one consensus flow.
                    SKOS_BROAD_MATCH_CURIE: {
                        "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{target_concept_id}",
                    },
                },
                XKOS_TARGET_CONCEPT_CURIE: {
                    "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{target_concept_id}",
                },
                "provenance": u_provenance,
            })

        # External name validation (transform-step function reused at merge
        # time).  The source list's own vocabulary, deliberately: this asks
        # whether PubChem or ChEBI agrees that the CAS names this substance,
        # and a label the pipeline invented would not be an independent
        # check of that.
        u_source_flow = source_flow_by_uuid.get(u_uuid)
        u_synonyms = (
            [u_source_flow.provided.name or "", *u_source_flow.provided.synonyms]
            if u_source_flow else []
        )
        external_u = external_names_by_cas.get(u_cas, {}) if u_cas else {}
        norm_ext_names = external_u.get("normalized_names", [])
        u_terms_norm = {_normalize_text(u_name)} | {_normalize_text(s) for s in u_synonyms if s}
        u_terms_norm = {x for x in u_terms_norm if x}
        cas_name_validated = (
            any(isinstance(n, str) and n in u_terms_norm for n in norm_ext_names)
            if u_cas and isinstance(norm_ext_names, list) else False
        )

        # Forwarded into source_metadata so callers retain full context.
        extra_fields = mapping.extra_fields

        accumulator.add_flow(ElementaryFlow(
            elementary_flow_id=new_elem_id,
            flow_object_id=manual_fo_id,
            source=source.manual_addition_source,
            source_refs=[{
                "list_name": source.list_name,
                "list_version": source.list_version,
                "source_flow_uuid": u_uuid,
                "source_flow_name": u_name,
                "source_metadata": {
                    "original_context": u_context,
                    "unit": u_unit,
                    "cas_number": u_cas,
                    "ec_number": u_ec,
                    "merge_basis": "manual_addition",
                    "merge_method": "manual_addition_lookup",
                    "selector_reason": "manual-addition-to-group",
                    "notes": mapping.notes,
                    "extra_fields": extra_fields,
                    "mapping_file": MAPPING_FILE_LABEL,
                    "provenance": u_provenance,
                    "merge_details": {},
                },
            }],
            context=_context_for_new_flow(u_context_iri),
            context_iri=u_context_iri,
            unit=flow_unit,
            unit_iri=flow_unit_iri,
            lcia_methods=[],
            general_comment=mapping.notes,
            concept_associations=concept_associations,
            # The substance keys, in the bag the record keeps undeclared keys
            # in; see `_inherited_flow_object_fields`.
            extra=_inherited_flow_object_fields(flow_object),
        ))

        has_exact_ctx = bool(
            target_ef_elem_id and u_context_iri and ef_elem_for_ctx is not None
            and ef_elem_for_ctx.context_iri == u_context_iri
        )
        manual_additions.append(ManualAddition(
            source_uuid=u_uuid,
            source_name=u_name,
            source_context=u_context,
            source_context_iri=u_context_iri,
            source_unit=u_unit,
            source_cas=u_cas,
            source_ec=u_ec,
            flow_object_id=manual_fo_id,
            flow_object_label=indexes.flow_object_label_by_id.get(manual_fo_id, ""),
            new_elementary_flow_id=new_elem_id,
            target_ef_elementary_flow_id=target_ef_elem_id,
            has_ef_context_match=has_exact_ctx,
            cas_name_validated=cas_name_validated if u_cas else None,
            notes=mapping.notes,
            extra_fields=extra_fields,
            provenance=u_provenance,
        ))
        logger.info(
            "manual_addition",
            source_uuid=u_uuid,
            source_name=u_name,
            flow_object_id=manual_fo_id,
            new_elementary_flow_id=new_elem_id,
            has_ef_context_match=has_exact_ctx,
        )

    if missing_targets:
        row_count = sum(len(uuids) for uuids in missing_targets.values())
        mapping_file = str(source.manual_additions_path or "manual-additions")
        if not consensus_is_partial:
            detail = "\n  ".join(
                f"{fo_id}: {len(uuids)} row(s), first {uuids[0]}"
                for fo_id, uuids in sorted(missing_targets.items())
            )
            logger.error(
                "manual_addition_target_flow_object_missing",
                source=source.key,
                object_count=len(missing_targets),
                row_count=row_count,
                examples=sorted(missing_targets)[:20],
            )
            raise ValueError(
                f"{len(missing_targets)} flow object(s) named by {mapping_file} do "
                f"not exist, and {row_count} {source.key} row(s) were grouped onto "
                f"them; refusing to write elementary flows that point at nothing:\n  "
                + detail
            )
        # A bounded run transforms part of the base list, so the group's object
        # is almost certainly outside the slice rather than gone.  Say so and
        # leave the rows unmatched, where the run's own creation step takes them.
        logger.warning(
            "manual_addition_target_outside_bounded_slice",
            source=source.key,
            object_count=len(missing_targets),
            row_count=row_count,
            examples=sorted(missing_targets)[:5],
        )

    return manual_additions
