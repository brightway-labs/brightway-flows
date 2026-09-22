"""Two renderings of one method, compared factor by factor.

**The headline is the agreement.**  Measured over a full build of 2026-08-17, the
JRC's implementation of EF 3.1 and the ecoinvent Centre's agree *exactly* -- same
float, full precision -- on **21,800 of 22,107** (flow, category, place) triples
they both state.  98.6%.  That is what makes the other 1.4% readable as signal
rather than noise, and it is not a number anybody has been able to quote before,
because until both are on one flow list the triples cannot be formed.

| | triples |
|---|---:|
| identical | 21,800 |
| differ, within 2% | 165 |
| differ, 2% to 2x | 36 |
| differ, 2x to 10x | 34 |
| differ, 10x to 100x | 52 |
| differ, over 100x | 20 |
| *(differ across zero or a sign)* | *0* |

**This report is the triples more than one implementation states.**  Where only
one speaks there is no comparison to record -- 230,647 of the JRC's non-zero
factors and 51,931 of its stated zeros are on flows no other implementation of
EF 3.1 has, which is a fact about differently sized flow lists (§8.4) and not a
difference between two readings.  Those are counted in the summary under
`only:<implementation>` and left out of the rows; the ecoinvent-only factors
are counted the same way, and what the restating rule does not settle of them
is the `proposed-factor` queue's own subject.

**One row per implementation, not per pair.**  Two implementations of one triple
are two rows carrying one band, and three would be three: the report is long-form
so that a third implementation needs no new column and no reader has to pivot.

**It must not call a difference an error.**  679 differences between competent
teams are mostly modelling choices, and the 36 over 100x are the ones worth a
conversation, not a correction.  A stated zero against a number is a difference and
gets a band of its own, because a relative difference across zero is not defined --
12 of them on the four-list build of 2026-08-29.

The trap §5 warned about is gone rather than guarded: a comparison across
timeframes would report 225 phantom differences that are a declared scope, and with
`no LT` unpublished (§2.4) every category a comparison can reach is `LONG`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from brightway_flows.domain.lcia.records import (
    LONG_TERM,
    Band,
    CoverageGap,
    Difference,
    only_stated_by,
)
from brightway_flows.flow_layers.contested_cas import FACTOR_TOLERANCE
from brightway_flows.domain.lcia.crosswalk import MethodImplementation
from brightway_flows.lcia.consensus import FactorKey
from brightway_flows.lcia.matching import MatchedFactor

logger = structlog.get_logger(__name__)

#: Re-exported: the rows this module computes are declared beside the records
#: they are published with (`domain.lcia.records`), and every reader of this
#: module imports them from here.
__all__ = [
    "LONG_TERM",
    "Band",
    "CoverageGap",
    "Difference",
    "band_for",
    "compare",
    "coverage",
    "only_stated_by",
]


def band_for(amounts: Sequence[float]) -> tuple[Band, float | None]:
    """How far apart the implementations are, from the widest pair among them.

    *amounts* is every number stated about one triple.  With two it is the pair;
    with more it is the extremes, because "how far apart is this triple" is the
    question the band answers and a middling third implementation does not make
    the widest disagreement narrower.
    """
    low, high = min(amounts), max(amounts)
    if low == high:
        return Band.IDENTICAL, 1.0
    if 0 in amounts or (low > 0) != (high > 0):
        return Band.INCOMPARABLE, None
    smallest, largest = sorted((abs(low), abs(high)))
    ratio = largest / smallest
    if ratio - 1 <= FACTOR_TOLERANCE:
        return Band.WITHIN_TOLERANCE, ratio
    for limit, band in ((2, Band.UP_TO_2X), (10, Band.UP_TO_10X), (100, Band.UP_TO_100X)):
        if ratio <= limit:
            return band, ratio
    return Band.OVER_100X, ratio


def compare(
    *,
    method: str,
    stated: Mapping[MethodImplementation, dict[FactorKey, MatchedFactor]],
    consensus: dict[FactorKey, str | None],
) -> tuple[list[Difference], dict[str, int]]:
    """Every triple more than one implementation states, and a count of them all.

    *method* is the method the implementations implement, carried onto every row:
    a category slug belongs to a method, and a report over two methods that did
    not say which would put two unrelated `acidification` rows side by side.

    *stated* is each published implementation's factors, keyed on
    :data:`FactorKey`.  A mapping rather than two named arguments because there
    will be more than two: every source list that ships factors is an
    implementation, and a signature naming two of them would have to be changed to
    compare a third -- while a caller passing three to a two-argument function
    would silently compare two.

    *consensus* maps a key to the derivation the consensus implementation
    published it under, or is missing the key where that implementation asked a
    curator instead -- so a reader of one row can see whether this list took a
    side.
    """
    rows: list[Difference] = []
    counts: Counter[str] = Counter()
    keys: set[FactorKey] = set()
    for factors in stated.values():
        keys.update(factors)

    shared = 0
    for key in keys:
        speaking = [
            (implementation, factors[key])
            for implementation, factors in stated.items()
            if key in factors
        ]
        if len(speaking) < 2:
            implementation, only = speaking[0]
            counts[
                only_stated_by(implementation.name, zero=only.factor.amount == 0)
            ] += 1
            continue
        shared += 1
        band, ratio = band_for([matched.factor.amount for _, matched in speaking])
        counts[str(band)] += 1
        for implementation, matched in speaking:
            rows.append(
                Difference(
                    method=method,
                    elementary_flow_uuid=key[0],
                    category_slug=key[1],
                    geography=key[2],
                    implemented_by=implementation.name,
                    amount=matched.factor.amount,
                    source_flow_uuid=matched.source_flow_uuid,
                    band=band,
                    ratio=ratio,
                    derivation=consensus.get(key),
                )
            )
    counts["shared"] = shared
    counts["total"] = len(keys)
    logger.info(
        "compared_implementations",
        method=method,
        implementations=len(stated),
        shared=shared,
        identical=counts[str(Band.IDENTICAL)],
        differing=shared - counts[str(Band.IDENTICAL)],
    )
    return rows, dict(counts)


def coverage(
    *,
    method: str,
    characterised: dict[tuple[str, str, str], set[str]],
    flows: dict[str, dict[str, Any]],
    own_flows: dict[str, set[str]],
) -> tuple[list[CoverageGap], dict[str, int]]:
    """Where an implementation characterises a substance and skips a context of it.

    *method* is the method being covered, carried onto every row for the reason
    :func:`compare` carries it: a category slug is only a category inside one.

    *characterised* maps ``(implementation, category slug, substance)`` to the
    flows it states a factor for; *flows* describes every published flow; and
    *own_flows* is the consensus flows each implementation's own list reaches,
    keyed on ``implemented_by``, which is what makes the question answerable at
    all: an implementation cannot skip a flow its list does not have.
    """
    by_substance: dict[str, set[str]] = defaultdict(set)
    for uuid, flow in flows.items():
        if not flow.get("deprecated"):
            by_substance[str(flow.get("flow_object_id") or "")].add(uuid)

    gaps: Counter[tuple[str, str, str]] = Counter()
    counts: Counter[str] = Counter()
    for (implemented_by, _slug, substance), covered in characterised.items():
        reachable = own_flows.get(implemented_by, set())
        for uuid in by_substance.get(substance, set()) - covered:
            context = str(flows[uuid].get("context_display") or "")
            if LONG_TERM in context.lower():
                counts["skipped_long_term"] += 1
                continue
            if uuid not in reachable:
                counts["skipped_not_in_own_list"] += 1
                continue
            # Under the method as well: an implementer can render two, and
            # what it skips under one says nothing about the other.
            counts[f"{method}:{implemented_by}"] += 1
            gaps[(implemented_by, "compartment", context)] += 1
            gaps[(implemented_by, "category", _slug)] += 1

    rows = [
        CoverageGap(
            method=method,
            implemented_by=implemented_by,
            dimension=dimension,
            value=value,
            flows=count,
        )
        for (implemented_by, dimension, value), count in sorted(
            gaps.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    logger.info("summarised_coverage", method=method, rows=len(rows), **counts)
    return rows, dict(counts)
