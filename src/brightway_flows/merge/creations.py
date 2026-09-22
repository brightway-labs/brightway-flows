"""Flow objects minted for source rows naming a substance the list does not have.

The rest of the merge attaches a source row to something that already exists: a
prepared decision, a matched flow, or a new flow in a missing context of a flow
object matching already found.  This is the one path that adds a *substance*.

Only ``no-flow-object-candidate`` reaches here.  A row with several candidate
flow objects matched too much rather than too little, and choosing between them
is a guess -- so it keeps reporting.  That is the same distinction
:data:`~brightway_flows.merge.rows._CREATABLE_SELECTOR_REASONS` draws one
layer down, applied to the layer above.

The derivation is :func:`~brightway_flows.flow_layers.resolve_flow_layers`,
the transform's own, rather than a second one written here that could disagree
with it.  It is run over the whole batch at once, which is what makes a
substance appearing in seven contexts one flow object with seven flows rather
than seven objects.

Identifiers are minted, not inherited from the source row.  The reason is
editorial: republishing a licensed vendor's identifiers as consensus identifiers
puts their keys in the published artifact more prominently than we want.  It
also keeps the uuid collision guard in ``_enrich_against_consensus`` quiet, since
the flow this run publishes would otherwise carry the uuid of the source row the
next list is enriched against.
"""

from __future__ import annotations

from typing import Any

import structlog

from brightway_flows.domain.elementary_flow import (
    ElementaryFlow,
    minted_elementary_flow_id,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.materials import material_for_source_flow
from brightway_flows.domain.property_values import normalise_records
from brightway_flows.domain.units import unit_iri_for
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    QUDT_CONVERSION_MULTIPLIER_CURIE,
    QUDT_HAS_UNIT_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    XKOS_CONCEPT_ASSOCIATION_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.ions import enrich_monoatomic_ions
from brightway_flows.flow_layers.land_hierarchy import attach_land_hierarchy
from brightway_flows.flow_layers.non_material import attach_non_material_families
from brightway_flows.merge.additions import _inherited_flow_object_fields
from brightway_flows.merge.contexts import (
    _context_for_new_flow,
    water_body_from_material,
)
from brightway_flows.merge.conversions import (
    UnitConversion,
    conversion_from_source_flow,
)
from brightway_flows.merge.matching import _classification_values
from brightway_flows.merge.provenance import (
    _append_concept_association,
    _append_source_ref,
    _build_match_provenance,
)
from brightway_flows.merge.report import (
    CreatedFlow,
    UnmatchedReason,
    UnmatchedRow,
)
from brightway_flows.merge.state import MergeAccumulator, MergeIndexes
from brightway_flows.merge.unit_changes import (
    UNDECIDED,
    CreatedFlowUnit,
    created_flow_unit_decisions,
    decide_created_flow_unit,
)
from brightway_flows.pipeline.semantic_typing import assign_semantic_types
from brightway_flows.transformers.unit_normalization import resolve_unit_notation

logger = structlog.get_logger(__name__)

#: Recorded on every flow this module creates, in place of the selector reason a
#: matched flow carries.  Nothing was selected: there was nothing to select from.
CREATION_SELECTOR_REASON = "new-flow-object-created"

#: `merge_method` for the same rows.  Deliberately not `algorithmic_fallback`:
#: that value makes `_build_match_provenance` write a scoring trace, and no
#: candidate was ever scored here.
CREATION_MERGE_METHOD = "flow_object_creation"

#: Set on an unmatched row whose creation was refused because the flow object it
#: would have minted already exists.  `_stable_object_id` seeds on substance
#: identity, so that is not a hash collision -- it means the matcher should have
#: found that object and did not.
CREATION_BLOCKED_KEY = "creation_blocked_by_existing_flow_object_id"


def create_flows_for_unmatched_rows(
    *,
    unmatched: list[UnmatchedRow],
    source_flow_by_uuid: dict[str, Flow],
    units_index: Any,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> tuple[list[FlowObject], list[CreatedFlow]]:
    """Mint a flow object and its elementary flows for every unplaceable row.

    Returns the new flow objects as the `FlowObject` records the layering built
    -- they used to be flattened with `to_dict()` here, for no reason except
    that `MergeIndexes.flow_objects_by_id` held dicts -- and one report row per
    source row that produced a flow.  The elementary
    flows go onto *accumulator*; the objects are returned because the caller
    writes them and the caller owns the database.

    *indexes* is read, with two deliberate exceptions: the new objects are added
    to ``flow_objects_by_id`` and ``flow_object_label_by_id`` before returning,
    because a later source list matches against them and because the datastore
    sync reads a created flow's label out of the second one.

    :raises ValueError: if a row's source context maps to no harmonised context
        IRI.  Same rule as
        :func:`~brightway_flows.merge.rows._add_flow_in_missing_context`:
        every source context must be registered, and guessing one would put a
        substance somewhere arbitrary.
    """
    rows = [
        row for row in unmatched
        if row.reason == UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE
        and row.source_uuid in source_flow_by_uuid
    ]
    if not rows:
        return [], []

    context_iri_by_uuid = {
        row.source_uuid: _harmonised_context_iri(row, indexes) for row in rows
    }

    # CAS-bearing rows first, so that where a substance reaches this batch both
    # with and without its number, the object is seeded on the number.  Order
    # matters because `resolve_flow_layers` seeds an object's id from the first
    # row that reaches it, and a name is something enrichment can change from
    # one run to the next whereas a CAS is not.
    ordered = sorted(rows, key=lambda row: (not row.source_cas.strip(), row.source_uuid))
    flows = [source_flow_by_uuid[row.source_uuid] for row in ordered]

    # `include_pubchem_isotopes=False`: that pass enriches flow objects reachable
    # from an `EF 3.1` elementary flow, and nothing in this batch is one, so it
    # would load the PubChem element cache and open a ChemLIN client to do
    # nothing.  It also carries a label-rewriting path (#221) that has no
    # business overruling the label `_enrich_against_consensus` just settled on.
    new_objects, new_elementary, layer_stats = resolve_flow_layers(
        flows,
        source_list=indexes.source,
        include_pubchem_isotopes=False,
        # Safe here, and needed: these objects are written straight out, and the
        # rename runs after every id in this call is settled.
        apply_curated_names=True,
    )
    object_id_by_uuid = {
        row.elementary_flow_id: row.flow_object_id for row in new_elementary
    }

    # An id the merge already knows is not a new substance.  Two ways it can be
    # known, and both have to be checked:
    #
    #   - it names an existing flow object.  `_stable_object_id` seeds on
    #     substance identity, so that is never a hash clash: it means the
    #     matcher should have found that object and did not.
    #   - it names an object that already has flows in this merge, without
    #     existing as an object itself.  A manual addition targets a flow object
    #     id from the groupings file, and that file's ids were minted by the
    #     same seeding -- so a curated grouping for a substance and a creation
    #     for the same substance land on one id.  Creating there would attach
    #     the row to the curator's group flow instead of giving it its own.
    #
    # Refuse the whole object rather than part of it, and leave its rows in the
    # review queue where a curator will see why.
    known_object_ids = (
        set(indexes.flow_objects_by_id) | set(accumulator.elementary_by_object)
    )
    blocked_object_ids = {
        object_id for object_id in object_id_by_uuid.values()
        if object_id in known_object_ids
    }
    if blocked_object_ids:
        for row in rows:
            object_id = object_id_by_uuid.get(row.source_uuid, "")
            if object_id in blocked_object_ids:
                row.extra[CREATION_BLOCKED_KEY] = object_id
        logger.warning(
            "flow_object_creation_blocked_by_existing_object",
            object_count=len(blocked_object_ids),
            examples=sorted(blocked_object_ids)[:5],
        )

    # Typed from the chemistry before they are written, like every other flow
    # object: `flow_objects.flow_type` is NOT NULL, and an object that reached
    # the database untyped would publish as `unclassified` for no reason other
    # than having come in through the merge.  The elementary flows carry the
    # harmonised context by then, because that is where the typing rules read
    # the dimension that separates a land-use class from a chemical.
    for row in new_elementary:
        context_iri = context_iri_by_uuid.get(row.elementary_flow_id, "")
        row.context_iri = context_iri
        row.context = _context_for_new_flow(context_iri)
    kept_objects = [
        obj for obj in new_objects if obj.flow_object_id not in blocked_object_ids
    ]
    # The ion layer, run here rather than left to the layering, and first
    # because everything below it reads what it writes: the typing rules
    # classify a charged single atom from the charge, and `normalise_records`
    # tidies the properties it adds.  That is the order the transform runs them
    # in as well -- there the pass is inside `resolve_flow_layers`, which is
    # where the merge cannot reach it, because it sits behind
    # `include_pubchem_isotopes` alongside the isotope machinery this batch has
    # no use for.
    #
    # The elements come from the consensus list rather than from this batch.  An
    # ion is recognised by its name resolving to an object typed
    # `chemrof:ChemicalElement`, and a merge mints no elements -- element
    # enrichment is seeded from the base list by decision -- so a batch asked
    # about itself would recognise nothing.  `Iron, ion` is an ion of the iron
    # the list already holds (#71).
    ion_stats = enrich_monoatomic_ions(
        {obj.flow_object_id: obj for obj in kept_objects},
        elements=indexes.flow_objects_by_id,
        rename_labels=False,
    )
    # Beside the typing and before it, because both ask the same question of the
    # same field: which contexts does this object occur in.  That is why the
    # loop above had to run first -- `resolve_flow_layers` sees the elementary
    # flows before their harmonised context is on them, so a family pass inside
    # the layering found no candidates at all and BAFU's noise flows reached no
    # family in a merge (#70).
    kept_objects, family_stats = attach_non_material_families(
        kept_objects, new_elementary
    )
    kept_objects, land_stats = attach_land_hierarchy(kept_objects)
    family_stats = {**family_stats, **land_stats}
    typing_stats = assign_semantic_types(kept_objects, new_elementary)
    normalise_records(kept_objects)
    objects_by_id = {obj.flow_object_id: obj for obj in kept_objects}

    # Before the loop, not inside it: the unit a flow declares is a property of
    # every row that lands on it, and a decision taken row by row is a decision
    # taken by file order.
    unit_by_flow = _unit_by_flow(
        ordered,
        object_id_by_uuid=object_id_by_uuid,
        context_iri_by_uuid=context_iri_by_uuid,
        source_label=indexes.source.source_label,
    )

    created: list[CreatedFlow] = []
    minted_objects: set[str] = set()
    for row in ordered:
        object_id = object_id_by_uuid.get(row.source_uuid, "")
        flow_object = objects_by_id.get(object_id)
        if flow_object is None:
            continue
        context_iri = context_iri_by_uuid[row.source_uuid]
        record = _add_created_flow(
            row=row,
            flow_object=flow_object,
            context_iri=context_iri,
            flow_unit=unit_by_flow.get((object_id, context_iri)),
            # Off the record rather than the report row: a fix that rebased this
            # row's unit stated the factor, and the mapping this creation
            # publishes is the only place it can be said.
            conversion=conversion_from_source_flow(
                source_flow_by_uuid.get(row.source_uuid)
            ),
            units_index=units_index,
            indexes=indexes,
            accumulator=accumulator,
            minted_flow_object=object_id not in minted_objects,
        )
        minted_objects.add(object_id)
        created.append(record)

    for object_id, flow_object in objects_by_id.items():
        indexes.flow_objects_by_id[object_id] = flow_object
        indexes.flow_object_label_by_id[object_id] = flow_label_value(flow_object) or ""

    name_only = sum(1 for record in created if record.identity_is_name_only)
    logger.info(
        "created_flows_for_unmatched_rows",
        source_row_count=len(rows),
        flow_object_count=len(objects_by_id),
        elementary_flow_count=len(created),
        name_only_flow_count=name_only,
        blocked_object_count=len(blocked_object_ids),
        # Nested rather than splatted: `resolve_flow_layers` reports a
        # `flow_object_count` of its own, and flattening both would silently
        # overwrite the count above with the pre-collision-guard one.
        layer_stats=layer_stats,
        typing_stats=dict(typing_stats),
        family_stats=family_stats,
        ion_stats=ion_stats,
    )
    return list(objects_by_id.values()), created


def _unit_by_flow(
    rows: list[UnmatchedRow],
    *,
    object_id_by_uuid: dict[str, str],
    context_iri_by_uuid: dict[str, str],
    source_label: str,
) -> dict[tuple[str, str], CreatedFlowUnit]:
    """The unit each about-to-be-created flow states, and how it was decided.

    Two source rows naming the same substance in the same context become one
    flow -- that is what keeps ``(flow_object_id, context_iri)`` unique -- and
    they do not always arrive in the same unit.  BAFU ships its road noise in
    kilometres and again in metres, and its waste heat in megajoules and again
    in kilowatt-hours (#70, #78).

    Whichever row reached `_add_created_flow` first used to decide, so the
    published unit was a function of file order: the lorry came out in metres
    and the passenger car in kilometres, from one list, on one day.

    :func:`~brightway_flows.merge.unit_changes.decide_created_flow_unit`
    decides it now, from a curated row where there is one and from the unit
    table otherwise, and says which -- see that module for the order.  Every
    group gets an entry, including the ones whose rows all agree: a caller
    asking what a flow states should not have to know whether anything was in
    dispute.
    """
    units_by_flow: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for row in rows:
        object_id = object_id_by_uuid.get(row.source_uuid, "")
        context_iri = context_iri_by_uuid.get(row.source_uuid, "")
        unit = str(row.source_unit or "").strip()
        if not object_id or not context_iri or not unit:
            continue
        units_by_flow.setdefault((object_id, context_iri), []).append(
            (unit, row.source_uuid)
        )

    decisions = created_flow_unit_decisions(source_label)
    decided: dict[tuple[str, str], CreatedFlowUnit] = {}
    for key, pairs in units_by_flow.items():
        decision = decide_created_flow_unit(
            [unit for unit, _uuid in pairs],
            source_uuids=[uuid for _unit, uuid in pairs],
            decisions=decisions,
        )
        decided[key] = decision
        if not decision.rows_disagree:
            continue
        log = logger.warning if decision.decided_by == UNDECIDED else logger.info
        log(
            "created_flow_rows_disagree_about_the_unit",
            flow_object_id=key[0], context_iri=key[1],
            units=list(decision.units), declared=decision.declared,
            decided_by=decision.decided_by,
        )
    return decided

def _harmonised_context_iri(row: UnmatchedRow, indexes: MergeIndexes) -> str:
    context_iri = indexes.context_expectations.resolve(
        row.source_uuid, row.source_context, row.source_name
    ) or ""
    if not context_iri:
        raise ValueError(
            f"No harmonised context IRI for source flow {row.source_uuid!r} "
            f"({row.source_name!r}, context={row.source_context!r}). "
            f"All source contexts must map to a known harmonised context."
        )
    # And the same refinement a matched row gets: a withdrawal whose material
    # names the body it was drawn from is minted *in* that body.  Applied here
    # as well because a material whose object does not exist yet arrives on this
    # path rather than the matching one -- BAFU's `Water, process, surface` is
    # the first flow surface water has ever had -- and a rule that placed a
    # matched row in a lake and a created one in an unstated body would be two
    # rules wearing one name.
    refined_iri, refined_body = water_body_from_material(
        material=material_for_source_flow(
            indexes.source.source_label, row.source_uuid
        ),
        source_context_iri=context_iri,
    )
    return refined_iri if refined_body else context_iri


def _add_created_flow(
    *,
    row: UnmatchedRow,
    flow_object: FlowObject,
    context_iri: str,
    units_index: Any,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
    minted_flow_object: bool,
    flow_unit: CreatedFlowUnit | None = None,
    conversion: UnitConversion | None = None,
) -> CreatedFlow:
    """Add one elementary flow for *row* on *flow_object*, and report it.

    When the object already has a flow in this context -- two source rows naming
    the same substance in the same place -- the second row is recorded on the
    first row's flow rather than duplicating it, which is what keeps
    ``(flow_object_id, context_iri)`` unique.  That flow is always one this call
    created: an object any other part of the merge had already put a flow on was
    refused before reaching here.

    *flow_unit* is what the flow states and how that was decided, computed for
    the whole group by :func:`_unit_by_flow`.  The row's own unit is unchanged
    everywhere it is recorded -- the source ref and the concept association both
    keep it, because it is what the source list says and this list does not get
    to restate it.  No `qudt:conversionMultiplier` is written for the
    difference: these are two spellings of one scale and `units.json` already
    converts between them, which is the same test every other conversion here
    passes.

    A row whose own unit is not the one the flow states is returned with
    ``has_unit_mismatch``, which means on a creation exactly what it means on a
    match: this source row is measured in something other than the flow it
    landed on (#78).

    *conversion* is the one case where the row's own unit is **not** what the
    mapping keeps, and it is the opposite of the paragraph above rather than an
    exception to it.  A manual fix rebased this row from the unit the vendor
    ships onto the one the flow is created in, across a quantity kind
    `units.json` has no factor for, and stated that factor itself.  The row is
    being carried in a unit the vendor did not use, so the mapping states the
    vendor's and publishes the factor beside it.  Applied only if it still holds
    between the two units in hand.
    """
    object_id = flow_object.flow_object_id
    declared_unit = flow_unit.declared if flow_unit else ""
    stated_unit = declared_unit or row.source_unit
    resolved_unit = (
        resolve_unit_notation(stated_unit, units_index) if stated_unit else None
    )
    unit_iri = (resolved_unit[1] or "") if resolved_unit else ""
    unit_mismatch = bool(
        row.source_unit and declared_unit and row.source_unit != declared_unit
    )
    provenance = _build_match_provenance(
        source_uuid=row.source_uuid,
        source_name=row.source_name,
        source=indexes.source,
        mapping_file=indexes.mapping_file,
        merge_method=CREATION_MERGE_METHOD,
        merge_basis=str(row.reason),
    )
    # What the *mapping* says, which is the vendor's unit where a fix rebased
    # the row, and the row's own unit everywhere else.
    provenance_unit = conversion.source_unit if conversion else row.source_unit
    conversion_factor = (
        conversion.factor
        if conversion is not None
        and conversion.holds_between(
            source_unit=provenance_unit, target_unit=stated_unit
        )
        else None
    )

    existing = accumulator.flows_for_object_in_context(object_id, context_iri)
    if existing:
        target = existing[0]
        _append_source_ref(
            target,
            source=indexes.source,
            source_uuid=row.source_uuid,
            source_name=row.source_name,
            source_shipped_name=row.source_shipped_name or "",
            source_context=row.source_context,
            source_unit=provenance_unit,
            source_cas=row.source_cas,
            source_ec=row.source_ec,
            merge_basis=str(row.reason),
            merge_method=CREATION_MERGE_METHOD,
            selector_reason=CREATION_SELECTOR_REASON,
            mapping_file=indexes.mapping_file or "",
            provenance=provenance,
            conversion_factor=conversion_factor,
        )
        _append_concept_association(
            target,
            source=indexes.source,
            source_uuid=row.source_uuid,
            source_name=row.source_name,
            source_context=row.source_context,
            source_unit=provenance_unit,
            # Exact, as for a flow added in a missing context: this row is the
            # only reason the flow exists, so it is that flow rather than a
            # narrower reading of it.
            map_type_curie=SKOS_EXACT_MATCH_CURIE,
            provenance=provenance,
            conversion_factor=conversion_factor,
        )
        elementary_flow_id = target.elementary_flow_id
    else:
        elementary_flow_id = minted_elementary_flow_id(object_id, context_iri)
        accumulator.add_flow(ElementaryFlow(
            elementary_flow_id=elementary_flow_id,
            flow_object_id=object_id,
            # The source string a merge-created flow already carries.  A new one
            # would have to be added to the sync's filter and to
            # `SourceList.addition_sources` as well, and a value that is not in
            # both produces flows that are silently never written.  What kind of
            # creation this was is in the report, which is where it belongs.
            source=indexes.source.algorithm_addition_source,
            source_refs=[{
                "list_name": indexes.source.list_name,
                "list_version": indexes.source.list_version,
                "source_flow_uuid": row.source_uuid,
                "source_flow_name": row.source_shipped_name or row.source_name,
                "source_metadata": {
                    "original_context": row.source_context,
                    "unit": provenance_unit,
                    "cas_number": row.source_cas,
                    "ec_number": row.source_ec,
                    "merge_basis": str(row.reason),
                    "merge_method": CREATION_MERGE_METHOD,
                    "selector_reason": CREATION_SELECTOR_REASON,
                    "notes": "",
                    "extra_fields": {},
                    "mapping_file": indexes.mapping_file or "",
                    "provenance": provenance,
                    "merge_details": {},
                    **(
                        {QUDT_CONVERSION_MULTIPLIER_CURIE: conversion_factor}
                        if conversion_factor is not None
                        else {}
                    ),
                },
            }],
            context=_context_for_new_flow(context_iri),
            context_iri=context_iri,
            unit=stated_unit,
            unit_iri=unit_iri,
            lcia_methods=[],
            general_comment="",
            concept_associations=[{
                "@type": XKOS_CONCEPT_ASSOCIATION_CURIE,
                XKOS_SOURCE_CONCEPT_CURIE: {
                    "@id": f"{indexes.source.flow_iri_prefix}{row.source_uuid}",
                    SKOS_PREF_LABEL_CURIE: row.source_name,
                    "context": " / ".join(str(x) for x in row.source_context if x),
                    **(
                        {QUDT_HAS_UNIT_CURIE: {"@id": source_unit_iri}}
                        if (source_unit_iri := unit_iri_for(provenance_unit))
                        else {}
                    ),
                    SKOS_EXACT_MATCH_CURIE: {
                        "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{elementary_flow_id}",
                    },
                },
                XKOS_TARGET_CONCEPT_CURIE: {
                    "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{elementary_flow_id}",
                },
                "provenance": provenance,
                **(
                    {QUDT_CONVERSION_MULTIPLIER_CURIE: conversion_factor}
                    if conversion_factor is not None
                    else {}
                ),
            }],
            # The substance keys, in the bag the record keeps undeclared keys
            # in; see `_inherited_flow_object_fields`.
            extra=_inherited_flow_object_fields(flow_object),
        ))

    cas = _classification_values(flow_object, CHEMINF_CAS_REGISTRY_NUMBER)
    ec = _classification_values(flow_object, CHEMINF_EC_NUMBER)
    return CreatedFlow(
        source_uuid=row.source_uuid,
        source_name=row.source_name,
        source_context=list(row.source_context),
        source_context_iri=context_iri,
        source_unit=row.source_unit,
        source_cas=row.source_cas,
        source_ec=row.source_ec,
        flow_object_id=object_id,
        flow_object_label=flow_label_value(flow_object) or "",
        flow_object_cas=cas,
        flow_object_ec=ec,
        new_elementary_flow_id=elementary_flow_id,
        minted_flow_object=minted_flow_object,
        # The number to watch run to run.  A third of these substances have no
        # CAS and no EC anywhere upstream, and a name-only object is the correct
        # outcome for a name-only source; a *jump* in this count means
        # enrichment regressed.
        identity_is_name_only=not cas and not ec,
        has_unit_mismatch=unit_mismatch,
        unit_decision=flow_unit.to_dict() if flow_unit else {},
        provenance=provenance,
        unmatched_basis=row.basis or None,
    )
