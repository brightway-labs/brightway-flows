"""The collision check, asked again of the list the merge hands the database.

`pipeline/collisions.py` holds the check: two live flows sharing a substance, a
context and a unit are two flows the pipeline is one field away from collapsing,
and which one keeps its identity is then a lexicographic sort's decision (#31).
It was called once, from the transform, immediately after the duplicate
deprecations -- and the merge, which runs afterwards and *adds flows*, never
called it at all.

So on the 2026-08-12 build the queue reported 116 groups and the published
database held 145.  The 29 missing ones were all in what the merge added: 190
flows minted onto a substance, context and unit a flow already occupied, under
the same name, every one of them carrying no characterisation factors, and 12
of the groups holding no base-list flow at all -- nothing in them with a number
on it.  All four substances are the pesticide classes, where a curated grouping
says "this ecoinvent herbicide belongs with the herbicide class" and the merge
answers it in one of two ways: a prepared correspondence attaches a *source
reference* to the flow that is already there, and a manual addition *mints a
flow* on the same object and context.  Which one a row gets depends on whether
it appears in the prepared table.

Whether minting is right is a curator's question, and this does not answer it.
What it does is put it (#60): the report runs over the flows the merge is about
to write, so the queue and the counters describe the database rather than the
transform's half of it.

**Nothing downstream of here reads these groups.**  Deduplication runs in the
transform, and so does `apply_collision_rulings`, so the flows a merge mints are
inspected by neither -- not in this build, and not in the next one either, whose
transform starts from the base list again.  A group the merge produced is
therefore not a collapse waiting to happen, which is what a transform-side
collision is; it is a published duplication that will stay published, and a
ruling in `elementary-flow-collision-decisions.json` written against one is
counted `collision_rulings_absent` and applied to nothing.  What answers it is
the grouping: a row in the prepared correspondence table attaches to the flow
that is already there, where a manual addition mints a second one beside it.

*Minted* is read from the flow's `source`.  The accumulator's `added_flow_ids`
is the wrong set here -- it names what *this pass* added, and a build merges
several lists in sequence, each loading the flows the last one wrote -- while
`source` names the list a flow was published by, so everything that is not the
base list's is a flow some merge pass minted.  That is what makes the last
pass's report the whole picture: it sees every earlier pass's flows too, which
is why writing it replaces the queue rather than adding to it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.lcia.records import StatedFactor
from brightway_flows.merge.state import MergeAccumulator
from brightway_flows.pipeline.collisions import report_collisions
from brightway_flows.pipeline.review_records import ReviewQueueItem
from brightway_flows.sources import base_source_label

#: The stage the counts are filed under in `run_stats`.  Distinct from the
#: transform's `elementary_flow_collisions`, so the two sit side by side and a
#: reader can see which of them the groups came from -- the whole of what was
#: missing while only one of them was counted.
MERGE_COLLISION_STAGE = "merge_elementary_flow_collisions"

#: Read off a merged row by nothing, so that "what is holding these two apart"
#: means here what it means in the transform.
#:
#: `fields_holding_apart` compares the fields deduplication's signature reads,
#: and the transform attaches concept associations *after* it has both
#: deduplicated and reported -- so no pass that could collapse a pair has ever
#: seen one.  By the time the merge reports, every flow carries its own, and
#: including them names a field as holding all 145 groups apart when it holds
#: none of them apart: the 116 the transform describes are held apart by a
#: general comment 114 times and by a CAS source twice (#58), and this is what
#: keeps the merge's answer for those groups the same answer.
#:
#: Scoped here rather than added to `SIGNATURE_EXCLUDED_KEYS`, which governs
#: which flows get deprecated: the exclusion would be a no-op there today, and a
#: no-op that changes what a deprecation pass signs on is not worth being right
#: about in passing.
ATTACHED_AFTER_DEDUPLICATION = frozenset({"concept_associations"})


@dataclass(frozen=True)
class MergedFlow:
    """One merged flow, as the fields the collision report reads.

    A narrowing of `ElementaryFlow`, not a second reading of a payload.  It was
    the second reading until #93 made the working list records: the accumulator
    held rows the merge had assembled beside rows an older build had written,
    and a record whose required fields grow refuses those -- `unit_iri` alone
    raised on a seeded fixture -- so the six fields the report needs were taken
    by name and the rest defaulted.  `_load_working_set` is where a stored row
    becomes a record now, which is where a stored row that cannot be one should
    stop the run.

    `to_dict` returns the whole record, because one of the report's readers
    wants that rather than a field of it: `fields_holding_apart` asks which of
    the fields deduplication signs on still differ, and it answers `[]` for a
    row that cannot produce one (#58).  A class that named six fields and
    stopped would therefore have reported every group in the published database
    as held apart by nothing -- including the 116 the transform describes
    correctly -- and empty is a legal answer, so nothing would have said so.
    What it hands over is `ElementaryFlow.to_dict()`, which is what
    `signed_on_fields` expects, less `ATTACHED_AFTER_DEDUPLICATION` -- the one
    difference between what the merge holds and what the transform reported on.
    """

    elementary_flow_id: str
    flow_object_id: str
    context_iri: str
    unit: str
    source: str
    lcia_methods: list[StatedFactor] = field(default_factory=list)
    owl_deprecated: bool | None = None
    #: The record this was read from, serialised by `to_dict` and read by
    #: nothing else here.
    record: ElementaryFlow | None = field(default=None, repr=False)

    @classmethod
    def from_record(cls, record: ElementaryFlow) -> MergedFlow:
        """Read one working-list row."""
        return cls(
            elementary_flow_id=record.elementary_flow_id,
            flow_object_id=record.flow_object_id,
            context_iri=record.context_iri,
            unit=record.unit or "",
            source=record.source,
            lcia_methods=(
                record.lcia_methods if isinstance(record.lcia_methods, list) else []
            ),
            owl_deprecated=record.owl_deprecated,
            record=record,
        )

    def to_dict(self) -> dict[str, Any]:
        """The row as the record it is, for the reader that signs on all of it."""
        if self.record is None:
            return {}
        return {
            key: value
            for key, value in self.record.to_dict().items()
            if key not in ATTACHED_AFTER_DEDUPLICATION
        }


def minted_flow_ids(elementary_flows: list[MergedFlow]) -> frozenset[str]:
    """The flows in *elementary_flows* that a merge minted rather than read.

    Every published flow carries the label of the list that published it, and a
    match leaves that label alone -- a matched source row becomes a source
    reference on the flow it landed on, not a flow.  So a flow whose source is
    not the base list's is one an addition or a creation minted, in this pass or
    an earlier one.
    """
    base = base_source_label()
    return frozenset(
        flow.elementary_flow_id
        for flow in elementary_flows
        if flow.elementary_flow_id and flow.source != base
    )


def report_merged_collisions(
    *, accumulator: MergeAccumulator, labels_by_object: dict[str, str]
) -> tuple[Counter, list[ReviewQueueItem]]:
    """Count the collisions in the merged list and raise one item per group.

    The accumulator holds `ElementaryFlow` records; the check reads the six
    fields :class:`MergedFlow` names, so that narrowing happens here -- one
    place, and cheap: 94,409 rows in about a tenth of a second.

    *labels_by_object* is `MergeIndexes.flow_object_label_by_id`, passed rather
    than the indexes themselves: this reads one lookup off them, and taking the
    lookup is what lets the report be exercised without building the twelve
    other indexes matching needs.
    """
    flows = [
        MergedFlow.from_record(flow) for flow in accumulator.merged_elementary
    ]
    return report_collisions(
        flows,
        labels_by_object=labels_by_object,
        minted_flow_ids=minted_flow_ids(flows),
    )
