"""What a caller asks, and turning it into the row the merge would have matched.

A source row does not reach matching as the vendor shipped it.  It goes through
the transform chain first, and matching then reads names the vendor never wrote:
the shipped name lifted into the label fields, the CAS check-digit-corrected, the
unit resolved to its notation.  A caller's raw row has none of that, so the same
steps run here -- the same steps, from `DEFAULT_TRANSFORMERS`, over the batch.

Two things a caller's row has that a build's does not, and one it lacks:

* It states whether the list is SimaPro-shaped, which a build reads off the
  registered `SourceList`.  See :func:`index.lookup_source_list`.
* It may state its own compartment in its own words, which no rule is written
  under.  :func:`resolve_context` is the four-step ladder that answers anyway,
  and says which step did.
* It has no uuid, so the two curated tables keyed on one -- which kind of water
  this is, which land class -- cannot answer directly.  §6.1 of the plan.  Both
  tables also record the vendor's spelling, and
  :mod:`brightway_flows.lookup.curated_names` reaches the curation that way
  (#358); a caller who knows better may state the concept and win.

See ``plans/lookup-api.md`` §3.1, §3.5 and §3.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from collections.abc import Sequence
from typing import Any

import structlog

from brightway_flows.context_mapping import (
    AmbiguousSourceContextError,
    consensus_context_strings,
    context_iri_by_any_source_context,
    context_iri_by_consensus_strings,
    context_iri_by_source_context,
    context_iri_for_any_source_context,
    known_mapping_sources,
    normalize_context_key,
    normalize_mapping_text,
    simapro_context_rules,
    simapro_name_prefix_policy,
    simapro_name_prefix_rules,
    UNMATCHED_SELECT,
)
from brightway_flows.domain.flow import Flow, ProvidedValues
from brightway_flows.domain.units import build_units_index, resolve_unit_notation
from brightway_flows.merge.matching import _source_labels
from brightway_flows.merge.state import SourceRow
from brightway_flows.pipeline.engine import apply_transformers
from brightway_flows.filesystem import SIMAPRO_LINEAGE_FIXES_FILEPATH
from brightway_flows.manual_fixes import UNIT_CONVERSION_KEY, apply_manual_fixes
from brightway_flows.simapro_names import (
    LINEAGE_FIX_STEP,
    PreparedRow,
    prepare_row_for_matching,
)
from brightway_flows.sources import SourceList
from brightway_flows.transformers import DEFAULT_TRANSFORMERS

logger = structlog.get_logger(__name__)

#: The uuid a query row carries.  A build's rows are identified by the vendor's
#: own uuid, which is what the curated per-flow tables key on; a query has none,
#: and giving it a plausible-looking one would let it collide with a real row in
#: a table it has no business being found in.  One constant, obviously not a
#: uuid, and the two tables return `None` for it.
QUERY_UUID = "lookup-query"

#: The steps of `DEFAULT_TRANSFORMERS` that answer per flow, touch no network,
#: no cache and no external index, and write nothing -- in chain order.
#:
#: What they give a caller: the shipped name and synonyms lifted into the label
#: fields where `_source_labels` looks for them, the CAS and EC
#: check-digit-corrected, and the name stripped and case-normalised the way every
#: consensus label already is.  Sub-millisecond, deterministic, offline.
#:
#: Named rather than filtered on `answers_per_flow`, because that flag says a
#: step can be asked about one flow -- not that asking is free or safe.
#: `chebi_altlabels` answers per flow and wants a 49 MB index resident;
#: `commonchem_cas_review` and `enrich_references` answer per flow and reach the
#: network.  A lookup that silently makes HTTP calls is not the capability being
#: asked for.
#:
#: **Two of `plans/lookup-api.md` §3.6's six are not here**, and both for the
#: same underlying reason: they raise a *build's* error at somebody who asked a
#: question.  A build is entitled to stop, because a source list it cannot read
#: has not been added properly.  A caller has made a typo, or shipped a name
#: nobody has ruled on, and the answer they need is "this row could not be
#: placed, here is why" -- for that row, not for the two thousand rows batched
#: with it.
#:
#: `unit_normalization` also *writes*: a unit it cannot resolve is recorded in
#: `missing-units.json` in the data directory, which is the thing §3.7 exists to
#: prevent, and worse here than anywhere because it would leave a caller's typo
#: behind in a directory a build is reading.  Nothing is lost by dropping it:
#: :func:`source_row` calls `resolve_unit_notation`, the same function the
#: transformer calls, and gets the same notation and IRI for every unit the table
#: knows.
#:
#: `default_context_mapping` raises `AmbiguousSourceContextError` on a name its
#: compartment's rules do not recognise -- BAFU ships a row called `Uranium` in
#: `resources / land`, which is one -- and killed the whole batch when it did.
#: Nothing is lost there either, because it was answering a question
#: :func:`resolve_context` has already answered, and answering it *worse*: the
#: transformer writes `flow.context` and `flow.context_iri`, which nothing in the
#: lookup path reads, while `resolve_context` runs four steps rather than three
#: and reports which one it was.
OFFLINE_TRANSFORMER_NAMES: tuple[str, ...] = (
    "bootstrap_labels",
    "strip_names",
    "normalize_name_case",
    "check_digits",
)

#: Named so a test can say *why* each is absent rather than only that it is.
WITHHELD_TRANSFORMER_NAMES: tuple[str, ...] = (
    # Writes `missing-units.json` and raises on a unit it cannot resolve.
    "unit_normalization",
    # Raises on a name its compartment's rules do not recognise, and answers a
    # question :func:`resolve_context` has already answered better.
    "default_context_mapping",
    # Reach the network.
    "commonchem_cas_review",
    "enrich_references",
)

#: The one further step worth paying for, and only on request.  It is where a
#: great many alternative names come from, so it is the step most likely to move
#: the match rate -- and its cost is load time rather than the network, which is
#: payable once by a caller matching a whole list.  `FlowMatcher.from_results(
#: chebi=True)`.
CHEBI_TRANSFORMER_NAME = "chebi_altlabels"

#: How :attr:`FlowMatch.context_resolution` reports which step placed the row.
CONTEXT_GIVEN = "given"
CONTEXT_NAMED_LIST = "named-list"
#: The compartment is one SimaPro writes, and this list knows what it means.
CONTEXT_SIMAPRO = "simapro"
#: The compartment names a dimension and refuses to name a medium -- `Raw`,
#: `Raw / (unspecified)`.  There is no context to give, so the answer is the
#: dimension alone: enough to keep an emission out of the running, not enough to
#: pick between a substance's resource flows.  The substance does that.
CONTEXT_DIMENSION_ONLY = "dimension-only"
CONTEXT_ANY_LIST = "any-list"
CONTEXT_CONSENSUS_STRINGS = "consensus-strings"
CONTEXT_UNRESOLVED = "unresolved"
#: The compartment's contexts are told apart by the flow's name, and this name
#: matches no rule.  Distinct from `unresolved`, because it is not "nobody has
#: mapped this compartment" -- somebody has, and has ruled that the compartment
#: alone does not decide.
CONTEXT_AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FlowQuery:
    """One row of somebody's flow list, and everything they know about it.

    Only :attr:`name` is required.  Everything else narrows the answer, and the
    two that matter most are not obvious:

    :attr:`synonyms` -- matching looks a row up under *every* name it is known
    by, because a row is known by all of them at once and looking up one breaks
    the moment enrichment renames it.  A caller usually has more names than the
    name field carries, and every one of them is a chance to match.

    :attr:`simapro_origin` -- what entitles the name-pattern fallback to run.
    `Benzene, chloro-` finds chlorobenzene under it and nothing without it.
    """

    name: str
    #: The caller's own compartment strings, in their own words.
    context: Sequence[str] = ()
    cas: str = ""
    ec: str = ""
    unit: str = ""
    #: Every other name the caller knows this row by.
    synonyms: Sequence[str] = ()
    #: Whether this list's names were shaped by SimaPro.
    simapro_origin: bool = False
    #: An escape hatch: a consensus context IRI, which skips the resolution
    #: entirely.  For a caller who has already done the mapping.
    context_iri: str = ""
    #: "Treat my compartments as this list's."  A registered list's
    #: `source_label` -- `ecoinvent-3.12`, `EF 3.1`, `bafu-2026-v1`.
    source_label: str = ""
    #: Which kind of water this is, as a published material concept id.  There is
    #: no name-derived route to it -- deriving one is what the water taxonomy
    #: exists to avoid -- so a caller who knows has to say.  §6.1.
    material: str = ""
    #: Which land class this is, as a published land-use key.  Same argument.
    land_class: str = ""
    #: Which particle size window this is, as a published size-class id --
    #: `pm10`, `pm2_5_to_pm10`, `unsized`.  Same argument again, and it bites
    #: hardest here: an airborne-particle row carries no registry number at all,
    #: so without this the only route is the name, and the name is what #153 is
    #: about.  A caller sending `Particulates, < 10 um` and meaning PM10 says
    #: `size_class="pm10"`; one meaning the coarse fraction says
    #: `size_class="pm2_5_to_pm10"`, and the two stop being the same query.
    size_class: str = ""
    #: The row's identifier in the caller's own list, and which list that is.
    #: Tier one only; ignored by the algorithm.
    identifier: str = ""
    list_key: str = ""

    def labels(self) -> list[str]:
        """The name and the synonyms, non-empty, in preference order."""
        return [
            value.strip()
            for value in [self.name, *self.synonyms]
            if isinstance(value, str) and value.strip()
        ]


@dataclass(frozen=True)
class PreparedQuery:
    """A caller's row after the rewrites a build's row gets before matching.

    Two fields because the answer needs both: :attr:`query` is what every step
    after this one reads, and :attr:`preparation` is what to tell the caller
    about it -- a row whose name was rewritten got its answer under a spelling
    it did not send, and being told that is the difference between an answer and
    a coincidence.
    """

    query: FlowQuery
    preparation: PreparedRow
    #: What the lineage's corrections said about the row's unit, where they
    #: rebased it: the pair of units and how many of the new one the old one
    #: is, as `apply_manual_fixes` records it on a row.  None otherwise.
    unit_conversion: dict[str, Any] | None = None


def _apply_lineage_fixes(query: FlowQuery) -> tuple[FlowQuery, dict[str, Any] | None]:
    """*query* with the lineage's curated corrections applied, as a row's are.

    Through `apply_manual_fixes` and the same file `load_flows` applies to a
    SimaPro-shaped list, rather than a second reading of that file: a fix that
    corrects a merged row and not a queried one would make the lookup answer
    differently from the build it claims to reproduce.  The row is shaped the
    way the project's own adapters shape one -- registry numbers under
    `cas_numbers`, as a list -- because that is the spelling the file is
    written against.

    Returns the query unchanged where no fix names it, which is nearly every
    query.  A rename keeps the name the caller sent among the synonyms, as
    :func:`prepare_query` keeps the spelling a split rewrote.
    """
    row: dict[str, Any] = {
        "name": query.name.strip(),
        "cas_numbers": [query.cas.strip()] if query.cas.strip() else [],
        "unit": query.unit.strip(),
        "synonyms": [value for value in query.synonyms if isinstance(value, str)],
    }
    apply_manual_fixes([row], SIMAPRO_LINEAGE_FIXES_FILEPATH, label="lookup", quiet=True)

    name = str(row.get("name") or "").strip()
    numbers = row.get("cas_numbers") or []
    cas = str(numbers[0]).strip() if numbers else ""
    unit = str(row.get("unit") or "").strip()
    if (name, cas, unit) == (query.name.strip(), query.cas.strip(), query.unit.strip()):
        return query, None

    retained = [
        item.get("@value") if isinstance(item, dict) else item
        for item in row.get("altLabel") or []
    ]
    synonyms = [
        value
        for value in (query.name.strip(), *retained, *query.synonyms)
        if isinstance(value, str) and value.strip() and value.strip() != name
    ]
    conversion = row.get(UNIT_CONVERSION_KEY)
    return (
        replace(query, name=name, cas=cas, unit=unit, synonyms=tuple(dict.fromkeys(synonyms))),
        dict(conversion) if isinstance(conversion, dict) else None,
    )


def prepare_query(query: FlowQuery) -> PreparedQuery:
    """Take the unit and the place back out of the caller's name (#328).

    A build's row reaches matching having been through its list's adapter and
    its list's `load_flows`, and those are where the two SimaPro splits run --
    see :mod:`brightway_flows.simapro_names` for why each is where it is.  A
    query goes through neither, so it arrived spelled the way SimaPro spells it:
    `Wood, unspecified, standing/m3` in a build is `Wood, unspecified,
    standing`, which is a flow object this list holds, and as asked it is a
    string nothing in any list answers to.

    Gated on :attr:`FlowQuery.simapro_origin`, like every other rule in that
    module.  Off it, the two rewrites are not corrections but guesses: a name
    with a slash in it belongs to whoever wrote it.

    **The rewritten name goes in front of the caller's, not instead of it.**
    The spelling as sent stays among the synonyms, which is exactly what
    `_strip_unit_suffixes` does with the vendor's, and for the same reason:
    matching looks a row up under every name it is known by, and a name a rule
    rewrote is still one of them.  So preparation can only add a way for the row
    to match -- it cannot take one away.

    This runs before :func:`resolve_context` as well as before the enrichment,
    because the compartment rules of a list whose contexts are told apart by the
    flow's name read that name: ecoinvent's `natural resource / land` is
    occupation or transformation according to what the name starts with, and a
    name still carrying `/m2a` is not a name those rules were written against.
    """
    if not query.simapro_origin:
        return PreparedQuery(query, PreparedRow(name=query.name.strip()))

    preparation = prepare_row_for_matching(query.name, query.unit)
    prepared = query
    if preparation.steps:
        synonyms = [
            value
            for value in (preparation.shipped_name, *query.synonyms)
            if isinstance(value, str) and value.strip()
        ]
        prepared = replace(
            query,
            name=preparation.name,
            synonyms=tuple(dict.fromkeys(synonyms)),
        )

    # Third, and after both splits for the reason `load_flows` applies the
    # lineage's fixes before its unit split: the fixes are written against the
    # names a vendor ships, and a query arrives spelled that way.  The splits
    # leave a name alone where they have nothing to take out, which is every
    # name the fixes name, so the order only matters for a name that is both.
    corrected, conversion = _apply_lineage_fixes(prepared)
    if corrected is prepared:
        return PreparedQuery(prepared, preparation, unit_conversion=None)
    preparation = replace(
        preparation,
        name=corrected.name,
        shipped_name=preparation.shipped_name or query.name.strip(),
        steps=(*preparation.steps, LINEAGE_FIX_STEP),
    )
    return PreparedQuery(corrected, preparation, unit_conversion=conversion)


@dataclass(frozen=True)
class ResolvedContext:
    """Which consensus context a query's compartment means, and how we know."""

    context_iri: str
    resolution: str
    #: The consensus renderings of :attr:`context_iri`, which is what the
    #: selector scores a candidate against when there is one.
    strings: tuple[str, ...] = ()
    #: Set when the resolution is `ambiguous`: the prefixes the compartment's
    #: rules recognise, so a caller can see what their name would have to start
    #: with.
    detail: str = ""

    @property
    def dimension(self) -> str:
        """The dimension half of this compartment, or ``""`` where none resolved.

        A fully resolved context reads it from the vocabulary itself, so the
        answer is the registered dimension rather than the leading display
        string happening to equal it.  A `dimension-only` resolution *is* a
        dimension and stores it as the single rendering -- which is the whole
        of what a caller writing `Raw` with no medium has said.  The one IRI
        the registry does not know is a caller's own `context_iri` escape
        hatch, which falls back to the renderings the same way the selector
        does.
        """
        if self.context_iri:
            from brightway_flows.domain.context_registry import (
                UnknownContextIRIError,
                context_for_iri,
            )

            try:
                return str(context_for_iri(self.context_iri).dimension)
            except UnknownContextIRIError:
                pass
        return self.strings[0] if self.strings else ""


def resolve_context(query: FlowQuery) -> ResolvedContext:
    """Which consensus context this row is in, most specific rule first.

    Five steps, and the answer says which one gave it.

    1. The caller gave an IRI.  Use it.
    2. The caller named a list this project has mapped.  Use that list's own
       compartment rules -- the answer a build of that list would give.
    3. The compartment rules of every list at once, name rules included.  A
       compartment is often not a private invention: BAFU is a SimaPro-shaped
       list and has written down what 26 of them mean.
    4. **The compartments SimaPro writes that no list has spelled** --
       `Raw / in ground`, `Airborne emissions / low. pop.`, `Water / river`,
       `Final waste flows /`.  A list exported from SimaPro carries SimaPro's
       compartments whatever the flows in it came from, and most of those
       spellings are nobody's list.
    5. The consensus renderings, read backwards.  A caller who writes
       `Environmental / Air / Indoor` has written our own words for a context.

    **If none answers, the match still runs.**  `_select_elementary_flow`
    degrades honestly without an IRI: it loses the exact-IRI short-circuit and
    the one-point IRI term, and scores on the raw strings and the unit, which is
    what it did before context IRIs existed.  What it must not do is guess an
    IRI, because the IRI is what the dimension and media filter is enforced on
    and a wrong one crosses a boundary the merge refuses to cross.

    Step 4 is after step 3 and not before it, and this was measured rather than
    reasoned: putting it first cost 56 of BAFU's rows their match.  48 were land
    rows, because a flat compartment rule for `resources / land` says occupation
    and step 3 consults the *name* rules that tell occupation from
    transformation -- which is #52 for the third time.  The other 8 were
    `resources / unspecified`, where BAFU has ruled and a caller writing BAFU's
    own spelling should get BAFU's answer.  So a spelling a mapped list has
    already ruled on keeps that ruling, and this step is what covers the
    spellings no list has.

    Step 4 carries its own name rules for the land compartments it introduces,
    for the same reason step 3 needs them: `Raw / land` holds both occupations
    and transformations and the name is what tells them apart.

    One thing in step 4 does outrank step 3's compartment index: a ruling that a
    compartment names a dimension and refuses to name a medium.  A refusal
    cannot be overturned by a single list's rule for the same spelling, because
    such a rule is about that list's leftovers rather than about the
    compartment -- see :func:`_refused_medium`, which is where the argument and
    the one compartment it applies to are written down.

    Step 2 does **not** fall through when it raises.  A caller who says "these
    are ecoinvent's compartments" and writes a name in `natural resource / land`
    that starts with neither `Occupation,` nor `Transformation,` has asked a
    question their own list cannot answer, and a later step would answer it with
    ecoinvent's compartment rule -- which is #52, and says occupation for a
    flow that may be a transformation.
    """
    context = [str(value) for value in query.context if str(value).strip()]

    if query.context_iri.strip():
        return _resolved(query.context_iri.strip(), CONTEXT_GIVEN)

    if query.source_label.strip():
        label = query.source_label.strip()
        if normalize_mapping_text(label) not in known_mapping_sources():
            logger.warning("lookup_unknown_source_label", source_label=label)
        else:
            try:
                # The list's own three rules, through the record the merge uses,
                # so a caller naming a list gets that list's answer and not an
                # approximation of it.  The per-flow rule cannot fire -- it keys
                # on the vendor's uuid, which a query has none of -- and that is
                # the one difference from what a build would do.
                from brightway_flows.merge.contexts import ContextExpectations

                expectations = ContextExpectations(
                    _by_source_context=dict(context_iri_by_source_context(label)),
                    _source_label=label,
                )
                iri = expectations.resolve(QUERY_UUID, context, query.name)
            except AmbiguousSourceContextError as error:
                return ResolvedContext("", CONTEXT_AMBIGUOUS, detail=str(error))
            if iri:
                return _resolved(iri, CONTEXT_NAMED_LIST)

    key = normalize_context_key(context)
    try:
        iri = context_iri_for_any_source_context(context, query.name)
    except AmbiguousSourceContextError as error:
        return ResolvedContext("", CONTEXT_AMBIGUOUS, detail=str(error))
    if iri:
        if refusal := _refused_medium(key, iri):
            return refusal
        return _resolved(iri, CONTEXT_ANY_LIST)

    if prefixes := simapro_name_prefix_rules().get(key):
        name = normalize_mapping_text(query.name)
        for prefix, context_iri in prefixes:
            if name.startswith(prefix):
                return _resolved(context_iri, CONTEXT_SIMAPRO)
        if simapro_name_prefix_policy().get(key) != UNMATCHED_SELECT:
            return ResolvedContext(
                "",
                CONTEXT_AMBIGUOUS,
                detail=(
                    f"{list(key)} is a compartment whose context the flow's name "
                    f"has to decide, and this name starts with none of "
                    f"{[prefix for prefix, _ in prefixes]}."
                ),
            )

    if rule := simapro_context_rules().get(key):
        if rule.context_iri:
            return _resolved(rule.context_iri, CONTEXT_SIMAPRO)
        return ResolvedContext(
            "", CONTEXT_DIMENSION_ONLY, strings=(rule.dimension,), detail=rule.comment
        )

    if iri := context_iri_by_consensus_strings().get(normalize_context_key(context)):
        return _resolved(iri, CONTEXT_CONSENSUS_STRINGS)

    return ResolvedContext("", CONTEXT_UNRESOLVED)


def _refused_medium(key: Any, iri: str) -> ResolvedContext | None:
    """The ruling that *key* names a dimension and no medium, where there is one.

    Step 3 reads the compartment rules of every list with the list dropped, and
    a rule written for one list can be a statement about that list rather than
    about the compartment.  ``Raw / (unspecified)`` is the case: Stepwise 2006
    is a SimaPro method file, so it writes SimaPro's own compartments, and it
    files 134 rows there -- 41 of them land, 4 standing timber, 1 an uptake from
    air, and 87 ordinary resources in the ground.  Its curated rules take the
    exceptions out by name and by uuid and then say `ground` for what is left,
    which is right for Stepwise and is not what the compartment means.  Read
    with the list dropped it would tell every SimaPro caller that a compartment
    which refuses to name a medium means the ground, and the selector rejects
    every candidate whose medium is not the row's -- so a caller's standing wood
    would lose the flow it was asking about.

    BAFU's ``resources / unspecified`` is the second case and the same shape
    (#356): its rule says ``ground`` for what is left once its land rows are
    taken out by name, and BAFU itself files ``Carbon dioxide, in air`` there,
    which a curated target had to move off the ground (#135).

    So a ruling that a compartment names no medium outranks the compartment
    half of step 3.  Only that half: *iri* is compared against the compartment
    index, so a name rule that picked this row out of the compartment --
    `Occupation, arable` -- is a decision about the row and still stands, which
    is what keeps this from being #52 again.  A caller who names the list gets
    the list's own answer at step 2 and never reaches here.
    """
    rule = simapro_context_rules().get(key)
    if rule is None or rule.context_iri:
        return None
    if context_iri_by_any_source_context().get(key) != iri:
        return None
    return ResolvedContext(
        "", CONTEXT_DIMENSION_ONLY, strings=(rule.dimension,), detail=rule.comment
    )


def _resolved(context_iri: str, resolution: str) -> ResolvedContext:
    return ResolvedContext(
        context_iri=context_iri,
        resolution=resolution,
        strings=tuple(consensus_context_strings().get(context_iri, ())),
    )


def query_flow(query: FlowQuery, *, source: SourceList) -> Flow:
    """The `Flow` record a build would have had before enrichment.

    `provided` is filled as well as the fields themselves, and that is the part
    that matters: `bootstrap_labels` moves `name` into `prefLabel` and then
    *purges* `name` and `synonyms` without moving the synonyms anywhere, so a
    query whose synonyms were only in `synonyms` would lose them.  `_source_labels`
    reads `provided.labels()`, which is where they survive -- the same place a
    real source row keeps them, and for the same reason.
    """
    labels = query.labels()
    return Flow(
        uuid=QUERY_UUID,
        source=source.source_label,
        name=query.name.strip(),
        synonyms=[value for value in labels[1:]],
        cas_numbers=[query.cas.strip()] if query.cas.strip() else [],
        ec_numbers=[query.ec.strip()] if query.ec.strip() else [],
        unit=query.unit.strip() or None,
        provided=ProvidedValues(
            name=query.name.strip(),
            synonyms=[value for value in labels[1:]],
            context=[str(value) for value in query.context if str(value).strip()],
            cas_numbers=[query.cas.strip()] if query.cas.strip() else [],
            ec_numbers=[query.ec.strip()] if query.ec.strip() else [],
            unit=query.unit.strip() or None,
        ),
    )


@dataclass
class OfflineEnrichment:
    """The steps of the chain that can run on one row, offline, in order.

    Constructed once per matcher and reused: `setup()` reads curated files, and
    re-reading them per query is what made the transform chain slow (#296).
    """

    transformers: list[Any] = field(default_factory=list)

    @classmethod
    def build(cls, *, chebi: bool = False) -> OfflineEnrichment:
        wanted = OFFLINE_TRANSFORMER_NAMES + (
            (CHEBI_TRANSFORMER_NAME,) if chebi else ()
        )
        by_name = {cls_.name: cls_ for cls_ in DEFAULT_TRANSFORMERS}
        missing = [name for name in wanted if name not in by_name]
        if missing:
            # A step renamed or dropped from the chain, which is a real change
            # to what a build does to a row -- so it is a failure here rather
            # than a lookup that quietly enriches less than the build it claims
            # to reproduce.
            raise ValueError(
                f"`DEFAULT_TRANSFORMERS` has no step called {missing}. The lookup "
                "runs a named subset of the chain, so a step that is renamed or "
                "removed has to be renamed or removed here too -- see "
                "`.claude/skills/adding-a-transformer`."
            )
        transformers = []
        for name in wanted:
            transformer = by_name[name]()
            transformer.setup()
            transformers.append(transformer)
        return cls(transformers=transformers)

    def run_all(self, flows: list[Flow], *, source: SourceList) -> None:
        """Enrich *flows* in place, exactly as the chain's first steps would.

        Through `apply_transformers` rather than by calling each `transform`
        directly: applying a change is the engine's work -- it is what records
        `pipeline_sources` and refuses to write a finished flow -- and a second
        implementation of that loop would be a second set of rules about what a
        transformer is allowed to do.

        The whole batch in one call, which is only correct because every step
        here declares ``answers_per_flow``: that flag *means* the step reads the
        flow it is asked about and what `setup()` loaded, and nothing else about
        the flows it was shown.  So a row's answer does not depend on what it was
        batched with.  `tests/test_lookup_matcher.py` checks it, because the flag
        is a declaration and this relies on it being true.
        """
        apply_transformers(
            self.transformers,
            flows,
            source_list=source,
            timing_stage="lookup",
        )


def source_row(
    query: FlowQuery, flow: Flow, *, context: ResolvedContext, units_index: Any
) -> SourceRow:
    """The parsed row `resolve_flow_object` and the selector are given.

    Built the way `merge/rows.py` builds one, off the same fields: the labels
    through `_source_labels`, the compartment off `provided.context`, the unit
    through `resolve_unit_notation`.

    A unit the table does not know is left as the caller wrote it rather than
    raising.  A build raises there, because a source list whose units this
    project cannot read is a list that has not been added properly; a caller
    typing `kilogrammes` has made a typo, and the honest response is to score
    them without a unit signal and say the unit was not recognised.
    """
    unit = str(flow.unit or "").strip()
    unit_iri = flow.unit_iri or ""
    if unit and not unit_iri:
        if resolved := resolve_unit_notation(unit, units_index):
            unit, unit_iri = resolved[0], resolved[1] or ""
    from brightway_flows.domain.context_registry import context_display_parts
    from brightway_flows.domain.labels import flow_label_value

    return SourceRow(
        uuid=QUERY_UUID,
        name=flow_label_value(flow) or (flow.provided.name or ""),
        synonyms=list(flow.provided.synonyms),
        labels=_source_labels(flow),
        context=context_display_parts(flow.provided.context),
        context_iri=context.context_iri,
        context_normalized=context.strings,
        unit=unit,
        unit_iri=unit_iri,
        cas=str(flow.cas_numbers[0] if flow.cas_numbers else "").strip(),
        ec=str(flow.ec_numbers[0] if flow.ec_numbers else "").strip(),
    )


def units_index() -> dict[str, Any]:
    """The unit table, built once per matcher."""
    return build_units_index()
