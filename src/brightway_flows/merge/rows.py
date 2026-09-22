"""What happens to one source row, and the loop that walks the source list.

:func:`match_source_rows` is the loop; the rest of the module is the routes one
row can take through it.  Two of those are handled here.

:func:`apply_prepared_decision` runs first: if a curator has already decided
where this source flow belongs, that decision is honoured rather than re-derived.

:func:`resolve_unselected_row` runs last: matching has identified the flow object
but no elementary flow in it covers the row's context, so either add one or
report the row for review.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import structlog

from brightway_flows.domain.elementary_flow import (
    ElementaryFlow,
    minted_elementary_flow_id,
)
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.units import unit_iri_for
from brightway_flows.domain.vocabulary import (
    CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX,
    QUDT_HAS_UNIT_CURIE,
    SKOS_CLOSE_MATCH_CURIE,
    SKOS_EXACT_MATCH_CURIE,
    SKOS_PREF_LABEL_CURIE,
    XKOS_CONCEPT_ASSOCIATION_CURIE,
    XKOS_SOURCE_CONCEPT_CURIE,
    XKOS_TARGET_CONCEPT_CURIE,
)
from brightway_flows.match_overrides import admitted_prepared_rows
from brightway_flows.merge.additions import _inherited_flow_object_fields
from brightway_flows.domain.context_registry import context_display_parts
from brightway_flows.merge.contexts import (
    context_contradicts,
    water_body_from_material,
    _context_for_new_flow,
)
from brightway_flows.merge.conversions import (
    UnitConversion,
    conversion_from_prepared_rows,
    conversion_from_source_flow,
)
from brightway_flows.merge.unit_changes import published_unit_for
from brightway_flows.merge.matching import (
    _record_unmatched_row,
    _select_elementary_flow,
    _source_labels,
    resolve_flow_object,
)
from brightway_flows.merge.prepared import (
    _pick_expected_context_target,
    _resolve_active_prepared_target,
)
from brightway_flows.merge.prepared_context_decisions import (
    PreparedContextDecision,
)
from brightway_flows.merge.provenance import (
    _append_concept_association,
    _append_source_ref,
    _build_match_provenance,
)
from brightway_flows.merge.report import (
    AlgorithmMatch,
    PreparedMatch,
    UnmatchedReason,
    UnmatchedRow,
)
from brightway_flows.merge.species import canonicalized_for_matching
from brightway_flows.merge.state import (
    MatchAttempt,
    MergeAccumulator,
    MergeIndexes,
    SourceRow,
)
from brightway_flows.transformers.unit_normalization import resolve_unit_notation

logger = structlog.get_logger(__name__)


def _log_conversion_dropped(
    *,
    row: SourceRow,
    conversion: UnitConversion,
    target_unit: str,
    target_elementary_flow_id: str,
    route: str,
    source_key: str,
) -> None:
    """Report a factor the merge declined to carry onto the pair it built.

    Logged rather than raised, and rather than passed through: a factor whose
    units no longer line up is a mapping to look at, but one of them should not
    stop a merge, and recording it anyway would convert an amount by a number
    measured for some other pair.
    """
    logger.warning(
        "conversion_factor_units_do_not_match_pair",
        source_list=source_key,
        source_flow_uuid=row.uuid,
        source_flow_name=row.name,
        route=route,
        factor=conversion.factor,
        stated_source_unit=conversion.source_unit,
        stated_target_unit=conversion.target_unit,
        actual_source_unit=row.unit,
        actual_target_unit=target_unit,
        target_elementary_flow_id=target_elementary_flow_id,
    )


#: Selector outcomes that mean "the right flow object, but no flow in this
#: context yet" -- the only cases where creating a flow is justified. Any other
#: failure is ambiguity, and is reported rather than guessed at.
#:
#: For an emission row this is a ruling, not a fallback (#186).  The stated
#: sub-compartment is the vendor's statement of where the release went, and a
#: scorer preference that coarsened river rows onto Surface water instead --
#: a water body outranking the Long-term time bucket -- was built, measured,
#: and declined: it re-decided 273 BAFU and Stepwise rows and retired their
#: published river flows, for a question the vendor had already answered.  The
#: minted flow links the existing substance and may carry no factors; factor
#: recovery is deliberate later work (#138), never a reason to land a row
#: somewhere it did not say.  Resource rows are the opposite case -- a wrong
#: sub-context there is a data error, and those rows are re-filed by the
#: context rules and manual fixes before matching runs.
_CREATABLE_SELECTOR_REASONS = frozenset({
    "no-candidates-same-dimension-media",
    "tied-elementary-candidates",
    # Everything that fit the row named a place the row denies.  The row's own
    # place is known -- it is what the disagreement was measured against -- so
    # the flow to create is not a guess (#85).
    "context-contradiction",
    # Nothing that fit the row was in the place the row named, and that place is
    # one this list holds.  Same argument as the line above, one step weaker:
    # there the candidates disagreed with the row, here they merely say less
    # than it does.  Creating is still right, because the alternative is to
    # publish a row that named a compartment on a flow that does not have one,
    # and which flow that turns out to be depends on what the merge had reached
    # by then (#112).
    "no-candidate-in-stated-context",
})


def resolve_unselected_row(
    *,
    row: SourceRow,
    match: MatchAttempt,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> None:
    """Handle a row whose flow object is known but whose elementary flow is not.

    Adds an elementary flow in the harmonised context when the selector failed
    only because that context was missing; otherwise records the row as
    unmatched. Either way the row is finished, so the caller moves on.
    """
    if match.selector_reason in _CREATABLE_SELECTOR_REASONS:
        if _add_flow_in_missing_context(
            row=row,
            match=match,
            indexes=indexes,
            accumulator=accumulator,
        ):
            return
    _record_unmatched(row=row, match=match, accumulator=accumulator)


def _add_flow_in_missing_context(
    *,
    row: SourceRow,
    match: MatchAttempt,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
    merge_method: str = "algorithmic_fallback",
    matching_method: str = "algorithm",
) -> bool:
    """Add an elementary flow for *row*'s context, if that context is not covered.

    Returns False when the flow object already has a flow in that context, in
    which case the row is ambiguous rather than missing and belongs in the
    unmatched report.

    *merge_method* and *matching_method* say how the substance in *match* was
    arrived at, and default to what matching does.  A correspondence table
    reaches here too -- it names the substance and the compartment stays the
    row's own (#84) -- and a report calling that an algorithmic match would
    name the wrong route for a decision a curator made.

    :raises ValueError: if the source context maps to no harmonised context IRI.
        Every context the source list uses must be registered; guessing one would
        put the flow somewhere arbitrary.
    """
    # `resolve`, not the compartment rule alone: this places one row, and the
    # row is in hand.  Reading the compartment here and the row's own rules
    # everywhere else meant a flow whose name or uuid says which context it
    # belongs in was created in whichever one its compartment defaults to --
    # ecoinvent land transformation into land occupation (#52).
    harmonised_iri = indexes.context_expectations.resolve(
        row.uuid, row.context, row.name
    ) or ""
    if not harmonised_iri:
        raise ValueError(
            f"No harmonised context IRI for {indexes.source.key} flow {row.uuid!r} "
            f"({row.name!r}, context={row.context!r}). "
            f"Every {indexes.source.key} context must map to a known harmonised "
            f"context: add a row with source {indexes.source.source_label!r} to "
            f"context-manual-mapping.json."
        )

    if accumulator.flows_for_object_in_context(match.flow_object_id, harmonised_iri):
        return False

    # The new flow states the unit this list publishes the row's quantity kind
    # in, where that differs on the same scale -- a becquerel row mints a
    # kilobecquerel flow beside EF 3.1's 954 kilobecquerel flows, rather than
    # whichever spelling reached this line first becoming the published unit
    # (#142).  The row keeps its own unit on its source ref and its concept
    # association, and no multiplier is published for the difference:
    # `units.json` already converts between two spellings of one scale.
    published = published_unit_for([row.unit] if row.unit else [])
    stated_unit = published or row.unit
    stated_unit_iri = unit_iri_for(published) if published else row.unit_iri

    context_strings = indexes.consensus_context_strings.get(harmonised_iri, row.context)
    new_elem_id = minted_elementary_flow_id(match.flow_object_id, harmonised_iri)
    provenance = _build_match_provenance(
        source_uuid=row.uuid,
        source_name=row.name,
        source=indexes.source,
        mapping_file=indexes.mapping_file,
        merge_method=merge_method,
        merge_basis=match.basis,
        merge_basis_value=match.basis_value,
        selector_reason="new-elementary-flow-created",
        algorithm_details=match.selector_details,
    )
    flow_object = indexes.flow_objects_by_id.get(match.flow_object_id)
    accumulator.add_flow(ElementaryFlow(
        elementary_flow_id=new_elem_id,
        flow_object_id=match.flow_object_id,
        source=indexes.source.algorithm_addition_source,
        source_refs=[{
            "list_name": indexes.source.list_name,
            "list_version": indexes.source.list_version,
            "source_flow_uuid": row.uuid,
            "source_flow_name": row.vendor_name,
            "source_metadata": {
                "original_context": row.context,
                "unit": row.unit,
                "cas_number": row.cas,
                "ec_number": row.ec,
                "merge_basis": match.basis,
                "merge_method": merge_method,
                "selector_reason": "new-elementary-flow-created",
                "notes": "",
                "extra_fields": {},
                "mapping_file": indexes.mapping_file,
                "provenance": provenance,
                "merge_details": match.selector_details,
            },
        }],
        context=_context_for_new_flow(harmonised_iri),
        context_iri=harmonised_iri,
        unit=stated_unit,
        unit_iri=stated_unit_iri,
        lcia_methods=[],
        general_comment="",
        concept_associations=[{
            "@type": XKOS_CONCEPT_ASSOCIATION_CURIE,
            XKOS_SOURCE_CONCEPT_CURIE: {
                "@id": f"{indexes.source.flow_iri_prefix}{row.uuid}",
                SKOS_PREF_LABEL_CURIE: row.name,
                "context": " / ".join(str(x) for x in row.context if x),
                **(
                    {QUDT_HAS_UNIT_CURIE: {"@id": unit_iri}}
                    if (unit_iri := unit_iri_for(row.unit))
                    else {}
                ),
                SKOS_EXACT_MATCH_CURIE: {
                    "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{new_elem_id}",
                },
            },
            XKOS_TARGET_CONCEPT_CURIE: {
                "@id": f"{CONSENSUS_ELEMENTARY_FLOW_IRI_PREFIX}{new_elem_id}",
            },
            "provenance": provenance,
        }],
        # The substance keys, in the bag the record keeps undeclared keys in;
        # see `_inherited_flow_object_fields`.  A flow object the merge cannot
        # find leaves them absent, which is what the payload build did.
        extra=(
            _inherited_flow_object_fields(flow_object)
            if flow_object is not None else {}
        ),
    ))
    accumulator.algorithm_matches.append(AlgorithmMatch(
        source_uuid=row.uuid,
        source_name=row.name,
        source_context=row.context,
        source_context_normalized=row.context_normalized,
        source_context_iri=row.context_iri or "",
        source_unit=row.unit,
        source_cas=row.cas,
        source_ec=row.ec,
        flow_object_id=match.flow_object_id,
        target_name=indexes.flow_object_label_by_id.get(match.flow_object_id, ""),
        target_elementary_flow_id=new_elem_id,
        target_context=context_strings,
        target_unit=stated_unit,
        basis=match.basis,
        basis_value=match.basis_value,
        selector_reason="new-elementary-flow-created",
        matching_method=matching_method,
        algorithm_details=match.selector_details,
        provenance=provenance,
    ))
    return True


def _record_unmatched(
    *,
    row: SourceRow,
    match: MatchAttempt,
    accumulator: MergeAccumulator,
) -> None:
    """Report a row whose elementary flow could not be chosen unambiguously."""
    accumulator.unmatched.append(UnmatchedRow(
        source_uuid=row.uuid,
        source_name=row.name,
        source_shipped_name=row.shipped_name or None,
        source_context=row.context,
        source_unit=row.unit,
        source_cas=row.cas,
        source_ec=row.ec,
        candidate_flow_object_ids=[match.flow_object_id],
        candidate_elementary_flow_ids=sorted(
            x.elementary_flow_id for x in match.candidates
        ),
        candidate_elementary_flows=match.selector_details.get("scored_candidates", []),
        # Coerced rather than assigned: a selection failure the selector learns
        # to report but nobody adds a category for should fail here, rather
        # than become another value nothing counts.
        reason=UnmatchedReason(match.selector_reason),
        basis=match.basis,
        basis_value=match.basis_value,
        matching_method="algorithm",
        algorithm_details=match.selector_details,
    ))


def apply_prepared_decision(
    *,
    row: SourceRow,
    prepared_rows: list[dict[str, Any]],
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> bool:
    """Honour a curator's existing decision about where this source flow belongs.

    Returns True when the row is finished -- matched, or reported as unmatched.
    Returns False when the caller should fall through to algorithmic matching,
    which happens for a decision explicitly marked ``"reject"``: the curator has
    said the prepared mapping is wrong, not that the row has no home.
    """
    target_uuids = sorted({
        str((r.get("target") or {}).get("uuid") or "").strip()
        for r in prepared_rows
        if isinstance(r, dict)
    })
    target_uuids = [x for x in target_uuids if x]
    if len(target_uuids) != 1:
        accumulator.unmatched.append(UnmatchedRow(
            source_uuid=row.uuid,
            source_name=row.name,
            source_shipped_name=row.shipped_name or None,
            source_context=row.context,
            source_unit=row.unit,
            source_cas=row.cas,
            source_ec=row.ec,
            reason=UnmatchedReason.PREPARED_MATCH_MULTIPLE_TARGETS,
            candidate_target_uuids=target_uuids,
        ))
        return True

    target_uuid = target_uuids[0]
    decision = indexes.prepared_context_decisions.get((row.uuid, target_uuid))
    decision_action = (
        decision.decision if decision is not None else PreparedContextDecision.MAPPED
    )
    if decision_action is PreparedContextDecision.REJECT:
        # Explicit override: the prepared mapping is wrong, so fall back to
        # matching this row like any other.
        return False

    (
        resolved_target_uuid,
        target_row,
        target_trace,
        target_resolution,
    ) = _resolve_active_prepared_target(
        target_uuid,
        all_by_elem_id=accumulator.all_by_elem_id,
        active_by_elem_id=accumulator.by_elem_id,
    )

    # Two reasons to move the row onto a flow of the *same substance* in the
    # compartment the row itself named, and one piece of code for both.
    #
    # The curator may have marked this pairing `expected`, which says in so many
    # words that the target does not cover the row's context.
    #
    # Or the target may sit somewhere the row denies.  EF 3.1 has no forestry
    # soil compartment, so a table mapping an ecoinvent `soil / forestry` row
    # onto `Emissions to non-agricultural soil` is naming the nearest flow EF
    # has -- the only thing a correspondence table can do here, and the
    # substance it names is the curated part.  Reading the compartment off it as
    # well is what made where a forestry emission is published depend on whether
    # EF happens to ship the substance: atrazine non-agricultural because a
    # table covered it, pyrethrins silvicultural because none did, with nothing
    # about the two emissions different (#84).
    denies_row_context = target_row is not None and context_contradicts(
        row.context_iri, (target_row.context_iri or "").strip()
    )
    if target_row is not None and (
        decision_action is PreparedContextDecision.EXPECTED or denies_row_context
    ):
        object_id = target_row.flow_object_id
        in_row_context = (
            accumulator.flows_for_object_in_context(object_id, row.context_iri)
            if row.context_iri and object_id
            else []
        )
        chosen_uuid, chosen_row = _pick_expected_context_target(
            candidates=in_row_context,
            source_unit=row.unit,
        )
        if chosen_uuid and chosen_row is not None:
            resolved_target_uuid = chosen_uuid
            # Re-resolved through the active index rather than used as handed
            # back.  `elementary_by_object` holds the rows the pass *loaded*,
            # while `merged_elementary` -- what gets written -- holds deep
            # copies of them, so appending the source ref and the association
            # to a candidate writes them to a record no writer ever reads.
            # `record_algorithmic_match` takes the same step for the same
            # reason.
            target_row = accumulator.by_elem_id.get(chosen_uuid, chosen_row)
            target_resolution = (
                "manual-expected-context-target"
                if decision_action is PreparedContextDecision.EXPECTED
                else "source-context-target"
            )
            target_trace = target_trace + [chosen_uuid]
        elif denies_row_context:
            # Nothing of this substance in the row's compartment yet, so the row
            # brings it into being.  Only a contradiction gets this far: an
            # `expected` decision on a target the row does not deny says the
            # target is the right flow anyway, and asks for a better one only if
            # one is already there.
            return _mint_flow_in_row_context(
                row=row,
                target_row=target_row,
                target_uuid=target_uuid,
                resolved_target_uuid=resolved_target_uuid,
                target_resolution=target_resolution,
                target_trace=target_trace,
                decision_action=decision_action,
                indexes=indexes,
                accumulator=accumulator,
            )

    if target_row is None:
        accumulator.unmatched.append(UnmatchedRow(
            source_uuid=row.uuid,
            source_name=row.name,
            source_shipped_name=row.shipped_name or None,
            source_context=row.context,
            source_unit=row.unit,
            source_cas=row.cas,
            source_ec=row.ec,
            # The target it could not resolve, and how far it got, are the
            # three fields below -- they do not belong in the category too.
            reason=UnmatchedReason.PREPARED_TARGET_NOT_FOUND,
            target_elementary_flow_id=target_uuid,
            prepared_target_resolution=target_resolution,
            prepared_target_trace=target_trace,
        ))
        return True

    _record_prepared_match(
        row=row,
        prepared_rows=prepared_rows,
        target_row=target_row,
        target_uuid=target_uuid,
        resolved_target_uuid=resolved_target_uuid,
        target_resolution=target_resolution,
        target_trace=target_trace,
        decision_action=decision_action,
        indexes=indexes,
        accumulator=accumulator,
    )
    return True


def _mint_flow_in_row_context(
    *,
    row: SourceRow,
    target_row: ElementaryFlow,
    target_uuid: str,
    resolved_target_uuid: str,
    target_resolution: str,
    target_trace: list[str],
    decision_action: PreparedContextDecision,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> bool:
    """Give *row* a flow of its table's substance, in the compartment *row* named.

    Reached when a correspondence table points at a flow whose context the row's
    own denies, and the substance has nothing yet in the row's compartment.  The
    substance is kept -- it is the curated half of the table's answer, and
    re-deriving it from the name and the CAS number would throw that away -- and
    the compartment comes from the row (#84).

    The flow this creates is the same one the algorithmic path would have
    created for a row of this substance that no table happened to cover, which
    is the whole point: the two rows stop coming out in different places.

    Returns True in every case, because the row is finished either way -- as
    every other path out of :func:`apply_prepared_decision` is.
    """
    contradicting_iri = (target_row.context_iri or "").strip()
    details = {
        "selector_model": "prepared-target;context-not-publishable",
        "prepared_target_uuid": target_uuid,
        "resolved_target_uuid": resolved_target_uuid,
        "rejected_contradicting_context_iri": contradicting_iri,
        "source_context_iri": row.context_iri,
        "prepared_target_resolution": target_resolution,
        "prepared_target_trace": target_trace,
        "prepared_context_decision": decision_action.value,
    }

    object_id = target_row.flow_object_id or ""
    created = bool(object_id) and _add_flow_in_missing_context(
        row=row,
        match=MatchAttempt(
            flow_object_id=object_id,
            candidates=[],
            selected=None,
            selector_reason=UnmatchedReason.CONTEXT_CONTRADICTION,
            selector_details=details,
            basis="prepared_mapping",
            basis_value=target_uuid,
        ),
        indexes=indexes,
        accumulator=accumulator,
        merge_method="randonneur_replace_table",
        matching_method="prepared",
    )
    if created:
        return True

    # Two ways to arrive here and neither can happen from a well-formed build: a
    # published flow with no substance on it, or a substance that turns out to
    # have a flow in this context after the lookup above said it had none.  The
    # row is reported rather than forced, because the one thing not to do with a
    # row whose context is in doubt is publish it in the context this branch
    # exists to refuse.
    accumulator.unmatched.append(UnmatchedRow(
        source_uuid=row.uuid,
        source_name=row.name,
        source_shipped_name=row.shipped_name or None,
        source_context=row.context,
        source_unit=row.unit,
        source_cas=row.cas,
        source_ec=row.ec,
        reason=UnmatchedReason.CONTEXT_CONTRADICTION,
        candidate_flow_object_ids=[object_id] if object_id else [],
        target_elementary_flow_id=resolved_target_uuid or target_uuid,
        prepared_target_resolution=target_resolution,
        prepared_target_trace=target_trace,
        algorithm_details=details,
    ))
    return True


def _record_prepared_match(
    *,
    row: SourceRow,
    prepared_rows: list[dict[str, Any]],
    target_row: ElementaryFlow,
    target_uuid: str,
    resolved_target_uuid: str,
    target_resolution: str,
    target_trace: list[str],
    decision_action: PreparedContextDecision,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> None:
    """Attach the source flow to its prepared target and record the match."""
    target_object_id = target_row.flow_object_id

    # A conversion factor is present when source and target differ in unit or in
    # substance basis (e.g. mineral mass -> elemental content).  Checked against
    # the pair actually being recorded rather than taken on trust: the target the
    # table named can have been redirected -- to a replacement for a deprecated
    # flow, or by an "expected" decision, which picks a candidate by the *source*
    # row's unit and would hand a kg->MJ factor to a kg->kg pair.
    conversion = conversion_from_prepared_rows(prepared_rows) or row.conversion
    target_unit = target_row.unit or ""
    conversion_factor: float | None = None
    conversion_comment = ""
    if conversion is not None:
        if conversion.holds_between(
            source_unit=row.provenance_unit, target_unit=target_unit
        ):
            conversion_factor = conversion.factor
            conversion_comment = conversion.comment
        else:
            _log_conversion_dropped(
                row=row,
                conversion=conversion,
                target_unit=target_unit,
                target_elementary_flow_id=resolved_target_uuid,
                route="prepared_mapping",
                source_key=indexes.source.key,
            )

    provenance = _build_match_provenance(
        source_uuid=row.uuid,
        source_name=row.name,
        source=indexes.source,
        mapping_file=indexes.mapping_file,
        merge_method="randonneur_replace_table",
        merge_basis="prepared_mapping",
    )
    _append_source_ref(
        target_row,
        source=indexes.source,
        source_uuid=row.uuid,
        source_name=row.name,
        source_shipped_name=row.shipped_name,
        source_context=row.context,
        source_unit=row.provenance_unit,
        source_cas=row.cas,
        source_ec=row.ec,
        merge_basis="prepared_mapping",
        merge_method="randonneur_replace_table",
        selector_reason="direct-target-uuid",
        mapping_file=indexes.mapping_file,
        provenance=provenance,
        conversion_factor=conversion_factor,
        merge_details={
            "prepared_target_uuid": target_uuid,
            "resolved_target_uuid": resolved_target_uuid,
            "prepared_target_resolution": target_resolution,
            "prepared_target_trace": target_trace,
            "prepared_row_count": len(prepared_rows),
            "prepared_context_decision": decision_action.value,
        },
    )
    _append_concept_association(
        target_row,
        source=indexes.source,
        source_uuid=row.uuid,
        source_name=row.name,
        source_context=row.context,
        source_unit=row.provenance_unit,
        map_type_curie=SKOS_EXACT_MATCH_CURIE,
        provenance=provenance,
        conversion_factor=conversion_factor,
    )

    entry: dict[str, Any] = {
        "source_uuid": row.uuid,
        "source_name": row.name,
        "source_context": row.context,
        "source_context_iri": row.context_iri or "",
        "source_unit": row.unit,
        "source_cas": row.cas,
        "target_elementary_flow_id": resolved_target_uuid,
        "prepared_target_elementary_flow_id": target_uuid,
        "target_flow_object_id": target_object_id,
        "target_name": indexes.flow_object_label_by_id.get(target_object_id, ""),
        "target_context": context_display_parts(target_row.context),
        "target_unit": target_row.unit or "",
        "prepared_target_resolution": target_resolution,
        "prepared_target_trace": target_trace,
        "prepared_context_decision": decision_action.value,
        "provenance": provenance,
    }
    # Published if there is one, without asking again whether it is worth
    # publishing: `UnitConversion.holds_between` is where that is decided.
    # See `merge/conversions.py`.
    if conversion_factor is not None:
        entry["conversion_factor"] = conversion_factor
        if conversion_comment:
            entry["conversion_comment"] = conversion_comment
    accumulator.prepared_matches.append(PreparedMatch(**entry))


def record_algorithmic_match(
    *,
    row: SourceRow,
    match: MatchAttempt,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
    conversion: UnitConversion | None = None,
) -> None:
    """Attach a source flow to the elementary flow matching chose for it.

    The selected flow must still be resolvable: it needs an id, and that id must
    name a flow in the active index. Either failure is reported rather than
    raised, because one bad row should not stop the merge.

    *conversion* is whatever the correspondence table said about this source
    flow, or -- for a list that has no table -- what a manual fix said when it
    rebased the row's unit.  Worth carrying even though matching, not the
    table, chose the target: a row reaches here when a curator rejected the
    table's target, and rejecting a target does not repeal the substance's
    calorific value.  It is applied only if the pair matching built still has
    the units the factor was stated between.
    """
    elem_id = match.selected.elementary_flow_id if match.selected else ""
    if not elem_id:
        _record_unmatched_row(
            row=row,
            accumulator=accumulator,
            reason=UnmatchedReason.SELECTED_ELEMENTARY_FLOW_MISSING_ID,
        )
        return

    target_row = accumulator.by_elem_id.get(elem_id)
    if target_row is None:
        _record_unmatched_row(
            row=row,
            accumulator=accumulator,
            reason=UnmatchedReason.SELECTED_ELEMENTARY_FLOW_NOT_FOUND,
        )
        return

    provenance = _build_match_provenance(
        source_uuid=row.uuid,
        source_name=row.name,
        source=indexes.source,
        mapping_file=indexes.mapping_file,
        merge_method="algorithmic_fallback",
        merge_basis=match.basis,
        merge_basis_value=match.basis_value,
        selector_reason=match.selector_reason,
        algorithm_details=match.selector_details,
    )
    target_unit = target_row.unit or ""
    conversion_factor: float | None = None
    if conversion is not None:
        if conversion.holds_between(
            source_unit=row.provenance_unit, target_unit=target_unit
        ):
            conversion_factor = conversion.factor
        else:
            _log_conversion_dropped(
                row=row,
                conversion=conversion,
                target_unit=target_unit,
                target_elementary_flow_id=elem_id,
                route="algorithmic_fallback",
                source_key=indexes.source.key,
            )
    _append_source_ref(
        target_row,
        source=indexes.source,
        source_uuid=row.uuid,
        source_name=row.name,
        source_shipped_name=row.shipped_name,
        source_context=row.context,
        source_unit=row.provenance_unit,
        source_cas=row.cas,
        source_ec=row.ec,
        merge_basis=match.basis,
        merge_method="algorithmic_fallback",
        selector_reason=match.selector_reason,
        mapping_file=indexes.mapping_file,
        provenance=provenance,
        merge_details=match.selector_details,
        conversion_factor=conversion_factor,
    )
    _append_concept_association(
        target_row,
        source=indexes.source,
        source_uuid=row.uuid,
        source_name=row.name,
        source_context=row.context,
        source_unit=row.provenance_unit,
        # Close rather than exact: the source flow was matched by identifier or
        # label, not asserted equivalent by a curator.
        map_type_curie=SKOS_CLOSE_MATCH_CURIE,
        provenance=provenance,
        conversion_factor=conversion_factor,
    )
    accumulator.algorithm_matches.append(AlgorithmMatch(
        source_uuid=row.uuid,
        source_name=row.name,
        source_context=row.context,
        source_context_normalized=row.context_normalized,
        source_context_iri=row.context_iri or "",
        source_unit=row.unit,
        source_cas=row.cas,
        source_ec=row.ec,
        flow_object_id=match.flow_object_id,
        target_name=indexes.flow_object_label_by_id.get(match.flow_object_id, ""),
        target_elementary_flow_id=elem_id,
        target_context=context_display_parts(target_row.context),
        target_unit=target_row.unit or "",
        basis=match.basis,
        basis_value=match.basis_value,
        selector_reason=match.selector_reason,
        matching_method="algorithm",
        algorithm_details=match.selector_details,
        provenance=provenance,
    ))


def match_source_rows(
    *,
    source_flows: list[Flow],
    replace_table: list[Any],
    units_index: Any,
    indexes: MergeIndexes,
    accumulator: MergeAccumulator,
) -> None:
    """Resolve every row of the source list, in order, onto *accumulator*.

    Each row takes one of three routes: a prepared decision, if a curator has
    made one for it; a matched elementary flow; or, when the flow object is
    known but no flow in it fits the row's context, whatever
    :func:`resolve_unselected_row` decides.  A row that resolves to nothing is
    recorded as unmatched, and the merge places it later -- a curator's grouping
    and flow creation both work from that list.

    Nothing is returned: every outcome is a report row or a mutated flow on
    *accumulator*.

    :raises ValueError: if a row's unit cannot be normalised.  A flow whose unit
        is unknown cannot be compared with a consensus flow's, and guessing one
        would make an incomparable pair look comparable.
    """
    prepared_by_source_uuid: dict[str, list[dict[str, Any]]] = {}
    for item in replace_table:
        if not isinstance(item, dict):
            continue
        # Named for the correspondence table's own vocabulary; `source` alone
        # would shadow the source list for the remainder of this function.
        prepared_source = item.get("source")
        target = item.get("target")
        if not isinstance(prepared_source, dict) or not isinstance(target, dict):
            continue
        source_uuid = str(prepared_source.get("uuid") or "").strip()
        target_uuid = str(target.get("uuid") or "").strip()
        if not source_uuid or not target_uuid:
            continue
        prepared_by_source_uuid.setdefault(source_uuid, []).append(item)

    for source_flow in source_flows:
        source_uuid = str(source_flow.uuid or "").strip()
        # `flow.provided` holds what the source list shipped.  Enrichment purges
        # `name` and `synonyms` once it has moved them into the label fields, and
        # rewrites `context` into a consensus dict -- and the merge keys its
        # context lookup on the list's *own* strings, so it has to read those.
        # Which of the two context mappings should govern is a real question;
        # enrichment must not answer it by accident.
        source_name = flow_label_value(source_flow) or (source_flow.provided.name or "")
        source_labels = _source_labels(source_flow)
        source_synonyms = source_flow.provided.synonyms
        source_context = context_display_parts(source_flow.provided.context)
        source_context_iri = indexes.context_expectations.resolve(
            source_uuid, source_context, source_name
        )
        source_context_normalized = (
            indexes.consensus_context_strings.get(source_context_iri, [])
            if source_context_iri else []
        )
        source_unit_raw = str(source_flow.unit or "").strip()
        if source_unit_raw:
            _resolved_unit = resolve_unit_notation(source_unit_raw, units_index)
            if _resolved_unit is None:
                # The command to re-run comes from the list's manifest: it used
                # to be `download-ecoinvent-flows` for every list, so merging
                # anything else told a curator to refetch ecoinvent (#242).
                refetch = (
                    f" and re-run `brightway-flows {indexes.source.fetch_command}`"
                    if indexes.source.fetch_command else ""
                )
                raise ValueError(
                    f"{indexes.source.key} merge: unit '{source_unit_raw}' for flow "
                    f"'{source_name}' ({source_uuid}) could not be normalized. "
                    f"Add it to units.json or UNIT_ALIASES{refetch}."
                )
            source_unit, source_unit_iri = _resolved_unit[0], _resolved_unit[1] or ""
        else:
            source_unit, source_unit_iri = source_unit_raw, ""
        # The normaliser folds the source list's singular `cas_number` into the
        # record's `cas_numbers`; a source list supplies at most one, so the
        # first is the whole of it.
        source_cas = str(source_flow.cas_numbers[0] if source_flow.cas_numbers else "").strip()
        source_ec = str(source_flow.ec_numbers[0] if source_flow.ec_numbers else "").strip()

        # Parsed once and reused by both the prepared-decision path and the
        # no-match path below.
        parsed_row = SourceRow(
            uuid=source_uuid,
            name=source_name,
            synonyms=source_synonyms,
            labels=source_labels,
            context=source_context,
            context_iri=source_context_iri or "",
            context_normalized=source_context_normalized,
            unit=source_unit,
            unit_iri=source_unit_iri,
            cas=source_cas,
            ec=source_ec,
            # The vendor's verbatim string, which for a row the geography
            # split renamed is `original_name` -- `Water, AE`, `Phosphorus,
            # CN` -- not the base the row is matched under.  `vendor_name` is
            # what a published mapping records as `source_flow_name` and what
            # the member-name pass offers the landed substance as a label, and
            # a consumer holding the vendor's inventory has the coded string
            # and no other (#192, decided 2026-09-01).  Deliberately not fed
            # to `_source_labels`: the matcher's evidence and the mapping's
            # record are different channels, and the place-free labels are the
            # matcher's (#65; `test_the_place_is_not_a_label_the_matcher_can_reach`).
            shipped_name=str(
                source_flow.extra.get("original_name")
                or source_flow.provided.name
                or ""
            ).strip(),
            # A fix may have rebased this row onto another unit and stated the
            # factor; the row is carried in the new one and its mapping is
            # published in the old one.  Read here rather than at each writer,
            # so every path down from this row states the same pair.
            conversion=conversion_from_source_flow(source_flow),
        )

        # The element/ion rule (merge/species.py): where it governs -- ecoinvent
        # with no prepared table, so nowhere until that table is retired -- the
        # row's matching evidence becomes the vendor's newest identity for its
        # uuid, charge-normalised to this list's spelling.  The provenance
        # recorded below keeps the release's own words either way.
        if indexes.canonical_identities:
            parsed_row = canonicalized_for_matching(
                parsed_row, indexes.canonical_identities
            )

        prepared_rows = admitted_prepared_rows(
            prepared_by_source_uuid.get(source_uuid, []),
            row_name=parsed_row.name,
        )
        if prepared_rows and apply_prepared_decision(
            row=parsed_row,
            prepared_rows=prepared_rows,
            indexes=indexes,
            accumulator=accumulator,
        ):
            # A "reject" decision returns False and falls through to matching.
            continue

        resolution = resolve_flow_object(
            row=parsed_row, indexes=indexes, accumulator=accumulator
        )
        if resolution is None:
            continue

        # A withdrawal whose material names the body it was drawn from moves
        # into that body, where the source stated none.  Here rather than in
        # `context_expectations`, because the material is not known until the
        # substance is: it is `resolution` above that answers which kind of
        # water this is, and a compartment rule that ran earlier could only
        # have guessed from the name.
        #
        # A prepared decision never reaches this line -- it returned above --
        # so a curated correspondence keeps the compartment it states.
        refined_iri, refined_body = water_body_from_material(
            material=resolution.material, source_context_iri=source_context_iri or ""
        )
        if refined_body:
            source_context_iri = refined_iri
            source_context_normalized = indexes.consensus_context_strings.get(
                refined_iri, []
            )
            parsed_row = replace(parsed_row, context_iri=refined_iri)

        # The selector prefers the normalised context when there is one; record
        # which was used so an unexpected match can be traced back.
        selector_source_context = (
            source_context_normalized
            if isinstance(source_context_normalized, list) and source_context_normalized
            else source_context
        )
        candidates = accumulator.elementary_by_object.get(resolution.flow_object_id, [])
        selected, selector_reason, selector_details = _select_elementary_flow(
            candidates,
            source_context=selector_source_context,
            source_unit=source_unit,
            source_context_iri=source_context_iri or "",
        )
        selector_details["flow_object_candidate_count"] = 1
        selector_details["source_context_original"] = source_context
        selector_details["source_context_normalized"] = source_context_normalized
        selector_details["source_context_used_for_matching"] = selector_source_context
        selector_details["source_context_matching_basis"] = (
            "normalized" if selector_source_context is source_context_normalized else "original"
        )

        match = MatchAttempt(
            flow_object_id=resolution.flow_object_id,
            candidates=candidates,
            selected=selected,
            selector_reason=selector_reason,
            selector_details=selector_details,
            basis=resolution.basis,
            basis_value=resolution.basis_value,
        )
        if selected is None:
            # The flow object is known but no elementary flow in it fits this
            # row's context: either add one, or report the row.
            resolve_unselected_row(
                row=parsed_row,
                match=match,
                indexes=indexes,
                accumulator=accumulator,
            )
            continue

        record_algorithmic_match(
            row=parsed_row,
            match=match,
            indexes=indexes,
            accumulator=accumulator,
            # The table's rows for this flow, even though its target was not
            # taken: what the table says about the *units* outlives its choice
            # of target, and `record_algorithmic_match` re-checks it.
            conversion=(
                conversion_from_prepared_rows(prepared_rows) or parsed_row.conversion
            ),
        )
