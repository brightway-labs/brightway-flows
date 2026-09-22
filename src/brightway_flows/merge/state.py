"""State threaded through the per-source-row logic of the merge.

`merge_source_list` grew to a thousand lines largely because its per-row logic
mutated a dozen local collections, so no part of it could be lifted out. Grouping
those locals into objects is what lets the row logic move into functions that can
be read on their own.

Four objects, split by lifetime and direction:

- :class:`SourceRow` -- one source row, parsed once.
- :class:`MatchAttempt` -- what matching concluded about that row.
- :class:`MergeIndexes` -- lookups the row logic *reads*; built once, frozen.
- :class:`MergeAccumulator` -- everything the row logic *writes*.

A new lookup belongs on the indexes; a new result belongs on the accumulator;
anything scoped to one row belongs on `SourceRow` or `MatchAttempt`. Anything
that is none of those is a local.

Both layers are records: `FlowObject` and `ElementaryFlow`, built by
`_load_working_set` at the read boundary, which is where a payload becomes a
record.

The elementary flows were the last dicts here, and they were the ones that
mattered most: the merge reads *which substance* a source row belongs to off a
flow object, and *which flow of it* off an elementary flow, so a misspelled key
on this half published an identifier pointing at the wrong place in the
environment (#93). Being the merge's mutable working list is what made them
last rather than what made them exempt -- a row is added to the list, merged
into and written back, and every one of those steps is now a field the record
declares.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from brightway_flows.domain.elementary_flow import ElementaryFlow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.vocabulary import XKOS_SOURCE_CONCEPT_CURIE
from brightway_flows.merge.contexts import ContextExpectations
from brightway_flows.merge.conversions import UnitConversion
from brightway_flows.merge.prepared_context_decisions import (
    PreparedContextRuling,
)
from brightway_flows.merge.historical_names import HistoricalName
from brightway_flows.merge.species import CanonicalIdentity
from brightway_flows.merge.report import (
    AlgorithmMatch,
    PreparedMatch,
    UnmatchedRow,
)
from brightway_flows.sources import SourceList


def _source_ref_key(ref: dict[str, Any]) -> tuple[str, str, str]:
    """A source reference's natural key: which flow, in which list version."""
    return (
        str(ref.get("list_name") or ""),
        str(ref.get("list_version") or ""),
        str(ref.get("source_flow_uuid") or ""),
    )


def _association_key(association: dict[str, Any]) -> str:
    """A concept association's identity: the source concept it is about."""
    source_concept = association.get(XKOS_SOURCE_CONCEPT_CURIE)
    if not isinstance(source_concept, dict):
        return ""
    return str(source_concept.get("@id") or "")


def _extend_unique(
    existing: list[Any], incoming: Any, key: Any
) -> None:
    """Append the entries of *incoming* that *existing* does not already carry."""
    if not isinstance(incoming, list):
        return
    seen = {key(item) for item in existing if isinstance(item, dict)}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        if (item_key := key(item)) in seen:
            continue
        seen.add(item_key)
        existing.append(item)


def _merge_links_into(existing: ElementaryFlow, rebuilt: ElementaryFlow) -> None:
    """Fold *rebuilt*'s source refs and concept associations into *existing*.

    Both fields default to ``None`` on the record rather than to an empty list,
    because an absent key and an empty one are different things in the stored
    payload, so a flow gaining its first link gets the list here.
    """
    for name, key in (
        ("source_refs", _source_ref_key),
        ("concept_associations", _association_key),
    ):
        current = getattr(existing, name)
        if not isinstance(current, list):
            current = []
            setattr(existing, name, current)
        _extend_unique(current, getattr(rebuilt, name), key)


@dataclass(frozen=True)
class SourceRow:
    """One source flow, with the fields the merge reads."""

    uuid: str
    #: The name the merge matches on: the label enrichment settled on, or the
    #: one the source list shipped where enrichment left it alone.
    name: str
    #: The synonyms the source list shipped.  Narrower than `labels`, and used
    #: where the source's own vocabulary is what matters -- CAS name validation
    #: against PubChem and ChEBI, which a label the pipeline invented would not
    #: be an independent check of.
    synonyms: list[str]
    #: Every name this row is known by, best first: the enriched label, the
    #: shipped name, its synonyms, the enriched alternative labels.  Matching
    #: looks up all of them, because a row is known by all of them at once and
    #: looking up one breaks the moment enrichment renames it.
    labels: list[str]
    #: Context as source strings, and the consensus IRI it maps to (may be empty
    #: when the source context is not registered).
    context: list[str]
    context_iri: str
    context_normalized: tuple[str, ...]
    unit: str
    unit_iri: str
    cas: str
    ec: str
    #: The factor a manual fix stated when it rebased this row onto another
    #: unit, or None for the ordinary row that arrived in the unit it is carried
    #: in.  A list with a correspondence table states its factors there; this is
    #: for one that has none.  See
    #: :func:`brightway_flows.merge.conversions.conversion_from_source_flow`.
    conversion: UnitConversion | None = None
    #: The name the source list shipped, verbatim (after its curated fixes),
    #: from `flow.provided.name`.  What the published mapping records as
    #: `source_flow_name` -- a consumer holding the vendor's inventory has this
    #: string and no other -- where `name` is what enrichment made of it for
    #: matching (#149).  Empty for a row built without a record, and then
    #: `vendor_name` falls back to `name`.
    shipped_name: str = ""

    @property
    def vendor_name(self) -> str:
        """The name a published mapping says this row had: the vendor's."""
        return self.shipped_name or self.name

    @property
    def provenance_unit(self) -> str:
        """The unit this row's *mapping* is published under.

        The unit the vendor shipped, where a fix rebased the row: `unit` is what
        the merge matches and creates on, because it is the unit the row is
        being carried in, but a mapping that stated that one would be telling a
        consumer their kilograms are cubic metres.  What it states instead is
        the vendor's own unit, with the factor beside it.
        """
        return self.conversion.source_unit if self.conversion else self.unit


@dataclass(frozen=True)
class CandidateResolution:
    """The single flow object a source row resolved to, and on what evidence."""

    flow_object_id: str
    basis: str
    basis_value: str
    #: The material concept the row was resolved through, where one answered.
    #:
    #: Declared rather than read back out of `basis_value`, which happens to
    #: carry the concept id when `basis` is `material` and carries a registry
    #: number, a label or a derived spelling otherwise.  A caller asking "which
    #: kind of water is this" should not have to know which of those it is
    #: looking at -- and the merge does ask, because for a withdrawal the
    #: material names the body the water came from.
    material: str = ""


@dataclass
class MatchAttempt:
    """What matching concluded about a source row.

    ``selected`` is the elementary flow chosen, or None when the flow object was
    identified but no elementary flow in it fits the row's context -- the case
    that leads either to creating a flow or to reporting the row.
    """

    flow_object_id: str
    candidates: list[ElementaryFlow]
    selected: ElementaryFlow | None
    selector_reason: str
    selector_details: dict[str, Any]
    basis: str
    basis_value: str


@dataclass(frozen=True)
class MergeIndexes:
    """Lookups the merge reads while processing source rows.

    Frozen: a row's outcome must not depend on rows processed before it except
    through :class:`MergeAccumulator`. Keeping that boundary explicit is what
    makes the per-row logic reviewable.
    """

    flow_objects_by_id: dict[str, FlowObject]
    flow_object_label_by_id: dict[str, str]

    # Identifier and label lookups, each mapping a key to the flow objects that
    # carry it.  A key may reach several objects; narrowing that down is what
    # `resolve_flow_object` does.
    cas_index: dict[str, set[str]]
    ec_index: dict[str, set[str]]
    label_index: dict[str, set[str]]
    #: prefLabel hits only, excluding altLabel -- a substance's primary name is
    #: safer evidence than a trade name.
    pref_label_index: dict[str, set[str]]
    #: origin_qualifier -> flow object ids, so a biogenic source row does not
    #: match the unqualified substance.
    qualifier_index: dict[str, set[str]]
    #: Flow objects carrying at least one CAS number, for the guard that refuses
    #: a label-only match against one of them.
    flow_objects_with_cas: set[str]
    context_expectations: ContextExpectations
    consensus_context_strings: dict[str, list[str]]
    #: (source uuid, prepared target uuid) -> a curator's decision about that
    #: pairing.
    prepared_context_decisions: Mapping[tuple[str, str], PreparedContextRuling]
    mapping_file: str | None
    #: Which list is being merged.  The row logic writes the list's name and
    #: version into every flow it creates, so it has to know them; before this
    #: existed they were literals in the middle of the flow it built.
    source: SourceList
    #: uuid -> the newest release's identity for it, loaded only for a list the
    #: element/ion rule governs (`merge/species.py`): ecoinvent, with no
    #: prepared correspondence table.  Empty everywhere else, including every
    #: list merged while a table still decides, which is what keeps the rule's
    #: machinery inert until the plan's PR F.
    canonical_identities: Mapping[str, "CanonicalIdentity"] = field(default_factory=dict)
    #: normalised retired vendor name -> the newest release's name for the same
    #: flow (`merge/historical_names.py`).  Consulted by `resolve_flow_object`
    #: only after every registry number and every shipped name has failed.
    historical_names: Mapping[str, "HistoricalName"] = field(default_factory=dict)


@dataclass
class MergeAccumulator:
    """Everything the merge collects as it processes source rows."""

    #: The working elementary-flow list: those loaded from the database, plus
    #: any added.
    merged_elementary: list[ElementaryFlow] = field(default_factory=list)
    #: The ids the working list already held when this merge started.
    #:
    #: "Did this pass create that flow?" cannot be answered from the flow's
    #: `source`: the string names the *list* -- `ecoinvent algorithm addition`
    #: -- and a run merges several of a list's versions in sequence, so the
    #: flows an earlier version's pass created answer to it too.  Reading it
    #: that way made the ecoinvent 3.8 pass treat 42 flows the 3.12 pass had
    #: created as its own, and `INSERT OR IGNORE` then dropped every field it
    #: had to write about them.
    preexisting_flow_ids: frozenset[str] = frozenset()
    #: Every id :meth:`add_flow` was handed, whether it minted the flow or
    #: merged into one that was already there.  A manual addition mints its id
    #: from the source uuid, which two versions of a list share, so "added" and
    #: "new" are not the same set.
    added_flow_ids: set[str] = field(default_factory=set)
    #: elementary_flow_id -> flow, including deprecated ones.
    all_by_elem_id: dict[str, ElementaryFlow] = field(default_factory=dict)
    #: elementary_flow_id -> flow, active only.
    by_elem_id: dict[str, ElementaryFlow] = field(default_factory=dict)
    #: flow_object_id -> its elementary flows, so a candidate flow can be checked
    #: against the contexts that object already covers.
    elementary_by_object: dict[str, list[ElementaryFlow]] = field(default_factory=dict)

    # Report rows, one per source row, by how it was resolved.  These are
    # records, not dicts: every append site already builds one, but the
    # annotation said otherwise, which is why `MergeReport.to_dict` still
    # carried a `hasattr(row, "to_dict")` shim for a case that cannot arise.
    prepared_matches: list[PreparedMatch] = field(default_factory=list)
    algorithm_matches: list[AlgorithmMatch] = field(default_factory=list)
    unmatched: list[UnmatchedRow] = field(default_factory=list)

    def add_flow(self, flow: ElementaryFlow) -> None:
        """Record a newly created elementary flow in every index that tracks it.

        Adding a flow means updating four collections; doing it in one place
        keeps them consistent.

        A flow whose id is already in the working list is *merged* into it
        rather than appended beside it.  The ids the merge mints are stable
        functions of the source flow's uuid, and two versions of a source list
        share those uuids, so the second version's pass rebuilds a row the
        first version's pass already wrote.  Appending it left
        `merged_elementary` holding two records for one id -- which every reader
        of it, and the `elementary_flows` primary key, assume cannot happen.
        Only the links are taken from the rebuilt row: its labels, context and
        properties are what the first pass already settled, and the second pass
        has nothing to add to them.
        """
        elem_id = flow.elementary_flow_id
        self.added_flow_ids.add(elem_id)
        if (existing := self.all_by_elem_id.get(elem_id)) is not None:
            _merge_links_into(existing, flow)
            return
        object_id = flow.flow_object_id
        self.merged_elementary.append(flow)
        self.all_by_elem_id[elem_id] = flow
        self.by_elem_id[elem_id] = flow
        self.elementary_by_object.setdefault(object_id, []).append(flow)

    def flows_for_object_in_context(
        self, flow_object_id: str, context_iri: str
    ) -> list[ElementaryFlow]:
        """Elementary flows of *flow_object_id* already sitting in *context_iri*."""
        return [
            flow
            for flow in self.elementary_by_object.get(flow_object_id, [])
            if flow.context_iri.strip() == context_iri
        ]
