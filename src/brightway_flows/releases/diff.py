"""What changed between two releases, as one record per thing that changed.

The alignment (`releases/alignment.py`) says which identifier became which;
this says what a consumer has to do about each substance, flow and factor:
create it, update some of its fields, replace one identifier with another,
delete it -- or, where the alignment could not answer, nothing yet.  The
randonneur files are written from these records (`releases/randonneur_files.py`),
and so is the unresolved report.

Two orderings matter.  **Factors follow flows**: the factor file is stated
against the *after* release's flow identifiers, on the assumption that the
consumer applies the flow migration first.  A before-side factor of a flow
that was replaced is translated to the survivor's key before the two sides
are compared, so a renamed flow's factors are updates rather than a deletion
and a creation; where the survivor already carried a factor in that category,
the translated one is redundant and dropped, because the survivor's own row
is the one the update speaks to.  A factor of an unresolved flow is
unresolved with it, and so is every factor of an impact category the after
release no longer publishes -- a category is a method as one implementer
rendered it, and its disappearance is a decision about the method, not a
row to delete.

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
    ReleaseSnapshot,
    ReleaseStamp,
    SnapshotFactor,
)


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
    factors: list[Delta] = field(default_factory=list)
    #: How many source-row answers the minted-identifier arithmetic checked.
    minted_identifiers_checked: int = 0

    @property
    def by_entity(self) -> dict[EntityKind, list[Delta]]:
        return {
            EntityKind.FLOW_OBJECT: self.flow_objects,
            EntityKind.ELEMENTARY_FLOW: self.elementary_flows,
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


def _diff_factors(
    before: ReleaseSnapshot,
    after: ReleaseSnapshot,
    flow_fates: dict[str, IdentifierFate],
    rulings: tuple[MigrationRuling, ...],
) -> list[Delta]:
    after_categories = {factor.impact_category_id for factor in after.characterization_factors}
    before_keys = set(before.factors_by_key)
    translated: dict[tuple[str, str, str], SnapshotFactor] = {}
    deltas: list[Delta] = []

    for key, factor in before.factors_by_key.items():
        fate = flow_fates.get(factor.elementary_flow_uuid)
        if fate is not None and fate.fate is Fate.UNRESOLVED:
            deltas.append(Delta(
                entity=EntityKind.FACTOR, kind=DeltaKind.UNRESOLVED,
                identifier=SnapshotFactor.key_text(key), reason="flow-unresolved",
                candidates=list(fate.candidates),
                comment=f"its flow {factor.elementary_flow_uuid} is unresolved: {fate.comment}",
                before=_factor_payload(factor),
            ))
            continue
        if fate is not None and fate.fate is Fate.DELETED:
            deltas.append(Delta(
                entity=EntityKind.FACTOR, kind=DeltaKind.DELETED,
                identifier=SnapshotFactor.key_text(key), reason="flow-deleted",
                comment=f"its flow {factor.elementary_flow_uuid} is deleted: {fate.comment}",
                before=_factor_payload(factor),
            ))
            continue
        if factor.impact_category_id not in after_categories:
            # Asked after the flow's fate: a deleted flow's factor is deleted
            # whatever became of the category.
            deltas.append(Delta(
                entity=EntityKind.FACTOR, kind=DeltaKind.UNRESOLVED,
                identifier=SnapshotFactor.key_text(key), reason="category-gone",
                comment=(
                    f"the after release publishes no factor under "
                    f"{factor.method} / {factor.category} ({factor.implemented_by})"
                ),
                before=_factor_payload(factor),
            ))
            continue
        if fate is None:
            translated[key] = factor
            continue
        new_key = (factor.impact_category_id, fate.replaced_by or "", factor.geography)
        if new_key in before_keys and fate.replaced_by in before.live_flows:
            # The survivor carried its own factor here; the update on that
            # row is what the consumer applies, and this one is redundant.
            continue
        if new_key in translated:
            continue  # two flows merged into one survivor: one factor suffices
        translated[new_key] = factor

    after_keys = after.factors_by_key
    for key in sorted(set(after_keys) - set(translated)):
        factor = after_keys[key]
        deltas.append(Delta(
            entity=EntityKind.FACTOR, kind=DeltaKind.CREATED,
            identifier=SnapshotFactor.key_text(key), reason="new-in-after",
            comment=f"{factor.method} / {factor.category} ({factor.implemented_by})",
            after=_factor_payload(factor),
        ))
    for key in sorted(set(translated) & set(after_keys)):
        old, new = translated[key], after_keys[key]
        if old.amount == new.amount:
            continue
        deltas.append(Delta(
            entity=EntityKind.FACTOR, kind=DeltaKind.UPDATED,
            identifier=SnapshotFactor.key_text(key), reason="fields-changed",
            changed_fields=["amount"],
            comment=f"{new.method} / {new.category} ({new.implemented_by}): amount {old.amount!r} -> {new.amount!r}",
            before={"amount": old.amount}, after={"amount": new.amount},
        ))
    for key in sorted(set(translated) - set(after_keys)):
        old = translated[key]
        deltas.append(Delta(
            entity=EntityKind.FACTOR, kind=DeltaKind.DELETED,
            identifier=SnapshotFactor.key_text(key), reason="gone-in-after",
            comment=f"{old.method} / {old.category} ({old.implemented_by}): no factor in the after release",
            before=_factor_payload(old),
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
) -> ReleaseDiff:
    """Every change between two releases.

    *rulings* is the whole rulings file; only those naming this pair apply.

    :raises AlignmentError: for two snapshots that cannot be compared, or an
        alignment that contradicts the minted-identifier arithmetic.
    :raises MigrationRulingError: for a ruling that answers no open question.
    """
    check_source_lists(before, after, allow_different_sources=allow_different_sources)
    pair = rulings_for(rulings, before.stamp.version, after.stamp.version)
    flow_fates = align_elementary_flows(before, after, rulings=pair)
    object_fates = align_flow_objects(before, after, flow_fates, rulings=pair)
    checked = check_minted_identifiers(before, after, flow_fates, object_fates)

    flows = _diff_records(
        EntityKind.ELEMENTARY_FLOW, before.live_flows, after.live_flows, flow_fates
    )
    objects = _diff_records(
        EntityKind.FLOW_OBJECT, before.objects_by_id, after.objects_by_id, object_fates
    )
    factors = _diff_factors(before, after, flow_fates, pair)
    return ReleaseDiff(
        before=before.stamp,
        after=after.stamp,
        flow_objects=objects,
        elementary_flows=flows,
        factors=factors,
        minted_identifiers_checked=checked,
    )
