"""The transform engine: applying transformers to flows and writing the result.

`run_pipeline` is the whole ETL run. It loads inputs, applies each transformer in
order, validates the result, resolves the layered model, and writes the
artifacts. Everything it delegates to lives in a sibling module.

Transformers do not mutate flows. They return `Change` objects that this module
applies, which is what produces the change log written to the `changelog` and
`provenance_activities` tables the review webapp reads.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import structlog

from brightway_flows.domain.context_registry import validate_flow_contexts
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.property_values import (
    normalise_records,
    normalise_semantic_properties,
    redundant_flat_inchikey_slots,
    redundant_smiles_slots,
)
from brightway_flows.domain.vocabulary import PROV_WAS_GENERATED_BY_CURIE
from brightway_flows.filesystem import (
    CONSENSUS_DB_FILEPATH,
    HARMONISED_FLOWS_SIMPLE_FILEPATH,
    git_revision,
)
from brightway_flows.flow_layers import resolve_flow_layers
from brightway_flows.flow_layers.layering import contested_cas_verdicts
from brightway_flows.flow_layers.land_hierarchy import attach_land_hierarchy
from brightway_flows.flow_layers.non_material import attach_non_material_families
from brightway_flows.flow_layers.synonyms import carry_member_names
from brightway_flows.pipeline.contested_cas_review import contested_cas_items
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.pipeline.concept_associations import (
    ConceptAssociationBuilder,
    _attach_concept_associations,
    builders_for,
)
from brightway_flows.pipeline.collision_decisions import (
    apply_collision_rulings,
)
from brightway_flows.pipeline.layer_writes import LayerWriteLog
from brightway_flows.pipeline.match_strength import apply_match_strengths
from brightway_flows.pipeline.deduplication import (
    _apply_elementary_duplicate_deprecations,
)
from brightway_flows.pipeline.element_labels import (
    ElementPrefLabelPass,
    IonPrefLabelPass,
)
from brightway_flows.pipeline.substance_labels import SubstancePrefLabelPass
from brightway_flows.pipeline.loading import (
    _load_transform_inputs,
)
from brightway_flows.pipeline.review_records import (
    ChangeEvent,
    PipelineRun,
    RunStat,
)
from brightway_flows.pipeline.collisions import report_collisions
from brightway_flows.pipeline.review_tables import (
    REVIEW_SCHEMA_VERSION,
    build_element_coverage,
    build_formula_mismatches,
    collect_review_queue_items,
    load_context_default_mappings,
    number_change_events,
    write_review_tables,
    write_run_timings,
)
from brightway_flows.pipeline.exporting import (
    correspondence_stats,
    retirement_stats,
    write_simple_export,
)
from brightway_flows.pipeline.redirects import FLOW_RETIREMENT_STAGE
from brightway_flows.pipeline.semantic_typing import (
    assign_semantic_types,
    isomeric_values_in_graph_slot,
    withdraw_single_substance_properties,
)
from brightway_flows.pipeline.sqlite import _write_consensus_sqlite
from brightway_flows.pipeline.timings import RunTimings
from brightway_flows.sources import SourceList, base_source_list

logger = structlog.get_logger(__name__)

class Change:
    """A single proposed field update on a flow.

    *field* is validated against :class:`~brightway_flows.domain.flow.Flow`
    at construction, so a misspelled name fails where it is written rather than
    silently creating a key that nothing ever reads.  Both attribute names and
    serialised keys are accepted; the attribute name is stored.
    """

    __slots__ = ("uuid", "field", "new_value", "comment")

    def __init__(self, uuid: str, field: str, new_value: Any, comment: str = "") -> None:
        self.uuid = uuid
        self.field = Flow.resolve_field(field)
        self.new_value = new_value
        self.comment = comment

    def __repr__(self) -> str:
        return (
            f"Change(uuid={self.uuid!r}, field={self.field!r}, "
            f"comment={self.comment!r})"
        )

class Transformer(Protocol):
    """Interface that each data-source transformer must satisfy.

    ``setup()`` loads supplementary data once.  ``transform()`` receives a list
    of flows and returns proposed :class:`Change` objects.  Which flows depends
    on ``answers_per_flow`` below: a transformer that asks about the *set* is
    shown every flow, so that it can compare and group them; one that answers
    per flow is shown only the flows the call can still write to.
    """

    name: str

    #: Does the change this proposes for a flow depend only on that flow?
    #:
    #: True for most of the chain: what a flow's registry number resolves to,
    #: what its structure implies, how its own labels should be spelled.  Such a
    #: transformer is shown only the flows the chain can still write to, because
    #: an answer it derives for a finished flow is discarded on arrival and the
    #: deriving was the expensive part -- three quarters of a build was spent
    #: producing about 210,000 such answers per merged source list and throwing
    #: every one of them away (#88).
    #:
    #: False -- the default -- for a transformer that asks a question about the
    #: *set*: whether two lists describe the same substance, whether a structure
    #: is unique across the build, whether a name belongs to some other flow.
    #: Those are shown everything, finished flows included, because an answer
    #: computed without them is not a slower right answer but a wrong one.
    #:
    #: The default is the safe one.  A transformer added later is shown the
    #: whole list until somebody has decided it can be shown less, which costs
    #: time and cannot cost correctness.
    answers_per_flow: bool = False

    def setup(self) -> None:
        """Load and index supplementary data (called once before processing)."""
        ...

    def transform(self, flows: list[Flow]) -> list[Change]:
        """Propose changes across the flows this call was shown."""
        ...

def writable_flows(flows: Iterable[Flow]) -> Iterator[Flow]:
    """The flows of *flows* a change can still be applied to.

    For the second half of a whole-list transformer.  Four of the twenty-two
    declare ``answers_per_flow = False`` and each has the same two-phase shape:
    an index built over every flow, because that is the question they ask, and
    then a decision taken flow by flow.  Only the index needs the whole list.
    A proposal for a finished flow is dropped on arrival by
    :func:`apply_transformers`, so deriving one is the work #88 is about, one
    level further in than #91 reached.

    On the transform stage this changes nothing, by construction: nothing is
    finished until the chain has run, so every flow is writable and each of the
    four sees what it saw before.  It is the merge that pays -- 95,193 consensus
    flows carrying 1,540,024 alternative labels between them, walked once per
    merged source list on the 2026-08-14 build.

    A generator rather than a list: the callers iterate once, and materialising
    a second 95,000-element list to avoid deriving from it would be an odd way
    to save the derivation.
    """
    return (flow for flow in flows if not flow.transformed)


def apply_transformers(
    transformers: list[Transformer],
    flows: list[Flow],
    *,
    source_list: SourceList,
    original_context_by_uuid: dict[str, Any] | None = None,
    timings: RunTimings | None = None,
    timing_stage: str = "transform",
) -> list[ChangeEvent]:
    """Run each transformer over *flows* in order and apply what it proposes.

    A transformer that compares or groups flows sees the whole list,
    deliberately: deduplication and consensus matching would be blind to
    anything they were not shown.  One that answers per flow sees only the flows
    this call can write to -- see ``Transformer.answers_per_flow``, which is what
    each declares.  Changes are applied last-writer-wins, and the transformer's
    ``name`` is recorded per field in ``flow.pipeline_sources``.

    A flow that is already ``flow.transformed`` is never written to, and every
    flow this call did write to is marked on the way out.  The chain is
    ordered for a single pass over raw input and is not idempotent:
    ``normalize_name_case`` runs fifth and re-title-cases labels that
    ``consensus_match`` sets at fourteenth, and ``rdkit_post_consensus``
    accumulates a settled property value into a list of near-duplicates.  Run
    again over its own output it degrades it -- 35 labels and 15 property sets
    of 596 in a bounded run.  So
    the merge can hand this the consensus flows for grouping and the source list
    it is about to match, in one list, without having to say which is which.

    *flows* is mutated in place; the return value is the change log, and it
    carries only changes that were applied.  It is a list of
    :class:`~brightway_flows.pipeline.review_records.ChangeEvent`, whose
    `change_index` and `flow_object_id` are filled in later, by
    ``number_change_events``: the position in the whole log is not known while a
    source list is being enriched, and a flow's substance is resolved by the
    layering that runs after the chain.

    Separate from :func:`run_pipeline` because the loop does not depend on where
    the flows came from: it is the same operation whether it is handed the whole
    build or one source list's flows together with the consensus so far.

    ``setup()`` is *not* called here.  It loads supplementary data once per
    build, so it stays with the caller that knows how many times this runs.

    *source_list* is the list being enriched -- the base list for the transform,
    the list being consumed for the merge.  It is passed through to
    `resolve_flow_layers`, which needs a list identity for any flow that has no
    `source_refs` of its own, and the merge's flows are exactly those: the
    consensus flows it shows alongside them come back from the database with
    theirs intact (#13).

    *timings* is the build's recorder, and each transformer is one stage of it.
    This is where the transform's half hour is actually spent, so a run that
    could say only "the transform took 26 minutes" could not say which of the
    twenty-odd steps to look at.  A caller with no recorder to pass gets one
    that logs each duration and keeps nothing, so the log line does not depend
    on who called.  *timing_stage* is which run of the chain this is -- the
    transform, or the enrichment the merge does per source list -- because the
    same transformer costs different amounts in each and one row for both would
    be a number describing neither.
    """
    timings = timings if timings is not None else RunTimings()
    changelog: list[ChangeEvent] = []
    flow_by_uuid: dict[str, Flow] = {f.uuid: f for f in flows}
    withheld = 0

    # The flows this call can still write to.  A transformer that answers per
    # flow sees only these: the loop below drops whatever it proposes for a
    # finished flow, so deriving it was work done to be thrown away.  On the
    # transform stage nothing is finished yet and this is the whole list, which
    # is why the base list's run is unaffected; on a merge it is the source list
    # being enriched, a few thousand rows against a consensus of two hundred
    # thousand.
    #
    # The same list object when nothing is finished, not a copy of it: a
    # transformer is entitled to compare `flows` by identity, and the base run
    # should be indistinguishable from what it was before this existed.
    writable = [flow for flow in flows if not flow.transformed]
    if len(writable) == len(flows):
        writable = flows

    for t in transformers:
        logger.info("transformer_run", transformer=t.name)
        started = perf_counter()
        # Duck-typed, with no name beside it: the `and t.name ==
        # "consensus_match"` this used to carry was belt and braces on one
        # condition, and the string coupled the engine to one transformer by
        # name (#92).  #91 cites this line as the precedent for reading a
        # capability off a transformer rather than knowing which one it is, so
        # the `hasattr` half is the half that says what is meant.
        if hasattr(t, "set_flow_object_context"):
            _set_flow_object_context(
                t,
                flows,
                source_list=source_list,
                original_context_by_uuid=original_context_by_uuid,
            )
        # `getattr` rather than `t.answers_per_flow`, matching the duck-typed
        # `set_flow_object_context` check above: a transformer is anything with
        # `name` and `transform`, and one that has never heard of this flag gets
        # the safe answer -- the whole list, as before.
        answers_per_flow = getattr(t, "answers_per_flow", False)
        proposed = t.transform(writable if answers_per_flow else flows)

        for change in proposed:
            flow = flow_by_uuid.get(change.uuid)
            if flow is None:
                logger.warning("change_unknown_uuid", uuid=change.uuid)
                continue
            if flow.transformed:
                withheld += 1
                continue

            old_value = getattr(flow, change.field)
            changelog.append(ChangeEvent(
                uuid=change.uuid,
                flow_name=flow_label_value(flow),
                field_name=change.field,
                old_value=old_value,
                new_value=change.new_value,
                transformer=t.name,
                comment=change.comment,
            ))
            setattr(flow, change.field, change.new_value)
            flow.pipeline_sources[change.field] = t.name

        # The transformer *and* what the engine did with what it proposed:
        # applying a change is the engine's work, not the transformer's, but a
        # reader asking which step to make faster is asking about both, and
        # splitting them would file half the cost under a stage with no name.
        timings.record(timing_stage, perf_counter() - started, detail=t.name)

    # Marked after the whole chain, not per transformer: a flow is transformed
    # once the chain has finished with it, and marking it earlier would make the
    # rest of the chain skip it.
    newly_transformed = 0
    for flow in flows:
        if not flow.transformed:
            flow.transformed = True
            newly_transformed += 1

    logger.info(
        "applied_transformers",
        applied=len(changelog),
        withheld_already_transformed=withheld,
        newly_transformed=newly_transformed,
        hidden_from_per_flow_transformers=len(flows) - len(writable),
    )
    return changelog


#: The activity that builds an association, as it appears in the association's
#: own provenance.  An association carrying it is one this run derived and can
#: derive again; anything else was put there by a merge and must survive the
#: rebuild.
_ASSOCIATION_BUILDER_ACTIVITIES = frozenset({"build_concept_associations"})

_CARRY_PASS_NAME = "carry_associations_onto_flows"


def _carry_associations_onto_flows(
    flows: list[Flow],
    elementary_flows: list[ElementaryFlow],
    *,
    writes: LayerWriteLog | None = None,
) -> Counter:
    """Copy each elementary flow's concept associations onto its harmonised flow.

    The published export and `flow_json` are flow-shaped, so an association
    resolved on the elementary layer has to travel to the flow or no consumer
    sees it.

    A flow's *existing* associations are not simply replaced.  The merge writes
    associations onto a flow directly, and those cannot be rebuilt from the
    elementary layer -- so the ones this run derived are replaced and the rest
    are kept, which is what the activity in an association's provenance
    distinguishes.

    Was twenty lines inside `run_pipeline`, reading through `isinstance(a, dict)`
    and `.get()` and using leading-underscore locals to avoid colliding with the
    enclosing function's names.  That is the tell that it was a pass: it has
    inputs, an output and a reason, and none of them were sayable while it lived
    in the middle of something else (#92).
    """
    log = LayerWriteLog() if writes is None else writes
    stats: Counter = Counter()
    derived_by_uuid = {
        row.elementary_flow_id: row.concept_associations
        for row in elementary_flows
        if row.elementary_flow_id and row.concept_associations
    }
    for flow in flows:
        derived = derived_by_uuid.get(flow.uuid)
        if derived is None:
            continue
        kept = [
            association
            for association in (flow.concept_associations or [])
            if isinstance(association, dict)
            and (association.get("provenance") or {}).get(PROV_WAS_GENERATED_BY_CURIE)
            not in _ASSOCIATION_BUILDER_ACTIVITIES
        ]
        stats["flows_carrying_associations"] += 1
        stats["associations_kept_from_a_merge"] += len(kept)
        if log.write(
            flow, "concept_associations", derived + kept,
            pass_name=_CARRY_PASS_NAME,
            comment="associations resolved on the elementary layer",
        ):
            stats["flows_changed"] += 1
    return stats


#: The stage name the run already reports this under, so a changelog row and a
#: `run_stats` row about the same correction carry the same word.
_NORMALISE_PASS_NAME = "normalise_property_values"


def _normalise_flow_properties(
    flows: list[Flow], *, writes: LayerWriteLog | None = None
) -> Counter:
    """Normalise the flow layer's `properties`, recording what moved.

    `domain.property_values.normalise_records` does this for any record that
    carries `properties`, and still does it for the flow objects and for the
    merge.  The flow layer has its own caller because a `LayerWriteLog` is a
    pipeline object and `domain` does not depend on `pipeline` -- the one edge
    of the old import cycle that was removed rather than deferred (see
    `docs/reference/architecture.md`).  What the two share is the correction
    itself, `normalise_semantic_properties`, which is where it belongs: it is a
    statement about what a property means, not about the run.

    Why the write is worth recording at all, when
    `_link_flows_to_their_substance` assigns `properties` a few lines later from
    the substance: on a 439-flow verification build this corrected 413 flows and
    the link pass then found a different value on 41 of them.  For the other
    372 the substance's answer is the corrected one -- both layers were
    normalised by the same rules -- so this pass is the last thing that wrote a
    published field, and before #94 it said so nowhere: `pipeline_sources`
    named the transformer that had written the *uncorrected* value.
    """
    log = LayerWriteLog() if writes is None else writes
    counts: Counter = Counter()
    for flow in flows:
        properties = flow.properties
        if not isinstance(properties, dict) or not properties:
            continue
        updated, flow_counts = normalise_semantic_properties(properties)
        counts.update(flow_counts)
        log.write(
            flow, "properties", updated,
            pass_name=_NORMALISE_PASS_NAME,
            comment="typed the way the ontology types it",
        )
    return counts


#: Recorded as the `transformer` on every changelog row this pass writes.  Not a
#: transformer -- it holds both layers and writes to them, which is what a layer
#: pass is -- but `changelog.transformer` is the column saying who wrote a
#: value, and leaving it blank would be worse than naming a non-transformer.
_LINK_PASS_NAME = "link_flows_to_their_substance"

#: The same on every row, because the reason is the same on every row.
_LINK_COMMENT = "the substance's answer, copied onto its flow"


def _link_flows_to_their_substance(
    flows: list[Flow],
    flow_objects: list[FlowObject],
    elementary_by_id: dict[str, Any],
    writes: LayerWriteLog | None = None,
) -> None:
    """Copy onto each flow what its flow object knows about the substance.

    A flow and its substance are different things -- that is the whole point of
    the two layers -- but the published export is flow-shaped, so anything a
    consumer needs about the substance has to travel with the flow or be
    re-derived by every reader.  Five things travel: which flow object it is,
    the RDF classes of the substance, why that substance is held apart from one
    it shares a CAS number with, which substance it was held apart *from*, and
    the substance's `properties` -- its formula, masses, structures, registry
    strings and charge.

    `properties` is the one of the five the flow used to answer for itself, and
    that is what #53 is.  A flow reached the layering carrying the chemistry
    its sources wrote, the layering merged that into the object, and every
    correction after it ran over the object alone.  The flow kept the
    pre-correction copy and published it: on the 2026-08-12 build the two layers
    were byte-identical on 6,859 of 7,674 objects and differed on 815, in every
    case because the substance had been corrected and the flow had not --

    * 673 objects where the stereochemistry had been moved out of
      `smiles_string` into `isomeric_smiles_string` (#51), so 8,542 published
      flows stated a shape in the field defined as carrying none, and none
      carried the field that does (#53);
    * 85 where an element's object had withdrawn the charge PubChem states for
      the neutral atom and the flow still claimed it;
    * and the element, isotope and `chemrof:has_element` statements that
      `flow_layers` and the typing write onto an object after the split, which
      no flow had at all.

    Deriving instead of correcting is what makes that unrepeatable.  There is
    one home for a substance's chemistry -- the substance -- and the flow shows
    what is in it, so a future correction to the object cannot reach one layer
    and not the other, and no rule has to say which properties are inherited.

    Extracted from `run_pipeline` because it was three lines inside a loop
    inside a 200-line function, and a copy that silently does nothing is
    invisible there: `origin_qualifier` reaches the export on 11 flow objects
    out of 7,660, none of them in a bounded run, so nothing would have noticed
    it being dropped.
    """
    types_by_object_id = {
        obj.flow_object_id: obj.types for obj in flow_objects if obj.types
    }
    qualifier_by_object_id = {
        obj.flow_object_id: obj.origin_qualifier
        for obj in flow_objects
        if obj.origin_qualifier
    }
    parent_by_object_id = {
        obj.flow_object_id: obj.parent_flow_object_id
        for obj in flow_objects
        if obj.parent_flow_object_id
    }
    intervention_by_object_id = {
        obj.flow_object_id: obj.parent_intervention_id
        for obj in flow_objects
        if obj.parent_intervention_id
    }
    roles_by_object_id = {
        obj.flow_object_id: obj.roles for obj in flow_objects if obj.roles
    }
    properties_by_object_id = {
        obj.flow_object_id: obj.properties
        for obj in flow_objects
        if isinstance(obj.properties, dict) and obj.properties
    }
    log = LayerWriteLog() if writes is None else writes
    for flow in flows:
        layer_row = elementary_by_id.get(flow.uuid)
        if layer_row is None:
            continue
        # `flow_object_id` and `source_refs` are set directly: they say which
        # substance this flow is and which source rows produced it, which is
        # bookkeeping the layering resolved rather than a change to what the
        # flow claims about the world.  Everything below is a published
        # statement about the substance, and goes through the log.
        flow.flow_object_id = layer_row.flow_object_id or ""
        flow.source_refs = layer_row.source_refs
        object_types = types_by_object_id.get(flow.flow_object_id)
        log.write(
            flow, "types",
            list(object_types) if object_types else None,
            pass_name=_LINK_PASS_NAME, comment=_LINK_COMMENT,
        )
        log.write(
            flow, "origin_qualifier",
            qualifier_by_object_id.get(flow.flow_object_id),
            pass_name=_LINK_PASS_NAME, comment=_LINK_COMMENT,
        )
        log.write(
            flow, "parent_flow_object_id",
            parent_by_object_id.get(flow.flow_object_id),
            pass_name=_LINK_PASS_NAME, comment=_LINK_COMMENT,
        )
        log.write(
            flow, "parent_intervention_id",
            intervention_by_object_id.get(flow.flow_object_id),
            pass_name=_LINK_PASS_NAME, comment=_LINK_COMMENT,
        )
        object_roles = roles_by_object_id.get(flow.flow_object_id)
        # `deepcopy`, not `dict(row)`.  A role row nests a `provenance` dict, so
        # a shallow copy leaves every flow of an object sharing one -- and a
        # flow is edited far more often than a substance.  Nothing mutates it
        # today; the point is that the isolation the test asserts is the
        # isolation the code provides.
        log.write(
            flow, "roles",
            deepcopy(object_roles) if object_roles else None,
            pass_name=_LINK_PASS_NAME, comment=_LINK_COMMENT,
        )
        # `deepcopy` for the reason the roles are deep-copied, and it matters
        # more here: a property entry nests `@value` lists and `provenance`
        # rows, an object has 12 flows on average, and sharing one bag between
        # them would make an edit to a flow an edit to its substance and to
        # every sibling.  5.4s of a build's wall clock, measured over the
        # 94,409 flows of the 2026-08-12 build.
        #
        # `{}` where the object states nothing, rather than leaving the flow's
        # own copy: a substance with no chemistry is an answer, and the flow
        # publishes the substance's answer.  `Flow.properties` is a plain dict
        # field, so this writes `"properties": {}` exactly as it did for a flow
        # that never had any.
        log.write(
            flow, "properties",
            deepcopy(properties_by_object_id.get(flow.flow_object_id, {})),
            pass_name=_LINK_PASS_NAME, comment=_LINK_COMMENT,
        )


def _set_flow_object_context(
    transformer: Transformer,
    flows: list[Flow],
    *,
    source_list: SourceList,
    original_context_by_uuid: dict[str, Any] | None,
) -> None:
    """Hand `consensus_match` the flow objects the current flows resolve to.

    It groups by substance rather than by flow, so it needs the layering that
    `resolve_flow_layers` derives -- which is a function of the flows as they
    stand when it runs, not of the build as a whole.
    """
    pre_objects, pre_elementary, _pre_stats = resolve_flow_layers(
        flows,
        source_list=source_list,
        include_pubchem_isotopes=False,
        original_context_by_uuid=original_context_by_uuid,
    )
    object_instances: list[FlowObject] = [
        row for row in pre_objects if row.flow_object_id.strip()
    ]

    members_by_object_id: dict[str, list[Flow]] = {}
    object_id_by_uuid: dict[str, str] = {}
    flow_by_uuid = {f.uuid: f for f in flows}
    for row in pre_elementary:
        ef_uuid = row.elementary_flow_id.strip()
        object_id = row.flow_object_id.strip()
        if not ef_uuid or not object_id:
            continue
        flow = flow_by_uuid.get(ef_uuid)
        if flow is None:
            # Was `not isinstance(flow, dict)`, left behind when flows became
            # records.  Always true, so this loop never ran and
            # `consensus_match` was handed empty member data on every build --
            # every flow object's `representative` fell back to an empty `Flow`.
            continue
        object_id_by_uuid[ef_uuid] = object_id
        members_by_object_id.setdefault(object_id, []).append(flow)

    transformer.set_flow_object_context(
        object_instances, members_by_object_id, object_id_by_uuid
    )


def bounded_sample(
    flows: list[Flow],
    limit: int,
    keep_uuids: Iterable[str] | None,
    *,
    option: str = "--include-uuid",
    list_name: str = "the base list",
) -> tuple[list[Flow], int]:
    """The first *limit* rows, plus any named in *keep_uuids*.

    `--max-flows` alone is a prefix of the base list in file order, which is a
    sample nobody chose: whether it contains the flows a change is about is an
    accident of where they sort.  EF 3.1's eleven water withdrawals sit at
    indices 12,722 to 75,846 of 94,062, so the default 400-flow run reaches none
    of them -- and a change to those flows passed that run while aborting the
    build at 80,000.  A clean diff from a sample that excludes the subject is
    not a weak signal, it is no signal.

    So a caller can name what the run is about and get it regardless of where it
    sorts.  Order is preserved, and the named rows are added rather than
    substituted, so the prefix a previous run used is still in the sample and
    two runs remain comparable.

    Both sides of a build bound their rows this way -- the transform with
    `--max-flows` / `--include-uuid` over the base list, the merge with
    `--max-rows` / `--include-source-uuid` over each source list -- so the
    prefix-plus-named rule is written once here and told which list and which
    option to name when a uuid turns out not to be in it (*option*,
    *list_name*).

    Returns the sample and how many rows were kept by name beyond the prefix.
    """
    wanted = {str(u).strip() for u in (keep_uuids or ()) if str(u).strip()}
    if not wanted:
        return flows[:limit], 0

    prefix_uuids = {flow.uuid for flow in flows[:limit]}
    extra = [
        flow
        for flow in flows[limit:]
        if flow.uuid in wanted - prefix_uuids
    ]
    found = prefix_uuids & wanted
    missing = wanted - found - {flow.uuid for flow in extra}
    if missing:
        # Naming a flow the list does not ship is a typo, and silently
        # sampling without it is how a run reports on the wrong thing.
        raise ValueError(
            f"{option} named {len(missing)} flow(s) {list_name} does not "
            f"ship: {sorted(missing)}"
        )
    return flows[:limit] + extra, len(extra)


def run_pipeline(
    transformers: list[Transformer],
    *,
    dry_run: bool = False,
    max_flows: int | None = None,
    keep_uuids: Iterable[str] | None = None,
    sources: list[SourceList] | None = None,
    concept_association_builders: list[ConceptAssociationBuilder] | None = None,
    timings: RunTimings | None = None,
) -> Path:
    """Load the base flows, apply *transformers* in order, and write the result.

    Each transformer's ``transform()`` is called with the flows it declares it
    needs -- the whole list here, since the transform stage finishes nothing
    before the chain has run, so ``answers_per_flow`` costs this call nothing
    and pays on every merge.  Returned changes are applied with
    last-writer-wins semantics, and the transformer ``name`` is recorded in a
    ``_sources`` dict on each flow.

    The change log, the PROV-O activity trail, and every curator queue the
    transformers produced go into the database alongside the flows, in the
    tables :mod:`brightway_flows.pipeline.review_tables` defines.  They used
    to be optional JSON side-car files behind ``--write-transform-log`` and
    ``--write-provenance``, which meant the review pages that read them worked
    only when someone had remembered the flag.

    The transform's input is EF 3.1 and nothing else.  Every other list is a
    ``SourceList``, enriched and matched by the merge, so there is no second
    route by which flows enter here (#210).

    *sources* are the lists this build will go on to merge.  They enter the
    transform for one reason: the mappings a build publishes are the base list's
    plus those of the lists it was asked for, and the mappings are attached
    here.  A list whose manifest declares a correspondence table therefore has
    that table read on the builds that name it and on no others (#244).

    *timings* is the build's recorder, and this stage's stages go into it.
    When `build` supplies one it also writes it, after the merge, so that one
    table describes the whole run; a caller with none -- a test, a transform
    run on its own -- gets a recorder of its own and this function writes it.

    Returns the path to the database it wrote.
    """
    owns_timings = timings is None
    timings = timings if timings is not None else RunTimings()
    if not dry_run and CONSENSUS_DB_FILEPATH.exists():
        CONSENSUS_DB_FILEPATH.unlink()
        logger.info("deleted_existing_consensus_sqlite", path=str(CONSENSUS_DB_FILEPATH))

    # The transform's input is one list, and it is the one the registry declares
    # as the base.  Named here rather than left implicit because every flow this
    # run publishes is one of its rows, and `source_refs` says so (#13).
    base = base_source_list()
    # Timed because it is a fixed cost every run pays whatever `--max-flows`
    # says: the whole 207 MB base list is read and manual-fixed here, and only
    # then is the sample taken below.  7 s of a 42 s 400-flow build.
    with timings.stage("load_transform_inputs"):
        flows, loaded_input_paths = _load_transform_inputs()
    original_count = len(flows)
    kept_by_uuid = 0
    if max_flows is not None:
        flows, kept_by_uuid = bounded_sample(flows, max_flows, keep_uuids)
    logger.info(
        "loaded_transform_inputs",
        count=len(flows),
        original_count=original_count,
        max_flows=max_flows,
        kept_by_uuid=kept_by_uuid,
        input_files=loaded_input_paths,
    )

    # What each flow's source list shipped, which is what the layering writes
    # into `source_metadata.original_context`.  Read from `provided`, the one
    # field that holds it: `flow.context` used to hold it too until
    # `default_context_mapping` overwrote it, which is the ambiguity #97
    # removed.  Copied because the layering is free to keep what it is given.
    original_context_by_uuid: dict[str, Any] = {
        flow.uuid: list(flow.provided.context) for flow in flows
    }

    # Once per build, whatever the flows are: `setup()` loads supplementary
    # data, which does not change between lists.
    for t in transformers:
        logger.info("transformer_setup", transformer=t.name)
        with timings.stage("transformer_setup", detail=t.name):
            t.setup()

    changelog = apply_transformers(
        transformers,
        flows,
        source_list=base,
        original_context_by_uuid=original_context_by_uuid,
        timings=timings,
    )

    # Gate before any artifact is written: a context that is unconstructible, or
    # that contradicts its own context_iri, must stop the run rather than be
    # serialised -- downstream consumers key on context_iri and cannot detect a
    # context that silently disagrees with it.
    context_problems = validate_flow_contexts(flows)
    if context_problems:
        logger.error(
            "invalid_flow_contexts",
            count=len(context_problems),
            examples=context_problems[:20],
        )
        raise ValueError(
            f"{len(context_problems)} flow(s) have an invalid or inconsistent "
            f"context; refusing to write artifacts. First problems:\n  "
            + "\n  ".join(context_problems[:20])
        )
    logger.info("validated_flow_contexts", flow_count=len(flows))

    timestamp = datetime.now(timezone.utc).isoformat()
    run_id = "".join(ch for ch in timestamp if ch.isalnum())
    git_commit, git_dirty = git_revision()
    run = PipelineRun(
        run_id=run_id,
        timestamp=timestamp,
        schema_version=REVIEW_SCHEMA_VERSION,
        dry_run=dry_run,
        max_flows=max_flows,
        input_files=list(loaded_input_paths),
        transformer_names=[t.name for t in transformers],
        flow_count=len(flows),
        change_count=len(changelog),
        git_commit=git_commit,
        git_dirty=git_dirty,
    )

    # Each of these returns a tally of what it did.  They were logged and
    # dropped -- and before that merged into a dict written four times and read
    # zero -- so a regression in any of them was invisible between runs (#232).
    # They go into `run_stats` now, keyed by the function that counted.
    run_stats: list[RunStat] = []
    # Everything the passes below write onto a flow, on its way to the
    # changelog.  Until #92 `ChangeEvent` was constructed in exactly one
    # place -- `apply_transformers` -- so every write after the layering
    # was invisible to the review app, including a published `prefLabel`
    # being replaced outright and a flow being deprecated.
    layer_writes = LayerWriteLog()

    def tally(stage: str, counts: Any) -> None:
        """Record one stage's counts, and log them as before.

        Sorted, because these rows are compared between runs and an order that
        depends on insertion would make every comparison noisy.
        """
        run_stats.extend(
            RunStat(stage=stage, key=str(key), value=int(value))
            for key, value in sorted(dict(counts).items())
            if isinstance(value, int)
        )

    with timings.stage("resolve_flow_layers"):
        flow_objects, elementary_flows, layer_stats = resolve_flow_layers(
            flows,
            source_list=base,
            include_pubchem_isotopes=True,
            original_context_by_uuid=original_context_by_uuid,
            # The pass whose objects are written, so the pass that publishes
            # curated names.  The pre-pass above deliberately does not: it feeds
            # `consensus_match`, which carries an object's label onto its member
            # flows, and a name that reached the flows could move them.
            apply_curated_names=True,
        )
    logger.info("resolved_flow_layers", **layer_stats)
    tally("resolve_flow_layers", layer_stats)

    # The passes between the layering and the writes, as one stage.  Marked
    # rather than wrapped: a `with` around the hundred lines below would
    # reindent every one of them, and a diff that large would hide what it was
    # for.  If this stage ever turns out to be where the time goes, the marks
    # move inwards -- but on the runs that prompted this it is the transformers
    # above and the writers below that cost.
    _passes_started = perf_counter()
    # The same verdicts the layering acted on, asked for again so the ones it
    # could not act on reach a curator.  Recomputed rather than returned through
    # `resolve_flow_layers`, whose stats are counters: a queue is not a statistic
    # and threading it through the layering's signature would make it one.
    contested_items = contested_cas_items(
        contested_cas_verdicts(flows, source_list=base),
        flow_counts=Counter(
            cas
            for flow in flows
            for cas in flow.cas_numbers
            if isinstance(cas, str) and cas.strip()
        ),
    )
    # Before deduplication, because a ruling is an answer to the question the
    # collision report asks and deduplication is what would otherwise answer it
    # by sorting: the curated survivor has to be chosen while both flows are
    # still live.
    ruling_stats = apply_collision_rulings(
        flows=flows,
        elementary_flows=elementary_flows,
        writes=layer_writes,
    )
    tally("apply_collision_rulings", ruling_stats)
    duplicate_stats = _apply_elementary_duplicate_deprecations(
        flows=flows,
        elementary_flows=elementary_flows,
        writes=layer_writes,
    )
    logger.info("deprecated_duplicate_elementary_flows", **duplicate_stats)
    tally("deprecate_duplicate_elementary_flows", duplicate_stats)
    # After the deprecations, deliberately: a deprecated flow is the record of a
    # collision already resolved, and counting it again would report every
    # resolution as an outstanding problem.  What is left is the collisions
    # deduplication did *not* act on -- two live flows one field away from
    # collapsing, which is the question #31 needed asked before it was answered
    # by a lexicographic sort.
    collision_stats, collision_items = report_collisions(
        elementary_flows,
        labels_by_object={
            obj.flow_object_id: flow_label_value(obj) for obj in flow_objects
        },
    )
    tally("elementary_flow_collisions", collision_stats)
    builders = (
        builders_for([base_source_list(), *(sources or [])])
        if concept_association_builders is None
        else concept_association_builders
    )
    _attach_concept_associations(elementary_flows, builders)
    # Immediately after, and never inside the attaching: how strong a mapping is
    # depends on how many of the same list's flows land on one consensus flow,
    # and no builder sees more than the flow it is building for.  Deduplication
    # has already run above, so the count is over the flows that will be
    # published -- which is what left 28 EF 3.1 flows claiming two exact matches
    # each, one of them a retired duplicate's, before this pass existed (#76).
    strength_stats = apply_match_strengths(
        f.concept_associations for f in elementary_flows if f.concept_associations
    )
    logger.info("resolved_match_strengths", **dict(strength_stats))
    tally("resolve_match_strengths", strength_stats)
    tally(
        "carry_associations_onto_flows",
        _carry_associations_onto_flows(flows, elementary_flows, writes=layer_writes),
    )

    # Which flows are not substances at all, and which of them are one another?
    # Immediately before the typing and never inside `resolve_flow_layers`,
    # because both passes read the contexts off the elementary flows and the
    # merge does not put them there until after the layering has run (#70).
    flow_objects, family_stats = attach_non_material_families(
        flow_objects, elementary_flows
    )
    logger.info("attached_non_material_families", **family_stats)
    tally("attach_non_material_families", family_stats)

    # And which land class sits under which.  Beside the family pass because it
    # is the same kind of statement -- a parent for something that is not a
    # substance -- but it reads no contexts, so its placement here is for one
    # convention rather than for the ordering #70 learned the hard way.
    flow_objects, land_stats = attach_land_hierarchy(flow_objects)
    logger.info("attached_land_hierarchy", **land_stats)
    tally("attach_land_hierarchy", land_stats)

    # What kind of thing is each substance?  Derived from the chemistry --
    # formula, charge, structure, registry identifiers and the contexts it is
    # emitted to -- rather than from a regex over its label, which is what
    # `flow_layers` had and which missed `Chloride` and `Sodium ion`.
    typing_stats = assign_semantic_types(flow_objects, elementary_flows)
    logger.info("assigned_semantic_types", **dict(typing_stats))
    tally("assign_semantic_types", typing_stats)

    # Last stop before serialisation: a semantic property must leave here typed
    # the way the ontology types it, a whole-entity charge must leave on the
    # predicate that means whole-entity charge, and one structure must leave as
    # one value however its sources spelled it.  Both layers, because the
    # published export projects `Flow` while the review apps read `FlowObject`
    # -- and a flow the layering did not place answers for its own chemistry,
    # so `flows` is not covered by the objects being covered.
    property_stats = _normalise_flow_properties(flows, writes=layer_writes)
    property_stats.update(normalise_records(flow_objects))

    # The substance's chemistry onto its flows, once every correction above has
    # run over the substance.  Before the measurements below rather than after,
    # so a figure read off a flow is the figure that will be published: with the
    # copy left in place, the run reported 8,560 flows stating a shape in
    # `smiles_string` and then wrote the corrected values over them.
    elementary_by_id = {
        row.elementary_flow_id: row for row in elementary_flows if row.elementary_flow_id
    }
    _link_flows_to_their_substance(
        flows, flow_objects, elementary_by_id, writes=layer_writes
    )

    # Read off the records afterwards rather than asserted by the step that
    # collapses, so this reports what is published and not what was intended.
    property_stats["objects_with_redundant_smiles"] = sum(
        1 for obj in flow_objects if redundant_smiles_slots(obj.properties)
    )
    property_stats["flows_with_redundant_smiles"] = sum(
        1 for flow in flows if redundant_smiles_slots(flow.properties)
    )
    property_stats["objects_with_redundant_flat_inchikey"] = sum(
        1 for obj in flow_objects if redundant_flat_inchikey_slots(obj.properties)
    )
    property_stats["flows_with_redundant_flat_inchikey"] = sum(
        1 for flow in flows if redundant_flat_inchikey_slots(flow.properties)
    )
    # The same question for #51: is anything published in the slot that says it
    # carries no stereochemistry carrying some?  Both figures have to be zero
    # now.  The flow figure was 8,560 on the 2026-08-12 build and 43 on a
    # 421-flow verification run, because the split runs over flow objects and
    # the flow layer kept the property as its sources wrote it (#53); the flows
    # take their properties from the object above, so the two figures are one
    # measurement made twice, and they part company only if that stops being
    # true.
    property_stats["objects_with_stereochemistry_in_smiles"] = sum(
        1 for obj in flow_objects if isomeric_values_in_graph_slot(obj.properties)
    )
    property_stats["flows_with_stereochemistry_in_smiles"] = sum(
        1 for flow in flows if isomeric_values_in_graph_slot(flow.properties)
    )
    logger.info("normalised_semantic_properties", **dict(property_stats))
    tally("normalise_property_values", property_stats)

    # Last thing before the objects are serialised, because it is a question
    # about the whole set and about what will be published: a name a source list
    # gave a flow stays a name the list answers to, and a name that would answer
    # for two substances is published for neither (#113).
    tally("carry_member_names", carry_member_names(flow_objects, elementary_flows))

    # The two review-table builders below serialise a flow object and read the
    # payload back, so they take the payload.  The SQLite writer no longer
    # does: it takes the records and converts them itself (#96), which is why
    # there is one list here and not three.
    flow_object_dicts = [obj.to_dict() for obj in flow_objects]

    # An assertion now, not a correction.  `assign_semantic_types` withdrew
    # these from the objects that are not one substance -- an alpha-emitter
    # aggregate (#238), a delayed-emission correction (#43) -- and the flows
    # take their properties from the object, so there is nothing left here to
    # withdraw and `properties_withdrawn` reads zero.  Kept, and kept reported,
    # because it reads zero only while that holds: a flow the derivation missed
    # would publish a molecular formula for a quantity in kg*a, and this is
    # where the run says so.  It still needs `origin_qualifier`, which reaches
    # the flow from its object above.
    tally(
        "withdraw_single_substance_properties",
        withdraw_single_substance_properties(flows, writes=layer_writes),
    )

    # The element name reaches the flows that resolve to it -- but only where
    # that is a titlecase of the name the flow already has, or where a curator
    # has ruled that the rename is right.  See `pipeline.element_labels`: this
    # was the one writer of a published `prefLabel` that
    # `preferred-label-decisions.json` did not gate (#16).
    element_labels = ElementPrefLabelPass(writes=layer_writes)
    element_label_stats = element_labels.apply(flows, flow_objects)
    tally("element_pref_labels", element_label_stats)

    # An ion named `X, ion` is one whose charge `flow_layers.ions` could not
    # work out from its label.  The charge arrives afterwards, from PubChem
    # against the registry number, and by then the name is written -- so this
    # runs here, where the charge is, rather than there (#128).  Before the
    # substance pass below, because that is what carries a substance's name onto
    # its flows.
    ion_labels = IonPrefLabelPass()
    tally(IonPrefLabelPass.name, ion_labels.apply(flow_objects))

    # After the element pass, and last of the label writers on purpose: a flow
    # leaves for the export called what its substance is called, or carrying a
    # queue item saying why it does not (#7).  Every substance-level rename
    # above -- the rulings, the element names, the land classes named from
    # their fields -- reaches the published flows through this one pass.
    substance_labels = SubstancePrefLabelPass(writes=layer_writes)
    tally(SubstancePrefLabelPass.name, substance_labels.apply(flows, flow_objects))

    # The passes after the layering, in the order they ran, appended to the
    # transformer chain's log rather than mixed into it: `change_index` is
    # chronological, and every one of these happened after every change above.
    changelog.extend(layer_writes.change_events())
    tally("layer_writes", Counter(
        write.pass_name for write in layer_writes.writes
    ))

    # Numbered only now: `change_index` is the position in the whole run's log,
    # and `flow_object_id` comes from the layering that has just resolved above.
    number_change_events(
        changelog,
        flow_object_id_by_uuid={
            row.elementary_flow_id: row.flow_object_id
            for row in elementary_flows
            if row.elementary_flow_id and row.flow_object_id
        },
    )

    timings.record("layer_passes", perf_counter() - _passes_started)

    if dry_run:
        # `--dry-run` used to skip only the harmonised JSON exports, while still
        # deleting and rewriting the database -- so a bounded smoke run
        # overwrote a real data directory, which is how multi-GB artifacts
        # were replaced by 400-flow ones. It now skips every write.
        logger.info(
            "dry_run_skipped_writes",
            flow_count=len(flows),
            flow_object_count=len(flow_objects),
            elementary_flow_count=len(elementary_flows),
        )
        return CONSENSUS_DB_FILEPATH

    with timings.stage("write_consensus_sqlite"):
        _write_consensus_sqlite(flows, changelog, flow_objects, elementary_flows)
    logger.info("wrote_consensus_sqlite", path=str(CONSENSUS_DB_FILEPATH))

    with timings.stage("write_simple_export"):
        write_simple_export(CONSENSUS_DB_FILEPATH, HARMONISED_FLOWS_SIMPLE_FILEPATH)
    # After the export, because it is the export that groups the per-flow
    # associations into correspondences, and this counts the same grouping.
    tally("build_correspondences", correspondence_stats(CONSENSUS_DB_FILEPATH))
    # Beside it, and for the same reason: the export is what publishes a retired
    # identifier's redirect, and this counts how many of them this build could
    # still resolve (#102).
    tally(FLOW_RETIREMENT_STAGE, retirement_stats(CONSENSUS_DB_FILEPATH))

    _review_started = perf_counter()
    write_review_tables(
        CONSENSUS_DB_FILEPATH,
        run=run,
        stats=run_stats,
        changes=changelog,
        queue_items=[
            *collect_review_queue_items(
                [*transformers, element_labels, ion_labels, substance_labels]
            ),
            *collision_items,
            *contested_items,
        ],
        formula_mismatches=build_formula_mismatches(flow_object_dicts),
        element_coverage=build_element_coverage(flow_object_dicts),
        context_mappings=load_context_default_mappings(),
        timings=timings.records(),
    )
    # After the call it is timing, so this stage is one row short in the table
    # `write_review_tables` just wrote.  It is complete in the recorder, and
    # `build` rewrites the table from that after the merge -- which is the
    # ordinary case.  A transform run on its own rewrites it here.
    timings.record("write_review_tables", perf_counter() - _review_started)
    if owns_timings:
        write_run_timings(CONSENSUS_DB_FILEPATH, timings=timings.records())

    return CONSENSUS_DB_FILEPATH
