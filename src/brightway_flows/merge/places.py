"""One substance, in two places no vaguer version of the other.

`pipeline/collisions.py` asks whether one place holds two flows.  This asks the
other half of the same question: whether one substance holds two *places*.

The two questions look symmetrical and are not.  A collision is a pair the
pipeline is one field away from collapsing; this is a pair that can never meet.
Two flows of one substance in two contexts are two identifiers, and an inventory
using one with a method characterising the other do not connect -- there is
nothing to collapse, nothing to deprecate, and nothing that goes wrong at any
single step.  #87 is that: `Energy, geothermal, converted` published in
`Resource -> Ground` for three lists and in `Resource -> Biotic` for BAFU, one
substance, two flows, and no symptom at all until somebody characterises one of
them and an inventory that used the other scores zero.

**Where a substance is released is a fact about the process; where it is taken
from is a fact about the substance.**  That asymmetry is the whole of the rule.
Zinc emitted to air and to a river is two ordinary flows, and a list that ships
only one of them is not disagreeing with a list that ships the other.  But peat
comes out of the ground, wood off a living tree, and geothermal heat out of the
rock beneath: no process chooses, so two of those on one substance are two
answers to a question that has one.  So release contexts -- the `Environmental`
dimension -- are set aside, and what is compared is everything else a substance
was filed under: resources, land use, the inventory indicators.

**Two places, or one described twice?**  `context_contradicts` already draws
that line for the merge, and this reads it in both directions.  A context that
leaves an axis unstated makes no claim on it, so `Water -> Unknown` and
`Water -> River` are one place at two levels of detail and a flow in each is
ordinary -- BAFU names rivers where EF 3.1 has only unspecified water.  Two
contexts that each state something the other denies are two places.  Reading it
in one direction only would have reported every one of those river rows.

**Asked of a place, not of a pair.**  What is reported is a minted place that
*no other* place of the substance is one description of -- one with nowhere else
to belong.  Asking it pairwise instead would report a river beside a ground
resource while the substance also holds unspecified water, which is a flow that
found the place it wanted and a third context sitting next to it.  On the
2026-08-14 build the two rules pick the same fifteen substances; the difference
is which of them a future build would invent.

**Only where the merge minted one of them.**  A split that lives entirely in the
base list is not a disagreement: EF 3.1 publishes magnesium as a ground resource
and as a water resource on purpose, and nobody contradicted it.  The moment a
second list's row lands somewhere the substance was not, two lists have answered
differently, and it is that flow -- the one the merge wrote -- that nothing
watched.  A matched row is reported already, as a context inconsistency against
the flow it landed on; a row that *creates* a flow in a second context raised
nothing at all, because from the inside nothing looks wrong.

**Not "two places no single list holds at once"**, which is how #87 puts it and
which the data does not support.  Read literally that rule asks whether some
source list files the substance in both places itself, and on the 2026-08-14
build it reports 8 substances and misses both of the two the issue is about:
BAFU ships `Energy, geothermal, converted` in `resources / in ground` *and* in
`resources / biotic`, and `Peat` in both as well, so BAFU holds both places for
each of them and the pair excuses itself.  A list filing one name in two
compartments is the defect seen from closer up, not evidence against it.  The
rule here reports 15, those 8 among them.

**Reported, not enforced**, for the same reason as the collision check: which of
the two places is right is a question about the substance, and the pipeline has
no way to answer it.  What it can do is stop the question going unasked.  The
answer, when a curator gives one, is a rule in `context-manual-mapping.json`
saying where that list's row belongs, or a target in the list's match overrides
saying which substance it meant.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import structlog

from brightway_flows.domain.context import Dimension
from brightway_flows.domain.context_registry import (
    UnknownContextIRIError,
    context_dict_for_iri,
    context_display_parts,
    context_for_iri,
)
from brightway_flows.merge.collisions import MergedFlow, minted_flow_ids
from brightway_flows.merge.contexts import context_contradicts
from brightway_flows.merge.state import MergeAccumulator
from brightway_flows.domain.lcia.records import non_zero_factor_count
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)

logger = structlog.get_logger(__name__)

#: The stage the counts are filed under in `run_stats`, beside the two
#: collision stages rather than inside either.
MERGE_PLACE_STAGE = "merge_substance_places"

#: The stage the land-class guard's tallies are recorded under (#193).
MERGE_LAND_PLACE_STAGE = "merge_land_class_places"


def is_a_release(context_iri: str) -> bool:
    """Whether *context_iri* names somewhere a substance goes rather than
    somewhere it comes from.

    An IRI this project does not know answers False, which keeps it in the
    comparison -- where `two_places` then says it is no place at all, because
    `context_contradicts` will not read an unknown context either.  So an
    unresolvable context can only quieten this report, never populate it.  None
    can reach here anyway: `_refuse_invalid_contexts` stops the build over the
    same list before the report runs, and a context this project cannot resolve
    is that defect rather than this one.
    """
    try:
        context = context_for_iri(context_iri)
    except UnknownContextIRIError:
        return False
    return context.dimension == Dimension.ENVIRONMENTAL


def two_places(first_iri: str, second_iri: str) -> bool:
    """Whether two contexts are two places rather than one at two detail levels.

    True when each states something the other denies.  `context_contradicts` is
    directional -- a target that leaves an axis unstated contradicts nothing --
    so a coarsening answers True one way and False the other, and requiring both
    is what keeps `Water -> River` and `Water -> Unknown` one place.
    """
    return context_contradicts(first_iri, second_iri) and context_contradicts(
        second_iri, first_iri
    )


def display_context(context_iri: str) -> str:
    """A context IRI as the string the database's `context_display` prints.

    The same rendering, so a queue item and a flow row name the place the same
    way; the IRI is carried beside it for anything that has to compare.
    """
    try:
        parts = context_display_parts(context_dict_for_iri(context_iri))
    except UnknownContextIRIError:
        return context_iri
    return " → ".join(parts) if parts else context_iri


@dataclass(frozen=True)
class Place:
    """One context a substance is published in, and what sits there."""

    context_iri: str
    context: str
    elementary_flow_ids: tuple[str, ...]
    units: tuple[str, ...]
    #: The `source` of each flow here: the list that published it, which for a
    #: minted flow names the merge pass that wrote it.
    sources: tuple[str, ...]
    factor_count: int
    minted: tuple[str, ...]

    @property
    def was_minted(self) -> bool:
        return bool(self.minted)


@dataclass(frozen=True)
class SplitSubstance:
    """One substance published in two places, and which of them is stranded."""

    flow_object_id: str
    #: Every non-release place the substance is published in, stranded or not:
    #: a place is only stranded relative to the others, so the others are what
    #: makes the finding readable.
    places: tuple[Place, ...]
    #: The context IRIs of the places the merge wrote that no other place of
    #: this substance is a description of.  Never empty on a result.
    stranded: tuple[str, ...]

    @property
    def elementary_flow_ids(self) -> tuple[str, ...]:
        return tuple(
            flow_id for place in self.places for flow_id in place.elementary_flow_ids
        )

    @property
    def minted(self) -> tuple[str, ...]:
        """The flows the merge wrote into a place that belongs nowhere else.

        Not every minted flow on the substance: one written into a place
        another place describes is a row that found where it wanted to be, and
        counting it here would say the merge stranded a flow it did not.
        """
        return tuple(
            flow_id
            for place in self.places
            if place.context_iri in self.stranded
            for flow_id in place.minted
        )


def places_of(
    flows: list[MergedFlow], minted: frozenset[str]
) -> dict[str, list[Place]]:
    """The non-release contexts each substance is published in.

    Deprecated flows are excluded, because a deprecated flow is a place the list
    has already left; so are flows with no context or no substance, which are
    unplaced rather than misplaced and are reported elsewhere.  A flow whose
    context IRI is not one this project knows is neither, and cannot reach here:
    `_refuse_invalid_contexts` has already stopped the build over this same
    list.
    """
    by_key: dict[tuple[str, str], list[MergedFlow]] = {}
    for flow in flows:
        if flow.owl_deprecated:
            continue
        if not flow.flow_object_id or not flow.context_iri:
            continue
        if is_a_release(flow.context_iri):
            continue
        by_key.setdefault((flow.flow_object_id, flow.context_iri), []).append(flow)

    out: dict[str, list[Place]] = {}
    for (object_id, context_iri), group in by_key.items():
        flow_ids = tuple(sorted(flow.elementary_flow_id for flow in group))
        out.setdefault(object_id, []).append(
            Place(
                context_iri=context_iri,
                context=display_context(context_iri),
                elementary_flow_ids=flow_ids,
                units=tuple(sorted({flow.unit for flow in group if flow.unit})),
                sources=tuple(sorted({flow.source for flow in group if flow.source})),
                factor_count=sum(
                    non_zero_factor_count(flow.lcia_methods)
                    for flow in group
                ),
                minted=tuple(
                    flow_id for flow_id in flow_ids if flow_id in minted
                ),
            )
        )
    for places in out.values():
        places.sort(key=lambda place: place.context_iri)
    return out


def find_split_substances(
    flows: list[MergedFlow], minted: frozenset[str]
) -> list[SplitSubstance]:
    """Every substance holding a minted place that no other place describes."""
    found: list[SplitSubstance] = []
    for object_id, places in sorted(places_of(flows, minted).items()):
        if len(places) < 2:
            continue
        stranded = tuple(
            place.context_iri
            for place in places
            if place.was_minted
            and all(
                two_places(place.context_iri, other.context_iri)
                for other in places
                if other.context_iri != place.context_iri
            )
        )
        if not stranded:
            continue
        found.append(
            SplitSubstance(
                flow_object_id=object_id,
                places=tuple(places),
                stranded=stranded,
            )
        )
    return found


def report_land_classes_out_of_place(
    *, accumulator: MergeAccumulator, labels_by_object: dict[str, str]
) -> tuple[Counter, list[ReviewQueueItem]]:
    """Report every live flow of a land-class substance outside `Land Use`.

    The narrower cousin of :func:`report_substance_places`, asked with the
    class's own authority rather than by comparing places: a land class has
    exactly one right dimension, stated by its direction, so a flow of one
    outside `Land Use` is wrong without a second place to disagree with
    (#193).  Seven AGRIBALYSE rows were published as ground and water
    resources on the first five-list build because the vendor's compartment
    decided; the resolve rule now asks the class first, and this is the guard
    that says so on the build if a new list finds a third way in.
    """
    # Function-local for the reason the land hierarchy pass gives: both ends
    # recompute the object id from the class, so they cannot disagree about
    # which object is which class.
    from brightway_flows.domain.land_flow_classes import published_land_classes
    from brightway_flows.flow_layers.land_hierarchy import land_object_id

    land_ids = {
        land_object_id(value): value
        for value in published_land_classes().values()
    }

    counts: Counter = Counter()
    counts["land_class_flows"] = 0
    counts["land_classes_out_of_place"] = 0

    items: list[ReviewQueueItem] = []
    for row in (MergedFlow.from_record(f) for f in accumulator.merged_elementary):
        if row.owl_deprecated or row.flow_object_id not in land_ids:
            continue
        counts["land_class_flows"] += 1
        try:
            dimension = context_for_iri(row.context_iri).dimension
        except UnknownContextIRIError:
            dimension = None
        if dimension is Dimension.LAND_USE:
            continue
        counts["land_classes_out_of_place"] += 1
        label = labels_by_object.get(row.flow_object_id, row.flow_object_id)
        items.append(
            ReviewQueueItem(
                queue_name=ReviewQueue.LAND_CLASS_OUT_OF_PLACE,
                item_key=f"{row.flow_object_id}|{row.context_iri}",
                title=(
                    f"{label} is a land class published in "
                    f"{display_context(row.context_iri)}"
                ),
                severity=Severity.WARNING,
                uuid=row.elementary_flow_id,
                flow_object_id=row.flow_object_id,
                payload={
                    "flow_object_id": row.flow_object_id,
                    "label": label,
                    "land_class_key": land_ids[row.flow_object_id].key,
                    "direction": land_ids[row.flow_object_id].direction.name,
                    "elementary_flow_id": row.elementary_flow_id,
                    "context_iri": row.context_iri,
                    "context": display_context(row.context_iri),
                    "unit": row.unit,
                    "factor_count": non_zero_factor_count(row.lcia_methods),
                },
            )
        )
    items.sort(key=lambda item: item.item_key)
    for index, item in enumerate(items):
        item.item_index = index
    logger.info("reported_land_classes_out_of_place", **dict(counts))
    return counts, items


def report_substance_places(
    *, accumulator: MergeAccumulator, labels_by_object: dict[str, str]
) -> tuple[Counter, list[ReviewQueueItem]]:
    """Count the substances published in two places and raise one item each.

    Asked of the merged list, like the collision report beside it, and for the
    same reason: the flows this is about are the ones the merge adds, so a check
    that ran before it would describe a list nobody publishes.  Cheap enough to
    ask of all of them: the 95,193 flows of the 2026-08-14 build in 0.14
    seconds, 15 substances found.

    *labels_by_object* is `MergeIndexes.flow_object_label_by_id`, so an item can
    name the substance rather than its identifier.
    """
    merged = [MergedFlow.from_record(flow) for flow in accumulator.merged_elementary]
    minted = minted_flow_ids(merged)
    found = find_split_substances(merged, minted)

    counts: Counter = Counter()
    # Seeded, so that a run which reports none says so rather than saying
    # nothing: an absent row in `run_stats` means a stage did not look.
    counts["substances_in_two_places"] = len(found)
    counts["places_belonging_nowhere_else"] = 0
    counts["flows_in_a_split_substance"] = 0
    counts["flows_minted_into_a_second_place"] = 0
    counts["splits_with_the_factors_on_one_side"] = 0

    items: list[ReviewQueueItem] = []
    for index, split in enumerate(found):
        counts["places_belonging_nowhere_else"] += len(split.stranded)
        counts["flows_in_a_split_substance"] += len(split.elementary_flow_ids)
        counts["flows_minted_into_a_second_place"] += len(split.minted)
        counts[f"substance_in_{len(split.places)}_places"] += 1
        characterised = [place for place in split.places if place.factor_count]
        if len(characterised) == 1 and len(split.places) > 1:
            # The consequence, rather than a second description of the cause:
            # one of these places answers for the substance and the others
            # publish a flow with no number on it, so an inventory that picked
            # the wrong one scores zero and nothing says why.
            counts["splits_with_the_factors_on_one_side"] += 1
        label = labels_by_object.get(split.flow_object_id, split.flow_object_id)
        items.append(
            ReviewQueueItem(
                queue_name=ReviewQueue.SUBSTANCE_IN_TWO_PLACES,
                item_key=split.flow_object_id,
                title=(
                    f"{label} is published in {len(split.places)} places: "
                    + ", ".join(place.context for place in split.places)
                ),
                # Always `review`: every group here needs a flow the merge
                # wrote, so the pipeline has acted and what it did wants
                # confirming.  There is no `info` half of this queue.
                severity=Severity.REVIEW,
                flow_object_id=split.flow_object_id,
                item_index=index,
                payload={
                    "flow_object_id": split.flow_object_id,
                    "substance": label,
                    "contexts": [place.context for place in split.places],
                    "units": sorted(
                        {unit for place in split.places for unit in place.units}
                    ),
                    "sources": sorted(
                        {source for place in split.places for source in place.sources}
                    ),
                    "places": [
                        {
                            "context_iri": place.context_iri,
                            "context": place.context,
                            "elementary_flow_ids": list(place.elementary_flow_ids),
                            "units": list(place.units),
                            "sources": list(place.sources),
                            "lcia_factor_count": place.factor_count,
                            "minted_by_merge": list(place.minted),
                            "belongs_nowhere_else": place.context_iri
                            in split.stranded,
                        }
                        for place in split.places
                    ],
                    "belongs_nowhere_else": list(split.stranded),
                    "minted_by_merge": list(split.minted),
                },
            )
        )

    logger.info("substances_in_two_places", **dict(counts))
    return counts, items
