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
where saying something rather than nothing is allowed.  Here, nothing -- with one
exception, which is not a judgement about the numbers either.

**One of the rows is another publisher's.**  GreenDelta's package ships some flows
twice, once under ecoinvent's uuid and once as its own row, and the two can reach
one consensus flow with different numbers because each carries the factor of a
*different* EF 3.1 flow.  The ecoinvent-uuid row restates ecoinvent's own
implementation, which mapped `Paraquat` to EF's paraquat dichloride and `MCPA` to
MCPA-sodium; GreenDelta's own row carries the factor of the flow the merge reaches.
The first number is already published, as ecoinvent's, so the manifest may name the
lists whose rows give way (`yields_in_a_collision`), and the implementation's own
row is published.  Only where its own rows agree among themselves; the finding is
written either way, naming the rows that gave way (#439).
"""

from __future__ import annotations

from collections.abc import Collection
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
    yielding: Collection[str] = (),
):
    """One factor for one (flow, category, place), or none and a finding.

    *ruling* is a `lcia.collision_rulings.CollisionRuling` about this flow and
    category, where a curator wrote one.  It is obeyed only where the rows that
    collide are exactly the rows it was made about, stating exactly the
    numbers it recorded; the finding is written either way, with the ruling on
    it where one applied (#196).

    *yielding* is the source rows that give way to the implementation's own
    where the two disagree: rows it states under another publisher's
    identifier (the module docstring's last case).

    *candidates* are `MatchedFactor` records, all naming the same flow, category
    and place; the return is `(kept, finding)` with at most one of each.
    """
    kept = _one_number(candidates)
    if kept is not None:
        return kept, None
    return _disagree(
        candidates,
        elementary_flow_uuid=elementary_flow_uuid,
        implemented_by=implemented_by,
        category=category,
        geography=geography,
        ruling=ruling,
        yielding=yielding,
    )


def _one_number(candidates: list):
    """The candidate to publish where every row states one number, or None."""
    first = candidates[0]
    if len(candidates) == 1:
        return first
    if len({candidate.factor.amount for candidate in candidates}) == 1:
        return first
    kept = first
    for candidate in candidates[1:]:
        if not _comparable(kept.factor.amount, candidate.factor.amount):
            return None
        if more_precise_value(kept.factor.amount, candidate.factor.amount) == (
            candidate.factor.amount
        ):
            kept = candidate
    return kept


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
    yielding: Collection[str] = (),
):
    """Rows too far apart to be one number: nothing, unless a curator ruled or
    the rows apart are another publisher's.

    A ruling names the row whose number is taken, and is obeyed only where the
    colliding rows and their numbers are the ones it was made about -- a third
    row arriving, or a number moving, is a new question rather than an old
    answer obeyed.  Failing a ruling, the rows in *yielding* give way where the
    rest state one number between them.  The finding is written either way, so
    a reader of the findings sees the collision and its answer in one place.
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
    own = [candidate for candidate in candidates if _source_of(candidate) not in yielding]
    if own and len(own) < len(candidates):
        chosen = _one_number(own)
        if chosen is not None:
            return chosen, _collision(
                candidates,
                elementary_flow_uuid=elementary_flow_uuid,
                implemented_by=implemented_by,
                category=category,
                geography=geography,
                yielded=[
                    _source_of(candidate)
                    for candidate in candidates
                    if _source_of(candidate) in yielding
                ],
                published=_source_of(chosen),
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
    yielded: list[str] | None = None,
    published: str | None = None,
) -> Finding:
    """The row that says which two rows disagreed, and by how much -- and,
    where a curator ruled or another publisher's rows gave way, whose number
    was published."""
    amounts = sorted(abs(candidate.factor.amount) for candidate in candidates)
    ratio = amounts[-1] / amounts[0] if amounts[0] else None
    if ruled is not None:
        outcome = f" -- ruled: {ruled.publish_source_flow_uuid} is published"
    elif yielded:
        outcome = (
            f" -- {', '.join(yielded)} restates another publisher's row and gives "
            f"way: {published} is published"
        )
    else:
        outcome = ", so neither is published"
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
            **(
                {"yielded": {"published": published, "gave_way": yielded}}
                if yielded
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
