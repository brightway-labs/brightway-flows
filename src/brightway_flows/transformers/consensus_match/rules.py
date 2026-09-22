"""The rules that turn evidence into a change, or into a row for a curator.

Four rules, in the order they run for one flow object:

1. `assign_consensus_cas` -- give a CAS to members that have none, when the
   sources agree on one and nothing about the group or the dataset says the
   name belongs to a different substance.
2. `rename_from_cc_chebi_agreement` -- take the name Common Chemistry and ChEBI
   both give the object's single CAS.
3. `rename_from_source_vote` -- the fallback when they do not both give one: the
   name a quorum of sources votes for.
4. `add_commonchem_altlabels` -- keep the Common Chemistry synonyms as English
   altLabels.
5. `assign_cas_match_labels` -- record whether each CAS on a member is an exact
   or merely related match, as the group decided.

Every rule takes the substance and its evidence and appends to `Proposals`;
none of them reads a source or the network, and none of them applies anything.
Rules 2 and 3 are mutually exclusive -- bilateral agreement outranks the vote --
and both go through `RenameGate` first, so a rename nobody has ruled on is
queued rather than written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from brightway_flows.domain.common import Provenance
from brightway_flows.domain.flow import Flow
from brightway_flows.domain.labels import (
    Label,
    canonical_label_value,
    coerce_alt_labels,
    coerce_pref_label,
    dedupe_alt_labels_against_pref,
    flow_label_value,
)
from brightway_flows.pipeline import Change, normalize
from brightway_flows.sources import base_source_label
from brightway_flows.transformers.consensus_match.grouping import (
    ObjectUnit,
    sorted_unique_strings,
)
from brightway_flows.transformers.consensus_match.lookups import LookupClient
from brightway_flows.transformers.consensus_match.records import (
    ConsensusDecision,
    ConsensusMatchReviewItem,
)
from brightway_flows.transformers.consensus_match.relationships import (
    RELATIONSHIP_EXACT,
    RELATIONSHIP_UNRESOLVED,
    RelationshipClassifier,
)
from brightway_flows.transformers.consensus_match.rename_gate import RenameGate
from brightway_flows.transformers.consensus_match.voting import (
    ConsensusVotes,
    build_conflicts,
)


#: What `rename_from_cc_chebi_agreement` records as the derivation of the label
#: it writes.  A constant because it is also how that rule's applied renames are
#: found again afterwards: the change log holds the provenance of every value
#: written, and this string is the only thing on a `prefLabel` change that says
#: which rename rule wrote it (#224).  Free text on the `Change` comment would
#: not do -- provenance is structured, and structured is what can be read back.
CC_CHEBI_AGREEMENT_DERIVATION = "Common Chemistry / ChEBI primary name agreement"


@dataclass
class Proposals:
    """What the rules produced, accumulated across every flow object."""

    changes: list[Change] = field(default_factory=list)
    review: list[ConsensusMatchReviewItem] = field(default_factory=list)
    #: Preferred labels a rename has proposed but nothing has applied yet.  The
    #: altLabel rule reads them so that it dedupes against the new name rather
    #: than the one still on the record.
    pending_pref: dict[str, Label] = field(default_factory=dict)
    #: Alternative labels a rename has proposed but nothing has applied yet, for
    #: the same reason and with sharper consequences.  Both rename rules keep
    #: the name they replaced as an altLabel, and `add_commonchem_altlabels`
    #: runs afterwards over the same member: reading the *record* there means
    #: building on the labels the rename has not yet written, so the second
    #: proposal replaces the field with a list the retained name is missing
    #: from.  Two changes to one field, the later one computed from stale
    #: input, and the engine applies both -- so the retention was silently
    #: undone for every substance whose registry number Common Chemistry has
    #: synonyms for.  Measured on the 2026-08-17 build: of the 9,493 live flows
    #: a rename touched, 5,188 no longer publish the name the source list gave
    #: them, over 443 distinct pairs (#104, #106).
    pending_alt: dict[str, list[Label]] = field(default_factory=dict)


def assign_consensus_cas(
    unit: ObjectUnit,
    *,
    votes: ConsensusVotes,
    classifier: RelationshipClassifier,
    altlabel_cas_in_dataset: dict[str, set[str]],
    out: Proposals,
) -> None:
    """Give members without a CAS the one the sources agree the name holds."""
    cas_candidate, cas_votes = votes.cas_from_name(unit.flow_name)
    missing_cas_members = [
        m for m in unit.members
        if not sorted_unique_strings(m.cas_numbers)
    ]
    if cas_candidate and missing_cas_members:
        relationship_class, rel_reason, supporting_refs = classifier.classify_name_cas(
            flow_name=unit.flow_name,
            candidate_name=unit.flow_name,
            candidate_cas=cas_candidate,
            existing_cas_numbers=unit.group.cas_set,
        )
        conflicts = build_conflicts(cas_votes, cas_candidate)
        source_votes = {k: sorted(v) for k, v in cas_votes.items()}
        supporting_refs = sorted(set(supporting_refs + unit.group.supporting_refs))
        blocked_by_group = unit.group.has_intra_group_conflict
        # Block if the name is already used as an altLabel of a different
        # CAS-bearing flow object in this dataset: the input data itself
        # distinguishes them, so we must not conflate them.
        blocked_by_altlabel = (
            cas_candidate in altlabel_cas_in_dataset.get(normalize(unit.flow_name), set())
        )
        if relationship_class == RELATIONSHIP_EXACT and not blocked_by_group and not blocked_by_altlabel:
            for member in missing_cas_members:
                member_uuid = str(member.uuid or "")
                if not member_uuid:
                    continue
                out.changes.append(Change(
                    member_uuid,
                    "cas_numbers",
                    [cas_candidate],
                    comment=(
                        f"group_key={unit.group.group_key}; "
                        f"relationship_class={relationship_class}; "
                        f"candidate_cas={cas_candidate}; "
                        f"sources={sorted(cas_votes.get(cas_candidate, []))}; "
                        f"reason={rel_reason}; object_uuid={unit.object_uuid}"
                    ),
                ))
        else:
            out.review.append(ConsensusMatchReviewItem(
                uuid=unit.object_uuid,
                flow_name=unit.flow_name,
                member_uuids=unit.member_uuids,
                decision=ConsensusDecision.BLOCKED_CAS_UPDATE,
                relationship_class=relationship_class,
                candidate_cas=cas_candidate,
                reason=(
                    rel_reason
                    if not blocked_by_group
                    else f"{rel_reason}; intra-group conflict: {unit.group.intra_group_conflict_summary}"
                ),
                source_votes=source_votes,
                conflicts=conflicts,
                supporting_refs=supporting_refs,
                **unit.group.review_fields(),
            ))
    elif not cas_candidate:
        out.review.append(ConsensusMatchReviewItem(
            uuid=unit.object_uuid,
            flow_name=unit.flow_name,
            member_uuids=unit.member_uuids,
            decision=ConsensusDecision.NO_CONSENSUS_CAS,
            relationship_class=RELATIONSHIP_UNRESOLVED,
            source_votes={k: sorted(v) for k, v in cas_votes.items()},
            conflicts=build_conflicts(cas_votes, None),
            supporting_refs=unit.group.supporting_refs,
            **unit.group.review_fields(),
        ))


def apply_name_rules(
    unit: ObjectUnit,
    *,
    votes: ConsensusVotes,
    classifier: RelationshipClassifier,
    lookups: LookupClient,
    gate: RenameGate,
    out: Proposals,
) -> None:
    """The rules that need the object to hold exactly one CAS.

    A group carrying several CAS numbers has no single substance to name, and a
    becquerel unit or an origin qualifier (`Carbon dioxide (fossil)`) means the
    flow is not simply the substance its CAS denotes -- so both are left alone.
    """
    if len(unit.cas_numbers) != 1 or unit.skip_name_updates:
        return
    cas = unit.cas_numbers[0]

    # High-confidence rule: Common Chemistry and ChEBI agree on the
    # primary name for this CAS (compared after Greek→ASCII stereo
    # normalisation).  No relationship classification or voting
    # quorum is required — bilateral agreement is sufficient.
    cc_chebi_name = votes.cc_chebi_agreed_name(cas)
    if cc_chebi_name:
        rename_from_cc_chebi_agreement(unit, cas, cc_chebi_name, gate=gate, out=out)
    else:
        rename_from_source_vote(
            unit, cas, votes=votes, classifier=classifier, gate=gate, out=out
        )

    add_commonchem_altlabels(unit, cas, lookups=lookups, out=out)


def rename_from_cc_chebi_agreement(
    unit: ObjectUnit,
    cas: str,
    cc_chebi_name: str,
    *,
    gate: RenameGate,
    out: Proposals,
) -> None:
    """Rename every member to the name Common Chemistry and ChEBI both give.

    The object's own label is not consulted.  `unit.flow_name` is the flow
    *object's* label but the loop rewrites its *members'*, and those need not
    agree.  While the rule skipped the loop whenever the object label already
    matched, members behind a converged object were stranded on the raw source
    name -- an object reading `3-methylpentane` publishing `Methyl Pentane`,
    `1,1,1-trichloroethane` publishing `HCFC-140`, and 227 flows sitting on a
    name their own flow object disagreed with.  `normalize` strips whitespace
    as well as case, which made it worse: it read `Ethyl Benzene` as equal to
    `Ethylbenzene` and skipped that improvement too.
    """
    new_pref = Label(
        value=cc_chebi_name,
        source=Provenance(
            was_generated_by="consensus_match",
            was_attributed_to="brightway-flows",
            had_primary_source=[f"CAS:{cas}"],
            was_derived_from=CC_CHEBI_AGREEMENT_DERIVATION,
        ).to_dict(),
    )
    for member in unit.members:
        member_uuid = str(member.uuid or "")
        if not member_uuid:
            continue
        old_name = flow_label_value(member)
        old_pref = coerce_pref_label(member.prefLabel)
        if not gate.approves(
            member_uuid, old_name, new_pref.value, rule="cc_chebi_agreement", cas=cas,
        ):
            continue
        if not _pref_label_differs(old_pref, new_pref):
            continue
        out.changes.append(Change(
            member_uuid,
            "prefLabel",
            [new_pref.to_dict()],
            comment=(
                f"cas={cas}; cc_chebi_agreed_name={cc_chebi_name!r}; "
                f"object_uuid={unit.object_uuid}"
            ),
        ))
        out.pending_pref[member_uuid] = new_pref
        if canonical_label_value(cc_chebi_name) != canonical_label_value(old_name):
            change = _retained_altlabel_change(
                member,
                old_name=old_name,
                new_pref=new_pref,
                derived_from="original name retained as altLabel",
                comment=(
                    f"cas={cas}; added original name as altLabel "
                    f"after CC/ChEBI rename; object_uuid={unit.object_uuid}"
                ),
                out=out,
            )
            if change is not None:
                out.changes.append(change)


def rename_from_source_vote(
    unit: ObjectUnit,
    cas: str,
    *,
    votes: ConsensusVotes,
    classifier: RelationshipClassifier,
    gate: RenameGate,
    out: Proposals,
) -> None:
    """Rename every member to the name a quorum of sources votes for.

    Which members those are is decided per member, not from the object's label.
    `unit.flow_name` is the flow *object's* label while the loop rewrites its
    *members'*, and the two need not agree -- so a guard that returned as soon as
    the object's label matched the candidate stranded every member behind a
    converged object on whatever it was called before.  That is the same defect
    #221 fixed at the `cc_chebi_agreement` site, where it had left 227 flows on a
    name their own flow object disagreed with, and `normalize` folding whitespace
    made it worse there: `Ethyl Benzene` read as equal to `Ethylbenzene`, so that
    improvement was skipped too (#245).

    The members that need the rename are selected before the relationship is
    classified rather than inside the loop, because classification is the
    expensive step -- it can reach Wikidata and Wikipedia -- and because a
    non-exact verdict files a review row.  An object none of whose members would
    change has nothing for a curator to look at, and asking for one would fill
    the queue with rows whose answer is "nothing was going to happen anyway".
    """
    name_candidate, name_votes = votes.name_from_cas(cas)
    if not name_candidate:
        return

    new_pref = Label(
        value=name_candidate,
        source=Provenance(
            was_generated_by="consensus_match",
            was_attributed_to="brightway-flows",
            had_primary_source=[f"CAS:{cas}"],
            was_derived_from="multi-source name consensus",
        ).to_dict(),
    )
    members_to_rename = [
        member
        for member in unit.members
        if str(member.uuid or "")
        and _pref_label_differs(coerce_pref_label(member.prefLabel), new_pref)
    ]
    if not members_to_rename:
        return

    relationship_class, rel_reason, supporting_refs = classifier.classify_name_cas(
        flow_name=unit.flow_name,
        candidate_name=name_candidate,
        candidate_cas=cas,
        existing_cas_numbers=unit.group.cas_set,
    )
    conflicts = build_conflicts(name_votes, normalize(name_candidate))
    source_votes = {k: sorted(v) for k, v in name_votes.items()}
    supporting_refs = sorted(set(supporting_refs + unit.group.supporting_refs))
    blocked_by_group = unit.group.has_intra_group_conflict
    if relationship_class != RELATIONSHIP_EXACT or blocked_by_group:
        out.review.append(ConsensusMatchReviewItem(
            uuid=unit.object_uuid,
            flow_name=unit.flow_name,
            member_uuids=unit.member_uuids,
            decision=ConsensusDecision.BLOCKED_NAME_UPDATE,
            relationship_class=relationship_class,
            candidate_name=name_candidate,
            cas=cas,
            reason=(
                rel_reason
                if not blocked_by_group
                else f"{rel_reason}; intra-group conflict: {unit.group.intra_group_conflict_summary}"
            ),
            source_votes=source_votes,
            conflicts=conflicts,
            supporting_refs=supporting_refs,
            **unit.group.review_fields(),
        ))
        return

    for member in members_to_rename:
        member_uuid = str(member.uuid or "")
        old_name = flow_label_value(member)
        if not gate.approves(
            member_uuid, old_name, new_pref.value, rule="multi_source_consensus", cas=cas,
        ):
            continue
        out.changes.append(Change(
            member_uuid,
            "prefLabel",
            [new_pref.to_dict()],
            comment=(
                f"group_key={unit.group.group_key}; "
                f"relationship_class={relationship_class}; "
                f"candidate_name={name_candidate}; "
                f"cas={cas}; "
                f"sources={sorted(name_votes.get(normalize(name_candidate), []))}; "
                f"reason={rel_reason}; object_uuid={unit.object_uuid}"
            ),
        ))
        out.pending_pref[member_uuid] = new_pref
        if canonical_label_value(name_candidate) != canonical_label_value(old_name):
            change = _retained_altlabel_change(
                member,
                old_name=old_name,
                new_pref=new_pref,
                derived_from="original EF name retained as altLabel",
                comment=(
                    f"group_key={unit.group.group_key}; cas={cas}; "
                    f"added current EF name as altLabel when prefLabel differs; "
                    f"object_uuid={unit.object_uuid}"
                ),
                out=out,
            )
            if change is not None:
                out.changes.append(change)


def add_commonchem_altlabels(
    unit: ObjectUnit,
    cas: str,
    *,
    lookups: LookupClient,
    out: Proposals,
) -> None:
    """Add Common Chemistry CAS names as English alt labels when missing from labels.

    Builds on `out.pending_alt` where a rename has already proposed one, for the
    same reason it reads `out.pending_pref` rather than the record's own
    preferred label: this rule runs after the rename over the same member and
    replaces the whole field, so starting from the record would drop the name
    the rename had just retained.
    """
    commonchem_names = sorted(lookups.names_for_cas(cas))
    if not commonchem_names:
        return
    detail = lookups.commonchem_detail(cas)
    detail_url = detail.get("url") if isinstance(detail.get("url"), str) else ""
    for member in unit.members:
        member_uuid = str(member.uuid or "")
        if not member_uuid:
            continue
        old_alt = out.pending_alt.get(member_uuid) or coerce_alt_labels(member.altLabel)
        current_pref = out.pending_pref.get(
            member_uuid, coerce_pref_label(member.prefLabel)
        )
        existing_norms = set()
        if current_pref is not None and isinstance(current_pref.value, str):
            existing_norms.add(canonical_label_value(current_pref.value))
        for alt in old_alt:
            existing_norms.add(canonical_label_value(alt.value))

        to_add: list[Label] = []
        for candidate in commonchem_names:
            key = canonical_label_value(candidate)
            if not key or key in existing_norms:
                continue
            existing_norms.add(key)
            primary_sources = [f"CAS:{cas}"]
            if detail_url:
                primary_sources.append(detail_url)
            to_add.append(
                Label(
                    value=candidate,
                    language="en",
                    source=Provenance(
                        was_generated_by="consensus_match",
                        was_attributed_to="brightway-flows",
                        had_primary_source=primary_sources,
                        was_derived_from="common chemistry CAS lookup",
                    ).to_dict(),
                )
            )

        if not to_add:
            continue
        merged_alt = dedupe_alt_labels_against_pref(
            alt_labels=old_alt + to_add,
            pref_label=current_pref,
        )
        if [x.to_dict() for x in merged_alt] != [x.to_dict() for x in old_alt]:
            out.pending_alt[member_uuid] = merged_alt
            out.changes.append(
                Change(
                    member_uuid,
                    "altLabel",
                    [x.to_dict() for x in merged_alt],
                    comment=(
                        f"group_key={unit.group.group_key}; cas={cas}; "
                        f"added Common Chemistry CAS names as altLabel: "
                        f"{', '.join(sorted(x.value for x in to_add))}; "
                        f"object_uuid={unit.object_uuid}"
                    ),
                )
            )


def assign_cas_match_labels(unit: ObjectUnit, *, out: Proposals) -> None:
    """Record each member's CAS as an exact or a related match, as the group decided."""
    if not unit.cas_numbers:
        return
    for member in unit.members:
        member_uuid = str(member.uuid or "")
        if not member_uuid:
            continue
        member_cas = sorted_unique_strings(member.cas_numbers)
        new_labels = {
            cas: unit.group.cas_label_decisions[cas]
            for cas in member_cas
            if cas in unit.group.cas_label_decisions
        }
        if not new_labels:
            continue
        if member.cas_match_labels == new_labels:
            continue
        out.changes.append(Change(
            member_uuid,
            "cas_match_labels",
            new_labels,
            comment=(
                f"group_key={unit.group.group_key}; "
                f"group_sources={unit.group.group_sources}; "
                f"cas_sources={unit.group.group_cas_sources}; "
                f"assigned CAS labels from group consensus; "
                f"object_uuid={unit.object_uuid}: {new_labels}"
            ),
        ))


def _pref_label_differs(old_pref: Label | None, new_pref: Label) -> bool:
    return (
        old_pref is None
        or canonical_label_value(old_pref.value) != canonical_label_value(new_pref.value)
        or old_pref.language != new_pref.language
    )


def _retained_altlabel_change(
    member: Flow,
    *,
    old_name: str,
    new_pref: Label,
    derived_from: str,
    comment: str,
    out: Proposals,
) -> Change | None:
    """Keep the name a rename replaced, as an altLabel, unless it is already one.

    Records what it proposed in `out.pending_alt`, so that
    `add_commonchem_altlabels` -- which runs next over the same member and also
    rewrites the whole field -- adds to this list rather than to the one still
    on the record.  Without that the retention is proposed and then overwritten,
    which is how 5,188 flows lost the name their source list gave them.
    """
    member_uuid = str(member.uuid or "")
    old_alt = out.pending_alt.get(member_uuid) or coerce_alt_labels(member.altLabel)
    alt_with_current = dedupe_alt_labels_against_pref(
        alt_labels=old_alt + [Label(
            value=old_name,
            source=Provenance(
                was_generated_by="consensus_match",
                was_attributed_to="brightway-flows",
                had_primary_source=[str(member.source or base_source_label())],
                was_derived_from=derived_from,
            ).to_dict(),
        )],
        pref_label=new_pref,
    )
    if [x.to_dict() for x in alt_with_current] == [x.to_dict() for x in old_alt]:
        return None
    out.pending_alt[member_uuid] = alt_with_current
    return Change(
        member_uuid,
        "altLabel",
        [x.to_dict() for x in alt_with_current],
        comment=comment,
    )
