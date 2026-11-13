"""Applying transformers to flows: the half of the engine that writes nothing.

A transformer proposes `Change` objects and `apply_transformers` applies them,
which is what produces the change log. `pipeline.engine` runs a whole build on
top of this, and imports everything a build needs to do it; this module imports
only what applying a change needs.

The two are separate so that `lookup` can run the first steps of the chain on
somebody's row without importing the rest of a build. A plain install has the
packages this module needs and not the ones `engine` does, and
`tests/test_install_boundaries.py` holds it to that.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from time import perf_counter
from typing import Any, Protocol

import structlog

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.pipeline.review_records import ChangeEvent
from brightway_flows.pipeline.timings import RunTimings
from brightway_flows.sources import SourceList

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
    # Imported here, not above: layering reaches the element and ion fetchers,
    # and only a transformer that groups by substance comes this way. The four
    # steps a lookup runs do not, and a lookup has to import without them
    # (`tests/test_install_boundaries.py`).
    from brightway_flows.flow_layers import resolve_flow_layers

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
