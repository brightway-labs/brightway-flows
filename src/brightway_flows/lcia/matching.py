"""Getting a factor onto a consensus flow.

Two joins, and everything a factor can run into on the way.

**Identity, for the JRC.**  A consensus flow of the base list is an EF flow under
the same UUID, so the factors read off the published flows are already where they
belong -- unless the build has since deprecated the flow they were read off, and
then they belong on the flow that replaced it.  166 identifiers were in that
position on the 2026-08-25 build, carrying 1,674 factors that the export's own
`redirects` array retires: two halves of one build disagreeing about which flows
exist (#163).  So the identity join is one hop after all, and the hop is the
redirect the export publishes rather than a second opinion about it.

**Only the redirects a consumer is told to follow.**  `identity-merge` is the
same flow reached twice, and a factor about one copy is a factor about the flow.
`context-collapse` is not: two source contexts the consensus vocabulary cannot
tell apart, whose factors legitimately disagree (#1, #36), and moving a number
across one would invent the coarsening #84 removed.  Those factors are reported
and not republished -- all 80 of them restate the survivor's own number today, so
refusing them loses nothing and would keep losing nothing if the numbers parted.

**The flow's own number wins.**  Where a redirected factor and the survivor's own
describe one (flow, category, place), the survivor's stands: `deduplication.
settle_factor_values` already settled that pair when it collapsed the two flows,
kept the more precise number and wrote the other onto it as a `superseded_value`
(#63, #283) -- so the redirected copy is a restatement of a question already
answered, not a second opinion, and re-opening it here would withdraw 132 factors
the build has decided.  What the survivor states *nothing* about is the other
case: 72 factors on the same build, published on the survivor and carrying the
retired identifier as their `source_flow_uuid` so a reader can see where the
number came from.

**Two hops, for ecoinvent.**  The workbook's triple resolved to an ecoinvent flow
UUID at fetch (§2.3's first hop); this is the second, that UUID through
`elementary_flow_sources` to the consensus flow the merge put it on.  Measured
against a full build: 9,848 of ecoinvent 3.12's 9,850 flows carry a reference, no
source flow reaches two consensus flows, and the references reach 9,407 distinct
consensus flows.

**Several hops, for GreenDelta.**  Their openLCA package names flows by the
ecoinvent UUID it was built against, so it takes the same second hop -- but
through whichever list has the UUID, in the order the manifest declares
(`chained_merge_targets`).  The package is not built against any one release,
and the flows it reaches are spread over two.

The second hop carries two more things the first cannot know, both recorded by the
merge on the same row: what the source flow was measured in, and the conversion
factor its correspondence table stated. A factor is per unit of a flow, and eight
of the flows that carry factors are published in a unit their source list did not
use -- so the join is not "which flow", it is "which flow, and in what".

Five things can then happen to a factor, and each is a row in `lcia_findings`
rather than a silent drop:

* its flow reaches no consensus flow (2 of ecoinvent's, carrying 8 factors);
* its units cross and no conversion is stated (none today, and the guard is what
  keeps that true);
* two rows reach one flow and disagree beyond tolerance (34 groups, §4.2);
* it was read off a retired identifier whose redirect must be refused (15
  identifiers, 80 factors);
* it was carried onto a survivor that states nothing for it (16 identifiers, 72
  factors).
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.lcia.records import StatedFactor
from brightway_flows.domain.vocabulary import QUDT_CONVERSION_MULTIPLIER_CURIE
from brightway_flows.lcia.collisions import settle
from brightway_flows.domain.units import canonical_unit
from brightway_flows.lcia.conversion import UnitCrossing
from brightway_flows.lcia.report import Finding, FindingKind
from brightway_flows.lcia.sources import FactorSource
from brightway_flows.pipeline.redirects import (
    IDENTITY_MERGE,
    classify_replacements,
)
from brightway_flows.pipeline.sqlite import read_source_contexts

logger = structlog.get_logger(__name__)

#: Where the merge records a conversion factor on a source reference (#260).
#: The registry's CURIE rather than the string, so a term is renamed in one place
#: (#233).
CONVERSION_MULTIPLIER_KEY = QUDT_CONVERSION_MULTIPLIER_CURIE


@dataclass(frozen=True, slots=True)
class MergeTarget:
    """Where one source flow was merged to, and what the two sides measure."""

    elementary_flow_uuid: str
    crossing: UnitCrossing


@dataclass(frozen=True, slots=True)
class RetiredFlow:
    """An identifier this build publishes as a redirect, and what it resolves to.

    *reason* is the export's own word for the deprecation, so the two artifacts
    cannot disagree about what a redirect means; *replaced_by* is the terminal
    survivor, or ``""`` where the chain ends on a flow this build does not
    publish.
    """

    replaced_by: str
    reason: str

    @property
    def followable(self) -> bool:
        """Whether a factor about this identifier is a factor about the survivor.

        Only for an `identity-merge`, and only where the chain lands somewhere:
        see the module docstring on why a `context-collapse` is refused.
        """
        return bool(self.replaced_by) and self.reason == IDENTITY_MERGE


@dataclass(frozen=True, slots=True)
class MatchedFactor:
    """One factor, on the consensus flow it characterises, in our unit."""

    elementary_flow_uuid: str
    factor: StatedFactor
    #: The flow the publisher named, where that is not the consensus flow.  Kept
    #: because a reader asking why a number is on a flow needs the row it came
    #: from, and because §4.2's collisions are named by it.
    source_flow_uuid: str | None = None
    #: What the amount was before the unit crossing, where there was one.
    stated_amount: float | None = None
    #: How this list arrived at the number, for the implementation that is ours.
    #: ``None`` on a transcription, which arrives at nothing: it says what its
    #: publisher said.  See `lcia.consensus.Derivation`.
    derivation: str | None = None
    #: What the other implementation stated, where the two agree and only one
    #: number can be published.
    also_stated: float | None = None


def merge_targets(
    db_path: Path,
    *,
    list_name: str,
    list_version: str,
    only: set[str] | None = None,
) -> dict[str, MergeTarget]:
    """Each source flow of one list, and the consensus flow it was merged onto.

    One target, not a set: measured over the build, no ecoinvent 3.12 source flow
    reaches two consensus flows, so a mapping is what the data is. A second target
    would mean the same published number on two flows, and this raises rather than
    picking one.

    *only* narrows both the mapping and that check to the flows an implementation
    actually states a factor for.  EF 3.1 needs it: 47 of its 93,993 source flows
    reach two consensus flows, because a deprecated flow's reference is carried
    onto the survivor that replaced it while the original row keeps its own --
    right, and none of anybody's business until a factor is on one of them.  The
    invariant is unchanged where it bites; it is asked about the flows in hand.
    """
    index: dict[str, MergeTarget] = {}
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT efs.source_flow_uuid, efs.elementary_flow_uuid, "
            "efs.source_metadata_json, ef.unit "
            "FROM elementary_flow_sources efs "
            "LEFT JOIN elementary_flows ef ON ef.uuid = efs.elementary_flow_uuid "
            "WHERE efs.list_name = ? AND efs.list_version = ?",
            (list_name, list_version),
        )
        for source_uuid, elementary_uuid, metadata, target_unit in rows:
            source_uuid = str(source_uuid)
            if only is not None and source_uuid not in only:
                continue
            claimed = index.get(source_uuid)
            if claimed is not None and claimed.elementary_flow_uuid != elementary_uuid:
                raise ValueError(
                    f"{list_name}-{list_version} flow {source_uuid} is merged onto "
                    f"both {claimed.elementary_flow_uuid} and {elementary_uuid}, so "
                    "a factor about it would be published on two flows."
                )
            payload = orjson.loads(metadata or "{}")
            multiplier = payload.get(CONVERSION_MULTIPLIER_KEY)
            index[source_uuid] = MergeTarget(
                elementary_flow_uuid=str(elementary_uuid),
                crossing=UnitCrossing(
                    source_unit=str(payload.get("unit") or ""),
                    target_unit=str(target_unit or ""),
                    multiplier=(
                        float(multiplier)
                        if isinstance(multiplier, (int, float))
                        else None
                    ),
                ),
            )
    finally:
        connection.close()
    return index


def retired_flows(db_path: Path) -> dict[str, RetiredFlow]:
    """Every identifier this build deprecated, and where its redirect leads.

    The other half of `merge_targets`: that one says where a source list's flow
    was merged to, this one says where a flow *of ours* went when the build
    collapsed it into another.  Both answer the same question for a factor --
    which published flow is this number about -- and neither decides it here.

    The reason is classified exactly as the export classifies it, by handing
    `pipeline.redirects` the same two inputs `build_simple_export` gives it: the
    replacement each deprecated payload names, and each flow's source contexts
    per source list.  Reading the contexts costs about half a second over the
    110,993 rows of `elementary_flow_sources`, which is what it is worth to have
    one answer rather than two.

    A deprecated flow whose replacement is missing is left out entirely: there
    is nothing for the redirect to resolve to, and a caller looking one up gets
    the same answer it would for a flow that was never deprecated.  Today the
    build has none.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        replaced_by: dict[str, str] = {}
        published: set[str] = set()
        for uuid, deprecated, replacement in connection.execute(
            "SELECT uuid, is_deprecated, replaced_by_uuid FROM elementary_flows"
        ):
            if not deprecated:
                published.add(str(uuid))
            elif replacement:
                replaced_by[str(uuid)] = str(replacement)
    finally:
        connection.close()
    classified = classify_replacements(
        replaced_by, read_source_contexts(db_path), published=published
    )
    out = {
        identifier: RetiredFlow(replaced_by=target, reason=reason)
        for identifier, (target, reason) in classified.items()
    }
    logger.info(
        "read_retired_flows",
        retired=len(out),
        followable=sum(1 for row in out.values() if row.followable),
    )
    return out



def recorded_conversions(db_path: Path) -> dict[tuple[str, str, str], float]:
    """Every conversion this build recorded, by the flow and the units it joins.

    ``(consensus flow, source unit, target unit)`` to the multiplier, read off
    the source references the merge wrote (#260).  It is the same number
    `merge_targets` hands to a row that arrives with its own identifier; this is
    how a row that arrives with only a name or a curated decision can find it.

    **A conversion is a statement about a pair, and the pair is what is keyed.**
    One kilogram of *this water* is 0.001 cubic metres *of this flow* -- so a
    multiplier is reused only where the flow is the same flow and both units are
    the same units, which is `merge.conversions.UnitConversion.holds_between`'s
    rule read from the other end.  A kilogram of standing wood is 0.00204 cubic
    metres and a kilogram of water is 0.001, and nothing here can mix them up
    because neither flow is the other.

    **A pair two rows disagree about is left out.**  Natural gas carries both
    34.5 and 36.0 megajoules per cubic metre, from two lists that measured
    different gas, and picking one would invent an answer where the evidence is
    that there is more than one.  Those rows keep the crossing they had, which
    is reported and publishes nothing (#170).

    Units are canonicalised on both sides, because a source list writes ``m2*a``
    where the flow says ``m2.a`` and a pair that differed only in spelling would
    look like a conversion nobody recorded.
    """
    seen: dict[tuple[str, str, str], set[float]] = defaultdict(set)
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT efs.elementary_flow_uuid, efs.source_metadata_json, ef.unit "
            "FROM elementary_flow_sources efs "
            "JOIN elementary_flows ef ON ef.uuid = efs.elementary_flow_uuid"
        )
        for elementary_uuid, metadata, target_unit in rows:
            payload = orjson.loads(metadata or "{}")
            multiplier = payload.get(CONVERSION_MULTIPLIER_KEY)
            if not isinstance(multiplier, (int, float)) or not multiplier:
                continue
            source_unit = canonical_unit(str(payload.get("unit") or ""))
            published_unit = canonical_unit(str(target_unit or ""))
            if not source_unit or not published_unit:
                continue
            key = (str(elementary_uuid), source_unit, published_unit)
            seen[key].add(float(multiplier))
    finally:
        connection.close()
    out = {key: next(iter(values)) for key, values in seen.items() if len(values) == 1}
    logger.info(
        "read_recorded_conversions",
        conversions=len(out),
        disagreeing=sum(1 for values in seen.values() if len(values) > 1),
    )
    return out


def chained_merge_targets(
    db_path: Path,
    *,
    lists: Sequence[tuple[str, str]],
    only: set[str],
) -> tuple[dict[str, MergeTarget], dict[str, str]]:
    """Resolve one set of source flows through several lists, first hit winning.

    For an implementation whose flows are somebody *else's*.  GreenDelta's
    openLCA package ships no flow list of its own: it identifies a flow by the
    ecoinvent UUID it was built against, declaring compatibility with ecoinvent
    3.6 through 3.11, and a handful of its rows carry EF 3.1 UUIDs instead.  So
    the manifest names the lists to try and this walks them in that order.

    **Order is a judgement and it is the manifest's.**  Newest release first,
    because a UUID ecoinvent has reused means a different substance in a later
    release than in an earlier one, and the release closest to what this list
    publishes is the reading to prefer.  Measured over the build of 2026-08-28:
    1,143 of GreenDelta's flows resolve identically through 3.12 and 3.8, one
    resolves differently -- Flupyrsulfuron-methyl, 4 factors, where 3.12 wins --
    and 50 resolve only through 3.8, all of them substances 3.12 no longer
    ships (aircraft cruise-height emissions, ore-grade copper and gold).

    Returns the index and, beside it, which list each flow was resolved through,
    so a run can report its own reach rather than a reader having to infer it.
    """
    index: dict[str, MergeTarget] = {}
    via: dict[str, str] = {}
    for list_name, list_version in lists:
        outstanding = only - index.keys()
        if not outstanding:
            break
        for source_uuid, target in merge_targets(
            db_path,
            list_name=list_name,
            list_version=list_version,
            only=outstanding,
        ).items():
            index[source_uuid] = target
            via[source_uuid] = f"{list_name}-{list_version}"
    return index, via


def _factor_key(factor: StatedFactor) -> tuple[str, str]:
    """What makes two factors the same factor, once the flow is fixed.

    The category and the place.  The category is the publisher's own identifier
    where it has one -- EF's method UUID -- and its name where it does not, which
    is ecoinvent's case for a category exactly as it is for a flow.  The place is
    what EF states on 42,871 of its rows and nothing else states at all.
    """
    for value in (factor.category.uuid, factor.category.name):
        if isinstance(value, str) and value.strip():
            return value.strip(), factor.geography or ""
    return "", factor.geography or ""


def _unreached(
    source: FactorSource,
    flow_uuid: str,
    factors: list,
    declined_because: str = "",
) -> Finding:
    """A source row with factors and no flow to put them on.

    Named rather than numbered: the row this reports is one nobody can look up,
    because it is the row that did *not* become a consensus flow -- so if this
    finding does not carry what the publisher calls it, no page can. The factors
    travel with it for the same reason: "4 factors" is a count, and
    `ecotoxicity: freshwater, 0.0050755` is the thing a reader can weigh.

    *declined_because* is the reasoning where a curator looked at this row and
    ruled that no flow is the right place for its numbers
    (`lcia.substance_decisions`). It rides on this finding rather than getting one
    of its own: the row reached nothing, which is one thing that happened, and
    a second finding would say it was two.
    """
    described = source.descriptions.get(flow_uuid, {})
    name = described.get("name") or ""
    return Finding(
        kind=FindingKind.FLOW_NOT_REACHED,
        implemented_by=source.implementation.name,
        elementary_flow_uuid=None,
        impact_category_id=None,
        detail=(
            f"{name or flow_uuid} carries {len(factors)} factors and is merged "
            "onto no consensus flow, so none of them can be published"
            + (", which was decided rather than missed" if declined_because else "")
        ),
        context={
            **({"declined_because": declined_because} if declined_because else {}),
            "source_flow_uuid": flow_uuid,
            "name": name,
            "context": described.get("context") or "",
            "unit": described.get("unit") or "",
            "factor_count": len(factors),
            "categories": sorted({_factor_key(factor)[0] for factor in factors}),
            "factors": [
                {
                    "category": _factor_key(factor)[0],
                    "geography": factor.geography or "",
                    "amount": factor.amount,
                }
                for factor in factors
            ],
        },
    )


def _redirect_refused(
    source: FactorSource, flow_uuid: str, factors: list, retirement: RetiredFlow
) -> Finding:
    """Factors about an identifier whose redirect this build must not follow.

    The whole reason is in `retirement.reason`, and it is the export's word for
    it, so a reader who has met the redirect in `harmonised-flows-simple.json.gz`
    meets the same explanation here.  The numbers travel with the row for the
    reason `_unreached` gives: what a reader can weigh is the factor, not a count
    of factors.
    """
    return Finding(
        kind=FindingKind.REDIRECT_REFUSED,
        implemented_by=source.implementation.name,
        elementary_flow_uuid=retirement.replaced_by or None,
        impact_category_id=None,
        detail=(
            f"{flow_uuid} carries {len(factors)} factors and this build retires "
            f"it as {retirement.reason}"
            + (
                f", replaced by {retirement.replaced_by}"
                if retirement.replaced_by
                else " with nothing published to replace it"
            )
            + " -- a redirect a consumer is told to refuse, so the numbers are "
            "not republished on the survivor"
        ),
        context={
            "retired_flow_uuid": flow_uuid,
            "reason": retirement.reason,
            "replaced_by": retirement.replaced_by,
            "factor_count": len(factors),
            "factors": [
                {
                    "category": _factor_key(factor)[0],
                    "geography": factor.geography or "",
                    "amount": factor.amount,
                }
                for factor in factors
            ],
        },
    )


def _redirect_followed(
    source: FactorSource, flow_uuid: str, carried: list[MatchedFactor]
) -> Finding:
    """Numbers a retired identifier held that its survivor does not state.

    Reported one row per retired identifier, and only where something was
    actually carried: an identifier whose factors merely restate the survivor's
    own is a count, not an event.  This is the case `deduplication.
    settle_factor_values` deliberately leaves open -- it settles a factor *both*
    rows publish and unions nothing -- and until #163 the number stayed published
    under the dead identifier, which is a union a consumer following redirects
    performed without being told.
    """
    return Finding(
        kind=FindingKind.REDIRECT_FOLLOWED,
        implemented_by=source.implementation.name,
        elementary_flow_uuid=carried[0].elementary_flow_uuid,
        impact_category_id=None,
        detail=(
            f"{flow_uuid} was retired onto {carried[0].elementary_flow_uuid}, "
            f"which states nothing for {len(carried)} of the factors it held: "
            + ", ".join(
                f"{_factor_key(row.factor)[0]} {row.factor.amount!r}"
                for row in carried[:4]
            )
            + (", ..." if len(carried) > 4 else "")
            + " -- so they are published on the survivor"
        ),
        context={
            "retired_flow_uuid": flow_uuid,
            "factor_count": len(carried),
            "factors": [
                {
                    "category": _factor_key(row.factor)[0],
                    "geography": row.factor.geography or "",
                    "amount": row.factor.amount,
                }
                for row in carried
            ],
        },
    )


def _unit_crossing(source: FactorSource, target: MergeTarget, flow_uuid: str,
                   factors: list) -> Finding:
    return Finding(
        kind=FindingKind.UNIT_CROSSING,
        implemented_by=source.implementation.name,
        elementary_flow_uuid=target.elementary_flow_uuid,
        impact_category_id=None,
        detail=(
            f"{flow_uuid} states {len(factors)} factors per "
            f"{target.crossing.source_unit} and the flow they reach is published "
            f"per {target.crossing.target_unit}, with no conversion recorded for "
            "the pair -- so publishing them would state a number in a unit nobody "
            "asked for"
        ),
        context={
            "source_flow_uuid": flow_uuid,
            "source_unit": target.crossing.source_unit,
            "target_unit": target.crossing.target_unit,
            "factor_count": len(factors),
        },
    )


def match(
    source: FactorSource,
    *,
    index: dict[str, MergeTarget] | None = None,
    retired: Mapping[str, RetiredFlow] | None = None,
    counts: Counter | None = None,
    declined: Mapping[str, str] | None = None,
    conversions: Mapping[tuple[str, str, str], float] | None = None,
    collision_rulings: Mapping[tuple[str, str], Any] | None = None,
) -> tuple[list[MatchedFactor], list[Finding]]:
    """Every factor of one implementation, on the consensus flow it belongs to.

    *index* maps the publisher's flow uuid to where the merge put it, and is not
    given for an implementation whose factors already name consensus flows.
    *retired* is `retired_flows`, and is what those implementations need instead:
    their uuids are ours, so a deprecation of ours moves their factors.  Omitting
    it publishes a factor under whatever identifier stated it, deprecated or not,
    which is the state #163 describes.

    *counts*, when given, is filled with what the redirects did -- the caller's
    statistics rather than a second return value, the arrangement
    `redirects.retirement_redirects` uses for the same reason.

    *declined* is the reasoning for the rows a curator ruled reach nothing, keyed
    the same way, and rides on the finding each of those rows already gets.

    *conversions* is `recorded_conversions`, and is what a row reached by its
    name or by a curated decision has instead of a multiplier of its own: the
    conversion this build already recorded for that flow between those two
    units.  Without it a factor stated per kilogram against a flow published per
    cubic metre is dropped even where the merge wrote down the density (#170).
    """
    findings: list[Finding] = []
    grouped: dict[tuple[str, str, str], list[MatchedFactor]] = defaultdict(list)
    tally: Counter = Counter() if counts is None else counts
    carried: dict[str, list[MatchedFactor]] = defaultdict(list)
    converted = 0
    for flow_uuid, factors in sorted(source.by_flow.items()):
        redirected: str | None = None
        if source.flows_are_consensus:
            retirement = (retired or {}).get(flow_uuid)
            if retirement is None:
                target = MergeTarget(flow_uuid, UnitCrossing("", ""))
            elif retirement.followable:
                target = MergeTarget(retirement.replaced_by, UnitCrossing("", ""))
                redirected = flow_uuid
                tally["retired_flows_followed"] += 1
                tally["factors_redirected"] += len(factors)
            else:
                findings.append(
                    _redirect_refused(source, flow_uuid, factors, retirement)
                )
                tally["retired_flows_refused"] += 1
                tally["factors_refused"] += len(factors)
                continue
        else:
            found = (index or {}).get(flow_uuid)
            if found is None:
                findings.append(
                    _unreached(
                        source,
                        flow_uuid,
                        factors,
                        (declined or {}).get(flow_uuid, ""),
                    )
                )
                continue
            target = found
            if not target.crossing.convertible:
                recorded = (conversions or {}).get(
                    (
                        target.elementary_flow_uuid,
                        target.crossing.source_unit,
                        target.crossing.target_unit,
                    )
                )
                if recorded is None:
                    findings.append(
                        _unit_crossing(source, target, flow_uuid, factors)
                    )
                    continue
                target = MergeTarget(
                    elementary_flow_uuid=target.elementary_flow_uuid,
                    crossing=UnitCrossing(
                        source_unit=target.crossing.source_unit,
                        target_unit=target.crossing.target_unit,
                        multiplier=recorded,
                    ),
                )
                tally["conversions_reused"] += 1
                tally["factors_converted_by_a_recorded_conversion"] += len(factors)
        for factor in factors:
            category, geography = _factor_key(factor)
            amount = target.crossing.convert(factor.amount)
            crossed = amount != factor.amount or target.crossing.crosses
            converted += 1 if crossed else 0
            grouped[(target.elementary_flow_uuid, category, geography)].append(
                MatchedFactor(
                    elementary_flow_uuid=target.elementary_flow_uuid,
                    factor=(
                        factor
                        if not crossed
                        else StatedFactor(
                            category=factor.category,
                            flow_uuid=factor.flow_uuid,
                            amount=amount,
                            geography=factor.geography,
                            amount_key=factor.amount_key,
                            stated_keys=factor.stated_keys,
                            provenance=factor.provenance,
                            superseded_values=factor.superseded_values,
                            extra=factor.extra,
                        )
                    ),
                    # For an implementation whose flows are ours, this is empty
                    # unless a redirect was followed -- and then it is the
                    # identifier the number was published under, which is what
                    # the field is for and the only way a reader can tell a
                    # carried factor from one the flow's own row states.
                    source_flow_uuid=(
                        redirected if source.flows_are_consensus else flow_uuid
                    ),
                    stated_amount=factor.amount if crossed else None,
                )
            )

    matched: list[MatchedFactor] = []
    for (elementary_uuid, category, geography), candidates in grouped.items():
        if source.flows_are_consensus:
            # The flow's own row outranks a redirect onto it: `source_flow_uuid`
            # is set here only where one was followed.  Not a judgement about the
            # numbers -- `deduplication.settle_factor_values` made that one when
            # it collapsed the two flows -- so `settle` is not asked to make it
            # again, which it would answer by publishing neither.
            direct = [row for row in candidates if row.source_flow_uuid is None]
            if direct and len(direct) < len(candidates):
                tally["factors_restated"] += len(candidates) - len(direct)
                candidates = direct
        kept, finding = settle(
            candidates,
            elementary_flow_uuid=elementary_uuid,
            implemented_by=source.implementation.name,
            category=category,
            geography=geography or None,
            # A curator's answer to this flow and category colliding, keyed
            # on the flow and the category's name as the finding prints it
            # (`lcia.collision_rulings`, #196).
            ruling=(collision_rulings or {}).get(
                (elementary_uuid, str(category).strip().lower())
            ),
        )
        if kept is not None:
            matched.append(kept)
            if source.flows_are_consensus and kept.source_flow_uuid is not None:
                tally["factors_carried"] += 1
                carried[kept.source_flow_uuid].append(kept)
        if finding is not None:
            findings.append(finding)
    findings.extend(
        _redirect_followed(source, flow_uuid, rows)
        for flow_uuid, rows in sorted(carried.items())
    )
    logger.info(
        "matched_factors",
        implemented_by=source.implementation.name,
        factors=len(matched),
        converted=converted,
        findings=len(findings),
        **{key: value for key, value in tally.items() if value},
    )
    return matched, findings
