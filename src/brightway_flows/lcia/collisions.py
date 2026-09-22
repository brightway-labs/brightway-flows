"""Two source rows, one consensus flow, one category: what to publish.

130 consensus flows are reached by more than one ecoinvent 3.12 row, and 277
(flow, category) groups hold more than one factor because of it.  The model holds
one factor per (flow, geography, category), so something is forced -- and what is
forced is *not* a judgement about which number is right.

Three cases, and only the third is an event:

**They agree.**  Nothing to decide, nothing to say.  Most of the 277 are this.

**They are one number written twice.**  `0.000118` and `0.00011755` differ by less
than `FACTOR_TOLERANCE`, and `more_precise_value` -- the same judgement
`pipeline.deduplication` makes about two rows that turned out to be one flow --
keeps the one written to more digits.

**They disagree beyond it.**  34 groups, over 13 flows.  No factor is published and
the rows are reported, because there is no faithful answer: a 7,068× gap between
`Glufosinate` and `Glufosinate ammonium` on one flow is not a number to choose
between, it is evidence that our merge has put two substances on one flow. That is
a claim about the matching, and the fix belongs there.

The consensus implementation (§4.3) is where a curator may rule on the same 34, and
where saying something rather than nothing is allowed.  Here, nothing.
"""

from __future__ import annotations

from typing import Any

from brightway_flows.flow_layers.contested_cas import (
    FACTOR_TOLERANCE,
    more_precise_value,
)
from brightway_flows.lcia.report import Finding, FindingKind


def _comparable(left: float, right: float) -> bool:
    """Whether two numbers are close enough to be one number written twice.

    Not defined across zero or across a sign change -- a relative difference is
    not -- and those are reported rather than silently kept, for the reason
    `deduplication._relative_difference` gives: a stated zero against a number is
    not a rounding of anything.
    """
    if left == 0 or right == 0 or (left > 0) != (right > 0):
        return False
    low, high = sorted((abs(left), abs(right)))
    return high / low - 1 <= FACTOR_TOLERANCE


def settle(
    candidates: list,
    *,
    elementary_flow_uuid: str,
    implemented_by: str,
    category: str,
    geography: str | None,
    ruling: Any | None = None,
):
    """One factor for one (flow, category, place), or none and a finding.

    *ruling* is a `lcia.collision_rulings.CollisionRuling` about this flow and
    category, where a curator wrote one.  It is obeyed only where the rows that
    collide are exactly the rows it was made about, stating exactly the
    numbers it recorded; the finding is written either way, with the ruling on
    it where one applied (#196).

    *candidates* are `MatchedFactor` records, all naming the same flow, category
    and place; the return is `(kept, finding)` with at most one of each.
    """
    first = candidates[0]
    if len(candidates) == 1:
        return first, None
    if len({candidate.factor.amount for candidate in candidates}) == 1:
        return first, None

    kept = first
    for candidate in candidates[1:]:
        if not _comparable(kept.factor.amount, candidate.factor.amount):
            return _disagree(
                candidates,
                elementary_flow_uuid=elementary_flow_uuid,
                implemented_by=implemented_by,
                category=category,
                geography=geography,
                ruling=ruling,
            )
        if more_precise_value(kept.factor.amount, candidate.factor.amount) == (
            candidate.factor.amount
        ):
            kept = candidate
    return kept, None


def _source_of(candidate) -> str:
    return str(candidate.source_flow_uuid or candidate.elementary_flow_uuid)


def _disagree(
    candidates: list,
    *,
    elementary_flow_uuid: str,
    implemented_by: str,
    category: str,
    geography: str | None,
    ruling: Any | None,
):
    """Rows too far apart to be one number: nothing, unless a curator ruled.

    A ruling names the row whose number is taken, and is obeyed only where the
    colliding rows and their numbers are the ones it was made about -- a third
    row arriving, or a number moving, is a new question rather than an old
    answer obeyed.  The finding is written either way, so a reader of the
    findings sees the collision and its answer in one place.
    """
    stated = {_source_of(candidate): candidate.factor.amount for candidate in candidates}
    if ruling is not None and ruling.covers(stated=stated):
        chosen = next(
            candidate
            for candidate in candidates
            if _source_of(candidate) == ruling.publish_source_flow_uuid
        )
        return chosen, _collision(
            candidates,
            elementary_flow_uuid=elementary_flow_uuid,
            implemented_by=implemented_by,
            category=category,
            geography=geography,
            ruled=ruling,
        )
    return None, _collision(
        candidates,
        elementary_flow_uuid=elementary_flow_uuid,
        implemented_by=implemented_by,
        category=category,
        geography=geography,
    )


def _collision(
    candidates: list,
    *,
    elementary_flow_uuid: str,
    implemented_by: str,
    category: str,
    geography: str | None,
    ruled: Any | None = None,
) -> Finding:
    """The row that says which two rows disagreed, and by how much -- and,
    where a curator ruled, whose number was published."""
    amounts = sorted(abs(candidate.factor.amount) for candidate in candidates)
    ratio = amounts[-1] / amounts[0] if amounts[0] else None
    outcome = (
        ", so neither is published"
        if ruled is None
        else f" -- ruled: {ruled.publish_source_flow_uuid} is published"
    )
    return Finding(
        kind=FindingKind.FACTOR_COLLISION,
        implemented_by=implemented_by,
        elementary_flow_uuid=elementary_flow_uuid,
        impact_category_id=None,
        detail=(
            f"{category}: "
            + ", ".join(
                f"{candidate.source_flow_uuid or candidate.elementary_flow_uuid} "
                f"states {candidate.factor.amount!r}"
                for candidate in candidates
            )
            + (f" -- {ratio:,.0f}x apart" if ratio and ratio >= 2 else "")
            + outcome
        ),
        context={
            "category": category,
            "geography": geography,
            "ratio": ratio,
            **(
                {
                    "ruled": {
                        "published": ruled.publish_source_flow_uuid,
                        "comment": ruled.comment,
                    }
                }
                if ruled is not None
                else {}
            ),
            "rows": [
                {
                    "source_flow_uuid": candidate.source_flow_uuid,
                    "amount": candidate.factor.amount,
                }
                for candidate in candidates
            ],
        },
    )
