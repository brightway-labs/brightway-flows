"""Two scores for one unit process, and what the gap between them is made of.

The inventory is the same on both sides by construction -- the artifact carries
it, and this re-scores it -- so a difference in score for one (unit process,
category) is entirely a difference in what happened to each flow on its way
from the vendor's factor to ours.  There are six things that can happen, and
:class:`ContributionReason` is the closed list of them:

* ``agree`` -- the flow mapped, both sides have a factor, and the two
  contributions agree within tolerance;
* ``factor-differs`` -- both sides have a factor and they do not agree;
* ``no-consensus-factor`` -- the flow mapped, the vendor has a factor, we do
  not: the flow reached a consensus flow this list does not characterise
  under this category;
* ``unmapped-flow`` -- the vendor's flow reached no consensus flow at all;
* ``unit-crossing-unconverted`` -- the flow mapped onto a flow in another
  unit and the merge recorded no conversion, so nothing of ours applies;
* ``only-consensus-factor`` -- we have a factor and the vendor does not.

One of these tables was first written by
hand for one activity: hard coal, crude oil, natural gas and brown coal as
``factor-differs`` (every fossil factor imported as 1.0), uranium and peat as
``no-consensus-factor``.  This produces it for every unit process of the
sample, and then ranks the flows by how much of a category's total score they
move, which is the order to fix them in.

**The multiplier goes on the amount.**  The inventory is in the vendor's unit
and our factor is per our unit; the merge recorded, per source flow, how many
of our units one of the vendor's is (`UnitCrossing.multiplier`, #260), so our
contribution is ``amount × multiplier × our_factor``.  `UnitCrossing.convert`
goes the other way -- it turns a factor per source unit into one per ours --
and is not what this needs.

Pure functions over records.  Nothing here opens the database: the caller
hands in the merge targets and our factors, which is what makes the fixture
tests possible without a build.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from brightway_flows.domain.lcia.crosswalk import ImpactCategoryDefinition
from brightway_flows.domain.lcia.records import Band
from brightway_flows.domain.lcia.unit_process_scores import (
    ArtifactCategory,
    ScoreArtifact,
    UnitProcess,
)
from brightway_flows.flow_layers.contested_cas import FACTOR_TOLERANCE
from brightway_flows.lcia.differences import band_for
from brightway_flows.lcia.matching import MergeTarget

#: A contribution smaller than this share of the pair's score, where the two
#: sides agree, is counted and not stored: 500 unit processes × 25 categories ×
#: ~2,000 inventory lines is 25 million rows of "the same small number on both
#: sides", and a reader asking what moved a score does not want them.
CONTRIBUTION_FLOOR = 1e-3


class ContributionReason(StrEnum):
    """What happened to one flow of one inventory under one category."""

    AGREE = "agree"
    FACTOR_DIFFERS = "factor-differs"
    NO_CONSENSUS_FACTOR = "no-consensus-factor"
    UNMAPPED_FLOW = "unmapped-flow"
    UNIT_CROSSING_UNCONVERTED = "unit-crossing-unconverted"
    ONLY_CONSENSUS_FACTOR = "only-consensus-factor"


@dataclass(frozen=True, slots=True)
class CategoryMatch:
    """One of the vendor's categories, and which of ours it is about.

    ``method``, ``slug`` and ``impact_category_id`` are ``None`` where the
    crosswalk has no row for the vendor's spelling -- EF 3.0's three ``metals``
    categories -- and such a category is reported, not scored.

    ``method`` is *our* method's slug rather than the release's ``method_family``,
    and it is here because the pair identifies the category: two methods can
    both publish an ``acidification`` and mean different units from different
    models (#349).
    """

    key: str
    method_family: str
    category: str
    indicator: str
    unit: str
    method: str | None
    slug: str | None
    impact_category_id: str | None


@dataclass(frozen=True, slots=True)
class Contribution:
    """One flow of one inventory under one category, on both sides."""

    activity_code: str
    category_key: str
    source_flow_uuid: str
    elementary_flow_uuid: str | None
    amount: float
    multiplier: float | None
    their_factor: float | None
    our_factor: float | None
    their_contribution: float
    our_contribution: float
    reason: ContributionReason

    @property
    def delta(self) -> float:
        return self.our_contribution - self.their_contribution


@dataclass(frozen=True, slots=True)
class ScoreComparison:
    """One unit process under one category, scored both ways."""

    activity_code: str
    category_key: str
    their_score: float
    our_score: float
    #: ``ours / theirs``, signed, or ``None`` where theirs is zero.  Beside the
    #: band because `band_for`'s ratio is unsigned and says nothing about
    #: which side is bigger.
    signed_ratio: float | None
    band: Band
    #: The share of |their score| carried by flows that reached no consensus
    #: flow.  A pair whose lines all failed to map has our score 0 and bands as
    #: `incomparable`, which is true and uninformative; this is the number
    #: that says why.
    unmapped_share: float


@dataclass(frozen=True, slots=True)
class UnitProcessSummary:
    activity_code: str
    inventory_lines: int
    mapped_lines: int
    unmapped_lines: int


@dataclass(frozen=True, slots=True)
class FlowPriority:
    """One vendor flow under one category, over every unit process it moved.

    ``share_of_category`` is Σ|Δ| over the category's Σ|their score|: how much
    of everything the vendor scored under this category this one flow moves.
    ``max_share`` is the worst single unit process.  ``reason`` is the reason
    most of its contributions carried.
    """

    category_key: str
    source_flow_uuid: str
    elementary_flow_uuid: str | None
    reason: ContributionReason
    datasets_affected: int
    abs_delta_sum: float
    share_of_category: float
    max_share: float


@dataclass
class ComparisonResult:
    categories: list[CategoryMatch]
    comparisons: list[ScoreComparison]
    contributions: list[Contribution]
    priorities: list[FlowPriority]
    unit_processes: list[UnitProcessSummary]
    stats: dict[str, Any] = field(default_factory=dict)


def match_categories(
    categories: list[ArtifactCategory],
    crosswalk: dict[tuple[str, str], ImpactCategoryDefinition],
    *,
    consensus_ids: dict[tuple[str, str], str],
) -> list[CategoryMatch]:
    """Which of our categories each of the vendor's is about.

    *crosswalk* is `domain.lcia.crosswalk.by_stated_method_category`, keyed
    on the vendor's ``(method, category)``; *consensus_ids* maps our
    ``(method slug, category slug)`` to the consensus implementation's category
    id, which is what the factor table is keyed on.

    The definition the crosswalk returns says which method it belongs to, and
    that is half the key: the vendor's ``EF v3.1|acidification`` is EF's
    category and not the Stepwise category of the same slug.
    """
    matched: list[CategoryMatch] = []
    for category in categories:
        definition = crosswalk.get((category.method_family, category.category))
        matched.append(
            CategoryMatch(
                key=category.key,
                method_family=category.method_family,
                category=category.category,
                indicator=category.indicator,
                unit=category.unit,
                method=definition.method if definition else None,
                slug=definition.slug if definition else None,
                impact_category_id=(
                    consensus_ids.get((definition.method, definition.slug))
                    if definition
                    else None
                ),
            )
        )
    return matched


def _agree(theirs: float, ours: float) -> bool:
    if theirs == ours:
        return True
    if theirs == 0 or ours == 0 or (theirs > 0) != (ours > 0):
        return False
    return abs(ours / theirs - 1) <= FACTOR_TOLERANCE


def contributions_for(
    process: UnitProcess,
    category: CategoryMatch,
    *,
    their_factors: dict[str, float],
    our_factors: dict[str, float],
    targets: dict[str, MergeTarget],
) -> list[Contribution]:
    """Every line of the inventory under one category, on both sides.

    *their_factors* is keyed by the vendor's flow uuid, *our_factors* by the
    consensus flow uuid, *targets* by the vendor's -- the join is here.  A line
    with nothing on either side is not a contribution and is not returned.
    """
    out: list[Contribution] = []
    for line in process.inventory:
        their_factor = their_factors.get(line.source_flow_uuid)
        theirs = line.amount * their_factor if their_factor is not None else 0.0
        target = targets.get(line.source_flow_uuid)
        our_factor: float | None = None
        multiplier: float | None = None
        ours = 0.0
        if target is None:
            reason = ContributionReason.UNMAPPED_FLOW
        elif not target.crossing.convertible:
            reason = ContributionReason.UNIT_CROSSING_UNCONVERTED
        else:
            multiplier = target.crossing.multiplier
            our_factor = our_factors.get(target.elementary_flow_uuid)
            if our_factor is not None:
                ours = line.amount * (multiplier or 1.0) * our_factor
            if their_factor is None and our_factor is None:
                continue
            if their_factor is None:
                reason = ContributionReason.ONLY_CONSENSUS_FACTOR
            elif our_factor is None:
                reason = ContributionReason.NO_CONSENSUS_FACTOR
            elif _agree(theirs, ours):
                reason = ContributionReason.AGREE
            else:
                reason = ContributionReason.FACTOR_DIFFERS
        if their_factor is None and our_factor is None:
            # Unmapped or unconverted, and the vendor had nothing to say either:
            # not a contribution to anything.
            continue
        out.append(
            Contribution(
                activity_code=process.activity_code,
                category_key=category.key,
                source_flow_uuid=line.source_flow_uuid,
                elementary_flow_uuid=target.elementary_flow_uuid if target else None,
                amount=line.amount,
                multiplier=multiplier,
                their_factor=their_factor,
                our_factor=our_factor,
                their_contribution=theirs,
                our_contribution=ours,
                reason=reason,
            )
        )
    return out


def _band(theirs: float, ours: float) -> tuple[Band, float | None]:
    band, _ = band_for([theirs, ours])
    ratio = ours / theirs if theirs != 0 else None
    return band, ratio


def _kept(contribution: Contribution, *, scale: float) -> bool:
    """Whether a contribution row is stored, or only counted."""
    if contribution.reason is not ContributionReason.AGREE:
        return True
    return abs(contribution.their_contribution) >= CONTRIBUTION_FLOOR * scale


def compare_release(
    artifact: ScoreArtifact,
    *,
    categories: list[CategoryMatch],
    targets: dict[str, MergeTarget],
    our_factors: dict[tuple[str, str], dict[str, float]],
) -> ComparisonResult:
    """Every unit process of the artifact under every matched category.

    *our_factors* is ``(method slug, category slug) -> {consensus flow uuid:
    amount}``, the consensus implementation's factors with no geography.  A
    category the crosswalk does not match is counted under
    ``their_categories_unmatched`` and produces no comparison; a category of
    ours no vendor category reaches is counted under ``our_categories_unmatched``
    -- which is every category of a method the release does not ship, so a
    second method is 19 of them rather than a defect.
    """
    their_by_category = artifact.factors_by_category()
    comparisons: list[ScoreComparison] = []
    kept: list[Contribution] = []
    dropped = 0
    reasons: Counter[str] = Counter()
    # Per (category, source flow): what the priorities are built from.
    by_flow: dict[tuple[str, str], list[Contribution]] = defaultdict(list)
    category_total: dict[str, float] = defaultdict(float)
    per_process_share: dict[tuple[str, str], list[float]] = defaultdict(list)

    matched = [c for c in categories if c.slug is not None and c.method is not None]
    for process in artifact.unit_processes:
        for category in matched:
            theirs_stated = process.scores[category.key]
            rows = contributions_for(
                process,
                category,
                their_factors=their_by_category.get(category.key, {}),
                our_factors=our_factors.get(
                    (category.method or "", category.slug or ""), {}
                ),
                targets=targets,
            )
            ours = sum(row.our_contribution for row in rows)
            unmapped = sum(
                abs(row.their_contribution)
                for row in rows
                if row.reason is ContributionReason.UNMAPPED_FLOW
            )
            their_abs = sum(abs(row.their_contribution) for row in rows)
            band, ratio = _band(theirs_stated, ours)
            comparisons.append(
                ScoreComparison(
                    activity_code=process.activity_code,
                    category_key=category.key,
                    their_score=theirs_stated,
                    our_score=ours,
                    signed_ratio=ratio,
                    band=band,
                    unmapped_share=unmapped / their_abs if their_abs else 0.0,
                )
            )
            category_total[category.key] += abs(theirs_stated)
            scale = max(abs(theirs_stated), abs(ours))
            for row in rows:
                reasons[str(row.reason)] += 1
                if _kept(row, scale=scale):
                    kept.append(row)
                else:
                    dropped += 1
                if row.delta != 0:
                    by_flow[(category.key, row.source_flow_uuid)].append(row)
                    if theirs_stated != 0:
                        per_process_share[(category.key, row.source_flow_uuid)].append(
                            abs(row.delta) / abs(theirs_stated)
                        )

    priorities: list[FlowPriority] = []
    for (category_key, source_uuid), rows in by_flow.items():
        total = category_total[category_key]
        abs_delta = sum(abs(row.delta) for row in rows)
        reason = Counter(row.reason for row in rows).most_common(1)[0][0]
        targets_seen = {row.elementary_flow_uuid for row in rows}
        priorities.append(
            FlowPriority(
                category_key=category_key,
                source_flow_uuid=source_uuid,
                elementary_flow_uuid=next(iter(targets_seen)) if len(targets_seen) == 1 else None,
                reason=reason,
                datasets_affected=len({row.activity_code for row in rows}),
                abs_delta_sum=abs_delta,
                share_of_category=abs_delta / total if total else math.inf,
                max_share=max(per_process_share.get((category_key, source_uuid), [0.0])),
            )
        )
    priorities.sort(key=lambda p: (-p.share_of_category, -p.abs_delta_sum, p.category_key, p.source_flow_uuid))

    summaries = [
        UnitProcessSummary(
            activity_code=process.activity_code,
            inventory_lines=len(process.inventory),
            mapped_lines=sum(1 for line in process.inventory if line.source_flow_uuid in targets),
            unmapped_lines=sum(1 for line in process.inventory if line.source_flow_uuid not in targets),
        )
        for process in artifact.unit_processes
    ]

    reached = {(c.method, c.slug) for c in matched}
    stats: dict[str, Any] = {
        "unit_processes": len(artifact.unit_processes),
        "their_categories": len(categories),
        "their_categories_unmatched": len(categories) - len(matched),
        "our_categories_unmatched": len(set(our_factors) - reached),
        "pairs_compared": len(comparisons),
        "contributions_stored": len(kept),
        "contributions_dropped_as_agreeing": dropped,
        "flow_priorities": len(priorities),
    }
    for band in Band:
        stats[f"pairs_{band}"] = sum(1 for c in comparisons if c.band is band)
    stats["pairs_within_2x"] = sum(
        1 for c in comparisons
        if c.band in (Band.IDENTICAL, Band.WITHIN_TOLERANCE, Band.UP_TO_2X)
    )
    for reason in ContributionReason:
        stats[f"contributions_{reason}"] = reasons.get(str(reason), 0)
    return ComparisonResult(
        categories=categories,
        comparisons=comparisons,
        contributions=kept,
        priorities=priorities,
        unit_processes=summaries,
        stats=stats,
    )
