"""The rules mapping a source list's own compartments onto consensus contexts.

There appeared to be two context-mapping systems, and the docs warned readers
not to confuse them.  They were one master file and a projection of it:
``context-manual-mapping.json`` held the rules, a CLI command grouped them by
``source`` into ``<list>-context-mapping.json``, and the *merge* read that
generated file back while the *transform* read the master (#11).

Three things followed.  The filename was derived twice, independently, so they
agreed for ecoinvent by coincidence, and a list whose projection was missing got
an **empty** index -- not an error, but "no row has a known context", so every
row failed into the report.  ``build`` never ran the export, so editing the
master changed the transform and left the merge on a stale projection with
nothing detecting the skew.  And ``SourceList.context_mapping_path`` read like
an input a curator authors when it was a build artifact.

So: one file, one loader, both stages.  This module is that loader.  It is not
under ``merge/`` for the same reason ``sources`` is not -- the transform reads
it too, and it is not a merge concept.

Rows are keyed by ``source``, which is the value a flow carries in
``Flow.source`` and therefore :attr:`SourceList.source_label` -- ``EF 3.1`` for
the base list, ``ecoinvent-3.12`` for a source list.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import orjson
import structlog
from brightway_flows.filesystem import PACKAGE_DATA_DIR

logger = structlog.get_logger(__name__)

#: The one file.  Package data, because these are decisions rather than derived
#: data, and hand-edited: a curator adds a row when a list's compartment has no
#: rule yet.
MANUAL_MAPPING_FILEPATH = (
    PACKAGE_DATA_DIR / "context-manual-mapping.json"
)

#: A normalised ``source_context``, e.g. ``("air", "indoor")``.
ContextKey = tuple[str, ...]


def normalize_mapping_text(value: str) -> str:
    """Casefold and collapse whitespace.

    The transform and the merge each had their own copy of this, spelled
    differently and agreeing by luck.  A single spelling is the point of the
    module: two normalisers that disagree place a row in one stage and not the
    other, which is the skew this file exists to make impossible.
    """
    return " ".join(str(value).lower().split())


def normalize_context_key(values: Any) -> ContextKey:
    """A ``source_context`` list as a lookup key; ``()`` if it is not one."""
    if not isinstance(values, list):
        return ()
    return tuple(
        normalize_mapping_text(value)
        for value in values
        if isinstance(value, str) and value.strip()
    )


@dataclass(frozen=True)
class CompartmentRule:
    """What one source list's compartment means, as a consensus context.

    The ordinary rule: a list ships a flow in a compartment, and the compartment
    says which context the flow belongs in.  The two rules below are what a
    compartment cannot say on its own -- :class:`FlowContextRule` for a body of
    water only the flow name identifies, :class:`NamePrefixRule` for a
    compartment holding two contexts the name selects between.
    """

    #: The list, normalised the way both stages normalise it.
    source: str
    #: The compartment, normalised, as the key both stages look it up by.
    source_context: ContextKey
    context_iri: str
    comment: str = ""


@lru_cache(maxsize=None)
def _load_rows() -> tuple[CompartmentRule, ...]:
    """Every usable ``default_context_mappings`` row.

    Cached: package data cannot change during a run, and both stages ask for it.

    A row naming no list, no compartment or no context is dropped, which is what
    the index built from these rows did before there was a record to drop it
    from.

    :raises FileNotFoundError: if the file is absent.  It is not optional --
        without it no list places any row -- so its absence is an error rather
        than an empty mapping, which would look like a clean run that matched
        nothing.
    """
    if not MANUAL_MAPPING_FILEPATH.exists():
        raise FileNotFoundError(
            f"Context mapping file not found at {MANUAL_MAPPING_FILEPATH}"
        )
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"{MANUAL_MAPPING_FILEPATH} must contain a JSON object")
    rows = payload.get("default_context_mappings")
    if not isinstance(rows, list):
        raise ValueError(
            f"{MANUAL_MAPPING_FILEPATH} must contain a 'default_context_mappings' list"
        )

    rules: list[CompartmentRule] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = row.get("source")
        context_iri = row.get("context_iri")
        if not isinstance(source, str) or not isinstance(context_iri, str):
            continue
        key = normalize_context_key(row.get("source_context"))
        if not key:
            continue
        rules.append(CompartmentRule(
            source=normalize_mapping_text(source),
            source_context=key,
            context_iri=context_iri.strip(),
            comment=str(row.get("comment") or ""),
        ))
    return tuple(rules)


@lru_cache(maxsize=None)
def context_mapping_index() -> dict[tuple[str, ContextKey], CompartmentRule]:
    """``(normalised source, normalised source_context) -> rule``, every list.

    What the transform wants: it walks flows from whichever list and reads
    ``flow.source`` per flow.
    """
    return {(rule.source, rule.source_context): rule for rule in _load_rows()}


@lru_cache(maxsize=None)
def context_iri_by_source_context(source_label: str) -> dict[ContextKey, str]:
    """``normalised source_context -> context_iri`` for one list.

    What the merge wants: it is placing rows from a single list, and it needs
    the IRI rather than the whole rule.

    Empty for a list with no rules, which is a list that has not been mapped
    yet.  The merge cannot place any of its rows, so
    :func:`sources.resolve_source_list` refuses such a list before a build
    starts rather than letting every row fail into the report.
    """
    wanted = normalize_mapping_text(source_label)
    return {
        key: rule.context_iri
        for (source, key), rule in context_mapping_index().items()
        if source == wanted
    }


def known_mapping_sources() -> frozenset[str]:
    """The ``source`` strings the file has rules for, normalised."""
    return frozenset(source for source, _ in context_mapping_index())


class ConflictingContextKeyError(ValueError):
    """One compartment, or one rendering, reaches two consensus contexts.

    The two loaders below drop the thing that made a context key unambiguous --
    which list wrote the rule, and which IRI the strings were rendered from --
    so both have to check that what is left still identifies one context.
    """


@lru_cache(maxsize=None)
def context_iri_by_any_source_context() -> dict[ContextKey, str]:
    """``normalised source_context -> context_iri``, over every list at once.

    :func:`context_iri_by_source_context` answers for a list this project has
    mapped.  This answers for one it has not.

    **Compartments only.**  Four of the 90 are compartments a list has already
    ruled cannot be decided by the compartment alone, and reading this index
    directly files a caller's land transformation as a land occupation with
    nothing said.  :func:`context_iri_for_any_source_context` is what callers
    want; this is the half of it that ignores the name.

    Somebody outside this project has a flow list of their own and one question
    about a row of it -- which consensus flow is this?  Their compartments are
    theirs, so no rule is written under their list's name, and the merge's own
    loader returns nothing for them.  But a compartment is often not a private
    invention.  A list built in SimaPro spells its compartments the way SimaPro
    spells them, and BAFU 2026-v1 -- which is SimaPro-shaped -- has already
    written down what 26 of those mean.

    So the rules are read with the list dropped.  On 21 August 2026 the file
    holds 190 rows from seven lists, naming 90 distinct compartments, and not
    one of them reaches two different context IRIs.

    **What that is not.**  It is not three vendors agreeing about a shared
    vocabulary.  Measured on the same file, the three vocabularies do not
    overlap *at all*: BAFU names 26 compartments, ecoinvent 27 across its five
    releases, EF 3.1 another 37, and no compartment string appears under two
    vendors.  The 25 compartments written more than once are all one ecoinvent
    release agreeing with the next.  So this is a union of three disjoint
    vocabularies rather than a consensus over one, and a caller is placed by it
    only when they happen to spell a compartment the way one of these three
    does.  Worth having -- BAFU's 26 are exactly the strings a SimaPro export
    carries -- but it is a lookup in three phrasebooks, not a translation.

    :raises ConflictingContextKeyError: if two lists give one compartment two
        different contexts.  There are none today, and given the disjointness
        above that is a weaker guarantee than it looks: the first two lists to
        share a compartment spelling are also the first that could disagree
        about it.  Raising is what makes that day a failure rather than a
        silent choice by iteration order.  A caller who names a *known* list is
        unharmed by such a row -- they still have that list's own rule -- so the
        conflict is refused here rather than in the file.
    """
    by_key: dict[ContextKey, str] = {}
    written_by: dict[ContextKey, str] = {}
    for (source, key), rule in context_mapping_index().items():
        if (existing := by_key.setdefault(key, rule.context_iri)) != rule.context_iri:
            raise ConflictingContextKeyError(
                f"{MANUAL_MAPPING_FILEPATH}: {list(key)} is mapped onto "
                f"{existing} by {written_by[key]} and onto {rule.context_iri} by "
                f"{source}. A compartment read without its list has to mean one "
                f"context; say which, or a list nobody has mapped cannot be "
                f"placed by this compartment at all."
            )
        written_by.setdefault(key, source)
    return by_key


@lru_cache(maxsize=None)
def _name_rules_for_any_source_context() -> tuple[
    dict[ContextKey, tuple[tuple[str, str], ...]], dict[ContextKey, str]
]:
    """The name-prefix rules with the list dropped, and each compartment's policy.

    Collapsed the same way and for the same reason as
    :func:`context_iri_by_any_source_context`, and it has to be, because those
    two indexes describe the same compartments.  Four of the 90 compartments in
    that index are ones a list has already ruled *cannot* be decided by the
    compartment alone -- ecoinvent's ``natural resource / land`` and BAFU's
    ``resources / land``, ``resources / in ground`` and
    ``resources / unspecified``.

    :raises ConflictingContextKeyError: if two lists give one compartment and
        prefix two contexts, or disagree about the compartment's ``unmatched``
        policy.  Neither happens today: every list spells the two prefixes
        ``occupation,`` and ``transformation,`` and maps them onto ``laus-occu``
        and ``laus-tran``.
    """
    by_prefix: dict[ContextKey, dict[str, str]] = {}
    written_by: dict[tuple[ContextKey, str], str] = {}
    policies: dict[ContextKey, str] = {}
    policy_written_by: dict[ContextKey, str] = {}
    for rule in _load_name_rows():
        if not rule.source_context or not rule.name_prefix or not rule.context_iri:
            continue
        prefixes = by_prefix.setdefault(rule.source_context, {})
        if (
            existing := prefixes.setdefault(rule.name_prefix, rule.context_iri)
        ) != rule.context_iri:
            raise ConflictingContextKeyError(
                f"{MANUAL_MAPPING_FILEPATH}: in {list(rule.source_context)}, names "
                f"starting {rule.name_prefix!r} are mapped onto {existing} by "
                f"{written_by[(rule.source_context, rule.name_prefix)]} and onto "
                f"{rule.context_iri} by {rule.source}. A prefix read without its "
                f"list has to mean one context."
            )
        written_by.setdefault((rule.source_context, rule.name_prefix), rule.source)
        if (
            policy := policies.setdefault(rule.source_context, rule.unmatched)
        ) != rule.unmatched:
            raise ConflictingContextKeyError(
                f"{MANUAL_MAPPING_FILEPATH}: {policy_written_by[rule.source_context]} "
                f"says {list(rule.source_context)} is {policy!r} and {rule.source} "
                f"says it is {rule.unmatched!r}. It describes the compartment, so "
                f"two lists that share one have to say the same thing about it."
            )
        policy_written_by.setdefault(rule.source_context, rule.source)
    return (
        {
            key: tuple(sorted(prefixes.items(), key=lambda item: -len(item[0])))
            for key, prefixes in by_prefix.items()
        },
        policies,
    )


def context_iri_for_any_source_context(
    source_context: Any, source_name: Any
) -> str | None:
    """Which consensus context a compartment means, for a list nobody has mapped.

    **Use this rather than :func:`context_iri_by_any_source_context` directly.**
    That index is compartments only, and a compartment is not always enough.

    ecoinvent puts land occupation and land transformation in one compartment
    and says which is which in the flow name -- ``Occupation, annual crop``
    against ``Transformation, from annual crop`` -- so its compartment rule has
    to choose one and be wrong about the other; it was wrong about 122
    transformation flows of every registered version (#52).  Read with the list
    dropped, ``natural resource / land`` answers ``laus-occu``, so an outside
    caller's transformation flow would be filed as an occupation with nothing
    said.  That is #52 again, one layer out, and this is what stops it.

    Two of the four are ``select`` compartments -- BAFU's ``resources / in
    ground`` and ``resources / unspecified`` hold land rows among ordinary
    resources -- so a name that matches no prefix there falls through to the
    compartment, which is what those rules mean.  The other two are
    ``partition``, and a name that matches nothing in them has no answer.

    Returns ``None`` when nothing places the compartment, which the caller
    reports as an unresolved context rather than guessing: the IRI is what the
    dimension and media filter is enforced on, and a wrong one crosses a
    boundary the merge refuses to cross.

    :raises AmbiguousSourceContextError: if the compartment's contexts are told
        apart by name, the compartment is a partition, and this name matches no
        prefix.  The same error, and the same reasoning, as
        :func:`name_prefix_context_iri` raises for a list we do know.
    """
    key = normalize_context_key(source_context if isinstance(source_context, list) else [])
    if not key:
        return None
    rules, policies = _name_rules_for_any_source_context()
    if prefixes := rules.get(key):
        name = normalize_mapping_text(source_name) if isinstance(source_name, str) else ""
        for prefix, context_iri in prefixes:
            if name.startswith(prefix):
                return context_iri
        if policies.get(key) != UNMATCHED_SELECT:
            raise AmbiguousSourceContextError(
                f"{MANUAL_MAPPING_FILEPATH}: {source_name!r} is in {list(key)}, a "
                f"compartment whose context its name has to decide, and it starts "
                f"with none of {[prefix for prefix, _ in prefixes]}. Nothing can "
                f"place this row from its compartment alone."
            )
    return context_iri_by_any_source_context().get(key)


#: The consensus contexts as the display strings a source row is matched on.
#: Generated from the context registry by ``brightway-flows`` and read here,
#: which is the one place that reads it: the merge scores a candidate on these
#: strings, and :func:`context_iri_by_consensus_strings` reads them backwards.
CONSENSUS_STRINGS_FILEPATH = PACKAGE_DATA_DIR / "consensus-flows-as-strings.json"


@lru_cache(maxsize=None)
def consensus_context_strings() -> dict[str, list[str]]:
    """``context_iri -> the display strings that context is printed as``.

    ``Context.to_list()``, frozen into a file so both sides of a comparison
    render a context the same way -- see :func:`domain.context_registry
    .context_display_parts` for what happens when they do not.

    Cached, and callers are given a fresh copy: package data cannot change
    during a run, and a shared mutable list of strings that four stages read is
    a hazard for the one that decides to sort it.

    :raises FileNotFoundError: if the file is absent.  It is a vocabulary, not
        an option: without it the merge scores every candidate against nothing
        and no row is placed by its context, which is not a clean run but a
        silent one.
    """
    if not CONSENSUS_STRINGS_FILEPATH.exists():
        raise FileNotFoundError(
            f"Consensus context strings not found at {CONSENSUS_STRINGS_FILEPATH}"
        )
    payload = orjson.loads(CONSENSUS_STRINGS_FILEPATH.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"{CONSENSUS_STRINGS_FILEPATH} must contain a JSON object")
    return {
        iri: [str(x) for x in value if isinstance(x, str) and x.strip()]
        for iri, value in payload.items()
        if isinstance(iri, str) and isinstance(value, list)
    }


@lru_cache(maxsize=None)
def context_iri_by_consensus_strings() -> dict[ContextKey, str]:
    """``normalised display strings -> context_iri``: the renderings, backwards.

    The last thing to try for a list nobody has mapped.  Its compartments are
    not in the rules file and are not any other list's either, but the caller
    may simply have written this project's own words: ``Environmental / Air /
    Indoor`` is a context of ours, spelled the way we spell it, and reading it
    back is exact rather than a guess.

    Sound only because the renderings identify the contexts they came from --
    all 60 of them are distinct on 21 August 2026 -- and that is a property of
    the vocabulary rather than a guarantee of the format, so it is checked.

    :raises ConflictingContextKeyError: if two contexts print the same.  That is
        #284 by another route: a rendering two contexts share cannot be read
        backwards, and picking one of them would file a caller's row in a
        compartment they did not name.
    """
    by_key: dict[ContextKey, str] = {}
    for iri, strings in consensus_context_strings().items():
        key = normalize_context_key(strings)
        if not key:
            continue
        if (existing := by_key.setdefault(key, iri)) != iri:
            raise ConflictingContextKeyError(
                f"{CONSENSUS_STRINGS_FILEPATH}: {existing} and {iri} are both "
                f"printed as {list(strings)}. A context has to be identified by "
                f"what it is called, or a row naming it cannot be placed."
            )
    return by_key


class FlowContextRuleError(ValueError):
    """A ``flow_specific_context_mappings`` row is unusable or out of date."""


#: What a per-flow row has to carry.  ``source_context`` is not decoration: it
#: is what makes a stale row fail loudly.  A rule that names a flow by uuid
#: keeps applying after the vendor moves that flow to another compartment, and
#: the reasoning that justified the rule was about the old one.
_FLOW_RULE_FIELDS = ("source", "source_uuid", "source_context", "context_iri", "comment")


@dataclass(frozen=True)
class FlowContextRule:
    """What one named flow's context is, whatever its compartment says.

    A field may be empty here and is checked in :func:`flow_context_rules`,
    which is where the list being asked about is known: a row for another list
    that cannot say which flow it is about must not stop this list from being
    placed.
    """

    source: str
    source_uuid: str
    #: The compartment the row was written about, checked against the one the
    #: vendor ships the flow in today; see :func:`flow_context_iri`.
    source_context: ContextKey
    context_iri: str
    comment: str


@lru_cache(maxsize=None)
def _load_flow_rows() -> tuple[FlowContextRule, ...]:
    """Every ``flow_specific_context_mappings`` row, unfiltered.

    Absent or empty is fine, unlike ``default_context_mappings``: a list places
    its rows from its compartments, and these are the exceptions to that.
    """
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    rows = payload.get("flow_specific_context_mappings")
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise ValueError(
            f"{MANUAL_MAPPING_FILEPATH}: 'flow_specific_context_mappings' must be a list"
        )
    return tuple(
        FlowContextRule(
            source=normalize_mapping_text(str(row.get("source") or "")),
            source_uuid=str(row.get("source_uuid") or "").strip(),
            source_context=normalize_context_key(row.get("source_context")),
            context_iri=str(row.get("context_iri") or "").strip(),
            comment=str(row.get("comment") or "").strip(),
        )
        for row in rows
        if isinstance(row, dict)
    )


@lru_cache(maxsize=None)
def flow_context_rules(source_label: str) -> dict[str, FlowContextRule]:
    """``source_uuid -> row`` for one list's per-flow context overrides.

    **Why this exists.**  A compartment is the wrong granularity for a water
    withdrawal.  EF 3.1 gives all six of its water bodies the single compartment
    ``Resources / Resources from water / Renewable material resources from
    water``, so lake water, sea water and ground water are told apart only by
    their names -- and a name is not something
    :func:`context_iri_by_source_context` can key on.  These rows are how the
    body reaches the context anyway, one flow at a time, each carrying the
    reasoning that put it there.

    **Precedence: a per-flow row wins over the compartment rule.**  It is the
    more specific statement, and being more specific is the only reason to write
    one.

    A row naming a uuid the list does not ship is inert rather than an error --
    the same argument ``ecoinvent-match-overrides.json`` makes, and for the same
    reason: one set of curated decisions covers every version of a list, and a
    flow that some versions dropped should not fail the ones that keep it.

    :raises FlowContextRuleError: if a row is missing a required field.  These
        are hand-written exceptions to an automatic rule; a row that cannot say
        which flow it is about, or why, is not a decision anyone can re-check.
    """
    wanted = normalize_mapping_text(source_label)
    rules: dict[str, FlowContextRule] = {}
    for rule in _load_flow_rows():
        if rule.source != wanted:
            continue
        missing = [field for field in _FLOW_RULE_FIELDS if not getattr(rule, field)]
        if missing:
            raise FlowContextRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: flow_specific_context_mappings row for "
                f"source={rule.source!r} uuid={rule.source_uuid!r} is "
                f"missing {missing}"
            )
        if rule.source_uuid in rules:
            # Last-wins would pick one of two curated statements about the same
            # flow by file order, which is how #31's survivor was chosen and
            # exactly the kind of silent arbitration this project is removing.
            raise FlowContextRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: flow_specific_context_mappings has two "
                f"rows for {source_label} {rule.source_uuid} -- "
                f"{rules[rule.source_uuid].context_iri} and {rule.context_iri}. "
                f"One flow, one rule."
            )
        rules[rule.source_uuid] = rule
    return rules


def flow_context_iri(source_label: str, source_uuid: str, raw_context: Any) -> str | None:
    """The per-flow context IRI for *source_uuid*, or None if no row names it.

    *raw_context* is the compartment the list actually ships the flow in --
    ``flow.provided.context``, the input snapshot, not ``flow.context``, which
    the context transform rewrites into a consensus dict.  It is checked against
    the row's ``source_context``, and a mismatch is raised rather than ignored:
    the rule outlived the flow it was written about, and applying it anyway
    would move a flow on reasoning that no longer describes it.  Quietly
    *skipping* it would be worse still -- the curated body would vanish from the
    output with nothing said.

    A *raw_context* that is not a non-empty list of strings returns None instead
    of raising.  That is not a vendor move, it is a caller holding a flow whose
    context has already been rewritten -- the transform is re-entrant and sees
    its own output -- and there is nothing to compare against.  Raising there
    conflates "the flow moved" with "you passed the wrong field", and the second
    one took a full pipeline run to surface because the bounded harness samples
    a prefix of the base list that contains none of these flows.

    :raises FlowContextRuleError: if the row's ``source_context`` is not the
        flow's current one.
    """
    rule = flow_context_rules(source_label).get(str(source_uuid).strip())
    if rule is None:
        return None
    actual = normalize_context_key(raw_context if isinstance(raw_context, list) else [])
    if not actual:
        return None
    if rule.source_context != actual:
        raise FlowContextRuleError(
            f"{MANUAL_MAPPING_FILEPATH}: flow_specific_context_mappings row for "
            f"{source_label} {source_uuid} states source_context "
            f"{list(rule.source_context)} but the flow is in {list(actual)}. The "
            f"vendor moved it; re-check the row's reasoning before updating the "
            f"context."
        )
    return rule.context_iri


class ContextNameRuleError(ValueError):
    """A ``name_prefix_context_mappings`` row is unusable."""


class AmbiguousSourceContextError(ValueError):
    """A flow sits in a compartment whose context only its name can decide, and
    no rule matches that name."""


#: What a name-prefix row has to carry.  The same fields a compartment rule
#: carries, plus the prefix that selects between them, and ``comment`` is
#: required for the same reason it is on a per-flow row: these are curated
#: statements, and one that cannot say why is not a decision anyone can
#: re-check.
_NAME_RULE_FIELDS = ("source", "source_context", "name_prefix", "context_iri", "comment")

#: What to do with a flow in a ruled compartment whose name matches no prefix.
#:
#: ``partition`` -- the rules cover the compartment, and a name none of them
#: catches is a curation question.  This is #52's case and stays the default:
#: every flow in ecoinvent's ``natural resource / land`` is a land flow, the
#: compartment rule can only be right about one of occupation and
#: transformation, so falling through to it would file the other silently.
#:
#: ``select`` -- the rules pick some flows *out* of a compartment the
#: compartment rule can still decide for the rest.  BAFU's
#: ``resources / unspecified`` holds 26 land rows and 16 ordinary resources, and
#: ``resources / in ground`` holds 3 land rows among 161; under ``partition``
#: every one of those 177 non-land rows would raise.  The compartment is mixed,
#: so the rules have to be an override rather than a partition.
#:
#: Per compartment rather than per row -- it describes the compartment's rules
#: as a set -- so :func:`name_prefix_context_rules` requires the rows of one
#: compartment to agree.
UNMATCHED_PARTITION = "partition"
UNMATCHED_SELECT = "select"
_UNMATCHED_POLICIES = (UNMATCHED_PARTITION, UNMATCHED_SELECT)


@dataclass(frozen=True)
class NamePrefixRule:
    """Which of a compartment's two contexts a flow's name selects.

    As with :class:`FlowContextRule`, a field may be empty here and is checked
    in :func:`name_prefix_context_rules`, for the same reason: an unusable row
    for one list must not stop another list from being placed.

    ``unmatched`` describes the *compartment* rather than this row; see
    :data:`UNMATCHED_PARTITION`.  It is carried on every row because that is
    where the file states it, and :func:`name_prefix_unmatched_policy` requires
    one compartment's rows to agree.
    """

    source: str
    source_context: ContextKey
    #: Normalised the same way the names are compared, so a trailing space in
    #: the file is not a rule that can never match.
    name_prefix: str
    context_iri: str
    comment: str
    unmatched: str


@lru_cache(maxsize=None)
def _load_name_rows() -> tuple[NamePrefixRule, ...]:
    """Every ``name_prefix_context_mappings`` row, unfiltered.

    Absent or empty is fine: most compartments say everything their flows need,
    and these are the compartments that do not.
    """
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    rows = payload.get("name_prefix_context_mappings")
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise ValueError(
            f"{MANUAL_MAPPING_FILEPATH}: 'name_prefix_context_mappings' must be a list"
        )
    return tuple(
        NamePrefixRule(
            source=normalize_mapping_text(str(row.get("source") or "")),
            source_context=normalize_context_key(row.get("source_context")),
            name_prefix=normalize_mapping_text(str(row.get("name_prefix") or "")),
            context_iri=str(row.get("context_iri") or "").strip(),
            comment=str(row.get("comment") or "").strip(),
            unmatched=str(row.get("unmatched") or UNMATCHED_PARTITION).strip(),
        )
        for row in rows
        if isinstance(row, dict)
    )


@lru_cache(maxsize=None)
def name_prefix_unmatched_policy(source_label: str) -> dict[ContextKey, str]:
    """``source_context -> what an unmatched name means`` for one list.

    Read from the same rows as :func:`name_prefix_context_rules`, and checked
    here rather than there because a compartment whose rows disagree about this
    has no answer: one row saying ``partition`` and another ``select`` would
    make the behaviour depend on file order.

    :raises ContextNameRuleError: on an unknown policy, or on two rows of one
        compartment that do not agree.
    """
    wanted = normalize_mapping_text(source_label)
    policies: dict[ContextKey, str] = {}
    for rule in _load_name_rows():
        if rule.source != wanted or not rule.source_context:
            continue
        if rule.unmatched not in _UNMATCHED_POLICIES:
            raise ContextNameRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: name_prefix_context_mappings row for "
                f"source={rule.source!r} prefix={rule.name_prefix!r} has "
                f"unmatched={rule.unmatched!r}; expected one of "
                f"{list(_UNMATCHED_POLICIES)}"
            )
        if policies.setdefault(rule.source_context, rule.unmatched) != rule.unmatched:
            raise ContextNameRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: name_prefix_context_mappings rows for "
                f"{source_label} {list(rule.source_context)} disagree about "
                f"`unmatched` ({policies[rule.source_context]!r} and "
                f"{rule.unmatched!r}). It describes the compartment, so every row "
                "of one compartment has to say the same thing."
            )
    return policies


@lru_cache(maxsize=None)
def name_prefix_context_rules(
    source_label: str,
) -> dict[ContextKey, tuple[tuple[str, str], ...]]:
    """``source_context -> ((name prefix, context IRI), ...)`` for one list.

    **Why this exists.**  ecoinvent puts land occupation and land transformation
    in one compartment, ``natural resource / land``, and says which is which in
    the flow name: ``Occupation, annual crop`` against ``Transformation, from
    annual crop``.  ``laus-occu`` and ``laus-tran`` are siblings in our
    vocabulary, not a general and a specific, so a compartment rule has to
    choose one and be wrong about the other -- it was wrong about the 122
    transformation flows of every registered version (#52).

    This is a middle granularity the other two rules do not cover.  A
    compartment rule cannot see the name; a per-flow rule sees one flow, and
    182 of them per version, restated for five versions, is a table nobody will
    keep true.  A prefix is what the vendor actually encodes.

    Prefixes are returned longest first, so where one is a prefix of another the
    more specific one is tested first rather than shadowed.

    :raises ContextNameRuleError: if a row is missing a field, or if two rows
        give the same compartment and prefix -- last-wins would pick between two
        curated statements by file order.
    """
    wanted = normalize_mapping_text(source_label)
    rules: dict[ContextKey, dict[str, str]] = {}
    for rule in _load_name_rows():
        if rule.source != wanted:
            continue
        missing = [field for field in _NAME_RULE_FIELDS if not getattr(rule, field)]
        if missing:
            raise ContextNameRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: name_prefix_context_mappings row for "
                f"source={rule.source!r} prefix={rule.name_prefix!r} is "
                f"missing {missing}"
            )
        by_prefix = rules.setdefault(rule.source_context, {})
        if rule.name_prefix in by_prefix:
            raise ContextNameRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: name_prefix_context_mappings has two rows "
                f"for {source_label} {list(rule.source_context)} {rule.name_prefix!r} "
                f"-- {by_prefix[rule.name_prefix]} and {rule.context_iri}. One prefix, "
                f"one rule."
            )
        by_prefix[rule.name_prefix] = rule.context_iri
    return {
        key: tuple(sorted(by_prefix.items(), key=lambda item: -len(item[0])))
        for key, by_prefix in rules.items()
    }


def name_prefix_context_iri(
    source_label: str, source_name: Any, raw_context: Any
) -> str | None:
    """The context IRI *source_name* selects within its compartment, or None.

    None means the compartment decides on its own: either no rule names the
    compartment, or its rules are a ``select`` over a mixed compartment (see
    :data:`UNMATCHED_SELECT`) and this name is not one they pick out.  The caller then falls
    through to :func:`context_iri_by_source_context`.

    *raw_context* is the compartment the list ships the flow in, the same input
    snapshot :func:`flow_context_iri` reads, for the same reason: after the
    context transform has run once ``flow.context`` is a consensus dict, and a
    dict is not a compartment key.

    :raises AmbiguousSourceContextError: if the compartment has rules and the
        name matches none of them.  Falling through to the compartment rule is
        what #52 was: the compartment rule for ``natural resource / land`` says
        occupation, so a transformation flow that no rule caught would be filed
        as occupation with nothing said.  A name this list has started using and
        we have not read is a curation decision, not a default.
    """
    key = normalize_context_key(raw_context if isinstance(raw_context, list) else [])
    if not key:
        return None
    rules = name_prefix_context_rules(source_label).get(key)
    if not rules:
        return None
    name = normalize_mapping_text(source_name) if isinstance(source_name, str) else ""
    for prefix, context_iri in rules:
        if name.startswith(prefix):
            return context_iri
    if name_prefix_unmatched_policy(source_label).get(key) == UNMATCHED_SELECT:
        # A mixed compartment: these rules pick some flows out of it, and the
        # compartment rule still decides for everything else.
        return None
    raise AmbiguousSourceContextError(
        f"{MANUAL_MAPPING_FILEPATH}: {source_label} flow {source_name!r} is in "
        f"{list(key)}, a compartment whose context its name has to decide, and it "
        f"starts with none of {[prefix for prefix, _ in rules]}. Add a "
        f"name_prefix_context_mappings row saying which context this name means."
    )


class SimaproContextRuleError(ValueError):
    """A ``simapro_context_mappings`` row that says nothing, or says two things."""


@dataclass(frozen=True)
class SimaproCompartmentRule:
    """One compartment as SimaPro writes it, and what this list makes of it.

    Two shapes, and a row is exactly one of them.

    Most rows name a **context**: `Emissions to air/low. pop.` is
    `Environmental / Air / Non-urban or high stack`, and that is an ordinary
    compartment rule.

    A few state only a **dimension**, because there is no context to name.
    `Raw` with nothing after it says *this is a resource* and refuses to say
    which kind, and this list publishes no bare `Resource` context -- only
    `Economic`, `Inventory Indicator` and `Social` render on their own.  Naming
    one of Resource's children instead would be worse than saying nothing: the
    selector rejects every candidate whose medium is not the row's, so a row
    filed as `Resource / Ground` loses every biotic, air and water flow of its
    own substance before scoring.  209 of the 222 substances with a resource
    flow have exactly one, so the substance can decide the medium -- and a row
    that states only the dimension lets it, while still keeping an emission to
    air out of the running.
    """

    source_context: ContextKey
    #: The consensus context, for a compartment that names one.
    context_iri: str = ""
    #: The consensus dimension, for a compartment that names only that.
    dimension: str = ""
    comment: str = ""


@lru_cache(maxsize=None)
def simapro_context_rules() -> dict[ContextKey, SimaproCompartmentRule]:
    """``normalised compartment -> rule``, for the compartments SimaPro writes.

    **A fourth phrasebook, kept out of the other three.**
    :func:`context_iri_by_any_source_context` reads the compartment rules of
    every *list* this project has mapped, with the list dropped, and its whole
    safety argument is that the three vocabularies are disjoint -- no
    compartment string appears under two vendors, so reading one without its
    list cannot silently pick a side.  SimaPro's spellings are not disjoint from
    them: BAFU is a SimaPro-shaped list, so `emissions to water / river` is in
    both, and `air / unspecified` is ecoinvent's as well.  Folding these in
    would end that property and put SimaPro's spelling in front of a merged
    list's own rule during a build.

    So they are their own section, read only by the lookup, and the merge never
    sees them.  Nothing here changes where a build puts a row.

    **Where the meaning comes from.**  The randonneur table
    ``simapro-2025-ecoinvent-3-contexts`` supplies the *spellings* -- 63 of
    them, which is the useful part, because they are the strings a SimaPro
    export actually carries.  It maps them onto **ecoinvent 3.12**, and this
    list's own vocabulary is finer than ecoinvent 3.12's, so the target is not
    taken where another list has already ruled on the same subcompartment:
    ecoinvent has no lake and no river, and routing through it turns eight of
    the 63 into something coarser or plainly wrong (`Emissions to air/indoor`
    becomes non-urban air).  Where nothing else has ruled, the routed target
    stands.  ``tests/test_simapro_contexts.py`` pins each of those against the
    rule it was taken from, so the two cannot drift apart.

    :raises SimaproContextRuleError: for a row naming neither a context nor a
        dimension, or naming both.  A row that says nothing would be a
        compartment silently unrecognised, which is the failure this section
        exists to end.
    """
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    rows = payload.get("simapro_context_mappings")
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise SimaproContextRuleError(
            f"{MANUAL_MAPPING_FILEPATH}: 'simapro_context_mappings' must be a list"
        )
    out: dict[ContextKey, SimaproCompartmentRule] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = normalize_context_key(row.get("source_context"))
        context_iri = str(row.get("context_iri") or "").strip()
        dimension = str(row.get("dimension") or "").strip()
        if not key:
            raise SimaproContextRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: a simapro_context_mappings row has no "
                f"'source_context': {row!r}"
            )
        if bool(context_iri) == bool(dimension):
            raise SimaproContextRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: {list(key)} must name exactly one of "
                f"'context_iri' and 'dimension'. A row with neither leaves the "
                f"compartment unrecognised; a row with both says the dimension "
                f"twice and lets the two disagree."
            )
        out[key] = SimaproCompartmentRule(
            source_context=key,
            context_iri=context_iri,
            dimension=dimension,
            comment=str(row.get("comment") or "").strip(),
        )
    return out


@lru_cache(maxsize=None)
def _load_simapro_name_rows() -> tuple[tuple[ContextKey, str, str, str], ...]:
    """Every ``simapro_name_prefix_context_mappings`` row, as tuples.

    ``(compartment, prefix, context_iri, unmatched)``.  Absent or empty is fine:
    most SimaPro compartments hold one kind of thing.
    """
    payload = orjson.loads(MANUAL_MAPPING_FILEPATH.read_bytes())
    rows = payload.get("simapro_name_prefix_context_mappings")
    if rows is None:
        return ()
    if not isinstance(rows, list):
        raise SimaproContextRuleError(
            f"{MANUAL_MAPPING_FILEPATH}: "
            "'simapro_name_prefix_context_mappings' must be a list"
        )
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = normalize_context_key(row.get("source_context"))
        prefix = normalize_mapping_text(str(row.get("name_prefix") or ""))
        context_iri = str(row.get("context_iri") or "").strip()
        if not (key and prefix and context_iri):
            raise SimaproContextRuleError(
                f"{MANUAL_MAPPING_FILEPATH}: a simapro_name_prefix_context_mappings "
                f"row needs a compartment, a prefix and a context: {row!r}"
            )
        out.append((key, prefix, context_iri, str(row.get("unmatched") or "").strip()))
    return tuple(out)


@lru_cache(maxsize=None)
def simapro_name_prefix_rules() -> dict[ContextKey, tuple[tuple[str, str], ...]]:
    """``compartment -> ((prefix, context_iri), ...)`` for SimaPro's own spellings.

    The same instrument :func:`name_prefix_context_rules` is for a list this
    project has mapped, and needed for the same reason: a compartment that holds
    both land occupations and land transformations cannot be read without the
    flow's name, and reading it without one files every transformation as an
    occupation.  That is #52, and it is what a flat rule for `Raw / land`
    would do.

    Only for the compartments SimaPro spells and no mapped list does -- `Raw /
    land`, `Raw materials / land`, `Raw / in ground`, `Raw materials / in
    ground`.  `resources / land` is
    BAFU's own spelling and keeps BAFU's own rules, which
    :func:`context_iri_for_any_source_context` has already applied by the time
    this is reached.
    """
    out: dict[ContextKey, list[tuple[str, str]]] = {}
    for key, prefix, context_iri, _policy in _load_simapro_name_rows():
        out.setdefault(key, []).append((prefix, context_iri))
    return {key: tuple(rules) for key, rules in out.items()}


@lru_cache(maxsize=None)
def simapro_name_prefix_policy() -> dict[ContextKey, str]:
    """What to do with a name none of a compartment's prefixes catches.

    :data:`UNMATCHED_SELECT` for a compartment that holds land rows *among*
    ordinary ones -- `Raw / in ground` is 161 resources and 3 land rows in
    BAFU's equivalent -- so the compartment rule still decides for the rest.
    Otherwise the compartment is a partition and a name matching nothing has no
    answer, which the caller reports rather than guessing at.
    """
    return {
        key: policy
        for key, _prefix, _iri, policy in _load_simapro_name_rows()
        if policy
    }
