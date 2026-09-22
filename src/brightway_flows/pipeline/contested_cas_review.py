"""The contested registry numbers no signal decides, as work for a curator.

`flow_layers.contested_cas` returns `UNDECIDED` for a number two names carry
where neither the source list's own characterisation factors nor Common
Chemistry says whether they are one substance, and no curator has ruled.  21 of
EF 3.1's groups land there.

Those keep today's behaviour -- they merge -- because splitting 307 published
flows on no evidence is the larger risk, and because that is precisely the
failure mode of the rule #34 originally proposed.  But a merge nothing supports
is not a merge anyone has checked, so it is asked about rather than assumed.

Ordered by characterisation factors at stake, which is the order the questions
matter in: `79-00-5` fusing `1,1,1-trichloroethane` with `1,1,2-trichloroethane`
carries 71, and `12447-40-4` fusing `borate` with `borax` carries none.
"""

from __future__ import annotations

from collections.abc import Mapping

from brightway_flows.flow_layers.contested_cas import ContestedCas, Verdict
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)


def contested_cas_items(
    verdicts: Mapping[str, ContestedCas],
    *,
    flow_counts: Mapping[str, int] | None = None,
) -> list[ReviewQueueItem]:
    """One item per contested number awaiting a ruling.

    `flow_counts` maps a registry number to the elementary flows carrying it,
    so the queue can be read in the order the answers matter.  Optional: the
    count is context for a curator, not part of the question.
    """
    flow_counts = flow_counts or {}
    undecided = [v for v in verdicts.values() if v.verdict is Verdict.UNDECIDED]
    undecided.sort(key=lambda v: (-flow_counts.get(v.cas, 0), v.cas))

    items: list[ReviewQueueItem] = []
    for index, verdict in enumerate(undecided):
        items.append(ReviewQueueItem(
            queue_name=ReviewQueue.CONTESTED_CAS,
            item_key=verdict.cas,
            title=f"{verdict.cas}: {', '.join(verdict.names)}",
            # A question, not a defect: the merge may well be right, and nothing
            # here has found otherwise -- only that nothing has found it right.
            severity=Severity.INFO,
            cas=verdict.cas,
            item_index=index,
            payload={
                "cas": verdict.cas,
                "names": list(verdict.names),
                "name_count": len(verdict.names),
                "flow_count": flow_counts.get(verdict.cas, 0),
                # Both are reported because they say different things.  Nothing
                # comparable means the two names never publish a factor for the
                # same method and context, so the source list has not been asked;
                # a divergence below the tolerance means it was asked and agreed.
                "comparable_factors": verdict.evidence.get("comparable", 0),
                "factor_divergence": round(verdict.evidence.get("divergence", 0.0), 4),
            },
        ))
    return items
