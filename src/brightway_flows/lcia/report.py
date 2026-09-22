"""What `characterise` could not do, as rows rather than as a log line.

A factor that does not reach a flow, or two that reach one flow and disagree, is
evidence about the matching rather than a number to fix here.  #63 is the lesson
this is built on: a value a pass declined used to vanish, and the only way to see
that a choice had been made was to notice a number had moved between builds.

One record, one closed set of kinds, one row per thing that happened (rule 19).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FindingKind(StrEnum):
    """What kind of thing a finding is.  Closed, and each is a question for a
    different reader."""

    #: A source flow carries factors and reaches no consensus flow.  A question
    #: for the merge: the flow was matched or it was not, and a factor cannot
    #: reach further than the flow it is about.
    FLOW_NOT_REACHED = "flow-not-reached"
    #: Two source rows reach one consensus flow and state different numbers for
    #: one category and place.  The model holds one factor per (flow, geography,
    #: category), so there is no faithful answer -- and a gap this wide is evidence that the
    #: two rows are two substances, which is a claim about our matching rather
    #: than about the publisher's file.
    FACTOR_COLLISION = "factor-collision"
    #: A factor is stated per one unit and the flow it reaches is published per
    #: another, with no conversion recorded for the pair.  A question for the
    #: merge's correspondence tables: publishing the number anyway would state a
    #: mass where an energy was asked for.
    UNIT_CROSSING = "unit-crossing"
    #: A number this list declined when two rows turned out to be one flow.  Not
    #: this pass's doing -- `pipeline.deduplication` and the collision rulings
    #: settle it during the build and write the loser onto the factor that kept
    #: it (#63) -- and surfaced here because a reader comparing two
    #: implementations needs to know that the number they are comparing was
    #: chosen from two.  #64's kresoxim-methyl is this: 134.73 published, 53,540
    #: declined, 397x apart, and the number ecoinvent's team kept is the one ours
    #: discarded.
    SUPERSEDED_VALUE = "superseded-value"
    #: A retired identifier held a factor its survivor states nothing for, so the
    #: number was carried onto the survivor.  The one case where following a
    #: redirect adds a factor rather than restating one, which makes it the one a
    #: reader has to see: `deduplication.settle_factor_values` settles a number
    #: two rows both publish and unions nothing, so this is the question it
    #: leaves open, answered by the deprecation the build already made (#163).
    REDIRECT_FOLLOWED = "redirect-followed"
    #: A retired identifier carries factors and its redirect is one a consumer is
    #: told to refuse -- a `context-collapse`, or a chain ending on a flow this
    #: build does not publish.  The numbers are not republished on the survivor,
    #: because the two flows are two source contexts the consensus vocabulary
    #: cannot tell apart and their factors may legitimately differ (#1, #36).
    REDIRECT_REFUSED = "redirect-refused"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing that happened to a factor on its way to a flow."""

    kind: FindingKind
    #: Who stated the factors this is about.
    implemented_by: str
    #: The consensus flow, where there is one.
    elementary_flow_uuid: str | None
    #: The impact category, where the finding is about one.
    impact_category_id: str | None
    #: A sentence a reader can act on, naming the rows and the numbers.
    detail: str
    #: The source rows involved, and whatever else is worth keeping about them.
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "implemented_by": self.implemented_by,
            "elementary_flow_uuid": self.elementary_flow_uuid,
            "impact_category_id": self.impact_category_id,
            "detail": self.detail,
            "context": self.context,
        }
