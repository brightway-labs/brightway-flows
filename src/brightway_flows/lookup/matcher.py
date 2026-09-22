"""Asking the merge's own matching what it would do, without letting it do it.

`merge/matching.py` reads like a stage of a build, but the two functions that
decide where a row goes do not behave like one.  `resolve_flow_object` -- which
substance is this? -- reads frozen indexes and touches the accumulator for
exactly one purpose, appending an `UnmatchedRow` to say why it gave up.
`_select_elementary_flow` -- which flow of that substance? -- reads nothing but
its arguments and returns the winner, the reason and the scoring trace.

Neither creates a flow, mints an id or writes a row.  Everything that does is
called by `merge_source_list` *after* those two have answered.

So this is not a second implementation of matching, and must not become one.  It
calls the same two functions, and the guarantee it can then make is strong: **an
answer from here is the answer the build would have given, or this is broken.**

Three things it does not do:

* **Never invent a flow.**  The merge's answer to "no consensus flow exists for
  this" is to create one.  The answer here is `matched=False` with the reason.
  Those are different questions and the second one is the caller's to decide.
* **Never return a bare `None`.**  An unmatched row is a question with evidence
  attached -- `_probe_flow_object_matches` already assembles exactly that
  evidence for the merge report, and it is returned here for the same reason: a
  wrong match is silent, an unmatched row is reviewable.
* **Always say which build answered.**  A match is a statement about one build
  and expires with it.

See ``plans/lookup-api.md`` §2, §3.2 and §3.7.
"""

from __future__ import annotations

import sqlite3

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import orjson
import structlog

from brightway_flows.domain.context_registry import context_display_parts
from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.labels import flow_label_value
from brightway_flows.domain.land_flow_classes import published_land_classes
from brightway_flows.domain.materials import flow_object_basis_for
from brightway_flows.domain.particulate_size import (
    size_class as particulate_size_class,
)
from brightway_flows.domain.flow_object import stable_flow_object_id
from brightway_flows.flow_layers.land_hierarchy import land_object_id
from brightway_flows.filesystem import CONSENSUS_DB_FILEPATH
from brightway_flows.domain.particulate_size import UnreadParticleRowError
from brightway_flows.merge.matching import (
    _probe_flow_object_matches,
    _record_unmatched_row,
    _select_elementary_flow,
    resolve_flow_object,
)
from brightway_flows.merge.report import UnmatchedReason
from brightway_flows.sources import SourceList
from brightway_flows.merge.state import (
    CandidateResolution,
    MergeAccumulator,
    MergeIndexes,
)
from brightway_flows.lookup.curated_names import (
    land_class_for_name,
    material_for_name,
)
from brightway_flows.lookup.index import (
    BuildStamp,
    load_lookup_index,
    lookup_source_list,
)
from brightway_flows.lookup.recorded import (
    RecordedDecision,
    RecordedDecisions,
    split_list_key,
)
from brightway_flows.lookup.query import (
    CONTEXT_AMBIGUOUS,
    FlowQuery,
    OfflineEnrichment,
    PreparedQuery,
    ResolvedContext,
    prepare_query,
    query_flow,
    resolve_context,
    source_row,
    units_index,
)

logger = structlog.get_logger(__name__)

#: What answered: a decision this build already recorded about this exact row,
#: one recorded about a row spelled identically, or the algorithm re-deriving it.
#:
#: On every answer, because a caller weighing one should know which it is: the
#: first is the row itself, the second is a row somebody decided was the same,
#: and the third is this project's rules run again.
TIER_RECORDED = "recorded"
TIER_RECORDED_BY_NAME = "recorded-by-name"
TIER_ALGORITHM = "algorithm"


@dataclass(frozen=True)
class CandidateFlowObject:
    """One substance a row could have been, with why it was reachable.

    What a curator needs to pick between twelve waters: which substance, what it
    is called, and whether the row reached it by its registry number or only by
    a name.  The same evidence `enrich_unmatched_rows` assembles for the review
    queue.
    """

    flow_object_id: str
    name: str
    #: `cas`, `ec`, `label` -- which lookups reached this object.
    basis_hits: tuple[str, ...] = ()


@dataclass(frozen=True)
class FlowMatch:
    """Where one row goes, or why it does not go anywhere.

    The vocabulary is the merge report's, deliberately: a curator reading a
    lookup result and a curator reading `merge_outcomes` should be reading the
    same words for the same things.
    """

    matched: bool
    #: The consensus flow's published identifier.
    elementary_flow_id: str = ""
    flow_object_id: str = ""
    pref_label: str = ""
    context_iri: str = ""
    context_display: tuple[str, ...] = ()
    unit: str = ""
    is_deprecated: bool = False
    replaced_by: str = ""
    #: `cas`, `cas+qualifier`, `cas+label`, `cas+designation`, `ec`, `label`,
    #: `simapro-name-pattern`, `historical-name`, `material`, `land_class`,
    #: `particulate_size_class` -- how the substance was identified.
    basis: str = ""
    basis_value: str = ""
    #: `best-score`, `exact-context-iri-match`, or an `UnmatchedReason`.
    selector_reason: str = ""
    #: The scoring trace, verbatim -- the same dict `merge_outcomes.detail_json`
    #: carries, so a surprising answer can be read rather than guessed at.
    selector_details: Mapping[str, Any] = field(default_factory=dict)
    tier: str = TIER_ALGORITHM
    #: What the context resolution made of the caller's compartment, and which
    #: of its four steps said so.
    resolved_context_iri: str = ""
    context_resolution: str = ""
    #: The name matching was given, where preparation rewrote the caller's --
    #: `Wood, unspecified, standing` for a row sent as `Wood, unspecified,
    #: standing/m3`.  Empty where the caller's name was already the one a build
    #: would have matched, which is almost every row.
    prepared_name: str = ""
    #: Which SimaPro habits preparation undid, in the order it undid them:
    #: `unit-suffix`, `geography`, `lineage-fix`.
    preparation_steps: tuple[str, ...] = ()
    #: The unit matching was given where the lineage's corrections rebased the
    #: caller's -- `MJ` for a row sent as `Uranium, 451 GJ per kg` in kg -- and
    #: how many of it one of the caller's unit is.  Empty and None for every
    #: other row, which is almost all of them.
    prepared_unit: str = ""
    unit_conversion_factor: float | None = None
    #: Set when the row matched too much: every substance it could have been.
    candidates: tuple[CandidateFlowObject, ...] = ()
    #: Which build answered.  A match expires with it.
    build: BuildStamp | None = None

    @property
    def identifier(self) -> str:
        """The published identifier, under the name the export uses for it."""
        return self.elementary_flow_id


class FlowMatcher:
    """One object, built once, asked many times.

    Measured against the 21 August 2026 build of ``8be43a3`` -- 7,984 flow
    objects, 96,277 active flows:

    * **Building it: 2.7 s.**  1.4 s reads the columns and builds the indexes;
      the other 1.3 s is ``check_digits.setup()`` parsing the PubChem cache, so
      that a caller's mistyped registry number can be corrected the way a build
      corrects one.  A data directory without that cache simply corrects fewer
      numbers.
    * **Asking it: 0.45 ms a row** -- 2,400 rows in 1.07 s, enrichment included.

    So the load is the cost and the question is not, and a caller with a whole
    list builds one matcher and calls :meth:`match_many` once.  (``plans/
    lookup-api.md`` §2 says half a second to build and half a second a row; the
    first is optimistic by five and the second pessimistic by a thousand.)

    It holds two `MergeIndexes` records sharing every dict underneath, one with
    `simapro_origin` set and one without, because the flag varies per query and
    the record is frozen.  Two records, one set of indexes.
    """

    def __init__(
        self,
        *,
        indexes: MergeIndexes,
        elementary_by_object: dict[str, list[ElementaryFlow]],
        build: BuildStamp,
        db_path: Path,
        enrichment: OfflineEnrichment,
        recorded_by_name: bool = False,
    ) -> None:
        self._plain = indexes
        self._simapro = replace(indexes, source=lookup_source_list(simapro_origin=True))
        self._elementary_by_object = elementary_by_object
        self._build = build
        self._db_path = db_path
        self._enrichment = enrichment
        self._units = units_index()
        self._recorded = RecordedDecisions(db_path)
        self._recorded_by_name = recorded_by_name

    @classmethod
    def from_results(
        cls,
        db_path: Path | None = None,
        *,
        chebi: bool = False,
        recorded_by_name: bool = False,
    ) -> FlowMatcher:
        """Read a build and prepare to answer questions about it.

        *db_path* defaults to the configured data directory's database, resolved
        at call time so a test can point the constant elsewhere.

        *chebi* adds `chebi_altlabels` to the enrichment, which is where a great
        many alternative names come from and so the step most likely to move the
        match rate.  It is off by default because it wants a 49 MB index
        resident; a caller matching a whole list can pay that once.

        *recorded_by_name* lets a row be answered by a decision recorded about a
        *different* row spelled identically, in the place the caller's
        compartment resolves to (#357).  Off by default: it is the one place
        this design could produce a confident wrong answer, from a name two
        lists spell the same and mean differently.  See
        :mod:`brightway_flows.lookup.recorded` for how large that risk
        measures, and note that a key two rows disagree about declines rather
        than being arbitrated -- so it cannot be quietly wrong about a
        disagreement this build contains.  The one caller it answers anyway is
        the one whose ``source_label`` names a merged list that ruled, because
        naming the lineage supplies the fact the tie is missing (#359); the
        answer then says which list ruled and what the others said.

        :raises UnusableBuildError: if the build is half-written, is a slice
            somebody chose for a smoke run, or cannot say which build it is.
        """
        resolved = CONSENSUS_DB_FILEPATH if db_path is None else db_path
        indexes, elementary_by_object, build = load_lookup_index(resolved)
        return cls(
            indexes=indexes,
            elementary_by_object=elementary_by_object,
            build=build,
            db_path=resolved,
            enrichment=OfflineEnrichment.build(chebi=chebi),
            recorded_by_name=recorded_by_name,
        )

    @property
    def build(self) -> BuildStamp:
        """Which build this matcher answers for."""
        return self._build

    @property
    def recorded_decisions(self) -> RecordedDecisions:
        """The recorded-decision indexes tier one answers from.

        Exposed so a caller reporting on the same build -- the assessment
        measures -- reads the indexes this matcher has already built rather
        than paying for a second copy.
        """
        return self._recorded

    def match(self, query: FlowQuery) -> FlowMatch:
        """Where this row would go, on the build this matcher was built from.

        One row through :meth:`match_many`, which is where the work is: a caller
        with a whole list should hand it the whole list, because the enrichment
        chain runs once per call rather than once per row.
        """
        return self.match_many([query])[0]

    def match_many(self, queries: Iterable[FlowQuery]) -> list[FlowMatch]:
        """Every row, with one index build and one run of the chain.

        Which is the whole reason it exists.  The load is the cost and the
        question is not, so a caller with 2,679 rows pays the first once -- and
        the enrichment too: every step the lookup runs declares
        ``answers_per_flow``, which *means* it reads the flow it is asked about
        and nothing else about the flows it was shown, so running it over a list
        gives each row the answer it would have got alone.  Two thousand rows in
        one call rather than two thousand calls is the difference between six log
        lines and twelve thousand.
        """
        # The two SimaPro splits first, before anything reads the name -- tier
        # one included, because a decision this build recorded is recorded
        # against the name the build matched, which is the prepared one.
        prepared = [prepare_query(query) for query in queries]
        rows = [item.query for item in prepared]
        # Tier one's second half is keyed on the *resolved* context (#357): a
        # recorded decision about `["resources", "in air"]` and a caller
        # writing `["Raw materials", "in air"]` are about the same place, and
        # only the resolution can say so.  Resolved here only when that half is
        # on: the identifier half never reads a compartment, and the batch a
        # merged list replays by identifier alone should not pay a resolution
        # per row for the early return below to discard.
        contexts = (
            [resolve_context(query) for query in rows]
            if self._recorded_by_name
            else None
        )
        # Then tier one, for the whole batch: a list this build has already
        # merged is answered from what it decided, with no enrichment, because
        # there is nothing left to derive.
        recorded = [
            self._recorded_answer(query, context=context)
            for query, context in zip(rows, contexts or (None,) * len(rows))
        ]
        if all(answer is not None for answer in recorded):
            return [
                _reporting_preparation(answer, item)
                for item, answer in zip(prepared, recorded)
                if answer is not None
            ]
        if contexts is None:
            contexts = [resolve_context(query) for query in rows]

        flows = [query_flow(query, source=self._list_for(query)) for query in rows]
        if flows:
            # Chain order is preserved and every step is per-flow, so this is the
            # same enrichment each row would get on its own.  `source_list` is
            # read by `resolve_flow_layers`, which none of these steps reaches,
            # and by `default_context_mapping`, which reads `flow.source` per
            # flow -- set on each flow above, and so correct per row even where
            # two rows name different lists.
            self._enrichment.run_all(flows, source=self._plain.source)
        return [
            _reporting_preparation(
                answer
                if answer is not None
                else self._match_one(item.query, flow=flow, context=context),
                item,
            )
            for item, flow, context, answer in zip(prepared, flows, contexts, recorded)
        ]

    # ── tier one ─────────────────────────────────────────────────────────────

    def _recorded_answer(
        self, query: FlowQuery, *, context: ResolvedContext | None
    ) -> FlowMatch | None:
        """What this build already decided about this row, or None to re-derive.

        Two tiers, most specific first, and they are not the same kind of claim.
        An identifier in a list this build merged names *the row itself*, so the
        answer is exact and needs no flag. A name recorded in the same resolved
        place as some other row's is a judgement that the two rows are the same
        row, which is the caller's to opt into.

        A name two lists ruled on differently in the same place declines --
        returns None here, handing the row to the algorithm as a dropped key
        always did -- unless the caller's ``source_label`` names a merged list
        that ruled, in which case that list's own decision answers and the
        answer says so (#359).
        """
        if query.list_key.strip() and query.identifier.strip():
            decisions = self._recorded.for_identifier(query.list_key, query.identifier)
            if len(decisions) == 1:
                return self._from_recorded(query, decisions[0], tier=TIER_RECORDED)
            if len(decisions) > 1:
                # One vendor row mapped onto two consensus flows -- 47 of the
                # 110,993 links. Returning either would be choosing between two
                # recorded decisions by row order.
                return self._recorded_is_ambiguous(query, decisions)

        if self._recorded_by_name and context is not None:
            answer = self._recorded.for_name_in_context(
                query.name,
                context_iri=context.context_iri,
                dimension=context.dimension,
                source_label=query.source_label,
            )
            if answer is not None:
                extra: dict[str, Any] = {}
                if answer.arbitrated_by:
                    extra["arbitrated_by_source_label"] = answer.arbitrated_by
                if answer.alternatives:
                    extra["recorded_alternatives"] = list(answer.alternatives)
                return self._from_recorded(
                    query, answer.decision, tier=TIER_RECORDED_BY_NAME, extra=extra
                )
        return None

    def _from_recorded(
        self,
        query: FlowQuery,
        decision: RecordedDecision,
        *,
        tier: str,
        extra: Mapping[str, Any] | None = None,
    ) -> FlowMatch:
        """A recorded decision as an answer, read back off the flow it names.

        The same read the algorithm's answer goes through, so a caller cannot
        tell the two apart by the shape of what they get -- only by `tier`,
        which is the field that exists to tell them.  *extra* is what a
        by-name answer owes on top: which list's ruling was preferred, and
        what the other lists said (#359).
        """
        published = self._published_flow(decision.elementary_flow_id)
        flow = published.get("flow") or {}
        context_iri = str(flow.get("context_iri") or "")
        return FlowMatch(
            matched=bool(published),
            elementary_flow_id=decision.elementary_flow_id if published else "",
            flow_object_id=str(flow.get("flow_object_id") or ""),
            pref_label=str(published.get("pref_label") or ""),
            context_iri=context_iri,
            context_display=tuple(context_display_parts(flow.get("context"))),
            unit=str(flow.get("unit") or ""),
            is_deprecated=bool(published.get("is_deprecated")),
            replaced_by=str(published.get("replaced_by") or ""),
            basis=(
                "recorded-source-reference"
                if tier == TIER_RECORDED
                else "recorded-name-and-context"
            ),
            basis_value=f"{decision.list_key} {decision.source_flow_uuid}".strip(),
            selector_reason="recorded-decision",
            selector_details={
                "recorded_list": decision.list_key,
                "recorded_source_uuid": decision.source_flow_uuid,
                "recorded_source_name": decision.source_flow_name,
                **dict(extra or {}),
            },
            tier=tier,
            resolved_context_iri=context_iri,
            context_resolution="recorded",
            build=self._build,
        )

    def _recorded_is_ambiguous(
        self, query: FlowQuery, decisions: tuple[RecordedDecision, ...]
    ) -> FlowMatch:
        """One vendor row, two consensus flows, and no way to choose between two
        decisions somebody made deliberately."""
        list_name, list_version = split_list_key(query.list_key)
        return FlowMatch(
            matched=False,
            basis="recorded-source-reference",
            basis_value=f"{query.list_key} {query.identifier}",
            selector_reason="multiple-recorded-decisions",
            selector_details={
                "recorded_list": query.list_key,
                "recorded_list_name": list_name,
                "recorded_list_version": list_version,
                "recorded_flow_ids": [d.elementary_flow_id for d in decisions],
            },
            tier=TIER_RECORDED,
            context_resolution="recorded",
            build=self._build,
        )

    def _list_for(self, query: FlowQuery) -> SourceList:
        """Which synthetic list this row is treated as coming from.

        A caller who names a list gets that list's `source` string on the flow,
        which is what `default_context_mapping` keys on -- so a row that says
        "treat my compartments as ecoinvent-3.12's" gets ecoinvent's own rules
        applied by the same transformer a build would apply them with.
        """
        indexes = self._simapro if query.simapro_origin else self._plain
        if not query.source_label.strip():
            return indexes.source
        return replace(indexes.source, declared_source_label=query.source_label.strip())

    def _match_one(
        self, query: FlowQuery, *, flow: Any, context: ResolvedContext
    ) -> FlowMatch:
        indexes = self._simapro if query.simapro_origin else self._plain
        filled, curated_from = self._with_curated_names(query, context, indexes=indexes)
        answer = self._match_filled(
            filled, flow=flow, context=context, indexes=indexes, curated_from=curated_from
        )
        if curated_from and not answer.matched:
            # A curated fill may only add a way for the row to match, never
            # take one away.  A filled query is answered on the fill alone --
            # the material and land branches of `_resolve` are exclusive, as
            # the merge's are -- so where the fill places nothing, the row is
            # asked again as if the table had no entry, which is the answer the
            # caller would have gotten before the tables could be reached by
            # name.  The filled answer is kept when both fail: it is the one
            # that says which table was consulted.
            plain = self._match_filled(
                query, flow=flow, context=context, indexes=indexes, curated_from=""
            )
            if plain.matched:
                return plain
        return answer

    def _match_filled(
        self,
        query: FlowQuery,
        *,
        flow: Any,
        context: ResolvedContext,
        indexes: MergeIndexes,
        curated_from: str,
    ) -> FlowMatch:
        row = source_row(query, flow, context=context, units_index=self._units)

        # Constructed per query and discarded, holding the shared candidate map.
        # `add_flow` is never called and no creation function is reachable from
        # this package, so the only thing it collects is the `UnmatchedRow` that
        # says why `resolve_flow_object` gave up.
        accumulator = MergeAccumulator(elementary_by_object=self._elementary_by_object)

        resolution = self._resolve(query, row=row, indexes=indexes, accumulator=accumulator)
        if resolution is None:
            return self._unmatched(query, row=row, indexes=indexes, accumulator=accumulator, context=context)

        # A withdrawal whose material names the body it was drawn from moves into
        # that body where the source stated none -- the same refinement
        # `merge/rows.py` applies, and for the same reason: which kind of water
        # this is is not known until the substance is.
        refined_iri, refined_body = _water_body(resolution, context.context_iri)
        if refined_body:
            context = replace(
                context,
                context_iri=refined_iri,
                strings=tuple(indexes.consensus_context_strings.get(refined_iri, ())),
            )
            row = replace(row, context_iri=refined_iri, context_normalized=context.strings)

        candidates = self._elementary_by_object.get(resolution.flow_object_id, [])
        # **The caller's own words are not passed to the selector.**
        #
        # `merge/rows.py` falls back to the raw compartment where the consensus
        # renderings are empty, and for a build that is safe: its raw strings are
        # a *mapped* list's, so the first two are a dimension and a medium the
        # vocabulary knows.  A caller's are their own -- `["over there"]` -- and
        # the selector's first act is to reject every candidate whose dimension
        # is not the row's first string.  Passing them through does not "score on
        # the raw strings", as `plans/lookup-api.md` §3.5 supposes; it filters
        # every candidate out and reports `no-candidates-same-dimension-media`,
        # which reads as "no flow of this substance is in your compartment" when
        # what happened is "your compartment could not be read".
        #
        # So an unresolved context is passed as no context, which is what it is.
        # The selector then does what §3.5 wants of it: no exact-IRI
        # short-circuit, no IRI term, no dimension filter, and a score on the
        # unit alone -- which settles a substance with one flow and honestly ties
        # a substance with several.  It cannot cross a compartment boundary the
        # caller named, because the caller named none this build can read.
        #
        # A `dimension-only` context is the one case between the two, and the
        # selector already reads it correctly without being told: it takes the
        # dimension from the first string and the medium from the second, and
        # applies the medium filter only where there *is* a second.  So a
        # one-string context filters on the dimension alone -- `Raw /
        # (unspecified)` keeps every resource flow of the substance and rejects
        # its emissions -- and carries no IRI to short-circuit on, because there
        # is no context to name.
        selector_context = list(context.strings)
        selected, reason, details = _select_elementary_flow(
            candidates,
            source_context=selector_context,
            source_unit=row.unit,
            source_context_iri=context.context_iri,
        )
        details["flow_object_candidate_count"] = 1
        details["source_context_original"] = list(row.context)
        details["source_context_normalized"] = list(context.strings)
        details["source_context_used_for_matching"] = selector_context
        details["source_context_matching_basis"] = (
            "dimension-only"
            if context.strings and not context.context_iri
            else "normalized"
            if context.strings
            else "none-resolved"
        )
        details["context_resolution"] = context.resolution
        if curated_from:
            # The caller stated no material or land class and a curated table's
            # rows spell this name, so the table's answer was used (#358).
            # Recorded on matched and unmatched answers alike, so a surprising
            # placement -- or a missing one -- can be traced to the table
            # rather than guessed at.
            details["curated_name_table"] = curated_from

        if selected is None:
            # The substance is known and no flow of it fits this row's context.
            # A build would either add a flow or report the row; this reports it,
            # because creating one is the caller's decision and not a lookup's.
            return FlowMatch(
                matched=False,
                flow_object_id=resolution.flow_object_id,
                pref_label=indexes.flow_object_label_by_id.get(resolution.flow_object_id, ""),
                basis=resolution.basis,
                basis_value=resolution.basis_value,
                selector_reason=str(reason),
                selector_details=details,
                resolved_context_iri=context.context_iri,
                context_resolution=context.resolution,
                build=self._build,
                candidates=(
                    CandidateFlowObject(
                        flow_object_id=resolution.flow_object_id,
                        name=indexes.flow_object_label_by_id.get(
                            resolution.flow_object_id, ""
                        ),
                        basis_hits=(resolution.basis,) if resolution.basis else (),
                    ),
                ),
            )

        return self._matched(
            selected,
            resolution=resolution,
            reason=reason,
            details=details,
            context=context,
            indexes=indexes,
        )


    # ── the substance ────────────────────────────────────────────────────────

    def _with_curated_names(
        self, query: FlowQuery, context: ResolvedContext, *, indexes: MergeIndexes
    ) -> tuple[FlowQuery, str]:
        """*query* with the curated tables consulted under its prepared name (#358).

        The two per-flow tables -- which kind of water, which land class -- are
        keyed on the vendor's uuid, which a query does not have, but their rows
        record the vendor's spelling and :mod:`brightway_flows.lookup.
        curated_names` makes that reachable.  Consulted here, inside the
        library, for the reason the issue gives: every caller doing the join
        separately is how one table gets read three different ways, and a
        caller keying on the raw name misses the entry `simapro_origin` would
        have stripped their name to.

        An explicit value from the caller wins untouched -- a caller who says
        `material="lake_water"` knows something the table does not -- and a
        name the tables disagree about at every rung the compartment reaches is
        left empty, which declines the way the uuid-keyed read raises.

        A value whose flow object this build does not hold is not filled in.
        A caller who *states* such a value is asking about a concept this
        build was not made with, and deserves the unmatched answer that says
        so; a table entry is this module's own addition, and like preparation
        it may only add a way for the row to match, never take one away.

        Returns the query and which table answered, ``""`` for the ordinary
        row that is in neither.
        """
        if query.material.strip() or query.land_class.strip() or query.size_class.strip():
            return query, ""
        if material := material_for_name(query.name, context):
            if material_object_id_or_empty(material) in indexes.flow_objects_by_id:
                return replace(query, material=material), "water-flow-materials"
        if land_class := land_class_for_name(query.name, context):
            if land_object_id_or_empty(land_class) in indexes.flow_objects_by_id:
                return replace(query, land_class=land_class), "land-flow-classes"
        return query, ""

    def _resolve(
        self,
        query: FlowQuery,
        *,
        row: Any,
        indexes: MergeIndexes,
        accumulator: MergeAccumulator,
    ) -> CandidateResolution | None:
        """Which substance this row is.

        A caller's stated material or land class is taken first, because that is
        where the merge takes its own: both are exclusive branches ahead of the
        CAS lookup, and they have to be.  Every kind of water shares 7732-18-5,
        so once the materials have their own objects a CAS lookup returns twelve
        candidates and narrows to none.

        The merge reads those two facts out of curated tables keyed on `(source,
        uuid)`, and a query has no uuid, so the caller states them instead.  The
        *derivation* is shared -- `land_object_id` and `flow_object_basis_for`
        are the same functions the merge mints its ids with -- so the two cannot
        drift into naming two objects for one concept; only the two-line branch
        is written twice, and it is written here rather than reached through the
        merge because reaching it would mean giving `SourceRow` a field the merge
        has no use for.
        """
        if query.land_class.strip():
            target = land_object_id_or_empty(query.land_class.strip())
            if target and target in indexes.flow_objects_by_id:
                return CandidateResolution(
                    flow_object_id=target, basis="land_class", basis_value=query.land_class.strip()
                )
            return None

        if query.material.strip():
            target = material_object_id_or_empty(query.material.strip())
            if target and target in indexes.flow_objects_by_id:
                return CandidateResolution(
                    flow_object_id=target,
                    basis="material",
                    basis_value=query.material.strip(),
                    material=query.material.strip(),
                )
            return None

        if query.size_class.strip():
            # The third of the same shape, and the one with no fallback at all.
            # A water row that states no material still has a CAS to be found
            # by; an airborne-particle row has nothing but its name, and the
            # name is what put BAFU's coarse fraction on `Particles (PM10)`.
            size = particulate_size_class(query.size_class.strip())
            target = (
                stable_flow_object_id("fo", size.flow_object_basis) if size else ""
            )
            if target and target in indexes.flow_objects_by_id:
                return CandidateResolution(
                    flow_object_id=target,
                    basis="particulate_size_class",
                    basis_value=query.size_class.strip(),
                )
            return None

        try:
            return resolve_flow_object(row=row, indexes=indexes, accumulator=accumulator)
        except UnreadParticleRowError as error:
            # The merge stops on a particle row nobody has read; a query about
            # one is declined with the same message, because a question is
            # not a build and must not crash on the row it is asking about.
            # Recorded as unmatched so the caller sees why (#196).
            _record_unmatched_row(
                row=row,
                accumulator=accumulator,
                reason=UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE,
                basis="unread-particle-row",
                basis_value=str(error),
            )
            return None

    # ── the answers ──────────────────────────────────────────────────────────

    def _matched(
        self,
        selected: ElementaryFlow,
        *,
        resolution: CandidateResolution,
        reason: str,
        details: dict[str, Any],
        context: ResolvedContext,
        indexes: MergeIndexes,
    ) -> FlowMatch:
        """The answer, with the winning flow read back in full.

        The candidate records the selector scored are partial by construction --
        four fields off a column projection -- so what the caller is handed comes
        from `flow_json` for this one row.  One row, not 96,277.
        """
        published = self._published_flow(selected.elementary_flow_id)
        return FlowMatch(
            matched=True,
            elementary_flow_id=selected.elementary_flow_id,
            flow_object_id=resolution.flow_object_id,
            pref_label=published.get("pref_label", "")
            or indexes.flow_object_label_by_id.get(resolution.flow_object_id, ""),
            context_iri=selected.context_iri,
            context_display=tuple(context_display_parts(selected.context)),
            unit=selected.unit or "",
            is_deprecated=bool(published.get("is_deprecated")),
            replaced_by=str(published.get("replaced_by") or ""),
            basis=resolution.basis,
            basis_value=resolution.basis_value,
            selector_reason=str(reason),
            selector_details=details,
            resolved_context_iri=context.context_iri,
            context_resolution=context.resolution,
            build=self._build,
        )

    def _unmatched(
        self,
        query: FlowQuery,
        *,
        row: Any,
        indexes: MergeIndexes,
        accumulator: MergeAccumulator,
        context: ResolvedContext,
    ) -> FlowMatch:
        """No substance, or too many -- with the evidence either way.

        A row that matched *too much* is the one a curator can act on: twelve
        substances share 7732-18-5, and being told which twelve, what each is
        called and whether the row reached it by number or by name is what
        picking one takes.
        """
        reason = (
            str(accumulator.unmatched[0].reason)
            if accumulator.unmatched
            else str(UnmatchedReason.NO_FLOW_OBJECT_CANDIDATE)
        )
        if context.resolution == CONTEXT_AMBIGUOUS:
            # The compartment's contexts are told apart by the flow's name and
            # this name matches no rule, so the row was never placed and the
            # reason it did not match is that, rather than anything about its
            # substance.
            reason = f"{reason}; {CONTEXT_AMBIGUOUS}-context"
        probe = _probe_flow_object_matches(
            source_labels=list(row.labels),
            source_cas=row.cas,
            source_ec=row.ec,
            cas_index=indexes.cas_index,
            ec_index=indexes.ec_index,
            label_index=indexes.label_index,
            flow_object_label_by_id=indexes.flow_object_label_by_id,
        )
        stated = (
            query.material.strip()
            or query.land_class.strip()
            or query.size_class.strip()
        )
        if stated:
            # A stated material, land class or size window that names no object
            # in this build is a concept the taxonomy knows and the list has not
            # been built with, which is a different question from "which of
            # twelve".
            probe = dict(probe, stated_concept=stated)
        return FlowMatch(
            matched=False,
            selector_reason=reason,
            selector_details=probe,
            resolved_context_iri=context.context_iri,
            context_resolution=context.resolution,
            build=self._build,
            candidates=tuple(
                CandidateFlowObject(
                    flow_object_id=str(item.get("flow_object_id") or ""),
                    name=str(item.get("name") or ""),
                    basis_hits=tuple(item.get("basis_hits") or ()),
                )
                for item in probe.get("candidate_flow_objects", [])
            ),
        )

    def _published_flow(self, elementary_flow_id: str) -> dict[str, Any]:
        """The winning flow's published columns, in one read.

        `mode=ro`, like the load: this is the second and last time the lookup
        opens the database, and it opens it the same way.
        """
        connection = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT pref_label_value, is_deprecated, replaced_by_uuid, flow_json "
                "FROM elementary_flows WHERE uuid = ?",
                (elementary_flow_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return {}
        pref_label, is_deprecated, replaced_by, flow_json = row
        published: dict[str, Any] = {
            "pref_label": str(pref_label or ""),
            "is_deprecated": bool(is_deprecated),
            "replaced_by": str(replaced_by or ""),
        }
        if flow_json:
            payload = orjson.loads(flow_json)
            if isinstance(payload, dict):
                published["flow"] = payload
                if not published["pref_label"]:
                    published["pref_label"] = flow_label_value(payload)
        return published


def _reporting_preparation(answer: FlowMatch, item: PreparedQuery) -> FlowMatch:
    """*answer*, saying what preparation did to the name that earned it.

    Applied to every answer in one place rather than inside each tier, because
    every tier reads the prepared name and so every tier owes the caller the
    same sentence about it.  A row nothing was taken out of is returned
    untouched, which is almost all of them.
    """
    if not item.preparation.steps:
        return answer
    conversion = item.unit_conversion or {}
    return replace(
        answer,
        prepared_name=item.preparation.name,
        preparation_steps=item.preparation.steps,
        prepared_unit=str(conversion.get("target_unit") or ""),
        unit_conversion_factor=(
            float(conversion["factor"]) if conversion.get("factor") is not None else None
        ),
    )


def material_object_id_or_empty(material: str) -> str:
    """The flow object id a material concept mints, or "" for one nothing maps.

    The same two-line derivation the merge mints material objects with
    (`flow_object_basis_for` then `stable_flow_object_id`), wrapped for the
    same reason `land_object_id_or_empty` is: the lookup asks the question in
    two places -- filling a curated name and resolving a stated material --
    and two spellings of the derivation is how the two drift.
    """
    basis = flow_object_basis_for(material)
    return stable_flow_object_id("fo", basis) if basis else ""


def land_object_id_or_empty(land_class: str) -> str:
    """The flow object id a land-use key mints, or "" for a key nothing reaches.

    Wrapped because `land_object_id` takes the `LandUse` record and a caller
    states the *key*, which is what the taxonomy publishes and therefore the only
    spelling an outside caller could be expected to have.  Looked up in
    `published_land_classes` -- the 339 classes four source lists actually ship
    -- rather than composed from the string, so a key nothing reaches comes back
    empty here instead of minting an id for an object that does not exist.
    """
    land_use = published_land_classes().get(land_class)
    return land_object_id(land_use) if land_use else ""


def _water_body(resolution: CandidateResolution, context_iri: str) -> tuple[str, str]:
    """The context a withdrawal's material moves it into, or the one it had.

    `merge.contexts.water_body_from_material` is the merge's spelling of this
    and is what should be called; it is reached through a module the lookup is
    allowed to import, so it is.
    """
    from brightway_flows.merge.contexts import water_body_from_material

    return water_body_from_material(
        material=resolution.material, source_context_iri=context_iri
    )
