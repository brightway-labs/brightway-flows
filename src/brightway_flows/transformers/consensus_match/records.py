"""The rows consensus matching writes to the review queues.

Records only; no decision is taken here.  They are separate from the rules that
fill them in because `pipeline.review_tables` and the review application read
them back, and a record several packages depend on should not have to be
imported from the middle of a transformer.

The unruled-rename records are not here: a ruling is keyed on a pair of names
rather than on the stage that proposed it, so `UndecidedLabelReplacement` and
`UndecidedLabelPair` live with the rulings in
`domain.preferred_label_decisions`, where the element pass reaches them too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from brightway_flows.domain.records import SerialisableRecord


class ConsensusDecision(StrEnum):
    """Why a proposed consensus update did not happen."""

    #: A CAS number the sources agree on, not applied because the group holds
    #: several CAS whose relationship is not exact, or because the name is
    #: already an altLabel of a different CAS-bearing substance.
    BLOCKED_CAS_UPDATE = "blocked_cas_update"
    #: The sources proposed no CAS at all for this name.
    NO_CONSENSUS_CAS = "no_consensus_cas"
    #: A name the sources agree on, blocked for the same reasons.
    BLOCKED_NAME_UPDATE = "blocked_name_update"


@dataclass
class CasVoteConflict(SerialisableRecord):
    """A CAS candidate that lost the vote, and who voted for it.

    Kept per review row rather than summarised: "which sources disagreed, and
    about what" is the whole content of the decision a curator is being asked
    to make, and a count cannot carry it.
    """

    candidate: str
    sources: list[str] = field(default_factory=list)


@dataclass
class ConsensusMatchReviewItem(SerialisableRecord):
    """One consensus decision the transformer would not take on its own.

    All three decisions share this shape.  They used to be three dict literals
    with overlapping keys, so which fields a row had depended on its `decision`
    and a reader had to know the difference; the fields that do not apply are
    now explicitly empty.

    `uuid` is the flow *object's* uuid -- the substance -- because consensus
    matching groups by substance.  `member_uuids` are the elementary flows in
    that group, which is what makes the row reachable from a flow page.
    """

    uuid: str
    flow_name: str
    decision: ConsensusDecision
    relationship_class: str
    reason: str = ""
    member_uuids: list[str] = field(default_factory=list)

    #: What was proposed.  `candidate_cas` for a blocked CAS update,
    #: `candidate_name` plus the `cas` it was keyed on for a blocked rename.
    candidate_cas: str = ""
    candidate_name: str = ""
    cas: str = ""

    #: Who voted for what, and what the losing candidates were.
    source_votes: dict[str, list[str]] = field(default_factory=dict)
    conflicts: list[CasVoteConflict] = field(default_factory=list)
    supporting_refs: list[str] = field(default_factory=list)

    #: The name/context group the substance was matched in, and what the other
    #: members of it carry.  A block is usually a property of the group rather
    #: than of this substance, so the group is the evidence.
    group_key: str = ""
    group_member_count: int = 0
    group_cas_set: list[str] = field(default_factory=list)
    group_cas_label_decisions: dict[str, str] = field(default_factory=dict)
    group_sources: list[str] = field(default_factory=list)
    group_cas_sources: dict[str, list[str]] = field(default_factory=dict)
    intra_group_conflict_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialise with the votes and the losing candidates in a fixed order.

        The tallies are built by iterating sets, so their order varies between
        processes.  Two runs over identical inputs then produce payloads that
        are equal as data and different as text -- invisible while this only
        reached a review file written behind a flag, and reported by
        `tools/verify_run.py` on every run once it became a table.

        Ordered here rather than where each field is built, because this is the
        only place the ordering has to hold: it is a property of the stored
        form, not of any decision the transformer makes.
        """
        payload = super().to_dict()
        payload["conflicts"] = [
            conflict.to_dict()
            for conflict in sorted(self.conflicts, key=lambda c: c.candidate)
        ]
        for key in ("source_votes", "group_cas_label_decisions", "group_cas_sources"):
            payload[key] = dict(sorted(payload[key].items()))
        return payload

