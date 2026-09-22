"""Asking the lookup every question a build has already answered.

``merge_outcomes`` stores, per source row, what the row was -- its name, its
compartment, its unit, its registry numbers -- and what the merge decided about
it.  That is this API's question and its answer, written down 16,953 times.  So
the way to find out whether the lookup agrees with the build is not to reason
about it: it is to rebuild a :class:`FlowQuery` from each recorded row, ask, and
count.

Offline, against a stored snapshot, in the spirit of
``tools/compare_merge_outcomes.py`` -- seconds, not the hour a build costs.

## What a divergence means, and what it does not

A row is sorted into one of six buckets by *how the build decided it*, because
the buckets are not equally answerable and lumping them would hide that:

``evidence``
    The row matched on something the query carries -- a CAS number, an EC
    number, a name, a SimaPro spelling.  **These must reproduce.**  A divergence
    here is a defect in the lookup, and the only bucket where that is true.

``material``, ``land_class``, ``particulate_size_class``
    The build read which kind of water, which land class, or which particle
    size window, out of a curated table keyed on the vendor's uuid.  A query
    has no uuid; the first two tables also record the vendor's spelling, and
    since #358 the lookup consults them under the row's prepared name, so these
    now reproduce except where two rows disagree about a name the compartment
    cannot split.  §6.1.

    The third is the one that reproduces least, and deliberately.  An
    airborne-particle row carries no registry number, and a per-name table is
    exactly what it must not have -- `Particulates, < 10 um` reaching PM10 by
    name is the accident #153 removed.  A caller who knows says
    `size_class="pm10"`.

``prepared``, ``prepared-mapping``
    A curator's correspondence table decided, not the algorithm.  The algorithm
    is *allowed* to reach a different flow, and how often it reaches the same
    one is worth knowing -- it is the measurement §3.3's tier one is argued
    from -- but it is not a claim about correctness either way.

``created``
    No consensus flow existed, so the merge made one.  Replayed against the
    *finished* build that flow is there, so the row should now find it: 840 of
    842 do.  That is not a divergence from the plan's expectation of
    ``matched=False`` -- it is the plan's expectation being about the build as
    it stood *before* the merge, and the strongest single piece of evidence that
    the lookup agrees with the merge about where a row belongs.

## What it cannot measure

``merge_outcomes`` records the row's *name*, and matching is done on every name
a row is known by.  A row that matched on a synonym, an alternative label
enrichment found, or a catalogue code cannot be reconstructed from what was
stored -- so the replay understates a real caller who supplies their synonyms,
and overstates one who does not.  :func:`replay` takes ``with_recorded_names``
for this: ``basis_value`` carries the names a label match actually used.

See ``plans/lookup-api.md`` §5.1.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace as _replace
from pathlib import Path

import orjson
import structlog

from brightway_flows.lookup.matcher import FlowMatch, FlowMatcher
from brightway_flows.lookup.query import FlowQuery
from brightway_flows.merge.store import (
    MergeOutcome,
    latest_run_id,
    read_outcomes,
)
from brightway_flows.sources import SourceList, known_source_lists

logger = structlog.get_logger(__name__)

#: How the build decided a row, as the buckets a replay is counted in.
EVIDENCE = "evidence"
MATERIAL = "material"
LAND_CLASS = "land_class"
SIZE_CLASS = "particulate_size_class"
PREPARED = "prepared"
PREPARED_MAPPING = "prepared-mapping"
CREATED = "created"
BUCKETS = (
    EVIDENCE, MATERIAL, LAND_CLASS, SIZE_CLASS, PREPARED, PREPARED_MAPPING, CREATED
)

#: The bases whose ``basis_value`` names labels rather than a registry number.
_LABEL_BASES = frozenset({
    "label",
    "cas+label",
    "cas+label+preferred-name",
    "label+preferred-name",
    "simapro-name-pattern",
    "historical-name",
    "preferred-name",
})


def bucket_of(outcome: MergeOutcome) -> str:
    """Which bucket *outcome* belongs to; see the module docstring."""
    if outcome.matching_method == "flow_object_creation":
        return CREATED
    if outcome.matching_method == "prepared":
        return PREPARED_MAPPING if outcome.basis == "prepared_mapping" else PREPARED
    if outcome.basis in (MATERIAL, LAND_CLASS, SIZE_CLASS):
        return outcome.basis
    return EVIDENCE


def query_for(
    outcome: MergeOutcome, *, with_recorded_names: bool = False
) -> FlowQuery:
    """The question a caller holding this row would have asked.

    The list is named through ``source_label``, which is what a caller who knows
    which vendor their rows came from would do, and is what makes the
    comparison about *matching* rather than about context resolution.  The
    SimaPro flag comes from the registered list, because it is a fact about the
    list rather than about the row.

    ``with_recorded_names`` adds the names a label match used, out of
    ``basis_value``.  Those are names the row was known by, which a real caller
    would plausibly carry as synonyms -- and their absence is exactly what the
    replay cannot otherwise see.
    """
    source = _registered_list(outcome)
    synonyms: list[str] = []
    if with_recorded_names and outcome.basis in _LABEL_BASES and outcome.basis_value:
        synonyms = [
            part.strip() for part in outcome.basis_value.split(";") if part.strip()
        ]
    return FlowQuery(
        name=outcome.source_name,
        context=list(outcome.source_context or []),
        cas=outcome.source_cas,
        ec=outcome.source_ec,
        unit=outcome.source_unit,
        synonyms=synonyms,
        simapro_origin=bool(source and source.simapro_origin),
        source_label=source.source_label if source else "",
    )


def _registered_list(outcome: MergeOutcome):
    for source in known_source_lists().values():
        if (source.list_name, source.list_version) == (
            outcome.list_name,
            outcome.list_version,
        ):
            return source
    return None


def shipped_names(source: SourceList) -> dict[str, str]:
    """``vendor uuid -> the name the vendor's own file spells``, unprepared.

    ``merge_outcomes`` stores the name matching *saw*, which for a SimaPro-shaped
    list is not the name the vendor wrote: `SourceList.load_flows` has already
    taken the unit back out of it, so BAFU's `Wood, unspecified, standing/m3` is
    recorded as `Wood, unspecified, standing`.  A replay built from the recorded
    name therefore never asks the question an outside caller asks, and cannot see
    the half of the row preparation exists for (#328).

    So the file is read.  It is the same file the build read, and the uuid is the
    same key, so the pairing is exact rather than a name match.

    Empty for a list whose flows are not on disk -- an `assess` run against a
    build somebody else made need not have the vendor's file -- which the caller
    reads as "cannot ask this list" rather than as "this list has no rows".
    """
    try:
        payload = orjson.loads(source.flows_path.read_bytes())
    except (FileNotFoundError, OSError, orjson.JSONDecodeError):
        logger.info("shipped_names_unavailable", source=source.key)
        return {}
    if not isinstance(payload, list):
        return {}
    return {
        str(row["uuid"]).strip(): str(row.get("name") or "")
        for row in payload
        if isinstance(row, dict) and str(row.get("uuid") or "").strip()
    }


@dataclass(frozen=True)
class BucketTally:
    """What happened to the rows of one bucket."""

    bucket: str
    rows: int = 0
    #: The lookup reached the flow the build recorded.
    same_target: int = 0
    #: …and reached it by the same route, which only `evidence` claims.
    same_basis: int = 0
    #: The lookup matched, and to some other flow.
    other_target: int = 0
    #: The lookup did not match at all.
    unmatched: int = 0

    @property
    def agreement(self) -> float:
        """Share of the bucket's rows that reached the same flow."""
        return (self.same_target / self.rows) if self.rows else 0.0


@dataclass(frozen=True)
class Divergence:
    """One row the lookup placed differently from the build."""

    outcome: MergeOutcome
    result: FlowMatch

    def describe(self) -> str:
        return (
            f"{self.outcome.list_name}-{self.outcome.list_version} "
            f"{self.outcome.source_name!r} {self.outcome.source_context} "
            f"cas={self.outcome.source_cas!r} unit={self.outcome.source_unit!r}\n"
            f"    build : {self.outcome.target_elementary_flow_id or '(none)'} "
            f"basis={self.outcome.basis!r}\n"
            f"    lookup: {self.result.elementary_flow_id or '(none)'} "
            f"basis={self.result.basis!r} reason={self.result.selector_reason!r} "
            f"context={self.result.context_resolution!r}"
        )


@dataclass(frozen=True)
class ReplayResult:
    """Every recorded row, asked again."""

    run_id: str
    rows: int
    tallies: dict[str, BucketTally] = field(default_factory=dict)
    #: The `evidence` rows that did not reach the recorded flow -- the only ones
    #: that are a defect.  Kept whole so a failure can be read rather than
    #: merely counted.
    divergences: tuple[Divergence, ...] = ()

    @property
    def same_target(self) -> int:
        return sum(tally.same_target for tally in self.tallies.values())

    def report(self) -> str:
        lines = [f"replay of {self.run_id}: {self.rows} rows"]
        for bucket in BUCKETS:
            tally = self.tallies.get(bucket)
            if tally is None or not tally.rows:
                continue
            lines.append(
                f"  {bucket:17} n={tally.rows:6}  same target={tally.same_target:6}"
                f"  other={tally.other_target:5}  unmatched={tally.unmatched:5}"
                f"  ({tally.agreement:.1%})"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class ShippedNameResult:
    """A SimaPro-shaped list asked under the names its vendor's file spells.

    Two numbers and the rows behind one of them.  :attr:`rewritten` is how many
    of the vendor's names carry a unit or a place that a build takes out before
    matching; :attr:`placed` is how many of those reach the flow the build
    recorded anyway, which is what preparation buys a caller.
    """

    list_key: str
    rows: int = 0
    #: Rows whose shipped name preparation rewrote.
    rewritten: int = 0
    #: …of which reached the flow the build recorded.
    placed: int = 0
    #: …and reached some other flow, which should be nothing: preparation puts
    #: the rewritten name in front of the caller's rather than instead of it, so
    #: it can add a way to match and cannot move one.
    elsewhere: int = 0
    names: tuple[str, ...] = ()


def replay_shipped_names(
    db_path: Path,
    *,
    run_id: str | None = None,
    matcher: FlowMatcher | None = None,
) -> tuple[ShippedNameResult, ...]:
    """Every SimaPro-shaped list, asked as the vendor's own file spells it.

    :func:`replay` asks under the name `merge_outcomes` recorded, which is the
    name matching saw -- already prepared.  This asks under the name the vendor
    wrote, which is what somebody holding that file has, and so is the only
    measurement that can see what :func:`~brightway_flows.lookup.query.
    prepare_query` is for.

    Only lists whose ``simapro_origin`` is true, because they are the only ones
    any of it applies to, and only where the vendor's file is on disk.
    """
    run = run_id or latest_run_id(db_path) or ""
    engine = matcher if matcher is not None else FlowMatcher.from_results(db_path)
    outcomes = read_outcomes(db_path, run_id=run)
    by_list: dict[tuple[str, str], list[MergeOutcome]] = {}
    for outcome in outcomes:
        by_list.setdefault((outcome.list_name, outcome.list_version), []).append(outcome)

    results: list[ShippedNameResult] = []
    for source in known_source_lists().values():
        rows = by_list.get((source.list_name, source.list_version))
        if not rows or not source.simapro_origin:
            continue
        names = shipped_names(source)
        if not names:
            continue
        asked = [
            _replace(query_for(outcome), name=names[outcome.source_uuid])
            for outcome in rows
            if outcome.source_uuid in names
        ]
        kept = [outcome for outcome in rows if outcome.source_uuid in names]
        answers = engine.match_many(asked)
        rewritten = [
            (outcome, answer)
            for outcome, answer in zip(kept, answers)
            if answer.preparation_steps
        ]
        results.append(ShippedNameResult(
            list_key=source.key,
            rows=len(kept),
            rewritten=len(rewritten),
            placed=sum(
                1
                for outcome, answer in rewritten
                if answer.elementary_flow_id == outcome.target_elementary_flow_id
            ),
            elsewhere=sum(
                1
                for outcome, answer in rewritten
                if answer.matched
                and outcome.target_elementary_flow_id
                and answer.elementary_flow_id != outcome.target_elementary_flow_id
            ),
            names=tuple(sorted(
                query.name
                for query, answer in zip(asked, answers)
                if answer.preparation_steps
            )),
        ))
    return tuple(results)


def replay(
    db_path: Path,
    *,
    run_id: str | None = None,
    with_recorded_names: bool = False,
    matcher: FlowMatcher | None = None,
    outcomes: Iterable[MergeOutcome] | None = None,
) -> ReplayResult:
    """Ask the lookup every question *db_path*'s merge already answered.

    *matcher* is accepted so a caller with one already built does not pay for a
    second; it must have been built from *db_path*, because a replay of one
    build against another's indexes is a comparison of two things at once.
    """
    run = run_id or latest_run_id(db_path) or ""
    rows = list(outcomes) if outcomes is not None else read_outcomes(db_path, run_id=run)
    if not rows:
        return ReplayResult(run_id=run, rows=0)

    engine = matcher if matcher is not None else FlowMatcher.from_results(db_path)
    results = engine.match_many(
        query_for(outcome, with_recorded_names=with_recorded_names) for outcome in rows
    )

    counts: dict[str, dict[str, int]] = {
        bucket: {"rows": 0, "same_target": 0, "same_basis": 0, "other_target": 0, "unmatched": 0}
        for bucket in BUCKETS
    }
    divergences: list[Divergence] = []
    for outcome, result in zip(rows, results):
        bucket = bucket_of(outcome)
        counter = counts[bucket]
        counter["rows"] += 1
        if not result.matched:
            counter["unmatched"] += 1
        elif result.elementary_flow_id == outcome.target_elementary_flow_id:
            counter["same_target"] += 1
            if result.basis == outcome.basis:
                counter["same_basis"] += 1
        else:
            counter["other_target"] += 1
        if bucket == EVIDENCE and (
            not result.matched
            or result.elementary_flow_id != outcome.target_elementary_flow_id
        ):
            divergences.append(Divergence(outcome=outcome, result=result))

    return ReplayResult(
        run_id=run,
        rows=len(rows),
        tallies={
            bucket: BucketTally(bucket=bucket, **values)
            for bucket, values in counts.items()
        },
        divergences=tuple(divergences),
    )
