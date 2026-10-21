"""What changed between two releases, as one record per thing that changed.

The alignment (`releases/alignment.py`) says which identifier became which;
this says what a consumer has to do about each substance, flow and factor:
create it, update some of its fields, replace one identifier with another,
delete it -- or, where the alignment could not answer, nothing yet.  The
randonneur files are written from these records (`releases/randonneur_files.py`),
and so is the unresolved report.

**A factor follows its flow and its category.**  The factor file is stated
against the identifiers the *before* release published, because those are
what a consumer's method table holds.  A factor whose flow was replaced, or
whose category was renamed, is the same factor under a new key: it is
`replaced`, and the file writes it as an ``update`` that matches the old
triple and sets the new one (randonneur cannot apply ``replace`` to a node).
Where the consumer already holds a row under the new key -- two flows merged,
and the survivor carried its own factor -- the moved one is redundant and
deleted, so the table does not end with two rows for one triple.  A factor of
an unresolved flow or category is unresolved with it.  A category the after
release no longer publishes is a method as one implementer rendered it, and
its disappearance is a decision about the method, not a row to delete.

**Entries are sorted by identifier**, so two runs over the same pair write
the same bytes, and a snapshot diffed against itself writes nothing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from brightway_flows.domain.records import SerialisableRecord
from brightway_flows.releases.alignment import (
    Fate,
    FateReason,
    IdentifierFate,
    align_elementary_flows,
    align_flow_objects,
    align_impact_categories,
    check_minted_identifiers,
    check_source_lists,
)
from brightway_flows.releases.rulings import (
    EntityKind,
    MigrationRuling,
    MigrationRulingError,
    RulingVerb,
    rulings_for,
)
from brightway_flows.releases.snapshot import (
    FACTOR_KEYS,
    ReleaseSnapshot,
    ReleaseStamp,
    SnapshotFactor,
)

#: Why a factor or a category was deleted though the after release publishes
#: its successor: the consumer already holds a row under the successor's key.
MERGED_INTO_HELD = "merged-into-held-row"


class DeltaKind(StrEnum):
    """What the consumer does about it."""

    CREATED = "created"
    UPDATED = "updated"
    REPLACED = "replaced"
    DELETED = "deleted"
    UNRESOLVED = "unresolved"


@dataclass
class Delta(SerialisableRecord):
    """One change to one substance, flow or factor between two releases.

    ``identifier`` is the before-side identifier for everything but a
    creation, which has none; a factor's is its triple joined with ``|``.
    ``before`` and ``after`` carry the published fields on each side, so a
    reader of the unresolved report sees what the row was without opening
    either snapshot.
    """

    entity: EntityKind
    kind: DeltaKind
    identifier: str
    reason: str = ""
    replaced_by: str | None = None
    conversion_factor: float | None = None
    changed_fields: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    comment: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    _OMIT_IF_NONE: ClassVar[frozenset[str]] = frozenset({
        "replaced_by", "conversion_factor", "before", "after",
    })


@dataclass
class ReleaseDiff:
    """Every delta between two releases, by entity."""

    before: ReleaseStamp
    after: ReleaseStamp
    flow_objects: list[Delta] = field(default_factory=list)
    elementary_flows: list[Delta] = field(default_factory=list)
    impact_categories: list[Delta] = field(default_factory=list)
    factors: list[Delta] = field(default_factory=list)
    #: How many source-row answers the minted-identifier arithmetic checked.
    minted_identifiers_checked: int = 0

    @property
    def by_entity(self) -> dict[EntityKind, list[Delta]]:
        return {
            EntityKind.FLOW_OBJECT: self.flow_objects,
            EntityKind.ELEMENTARY_FLOW: self.elementary_flows,
            EntityKind.IMPACT_CATEGORY: self.impact_categories,
            EntityKind.FACTOR: self.factors,
        }

    @property
    def unresolved(self) -> list[Delta]:
        return [
            delta
            for deltas in self.by_entity.values()
            for delta in deltas
            if delta.kind is DeltaKind.UNRESOLVED
        ]

    def counts(self) -> Counter[tuple[str, str]]:
        """``(entity, kind) -> n``, every pair present so a zero is a zero."""
        counts: Counter[tuple[str, str]] = Counter()
        for entity, deltas in self.by_entity.items():
            for kind in DeltaKind:
                counts[(entity.value, kind.value)] = 0
            for delta in deltas:
                counts[(entity.value, delta.kind.value)] += 1
        return counts

    def is_empty(self) -> bool:
        return not any(self.by_entity.values())


def _delta_from_fate(
    entity: EntityKind, fate: IdentifierFate, before: dict[str, Any]
) -> Delta:
    kind = {
        Fate.REPLACED: DeltaKind.REPLACED,
        Fate.DELETED: DeltaKind.DELETED,
        Fate.UNRESOLVED: DeltaKind.UNRESOLVED,
    }[fate.fate]
    return Delta(
        entity=entity,
        kind=kind,
        identifier=fate.identifier,
        reason=fate.reason.value,
        replaced_by=fate.replaced_by,
        conversion_factor=fate.conversion_factor,
        candidates=list(fate.candidates),
        comment=fate.comment,
        before=before,
    )


def _changed_fields(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(
        key for key in set(before) | set(after) if before.get(key) != after.get(key)
    )


def _describe_change(field_name: str, before: Any, after: Any) -> str:
    def short(value: Any) -> str:
        text = repr(value)
        return text if len(text) <= 60 else text[:57] + "..."

    if field_name not in ("prefLabel", "unit", "context_iri", "amount"):
        return field_name
    return f"{field_name}: {short(before)} -> {short(after)}"


def _diff_records(
    entity: EntityKind,
    before_live: dict[str, Any],
    after_live: dict[str, Any],
    fates: dict[str, IdentifierFate],
) -> list[Delta]:
    """Created, updated, and the fates, for one entity's records.

    *before_live* and *after_live* map identifier to a record with a
    ``published_fields()``; a record present on both sides is compared.
    """
    deltas: list[Delta] = []
    for identifier in sorted(set(after_live) - set(before_live)):
        record = after_live[identifier]
        deltas.append(Delta(
            entity=entity, kind=DeltaKind.CREATED, identifier=identifier,
            reason="new-in-after", comment="published by the after release only",
            after=record.published_fields(),
        ))
    for identifier in sorted(set(before_live) & set(after_live)):
        old, new = before_live[identifier].published_fields(), after_live[identifier].published_fields()
        changed = _changed_fields(old, new)
        if not changed:
            continue
        deltas.append(Delta(
            entity=entity, kind=DeltaKind.UPDATED, identifier=identifier,
            reason="fields-changed", changed_fields=changed,
            comment="; ".join(_describe_change(key, old.get(key), new.get(key)) for key in changed),
            before={key: old.get(key) for key in changed},
            after={key: new.get(key) for key in changed},
        ))
    for identifier in sorted(fates):
        deltas.append(_delta_from_fate(
            entity, fates[identifier], before_live[identifier].published_fields()
        ))
    return deltas


def _factor_payload(factor: SnapshotFactor) -> dict[str, Any]:
    return factor.to_dict()


def _label(factor: SnapshotFactor) -> str:
    return f"{factor.method} / {factor.category} ({factor.implemented_by})"


def _diff_categories(
    before: ReleaseSnapshot, after: ReleaseSnapshot, fates: dict[str, IdentifierFate]
) -> list[Delta]:
    """Created, updated and the fates, for the impact categories.

    A renamed category is the same row under a new id, so its delta carries
    the new id and every published field that moved with it; the file writes
    it as an ``update`` that sets the id.  Where the consumer already holds the
    new id, the old row is a duplicate of it, and is deleted instead.
    """
    # A category only a factor names has no row for a consumer to change; its
    # fate still moves the factors.
    held = {key: fate for key, fate in fates.items() if key in before.categories_by_id}
    deltas = _diff_records(
        EntityKind.IMPACT_CATEGORY, before.categories_by_id, after.categories_by_id, held
    )
    # A category a renamed one becomes arrives by that update, not by a
    # create -- where there is a row to update.  A rename whose old id only
    # factors name writes no update, so its target is created like any other.
    moved_to = {
        fate.replaced_by
        for fate in held.values()
        if fate.fate is Fate.REPLACED and fate.replaced_by not in before.categories_by_id
    }
    deltas = [
        delta for delta in deltas
        if not (delta.kind is DeltaKind.CREATED and delta.identifier in moved_to)
    ]
    for delta in deltas:
        if delta.kind is not DeltaKind.REPLACED or delta.replaced_by is None:
            continue
        if delta.replaced_by in before.categories_by_id:
            delta.kind = DeltaKind.DELETED
            delta.reason = MERGED_INTO_HELD
            delta.comment = f"{delta.comment}; the before release already published {delta.replaced_by}"
            continue
        old = before.categories_by_id[delta.identifier].published_fields()
        new = after.categories_by_id[delta.replaced_by].published_fields()
        changed = _changed_fields(old, new)
        delta.changed_fields = ["id", *changed]
        delta.before = {"id": delta.identifier, **{key: old.get(key) for key in changed}}
        delta.after = {"id": delta.replaced_by, **{key: new.get(key) for key in changed}}
    return deltas


def _diff_factors(
    before: ReleaseSnapshot,
    after: ReleaseSnapshot,
    flow_fates: dict[str, IdentifierFate],
    category_fates: dict[str, IdentifierFate],
    rulings: tuple[MigrationRuling, ...],
) -> list[Delta]:
    before_keys = before.factors_by_key
    after_keys = after.factors_by_key
    #: Before-side factors whose key the after release still uses.
    kept: dict[tuple[str, str, str], SnapshotFactor] = {}
    #: New key -> the before-side key and factor that moved to it.
    moved: dict[tuple[str, str, str], tuple[tuple[str, str, str], SnapshotFactor]] = {}
    deltas: list[Delta] = []

    def closed(kind: DeltaKind, key: tuple[str, str, str], factor: SnapshotFactor, reason: str,
               comment: str, candidates: tuple[str, ...] = ()) -> None:
        deltas.append(Delta(
            entity=EntityKind.FACTOR, kind=kind, identifier=SnapshotFactor.key_text(key),
            reason=reason, candidates=list(candidates), comment=comment,
            before=_factor_payload(factor),
        ))

    # A factor whose flow did not move is visited first, so that where a
    # merged flow's factor lands on its survivor's key, the survivor's own
    # factor is the one kept.
    ordered = sorted(
        before_keys.items(),
        key=lambda item: (item[1].elementary_flow_uuid in flow_fates, item[0]),
    )
    for key, factor in ordered:
        flow_fate = flow_fates.get(factor.elementary_flow_uuid)
        category_fate = category_fates.get(factor.impact_category_id)
        if flow_fate is not None and flow_fate.fate is Fate.UNRESOLVED:
            closed(DeltaKind.UNRESOLVED, key, factor, "flow-unresolved",
                   f"its flow {factor.elementary_flow_uuid} is unresolved: {flow_fate.comment}",
                   flow_fate.candidates)
            continue
        if flow_fate is not None and flow_fate.fate is Fate.DELETED:
            closed(DeltaKind.DELETED, key, factor, "flow-deleted",
                   f"its flow {factor.elementary_flow_uuid} is deleted: {flow_fate.comment}")
            continue
        # Asked after the flow's fate: a deleted flow's factor is deleted
        # whatever became of the category.
        if category_fate is not None and category_fate.fate is Fate.UNRESOLVED:
            closed(DeltaKind.UNRESOLVED, key, factor, category_fate.reason.value,
                   category_fate.comment, category_fate.candidates)
            continue
        if category_fate is not None and category_fate.fate is Fate.DELETED:
            closed(DeltaKind.DELETED, key, factor, "category-deleted",
                   f"its category is deleted: {category_fate.comment}")
            continue
        new_key = (
            category_fate.replaced_by if category_fate else factor.impact_category_id,
            flow_fate.replaced_by if flow_fate else factor.elementary_flow_uuid,
            factor.geography,
        )
        if new_key == key:
            kept[key] = factor
            continue
        if new_key in before_keys or new_key in moved:
            closed(DeltaKind.DELETED, key, factor, MERGED_INTO_HELD,
                   f"{_label(factor)}: it moves to {SnapshotFactor.key_text(new_key)}, "
                   "where the consumer already holds a factor")
            continue
        moved[new_key] = (key, factor)

    for key in sorted(set(after_keys) - set(kept) - set(moved)):
        factor = after_keys[key]
        deltas.append(Delta(
            entity=EntityKind.FACTOR, kind=DeltaKind.CREATED,
            identifier=SnapshotFactor.key_text(key), reason="new-in-after",
            comment=_label(factor), after=_factor_payload(factor),
        ))
    for key in sorted(kept):
        old = kept[key]
        new = after_keys.get(key)
        if new is None:
            closed(DeltaKind.DELETED, key, old, "gone-in-after",
                   f"{_label(old)}: no factor in the after release")
        elif old.amount != new.amount:
            deltas.append(Delta(
                entity=EntityKind.FACTOR, kind=DeltaKind.UPDATED,
                identifier=SnapshotFactor.key_text(key), reason="fields-changed",
                changed_fields=["amount"],
                comment=f"{_label(new)}: amount {old.amount!r} -> {new.amount!r}",
                before={"amount": old.amount}, after={"amount": new.amount},
            ))
    for new_key in sorted(moved):
        old_key, old = moved[new_key]
        new = after_keys.get(new_key)
        if new is None:
            closed(DeltaKind.DELETED, old_key, old, "gone-in-after",
                   f"{_label(old)}: no factor under {SnapshotFactor.key_text(new_key)} in the after release")
            continue
        changed = [name for name, was, now in zip(FACTOR_KEYS, old_key, new_key) if was != now]
        before_fields = {name: was for name, was in zip(FACTOR_KEYS, old_key) if name in changed}
        after_fields = {name: now for name, now in zip(FACTOR_KEYS, new_key) if name in changed}
        if old.amount != new.amount:
            changed.append("amount")
            before_fields["amount"], after_fields["amount"] = old.amount, new.amount
        moves = " and ".join(
            {"impact_category_id": "its category was renamed",
             "elementary_flow_uuid": "its flow was replaced"}[name]
            for name in changed if name in ("impact_category_id", "elementary_flow_uuid")
        )
        deltas.append(Delta(
            entity=EntityKind.FACTOR, kind=DeltaKind.REPLACED,
            identifier=SnapshotFactor.key_text(old_key), reason="key-moved",
            replaced_by=SnapshotFactor.key_text(new_key), changed_fields=changed,
            comment=f"{_label(new)}: {moves}",
            before=before_fields, after=after_fields,
        ))

    for ruling in rulings:
        if ruling.entity is not EntityKind.FACTOR:
            continue
        matching = [
            d for d in deltas if d.identifier == ruling.identifier and d.kind is DeltaKind.UNRESOLVED
        ]
        if not matching:
            raise MigrationRulingError(
                f"the ruling on factor {ruling.identifier} between {ruling.from_version} "
                f"and {ruling.to_version} answers no open question"
            )
        if ruling.verb is not RulingVerb.DELETE:
            raise MigrationRulingError(
                f"the ruling on factor {ruling.identifier}: a factor can be ruled "
                "`delete` only; a value comes from a characterisation, not a ruling"
            )
        (delta,) = matching
        delta.kind = DeltaKind.DELETED
        delta.reason = FateReason.RULING.value
        delta.comment = ruling.comment
        delta.candidates = []

    deltas.sort(key=lambda delta: (delta.identifier, delta.kind.value))
    return deltas


def diff_releases(
    before: ReleaseSnapshot,
    after: ReleaseSnapshot,
    *,
    rulings: tuple[MigrationRuling, ...] = (),
    allow_different_sources: bool = False,
    retired_categories: dict[str, str] | None = None,
) -> ReleaseDiff:
    """Every change between two releases.

    *rulings* is the whole rulings file; only those naming this pair apply.
    *retired_categories* maps a category id an old implementation slug minted
    to the id it is now; by default every one the method files declare
    (`lcia.categories.retired_impact_category_ids`).

    :raises AlignmentError: for two snapshots that cannot be compared, or an
        alignment that contradicts the minted-identifier arithmetic.
    :raises MigrationRulingError: for a ruling that answers no open question.
    """
    if retired_categories is None:
        from brightway_flows.lcia.categories import retired_impact_category_ids

        retired_categories = retired_impact_category_ids()
    check_source_lists(before, after, allow_different_sources=allow_different_sources)
    pair = rulings_for(rulings, before.stamp.version, after.stamp.version)
    flow_fates = align_elementary_flows(before, after, rulings=pair)
    object_fates = align_flow_objects(before, after, flow_fates, rulings=pair)
    category_fates = align_impact_categories(
        before, after, retired=retired_categories, rulings=pair
    )
    checked = check_minted_identifiers(before, after, flow_fates, object_fates)

    flows = _diff_records(
        EntityKind.ELEMENTARY_FLOW, before.live_flows, after.live_flows, flow_fates
    )
    objects = _diff_records(
        EntityKind.FLOW_OBJECT, before.objects_by_id, after.objects_by_id, object_fates
    )
    categories = _diff_categories(before, after, category_fates)
    factors = _diff_factors(before, after, flow_fates, category_fates, pair)
    return ReleaseDiff(
        before=before.stamp,
        after=after.stamp,
        flow_objects=objects,
        elementary_flows=flows,
        impact_categories=categories,
        factors=factors,
        minted_identifiers_checked=checked,
    )
