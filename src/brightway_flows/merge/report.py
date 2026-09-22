"""The record types of the merge report.

The report is what a curator works from: it says what the merge matched, what it
added, and — most importantly — what it could not place and why. Until these
types existed its rows were dict literals assembled in six different places, so
their shape was defined only by whichever branch produced them.

These record types are list-agnostic, and were named for one list until #242:
the report was a file per ecoinvent version, `ecoinvent-merge-report-{version}.json`.
It is now the `merge_outcomes` and `merge_conflicts` tables, keyed by run, which
is what lets one run merge several lists (#243).

Field declaration order matches the order the rows are written in, because
`to_dict()` follows declaration order and the tables should not churn.

Seven row kinds, by how the merge resolved a source flow:

- :class:`PreparedMatch` — a curator's existing decision was honoured
- :class:`AlgorithmMatch` — matched by identifier or label
- :class:`ManualAddition` — a flow was added from a curated grouping
- :class:`CreatedFlow` — the substance was not in the list, so it was added
- :class:`UnmatchedRow` — could not be placed; the review queue
- :class:`EnrichedUnmatchedRow` — an unmatched row with the evidence gathered
  afterwards to help a curator decide
- :class:`PreparedContextInconsistency` — a prepared decision that no longer
  agrees with the contexts the target covers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from brightway_flows.domain.records import SerialisableRecord

#: Fields every row carries, identifying the source flow it came from.
#: Declared on each record rather than inherited: dataclass inheritance forces
#: base fields first, which would not match the emitted order in every case.


class UnmatchedReason(StrEnum):
    """Why the merge could not place a source flow.  A closed set.

    A category, never an instance.  `prepared-target-not-found` used to
    interpolate the target UUID it could not resolve, which made grouping on
    the value useless -- 8,439 distinct values for 9,614 rows -- and pushed the
    run report into splitting the string back apart in SQL.  Nothing was lost
    by dropping the interpolation: every row that carries this reason also sets
    `target_elementary_flow_id`, `prepared_target_resolution` and
    `prepared_target_trace`, which is where that detail already was.

    An enum for the same reason :class:`~brightway_flows.merge.store.Outcome`
    is one: a category invented by a typo is indistinguishable from a real one
    once it is in the table.
    """

    # Set by `resolve_flow_object`: which flow object, if any, the row belongs to.
    NO_FLOW_OBJECT_CANDIDATE = "no-flow-object-candidate"
    MULTIPLE_FLOW_OBJECT_CANDIDATES = "multiple-flow-object-candidates"

    # Set by `_select_elementary_flow`: which of the object's flows to attach
    # to.  That function also returns reasons for the selections it *makes*
    # (`best-score`, `exact-context-iri-match`); those are not categories of
    # failure and are not members here.
    NO_ELEMENTARY_CANDIDATES = "no-elementary-candidates"
    NO_CANDIDATES_SAME_DIMENSION_MEDIA = "no-candidates-same-dimension-media"
    UNABLE_TO_SCORE_CANDIDATES = "unable-to-score-candidates"
    NO_CONTEXT_OR_UNIT_SIGNAL = "no-context-or-unit-signal"
    TIED_ELEMENTARY_CANDIDATES = "tied-elementary-candidates"
    #: Every flow that fit this row named a place the row denies -- groundwater
    #: for a release to a lake, farm soil for a pesticide on forest soil.  Its
    #: own category rather than one of the two above, because those describe a
    #: selector that could not choose and this one describes a selector that
    #: was not allowed to (#85).
    CONTEXT_CONTRADICTION = "context-contradiction"
    #: The row named a compartment this list holds, and the substance has no
    #: flow in it.  Sibling of the one above and creatable for the same reason:
    #: the place to make the flow is the place the row named, so it is not a
    #: guess.  What it replaces is a coarsening -- taking the best-scoring flow
    #: of the right substance in some other compartment -- which made the answer
    #: depend on which flows happened to exist when the row was reached (#112).
    NO_CANDIDATE_IN_STATED_CONTEXT = "no-candidate-in-stated-context"

    # Set while following a curator's prepared decision.
    PREPARED_MATCH_MULTIPLE_TARGETS = "prepared-match-multiple-targets"
    PREPARED_TARGET_NOT_FOUND = "prepared-target-not-found"

    # Set when the flow matching chose is no longer resolvable.
    SELECTED_ELEMENTARY_FLOW_MISSING_ID = "selected-elementary-flow-missing-id"
    SELECTED_ELEMENTARY_FLOW_NOT_FOUND = "selected-elementary-flow-not-found"


@dataclass
class PreparedMatch(SerialisableRecord):
    """A source flow attached to the target a curator had already chosen."""

    source_uuid: str
    source_name: str
    source_context: list[str]
    #: The place the build resolved the row's compartment to.  The other three
    #: record kinds have always carried it; a reader of the stored decision
    #: (`lookup.recorded`) otherwise has to re-derive the place outside the
    #: build, where rules that fired during it cannot fire again (#361).
    #: Defaulted so `from_dict` still loads a record written before the field
    #: existed -- the reader treats the absent field as "re-derive" anyway.
    source_context_iri: str = field(default="", kw_only=True)
    source_unit: str
    source_cas: str
    target_elementary_flow_id: str
    prepared_target_elementary_flow_id: str
    target_flow_object_id: str
    target_name: str
    target_context: list[str]
    target_unit: str
    #: How the stored target was followed to the flow that is active now.
    prepared_target_resolution: str
    prepared_target_trace: list[str]
    prepared_context_decision: str
    provenance: dict[str, Any]
    #: Present only when source and target differ in unit or substance basis.
    conversion_factor: float | None = None
    conversion_comment: str | None = None

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "conversion_factor", "conversion_comment",
    })


@dataclass
class AlgorithmMatch(SerialisableRecord):
    """A source flow matched to an existing flow by identifier or label."""

    source_uuid: str
    source_name: str
    source_context: list[str]
    source_context_normalized: Any
    source_context_iri: str
    source_unit: str
    source_cas: str
    source_ec: str
    flow_object_id: str
    target_name: str
    target_elementary_flow_id: str
    target_context: list[str]
    target_unit: str
    #: What the match rested on: cas, ec, label, or a narrowed combination.
    basis: str
    basis_value: str
    selector_reason: str
    matching_method: str
    algorithm_details: dict[str, Any]
    provenance: dict[str, Any]


@dataclass
class ManualAddition(SerialisableRecord):
    """A flow added to the consensus list from a curated grouping."""

    source_uuid: str
    source_name: str
    source_context: list[str]
    source_context_iri: str
    source_unit: str
    source_cas: str
    source_ec: str
    flow_object_id: str
    flow_object_label: str
    new_elementary_flow_id: str
    #: The EF 3.1 flow in the same context, when one exists.
    target_ef_elementary_flow_id: str
    has_ef_context_match: bool
    cas_name_validated: Any
    notes: str
    extra_fields: dict[str, Any]
    provenance: dict[str, Any]


@dataclass
class CreatedFlow(SerialisableRecord):
    """A substance the consensus list did not have, minted from a source row.

    Distinct from :class:`ManualAddition`, which groups source flows onto a flow
    object a curator chose, and from an :class:`AlgorithmMatch` carrying
    ``new-elementary-flow-created``, which adds a context to a flow object
    matching already found.  Here there was no flow object at all.

    The published flow carries the same ``source`` string as those additions, so
    this record is where the three are told apart.
    """

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({"unmatched_basis"})

    source_uuid: str
    source_name: str
    source_context: list[str]
    source_context_iri: str
    source_unit: str
    source_cas: str
    source_ec: str
    flow_object_id: str
    flow_object_label: str
    #: The identity the new object ended up with, which is what the source row
    #: carried unless enrichment found more.
    flow_object_cas: list[str]
    flow_object_ec: list[str]
    new_elementary_flow_id: str
    #: False for the second and later rows of one substance: they share the
    #: object, and share the flow too when they share a context.
    minted_flow_object: bool
    #: Neither a CAS nor an EC anywhere upstream.  A correct outcome for a
    #: name-only source, and a count to compare between runs.
    identity_is_name_only: bool
    provenance: dict[str, Any]
    #: This row is measured in something other than the flow it landed on --
    #: the same statement `has_unit_mismatch` makes about a match, and reached
    #: a different way: a created flow states one unit for a group of rows, and
    #: the rows do not always agree (#78).  Which kind of disagreement it was
    #: is the outcome's `outcome` column, so nothing here says it twice.
    has_unit_mismatch: bool = False
    #: What the flow states and how that was settled -- `units`, `declared`,
    #: `decided_by`.  Carried so the report can tell a disagreement the unit
    #: table resolved from one nobody has: only the second needs a curator.
    unit_decision: dict[str, Any] = field(default_factory=dict)
    #: The basis the unmatched record carried when the row was *refused* a
    #: match rather than missed by one -- `label+ion-element-refused` (#198):
    #: the name found the bare element of the row's own ion name, and the
    #: matcher declined it.  Minting overwrites the unmatched record with this
    #: one, so without this field the refusal would be the one decision the
    #: outcome does not show.  None, and omitted, for the ordinary case.
    unmatched_basis: str | None = None


@dataclass
class UnmatchedRow(SerialisableRecord):
    """A source flow the merge could not place. The review queue.

    The optional fields are set only by the paths that reach them, so they are
    omitted rather than serialised as null.
    """

    source_uuid: str
    source_name: str
    source_context: list[str]
    source_unit: str
    source_cas: str
    source_ec: str
    #: Why it could not be placed.  A category; the instance detail that goes
    #: with it is in the fields below and in `detail` on the stored outcome.
    reason: UnmatchedReason
    #: The name the vendor shipped, where `source_name` is the enriched one the
    #: merge matched on; what a flow created for this row publishes as its
    #: `source_flow_name` (#149).  None for a row that arrived without it.
    source_shipped_name: str | None = None
    target_elementary_flow_id: str | None = None
    prepared_target_resolution: str | None = None
    prepared_target_trace: list[str] | None = None
    matching_method: str | None = None
    candidate_flow_object_ids: list[str] | None = None
    candidate_elementary_flow_ids: list[str] | None = None
    candidate_elementary_flows: list[Any] | None = None
    candidate_target_uuids: list[str] | None = None
    basis: str | None = None
    basis_value: str | None = None
    algorithm_details: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "target_elementary_flow_id", "prepared_target_resolution",
        "prepared_target_trace", "matching_method", "candidate_flow_object_ids",
        "candidate_elementary_flow_ids", "candidate_elementary_flows",
        "candidate_target_uuids", "basis", "basis_value", "algorithm_details",
        "source_shipped_name",
    })
    _EXTRA_FIELD: ClassVar[str | None] = "extra"


@dataclass
class EnrichedUnmatchedRow(SerialisableRecord):
    """An unmatched row plus the evidence gathered to help a curator place it.

    The enrichment is a second pass over the unmatched rows: it probes the flow
    object indexes again, cross-checks the source name against ChEBI and PubChem
    names for the same CAS, and reports the nearest contexts. None of it changes
    the merge outcome; it exists so the review queue is actionable.
    """

    source_uuid: str
    source_name: str
    source_context: list[str]
    source_unit: str
    source_cas: str
    source_ec: str
    reason: UnmatchedReason
    target_elementary_flow_id: str | None = None
    prepared_target_resolution: str | None = None
    prepared_target_trace: list[str] | None = None
    matching_method: str | None = None

    # Second-pass probe of the flow-object indexes.
    has_flow_object_candidates: bool = False
    preferred_basis: str = ""
    candidate_flow_object_ids: list[str] = field(default_factory=list)
    candidate_flow_objects: list[Any] = field(default_factory=list)
    basis_counts: dict[str, int] = field(default_factory=dict)
    labels_used: list[str] = field(default_factory=list)

    # Whether external databases agree the CAS names this substance.
    cas_name_agrees_pubchem_or_chebi: bool | None = None
    cas_name_agreeing_records: list[Any] = field(default_factory=list)
    cas_name_agreeing_sources: list[str] = field(default_factory=list)
    source_cas_known_flow_object: bool | None = None

    # Where the row's context maps to, and what sits nearby.
    harmonised_source_context_iri: str = ""
    harmonised_source_context: list[str] = field(default_factory=list)
    exact_context_elementary_flow_count: int = 0
    closest_context_candidates: list[Any] = field(default_factory=list)

    extra: dict[str, Any] = field(default_factory=dict)

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "target_elementary_flow_id", "prepared_target_resolution",
        "prepared_target_trace", "matching_method",
    })
    _EXTRA_FIELD: ClassVar[str | None] = "extra"


@dataclass
class PreparedContextInconsistency(SerialisableRecord):
    """A prepared decision that no longer agrees with its target's contexts."""

    source_uuid: str
    source_name: str
    source_context: list[str]
    expected_context_iri: str
    expected_context: list[str]
    actual_context_iri: str
    actual_context: list[str]
    target_elementary_flow_id: str
    prepared_target_elementary_flow_id: str
    target_flow_object_id: str
    target_name: str
    prepared_context_decision: str
    expected_context_elementary_present: bool
    expected_context_elementary_count: int
    expected_context_elementary_ids: list[str]
    provenance: dict[str, Any]
    reason: str


@dataclass
class MergeReport(SerialisableRecord):
    """The whole report: what the merge did, and what it could not do.

    .. deprecated::
       Nothing writes this any more.  A run is recorded in the `merge_runs` and
       `merge_outcomes` tables instead, keyed so that one source flow has one
       outcome.  This type survives only because `webapps.merge_review` still
       reads the old file, and goes when that app is ported.

    ``unmatched`` and the two enriched lists describe the same rows. The split
    exists because a curator triages them differently — a row with candidate
    flow objects needs a choice made, one without needs a flow object created.
    """

    schema_version: int
    generated_at: str
    source_list: str
    source_version: str
    input_paths: dict[str, str]
    stats: dict[str, Any]
    prepared_matches: list[PreparedMatch] = field(default_factory=list)
    algorithm_matches: list[AlgorithmMatch] = field(default_factory=list)
    prepared_context_inconsistencies: list[PreparedContextInconsistency] = field(
        default_factory=list
    )
    manual_additions: list[ManualAddition] = field(default_factory=list)
    unmatched: list[UnmatchedRow] = field(default_factory=list)
    unmatched_with_flow_object_candidates: list[EnrichedUnmatchedRow] = field(
        default_factory=list
    )
    unmatched_without_flow_object_candidates: list[EnrichedUnmatchedRow] = field(
        default_factory=list
    )

    #: The row lists, in the order they are written.
    ROW_KEYS: ClassVar[tuple[str, ...]] = (
        "prepared_matches",
        "algorithm_matches",
        "prepared_context_inconsistencies",
        "manual_additions",
        "unmatched",
        "unmatched_with_flow_object_candidates",
        "unmatched_without_flow_object_candidates",
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialise, converting each row list through its own record type.

        Every row is a record.  This used to fall back to passing a row through
        unchanged if it had no `to_dict`, which was a hedge against the rows
        still being dicts; they are not, and a dict reaching here would be a bug
        worth raising on rather than silently serialising.
        """
        out = super().to_dict()
        for key in self.ROW_KEYS:
            out[key] = [row.to_dict() for row in out[key]]
        return out
