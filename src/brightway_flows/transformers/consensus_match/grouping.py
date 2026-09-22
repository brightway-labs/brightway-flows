"""The units matching works on: flow objects, and the groups they fall into.

Consensus matching does not decide anything about a single elementary flow.  It
decides about a substance -- one flow object and every flow behind it -- and it
weighs that decision against the other objects sharing the same name and
context, because a block is usually a property of the group rather than of the
substance.  This module builds both: the synthetic object rows, and the group
evidence a rule is handed alongside one.

`build_altlabel_cas_index` is here for the same reason: it is what the dataset
as a whole already says about a name, which is evidence no single row carries.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from brightway_flows.domain.flow import Flow
from brightway_flows.domain.flow_object import FlowObject
from brightway_flows.domain.labels import Label, flow_label_value
from brightway_flows.domain.vocabulary import (
    CHEMINF_CAS_REGISTRY_NUMBER,
    CHEMINF_EC_NUMBER,
)
from brightway_flows.pipeline import is_becquerel_unit, normalize
from brightway_flows.qualifiers import detect_origin_qualifier
from brightway_flows.domain.context_registry import context_to_dict
from brightway_flows.transformers.consensus_match.indexes import SourceIndexes
from brightway_flows.transformers.consensus_match.naming import (
    is_exact_name_match_for_group,
)
from brightway_flows.transformers.consensus_match.profiles import CompoundProfiles
from brightway_flows.transformers.consensus_match.relationships import (
    RELATIONSHIP_EXACT,
    RelationshipClassifier,
)

#: Keys under which a synthetic flow-object record carries its member flows.
#: They live in the passthrough bag because they are internal to matching and
#: must never reach an artifact.
MEMBERS_KEY = "_object_members"
MEMBER_UUIDS_KEY = "_object_member_uuids"

#: A group is one name in one context.
GroupKey = tuple[str, tuple[str, ...]]


def sorted_unique_strings(values: list[Any]) -> list[str]:
    return sorted({
        str(v).strip()
        for v in values
        if isinstance(v, str) and str(v).strip()
    })


def flow_context(flow: Flow) -> list[str]:
    """One flow's context, as the parts a group key is built from.

    ``field=value`` per set field, in the vocabulary's field order.  This is a
    key, not a display string: it is compared against other flows' and never
    shown, so it states which axis each value is on.

    Was ten branches over a field that held either the source list's compartment
    or the consensus context, plus a legacy-key fallback and a last-resort
    ``sorted(items())``.  ``flow.context`` is a :class:`Context` now, and this
    transformer is the fourteenth of the chain -- the second decided the context
    and nothing may reach an artifact without one -- so the only case left is a
    flow the chain has not reached yet (#97).
    """
    if flow.context is not None:
        return [f"{key}={value}" for key, value in context_to_dict(flow.context).items()]
    # Source-specific key, so read from the passthrough bag explicitly.
    ef_context = flow.extra.get("elementary_flow_categorization")
    if isinstance(ef_context, list):
        return [str(x) for x in ef_context]
    return []


def flow_group_key(flow: Flow) -> GroupKey:
    name = normalize(flow_label_value(flow))
    context = tuple(flow_context(flow))
    return (name, context)


def group_key_to_str(group_key: GroupKey) -> str:
    name, ctx = group_key
    return f"{name}||{' > '.join(ctx)}"


def build_object_rows(
    *,
    flow_objects: list[FlowObject],
    members_by_object_id: dict[str, list[Flow]],
    flows: list[Flow],
) -> list[Flow]:
    """One synthetic row per flow object, carrying its members in `extra`.

    Falls back to grouping the flows itself when the pipeline did not inject
    flow-object context, so the transformer runs the same way standalone.
    """
    object_rows: list[Flow] = []
    if flow_objects:
        for fo in flow_objects:
            object_id = str(fo.flow_object_id or "").strip()
            if not object_id:
                continue
            members = list(members_by_object_id.get(object_id, []))
            member_uuids = [
                str(m.uuid or "")
                for m in members
                if isinstance(m.uuid, str)
            ]
            cas_numbers = sorted_unique_strings(
                ((fo.classifications or {}).get(CHEMINF_CAS_REGISTRY_NUMBER, {}) or {}).get("@value", [])
            )
            ec_numbers = sorted_unique_strings(
                ((fo.classifications or {}).get(CHEMINF_EC_NUMBER, {}) or {}).get("@value", [])
            )
            representative = members[0] if members else Flow(uuid=object_id)
            # A synthetic record standing for the whole flow object.  Built
            # as a Flow so downstream reads are attribute access like any
            # other flow; the member lists ride in the passthrough bag.
            payload = representative.to_dict()
            payload["uuid"] = object_id
            object_pref = flow_label_value({"prefLabel": fo.prefLabel}) if isinstance(fo.prefLabel, list) else ""
            if object_pref:
                payload["prefLabel"] = [Label(value=object_pref).to_dict()]
            payload["cas_numbers"] = cas_numbers
            payload["ec_numbers"] = ec_numbers
            synthetic = Flow.from_dict(payload)
            synthetic.extra[MEMBER_UUIDS_KEY] = member_uuids
            synthetic.extra[MEMBERS_KEY] = members
            object_rows.append(synthetic)
        return object_rows

    # Fallback when flow-object context was not injected by pipeline.
    object_members: dict[tuple[str, str], list[Flow]] = defaultdict(list)
    for flow in flows:
        cas_key = tuple(sorted_unique_strings(flow.cas_numbers))
        if cas_key:
            key = ("cas", "|".join(cas_key))
        else:
            name_key = normalize(flow_label_value(flow))
            key = ("name", name_key) if name_key else ("uuid", str(flow.uuid or ""))
        object_members[key].append(flow)

    for members in object_members.values():
        rep = members[0]
        member_uuids = [
            str(m.uuid or "")
            for m in members
            if isinstance(m.uuid, str)
        ]
        names = [flow_label_value(m).strip() for m in members if flow_label_value(m).strip()]
        display_name = max(names, key=len) if names else flow_label_value(rep).strip()
        merged_cas = sorted_unique_strings([x for m in members for x in (m.cas_numbers or [])])
        merged_ec = sorted_unique_strings([x for m in members for x in (m.ec_numbers or [])])
        payload = rep.to_dict()
        payload["cas_numbers"] = merged_cas
        payload["ec_numbers"] = merged_ec
        if display_name:
            payload["prefLabel"] = [Label(value=display_name).to_dict()]
        synthetic = Flow.from_dict(payload)
        synthetic.extra[MEMBER_UUIDS_KEY] = member_uuids
        synthetic.extra[MEMBERS_KEY] = members
        object_rows.append(synthetic)
    return object_rows


def build_altlabel_cas_index(
    *,
    flow_objects: list[FlowObject],
    object_rows: list[Flow],
    indexes: SourceIndexes,
) -> dict[str, set[str]]:
    """Synonym (normalized) → the CAS numbers this dataset already gives it.

    Used to block external CAS-from-name lookups when the dataset already
    distinguishes the no-CAS flow from a CAS-bearing substance that shares
    its name as a trade-name synonym.

    Example: EF 3.1 has "granite" (stone, no CAS) AND "Penoxsulam" (CAS
    219714-96-2).  PubChem lists "Granite" as a synonym for Penoxsulam.
    Without this guard the stone incorrectly inherits Penoxsulam's CAS.

    Two sources are combined:
    1. altLabels already present on CAS-bearing flow objects (covers
       synonyms added by earlier transformers, e.g. ChebiAltLabels).
    2. A pre-pass over PubChem and ChEBI synonym tables for every CAS
       that is already assigned to a flow in this dataset.  This catches
       synonyms that consensus matching itself would add later in the loop --
       so ordering of flows in the loop does not matter.
    """
    altlabel_cas_in_dataset: dict[str, set[str]] = {}

    # Source 1: existing altLabels on pre-computed flow objects.
    for fo in flow_objects:
        fo_cas: set[str] = set(
            (((fo.classifications or {}).get(CHEMINF_CAS_REGISTRY_NUMBER, {}) or {}).get("@value") or [])
        )
        if not fo_cas:
            continue
        for al_item in (fo.altLabel or []):
            al_value = al_item.get("@value") if isinstance(al_item, dict) else None
            if not isinstance(al_value, str) or not al_value.strip():
                continue
            norm_al = normalize(al_value)
            altlabel_cas_in_dataset.setdefault(norm_al, set()).update(fo_cas)

    # Source 2: PubChem and ChEBI synonyms for every CAS already present in
    # the dataset.
    known_cas_in_dataset: set[str] = set()
    for obj_flow in object_rows:
        for cas in sorted_unique_strings(obj_flow.cas_numbers):
            known_cas_in_dataset.add(cas)

    for cas in known_cas_in_dataset:
        for syn_name in indexes.pubchem_names_by_cas.get(cas, set()):
            altlabel_cas_in_dataset.setdefault(normalize(syn_name), set()).add(cas)
        for chebi_id in indexes.chebi_by_cas.get(cas, []):
            chebi_rec = indexes.chebi_records.get(chebi_id, {})
            for syn_name in chebi_rec.get("synonyms", []):
                if isinstance(syn_name, str) and syn_name.strip():
                    altlabel_cas_in_dataset.setdefault(normalize(syn_name), set()).add(cas)
            chebi_label = chebi_rec.get("label")
            if isinstance(chebi_label, str) and chebi_label.strip():
                altlabel_cas_in_dataset.setdefault(normalize(chebi_label), set()).add(cas)
        for ec_name in indexes.ec_names_by_cas.get(cas, set()):
            altlabel_cas_in_dataset.setdefault(normalize(ec_name), set()).add(cas)

    return altlabel_cas_in_dataset


@dataclass
class GroupEvidence:
    """What the group a substance was matched in says about it."""

    group_key: str
    group_member_count: int
    cas_set: list[str] = field(default_factory=list)
    cas_label_decisions: dict[str, str] = field(default_factory=dict)
    group_sources: list[str] = field(default_factory=list)
    group_cas_sources: dict[str, list[str]] = field(default_factory=dict)
    supporting_refs: list[str] = field(default_factory=list)
    has_intra_group_conflict: bool = False
    intra_group_conflict_summary: str = "no intra-group CAS conflict"

    def review_fields(self) -> dict[str, Any]:
        """The group fields every review row carries, in one place.

        The names differ from this record's own -- `cas_set` is `group_cas_set`
        on a review row -- so spelling the mapping out once here is the
        difference between one place to get it wrong and three.
        """
        return {
            "group_key": self.group_key,
            "group_member_count": self.group_member_count,
            "group_cas_set": self.cas_set,
            "group_cas_label_decisions": self.cas_label_decisions,
            "group_sources": self.group_sources,
            "group_cas_sources": self.group_cas_sources,
            "intra_group_conflict_summary": self.intra_group_conflict_summary,
        }


@dataclass
class ObjectUnit:
    """One substance as the rules see it: the object, its members, its group."""

    row: Flow
    members: list[Flow]
    member_uuids: list[str]
    object_uuid: str
    flow_name: str
    cas_numbers: list[str]
    #: A becquerel unit or an origin qualifier (`Carbon dioxide (fossil)`) means
    #: the flow is not simply the substance its CAS denotes, so no rule may
    #: rename it to that substance's name.
    skip_name_updates: bool
    group: GroupEvidence

    @classmethod
    def from_row(cls, row: Flow, group: GroupEvidence) -> ObjectUnit:
        flow_name = flow_label_value(row)
        return cls(
            row=row,
            members=row.extra.get(MEMBERS_KEY, []),
            member_uuids=row.extra.get(MEMBER_UUIDS_KEY, []),
            object_uuid=str(row.uuid or ""),
            flow_name=flow_name,
            cas_numbers=list(row.cas_numbers),
            skip_name_updates=(
                is_becquerel_unit(row.unit) or bool(detect_origin_qualifier(flow_name))
            ),
            group=group,
        )


def analyze_group(
    group_key: GroupKey,
    members: list[Flow],
    *,
    indexes: SourceIndexes,
    profiles: CompoundProfiles,
    classifier: RelationshipClassifier,
) -> GroupEvidence:
    group_name_raw = flow_label_value(members[0]) if members else ""
    cas_set = sorted({
        cas
        for flow in members
        for cas in flow.cas_numbers
        if isinstance(cas, str) and cas
    })

    supporting_refs: list[str] = []
    has_intra_group_conflict = False
    summary = "no intra-group CAS conflict"

    if len(cas_set) > 1:
        summary = f"{len(cas_set)} distinct CAS in group"
        for left, right in combinations(cas_set, 2):
            rel_class, _reason, refs = classifier.classify_cas_pair_with_fallback(left, right)
            supporting_refs.extend(refs)
            if rel_class != RELATIONSHIP_EXACT:
                has_intra_group_conflict = True

        if has_intra_group_conflict:
            summary = "multiple CAS in group with non-exact CAS pair relations"
        else:
            summary = "multiple CAS in group but all CAS pairs look exact-equivalent"

    cas_label_decisions: dict[str, str] = {}
    group_cas_sources: dict[str, list[str]] = {}
    group_sources: set[str] = set()
    if cas_set:
        for cas in cas_set:
            cas_sources: set[str] = set()
            if indexes.chebi_by_cas.get(cas):
                cas_sources.add("chebi")
            if indexes.ec_names_by_cas.get(cas):
                cas_sources.add("ec_inventory")
            if indexes.pubchem_names_by_cas.get(cas):
                cas_sources.add("pubchem")
            group_cas_sources[cas] = sorted(cas_sources)
            group_sources.update(cas_sources)

        # If one CAS has a preferred name exactly matching the grouped flow name,
        # mark it exactMatch and mark the rest relatedMatch.
        exact_cas: list[str] = []
        for cas in cas_set:
            profile = profiles.get(cas)
            preferred = profile.get("preferred_name")
            if (
                isinstance(preferred, str)
                and is_exact_name_match_for_group(group_name_raw, preferred)
            ):
                exact_cas.append(cas)
        if exact_cas:
            for cas in exact_cas:
                cas_label_decisions[cas] = "exactMatch"
            for cas in cas_set:
                cas_label_decisions.setdefault(cas, "relatedMatch")
        elif len(cas_set) == 1:
            cas_label_decisions[cas_set[0]] = "exactMatch"
        else:
            # Ambiguous multi-CAS group without an exact preferred-name hit.
            for cas in cas_set:
                cas_label_decisions[cas] = "relatedMatch"

    return GroupEvidence(
        group_key=group_key_to_str(group_key),
        group_member_count=len(members),
        cas_set=cas_set,
        cas_label_decisions=cas_label_decisions,
        group_sources=sorted(group_sources),
        group_cas_sources=group_cas_sources,
        supporting_refs=sorted(set(supporting_refs)),
        has_intra_group_conflict=has_intra_group_conflict,
        intra_group_conflict_summary=summary,
    )
