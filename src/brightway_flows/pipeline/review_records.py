"""The records behind the review tables in the consensus database.

Phase 0 of `plans/webapp-consolidation.md`: everything the review web
application needs moves out of side-car JSON files and into
`consensus-flows.sqlite3`, so that one file is sufficient to serve the app.

This module holds *what* is stored; :mod:`brightway_flows.pipeline.review_tables`
holds the SQL and the writer.  They are separate so that
:mod:`brightway_flows.pipeline.engine` can import :class:`ChangeEvent` --
which it produces on every run -- without dragging in the ChEBI index loader
that the mismatch builder needs.

Every row written to those tables is one of these dataclasses.  Per `AGENTS.md`
a dict inside the pipeline is a bug unless it is an external payload, and the
change log was the last place a bare dict survived: `apply_transformers` used to
return `list[dict]`, so a misspelt key in the SQLite writer produced a column of
`None` rather than an error.

The files each table replaces:

| Record | Table | Replaced file |
|---|---|---|
| :class:`PipelineRun` | `pipeline_runs` | the header of `transform-log.json` |
| :class:`RunStat` | `run_stats` | the stats section of `transform-log.json` |
| :class:`StageTiming` | `run_timings` | nothing -- no run recorded where its time went |
| :class:`ChangeEvent` | `changelog` | the `changes` list of `transform-log.json`, and `consensus-match-applied-changes.json` |
| :class:`ProvenanceActivity` | `provenance_activities` | the `activities` list of `provenance.json` |
| :class:`ReviewQueueItem` | `review_queue` | `chebi-name-cas-review.json`, `ec-cross-check-review.json`, `ec-malformed-review.json`, `consensus-match-review.json` |
| :class:`FormulaMismatch` | `formula_mismatches` | the ChEBI index, loaded per request by the webapp |
| :class:`ElementCoverage` | `element_coverage` | `pubchem-elements-isotopes.json` joined against `flow-objects.json` |
| :class:`ContextDefaultMapping` | `context_default_mappings` | `data/context-manual-mapping.json` |
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
from typing import Any, ClassVar, Protocol, runtime_checkable

import orjson

from brightway_flows.domain.context import Context
from brightway_flows.domain.context_registry import context_to_dict
from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.domain.vocabulary import MintedNamespace, Namespace

#: The prefix the identifiers below are written under.  Local to this module --
#: nothing in the published export uses it -- but written once, because it is
#: half of every identifier here and an unresolvable prefix is how `ef:runId`
#: and `ef:flowUuid` expanded to nothing in the app #229 deleted.
EF_PREFIX = "ef"

#: What the prefixes in the identifiers below expand to.  Read from the registry
#: rather than restated, so `prov:` and `xsd:` mean here what they mean in the
#: export, and `ef:flow/...` is a resolvable claim rather than an opaque one.
PROV_CONTEXT = {
    Namespace.PROV.name.lower(): Namespace.PROV.value,
    EF_PREFIX: MintedNamespace.REVIEW_PROVENANCE.value,
    Namespace.XSD.name.lower(): Namespace.XSD.value,
}


def prov_entity_id(flow_uuid: str, version: int) -> str:
    """The entity IRI for one version of one flow."""
    return f"{EF_PREFIX}:flow/{flow_uuid}/v{version}"


def prov_agent_id(transformer: str) -> str:
    """The agent IRI for a transformer.  One agent per transformer, per run."""
    return f"{EF_PREFIX}:agent/{transformer}"


def prov_activity_id(run_id: str, change_index: int) -> str:
    """The activity IRI for one field change.

    Takes the run id rather than reading it off the activity: the database holds
    exactly one transform run, so the run id lives once in `pipeline_runs`
    instead of being repeated across every activity row.
    """
    return f"{EF_PREFIX}:activity/change/{run_id}/{change_index}"


@dataclass
class PipelineRun(SerialisableRecord):
    """What one transform run was asked to do, and what it did.

    Exactly one row: `run_pipeline` deletes and rewrites the database, so a
    second row would mean two runs wrote the same file.  This is the header
    `transform-log.json` carried, and it is what gives every other table in this
    module a timestamp and a run id without repeating them per row.
    """

    run_id: str
    timestamp: str
    schema_version: int
    dry_run: bool = False
    max_flows: int | None = None
    #: One entry, the EF 3.1 base file.  A list because it was one when the
    #: transform composed its input from several files (#210), and because the
    #: overview page renders it as one.
    input_files: list[str] = field(default_factory=list)
    transformer_names: list[str] = field(default_factory=list)
    flow_count: int = 0
    change_count: int = 0
    #: The revision the code came from, and whether the tree was clean.
    #:
    #: A build is otherwise anonymous about the one thing a comparison depends
    #: on.  Two databases can be diffed row by row -- that is
    #: `tools/compare_merge_outcomes.py` -- and the diff means "what this change
    #: did" only if the other side was built from the commit the branch started
    #: at.  Without this the reader has to remember, and forgetting is silent.
    #:
    #: Recorded so a *stored* build can be reused as the before side rather than
    #: rebuilt, which is ten minutes a change.  `git_dirty` is why it is two
    #: fields: a build from a modified tree is not a build of its commit, and
    #: reusing one would be the same silent failure by another route (#101).
    git_commit: str = ""
    git_dirty: bool = False


@dataclass
class RunStat(SerialisableRecord):
    """One number a stage of the run counted about its own work.

    `(stage, key, value)` rather than a `stats_json` blob on `PipelineRun`,
    because the question these answer is a run-over-run one -- "386 of 387
    objects typed last week, 340 today" is a regression in the typing rules,
    and a blob has to be parsed and diffed to see it where rows can be selected
    and charted.

    Every producer already returns a `Counter`; this is what happens to it.
    They were logged and dropped, and before that merged into a dict that was
    written four times and read zero (#232).

    `stage` is the function that counted, not the file it lives in: the reader
    of this table is asking which part of the run moved, and a rename of a
    module should not look like a stage appearing.

    An absent row is not a zero. The producers return `Counter` objects, which
    have no key for a case they never saw -- so `skipped_unknown_scheme`
    missing means that stage counted no skips *and did not say so*, where a
    stored zero means it looked. A producer that wants the stronger claim has
    to seed its counter.
    """

    stage: str
    key: str
    value: int


@dataclass
class StageTiming(SerialisableRecord):
    """How long one stage of a build took.

    Beside :class:`RunStat` rather than in it, because a count and a clock are
    read differently: `objects_typed` is compared between runs and must be
    identical for the same input, while a duration differs on every run of the
    same code and would make every artifact comparison fail. They are separate
    tables so that `run_stats` stays exactly comparable and every volatile
    number lives in one place `tools/verify_run.py` masks.

    `stage` is the part of the build that ran, spelled as the function or the
    step a reader would name -- `resolve_flow_layers`, `merge`, `transform` --
    and `detail` narrows it to one transformer or one source list, so that "the
    transform took 26 minutes" and "`consensus_match` took 19 of them" are the
    same table read at two depths.

    Seconds, not milliseconds, and the field is called `duration_seconds`
    because that is one of the names `verify_run` already treats as volatile:
    a build that reports its own timings must not thereby report a difference
    between two runs of identical code.
    """

    stage: str
    detail: str = ""
    duration_seconds: float = 0.0


@dataclass
class ChangeEvent(SerialisableRecord):
    """One field change that a transformer proposed and the engine applied.

    Produced by `apply_transformers`, which returns these in the order they were
    applied.  `change_index` is assigned by the writer rather than the loop,
    because the merge calls `apply_transformers` once per source list and the
    log is only numbered once, when it is written.

    `flow_object_id` is likewise filled in at write time.  A flow's substance is
    a property of the layer resolution that runs *after* the transformer chain,
    so it is not knowable while the change is being applied -- but it is what
    makes "everything that happened to this substance" answerable without a
    join, which is the whole reason `changelog` replaces `consensus_changes`.
    """

    uuid: str
    field_name: str
    old_value: Any
    new_value: Any
    transformer: str
    flow_name: str = ""
    comment: str = ""
    change_index: int = 0
    flow_object_id: str = ""

    #: `field` is the serialised name, kept from `transform-log.json`.  The
    #: attribute cannot be called `field`: this module imports
    #: `dataclasses.field`, and a class attribute of that name would shadow it
    #: for every default declared after it.
    _ALIASES: ClassVar[dict[str, str]] = {"field_name": "field"}


def change_value_json(value: Any) -> str:
    """One changelog cell, as the JSON stored in `old_value_json` / `new_value_json`.

    A change's value is whatever the field holds, and since #97 one field holds
    a :class:`~brightway_flows.domain.context.Context`.  `orjson` serialises
    a dataclass by emitting every field, so a context would arrive here as eight
    keys, five of them null -- a shape it has nowhere else in the artifacts.  The
    record's own encoder decides what a context looks like on disk, so it
    decides what it looks like in a changelog cell too.
    """
    return orjson.dumps(
        value,
        default=_encode_change_value,
        option=orjson.OPT_PASSTHROUGH_DATACLASS,
    ).decode()


def _encode_change_value(value: Any) -> Any:
    """Whatever `orjson` will not write itself, once dataclasses are passed through."""
    if isinstance(value, Context):
        return context_to_dict(value)
    if isinstance(value, SerialisableRecord):
        return value.to_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"cannot serialise {type(value).__name__} into a changelog cell")


@dataclass
class ProvenanceActivity(SerialisableRecord):
    """One PROV-O `ef:FieldChange` activity: a transformer changed a field.

    Deliberately narrow.  `provenance.json` restated the old and new value on
    every activity, which doubled the largest payload in the run for no new
    information -- the values are already on the :class:`ChangeEvent` with the
    same `change_index`, which is this record's key.  What is stored here is the
    graph structure that cannot be recovered from the change log alone: which
    version of the flow the activity consumed and which it produced.

    The IRIs are properties rather than columns for the same reason.  They are
    a fixed function of the fields below (and, for :meth:`activity_id`, of the
    run id in `pipeline_runs`), so storing them would be storing the same uuid
    three times per row.
    """

    change_index: int
    uuid: str
    field_name: str
    transformer: str
    #: Which version of the flow this activity produced.  Version 0 is the flow
    #: as loaded, so the first change to a flow generates version 1.
    entity_version: int

    _ALIASES: ClassVar[dict[str, str]] = {"field_name": "field"}

    @property
    def used_entity_id(self) -> str:
        return prov_entity_id(self.uuid, self.entity_version - 1)

    @property
    def generated_entity_id(self) -> str:
        return prov_entity_id(self.uuid, self.entity_version)

    @property
    def agent_id(self) -> str:
        return prov_agent_id(self.transformer)

    def activity_id(self, run_id: str) -> str:
        return prov_activity_id(run_id, self.change_index)


class ReviewQueue(StrEnum):
    """The decision queues a curator works through.

    One table, not one per queue: they differ in which columns they render and
    in nothing else.  The value is the URL segment -- `/queue/<name>` in the
    consolidated app -- so renaming one is a routing change, not a data change.

    Adding a queue is adding a member here and a `review_queue_items()` on
    whatever produces it; nothing else has to change.  That is the affordance
    #225 was waiting for: a merge-side finding such as a unit disagreement
    between a source flow and the flow it resolves onto is not an *outcome* --
    every source flow already has exactly one of those -- and putting it in
    `accumulator.unmatched` would send an already-matched flow through the
    manual-additions pass and mint a duplicate.  It is a queue item.
    """

    #: Common Chemistry knows this name and gives a different CAS for it.
    COMMONCHEM_NAME_CAS = "commonchem-name-cas"
    #: Common Chemistry knows this CAS and gives a different name for it.
    COMMONCHEM_CAS_NAME_DIFFERENCES = "commonchem-cas-name-differences"
    #: The name resolves to several ChEBI records, none carrying the flow's CAS.
    CAS_AMBIGUOUS = "cas-ambiguous"
    #: The EC inventory disagrees with the flow about a CAS↔EC pair.
    EC_CROSS_CHECK = "ec-cross-check"
    #: An EC number with no valid check digit, so nothing can be resolved from it.
    EC_MALFORMED = "ec-malformed"
    #: A consensus-match decision that was blocked or left unresolved.
    CONSENSUS_MATCH = "consensus-match"
    #: PubChem's `xref/RN` index linked a CAS to a compound whose own curated
    #: record does not list that number, and the compound was dropped.
    CURATED_CAS_EXCLUSION = "curated-cas-exclusion"
    #: CAS Common Chemistry publishes no structure for a CAS, or a different one
    #: from the candidate offered, and the structure lookup was blocked or
    #: narrowed accordingly.
    COMMONCHEM_STRUCTURE_EXCLUSION = "commonchem-structure-exclusion"
    #: A structure that survived every gate and still disagrees with Common
    #: Chemistry about the stereochemistry of the same skeleton.  The one queue
    #: here that reports a defect no rule can settle: nothing was changed, and
    #: nothing will be until a curator says which side is right.
    STEREO_DISAGREEMENT = "stereo-disagreement"
    #: A preferred-label replacement a rule proposed and no ruling covers.
    UNDECIDED_LABEL_REPLACEMENT = "undecided-label-replacement"
    #: A flow's own name answers for a different substance than the one the
    #: flow sits on, so giving the flow its substance's name would delete the
    #: only visible symptom of a mis-grouping (#116).  The flow keeps its name
    #: and the pair waits for a ruling in `preferred-label-decisions.json`:
    #: `approve` says the grouping is right and the rename proceeds with the
    #: colliding synonym withheld (#113), `reject` says the flow's own name
    #: stands.
    SUBSTANCE_LABEL_CONFLICT = "substance-label-conflict"
    #: More than one flow name in one source list carries this registry number,
    #: and no signal says whether they are one substance.  The merge stands
    #: until a curator rules, because splitting on suspicion is the larger risk.
    CONTESTED_CAS = "contested-cas"
    #: A flow of a land-class substance is published outside `Land Use`.  A
    #: land class and its flows' contexts must agree about what a thing is --
    #: an occupation filed among the water resources is the vendor's
    #: compartment overruling the curated class (#193) -- and this queue is
    #: what turns the next list's version of that into a build finding
    #: rather than seven rows discovered one at a time.
    LAND_CLASS_OUT_OF_PLACE = "land-class-out-of-place"
    #: Two or more live flows share a flow object, a context and a unit --
    #: most of what deduplication signs on, so they are one field away from
    #: collapsing, and a lexicographic identifier sort would pick the survivor.
    #: #31 is that collapse having happened; this is the question being asked
    #: before it does.
    ELEMENTARY_FLOW_COLLISION = "elementary-flow-collision"
    #: The other half of that question.  One substance is published in two
    #: contexts that are two different places rather than one described at two
    #: levels of detail, and the merge wrote one of them -- so two source lists
    #: have answered differently about where the substance comes from, and the
    #: two halves can never meet.  #87.
    SUBSTANCE_IN_TWO_PLACES = "substance-in-two-places"
    #: An identifier the renumbering retired whose replacement this build does
    #: not mint, so the identifier resolves to nothing.  A redirect is published
    #: only where the flow it points at exists, which is right for a build that
    #: merges fewer source lists and wrong for a flow curation has taken away:
    #: the fix that removed it was correct and a published identifier went with
    #: it.  Reported rather than repaired, because where the substance survives
    #: it usually survives in several contexts and picking one of them is a
    #: decision about the substance.  #344.
    RETIRED_IDENTIFIER_UNRESOLVED = "retired-identifier-unresolved"
    #: Two implementations of one LCIA method state a factor for one flow and
    #: category and the numbers differ beyond tolerance.  The consensus
    #: implementation publishes neither until a curator rules: a default would
    #: publish a number nobody had looked at under a label saying a decision was
    #: made.  Written by `characterise`, not by a build.
    CONTESTED_FACTOR = "contested-factor"
    #: A factor only the second implementation states, on a flow the method's own
    #: publisher did not characterise -- most often because its flow list has no
    #: such compartment (#84).  Adopting it is a real option and often the right
    #: one; it is somebody else's number, so it is offered rather than taken.
    PROPOSED_FACTOR = "proposed-factor"
    #: The model an LCIA method states it is derived from -- USEtox 2.1, for EF
    #: 3.1's toxicity categories -- gives a number more than a hundredfold away
    #: from the method's own, in every compartment.  Neither transcription can
    #: see this and both state the method's number, so agreement between them is
    #: not evidence; the consensus implementation publishes nothing for that
    #: substance and category until a curator rules.  #107.
    CONTRADICTED_FACTOR = "contradicted-factor"


class Severity(StrEnum):
    """How much a queue item is asking for.

    Ordering is the point: a queue sorts `blocking` first.  It is not a
    judgement about data quality, it is about whether the pipeline already acted.
    """

    #: Recorded for a curator to read; the pipeline made no change.
    INFO = "info"
    #: The pipeline made a change it wants confirmed.
    REVIEW = "review"
    #: The pipeline could not act, and will not until someone rules.
    BLOCKING = "blocking"


@dataclass
class ReviewQueueItem(SerialisableRecord):
    """One row in one queue.

    The indexed fields are what every queue filters and cross-links on -- a
    flow, a substance, a CAS.  Everything queue-specific is in `payload`, stored
    as JSON, exactly as `MergeOutcome.detail` does for the merge.  That is what
    lets six queues share a table and a template.

    `item_key` is unique within a queue and stable across runs: it is what a
    stored ruling would key on, and what lets a curator link to one row.
    """

    queue_name: ReviewQueue
    item_key: str
    title: str = ""
    severity: Severity = Severity.INFO
    uuid: str = ""
    flow_object_id: str = ""
    cas: str = ""
    item_index: int = 0
    payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ReviewQueueProvider(Protocol):
    """A transformer that also produces work for a curator.

    Replaces the `export_review(path)` methods, which each invented their own
    JSON envelope and had to be wired up one by one in the CLI -- so a new
    review file meant remembering to call it, and forgetting meant a page that
    silently showed nothing.  `run_pipeline` asks every transformer it was given
    for its items instead, so a transformer that grows a queue is served by
    implementing one method.
    """

    name: str

    def review_queue_items(self) -> list[ReviewQueueItem]:
        """Everything this transformer wants a curator to look at, this run."""
        ...


@dataclass
class FormulaMismatch(SerialisableRecord):
    """A flow object whose molecular formula disagrees with a ChEBI record it cites.

    One row per (flow object, ChEBI record) pair below the threshold, rather
    than one row per flow object with a nested list, so the page can sort and
    page in SQL.  The webapp computed this per request by loading the whole
    ChEBI index -- around a second of work repeated on every page view, over
    data that only changes when the pipeline runs.

    `threshold` is stored rather than assumed: it is the reason a pair is in the
    table at all, and a run made under a different threshold should say so
    rather than be silently compared against today's value.
    """

    flow_object_id: str
    chebi_id: str
    similarity_score: float
    threshold: float
    pref_label: str = ""
    flow_formula: str = ""
    chebi_label: str = ""
    chebi_formula: str = ""
    chebi_cas_numbers: list[str] = field(default_factory=list)


class ElementStatus(StrEnum):
    """Whether the consensus list accounts for a chemical element."""

    #: A flow object exists for the element and is linked back to EF 3.1.
    LINKED = "linked"
    #: A flow object exists but nothing in EF 3.1 references it.
    NOT_LINKED = "not-linked-to-ef31"
    #: No flow object carries this atomic number at all.
    MISSING = "missing-flow-object"


@dataclass
class ElementCoverage(SerialisableRecord):
    """One chemical element, and whether the consensus list covers it.

    Every element gets a row, not only the uncovered ones.  The page shows the
    gaps, but "118 of 118 covered" is only sayable if the covered ones are in
    the table too -- and a queue that can never report success is a queue nobody
    checks.
    """

    atomic_number: int
    symbol: str = ""
    name: str = ""
    status: ElementStatus = ElementStatus.MISSING
    flow_object_id: str = ""
    pubchem_page_url: str = ""

    @property
    def is_covered(self) -> bool:
        return self.status is ElementStatus.LINKED


@dataclass
class ContextDefaultMapping(SerialisableRecord):
    """One rule mapping a source list's raw compartment onto a consensus context.

    Read from `data/context-manual-mapping.json`, a package data file rather
    than a pipeline artifact: it describes the mapping rules themselves, so it
    outlives the input layer that is being dropped.  It is copied into the
    database so the app has one place to read from, not because the file is
    going away.

    There used to be a warning here not to confuse these with the per-release
    `<list>-context-mapping.json` files the merge read.  Those were a generated
    projection of this same file, so the two never had different jobs -- only
    different freshness, because `build` regenerated neither.  The merge now
    reads these rows too, filtered by `source` (#11), so there is one system
    to describe: the `default_context_mapping` transformer applies them during
    the transform, and the merge applies them to place a source row's context.
    """

    source: str
    source_context: list[str]
    context_iri: str
    context_display: str = ""
    comment: str = ""
