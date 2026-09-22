"""Two live flows of one substance, in one context, in one unit.

`ElementaryFlow` says ``(flow_object_id, context_iri)`` must be unique across
non-deprecated flows, and nothing checked it.  That is not a style rule: those
three fields are most of what `pipeline/deduplication.py` signs on, so two flows
sharing them are two flows the pipeline is one field away from collapsing --
and when it does collapse them, a lexicographic identifier sort picks which one
keeps its identity.

That is #31.  EF 3.1's `Water use` publishes a balanced pair of withdrawal and
return factors; `Water to Cooling` and `Water to turbine` shared an object, a
context and a unit, and were told apart only by a `general_comment` neither
carried.  The return was deprecated onto the withdrawal, and a balanced set
became a 434x one-sided charge.  #251 section 3 is the same shape seen from the
substance side: eight EF flows on one object because the only thing separating
them was a name no field held.

**Reported, not enforced.**  A collision is a question -- are these two flows or
one? -- and the pipeline cannot answer it.  What it can do is stop the question
going unasked, which is what an audit had to do for water.

**What an item says**, all three of it about deduplication rather than about the
pipeline at large: which flow deduplication would keep if the group ever became
collapsible, which of the fields it signs on still differ -- the answer to what
is holding these two apart -- and whether the two disagree about a factor they
both publish.  None of it is a prediction.  The transform runs this *after* the
deduplication pass, deliberately, so every group it reports is one deduplication
has already declined to collapse and will decline again for as long as
`differing_fields` is not empty.  The survivor is a conditional, and #58 is it
having been written as a forecast, computed by a rule deduplication does not
use.  The merge's run of it is a conditional in a second way as well -- see the
stage paragraph below.

This is also the general form of the gap #260 left open when it published the
ecoinvent conversion factors: *"`merge.unit_changes` is unit-based, so a
substance change at identical units is invisible to it"*, its example being
`TiO2 ... in crude ore` mapping onto elemental titanium, kg to kg.  A unit-based
check cannot see two substances that agree on units; this one keys on the
substance and does.

**Asked of whatever wrote the flows last.**  The transform asks it of its own
output and the merge asks it again of the list it hands to the database, which
is what #60 is: the merge adds flows, and for as long as this ran only in the
transform the queue described 116 groups while the published database held 145.
The 29 it never saw carried 190 flows the merge had minted onto a substance,
context and unit another flow already occupied, every one of them with no
characterisation factors at all.  So a group carries the stage that produced it
-- `merge` when it needs those minted flows to exist at all, `transform` when it
would collide without them -- and *minted* is what the caller says it is:
`minted_flow_ids` names them, because which flows a stage added is the stage's
own knowledge and not something a flow's fields state.

The stage is not decoration, because what an item says about deduplication
means something different on each side of it.  Deduplication and the curated
rulings both run in the transform, so a `transform` group is one both have
already looked at and declined to collapse, while a `merge` group is one
neither has ever seen: its flows did not exist when they ran, and the next
build's transform starts from the base list again, so they never will.  A
ruling written against a `merge` collision is counted `collision_rulings_absent`
and does nothing.  Those groups are answered by curating the grouping that
minted them, not by ruling on the flows it produced.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import structlog

from brightway_flows.domain.lcia.records import non_zero_factor_count
from brightway_flows.flow_layers.contested_cas import (
    FACTOR_TOLERANCE,
    factor_rows,
    worst_disagreement,
)
from brightway_flows.pipeline.deduplication import (
    duplicate_survivor_rank,
    fields_holding_apart,
)
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)

logger = structlog.get_logger(__name__)

#: The stage a group is attributed to.  Written into every item's payload, so a
#: reader of one row knows which half of the build put it there without
#: comparing two queues.
STAGE_TRANSFORM = "transform"
STAGE_MERGE = "merge"


def is_deprecated(flow: Any) -> bool:
    return bool(getattr(flow, "owl_deprecated", None))


def collision_key(flow: Any) -> tuple[str, str, str]:
    return (
        str(getattr(flow, "flow_object_id", "") or ""),
        str(getattr(flow, "context_iri", "") or ""),
        str(getattr(flow, "unit", "") or ""),
    )


def find_collisions(elementary_flows: list[Any]) -> list[list[Any]]:
    """Groups of two or more live flows sharing object, context and unit.

    Deprecated flows are excluded: a deprecated flow *is* the record of a
    collision already resolved, and counting it again would report every
    resolution as an outstanding problem.

    :raises TypeError: if handed payloads rather than records.  Every field
        below is read by attribute, so a dict answers `""` to all of them and
        the whole list filters out as unplaced -- "no collisions" from a run
        that was never looked at.  The merge narrows its `ElementaryFlow`
        records to `merge.collisions.MergedFlow` before calling this, which is
        what puts `lcia_methods` and the merge's `source` label on one record.
    """
    if elementary_flows and isinstance(elementary_flows[0], dict):
        raise TypeError(
            "find_collisions reads flows by attribute and was handed payloads; "
            "a dict would answer nothing to every field and report no "
            "collisions at all."
        )
    by_key: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for flow in elementary_flows:
        if is_deprecated(flow):
            continue
        object_id, context_iri, _unit = key = collision_key(flow)
        if not object_id or not context_iri:
            # A flow with neither is not yet placed; the merge reports it
            # elsewhere and pairing it with another unplaced flow would be an
            # invented finding.
            continue
        by_key[key].append(flow)
    return [group for group in by_key.values() if len(group) > 1]


def factor_value_disagreement(group: list[Any]) -> tuple[float, dict[str, Any] | None, int]:
    """The largest relative disagreement between two flows of a group on one factor.

    `(worst, where, comparable)`, read from `worst_disagreement` -- the same
    comparison, against the same `FACTOR_TOLERANCE`, that decides a contested
    registry number in `flow_layers/contested_cas.py`.  The comparable key is
    the method alone, because a collision group is one context by construction.

    This is not the same question as "do these two carry the same *number* of
    factors", and on the 2026-08-12 build the two find disjoint sets: the count
    test flags 28 groups, this flags 6, and no group is in both.  A group where
    both flows carry two factors and disagree about both is invisible to a
    count, and all six of these are that shape (#281).
    """
    rows: list[tuple[Any, str, float]] = []
    for flow in group:
        side = str(getattr(flow, "elementary_flow_id", "") or "")
        if not side:
            continue
        for method, factor in factor_rows(flow):
            rows.append((method, side, factor))

    worst, at, comparable = worst_disagreement(rows)
    where: dict[str, Any] | None = None
    if at is not None:
        method, low, high = at
        where = {"method": method, "low": low, "high": high}
    return worst, where, comparable


def report_collisions(
    elementary_flows: list[Any],
    *,
    labels_by_object: dict[str, str] | None = None,
    minted_flow_ids: frozenset[str] | None = None,
) -> tuple[Counter, list[ReviewQueueItem]]:
    """Count the collisions and raise one queue item per group.

    Returns `(counts, items)`.  `counts` goes to `run_stats`, where a number
    that moves between runs is the signal: a stage that starts producing
    collisions is a regression, and one that stops producing them is the fix
    landing.

    Two counts about the characterisation, because they are two questions and
    on the current build they never agree.  `collision_with_unequal_factors` is
    "one of these holds factors the other does not", which is what cost #31 its
    factors and what #279's rulings are about.
    `collision_with_disagreeing_factor_values` is "these publish the same factor
    and say different things about it", which a count cannot see.

    *minted_flow_ids* names the flows the calling stage added to the list it is
    reporting on.  The transform passes nothing, because every flow it holds is
    one it read; the merge passes the flows it minted, and the counts then carry
    the merge-side keys -- present at zero, so the run a merge *stops* minting
    into an occupied place is as visible as the run it starts.  A group needing
    those flows to exist at all is attributed to the merge; one that would
    collide without them was already colliding and the merge only made it
    bigger, which is a different finding and is counted as one.

    Severity is the same distinction: a group of flows nobody added is
    `info`, and one the merge minted into is `review`, because there the
    pipeline did act -- it wrote a flow onto a substance, context and unit that
    another flow already held -- and what it did wants confirming.
    """
    groups = find_collisions(elementary_flows)
    minted = frozenset() if minted_flow_ids is None else minted_flow_ids
    counts: Counter = Counter()
    counts["collision_groups"] = len(groups)
    counts["collision_flows"] = sum(len(group) for group in groups)
    if minted_flow_ids is not None:
        counts["collision_groups_from_merge"] = 0
        counts["collision_flows_minted_by_merge"] = 0

    items: list[ReviewQueueItem] = []
    labels = labels_by_object or {}
    for index, group in enumerate(sorted(groups, key=lambda g: collision_key(g[0]))):
        object_id, context_iri, unit = collision_key(group[0])
        uuids = sorted(str(getattr(f, "elementary_flow_id", "") or "") for f in group)
        # Deduplication's count, which is also the `lcia_factor_count` column's:
        # a row is one factor, except a stated zero, which is none (#47).  The
        # two agree on all 94,409 flows of the 2026-08-12 build, so this is not
        # a correction -- it is the number beside a flow being the number that
        # ranks it, rather than a second count that could come to differ.
        factors = {
            str(getattr(f, "elementary_flow_id", "") or ""):
                non_zero_factor_count(getattr(f, "lcia_methods", None))
            for f in group
        }
        # Deduplication's own ordering, not a restatement of it: it ranks on how
        # many characterisation factors a flow carries and uses the identifier
        # only to break a tie, so the flow it would keep is usually not the
        # lowest identifier.  See `duplicate_survivor_rank`.
        would_keep = min(group, key=duplicate_survivor_rank)
        # Which of the fields deduplication signs on still differ -- the answer
        # to "what is holding these two apart", asked of the module that would
        # do the collapsing.  On a group the merge produced this is a
        # hypothetical, and `stage` below is what says so: deduplication ran in
        # the transform, before these flows existed, and will not run over them.
        differing = fields_holding_apart(group)
        worst, where, comparable = factor_value_disagreement(group)
        minted_here = [uuid for uuid in uuids if uuid in minted]
        # Not "did a stage add to this group?" but "would the group be here
        # without what it added?".  Two flows the merge found colliding and
        # added a third to are the transform's group, still.
        stage = (
            STAGE_MERGE if len(group) - len(minted_here) < 2 else STAGE_TRANSFORM
        )
        counts[f"collision_group_of_{len(group)}"] += 1
        if len(set(factors.values())) > 1:
            # The case that cost #31 its factors: the flows do not carry the
            # same characterisation, so collapsing them loses one side.
            counts["collision_with_unequal_factors"] += 1
        if comparable and worst > FACTOR_TOLERANCE:
            # The other case: both sides characterise the same method and say
            # different things about it, so they may not be one flow at all.
            counts["collision_with_disagreeing_factor_values"] += 1
        if not any(factors.values()):
            # Nothing in the group holds a number, so the question is not which
            # flow answers for the substance -- none of them does.
            counts["collision_groups_without_factors"] += 1
        if minted_here:
            # Every count below reads `factors` rather than the flows, so what
            # "carries no characterisation" means here is whatever counting the
            # dict above does, and there is one answer to that per report.
            counts["collision_flows_minted_by_merge"] += len(minted_here)
            counts["collision_minted_flows_without_factors"] += sum(
                1 for uuid in minted_here if not factors[uuid]
            )
            if stage == STAGE_MERGE:
                counts["collision_groups_from_merge"] += 1
            else:
                counts["collision_groups_enlarged_by_merge"] += 1
            if len(minted_here) == len(group):
                # A group of minted flows and nothing else: no published flow
                # in it came from a list, so there is no side holding the
                # substance's factors for the others to be read against.
                counts["collision_groups_entirely_minted"] += 1
        items.append(
            ReviewQueueItem(
                queue_name=ReviewQueue.ELEMENTARY_FLOW_COLLISION,
                item_key=f"{object_id}|{context_iri}|{unit}",
                title=(
                    f"{len(group)} live flows share "
                    f"{labels.get(object_id, object_id)} in one context and unit"
                    + (f"; the merge minted {len(minted_here)}" if minted_here else "")
                ),
                severity=Severity.REVIEW if minted_here else Severity.INFO,
                flow_object_id=object_id,
                item_index=index,
                payload={
                    "flow_object_id": object_id,
                    "context_iri": context_iri,
                    "unit": unit,
                    "elementary_flow_ids": uuids,
                    "lcia_factor_counts": factors,
                    # Not "would survive": nothing here survives anything.  A
                    # `transform` group is one deduplication has already
                    # declined to collapse, and will decline again on every
                    # future run for as long as `differing_fields` is not
                    # empty; a `merge` group is one it has never seen and never
                    # will.  Either way the field says which flow would be kept
                    # *if* it ran and those differences went away -- the warning
                    # #31 needed, which is a conditional and now reads as one.
                    "deduplication_would_keep": str(
                        getattr(would_keep, "elementary_flow_id", "") or ""
                    ),
                    "differing_fields": differing,
                    "factor_value_disagreement": (
                        {"worst": worst, "comparable": comparable, **(where or {})}
                        if comparable
                        else None
                    ),
                    "stage": stage,
                    "minted_by_merge": minted_here,
                },
            )
        )

    logger.info("elementary_flow_collisions", **dict(counts))
    return counts, items
