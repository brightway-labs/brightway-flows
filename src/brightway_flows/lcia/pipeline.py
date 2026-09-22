"""`characterise`: every registered method, onto the consensus flows.

Runs after `build` and reads what it wrote.  That is worth protecting: iterating
on a rule about factors should cost a minute rather than an hour, which is the
same reason `tools/replay_selector_traces.py` exists for the merge.

**One method at a time, and the methods do not meet.**  `domain.lcia.crosswalk`
registers one file per method, and this walks them: EF 3.1 today, and a second
method is a second file.  Two methods share a flow list and nothing else -- not a
category, not a unit, not an implementation, not a curated ruling -- so every
step below runs inside a method and every statistic it counts is written under
that method's slug.  What is *not* per method is the run's own totals: how many
categories were published, how many factors, how many findings, and the two
reports, which are one report over every method characterised.

The order inside a method is short, because most of the work was done before this
runs:

1. the impact categories, built from the method file (`lcia.categories`);
2. each implementation's factors, by whichever route its own row names -- already
   on the published flows, or in the file `fetch-lcia` wrote from the list it
   names (`lcia.sources`);
3. each set matched onto consensus flows -- identity for the first route, two
   hops for the second (`lcia.matching`);
3b. what the model the method's toxicity categories are derived from states about
   the same substances, and which of them it contradicts in this build
   (`lcia.contradictions`);
4. the questions nobody has ruled on written to the three factor queues, and the
   ones somebody has published as `ruled` (`lcia.consensus`, `lcia.rulings`);
5. all of it written to the LCIA tables (`lcia.store`), and out as the two
   published artifacts (`lcia.publish`).

Two mappings and the difference between them is the point: **everything
transcribed is compared**, and only the implementations the method file says
`decides` are derived from.  GreenDelta's implementation of EF 3.1 is published,
is in the difference report, and decides nothing
(`plans/greendelta-implementation.md`).

Every curated file a method's derivation reads states which method it is about,
and is read for that method only (`lcia.scope`): two methods can spell one
category slug, and a ruling applied because the slugs matched would publish a
number no curator looked at.

Nothing in `build` reads any of this, and nothing here writes a table `build` owns.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from brightway_flows.domain.lcia.crosswalk import (
    FactorRoute,
    ImpactCategoryDefinition,
    LCIAMethodDefinition,
    MethodImplementation,
    lcia_methods,
)
from brightway_flows.domain.lcia.records import ImpactCategory, StatedFactor
from brightway_flows.lcia.categories import (
    consensus_categories_for,
    impact_category_id,
    impact_category_iri,
    published_impact_categories,
)
from brightway_flows.lcia.consensus import (
    Derivation,
    FactorKey,
    derive,
    queue_items,
)
from brightway_flows.lcia.contradictions import (
    ModelEvidence,
    comparable_categories,
    contradictions,
    load_underlying_model_factors,
)
from brightway_flows.lcia.differences import (
    CoverageGap,
    Difference,
    compare,
    coverage,
)
from brightway_flows.lcia.matching import (
    MatchedFactor,
    MergeTarget,
    RetiredFlow,
    chained_merge_targets,
    match,
    recorded_conversions,
    retired_flows,
)
from brightway_flows.lcia.regionalised_names import (
    set_aside as regionalised_set_aside,
)
from brightway_flows.lcia.report import Finding, FindingKind
from brightway_flows.lcia.substance_matching import (
    substance_index,
    substance_targets,
)
from brightway_flows.lcia.sources import (
    FactorSource,
    factors_for,
    flow_descriptions,
    flows_reached_by,
    lcia_source_lists,
    registered_lists,
    source_list_for,
    substance_relatives,
    substances_by_registry_number,
)
from brightway_flows.lcia.publish import (
    artifact_paths,
    build_differences_document,
    build_factors_document,
    write_differences,
    write_factors,
)
from brightway_flows.lcia.misattributions import (
    MisattributedFactor,
    load_misattributed_factors,
    move_factors,
    stated_by_substance,
)
from brightway_flows.lcia.precision import (
    RoundedPrinting,
    load_rounded_printings,
    refine_factors,
)
from brightway_flows.lcia.census import (
    BLANK_DIMENSION,
    IDENTITY_BLANK_DIMENSION,
    PublishedFactor,
    SubstanceRelative,
    context_census,
    identity_census,
)
from brightway_flows.lcia.context_carry import (
    ContextCarryRules,
    carry_across_contexts,
    load_context_carry_rules,
)
from brightway_flows.lcia.collision_rulings import (
    CollisionRuling,
    load_collision_rulings,
)
from brightway_flows.lcia.size_class_carry import (
    SizeClassCarryRules,
    carry_across_size_classes,
    load_size_class_carry_rules,
)
from brightway_flows.lcia.adoptions import (
    FactorAdoption,
    load_factor_adoptions,
)
from brightway_flows.lcia.donors import adopt_donor_numbers
from brightway_flows.lcia.rulings import FactorRuling, load_factor_rulings
from brightway_flows.pipeline.review_records import (
    ReviewQueue,
    ReviewQueueItem,
    Severity,
)
from brightway_flows.pipeline.review_tables import replace_queue_items
from brightway_flows.sources import SourceList
from brightway_flows.lcia.store import (
    CharacterisationRun,
    build_run_id,
    finish_run,
    write_characterisation,
)

logger = structlog.get_logger(__name__)


def _definition_for(
    method: LCIAMethodDefinition,
    factor: StatedFactor,
    *,
    implementation: MethodImplementation,
) -> ImpactCategoryDefinition:
    """The category row a publisher's factor names, inside one method.

    By whatever the publisher's own rows carry -- the JRC's method UUID, or
    ecoinvent's category name -- looked up in that publisher's own index and
    nobody else's (`LCIAMethodDefinition.definition_for`).  A publisher that kept
    somebody else's identifiers needs no case of its own: GreenDelta's rows carry
    the JRC's UUIDs, and the method file states them under GreenDelta's slug, so
    the same lookup finds them.

    :raises ValueError: if the category is not in the method file. That is the
        method file and the ingested data disagreeing about what the words mean,
        and a factor filed under a category nobody declared would be a number no
        reader could interpret.
    """
    definition = method.definition_for(
        implementation=implementation,
        identifier=factor.category.uuid or "",
        name=factor.category.name or "",
    )
    if definition is not None:
        return definition
    raise ValueError(
        f"{implementation.name} states a factor for the category "
        f"{factor.category.name!r} (method {factor.category.uuid!r}), which "
        f"{method.read_from} does not pair with any {method.label_with_version} "
        f"category."
    )


def _comparable(
    method: LCIAMethodDefinition,
    matched: list[MatchedFactor],
    implementation: MethodImplementation,
) -> dict[FactorKey, MatchedFactor]:
    """One implementation's factors, keyed on what makes two of them one factor.

    Our flow, our category and the place.  **Our** category: the JRC calls it
    `Ecotoxicity, freshwater` and ecoinvent calls it `ecotoxicity: freshwater`,
    and the method file is the only thing that knows those are one category.
    Keying on either publisher's own name compares nothing with nothing -- every
    JRC factor `sole`, every ecoinvent factor proposed, and a consensus
    implementation that looks plausible and has compared no numbers at all.
    """
    return {
        (
            row.elementary_flow_uuid,
            _definition_for(method, row.factor, implementation=implementation).slug,
            row.factor.geography or "",
        ): row
        for row in matched
    }


def _by_category(
    method: LCIAMethodDefinition,
    matched: list[MatchedFactor],
    *,
    implementation: MethodImplementation,
) -> dict[str, list[MatchedFactor]]:
    """The matched factors, grouped by the impact category id they belong to."""
    grouped: dict[str, list[MatchedFactor]] = defaultdict(list)
    for row in matched:
        definition = _definition_for(method, row.factor, implementation=implementation)
        iri = impact_category_iri(method, definition, implementation)
        grouped[str(impact_category_id(iri))].append(row)
    return dict(grouped)


def _stat_key(key: str) -> str:
    """A count key as a statistic's name.

    The comparison counts `only:ecoinvent Centre` -- the implementation's own
    name, because the set of them is not fixed -- and a stat key is read from a
    log line and a baseline diff, so the punctuation and the spaces come out.
    """
    for character in (":", "-", " ", "."):
        key = key.replace(character, "_")
    return key.replace("__", "_").strip("_")


def _factor_count(items: list[ReviewQueueItem]) -> int:
    """How many factors a set of queue items is about."""
    return sum(item.payload["factor_count"] for item in items)


def _declined_numbers(
    source: FactorSource, matched: list[MatchedFactor]
) -> list[Finding]:
    """The numbers this list declined, said out loud where a comparison can see.

    `pipeline.deduplication` settles them during the build -- two rows that turn
    out to be one flow, one factor, two numbers -- and writes the loser onto the
    factor that kept it rather than dropping it (#63).  196 factor rows over 59
    flows carry one, 40 of them differing by more than 2x and the worst by 397x,
    which is #64's kresoxim-methyl: 134.73 published, 53,540 declined, and the
    number the ecoinvent team kept reading the same two EF rows is the one ours
    discarded.

    A reader comparing two implementations has to know that the number they are
    comparing was chosen from two, so each becomes a row.  Nothing is republished
    and nothing moves: this only makes visible what the build already recorded.
    """
    findings: list[Finding] = []
    for row in matched:
        for declined in row.factor.superseded_values:
            ratio = None
            if declined.amount and row.factor.amount:
                low, high = sorted((abs(declined.amount), abs(row.factor.amount)))
                ratio = high / low if low else None
            settled_by = (
                declined.provenance.was_generated_by if declined.provenance else ""
            )
            findings.append(
                Finding(
                    kind=FindingKind.SUPERSEDED_VALUE,
                    implemented_by=source.implementation.name,
                    elementary_flow_uuid=row.elementary_flow_uuid,
                    impact_category_id=None,
                    detail=(
                        f"{row.factor.category.name}: {row.factor.amount!r} is "
                        f"published and {declined.amount!r} was declined"
                        + (f", {ratio:,.0f}x apart" if ratio and ratio >= 2 else "")
                        + (f", settled by {settled_by}" if settled_by else "")
                    ),
                    context={
                        "category": row.factor.category.name,
                        "published": row.factor.amount,
                        "declined": declined.amount,
                        "ratio": ratio,
                        "relative_difference": declined.relative_difference,
                        "settled_by": settled_by,
                        "declined_by": (
                            declined.provenance.had_primary_source
                            if declined.provenance
                            else []
                        ),
                    },
                )
            )
    return findings


def _resolution_chain(source_list: SourceList) -> tuple[tuple[str, str], ...]:
    """The lists an implementation's flows are looked up in, in order.

    The manifest's `resolve_through` where it declares one, and otherwise the
    list's own: ecoinvent's workbook names ecoinvent's flows, and saying so in
    every manifest would be a line that could only ever be the same.
    """
    if source_list.lcia is not None and source_list.lcia.resolve_through:
        registry = registered_lists()
        return tuple(
            (registry[key].list_name, registry[key].list_version)
            for key in source_list.lcia.resolve_through
        )
    return ((source_list.list_name, source_list.list_version),)


def _transcribe(
    method: LCIAMethodDefinition,
    source: FactorSource,
    *,
    db_path: Path,
    source_list: SourceList,
    stats: dict[str, Any],
    conversions: Mapping[tuple[str, str, str], float] | None = None,
    collision_rulings: Mapping[tuple[str, str], CollisionRuling] | None = None,
) -> tuple[dict[str, list[MatchedFactor]], list[Finding], list[MatchedFactor]]:
    """One published implementation, matched and counted.

    The matched rows come back as well as the grouping, because the consensus
    implementation is derived from two of them and grouping by category is not
    the shape that comparison wants.
    """
    index: dict[str, MergeTarget] | None = None
    retired: dict[str, RetiredFlow] | None = None
    # Every count under `{method}_{implementation}`.  Two methods'
    # `brightway-flows` rows are two different things, and so are two
    # methods' ecoinvent rows where one implementer renders both.
    prefix = f"{method.slug}_{source.implementation.slug.replace('-', '_')}"
    findings: list[Finding] = []
    declined: dict[str, str] = {}
    if not source.flows_are_consensus:
        chain = _resolution_chain(source_list)
        index, via = chained_merge_targets(
            db_path, lists=chain, only=set(source.by_flow)
        )
        stats[f"{prefix}_source_flows_merged"] = len(index)
        # The second route, for the flows no identifier reaches: the substance
        # this list already publishes, in the compartment the factor is about
        # (#165). Only what the first route missed -- an identifier is the
        # stronger statement and is not re-decided on a weaker one.
        outstanding = set(source.by_flow) - index.keys()
        if outstanding:
            # A place written into the flow name is not a substance, and a
            # sibling row already carries the number (#166). Found here rather
            # than inside `substance_targets` so the count is its own
            # statistic, apart from the rows a curator declined.
            aside = regionalised_set_aside(source, outstanding)
            by_substance, basis_of, ambiguous, ruled_out = substance_targets(
                source,
                index=substance_index(db_path),
                outstanding=outstanding,
                set_aside=aside,
            )
            index.update(by_substance)
            findings.extend(ambiguous)
            declined = ruled_out
            stats[f"{prefix}_source_flows_by_substance"] = len(by_substance)
            stats[f"{prefix}_source_flows_regionalised_in_name"] = len(aside)
            stats[f"{prefix}_source_flows_declined"] = len(
                ruled_out.keys() - aside.keys()
            )
            for basis in sorted(set(basis_of.values())):
                stats[f"{prefix}_matched_on_{_stat_key(basis)}"] = sum(
                    1 for value in basis_of.values() if value == basis
                )
        # Which list each flow was reached through, where more than one was
        # tried.  A run that says only "1,223 resolved" cannot be asked whether
        # a release it no longer publishes is carrying the answer.
        if len(chain) > 1:
            for list_key in sorted(set(via.values())):
                stats[f"{prefix}_resolved_via_{_stat_key(list_key)}"] = sum(
                    1 for value in via.values() if value == list_key
                )
    else:
        # The identity join is the one a deprecation of ours can move, because
        # its flow uuids are ours (#163).  The implementations whose flows are
        # somebody else's name their publisher's flows, and
        # `elementary_flow_sources` already carries a deprecated flow's
        # references onto its survivor.
        retired = retired_flows(db_path)
    redirect_counts: Counter = Counter()
    matched, found = match(
        source,
        index=index,
        retired=retired,
        counts=redirect_counts,
        declined=declined,
        conversions=(
            recorded_conversions(db_path) if conversions is None else conversions
        ),
        collision_rulings=collision_rulings,
    )
    findings.extend(found)
    findings.extend(_declined_numbers(source, matched))
    grouped = _by_category(method, matched, implementation=source.implementation)
    stats[f"{prefix}_factors_stated"] = source.factor_count
    stats[f"{prefix}_factors_published"] = len(matched)
    stats[f"{prefix}_flows_characterised"] = len(
        {row.elementary_flow_uuid for row in matched}
    )
    stats[f"{prefix}_categories_filled"] = len(grouped)
    for name, count in redirect_counts.items():
        stats[f"{prefix}_{name}"] = count
    for finding in findings:
        stats[f"{prefix}_{finding.kind}"] = stats.get(
            f"{prefix}_{finding.kind}", 0
        ) + 1
    return grouped, findings, matched


def _comparable_key(method: LCIAMethodDefinition, row: MatchedFactor) -> FactorKey:
    """The key a published consensus factor was compared under.

    Resolved from whichever publisher's identity the row carries, the same way
    `_comparable` does -- an `agreed` factor may be ecoinvent's row where its
    number was the more precise one.
    """
    return (
        row.elementary_flow_uuid,
        _definition_for(method, row.factor, implementation=method.consensus).slug,
        row.factor.geography or "",
    )


def _characterised(
    method: LCIAMethodDefinition,
    transcribed: dict[str, list[MatchedFactor]],
    *,
    flows: dict[str, dict[str, Any]],
) -> dict[tuple[str, str, str], set[str]]:
    """Which flows each implementation characterises, per category and substance.

    Keyed on the substance rather than on the flow, because the coverage question
    is about a substance: this implementation characterises it here and not there.
    """
    characterised: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for slug, rows in transcribed.items():
        implementation = method.implementation(slug)
        for row in rows:
            definition = _definition_for(
                method, row.factor, implementation=implementation
            )
            substance = str(
                (flows.get(row.elementary_flow_uuid) or {}).get("flow_object_id") or ""
            )
            characterised[(implementation.name, definition.slug, substance)].add(
                row.elementary_flow_uuid
            )
    return characterised


def _own_flows(
    db_path: Path,
    *,
    method: LCIAMethodDefinition,
    lists: Mapping[str, SourceList],
    reached: Mapping[str, set[str]],
) -> dict[str, set[str]]:
    """The consensus flows each implementation could have characterised.

    What makes the coverage question answerable: an implementation cannot skip a
    flow its own list does not have, and 30,339 of the 36,007 apparent gaps are
    exactly that (§5).

    For a publisher whose factors name its *own* list's flows, that is the list
    -- every consensus flow it was merged onto, whether or not a factor landed
    there.  A publisher with no list of its own names somebody else's, and its
    manifest says so by declaring a `resolve_through`: GreenDelta's package ships
    1,781 flows and no more, so the flows it *could* characterise are the ones
    its factors reached, and *reached* is what the run just measured.  Asking
    after the fact would be the same answer computed twice.

    Keyed on `implemented_by`, which is what a coverage row carries.
    """
    own: dict[str, set[str]] = {}
    for slug, source in lists.items():
        implementation = method.implementation(slug)
        borrows = source.lcia is not None and bool(source.lcia.resolve_through)
        own[implementation.name] = (
            set(reached.get(slug, set()))
            if borrows
            else flows_reached_by(
                db_path,
                list_name=source.list_name,
                list_version=source.list_version,
            )
        )
    return own


@dataclass(frozen=True, slots=True)
class MethodOutcome:
    """Everything one method contributed to the run.

    A record rather than a tuple of seven things, because the run adds them up
    and a caller that got the order wrong would add a coverage count to a
    difference count without failing.
    """

    factors: dict[str, list[MatchedFactor]]
    findings: list[Finding]
    differences: list[Difference]
    coverage: list[CoverageGap]
    queues: dict[ReviewQueue, list[ReviewQueueItem]]
    difference_counts: dict[str, int]
    coverage_counts: dict[str, int]


def _lists_for(
    method: LCIAMethodDefinition, source_lists: Mapping[str, SourceList] | None
) -> dict[str, SourceList]:
    """The registered list each transcription of *method* reads, by its slug.

    *source_lists* is a caller's own registry, keyed on the list key the method
    file names.  Handing one over does two things, and the second is what a test
    is after: the lists in it are read instead of the registry's, **and they are
    the only ones read**.  A run whose factors also came from whatever the data
    directory happened to hold would be a test of somebody's last fetch.

    The implementations that read no list are always here: the
    ``published-flows`` route reads the database the run was given, so there is
    no file for a caller to substitute and nothing for it to leave out.
    """
    lists: dict[str, SourceList] = {}
    for implementation in method.transcriptions:
        key = implementation.factors.source_list
        if source_lists is not None:
            if implementation.factors.route is FactorRoute.SOURCE_LIST:
                if key not in source_lists:
                    continue
                lists[implementation.slug] = source_lists[key]
                continue
        lists[implementation.slug] = source_list_for(implementation)
    return lists


def _collision_rulings_by_flow(
    rulings: Mapping[tuple[str, str, str], CollisionRuling],
    *,
    flows: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], CollisionRuling]:
    """The rulings, keyed the way `lcia.matching` looks them up.

    A ruling names a substance, a category and a compartment; the matching
    settles a collision on an elementary flow and a category name.  Resolved
    here, once per method, over the flows this build publishes: every live flow
    of the ruling's substance in the ruling's compartment answers to it.
    """
    by_place: dict[tuple[str, str], list[CollisionRuling]] = {}
    for ruling in rulings.values():
        by_place.setdefault((ruling.flow_object_id, ruling.context_iri), []).append(ruling)
    out: dict[tuple[str, str], CollisionRuling] = {}
    for uuid, flow in flows.items():
        if flow.get("deprecated"):
            continue
        place = (str(flow.get("flow_object_id") or ""), str(flow.get("context_iri") or ""))
        for ruling in by_place.get(place, ()):
            out[(str(uuid), ruling.category.strip().lower())] = ruling
    return out


def _characterise_method(
    method: LCIAMethodDefinition,
    *,
    db_path: Path,
    flows: dict[str, dict[str, Any]],
    substances: dict[str, list[str]],
    stats: dict[str, Any],
    source_lists: Mapping[str, SourceList] | None = None,
    factor_rulings: dict[tuple[str, str, str], FactorRuling] | None = None,
    factor_adoptions: dict[str, FactorAdoption] | None = None,
    misattributed_factors: dict[tuple[str, str], MisattributedFactor] | None = None,
    rounded_printings: dict[tuple[str, str], RoundedPrinting] | None = None,
    context_carry_rules: ContextCarryRules | None = None,
    size_class_carry_rules: SizeClassCarryRules | None = None,
    underlying_model_factors: Iterable[ModelEvidence] | None = None,
    relatives: Mapping[str, SubstanceRelative] | None = None,
) -> MethodOutcome:
    """One method: its transcriptions, its consensus implementation, its reports.

    Every count it writes into *stats* is prefixed with the method's slug, and
    every curated file it reads is read for this method (`lcia.scope`).  Nothing
    it produces is joined to another method's: two methods share the flow table
    and nothing else.

    *relatives* is which substances the build records as an ion of which
    element, read once by the caller for the same reason *flows* is: it is a
    property of the build, not of the method.  Left out, the identity census
    reads it from the build itself.
    """
    prefix = method.slug
    lists = _lists_for(method, source_lists)
    # Read once and handed to every transcription: it is a property of the
    # build, not of the implementation asking, and the table it reads is the
    # largest one here.
    conversions = recorded_conversions(db_path)

    # A curator's answers to two rows of one publisher colliding on one flow,
    # read for this method and resolved onto the flows this build publishes
    # (`lcia.collision_rulings`, #196).
    collision_rulings = _collision_rulings_by_flow(
        load_collision_rulings(method=method.slug), flows=flows
    )
    stats[f"{prefix}_collision_rulings"] = len(collision_rulings)
    factors: dict[str, list[MatchedFactor]] = {}
    findings: list[Finding] = []
    transcribed: dict[str, list[MatchedFactor]] = {}
    reached: dict[str, set[str]] = {}
    for implementation in method.transcriptions:
        source_list = lists.get(implementation.slug)
        if source_list is None:
            # A caller handed over its own registry and left this one out.
            continue
        source = factors_for(
            implementation, db_path=db_path, source=source_list
        )
        grouped, found, matched = _transcribe(
            method,
            source,
            db_path=db_path,
            source_list=source_list,
            stats=stats,
            conversions=conversions,
            collision_rulings=collision_rulings,
        )
        factors.update(grouped)
        findings.extend(found)
        transcribed[implementation.slug] = matched
        reached[implementation.slug] = {row.elementary_flow_uuid for row in matched}

    # Only the implementations the method file says decide.  A transcription
    # ingested to be compared is published and compared and decides nothing:
    # handing it to `derive` would make a number of theirs a candidate for one of
    # ours, and #157 is the argument that it should not be.
    comparable = {
        implementation: _comparable(
            method, transcribed.get(implementation.slug, []), implementation
        )
        for implementation in method.deciding
        if implementation.slug in transcribed
    }
    # A method whose own publisher was not read has nothing to characterise, and
    # is skipped rather than half-published.  Everything below measures against
    # the reference -- the contradiction check, `derive`, the difference report --
    # so without it there is no number to compare anything to.
    #
    # This is the ordinary state of a registered method whose list a run did not
    # merge: Stepwise 2006 is a `--source` like any other, and a build of the
    # three lists that came before it reads no Stepwise factors. Publishing 19
    # empty categories would be worse than publishing none, and crashing on a
    # `--source` the operator did not ask for would be worse still.
    if method.reference not in comparable:
        logger.info(
            "method_not_characterised",
            method=method.slug,
            reference=method.reference.slug,
            reason=(
                "its own publisher's factors were not read; the list they come "
                "from was not merged by this run"
            ),
        )
        return MethodOutcome(
            factors={},
            findings=findings,
            differences=[],
            coverage=[],
            queues={},
            difference_counts={},
            coverage_counts={},
        )
    rulings = (
        load_factor_rulings(method=method.slug)
        if factor_rulings is None
        else dict(factor_rulings)
    )
    # The curated adoptions, read the same way and for the same
    # reason: a test hands over its own and must not be answered with ours.
    adoptions = (
        load_factor_adoptions(method=method.slug)
        if factor_adoptions is None
        else dict(factor_adoptions)
    )
    moves = (
        load_misattributed_factors(method=method.slug)
        if misattributed_factors is None
        else dict(misattributed_factors)
    )
    # The curated printings, read the same way.  A number one implementation
    # rounded and another did not, where the document says they are one number.
    printings = (
        load_rounded_printings(method=method.slug)
        if rounded_printings is None
        else dict(rounded_printings)
    )
    # The context convention is not read per method: it is about our contexts
    # and the same for every method, so `characterise` reads it once and hands
    # it down.  A direct caller that hands nothing gets the curated file.
    carry_rules = (
        load_context_carry_rules() if context_carry_rules is None else context_carry_rules
    )
    # The size-window convention, read the same way: about our windows, the
    # same for every method.
    size_rules = (
        load_size_class_carry_rules()
        if size_class_carry_rules is None
        else size_class_carry_rules
    )
    # What the model this method's toxicity categories are derived from states,
    # and which (substance, category) pairs it contradicts in *this* build.
    # Measured against the reference implementation, because the question is
    # about the method's own number and the others are transcribing it.
    evidence = (
        load_underlying_model_factors(method=method.slug)
        if underlying_model_factors is None
        else tuple(underlying_model_factors)
    )
    contradicted = contradictions(
        evidence,
        stated=comparable[method.reference],
        flows=flows,
        substances=substances,
    )
    published, questions, applied = derive(
        stated=comparable,
        reference=method.reference,
        substances={
            uuid: str(flow.get("flow_object_id") or "") for uuid, flow in flows.items()
        },
        rulings=rulings,
        adoptions=adoptions,
        contradicted=contradicted,
    )

    def slug_of(row: MatchedFactor) -> str:
        return _definition_for(
            method, row.factor, implementation=method.consensus
        ).slug

    # After `derive` and before anything reads the result: a move is about which
    # substance a published number is on, and `derive` has no opinion about that
    # -- it compares implementations flow by flow and cannot see that none of
    # them is talking about the flow the number sits on.  Only the consensus
    # implementation is touched; the transcriptions keep saying what their
    # publishers said (#126).
    published, moved = move_factors(
        published,
        moves=moves,
        slug_of=slug_of,
        flows=flows,
        stated=stated_by_substance(comparable, flows=flows),
    )
    stats[f"{prefix}_misattributed_factors"] = len(moves)
    for name, count in moved.items():
        stats[f"{prefix}_misattributed_factors_{name}"] = count
    # And after the move, for the same reason it runs after `derive`: a printing
    # is about the number a row publishes, and both of the passes above can
    # change which row that is.  Only rows carrying the rounded amount are
    # rewritten -- the compartments where both implementations spoke already
    # carry the precise value as `agreed` (#342).
    published, refined = refine_factors(
        published,
        printings=printings,
        slug_of=slug_of,
        flows=flows,
        stated=stated_by_substance(comparable, flows=flows),
    )
    stats[f"{prefix}_rounded_printings"] = len(printings)
    for name, count in refined.items():
        stats[f"{prefix}_rounded_printings_{name}"] = count
    # A signed substance taking its donor's *published* number where nobody
    # states one for it (#197): after everything that states a number for the
    # donor, and before the convention, so the recipient's own blank contexts
    # are then filled from the recipient's own rows the way the donor's are.
    published, donated = adopt_donor_numbers(
        published,
        adoptions=adoptions,
        slug_of=slug_of,
        flows=flows,
        stated=comparable,
    )
    for name, count in donated.items():
        stats[f"{prefix}_donor_adoptions_{name}"] = count
    # Last of the passes, and it has to be: it fills a context *nobody*
    # characterises, so every pass that could still publish a row -- the queues'
    # rulings, the moves, the printings -- has to have run first, or a
    # context that is only empty because a curator has not answered yet would
    # be answered here by accident.  `stated` is the deciding implementations
    # alone, which is what the flowchart means by "nobody spoke".
    # The size-window convention first, inside each compartment: a particle
    # window nobody characterises takes its nearest broader window's stated
    # number, so that the compartment convention below then spreads that
    # number the way it spreads a stated one (`lcia.size_class_carry`, #196).
    published, windowed = carry_across_size_classes(
        published,
        rules=size_rules,
        slug_of=slug_of,
        flows=flows,
        stated=comparable,
    )
    stats[f"{prefix}_size_class_carry_rules"] = len(size_rules.rules)
    for name, count in windowed.items():
        if name.startswith("rule_"):
            continue
        stats[f"{prefix}_size_class_carry_{name}"] = count
    logger.info(
        "size_class_carry_by_rule",
        method=method.slug,
        **{name.removeprefix("rule_"): count for name, count in windowed.items() if name.startswith("rule_")},
    )
    published, carried = carry_across_contexts(
        published,
        rules=carry_rules,
        slug_of=slug_of,
        flows=flows,
        stated=comparable,
    )
    stats[f"{prefix}_context_carry_rules"] = len(carry_rules.rules)
    for name, count in carried.items():
        # The per-rule counts are logged rather than recorded: eighteen rules
        # times two methods is a baseline nobody could read, and the totals are
        # what a build is compared on.
        if name.startswith("rule_"):
            continue
        stats[f"{prefix}_context_carry_{name}"] = count
    logger.info(
        "context_carry_by_rule",
        method=method.slug,
        **{name.removeprefix("rule_"): count for name, count in carried.items() if name.startswith("rule_")},
    )
    # The census of what is still blank, taken after every pass: a context our
    # taxonomy has, the same substance characterised next door, and nobody
    # stating anything here.  It decides nothing -- the convention that fills a
    # blank is a data file people write from these numbers
    # (`plans/lcia-consensus-decisions.md` §4.1) -- and it is counted here so
    # the number of blanks in each context is a number of the run.
    blank_pairs, blank_contexts = context_census(
        method=method.slug,
        published=[
            PublishedFactor(
                elementary_flow_uuid=row.elementary_flow_uuid,
                category_slug=slug_of(row),
                geography=row.factor.geography or "",
                amount=row.factor.amount,
                derivation=row.derivation,
            )
            for row in published
        ],
        stated={key for rows in comparable.values() for key in rows},
        flows=flows,
    )
    stats[f"{prefix}_blank_contexts"] = len(blank_contexts)
    stats[f"{prefix}_blanks"] = sum(row.blanks for row in blank_contexts)
    # And the blanks beside a *substance*: an ion with no factor where its
    # element has one in the same context (#197).  The context census cannot
    # see these -- the ion is another substance -- and the convention never
    # crosses one; a signed adoption does, or nothing.  Counted so the next
    # method shaped like Stepwise shows the gap before a user's validation does.
    blank_ions = identity_census(
        method=method.slug,
        published=[
            PublishedFactor(
                elementary_flow_uuid=row.elementary_flow_uuid,
                category_slug=slug_of(row),
                geography=row.factor.geography or "",
                amount=row.factor.amount,
                derivation=row.derivation,
            )
            for row in published
        ],
        stated={key for rows in comparable.values() for key in rows},
        flows=flows,
        relatives=substance_relatives(db_path) if relatives is None else relatives,
    )
    stats[f"{prefix}_identity_blank_substances"] = len(blank_ions)
    stats[f"{prefix}_identity_blanks"] = sum(row.blanks for row in blank_ions)
    factors.update(_by_category(method, published, implementation=method.consensus))
    for derivation in Derivation:
        stats[f"{prefix}_consensus_{derivation}"] = sum(
            1 for row in published if row.derivation == derivation
        )
    stats[f"{prefix}_consensus_factors_published"] = len(published)
    # The evidence, and what it reached.  Counted apart from the queue below,
    # because a row of the file that matched no substance and a substance whose
    # numbers have moved back into agreement both leave the queue shorter without
    # saying so: `underlying_model_evidence` is what was read and
    # `underlying_model_contradicted` is what still holds against this build.
    stats[f"{prefix}_underlying_model_evidence"] = len(evidence)
    # The rows the two publications do not state one quantity for, which are
    # measured and asked nothing about: a ratio between them is about the two
    # models rather than about the substance
    # (`contradictions.comparable_categories`).  Counted rather than left to be
    # inferred from the difference, because a file that stopped loading and a
    # category nobody compares look the same from the queue.
    comparable_slugs = comparable_categories(method.slug)
    stats[f"{prefix}_underlying_model_not_comparable"] = sum(
        1 for row in evidence if row.category_slug not in comparable_slugs
    )
    stats[f"{prefix}_underlying_model_contradicted"] = len(contradicted)
    stats[f"{prefix}_underlying_model_substances"] = len(
        {key[0] for key in contradicted}
    )
    stats[f"{prefix}_factor_adoptions"] = len(adoptions)
    stats[f"{prefix}_factor_rulings"] = len(rulings)
    stats[f"{prefix}_factor_rulings_applied"] = len(applied)
    # A ruling that settled nothing is the loud half of the contract: the file is
    # answering a question this build no longer asks, or asks with different
    # numbers.  `derive` logs which; this counts them so a run says so.
    stats[f"{prefix}_factor_rulings_absent"] = len(rulings) - len(applied)
    stats[f"{prefix}_factor_rulings_factors"] = sum(applied.values())
    queues = queue_items(
        questions,
        method=method.slug,
        flows=flows,
        category_names={
            definition.slug: definition.name for definition in method.categories
        },
    )
    for queue, items in queues.items():
        # Answered and still asking, counted apart, and counted the same way on
        # both scales.  A queue whose numbers never move as rulings arrive would
        # say the work was not getting done -- and a total that still said "142
        # contested factors" when 34 of them were settled would say it twice.
        open_items = [item for item in items if item.severity == Severity.BLOCKING]
        ruled_items = [item for item in items if item.severity == Severity.INFO]
        stats[f"{prefix}_consensus_{queue}_items"] = len(items)
        stats[f"{prefix}_consensus_{queue}_items_open"] = len(open_items)
        stats[f"{prefix}_consensus_{queue}_items_ruled"] = len(ruled_items)
        stats[f"{prefix}_consensus_{queue}_factors"] = _factor_count(items)
        stats[f"{prefix}_consensus_{queue}_factors_open"] = _factor_count(open_items)
        stats[f"{prefix}_consensus_{queue}_factors_ruled"] = _factor_count(ruled_items)

    # §5's two reports.  The comparison is over *every* transcription, which is
    # a wider set than the consensus implementation was derived from: comparing
    # is what a non-deciding transcription is here for, and a report that left it
    # out would leave the reader to do by hand what #157 did by hand.  Keyed the
    # same way, so a row of the report and a row of the implementation still
    # cannot disagree about what was compared.
    compared = {
        method.implementation(slug): _comparable(
            method, rows, method.implementation(slug)
        )
        for slug, rows in transcribed.items()
    }
    differences, difference_counts = compare(
        method=method.slug,
        stated=compared,
        consensus={
            _comparable_key(method, row): row.derivation for row in published
        },
    )
    gaps, coverage_counts = coverage(
        method=method.slug,
        characterised=_characterised(method, transcribed, flows=flows),
        flows=flows,
        own_flows=_own_flows(db_path, method=method, lists=lists, reached=reached),
    )
    # One coverage row per context with blanks, on the consensus implementation:
    # the other rows say where a *transcription* skipped a flow its list has,
    # and these say where *nobody* characterised a flow ours has.
    gaps.extend(
        CoverageGap(
            method=method.slug,
            implemented_by=method.consensus.name,
            dimension=BLANK_DIMENSION,
            value=row.recipient,
            flows=row.blanks,
        )
        for row in blank_contexts
    )
    # And one per substance blank beside its relative, under the same
    # implementation: `Zinc(2+) — ion of Zinc`, and how many pairs are blank.
    gaps.extend(
        CoverageGap(
            method=method.slug,
            implemented_by=method.consensus.name,
            dimension=IDENTITY_BLANK_DIMENSION,
            value=row.value,
            flows=row.blanks,
        )
        for row in blank_ions
    )
    del blank_pairs  # the per-pair table is the tool's; the run keeps the totals
    logger.info(
        "characterised_method",
        method=method.slug,
        version=method.version,
        implementations=len(method.implementations),
        deciding=[row.slug for row in method.deciding],
        categories_filled=len(factors),
        factors=sum(len(rows) for rows in factors.values()),
    )
    return MethodOutcome(
        factors=factors,
        findings=findings,
        differences=differences,
        coverage=gaps,
        queues=queues,
        difference_counts=difference_counts,
        coverage_counts=coverage_counts,
    )


def characterise(
    db_path: Path | None = None,
    *,
    source_lists: Mapping[str, SourceList] | None = None,
    factor_rulings: dict[tuple[str, str, str], FactorRuling] | None = None,
    factor_adoptions: dict[str, FactorAdoption] | None = None,
    misattributed_factors: dict[tuple[str, str], MisattributedFactor] | None = None,
    rounded_printings: dict[tuple[str, str], RoundedPrinting] | None = None,
    context_carry_rules: ContextCarryRules | None = None,
    size_class_carry_rules: SizeClassCarryRules | None = None,
    underlying_model_factors: Iterable[ModelEvidence] | None = None,
) -> dict[str, Any]:
    """Publish every registered method into the LCIA tables, and say what happened.

    *db_path* defaults at call time rather than at import, so a caller in a test or
    a second data directory gets the database it configured (rule 20).
    *source_lists* is the registered lists by default, keyed on the list key an
    implementation's method file names, and is a parameter so a test can hand over
    a manifest of its own rather than the data directory's.  *factor_rulings*
    likewise: `data/lcia-factor-rulings.json` unless a caller hands over its own,
    so a test's rulings and the curated ones cannot be confused for each other.
    *underlying_model_factors* is the same arrangement for
    `data/lcia-underlying-model-factors.json`, which says what USEtox 2.1 states
    about the substances EF 3.1's toxicity categories are derived from.  A curated
    override is used for every method characterised, which is a test affordance
    and not a shape the curated files have: those state the one method they are
    about and are read for it alone.
    """
    from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH

    db_path = Path(db_path or CONSENSUS_DB_FILEPATH)
    if not db_path.exists():
        raise FileNotFoundError(
            f"No build to characterise at {db_path}. `characterise` reads what "
            f"`build` wrote; run the build first."
        )
    _check_every_list_is_read()

    run = CharacterisationRun(
        run_id=uuid4().hex,
        started_at=datetime.now(timezone.utc).isoformat(),
        build_run_id=build_run_id(db_path),
    )
    logger.info(
        "characterise_started",
        run_id=run.run_id,
        build_run_id=run.build_run_id,
        db_path=str(db_path),
        methods=[method.slug for method in lcia_methods()],
    )

    stats: dict[str, Any] = {}
    # Read once for the whole run rather than once per method: both describe the
    # flow tables, which no method touches.  A ruling is keyed on a substance and
    # it is `flows` that says which substance a flow is an occurrence of, so it is
    # read before anything derives.
    flows = flow_descriptions(db_path)
    substances = substances_by_registry_number(db_path)
    # Which substances are an ion of which element, for the identity census;
    # a property of the build like the two above.
    relatives = substance_relatives(db_path)
    # And the context convention, which names no method: read once, checked
    # once, handed to every method.
    carry_rules = (
        load_context_carry_rules() if context_carry_rules is None else context_carry_rules
    )
    size_rules = (
        load_size_class_carry_rules()
        if size_class_carry_rules is None
        else size_class_carry_rules
    )

    factors: dict[str, list[MatchedFactor]] = {}
    findings: list[Finding] = []
    differences: list[Difference] = []
    gaps: list[CoverageGap] = []
    difference_counts: Counter[str] = Counter()
    coverage_counts: Counter[str] = Counter()
    # Accumulated across the methods and written once.  `replace_queue_items`
    # rewrites a queue whole, so writing per method would leave the last method's
    # questions and nobody else's.
    queues: dict[ReviewQueue, list[ReviewQueueItem]] = defaultdict(list)

    for method in lcia_methods():
        outcome = _characterise_method(
            method,
            db_path=db_path,
            flows=flows,
            substances=substances,
            stats=stats,
            source_lists=source_lists,
            factor_rulings=factor_rulings,
            factor_adoptions=factor_adoptions,
            misattributed_factors=misattributed_factors,
            rounded_printings=rounded_printings,
            context_carry_rules=carry_rules,
            size_class_carry_rules=size_rules,
            underlying_model_factors=underlying_model_factors,
            relatives=relatives,
        )
        factors.update(outcome.factors)
        findings.extend(outcome.findings)
        differences.extend(outcome.differences)
        gaps.extend(outcome.coverage)
        difference_counts.update(outcome.difference_counts)
        coverage_counts.update(outcome.coverage_counts)
        for queue, items in outcome.queues.items():
            queues[queue].extend(items)

    categories: dict[str, ImpactCategory] = {
        str(category.id): category for category in published_impact_categories()
    }
    # The run's own totals, over every method: unprefixed, because they are about
    # the artifacts this run wrote rather than about anybody's method.
    stats["methods"] = len(lcia_methods())
    stats["impact_categories"] = len(categories)
    stats["impact_categories_filled"] = len(factors)
    stats["factors_published"] = sum(len(rows) for rows in factors.values())
    stats["findings"] = len(findings)
    stats["consensus_categories_awaiting_factors"] = sum(
        1
        for method in lcia_methods()
        for category in consensus_categories_for(method.slug)
        if str(category.id) not in factors
    )
    for key, count in difference_counts.items():
        stats[f"difference_{_stat_key(key)}"] = count
    for key, count in coverage_counts.items():
        stats[f"coverage_{_stat_key(key)}"] = count

    for queue, items in queues.items():
        replace_queue_items(db_path, queue=queue, items=items)

    write_characterisation(
        db_path,
        run=run,
        categories=categories,
        factors=factors,
        findings=findings,
        differences=differences,
        coverage=gaps,
        stats=stats,
    )
    # The published files, from the same records the tables were written from
    # and in the same call, so the two cannot disagree about what this run found.
    factors_path, differences_path = artifact_paths(db_path)
    write_factors(
        build_factors_document(categories=categories, factors=factors, stats=stats),
        factors_path,
    )
    write_differences(
        build_differences_document(
            differences=differences, coverage=gaps, stats=stats
        ),
        differences_path,
    )

    finish_run(
        db_path,
        run_id=run.run_id,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info("characterise_finished", run_id=run.run_id, **stats)
    return stats


def _check_every_list_is_read() -> None:
    """That no registered list ships factors nothing reads.

    The link between a method file and a source manifest runs one way -- the
    method names the list -- so a manifest that declares an `lcia` block and is
    named by no method would be fetched, would sit in the data directory, and
    would be published by nobody.

    :raises ValueError: naming the list, because the fix is a row in a method
        file and the message should say which file is waiting for one.
    """
    read = {
        implementation.factors.source_list
        for method in lcia_methods()
        for implementation in method.implementations
        if implementation.factors.source_list
    }
    unread = sorted(
        source.key for source in lcia_source_lists() if source.key not in read
    )
    if unread:
        raise ValueError(
            f"{', '.join(unread)} declare an lcia block and no method file reads "
            f"them, so their factors would be fetched and published by nobody."
        )
