"""Which identifier of the before release became which of the after release.

An identifier that is live on both sides is the same thing on both sides,
and the diff compares its fields.  This module is about the rest: a flow or a
substance a consumer holds that the after release does not publish under that
name.  Three questions are asked, in order, and the first one with an answer
wins.

**Does the after release say so itself?**  The export's ``redirects`` name a
survivor for every deprecated identifier, with a reason.  ``identity-merge``
and ``identifier-scheme-change`` are safe to follow; ``source-row-withdrawn``
says there is nothing to follow; ``context-collapse`` and ``unclassified`` are
the two the export tells a consumer to refuse, and this refuses them the same
way -- they are left unresolved with the survivor named as the candidate.

**Where did its source rows go?**  A vendor row is the one thing both builds
name the same way.  If every row the old flow carried now lands on one live
flow, that flow is what the old identifier became -- provided the unit is the
same, because a unit that moved needs a conversion this cannot guess.  Rows
that land on several live flows are a split, and a split is a decision about
the substance rather than an arithmetic: it is left unresolved.  Rows found
nowhere, on a list the after release still merged, mean the flow is gone.

**Does the arithmetic agree?**  A flow this list mints is named by its
substance and its compartment, so when a substance moved the new name is
predictable, and the source-row answer is checked against it.  A disagreement
is not something to publish; it raises.

A substance follows its flows: a vanished ``flow_object_id`` whose live flows
all resolved to flows of one surviving substance became that substance.

A ruling in ``release-migration-rulings.json`` answers an unresolved
identifier, and only one: a ruling that finds no open question is stale and
refused (see `releases/rulings.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from brightway_flows.domain.elementary_flow import minted_elementary_flow_id
from brightway_flows.pipeline.redirects import (
    CONTEXT_COLLAPSE,
    IDENTIFIER_SCHEME_CHANGE,
    IDENTITY_MERGE,
    SOURCE_ROW_WITHDRAWN,
    UNCLASSIFIED,
)
from brightway_flows.releases.rulings import (
    EntityKind,
    MigrationRuling,
    MigrationRulingError,
    RulingVerb,
)
from brightway_flows.releases.snapshot import ReleaseSnapshot, SnapshotElementaryFlow

#: The redirect reasons a consumer is told to follow, and this follows.
_SAFE_REDIRECTS = frozenset({IDENTITY_MERGE, IDENTIFIER_SCHEME_CHANGE})
_REFUSED_REDIRECTS = frozenset({CONTEXT_COLLAPSE, UNCLASSIFIED})


class AlignmentError(ValueError):
    """The two snapshots cannot be aligned, or the alignment contradicts itself."""


class Fate(StrEnum):
    """What became of an identifier the after release does not publish."""

    REPLACED = "replaced"
    DELETED = "deleted"
    UNRESOLVED = "unresolved"


class FateReason(StrEnum):
    """How the fate was decided, or why it could not be."""

    #: The after release's own redirect, with a reason a consumer may follow.
    REDIRECT = "redirect"
    #: The after release's own redirect says the source row was withdrawn.
    WITHDRAWN = "source-row-withdrawn"
    #: Every source row the flow carried now lands on one live flow.
    SOURCE_ROWS = "source-rows"
    #: Every source row is absent from the after release, on a list it merged.
    ROWS_GONE = "source-rows-gone"
    #: A curator ruled it, in `release-migration-rulings.json`.
    RULING = "ruling"
    # -- unresolved from here on --
    #: A redirect the export tells a consumer to refuse.
    REFUSED_REDIRECT = "refused-redirect"
    #: The source rows land on several live flows.
    SPLIT = "split"
    #: One live flow, in another unit.
    UNIT_CHANGE = "unit-change"
    #: The rows belong to a list the after release did not merge.
    LIST_NOT_MERGED = "list-not-merged"
    #: The flow carried no source row, so nothing can be followed.
    NO_SOURCE_ROWS = "no-source-rows"
    #: A substance whose flows resolved to several substances.
    OBJECT_SPLIT = "object-split"
    #: A substance one of whose flows is itself unresolved.
    FLOWS_UNRESOLVED = "flows-unresolved"


@dataclass(frozen=True)
class IdentifierFate:
    """What became of one identifier, and how that was decided."""

    identifier: str
    fate: Fate
    reason: FateReason
    replaced_by: str | None = None
    #: For a split or a refused redirect: the flows it might be.
    candidates: tuple[str, ...] = ()
    comment: str = ""
    conversion_factor: float | None = None


def check_source_lists(
    before: ReleaseSnapshot, after: ReleaseSnapshot, *, allow_different_sources: bool
) -> None:
    """Both sides must have merged the same lists, unless told otherwise.

    A list the after side did not merge takes every one of its rows with it,
    and a migration that read that as a thousand deletions would be wrong in
    a way nothing downstream could see.  The same rule `assessment/baseline`
    applies to a comparison.
    """
    if set(before.stamp.merged_lists) == set(after.stamp.merged_lists):
        return
    message = (
        f"the two releases merged different source lists: "
        f"{sorted(before.stamp.merged_lists)} against {sorted(after.stamp.merged_lists)}"
    )
    if not allow_different_sources:
        raise AlignmentError(message + "; pass --allow-different-sources to proceed")


def vanished_flows(before: ReleaseSnapshot, after: ReleaseSnapshot) -> list[SnapshotElementaryFlow]:
    """The flows a consumer of *before* holds that *after* does not publish."""
    live_after = after.live_flows
    return [flow for identifier, flow in before.live_flows.items() if identifier not in live_after]


def _fate_from_redirect(flow: SnapshotElementaryFlow, after: ReleaseSnapshot) -> IdentifierFate | None:
    redirect = after.redirects_by_identifier.get(flow.identifier)
    if redirect is None:
        return None
    target = redirect.replaced_by_identifier
    if redirect.reason == SOURCE_ROW_WITHDRAWN:
        return IdentifierFate(
            flow.identifier, Fate.DELETED, FateReason.WITHDRAWN,
            comment="the after release withdrew the source row this flow was minted from",
        )
    if target is None or target not in after.live_flows:
        # A redirect whose survivor is not published is the export's own
        # inconsistency, and not one to paper over here.
        raise AlignmentError(
            f"the after release redirects {flow.identifier} to "
            f"{target!r}, which it does not publish"
        )
    if redirect.reason in _SAFE_REDIRECTS:
        return IdentifierFate(
            flow.identifier, Fate.REPLACED, FateReason.REDIRECT, replaced_by=target,
            comment=f"the after release redirects it ({redirect.reason})",
            conversion_factor=1.0 if flow.unit == after.live_flows[target].unit else None,
        )
    if redirect.reason in _REFUSED_REDIRECTS:
        return IdentifierFate(
            flow.identifier, Fate.UNRESOLVED, FateReason.REFUSED_REDIRECT,
            candidates=(target,),
            comment=(
                f"the after release redirects it to {target} for reason "
                f"'{redirect.reason}', which the export tells a consumer to refuse"
            ),
        )
    raise AlignmentError(f"unknown redirect reason {redirect.reason!r} on {flow.identifier}")


def _fate_from_source_rows(
    flow: SnapshotElementaryFlow, before: ReleaseSnapshot, after: ReleaseSnapshot
) -> IdentifierFate:
    rows = sorted(before.rows_by_flow.get(flow.identifier, ()))
    if not rows:
        return IdentifierFate(
            flow.identifier, Fate.UNRESOLVED, FateReason.NO_SOURCE_ROWS,
            comment="the flow carried no source row, so nothing can be followed",
        )
    live_after = after.live_flows
    targets: set[str] = set()
    for key in rows:
        targets.update(t for t in after.rows_by_key.get(key, ()) if t in live_after)
    if not targets:
        unmerged = sorted({
            f"{name}-{version}" for name, version, _uuid in rows
            if (name, version) not in after.source_lists
        })
        if unmerged:
            return IdentifierFate(
                flow.identifier, Fate.UNRESOLVED, FateReason.LIST_NOT_MERGED,
                comment=f"its source rows belong to {', '.join(unmerged)}, which the after release did not merge",
            )
        return IdentifierFate(
            flow.identifier, Fate.DELETED, FateReason.ROWS_GONE,
            comment=f"none of its {len(rows)} source rows reaches a live flow in the after release",
        )
    if len(targets) > 1:
        return IdentifierFate(
            flow.identifier, Fate.UNRESOLVED, FateReason.SPLIT,
            candidates=tuple(sorted(targets)),
            comment=f"its {len(rows)} source rows now land on {len(targets)} flows",
        )
    (target,) = targets
    target_flow = live_after[target]
    if target_flow.unit != flow.unit:
        return IdentifierFate(
            flow.identifier, Fate.UNRESOLVED, FateReason.UNIT_CHANGE,
            candidates=(target,),
            comment=(
                f"its source rows land on {target}, published in "
                f"{target_flow.unit} where this flow was in {flow.unit}"
            ),
        )
    return IdentifierFate(
        flow.identifier, Fate.REPLACED, FateReason.SOURCE_ROWS, replaced_by=target,
        comment=f"its {len(rows)} source rows land on it in the after release",
        conversion_factor=1.0,
    )


def _apply_rulings(
    fates: dict[str, IdentifierFate],
    rulings: tuple[MigrationRuling, ...],
    *,
    entity: EntityKind,
    live_after: set[str],
) -> None:
    for ruling in rulings:
        if ruling.entity is not entity:
            continue
        current = fates.get(ruling.identifier)
        if current is None or current.fate is not Fate.UNRESOLVED:
            raise MigrationRulingError(
                f"the ruling on {entity.value} {ruling.identifier} between "
                f"{ruling.from_version} and {ruling.to_version} answers no open "
                "question: the identifier is not unresolved in this pair"
            )
        if ruling.verb is RulingVerb.REPLACE:
            if ruling.replaced_by not in live_after:
                raise MigrationRulingError(
                    f"the ruling on {ruling.identifier} names {ruling.replaced_by}, "
                    "which the after release does not publish"
                )
            fates[ruling.identifier] = IdentifierFate(
                ruling.identifier, Fate.REPLACED, FateReason.RULING,
                replaced_by=ruling.replaced_by, comment=ruling.comment,
                conversion_factor=(
                    1.0 if ruling.conversion_factor is None else ruling.conversion_factor
                ),
            )
        else:
            fates[ruling.identifier] = IdentifierFate(
                ruling.identifier, Fate.DELETED, FateReason.RULING, comment=ruling.comment,
            )


def align_elementary_flows(
    before: ReleaseSnapshot,
    after: ReleaseSnapshot,
    *,
    rulings: tuple[MigrationRuling, ...] = (),
) -> dict[str, IdentifierFate]:
    """The fate of every flow *before* publishes live and *after* does not."""
    fates: dict[str, IdentifierFate] = {}
    for flow in vanished_flows(before, after):
        fate = _fate_from_redirect(flow, after) or _fate_from_source_rows(flow, before, after)
        fates[flow.identifier] = fate
    _apply_rulings(
        fates, rulings, entity=EntityKind.ELEMENTARY_FLOW, live_after=set(after.live_flows)
    )
    return fates


def align_flow_objects(
    before: ReleaseSnapshot,
    after: ReleaseSnapshot,
    flow_fates: dict[str, IdentifierFate],
    *,
    rulings: tuple[MigrationRuling, ...] = (),
) -> dict[str, IdentifierFate]:
    """The fate of every substance *before* has and *after* has not.

    A substance follows its flows: it became the one substance its resolved
    flows now belong to, is gone if every flow is gone, and is unresolved if
    its flows are, or if they went to several substances.
    """
    fates: dict[str, IdentifierFate] = {}
    live_after = after.live_flows
    for object_id, obj in before.objects_by_id.items():
        if object_id in after.objects_by_id:
            continue
        flows = before.live_flows_by_object.get(object_id, [])
        targets: set[str] = set()
        unresolved: list[str] = []
        for flow in flows:
            fate = flow_fates.get(flow.identifier)
            if fate is None:
                # Live on both sides under the same identifier, but the object
                # is gone: the flow simply belongs to another object now.
                targets.add(live_after[flow.identifier].flow_object_id)
            elif fate.fate is Fate.REPLACED and fate.replaced_by:
                targets.add(live_after[fate.replaced_by].flow_object_id)
            elif fate.fate is Fate.UNRESOLVED:
                unresolved.append(flow.identifier)
        label = f"'{obj.prefLabel}'" if obj.prefLabel else object_id
        if unresolved:
            fates[object_id] = IdentifierFate(
                object_id, Fate.UNRESOLVED, FateReason.FLOWS_UNRESOLVED,
                candidates=tuple(sorted(targets)),
                comment=f"{label}: {len(unresolved)} of its flows are unresolved",
            )
        elif len(targets) > 1:
            fates[object_id] = IdentifierFate(
                object_id, Fate.UNRESOLVED, FateReason.OBJECT_SPLIT,
                candidates=tuple(sorted(targets)),
                comment=f"{label}: its flows now belong to {len(targets)} substances",
            )
        elif targets:
            (target,) = targets
            fates[object_id] = IdentifierFate(
                object_id, Fate.REPLACED, FateReason.SOURCE_ROWS, replaced_by=target,
                comment=f"{label}: every one of its {len(flows)} flows now belongs to it",
                conversion_factor=1.0,
            )
        else:
            fates[object_id] = IdentifierFate(
                object_id, Fate.DELETED, FateReason.ROWS_GONE,
                comment=f"{label}: none of its {len(flows)} flows survives",
            )
    _apply_rulings(
        fates, rulings, entity=EntityKind.FLOW_OBJECT, live_after=set(after.objects_by_id)
    )
    return fates


def check_minted_identifiers(
    before: ReleaseSnapshot,
    after: ReleaseSnapshot,
    flow_fates: dict[str, IdentifierFate],
    object_fates: dict[str, IdentifierFate],
) -> int:
    """Check every source-row answer the arithmetic can predict.

    A minted flow of a substance that moved, in a compartment that did not,
    must have become the flow minted for the new substance in that compartment.
    Returns how many were checked.

    :raises AlignmentError: where the two disagree.
    """
    checked = 0
    for fate in flow_fates.values():
        if fate.fate is not Fate.REPLACED or fate.reason is not FateReason.SOURCE_ROWS:
            continue
        old = before.live_flows[fate.identifier]
        new = after.live_flows[fate.replaced_by or ""]
        object_fate = object_fates.get(old.flow_object_id)
        if object_fate is None or object_fate.fate is not Fate.REPLACED:
            continue
        if old.context_iri != new.context_iri:
            continue
        if old.identifier != minted_elementary_flow_id(old.flow_object_id, old.context_iri):
            continue  # a vendor identifier, which no arithmetic names
        predicted = minted_elementary_flow_id(object_fate.replaced_by or "", old.context_iri)
        checked += 1
        if new.identifier != predicted and new.identifier == minted_elementary_flow_id(
            new.flow_object_id, new.context_iri
        ):
            raise AlignmentError(
                f"{old.identifier} resolves by its source rows to {new.identifier}, "
                f"but its substance became {object_fate.replaced_by}, which would "
                f"mint {predicted} in the same compartment"
            )
    return checked
