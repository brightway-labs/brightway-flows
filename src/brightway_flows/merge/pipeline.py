"""Separate merge pipeline for appending external source flow lists."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

import structlog

from brightway_flows.domain.context_registry import (
    validate_flow_contexts,
)
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow import Flow
from brightway_flows.filesystem import (
    CONSENSUS_DB_FILEPATH,
    HARMONISED_FLOWS_SIMPLE_FILEPATH,
)
from brightway_flows.merge.additions import (
    apply_manual_additions,
)
from brightway_flows.flow_layers.synonyms import (
    MERGE_SYNONYM_STAGE,
    carry_member_names,
)
from brightway_flows.merge.collisions import (
    MERGE_COLLISION_STAGE,
    report_merged_collisions,
)
from brightway_flows.merge.contexts import (
    _load_context_expectation_indexes,
)
from brightway_flows.merge.creations import (
    create_flows_for_unmatched_rows,
)
from brightway_flows.merge.datastores import (
    sync_flow_object_synonyms,
    sync_merge_results,
)
from brightway_flows.merge.matching import (
    _load_external_names_by_cas,
    _load_working_set,
    build_merge_accumulator,
    build_merge_indexes,
)
from brightway_flows.merge.land_groupings import (
    load_land_flow_groupings,
    unrecorded_land_groupings,
)
from brightway_flows.merge.places import (
    MERGE_LAND_PLACE_STAGE,
    MERGE_PLACE_STAGE,
    report_land_classes_out_of_place,
    report_substance_places,
)
from brightway_flows.merge.prepared import (
    find_prepared_context_inconsistencies,
)
from brightway_flows.merge.prepared_context_decisions import (
    load_prepared_context_decision_index,
)
from brightway_flows.merge.report import (
    AlgorithmMatch,
    PreparedMatch,
)
from brightway_flows.merge.rows import (
    match_source_rows,
)
from brightway_flows.merge.store import (
    MergeRunInput,
    build_outcomes,
    detect_conflicts,
    finish_run,
    start_run,
    write_source_outcomes,
)
from brightway_flows.merge.unit_changes import (
    find_unit_mismatches,
    load_unit_change_allowlist,
    report_unrecorded_crossings,
)
from brightway_flows.merge.unmatched import (
    enrich_unmatched_rows,
)
from brightway_flows.pipeline.engine import (
    Transformer,
    apply_transformers,
    bounded_sample,
)
from brightway_flows.pipeline.exporting import (
    retired_identifier_queue_items,
    retirement_stats,
    write_simple_export,
)
from brightway_flows.pipeline.redirects import FLOW_RETIREMENT_STAGE
from brightway_flows.pipeline.review_records import ReviewQueue
from brightway_flows.pipeline.substance_labels import (
    MERGE_SUBSTANCE_LABEL_STAGE,
    apply_substance_labels_to_database,
)
from brightway_flows.pipeline.review_tables import (
    replace_queue_items,
    replace_stage_stats,
    write_run_timings,
)
from brightway_flows.pipeline.sqlite import (
    read_published_flow_payloads,
    recompute_match_strengths,
)
from brightway_flows.pipeline.timings import RunTimings
from brightway_flows.sources import (
    SourceList,
    load_prepared_match_table,
)
from brightway_flows.transformers.unit_normalization import build_units_index

logger = structlog.get_logger(__name__)


# `merge_ecoinvent(version)` was here until #243.  It resolved
# `f"ecoinvent-{version}"` and called `merge_source_list`, and it was called by
# nothing: `build` resolves its own `--source` values.  Two entry points, one of
# which could name only ecoinvent, is the shape this package spent #12 removing.


def _enrich_against_consensus(
    *,
    source: SourceList,
    source_flows: list[Flow],
    transformers: list[Transformer],
    timings: RunTimings | None = None,
) -> None:
    """Run *transformers* over this source list's flows and the consensus so far.

    Step 2 of #210.  Both sides go in one list deliberately: deduplication,
    consensus matching and shared labels compare and group *across* the list, so
    showing *those* transformers only the new rows blinds exactly the logic that
    makes enrichment worth doing.  Which is why the two sides are handed over
    together and told apart afterwards rather than here: `apply_transformers`
    shows the whole list to the transformers that group, and only the new rows
    to the ones that answer per flow, and it knows which is which because each
    says so (#88).

    Only *source_flows* are written to, and this function does not have to say
    so: the consensus flows come back from the database already
    `Flow.transformed`, and `apply_transformers` shows a transformed flow to
    every transformer without letting any of them write to it.  The chain is
    ordered for a single pass over raw input and is not idempotent, so running
    it again over its own output degrades it -- 35 published labels and 15
    property sets of 596 in a bounded run.

    *source_flows* are mutated in place, so they carry their enrichment into the
    matching below: better names, CAS and EC before lookup.  That is the whole
    benefit, and it is one-sided in a second way too -- matching indexes on
    `flow_objects`, which this does not re-derive, so nothing on the consensus
    side would reach the lookup even if it were enriched.  Re-deriving flow
    objects inside the loop is a larger change than the loop itself.

    ``setup()`` is not called: these are the instances the transform stage
    already set up, and setting them up again would reload ChEBI and PubChem
    once per source list.
    """
    consensus_flows = [
        Flow.from_dict(row) for row in read_published_flow_payloads(CONSENSUS_DB_FILEPATH)
    ]

    # A `Change` addresses its target by uuid, so uuid has to be unique within
    # one `apply_transformers` call even though the merge itself knows perfectly
    # well which side a flow came from.  Both copies are shown; both copies'
    # changes route to whichever the `{uuid: flow}` dict kept, which is the
    # source row, since it comes second.  So a change a transformer derived from
    # the *consensus* flow's state lands on the source row -- and `transformed`
    # does not catch it, because the flow it is checked on is the source row,
    # which is not marked.  Nothing is corrupted, nothing is lost; the routing is
    # simply wrong, and silently so.
    #
    # Nothing produces a collision today: #212 removed the merge feedback file,
    # which reused ecoinvent's uuids for consensus flows.  This makes a silent
    # mis-route a loud failure if one returns.
    collisions = {f.uuid for f in consensus_flows} & {f.uuid for f in source_flows}
    if collisions:
        raise ValueError(
            f"{len(collisions)} uuid(s) name both a consensus flow and a "
            f"{source.key} source row. A change is addressed by uuid, so "
            f"changes meant for the consensus flow would be applied to the "
            f"source row instead. First: {sorted(collisions)[:5]}"
        )

    changelog = apply_transformers(
        transformers,
        consensus_flows + source_flows,
        source_list=source,
        timings=timings,
        # Under a stage of its own, so that a transformer's cost here is not
        # added to its cost in the transform: they are different work over
        # different flows.  Several source lists do accumulate into one row --
        # `merge_enrich` beside it is the per-list total.
        timing_stage="merge_enrich_transformer",
    )

    by_transformer: dict[str, int] = {}
    for change in changelog:
        by_transformer[change.transformer] = by_transformer.get(change.transformer, 0) + 1
    logger.info(
        "enriched_source_list",
        source=source.key,
        consensus_flow_count=len(consensus_flows),
        source_flow_count=len(source_flows),
        change_count=len(changelog),
        changed_source_flow_count=len({change.uuid for change in changelog}),
        changes_by_transformer=by_transformer,
    )


def _refuse_invalid_contexts(merged_elementary: list[ElementaryFlow]) -> None:
    """Stop the merge before it writes a flow whose context contradicts its IRI.

    The merge path is what produced those flows in the first place.  Catch a
    regression here rather than shipping it -- downstream consumers key on
    `context_iri` and cannot detect a context that silently disagrees with it.

    :raises ValueError: if any merged flow has an invalid or inconsistent
        context.
    """
    context_problems = validate_flow_contexts(merged_elementary)
    if context_problems:
        logger.error(
            "invalid_merged_flow_contexts",
            count=len(context_problems),
            examples=context_problems[:20],
        )
        raise ValueError(
            f"{len(context_problems)} merged flow(s) have an invalid or "
            f"inconsistent context; refusing to write artifacts. First problems:\n  "
            + "\n  ".join(context_problems[:20])
        )
    logger.info("validated_merged_flow_contexts", flow_count=len(merged_elementary))


def _refuse_dangling_flow_objects(
    merged_elementary: list[ElementaryFlow],
    known_object_ids: set[str],
) -> None:
    """Stop the merge before it writes a flow whose flow object does not exist.

    Many elementary flows to one flow object is the core relationship of the
    data model, and every substance-level fact -- formula, mass, structure,
    synonyms, CAS, `@type` -- lives on the object.  A flow whose pointer
    resolves to nothing therefore publishes as an empty shell, cannot be shown
    by the review application, and is invisible to the deduplication invariant,
    which is stated over objects that exist.

    The sibling of :func:`_refuse_invalid_contexts`, and added for the same
    reason: the merge path is what produces these flows, and #228 found 189 of
    them only by joining the two tables by hand, long after the run that wrote
    them.

    *known_object_ids* is the merge's own index, which carries the objects
    loaded from the database plus every object created during this merge -- the
    same set the datastore sync writes.

    :raises ValueError: if any merged flow names a flow object that is not in
        *known_object_ids*.
    """
    missing: dict[str, int] = {}
    for flow in merged_elementary:
        object_id = flow.flow_object_id
        if object_id not in known_object_ids:
            missing[object_id] = missing.get(object_id, 0) + 1
    if missing:
        logger.error(
            "dangling_merged_flow_objects",
            object_count=len(missing),
            flow_count=sum(missing.values()),
            examples=sorted(missing)[:20],
        )
        raise ValueError(
            f"{sum(missing.values())} merged flow(s) name {len(missing)} flow "
            f"object(s) that do not exist; refusing to write artifacts. "
            "Flow objects, with the flows naming them:\n  "
            + "\n  ".join(
                f"{object_id or '<empty>'}: {count}"
                for object_id, count in sorted(missing.items())
            )
        )
    logger.info("validated_merged_flow_objects", flow_count=len(merged_elementary))


def _refuse_unrecorded_land_groupings(
    matches: list[PreparedMatch | AlgorithmMatch],
    *,
    list_name: str,
) -> None:
    """Stop the merge before it folds land classes nobody has decided to fold.

    A correspondence table maps one flow at a time, so it never states that
    several land classes have become one; applied flow by flow it does it
    anyway, and nothing in the published list says so.  Five of ecoinvent's
    landfill classes were one `Dump Site`, twice over, until #111 measured it.

    The third sibling of :func:`_refuse_invalid_contexts` and
    :func:`_refuse_dangling_flow_objects`, and refusing rather than warning for
    the same reason: the fold is invisible in the output it produces, so a
    warning is a line in a log nobody re-reads a month later.  Accepting one is
    a row in ``land-flow-groupings.json`` with its reasoning; rejecting one is a
    ``decline`` in the list's match overrides.  Either is a decision, and this
    is what makes the build ask for one.

    :raises ValueError: if two or more of *list_name*'s rows reach one land flow
        and no grouping accounts for them.
    """
    problems = unrecorded_land_groupings(
        matches, list_name=list_name, recorded=load_land_flow_groupings()
    )
    if problems:
        logger.error(
            "unrecorded_land_groupings", source=list_name, count=len(problems),
        )
        raise ValueError(
            f"{len(problems)} land flow(s) are reached by more than one "
            f"{list_name} row without a grouping saying so; refusing to write "
            f"artifacts. Either the fold is meant, and belongs in "
            f"land-flow-groupings.json with the reason, or it is not, and the "
            f"rows belong in the list's match overrides as declines:\n  "
            + "\n  ".join(problems)
        )
    logger.info("validated_land_groupings", source=list_name)


def merge_source_list(
    source: SourceList,
    *,
    run_id: str | None = None,
    sequence: int = 0,
    transformers: list[Transformer] | None = None,
    consensus_is_partial: bool = False,
    max_rows: int | None = None,
    keep_uuids: Iterable[str] | None = None,
    timings: RunTimings | None = None,
) -> str:
    """Merge *source*'s flows into the transformed elementary flows.

    Load, enrich, index, match every row, place what did not match, report,
    persist, and check what was persisted.  Each of those is a function
    elsewhere in this package; what is here is the order they run in and what
    they hand each other.

    Returns the run id.  The run is recorded in the database rather than in a
    per-version JSON file, so there is no output path to hand back.

    `run_id` is supplied by `build`, so that the transform and every source list
    merged after it belong to one run.  `sequence` is where this list came in
    that order, which matters because a later list can match a flow an earlier
    one created.

    When no `run_id` is given this call owns the run: it opens and closes it,
    and looks for conflicts afterwards.  When `build` supplies one, `build` does
    those, because opening a run per source list would erase the previous ones
    and a conflict is a property of the whole set.

    `transformers` are the *already set up* instances the transform stage used.
    Given them, this list is enriched before it is matched -- which is what the
    two-pass workflow used a second build for.  Omitting them merges the list
    raw; that is what a caller with no transform stage of its own gets, not a
    supported way to run `build`.

    `consensus_is_partial` says that the consensus list being merged into is a
    bounded slice of the base list (`build --max-flows`) rather than all of it.
    The merge has to be told, because it cannot tell: a flow object it cannot
    find is a stale curated decision on a full run and an ordinary consequence
    of the bound on a smoke run, and those want opposite treatment (#228).

    `max_rows` and `keep_uuids` bound the *other* side of the same run.
    `--max-flows` bounds the transform and this stage went on matching every
    source row against it -- all 9,850 ecoinvent 3.12 rows against a 400-flow
    consensus list, 25.9 s of a 135 s verification run on 2026-08-15, of which
    21.7 s was running the transformer chain over rows the run was not about.
    A bound here is the same prefix-plus-named rule the transform uses
    (`bounded_sample`), for the same reason: a prefix alone is a sample nobody
    chose, so a run about particular rows names them with
    `--include-source-uuid`.

    What the bound cannot do is hide itself.  `merge_run_inputs` records the
    limit and how many rows the list actually ships, so a bounded merge is
    visible in the database, in the artifact snapshot `tools/verify_run.py`
    takes of it, and to `assess`, which refuses to record a baseline from one.

    `timings` is the build's recorder; this stage and its sub-stages go into
    it.  A caller with none gets one of its own and writes it here.
    """
    owns_run = run_id is None
    owns_timings = timings is None
    timings = timings if timings is not None else RunTimings()
    # The whole of this list's merge, beside the sub-stages below.  The parts
    # do not add up to it -- the reporting passes after the writes are in
    # neither -- and that gap is the point of keeping the total.
    merge_started = perf_counter()
    run_id = run_id or uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    with timings.stage("merge_load_working_set", detail=source.key):
        flow_objects, elementary = _load_working_set(CONSENSUS_DB_FILEPATH)
    # Records, loaded and repaired by the source list itself.  The merge used to
    # read and fix the file here, which is why its source flows were the last
    # dict-shaped data in the pipeline.
    with timings.stage("merge_load_flows", detail=source.key):
        source_flows = source.load_flows()
    available_rows = len(source_flows)
    kept_by_uuid = 0
    # Bounded here, before the enrichment below and the matching after it:
    # enriching a row this run will not match is the same work done to be
    # thrown away that #88 removed on the consensus side.
    if max_rows is not None:
        source_flows, kept_by_uuid = bounded_sample(
            source_flows,
            max_rows,
            keep_uuids,
            option="--include-source-uuid",
            list_name=source.key,
        )
        logger.info(
            "bounded_source_rows",
            source=source.key,
            count=len(source_flows),
            available_rows=available_rows,
            max_rows=max_rows,
            kept_by_uuid=kept_by_uuid,
        )
    if transformers:
        with timings.stage("merge_enrich", detail=source.key):
            _enrich_against_consensus(
                source=source,
                source_flows=source_flows,
                transformers=transformers,
                timings=timings,
            )

    mapping_file = source.prepared_match_table
    context_expectations, consensus_context_strings = _load_context_expectation_indexes(source)
    # The row logic reads its lookups from `indexes` and writes its results to
    # `accumulator`; nothing else is threaded through it.
    with timings.stage("merge_build_indexes", detail=source.key):
        indexes = build_merge_indexes(
            flow_objects,
            context_expectations=context_expectations,
            consensus_context_strings=consensus_context_strings,
            prepared_context_decisions=load_prepared_context_decision_index(source),
            mapping_file=mapping_file,
            source=source,
        )
    accumulator = build_merge_accumulator(elementary)
    units_index = build_units_index()
    external_names_by_cas = _load_external_names_by_cas()
    source_flow_by_uuid: dict[str, Flow] = {
        flow.uuid.strip(): flow for flow in source_flows if flow.uuid.strip()
    }

    # What this release registers each flow as, for the curated targets that
    # record having been checked against a renumbering.  Read off the flows the
    # merge is about to match rather than the shipped file, so a manual fix to
    # a registry number is the number the check is asked about (#109).
    registered_as = {
        uuid: tuple(flow.cas_numbers)
        for uuid, flow in source_flow_by_uuid.items()
        if flow.cas_numbers
    }

    with timings.stage("merge_match_rows", detail=source.key):
        match_source_rows(
            source_flows=source_flows,
            replace_table=load_prepared_match_table(
                source, registered_as=registered_as
            ),
            units_index=units_index,
            indexes=indexes,
            accumulator=accumulator,
        )
    prepared_context_inconsistencies = find_prepared_context_inconsistencies(
        indexes=indexes, accumulator=accumulator
    )

    # --- Manual additions ---
    unmatched = accumulator.unmatched
    manual_additions = apply_manual_additions(
        unmatched=unmatched,
        source_flow_by_uuid=source_flow_by_uuid,
        external_names_by_cas=external_names_by_cas,
        units_index=units_index,
        indexes=indexes,
        accumulator=accumulator,
        consensus_is_partial=consensus_is_partial,
    )
    if manual_additions:
        placed_uuids = {row.source_uuid for row in manual_additions}
        unmatched = [row for row in unmatched if row.source_uuid not in placed_uuids]

    # --- Created flows ---
    # A row that matched nothing names a substance the consensus list does not
    # have, so the merge adds it.  After the manual additions, deliberately: a
    # curator's grouping is a decision about where a row belongs, and a decision
    # outranks the fallback of minting a new substance for it.
    new_flow_objects, created_flows = create_flows_for_unmatched_rows(
        unmatched=unmatched,
        source_flow_by_uuid=source_flow_by_uuid,
        units_index=units_index,
        indexes=indexes,
        accumulator=accumulator,
    )
    if created_flows:
        created_uuids = {row.source_uuid for row in created_flows}
        unmatched = [row for row in unmatched if row.source_uuid not in created_uuids]

    enriched_with_candidates, enriched_without_candidates = enrich_unmatched_rows(
        unmatched=unmatched,
        source_flow_by_uuid=source_flow_by_uuid,
        external_names_by_cas=external_names_by_cas,
        indexes=indexes,
        accumulator=accumulator,
    )

    # Over both kinds of match, because a fold is a fold whether a curator's
    # table made it or the selector did.
    _refuse_unrecorded_land_groupings(
        [*accumulator.prepared_matches, *accumulator.algorithm_matches],
        list_name=source.list_name,
    )
    _refuse_invalid_contexts(accumulator.merged_elementary)
    # After the creations, which add their objects to the index as they mint
    # them, so the check sees the objects this merge is about to write.
    _refuse_dangling_flow_objects(
        accumulator.merged_elementary, set(indexes.flow_objects_by_id)
    )

    # An annotation on a match rather than an outcome of its own: the source flow
    # and the flow it landed on are measured in different units.  Computed over
    # the matches that were made, prepared and algorithmic alike -- the
    # algorithmic ones need it more, because nobody has looked at those pairings.
    allowed_unit_changes = load_unit_change_allowlist()
    unit_mismatch_uuids = find_unit_mismatches(
        [*accumulator.prepared_matches, *accumulator.algorithm_matches],
        units_index=units_index,
        allowed=allowed_unit_changes,
    )
    # The subset of those that cross from one kind of quantity to another --
    # a mass onto an energy, an area onto an area-year -- and that no allowlist
    # entry accepts.  Warned about rather than refused (#171): see
    # `report_unrecorded_crossings` for why, and
    # `merge.unit_crossings_unrecorded` for what keeps it at nothing.
    report_unrecorded_crossings(
        [*accumulator.prepared_matches, *accumulator.algorithm_matches],
        units_index=units_index,
        allowed=allowed_unit_changes,
    )
    outcomes = build_outcomes(
        run_id=run_id,
        source=source,
        prepared_matches=accumulator.prepared_matches,
        algorithm_matches=accumulator.algorithm_matches,
        manual_additions=manual_additions,
        created_flows=created_flows,
        unmatched=unmatched,
        inconsistencies=prepared_context_inconsistencies,
        unit_mismatch_uuids=unit_mismatch_uuids,
        enriched_with_candidates=enriched_with_candidates,
        enriched_without_candidates=enriched_without_candidates,
    )

    if owns_run:
        start_run(CONSENSUS_DB_FILEPATH, run_id=run_id, started_at=started_at)
    write_source_outcomes(
        CONSENSUS_DB_FILEPATH,
        run_id=run_id,
        source_input=MergeRunInput(
            run_id=run_id,
            list_name=source.list_name,
            list_version=source.list_version,
            sequence=sequence,
            source_path=str(source.flows_path),
            prepared_match_table=mapping_file or "",
            row_count=len(source_flows),
            # What the list ships, beside what this run read of it.  Two
            # numbers rather than one flag, because "3,412 rows merged" and
            # "3,412 of 21,088 rows merged" are different claims and the row
            # count alone cannot tell them apart.
            available_row_count=available_rows,
            max_rows=max_rows,
        ),
        outcomes=outcomes,
    )
    if owns_run:
        finish_run(
            CONSENSUS_DB_FILEPATH,
            run_id=run_id,
            finished_at=datetime.now(timezone.utc).isoformat(),
            stats={"elementary_flow_count": len(accumulator.merged_elementary)},
        )
        detect_conflicts(CONSENSUS_DB_FILEPATH, run_id)

    logger.info(
        "wrote_merge_outputs",
        source=source.key,
        run_id=run_id,
        outcome_count=len(outcomes),
        prepared_match_count=len(accumulator.prepared_matches),
        algorithm_match_count=len(accumulator.algorithm_matches),
        manual_addition_count=len(manual_additions),
        created_flow_count=len(created_flows),
        created_flow_object_count=len(new_flow_objects),
        unmatched_count=len(unmatched),
        prepared_context_inconsistency_count=len(prepared_context_inconsistencies),
        unit_mismatch_count=len(unit_mismatch_uuids),
    )

    sync_merge_results(
        new_flow_objects=new_flow_objects, indexes=indexes, accumulator=accumulator
    )

    # Over the whole working set rather than the objects this pass minted, and
    # for the same reason `recompute_match_strengths` below is: whether a name
    # answers for two substances is a fact about the list, and a merge that
    # asked it only of its own batch would miss the substance an earlier stage
    # wrote (#113).  After the writes, because the write-back is what the
    # withdrawals need and `sync_merge_results` has to have put the minted rows
    # there for it to update them.
    changed_synonyms: set[str] = set()
    synonym_objects = list(indexes.flow_objects_by_id.values())
    synonym_stats = carry_member_names(
        synonym_objects, accumulator.merged_elementary, changed=changed_synonyms
    )
    synonym_stats["substances_rewritten"] = sync_flow_object_synonyms(
        synonym_objects, changed_synonyms, CONSENSUS_DB_FILEPATH
    )
    replace_stage_stats(
        CONSENSUS_DB_FILEPATH,
        stage=MERGE_SYNONYM_STAGE,
        counts=dict(synonym_stats),
    )

    # After the synonym pass, because that is the last writer of an object's
    # labels, and over the whole database rather than this pass's flows: a
    # merge moves object labels on flows it never touches -- a minted object's
    # name wins a contest, `carry_member_names` demotes a second preferred
    # label -- and the flows of a pre-existing object are not otherwise
    # rewritten, which is how 886 published flows came to carry a name their
    # own substance had superseded (#7).  Replaced rather than added to, and
    # the queue with it, because this pass has seen every earlier pass's flows
    # and its answer is the whole of it.
    substance_label_stats, substance_label_items = apply_substance_labels_to_database(
        CONSENSUS_DB_FILEPATH
    )
    replace_stage_stats(
        CONSENSUS_DB_FILEPATH,
        stage=MERGE_SUBSTANCE_LABEL_STAGE,
        counts=dict(substance_label_stats),
    )
    replace_queue_items(
        CONSENSUS_DB_FILEPATH,
        queue=ReviewQueue.SUBSTANCE_LABEL_CONFLICT,
        items=substance_label_items,
    )

    # After the flows have been written, and asked of all of them: the transform
    # asks the same question of its own output, before this pass adds anything,
    # so on its own it described 116 groups of a published 145 (#60).  The
    # counters go to a stage of their own beside the transform's rather than
    # over them -- two numbers is the comparison -- and the queue is replaced
    # rather than added to, because this pass has seen every earlier pass's
    # flows as well and its answer is the whole of it.
    collision_stats, collision_items = report_merged_collisions(
        accumulator=accumulator, labels_by_object=indexes.flow_object_label_by_id
    )
    replace_stage_stats(
        CONSENSUS_DB_FILEPATH, stage=MERGE_COLLISION_STAGE, counts=collision_stats
    )
    replace_queue_items(
        CONSENSUS_DB_FILEPATH,
        queue=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
        items=collision_items,
    )

    # The same question asked the other way round, and asked here for the same
    # reason: a substance published in two places that are not one another's
    # coarsening, where the merge wrote one of the two (#87).  The collision
    # check reports two flows in one place; nothing reported one substance in
    # two, because a row that creates a flow in a second context looks like an
    # ordinary creation from the inside.  Replaced rather than added to, again
    # because this pass sees every earlier pass's flows.
    place_stats, place_items = report_substance_places(
        accumulator=accumulator, labels_by_object=indexes.flow_object_label_by_id
    )
    replace_stage_stats(
        CONSENSUS_DB_FILEPATH, stage=MERGE_PLACE_STAGE, counts=place_stats
    )
    replace_queue_items(
        CONSENSUS_DB_FILEPATH,
        queue=ReviewQueue.SUBSTANCE_IN_TWO_PLACES,
        items=place_items,
    )

    # The narrower cousin of the check above, and the guard #193 asked for: a
    # land-class substance has exactly one right dimension, stated by its own
    # class, so a flow of one outside `Land Use` is wrong without needing a
    # second place to disagree with.  This is what would have caught the seven
    # compartment-misfiled land rows on the first five-list build, and the
    # population it guards grows with every list.
    land_stats, land_items = report_land_classes_out_of_place(
        accumulator=accumulator, labels_by_object=indexes.flow_object_label_by_id
    )
    replace_stage_stats(
        CONSENSUS_DB_FILEPATH, stage=MERGE_LAND_PLACE_STAGE, counts=land_stats
    )
    replace_queue_items(
        CONSENSUS_DB_FILEPATH,
        queue=ReviewQueue.LAND_CLASS_OUT_OF_PLACE,
        items=land_items,
    )

    # Before the export, and over the whole database rather than this pass's
    # flows: how strong a mapping is depends on how many of one list's flows end
    # up on one consensus flow, which is a fact about the list and not about the
    # row that happened to be merged (#76).  Every list recounts, because this
    # one's flows can join a consensus flow an earlier list already mapped onto.
    recompute_match_strengths(CONSENSUS_DB_FILEPATH)

    # The only artifact with a downstream consumer, projected from the database.
    with timings.stage("merge_simple_export", detail=source.key):
        write_simple_export(CONSENSUS_DB_FILEPATH, HARMONISED_FLOWS_SIMPLE_FILEPATH)

    # After the export, because the export is what publishes a retired
    # identifier's redirect, and replaced rather than added to for the reason
    # every counter here is: a later list mints flows an earlier one did not, so
    # each merge's answer covers the whole database and supersedes the last (#102).
    replace_stage_stats(
        CONSENSUS_DB_FILEPATH,
        stage=FLOW_RETIREMENT_STAGE,
        counts=dict(retirement_stats(CONSENSUS_DB_FILEPATH)),
    )
    # And the identifiers that count leaves behind. A retirement this build
    # cannot answer used to be a number with nothing behind it, so nothing said
    # which identifiers had died or whether the substance was still published
    # somewhere a curator could point them at (#344).
    replace_queue_items(
        CONSENSUS_DB_FILEPATH,
        queue=ReviewQueue.RETIRED_IDENTIFIER_UNRESOLVED,
        items=retired_identifier_queue_items(CONSENSUS_DB_FILEPATH),
    )

    timings.record("merge", perf_counter() - merge_started, detail=source.key)
    if owns_timings:
        write_run_timings(CONSENSUS_DB_FILEPATH, timings=timings.records())

    return run_id
